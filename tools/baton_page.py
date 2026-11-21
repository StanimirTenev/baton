#!/usr/bin/env python3
"""Baton's page: this install's ID, what is new in this version, "Update Baton", and friends.

A small web server for the human, on this machine only. It listens on 127.0.0.1 and on a port
the system picks, and answers only a request that carries the random key in its link (the page)
or in its X-Baton-Ticket header (the page's own buttons), with a Host of 127.0.0.1:<port>. The
key keeps other web pages in the browser from pressing the buttons; it does not stop a program
running on this machine as you, which can read the state file. One server per install: its
port, pid and key are in `baton.page.json` beside the identity folder. It stops by itself after
30 minutes without a request (BATON_PAGE_IDLE seconds).

SessionStart starts it, detached, the first time a version runs, and opens the page once
(`--ensure --open`). By hand:

    python3 tools/baton_page.py --serve --no-open   run it here and print the link (a demo)
    python3 tools/baton_page.py --open              open the page; the link is not printed
    python3 tools/baton_page.py --invite "text"     print an invitation code
    python3 tools/baton_page.py --accept CODE       accept an invitation (prints the reply
                                                    code) or take in a reply ("-" reads stdin)

Friends: an invitation is a code. It carries the sender's ID, public key, a text of up to 140
characters, a time, a nonce and (since v3.44.0) the ID it is for, signed with this install's key
(`ssh-keygen -Y sign -n baton-invite`). The receiver checks the signature against the key inside
and that the key gives the ID claimed. Accepting makes a reply code, signed the same way, that
names the invitation. An addressed invitation waits in this install's box (below), which the
friend's page fetches from, and the reply is posted back to it; or the human copies the code and
sends it by any channel. Only the page server opens the box and talks to other boxes, never a
hook, never the command line. The text of an invitation is
for the human: nothing here prints it, and the hook counts them. A nickname is the human's own
name for a friend: kept in friends.json only, never sent, never given to the agent.
"""
from __future__ import annotations   # `str | None`: Python 3.8 and 3.9 too

import argparse
import base64
import hashlib
import hmac
import importlib.util
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
HEADER = "X-Baton-Ticket"
NAMESPACE = "baton-invite"
TEXT_MAX = 140
NICK_MAX = 40
BODY_MAX = 65536
ID_RE = re.compile(r"BTN-[A-Z2-7]{4}-[A-Z2-7]{4}-[A-Z2-7]{4}")
PUB_RE = re.compile(r"ssh-ed25519 [A-Za-z0-9+/]{68}")    # 51 bytes of key blob, one line
NONCE_RE = re.compile(r"[0-9a-f]{32}")
ARMOR = {"invite": "BATON INVITE", "accept": "BATON REPLY"}


class PageError(Exception):
    """Said to the human as it is."""


def _idle() -> float:
    try:
        return max(0.5, float(os.environ.get("BATON_PAGE_IDLE") or 1800))
    except ValueError:
        return 1800.0


_HOOK = None


