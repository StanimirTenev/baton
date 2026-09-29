"""Installed by install.sh AND as a plugin, every hook would run twice: two boards, two
hand-backs, two reminders. The plugin's copy notices the installer's entries in
~/.claude/settings.json and stands down; SessionStart says once which to remove. The
installed copy keeps working, so the behaviour is that of one install plus the warning."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"


def _env(tmp_path, *, plugin=True, installer=True):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    if installer:
        inst = home / ".claude" / "baton" / "hooks"
        settings = {"hooks": {ev: [{"hooks": [{"type": "command", "command": "/usr/bin/python3",
                                               "args": [str(inst / f)]}]}]
                              for ev, f in (("SessionStart", "baton_session_start.py"),
                                            ("Stop", "baton_stop.py"),
                                            ("UserPromptSubmit", "baton_prompt.py"))}}
        (home / ".claude" / "settings.json").write_text(json.dumps(settings))
    tasks = tmp_path / "tasks"
    task = tasks / "billing"
    task.mkdir(parents=True, exist_ok=True)
    (task / "LOGBOOK.md").write_text("---\nstate: active\nturn: us\nnext: \"run it\"\n"
                                     "aliases: [billing]\n---\n\n## 2026-09-01 10:00 — a\n\nx\n")
    old = time.time() - 3600
    os.utime(task / "LOGBOOK.md", (old, old))
    (task / "draft.txt").write_text("unrecorded work")
    ten_min = time.time() - 600          # past Stop's 90 s grace, after the last entry
    os.utime(task / "draft.txt", (ten_min, ten_min))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BATON_", "CLAUDE_PLUGIN"))}
    env.update(HOME=str(home), BATON_HOME=str(tasks), BATON_LOGBOOK="LOGBOOK.md",
               BATON_SESSION_STATE=str(tmp_path / "s.json"), BATON_BODY_STATE=str(tmp_path / "b.json"),
               BATON_STATE_DIR=str(tmp_path))   # the prompt hook's per-session memory, not /tmp's
    if plugin:
        (tmp_path / "data").mkdir(exist_ok=True)
        env.update(CLAUDE_PLUGIN_ROOT=str(ROOT), CLAUDE_PLUGIN_DATA=str(tmp_path / "data"))
    return env


def _run(hook, env, payload):
    out = subprocess.run([sys.executable, str(HOOKS / hook)], input=json.dumps(payload),
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_session_start_says_it_once_and_shows_no_second_board(tmp_path):
    out = _run("baton_session_start.py", _env(tmp_path), {})
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "installed twice" in context
    assert "billing" not in context, "the board comes from the installed copy, not this one"


def test_stop_and_prompt_stand_down(tmp_path):
    env = _env(tmp_path)
    assert _run("baton_stop.py", env, {"session_id": tmp_path.name}) == ""
    assert _run("baton_prompt.py", env, {"prompt": "let us do billing", "session_id": tmp_path.name}) == ""


def test_the_plugin_alone_works(tmp_path):
    env = _env(tmp_path, installer=False)
    assert "billing" in _run("baton_session_start.py", env, {})
    assert _run("baton_stop.py", env, {"session_id": tmp_path.name}) != ""
    assert "billing" in _run("baton_prompt.py", env, {"prompt": "let us do billing", "session_id": tmp_path.name})


def test_the_installer_alone_is_untouched(tmp_path):
    env = _env(tmp_path, plugin=False)
    out = _run("baton_session_start.py", env, {})
    assert "billing" in out and "installed twice" not in out


def test_claude_config_dir_is_where_the_installer_would_be(tmp_path):
    """Found in the first real plugin session, 2026-09-29: with CLAUDE_CONFIG_DIR pointing
    at a clean config, the hook read ~/.claude/settings.json anyway, saw the installer's
    hooks there -- which that session does not run -- and stood down for nothing."""
    env = _env(tmp_path)                      # installer entries in HOME/.claude/settings.json
    cfg = tmp_path / "clean-config"
    cfg.mkdir()
    env["CLAUDE_CONFIG_DIR"] = str(cfg)
    out = _run("baton_session_start.py", env, {})
    assert "installed twice" not in out and "billing" in out
    (cfg / "settings.json").write_text((tmp_path / "home" / ".claude" / "settings.json").read_text())
    assert "installed twice" in _run("baton_session_start.py", env, {})
