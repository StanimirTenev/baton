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


def test_a_partial_review_names_what_it_did_not_read(tmp_path):
    """Seven of ten is not zero, so BLOCKED does not fire -- and the output looked whole
    (Abhillash Jadhav, 2026-10-17). The run now says how many it was pointed at, how
    many it read, and names each one it did not, with the reason."""
    tasks = tmp_path / "tasks"
    for name, text in (("held", "---\nnext: x\n---\n## entry secretword\n"),
                       ("bare", "## entry without a header\n")):
        (tasks / name).mkdir(parents=True)
        (tasks / name / "DNEVNIK.md").write_text(text, encoding="utf-8")
    (tasks / "renamed").mkdir()
    (tasks / "renamed" / "LOGBOOK-old.md").write_text("x", encoding="utf-8")
    (tmp_path / "INDEX.md").write_text("", encoding="utf-8")
    env = _home(tmp_path, {"home": str(tasks), "logbook": "DNEVNIK.md",
                           "review_index": str(tmp_path / "INDEX.md"),
                           "review_confidential": ["secretword"]})
    out = _run(env, "--tasks").stdout
    assert "ACCOUNT: 3 task folders expected -- 0 reviewed, 1 held, 2 not read" in out, out
    assert "not read: bare (no header)" in out, out
    assert "not read: renamed (no DNEVNIK.md)" in out, out


def test_stale_names_a_pointer_whose_file_is_gone(tmp_path):
    (tmp_path / "INDEX.md").write_text("- [Row](missing.md) — a claim\n", encoding="utf-8")
    env = _home(tmp_path, {"review_index": str(tmp_path / "INDEX.md"),
                           "review_confidential": []})
    out = _run(env, "--stale").stdout
    assert "ACCOUNT: 1 pointers expected -- 0 reviewed, 0 held, 1 not read" in out, out
    assert "not read: missing.md (no file)" in out, out


def _partial_home(tmp_path, required=None):
    """Three folders: one held, one with no header, one whose logbook was renamed."""
    tasks = tmp_path / "tasks"
    for name, text in (("held", "---\nnext: x\n---\n## entry secretword\n"),
                       ("bare", "## entry without a header\n")):
        (tasks / name).mkdir(parents=True)
        (tasks / name / "DNEVNIK.md").write_text(text, encoding="utf-8")
    (tasks / "renamed").mkdir()
    (tasks / "renamed" / "LOGBOOK-old.md").write_text("x", encoding="utf-8")
    (tmp_path / "INDEX.md").write_text("", encoding="utf-8")
    cfg = {"home": str(tasks), "logbook": "DNEVNIK.md", "review_index": str(tmp_path / "INDEX.md"),
           "review_confidential": ["secretword"]}
    if required is not None:
        cfg["review_required"] = required
    return _home(tmp_path, cfg)


def test_a_partial_review_says_partial_and_does_not_exit_clean(tmp_path):
    """The second half of Jadhav's point (17.10): seven of ten still exited 0, and the output
    did not say PARTIAL. Through the CLI, the way a human or a skill runs it."""
    r = _run(_partial_home(tmp_path), "--tasks")
    out = r.stdout + r.stderr
    assert r.returncode == 2, f"a partial review exited {r.returncode}:\n{out}"
    assert "PARTIAL" in out and "bare" in out and "renamed" in out, out
    assert "BLOCKED" not in out, out


def test_required_input_that_is_missing_is_blocked(tmp_path):
    """`review_required`: every folder it was pointed at must be read, or the run is BLOCKED."""
    r = _run(_partial_home(tmp_path, required=True), "--tasks")
    out = r.stdout + r.stderr
    assert r.returncode == 1 and "BLOCKED" in out, out
    assert "bare" in out and "renamed" in out, out


