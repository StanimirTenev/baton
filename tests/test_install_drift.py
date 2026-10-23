"""The running hook is a copy. Nobody checks that the copy is current.

v2.2.0 shipped a shelf-life layer that never ran for two days: written, tested,
tagged, and never copied into the directory the harness actually executes.
"""
from __future__ import annotations

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


def test_a_hook_in_the_source_that_was_never_installed_is_reported(tmp_path, monkeypatch):
    """2026-09-28: a third hook (`baton_prompt.py`). Both-files-exist was the only case
    compared, so a hook that was never copied at all passed in silence -- the 19.09 failure
    again, one level down: the check is there, and the file it would check is not."""
    monkeypatch.delenv("BATON_SOURCE", raising=False)
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(HOOK, src / "baton_session_start.py")
    (src / "baton_stop.py").write_text("# stop\n", encoding="utf-8")
    (src / "baton_prompt.py").write_text("# prompt\n", encoding="utf-8")
    mod = _load(_install(tmp_path, source=src))
    assert mod.install_drift() == ["baton_prompt.py (not installed)"]


def test_baton_source_alone_is_enough(tmp_path, monkeypatch):
    """ZA-OPRAVYANE row 50 (Benjamin Brachert, 22.10, said publicly): the README says `source` in
    baton.local.json "or BATON_SOURCE", but with no settings file source_dir() returned None before
    it read the variable, and nothing was compared."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "baton_session_start.py").write_text("# a teammate's edit\n", encoding="utf-8")
    hookdir = _install(tmp_path, source=None)
    (hookdir / "baton.local.json").unlink()
    shutil.copy(HOOK, src / "baton_stop.py")
    (hookdir / "baton_stop.py").write_text(HOOK.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("BATON_SOURCE", str(src))
    mod = _load(hookdir)
    assert mod.install_drift() == ["baton_session_start.py"]
    (hookdir / "baton.local.json").write_text("{not json", encoding="utf-8")   # broken: the same
    assert _load(hookdir).install_drift() == ["baton_session_start.py"]


def _repo(tmp_path: Path, skills: dict) -> Path:
    """A working copy: hooks/ (the `source`) beside skills/."""
    src = tmp_path / "repo" / "hooks"
    src.mkdir(parents=True)
    shutil.copy(HOOK, src / "baton_session_start.py")
    (src / "baton_stop.py").write_text("# stop\n", encoding="utf-8")
    for name, text in skills.items():
        (tmp_path / "repo" / "skills" / name).mkdir(parents=True)
        (tmp_path / "repo" / "skills" / name / "SKILL.md").write_text(text, encoding="utf-8")
    return src


def test_a_changed_or_missing_skill_is_reported(tmp_path, monkeypatch):
    """ZA-OPRAVYANE row 51 (Benjamin Brachert, 22.10): only the four hooks were compared; a
    SKILL.md changed in the source and not copied gave []. install.sh copies skills to
    ~/.claude/skills/<name>/SKILL.md."""
    monkeypatch.delenv("BATON_SOURCE", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    src = _repo(tmp_path, {"baton-plan": "new\n", "baton-task": "same\n", "baton-key": "k\n"})
    for name, text in {"baton-plan": "old\n", "baton-task": "same\n"}.items():
        (cfg / "skills" / name).mkdir(parents=True)
        (cfg / "skills" / name / "SKILL.md").write_text(text, encoding="utf-8")
    mod = _load(_install(tmp_path, source=src))
    assert mod.install_drift() == ["skills/baton-key/SKILL.md (not installed)",
                                   "skills/baton-plan/SKILL.md"]


def _plugin(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "cache" / "baton"
    (root / "hooks").mkdir(parents=True)
    shutil.copy(HOOK, root / "hooks" / "baton_session_start.py")
    (root / "hooks" / "baton_stop.py").write_text("# stop\n", encoding="utf-8")
    (root / "hooks" / "hooks.json").write_text("{}\n", encoding="utf-8")
    (root / "skills" / "baton-plan").mkdir(parents=True)
    (root / "skills" / "baton-plan" / "SKILL.md").write_text("released\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    return root


def test_baton_source_compares_the_plugin_too(tmp_path, monkeypatch):
    """ZA-OPRAVYANE row 72 (22.10): row 50 made BATON_SOURCE work without a settings file, and
    as a plugin install_drift still returned [] before reading it."""
    root = _plugin(tmp_path, monkeypatch)
    src = _repo(tmp_path, {"baton-plan": "being written\n"})
    (src / "hooks.json").write_text('{"hooks": {}}\n', encoding="utf-8")
    monkeypatch.setenv("BATON_SOURCE", str(src))
    assert _load(root / "hooks").install_drift() == ["hooks.json", "skills/baton-plan/SKILL.md"]


def test_as_a_plugin_without_the_variable_nothing_is_compared(tmp_path, monkeypatch):
    root = _plugin(tmp_path, monkeypatch)
    src = _repo(tmp_path, {"baton-plan": "being written\n"})
    monkeypatch.delenv("BATON_SOURCE", raising=False)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "baton.local.json").write_text(json.dumps({"source": str(src)}), "utf-8")
    assert _load(root / "hooks").install_drift() == []
