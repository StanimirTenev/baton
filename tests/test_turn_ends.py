"""ZA-OPRAVYANE rows 90 and 49 (Synthetixis, 22-23.10).

Row 90: a turn that ends on an API error runs StopFailure instead of Stop
(code.claude.com/docs/en/hooks, read 23.10), and Baton did not register it -- such a turn left no
beat and looked like a Stop that did not run. Row 49: the doctor looked at each hook on its own, so
a Stop three days old beside the others a minute old was ✅. Now the hooks add a line per run to
`baton.turns/<session>` and the doctor asks, per session, whether the last activity was followed
by a Stop or a StopFailure -- a question (⚠️), not a failure.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(tmp_path, data, **extra):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), BATON_HOME=str(tmp_path / "tasks"), CLAUDE_PLUGIN_ROOT=str(ROOT),
               CLAUDE_PLUGIN_DATA=str(data), BATON_MANAGED_DIR=str(tmp_path / ".managed"),
               BATON_LESSONS_STATE=str(tmp_path / "lessons.json"),
               BATON_SESSION_STATE=str(tmp_path / "state.json"),
               BATON_BODY_STATE=str(tmp_path / "bodies.json"), **extra)
    return env


def _hook(tmp_path, data, hook, payload: bytes):
    return subprocess.run([sys.executable, str(ROOT / "hooks" / f"{hook}.py")], input=payload,
                          capture_output=True, env=_env(tmp_path, data))


def _doctor(tmp_path, data, **extra):
    return subprocess.run([sys.executable, str(ROOT / "tools" / "baton_doctor.py")],
                          capture_output=True, text=True, env=_env(tmp_path, data, **extra))


def _beats(data):
    """Heartbeats as a working install leaves them: every hook finished a minute ago."""
    data.mkdir(parents=True, exist_ok=True)
    when = (datetime.now() - timedelta(minutes=1)).isoformat()
    for stem in ("baton_session_start", "baton_prompt", "baton_stop", "baton_batch"):
        (data / f"baton.beat.{stem}").write_text(when, "utf-8")


def _turns(data, session, *rows):
    """`rows`: (minutes ago, event, extra)."""
    folder = data / "baton.turns"
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    (folder / session).write_text("".join(
        f"{(now - timedelta(minutes=m)).isoformat()} {event} {extra}".rstrip() + "\n"
        for m, event, extra in rows), "utf-8")


# (a) StopFailure is registered and its hook writes a beat with the error type

def test_the_plugin_registers_stopfailure():
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text("utf-8"))["hooks"]
    commands = [h["command"] for g in hooks["StopFailure"] for h in g["hooks"]]
    assert any("baton_stop_failure.py" in c for c in commands), commands


def test_the_installer_registers_stopfailure_once(tmp_path):
    hookdir, settings = tmp_path / "hooks", tmp_path / "settings.json"
    hookdir.mkdir()
    for _ in range(2):
        out = subprocess.run([sys.executable, str(ROOT / "hooks" / "_install_hooks.py"),
                              str(settings), str(hookdir), sys.executable, "0",
                              str(tmp_path / "tasks"), "LOGBOOK.md"], capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
    data = json.loads(settings.read_text("utf-8"))
    args = [h.get("args") for g in data["hooks"]["StopFailure"] for h in g["hooks"]]
    assert args == [[str(hookdir / "baton_stop_failure.py")]], args
    assert "StopFailure: hook already installed" in out.stdout
    for script in ("install.sh", "install.ps1"):     # and both copy the file it points at
        assert "baton_stop_failure.py" in (ROOT / script).read_text("utf-8"), script


def test_the_stopfailure_hook_records_the_error_type_and_says_nothing(tmp_path):
    data = tmp_path / "data"
    payload = {"session_id": "abc-123", "hook_event_name": "StopFailure", "error": "rate_limit",
               "error_details": "429 Too Many Requests",
               "last_assistant_message": "API Error: Rate limit reached"}
    out = _hook(tmp_path, data, "baton_stop_failure", json.dumps(payload).encode())
    assert out.returncode == 0 and out.stdout == b"" and out.stderr == b"", out
    assert (data / "baton.beat.baton_stop_failure").is_file()
    line = (data / "baton.turns" / "abc-123").read_text("utf-8").strip()
    assert line.endswith(" StopFailure rate_limit"), line
    datetime.fromisoformat(line.split(" ")[0])


def test_the_stopfailure_hook_takes_any_payload(tmp_path):
    """Fields missing, or no payload at all: still a beat, never a crash, never output."""
    data = tmp_path / "data"
    for payload in (b'{"session_id": "s2"}', b"{}", b"not json", b"[]", b""):
        out = _hook(tmp_path, data, "baton_stop_failure", payload)
        assert out.returncode == 0 and out.stdout == b"", (payload, out)
    assert (data / "baton.beat.baton_stop_failure").is_file()
    assert not (data / "baton.beat.baton_stop_failure.crashed").exists()
    assert (data / "baton.turns" / "s2").read_text("utf-8").strip().endswith(" StopFailure unknown")


def test_the_other_hooks_record_their_session(tmp_path):
    data = tmp_path / "data"
    _hook(tmp_path, data, "baton_batch", b'{"session_id": "s1", "tool_calls": []}')
    _hook(tmp_path, data, "baton_stop", b'{"session_id": "s1", "stop_hook_active": false}')
    _hook(tmp_path, data, "baton_stop", b'{"session_id": "s1", "stop_hook_active": true}')
    events = [ln.split(" ", 1)[1] for ln in
              (data / "baton.turns" / "s1").read_text("utf-8").splitlines()]
    assert events == ["PostToolBatch", "Stop", "Stop again"], events


# (b) the doctor asks per session

def test_a_last_tool_call_with_no_stop_after_it_is_a_question(tmp_path):
    data = tmp_path / "data"
    _beats(data)
    _turns(data, "good-session", (30, "UserPromptSubmit", ""), (29, "PostToolBatch", ""),
           (28, "Stop", ""))
    _turns(data, "open-session", (20, "UserPromptSubmit", ""), (10, "PostToolBatch", ""))
    out = _doctor(tmp_path, data)
    assert out.returncode == 0, out.stdout            # a question, not a failure
    assert "⚠️  A turn with no end seen, in 1 of the last 2 sessions" in out.stdout, out.stdout
    assert "open-ses  PostToolBatch" in out.stdout and "good-ses" not in out.stdout
    assert "human interrupts a turn" in out.stdout


def test_a_stopfailure_explains_the_missing_stop(tmp_path):
    data = tmp_path / "data"
    _beats(data)
    _turns(data, "failed-session", (20, "UserPromptSubmit", ""), (10, "PostToolBatch", ""),
           (9, "StopFailure", "rate_limit"))
    out = _doctor(tmp_path, data)
    assert out.returncode == 0, out.stdout
    assert "⚠️" not in out.stdout, out.stdout
    assert "✅ Turns ended" in out.stdout and "ended on an API error: rate_limit" in out.stdout


def test_two_stops_in_a_turn_are_not_an_anomaly(tmp_path):
    """Baton's hand-back, then the pass with `stop_hook_active` true: by design."""
    data = tmp_path / "data"
    _beats(data)
    _turns(data, "s", (9, "PostToolBatch", ""), (8, "Stop", ""), (7, "PostToolBatch", ""),
           (6, "Stop", "again"))
    out = _doctor(tmp_path, data)
    assert "✅ Turns ended" in out.stdout and "⚠️" not in out.stdout, out.stdout


def test_the_doctors_own_turn_and_a_young_one_are_not_judged(tmp_path):
    data = tmp_path / "data"
    _beats(data)
    _turns(data, "this-session", (30, "UserPromptSubmit", ""))
    _turns(data, "busy-session", (0, "PostToolBatch", ""))
    out = _doctor(tmp_path, data, BATON_SESSION="this-session")
    assert "Turns" not in out.stdout and "⚠️" not in out.stdout, out.stdout


# (c) heartbeats from before session ids

def test_old_heartbeats_without_a_session_still_work(tmp_path):
    data = tmp_path / "data"
    _beats(data)
    out = _doctor(tmp_path, data)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "✅ Running" in out.stdout and "Traceback" not in out.stderr
    assert "Turns" not in out.stdout and "turn with no end" not in out.stdout


def test_a_broken_turn_record_does_not_crash_the_doctor(tmp_path):
    data = tmp_path / "data"
    _beats(data)
    (data / "baton.turns").mkdir()
    (data / "baton.turns" / "x").write_bytes(b"\xff\xfe garbage\n\nnot-a-time Stop\n")
    out = _doctor(tmp_path, data)
    assert out.returncode == 0 and "Traceback" not in out.stderr, out.stderr
