"""Codex's rollout transcript: whose work a file is, and how big the context is.

Under Codex, Stop read the rollout with Claude Code's reader, found no `"type":"tool_use"`, and
fell back to "everything since the session began is this session's" -- in the live probe of
14.11 (Codex CLI 0.169.0, run r4) it handed back `ptica-proba/bird.txt`, which another process
wrote. The prompt hook's context count read 0. Now the rollout is read by _baton.codex_calls and
_baton.codex_context_tokens when host() says Codex; Claude Code's readers are unchanged.

tests/fixtures/codex/rollout-*.jsonl is built, not copied: the real rollout carries account ids
and was not kept. Observed in the probe: the line envelope `{timestamp, ordinal, type, payload}`,
the line types, and that calls are `custom_tool_call` `exec` and `function_call` `wait`, each
with a `*_output`. Reconstructed from Codex's own field names (its binary): `name`, `input`,
`arguments`, `call_id`, `turn_context.cwd`, `token_count.info.last_token_usage.input_tokens`, and
the JavaScript `exec` input with `tools.exec_command` / `tools.apply_patch` inside. One live
rollout should confirm them; until then this pins what Baton reads, not what Codex writes.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
FIXTURES = ROOT / "tests" / "fixtures" / "codex"
ROLLOUT = next(FIXTURES.glob("rollout-*.jsonl"))
BODY = "".join(f"### {s}\n{s}: a full sentence about the work, long enough to count as said.\n"
               for s in ("What was asked", "Done", "Result", "Open"))


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HOOKS / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_calls_of_a_codex_session_are_read_from_its_rollout():
    core = _load("_baton_rollout", "_baton.py")
    calls = core.codex_calls(str(ROLLOUT))
    assert calls["files"] == {
        os.path.normcase("/work/codex-probe/tasks/kotka-proba/LOGBOOK.md"),   # inside exec's script
        os.path.normcase("/work/codex-probe/tasks/riba-proba/notes.md"),      # relative, own call
    }
    assert any("cat /work/codex-probe/tasks/kotka-proba/LOGBOOK.md" in t for t in calls["texts"])
    assert not any("fish" in t for t in calls["texts"]), "an apply_patch alone is a write, not a text"
    assert calls["cwds"] == {os.path.normcase("/work/codex-probe/proj")}
    assert len(calls["windows"]) == 3 and all(a <= b for a, b in calls["windows"])


def test_the_context_count_of_a_codex_session_is_its_last_request():
    core = _load("_baton_rollout", "_baton.py")
    assert core.codex_context_tokens(str(ROLLOUT), 1 << 20) == 234567


def test_claude_code_s_readers_are_unchanged_on_a_rollout():
    """What an unknown host gets: today's behaviour, nothing read."""
    stop = _load("bs_rollout", "baton_stop.py")
    assert stop.HOST == "unknown"
    assert stop.session_calls(str(ROLLOUT)) is None
    prompt = _load("bp_rollout", "baton_prompt.py")
    assert prompt.context_tokens(str(ROLLOUT)) == 0


def test_stop_picks_the_reader_by_host():
    stop = _load("bs_rollout2", "baton_stop.py")
    stop.HOST = "codex"
    assert stop.session_calls(str(ROLLOUT))["files"], "the Codex reader"


def test_a_reader_that_cannot_read_says_none():
    core = _load("_baton_rollout", "_baton.py")
    assert core.codex_calls("/nonexistent/rollout.jsonl") is None
    assert core.codex_context_tokens("/nonexistent/rollout.jsonl", 1024) == 0


# Through the hook: the shape of the probe's r4 -- a file another process wrote, in a folder no
# call named. In r4 itself bird.txt was saved 1.3 s before the `sleep` call began, inside
# CALL_SLACK_S, so that very timing would still be handed back; here it is outside every call.

