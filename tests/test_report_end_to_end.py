"""The report as a whole, run the way the harness runs it.

Every other test here calls one function directly. That is how a `NameError` in
`main()` survived a green suite: each check was tested, the wiring that calls it
was not -- and the entry point catches everything and exits 0, so the failure was
a session with no Baton output at all and no error anywhere.

So this runs the script as a subprocess over a real folder tree and reads the JSON
it prints. It does not re-test what each check decides; it tests that each check is
reached, and that a crash is no longer silent.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_session_start.py"
LOGBOOK = "DNEVNIK.md"

HEADER = """---
sastoyanie: aktivna
na_hod: nie
sledvashto: "{pointer}"
prioritet: visok
---

## 2026-09-21 10:00 — запис
"""


def _run(root: Path) -> dict:
    env = dict(os.environ, BATON_HOME=str(root), BATON_LOGBOOK=LOGBOOK)
    done = subprocess.run([sys.executable, str(HOOK)], input="", env=env,
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert not done.stderr, f"the hook crashed silently:\n{done.stderr}"
    return json.loads(done.stdout) if done.stdout.strip() else {}


def _task(root: Path, name: str, pointer: str) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / LOGBOOK).write_text(HEADER.format(pointer=pointer), encoding="utf-8")
    return folder


def test_a_task_is_listed(tmp_path):
    _task(tmp_path, "zadacha", "да се пусне коментарът")
    report = _run(tmp_path)["hookSpecificOutput"]["additionalContext"]
    assert "zadacha" in report
    assert "да се пусне коментарът" in report


def test_a_stale_reference_reaches_the_report(tmp_path):
    """The wiring this file exists for: the check ran, and its line came out."""
    folder = _task(tmp_path, "zadacha", "чакат 5 решения (DARVO.md)")
    darvo = folder / "DARVO.md"
    darvo.write_text("въпроси\n", encoding="utf-8")
    old = time.time() - 4 * 86400
    os.utime(darvo, (old, old))
    report = _run(tmp_path)["hookSpecificOutput"]["additionalContext"]
    assert "DARVO.md" in report
    assert "shelf life" in report


def test_a_bloated_pointer_reaches_the_report(tmp_path):
    _task(tmp_path, "zadacha", "x" * 400)
    assert "`next`" in _run(tmp_path)["hookSpecificOutput"]["additionalContext"]


def test_an_empty_root_says_nothing_rather_than_failing(tmp_path):
    assert _run(tmp_path) == {}


def test_the_board_goes_to_the_agent_to_show_in_the_humans_language(tmp_path):
    """The board used to reach the human as a systemMessage -- in English, whatever language
    they speak. Only the agent knows that language, so only the agent gets the board, with
    the instruction to show all of it, translated."""
    _task(tmp_path, "zadacha", "нещо")
    out = _run(tmp_path)
    context = out["hookSpecificOutput"]["additionalContext"]
    assert "systemMessage" not in out
    assert "zadacha" in context
    assert "translated into the human's language" in context
    assert "every group and every line" in context
    assert "WHOLE board" in context and "no summary" in context
    assert LOGBOOK in context
