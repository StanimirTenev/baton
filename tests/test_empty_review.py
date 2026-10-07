"""A review that examined nothing must not read as a clean review.

The defect (tools/baton_review.py, the comment in `tasks`): the tool read a different
baton.local.json than the hooks did -- the source copy, which named no logbook -- found
no logbooks at all, printed an empty list and "cost: $0", and exited 0. Nothing failed.
An empty set had been verified and reported as done.

Said in public on 2026-10-07 ("ours covers only half of it"): the running hook was
compared with its source, the configuration was not. So two things are pinned here,
both through the CLI the way a human or a skill runs it:

- zero items examined is BLOCKED, with a non-zero exit, never an empty "(none)";
- every run says which configuration file it used, with a fingerprint of its bytes,
  so two runs that disagree can be told apart by the file that produced them.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "baton_review.py"


def _home(tmp_path: Path, config: dict | None = None) -> dict:
    """A fake HOME with a stored key, and optionally an installed baton.local.json."""
    home = tmp_path / "home"
    (home / ".config/baton").mkdir(parents=True)
    (home / ".config/baton/env").write_text("OPENROUTER_API_KEY=k\n", encoding="utf-8")
    if config is not None:
        hooks = home / ".claude/baton/hooks"
        hooks.mkdir(parents=True)
        (hooks / "baton.local.json").write_text(json.dumps(config), encoding="utf-8")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN_DATA"))}
    env["HOME"] = str(home)
    return env


def _run(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], env=env,
                          capture_output=True, text=True, timeout=60)


def test_tasks_over_an_empty_folder_is_blocked_not_clean(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tmp_path / "INDEX.md").write_text("", encoding="utf-8")
    env = _home(tmp_path, {"home": str(tasks), "review_index": str(tmp_path / "INDEX.md"),
                           "review_confidential": []})
    r = _run(env, "--tasks")
    out = r.stdout + r.stderr
    assert r.returncode != 0, f"an empty review exited 0:\n{out}"
    assert "BLOCKED" in out and "0" in out, out


def test_tasks_whose_logbook_name_matches_nothing_is_blocked(tmp_path):
    """The exact shape of the incident: folders exist, the logbook name is wrong."""
    tasks = tmp_path / "tasks"
    (tasks / "one").mkdir(parents=True)
    (tasks / "one" / "DNEVNIK.md").write_text("---\nnext: x\n---\n## entry\n", encoding="utf-8")
    (tmp_path / "INDEX.md").write_text("", encoding="utf-8")
    env = _home(tmp_path, {"home": str(tasks), "review_index": str(tmp_path / "INDEX.md"),
                           "review_confidential": []})     # logbook defaults to LOGBOOK.md
    r = _run(env, "--tasks")
    out = r.stdout + r.stderr
    assert r.returncode != 0, f"no logbook matched and the run exited 0:\n{out}"
    assert "BLOCKED" in out, out


def test_stale_whose_pointers_lead_nowhere_is_blocked(tmp_path):
    (tmp_path / "INDEX.md").write_text("- [Row](missing.md) — a claim\n", encoding="utf-8")
    env = _home(tmp_path, {"review_index": str(tmp_path / "INDEX.md"),
                           "review_confidential": []})
    r = _run(env, "--stale")
    out = r.stdout + r.stderr
    assert r.returncode != 0, f"nothing examined and the run exited 0:\n{out}"
    assert "BLOCKED" in out, out


def test_the_run_names_the_config_file_and_its_fingerprint(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tmp_path / "INDEX.md").write_text("", encoding="utf-8")
    env = _home(tmp_path, {"home": str(tasks), "review_index": str(tmp_path / "INDEX.md"),
                           "review_confidential": []})
    path = Path(env["HOME"]) / ".claude/baton/hooks/baton.local.json"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    out = _run(env, "--tasks").stdout
    assert str(path) in out, f"the config file is not named:\n{out}"
    assert digest in out, f"the config fingerprint {digest} is not shown:\n{out}"


def test_no_config_file_says_so_instead_of_naming_one(tmp_path):
    """Environment only: there is no file to fingerprint, and the run must not pretend."""
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tmp_path / "INDEX.md").write_text("", encoding="utf-8")
    env = _home(tmp_path)
    env.update({"BATON_HOME": str(tasks), "BATON_REVIEW_INDEX": str(tmp_path / "INDEX.md"),
                "BATON_REVIEW_CONFIDENTIAL": ""})
    out = _run(env, "--tasks").stdout
    assert "no config file" in out, out
