import pytest


@pytest.fixture(autouse=True)
def _baton_state_outside_the_repo(tmp_path, monkeypatch):
    """The Stop hook remembers logbook bodies next to itself by default. In a test that
    is the repository's hooks/ folder -- shared between tests and one `git add` from a
    commit. Every test gets its own."""
    monkeypatch.setenv("BATON_BODY_STATE", str(tmp_path / ".baton.bodies.json"))
