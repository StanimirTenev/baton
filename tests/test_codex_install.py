"""The Codex install files in codex/: one set of hooks, the same rules text.

codex/hooks.json starts the very hooks Claude Code runs, through hooks/run.sh; codex/
AGENTS.md.snippet is templates/CLAUDE.md byte for byte, so the rules are written once.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_snippet_is_the_template():
    assert (ROOT / "codex" / "AGENTS.md.snippet").read_bytes() == (ROOT / "templates" / "CLAUDE.md").read_bytes()


def test_the_four_codex_events_each_start_a_hook_through_run_sh():
    hooks = json.loads((ROOT / "codex" / "hooks.json").read_text("utf-8"))["hooks"]
    want = {"SessionStart": "baton_session_start.py", "UserPromptSubmit": "baton_prompt.py",
            "PreToolUse": "baton_pretool.py", "Stop": "baton_stop.py"}
    assert set(hooks) == set(want), "Codex has no PostToolBatch or StopFailure"
    for event, script in want.items():
        (group,) = hooks[event]
        (handler,) = group["hooks"]
        m = re.fullmatch(r'sh "\$HOME/\.codex/baton/hooks/run\.sh" "\$HOME/\.codex/baton/hooks/(\w+\.py)"',
                         handler["command"])
        assert m and m.group(1) == script, handler["command"]
        assert (ROOT / "hooks" / script).is_file()
        assert handler["type"] == "command" and handler["timeout"] <= 20


def test_pretool_matches_what_codex_calls_its_shell_and_its_edit():
    (group,) = json.loads((ROOT / "codex" / "hooks.json").read_text("utf-8"))["hooks"]["PreToolUse"]
    pat = re.compile(group["matcher"])
    assert pat.search("Bash") and pat.search("apply_patch")
    assert not pat.search("mcp__fs__read_file") and not pat.search("update_plan")
