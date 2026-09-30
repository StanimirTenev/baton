"""One English line in the terminal at session start, and the board for the agent only.

Since v3.7.0 the board went to the agent alone, to be shown translated in its first reply.
On a Mac (2026-09-30) the agent did not show it, and the author concluded Baton had not
loaded at all: nothing on the screen said otherwise. The agent cannot speak first in an
interactive session (`initialUserMessage` applies to `-p` only), so the hook now says, in one
English line the human sees at once, that Baton is on and what to do -- and the board itself
still comes from the agent, in the human's language."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_session_start.py"


def _run(tmp_path, *, tasks=True, plugin=False, installer=False):
    root = tmp_path / "tasks"
    root.mkdir(exist_ok=True)
    if tasks:
        t = root / "billing"
        t.mkdir()
        (t / "LOGBOOK.md").write_text('---\nstate: active\nturn: us\nnext: "send the invoice"\n'
                                      '---\n\n## 2026-09-01 10:00 — a\n\nx\n', encoding="utf-8")
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    if installer:
        (home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "python3", "args": ["/x/baton_stop.py"]}]}]}}))
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), BATON_HOME=str(root), BATON_LOGBOOK="LOGBOOK.md",
               BATON_SESSION_STATE=str(tmp_path / "s.json"))
    if plugin:
        env.update(CLAUDE_PLUGIN_ROOT=str(ROOT), CLAUDE_PLUGIN_DATA=str(tmp_path / "data"))
    out = subprocess.run([sys.executable, str(HOOK)], input="{}", capture_output=True,
                         text=True, env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_human_sees_one_line_and_the_agent_gets_the_board(tmp_path):
    out = _run(tmp_path)
    line = out["systemMessage"]
    assert line.startswith("🧭 Baton") and "\n" not in line
    assert "1 on your move" in line and "Write anything" in line
    assert "send the invoice" not in line, "the board itself is for the agent to translate"
    assert "send the invoice" in out["hookSpecificOutput"]["additionalContext"]


def test_the_agent_is_told_to_open_with_the_board_whatever_the_first_message(tmp_path):
    context = _run(tmp_path)["hookSpecificOutput"]["additionalContext"]
    assert "whatever the human's first message" in context.lower()


def test_a_new_user_with_no_tasks_is_told_baton_is_on(tmp_path):
    line = _run(tmp_path, tasks=False)["systemMessage"]
    assert line.startswith("🧭 Baton is on") and "no task folders yet" in line


def test_installed_twice_says_so_on_the_screen_too(tmp_path):
    line = _run(tmp_path, plugin=True, installer=True)["systemMessage"]
    assert "installed twice" in line
