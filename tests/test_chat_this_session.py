"""Chat-only work, asked about in the same session (the owner's decision, 24.10).

SessionStart asks about the LAST session's messages (tests/test_quiet_session.py) -- one context
too late when the human followed Baton's own advice and typed /clear: the conversation was gone
by the time anyone asked. Two places now count this session's transcript instead:

- the ~200k reminder (UserPromptSubmit): before the agent tells the human to /clear, it asks
  whether anything decided only in chat should be recorded, with the count and the messages;
- Stop: no task file changed, and six or more messages since the last entry written in this
  session -- the turn is handed back once, to ask. Once per six messages; never on a turn that
  wrote an entry; never with `stop_hook_active`; silent when the transcript cannot be read.

Through the hooks' entry points, JSON on stdin, as the harness runs them.
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
PROMPT = ROOT / "hooks" / "baton_prompt.py"
STOP = ROOT / "hooks" / "baton_stop.py"


def _ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _transcript(path: Path, messages: list, start: datetime, tokens: int = 0) -> Path:
    """`messages` typed by the human ten minutes apart from `start`, each with a tool result and
    an answer after it (neither is the human's word); the last answer used `tokens` of context."""
    rows = []
    for i, text in enumerate(messages):
        at = _ts(start + timedelta(minutes=10 * i))
        rows.append({"type": "user", "timestamp": at, "message": {"role": "user", "content": text}})
        rows.append({"type": "user", "timestamp": at, "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "x", "content": "ok"}]}})
        rows.append({"type": "assistant", "timestamp": at, "message": {"content": "sure"}})
    if tokens:
        rows.append({"type": "assistant", "timestamp": _ts(start), "message": {"usage": {
            "input_tokens": 2, "cache_read_input_tokens": tokens - 1002,
            "cache_creation_input_tokens": 1000, "output_tokens": 50}}})
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", "utf-8")
    return path


def _setup(tmp_path, entry_at: datetime | None = None):
    tasks = tmp_path / "tasks"
    folder = tasks / "pricing"
    folder.mkdir(parents=True)
    book = folder / "LOGBOOK.md"
    entry_at = entry_at or datetime.now() - timedelta(days=3)
    body = "".join(f"### {s}\n{s} of the pricing talk, written out in a full sentence or two.\n"
                   for s in ("What was asked", "Done", "Result", "Open"))
    book.write_text(f"---\ndone_when: shipped\n---\n\n## {entry_at:%Y-%m-%d %H:%M} — e\n\n{body}",
                    "utf-8")
    old = time.time() - 4 * 86400
    os.utime(book, (old, old))
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR", "BATON_HOME"))}
    env.update(BATON_HOME=str(tasks), BATON_LOGBOOK="LOGBOOK.md", HOME=str(tmp_path / "home"),
               BATON_STATE_DIR=str(tmp_path / "state"))
    return env, book


def _run(hook: Path, env: dict, payload: dict) -> dict:
    out = subprocess.run([sys.executable, str(hook)], input=json.dumps(payload).encode(),
                         capture_output=True, env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def _msgs(n: int, first: str = "") -> list:
    return [first if first and not i else f"we settle on option {i}" for i in range(n)]


# --- before /clear ---------------------------------------------------------------------------

def _prompt(env, tr):
    return _run(PROMPT, env, {"prompt": "go on", "session_id": "s", "transcript_path": str(tr)})


def test_before_clear_the_agent_asks_with_the_count_and_the_messages(tmp_path):
    """🔴 The reproduction: until now the ~200k reminder said "write the logbooks, then tell the
    human to /clear" -- nothing about what was only said."""
    env, _ = _setup(tmp_path)
    tr = _transcript(tmp_path / "t.jsonl", _msgs(4), datetime.now() - timedelta(hours=1), 250_000)
    out = _prompt(env, tr)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "4 messages" in ctx and "we settle on option 0" in ctx, ctx
    ask, clear = ctx.index("whether anything"), ctx.index("type /clear")
    assert ask < clear and "after they answer" in ctx[ask:clear], ctx
    assert "/clear" in out["systemMessage"] and "asks" in out["systemMessage"], out


def test_before_clear_only_the_messages_after_the_last_entry_count(tmp_path):
    start = datetime.now() - timedelta(hours=1)
    env, _ = _setup(tmp_path, entry_at=start + timedelta(minutes=25))    # after message 2
    tr = _transcript(tmp_path / "t.jsonl", _msgs(5), start, 250_000)
    ctx = _prompt(env, tr)["hookSpecificOutput"]["additionalContext"]
    assert "2 messages" in ctx and "option 3" in ctx and "option 0" not in ctx, ctx


def test_before_clear_a_pasted_key_is_masked(tmp_path):
    env, _ = _setup(tmp_path)
    key = "sk-or-v1-" + "a1B2" * 12
    tr = _transcript(tmp_path / "t.jsonl", _msgs(3, f"use {key} for it"),
                     datetime.now() - timedelta(hours=1), 250_000)
    ctx = _prompt(env, tr)["hookSpecificOutput"]["additionalContext"]
    assert key not in ctx and "[masked]" in ctx, ctx


def test_before_clear_without_a_count_the_question_is_still_asked(tmp_path):
    """No timestamps to count by: the ask stays, without a number."""
    env, _ = _setup(tmp_path)
    tr = tmp_path / "t.jsonl"
    tr.write_text(json.dumps({"type": "assistant", "message": {"usage": {
        "input_tokens": 250_000}}}) + "\n", "utf-8")
    ctx = _prompt(env, tr)["hookSpecificOutput"]["additionalContext"]
    assert "whether anything" in ctx and "messages typed" not in ctx, ctx


# --- Stop ------------------------------------------------------------------------------------

def _stop(env, tr, active=False):
    payload = {"session_id": "s", "transcript_path": str(tr)}
    if active:
        payload["stop_hook_active"] = True
    return _run(STOP, env, payload)


def test_stop_asks_after_six_messages_with_no_entry(tmp_path):
    """🔴 The reproduction: a turn that touched no file passed clean however much was said."""
    env, _ = _setup(tmp_path)
    tr = _transcript(tmp_path / "t.jsonl", _msgs(6), datetime.now() - timedelta(hours=1))
    out = _stop(env, tr)
    assert out.get("decision") == "block", out
    assert "6 messages" in out["reason"] and "we settle on option 0" in out["reason"], out


def test_stop_asks_once_per_six_messages(tmp_path):
    env, _ = _setup(tmp_path)
    start = datetime.now() - timedelta(hours=2)
    tr = _transcript(tmp_path / "t.jsonl", _msgs(6), start)
    assert _stop(env, tr).get("decision") == "block"
    assert _stop(env, tr) == {}                          # the same six: asked already
    _transcript(tr, _msgs(11), start)
    assert _stop(env, tr) == {}                          # five more: not yet
    _transcript(tr, _msgs(12), start)
    assert "12 messages" in _stop(env, tr).get("reason", "")


def test_stop_is_silent_under_six(tmp_path):
    env, _ = _setup(tmp_path)
    tr = _transcript(tmp_path / "t.jsonl", _msgs(5), datetime.now() - timedelta(hours=1))
    assert _stop(env, tr) == {}


def test_stop_never_asks_on_the_pass_after_a_hand_back(tmp_path):
    env, _ = _setup(tmp_path)
    tr = _transcript(tmp_path / "t.jsonl", _msgs(8), datetime.now() - timedelta(hours=1))
    assert _stop(env, tr, active=True).get("decision") is None


def test_stop_is_silent_when_the_transcript_cannot_be_read(tmp_path):
    env, _ = _setup(tmp_path)
    assert _stop(env, tmp_path / "missing.jsonl") == {}


def test_stop_never_asks_on_a_turn_that_wrote_an_entry(tmp_path):
    """The entry may be headed with a wrong hour (lesson L1); the logbook saved after the last
    message is what says this turn wrote one."""
    env, book = _setup(tmp_path)
    tr = _transcript(tmp_path / "t.jsonl", _msgs(7), datetime.now() - timedelta(hours=2))
    os.utime(book, None)        # saved now, after the last message; its heading says nothing new
    assert _stop(env, tr) == {}


def test_stop_counts_from_the_last_entry_of_this_session(tmp_path):
    start = datetime.now() - timedelta(hours=2)
    env, _ = _setup(tmp_path, entry_at=start + timedelta(minutes=35))   # after message 3
    tr = _transcript(tmp_path / "t.jsonl", _msgs(9), start)
    assert _stop(env, tr) == {}                          # five since the entry
    _transcript(tr, _msgs(10), start)
    assert "6 messages" in _stop(env, tr).get("reason", "")
