import json
from datetime import date

import re
from pathlib import Path

import pytest

_VERSION = re.search(r'BATON_VERSION = "([^"]+)"', (Path(__file__).resolve().parent.parent / "hooks" / "baton_session_start.py").read_text("utf-8")).group(1)


@pytest.fixture(autouse=True)
def _baton_state_outside_the_repo(tmp_path, monkeypatch):
    """The Stop hook remembers logbook bodies next to itself by default. In a test that
    is the repository's hooks/ folder -- shared between tests and one `git add` from a
    commit. Every test gets its own."""
    monkeypatch.setenv("BATON_BODY_STATE", str(tmp_path / ".baton.bodies.json"))
    # SessionStart remembers when it last checked for a newer version, the same way. Today's
    # question about the check, and the offer of an inventory, count as made, so neither appears
    # in every board a test compares; tests/test_update.py starts from an empty state.
    state = tmp_path / ".baton.state.json"
    today = date.today().isoformat()
    # The version seen counts as this one, so the note after an update is not in every board
    # either; tests/test_whats_new.py starts from its own states.
    # The page (v3.43.0) counts as opened for this version, so no session start in a test starts
    # its server; tests/test_page.py starts from its own states.
    state.write_text(json.dumps({"asked": today, "inventory_offered": today,
                                 "review_offered": today, "seen_version": _VERSION,
                                 "page_opened_version": _VERSION}), "utf-8")
    monkeypatch.setenv("BATON_SESSION_STATE", str(state))
    # Lesson counters (L1, L2) the same way: a test must not count into the real register.
    monkeypatch.setenv("BATON_LESSONS_STATE", str(tmp_path / ".baton.lessons.json"))
    # The memory lint's remembered lines (row 29), the same way.
    monkeypatch.setenv("BATON_MEMLINT_STATE", str(tmp_path / ".baton.memlint.json"))
    # The doctor reads the machine's managed settings (row 78): not this machine's, in a test.
    monkeypatch.setenv("BATON_MANAGED_DIR", str(tmp_path / ".managed"))
    # The ledger (row 153) is a git repository beside the hooks by default: not in this one.
    monkeypatch.setenv("BATON_LEDGER", str(tmp_path / ".baton.ledger"))
    # The install's key (v3.42.0): a test run made the developer's real one on 21.11.
    monkeypatch.setenv("BATON_IDENTITY", str(tmp_path / ".baton.identity"))
    # The page (v3.43.0): no server and no browser from a test, unless it asks for them. A hook
    # started with its environment built by hand loses these two, so there is no display either.
    monkeypatch.setenv("BATON_PAGE", "off")
    monkeypatch.setenv("BATON_NO_BROWSER", "1")
    # The box (v3.44.0): no test listens on the network or broadcasts; tests/test_box.py opens
    # its own on 127.0.0.1.
    monkeypatch.setenv("BATON_BOX", "off")
    for name in ("DISPLAY", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(name, raising=False)


_REAL_PAGE = Path.home() / ".claude" / "baton" / "baton.page.json"


def _page_servers(root):
    return [p for p in root.rglob("baton.page.json")] if root.exists() else []


def _real_page_mark():
    try:
        return _REAL_PAGE.stat().st_mtime_ns
    except OSError:
        return None


@pytest.fixture(autouse=True)
def _no_page_server_left(request, tmp_path):
    """A page server started by a test is stopped after it, and one a test did not ask for (no
    `page` mark) fails it: a listener left running is what this guards against."""
    before = _real_page_mark()
    yield
    import os
    import signal
    found = _page_servers(tmp_path)
    for path in found:
        try:
            pid = int(json.loads(path.read_text("utf-8"))["pid"])
            os.kill(pid, signal.SIGTERM if hasattr(signal, "SIGTERM") else 9)
        except Exception:
            pass
    assert _real_page_mark() == before, "a test touched the real ~/.claude/baton/baton.page.json"
    if found and request.node.get_closest_marker("page") is None:
        pytest.fail(f"a page server was started without the `page` mark: {found}")


def pytest_configure(config):
    config.addinivalue_line("markers", "page: the test starts Baton's page server on purpose")


# What a hook or script started by a test gets from the environment: what Python and a shell
# need to start (the Windows names too), and the state files pointed above at tmp_path. Each by
# name, never a copy of os.environ: a developer's environment can hold API keys and tokens, and
# no process under test needs them.
CHILD_ENV = ("PATH", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "SYSTEMROOT", "SYSTEMDRIVE",
             "WINDIR", "COMSPEC", "PATHEXT", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR",
             "LANG", "LC_ALL", "LC_CTYPE", "BATON_BODY_STATE", "BATON_SESSION_STATE",
             "BATON_LESSONS_STATE", "BATON_MEMLINT_STATE", "BATON_MANAGED_DIR", "BATON_LEDGER",
             "BATON_IDENTITY", "BATON_PAGE", "BATON_NO_BROWSER", "BATON_BOX", "BATON_BOX_UDP")


def child_env(**extra) -> dict:
    """The environment for a child process of a test: the names in CHILD_ENV, then `extra`."""
    import os
    env = {k: os.environ[k] for k in CHILD_ENV if k in os.environ}
    env.update(extra)
    return env
