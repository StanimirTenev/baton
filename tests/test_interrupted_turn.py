"""ZA-OPRAVYANE row 185 (18.11): a turn cut off -- no Stop and no StopFailure after it -- is named at
the next SessionStart in one line: the task, the time, the newest entry, and an offer to go on
from there.

The doctor already sees such a turn (`baton.turns/<session>`); the task comes from that session's
transcript, the turn's own calls (baton_stop.turn_task). Only the most recent turn, only when it is
the newest activity of any other session, never one tied to no task or to several, and never a
turn of a session still running in another window.

Run the way the harness runs it: a subprocess with the hook's JSON on stdin.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_session_start.py"
TITLE = "the invoice, half done"


def _turns(data: Path, session: str, *rows, pid: int | None = None):
    """`rows`: (minutes ago, event). The file's time is its last row's, as the hooks leave it."""
    folder = data / "baton.turns"
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    lines = [f"{(now - timedelta(minutes=m)).isoformat()} {event}"
             + (f" pid={pid}" if pid and event == "UserPromptSubmit" else "") for m, event in rows]
    path = folder / session
    path.write_text("\n".join(lines) + "\n", "utf-8")
    last = time.time() - 60 * min(m for m, _ in rows)
    os.utime(path, (last, last))


def _task(tasks: Path, name: str) -> Path:
    folder = tasks / name
    folder.mkdir(parents=True)
    (folder / "LOGBOOK.md").write_text(
        f"---\nstate: active\n---\n\n## 2026-11-17 18:00 — {TITLE}\n\nThe totals are left.\n", "utf-8")
    return folder


def _transcript(projects: Path, session: str, *paths: Path):
    """That session's Claude Code transcript: the human's message, then the turn's Write calls."""
    now = datetime.now(timezone.utc)
    rows = [{"type": "user", "timestamp": (now - timedelta(minutes=30)).isoformat(),
             "message": {"role": "user", "content": "go on with the invoice"}},
            {"type": "assistant", "timestamp": (now - timedelta(minutes=25)).isoformat(),
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": f"w{i}", "name": "Write",
                  "input": {"file_path": str(p), "content": "x"}} for i, p in enumerate(paths)]}}]
    path = projects / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")


def _start(tmp_path, source: str = "startup") -> str:
    home = tmp_path / "home"
    projects = home / ".claude" / "projects" / "-work"
    projects.mkdir(parents=True, exist_ok=True)
    own = projects / "new-session.jsonl"
    own.write_text(json.dumps({"type": "user", "timestamp": datetime.now(timezone.utc).isoformat()})
                   + "\n", "utf-8")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(BATON_PAGE="off", HOME=str(home), BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               CLAUDE_PLUGIN_ROOT=str(ROOT), CLAUDE_PLUGIN_DATA=str(tmp_path / "data"),
               BATON_SESSION_STATE=str(tmp_path / "s.json"),
               BATON_BODY_STATE=str(tmp_path / "bodies.json"),
               BATON_LESSONS_STATE=str(tmp_path / "lessons.json"),
               BATON_STATE_DIR=str(tmp_path / "state"), BATON_MANAGED_DIR=str(tmp_path / ".managed"))
    payload = {"session_id": "new-session", "transcript_path": str(own), "source": source,
               "hook_event_name": "SessionStart"}
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload).encode("utf-8"),
                         capture_output=True, env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]


def _projects(tmp_path) -> Path:
    return tmp_path / "home" / ".claude" / "projects" / "-work"


def _cut(ctx: str) -> list[str]:
    return [ln for ln in ctx.splitlines() if "was cut off" in ln]


