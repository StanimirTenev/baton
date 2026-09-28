"""The Stop hook had no test file of its own. An external review of v2.14.0 said so,
and the defect it found is the kind that only an end-to-end test catches.

`unrecorded()` compared `work > logged + GRACE_SECONDS`, so a file saved thirty seconds
after the logbook was **never** reported — not a minute later, not a day later. And an
old file two minutes newer than its logbook kept stopping unrelated sessions forever.

The hook's own comment states the intent: "a file saved moments ago is still being
worked on". That is a grace against **now**, not against the logbook. The code had
drifted from its own sentence.
"""

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_stop.py"
spec = importlib.util.spec_from_file_location("bs", HOOK)
bs = importlib.util.module_from_spec(spec)
sys.modules["bs"] = bs
spec.loader.exec_module(bs)


def _task(root: Path, name: str, log_age: float, work_age: float, logbook="LOGBOOK.md"):
    """A folder whose logbook and work file are aged in seconds before now."""
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    now = time.time()
    log = folder / logbook
    log.write_text("---\nsastoyanie: aktivna\n---\n\n## 2026-01-01 00:00 — x\n\ny\n",
                   encoding="utf-8")
    os.utime(log, (now - log_age, now - log_age))
    work = folder / "draft.md"
    work.write_text("some work\n", encoding="utf-8")
    os.utime(work, (now - work_age, now - work_age))
    return folder


def test_work_saved_just_after_the_logbook_is_still_unrecorded(tmp_path):
    """🔴 The reproduction. Logbook an hour ago, file 30 s later — thirty minutes back.

    Under the old comparison this folder could never be reported, however long it sat.
    """
    _task(tmp_path, "alpha", log_age=3600, work_age=3570)
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == ["alpha (newest: draft.md)"]


def test_a_file_saved_moments_ago_is_left_alone(tmp_path):
    """The grace the comment actually describes: still being worked on, right now."""
    _task(tmp_path, "beta", log_age=3600, work_age=5)
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []


def test_a_logbook_newer_than_the_work_is_recorded(tmp_path):
    _task(tmp_path, "gama", log_age=10, work_age=3600)
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []


def test_a_folder_with_no_logbook_at_all_is_named_as_such(tmp_path):
    folder = tmp_path / "delta"
    folder.mkdir()
    work = folder / "draft.md"
    work.write_text("x\n", encoding="utf-8")
    os.utime(work, (time.time() - 600, time.time() - 600))
    out = bs.unrecorded(tmp_path, "LOGBOOK.md")
    assert out and "no LOGBOOK.md at all" in out[0]


def test_batonignore_silences_a_folder(tmp_path):
    folder = _task(tmp_path, "epsilon", log_age=3600, work_age=600)
    (folder / ".batonignore").write_text("draft.md\n", encoding="utf-8")
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []


def test_the_hook_blocks_through_its_real_entry_point(tmp_path, monkeypatch):
    """Through `main()` and its JSON, not the function — that is where it broke before."""
    _task(tmp_path, "zeta", log_age=3600, work_age=600)
    monkeypatch.setenv("BATON_HOME", str(tmp_path))
    monkeypatch.setenv("BATON_LOGBOOK", "LOGBOOK.md")
    out = subprocess.run([sys.executable, str(HOOK)], input="{}",
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout)
    assert payload.get("decision") == "block"
    assert "zeta" in payload.get("reason", "")


# --- a task with no criterion of done -----------------------------------------
# 2026-09-28: a conversation that was "only thinking aloud" ended in a decision on
# priorities and was never recognised as a task. The mechanical half of that: a folder
# worked in now whose header does not say when it is finished. Asked once per session,
# never on legacy folders nobody touched.

def _headed(root: Path, name: str, header: str, age: float, logbook="LOGBOOK.md"):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / logbook
    log.write_text(header + "\n## 2026-09-28 20:00 — x\n\ny\n", encoding="utf-8")
    now = time.time()
    os.utime(log, (now - age, now - age))
    return folder


def test_a_touched_task_without_a_criterion_is_named(tmp_path):
    _headed(tmp_path, "strategy", "---\nsastoyanie: aktivna\n---\n", age=60)
    assert bs.undefined(tmp_path, "LOGBOOK.md") == ["strategy"]


def test_a_touched_task_with_no_header_at_all_is_named(tmp_path):
    _headed(tmp_path, "fresh", "# just notes", age=60)
    assert bs.undefined(tmp_path, "LOGBOOK.md") == ["fresh"]


def test_a_task_with_a_criterion_is_left_alone(tmp_path):
    _headed(tmp_path, "done-able", "---\nkriterii_zavarshvane: \"the page is live\"\n---\n", age=60)
    assert bs.undefined(tmp_path, "LOGBOOK.md") == []


def test_an_empty_criterion_is_no_criterion(tmp_path):
    _headed(tmp_path, "blank", "---\nkriterii_zavarshvane: \"\"\n---\n", age=60)
    assert bs.undefined(tmp_path, "LOGBOOK.md") == ["blank"]


def test_an_untouched_legacy_folder_is_left_alone(tmp_path):
    """Not this session's work: asking about it would nag on day one."""
    _headed(tmp_path, "old", "---\nsastoyanie: aktivna\n---\n", age=3 * 3600)
    assert bs.undefined(tmp_path, "LOGBOOK.md") == []


def _run(tmp_path, monkeypatch, payload):
    monkeypatch.setenv("BATON_HOME", str(tmp_path))
    monkeypatch.setenv("BATON_LOGBOOK", "LOGBOOK.md")
    monkeypatch.setenv("BATON_STATE_DIR", str(tmp_path / ".state"))
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def test_no_criterion_blocks_once_per_session_through_the_entry_point(tmp_path, monkeypatch):
    _headed(tmp_path, "strategy", "---\nsastoyanie: aktivna\n---\n", age=60)
    first = _run(tmp_path, monkeypatch, {"session_id": "s1"})
    assert first.get("decision") == "block"
    assert "strategy" in first["reason"] and "kriterii_zavarshvane" in first["reason"]
    assert _run(tmp_path, monkeypatch, {"session_id": "s1"}) == {}, "asked twice in one session"
    assert _run(tmp_path, monkeypatch, {"session_id": "s2"}).get("decision") == "block"


def test_both_findings_arrive_in_one_block(tmp_path, monkeypatch):
    _task(tmp_path, "zeta", log_age=3600, work_age=600)
    _headed(tmp_path, "strategy", "---\nsastoyanie: aktivna\n---\n", age=60)
    out = _run(tmp_path, monkeypatch, {"session_id": "s1"})
    assert "zeta" in out["reason"] and "strategy" in out["reason"]


def test_stop_hook_active_still_wins(tmp_path, monkeypatch):
    _headed(tmp_path, "strategy", "---\nsastoyanie: aktivna\n---\n", age=60)
    assert _run(tmp_path, monkeypatch, {"session_id": "s1", "stop_hook_active": True}) == {}
