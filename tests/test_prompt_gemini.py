"""The prompt hook's task pointer reaches the model under Gemini CLI too.

Gemini turns plain stdout into `{decision: "allow", systemMessage: <text>}`: the human sees it in
the interactive CLI, nobody sees it headless, and the model never does (hookRunner, bundle
chunk-RCB6BI5H.js:366815-366822; only `additionalContext` is added to the request, client
:349256-349258). The fixture run of 16.11.2026 (faza2/GEMINI-FIXTURE.md, case 02) showed exactly
that. Under Gemini the pointer goes out as `hookSpecificOutput.additionalContext`; Claude Code and
Codex keep the plain text they had, byte for byte.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_prompt.py"
GEMINI = json.loads((ROOT / "tests" / "fixtures" / "gemini" / "before_agent.json").read_text("utf-8"))
CODEX = json.loads((ROOT / "tests" / "fixtures" / "codex" / "user_prompt_submit.json").read_text("utf-8"))


def _task(root: Path, name: str = "alpha"):
    (root / name).mkdir(parents=True)
    (root / name / "LOGBOOK.md").write_text(
        "---\nstate: active\nnext: \"write the notes\"\n---\n\n## 2026-11-16 14:02 — Started alpha\n\nx\n",
        encoding="utf-8")


def _run(root: Path, payload: dict) -> str:
    env = {"BATON_HOME": str(root), "BATON_LOGBOOK": "LOGBOOK.md",
           "BATON_STATE_DIR": str(root / ".state"), "PATH": "/usr/bin:/bin"}
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                         text=True, env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout


def _plain(root: Path) -> str:
    """What Claude Code gets for the same prompt: the reference text."""
    return _run(root, {"session_id": "claude-1", "prompt": GEMINI["prompt"]})


def test_under_gemini_the_pointer_is_additional_context(tmp_path):
    _task(tmp_path)
    out = _run(tmp_path, GEMINI)
    doc = json.loads(out)                    # one JSON object, nothing else on stdout
    hso = doc["hookSpecificOutput"]
    assert hso["hookEventName"] == "BeforeAgent"
    assert hso["additionalContext"] + "\n" == _plain(tmp_path)
    assert "alpha" in hso["additionalContext"] and "write the notes" in hso["additionalContext"]
    assert set(doc) == {"hookSpecificOutput"}, "no systemMessage: on Claude Code the pointer is for the agent only"


def test_under_gemini_silence_stays_silence(tmp_path):
    _task(tmp_path)
    assert _run(tmp_path, dict(GEMINI, prompt="What time is it?")) == ""


def test_under_codex_the_pointer_stays_plain_text(tmp_path):
    """Pinned before the Gemini change: Codex reads plain stdout as context (live probe, 14.11)."""
    _task(tmp_path)
    out = _run(tmp_path, dict(CODEX, prompt=GEMINI["prompt"]))
    assert out == _plain(tmp_path)
    assert out.startswith("Baton: this message touches a task with a record.")


def test_under_an_unknown_host_the_pointer_stays_plain_text(tmp_path):
    _task(tmp_path)
    out = _run(tmp_path, {"prompt": GEMINI["prompt"], "session_id": "s9",
                          "transcript_path": "/tmp/proj/b.jsonl"})
    assert out.startswith("Baton: this message touches a task with a record.")
    assert "hookSpecificOutput" not in out
