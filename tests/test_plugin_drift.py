"""The plugin's running copy against what Claude Code recorded and the catalog released.

Until v3.17.0 `install_drift` returned nothing at all as a plugin -- the main way Baton is
installed -- while comments in public (06.10, 08.10) said each session compares the running
hook with its source. Two things are checkable without the network, and both are checked:

- Claude Code records where it installed the plugin (installed_plugins.json). A session that
  runs from another folder is running an older copy: `claude plugin update` took effect on
  disk, not in this session -- the v2.2.0 failure, where a release ran nowhere for two days.
- The catalog's copy of the same version (the marketplace clone) holds the released hooks.
  Same version, different bytes: the cache is not the release it says it is.

Not checkable here: whether the catalog clone is the newest release (that needs the network).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ("baton_session_start.py", "baton_stop.py", "baton_prompt.py", "baton_batch.py",
         "baton_stop_failure.py", "baton_pretool.py", "_baton.py", "hooks.json")


def _copy(dest: Path, version: str) -> Path:
    (dest / "hooks").mkdir(parents=True)
    (dest / ".claude-plugin").mkdir()
    for name in HOOKS:
        shutil.copy(ROOT / "hooks" / name, dest / "hooks" / name)
    (dest / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "baton", "version": version}), "utf-8")
    return dest


def _machine(tmp_path: Path, running="3.16.0", installed="3.16.0", catalog="3.16.0"):
    """A config dir with Baton installed from the `baton` catalog, as Claude Code lays it out."""
    cfg = tmp_path / "claude"
    cache = cfg / "plugins" / "cache" / "baton" / "baton"
    run = _copy(cache / running, running)
    if installed != running:
        _copy(cache / installed, installed)
    clone = _copy(cfg / "plugins" / "marketplaces" / "baton", catalog)
    (clone / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
        {"name": "baton", "plugins": [{"name": "baton", "source": "./"}]}), "utf-8")
    (cfg / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {
        "baton@baton": [{"scope": "user", "installPath": str(cache / installed),
                         "version": installed}]}}), "utf-8")
    (cfg / "plugins" / "known_marketplaces.json").write_text(json.dumps({"baton": {
        "source": {"source": "github", "repo": "StanimirTenev/baton"},
        "installLocation": str(clone)}}), "utf-8")
    return cfg, run, clone


def _load(run: Path, monkeypatch, cfg: Path, tmp_path: Path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(run))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    spec = importlib.util.spec_from_file_location(f"pd_{abs(hash(run))}", run / "hooks" / "baton_session_start.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_cache_equal_to_the_release_reports_nothing(tmp_path, monkeypatch):
    cfg, run, _ = _machine(tmp_path)
    assert _load(run, monkeypatch, cfg, tmp_path).plugin_drift() is None


def test_a_cache_that_differs_from_the_release_of_its_version_is_named(tmp_path, monkeypatch):
    cfg, run, _ = _machine(tmp_path)
    with open(run / "hooks" / "baton_stop.py", "a", encoding="utf-8") as fh:
        fh.write("\n# edited in the cache\n")
    note = _load(run, monkeypatch, cfg, tmp_path).plugin_drift()
    assert note and "baton_stop.py" in note and "3.16.0" in note, note
    assert "baton_prompt.py" not in note


def test_an_update_this_session_does_not_run_is_said(tmp_path, monkeypatch):
    """`claude plugin update` moved the record to 3.17.0; this session still runs 3.16.0."""
    cfg, run, _ = _machine(tmp_path, running="3.16.0", installed="3.17.0", catalog="3.17.0")
    note = _load(run, monkeypatch, cfg, tmp_path).plugin_drift()
    assert note and "3.17.0" in note and "3.16.0" in note and "restart" in note, note


def test_the_same_plugin_from_another_catalog_is_not_an_update(tmp_path, monkeypatch):
    """Baton recorded under two catalogs (the directory's `baton@synced`, disabled, next to
    `baton@baton`): the other one is a second install, not an update this session missed."""
    cfg, run, _ = _machine(tmp_path)
    other = _copy(cfg / "plugins" / "cache" / "synced" / "baton" / "3.12.0", "3.12.0")
    records = json.loads((cfg / "plugins" / "installed_plugins.json").read_text("utf-8"))
    records["plugins"]["baton@synced"] = [{"scope": "user", "installPath": str(other),
                                           "version": "3.12.0"}]
    (cfg / "plugins" / "installed_plugins.json").write_text(json.dumps(records), "utf-8")
    assert _load(run, monkeypatch, cfg, tmp_path).plugin_drift() is None


def test_another_catalog_version_is_not_compared_byte_for_byte(tmp_path, monkeypatch):
    """The catalog moved on (3.17.0) and nothing is installed from it yet: different files are
    expected, and whether to update is the human's call, not a drift."""
    cfg, run, _ = _machine(tmp_path, catalog="3.17.0")
    with open(run / "hooks" / "baton_stop.py", "a", encoding="utf-8") as fh:
        fh.write("\n# 3.16.0's own bytes\n")
    assert _load(run, monkeypatch, cfg, tmp_path).plugin_drift() is None


def test_a_copy_claude_code_did_not_install_is_left_alone(tmp_path, monkeypatch):
    """--plugin-dir from a working copy: no record of it to compare with."""
    cfg, _, _ = _machine(tmp_path)
    assert _load(ROOT, monkeypatch, cfg, tmp_path).plugin_drift() is None


def test_no_record_at_all_is_silence(tmp_path, monkeypatch):
    cfg, run, _ = _machine(tmp_path)
    (cfg / "plugins" / "installed_plugins.json").unlink()
    assert _load(run, monkeypatch, cfg, tmp_path).plugin_drift() is None


def test_the_board_carries_it_through_the_real_entry_point(tmp_path):
    cfg, run, _ = _machine(tmp_path)
    with open(run / "hooks" / "baton_batch.py", "a", encoding="utf-8") as fh:
        fh.write("\n# edited in the cache\n")
    tasks = tmp_path / "tasks"
    (tasks / "one").mkdir(parents=True)
    (tasks / "one" / "LOGBOOK.md").write_text("## 2026-10-20 10:00 — x\n\ny\n", "utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "BATON_"))}
    env.update(CLAUDE_CONFIG_DIR=str(cfg), CLAUDE_PLUGIN_ROOT=str(run),
               CLAUDE_PLUGIN_DATA=str(tmp_path / "data"), BATON_HOME=str(tasks),
               BATON_LOGBOOK="LOGBOOK.md", HOME=str(tmp_path / "home"),
               BATON_SESSION_STATE=os.environ["BATON_SESSION_STATE"])
    out = subprocess.run([sys.executable, str(run / "hooks" / "baton_session_start.py")],
                         input=json.dumps({"session_id": "s", "source": "startup"}),
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    assert "NOT THE RELEASED v3.16.0" in out.stdout and "baton_batch.py" in out.stdout, out.stdout
