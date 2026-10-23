"""ZA-OPRAVYANE row 67 (swarm D, 22.10; probe G14): stdin that is valid JSON but not an object
crashed three of the four hooks.

SessionStart checked `isinstance(payload, dict)`; Stop, UserPromptSubmit and PostToolBatch called
`payload.get(...)` straight after json.load -- and PostToolBatch `c.get` on each tool call. Each
exited 0 with a `.crashed` marker, so that turn's check did not happen. Now a payload of another
shape is no payload, and a tool call of another shape is skipped.
"""
from __future__ import annotations

import json
import time
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _env(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"),
               BATON_HOME=str(tmp_path / "tasks"), CLAUDE_PLUGIN_DATA=str(tmp_path / "data"),
               BATON_STATE_DIR=str(tmp_path / "state"),
               BATON_LESSONS_STATE=str(tmp_path / "data" / "baton.lessons.json"),
               BATON_BODY_STATE=str(tmp_path / "data" / "baton.bodies.json"))
    (tmp_path / "tasks").mkdir(exist_ok=True)
    return env


def _run(tmp_path, hook, raw: bytes):
    out = subprocess.run([sys.executable, str(ROOT / "hooks" / f"{hook}.py")], input=raw,
                         capture_output=True, env=_env(tmp_path))
    assert out.returncode == 0 and out.stderr == b"", out.stderr
    marker = tmp_path / "data" / f"baton.beat.{hook}.crashed"
    assert not marker.exists(), f"{hook} crashed on {raw!r}: {marker.read_text('utf-8')}"
    return out


@pytest.mark.parametrize("hook", ["baton_stop", "baton_prompt", "baton_batch"])
@pytest.mark.parametrize("raw", [b"[]", b'"x"', b"null", b"42"], ids=lambda r: r.decode())
def test_a_payload_that_is_not_an_object_is_no_payload(tmp_path, hook, raw):
    _run(tmp_path, hook, raw)


@pytest.mark.parametrize("calls", ["grep x", ["grep x"], [None], [1]])
def test_tool_calls_of_another_shape_are_skipped(tmp_path, calls):
    _run(tmp_path, "baton_batch", json.dumps({"session_id": "s", "tool_calls": calls}).encode())


def test_a_good_call_beside_a_bad_one_still_counts(tmp_path):
    call = {"tool_name": "Bash", "tool_input": {"command": "grep -rn Featured page.html"},
            "tool_response": "(Bash completed with no output)"}
    out = _run(tmp_path, "baton_batch",
               json.dumps({"session_id": "s", "tool_calls": [None, "x", call]}).encode())
    assert "lesson L2" in out.stdout.decode("utf-8")


@pytest.mark.parametrize("raw", [b"[]", b"null", b"{", b""], ids=["list", "null", "broken", "empty"])
def test_stop_without_an_object_runs_nothing(tmp_path, raw):
    """ZA-OPRAVYANE row 70 (22.10): Stop read such stdin as `{}` and went on -- no session start,
    so every folder's work older than this session was handed back to this turn."""
    folder = tmp_path / "tasks" / "old-debt"
    folder.mkdir(parents=True)
    (folder / "LOGBOOK.md").write_text("## 2026-10-01 10:00 — start\n", "utf-8")
    work = folder / "draft.md"
    work.write_text("x\n", "utf-8")
    t = time.time() - 3600
    os.utime(folder / "LOGBOOK.md", (t - 60, t - 60))
    os.utime(work, (t, t))
    out = _run(tmp_path, "baton_stop", raw)
    assert out.stdout == b"", out.stdout
    # The control: an object without a transcript is still read as before.
    assert b'"block"' in _run(tmp_path, "baton_stop", b"{}").stdout
