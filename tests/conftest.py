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
