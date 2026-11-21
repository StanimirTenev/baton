"""The page (v3.43.0): tools/baton_page.py on 127.0.0.1, opened once per version by SessionStart.

Run as the harness runs the hook: a subprocess, its stdout parsed as JSON. The browser is a stub
named by BATON_OPENER that writes the link it was given to a file; no real browser is started,
and every server a test starts is stopped by conftest after it.
"""
from __future__ import annotations

import base64
import concurrent.futures
import http.client
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_session_start.py"
TOOL = ROOT / "tools" / "baton_page.py"

pytestmark = pytest.mark.page
needs_keygen = pytest.mark.skipif(not shutil.which("ssh-keygen"), reason="ssh-keygen is not here")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VERSION = _load(HOOK, "bss_for_page_tests").BATON_VERSION


def _opener(tmp_path, code=0):
    stub = tmp_path / f"opener{code}.py"
    stub.write_text("import sys\n"
                    f"open({str(tmp_path / 'opened.log')!r}, 'a').write(sys.argv[1] + '\\n')\n"
                    f"sys.exit({code})\n", "utf-8")
    return stub


def _opened(tmp_path):
    try:
        return (tmp_path / "opened.log").read_text("utf-8").split()
    except OSError:
        return []


def _base_env(tmp_path, **extra):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home), "USERPROFILE": str(home),
           "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
           "PROGRAMDATA": os.environ.get("PROGRAMDATA"), "BATON_IDENTITY": str(tmp_path / "identity"),
           "BATON_PAGE_IDLE": "60", "BATON_OPENER": str(_opener(tmp_path)), "BATON_BOX": "off"}
    env.update(extra)
    return {k: v for k, v in env.items() if v is not None}


def _hook(tmp_path, state=None, source="startup", tasks=True, **extra):
    root = tmp_path / "tasks"
    if tasks:
        (root / "t1").mkdir(parents=True, exist_ok=True)
        (root / "t1" / "LOGBOOK.md").write_text('---\nstate: active\nturn: "us"\nnext: "x"\n---\n', "utf-8")
    st = tmp_path / "state.json"
    if state is not None and not st.is_dir():
        st.write_text(json.dumps(state), "utf-8")
    env = _base_env(tmp_path, BATON_HOME=str(root), BATON_SESSION_STATE=str(st), **extra)
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"source": source}).encode(),
                         capture_output=True, env=env, timeout=60)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)                 # the hook's stdout is one JSON object, nothing else
    ctx = (got.get("hookSpecificOutput") or {}).get("additionalContext", "")
    assert "127.0.0.1" not in ctx, "the page's link reached the agent"
    return got, ctx


