"""#9: each hook leaves a heartbeat; /baton-doctor tells "installed" from "running".

Through the entry points the harness uses: each hook as a subprocess with JSON on stdin, the
doctor as a subprocess. The failure this exists for is a plugin that is enabled and silent.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ("baton_session_start", "baton_prompt", "baton_stop", "baton_batch")


def _env(tmp_path, data):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), BATON_HOME=str(tmp_path / "tasks"),
               CLAUDE_PLUGIN_ROOT=str(ROOT), CLAUDE_PLUGIN_DATA=str(data))
    return env


def _doctor(tmp_path, data):
    return subprocess.run([sys.executable, str(ROOT / "tools" / "baton_doctor.py")],
                          capture_output=True, text=True, env=_env(tmp_path, data))


def test_every_hook_leaves_a_heartbeat_when_it_runs(tmp_path):
    data = tmp_path / "data"
    for hook in HOOKS:
        out = subprocess.run([sys.executable, str(ROOT / "hooks" / f"{hook}.py")],
                             input=b"{}", capture_output=True, env=_env(tmp_path, data))
        assert out.returncode == 0, (hook, out.stderr)
        assert (data / f"baton.beat.{hook}").is_file(), hook


def test_doctor_says_installed_but_not_running_when_nothing_ran(tmp_path):
    out = _doctor(tmp_path, tmp_path / "empty")
    assert out.returncode == 1
    assert "Installed but not running" in out.stdout


def test_doctor_says_running_after_sessionstart_ran(tmp_path):
    data = tmp_path / "data"
    subprocess.run([sys.executable, str(ROOT / "hooks" / "baton_session_start.py")],
                   input=b"{}", capture_output=True, env=_env(tmp_path, data))
    out = _doctor(tmp_path, data)
    assert out.returncode == 0, out.stdout
    assert "Running" in out.stdout
    # Stop and PostToolBatch have not had their moment yet: that is not a failure, and a
    # fresh install must not be told NEVER RAN (seen live on 05.10, before release).
    assert "NEVER RAN" not in out.stdout and "❌" not in out.stdout
    assert "not yet" in out.stdout and "PostToolBatch" in out.stdout


def test_doctor_finds_the_plugin_heartbeats_when_the_variable_arrives_empty(tmp_path):
    """The skill passes CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}"; if Claude Code did not fill
    it in, the shell makes it "" -- and a working plugin must not be called not running."""
    data = tmp_path / "home" / ".claude" / "plugins" / "data" / "baton-baton"
    subprocess.run([sys.executable, str(ROOT / "hooks" / "baton_session_start.py")],
                   input=b"{}", capture_output=True, env=_env(tmp_path, data))
    env = _env(tmp_path, "")
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "baton_doctor.py")],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stdout
    assert "baton-baton" in out.stdout and "Running" in out.stdout
