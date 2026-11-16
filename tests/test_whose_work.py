"""Stop counted files a cron job or another session wrote as this session's work (08.11).

Evidence that morning: two hand-backs for folders the session never touched -- a nightly cron's
`emaili-finansovi/baza/*` (02:30) and `prodazhbi-atestacia/reklama-poshta/proverka-*` (08:15) --
and on 07.11, after /clear, `done_when` asked for a task another session had just written in.
Now a file counts when this session's tool calls touched it: a Write/Edit naming it, a call that
names its folder or runs in it, or a Bash call running when it was saved -- the subagents' calls
too. What none touched is said to the human once and left for the board. Through the hook.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_stop.py"
BODY = "".join(f"### {s}\n{s}: a full sentence about the work, long enough to count as said.\n"
               for s in ("What was asked", "Done", "Result", "Open"))


def _ts(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def _age(path: Path, seconds: float) -> None:
    t = time.time() - seconds
    os.utime(path, (t, t))


def _task(tmp_path, name: str, header: str = "done_when: shipped\n") -> Path:
    folder = tmp_path / "tasks" / name
    folder.mkdir(parents=True)
    book = folder / "LOGBOOK.md"
    book.write_text(f"---\n{header}---\n\n## {datetime.now() - timedelta(hours=3):%Y-%m-%d %H:%M} — e\n\n{BODY}",
                    "utf-8")
    _age(book, 3 * 3600)
    return folder


def _work(folder: Path, rel: str, age: float = 300) -> Path:
    path = folder / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", "utf-8")
    _age(path, age)
    return path


def _transcript(path: Path, calls: list) -> str:
    """A session begun 30 minutes ago; `calls` are (tool, input, seconds ago begun, seconds run)."""
    rows = [{"type": "user", "timestamp": _ts(time.time() - 1800), "cwd": str(path.parent),
             "message": {"role": "user", "content": "go on"}}]
    for i, (tool, args, ago, ran) in enumerate(calls):
        rows.append({"type": "assistant", "timestamp": _ts(time.time() - ago), "cwd": args.pop("_cwd", "/"),
                     "message": {"content": [{"type": "tool_use", "id": f"t{i}", "name": tool, "input": args}]}})
        rows.append({"type": "user", "timestamp": _ts(time.time() - ago + ran),
                     "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "ok"}]}})
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", "utf-8")
    return str(path)


def _stop(tmp_path, transcript: str, session="s") -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_HOME", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               HOME=str(tmp_path / "home"), BATON_STATE_DIR=str(tmp_path / "state"))
    out = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, env=env,
                         input=json.dumps({"session_id": session, "transcript_path": transcript}))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


ELSEWHERE = ("Bash", {"command": "ls /etc"}, 1200, 1)     # a session that did something, not here


def test_a_file_a_cron_wrote_is_not_handed_back_and_is_said_once(tmp_path):
    folder = _task(tmp_path, "emaili-finansovi")
    _work(folder, "baza/2026-11-08.csv")
    tr = _transcript(tmp_path / "t.jsonl", [ELSEWHERE])
    out = _stop(tmp_path, tr)
    assert out.get("decision") != "block", out
    assert "emaili-finansovi" in out.get("systemMessage", "") and "2026-11-08.csv" in out["systemMessage"]
    assert "emaili-finansovi" not in json.dumps(_stop(tmp_path, tr)), "said once a session"


def test_a_file_this_session_wrote_is_still_handed_back(tmp_path):
    cases = {
        "write": lambda f: ("Write", {"file_path": str(f / "notes.md")}, 400, 1),
        "named": lambda f: ("Bash", {"command": f"cd ~/x && python3 gen.py --out {f.name}/notes.md"}, 1500, 1),
        "cwd": lambda f: ("Bash", {"command": "python3 gen.py", "_cwd": str(f)}, 1500, 1),
        "agent": lambda f: ("Agent", {"prompt": f"Update the notes in {f}"}, 1500, 1),
        "window": lambda f: ("Bash", {"command": "python3 ~/bin/report.py"}, 310, 20),
    }
    for case, call in cases.items():
        here = tmp_path / case
        folder = _task(here, "pricing")
        _work(folder, "notes.md")
        tr = _transcript(here / "t.jsonl", [ELSEWHERE, call(folder)])
        out = _stop(here, tr)
        assert out.get("decision") == "block" and "notes.md" in out.get("reason", ""), (case, out)


def test_a_subagent_s_write_is_this_session_s_work(tmp_path):
    folder = _task(tmp_path, "pricing")
    _work(folder, "notes.md")
    tr = _transcript(tmp_path / "t.jsonl", [ELSEWHERE])
    (tmp_path / "t" / "subagents").mkdir(parents=True)
    _transcript(tmp_path / "t" / "subagents" / "agent-a1.jsonl",
                [("Edit", {"file_path": str(folder / "notes.md")}, 400, 1)])
    out = _stop(tmp_path, tr)
    assert out.get("decision") == "block" and "notes.md" in out.get("reason", ""), out


def test_only_this_session_s_files_are_named_beside_a_cron_s(tmp_path):
    folder = _task(tmp_path, "prodazhbi")
    _work(folder, "reklama/proverka-1.txt", age=200)
    _work(folder, "plan.md")
    tr = _transcript(tmp_path / "t.jsonl", [("Edit", {"file_path": str(folder / "plan.md")}, 400, 1)])
    reason = _stop(tmp_path, tr).get("reason", "")
    assert "plan.md" in reason and "proverka-1.txt" not in reason, reason


def test_another_session_s_task_is_not_asked_for_done_when(tmp_path):
    """07.11 17:11: after /clear, `done_when` was asked for `finansirane`, written by another session."""
    folder = _task(tmp_path, "finansirane", header="state: active\n")
    _age(folder / "LOGBOOK.md", 600)
    tr = _transcript(tmp_path / "t.jsonl", [ELSEWHERE])
    assert "finansirane" not in _stop(tmp_path, tr).get("reason", "")
    other = _task(tmp_path / "b", "finansirane", header="state: active\n")
    _age(other / "LOGBOOK.md", 600)
    tr = _transcript(tmp_path / "b" / "t.jsonl", [("Edit", {"file_path": str(other / "LOGBOOK.md")}, 600, 1)])
    assert "done_when" in _stop(tmp_path / "b", tr).get("reason", ""), "its own is still asked"


# ZA-OPRAVYANE row 165 -- the phase-1 handoff test (16.11), replay case I: a Claude session that
# has made no tool call yet, while another agent (Codex) writes an entry in a task's logbook and
# then a work file after it. The transcript says nothing of whose the file is, and Stop counts
# everything since the start: it hands back the other agent's file. NOT FIXED in v3.36.0, on
# purpose. The narrow fix -- a logbook written after the session began, by a session with no call,
# means another writer, so its newer files go to FOREIGN -- was written and made this test pass,
# and it broke seven older tests (test_declined x2, test_folder_names, test_handback, test_pulled
# x3): each builds a transcript with no tool call and writes the session's own entry after `since`,
# exactly the shape of case I. The comment above session_calls() keeps that fallback, and handing
# back is the cheaper mistake there. Pinned as a strict xfail, so a fix shows itself.
def _entry_by_another(folder: Path, ago: float) -> None:
    book = folder / "LOGBOOK.md"
    book.write_text(book.read_text("utf-8").replace(
        "---\n\n", f"---\n\n## {datetime.now() - timedelta(seconds=ago):%Y-%m-%d %H:%M} — "
        f"another agent's entry\n\n{BODY}Wrote comparison.md.\n\n", 1), "utf-8")
    _age(book, ago)


@pytest.mark.xfail(strict=True, reason="row 165: case I is not fixed in v3.36.0 -- see the comment")
def test_another_agent_s_file_is_not_handed_back_to_a_session_with_no_call(tmp_path):
    folder = _task(tmp_path, "handoff-demo")
    _entry_by_another(folder, 300)
    _work(folder, "comparison.md", age=295)
    out = _stop(tmp_path, _transcript(tmp_path / "t.jsonl", []))
    # The entry names its file, so the hollow check (which still reads any entry written since
    # the session began as this session's -- not changed here) has nothing to say.
    assert out.get("decision") != "block", out
    assert "handoff-demo: comparison.md" in out.get("systemMessage", ""), out


def test_with_no_call_and_no_newer_entry_the_file_is_still_handed_back(tmp_path):
    """The documented fallback stays: no entry since the session began, nothing says whose."""
    folder = _task(tmp_path, "handoff-demo")
    _work(folder, "comparison.md", age=300)
    out = _stop(tmp_path, _transcript(tmp_path / "t.jsonl", []))
    assert out.get("decision") == "block" and "handoff-demo" in out.get("reason", ""), out
