"""#2: the optional review is offered once -- with its cost and what it sends -- never run.

Through the hook's entry point, as the harness runs it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_session_start.py"


def _run(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tasks").mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), BATON_HOME=str(tmp_path / "tasks"),
               BATON_SESSION_STATE=str(tmp_path / "s.json"))
    out = subprocess.run([sys.executable, str(HOOK)], input=b'{"source":"startup"}',
                         capture_output=True, env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout).get("hookSpecificOutput", {}).get("additionalContext", "")


def test_offered_on_the_first_run_with_cost_and_what_is_sent(tmp_path):
    ctx = _run(tmp_path)
    assert "optional review" in ctx
    assert "SENDS" in ctx and "OpenRouter" in ctx and "$0.0013" in ctx
    assert "/baton-key" in ctx and "never runs by itself" in ctx


def test_offered_only_once(tmp_path):
    _run(tmp_path)
    assert "optional review" not in _run(tmp_path)


def test_not_offered_when_a_key_is_already_stored(tmp_path):
    env_file = tmp_path / "home" / ".config" / "baton" / "env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("OPENROUTER_API_KEY=x\n", "utf-8")
    assert "optional review" not in _run(tmp_path)
