"""Reinstalling must not take the confidentiality list with it.

External review of v2.14.0, reproduced here before anything was touched: the installer
wrote `baton.local.json` from scratch with `home` and `logbook` only, so
`pregled_poveritelni`, `pregled_indeks` and `source` disappeared on a second run. And
it did that *before* validating `settings.json`, so an invalid settings file returned 1
with the config already destroyed.

The barrier that keeps client material off a hosted API reads that list. `baton_pregled`
is written to stop when the list is missing rather than treat it as empty — which is the
right refusal, and also means a silent reinstall turns the review tool off.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

INSTALL = Path(__file__).resolve().parent.parent / "hooks" / "_install_hooks.py"

EXISTING = {
    "home": "/home/x/tasks",
    "logbook": "LOGBOOK.md",
    "source": "/home/x/dev/baton",
    "pregled_indeks": "/home/x/memory/MEMORY.md",
    "pregled_poveritelni": ["darmi", "дарми", "client-alpha"],
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
