"""A plan that was never closed leaves the task unfinished.

The failure: research was run, a plan was written, work was done against it — and
then nobody ever said whether the plan had been carried out. Nothing marked it
finished, and nothing asked. Over six weeks this project ran reconnaissance,
analysis and planning repeatedly and closed a plan exactly never.

Unlike the other shelf-life checks this one has no grace period, because it is not
a guess about whether something aged: the plan either says it is closed or it does
not. And closing requires saying what came of it — a state with no result is a
tick, which is how a check gets satisfied without the thing behind it being true.
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


def _task(tmp_path: Path, plan: str | None = None) -> Path:
    folder = tmp_path / "zadacha"
    folder.mkdir()
    (folder / "DNEVNIK.md").write_text("## entry\n", encoding="utf-8")
    if plan is not None:
        (folder / "PLAN.md").write_text(plan, encoding="utf-8")
    return folder


OPEN = "---\nsastoyanie: otvoren\n---\n\n# План\n"
CLOSED = "---\nsastoyanie: zatvoren\nrezultat: \"пуснато, два канала отказаха\"\n---\n"
TICKED = "---\nsastoyanie: zatvoren\n---\n"


def test_no_plan_is_not_a_finding(tmp_path):
    """Not every task needs one."""
    assert bss.open_plan(_task(tmp_path)) is None


def test_an_open_plan_is_reported(tmp_path):
    assert bss.open_plan(_task(tmp_path, OPEN)) is not None


def test_a_closed_plan_with_a_result_is_quiet(tmp_path):
    assert bss.open_plan(_task(tmp_path, CLOSED)) is None


def test_closed_with_no_result_is_not_closed(tmp_path):
    """A tick is how a check gets satisfied without the thing behind it being true."""
    out = bss.open_plan(_task(tmp_path, TICKED))
    assert out is not None and "rezultat" in out


def test_an_abandoned_plan_closes_the_same_way(tmp_path):
    """Giving up is a result. It is stated, not left open forever."""
    plan = "---\nsastoyanie: zatvoren\nrezultat: \"изоставен — гейтът не падна\"\n---\n"
    assert bss.open_plan(_task(tmp_path, plan)) is None


def test_a_plan_with_no_header_has_never_been_closed(tmp_path):
    out = bss.open_plan(_task(tmp_path, "# План\n\nнякакъв текст\n"))
    assert out is not None and "хедър" in out


def test_the_line_says_how_long_it_has_sat(tmp_path):
    folder = _task(tmp_path, OPEN)
    old = time.time() - 40 * 86400
    os.utime(folder / "PLAN.md", (old, old))
    assert "40 дни" in bss.open_plan(folder)


def test_english_spellings_close_it_too(tmp_path):
    plan = "---\nsastoyanie: closed\nresult: \"shipped\"\n---\n"
    assert bss.open_plan(_task(tmp_path, plan)) is None


# --- carried out is not the same fact as given up on -------------------------

def test_a_plan_carried_out_closes(tmp_path):
    plan = "---\nsastoyanie: izpalnen\nrezultat: \"пуснато на четирите канала\"\n---\n"
    assert bss.open_plan(_task(tmp_path, plan)) is None


def test_a_plan_abandoned_closes_too(tmp_path):
    """Giving up finishes the task. It is not a failure of record-keeping, and it
    is not the same fact as having carried the plan out — the folder has to say
    which, six weeks later."""
    plan = "---\nsastoyanie: izostaven\nrezultat: \"гейтът не падна; парите отидоха другаде\"\n---\n"
    assert bss.open_plan(_task(tmp_path, plan)) is None


def test_abandoned_still_needs_a_result(tmp_path):
    """Why we gave up is the part worth keeping."""
    out = bss.open_plan(_task(tmp_path, "---\nsastoyanie: izostaven\n---\n"))
    assert out is not None and "rezultat" in out


def test_the_older_generic_closer_is_still_accepted(tmp_path):
    """Plans closed before the distinction existed do not start failing."""
    plan = "---\nsastoyanie: zatvoren\nrezultat: \"нещо\"\n---\n"
    assert bss.open_plan(_task(tmp_path, plan)) is None