def hook():
    """The session hook's own code: own_id() and release_leads() come from there, not a copy."""
    global _HOOK
    if _HOOK is None:
        spec = importlib.util.spec_from_file_location("baton_session_start_for_page",
                                                      HOOKS / "baton_session_start.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _HOOK = mod
    return _HOOK


def identity_dir() -> Path:
    raw = os.environ.get("BATON_IDENTITY")
    if raw:
        return Path(raw)
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "baton" / "identity"


def state_path() -> Path:
    """Beside the identity folder, so every way of starting the page finds the same server."""
    return identity_dir().parent / "baton.page.json"


def friends_path() -> Path:
    return identity_dir() / "friends.json"


# -- small file helpers -----------------------------------------------------------------------

def _write_json(path: Path, data: dict) -> None:
    """Whole or not at all: written aside, readable only by the owner, then moved in."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class FileLock:
    """O_EXCL lock file; one left behind by a killed process is taken over after `stale` s."""

    def __init__(self, path: Path, wait: float = 5.0, stale: float = 10.0) -> None:
        self.path, self.wait, self.stale = path, wait, stale

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        end = time.time() + self.wait
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale:
                        os.unlink(str(self.path))
                        continue
                except OSError:
                    continue
                if time.time() > end:
                    raise PageError("another Baton process holds " + self.path.name)
                time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            os.unlink(str(self.path))
        except OSError:
            pass


# -- text that came from someone else ------------------------------------------------------

_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)?|[@-Z\\-_])")


def clean(text: str) -> str:
    """Plain text of one line: escape sequences, control and format characters (bidi overrides,
    zero-width) gone, whitespace runs one space."""
    text = _ANSI.sub("", str(text))
    text = "".join(" " if ch in "\t\n\r\v\f" else ch for ch in text
                   if ch in "\t\n\r\v\f" or unicodedata.category(ch) not in ("Cc", "Cf", "Co", "Cs"))
    return re.sub(r"\s+", " ", text).strip()


# -- the install's key -----------------------------------------------------------------------

def id_of(pub: str) -> str:
    """The ID a public key gives: the same computation as own_id() in the session hook."""
    blob = base64.b64decode(pub.split()[1])
    code = base64.b32encode(hashlib.sha256(blob).digest()).decode()[:12]
    return "BTN-" + "-".join(code[i:i + 4] for i in range(0, 12, 4))


def my_key() -> tuple:
    """(ID, public key line, private key path), or PageError. The key is made by the session
    hook (own_id), with the identity folder this process was given."""
    try:
        ident = hook().own_id()
    except Exception:
        ident = None
    key = identity_dir() / "baton_ed25519"
    try:
        pub = " ".join(key.with_name(key.name + ".pub").read_text("utf-8").split()[:2])
    except OSError:
        pub = ""
    if not ident or not PUB_RE.fullmatch(pub) or id_of(pub) != ident:
        raise PageError("this install has no ID yet: it is made at a session start, by ssh-keygen")
    return ident, pub, key


def _keygen() -> str:
    exe = shutil.which("ssh-keygen")
    if not exe:
        raise PageError("ssh-keygen is not on this machine")
    return exe


def sign(message: bytes, namespace: str = NAMESPACE) -> str:
    """An SSH signature of `message` in the baton-invite namespace (or `namespace`). The old .sig is removed
    first (ssh-keygen asks before overwriting one and, with no input, keeps the old one and
    exits 0); its input is closed; its output goes to a file, never a pipe (Windows)."""
    _, _, key = my_key()
    exe = _keygen()
    with tempfile.TemporaryDirectory(prefix="baton-sign-") as work:
        msg, sig, out = Path(work) / "msg", Path(work) / "msg.sig", Path(work) / "out"
        msg.write_bytes(message)
        if sig.exists():
            sig.unlink()
        with open(out, "wb") as fo:
            try:
                subprocess.run([exe, "-Y", "sign", "-f", str(key), "-n", namespace, str(msg)],
                               stdin=subprocess.DEVNULL, stdout=fo, stderr=fo, timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                raise PageError("ssh-keygen did not sign")
        if not sig.is_file():
            raise PageError("ssh-keygen did not sign")
        return sig.read_text("ascii").replace("\r\n", "\n")


def verify(message: bytes, signature: str, pub: str, namespace: str = NAMESPACE) -> bool:
    """Whether `signature` is `pub`'s over `message` in the baton-invite namespace (or `namespace`). The message
    goes in from a file and the output to a file, with a time limit: on Windows a wrong
    signature checked through a pipe hung (2 of 2, 21.11.2026)."""
    if not PUB_RE.fullmatch(pub):
        return False
    exe = _keygen()
    with tempfile.TemporaryDirectory(prefix="baton-verify-") as work:
        msg, sig = Path(work) / "msg", Path(work) / "msg.sig"
        allowed, out = Path(work) / "allowed", Path(work) / "out"
        msg.write_bytes(message)
        sig.write_bytes(signature.replace("\r\n", "\n").encode("ascii", "replace"))
        allowed.write_text(f'peer namespaces="{namespace}" {pub}\n', "ascii")
        with open(msg, "rb") as fi, open(out, "wb") as fo:
            try:
                done = subprocess.run([exe, "-Y", "verify", "-f", str(allowed), "-I", "peer",
                                       "-n", namespace, "-s", str(sig)],
                                      stdin=fi, stdout=fo, stderr=fo, timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                return False
        return done.returncode == 0


# -- codes -----------------------------------------------------------------------------------

def encode(kind: str, message: bytes, signature: str) -> str:
    blob = json.dumps({"m": message.decode("ascii"), "s": signature}, separators=(",", ":"))
    b64 = base64.b64encode(blob.encode("ascii")).decode()
    lines = "\n".join(b64[i:i + 64] for i in range(0, len(b64), 64))
    return f"-----BEGIN {ARMOR[kind]}-----\n{lines}\n-----END {ARMOR[kind]}-----\n"


def decode(code: str) -> tuple:
    """(payload dict, the exact signed bytes, signature) of a pasted code, checked for shape
    only. The signature is checked over the bytes carried, never over JSON written again."""
    text = str(code or "").replace("\r", "")
    if len(text) > 20000:
        raise PageError("that is too long to be a Baton code")
    armored = re.search(r"-----BEGIN BATON (INVITE|REPLY)-----(.*?)-----END BATON \1-----", text, re.S)
    # Inside the armour only base64 counts: a mail's "> ", a messenger's spaces and line breaks go.
    body = re.sub(r"[^A-Za-z0-9+/=]" if armored else r"\s+", "", armored.group(2) if armored else text)
    try:
        outer = json.loads(base64.b64decode(body, validate=True).decode("ascii"))
        message, signature = outer["m"].encode("ascii"), outer["s"]
        payload = json.loads(message)
    except Exception:
        raise PageError("that is not a Baton code")
    if not isinstance(payload, dict) or not isinstance(signature, str):
        raise PageError("that is not a Baton code")
    kind = payload.get("kind")
    if kind not in ARMOR or (armored and ARMOR[kind] != f"BATON {armored.group(1)}"):
        raise PageError("that is not a Baton code")
    # v1: an invitation for anyone (v3.43); v2 (v3.44.0): addressed, `to` the ID it is for.
    # A reply always names its `to`, and stays v1.
    want = {"v": int, "kind": str, "id": str, "pub": str, "created": str, "nonce": str}
    want.update({"text": str} if kind == "invite" else {"to": str, "invite": str})
    if kind == "invite" and payload.get("v") == 2:
        want["to"] = str
    if set(payload) != set(want) or any(not isinstance(payload[k], t) for k, t in want.items()):
        raise PageError("that code is not in a form this Baton reads")
    if (payload["v"] != (2 if "to" in want and kind == "invite" else 1)
            or not ID_RE.fullmatch(payload["id"]) or not PUB_RE.fullmatch(payload["pub"])
            or not NONCE_RE.fullmatch(payload["nonce"])
            or ("to" in want and not ID_RE.fullmatch(payload["to"]))
            or (kind == "invite" and len(payload["text"]) > TEXT_MAX)
            or (kind == "accept" and not NONCE_RE.fullmatch(payload["invite"]))):
        raise PageError("that code is not in a form this Baton reads")
    return payload, message, signature


def _signed(payload: dict) -> str:
    message = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return encode(payload["kind"], message, sign(message))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# -- the trust list --------------------------------------------------------------------------

_LOCK = threading.Lock()


class Store:
    """friends.json in the identity folder: invitations made here and waiting for a reply,
    invitations pasted here and not yet decided, and the peers. Read and written under a lock."""

    def __enter__(self):
        _LOCK.acquire()
        try:
            self._file = FileLock(friends_path().with_name("friends.lock"))
            self._file.__enter__()
        except BaseException:
            _LOCK.release()
            raise
        data = _read_json(friends_path()) or {}
        self.data = {k: data.get(k) if isinstance(data.get(k), dict) else {}
                     for k in ("invites", "incoming", "friends")}
        return self.data

    def __exit__(self, kind, *rest):
        try:
            if kind is None:
                _write_json(friends_path(), self.data)
        finally:
            self._file.__exit__()
            _LOCK.release()


def check_nick(nick) -> str:
    """The human's own name for a friend: plain text of one line, at most NICK_MAX characters."""
    nick = clean(nick or "")
    if len(nick) > NICK_MAX:
        raise PageError(f"a nickname is at most {NICK_MAX} characters")
    return nick


def _their_id(to) -> str:
    to = clean(to or "").upper()
    if to and not ID_RE.fullmatch(to):
        raise PageError("a Baton ID looks like BTN-XXXX-XXXX-XXXX")
    return to


def make_invite(text: str = "", to: str = "", nick: str = "") -> str:
    """An invitation code, kept here as waiting. With `to` (their Baton ID) it is addressed: only
    that install takes it, and it waits in this install's box for them to fetch. Without, the v1
    code of v3.43, which any Baton reads, to copy and send."""
    text, to, nick = clean(text), _their_id(to), check_nick(nick)
    if len(text) > TEXT_MAX:
        raise PageError(f"the text is longer than {TEXT_MAX} characters")
    ident, pub, _ = my_key()
    if to == ident:
        raise PageError("that is this install's own ID")
    payload = {"v": 2 if to else 1, "kind": "invite", "id": ident, "pub": pub, "text": text,
               "created": _now(), "nonce": os.urandom(16).hex()}
    if to:
        payload["to"] = to
    code = _signed(payload)
    with Store() as s:
        s["invites"][payload["nonce"]] = {"text": text, "created": payload["created"], "code": code,
                                          "to": to, "nick": nick}
    return code


def read_code(code: str, via: str = "paste", box: str = "") -> dict:
    """Check a code (pasted, or from a box) and keep what it says. An invitation waits for
    the human's decision; a reply to an invitation made here makes the friendship mutual."""
    payload, message, signature = decode(code)
    if id_of(payload["pub"]) != payload["id"]:
        raise PageError("the ID in that code is not the ID of the key in it")
    if not verify(message, signature, payload["pub"]):
        raise PageError("the signature on that code does not verify: it was changed, or not made by Baton")
    ident, _, _ = my_key()
    if payload["id"] == ident:
        raise PageError("that code was made by this install")
    if payload["kind"] == "invite" and payload.get("to", ident) != ident:
        raise PageError(f"that invitation is for another Baton ({payload['to']}), not this one")
    with Store() as s:
        if payload["kind"] == "invite":
            s["incoming"][payload["nonce"]] = {"id": payload["id"], "pub": payload["pub"],
                                               "text": payload["text"], "created": payload["created"],
                                               "to": payload.get("to", ""), "via": via, "box": box}
            return {"kind": "invite", "id": payload["id"], "nonce": payload["nonce"],
                    "text": clean(payload["text"])}
        inv = s["invites"].get(payload["invite"])
        if payload["to"] != ident or not inv or (inv.get("to") or payload["id"]) != payload["id"]:
            raise PageError("that reply does not answer an invitation waiting on this install "
                            "(made elsewhere, for someone else, cancelled, or already used)")
        s["invites"].pop(payload["invite"])
        s["friends"][payload["id"]] = {"pub": payload["pub"], "status": "mutual", "since": _now(),
                                       "note": inv.get("text", ""), "nick": inv.get("nick", "")}
        return {"kind": "accept", "id": payload["id"], "status": "mutual"}


def accept(nonce: str, nick: str = "") -> str:
    """Accept an invitation: the peer is trusted from this side, and the reply code to send back
    is returned. Mutual only once the inviter has it (accept_to_box() posts it to their box)."""
    nick = check_nick(nick)
    ident, pub, _ = my_key()
    with Store() as s:
        got = s["incoming"].get(nonce)
    if not got:
        raise PageError("no such invitation waiting")
    payload = {"v": 1, "kind": "accept", "id": ident, "pub": pub, "to": got["id"],
               "invite": nonce, "created": _now(), "nonce": os.urandom(16).hex()}
    code = _signed(payload)
    with Store() as s:
        s["incoming"].pop(nonce, None)
        old = s["friends"].get(got["id"]) or {}
        s["friends"][got["id"]] = {"pub": got["pub"], "since": _now(), "note": got.get("text", ""),
                                   "status": "mutual" if old.get("status") == "mutual" else "accepted-by-me",
                                   "reply": code, "nick": nick or old.get("nick", ""),
                                   "box": got.get("box", "") if got.get("to") == ident else ""}
    return code


def accept_to_box(nonce: str, nick: str = "") -> dict:
    """The page's Accept: the reply goes back the way the invitation came. One fetched from the
    inviter's box is posted to that box, and once the box took it both sides have accepted; a
    pasted one is answered by the human, with the code."""
    with Store() as s:
        got = dict(s["incoming"].get(nonce) or {})
    code = accept(nonce, nick)
    if not got.get("box") or got.get("to") != my_key()[0]:
        return {"code": code, "sent": False, "error": ""}
    try:
        send_reply(got["id"])
        return {"code": code, "sent": True, "error": ""}
    except PageError as err:
        return {"code": code, "sent": False, "error": str(err)}


def ignore(nonce: str) -> None:
    with Store() as s:
        s["incoming"].pop(nonce, None)


def cancel(nonce: str) -> None:
    with Store() as s:
        s["invites"].pop(nonce, None)


def remove(ident: str) -> None:
    with Store() as s:
        s["friends"].pop(ident, None)


def set_nick(nick: str, ident: str = "", nonce: str = "") -> None:
    """The human's name for a friend (`ident`) or for an invitation still waiting (`nonce`)."""
    nick = check_nick(nick)
    with Store() as s:
        row = s["friends"].get(ident) if ident else s["invites"].get(nonce)
        if not isinstance(row, dict):
            raise PageError("no such friend or invitation")
        row["nick"] = nick


# -- the box: invitations fetched from the inviter's own machine ------------------------------
#
# While an addressed invitation waits here, the page server opens a second listener, the box,
# on BATON_BOX (default 0.0.0.0:47800; BATON_BOX=off: never). It answers two calls and nothing
# else -- never the page or its buttons:
#   POST /box/v1/fetch {id, pub, time, sig}: the invitations addressed to `id`, for the holder of
#     its key (`ssh-keygen -Y sign -n baton-box` over "baton-box\n<id>\n<time>\n", within 5
#     minutes, later than the last time used, and the key gives the ID);
#   POST /box/v1/reply {code}: a signed reply, kept only if it answers an invitation waiting here.
# Every 5 s it says on the local network "a Baton box, this ID, this port" (UDP broadcast on
# BATON_BOX_UDP, default 47800); an open page hears that and fetches by itself, so on one network
# nothing is typed. Across networks the code goes by a messenger (share_links()). The page
# trusts no box: every code from one gets read_code()'s checks, as a pasted one does.

BOX_NS = "baton-box"
BOX_PORT = 47800
CODE_MAX = 8192
ANSWER_MAX = 1 << 20
SKEW = 300
BOX_DAYS = 7             # an addressed invitation waits this long, then it is dropped


def box_bind() -> tuple | None:
    """(host, port) the box listens on, or None when BATON_BOX=off or not an IP:port."""
    raw = (os.environ.get("BATON_BOX") or f"0.0.0.0:{BOX_PORT}").strip()
    host, _, port = raw.rpartition(":")
    try:
        ipaddress.ip_address(host.strip("[]"))
        return host.strip("[]"), int(port)
    except ValueError:
        return None


def udp_port() -> int:
    try:
        return int(os.environ.get("BATON_BOX_UDP") or BOX_PORT)
    except ValueError:
        return BOX_PORT


def parse_announce(data: bytes, ip: str) -> tuple | None:
    """(ID, ip, port) from a box's broadcast, or None for anything else."""
    try:
        got = json.loads(data[:512].decode("ascii")) if len(data) <= 512 else None
    except (UnicodeDecodeError, ValueError):
        return None
    if (not isinstance(got, dict) or got.get("baton") != "box" or not isinstance(got.get("id"), str)
            or not ID_RE.fullmatch(got["id"]) or not isinstance(got.get("port"), int)
            or not 0 < got["port"] < 65536):
        return None
    return got["id"], ip, got["port"]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _call(host: str, port: int, name: str, body: dict) -> dict:
    """One POST to a friend's box: no proxy (a box is on this network or the VPN), no redirect."""
    h = f"[{host}]" if ":" in host else host
    req = urllib.request.Request(f"http://{h}:{port}/box/v1/{name}", method="POST",
                                 data=json.dumps(body).encode("ascii"),
                                 headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    try:
        with opener.open(req, timeout=10) as resp:
            raw = resp.read(ANSWER_MAX + 1)
    except urllib.error.HTTPError as err:
        try:
            said = clean(json.loads(err.read(4096)).get("error"))[:200]
        except Exception:
            said = ""
        raise PageError(f"their box refused it ({err.code}{': ' + said if said else ''})")
    except (urllib.error.URLError, OSError, ValueError) as err:
        raise PageError(f"their box at {h}:{port} could not be reached "
                        f"({clean(getattr(err, 'reason', err))[:200]})")
    try:
        got = json.loads(raw) if len(raw) <= ANSWER_MAX else None
    except ValueError:
        got = None
    if not isinstance(got, dict) or not got.get("ok"):
        raise PageError("their box's answer is not one this Baton reads")
    return got


_PROOF = {"last": 0}
_PROOF_LOCK = threading.Lock()


def proof_text(ident: str, box_id: str, t: int) -> bytes:
    """What a fetch proof signs: who asks, whose box it is for, and when. A box takes only proofs
    for itself, so one box cannot reuse a proof at another."""
    return f"{BOX_NS}\n{ident}\n{box_id}\n{t}\n".encode("ascii")


def _proof(box_id: str) -> dict:
    ident, pub, _ = my_key()
    with _PROOF_LOCK:
        t = max(int(time.time()), _PROOF["last"] + 1)
        _PROOF["last"] = t
    return {"id": ident, "pub": pub, "time": str(t), "sig": sign(proof_text(ident, box_id, t), BOX_NS)}


def share_links(kind: str, code: str) -> dict:
    """The message that carries a code by a messenger the human already uses: its text, a
    WhatsApp link (wa.me opens WhatsApp with the text ready; the human picks the contact) and a
    mail link. Only the ID goes in the line: a nickname is never sent."""
    ident = my_key()[0]
    line = (f"{ident} invites you to be friends on Baton \u2014 paste this into your Baton page:"
            if kind == "invite" else
            f"{ident} accepted your Baton invitation \u2014 paste this into your Baton page:")
    text = line + "\n\n" + code

    def q(x):
        return urllib.parse.quote(x, safe="")
    subject = "Baton: an invitation" if kind == "invite" else "Baton: my reply"
    return {"text": text, "whatsapp": "https://wa.me/?text=" + q(text),
            "email": "mailto:?subject=" + q(subject) + "&body=" + q(text)}


def fetch_from(their_id: str, host: str, port: int) -> dict:
    """Take the invitations `their_id`'s box holds for this install. Only invitations made by
    `their_id` are kept, each after read_code()'s checks."""
    their_id = _their_id(their_id)
    got = _call(host, port, "fetch", _proof(their_id))
    codes = got.get("codes") if isinstance(got.get("codes"), list) else []
    kept = refused = 0
    for code in codes[:20]:
        try:
            if decode(str(code))[0]["id"] != their_id or decode(str(code))[0]["kind"] != "invite":
                raise PageError("not an invitation from that ID")
            read_code(str(code), via="box", box=f"{host}:{port}")
            kept += 1
        except PageError:
            refused += 1
    return {"invites": kept, "refused": refused}


def send_reply(ident: str) -> None:
    """The reply to an invitation fetched from a box, posted to that box (again)."""
    with Store() as s:
        f = dict(s["friends"].get(ident) or {})
    if not f.get("reply") or not f.get("box"):
        raise PageError("no box to send that reply to: copy it and send it yourself")
    host, _, port = f["box"].rpartition(":")
    _call(host, int(port), "reply", {"code": f["reply"]})
    with Store() as s:
        if ident in s["friends"]:
            s["friends"][ident]["status"] = "mutual"


def expires(created) -> str:
    """When an addressed invitation made at `created` stops waiting ("" if unreadable)."""
    try:
        made = datetime.fromisoformat(str(created))
    except ValueError:
        return ""
    return (made + timedelta(days=BOX_DAYS)).isoformat()


def _expired(v: dict) -> bool:
    end = expires(v.get("created"))
    return bool(v.get("to")) and (not end or end <= _now())


def waiting_for_box() -> int:
    """Addressed invitations waiting here: the box is open while there is one. Those older than
    BOX_DAYS are dropped first."""
    data = _read_json(friends_path()) or {}
    inv = data.get("invites") if isinstance(data.get("invites"), dict) else {}
    if any(isinstance(v, dict) and _expired(v) for v in inv.values()):
        with Store() as s:
            for k in [k for k, v in s["invites"].items() if isinstance(v, dict) and _expired(v)]:
                del s["invites"][k]
            inv = dict(s["invites"])
    return sum(1 for v in inv.values() if isinstance(v, dict) and v.get("to"))


class BoxRefused(Exception):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status, self.reason = status, reason


class BoxHandler(BaseHTTPRequestHandler):
    server_version = "Baton"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:
        pass

    def _say(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self.close_connection = True
        self._say(404, {"ok": False, "error": "not here"})

    do_PUT = do_DELETE = do_OPTIONS = do_HEAD = do_GET

    def do_POST(self) -> None:
        self.close_connection = True
        name = {"/box/v1/fetch": "fetch", "/box/v1/reply": "reply"}.get(self.path)
        try:
            if not self.server.allow(("ip", self.client_address[0]), 30):
                raise BoxRefused(429, "too many requests")
            size = int(self.headers.get("Content-Length") or 0)
            if size < 0 or size > 2 * CODE_MAX:
                raise BoxRefused(413, "too large")
            data = json.loads(self.rfile.read(size) or b"{}")
            if name is None:
                raise BoxRefused(404, "not here")
            if not isinstance(data, dict):
                raise BoxRefused(400, "not JSON")
            self._say(200, getattr(self.server, name)(data))
        except BoxRefused as err:
            self._say(err.status, {"ok": False, "error": err.reason})
        except PageError as err:
            self._say(403, {"ok": False, "error": str(err)})
        except ValueError:
            self._say(400, {"ok": False, "error": "not JSON"})
        except Exception:
            self._say(500, {"ok": False, "error": "error"})


class Box(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, host: str, port: int) -> None:
        if ":" in host:
            self.address_family = socket.AF_INET6
        super().__init__((host, port), BoxHandler)
        self._mx, self._hits, self._seen = threading.Lock(), {}, {}

    def allow(self, key, limit: int) -> bool:
        now = time.time()
        with self._mx:
            hits = [t for t in self._hits.get(key, []) if now - t < 60]
            ok = len(hits) < limit
            self._hits[key] = hits + [now] if ok else hits
            if len(self._hits) > 10000:
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < 60}
            return ok

    def fetch(self, data: dict) -> dict:
        ident, pub, when, sig = (data.get(k) for k in ("id", "pub", "time", "sig"))
        if not (all(isinstance(x, str) for x in (ident, pub, when, sig)) and ID_RE.fullmatch(ident)
                and PUB_RE.fullmatch(pub) and re.fullmatch(r"[0-9]{1,12}", when)):
            raise BoxRefused(400, "fetch wants id, pub, time and sig")
        t = int(when)
        if abs(time.time() - t) > SKEW:
            raise BoxRefused(403, "the proof's time is too far from now")
        if id_of(pub) != ident:
            raise BoxRefused(403, "the ID is not the ID of the key")
        if not self.allow(("id", ident), 10):
            raise BoxRefused(429, "too many requests")
        if not verify(proof_text(ident, my_key()[0], t), sig, pub, BOX_NS):
            raise BoxRefused(403, "the proof does not verify")
        with self._mx:
            if t <= self._seen.get(ident, 0):
                raise BoxRefused(403, "that proof was used already")
            self._seen[ident] = t
        with Store() as s:
            codes = [v["code"] for v in s["invites"].values() if v.get("to") == ident and not _expired(v)]
            for v in s["invites"].values():
                if v.get("to") == ident:
                    v["fetched"] = _now()
        return {"ok": True, "codes": codes}

    def reply(self, data: dict) -> dict:
        code = data.get("code")
        if not isinstance(code, str) or len(code.encode("utf-8")) > CODE_MAX:
            raise BoxRefused(400, "reply wants a code of at most 8 KiB")
        payload = decode(code)[0]
        if payload["kind"] != "accept":
            raise BoxRefused(400, "only a reply goes here")
        if not self.allow(("id", payload["id"]), 10):
            raise BoxRefused(429, "too many requests")
        read_code(code, via="box")
        return {"ok": True}


class Nearby:
    """The boxes this page heard on the local network in the last 30 s: {ID: (ip, port)}."""

    def __init__(self) -> None:
        self.seen, self.sock = {}, None

    def start(self) -> None:
        if self.sock is not None:
            return
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            s.bind(("", udp_port()))
        except OSError:
            return
        self.sock = s
        threading.Thread(target=self._listen, daemon=True).start()

    def _listen(self) -> None:
        while self.sock is not None:
            try:
                data, addr = self.sock.recvfrom(1024)
            except OSError:
                return
            got = parse_announce(data, addr[0])
            if got:
                self.seen[got[0]] = (got[1], got[2], time.time())

    def boxes(self) -> dict:
        now = time.time()
        return {k: v[:2] for k, v in list(self.seen.items()) if now - v[2] < 30}

    def stop(self) -> None:
        s, self.sock = self.sock, None
        if s is not None:
            s.close()


def announce(box: Box, port: int, stop: threading.Event) -> None:
    """Every 5 s while the box is open: "a Baton box, this ID, this port", by UDP broadcast."""
    host = box.server_address[0]
    target = "127.255.255.255" if host.startswith("127.") else "255.255.255.255"
    try:
        ident = my_key()[0]
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if host not in ("0.0.0.0", "::"):
            s.bind((host, 0))                    # the hearer fetches from where it came from
    except (PageError, OSError):
        return
    msg = json.dumps({"baton": "box", "v": 1, "id": ident, "port": port}).encode("ascii")
    with s:
        while not stop.is_set():
            try:
                s.sendto(msg, (target, udp_port()))
            except OSError:
                pass
            stop.wait(5)


def friends_view() -> dict:
    data = _read_json(friends_path()) or {}

    def part(name):
        return data.get(name) if isinstance(data.get(name), dict) else {}
    return {
        "friends": [{"id": k, "status": v.get("status"), "since": v.get("since"),
                     "note": clean(v.get("note", "")), "reply": v.get("reply", ""),
                     "nick": clean(v.get("nick", "")), "box": v.get("box", "")}
                    for k, v in sorted(part("friends").items())],
        "invites": [{"nonce": k, "text": clean(v.get("text", "")), "created": v.get("created"),
                     "code": v.get("code", ""), "to": v.get("to", ""),
                     "nick": clean(v.get("nick", "")), "fetched": v.get("fetched", ""),
                     "expires": expires(v.get("created")) if v.get("to") else ""}
                    for k, v in part("invites").items()],
        "incoming": [{"nonce": k, "id": v.get("id"), "text": clean(v.get("text", "")),
                      "created": v.get("created"), "via": v.get("via", "paste")}
                     for k, v in part("incoming").items()],
    }


# -- update ----------------------------------------------------------------------------------

def run_update(kind: str, catalog: str, how: str) -> dict:
    """In plugin mode, Claude Code's own two commands, as the weekly reminder names them. For
    any other install nothing is run: the page shows how that install is updated."""
    if kind != "plugin":
        return {"ok": False, "manual": how}
    by_hand = (f"claude plugin marketplace update {catalog}` then `claude plugin update baton@{catalog}")
    exe = shutil.which("claude")
    if not exe:
        return {"ok": False, "error": "the claude command is not on this machine's PATH",
                "manual": f"Run `{by_hand}` in a terminal, then restart the session."}
    steps = []
    for argv in ([exe, "plugin", "marketplace", "update", catalog],
                 [exe, "plugin", "update", f"baton@{catalog}"]):
        try:
            done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=180)
            code, out = done.returncode, (done.stdout + done.stderr).decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            code, out = -1, "timed out after 180 s"
        except OSError as err:
            code, out = -1, str(err)
        steps.append({"cmd": "claude " + " ".join(argv[1:]), "code": code,
                      "out": _ANSI.sub("", out)[-1500:]})
        if code != 0:
            return {"ok": False, "steps": steps,
                    "manual": f"Run `{by_hand}` in a terminal, then restart the session."}
    return {"ok": True, "steps": steps,
            "message": "Done. Restart the Claude Code session (exit, then start claude again) "
                       "to run the new version."}


# -- the server ------------------------------------------------------------------------------

def _ask(st: dict, method: str, name: str, timeout: float = 1.0) -> dict | None:
    """One request to a running page server on 127.0.0.1, by its key. None if none answers."""
    import http.client
    try:
        conn = http.client.HTTPConnection("127.0.0.1", int(st["port"]), timeout=timeout)
        conn.request(method, "/api/" + name, body=b"{}" if method == "POST" else None,
                     headers={HEADER: str(st["ticket"]), "Content-Type": "application/json",
                              "Host": f"127.0.0.1:{int(st['port'])}"})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        if resp.status != 200:
            return None
        got = json.loads(body)
        return got if isinstance(got, dict) else None
    except Exception:
        return None


def live() -> dict | None:
    """The state of the server that answers its own key, with its version, or None."""
    st = _read_json(state_path())
    if not st:
        return None
    got = _ask(st, "GET", "ping")
    if not got or not got.get("ok"):
        return None
    st["running"] = got.get("version")
    return st


def conf_path() -> Path:
    return identity_dir().parent / "baton.page.conf.json"


class Config:
    """What the page says about this install. SessionStart passes it; it is kept beside the state
    file, so a page opened later by hand (`--open`) knows a plugin install from a script one."""

    def __init__(self, args) -> None:
        if args.kind:
            try:
                _write_json(conf_path(), {"kind": args.kind, "catalog": args.catalog or "baton",
                                          "how": args.how or ""})
            except OSError:
                pass
        kept = _read_json(conf_path()) or {}
        self.version = args.version or hook().BATON_VERSION
        self.kind = args.kind or kept.get("kind") or "script"
        self.catalog = args.catalog or kept.get("catalog") or "baton"
        self.how = args.how or kept.get("how") or (
            "Update it the way it was installed: `git pull` in the folder Baton was installed from, "
            "then the installer again.")


def page_html() -> bytes:
    return PAGE.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "Baton"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:       # nothing on stdout or stderr
        pass

    def _send(self, status: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data).encode("utf-8"))

    def _refuse(self, status: int = 403) -> None:
        self.close_connection = True             # a body left unread must not start a request
        self._json(status, {"ok": False, "error": "refused"})

    def _host_ok(self) -> bool:
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def _ticket_ok(self, given) -> bool:
        return hmac.compare_digest(str(given or "").encode(), self.server.ticket.encode())

    def do_GET(self) -> None:
        self.server.touch()
        path = self.path.split("?", 1)[0]
        if not self._host_ok():
            return self._refuse()
        if path.startswith("/api/"):
            if not self._ticket_ok(self.headers.get(HEADER)):
                return self._refuse()
            return self._route("GET", path[5:], {})
        parts = path.strip("/").split("/")
        if len(parts) == 1 and self._ticket_ok(parts[0]):
            return self._send(200, page_html(), "text/html; charset=utf-8")
        self._json(404, {"ok": False, "error": "not here"})

    def do_POST(self) -> None:
        # The open page looks every 15 s: that is not use, so a forgotten tab does not keep the
        # server going past its idle time.
        polled = self.path.split("?", 1)[0] == "/api/watch"
        if not polled:
            self.server.touch()
        if not self._host_ok():
            return self._refuse()
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://127.0.0.1:{self.server.server_port}":
            return self._refuse()
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None and site not in ("same-origin", "none"):
            return self._refuse()
        if not self._ticket_ok(self.headers.get(HEADER)):
            return self._refuse()
        if not str(self.headers.get("Content-Type", "")).startswith("application/json"):
            return self._refuse(415)
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._refuse(400)
        if size < 0 or size > BODY_MAX:
            return self._refuse(413)
        try:
            data = json.loads(self.rfile.read(size) or b"{}")
        except ValueError:
            return self._refuse(400)
        if not isinstance(data, dict):
            return self._refuse(400)
        path = self.path.split("?", 1)[0]
        if not path.startswith("/api/"):
            return self._json(404, {"ok": False, "error": "not here"})
        self._route("POST", path[5:], data)

    def _route(self, method: str, name: str, data: dict) -> None:
        fn = ROUTES.get((method, name))
        if fn is None:
            return self._json(404, {"ok": False, "error": "not here"})
        use = name != "watch"
        self.server.busy(+1, use)
        try:
            status, out = 200, fn(self.server, data)
        except PageError as err:
            status, out = 200, {"ok": False, "error": str(err)}
        except Exception as err:
            status, out = 500, {"ok": False, "error": type(err).__name__}
        try:
            if name not in ("quit", "ping"):  # before the answer, so the page sees the box as it is
                self.server.sync_box()
            if name in ("state", "watch", "invite") and isinstance(out.get("box"), dict):
                out["box"] = self.server.box_view()
            self._json(status, out)
        finally:
            self.server.busy(-1, use)


