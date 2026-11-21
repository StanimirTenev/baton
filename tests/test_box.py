"""The box (v3.44.0): an addressed invitation waits on the inviter's own machine, the friend's page
fetches it with a key proof and posts the reply back. tools/baton_page.py, both sides.

The inviter is a real page server (a subprocess, its box on 127.0.0.x and a free port); the
friend is the tool loaded here, or a second server. Every code is signed by the real ssh-keygen.
No broadcast leaves the machine: announcements go to 127.255.255.255 on a free UDP port.
"""
from __future__ import annotations

import base64
import http.client
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "baton_page.py"
HOOK = ROOT / "hooks" / "baton_session_start.py"

pytestmark = [pytest.mark.page,
              pytest.mark.skipif(not shutil.which("ssh-keygen"), reason="ssh-keygen is not here")]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VERSION = _load(HOOK, "bss_for_box_tests").BATON_VERSION


def _free(kind=socket.SOCK_STREAM):
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _env(tmp_path, name, box="off", udp=None):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home), "USERPROFILE": str(home),
           "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "BATON_IDENTITY": str(tmp_path / name / "identity"),
           "BATON_PAGE_IDLE": "60", "BATON_BOX": box, "BATON_BOX_UDP": str(udp or _free(socket.SOCK_DGRAM))}
    return env


