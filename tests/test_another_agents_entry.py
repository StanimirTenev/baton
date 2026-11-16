"""ZA-OPRAVYANE row 166: an entry another agent wrote is not judged as this session's.

Found while fixing row 165 (D6): the hollow check, L3 and L4 all read "the logbook's body changed
since this session began" (`_changed_tops`) as "this session wrote its newest entries". Two agents
sharing one logbook break that: Codex writes an entry while a Claude session is open, and the
Claude session's Stop judged Codex's entry -- handed it back as hollow, or asked it for a claims
section -- to an agent that never wrote it. Now a logbook counts as this session's when its tool
calls touched it the way Stop already decides whose a file is (`by_this_session`: a write naming
it, a call naming its folder or running in it, or saved while a shell call ran); a session with no
tool call has written no entry. Without a readable transcript nothing changes. Both hosts, through
the hook.

Two agents in the SAME folder: naming the folder is not enough for the logbook. It is this
session's when a write of its own named the logbook itself, or when it was last saved while one of
this session's calls was running -- so an entry the other agent writes after this session's last
call is the other agent's. Missed, still: the other agent writing while one of this session's shell
calls runs; and a logbook this session edited with Write/Edit and the other agent wrote after it.
And this session's own entry under the other's is then not judged at all.
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
HOOK = ROOT / "hooks" / "baton_stop.py"
FIXTURES = ROOT / "tests" / "fixtures" / "codex"
BODY = "".join(f"### {s}\n{s}: a full sentence about the work, long enough to count as said.\n"
               for s in ("What was asked", "Done", "Result", "Open"))
HOLLOW = "### Done\nok\n"                                          # one section, a few characters
PUBLIC = BODY + "The repository is public now.\n"                  # L3, no claims section
PASSING = BODY + "All tests pass.\n"                               # L4, no claims section
ELSEWHERE = ("Bash", {"command": "ls /etc"}, 1200, 1)             # a call, not in the task


def _ts(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def _age(path: Path, seconds: float) -> None:
    t = time.time() - seconds
    os.utime(path, (t, t))


def _task(tasks: Path, name: str, body: str, ago: float = 300) -> Path:
    """A task whose logbook got an entry `ago` seconds ago, above one from three hours before."""
    folder = tasks / name
    folder.mkdir(parents=True)
    book = folder / "LOGBOOK.md"
    book.write_text(
        f"---\ndone_when: shipped\n---\n\n"
        f"## {datetime.now() - timedelta(seconds=ago):%Y-%m-%d %H:%M} — the newest entry\n\n{body}\n"
        f"## {datetime.now() - timedelta(hours=3):%Y-%m-%d %H:%M} — e\n\n{BODY}", "utf-8")
    _age(book, ago)
    return folder


def _claude(path: Path, calls: list) -> str:
    """A Claude Code session begun 30 minutes ago; `calls` are (tool, input, seconds ago, seconds run)."""
    rows = [{"type": "user", "timestamp": _ts(time.time() - 1800), "cwd": str(path.parent),
             "message": {"role": "user", "content": "go on"}}]
    for i, (tool, args, ago, ran) in enumerate(calls):
        rows.append({"type": "assistant", "timestamp": _ts(time.time() - ago), "cwd": "/",
                     "message": {"content": [{"type": "tool_use", "id": f"t{i}", "name": tool, "input": args}]}})
        rows.append({"type": "user", "timestamp": _ts(time.time() - ago + ran),
                     "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "ok"}]}})
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", "utf-8")
    return str(path)


def _run(tmp_path: Path, payload: dict) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_HOME", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               HOME=str(tmp_path / "home"), BATON_STATE_DIR=str(tmp_path / "state"))
    out = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, env=env,
                         input=json.dumps(payload))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def _stop_claude(tmp_path: Path, calls: list) -> dict:
    return _run(tmp_path, {"session_id": "s", "transcript_path": _claude(tmp_path / "s.jsonl", calls)})


def _stop_codex(tmp_path: Path, command: str, ago: float = 1200) -> dict:
    """A Codex session begun 30 minutes ago with one exec call, `ago` seconds ago, two seconds long."""
    payload = json.loads((FIXTURES / "stop.json").read_text("utf-8"))
    sid = payload["session_id"]
    rollout = tmp_path / "sessions" / f"rollout-2026-11-14T11-09-33-{sid}.jsonl"
    rollout.parent.mkdir()
    now, cwd = time.time(), tmp_path / "proj"
    cwd.mkdir()
    rows = [("session_meta", now - 1800, {"id": sid, "cwd": str(cwd)}),
            ("turn_context", now - 1799, {"cwd": str(cwd)}),
            ("response_item", now - ago, {"type": "custom_tool_call", "name": "exec", "call_id": "c1",
             "input": f'await tools.exec_command({{cmd: {json.dumps(command)}}});'}),
            ("response_item", now - ago + 2, {"type": "custom_tool_call_output", "call_id": "c1", "output": ""})]
    rollout.write_text("".join(json.dumps({"timestamp": _ts(t), "ordinal": i, "type": k, "payload": p}) + "\n"
                               for i, (k, t, p) in enumerate(rows)), "utf-8")
    payload.update(transcript_path=str(rollout), cwd=str(cwd))
    return _run(tmp_path, payload)


def _judged(out: dict, folder: str) -> bool:
    return folder in out.get("reason", "") or folder in out.get("systemMessage", "")


CASES = {"hollow": HOLLOW, "L3": PUBLIC, "L4": PASSING}


@pytest.mark.parametrize("case", sorted(CASES))
@pytest.mark.parametrize("who", ["no-call", "elsewhere"])
def test_claude_another_agent_s_entry_is_not_judged_by_a_session_that_never_touched_it(tmp_path, case, who):
    _task(tmp_path / "tasks", "handoff-demo", CASES[case])
    out = _stop_claude(tmp_path, [] if who == "no-call" else [ELSEWHERE])
    assert out.get("decision") != "block" and not _judged(out, "handoff-demo"), out


@pytest.mark.parametrize("case", sorted(CASES))
def test_claude_the_session_s_own_entry_is_still_judged(tmp_path, case):
    folder = _task(tmp_path / "tasks", "handoff-demo", CASES[case])
    call = ("Bash", {"command": f'python3 tools/baton_entry.py "{folder / "LOGBOOK.md"}" e.md'}, 301, 2)
    out = _stop_claude(tmp_path, [call])
    assert out.get("decision") == "block" and "handoff-demo" in out.get("reason", ""), out


@pytest.mark.parametrize("case", sorted(CASES))
def test_codex_another_agent_s_entry_is_not_judged(tmp_path, case):
    _task(tmp_path / "tasks", "handoff-demo", CASES[case])
    out = _stop_codex(tmp_path, "ls /etc")
    assert out.get("decision") != "block" and not _judged(out, "handoff-demo"), out


@pytest.mark.parametrize("case", sorted(CASES))
def test_codex_the_session_s_own_entry_is_still_judged(tmp_path, case):
    folder = _task(tmp_path / "tasks", "handoff-demo", CASES[case])
    out = _stop_codex(tmp_path, f'python3 baton_entry.py "{folder / "LOGBOOK.md"}" e.md', ago=301)
    assert out.get("decision") == "block" and "handoff-demo" in out.get("reason", ""), out


@pytest.mark.parametrize("case", sorted(CASES))
def test_claude_in_the_same_folder_the_other_agent_s_later_entry_is_not_judged(tmp_path, case):
    """Both wrote in handoff-demo: this session at 1200 s ago, the other agent at 300 s ago."""
    folder = _task(tmp_path / "tasks", "handoff-demo", CASES[case])
    call = ("Bash", {"command": f'python3 tools/baton_entry.py "{folder / "LOGBOOK.md"}" e.md'}, 1200, 2)
    out = _stop_claude(tmp_path, [call])
    assert out.get("decision") != "block" and not _judged(out, "handoff-demo"), out


@pytest.mark.parametrize("case", sorted(CASES))
def test_codex_in_the_same_folder_the_other_agent_s_later_entry_is_not_judged(tmp_path, case):
    folder = _task(tmp_path / "tasks", "handoff-demo", CASES[case])
    out = _stop_codex(tmp_path, f'python3 baton_entry.py "{folder / "LOGBOOK.md"}" e.md', ago=1200)
    assert out.get("decision") != "block" and not _judged(out, "handoff-demo"), out


@pytest.mark.parametrize("case", sorted(CASES))
def test_claude_an_edit_of_the_logbook_itself_is_this_session_s(tmp_path, case):
    """The Edit tool names the logbook: judged, whenever it was saved (an Edit has no window)."""
    folder = _task(tmp_path / "tasks", "handoff-demo", CASES[case])
    out = _stop_claude(tmp_path, [("Edit", {"file_path": str(folder / "LOGBOOK.md")}, 1200, 1)])
    assert out.get("decision") == "block" and "handoff-demo" in out.get("reason", ""), out


def _typed_by_hand(tmp_path: Path, calls: list) -> dict:
    """L1: Stop has seen the logbook once; then an entry headed two hours off the clock lands."""
    folder = _task(tmp_path / "tasks", "handoff-demo", BODY, ago=4000)
    first = tmp_path / "first.jsonl"
    _run(tmp_path, {"session_id": "s0", "transcript_path": _claude(first, [])})   # remembers the top
    book = folder / "LOGBOOK.md"
    head, rest = book.read_text("utf-8").split("\n\n", 1)
    book.write_text(f"{head}\n\n## {datetime.now() - timedelta(hours=2):%Y-%m-%d %H:%M} — typed\n\n"
                    f"{BODY}\n{rest}", "utf-8")
    _age(book, 300)
    return _stop_claude(tmp_path, calls)


def test_l1_another_agent_s_hand_typed_hour_is_not_this_session_s(tmp_path):
    out = _typed_by_hand(tmp_path, [ELSEWHERE])
    assert "behind the clock" not in json.dumps(out, ensure_ascii=False), out


def test_l1_the_session_s_own_hand_typed_hour_is_still_said(tmp_path):
    call = ("Bash", {"command": "python3 write.py LOGBOOK.md"}, 301, 2)     # running when it was saved
    out = _typed_by_hand(tmp_path, [call])
    assert "behind the clock" in json.dumps(out, ensure_ascii=False), out
