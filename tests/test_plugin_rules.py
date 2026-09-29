"""install.sh appends Baton's rules to ~/.claude/CLAUDE.md -- the fallback that holds even
where a hook does not. A plugin's CLAUDE.md is not loaded, so installed as a plugin the rules
would never reach the agent. SessionStart carries them instead, in plugin mode only, and
not when the installer has already put them in CLAUDE.md."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_session_start.py"
RULE = "Before starting work on a task"


def _run(tmp_path, *, plugin=True, claude_md=None, task=True):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    if claude_md is not None:
        (home / ".claude" / "CLAUDE.md").write_text(claude_md, encoding="utf-8")
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    if task:
        (tasks / "a").mkdir()
        (tasks / "a" / "LOGBOOK.md").write_text("## 2026-09-01 10:00 — a\n\ntext\n", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), BATON_HOME=str(tasks), BATON_LOGBOOK="LOGBOOK.md")
    if plugin:
        env.update(CLAUDE_PLUGIN_ROOT=str(ROOT), CLAUDE_PLUGIN_DATA=str(data))
    out = subprocess.run([sys.executable, str(HOOK)], input="{}", capture_output=True,
                         text=True, env=env)
    assert out.returncode == 0, out.stderr
    if not out.stdout.strip():
        return ""
    return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]


def test_as_a_plugin_the_rules_reach_the_agent(tmp_path):
    context = _run(tmp_path)
    assert RULE in context
    assert str(tmp_path / "tasks") in context, "the real task folder is named"


def test_a_new_user_with_an_empty_folder_gets_the_rules_too(tmp_path):
    assert RULE in _run(tmp_path, task=False)


def test_rules_the_installer_already_wrote_are_not_repeated(tmp_path):
    installed = (ROOT / "templates" / "CLAUDE.md").read_text(encoding="utf-8")
    assert RULE not in _run(tmp_path, claude_md="# mine\n\n" + installed)


def test_installed_by_the_script_nothing_is_added(tmp_path):
    assert RULE not in _run(tmp_path, plugin=False)


def test_the_marker_is_looked_for_in_claude_config_dir(tmp_path):
    installed = (ROOT / "templates" / "CLAUDE.md").read_text(encoding="utf-8")
    home = tmp_path / "home" / ".claude"
    home.mkdir(parents=True)
    (home / "CLAUDE.md").write_text(installed, encoding="utf-8")   # another config's rules
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(tmp_path / "home"), CLAUDE_CONFIG_DIR=str(cfg), BATON_HOME=str(tasks),
               CLAUDE_PLUGIN_ROOT=str(ROOT), CLAUDE_PLUGIN_DATA=str(tmp_path / "data"))
    out = subprocess.run([sys.executable, str(HOOK)], input="{}", capture_output=True, text=True, env=env)
    assert RULE in out.stdout, "this session's config has no rules, so the plugin brings them"


def _plugin_env(tmp_path, claude_md: bytes):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "CLAUDE.md").write_bytes(claude_md)
    tasks = tmp_path / "tasks"
    (tasks / "a").mkdir(parents=True)
    (tasks / "a" / "LOGBOOK.md").write_text("## 2026-09-01 10:00 — a\n\ntext\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BATON_", "CLAUDE_"))}
    env.update(HOME=str(tmp_path / "home"), CLAUDE_CONFIG_DIR=str(cfg), BATON_HOME=str(tasks),
               CLAUDE_PLUGIN_ROOT=str(ROOT), CLAUDE_PLUGIN_DATA=str(tmp_path / "data"))
    out = subprocess.run([sys.executable, str(HOOK)], input="{}", capture_output=True, text=True, env=env)
    return out


def test_a_claude_md_that_is_not_utf8_does_not_wipe_the_board(tmp_path):
    """Found by review of 3.8.0: an undecodable CLAUDE.md raised out of plugin_rules and the
    whole board was lost (the hook exits 0 in silence). PowerShell 5 writes UTF-16 by default;
    older files are often cp1251."""
    out = _plugin_env(tmp_path, b"\xe0\xe1\xe2 cp1251 text\n")
    assert out.returncode == 0 and '"a"' not in out.stderr
    assert "a — last entry" in json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]


def test_the_marker_is_found_in_a_utf16_claude_md(tmp_path):
    installed = (ROOT / "templates" / "CLAUDE.md").read_text(encoding="utf-8")
    out = _plugin_env(tmp_path, installed.encode("utf-16"))
    assert RULE not in json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