def test_a_cut_off_turn_is_named_with_its_task_time_and_entry(tmp_path):
    folder = _task(tmp_path / "tasks", "invoice")
    _task(tmp_path / "tasks", "report")
    _turns(tmp_path / "data", "old-session", (30, "UserPromptSubmit"), (25, "PostToolBatch"))
    _transcript(_projects(tmp_path), "old-session", folder / "invoice.md")
    lines = _cut(_start(tmp_path))
    when = (datetime.now() - timedelta(minutes=25)).strftime("%H:%M")
    assert len(lines) == 1, lines
    assert "invoice" in lines[0] and when in lines[0] and TITLE in lines[0], lines
    assert "report" not in lines[0]


def test_a_turn_that_ended_with_a_stop_is_not_named(tmp_path):
    folder = _task(tmp_path / "tasks", "invoice")
    _turns(tmp_path / "data", "old-session", (30, "UserPromptSubmit"), (25, "Stop"))
    _transcript(_projects(tmp_path), "old-session", folder / "invoice.md")
    assert _cut(_start(tmp_path)) == []


def test_only_the_most_recent_and_only_when_nothing_came_after_it(tmp_path):
    a, b = _task(tmp_path / "tasks", "invoice"), _task(tmp_path / "tasks", "report")
    _turns(tmp_path / "data", "older", (90, "UserPromptSubmit"), (85, "PostToolBatch"))
    _turns(tmp_path / "data", "newer", (30, "UserPromptSubmit"), (25, "PostToolBatch"))
    _transcript(_projects(tmp_path), "older", a / "invoice.md")
    _transcript(_projects(tmp_path), "newer", b / "report.md")
    lines = _cut(_start(tmp_path))
    assert len(lines) == 1 and "report" in lines[0], lines
    _turns(tmp_path / "data", "later", (10, "UserPromptSubmit"), (9, "Stop"))
    assert _cut(_start(tmp_path)) == []          # work went on after it: not "the last turn"


def test_a_turn_tied_to_two_tasks_or_none_is_not_named(tmp_path):
    a, b = _task(tmp_path / "tasks", "invoice"), _task(tmp_path / "tasks", "report")
    _turns(tmp_path / "data", "old-session", (30, "UserPromptSubmit"), (25, "PostToolBatch"))
    _transcript(_projects(tmp_path), "old-session", a / "invoice.md", b / "report.md")
    assert _cut(_start(tmp_path)) == []
    _transcript(_projects(tmp_path), "old-session", tmp_path / "elsewhere.md")
    assert _cut(_start(tmp_path)) == []


def test_a_session_still_running_in_another_window_is_not_named(tmp_path):
    """A long tool call is an open turn too. Its Claude Code process is alive (here: this one)."""
    folder = _task(tmp_path / "tasks", "invoice")
    _turns(tmp_path / "data", "old-session", (30, "UserPromptSubmit"), (25, "PostToolBatch"),
           pid=os.getpid())
    _transcript(_projects(tmp_path), "old-session", folder / "invoice.md")
    assert _cut(_start(tmp_path)) == []


def test_the_prompt_hook_records_the_claude_process_it_runs_under(tmp_path):
    """What the guard above reads: UserPromptSubmit's turn line carries `pid=` when the hook runs
    under a process named claude, and stays as it was otherwise."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(BATON_PAGE="off", HOME=str(tmp_path / "home"), BATON_HOME=str(tmp_path / "tasks"),
               CLAUDE_PLUGIN_ROOT=str(ROOT), CLAUDE_PLUGIN_DATA=str(tmp_path / "data"),
               BATON_SESSION_STATE=str(tmp_path / "s.json"))
    out = subprocess.run([sys.executable, str(ROOT / "hooks" / "baton_prompt.py")],
                         input=json.dumps({"session_id": "s9", "prompt": ""}).encode("utf-8"),
                         capture_output=True, env=env)
    assert out.returncode == 0, out.stderr
    line = (tmp_path / "data" / "baton.turns" / "s9").read_text("utf-8").strip()
    parts = line.split(" ")
    assert parts[1] == "UserPromptSubmit", line
    assert len(parts) == 2 or (len(parts) == 3 and parts[2].startswith("pid=")
                               and parts[2][4:].isdigit()), line
