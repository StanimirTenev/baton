"""L1 before the write, not only after it.

Until now L1 (the hour in a logbook heading is read from the clock, never typed) was caught at
Stop, once the entry was already on disk. The PreToolUse hook surfaces it one step earlier: when
a Write or Edit is about to put a `## YYYY-MM-DD HH:MM --` heading into a logbook by hand, it
says, before the write, to use tools/baton_entry.py (which stamps the time itself). It never
blocks the tool; a hook that cannot be sure says nothing.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_pretool.py"


def _run(event: dict, tmp_path: Path) -> dict:
    env = {
        "PATH": "/usr/bin:/bin",
        "CLAUDE_PLUGIN_DATA": str(tmp_path),
        "BATON_LOGBOOK": "DNEVNIK.md",
        "BATON_HOME": str(tmp_path / "tasks"),
    }
    out = subprocess.run([sys.executable, str(HOOK)],
                         input=json.dumps(event).encode("utf-8"),
                         capture_output=True, env=env)
    assert out.returncode == 0, out.stderr.decode("utf-8")
    text = out.stdout.decode("utf-8").strip()
    return json.loads(text) if text else {}


def _context(payload: dict) -> str:
    return (payload.get("hookSpecificOutput") or {}).get("additionalContext", "")


def test_a_hand_typed_hour_heading_in_a_logbook_is_flagged_before_the_write(tmp_path):
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(tmp_path / "tasks" / "demo" / "DNEVNIK.md"),
            "content": "## 2026-10-28 14:30 — нещо\n\n### Направено\n...\n",
        },
    }
    ctx = _context(_run(event, tmp_path))
    assert "baton_entry.py" in ctx and "L1" in ctx, ctx


def test_an_edit_that_adds_the_heading_is_flagged(tmp_path):
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(tmp_path / "tasks" / "demo" / "DNEVNIK.md"),
            "old_string": "# log\n",
            "new_string": "# log\n\n## 2026-10-28 09:05 — x\n",
        },
    }
    assert "baton_entry.py" in _context(_run(event, tmp_path))


def test_a_date_only_heading_is_not_flagged(tmp_path):
    """No typed hour, nothing baton_entry.py would have stamped differently."""
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(tmp_path / "tasks" / "demo" / "DNEVNIK.md"),
            "content": "## 2026-10-28 — нещо\n",
        },
    }
    assert _context(_run(event, tmp_path)) == ""


def test_the_same_heading_in_a_non_logbook_file_is_left_alone(tmp_path):
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(tmp_path / "notes.md"),
            "content": "## 2026-10-28 14:30 — a note, not a logbook\n",
        },
    }
    assert _context(_run(event, tmp_path)) == ""


def test_other_tools_say_nothing(tmp_path):
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "echo '## 2026-10-28 14:30 — x' >> DNEVNIK.md"},
    }
    assert _run(event, tmp_path) == {}


def test_a_surfaced_before_event_is_counted(tmp_path):
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(tmp_path / "tasks" / "demo" / "DNEVNIK.md"),
            "content": "## 2026-10-28 14:30 — x\n",
        },
    }
    _run(event, tmp_path)
    state = json.loads((tmp_path / "baton.lessons.json").read_text("utf-8"))
    assert state.get("L1", {}).get("surfaced_before", 0) == 1
