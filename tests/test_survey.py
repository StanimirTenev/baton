"""The survey before installing: it finds what an earlier Claude setup left, and writes nothing.

The machine it is modelled on (Windows, 2026-09-30): dated logbook files in the profile
folder, memory under `projects/C--Windows-System32/`, work in folders on other drives whose
names have spaces and Cyrillic, a `CLAUDE.md` rule for the record, a hook of its own, and a
drive root where two folders out of many keep a `ДНЕВНИК.md`. The first run of the survey on
that machine proposed the drive root as the task root.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "baton_survey.py"
RULES = ROOT / "hooks" / "_install_rules.py"
HOOKS = ROOT / "hooks" / "_install_hooks.py"


def _load():
    spec = importlib.util.spec_from_file_location("baton_survey", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.SYSTEM = ()            # pytest's folders live under /tmp, which the survey skips
    return mod


def _old(path: Path, days: int):
    t = path.stat().st_mtime - days * 86400
    os.utime(path, (t, t))


@pytest.fixture
def machine(tmp_path):
    home = tmp_path / "home"
    config = home / ".claude"
    drive = tmp_path / "D"
    work = drive / "проект с интервал"
    work.mkdir(parents=True)
    (work / "ДНЕВНИК.md").write_text("# дневник\n", "utf-8")
    _old(work / "ДНЕВНИК.md", 20)
    (work / "notes.txt").write_text("newer than the logbook\n", "utf-8")
    (drive / "втори проект").mkdir()
    (drive / "втори проект" / "ДНЕВНИК.md").write_text("x\n", "utf-8")
    for name in ("Program Files", "Temp", "VS2022", "Logs", "music"):
        (drive / name).mkdir()

    mem = config / "projects" / "C--Windows-System32" / "memory"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text(
        f"- [Консултант](p.md) — папка `{work}\\`, чети преди всяка задача\n", "utf-8")
    (config / "CLAUDE.md").write_text(
        "# Правила\n\n## Дневник на задачите\n\nсъздай `YYYY-MM-DD_HHmm_<име>.md`\n", "utf-8")
    (config / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [
        {"hooks": [{"type": "command", "command": "their-own-hook.ps1"}]}]}}), "utf-8")
    for i in range(5):
        (home / f"2026-09-2{i}_1130_proekt-{i}.md").write_text("x\n", "utf-8")
    return home, config, drive, work


def _tree(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        st = p.stat()
        out[str(p)] = (st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()
                       if p.is_file() else "dir")
    return out


def test_it_finds_what_the_earlier_setup_left(machine):
    home, config, drive, work = machine
    s = _load().survey(home, config)
    assert [m["path"] for m in s["memory"]] == [
        str(config / "projects" / "C--Windows-System32" / "memory")]
    assert str(work) in [p["path"] for p in s["places"]], "a path with a space and Cyrillic, from memory"
    assert s["flat_logbooks"][0]["files"] == 5
    assert s["flat_logbooks"][0]["topics"][0] == ("proekt", 5)
    assert s["instructions"][0]["rules"], "the older rule for the record must be shown"
    assert any("their-own-hook" in h["command"] and not h["baton"] for h in s["hooks"])
    stale = [p for p in s["places"] if p["path"] == str(work)][0]["logbook"]
    assert stale["stale"], "a logbook older than the work beside it is not the current record"


def test_a_crowd_with_two_logbooks_is_not_a_task_root(machine):
    """Two folders out of seven keep a ДНЕВНИК.md -- the drive root is not a task root."""
    home, config, drive, _ = machine
    s = _load().survey(home, config)
    assert str(drive) not in [r["path"] for r in s["task_roots"]]
    assert s["proposal"]["home"] == str(home / "tasks")


def test_a_folder_of_tasks_is_proposed(tmp_path):
    home = tmp_path / "home"
    for t in ("a", "b", "c"):
        (home / "zadachi" / t).mkdir(parents=True)
        (home / "zadachi" / t / "DNEVNIK.md").write_text("x\n", "utf-8")
    s = _load().survey(home, home / ".claude")
    assert s["proposal"] == {"home": str(home / "zadachi"), "logbook": "DNEVNIK.md",
                             "why": "3 of its 3 folders already keep a DNEVNIK.md"}


def test_it_writes_nothing(machine):
    home, config, drive, _ = machine
    before = _tree(home.parent)
    r = subprocess.run([sys.executable, str(TOOL), "--home", str(home), "--config", str(config)],
                       capture_output=True)
    assert r.returncode == 0, r.stderr
    assert "Nothing was written" in r.stdout.decode("utf-8")
    assert _tree(home.parent) == before


def test_rules_carry_the_real_path_and_keep_a_copy(tmp_path):
    target = tmp_path / "CLAUDE.md"
    old = "# my rules\n\nkeep dated files\n".encode("utf-8")
    target.write_bytes(old)
    tasks = str(tmp_path / "D" / "задачи с интервал")
    r = subprocess.run([sys.executable, str(RULES), str(ROOT / "templates" / "CLAUDE.md"),
                        str(target), tasks, "ДНЕВНИК.md", "0"], capture_output=True)
    assert r.returncode == 0, r.stderr
    text = target.read_text("utf-8")
    assert text.startswith("# my rules"), "the old rules stay as they were"
    assert "$BATON_HOME" not in text and "~/tasks" not in text
    assert f"`{tasks}`" in text and "ДНЕВНИК.md" in text and "LOGBOOK.md" not in text
    copies = list(tmp_path.glob("CLAUDE.md.before-baton-*"))
    assert len(copies) == 1 and copies[0].read_bytes() == old
    subprocess.run([sys.executable, str(RULES), str(ROOT / "templates" / "CLAUDE.md"),
                    str(target), tasks, "ДНЕВНИК.md", "0"], check=True, capture_output=True)
    assert target.read_text("utf-8") == text, "a second run changes nothing"


def test_settings_are_copied_before_hooks_go_in(tmp_path):
    settings = tmp_path / "settings.json"
    old = json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say.ps1"}]}]}})
    settings.write_text(old, "utf-8")
    hookdir = tmp_path / "hooks"
    hookdir.mkdir()
    r = subprocess.run([sys.executable, str(HOOKS), str(settings), str(hookdir), sys.executable,
                        "0", str(tmp_path / "tasks"), "LOGBOOK.md"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    copies = list(tmp_path.glob("settings.json.before-baton-*"))
    assert len(copies) == 1 and copies[0].read_text("utf-8") == old
    assert "say.ps1" in settings.read_text("utf-8"), "the hook that was there stays"