def _state(srv, data) -> dict:
    cfg = srv.cfg
    srv.sync_box()                               # expired invitations go before they are listed
    try:
        ident = my_key()[0]
    except PageError:
        ident = None
    try:
        leads = [x for x in hook().release_leads(cfg.version) if not x.startswith("Not checked")]
    except Exception:
        leads = []
    return {"ok": True, "id": ident, "version": cfg.version, "leads": leads, "kind": cfg.kind,
            "how": cfg.how, "catalog": cfg.catalog, "keygen": bool(shutil.which("ssh-keygen")),
            "box": srv.box_view(), **_with_shares(friends_view())}


def _with_shares(view: dict) -> dict:
    """The messenger links for what can still be sent again: invitations waiting, replies."""
    try:
        for v in view["invites"]:
            v["share"] = share_links("invite", v["code"]) if v.get("code") else None
        for f in view["friends"]:
            f["share"] = share_links("accept", f["reply"]) if f.get("reply") else None
    except PageError:
        pass
    return view


def _update(srv, data) -> dict:
    if not srv.updating.acquire(blocking=False):
        return {"ok": False, "error": "an update is already running"}
    try:
        return run_update(srv.cfg.kind, srv.cfg.catalog, srv.cfg.how)
    finally:
        srv.updating.release()