def _state(tmp_path):
    try:
        return json.loads((tmp_path / "state.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _page(tmp_path):
    return json.loads((tmp_path / "baton.page.json").read_text("utf-8"))


SHOWN = {"DISPLAY": ":0"} if sys.platform.startswith("linux") else {}


def test_a_fresh_install_opens_the_page_once(tmp_path):
    got, ctx = _hook(tmp_path, state=None, **SHOWN)
    assert len(_opened(tmp_path)) == 1
    url = _opened(tmp_path)[0]
    assert url.startswith("http://127.0.0.1:") and url == _page(tmp_path)["url"]
    assert _state(tmp_path)["page_opened_version"] == VERSION
    assert "page:" not in got["systemMessage"], "opened, so the line does not carry the link"
    again, _ = _hook(tmp_path, **SHOWN)
    assert len(_opened(tmp_path)) == 1, "opened twice for one version"
    assert "page:" not in again["systemMessage"]


def test_an_upgrade_opens_it_once_for_the_new_version(tmp_path):
    _hook(tmp_path, state={"seen_version": "3.41.0", "page_opened_version": "3.41.0"}, **SHOWN)
    assert len(_opened(tmp_path)) == 1
    assert _state(tmp_path)["page_opened_version"] == VERSION
    _hook(tmp_path, source="resume", **SHOWN)
    assert len(_opened(tmp_path)) == 1


def test_compact_and_clear_do_not_open_it(tmp_path):
    _hook(tmp_path, state={}, source="clear", **SHOWN)
    _hook(tmp_path, source="compact", **SHOWN)
    assert _opened(tmp_path) == []


@pytest.mark.parametrize("env", [
    {"SSH_CONNECTION": "10.0.0.1 5000 10.0.0.2 22", "DISPLAY": ":0"},
    {"SSH_TTY": "/dev/pts/3", "DISPLAY": ":0"},
    {"BATON_NO_BROWSER": "1", "DISPLAY": ":0"},
    {"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", "DISPLAY": ":0"},
    pytest.param({}, marks=pytest.mark.skipif(not sys.platform.startswith("linux"),
                                              reason="no display is a Linux test")),
], ids=["ssh", "ssh-tty", "opt-out", "sdk", "no-display"])
def test_no_browser_here_means_the_link_on_the_line_until_it_opens(tmp_path, env):
    got, ctx = _hook(tmp_path, state={}, **env)
    assert _opened(tmp_path) == []
    assert "page_opened_version" not in _state(tmp_path)
    url = _page(tmp_path)["url"]
    assert got["systemMessage"].endswith(" · 🆕 page: " + url)
    assert got["systemMessage"].startswith("🪪 This Baton's ID: BTN-")
    again, _ = _hook(tmp_path, **env)
    assert again["systemMessage"].endswith(url), "the link must stay until a real open"
    _hook(tmp_path, **SHOWN)                     # now with a browser: opened, and the link goes
    assert _opened(tmp_path) == [url]
    last, _ = _hook(tmp_path, **SHOWN)
    assert "page:" not in last["systemMessage"]


def test_a_launch_that_fails_does_not_count_as_opened(tmp_path):
    failing = _opener(tmp_path, code=1)
    got, _ = _hook(tmp_path, state={}, BATON_OPENER=str(failing), **SHOWN)
    assert len(_opened(tmp_path)) == 1                         # it was tried
    assert "page_opened_version" not in _state(tmp_path)
    assert "🆕 page: http://127.0.0.1:" in got["systemMessage"]
    missing, _ = _hook(tmp_path, BATON_OPENER=str(tmp_path / "no-such-opener"), **SHOWN)
    assert "page_opened_version" not in _state(tmp_path)
    assert "🆕 page:" in missing["systemMessage"]


def test_a_state_file_that_cannot_be_written_opens_nothing(tmp_path):
    (tmp_path / "state.json").mkdir()                          # read and write both fail
    got, _ = _hook(tmp_path, **SHOWN)
    assert _opened(tmp_path) == []
    assert "🆕 page:" in got["systemMessage"]


def test_switched_off_there_is_no_server_and_no_link(tmp_path):
    got, _ = _hook(tmp_path, state={}, BATON_PAGE="off", **SHOWN)
    assert _opened(tmp_path) == [] and not (tmp_path / "baton.page.json").exists()
    assert "page:" not in got["systemMessage"]


def test_without_task_folders_the_line_still_carries_the_link(tmp_path):
    got, ctx = _hook(tmp_path, state={}, tasks=False, BATON_NO_BROWSER="1")
    assert "🆕 page: http://127.0.0.1:" in got["systemMessage"]


# -- the server ------------------------------------------------------------------------------

def _ensure(tmp_path, *args, **extra):
    env = _base_env(tmp_path, **extra)
    out = subprocess.run([sys.executable, str(TOOL), "--ensure", "--version", "9.9.9", *args],
                         capture_output=True, env=env, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _req(port, method, path, headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Host": f"127.0.0.1:{port}"}
    h.update(headers or {})
    conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    for k, v in h.items():
        if v is not None:
            conn.putheader(k, v)
    data = json.dumps(body).encode() if body is not None else b""
    if body is not None:
        conn.putheader("Content-Length", str(len(data)))
    conn.endheaders(data if body is not None else None)
    resp = conn.getresponse()
    out = resp.status, resp.read()
    conn.close()
    return out


def _server(tmp_path, **extra):
    got = _ensure(tmp_path, **extra)
    st = _page(tmp_path)
    assert got["url"] == st["url"] and got["opened"] is False
    return st["port"], st["ticket"]


def test_the_page_answers_only_its_own_key_and_host(tmp_path):
    port, key = _server(tmp_path)
    status, body = _req(port, "GET", f"/{key}/")
    assert status == 200 and b"<title>Baton</title>" in body
    assert _req(port, "GET", f"/{'0' * 32}/")[0] == 404
    assert _req(port, "GET", "/")[0] == 404
    assert _req(port, "GET", f"/{key}/", {"Host": f"localhost:{port}"})[0] == 403
    assert _req(port, "GET", f"/{key}/", {"Host": f"evil.example:{port}"})[0] == 403
    assert _req(port, "GET", "/api/state")[0] == 403                  # no key header
    assert _req(port, "GET", "/api/state", {"X-Baton-Ticket": "0" * 32})[0] == 403
    status, body = _req(port, "GET", "/api/state", {"X-Baton-Ticket": key})
    assert status == 200 and json.loads(body)["version"] == "9.9.9"


def test_a_post_from_another_origin_is_refused(tmp_path):
    port, key = _server(tmp_path)
    ok = {"X-Baton-Ticket": key, "Content-Type": "application/json"}
    for origin in ("http://evil.example", "null", f"http://localhost:{port}", f"http://127.0.0.1:{port + 1}"):
        assert _req(port, "POST", "/api/ignore", dict(ok, Origin=origin), {"nonce": "0" * 32})[0] == 403
    assert _req(port, "POST", "/api/ignore", dict(ok, **{"Sec-Fetch-Site": "cross-site"}),
                {"nonce": "0" * 32})[0] == 403
    assert _req(port, "POST", "/api/ignore", {"Content-Type": "application/json"}, {"nonce": "0" * 32})[0] == 403
    assert _req(port, "POST", "/api/ignore", {"X-Baton-Ticket": key, "Content-Type": "text/plain"},
                {"nonce": "0" * 32})[0] == 415
    assert _req(port, "POST", "/api/ignore", dict(ok, Host=f"evil.example:{port}"), {"nonce": "0" * 32})[0] == 403
    assert _req(port, "OPTIONS", "/api/ignore", ok)[0] >= 400
    status, _ = _req(port, "POST", "/api/ignore", dict(ok, Origin=f"http://127.0.0.1:{port}"), {"nonce": "0" * 32})
    assert status == 200
    assert _req(port, "POST", "/api/ignore", ok, {"nonce": "0" * 32})[0] == 200   # no Origin: the key


def test_the_page_has_no_way_out_and_no_html_from_data(tmp_path):
    port, key = _server(tmp_path)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", f"/{key}/")
    resp = conn.getresponse()
    page = resp.read().decode()
    csp = resp.getheader("Content-Security-Policy")
    assert "default-src 'none'" in csp and "connect-src 'self'" in csp
    assert resp.getheader("Referrer-Policy") == "no-referrer"
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in page.replace("Never use innerHTML", "")
    assert "src=\"http" not in page and "href=\"http" not in page


@pytest.mark.skipif(os.name == "nt", reason="pgrep")
def test_sessions_starting_together_share_one_server(tmp_path):
    with concurrent.futures.ThreadPoolExecutor(6) as pool:
        urls = list(pool.map(lambda _: _ensure(tmp_path)["url"], range(6)))
    assert len(set(urls)) == 1, urls
    assert urls[0] == _page(tmp_path)["url"]
    time.sleep(0.5)
    found = subprocess.run(["pgrep", "-f", f"baton_page.py --serve --no-open --quiet --identity {tmp_path / 'identity'} "],
                           capture_output=True, text=True).stdout.split()
    assert found == [str(_page(tmp_path)["pid"])], found


def test_a_server_of_another_version_gives_way(tmp_path):
    first = _ensure(tmp_path)
    old = _page(tmp_path)
    env = _base_env(tmp_path)
    out = subprocess.run([sys.executable, str(TOOL), "--ensure", "--version", "9.9.10"],
                         capture_output=True, env=env, timeout=60)
    new = _page(tmp_path)
    assert json.loads(out.stdout)["url"] != first["url"] and new["version"] == "9.9.10"
    with pytest.raises(OSError):
        _req(old["port"], "GET", "/api/ping", {"X-Baton-Ticket": old["ticket"]})


def test_an_idle_server_stops_by_itself(tmp_path):
    port, key = _server(tmp_path, BATON_PAGE_IDLE="1")
    assert _req(port, "GET", "/api/ping", {"X-Baton-Ticket": key})[0] == 200
    end = time.time() + 15
    while time.time() < end and (tmp_path / "baton.page.json").exists():
        time.sleep(0.2)
    assert not (tmp_path / "baton.page.json").exists(), "still running after its idle time"
    with pytest.raises(OSError):
        _req(port, "GET", "/api/ping", {"X-Baton-Ticket": key})


def _fake_claude(tmp_path, code=0):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    exe = bindir / "claude"
    exe.write_text("#!/bin/sh\n"
                   f"echo \"$@\" >> {tmp_path / 'claude.log'}\necho done\nexit {code}\n", "utf-8")
    exe.chmod(0o755)
    return str(bindir) + os.pathsep + os.environ.get("PATH", "")


@pytest.mark.skipif(os.name == "nt", reason="a shell stub for claude")
def test_update_runs_claude_code_own_two_commands_on_a_click(tmp_path):
    path = _fake_claude(tmp_path)
    _ensure(tmp_path, "--kind", "plugin", "--catalog", "mycat", PATH=path)
    st = _page(tmp_path)
    assert not (tmp_path / "claude.log").exists(), "nothing runs before the click"
    status, body = _req(st["port"], "POST", "/api/update",
                        {"X-Baton-Ticket": st["ticket"], "Content-Type": "application/json"}, {})
    got = json.loads(body)
    assert status == 200 and got["ok"], got
    assert (tmp_path / "claude.log").read_text().splitlines() == [
        "plugin marketplace update mycat", "plugin update baton@mycat"]
    assert "Restart" in got["message"]


@pytest.mark.skipif(os.name == "nt", reason="a shell stub for claude")
def test_a_failed_marketplace_update_stops_and_says_what_to_run(tmp_path):
    path = _fake_claude(tmp_path, code=3)
    _ensure(tmp_path, "--kind", "plugin", "--catalog", "baton", PATH=path)
    st = _page(tmp_path)
    got = json.loads(_req(st["port"], "POST", "/api/update",
                          {"X-Baton-Ticket": st["ticket"], "Content-Type": "application/json"}, {})[1])
    assert not got["ok"] and len(got["steps"]) == 1 and "claude plugin update baton@baton" in got["manual"]


def test_another_install_is_shown_how_it_updates_and_nothing_runs(tmp_path):
    path = _fake_claude(tmp_path) if os.name != "nt" else os.environ.get("PATH", "")
    _ensure(tmp_path, "--kind", "script", "--how", "`cd /x && git pull && ./install.sh`", PATH=path)
    st = _page(tmp_path)
    got = json.loads(_req(st["port"], "POST", "/api/update",
                          {"X-Baton-Ticket": st["ticket"], "Content-Type": "application/json"}, {})[1])
    assert got == {"ok": False, "manual": "`cd /x && git pull && ./install.sh`"}
    assert not (tmp_path / "claude.log").exists()


def test_the_hook_tells_the_page_how_a_script_install_updates(tmp_path):
    _hook(tmp_path, state={}, BATON_NO_BROWSER="1")
    st = _page(tmp_path)
    got = json.loads(_req(st["port"], "GET", "/api/state", {"X-Baton-Ticket": st["ticket"]})[1])
    assert got["kind"] == "script" and "installer" in got["how"] and got["version"] == VERSION
    assert got["id"] and got["id"].startswith("BTN-")


# -- invitations -----------------------------------------------------------------------------

@pytest.fixture
def page(monkeypatch, tmp_path):
    """The tool, loaded here, with two installs: `use("a")` or `use("b")` switches between them."""
    mod = _load(TOOL, "baton_page_under_test")

    def use(name):
        monkeypatch.setenv("BATON_IDENTITY", str(tmp_path / name / "identity"))
        return mod.my_key()[0]
    mod.use = use
    return mod


def _parts(code):
    body = "".join(code.strip().splitlines()[1:-1])
    return json.loads(base64.b64decode(body))


def _repack(kind, outer):
    b64 = base64.b64encode(json.dumps(outer, separators=(",", ":")).encode()).decode()
    name = {"invite": "INVITE", "accept": "REPLY"}[kind]
    return f"-----BEGIN BATON {name}-----\n{b64}\n-----END BATON {name}-----\n"


@needs_keygen
def test_two_installs_become_friends_only_when_both_have_accepted(page):
    a = page.use("a")
    code = page.make_invite("Hi, it's Ana from the Sofia meeting")
    assert len(page.friends_view()["invites"]) == 1
    b = page.use("b")
    got = page.read_code(code)
    assert got == {"kind": "invite", "id": a, "nonce": got["nonce"], "text": "Hi, it's Ana from the Sofia meeting"}
    assert page.friends_view()["friends"] == []
    reply = page.accept(got["nonce"])
    view = page.friends_view()
    assert view["incoming"] == [] and [(f["id"], f["status"]) for f in view["friends"]] == [(a, "accepted-by-me")]
    page.use("a")
    assert page.read_code(reply) == {"kind": "accept", "id": b, "status": "mutual"}
    view = page.friends_view()
    assert [(f["id"], f["status"]) for f in view["friends"]] == [(b, "mutual")] and view["invites"] == []
    with pytest.raises(page.PageError, match="does not answer"):
        page.read_code(reply)                                  # one invitation, one reply
    page.remove(b)
    assert page.friends_view()["friends"] == []


@needs_keygen
def test_a_forged_signature_is_refused(page):
    page.use("a")
    outer = _parts(page.make_invite("x"))
    page.use("c")
    page.make_invite("y")                                      # c's key exists
    other = _parts(page.make_invite("x"))
    outer["s"] = other["s"]                                    # someone else's valid signature
    page.use("b")
    with pytest.raises(page.PageError, match="does not verify"):
        page.read_code(_repack("invite", outer))
    lines = outer["s"].split("\n")
    lines[2] = lines[2][:-4] + ("AAAA" if not lines[2].endswith("AAAA") else "BBBB")
    outer["s"] = "\n".join(lines)
    with pytest.raises(page.PageError):
        page.read_code(_repack("invite", outer))
    assert page.friends_view()["incoming"] == []


@needs_keygen
def test_tampered_text_is_refused(page):
    page.use("a")
    outer = _parts(page.make_invite("meet me at noon"))
    outer["m"] = outer["m"].replace("meet me at noon", "meet me at nine")
    page.use("b")
    with pytest.raises(page.PageError, match="does not verify"):
        page.read_code(_repack("invite", outer))


@needs_keygen
def test_an_id_that_is_not_the_key_inside_is_refused(page):
    a = page.use("a")
    b = page.use("b")
    page.use("a")
    outer = _parts(page.make_invite("hi"))
    payload = json.loads(outer["m"])
    payload["id"] = b                                          # claims b's ID with a's key
    message = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    outer = {"m": message.decode(), "s": page.sign(message)}   # and a real signature by a
    page.use("c")
    with pytest.raises(page.PageError):
        page.read_code(_repack("invite", outer))
    assert a != b


@needs_keygen
def test_a_signature_in_another_namespace_is_refused(page, tmp_path):
    page.use("a")
    outer = _parts(page.make_invite("hi"))
    message = outer["m"].encode()
    work = tmp_path / "ns"
    work.mkdir()
    (work / "msg").write_bytes(message)
    key = tmp_path / "a" / "identity" / "baton_ed25519"
    subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", "baton-entry", str(work / "msg")],
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=True)
    outer["s"] = (work / "msg.sig").read_text()
    page.use("b")
    with pytest.raises(page.PageError, match="does not verify"):
        page.read_code(_repack("invite", outer))


@needs_keygen
def test_a_reply_to_an_unknown_invitation_is_refused(page):
    page.use("a")
    code = page.make_invite("hi")
    page.use("b")
    reply = page.accept(page.read_code(code)["nonce"])
    page.use("c")                                              # c never invited b
    with pytest.raises(page.PageError, match="does not answer"):
        page.read_code(reply)
    page.use("a")
    page.cancel(page.friends_view()["invites"][0]["nonce"])    # cancelled: gone too
    with pytest.raises(page.PageError, match="does not answer"):
        page.read_code(reply)


@needs_keygen
def test_own_code_and_junk_are_refused(page):
    page.use("a")
    code = page.make_invite("hi")
    with pytest.raises(page.PageError, match="this install"):
        page.read_code(code)
    for junk in ("", "hello", "-----BEGIN BATON INVITE-----\n!!!\n-----END BATON INVITE-----",
                 code.replace("BATON INVITE", "BATON REPLY")):
        with pytest.raises(page.PageError):
            page.read_code(junk)
    with pytest.raises(page.PageError, match="140"):
        page.make_invite("x" * 141)


def test_text_from_someone_else_is_shown_as_plain_text(page):
    assert page.clean("hi\x1b[31m red\x1b[0m\u202eevil\u200b\nnext\x07") == "hi redevil next"


@needs_keygen
def test_the_invitation_text_never_reaches_the_agent(page, tmp_path):
    page.use("a")
    code = page.make_invite("ZEBRA-42 call me")
    page.use("b")
    page.read_code(code)                                       # pasted on b's page, undecided
    got, ctx = _hook(tmp_path / "b", state=None, BATON_IDENTITY=str(tmp_path / "b" / "identity"),
                     BATON_NO_BROWSER="1")
    out = json.dumps(got, ensure_ascii=False)
    assert "ZEBRA" not in out
    assert "1 friend invitation is waiting" in ctx
    assert "👥 1 invitation waiting" in got["systemMessage"]


@needs_keygen
def test_the_command_line_invites_and_accepts_without_printing_the_text(tmp_path):
    env_a = _base_env(tmp_path, BATON_IDENTITY=str(tmp_path / "a" / "identity"))
    env_b = _base_env(tmp_path, BATON_IDENTITY=str(tmp_path / "b" / "identity"))
    for env in (env_a, env_b):                                # each install makes its key
        subprocess.run([sys.executable, "-c", "import importlib.util as u, sys; s = u.spec_from_file_location"
                        "('h', sys.argv[1]); m = u.module_from_spec(s); s.loader.exec_module(m); m.own_id()",
                        str(HOOK)], env=env, check=True, timeout=60)

    def run(env, *args, stdin=None):
        return subprocess.run([sys.executable, str(TOOL), *args], input=stdin, capture_output=True,
                              text=True, env=env, timeout=60)
    inv = run(env_a, "--invite", "PRIVATE-NOTE-77")
    assert inv.returncode == 0 and inv.stdout.startswith("-----BEGIN BATON INVITE-----")
    acc = run(env_b, "--accept", "-", stdin=inv.stdout)
    assert acc.returncode == 0 and acc.stdout.startswith("-----BEGIN BATON REPLY-----")
    assert "PRIVATE-NOTE-77" not in acc.stdout + acc.stderr
    done = run(env_a, "--accept", acc.stdout)
    assert done.returncode == 0 and "friends now" in done.stdout


def test_as_a_plugin_the_page_has_the_button_and_the_catalog(tmp_path):
    home = tmp_path / "home"
    root = home / ".claude" / "plugins" / "cache" / "mycat" / "baton" / VERSION
    root.mkdir(parents=True)
    _hook(tmp_path, state={}, BATON_NO_BROWSER="1", CLAUDE_PLUGIN_ROOT=str(root),
          CLAUDE_PLUGIN_DATA=str(tmp_path / "data"))
    st = _page(tmp_path)
    got = json.loads(_req(st["port"], "GET", "/api/state", {"X-Baton-Ticket": st["ticket"]})[1])
    assert got["kind"] == "plugin" and got["catalog"] == "mycat"
    assert not any(x.startswith("Not checked") for x in got["leads"])


def test_opened_again_by_hand_it_still_knows_the_install(tmp_path):
    """--open has no --kind: what SessionStart said about the install is kept beside the state."""
    _ensure(tmp_path, "--kind", "plugin", "--catalog", "mycat")
    st = _page(tmp_path)
    _req(st["port"], "POST", "/api/quit", {"X-Baton-Ticket": st["ticket"], "Content-Type": "application/json"}, {})
    end = time.time() + 10
    while time.time() < end and (tmp_path / "baton.page.json").exists():
        time.sleep(0.1)
    out = subprocess.run([sys.executable, str(TOOL), "--open"], capture_output=True, text=True,
                         env=_base_env(tmp_path), timeout=60)
    assert out.returncode == 0 and "127.0.0.1" not in out.stdout, "the link must not be printed"
    assert len(_opened(tmp_path)) == 1
    st = _page(tmp_path)
    got = json.loads(_req(st["port"], "GET", "/api/state", {"X-Baton-Ticket": st["ticket"]})[1])
    assert got["kind"] == "plugin" and got["catalog"] == "mycat"


@pytest.mark.skipif(os.name == "nt", reason="SIGKILL")
def test_a_killed_server_leaves_a_state_file_that_is_not_believed(tmp_path):
    import signal
    first = _ensure(tmp_path)
    os.kill(_page(tmp_path)["pid"], signal.SIGKILL)
    time.sleep(0.3)
    assert (tmp_path / "baton.page.json").exists()           # left behind
    second = _ensure(tmp_path)
    assert second["url"] != first["url"]
    st = _page(tmp_path)
    assert _req(st["port"], "GET", "/api/ping", {"X-Baton-Ticket": st["ticket"]})[0] == 200


@needs_keygen
def test_a_code_carried_by_mail_or_chat_still_reads(page):
    page.use("a")
    code = page.make_invite("hi")
    page.use("b")
    mangled = ("Hey, here is my code:\r\n\r\n" + "\r\n".join("    " + l for l in code.splitlines())
               + "\r\n\r\nsee you")
    assert page.read_code(mangled)["kind"] == "invite"


@needs_keygen
def test_an_inviter_waiting_for_a_reply_is_told_how_to_reopen_the_page(page, tmp_path):
    page.use("a")
    page.make_invite("ZEBRA-7")
    got, ctx = _hook(tmp_path / "a", state={"page_opened_version": VERSION},
                     BATON_IDENTITY=str(tmp_path / "a" / "identity"))
    assert "--open" in ctx and "ZEBRA" not in json.dumps(got, ensure_ascii=False)
    assert "invitation" not in got["systemMessage"]


def test_page_env_carries_programdata(monkeypatch):
    """Windows ssh-keygen exits 255 without PROGRAMDATA: a page started by the hook could not sign
    or check a code (21.11, found on Windows; Linux does not need it, so it is pinned here)."""
    sys.path.insert(0, str(HOOK.parent))
    import _baton
    assert "PROGRAMDATA" in _baton.PAGE_ENV
    monkeypatch.setenv("PROGRAMDATA", "C:\\ProgramData")
    out = _baton.run_page([sys.executable, "-c", "import os; print(os.environ.get('PROGRAMDATA'))"])
    assert out.decode().strip() == "C:\\ProgramData"
