"""Shelf life: a claim nobody checked does not improve with age.

Three real failures, on three consecutive days, produced this:

* a comparison table written for one release was quoted three releases later,
  because nothing in it said which release it described;
* a line reading "auditors probably cannot take a commission" -- marked at the
  time as an inference -- was carried as if settled, and nearly cancelled a
  plan before anyone read the code of ethics it claimed to summarise;
* two decisions recorded in memory stayed live for weeks after the work had
  gone the other way.

None of the three was a wrong fact. Each was a fact that had stopped being one
and still read exactly like the others. So a document may declare when it was
last true and how long that is expected to hold, and an unverified claim is
reported as a debt once it is old enough.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_session_start.py"
spec = importlib.util.spec_from_file_location("baton_session_start", HOOK)
baton = importlib.util.module_from_spec(spec)
sys.modules["baton_session_start"] = baton
spec.loader.exec_module(baton)

TODAY = date(2026, 9, 19)


# --- the review date -----------------------------------------------------------

def test_a_header_with_no_shelf_life_behaves_as_before():
    """Every task written before this existed must keep working untouched."""
    assert baton.review_due({"sastoyanie": "aktivna"}, TODAY) is None


def test_a_review_that_has_not_come_due_is_silent():
    fm = {"vyarno_kum": "2026-09-01", "pregled_sled": "30d"}
    assert baton.review_due(fm, TODAY) is None


def test_a_review_that_has_passed_is_reported_with_its_lateness():
    fm = {"vyarno_kum": "2026-08-01", "pregled_sled": "30d"}
    due = baton.review_due(fm, TODAY)
    assert due is not None
    when, late = due
    assert when == date(2026, 8, 31)
    assert late == 19


def test_months_are_understood_as_well_as_days():
    fm = {"vyarno_kum": "2026-01-01", "pregled_sled": "6m"}
    assert baton.review_due(fm, TODAY) is not None


def test_the_bulgarian_spellings_work_too():
    """The header is written by hand, in whichever alphabet the writer uses."""
    fm = {"вярно_към": "01.08.2026", "преглед_след": "30д"}
    assert baton.review_due(fm, TODAY) is not None


def test_an_as_of_date_with_no_period_says_nothing():
    """Half the pair is not a rule. It must not start reporting on its own."""
    assert baton.review_due({"vyarno_kum": "2026-01-01"}, TODAY) is None


def test_a_malformed_date_does_not_raise():
    assert baton.review_due({"vyarno_kum": "last spring", "pregled_sled": "30d"}, TODAY) is None


# --- the unverified debt -------------------------------------------------------

def facts(tmp_path: Path, body: str) -> Path:
    folder = tmp_path / "task"
    folder.mkdir()
    (folder / "FAKTI.md").write_text(body, encoding="utf-8")
    return folder


OLD = "## Кръг 1 — 01.06.2026\n\n| # | Факт | Статус | Източник |\n|---|---|---|---|\n"
NEW = "## Кръг 2 — 19.09.2026\n\n| # | Факт | Статус | Източник |\n|---|---|---|---|\n"


def test_an_old_inference_is_a_debt(tmp_path):
    folder = facts(tmp_path, OLD + "| 1.1 | auditors probably cannot | И | 06 |\n")
    debt = baton.unverified_debt(folder, TODAY)
    assert debt == (1, 110)


def test_a_verified_claim_of_any_age_is_not(tmp_path):
    folder = facts(tmp_path, OLD + "| 1.1 | checked against the code | П | ISO |\n"
                                   "| 1.2 | read locally | В | file:12 |\n")
    assert baton.unverified_debt(folder, TODAY) is None


def test_a_recent_inference_is_not_yet_a_debt(tmp_path):
    """Written yesterday, it is work in progress, not rot."""
    folder = facts(tmp_path, NEW + "| 2.1 | inferred today | И | — |\n")
    assert baton.unverified_debt(folder, TODAY) is None


def test_each_claim_is_dated_by_the_block_it_sits_in(tmp_path):
    """A file grows by rounds. A new round must not make the old ones young."""
    folder = facts(tmp_path,
                   OLD + "| 1.1 | old and unchecked | И | — |\n"
                         "| 1.2 | also old | А | agent |\n\n"
                   + NEW + "| 2.1 | new and unchecked | И | — |\n")
    count, oldest = baton.unverified_debt(folder, TODAY)
    assert (count, oldest) == (2, 110)


def test_latin_statuses_count_as_well(tmp_path):
    folder = facts(tmp_path, OLD + "| 1.1 | inferred | I | — |\n| 1.2 | agent said | A | x |\n")
    assert baton.unverified_debt(folder, TODAY)[0] == 2


def test_a_task_with_no_facts_file_is_silent(tmp_path):
    folder = tmp_path / "task"
    folder.mkdir()
    assert baton.unverified_debt(folder, TODAY) is None


def test_a_facts_file_with_no_dated_blocks_is_silent(tmp_path):
    """No date, no age. Reporting on a guess would be the defect itself."""
    folder = facts(tmp_path, "| 1 | something | И | — |\n")
    assert baton.unverified_debt(folder, TODAY) is None


def test_an_english_facts_file_is_read_too(tmp_path):
    folder = tmp_path / "task"
    folder.mkdir()
    (folder / "FACTS.md").write_text(
        "## Round 1 — 2026-06-01\n\n| # | Claim | Status | Source |\n|---|---|---|---|\n"
        "| 1 | inferred | I | — |\n", encoding="utf-8")
    assert baton.unverified_debt(folder, TODAY)[0] == 1