def _quit(srv, data) -> dict:
    # A moment later, so this answer is written before the process ends (a test saw it cut, 21.11).
    threading.Timer(0.3, srv.shutdown).start()
    return {"ok": True}


def _nonce(data) -> str:
    n = str(data.get("nonce", ""))
    if not NONCE_RE.fullmatch(n):
        raise PageError("no such invitation")
    return n


def _invite(srv, data) -> dict:
    code = make_invite(str(data.get("text", "")), str(data.get("to", "")), str(data.get("nick", "")))
    return {"ok": True, "code": code, "share": share_links("invite", code)}


def _watch(srv, data) -> dict:
    """The open page's look every 15 s, not counted as use: it listens for boxes nearby and lists
    them. Nothing is fetched from one until the human clicks (_fetch)."""
    srv.nearby.start()
    return _state(srv, data)


def _fetch(srv, data) -> dict:
    """"Get invitation" for a box heard nearby: its ID, from the list the page shows."""
    ident = _their_id(data.get("id", ""))
    found = srv.nearby.boxes().get(ident)
    if not ident or not found:
        raise PageError("that box is no longer heard on this network")
    return {"ok": True, **fetch_from(ident, *found)}


def _accept(srv, data) -> dict:
    got = accept_to_box(_nonce(data), str(data.get("nick", "")))
    return {"ok": True, **got, "share": share_links("accept", got["code"])}


