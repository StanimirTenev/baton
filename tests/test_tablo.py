"""The board is a view of the logbooks, never a second source of truth.

The session-start hook already says all of this, but it says it as a wall of text
at the top of a conversation, where it is least readable. The board lays the same
state out. It reuses the hook's own parsing: two readers of one header that
disagree is a defect waiting to happen, and the board is the one that would be
believed, because it is prettier.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "baton_tablo.py"
spec = importlib.util.spec_from_file_location("baton_tablo", TOOL)
tablo = importlib.util.module_from_spec(spec)
sys.modules["baton_tablo"] = tablo
spec.loader.exec_module(tablo)

TODAY = date(2026, 9, 19)


def task(root: Path, name: str, header: str = "", extra: dict[str, str] | None = None) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    body = f"---\n{header}\n---\n\n## 2026-09-19 10:00 — entry\n" if header else "## entry\n"
    (folder / "LOGBOOK.md").write_text(body, encoding="utf-8")
    for filename, content in (extra or {}).items():
        (folder / filename).write_text(content, encoding="utf-8")
    return folder


def test_a_task_on_us_and_one_waiting_are_separated(tmp_path):
    task(tmp_path, "ours", "sastoyanie: aktivna\nna_hod: nie\nprioritet: visok")
    task(tmp_path, "theirs", "sastoyanie: chakashta\nna_hod: David")
    rows, _ = tablo.collect(tmp_path, "LOGBOOK.md")
    page = tablo.render(rows, tmp_path, TODAY)
    assert "На наш ход" in page and "Чакат външен" in page
    assert page.index("На наш ход") < page.index("Чакат външен")
    assert "чака: David" in page


def test_a_frozen_task_is_listed_but_not_offered(tmp_path):
    task(tmp_path, "parked", "sastoyanie: zamrazena\nna_hod: nie")
    page = tablo.render(*tablo.collect(tmp_path, "LOGBOOK.md")[:1], tmp_path, TODAY)
    assert "Замразени" in page
    assert "На наш ход" not in page


def test_a_shelf_life_warning_reaches_the_card(tmp_path):
    task(tmp_path, "stale",
         "sastoyanie: aktivna\nna_hod: nie\nvyarno_kum: 2026-08-01\npregled_sled: 30d")
    rows, _ = tablo.collect(tmp_path, "LOGBOOK.md")
    assert rows[0]["warnings"] and "закъснява" in rows[0]["warnings"][0]
    assert "срок на годност" in tablo.render(rows, tmp_path, TODAY)


def test_an_unretired_constraint_reaches_the_card(tmp_path):
    task(tmp_path, "t", "sastoyanie: aktivna\nna_hod: nie", {
        "OGRANICHENIYA.md": "| id | статус | файл | текст |\n|--|--|--|--|\n"
                            "| O1 | пада | X.md | a sentence long enough to find |\n",
        "X.md": "a sentence long enough to find, still here\n"})
    rows, _ = tablo.collect(tmp_path, "LOGBOOK.md")
    assert any("още стои" in w for w in rows[0]["warnings"])


def test_a_passed_deadline_is_marked_hot(tmp_path):
    task(tmp_path, "late", "sastoyanie: aktivna\nna_hod: nie\nvremevi_kriterii: srok:2026-09-01")
    rows, _ = tablo.collect(tmp_path, "LOGBOOK.md")
    page = tablo.render(rows, tmp_path, TODAY)
    assert "card hot" in page and "мина" in page


def test_a_task_without_a_header_still_appears(tmp_path):
    """A logbook nobody has given a header must not vanish from the board."""
    task(tmp_path, "plain")
    rows, _ = tablo.collect(tmp_path, "LOGBOOK.md")
    assert rows[0]["headerless"]
    assert "plain" in tablo.render(rows, tmp_path, TODAY)


def test_html_in_a_logbook_cannot_reach_the_page(tmp_path):
    """A logbook is written by hand and may contain anything at all."""
    task(tmp_path, "x", 'sastoyanie: aktivna\nna_hod: nie\nsledvashto: "<script>alert(1)</script>"')
    page = tablo.render(*tablo.collect(tmp_path, "LOGBOOK.md")[:1], tmp_path, TODAY)
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page


def test_an_empty_root_produces_no_page(tmp_path):
    rows, _ = tablo.collect(tmp_path, "LOGBOOK.md")
    assert rows == []


def test_the_board_says_it_is_generated_and_local(tmp_path):
    """It must never read as the record. The logbooks are."""
    task(tmp_path, "t", "sastoyanie: aktivna\nna_hod: nie")
    page = tablo.render(*tablo.collect(tmp_path, "LOGBOOK.md")[:1], tmp_path, TODAY)
    assert "Генерирано от дневниците" in page
    assert "Нищо не напуска машината" in page