def test_seven_of_ten_read_is_partial_with_the_three_named(tmp_path, monkeypatch, capsys):
    """Some reviewed, some not -- the case BLOCKED-at-zero never saw. The model is stubbed."""
    import importlib.util
    import pytest
    spec = importlib.util.spec_from_file_location("br_partial", TOOL)
    br = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(br)
    tasks = tmp_path / "tasks"
    for i in range(10):
        (tasks / f"t{i}").mkdir(parents=True)
        if i < 7:
            (tasks / f"t{i}" / "DNEVNIK.md").write_text("---\nnext: go on\n---\n## e\n", "utf-8")
    monkeypatch.setattr(br, "value_of", lambda *a, **k: (0.1, [0.1], 0.0))
    monkeypatch.setattr(br, "log_spend", lambda *a, **k: None)
    cfg = {"home": str(tasks), "logbook": "DNEVNIK.md", "confidential": [], "source": None}
    with pytest.raises(SystemExit) as stop:
        br.tasks("k", cfg, set())
    out = capsys.readouterr().out
    assert stop.value.code == 2, out
    assert "PARTIAL: 7 of 10 task folders read" in out and "t7, t8, t9" in out, out
    cfg["required"] = True
    with pytest.raises(SystemExit) as stop:
        br.tasks("k", cfg, set())
    assert "BLOCKED" in str(stop.value.code) and "t7, t8, t9" in str(stop.value.code)


def _stray_folder(tmp_path, ignore: str | None):
    """Two tasks and a folder of photos (ZA-OPRAVYANE row 31, the probe of 21.10)."""
    tasks = tmp_path / "tasks"
    for name in ("a", "b"):
        (tasks / name).mkdir(parents=True)
        (tasks / name / "DNEVNIK.md").write_text("---\nnext: go on\n---\n## e\n", "utf-8")
    (tasks / "snimki").mkdir()
    (tasks / "snimki" / "photo.jpg").write_bytes(b"\xff\xd8")
    if ignore is not None:
        (tasks / ".batonignore").write_text(ignore, "utf-8")
    return tasks


def _tasks_stubbed(tmp_path, monkeypatch, tasks, required=False):
    import importlib.util
    spec = importlib.util.spec_from_file_location("br_stray", TOOL)
    br = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(br)
    monkeypatch.setattr(br, "value_of", lambda *a, **k: (0.1, [0.1], 0.0))
    monkeypatch.setattr(br, "log_spend", lambda *a, **k: None)
    cfg = {"home": str(tasks), "logbook": "DNEVNIK.md", "confidential": [], "source": None,
           "required": required}
    try:
        br.tasks("k", cfg, set())
        return 0
    except SystemExit as stop:
        return stop.code


def test_a_stray_folder_makes_the_review_partial(tmp_path, monkeypatch, capsys):
    """The defect as found: one folder of photos and every run is PARTIAL. Kept as it is --
    a folder that lost its logbook must still be named."""
    code = _tasks_stubbed(tmp_path, monkeypatch, _stray_folder(tmp_path, None))
    out = capsys.readouterr().out
    assert code == 2 and "PARTIAL: 2 of 3" in out and "snimki" in out, out


def test_a_folder_the_root_batonignore_names_is_not_a_task(tmp_path, monkeypatch, capsys):
    """Row 31: a folder can be declared not a task -- in a `.batonignore` at the task root --
    and is then neither expected nor missing. It is named as skipped, never hidden."""
    tasks = _stray_folder(tmp_path, "# not tasks\nsnimki\n")
    code = _tasks_stubbed(tmp_path, monkeypatch, tasks)
    out = capsys.readouterr().out
    assert code in (0, None), out
    assert "PARTIAL" not in out and "ACCOUNT: 2 task folders expected" in out, out
    assert "skipped (the task root's .batonignore): snimki" in out, out
    code = _tasks_stubbed(tmp_path, monkeypatch, tasks, required=True)
    assert code in (0, None), "review_required: a declared non-task is not required input"