def _send(srv, data) -> dict:
    send_reply(str(data.get("id", "")))
    return {"ok": True}


def _nick(srv, data) -> dict:
    ident = str(data.get("id", ""))
    set_nick(str(data.get("nick", "")), ident=ident, nonce="" if ident else _nonce(data))
    return {"ok": True}


ROUTES = {
    ("GET", "ping"): lambda srv, data: {"ok": True, "version": srv.cfg.version},
    ("GET", "state"): _state,
    ("POST", "quit"): _quit,
    ("POST", "update"): _update,
    ("POST", "invite"): _invite,
    ("POST", "paste"): lambda srv, data: {"ok": True, **read_code(str(data.get("code", "")))},
    ("POST", "accept"): _accept,
    ("POST", "send"): _send,
    ("POST", "nick"): _nick,
    ("POST", "watch"): _watch,
    ("POST", "fetch"): _fetch,
    ("POST", "ignore"): lambda srv, data: (ignore(_nonce(data)), {"ok": True})[1],
    ("POST", "cancel"): lambda srv, data: (cancel(_nonce(data)), {"ok": True})[1],
    ("POST", "remove"): lambda srv, data: (remove(str(data.get("id", ""))), {"ok": True})[1],
}


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, cfg: Config) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.cfg = cfg
        self.ticket = os.urandom(16).hex()      # 128 bits, never on a command line
        self.updating = threading.Lock()
        self._last, self._busy, self._mx = time.time(), 0, threading.Lock()
        self.box, self._box_stop, self._box_mx, self.box_error = None, None, threading.Lock(), ""
        self.nearby = Nearby()

    def sync_box(self) -> None:
        """The box open while an addressed invitation waits here, closed when none does."""
        with self._box_mx:
            want = box_bind() if waiting_for_box() else None
            if want and self.box is None:
                try:
                    self.box = Box(*want)
                except OSError as err:
                    self.box_error = f"the box could not open {want[0]}:{want[1]} ({err.strerror or err})"
                    return
                self.box_error, self._box_stop = "", threading.Event()
                threading.Thread(target=self.box.serve_forever, kwargs={"poll_interval": 0.2},
                                 daemon=True).start()
                threading.Thread(target=announce, args=(self.box, want[1], self._box_stop),
                                 daemon=True).start()
            elif not want and self.box is not None:
                self.close_box()

    def close_box(self) -> None:
        box, self.box = self.box, None
        if box is not None:
            self._box_stop.set()
            box.shutdown()
            box.server_close()

    def box_view(self) -> dict:
        box = self.box
        if box is None:
            return {"on": False, "error": self.box_error, "nearby": sorted(self.nearby.boxes())}
        return {"on": True, "nearby": sorted(self.nearby.boxes())}

    def touch(self) -> None:
        self._last = time.time()

    def busy(self, n: int, use: bool = True) -> None:
        with self._mx:
            self._busy += n
            if use:
                self._last = time.time()

    def idle_watch(self) -> None:
        limit = _idle()
        while True:
            time.sleep(min(5.0, limit / 4))
            self.sync_box()                      # a reply taken by the box, with no page open, closes it
            with self._mx:
                quiet = self._busy == 0 and time.time() - self._last > limit
            if quiet:
                self.shutdown()
                return


def serve(cfg: Config, open_it: bool, quiet: bool = False) -> int:
    """Run the one server of this install here, or say the link of the one already running."""
    path = state_path()
    try:
        with FileLock(path.with_name("baton.page.lock")):
            st = live()
            if st and st.get("running") == cfg.version:
                if not quiet:
                    print(st["url"], flush=True)
                return 0
            if st:                               # another version: it gives way
                _ask(st, "POST", "quit")
                for _ in range(40):
                    if not live():
                        break
                    time.sleep(0.05)
            srv = Server(cfg)
            url = f"http://127.0.0.1:{srv.server_port}/{srv.ticket}/"
            _write_json(path, {"pid": os.getpid(), "port": srv.server_port, "ticket": srv.ticket,
                               "url": url, "version": cfg.version, "started": _now()})
    except (PageError, OSError) as err:
        if not quiet:
            print(f"baton page: {err}", file=sys.stderr)
        return 1
    if not quiet:
        print(url, flush=True)
    if open_it:
        open_url(url)
    threading.Thread(target=srv.idle_watch, daemon=True).start()
    srv.sync_box()
    try:
        srv.serve_forever(poll_interval=0.2)
    finally:
        srv.close_box()
        srv.nearby.stop()
        srv.server_close()
        if (_read_json(path) or {}).get("pid") == os.getpid():
            try:
                path.unlink()
            except OSError:
                pass
    return 0


def open_url(url: str) -> bool:
    """Open the link in the browser, with nothing written to our output. True when the opener
    started and did not fail within 1.5 s. BATON_OPENER names another opener (tests)."""
    opener = os.environ.get("BATON_OPENER")
    if opener:
        argv = ([sys.executable, opener] if opener.endswith(".py") else [opener]) + [url]
    elif os.name == "nt":
        try:
            os.startfile(url)                    # noqa: the shell's own opener, no console
            return True
        except OSError:
            return False
    elif sys.platform == "darwin":
        argv = ["open", url]
    else:
        exe = shutil.which("xdg-open")
        if not exe:
            return False
        argv = [exe, url]
    detach = ({"creationflags": 0x00000008 | 0x00000200 | 0x08000000} if os.name == "nt"
              else {"start_new_session": True})
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, **detach)
    except OSError:
        return False
    try:
        return proc.wait(timeout=1.5) == 0
    except subprocess.TimeoutExpired:
        return True


