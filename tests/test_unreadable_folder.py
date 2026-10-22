"""ZA-OPRAVYANE row 54 (swarm D, 22.10; probe G01): one unreadable task folder took the whole board
and every Stop check with it.

`Path.is_file()` re-raises PermissionError. A folder owned by root under the tasks root (a docker
volume, a mounted share) crashed SessionStart and Stop on every run: no board for any task, no
Stop check for any task, and the crash notice is built by the SessionStart that crashed. Now such
a folder is left out of `task_folders` -- the one function every hook asks -- and named: on the
board, and by Stop once a session.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0,
                                reason="chmod 0 does not lock a folder for root or on Windows")

BODY = ("### What was asked\nA draft of the quarterly report in the usual layout for the board.\n\n"
        "### Done\nWrote report.md from last quarter's numbers; the revenue table is filled.\n\n"
        "### Result\nThe draft is complete except the outlook paragraph, which needs data.\n\n"
        "### Still open\nThe outlook paragraph, once the forecast arrives on Friday morning.\n")


def _env(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"),
               BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               CLAUDE_PLUGIN_DATA=str(tmp_path / "data"), BATON_STATE_DIR=str(tmp_path / "state"),
               BATON_LESSONS_STATE=str(tmp_path / "data" / "baton.lessons.json"),
               BATON_BODY_STATE=str(tmp_path / "data" / "baton.bodies.json"),
               BATON_SESSION_STATE=os.environ["BATON_SESSION_STATE"])
    return env


def _run(hook, env, payload):
    out = subprocess.run([sys.executable, str(ROOT / "hooks" / f"{hook}.py")],
                         input=json.dumps(payload).encode("utf-8"), capture_output=True, env=env)
    assert out.returncode == 0, out.stderr
    text = out.stdout.decode("utf-8").strip()
    return json.loads(text) if text.startswith("{") else {}


def _age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


@pytest.fixture
def tasks(tmp_path):
    good = tmp_path / "tasks" / "report"
    good.mkdir(parents=True)
    (good / "LOGBOOK.md").write_text(
        "---\nstate: active\nturn: us\nnext: finish the outlook\n---\n\n"
        f"## {datetime.now() - timedelta(hours=1):%Y-%m-%d %H:%M} — draft\n\n" + BODY, "utf-8")
    locked = tmp_path / "tasks" / "docker-volume"
    locked.mkdir()
    (locked / "LOGBOOK.md").write_text("---\nstate: active\n---\n", "utf-8")
    os.chmod(locked, 0)
    yield good
    os.chmod(locked, 0o755)


def test_the_board_survives_and_names_the_folder(tmp_path, tasks):
    out = _run("baton_session_start", _env(tmp_path), {"source": "startup"})
    ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "report" in ctx and "finish the outlook" in ctx, ctx
    assert "docker-volume" in ctx and "could not read" in ctx, ctx
    assert not (tmp_path / "data" / "baton.beat.baton_session_start.crashed").exists()


def test_stop_still_checks_the_other_folders_and_says_the_locked_one(tmp_path, tasks):
    _age(tasks / "LOGBOOK.md", 3600)
    (tasks / "report.md").write_text("new work", "utf-8")
    _age(tasks / "report.md", 600)                          # unrecorded, past the grace period
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({"type": "user", "timestamp": (
        datetime.now() - timedelta(minutes=30)).astimezone().isoformat()}) + "\n", "utf-8")
    env = _env(tmp_path)
    out = _run("baton_stop", env, {"session_id": "s", "transcript_path": str(transcript)})
    assert out.get("decision") == "block" and "report" in out.get("reason", ""), out
    assert "docker-volume" in out.get("systemMessage", ""), out
    assert not (tmp_path / "data" / "baton.beat.baton_stop.crashed").exists()
    again = _run("baton_stop", env, {"session_id": "s", "transcript_path": str(transcript),
                                     "stop_hook_active": True})
    assert "docker-volume" not in json.dumps(again), "said once a session"
