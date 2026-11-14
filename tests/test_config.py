"""Where the tasks are and what the logbook is called: one resolution, `config` in hooks/_baton.py.

Until stage 1 of the shared core (2026-11-14) it was three copies of the same code, in
SessionStart, Stop and the prompt hook, that differed only in their docstrings. Each hook now
calls the shared one and nothing else (stage 3 removed the fallback bodies); a hook without
_baton.py beside it says so on stderr instead of doing nothing (the last test below).

The order, first set wins: BATON_HOME / BATON_LOGBOOK, the plugin's option, baton.local.json
(`home`, `logbook`), then ~/tasks and LOGBOOK.md.
"""
import importlib.util
import json
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
NAMES = ("baton_session_start", "baton_stop", "baton_prompt")
VARS = ("BATON_HOME", "BATON_LOGBOOK", "CLAUDE_PLUGIN_OPTION_TASKS_FOLDER",
        "CLAUDE_PLUGIN_OPTION_LOGBOOK")


def _load(name):
    spec = importlib.util.spec_from_file_location(f"cfg_{name}", HOOKS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def clean(tmp_path, monkeypatch):
    """No variable set, the local file in a data folder of its own, home in tmp_path."""
    for var in VARS:
        monkeypatch.delenv(var, raising=False)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    return data


def _both(name):
    """config() as the hook answers it, and as _baton.config answers it directly."""
    mod = _load(name)
    shared = mod.config()
    assert shared == mod._baton.config(mod._local_file)
    return shared


def _local(data: Path, cfg, bom=False):
    text = cfg if isinstance(cfg, str) else json.dumps(cfg)
    (data / "baton.local.json").write_text(("﻿" if bom else "") + text, encoding="utf-8")


@pytest.mark.parametrize("name", NAMES)
def test_nothing_set_is_tasks_in_home_and_logbook_md(clean, tmp_path, name):
    assert _both(name) == (tmp_path / "home" / "tasks", "LOGBOOK.md")


@pytest.mark.parametrize("name", NAMES)
def test_the_local_file_comes_before_the_defaults(clean, tmp_path, name):
    _local(clean, {"home": str(tmp_path / "local"), "logbook": "LOCAL.md"})
    assert _both(name) == (tmp_path / "local", "LOCAL.md")


@pytest.mark.parametrize("name", NAMES)
def test_the_plugin_option_comes_before_the_local_file(clean, monkeypatch, tmp_path, name):
    _local(clean, {"home": str(tmp_path / "local"), "logbook": "LOCAL.md"})
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_TASKS_FOLDER", str(tmp_path / "option"))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_LOGBOOK", "OPTION.md")
    assert _both(name) == (tmp_path / "option", "OPTION.md")


@pytest.mark.parametrize("name", NAMES)
def test_baton_variables_come_first(clean, monkeypatch, tmp_path, name):
    _local(clean, {"home": str(tmp_path / "local"), "logbook": "LOCAL.md"})
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_TASKS_FOLDER", str(tmp_path / "option"))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_LOGBOOK", "OPTION.md")
    monkeypatch.setenv("BATON_HOME", str(tmp_path / "env"))
    monkeypatch.setenv("BATON_LOGBOOK", "ENV.md")
    assert _both(name) == (tmp_path / "env", "ENV.md")


@pytest.mark.parametrize("name", NAMES)
def test_an_empty_variable_counts_as_unset(clean, monkeypatch, tmp_path, name):
    _local(clean, {"home": str(tmp_path / "local"), "logbook": "LOCAL.md"})
    for var in VARS:
        monkeypatch.setenv(var, "")
    assert _both(name) == (tmp_path / "local", "LOCAL.md")


@pytest.mark.parametrize("name", NAMES)
def test_each_field_falls_through_on_its_own(clean, monkeypatch, tmp_path, name):
    _local(clean, {"logbook": "LOCAL.md"})
    monkeypatch.setenv("BATON_HOME", str(tmp_path / "env"))
    assert _both(name) == (tmp_path / "env", "LOCAL.md")


@pytest.mark.parametrize("name", NAMES)
def test_a_local_file_with_a_bom_is_read(clean, tmp_path, name):
    """Notepad on Windows writes UTF-8 with a BOM."""
    _local(clean, {"home": str(tmp_path / "local"), "logbook": "DNEVNIK.md"}, bom=True)
    assert _both(name) == (tmp_path / "local", "DNEVNIK.md")


@pytest.mark.parametrize("name", NAMES)
def test_a_broken_local_file_falls_back_to_the_defaults(clean, tmp_path, name):
    _local(clean, '{"home": "/somewhere", ')
    assert _both(name) == (tmp_path / "home" / "tasks", "LOGBOOK.md")


@pytest.mark.parametrize("name", NAMES)
def test_a_tilde_in_home_is_expanded(clean, tmp_path, name):
    _local(clean, {"home": "~/elsewhere"})
    assert _both(name)[0] == tmp_path / "home" / "elsewhere"


@pytest.mark.parametrize("name", NAMES)
def test_the_hook_asks_the_shared_copy(clean, name):
    """Without this, the shared config could be dead code and every case above still pass."""
    mod = _load(name)
    seen = []
    mod._baton.config = lambda local_file: seen.append(local_file) or ("sentinel", "S.md")
    assert mod.config() == ("sentinel", "S.md")
    assert seen == [mod._local_file], "the hook's own _local_file, not another"


@pytest.mark.parametrize("name", NAMES + ("baton_batch", "baton_pretool", "baton_stop_failure"))
def test_a_hook_without_baton_py_says_so(tmp_path, name):
    """Until stage 3 a hook alone ran a fallback copy of config(); before that copy existed, it
    crashed inside main() and exited 0 with nothing on stderr -- the heartbeat that would have
    recorded the crash lives in _baton.py too. Now it names the missing file, and still exits 0,
    as run.sh does when there is no Python: a hook never breaks the session. Batch and pretool
    ask SessionStart's config() (`ss.config()`), so they need _baton.py as much; StopFailure's one
    job, the turn line, is _baton.turn since stage 5."""
    import shutil
    import subprocess
    import sys
    alone = tmp_path / "hooks"
    alone.mkdir()
    for hook in NAMES + ("baton_batch", "baton_pretool", "baton_stop_failure"):   # not _baton.py
        shutil.copy(HOOKS / f"{hook}.py", alone)
    out = subprocess.run([sys.executable, str(alone / f"{name}.py")], input="{}",
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, "a hook never breaks the session"
    assert "_baton.py" in out.stderr and "did not run" in out.stderr, out.stderr
    assert not out.stdout.strip()