def _ts(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def _age(path: Path, seconds: float) -> None:
    t = time.time() - seconds
    os.utime(path, (t, t))


def _task(tasks: Path, name: str) -> Path:
    folder = tasks / name
    folder.mkdir(parents=True)
    book = folder / "LOGBOOK.md"
    book.write_text(f"---\ndone_when: shipped\n---\n\n## {datetime.now() - timedelta(hours=3):%Y-%m-%d %H:%M}"
                    f" — e\n\n{BODY}", "utf-8")
    _age(book, 3 * 3600)
    return folder


def _work(folder: Path, rel: str, age: float) -> None:
    path = folder / rel
    path.write_text("x", "utf-8")
    _age(path, age)


def _rollout(path: Path, tasks: Path, cwd: Path) -> None:
    """A session begun 30 minutes ago: an exec that writes into kotka-proba (900 s ago, 2 s), and
    an apply_patch of its own that adds riba-proba/notes.md by a relative path (800 s ago)."""
    now = time.time()
    rows = [("session_meta", now - 1800, {"id": "s", "cwd": str(cwd)}),
            ("turn_context", now - 1799, {"cwd": str(cwd)}),
            ("response_item", now - 900, {"type": "custom_tool_call", "name": "exec", "call_id": "c1",
             "input": f'await tools.exec_command({{cmd: "echo work > {tasks}/kotka-proba/cat.txt"}});'}),
            ("response_item", now - 898, {"type": "custom_tool_call_output", "call_id": "c1", "output": ""}),
            ("response_item", now - 800, {"type": "custom_tool_call", "name": "apply_patch", "call_id": "c2",
             "input": f"*** Begin Patch\n*** Add File: {os.path.relpath(tasks, cwd)}/riba-proba/notes.md"
                      "\n+fish\n*** End Patch"}),
            ("response_item", now - 799, {"type": "custom_tool_call_output", "call_id": "c2", "output": ""})]
    path.write_text("".join(json.dumps({"timestamp": _ts(t), "ordinal": i, "type": k, "payload": p}) + "\n"
                            for i, (k, t, p) in enumerate(rows)), "utf-8")


def test_a_file_another_process_wrote_is_not_handed_back_to_codex(tmp_path):
    tasks, cwd = tmp_path / "tasks", tmp_path / "proj"
    cwd.mkdir()
    _work(_task(tasks, "kotka-proba"), "cat.txt", 899)
    _work(_task(tasks, "riba-proba"), "notes.md", 800)
    _work(_task(tasks, "ptica-proba"), "bird.txt", 600)        # no call of this session, none running
    payload = json.loads((FIXTURES / "stop.json").read_text("utf-8"))
    sid = payload["session_id"]
    rollout = tmp_path / "sessions" / f"rollout-2026-11-14T11-09-33-{sid}.jsonl"
    rollout.parent.mkdir()
    _rollout(rollout, tasks, cwd)
    payload.update(transcript_path=str(rollout), cwd=str(cwd))
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_HOME", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(BATON_HOME=str(tasks), BATON_LOGBOOK="LOGBOOK.md", HOME=str(tmp_path / "home"),
               BATON_STATE_DIR=str(tmp_path / "state"))
    out = subprocess.run([sys.executable, str(HOOKS / "baton_stop.py")], capture_output=True,
                         text=True, env=env, input=json.dumps(payload))
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    reason = got.get("reason", "")
    assert got.get("decision") == "block", got
    assert "kotka-proba" in reason and "riba-proba" in reason, reason
    assert "ptica-proba" not in reason, "another process's file: said once, not handed back"
    assert "bird.txt" in got.get("systemMessage", ""), got


def test_a_long_codex_session_gets_the_restart_reminder(tmp_path):
    """The probe: under Codex the reminder never came, the count read 0."""
    payload = json.loads((FIXTURES / "user_prompt_submit.json").read_text("utf-8"))
    payload.update(transcript_path=str(ROLLOUT), prompt="hello")       # 234567 tokens, over 200k
    env = {"BATON_HOME": str(tmp_path), "BATON_LOGBOOK": "LOGBOOK.md",
           "BATON_STATE_DIR": str(tmp_path / ".state"), "PATH": "/usr/bin:/bin"}
    out = subprocess.run([sys.executable, str(HOOKS / "baton_prompt.py")], input=json.dumps(payload),
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    assert "234k" in out.stdout or "235k" in out.stdout, out.stdout
