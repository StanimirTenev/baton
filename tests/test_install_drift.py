"""The running hook is a copy. Nobody checks that the copy is current.

v2.2.0 shipped a shelf-life layer that never ran for two days: written, tested,
tagged, and never copied into the directory the harness actually executes.
"""

import importlib.util
import json
import shutil
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_session_start.py"


def _load(hookdir: Path):
    """Import a copy of the hook living in `hookdir`, so __file__ points there."""
    target = hookdir / "baton_session_start.py"
    spec = importlib.util.spec_from_file_location(f"bss_{hookdir.name}", target)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _install(tmp_path: Path, source: Path | None) -> Path:
    hookdir = tmp_path / "installed"
    hookdir.mkdir()
    shutil.copy(HOOK, hookdir / "baton_session_start.py")
    (hookdir / "baton_stop.py").write_text("# stop\n", encoding="utf-8")
    cfg = {"home": str(tmp_path / "tasks"), "logbook": "LOGBOOK.md"}
    if source is not None:
        cfg["source"] = str(source)
    (hookdir / "baton.local.json").write_text(json.dumps(cfg), encoding="utf-8")
    return hookdir


def test_no_source_configured_reports_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("BATON_SOURCE", raising=False)
    mod = _load(_install(tmp_path, source=None))
    assert mod.install_drift() == []


def test_identical_copies_report_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("BATON_SOURCE", raising=False)
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(HOOK, src / "baton_session_start.py")
    (src / "baton_stop.py").write_text("# stop\n", encoding="utf-8")
    mod = _load(_install(tmp_path, source=src))
    assert mod.install_drift() == []


def test_a_stale_installed_hook_is_reported(tmp_path, monkeypatch):
    """The real case: the source moved on and the install did not."""
    monkeypatch.delenv("BATON_SOURCE", raising=False)
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(HOOK, src / "baton_session_start.py")
    (src / "baton_stop.py").write_text("# stop\n", encoding="utf-8")
    hookdir = _install(tmp_path, source=src)
    # source gains a feature; the installed copy does not
    (src / "baton_session_start.py").write_text(
        HOOK.read_text(encoding="utf-8") + "\n# a new feature\n", encoding="utf-8")
    mod = _load(hookdir)
    assert mod.install_drift() == ["baton_session_start.py"]


def test_both_hooks_drifting_are_both_named(tmp_path, monkeypatch):
    monkeypatch.delenv("BATON_SOURCE", raising=False)
    src = tmp_path / "src"
    src.mkdir()
    (src / "baton_session_start.py").write_text("# different\n", encoding="utf-8")
    (src / "baton_stop.py").write_text("# also different\n", encoding="utf-8")
    mod = _load(_install(tmp_path, source=src))
    assert mod.install_drift() == ["baton_session_start.py", "baton_stop.py"]


def test_a_missing_source_directory_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.delenv("BATON_SOURCE", raising=False)
    mod = _load(_install(tmp_path, source=tmp_path / "does-not-exist"))
    assert mod.install_drift() == []
