"""The review tools from a plugin-only install: no installer, no baton.local.json next to it.

Found 2026-10-05 (ZA-OPRAVYANE #1): the review "worked from the plugin" on 03.10 only because
this machine also had the script install's settings. Alone, the plugin's copy stopped at "NO
index", and no folder a plugin keeps across updates was read -- the plugin's own hooks/ folder
is replaced on every update. Settings now also come from ${CLAUDE_PLUGIN_DATA}, the folder the
hooks already use, which the skills pass in. Run as the human runs them: a subprocess, clean HOME.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(tmp_path, tool, *args, data=None):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home)}
    if data is not None:
        env["CLAUDE_PLUGIN_DATA"] = str(data)
    return subprocess.run([sys.executable, str(ROOT / "tools" / tool), *args],
                          capture_output=True, text=True, env=env, timeout=60)


def test_key_check_runs_from_the_plugin_and_names_where_the_key_goes(tmp_path):
    out = _run(tmp_path, "baton_key.py", "--check")
    assert out.returncode == 1 and "no key stored" in out.stdout
    assert ".config/baton/env" in out.stdout


def test_review_reads_its_settings_from_the_plugin_data_folder(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    index = tmp_path / "MEMORY.md"
    index.write_text("- [x](x.md) — y\n", "utf-8")
    (data / "baton.local.json").write_text(
        json.dumps({"review_index": str(index), "review_confidential": []}), "utf-8")
    out = _run(tmp_path, "baton_review.py", "--stale", data=data)
    # Past the settings, stopped at the key: nothing is sent without one.
    assert "NO index" not in out.stdout + out.stderr
    assert "NO key" in out.stdout + out.stderr


def test_without_settings_the_review_says_where_to_put_them(tmp_path):
    data = tmp_path / "data"
    out = _run(tmp_path, "baton_review.py", "--stale", data=data)
    assert out.returncode != 0
    assert str(data / "baton.local.json") in out.stdout + out.stderr
