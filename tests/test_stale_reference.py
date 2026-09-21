"""A pointer sending you to a file that has not moved since the work did.

The failure this guards is the mirror of the one the Stop hook already covers.
Stop catches a folder with files newer than its logbook -- work done and not
recorded. This catches a decisions file *older* than the logbook: recorded work
that the decisions file has not been reconciled with.

The real case: a negative corpus asked for in one task's decisions file was built
two days later in a different task's folder and shipped in a release. The question
stayed open where it had been asked, the pointer quoted it at the top of every
session, and it was handed back as unfinished work three sessions running.
"""

import importlib.util
import os
import sys
import time
from datetime import date, timedelta
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


def _folder(tmp_path: Path, *, book_days_ago: int = 0, **files: int) -> Path:
    folder = tmp_path / "zadacha"
    folder.mkdir()
    book = folder / LOGBOOK
    book.write_text("## entry\n", encoding="utf-8")
    _aged(book, book_days_ago)
    for name, days_ago in files.items():
        target = folder / name.replace("_", ".")
        target.write_text("questions\n", encoding="utf-8")
        _aged(target, days_ago)
    return folder


def test_a_file_older_than_the_logbook_is_reported(tmp_path):
    folder = _folder(tmp_path, book_days_ago=0, DARVO_md=3)
    out = bss.stale_reference(folder, LOGBOOK, {"sledvashto": "чакат 5 решения (DARVO.md)"})
    assert len(out) == 1
    assert "DARVO.md" in out[0]


def test_a_file_touched_with_the_logbook_is_not_reported(tmp_path):
    folder = _folder(tmp_path, book_days_ago=0, DARVO_md=0)
    assert bss.stale_reference(folder, LOGBOOK, {"sledvashto": "виж DARVO.md"}) == []


def test_a_file_newer_than_the_logbook_is_not_reported(tmp_path):
    """That direction is the Stop hook's job, and it says something different."""
    folder = _folder(tmp_path, book_days_ago=3, DARVO_md=0)
    assert bss.stale_reference(folder, LOGBOOK, {"sledvashto": "виж DARVO.md"}) == []


def test_a_name_that_is_not_a_file_here_is_left_alone(tmp_path):
    """The pointer may name the memory index or a document elsewhere. A hook that
    cannot check something must not imply that it did."""
    folder = _folder(tmp_path, book_days_ago=0)
    assert bss.stale_reference(folder, LOGBOOK, {"sledvashto": "сверѝ с MEMORY.md"}) == []


def test_the_logbook_naming_itself_is_not_a_reference(tmp_path):
    folder = _folder(tmp_path, book_days_ago=0)
    assert bss.stale_reference(folder, LOGBOOK, {"sledvashto": f"виж {LOGBOOK}"}) == []


def test_an_empty_pointer_reports_nothing(tmp_path):
    folder = _folder(tmp_path, book_days_ago=0, DARVO_md=9)
    assert bss.stale_reference(folder, LOGBOOK, {}) == []
    assert bss.stale_reference(folder, LOGBOOK, {"sledvashto": ""}) == []


def test_a_backticked_name_is_found(tmp_path):
    folder = _folder(tmp_path, book_days_ago=0, PLAN_md=2)
    out = bss.stale_reference(folder, LOGBOOK, {"sledvashto": "изпълнявай `PLAN.md`"})
    assert len(out) == 1 and "PLAN.md" in out[0]


def test_several_named_files_are_each_checked(tmp_path):
    folder = _folder(tmp_path, book_days_ago=0, DARVO_md=4, FAKTI_md=0)
    out = bss.stale_reference(folder, LOGBOOK, {"sledvashto": "DARVO.md + FAKTI.md"})
    assert len(out) == 1 and "DARVO.md" in out[0]


def test_a_missing_logbook_reports_nothing(tmp_path):
    folder = tmp_path / "prazna"
    folder.mkdir()
    (folder / "DARVO.md").write_text("x", encoding="utf-8")
    assert bss.stale_reference(folder, LOGBOOK, {"sledvashto": "DARVO.md"}) == []


def test_the_real_case(tmp_path):
    """18.09 decisions file, 19.09 logbook entry -- one day apart, and already stale:
    the corpus it asks for was built on the 19th."""
    folder = _folder(tmp_path, book_days_ago=0, DARVO_md=1)
    pointer = ("кръг 2 ПРИКЛЮЧИ. Чакат 5 решения на стенли (DARVO.md, най-важно 🧑2 "
               "отрицателният корпус)")
    out = bss.stale_reference(folder, LOGBOOK, {"sledvashto": pointer})
    assert len(out) == 1
    assert "DARVO.md" in out[0]
    assert str(date.today() - timedelta(days=1)) in out[0]