class Page:
    """A page server of one install, reached by its key."""

    def __init__(self, tmp_path, name, box="off", udp=None):
        self.env = _env(tmp_path, name, box, udp)
        out = subprocess.run([sys.executable, str(TOOL), "--ensure", "--version", "9.9.9"],
                             capture_output=True, env=self.env, timeout=60)
        assert out.returncode == 0, out.stderr
        st = json.loads((tmp_path / name / "baton.page.json").read_text())
        self.port, self.ticket = st["port"], st["ticket"]

    def api(self, name, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": f"127.0.0.1:{self.port}", "X-Baton-Ticket": self.ticket}
        if body is not None:
            h["Content-Type"] = "application/json"
        conn.request("POST" if body is not None else "GET", "/api/" + name,
                     body=json.dumps(body) if body is not None else None, headers=h)
        got = json.loads(conn.getresponse().read())
        conn.close()
        return got


def _post(host, port, path, body=None, raw=None, method="POST", headers=None):
    conn = http.client.HTTPConnection(host, port, timeout=30)
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    conn.request(method, path, body=data, headers=dict({"Content-Type": "application/json"}, **(headers or {})))
    resp = conn.getresponse()
    out = resp.status, resp.read()
    conn.close()
    try:
        return out[0], json.loads(out[1] or b"{}")
    except ValueError:
        return out[0], {"raw": out[1]}


def _closed(host, port):
    try:
        socket.create_connection((host, port), timeout=2).close()
        return False
    except OSError:
        return True


@pytest.fixture
def page(monkeypatch, tmp_path):
    """The tool, loaded here: `use("b")` makes it install b."""
    mod = _load(TOOL, "baton_page_for_box_tests")

    def use(name):
        monkeypatch.setenv("BATON_IDENTITY", str(tmp_path / name / "identity"))
        return mod.my_key()[0]
    mod.use = use
    return mod


@pytest.fixture
def inviter(tmp_path):
    """Install a, its page server running, its box (when open) on 127.0.0.2."""
    port = _free()
    a = Page(tmp_path, "a", box=f"127.0.0.2:{port}")
    a.box = ("127.0.0.2", port)
    a.id = a.api("state")["id"]
    return a


def _proof(page, t=None, ns=None):
    ident, pub, _ = page.my_key()
    t = int(time.time()) if t is None else t
    return {"id": ident, "pub": pub, "time": str(t),
            "sig": page.sign(f"baton-box\n{ident}\n{t}\n".encode(), ns or page.BOX_NS)}


def _parts(code):
    return json.loads(base64.b64decode("".join(code.strip().splitlines()[1:-1])))


def _repack(kind, outer):
    b64 = base64.b64encode(json.dumps(outer, separators=(",", ":")).encode()).decode()
    name = {"invite": "INVITE", "accept": "REPLY"}[kind]
    return f"-----BEGIN BATON {name}-----\n{b64}\n-----END BATON {name}-----\n"


# -- the box opens only while an addressed invitation waits ---------------------------------

def test_the_box_is_closed_until_an_addressed_invitation_waits(inviter, page):
    host, port = inviter.box
    assert inviter.api("state")["box"]["on"] is False and _closed(host, port)
    assert inviter.api("invite", {"text": "anyone"})["ok"]                  # a code to copy
    assert inviter.api("state")["box"]["on"] is False and _closed(host, port)
    bob = page.use("b")
    assert inviter.api("invite", {"text": "hi", "to": bob})["ok"]
    assert inviter.api("state")["box"]["on"] is True
    assert not _closed(host, port)
    for v in inviter.api("state")["invites"]:
        if v["to"]:
            inviter.api("cancel", {"nonce": v["nonce"]})
    assert inviter.api("state")["box"]["on"] is False and _closed(host, port)


def test_the_default_listens_on_the_network_and_off_means_never(page, monkeypatch):
    monkeypatch.delenv("BATON_BOX", raising=False)
    assert page.box_bind() == ("0.0.0.0", 47800)
    for off in ("off", "nonsense", "example.com:1"):
        monkeypatch.setenv("BATON_BOX", off)
        assert page.box_bind() is None


def test_the_page_and_its_buttons_are_not_on_the_box(inviter, page):
    inviter.api("invite", {"text": "hi", "to": page.use("b")})
    host, port = inviter.box
    key = {"X-Baton-Ticket": inviter.ticket, "Host": f"127.0.0.1:{inviter.port}"}
    for method, path in (("GET", f"/{inviter.ticket}/"), ("GET", "/api/state"), ("POST", "/api/invite"),
                         ("POST", "/api/quit"), ("GET", "/box/v1/fetch"), ("POST", "/box/"), ("GET", "/")):
        status, got = _post(host, port, path, {"text": "x"} if method == "POST" else None,
                            method=method, headers=key)
        assert status == 404, (method, path, status)
        assert b"<html" not in json.dumps(got).encode()
    assert inviter.api("state")["ok"]                                          # still running


# -- fetch: only the holder of the key, only its own invitations ----------------------------

def test_a_fetch_gives_each_id_only_its_own_invitations(inviter, page):
    bob, cid, did = page.use("b"), page.use("c"), page.use("d")
    inviter.api("invite", {"text": "for b", "to": bob, "nick": "ZEBRA-NICK"})
    inviter.api("invite", {"text": "for c", "to": cid})
    inviter.api("invite", {"text": "for anyone"})
    host, port = inviter.box
    for who, ident, want in (("b", bob, "for b"), ("c", cid, "for c")):
        page.use(who)
        status, got = _post(host, port, "/box/v1/fetch", _proof(page))
        assert status == 200 and len(got["codes"]) == 1, got
        payload = json.loads(_parts(got["codes"][0])["m"])
        assert payload["to"] == ident and payload["text"] == want
        assert "ZEBRA" not in json.dumps(got)                                  # nicknames stay home
    page.use("d")
    assert _post(host, port, "/box/v1/fetch", _proof(page))[1]["codes"] == []
    assert did


def test_a_fetch_without_a_valid_proof_is_refused(inviter, page):
    bob = page.use("b")
    inviter.api("invite", {"text": "hi", "to": bob})
    host, port = inviter.box
    fetch = lambda body: _post(host, port, "/box/v1/fetch", body)[0]       # noqa: E731
    assert fetch({}) == 400
    assert fetch({"id": bob}) == 400
    page.use("c")
    assert fetch(dict(_proof(page), id=bob)) == 403                         # c's proof, b's ID
    t = int(time.time())
    _, cpub, _ = page.my_key()
    claim = {"id": bob, "pub": cpub, "time": str(t),                        # c's key signs for b's ID
             "sig": page.sign(f"baton-box\n{bob}\n{t}\n".encode(), page.BOX_NS)}
    status, got = _post(host, port, "/box/v1/fetch", claim)
    assert status == 403 and "ID" in got["error"], got
    page.use("b")
    good = _proof(page)
    page.use("c")
    assert fetch(dict(good, sig=_proof(page, int(good["time"]))["sig"])) == 403   # b's key, c's signature
    page.use("b")
    assert fetch(_proof(page, ns=page.NAMESPACE)) == 403                    # a real signature, another namespace
    assert fetch(_proof(page, int(time.time()) - 400)) == 403              # old
    assert fetch(_proof(page, int(time.time()) + 400)) == 403              # from the future
    once = _proof(page, int(time.time()) + 30)
    assert fetch(once) == 200
    assert fetch(once) == 403                                               # replayed
    assert fetch(_proof(page, int(time.time()))) == 403                     # older than the last used


# -- reply: only a reply that answers an invitation waiting here, from its addressee --------

def test_a_reply_is_kept_only_if_it_answers_an_invitation_waiting_here(inviter, page, tmp_path):
    bob, cid = page.use("b"), page.use("c")
    inviter.api("invite", {"text": "hi", "to": bob})
    host, port = inviter.box
    page.use("b")
    got = page.fetch_from(inviter.id, host, port)
    assert got == {"invites": 1, "refused": 0}
    nonce = page.friends_view()["incoming"][0]["nonce"]
    reply = page.accept(nonce)
    outer = _parts(reply)
    tampered = _repack("accept", dict(outer, m=outer["m"].replace(bob, cid)))
    assert _post(host, port, "/box/v1/reply", {"code": tampered})[0] == 403
    assert _post(host, port, "/box/v1/reply", {"code": "junk"})[0] == 403
    assert _post(host, port, "/box/v1/reply", {"code": "A" * 9000})[0] == 400
    assert _post(host, port, "/box/v1/reply", raw=b"{" + b" " * 20000 + b"}")[0] == 413
    page.use("c")                                                           # c answers b's invitation
    payload = json.loads(outer["m"])
    _, cpub, _ = page.my_key()
    payload.update(id=cid, pub=cpub)
    msg = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    assert _post(host, port, "/box/v1/reply", {"code": _repack("accept", {"m": msg.decode(), "s": page.sign(msg)})})[0] == 403
    inv = inviter.api("state")["invites"]
    assert len(inv) == 1, "a refused reply used the invitation up"
    page.use("b")
    other = page.make_invite("an invitation is not a reply", to=inviter.id)
    assert _post(host, port, "/box/v1/reply", {"code": other})[0] == 400
    assert _post(host, port, "/box/v1/reply", {"code": reply})[0] == 200
    assert [(f["id"], f["status"]) for f in inviter.api("state")["friends"]] == [(bob, "mutual")]
    assert inviter.api("state")["box"]["on"] is False and _closed(host, port)   # nothing waits: closed


def test_too_many_requests_from_one_address_or_for_one_id(inviter, page):
    inviter.api("invite", {"text": "hi", "to": page.use("b")})
    host, port = inviter.box
    for _ in range(10):
        assert _post(host, port, "/box/v1/fetch", page._proof())[0] == 200   # each a later time
    assert _post(host, port, "/box/v1/fetch", page._proof())[0] == 429       # 10 a minute for one ID
    codes = [_post(host, port, "/box/v1/fetch", {})[0] for _ in range(25)]
    assert codes == [400] * 19 + [429] * 6                                   # 30 a minute from one address


# -- the friend's side: the page trusts no box ----------------------------------------------

class _Liar(BaseHTTPRequestHandler):
    codes: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        data = json.dumps({"ok": True, "codes": type(self).codes}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_the_page_does_not_trust_a_box(page):
    bob, cid = page.use("b"), page.use("c")
    alice = page.use("a")
    outer = _parts(page.make_invite("meet at noon", to=bob))
    tampered = _repack("invite", dict(outer, m=outer["m"].replace("noon", "nine")))
    for_c = page.make_invite("for c", to=cid)
    page.use("c")
    from_c = page.make_invite("c pretends to be a", to=bob)
    _Liar.codes = [tampered, for_c, from_c, "junk", 7]
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Liar)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        page.use("b")
        assert page.fetch_from(alice, "127.0.0.1", srv.server_port) == {"invites": 0, "refused": 5}
        assert page.friends_view()["incoming"] == []
    finally:
        srv.shutdown()
        srv.server_close()


def test_announcements_are_read_strictly(page):
    ident = "BTN-AAAA-BBBB-CCCC"
    good = json.dumps({"baton": "box", "v": 1, "id": ident, "port": 47800}).encode()
    assert page.parse_announce(good, "10.0.0.5") == (ident, "10.0.0.5", 47800)
    for bad in (b"", b"x" * 600, b"[]", json.dumps({"baton": "box", "id": "BTN-X", "port": 1}).encode(),
                json.dumps({"baton": "box", "id": ident, "port": "47800"}).encode(),
                json.dumps({"baton": "box", "id": ident, "port": 70000}).encode(),
                json.dumps({"baton": "other", "id": ident, "port": 1}).encode(), b"\xff\xfe"):
        assert page.parse_announce(bad, "10.0.0.5") is None


# -- by a messenger: WhatsApp, mail, the clipboard ------------------------------------------

def test_a_code_is_found_in_whatever_the_messenger_pasted_around_it(page):
    page.use("a")
    code = page.make_invite("hi from Ana")
    page.use("b")
    body = code.strip().splitlines()
    noisy = [
        "[21/11/2026, 10:15] Ana: BTN-X invites you to be friends on Baton \u2014 paste this into your Baton page:\r\n\r\n"
        + "\r\n".join(body) + "\r\n[21/11/2026, 10:16] Ana: did it work?",
        "On Sat, Ana wrote:\n" + "\n".join("> " + l for l in body) + "\n> \n",   # a mail's quote
        "\n\n" + "\n".join("   " + l + "  " for l in body) + "\n\nsee you\n",
        " ".join(body),                                                        # lines run together
    ]
    for text in noisy:
        got = page.read_code(text)
        assert got["kind"] == "invite" and got["text"] == "hi from Ana"


def test_the_messenger_links_carry_the_line_and_the_code_and_no_nickname(page):
    import urllib.parse
    bob = page.use("b")
    alice = page.use("a")
    code = page.make_invite("hi & bye + more?", to=bob, nick="ZEBRA-NICK")
    sh = page.share_links("invite", code)
    assert sh["text"].startswith(f"{alice} invites you to be friends on Baton") and sh["text"].endswith(code)
    assert sh["whatsapp"].startswith("https://wa.me/?text=")
    wa = sh["whatsapp"][len("https://wa.me/?text="):]
    assert all(c not in wa for c in "&+=\n /#?") and urllib.parse.unquote(wa) == sh["text"]
    assert len(sh["whatsapp"]) < 2000, len(sh["whatsapp"])
    mail = urllib.parse.urlsplit(sh["email"])
    q = urllib.parse.parse_qs(mail.query)
    assert mail.scheme == "mailto" and q["body"] == [sh["text"]] and q["subject"] == ["Baton: an invitation"]
    assert "ZEBRA" not in json.dumps(sh)
    page.use("b")
    reply = page.accept(page.read_code(sh["text"])["nonce"])                # the whole message pasted
    assert page.share_links("accept", reply)["text"].startswith(f"{bob} accepted your Baton invitation")


def test_a_pasted_invitation_for_another_install_is_refused_and_old_codes_still_read(page):
    bob = page.use("b")
    page.use("c")
    page.use("a")
    addressed = page.make_invite("for b", to=bob)
    old = page.make_invite("old style")
    assert json.loads(_parts(old)["m"])["v"] == 1 and "to" not in json.loads(_parts(old)["m"])
    page.use("c")
    with pytest.raises(page.PageError, match="another Baton"):
        page.read_code(addressed)
    assert page.read_code(old)["kind"] == "invite"
    page.use("b")
    assert page.read_code(addressed)["kind"] == "invite"


def test_nicknames_are_plain_short_text_and_editable(page):
    bob = page.use("b")
    alice = page.use("a")
    with pytest.raises(page.PageError, match="40"):
        page.make_invite("hi", to=bob, nick="x" * 41)
    code = page.make_invite("hi", to=bob, nick="Bo\x1b[31mb‮")
    assert page.friends_view()["invites"][0]["nick"] == "Bob"
    page.use("b")
    page.accept(page.read_code(code)["nonce"], nick="Ana")
    assert page.friends_view()["friends"][0]["nick"] == "Ana"
    page.set_nick("Ana K.", ident=alice)
    assert page.friends_view()["friends"][0]["nick"] == "Ana K."
    with pytest.raises(page.PageError):
        page.set_nick("y" * 41, ident=alice)
    with pytest.raises(page.PageError):
        page.set_nick("z", ident="BTN-AAAA-AAAA-AAAA")


def test_a_nickname_never_reaches_the_agent(page, tmp_path):
    bob = page.use("b")
    page.use("a")
    page.make_invite("hi", to=bob, nick="ZEBRA-WAITING")
    page.use("b")
    page.use("a")
    other = page.make_invite("x")
    page.use("b")
    page.accept(page.read_code(other)["nonce"], nick="ZEBRA-FRIEND")
    for who in ("a", "b"):
        env = _env(tmp_path, who)
        env["BATON_BOX"] = "off"
        state = tmp_path / f"{who}.state.json"                             # the page counts as opened:
        state.write_text(json.dumps({"page_opened_version": VERSION, "seen_version": VERSION}))  # no server
        env.update(BATON_HOME=str(tmp_path / "tasks"), BATON_SESSION_STATE=str(state))
        out = subprocess.run([sys.executable, str(HOOK)], input=b'{"source":"startup"}',
                             capture_output=True, env=env, timeout=60)
        assert out.returncode == 0, out.stderr
        assert b"ZEBRA" not in out.stdout + out.stderr
        assert b"wa.me" not in out.stdout and b"mailto" not in out.stdout     # the share buttons are the human's
        if who == "a":
            assert "invitation" in json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]


