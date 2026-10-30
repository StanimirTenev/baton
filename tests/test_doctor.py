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
HOOKS = ("baton_session_start", "baton_prompt", "baton_stop", "baton_batch", "baton_stop_failure")


def _env(tmp_path, data):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env["BATON_MANAGED_DIR"] = os.environ["BATON_MANAGED_DIR"]   # the test's, not /etc (row 87)
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


def _disabled(tmp_path, files: dict, cwd: str = "proj"):
    """ZA-OPRAVYANE row 78 (Amir Raza, Kumar V., 23.10): `"disableAllHooks": true` silences every
    hook and the doctor said ✅ Running from the heartbeats of the last run. `files` maps a path
    under tmp_path to that file's settings."""
    data = tmp_path / "data"
    subprocess.run([sys.executable, str(ROOT / "hooks" / "baton_session_start.py")],
                   input=b"{}", capture_output=True, env=_env(tmp_path, data))
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    for rel, body in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(json.dumps(body), "utf-8")
    env = dict(_env(tmp_path, data), CLAUDE_CONFIG_DIR=str(tmp_path / "home" / ".claude"),
               BATON_MANAGED_DIR=str(tmp_path / "managed"))
    env.pop("CLAUDE_PROJECT_DIR", None)
    (tmp_path / cwd).mkdir(parents=True, exist_ok=True)
    return subprocess.run([sys.executable, str(ROOT / "tools" / "baton_doctor.py")], cwd=tmp_path / cwd,
                          capture_output=True, text=True, env=env)


def test_switched_off_in_user_settings_is_said_and_not_running(tmp_path):
    out = _disabled(tmp_path, {"home/.claude/settings.json": {"disableAllHooks": True}})
    assert out.returncode == 1, out.stdout
    assert "SWITCHED OFF" in out.stdout and "settings.json (user)" in out.stdout
    assert "✅" not in out.stdout and "⛔ SessionStart" in out.stdout


def test_switched_off_in_local_settings(tmp_path):
    out = _disabled(tmp_path, {"proj/.claude/settings.local.json": {"disableAllHooks": True}})
    assert out.returncode == 1 and "(local)" in out.stdout, out.stdout


def test_a_project_false_overrides_a_user_true(tmp_path):
    out = _disabled(tmp_path, {"home/.claude/settings.json": {"disableAllHooks": True},
                               "proj/.claude/settings.json": {"disableAllHooks": False}})
    assert out.returncode == 0 and "SWITCHED OFF" not in out.stdout, out.stdout
    assert "disableAllHooks: true" in out.stdout and "disableAllHooks: false" in out.stdout


def test_managed_true_wins_over_a_local_false(tmp_path):
    out = _disabled(tmp_path, {"proj/.claude/settings.local.json": {"disableAllHooks": False},
                               "managed/managed-settings.d/10-policy.json": {"disableAllHooks": True}})
    assert out.returncode == 1 and "(managed)" in out.stdout, out.stdout


def test_nothing_set_is_not_mentioned(tmp_path):
    out = _disabled(tmp_path, {"home/.claude/settings.json": {"theme": "dark"}})
    assert out.returncode == 0 and "disableAllHooks" not in out.stdout, out.stdout


def test_the_local_file_at_the_repository_root_from_a_subfolder(tmp_path):
    """In a git repository Claude Code keeps the local file at the root, whatever the folder."""
    (tmp_path / "proj" / ".git").mkdir(parents=True)
    out = _disabled(tmp_path, {"proj/.claude/settings.local.json": {"disableAllHooks": True}},
                    cwd="proj/src/deep")
    assert out.returncode == 1 and "(local)" in out.stdout, out.stdout


def test_the_doctor_run_by_these_tests_reads_the_tests_managed_folder(tmp_path):
    """ZA-OPRAVYANE row 87 (agent, 23.10): _env dropped every BATON_* name, BATON_MANAGED_DIR
    with them, so the doctor these tests start read the machine's own managed settings -- and
    where a policy sets disableAllHooks, every test here that reads its output would fail."""
    managed = Path(os.environ["BATON_MANAGED_DIR"])
    managed.mkdir(parents=True, exist_ok=True)
    (managed / "managed-settings.json").write_text('{"disableAllHooks": true}', "utf-8")
    out = _doctor(tmp_path, tmp_path / "data")
    assert "ALL HOOKS ARE SWITCHED OFF" in out.stdout, out.stdout[-600:]
