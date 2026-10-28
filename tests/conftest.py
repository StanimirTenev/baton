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
    state.write_text(json.dumps({"asked": today, "inventory_offered": today,
                                 "review_offered": today, "seen_version": _VERSION}), "utf-8")
    monkeypatch.setenv("BATON_SESSION_STATE", str(state))
    # Lesson counters (L1, L2) the same way: a test must not count into the real register.
    monkeypatch.setenv("BATON_LESSONS_STATE", str(tmp_path / ".baton.lessons.json"))
    # The memory lint's remembered lines (row 29), the same way.
    monkeypatch.setenv("BATON_MEMLINT_STATE", str(tmp_path / ".baton.memlint.json"))
    # The doctor reads the machine's managed settings (row 78): not this machine's, in a test.
    monkeypatch.setenv("BATON_MANAGED_DIR", str(tmp_path / ".managed"))


# What a hook or script started by a test gets from the environment: what Python and a shell
# need to start (the Windows names too), and the state files pointed above at tmp_path. Each by
# name, never a copy of os.environ: a developer's environment can hold API keys and tokens, and
# no process under test needs them.
CHILD_ENV = ("PATH", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "SYSTEMROOT", "SYSTEMDRIVE",
             "WINDIR", "COMSPEC", "PATHEXT", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR",
             "LANG", "LC_ALL", "LC_CTYPE", "BATON_BODY_STATE", "BATON_SESSION_STATE",
             "BATON_LESSONS_STATE", "BATON_MEMLINT_STATE", "BATON_MANAGED_DIR")


def child_env(**extra) -> dict:
    """The environment for a child process of a test: the names in CHILD_ENV, then `extra`."""
    import os
    env = {k: os.environ[k] for k in CHILD_ENV if k in os.environ}
    env.update(extra)
    return env
