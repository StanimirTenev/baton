"""Skills a task says it needs: named in the header, checked by the hook.

A task folder carries state and history. It does not carry competence — the way a
thing is done here, as opposed to what was done and what is true. That knowledge
ends up scattered through logbook entries and is re-derived by whoever reads them
next, or not derived at all.

So the header names the skills, and this checks the naming stays honest. Two
failures, and the second is the dangerous one: a missing skill is loud and nothing
loads, while a stale skill is quiet and gets read with confidence. A skill written
once and re-read fifty times is exactly where knowledge goes out of date without
anyone noticing.

Nothing here fetches, updates or adopts anything. The hook reports; the human
decides. That matters more for skills than for anything else Baton touches,
because a skill is instructions, and instructions fail silently where code fails
loudly.
"""

import importlib.util
import os
import sys
import time
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_session_start.py"
spec = importlib.util.spec_from_file_location("bss", HOOK)
bss = importlib.util.module_from_spec(spec)
sys.modules["bss"] = bss
spec.loader.exec_module(bss)

LOGBOOK = "DNEVNIK.md"


def _aged(path: Path, days_ago: int) -> None:
    when = time.time() - days_ago * 86400
    os.utime(path, (when, when))


def _skill(root: Path, name: str, days_ago: int = 0) -> None:
    folder = root / name
    folder.mkdir(parents=True)
    skill = folder / "SKILL.md"
    skill.write_text("---\nname: x\n---\n", encoding="utf-8")
    _aged(skill, days_ago)


def _task(tmp_path: Path, book_days_ago: int = 0) -> Path:
    folder = tmp_path / "zadacha"
    folder.mkdir()
    book = folder / LOGBOOK
    book.write_text("## entry\n", encoding="utf-8")
    _aged(book, book_days_ago)
    return folder


# --- what the header says it needs -------------------------------------------

def test_a_list_is_read():
    assert bss.skills_for({"umeniya": ["a", "b"]}) == ["a", "b"]


def test_a_bare_string_is_read_as_a_list():
    assert bss.skills_for({"umeniya": "a, b"}) == ["a", "b"]


def test_the_english_spelling_works_too():
    assert bss.skills_for({"skills": ["a"]}) == ["a"]


def test_no_skills_named_is_not_an_error():
    assert bss.skills_for({}) == []
    assert bss.skills_for({"umeniya": ""}) == []


# --- what the hook does about it ---------------------------------------------

def test_a_named_skill_that_exists_and_is_current_is_quiet(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    _skill(root, "komentar", days_ago=0)
    monkeypatch.setenv("BATON_SKILLS", str(root))
    folder = _task(tmp_path)
    assert bss.skill_trouble(["komentar"], folder, LOGBOOK) == []


def test_a_missing_skill_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("BATON_SKILLS", str(tmp_path / "skills"))
    folder = _task(tmp_path)
    out = bss.skill_trouble(["komentar"], folder, LOGBOOK)
    assert len(out) == 1 and "ЛИПСВА" in out[0]


def test_a_skill_older_than_the_logbook_is_reported(tmp_path, monkeypatch):
    """The quiet one. Work was recorded after this skill was last written, so what
    it teaches may already have been superseded by what the logbook now says."""
    root = tmp_path / "skills"
    _skill(root, "komentar", days_ago=5)
    monkeypatch.setenv("BATON_SKILLS", str(root))
    folder = _task(tmp_path, book_days_ago=0)
    out = bss.skill_trouble(["komentar"], folder, LOGBOOK)
    assert len(out) == 1 and "ЛИПСВА" not in out[0]


def test_a_skill_newer_than_the_logbook_is_quiet(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    _skill(root, "komentar", days_ago=0)
    monkeypatch.setenv("BATON_SKILLS", str(root))
    folder = _task(tmp_path, book_days_ago=5)
    assert bss.skill_trouble(["komentar"], folder, LOGBOOK) == []


def test_each_named_skill_is_judged_separately(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    _skill(root, "fresh", days_ago=0)
    _skill(root, "old", days_ago=9)
    monkeypatch.setenv("BATON_SKILLS", str(root))
    folder = _task(tmp_path)
    out = bss.skill_trouble(["fresh", "old", "gone"], folder, LOGBOOK)
    assert len(out) == 2
    assert any("old" in o and "ЛИПСВА" not in o for o in out)
    assert any("gone" in o and "ЛИПСВА" in o for o in out)


def test_naming_nothing_checks_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("BATON_SKILLS", str(tmp_path / "skills"))
    assert bss.skill_trouble([], _task(tmp_path), LOGBOOK) == []


def test_a_missing_logbook_reports_nothing(tmp_path, monkeypatch):
    """No logbook, no date to compare against. Silence is the honest answer."""
    monkeypatch.setenv("BATON_SKILLS", str(tmp_path / "skills"))
    folder = tmp_path / "prazna"
    folder.mkdir()
    assert bss.skill_trouble(["komentar"], folder, LOGBOOK) == []


def test_the_line_names_the_skills_without_loading_them(tmp_path):
    """The header names; the agent loads. The hook never reaches into the session."""
    line = bss.line_for("zadacha", {"umeniya": ["komentar"], "sledvashto": "нещо"})
    assert "умения: komentar" in line
