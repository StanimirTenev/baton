"""ZA-OPRAVYANE row 64 (swarm D, 22.10; probe G15): a crash in the hour after the clocks go back
was shown as ✅.

Heartbeats, crash markers and start marks hold naive local time, and were ordered by comparing
that text. On 25.10.2026 (EU: 04:00 -> 03:00) a crash at 03:20, second pass, sorts before a finish
at 03:50, first pass, written half an hour earlier: SessionStart said nothing and /baton-doctor
printed "✅ last finished" with exit 0. Now the files' own times (epoch, never repeating) decide
which is newer; the text breaks a tie and is shown.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FIRST_PASS = "2026-10-25T03:50:00.000001"      # Stop finished, summer time (00:50 UTC)
SECOND_PASS = "2026-10-25T03:20:00.000001"     # 30 real minutes later, winter time: it crashed


def _env(tmp_path, data):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), BATON_HOME=str(tmp_path / "tasks"), CLAUDE_PLUGIN_DATA=str(data),
               BATON_STATE_DIR=str(tmp_path / "state"),
               BATON_LESSONS_STATE=str(data / "baton.lessons.json"))
    return env


def _markers(data, kind="crashed"):
    data.mkdir(parents=True, exist_ok=True)
    beat = data / "baton.beat.baton_stop"
    beat.write_text(FIRST_PASS, "utf-8")
    os.utime(beat, (1792889400, 1792889400))                  # 2026-10-25 00:50 UTC
    if kind == "crashed":
        mark = data / "baton.beat.baton_stop.crashed"
        mark.write_text(f"{SECOND_PASS} PermissionError", "utf-8")
    else:
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()                                            # a pid that is surely not running
        mark = data / f"baton.beat.baton_stop.started.{gone.pid}"
        mark.write_text(SECOND_PASS, "utf-8")
    os.utime(mark, (1792891200, 1792891200))                  # 01:20 UTC, 30 minutes later
    (data / "baton.beat.baton_session_start").write_text(FIRST_PASS, "utf-8")


def _start(env):
    out = subprocess.run([sys.executable, str(ROOT / "hooks" / "baton_session_start.py")],
                         input=b'{"source": "startup"}', capture_output=True, env=env)
    return out.stdout.decode("utf-8")


def _doctor(env):
    return subprocess.run([sys.executable, str(ROOT / "tools" / "baton_doctor.py")],
                          capture_output=True, text=True, env=env)


def test_a_crash_after_the_clocks_go_back_is_said(tmp_path):
    data = tmp_path / "data"
    env = _env(tmp_path, data)
    _markers(data)
    assert "crashed on its last run" in _start(env)
    _markers(data)                                            # SessionStart wrote its own beat
    out = _doctor(env)
    assert out.returncode == 1 and "CRASHED" in out.stdout, out.stdout


def test_a_kill_after_the_clocks_go_back_is_said(tmp_path):
    data = tmp_path / "data"
    env = _env(tmp_path, data)
    _markers(data, "started")
    assert "did not finish its last run" in _start(env)
    _markers(data, "started")
    out = _doctor(env)
    assert out.returncode == 1 and "DID NOT FINISH" in out.stdout, out.stdout


def test_a_finish_after_the_crash_still_makes_it_history(tmp_path):
    """The other direction: the crash first, the finish 30 minutes later but an hour 'earlier'
    by the clock text -- the crash is history, not news."""
    data = tmp_path / "data"
    env = _env(tmp_path, data)
    _markers(data)
    beat, crash = data / "baton.beat.baton_stop", data / "baton.beat.baton_stop.crashed"
    crash.write_text(f"{FIRST_PASS} PermissionError", "utf-8")
    os.utime(crash, (1792889400, 1792889400))
    beat.write_text(SECOND_PASS, "utf-8")
    os.utime(beat, (1792891200, 1792891200))
    assert "crashed on its last run" not in _start(env)


def test_same_second_falls_back_to_the_text(tmp_path):
    """A coarse clock can give two files the same time; the text decides then."""
    data = tmp_path / "data"
    env = _env(tmp_path, data)
    _markers(data)
    (data / "baton.beat.baton_stop").write_text("2026-10-22T03:20:00.000001", "utf-8")
    (data / "baton.beat.baton_stop.crashed").write_text("2026-10-22T03:50:00.000001 OSError", "utf-8")
    for p in (data / "baton.beat.baton_stop", data / "baton.beat.baton_stop.crashed"):
        os.utime(p, (1792889400, 1792889400))
    assert "crashed on its last run" in _start(env)
