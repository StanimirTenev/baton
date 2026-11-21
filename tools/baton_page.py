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

Friends: an invitation is a code the human sends by any channel. It carries the sender's ID,
public key, a text of up to 140 characters, a time and a nonce, signed with this install's key
(`ssh-keygen -Y sign -n baton-invite`). The receiver checks the signature against the key inside
and that the key gives the ID claimed. Accepting makes a reply code, signed the same way, that
names the invitation; the inviter pastes it and both have accepted. Nothing is sent by Baton.
The text of an invitation is for the human: nothing here prints it, and the hook counts them.
"""
from __future__ import annotations   # `str | None`: Python 3.8 and 3.9 too

import argparse
import base64
import hashlib
import hmac
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
HEADER = "X-Baton-Ticket"
NAMESPACE = "baton-invite"
TEXT_MAX = 140
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


def sign(message: bytes) -> str:
    """An SSH signature of `message` in the baton-invite namespace. The old .sig is removed
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
                subprocess.run([exe, "-Y", "sign", "-f", str(key), "-n", NAMESPACE, str(msg)],
                               stdin=subprocess.DEVNULL, stdout=fo, stderr=fo, timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                raise PageError("ssh-keygen did not sign")
        if not sig.is_file():
            raise PageError("ssh-keygen did not sign")
        return sig.read_text("ascii").replace("\r\n", "\n")


def verify(message: bytes, signature: str, pub: str) -> bool:
    """Whether `signature` is `pub`'s over `message` in the baton-invite namespace. The message
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
        allowed.write_text(f'peer namespaces="{NAMESPACE}" {pub}\n', "ascii")
        with open(msg, "rb") as fi, open(out, "wb") as fo:
            try:
                done = subprocess.run([exe, "-Y", "verify", "-f", str(allowed), "-I", "peer",
                                       "-n", NAMESPACE, "-s", str(sig)],
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
    body = re.sub(r"\s+", "", armored.group(2) if armored else text)
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
    want = {"v": int, "kind": str, "id": str, "pub": str, "created": str, "nonce": str}
    want.update({"text": str} if kind == "invite" else {"to": str, "invite": str})
    if set(payload) != set(want) or any(not isinstance(payload[k], t) for k, t in want.items()):
        raise PageError("that code is not in a form this Baton reads")
    if (payload["v"] != 1 or not ID_RE.fullmatch(payload["id"]) or not PUB_RE.fullmatch(payload["pub"])
            or not NONCE_RE.fullmatch(payload["nonce"])
            or (kind == "invite" and len(payload["text"]) > TEXT_MAX)
            or (kind == "accept" and not (ID_RE.fullmatch(payload["to"])
                                         and NONCE_RE.fullmatch(payload["invite"])))):
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


def make_invite(text: str = "") -> str:
    text = clean(text)
    if len(text) > TEXT_MAX:
        raise PageError(f"the text is longer than {TEXT_MAX} characters")
    ident, pub, _ = my_key()
    payload = {"v": 1, "kind": "invite", "id": ident, "pub": pub, "text": text,
               "created": _now(), "nonce": os.urandom(16).hex()}
    code = _signed(payload)
    with Store() as s:
        s["invites"][payload["nonce"]] = {"text": text, "created": payload["created"], "code": code}
    return code


def read_code(code: str) -> dict:
    """Check a pasted code and keep what it says. An invitation waits for the human's decision;
    a reply to an invitation made here makes the friendship mutual."""
    payload, message, signature = decode(code)
    if id_of(payload["pub"]) != payload["id"]:
        raise PageError("the ID in that code is not the ID of the key in it")
    if not verify(message, signature, payload["pub"]):
        raise PageError("the signature on that code does not verify: it was changed, or not made by Baton")
    ident, _, _ = my_key()
    if payload["id"] == ident:
        raise PageError("that code was made by this install")
    with Store() as s:
        if payload["kind"] == "invite":
            s["incoming"][payload["nonce"]] = {"id": payload["id"], "pub": payload["pub"],
                                               "text": payload["text"], "created": payload["created"]}
            return {"kind": "invite", "id": payload["id"], "nonce": payload["nonce"],
                    "text": clean(payload["text"])}
        if payload["to"] != ident or payload["invite"] not in s["invites"]:
            raise PageError("that reply does not answer an invitation waiting on this install "
                            "(made elsewhere, cancelled, or already used)")
        note = s["invites"].pop(payload["invite"]).get("text", "")
        s["friends"][payload["id"]] = {"pub": payload["pub"], "status": "mutual", "since": _now(),
                                       "note": note}
        return {"kind": "accept", "id": payload["id"], "status": "mutual"}


def accept(nonce: str) -> str:
    """Accept a pasted invitation: the peer is trusted from this side, and the reply code to
    send back is returned. Mutual only once the inviter pastes it."""
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
                                   "reply": code}
    return code


def ignore(nonce: str) -> None:
    with Store() as s:
        s["incoming"].pop(nonce, None)


def cancel(nonce: str) -> None:
    with Store() as s:
        s["invites"].pop(nonce, None)


def remove(ident: str) -> None:
    with Store() as s:
        s["friends"].pop(ident, None)


def friends_view() -> dict:
    data = _read_json(friends_path()) or {}

    def part(name):
        return data.get(name) if isinstance(data.get(name), dict) else {}
    return {
        "friends": [{"id": k, "status": v.get("status"), "since": v.get("since"),
                     "note": clean(v.get("note", "")), "reply": v.get("reply", "")}
                    for k, v in sorted(part("friends").items())],
        "invites": [{"nonce": k, "text": clean(v.get("text", "")), "created": v.get("created"),
                     "code": v.get("code", "")} for k, v in part("invites").items()],
        "incoming": [{"nonce": k, "id": v.get("id"), "text": clean(v.get("text", "")),
                      "created": v.get("created")} for k, v in part("incoming").items()],
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
        self.server.busy(+1)
        try:
            self._json(200, fn(self.server, data))
        except PageError as err:
            self._json(200, {"ok": False, "error": str(err)})
        except Exception as err:
            self._json(500, {"ok": False, "error": type(err).__name__})
        finally:
            self.server.busy(-1)


def _state(srv, data) -> dict:
    cfg = srv.cfg
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
            **friends_view()}


def _update(srv, data) -> dict:
    if not srv.updating.acquire(blocking=False):
        return {"ok": False, "error": "an update is already running"}
    try:
        return run_update(srv.cfg.kind, srv.cfg.catalog, srv.cfg.how)
    finally:
        srv.updating.release()


def _quit(srv, data) -> dict:
    threading.Thread(target=srv.shutdown, daemon=True).start()
    return {"ok": True}


def _nonce(data) -> str:
    n = str(data.get("nonce", ""))
    if not NONCE_RE.fullmatch(n):
        raise PageError("no such invitation")
    return n


ROUTES = {
    ("GET", "ping"): lambda srv, data: {"ok": True, "version": srv.cfg.version},
    ("GET", "state"): _state,
    ("POST", "quit"): _quit,
    ("POST", "update"): _update,
    ("POST", "invite"): lambda srv, data: {"ok": True, "code": make_invite(str(data.get("text", "")))},
    ("POST", "paste"): lambda srv, data: {"ok": True, **read_code(str(data.get("code", "")))},
    ("POST", "accept"): lambda srv, data: {"ok": True, "code": accept(_nonce(data))},
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

    def touch(self) -> None:
        self._last = time.time()

    def busy(self, n: int) -> None:
        with self._mx:
            self._busy += n
            self._last = time.time()

    def idle_watch(self) -> None:
        limit = _idle()
        while True:
            time.sleep(min(5.0, limit / 4))
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
    try:
        srv.serve_forever(poll_interval=0.2)
    finally:
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
        detach = ({"creationflags": 0x00000008 | 0x00000200 | 0x08000000} if os.name == "nt"
                  else {"start_new_session": True})
        try:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", "--no-open",
                              "--quiet", *argv_tail],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True, **detach)
        except OSError:
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
.friend .nm{display:flex;align-items:center;gap:8px}
.friend .nm .mono{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.st{font-size:12px;font-weight:600;padding:1px 8px;border-radius:999px;white-space:nowrap}
.st.ok{color:var(--ok);background:var(--ok-soft)} .st.wait{color:var(--turn-text);background:var(--turn);border:1px solid var(--turn-line)}
.field{display:flex;flex-direction:column;gap:4px;margin-bottom:10px;font-size:13px;color:var(--muted)}
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
  <span class="pill hide-sm"><span data-icon="lock"></span>this machine only</span>
  <span class="pill" id="ver-pill"></span>
</div></header>
<main class="wrap">
  <aside class="col left" id="left"></aside>
  <section class="col center" id="center"></section>
  <aside class="col right" id="right"></aside>
  <div class="foot">Served by Baton on 127.0.0.1. It stops by itself after 30 minutes without use.</div>
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
      ? "Your install's ID. Give it only to people you trust. It is a fingerprint of a key made on this machine; nothing is sent anywhere."
      : "The ID is made at a session start by ssh-keygen" + (S.keygen ? "." : ", which is not on this machine.")))));

  const fc = el("div.card", null, el("h2", null, icon("users"), "Friends", el("span.count.muted", null, String(S.friends.length))));
  if (!S.friends.length) fc.appendChild(el("div.small.muted", null, "No friends yet. Invite someone, or paste their invitation."));
  for (const f of S.friends) {
    const mutual = f.status === "mutual";
    const row = el("div.friend", null,
      el("div.nm", null, el("span.mono", {title: f.id}, f.id),
        el("span.st." + (mutual ? "ok" : "wait"), null, mutual ? "friends" : "waiting for them"),
        el("button.btn.sm", {type: "button", title: "Stops new things only; what they already have stays with them",
          on: {click: async () => { if (!confirm("Remove " + f.id + "? It stops new things only.")) return;
            const r = await api("remove", {id: f.id}); toast(r.ok ? "Removed" : r.error); refresh(); }}}, "Remove")));
    if (!mutual) {
      row.appendChild(el("div.small.muted", null, "You accepted. Friends once they paste your reply."));
      if (f.reply) row.appendChild(el("div", null, el("button.btn.sm", {type: "button", on: {click: () => copy(f.reply, "Reply")}}, icon("copy"), "Copy my reply again")));
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
  const msgIn = el("textarea", {maxlength: "140", placeholder: "Optional: who you are, in a sentence", "aria-label": "Short message"});
  const counter = el("span", null, "0 / 140");
  const result = el("div"), err = el("div.err"), list = el("div");
  msgIn.addEventListener("input", () => { counter.textContent = msgIn.value.length + " / 140"; });
  const create = el("button.btn.primary", {type: "button"}, icon("user"), "Invite a friend");
  create.addEventListener("click", async () => {
    err.textContent = ""; create.disabled = true;
    const r = await api("invite", {text: msgIn.value});
    create.disabled = false;
    if (!r.ok) { err.textContent = r.error; return; }
    msgIn.value = ""; counter.textContent = "0 / 140";
    result.replaceChildren(el("div.code", {title: "Invitation code"}, r.code),
      el("div.btns", null, el("button.btn", {type: "button", on: {click: () => copy(r.code, "Invitation")}}, icon("copy"), "Copy")),
      el("div.note", null, icon("info"), el("span", null, "Send it to them yourself: a message, a mail, in person. Baton sends nothing. When they accept, paste their reply below.")));
    refresh();
  });
  keep.drawInvites = () => {
    list.replaceChildren();
    for (const v of S.invites) list.appendChild(el("div.pending", null,
      el("div", null, "Waiting for a reply since " + (v.created || "").replace("T", " ").slice(0, 16) + (v.text ? ": " : ""), v.text ? el("span", null, v.text) : null),
      el("div.btns", null,
        el("button.btn.sm", {type: "button", on: {click: () => copy(v.code, "Invitation")}}, icon("copy"), "Copy again"),
        el("button.btn.sm", {type: "button", on: {click: async () => { await api("cancel", {nonce: v.nonce}); toast("Invitation cancelled"); refresh(); }}}, "Cancel"))));
  };
  keep.drawInvites();
  keep.invite = el("div.card", null, el("h2", null, icon("users"), "Invite a friend"),
    el("label.field", null, "Message (plain text, shown to them; Baton never puts it in their agent's context)", msgIn, el("div.hint", null, el("span", null, "Links are not clickable"), counter)),
    create, err, result, list);
  return keep.invite;
}

function pasteCard(){
  if (keep.paste) { keep.drawIncoming(); return keep.paste; }
  const codeIn = el("textarea.code-in", {placeholder: "-----BEGIN BATON INVITE----- ...", "aria-label": "Invitation or reply code", spellcheck: "false"});
  const err = el("div.err"), out = el("div"), list = el("div");
  const check = el("button.btn.primary", {type: "button"}, icon("check"), "Check");
  check.addEventListener("click", async () => {
    err.textContent = ""; out.replaceChildren(); check.disabled = true;
    const r = await api("paste", {code: codeIn.value});
    check.disabled = false;
    if (!r.ok) { err.textContent = r.error; return; }
    codeIn.value = "";
    if (r.kind === "accept") out.appendChild(el("div.okline", null, icon("check"), "You and " + r.id + " are friends now."));
    refresh();
  });
  keep.drawIncoming = () => {
    list.replaceChildren();
    for (const v of S.incoming) {
      const box = el("div.request", null,
        el("div", null, el("b", null, "Invitation from "), el("span.mono", null, v.id)),
        el("div.small.muted", null, "Signature checked against the key inside; the ID matches that key."));
      if (v.text) box.appendChild(el("blockquote.msg", null, v.text));
      const reply = el("div");
      box.appendChild(el("div.btns", null,
        el("button.btn.primary", {type: "button", on: {click: async () => {
          const r = await api("accept", {nonce: v.nonce});
          if (!r.ok) { toast(r.error); return; }
          out.replaceChildren(el("div.okline", null, icon("check"), "Accepted. Send this reply back to " + v.id + ":"),
            el("div.code", null, r.code),
            el("div.btns", null, el("button.btn", {type: "button", on: {click: () => copy(r.code, "Reply")}}, icon("copy"), "Copy")));
          refresh(); }}}, icon("check"), "Accept"),
        el("button.btn", {type: "button", on: {click: async () => { await api("ignore", {nonce: v.nonce}); toast("Ignored. They are not told."); refresh(); }}}, "Ignore")));
      box.appendChild(reply);
      list.appendChild(box);
    }
  };
  keep.drawIncoming();
  keep.paste = el("div.card", null, el("h2", null, icon("inbox"), "Paste an invitation or a reply"),
    el("label.field", null, "The code they sent you", codeIn), check, err, list, out,
    el("div.note", null, icon("info"), el("span", null, "An invitation's message is shown here; Baton never puts it in your agent's context. Ignore tells nobody.")));
  return keep.paste;
}

function renderRight(){
  const R = document.getElementById("right"); R.replaceChildren();
  R.appendChild(el("div.card.soon", null, el("h2", null, icon("book"), "Shared tasks"),
    el("div.small.muted", null, "Coming soon: tasks shared with friends, and their feed, on this page.")));
  const n = S.incoming.length;
  R.appendChild(el("div.card", null, el("h2", null, icon("eye"), "What my agent sees"),
    el("div.term", null, n ? n + " friend invitation" + (n === 1 ? "" : "s") + " waiting" : "(nothing from this page)"),
    el("div.note", null, icon("info"), el("span", null, "Counts only: never a message, never this page's link."))));
}

refresh();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
