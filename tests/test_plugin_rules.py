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
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN"))}
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
