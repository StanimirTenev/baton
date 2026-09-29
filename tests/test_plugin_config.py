"""Installed as a Claude Code plugin, the hooks run from a folder that is replaced on every
update (${CLAUDE_PLUGIN_ROOT}). Settings and state written next to the scripts would be
lost each time, so in plugin mode they live in ${CLAUDE_PLUGIN_DATA}, and the task folder
and logbook name the user gives when enabling the plugin arrive as
CLAUDE_PLUGIN_OPTION_TASKS_FOLDER / _LOGBOOK. Installed by install.sh nothing changes:
none of those variables is set there."""
import importlib.util
import json
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
NAMES = ("baton_session_start", "baton_stop", "baton_prompt")


def _load(name):
    spec = importlib.util.spec_from_file_location(f"pc_{name}", HOOKS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    for var in ("BATON_HOME", "BATON_LOGBOOK", "BATON_SESSION_STATE", "BATON_BODY_STATE",
                "CLAUDE_PLUGIN_OPTION_TASKS_FOLDER", "CLAUDE_PLUGIN_OPTION_LOGBOOK"):
        monkeypatch.delenv(var, raising=False)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    return data


@pytest.mark.parametrize("name", NAMES)
def test_the_options_given_at_enable_are_the_task_folder_and_logbook(plugin, monkeypatch, tmp_path, name):
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_TASKS_FOLDER", str(tmp_path / "zadachi"))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_LOGBOOK", "DNEVNIK.md")
    assert _load(name).config() == (tmp_path / "zadachi", "DNEVNIK.md")


@pytest.mark.parametrize("name", NAMES)
def test_an_explicit_baton_home_still_wins(plugin, monkeypatch, tmp_path, name):
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_TASKS_FOLDER", str(tmp_path / "zadachi"))
    monkeypatch.setenv("BATON_HOME", str(tmp_path / "explicit"))
    assert _load(name).config()[0] == tmp_path / "explicit"


@pytest.mark.parametrize("name", NAMES)
def test_local_settings_are_read_from_the_plugin_data_folder(plugin, tmp_path, name):
    (plugin / "baton.local.json").write_text(json.dumps({"home": str(tmp_path / "t"),
                                                         "logbook": "LOG.md"}))
    assert _load(name).config() == (tmp_path / "t", "LOG.md")


def test_state_is_written_to_the_plugin_data_folder(plugin):
    assert _load("baton_session_start")._state_file() == plugin / "baton.state.json"
    assert _load("baton_stop")._bodies_path() == plugin / "baton.bodies.json"


def test_without_the_plugin_nothing_moves(monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    for var in ("BATON_SESSION_STATE", "BATON_BODY_STATE"):
        monkeypatch.delenv(var, raising=False)
    assert _load("baton_session_start")._state_file() == HOOKS / "baton.state.json"
    assert _load("baton_stop")._bodies_path() == HOOKS / "baton.bodies.json"


@pytest.mark.parametrize("name", NAMES)
def test_a_missing_data_folder_is_created_not_silently_skipped(tmp_path, monkeypatch, name):
    """Found on Windows, 2026-09-29: the docs say Claude Code creates ${CLAUDE_PLUGIN_DATA}
    'on first reference', and these hooks only read it from the environment. Without the
    folder every state write failed quietly -- notices repeated, Stop lost its memory."""
    data = tmp_path / "not-yet" / "data"
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    assert _load(name)._local_file("x.json").parent.is_dir()


def test_the_plugin_version_is_the_hooks_version():
    """A second place to bump since 3.8.0. With `version` set, Claude Code keeps users on it
    until it changes (code.claude.com/docs/en/plugins/manifest-reference) -- a release that
    forgot plugin.json would never reach a plugin user."""
    manifest = json.loads((HOOKS.parent / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["version"] == _load("baton_session_start").BATON_VERSION
