"""The agent is told where tools/baton_entry.py is, not only its name.

v3.36.0, ZA-OPRAVYANE row 164 -- the phase-1 handoff test (16.11): the rules and the L1 note said
`tools/baton_entry.py` with no path. Codex did not know where that was, searched the whole temp
tree for it (reading paths in other sessions' folders), and wrote the path it found into the
shared logbook; the next Claude session then used Codex's copy. Wherever Baton tells the agent to
use the tool, it now names the one beside the hooks that run -- for both hosts. Through the hooks'
and the installer's entry points.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import child_env

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "baton_entry.py"
CODEX_PATCH = json.loads((ROOT / "tests" / "fixtures" / "codex" / "pretool_apply_patch.json").read_text("utf-8"))


def _paths(text: str) -> list:
    return re.findall(r"(/[^\s\"'`]*/tools/baton_entry\.py)", text)


def _named_here(text: str):
    found = _paths(text)
    assert found, text[-600:]
    assert all(Path(p).is_file() for p in found), found
    assert str(TOOL) in found


def test_the_plugin_rules_name_the_tool_s_path(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (tmp_path / "tasks").mkdir()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), BATON_HOME=str(tmp_path / "tasks"), CLAUDE_PLUGIN_ROOT=str(ROOT),
               CLAUDE_PLUGIN_DATA=str(tmp_path / "data"))
    out = subprocess.run([sys.executable, str(ROOT / "hooks" / "baton_session_start.py")],
                         input="{}", capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    rules = json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"].split("[baton:rules")[1]
    _named_here(rules)


@pytest.mark.parametrize("template", ["templates/CLAUDE.md", "codex/AGENTS.md.snippet",
                                      "gemini/GEMINI.md.snippet"])
def test_the_installed_rules_name_the_tool_s_path(tmp_path, template):
    """install.sh and install.ps1 pass templates/CLAUDE.md; the Codex install (codex/README.md,
    step 4) passes codex/AGENTS.md.snippet. Both write the rules with the tool's path."""
    target = tmp_path / "AGENTS.md"
    r = subprocess.run([sys.executable, str(ROOT / "hooks" / "_install_rules.py"),
                        str(ROOT / template), str(target), "/x/tasks", "LOGBOOK.md", "0"],
                       capture_output=True, text=True, env=child_env())
    assert r.returncode == 0, r.stderr
    _named_here(target.read_text("utf-8"))


def _pretool(event: dict, tmp_path) -> str:
    env = {"PATH": "/usr/bin:/bin", "CLAUDE_PLUGIN_DATA": str(tmp_path),
           "BATON_LOGBOOK": "LOGBOOK.md", "BATON_HOME": str(tmp_path / "tasks")}
    out = subprocess.run([sys.executable, str(ROOT / "hooks" / "baton_pretool.py")],
                         input=json.dumps(event).encode("utf-8"), capture_output=True, env=env)
    assert out.returncode == 0, out.stderr.decode("utf-8")
    return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]


def test_the_l1_note_names_the_tool_s_path_under_claude_code(tmp_path):
    note = _pretool({"hook_event_name": "PreToolUse", "tool_name": "Write",
                     "tool_input": {"file_path": str(tmp_path / "tasks" / "a" / "LOGBOOK.md"),
                                    "content": "## 2026-11-16 16:34 — typed\n"}}, tmp_path)
    _named_here(note)


def test_the_l1_note_names_the_tool_s_path_under_codex(tmp_path):
    patch = ("*** Begin Patch\n*** Update File: /work/tasks/a/LOGBOOK.md\n@@\n ---\n+\n"
             "+## 2026-11-14 10:00 — typed hour\n*** End Patch")
    _named_here(_pretool(dict(CODEX_PATCH, tool_input={"command": patch}), tmp_path))
