"""ZA-OPRAVYANE row 181 (Д4, the three-host handoff of 17.11, step S3): Gemini headed its entry
09:20 and saved it at 09:13:55. Nothing said a word. Six minutes ahead is under both of Stop's
windows -- FUTURE_SLACK_SECONDS (600 s ahead of *now*) and L1's 20 minutes off the save time --
and L1 does not judge an entry it cannot attribute, which under Gemini is every entry: Stop reads
no Gemini tool call (row 174), so the logbook reads as another agent's. (Checked 17.11 with two
Stops: a new entry headed 40 minutes behind its save is L1's under Claude Code and Codex, and
passes in silence under Gemini.)

A heading read from the clock cannot be later than the moment the file was saved: the hour is
read first, then written, and the minute is cut, not rounded. Since 3.39.0 Stop also hands back a
top entry headed more than AHEAD_OF_SAVE_SECONDS after its logbook's own save time, for a logbook
saved since this session began -- whoever wrote it, under every host. Measured before choosing the
window, 17.11: 0 of the 56 top entries with an hour in the owner's logbooks are more than two
minutes ahead of their file's save time.

Through the hook's entry point, with each host's payload and transcript shape.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
BODY = "".join(f"### {s}\n{s}: a full sentence about the converter work, long enough to count.\n\n"
               for s in ("What was asked", "Done", "Result", "Open / notes"))


def _ts(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def _book(tasks: Path, top: datetime, saved: float) -> Path:
    folder = tasks / "tempconv"
    folder.mkdir(parents=True)
    book = folder / "LOGBOOK.md"
    older = datetime.fromtimestamp(saved) - timedelta(hours=2)
    book.write_text(f"---\nstate: active\ndone_when: \"tests pass\"\nnext: \"none\"\n---\n\n"
                    f"## {top:%Y-%m-%d %H:%M} — conclusion\n\n{BODY}"
                    f"## {older:%Y-%m-%d %H:%M} — start\n\n{BODY}", "utf-8")
    os.utime(book, (saved, saved))
    return book


def _transcript(host: str, tmp_path: Path, book: Path, began: float) -> dict:
    """The Stop payload of a session that began at `began` and edited `book` itself."""
    if host == "claude":
        sid = "c1a0de00-0000-4000-8000-000000000001"
        path = tmp_path / "proj" / f"{sid}.jsonl"
        rows = [{"type": "user", "timestamp": _ts(began), "message": {"role": "user", "content": "go"}},
                {"type": "assistant", "timestamp": _ts(began + 60), "message": {"content": [
                    {"type": "tool_use", "id": "t1", "name": "Edit",
                     "input": {"file_path": str(book), "old_string": "a", "new_string": "b"}}]}},
                {"type": "user", "timestamp": _ts(began + 61), "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}]
        payload = {"session_id": sid, "hook_event_name": "Stop"}
    elif host == "codex":
        payload = json.loads((FIXTURES / "codex" / "stop.json").read_text("utf-8"))
        sid = payload["session_id"]
        path = tmp_path / "sessions" / f"rollout-2026-11-14T11-09-33-{sid}.jsonl"
        patch = f"*** Begin Patch\n*** Update File: {book}\n@@\n+x\n*** End Patch"
        rows = [{"timestamp": _ts(began), "ordinal": 0, "type": "session_meta",
                 "payload": {"id": sid, "cwd": str(tmp_path / "proj")}},
                {"timestamp": _ts(began + 60), "ordinal": 1, "type": "response_item",
                 "payload": {"type": "custom_tool_call", "name": "apply_patch", "call_id": "c1", "input": patch}},
                {"timestamp": _ts(began + 61), "ordinal": 2, "type": "response_item",
                 "payload": {"type": "custom_tool_call_output", "call_id": "c1", "output": ""}}]
    else:
        payload = json.loads((FIXTURES / "gemini" / "after_agent.json").read_text("utf-8"))
        sid = payload["session_id"]
        path = tmp_path / "chats" / f"session-2026-11-17T09-13-{sid[:8]}.jsonl"
        rows = [{"sessionId": sid, "startTime": _ts(began), "kind": "main"},
                {"id": "u1", "timestamp": _ts(began), "type": "user", "content": [{"text": "go"}]},
                {"id": "g1", "timestamp": _ts(began + 60), "type": "gemini", "content": [], "toolCalls": [
                    {"id": "r1", "name": "replace", "args": {"file_path": str(book)},
                     "status": "success", "timestamp": _ts(began + 60)}]}]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    payload.update(transcript_path=str(path), cwd=str(tmp_path / "proj"), stop_hook_active=False)
    return payload


def _stop(tmp_path: Path, tasks: Path, payload: dict) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(BATON_HOME=str(tasks), BATON_LOGBOOK="LOGBOOK.md", HOME=str(tmp_path / "home"),
               CLAUDE_PLUGIN_DATA=str(tmp_path / "data"), BATON_STATE_DIR=str(tmp_path / "state"),
               BATON_LESSONS_STATE=str(tmp_path / "lessons.json"),
               BATON_SESSION_STATE=str(tmp_path / "session.json"),
               BATON_BODY_STATE=str(tmp_path / "bodies.json"),
               BATON_MANAGED_DIR=str(tmp_path / ".managed"))
    (tmp_path / "proj").mkdir(exist_ok=True)
    out = subprocess.run([sys.executable, str(HOOKS / "baton_stop.py")], input=json.dumps(payload),
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def _case(tmp_path, host, ahead_min: float, saved_ago: float = 30, began_ago: float = 1800):
    tasks = tmp_path / "tasks"
    saved = time.time() - saved_ago
    top = datetime.fromtimestamp(saved).replace(second=0, microsecond=0) + timedelta(minutes=ahead_min)
    book = _book(tasks, top, saved)
    payload = _transcript(host, tmp_path, book, time.time() - began_ago)
    return _stop(tmp_path, tasks, payload), top


HOSTS = ["claude", "codex", "gemini"]


@pytest.mark.parametrize("host", HOSTS)
def test_an_entry_headed_minutes_after_it_was_saved_is_handed_back(tmp_path, host):
    """The S3 case: six minutes ahead of the save, under every window there was."""
    got, top = _case(tmp_path, host, ahead_min=6)
    assert got.get("decision") == "block", (host, got)
    reason = got.get("reason", "")
    assert "tempconv" in reason and f"{top:%H:%M}" in reason, reason
    assert "after the logbook was saved" in reason, reason


@pytest.mark.parametrize("host", HOSTS)
def test_a_heading_read_from_the_clock_is_not_handed_back(tmp_path, host):
    """The same logbook headed with the minute it was saved in: nothing to say."""
    got, _ = _case(tmp_path, host, ahead_min=0)
    assert "LATER than" not in got.get("reason", "") and "after the logbook was saved" \
        not in got.get("reason", ""), (host, got)


@pytest.mark.parametrize("host", HOSTS)
def test_a_heading_behind_its_save_is_not_this_check(tmp_path, host):
    """A header edited after the entry moves the save time later, never the heading ahead."""
    got, _ = _case(tmp_path, host, ahead_min=-12)
    assert "after the logbook was saved" not in got.get("reason", ""), (host, got)


def test_asked_once_a_session_even_when_the_logbook_is_saved_again(tmp_path):
    tasks = tmp_path / "tasks"
    saved = time.time() - 120
    top = datetime.fromtimestamp(saved).replace(second=0, microsecond=0) + timedelta(minutes=6)
    book = _book(tasks, top, saved)
    payload = _transcript("gemini", tmp_path, book, time.time() - 1800)
    assert _stop(tmp_path, tasks, payload).get("decision") == "block"
    again = time.time() - 30                               # the header edited, the heading not
    os.utime(book, (again, again))
    assert "after the logbook was saved" not in _stop(tmp_path, tasks, payload).get("reason", "")


def test_a_logbook_saved_before_the_session_began_is_history(tmp_path):
    """Another session's old mistake, whose heading is by now in the past: not this turn's."""
    got, _ = _case(tmp_path, "gemini", ahead_min=6, saved_ago=3600, began_ago=1800)
    assert "after the logbook was saved" not in got.get("reason", ""), got
