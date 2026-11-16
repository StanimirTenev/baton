"""ZA-OPRAVYANE row 124 (the owner, 07.11): the chat after the last logbook entry survives /clear.

Stop writes the human's messages and the agent's text replies since the last entry to
`<task root>/.baton-chat/<session>.md` -- no tool call, no tool output; an entry written trims it.
SessionStart after /clear or a restart hands it to the new session and removes it. Never a file
of a session still running in another window. Through the hooks' entry points.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
BODY = "".join(f"### {s}\n{s}: a full sentence about the pricing work, long enough to count.\n"
               for s in ("What was asked", "Done", "Result", "Open"))


def _ts(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _setup(tmp_path):
    tasks = tmp_path / "tasks"
    (tasks / "pricing").mkdir(parents=True)
    book = tasks / "pricing" / "LOGBOOK.md"
    book.write_text(f"---\ndone_when: shipped\n---\n\n## {datetime.now() - timedelta(days=3):%Y-%m-%d %H:%M} — e\n\n"
                    + BODY, "utf-8")
    old = time.time() - 3 * 86400
    os.utime(book, (old, old))
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR", "BATON_HOME"))}
    env.update(BATON_HOME=str(tasks), BATON_LOGBOOK="LOGBOOK.md", HOME=str(tmp_path / "home"),
               BATON_STATE_DIR=str(tmp_path / "state"))
    (tmp_path / "proj").mkdir()
    return env, tasks, book


def _talk(path: Path, turns: list) -> str:
    """(human, reply) turns five minutes apart, from 40 minutes ago, each with a tool call between."""
    rows, start = [], datetime.now() - timedelta(minutes=40)
    for i, (said, reply) in enumerate(turns):
        at = _ts(start + timedelta(minutes=5 * i))
        rows += [{"type": "user", "timestamp": at, "message": {"role": "user", "content": said}},
                 {"type": "assistant", "timestamp": at, "message": {"content": [
                     {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": "ls TOOLCALL"}}]}},
                 {"type": "user", "timestamp": at, "message": {"content": [
                     {"type": "tool_result", "tool_use_id": f"t{i}", "content": "TOOLOUTPUT"}]}},
                 {"type": "assistant", "timestamp": at, "message": {"content": [{"type": "text", "text": reply}]}}]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", "utf-8")
    return str(path)


def _run(hook, env, payload):
    out = subprocess.run([sys.executable, str(HOOKS / hook)], input=json.dumps(payload).encode(),
                         capture_output=True, env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout.decode("utf-8")


TURNS = [("how should we price the scanner?", "Three options: per seat, per repo, flat."),
         ("per seat, and my key is sk-abcdefghijklmnop1234", "Per seat it is."),
         ("49 euro per seat from December, decided", "Agreed: 49 euro per seat from December.")]


def test_the_chat_after_the_last_entry_reaches_the_session_after_clear(tmp_path):
    env, tasks, _ = _setup(tmp_path)
    tr = _talk(tmp_path / "proj" / "a.jsonl", TURNS)
    stop = _run("baton_stop.py", env, {"session_id": "a", "transcript_path": tr})
    kept = tasks / ".baton-chat" / "a.md"
    text = kept.read_text("utf-8")
    assert "49 euro per seat from December" in text and "Agreed: 49 euro" in text
    assert "TOOLOUTPUT" not in text and "TOOLCALL" not in text and "sk-abcdefghijklmnop1234" not in text
    assert "newer than" not in stop, "the chat file is not work to hand back"

    board = _run("baton_session_start.py", env, {"session_id": "b", "source": "clear",
                                                 "transcript_path": str(tmp_path / "proj" / "b.jsonl")})
    context = json.loads(board)["hookSpecificOutput"]["additionalContext"]
    assert "Agreed: 49 euro per seat from December." in context, context
    assert not kept.exists(), "handed over, then removed"
    assert list((tmp_path / "state").glob("baton-chat-a.md")), "the full text, in Baton's own state"


def test_an_entry_written_trims_the_chat(tmp_path):
    env, tasks, book = _setup(tmp_path)
    tr = _talk(tmp_path / "proj" / "a.jsonl", TURNS)
    _run("baton_stop.py", env, {"session_id": "a", "transcript_path": tr})
    assert (tasks / ".baton-chat" / "a.md").is_file()
    book.write_text(book.read_text("utf-8").replace(
        "---\n\n", f"---\n\n## {datetime.now():%Y-%m-%d %H:%M} — priced\n\n{BODY}\n", 1), "utf-8")
    _run("baton_stop.py", env, {"session_id": "a", "transcript_path": tr})
    assert not (tasks / ".baton-chat" / "a.md").exists(), "all of it is in the logbook now"


def test_a_running_session_s_chat_is_not_taken_at_startup(tmp_path):
    env, tasks, _ = _setup(tmp_path)
    (tasks / ".baton-chat").mkdir()
    other = tasks / ".baton-chat" / "x.md"
    other.write_text("<!-- baton-chat " + json.dumps({"session": "x", "pid": os.getpid(),
                                                       "project": str(tmp_path / "proj")})
                     + " -->\n**human 2026-11-08 09:00:** still talking in another window\n", "utf-8")
    board = _run("baton_session_start.py", env, {"session_id": "b", "source": "startup",
                                                 "transcript_path": str(tmp_path / "proj" / "b.jsonl")})
    assert "another window" not in board and other.is_file()


def test_a_chat_older_than_another_session_s_entry_is_not_called_the_previous_one(tmp_path):
    """v3.36.0, ZA-OPRAVYANE row 163 -- the phase-1 handoff test (16.11): Claude, then Codex, then
    Claude on one logbook. The third session's board offered the first one's chat as "the previous
    session's conversation after its last logbook entry", though Codex had written two entries
    after it; its end said the task waited on a review that was by then done. A chat saved before
    a logbook was last written is said to be older than that, with when and where -- for a task
    the chat names, as the phase-1 one did ("Continue the task handoff-demo")."""
    env, tasks, book = _setup(tmp_path)
    tr = _talk(tmp_path / "proj" / "a.jsonl", [("continue the task pricing", "Reading its logbook.")] + TURNS)
    _run("baton_stop.py", env, {"session_id": "a", "transcript_path": tr})
    kept = tasks / ".baton-chat" / "a.md"
    saved = time.time() - 600
    os.utime(kept, (saved, saved))
    later = datetime.fromtimestamp(saved) + timedelta(minutes=4)
    book.write_text(book.read_text("utf-8").replace(
        "---\n\n", f"---\n\n## {later:%Y-%m-%d %H:%M} — another agent's entry\n\n{BODY}\n", 1), "utf-8")
    os.utime(book, (later.timestamp(), later.timestamp()))
    board = _run("baton_session_start.py", env, {"session_id": "b", "source": "startup",
                                                 "transcript_path": str(tmp_path / "proj" / "b.jsonl")})
    context = json.loads(board)["hookSpecificOutput"]["additionalContext"]
    assert "Agreed: 49 euro per seat from December." in context, "still handed over"
    assert "The previous session's conversation" not in context, context
    assert "NOT the latest" in context and "Claude Code" in context
    assert f"pricing's LOGBOOK.md was written at {later:%Y-%m-%d %H:%M}" in context, context


def test_a_chat_newer_than_every_logbook_keeps_its_words(tmp_path):
    env, tasks, _ = _setup(tmp_path)
    tr = _talk(tmp_path / "proj" / "a.jsonl", TURNS)
    _run("baton_stop.py", env, {"session_id": "a", "transcript_path": tr})
    board = _run("baton_session_start.py", env, {"session_id": "b", "source": "startup",
                                                 "transcript_path": str(tmp_path / "proj" / "b.jsonl")})
    context = json.loads(board)["hookSpecificOutput"]["additionalContext"]
    assert "💬 The previous session's conversation after its last logbook entry" in context
    assert "NOT the latest" not in context


def test_a_newer_logbook_of_a_task_the_chat_never_names_changes_nothing(tmp_path):
    """Row 163: on a root with many tasks other sessions and scheduled agents write all day. A
    newer logbook makes the chat out of date only for a task the chat talks about -- by its folder
    name. Here the chat is about pricing, and only an unrelated task's logbook is newer."""
    env, tasks, _ = _setup(tmp_path)
    tr = _talk(tmp_path / "proj" / "a.jsonl", TURNS)
    _run("baton_stop.py", env, {"session_id": "a", "transcript_path": tr})
    kept = tasks / ".baton-chat" / "a.md"
    saved = time.time() - 600
    os.utime(kept, (saved, saved))
    other = tasks / "nightly-mail" / "LOGBOOK.md"
    other.parent.mkdir()
    other.write_text(f"---\ndone_when: x\n---\n\n## {datetime.now():%Y-%m-%d %H:%M} — cron\n\n{BODY}", "utf-8")
    os.utime(other, (saved + 240, saved + 240))
    board = _run("baton_session_start.py", env, {"session_id": "b", "source": "startup",
                                                 "transcript_path": str(tmp_path / "proj" / "b.jsonl")})
    context = json.loads(board)["hookSpecificOutput"]["additionalContext"]
    assert "💬 The previous session's conversation after its last logbook entry" in context
    assert "NOT the latest" not in context and "nightly-mail's" not in context
