"""A claim written down and never checked.

The logbook cannot hold a status: it is a record and does not get edited, while a
status is exactly what changes when someone finally checks. So claims with a status
live in a register, and the register ages them.
"""

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_session_start.py"
spec = importlib.util.spec_from_file_location("bss_claims", HOOK)
bss = importlib.util.module_from_spec(spec)
sys.modules["bss_claims"] = bss
spec.loader.exec_module(bss)

TODAY = date(2026, 9, 19)
OLD = (TODAY - timedelta(days=bss.STALE_CLAIM_DAYS + 5)).isoformat()
FRESH = (TODAY - timedelta(days=3)).isoformat()


def _task(tmp_path, filename, body):
    folder = tmp_path / "task"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_text(body, encoding="utf-8")
    return folder


def test_no_register_is_no_debt(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    assert bss.unverified_debt(folder, TODAY) is None


def test_a_row_dates_itself(tmp_path):
    """A register filled a row at a time has no meaningful block heading."""
    folder = _task(tmp_path, "TVARDENIYA.md",
                   f"| claim | status | date |\n|---|---|---|\n"
                   f"| this firm has no scanner | И | {OLD} |\n")
    debt = bss.unverified_debt(folder, TODAY)
    assert debt is not None
    count, age = debt
    assert count == 1 and age == bss.STALE_CLAIM_DAYS + 5


def test_a_fresh_claim_is_not_yet_a_debt(tmp_path):
    folder = _task(tmp_path, "TVARDENIYA.md",
                   f"| claim | status | date |\n|---|---|---|\n| new one | И | {FRESH} |\n")
    assert bss.unverified_debt(folder, TODAY) is None


def test_a_verified_claim_is_never_a_debt(tmp_path):
    folder = _task(tmp_path, "TVARDENIYA.md",
                   f"| claim | status | date |\n|---|---|---|\n| checked | П | {OLD} |\n")
    assert bss.unverified_debt(folder, TODAY) is None


def test_an_agents_word_counts_as_debt_too(tmp_path):
    folder = _task(tmp_path, "TVARDENIYA.md",
                   f"| claim | status | date |\n|---|---|---|\n| agent said so | А | {OLD} |\n")
    assert bss.unverified_debt(folder, TODAY)[0] == 1


def test_the_block_heading_still_dates_a_row_without_its_own_date(tmp_path):
    """The old shape keeps working: one table written in one sitting."""
    folder = _task(tmp_path, "FAKTI.md",
                   f"## Round 2 — {OLD}\n\n| claim | status |\n|---|---|\n| inferred | И |\n")
    assert bss.unverified_debt(folder, TODAY)[0] == 1


def test_the_oldest_claim_sets_the_reported_age(tmp_path):
    older = (TODAY - timedelta(days=90)).isoformat()
    folder = _task(tmp_path, "TVARDENIYA.md",
                   f"| c | s | d |\n|---|---|---|\n"
                   f"| one | И | {OLD} |\n| two | И | {older} |\n")
    count, age = bss.unverified_debt(folder, TODAY)
    assert count == 2 and age == 90


def test_a_dotted_european_date_in_a_row_is_read(tmp_path):
    d = (TODAY - timedelta(days=60))
    folder = _task(tmp_path, "TVARDENIYA.md",
                   f"| c | s | d |\n|---|---|---|\n| one | И | {d.strftime('%d.%m.%Y')} |\n")
    assert bss.unverified_debt(folder, TODAY)[0] == 1


# --- a day is not always fine enough ---------------------------------------

def test_a_row_may_carry_a_time_as_well_as_a_date(tmp_path):
    """On the day this was written, two claims were falsified within an hour of
    being made. Dated only to the day, a register cannot say what followed what."""
    folder = _task(tmp_path, "TVARDENIYA.md",
                   f"| c | s | d |\n|---|---|---|\n| with a time | И | {OLD} 09:15 |\n")
    debt = bss.unverified_debt(folder, TODAY)
    assert debt is not None and debt[0] == 1


def test_the_time_does_not_change_the_age_in_days(tmp_path):
    a = _task(tmp_path / "a", "TVARDENIYA.md",
              f"| c | s | d |\n|---|---|---|\n| bare | И | {OLD} |\n")
    b = _task(tmp_path / "b", "TVARDENIYA.md",
              f"| c | s | d |\n|---|---|---|\n| stamped | И | {OLD} 23:59 |\n")
    assert bss.unverified_debt(a, TODAY) == bss.unverified_debt(b, TODAY)


def test_an_iso_stamp_with_T_is_read(tmp_path):
    folder = _task(tmp_path, "TVARDENIYA.md",
                   f"| c | s | d |\n|---|---|---|\n| iso | И | {OLD}T14:30 |\n")
    assert bss.unverified_debt(folder, TODAY)[0] == 1


def test_a_fresh_claim_with_a_time_is_still_not_a_debt(tmp_path):
    folder = _task(tmp_path, "TVARDENIYA.md",
                   f"| c | s | d |\n|---|---|---|\n| today | И | {FRESH} 08:00 |\n")
    assert bss.unverified_debt(folder, TODAY) is None


def test_a_date_inside_the_claim_text_is_not_the_claims_date(tmp_path):
    """`| last release 0.12.0 (14.08.2026) | А |` was read as a claim written in
    August. That is a date inside the claim, not the date the claim was made. A
    detector that fires on the wrong thing gets switched off, and then the real
    ones go unread too."""
    folder = _task(tmp_path, "TVARDENIYA.md",
                   "| claim | s |\n|---|---|\n"
                   "| last release 0.12.0 (14.08.2026); registry says 0.5.2 | А |\n")
    assert bss.unverified_debt(folder, TODAY) is None


def test_a_date_column_still_dates_the_row(tmp_path):
    folder = _task(tmp_path, "TVARDENIYA.md",
                   f"| claim | s | d |\n|---|---|---|\n"
                   f"| release 0.12.0 (14.08.2026) | А | {OLD} |\n")
    assert bss.unverified_debt(folder, TODAY)[0] == 1


def test_a_standard_reference_is_not_a_date(tmp_path):
    folder = _task(tmp_path, "TVARDENIYA.md",
                   "| claim | s |\n|---|---|\n| ISO 17065 4.2.6 applies | А |\n")
    assert bss.unverified_debt(folder, TODAY) is None
