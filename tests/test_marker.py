"""Each block SessionStart injects opens with a fixed line naming it: [baton:board vX],
[baton:rules vX], [baton:compact vX]. Asked for on 2026-10-10 by the author of a tool that
attributes context to its source: injected context lands in the turn totals with no label,
and one SessionStart hook injects two blocks that behave differently -- the board grows with
the tasks, the rules stay fixed. A plain first line is something any reader can match.

Run the way the harness runs it: a subprocess with the hook's JSON on stdin."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_session_start.py"
VERSION = re.search(r'BATON_VERSION = "([^"]+)"', HOOK.read_text(encoding="utf-8")).group(1)


def _context(tmp_path, *, plugin, source=None):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    tasks = tmp_path / "tasks"
    (tasks / "a").mkdir(parents=True)
    (tasks / "a" / "LOGBOOK.md").write_text("## 2026-09-01 10:00 — a\n\ntext\n", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), BATON_HOME=str(tasks), BATON_LOGBOOK="LOGBOOK.md",
               BATON_SESSION_STATE=str(data / "state.json"),
               BATON_LESSONS_STATE=str(data / "lessons.json"))
    if plugin:
        env.update(CLAUDE_PLUGIN_ROOT=str(ROOT), CLAUDE_PLUGIN_DATA=str(data))
    stdin = json.dumps({"source": source} if source else {})
    out = subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True,
                         text=True, env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]


def test_the_board_opens_with_its_marker(tmp_path):
    assert _context(tmp_path, plugin=False).startswith(f"[baton:board v{VERSION}]\n")


def test_as_a_plugin_the_rules_are_a_second_marked_block(tmp_path):
    context = _context(tmp_path, plugin=True)
    assert context.startswith(f"[baton:board v{VERSION}]\n")
    assert f"\n\n[baton:rules v{VERSION}]\nBaton's working rules." in context


def test_without_the_plugin_there_is_no_rules_block(tmp_path):
    assert "[baton:rules" not in _context(tmp_path, plugin=False)


def test_after_compaction_the_block_is_named_for_what_it_is(tmp_path):
    context = _context(tmp_path, plugin=False, source="compact")
    assert context.startswith(f"[baton:compact v{VERSION}]\n")
    assert "[baton:board" not in context
