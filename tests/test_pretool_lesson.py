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
        "tool_name": "Read",
        "tool_input": {"file_path": "DNEVNIK.md"},
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


# Row 139 / the L1 board line ("recurred 6 times in 14 days"): every heading L1 caught that could
# be traced in the transcripts here (15.10, 22.10, 24.10, 07.11) was written by a Bash call --
# `python3 - <<'EOF'` or `sed -i` -- never by Write or Edit, so the note above never ran on the path
# the mistake takes. A Bash call that writes the logbook with a typed hour gets the same note.
def _bash(command: str, tmp_path) -> str:
    return _context(_run({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                          "tool_input": {"command": command}}, tmp_path))


def test_a_bash_heredoc_that_writes_a_typed_hour_into_the_logbook_is_flagged(tmp_path):
    cmd = ("cd ~/zadachi/vps-agent && python3 - <<'EOF'\np='DNEVNIK.md'\ns=open(p).read()\n"
           "e='''## 2026-11-07 15:10 — Доставчик\\n\\n### Направено\\n'''\nopen(p,'w').write(e+s)\nEOF")
    assert "baton_entry.py" in _bash(cmd, tmp_path)
    state = json.loads((tmp_path / "baton.lessons.json").read_text("utf-8"))
    assert state["L1"]["surfaced_before"] == 1


def test_a_sed_that_types_the_hour_into_the_logbook_is_flagged(tmp_path):
    cmd = "sed -i 's/^## 2026-10-15 08:40 — x/## 2026-10-15 16:49 — x/' ~/zadachi/a/DNEVNIK.md"
    assert "baton_entry.py" in _bash(cmd, tmp_path)


def test_a_bash_read_or_a_clock_read_hour_says_nothing(tmp_path):
    for cmd in ("grep -n '^## 2026-11-10 12:16' ~/zadachi/a/DNEVNIK.md 2>/dev/null",
                "t=$(date '+%Y-%m-%d %H:%M') && sed -i \"s/^## 2026-11-07 15:10 — x/## $t — x/\" DNEVNIK.md",
                "python3 ~/dev/baton/tools/baton_entry.py ~/zadachi/a/DNEVNIK.md body.md --title x",
                "echo '## 2026-10-28 14:30 — x' >> notes.md"):
        assert _bash(cmd, tmp_path) == "", cmd


def test_a_baton_skill_call_is_counted_and_the_doctor_shows_it(tmp_path):
    """ZA-OPRAVYANE row 134 (Ivan Petrakov, 09.11): a skill that does not load fails silently;
    Baton counted none of its five. The numerator: each call of the Skill tool for one of Baton's
    skills is counted with its time, and /baton-doctor shows it. Another skill is not counted.
    (When a skill should have fired and did not -- the denominator -- is row 136, not here.)"""
    import os
    for name in ("baton:baton-task", "baton-task", "someone-elses-skill"):
        out = _run({"hook_event_name": "PreToolUse", "tool_name": "Skill",
                    "tool_input": {"skill": name}}, tmp_path)
        assert out == {}, "counted, never a note"
    state = json.loads((tmp_path / "baton.lessons.json").read_text("utf-8"))
    assert state["skills"]["baton-task"]["used"] == 2 and "someone-elses-skill" not in state["skills"]
    doctor = subprocess.run([sys.executable, str(HOOK.parent.parent / "tools" / "baton_doctor.py")],
                            capture_output=True, text=True,
                            env={**os.environ, "CLAUDE_PLUGIN_DATA": str(tmp_path),
                                 "BATON_LESSONS_STATE": str(tmp_path / "baton.lessons.json")})
    assert "baton-task: 2" in doctor.stdout and "baton-plan: never" in doctor.stdout, doctor.stdout


def test_the_plugin_and_the_installer_send_bash_to_it():
    hooks = json.loads((HOOK.parent / "hooks.json").read_text("utf-8"))
    assert {"Bash", "Skill"} <= set(hooks["hooks"]["PreToolUse"][0]["matcher"].split("|"))
    assert '"PreToolUse": "Write|Edit|MultiEdit|Bash' in (HOOK.parent / "_install_hooks.py").read_text("utf-8")


