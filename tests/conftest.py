import json
from datetime import date

import pytest


@pytest.fixture(autouse=True)
def _baton_state_outside_the_repo(tmp_path, monkeypatch):
    """The Stop hook remembers logbook bodies next to itself by default. In a test that
    is the repository's hooks/ folder -- shared between tests and one `git add` from a
    commit. Every test gets its own."""
    monkeypatch.setenv("BATON_BODY_STATE", str(tmp_path / ".baton.bodies.json"))
    # SessionStart remembers when it last checked for a newer version, the same way. Today's
    # question about the check counts as asked, so it does not appear in every board a test
    # compares; tests/test_update.py starts from an empty state.
    state = tmp_path / ".baton.state.json"
    state.write_text(json.dumps({"asked": date.today().isoformat()}), "utf-8")
    monkeypatch.setenv("BATON_SESSION_STATE", str(state))
