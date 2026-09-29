"""Plugin mode (CLAUDE_PLUGIN_ROOT set): what the installer-era checks must not do there.

- install_drift compares running hooks with a working copy; Claude Code owns the plugin's
  copy, so there is nothing of ours to drift.
- the weekly GitHub check and its question are the installer's update path; a plugin is
  updated by Claude Code (`claude plugin update`, or auto-update for the marketplace), so
  in plugin mode the hooks make no network request at all.
- a plugin's skills are namespaced: /baton:baton-plan, not /baton-plan.
- a skill a task header names may live inside the plugin, not in ~/.claude/skills."""
import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _hook():
    spec = importlib.util.spec_from_file_location("pm_bss", ROOT / "hooks" / "baton_session_start.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    for var in ("BATON_HOME", "CLAUDE_CONFIG_DIR", "BATON_SKILLS", "BATON_SOURCE", "BATON_SESSION_STATE",
                "BATON_UPDATE_URL"):
        monkeypatch.delenv(var, raising=False)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(ROOT))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return data


def test_no_drift_check_in_plugin_mode(plugin, tmp_path):
    src = tmp_path / "src"          # `source` names the folder holding the hook files
    src.mkdir()
    for name in ("baton_session_start.py", "baton_stop.py", "baton_prompt.py"):
        (src / name).write_text("# a different version\n")
    (plugin / "baton.local.json").write_text(json.dumps({"source": str(src)}))
    assert _hook().install_drift() == []


@pytest.mark.parametrize("setting", [None, True])
def test_no_update_question_and_no_network_in_plugin_mode(plugin, monkeypatch, setting):
    if setting is not None:
        (plugin / "baton.local.json").write_text(json.dumps({"update_check": setting}))
    def refuse(*a, **k):
        raise AssertionError("a plugin-mode hook reached for the network")
    monkeypatch.setattr("urllib.request.urlopen", refuse)
    assert _hook().update_notice(date(2026, 9, 29)) is None


def test_commands_are_named_with_the_plugin_prefix(plugin):
    h = _hook()
    assert h.command("baton-inventory") == "/baton:baton-inventory"
    rules = h.plugin_rules()
    assert "/baton:baton-plan" in rules and "`/baton-plan`" not in rules


def test_without_the_plugin_commands_keep_their_names(monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    assert _hook().command("baton-inventory") == "/baton-inventory"


def test_a_skill_inside_the_plugin_is_not_missing(plugin, tmp_path):
    task = tmp_path / "task"
    task.mkdir()
    (task / "LOGBOOK.md").write_text("x")
    h = _hook()
    for name in ("baton-task", "baton:baton-task"):
        assert not [t for t in h.skill_trouble([name], task, "LOGBOOK.md") if "MISSING" in t], name
    assert any("MISSING" in t for t in h.skill_trouble(["no-such-skill"], task, "LOGBOOK.md"))
