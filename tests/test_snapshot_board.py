"""What the three hooks say about one fixed set of tasks, held word for word.

The baseline for taking a shared core out of the hooks (stage 0, 2026-11-14): every later step
of that work must leave these files unchanged, and a test that compares the whole output is the
only one that notices a sentence lost on the way. Each hook runs as the harness runs it -- a
subprocess, a payload on stdin -- over a task root built in tmp_path, never the real one.

Nothing here freezes the clock. The fixture's dates and file times are set relative to now, so
every age the hooks print is the same on any day; the dates themselves, the tmp root and the
version are replaced with placeholders before the comparison.

To write the golden files again after a change that is meant to alter the output:

    UPDATE_SNAPSHOTS=1 python3 -m pytest -q -p no:cacheprovider tests/test_snapshot_board.py

and read the diff before committing it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from conftest import _VERSION, child_env

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
SNAPSHOTS = Path(__file__).resolve().parent / "snapshots"
DAY = 86400


def _day(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _write(path: Path, text: str, age_seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    then = time.time() - age_seconds
    os.utime(path, (then, then))


def _logbook(header: str, days_ago: int, title: str) -> str:
    return (f"---\n{header}---\n\n## {_day(days_ago)} 10:00 — {title}\n\n"
            "### What was asked\nx\n### Done\ny\n### Result\nz\n")


def _tasks(root: Path) -> Path:
    """Seven invented tasks, one for each thing the board sorts or warns about."""
    # Cyrillic name and alias, high priority, ours, with a plan never closed.
    _write(root / "проба-диск" / "LOGBOOK.md", _logbook(
        'state: active\nturn: us\npriority: high\nnext: "смени диска"\naliases: [диск, disk]\n',
        2, "дискът е поръчан"), 2 * DAY)
    _write(root / "проба-диск" / "PLAN.md", "---\nstate: open\n---\n\n# План\n", 3 * DAY)
    # Medium priority, ours, a claims register with an I row 45 days old.
    _write(root / "alpha-web" / "LOGBOOK.md", _logbook(
        'state: active\nturn: us\npriority: medium\nnext: "publish the page"\n',
        5, "page drafted"), 5 * DAY)
    _write(root / "alpha-web" / "TVARDENIYA.md",
           "| claim | status | date | time |\n|---|---|---|---|\n"
           f"| the page loads in 1 s | И | {_day(45)} | 10:00 |\n"
           f"| the domain is ours | П | {_day(45)} | 10:05 |\n", 6 * DAY)
    # Low priority, the human's move.
    _write(root / "beta-docs" / "LOGBOOK.md", _logbook(
        'state: active\nturn: human\npriority: low\nnext: "approve the text"\n',
        7, "text sent for approval"), 7 * DAY)
    # Waiting on someone outside.
    _write(root / "gamma-supplier" / "LOGBOOK.md", _logbook(
        'state: waiting\nturn: supplier\npriority: medium\nnext: "the part arrives"\n',
        10, "part ordered"), 10 * DAY)
    # Frozen and done.
    _write(root / "delta-old" / "LOGBOOK.md", _logbook(
        'state: frozen\nnext: "nothing for now"\n', 30, "parked"), 30 * DAY)
    _write(root / "epsilon-done" / "LOGBOOK.md", _logbook(
        'state: done\nresult: "shipped"\n', 20, "finished"), 20 * DAY)
    # Ours, and a work file an hour newer than its logbook.
    _write(root / "zeta-work" / "LOGBOOK.md", _logbook(
        'state: active\nturn: us\npriority: medium\nnext: "finish the draft"\n',
        1, "draft started"), 2 * 3600)
    _write(root / "zeta-work" / "draft.md", "more of the draft\n", 3600)
    return root


def _env(tmp_path: Path, root: Path) -> dict:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    return child_env(BATON_HOME=str(root), BATON_LOGBOOK="LOGBOOK.md", HOME=str(home),
                     USERPROFILE=str(home), CLAUDE_PLUGIN_DATA=str(data),
                     BATON_STATE_DIR=str(tmp_path / "state"), LANG="C.UTF-8")


def _run(hook: str, env: dict, payload: dict) -> str:
    out = subprocess.run([sys.executable, str(HOOKS / hook)],
                         input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                         env=env, capture_output=True, timeout=60)
    assert out.returncode == 0 and not out.stderr, out.stderr.decode("utf-8", "replace")
    return out.stdout.decode("utf-8")


def _normalise(text: str, root: Path) -> str:
    """The parts that differ by day or machine become placeholders; nothing else is touched."""
    text = text.replace(str(root), "<ROOT>").replace(_VERSION, "<VERSION>")
    today = date.today()

    def stamp(m: re.Match) -> str:
        try:
            ago = (today - datetime.strptime(m.group(1), "%Y-%m-%d").date()).days
        except ValueError:
            return m.group(0)
        return f"<today-{ago}>" + (" <HH:MM>" if m.group(2) else "")
    return re.sub(r"(\d{4}-\d\d-\d\d)( \d\d:\d\d)?", stamp, text)


def _compare(name: str, actual: str) -> None:
    golden = SNAPSHOTS / name
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        golden.parent.mkdir(exist_ok=True)
        with open(golden, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(actual)
        return
    assert golden.is_file(), f"no {golden.name}: run with UPDATE_SNAPSHOTS=1 once"
    assert actual == golden.read_text(encoding="utf-8"), (
        f"{name} changed. If the change is meant, regenerate with UPDATE_SNAPSHOTS=1 and read "
        "the diff; if not, the refactor changed what the hook says.")


def test_the_session_start_board(tmp_path):
    root = _tasks(tmp_path / "tasks")
    raw = _run("baton_session_start.py", _env(tmp_path, root), {"source": "startup"})
    context = json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    _compare("session_start_board.txt", _normalise(context, root))


def test_the_prompt_naming_the_cyrillic_task(tmp_path):
    root = _tasks(tmp_path / "tasks")
    raw = _run("baton_prompt.py", _env(tmp_path, root),
               {"session_id": "snap", "prompt": "какво остава за диска?"})
    _compare("prompt_cyrillic_task.txt", _normalise(raw, root))


def test_the_stop_hand_back(tmp_path):
    root = _tasks(tmp_path / "tasks")
    raw = _run("baton_stop.py", _env(tmp_path, root), {"session_id": "snap"})
    out = json.loads(raw)
    assert out.get("decision") == "block" and "zeta-work" in out.get("reason", "")
    _compare("stop_hand_back.json", _normalise(json.dumps(out, ensure_ascii=False, indent=2,
                                                          sort_keys=True) + "\n", root))
