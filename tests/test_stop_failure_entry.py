"""ZA-OPRAVYANE row 186 (18.11): a turn that ends on an API error or a spent quota leaves a short
entry in the logbook of the task it worked on, so another session or agent can go on from there.

StopFailure runs instead of Stop then (code.claude.com/docs/en/hooks), and until now it only
recorded the beat. Now it writes `## <now> — turn ended on <error>` with the files written in that
turn -- only when the turn can be tied to exactly one task folder, never to a guessed one. The stub
is not the entry for the work: Stop and the board must still ask for it.

Run the way the harness runs it: a subprocess with the hook's JSON on stdin.
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
HOOK = ROOT / "hooks" / "baton_stop_failure.py"
OLD = "## 2026-09-01 10:00 — the first invoice\n\nWrote the first invoice.\n"


def _stop_module():
    spec = importlib.util.spec_from_file_location("bs_failure", ROOT / "hooks" / "baton_stop.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bs_failure"] = mod
    spec.loader.exec_module(mod)
    return mod


def _task(root: Path, name: str) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    book = folder / "LOGBOOK.md"
    book.write_text("---\nstate: active\n---\n\n" + OLD, "utf-8")
    then = time.time() - 7200
    os.utime(book, (then, then))
    return folder


def _transcript(tmp_path, *paths: Path, bash: str = "") -> Path:
    """A Claude Code transcript: the human's message, then this turn's Write calls."""
    now = datetime.now(timezone.utc)
    rows = [{"type": "user", "timestamp": (now - timedelta(minutes=20)).isoformat(),
             "message": {"role": "user", "content": "finish the invoice"}}]
    blocks = [{"type": "tool_use", "id": f"w{i}", "name": "Write",
               "input": {"file_path": str(p), "content": "x"}} for i, p in enumerate(paths)]
    if bash:
        blocks.append({"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": bash}})
    rows.append({"type": "assistant", "timestamp": (now - timedelta(minutes=15)).isoformat(),
                 "message": {"role": "assistant", "content": blocks}})
    tr = tmp_path / "session.jsonl"
    tr.write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("draft\n", "utf-8")
        os.utime(p, (time.time() - 600,) * 2)          # in the turn, past Stop's grace
    return tr


def _env(tmp_path) -> dict:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               CLAUDE_PLUGIN_ROOT=str(ROOT), CLAUDE_PLUGIN_DATA=str(tmp_path / "data"),
               BATON_SESSION_STATE=str(tmp_path / "s.json"),
               BATON_BODY_STATE=str(tmp_path / "bodies.json"),
               BATON_LESSONS_STATE=str(tmp_path / "lessons.json"))
    return env


def _fail(tmp_path, transcript: Path | None, error: str = "rate_limit"):
    payload = {"session_id": "s1", "hook_event_name": "StopFailure", "error": error}
    if transcript is not None:
        payload["transcript_path"] = str(transcript)
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload).encode("utf-8"),
                         capture_output=True, env=_env(tmp_path))
    assert out.returncode == 0, out.stderr
    assert out.stdout == b"", out.stdout            # Claude Code ignores it; nothing is printed


def test_a_turn_ended_on_an_api_error_leaves_a_stub_in_its_task(tmp_path):
    folder = _task(tmp_path / "tasks", "invoice")
    _fail(tmp_path, _transcript(tmp_path, folder / "invoice.md", folder / "out" / "total.csv"))
    text = (folder / "LOGBOOK.md").read_text("utf-8")
    top = text.split("\n## ")[1]
    assert f"{datetime.now():%Y-%m-%d}" in top and "turn ended on rate_limit" in top, text
    assert "invoice.md" in top and "out/total.csv" in top, top
    assert OLD in text and text.startswith("---\nstate: active\n---\n"), text


def test_the_stub_does_not_count_as_the_entry_for_the_work(tmp_path, monkeypatch):
    """The trap: a new top entry moves the logbook's recorded time past the work, and Stop and the
    board would stop asking for the real entry."""
    folder = _task(tmp_path / "tasks", "invoice")
    _fail(tmp_path, _transcript(tmp_path, folder / "invoice.md"))
    assert "turn ended on" in (folder / "LOGBOOK.md").read_text("utf-8")
    monkeypatch.setenv("BATON_BODY_STATE", str(tmp_path / "bodies.json"))
    monkeypatch.setenv("BATON_LESSONS_STATE", str(tmp_path / "lessons.json"))
    bs = _stop_module()
    assert any("invoice" in f for f in bs.unrecorded(tmp_path / "tasks", "LOGBOOK.md")), \
        "the stub was taken for the entry"


def test_a_turn_in_two_task_folders_writes_nowhere(tmp_path):
    a, b = _task(tmp_path / "tasks", "invoice"), _task(tmp_path / "tasks", "report")
    _fail(tmp_path, _transcript(tmp_path, a / "invoice.md", b / "report.md"))
    for f in (a, b):
        assert "turn ended" not in (f / "LOGBOOK.md").read_text("utf-8")


def test_a_turn_tied_to_no_task_writes_nowhere(tmp_path):
    folder = _task(tmp_path / "tasks", "invoice")
    _fail(tmp_path, _transcript(tmp_path, tmp_path / "elsewhere" / "notes.md"))
    assert "turn ended" not in (folder / "LOGBOOK.md").read_text("utf-8")


def test_without_a_transcript_nothing_is_written(tmp_path):
    folder = _task(tmp_path / "tasks", "invoice")
    _fail(tmp_path, None)
    assert "turn ended" not in (folder / "LOGBOOK.md").read_text("utf-8")


def test_a_shell_call_in_the_folder_ties_the_turn_to_it(tmp_path):
    folder = _task(tmp_path / "tasks", "invoice")
    _fail(tmp_path, _transcript(tmp_path, bash=f"cd {folder} && make total"))
    top = (folder / "LOGBOOK.md").read_text("utf-8").split("\n## ")[1]
    assert "turn ended on rate_limit" in top, top


def test_the_same_failure_again_is_not_written_twice(tmp_path):
    """A spent quota fails every retry; one stub says it."""
    folder = _task(tmp_path / "tasks", "invoice")
    tr = _transcript(tmp_path, folder / "invoice.md")
    _fail(tmp_path, tr)
    _fail(tmp_path, tr)
    assert (folder / "LOGBOOK.md").read_text("utf-8").count("— turn ended on") == 1