# v3.36.0, ZA-OPRAVYANE row 161 -- the phase-1 handoff test (16.11): the note came three times for
# edits that carried an existing heading through unchanged, to add a claims section under it (a
# Claude Edit twice, a Codex Python replace once). Only a heading whose typed hour is not already
# in the logbook is one baton_entry.py would have stamped. The payloads are those of the test.
DEMO_LOG = """---
state: active
---

# Logbook -- handoff-demo

## 2026-11-16 16:38 — Approved criteria and completed short market overview

### What was asked
Go on.

## 2026-11-16 16:34 — Draft criteria table (v1)

### What was asked
Continue the task.
"""


def _demo(tmp_path) -> Path:
    log = tmp_path / "tasks" / "handoff-demo" / "DNEVNIK.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(DEMO_LOG, "utf-8")
    return log


def _edit(path, old, new) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Edit",
            "tool_input": {"file_path": str(path), "old_string": old, "new_string": new}}


def test_an_edit_that_keeps_the_heading_and_adds_a_section_says_nothing(tmp_path):
    log = _demo(tmp_path)
    head = "## 2026-11-16 16:34 — Draft criteria table (v1)\n\n"
    event = _edit(log, head, head + "### Claims to verify\nNone: \"public\" here is the kind of "
                  "source.\n\n")
    assert _context(_run(event, tmp_path)) == ""


def test_a_python_replace_that_keeps_the_heading_says_nothing(tmp_path):
    log = _demo(tmp_path)
    cmd = ("python - <<'PY'\nfrom pathlib import Path\n"
           "p=Path('../tasks/handoff-demo/DNEVNIK.md')\ns=p.read_text()\n"
           "heading='## 2026-11-16 16:38 — Approved criteria and completed short market overview\\n'\n"
           "s=s.replace(heading,heading+'\\n### Claims to verify\\nPublic means the sources.\\n',1)\n"
           "p.write_text(s)\nPY")
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(tmp_path / "work"),
             "tool_input": {"command": cmd}}
    assert _context(_run(event, tmp_path)) == ""
    assert log.is_file()


def test_an_edit_that_changes_the_hour_is_still_flagged(tmp_path):
    log = _demo(tmp_path)
    event = _edit(log, "## 2026-11-16 16:34 — Draft", "## 2026-11-16 16:36 — Draft")
    assert "baton_entry.py" in _context(_run(event, tmp_path))


def test_a_new_heading_above_kept_ones_is_still_flagged(tmp_path):
    log = _demo(tmp_path)
    head = "## 2026-11-16 16:38 — Approved"
    event = _edit(log, head, "## 2026-11-16 16:50 — New entry\n\n### Done\nx\n\n" + head)
    assert "baton_entry.py" in _context(_run(event, tmp_path))


def test_a_write_of_the_whole_logbook_with_its_headings_kept_says_nothing(tmp_path):
    log = _demo(tmp_path)
    event = {"hook_event_name": "PreToolUse", "tool_name": "Write",
             "tool_input": {"file_path": str(log), "content": DEMO_LOG.replace("Go on.", "Go on!")}}
    assert _context(_run(event, tmp_path)) == ""
    event["tool_input"]["content"] = "## 2026-11-16 17:01 — x\n\n" + DEMO_LOG
    assert "baton_entry.py" in _context(_run(event, tmp_path))


def test_a_bash_command_on_a_logbook_it_cannot_find_still_says_it(tmp_path):
    """Nothing to compare with: the note, as before."""
    cmd = ("python - <<'PY'\np='elsewhere/DNEVNIK.md'\nh='## 2026-11-16 16:38 — x\\n'\n"
           "s=open(p).read().replace(h,h+'more',1)\nopen(p,'w').write(s)\nPY")
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(tmp_path),
             "tool_input": {"command": cmd}}
    assert "baton_entry.py" in _context(_run(event, tmp_path))