# -- the whole way, two page servers --------------------------------------------------------

def test_on_one_network_invite_shows_up_accept_and_both_are_friends_with_nicknames(tmp_path):
    udp = _free(socket.SOCK_DGRAM)
    port = _free()
    a = Page(tmp_path, "a", box=f"127.0.0.2:{port}", udp=udp)
    b = Page(tmp_path, "b", udp=udp)
    bob = b.api("state")["id"]
    b.api("watch", {})                                                     # the page is open: it listens
    a.api("invite", {"text": "nearby", "to": bob, "nick": "Bobby"})
    end = time.time() + 20
    while time.time() < end and not b.api("watch", {})["incoming"]:
        time.sleep(0.5)
    st = b.api("watch", {})
    assert [v["text"] for v in st["incoming"]] == ["nearby"], st["box"]
    assert a.api("state")["id"] in st["box"]["nearby"]
    out = b.api("accept", {"nonce": st["incoming"][0]["nonce"], "nick": "Ana"})
    assert out["ok"] and out["sent"] is True, out
    assert out["share"]["whatsapp"].startswith("https://wa.me/?text=")
    assert [(f["id"], f["status"], f["nick"]) for f in b.api("state")["friends"]] == [(a.api("state")["id"], "mutual", "Ana")]
    got = a.api("state")
    assert [(f["id"], f["status"], f["nick"]) for f in got["friends"]] == [(bob, "mutual", "Bobby")]
    assert got["invites"] == [] and got["box"]["on"] is False
