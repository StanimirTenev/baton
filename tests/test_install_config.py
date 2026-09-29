"""Reinstalling must not take the confidentiality list with it.

External review of v2.14.0, reproduced here before anything was touched: the installer
wrote `baton.local.json` from scratch with `home` and `logbook` only, so
`pregled_poveritelni`, `pregled_indeks` and `source` disappeared on a second run. And
it did that *before* validating `settings.json`, so an invalid settings file returned 1
with the config already destroyed.

The barrier that keeps client material off a hosted API reads that list. `baton_review`
is written to stop when the list is missing rather than treat it as empty — which is the
right refusal, and also means a silent reinstall turns the review tool off.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

INSTALL = Path(__file__).resolve().parent.parent / "hooks" / "_install_hooks.py"

EXISTING = {
    "home": "/home/x/tasks",
    "logbook": "LOGBOOK.md",
    "source": "/home/x/dev/baton",
    "pregled_indeks": "/home/x/memory/MEMORY.md",
    "pregled_poveritelni": ["acme", "акме", "client-alpha"],
}


def _run(tmp_path, settings_body="{}", dry="0"):
    hookdir = tmp_path / "hooks"
    hookdir.mkdir(exist_ok=True)
    local = hookdir / "baton.local.json"
    local.write_text(json.dumps(EXISTING, ensure_ascii=False, indent=2), encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(settings_body, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(INSTALL), str(settings), str(hookdir), sys.executable,
         dry, "/home/x/tasks", "LOGBOOK.md"],
        capture_output=True, text=True)
    return result, local


def test_a_second_install_keeps_every_key_it_does_not_own(tmp_path):
    result, local = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    after = json.loads(local.read_text(encoding="utf-8"))
    assert after["pregled_poveritelni"] == EXISTING["pregled_poveritelni"], (
        "the confidentiality list is what keeps client material off a hosted API")
    assert after["pregled_indeks"] == EXISTING["pregled_indeks"]
    assert after["source"] == EXISTING["source"]
    assert after["home"] == "/home/x/tasks" and after["logbook"] == "LOGBOOK.md"


def test_an_invalid_settings_file_leaves_the_config_byte_identical(tmp_path):
    """It used to write first and validate second, so a broken settings.json cost the
    config and returned 1."""
    hookdir = tmp_path / "hooks"
    hookdir.mkdir()
    local = hookdir / "baton.local.json"
    local.write_text(json.dumps(EXISTING, ensure_ascii=False, indent=2), encoding="utf-8")
    before = local.read_bytes()
    settings = tmp_path / "settings.json"
    settings.write_text("{ this is not json", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(INSTALL), str(settings), str(hookdir), sys.executable,
         "0", "/home/x/tasks", "LOGBOOK.md"],
        capture_output=True, text=True)
    assert result.returncode == 1, "an invalid settings.json must still fail"
    assert local.read_bytes() == before, "and must change nothing on the way out"


def test_a_dry_run_writes_nothing(tmp_path):
    _result, local = _run(tmp_path, dry="1")
    after = json.loads(local.read_text(encoding="utf-8"))
    assert after == EXISTING, "a dry run may not touch the file"


def test_all_three_hooks_are_registered_and_each_points_at_its_own_file(tmp_path):
    """2026-09-28: the third hook. A hook the installer does not register never runs,
    whatever the tests of the hook itself say."""
    result, _ = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    hooks = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["hooks"]
    want = {"SessionStart": "baton_session_start.py", "Stop": "baton_stop.py",
            "UserPromptSubmit": "baton_prompt.py"}
    for event, script in want.items():
        args = [a for g in hooks.get(event, []) for h in g["hooks"] for a in h.get("args", [])]
        assert any(a.endswith(script) for a in args), f"{event} does not run {script}: {args}"


def test_a_second_install_without_env_keeps_the_task_root_and_logbook(tmp_path):
    """2026-09-28, on this machine: `./install.sh` run again without BATON_HOME /
    BATON_LOGBOOK wrote the defaults (~/tasks, LOGBOOK.md) over DNEVNIK.md in ~/zadachi.
    Every hook then looked at an empty folder and said nothing -- the quiet failure. The
    header of install.sh promised "running it twice changes nothing"."""
    install = Path(__file__).resolve().parent.parent / "install.sh"
    home, claude, zad = tmp_path / "home", tmp_path / "claude", tmp_path / "zad"
    home.mkdir()
    env = {"HOME": str(home), "CLAUDE_CONFIG_DIR": str(claude), "PATH": os.environ["PATH"]}
    first = subprocess.run(["bash", str(install)], capture_output=True, text=True,
                           env={**env, "BATON_HOME": str(zad), "BATON_LOGBOOK": "DNEVNIK.md"})
    assert first.returncode == 0, first.stderr
    second = subprocess.run(["bash", str(install)], capture_output=True, text=True, env=env)
    assert second.returncode == 0, second.stderr
    cfg = json.loads((claude / "baton" / "hooks" / "baton.local.json").read_text(encoding="utf-8"))
    assert cfg["home"] == str(zad) and cfg["logbook"] == "DNEVNIK.md", cfg
    assert not (home / "tasks").exists(), "a second install created the default folder"
