"""ZA-OPRAVYANE row 26: a session that touched no task folder is never asked about.

Stop judges by file times, so a decision made only in chat passes clean (the probe of 21.10:
a turn with no file touched -> exit 0, nothing). Jake Manis's idea (20.10): at session start,
put the messages of the last session next to the logbook entries written in that time -- two
numbers, no judgement -- and say so when there were messages and no entry.

A "message" is one the human typed: not a tool result, not a command's output, not the
agent's turns (those multiply in loops and subagents). Through the hook's entry point.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_session_start.py"


def _ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _setup(tmp_path, entry_at: datetime, messages=5):
    home = tmp_path / "home"
    project = home / ".claude" / "projects" / "-p"
    project.mkdir(parents=True)
    start = datetime.now() - timedelta(hours=2)
    lines = []
    for i in range(messages):
        at = start + timedelta(minutes=10 * i)
        lines.append({"type": "user", "timestamp": _ts(at),
                      "message": {"role": "user", "content": f"decide the price, option {i}"}})
        lines.append({"type": "user", "timestamp": _ts(at), "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "x", "content": "ok"}]}})
        lines.append({"type": "assistant", "timestamp": _ts(at), "message": {"content": "sure"}})
    lines.append({"type": "user", "isMeta": True, "timestamp": _ts(start),
                  "message": {"content": "<local-command-caveat>x</local-command-caveat>"}})
    lines.append({"type": "user", "timestamp": _ts(start),
                  "message": {"content": "<command-name>/model</command-name>"}})
    prev = project / "prev.jsonl"
    prev.write_text("\n".join(json.dumps(x) for x in lines) + "\n", "utf-8")
    old = (datetime.now() - timedelta(minutes=30)).timestamp()
    os.utime(prev, (old, old))
    own = project / "own.jsonl"
    own.write_text(json.dumps({"type": "user", "timestamp": _ts(datetime.now())}) + "\n", "utf-8")
    tasks = tmp_path / "tasks"
    (tasks / "pricing").mkdir(parents=True)
    (tasks / "pricing" / "LOGBOOK.md").write_text(
        f"---\nstate: active\nturn: us\n---\n\n## {entry_at:%Y-%m-%d %H:%M} — e\n\nx\n", "utf-8")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR", "BATON_HOME"))}
    env.update(HOME=str(home), BATON_HOME=str(tasks), BATON_LOGBOOK="LOGBOOK.md")
    return env, str(own)


def _ctx(env, own, source="startup"):
    payload = json.dumps({"source": source, "session_id": "own", "transcript_path": own})
    out = subprocess.run([sys.executable, str(HOOK)], input=payload.encode(), capture_output=True,
                         env=env)
    assert out.returncode == 0, out.stderr
    if not out.stdout.strip():
        return ""
    return json.loads(out.stdout).get("hookSpecificOutput", {}).get("additionalContext", "")


def test_messages_and_no_entry_in_that_time_are_said(tmp_path):
    env, own = _setup(tmp_path, datetime.now() - timedelta(days=3))
    ctx = _ctx(env, own)
    assert "5 messages from the human" in ctx and "0 logbook entries" in ctx, ctx
    assert "decide the price, option 0" in ctx, "the messages are named, not only counted"
    assert "tool result" not in ctx.split("5 messages")[0][-200:]


def test_an_entry_written_in_that_time_is_enough(tmp_path):
    env, own = _setup(tmp_path, datetime.now() - timedelta(minutes=90))   # inside the session
    assert "messages from the human" not in _ctx(env, own)


def test_said_once_per_session_and_also_after_clear(tmp_path):
    env, own = _setup(tmp_path, datetime.now() - timedelta(days=3))
    assert "5 messages from the human" in _ctx(env, own, "clear")
    assert "messages from the human" not in _ctx(env, own), "the same session is said once"


def test_not_after_compaction_or_on_resume(tmp_path):
    env, own = _setup(tmp_path, datetime.now() - timedelta(days=3))
    assert "messages from the human" not in _ctx(env, own, "compact")
    assert "messages from the human" not in _ctx(env, own, "resume")


def test_a_short_exchange_is_not_a_finding(tmp_path):
    env, own = _setup(tmp_path, datetime.now() - timedelta(days=3), messages=2)
    assert "messages from the human" not in _ctx(env, own)