def ensure(cfg: Config, argv_tail: list, open_it: bool) -> dict:
    """The running server of this version, started detached if there is none; then opened if
    asked. {"url", "opened"} -- the link for the caller alone, or {} when none could start."""
    st = live()
    if not (st and st.get("running") == cfg.version):
        flags = 0x00000008 | 0x00000200 | 0x08000000          # DETACHED, NEW_GROUP, NO_WINDOW
        # Windows: also leave the caller's job (BREAKAWAY), or the server dies with an SSH session
        # (21.11); a job that forbids it refuses the start, so the second try goes without.
        tries = ([{"creationflags": flags | 0x01000000}, {"creationflags": flags}] if os.name == "nt"
                 else [{"start_new_session": True}])
        for detach in tries:
            try:
                subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve",
                                  "--no-open", "--quiet", *argv_tail],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, close_fds=True, **detach)
                break
            except OSError:
                continue
        else:
            return {}
        st = None
        end = time.time() + 6
        while time.time() < end:
            st = live()
            if st and st.get("running") == cfg.version:
                break
            st = None
            time.sleep(0.05)
        if not st:
            return {}
    return {"url": st["url"], "opened": bool(open_it and open_url(st["url"]))}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Baton's page on 127.0.0.1, and friend invitations.")
    p.add_argument("--serve", action="store_true", help="run the page server here and print its link")
    p.add_argument("--no-open", action="store_true", help="with --serve: do not open the browser")
    p.add_argument("--quiet", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--ensure", action="store_true", help=argparse.SUPPRESS)   # SessionStart's
    p.add_argument("--open", action="store_true", help="open the page (the link is not printed)")
    p.add_argument("--invite", metavar="TEXT", nargs="?", const="", help="print an invitation code")
    p.add_argument("--accept", metavar="CODE", help="accept an invitation or take in a reply; - reads stdin")
    p.add_argument("--identity", help="the identity folder (default: BATON_IDENTITY, else ~/.claude/baton/identity)")
    p.add_argument("--version", help=argparse.SUPPRESS)
    p.add_argument("--kind", choices=("plugin", "script", "gemini", "codex"), help=argparse.SUPPRESS)
    p.add_argument("--catalog", help=argparse.SUPPRESS)
    p.add_argument("--how", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    if args.identity:
        os.environ["BATON_IDENTITY"] = args.identity     # read by own_id() in the hook's code
    tail = [a for pair in (("--identity", str(identity_dir())), ("--version", args.version),
                           ("--kind", args.kind), ("--catalog", args.catalog), ("--how", args.how))
            if pair[1] for a in pair]
    try:
        if args.invite is not None:
            print(make_invite(args.invite), end="")
            print("Send this code to them yourself (a message, a mail, in person). You are friends "
                  "once they accept and you paste their reply here.", file=sys.stderr)
            return 0
        if args.accept is not None:
            code = sys.stdin.read() if args.accept == "-" else args.accept
            got = read_code(code)
            if got["kind"] == "accept":
                print(f"{got['id']} accepted your invitation: you are friends now.")
                return 0
            # The invitation's text is the human's: shown on the page, never printed here.
            print(accept(got["nonce"]), end="")
            print(f"Accepted the invitation of {got['id']}. Send this reply code back to them; "
                  "its message is on the Baton page.", file=sys.stderr)
            return 0
        cfg = Config(args)
        if args.serve:
            return serve(cfg, open_it=not args.no_open, quiet=args.quiet)
        if args.ensure or args.open:
            got = ensure(cfg, tail, open_it=args.open)
            if args.ensure:
                print(json.dumps(got))
            elif not got:
                print("baton page: the page server did not start", file=sys.stderr)
                return 1
            else:
                print("The Baton page is open in the browser." if got["opened"] else
                      "The page server runs, but no browser could be opened here; run "
                      "--serve --no-open in your own terminal for the link.")
            return 0
    except PageError as err:
        print(f"baton page: {err}", file=sys.stderr)
        return 1
    p.print_help()
    return 2


CSP = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Baton</title>
<style>
:root{
  --bg:#f4f5f7; --card:#ffffff; --card-2:#f8f9fb; --line:#e4e7ec; --text:#1c2230; --muted:#667085;
  --accent:#2f7d6d; --accent-soft:#e3f2ee; --accent-text:#1f5e51;
  --turn:#fff7e6; --turn-line:#f0c36d; --turn-text:#8a5a00;
  --ok:#1f8a4c; --ok-soft:#e5f5ec; --bad:#c2362b; --bad-soft:#fdecea;
  --shadow:0 1px 2px rgba(16,24,40,.05),0 4px 14px rgba(16,24,40,.06);
  --radius:16px;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#11151c; --card:#1a2029; --card-2:#202733; --line:#2c3441; --text:#e6e9ef; --muted:#98a2b3;
    --accent:#5cc4ab; --accent-soft:#16332d; --accent-text:#8fe0cb;
    --turn:#2a2416; --turn-line:#8a6a2a; --turn-text:#f0c36d;
    --ok:#4cc483; --ok-soft:#14301f; --bad:#ff7a6e; --bad-soft:#3a1c1a;
    --shadow:0 1px 2px rgba(0,0,0,.3),0 6px 18px rgba(0,0,0,.25);
  }
  .btn.primary{color:#0d1f1a}.btn.primary svg{stroke:#0d1f1a}
}
*{box-sizing:border-box}
html,body{margin:0}
body{background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans",Ubuntu,Cantarell,sans-serif;-webkit-font-smoothing:antialiased}
button{font:inherit;color:inherit;cursor:pointer}
.mono{font-family:var(--mono);font-size:.86em;letter-spacing:.02em}
.muted{color:var(--muted)} .small{font-size:13px}
svg.i{width:16px;height:16px;flex:none;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;vertical-align:-3px}
.top{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line)}
.top-in{max-width:1180px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:12px}
.brand{display:flex;align-items:center;gap:8px;font-weight:700;font-size:17px}
.brand .logo{width:28px;height:28px;border-radius:8px;background:var(--accent);display:grid;place-items:center}
.brand .logo svg{stroke:#fff}
.sp{flex:1}
.pill{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;background:var(--card);border:1px solid var(--line);font-size:13px;color:var(--muted)}
.wrap{max-width:1180px;margin:0 auto;padding:20px 16px 48px;display:grid;grid-template-columns:300px minmax(0,1fr) 260px;gap:20px;align-items:start}
.col{display:flex;flex-direction:column;gap:16px;min-width:0}
@media (max-width:1020px){.wrap{grid-template-columns:280px minmax(0,1fr)}.right{grid-column:1 / -1}}
@media (max-width:720px){.wrap{grid-template-columns:1fr;padding-top:12px}.top .hide-sm{display:none}}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);padding:16px}
.card h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 12px;font-weight:600;display:flex;align-items:center;gap:8px}
.card h2 .count{margin-left:auto;text-transform:none;letter-spacing:0}
.av{width:56px;height:56px;border-radius:50%;display:grid;place-items:center;background:var(--accent);flex:none}
.av svg{stroke:#fff;width:26px;height:26px}
.prof-head{display:flex;gap:12px;align-items:center}
.prof-name{font-weight:700;font-size:17px}
.idrow{margin-top:14px;display:flex;align-items:center;gap:8px;background:var(--card-2);border:1px solid var(--line);border-radius:10px;padding:8px 10px}
.idrow .mono{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.icon-btn{border:0;background:transparent;padding:4px;border-radius:8px;color:var(--muted);display:inline-grid;place-items:center}
.icon-btn:hover{background:var(--accent-soft);color:var(--accent-text)}
.friend{display:flex;flex-direction:column;gap:4px;padding:10px 0;border-top:1px solid var(--line)}
.friend:first-of-type{border-top:0;padding-top:0}
.friend .nm{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.friend .nm .mono{flex:1 1 100%;font-weight:600}
.st{font-size:12px;font-weight:600;padding:1px 8px;border-radius:999px;white-space:nowrap}
.st.ok{color:var(--ok);background:var(--ok-soft)} .st.wait{color:var(--turn-text);background:var(--turn);border:1px solid var(--turn-line)}
.field{display:flex;flex-direction:column;gap:4px;margin-bottom:10px;font-size:13px;color:var(--muted)}
.field input{font:inherit;font-size:14px;color:var(--text);background:var(--card-2);border:1px solid var(--line);border-radius:10px;padding:7px 10px;width:100%}
.field input.mono{font-family:var(--mono);font-size:13px}
.field textarea{font:inherit;font-size:14px;color:var(--text);background:var(--card-2);border:1px solid var(--line);border-radius:10px;padding:8px 10px;width:100%;resize:vertical;min-height:64px}
.field textarea.code-in{font-family:var(--mono);font-size:12px;min-height:110px}
.field textarea:focus{outline:2px solid color-mix(in srgb,var(--accent) 45%,transparent);border-color:var(--accent)}
.hint{display:flex;justify-content:space-between;gap:8px;font-size:12px}
.err{color:var(--bad);font-size:13px;margin-top:8px}
.okline{display:flex;gap:6px;align-items:center;font-weight:600;color:var(--ok);margin-top:10px;font-size:14px}
.code{font-family:var(--mono);font-size:12px;background:var(--card-2);border:1px solid var(--line);border-radius:10px;padding:8px 10px;overflow-wrap:anywhere;white-space:pre-wrap;line-height:1.5;margin:10px 0 0;max-height:180px;overflow:auto}
.request{background:var(--accent-soft);border:1px solid color-mix(in srgb,var(--accent) 30%,transparent);border-radius:12px;padding:12px;margin-top:12px}
.msg{margin:10px 0;border-left:3px solid var(--accent);background:var(--card);border-radius:0 10px 10px 0;padding:8px 10px;font-size:14px;white-space:pre-wrap;overflow-wrap:anywhere}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.btn{border:1px solid var(--line);background:var(--card);border-radius:10px;padding:7px 14px;font-weight:600;font-size:14px;display:inline-flex;align-items:center;gap:6px}
.btn:hover{border-color:var(--accent)} .btn[disabled]{opacity:.5;cursor:wait}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.btn.primary svg{stroke:#fff}
.btn.sm{padding:3px 10px;font-size:12.5px}
a.btn{text-decoration:none;color:inherit} a.btn.primary{color:#fff}
.btn.big{padding:10px 18px;font-size:15px}
.note{display:flex;gap:8px;font-size:12.5px;color:var(--muted);margin-top:12px;line-height:1.45}
.note svg{margin-top:2px}
.leads{margin:0;padding-left:20px;display:flex;flex-direction:column;gap:6px}
.ver{font-size:20px;font-weight:700;margin:0 0 4px}
.status{margin-top:10px;font-size:14px;white-space:pre-wrap;overflow-wrap:anywhere}
.status pre{font-family:var(--mono);font-size:12px;background:var(--card-2);border:1px solid var(--line);border-radius:10px;padding:8px 10px;white-space:pre-wrap;max-height:200px;overflow:auto}
.pending{display:flex;flex-direction:column;gap:6px;margin-top:12px;padding:8px 10px;border-radius:10px;background:var(--turn);border:1px solid var(--turn-line);color:var(--turn-text);font-size:13px}
.soon{background:var(--card-2);border-style:dashed}
.term{font-family:var(--mono);font-size:12.5px;background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:10px 12px;line-height:1.65;white-space:pre-wrap}
.toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%) translateY(20px);background:var(--text);color:var(--bg);padding:8px 14px;border-radius:10px;font-size:14px;opacity:0;transition:.2s;pointer-events:none}
.toast.on{opacity:1;transform:translateX(-50%)}
.foot{grid-column:1 / -1;text-align:center;font-size:12px;color:var(--muted)}
</style>
</head>
<body>
<header class="top"><div class="top-in">
  <div class="brand"><span class="logo" data-icon="baton"></span>Baton</div>
  <div class="sp"></div>
  <span class="pill hide-sm"><span data-icon="lock"></span><span id="where-pill">this machine only</span></span>
  <span class="pill" id="ver-pill"></span>
</div></header>
<main class="wrap">
  <aside class="col left" id="left"></aside>
  <section class="col center" id="center"></section>
  <aside class="col right" id="right"></aside>
  <div class="foot">Served by Baton on 127.0.0.1. It stops by itself after 30 minutes without use, and your box with it.</div>
</main>
<div class="toast" id="toast" role="status"></div>
<script>
"use strict";
/* Every string from the server is shown with textContent, never as HTML: an invitation's text
   was written by someone else. Icons are built from the fixed paths below. */
const KEY = location.pathname.split("/")[1];
const ICONS = {
  baton: ["M4 20 L20 4", "M15 4h5v5", "M4 15v5h5"],
  copy: ["M9 9h11v11H9z", "M5 15H4V4h11v1"],
  check: ["M5 12l5 5 9-10"],
  x: ["M6 6l12 12", "M18 6L6 18"],
  lock: ["M6 11h12v9H6z", "M8 11V8a4 4 0 0 1 8 0v3"],
  user: ["M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M4 21a8 8 0 0 1 16 0"],
  users: ["M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M2 21a7 7 0 0 1 14 0", "M16 3.5a4 4 0 0 1 0 7.5", "M22 21a7 7 0 0 0-4-6.3"],
  star: ["M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"],
  down: ["M12 4v12", "M6 10l6 6 6-6", "M4 20h16"],
  inbox: ["M3 13h5l2 3h4l2-3h5", "M5 5h14l2 8v6H3v-6z"],
  book: ["M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z", "M4 19V5", "M8 7h7"],
  eye: ["M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z", "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"],
  info: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M12 11v6", "M12 7h.01"]
};
const SVGNS = "http://www.w3.org/2000/svg";
function icon(name){
  const s = document.createElementNS(SVGNS, "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("class", "i"); s.setAttribute("aria-hidden", "true");
  for (const d of ICONS[name] || []) { const p = document.createElementNS(SVGNS, "path"); p.setAttribute("d", d); s.appendChild(p); }
  return s;
}
function el(spec, attrs, ...kids){
  const [tag, ...cls] = spec.split(".");
  const n = document.createElement(tag || "div");
  if (cls.length) n.className = cls.join(" ");
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (k === "on") for (const [ev, fn] of Object.entries(v)) n.addEventListener(ev, fn);
    else n.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) n.appendChild(typeof k === "string" ? document.createTextNode(k) : k);
  return n;
}
function toast(msg){
  const t = document.getElementById("toast"); t.textContent = msg; t.classList.add("on");
  clearTimeout(toast._h); toast._h = setTimeout(() => t.classList.remove("on"), 1800);
}
function copy(text, what){
  (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(
    () => toast(what + " copied"), () => toast("Copy failed: select the text"));
}
/* A code goes by the messenger the human already uses: WhatsApp (wa.me opens it with the text
   ready; they pick the contact), a mail, or the clipboard. The links come from the server. */
function link(spec, href, ...kids){
  const a = el(spec, {target: "_blank", rel: "noopener noreferrer"}, ...kids);
  a.setAttribute("href", href);
  return a;
}
function shareButtons(sh, what, small){
  if (!sh) return null;
  const sz = small ? ".sm" : "";
  return el("div.btns", null,
    link("a.btn" + sz + (small ? "" : ".primary.big"), sh.whatsapp, "Send on WhatsApp"),
    link("a.btn" + sz, sh.email, "Email"),
    el("button.btn" + sz, {type: "button", on: {click: () => copy(sh.text, what)}}, icon("copy"), "Copy"));
}
function shareBox(sh, what){
  copy(sh.text, what);                       // on the click that made it: ready to paste anywhere
  return el("div", null, shareButtons(sh, what, false),
    el("div.note", null, icon("info"), el("span", null, "WhatsApp opens with the message ready; you pick the contact. The messenger carries a signed code: it sees the code and its note, nothing else of yours.")));
}
async function api(name, body){
  const opt = {method: body === undefined ? "GET" : "POST", headers: {"X-Baton-Ticket": KEY}};
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  try {
    const r = await fetch("/api/" + name, opt);
    return await r.json();
  } catch (e) {
    return {ok: false, error: "the page server has stopped (30 minutes without use). Ask your agent to open the Baton page, or run: python3 tools/baton_page.py --open"};
  }
}
document.querySelectorAll("[data-icon]").forEach(n => n.appendChild(icon(n.dataset.icon)));

let S = null;
const keep = {};        // cards built once, so typed text survives a refresh
async function refresh(){
  const got = await api("state");
  if (!got.ok) { toast(got.error || "error"); return; }
  S = got; render();
}

function render(){
  document.getElementById("ver-pill").textContent = "v" + S.version;
  document.getElementById("where-pill").textContent = S.box.on ? "this machine; my box is open to friends" : "this machine only";
  renderLeft(); renderCenter(); renderRight();
}

function renderLeft(){
  const L = document.getElementById("left"); L.replaceChildren();
  const id = S.id || "no ID yet";
  L.appendChild(el("div.card", null,
    el("div.prof-head", null, el("span.av", {"aria-hidden": "true"}, icon("user")),
      el("div", null, el("div.prof-name", null, "This Baton"), el("div.small.muted", null, "My profile"))),
    el("div.idrow", null, el("span.mono", {title: id}, id),
      S.id ? el("button.icon-btn", {type: "button", "aria-label": "Copy my Baton ID", title: "Copy",
        on: {click: () => copy(S.id, "ID")}}, icon("copy")) : null),
    el("div.note", null, icon("info"), el("span", null, S.id
      ? "Your install's ID. Give it only to people you trust: they need it to invite you. It is a fingerprint of a key made on this machine."
      : "The ID is made at a session start by ssh-keygen" + (S.keygen ? "." : ", which is not on this machine.")))));

  const fc = el("div.card", null, el("h2", null, icon("users"), "Friends", el("span.count.muted", null, String(S.friends.length))));
  if (!S.friends.length) fc.appendChild(el("div.small.muted", null, "No friends yet. Invite someone, or paste their invitation."));
  for (const f of S.friends) {
    const mutual = f.status === "mutual";
    const name = f.nick ? el("span", {title: f.id}, el("b", null, f.nick), " (", el("span.mono", null, f.id), ")")
                        : el("span.mono", {title: f.id}, f.id);
    const row = el("div.friend", null,
      el("div.nm", null, name,
        el("span.st." + (mutual ? "ok" : "wait"), null, mutual ? "friends" : "send them your reply"),
        el("button.btn.sm", {type: "button", title: "Your own name for them: kept on this machine only",
          on: {click: async () => { const n = prompt("Nickname for " + f.id + " (only you see it, up to 40 characters)", f.nick || "");
            if (n === null) return; const r = await api("nick", {id: f.id, nick: n}); toast(r.ok ? "Saved" : r.error); refresh(); }}}, "Rename"),
        el("button.btn.sm", {type: "button", title: "Stops new things only; what they already have stays with them",
          on: {click: async () => { if (!confirm("Remove " + f.id + "? It stops new things only.")) return;
            const r = await api("remove", {id: f.id}); toast(r.ok ? "Removed" : r.error); refresh(); }}}, "Remove")));
    if (!mutual) {
      row.appendChild(el("div.small.muted", null, "You accepted. Send them your reply; on their side you become friends when they paste it. Nothing more comes back here."));
      const b = el("div.btns");
      if (f.share) b.appendChild(shareButtons(f.share, "Reply", true));
      if (f.reply && f.box) b.appendChild(el("button.btn.sm", {type: "button", on: {click: async () => {
        const r = await api("send", {id: f.id}); toast(r.ok ? "Reply sent to their box" : r.error); refresh(); }}}, "Send it to their box again"));
      row.appendChild(b);
    }
    if (f.note) row.appendChild(el("div.small.muted", null, "Their note: ", el("span", null, f.note)));
    fc.appendChild(row);
  }
  fc.appendChild(el("div.note", null, icon("lock"), el("span", null,
    "Friends only when both sides accept. Remove stops new things only; what they already have stays with them.")));
  L.appendChild(fc);
}

function renderCenter(){
  const C = document.getElementById("center"); C.replaceChildren();
  const news = el("div.card", null, el("h2", null, icon("star"), "New in this version"),
    el("p.ver", null, "Baton v" + S.version));
  if (S.leads.length) news.appendChild(el("ul.leads", null, S.leads.map(t => el("li", null, t))));
  else news.appendChild(el("div.small.muted", null, "The notes for this version are not on this machine."));
  C.appendChild(news);
  C.appendChild(updateCard());
  C.appendChild(inviteCard());
  C.appendChild(pasteCard());
}

function updateCard(){
  const status = el("div.status", {role: "status"});
  const card = el("div.card", null, el("h2", null, icon("down"), "Update Baton"));
  if (S.kind === "plugin") {
    const btn = el("button.btn.primary", {type: "button"}, icon("down"), "Update Baton");
    btn.addEventListener("click", async () => {
      btn.disabled = true; status.replaceChildren("Updating: claude plugin marketplace update " + S.catalog + ", then claude plugin update baton@" + S.catalog + " ...");
      const r = await api("update", {});
      btn.disabled = false; status.replaceChildren();
      status.appendChild(el(r.ok ? "div.okline" : "div.err", null, r.ok ? icon("check") : icon("x"),
        r.ok ? (r.message || "Done.") : (r.error || "The update did not finish.")));
      for (const s of r.steps || []) status.appendChild(el("pre", null, "$ " + s.cmd + "  (exit " + s.code + ")\n" + s.out));
      if (r.manual) status.appendChild(el("div", null, r.manual));
    });
    card.append(el("div.small.muted", null, "Runs Claude Code's own update for the " + S.catalog + " catalog. Nothing runs until you click."), el("div.btns", null, btn), status);
  } else {
    card.append(el("div.small.muted", null, "This Baton was not installed as a Claude Code plugin, so the page does not update it. To update:"),
      el("div.code", null, S.how));
  }
  return card;
}

function inviteCard(){
  if (keep.invite) { keep.drawInvites(); return keep.invite; }
  const toIn = el("input.mono", {maxlength: "18", placeholder: "BTN-XXXX-XXXX-XXXX", "aria-label": "Your friend's Baton ID", spellcheck: "false", autocomplete: "off"});
  const nickIn = el("input", {maxlength: "40", placeholder: "Optional: what you call them", "aria-label": "Nickname"});
  const msgIn = el("textarea", {maxlength: "140", placeholder: "Optional: who you are, in a sentence", "aria-label": "Short message"});
  const counter = el("span", null, "0 / 140");
  const result = el("div"), err = el("div.err"), list = el("div");
  msgIn.addEventListener("input", () => { counter.textContent = msgIn.value.length + " / 140"; });
  const create = el("button.btn.primary", {type: "button"}, icon("user"), "Invite");
  create.addEventListener("click", async () => {
    err.textContent = ""; result.replaceChildren(); create.disabled = true;
    const addressed = toIn.value.trim() !== "";
    const r = await api("invite", {text: msgIn.value, to: toIn.value, nick: nickIn.value});
    create.disabled = false;
    if (!r.ok) { err.textContent = r.error; return; }
    msgIn.value = ""; toIn.value = ""; nickIn.value = ""; counter.textContent = "0 / 140";
    await refresh();
    result.replaceChildren(el("div", null,
      addressed ? el("div.okline", null, icon("check"), S.box.on ? "Waiting in your box, which is now open to friends." : "Kept here; the box did not open: " + (S.box.error || "switched off")) : null,
      addressed ? el("div.small.muted", null, "On the same network their page finds it by itself. Otherwise send it:") : null,
      shareBox(r.share, "Invitation"),
      el("div.small.muted", null, "When they accept, their reply comes back to your box, or they send it the same way and you paste it below.")));
  });
  keep.drawInvites = () => {
    list.replaceChildren();
    for (const v of S.invites) {
      const whom = v.to ? [" for ", v.nick ? el("b", null, v.nick) : null, v.nick ? " (" : "", el("span.mono", null, v.to), v.nick ? ")" : ""]
                        : (v.nick ? [" for ", el("b", null, v.nick)] : []);
      list.appendChild(el("div.pending", null,
        el("div", null, "Invitation", ...whom, (v.fetched ? ", fetched by them," : "") + " waiting for a reply since " + (v.created || "").replace("T", " ").slice(0, 16) + (v.expires ? ", in your box until " + v.expires.slice(0, 10) : "") + (v.text ? ": " : ""), v.text ? el("span", null, v.text) : null),
        el("div.btns", null,
          shareButtons(v.share, "Invitation", true),
          el("button.btn.sm", {type: "button", on: {click: async () => { await api("cancel", {nonce: v.nonce}); toast("Invitation cancelled"); refresh(); }}}, "Cancel"))));
    }
  };
  keep.drawInvites();
  keep.invite = el("div.card", null, el("h2", null, icon("users"), "Invite a friend"),
    el("label.field", null, "Their Baton ID (on their own page). With it, the invitation waits in your box for them; without, you get a code to send yourself", toIn),
    el("label.field", null, "Nickname (only for you: kept on this machine, never sent)", nickIn),
    el("label.field", null, "Message (plain text, shown to them; Baton never puts it in their agent's context)", msgIn, el("div.hint", null, el("span", null, "Links are not clickable"), counter)),
    create, err, result, list);
  return keep.invite;
}

function pasteCard(){
  if (keep.paste) { keep.drawIncoming(); return keep.paste; }
  const codeIn = el("textarea.code-in", {placeholder: "The whole message is fine: -----BEGIN BATON INVITE----- ...", "aria-label": "Invitation or reply code", spellcheck: "false"});
  const err = el("div.err"), out = el("div"), list = el("div");
  const check = el("button.btn", {type: "button"}, icon("check"), "Check");
  check.addEventListener("click", async () => {
    err.textContent = ""; out.replaceChildren(); check.disabled = true;
    await take(codeIn.value);
    check.disabled = false;
  });
  async function take(text){
    const r = await api("paste", {code: text});
    if (!r.ok) { err.textContent = r.error; return; }
    codeIn.value = "";
    if (r.kind === "accept") out.appendChild(el("div.okline", null, icon("check"), "You and " + r.id + " are friends now."));
    refresh();
  }
  const fromClip = el("button.btn.primary.big", {type: "button"}, icon("inbox"), "Paste invitation or reply");
  fromClip.addEventListener("click", async () => {
    err.textContent = ""; out.replaceChildren();
    let text = null;
    try { text = await navigator.clipboard.readText(); } catch (e) { text = null; }
    if (!text) { err.textContent = "The page could not read the clipboard here: paste it into the box below and press Check."; codeIn.focus(); return; }
    await take(text);
  });
  keep.drawIncoming = () => {
    list.replaceChildren();
    for (const v of S.incoming) {
      const box = el("div.request", null,
        el("div", null, el("b", null, "Invitation from "), el("span.mono", null, v.id)),
        el("div.small.muted", null, (v.via === "box" ? "Fetched from their box. " : "") + "Signature checked against the key inside; the ID matches that key."));
      if (v.text) box.appendChild(el("blockquote.msg", null, v.text));
      const nickIn = el("input", {maxlength: "40", placeholder: "Optional: what you call them", "aria-label": "Nickname"});
      box.appendChild(el("label.field", null, "Nickname (only for you)", nickIn));
      const reply = el("div");
      box.appendChild(el("div.btns", null,
        el("button.btn.primary", {type: "button", on: {click: async () => {
          const r = await api("accept", {nonce: v.nonce, nick: nickIn.value});
          if (!r.ok) { toast(r.error); return; }
          if (r.sent) out.replaceChildren(el("div.okline", null, icon("check"), "Accepted. Your reply went to " + v.id + "'s box: you are friends."));
          else out.replaceChildren(el("div", null, r.error ? el("div.err", null, "Their box did not take the reply: " + r.error) : null,
            el("div.okline", null, icon("check"), "Accepted. Send this reply back to " + v.id + ":"),
            shareBox(r.share, "Reply")));
          refresh(); }}}, icon("check"), "Accept"),
        el("button.btn", {type: "button", on: {click: async () => { await api("ignore", {nonce: v.nonce}); toast("Ignored. They are not told."); refresh(); }}}, "Ignore")));
      box.appendChild(reply);
      list.appendChild(box);
    }
  };
  keep.drawIncoming();
  keep.paste = el("div.card", null, el("h2", null, icon("inbox"), "An invitation or a reply"),
    el("div.btns", null, fromClip), el("label.field", null, "Or paste the message they sent you here", codeIn), check, err, list, out,
    el("div.note", null, icon("info"), el("span", null, "On the same network, an invitation from a friend's box shows here by itself while this page is open. An invitation's message is shown here; Baton never puts it in your agent's context. Ignore tells nobody.")));
  return keep.paste;
}

function renderRight(){
  const R = document.getElementById("right"); R.replaceChildren();
  const B = S.box, card = el("div.card", null, el("h2", null, icon("inbox"), "My box"));
  if (B.on) card.append(el("div.small", null, "Open to friends on this network while an invitation of yours waits."));
  else card.append(el("div.small.muted", null, B.error ? "Closed: " + B.error : "Closed. It opens by itself while an invitation you addressed waits (7 days at most) and this page's server runs."));
  for (const id of B.nearby || []) card.append(el("div.pending", null,
    el("div", null, el("span.mono", null, id), " (nearby) has a box open"),
    el("div.btns", null, el("button.btn.sm.primary", {type: "button", on: {click: async () => {
      const r = await api("fetch", {id: id});
      toast(!r.ok ? r.error : r.invites ? "An invitation from " + id + " is below" : "Nothing there for you" + (r.refused ? " that checks out" : ""));
      refresh(); }}}, "Get invitation"))));
  card.append(el("div.note", null, icon("info"), el("span", null, "On one network the pages find each other and nothing is typed. Across networks, send the code by WhatsApp or mail. The box gives an invitation only to the ID it is for, after a key proof; nicknames never leave this machine.")));
  R.appendChild(card);
  R.appendChild(el("div.card.soon", null, el("h2", null, icon("book"), "Shared tasks"),
    el("div.small.muted", null, "Coming soon: tasks shared with friends, and their feed, on this page.")));
  const n = S.incoming.length;
  R.appendChild(el("div.card", null, el("h2", null, icon("eye"), "What my agent sees"),
    el("div.term", null, n ? n + " friend invitation" + (n === 1 ? "" : "s") + " waiting" : "(nothing from this page)"),
    el("div.note", null, icon("info"), el("span", null, "Counts only: never a message, never this page's link."))));
}

let POLL = null;
async function watch(){
  const got = await api("watch", {});
  if (!got.ok) { if (/has stopped/.test(got.error || "")) { clearInterval(POLL); toast(got.error); } return; }
  const was = JSON.stringify([S.incoming, S.friends, S.invites, S.box]);
  if (JSON.stringify([got.incoming, got.friends, got.invites, got.box]) !== was) { S = got; render(); }
}
refresh().then(() => { watch(); POLL = setInterval(watch, 15000); });
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
