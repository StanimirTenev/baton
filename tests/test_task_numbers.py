"""Task numbers: the human says "12 приключи" or "към 12" instead of typing a folder name.

The numbers live in one registry at the tasks root, `.baton-ids.json` -- never in the headers,
whose mtime a write would move (that has set off Stop before). SessionStart numbers every task
that has none, in the board's order; a number is never changed and never reused. The prompt hook
reads a number only where nothing else could be meant: a version, a date, a time, a hash or a
count names no task -- the negative strings below are from the session that asked for this.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "hooks" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bss = _load("baton_session_start")
bp = _load("baton_prompt")


def _task(root: Path, name: str, header: str = "state: active\nturn: us"):
    (root / name).mkdir(parents=True, exist_ok=True)
    (root / name / "LOGBOOK.md").write_text(
        f"---\n{header}\nnext: \"the move of {name}\"\n---\n\n## 2026-10-28 10:00 — entry\n\nx\n",
        encoding="utf-8")


def _board(root: Path, tmp_path: Path) -> str:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), BATON_HOME=str(root), BATON_LOGBOOK="LOGBOOK.md",
               BATON_SESSION_STATE=os.environ["BATON_SESSION_STATE"],
               BATON_LESSONS_STATE=str(tmp_path / "lessons.json"))
    out = subprocess.run([sys.executable, str(ROOT / "hooks" / "baton_session_start.py")],
                         input="{}", capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]


def _ids(root: Path) -> dict:
    return json.loads((root / ".baton-ids.json").read_text("utf-8"))


# --- the registry -------------------------------------------------------------------------------

def test_first_numbers_follow_the_board_order(tmp_path):
    """The board shows high priority on us first, then lower, then outside, frozen, finished;
    the smallest numbers go to the tasks shown first, not to the alphabet."""
    root = tmp_path / "tasks"
    _task(root, "a-done", "state: done")
    _task(root, "b-frozen", "state: frozen")
    _task(root, "c-theirs", "state: waiting\nturn: David")
    _task(root, "d-low", "state: active\nturn: us\npriority: low")
    _task(root, "e-high", "state: active\nturn: us\npriority: high")
    _board(root, tmp_path)
    assert _ids(root) == {"e-high": 1, "d-low": 2, "c-theirs": 3, "b-frozen": 4, "a-done": 5}


def test_every_group_shows_the_number_and_the_board_says_what_it_is(tmp_path):
    root = tmp_path / "tasks"
    _task(root, "a-done", "state: done")
    _task(root, "b-frozen", "state: frozen")
    _task(root, "e-high", "state: active\nturn: us\npriority: high")
    (root / "plain").mkdir()
    (root / "plain" / "LOGBOOK.md").write_text("## 2026-10-28 10:00 — x\n", encoding="utf-8")
    board = _board(root, tmp_path)
    assert "- 1 · e-high 🔴 [high] — the move of e-high" in board
    assert "- 2 · plain — last entry" in board
    assert "❄️ Frozen (not offered): 3 · b-frozen" in board
    assert "✅ Finished (not touched): 4 · a-done" in board
    assert "name a task by it" in board


def test_numbers_stay_from_one_session_to_the_next(tmp_path):
    """Priorities change; the numbers do not follow them."""
    root = tmp_path / "tasks"
    _task(root, "a", "state: active\nturn: us\npriority: low")
    _task(root, "b", "state: active\nturn: us\npriority: high")
    _board(root, tmp_path)
    first = _ids(root)
    _task(root, "a", "state: active\nturn: us\npriority: high")
    _task(root, "b", "state: done")
    _board(root, tmp_path)
    assert _ids(root) == first == {"b": 1, "a": 2}


def test_a_number_is_not_reused_after_its_folder_is_gone(tmp_path):
    root = tmp_path / "tasks"
    for n in ("a", "b", "c"):
        _task(root, n)
    _board(root, tmp_path)
    top = _ids(root)["c"]
    (root / "c" / "LOGBOOK.md").unlink()
    (root / "c").rmdir()
    _task(root, "d")
    board = _board(root, tmp_path)
    ids = _ids(root)
    assert ids["c"] == top and ids["d"] == top + 1
    assert f"- {top + 1} · d" in board


def test_a_new_folder_gets_the_highest_number_plus_one(tmp_path):
    root = tmp_path / "tasks"
    root.mkdir()
    (root / ".baton-ids.json").write_text(json.dumps({"old": 40, "other": 7}), "utf-8")
    _task(root, "other")
    _task(root, "new-one", "state: active\nturn: us\npriority: high")
    board = _board(root, tmp_path)
    assert _ids(root) == {"old": 40, "other": 7, "new-one": 41}
    assert "- 41 · new-one" in board and "- 7 · other" in board


def test_a_renamed_folder_is_a_new_folder(tmp_path):
    """Decided on purpose: the registry keys on the folder name and cannot tell a rename from a
    new task. The old name keeps its number, unused; the new name gets max + 1."""
    root = tmp_path / "tasks"
    _task(root, "old-name")
    _board(root, tmp_path)
    (root / "old-name").rename(root / "new-name")
    _board(root, tmp_path)
    assert _ids(root) == {"old-name": 1, "new-name": 2}


def test_a_corrupt_registry_is_said_and_left_as_it_is(tmp_path):
    """Not a crash, and not a silent renumbering: every number the human has used would then
    mean another task."""
    root = tmp_path / "tasks"
    _task(root, "a")
    (root / ".baton-ids.json").write_text("{not json", "utf-8")
    board = _board(root, tmp_path)
    assert (root / ".baton-ids.json").read_text("utf-8") == "{not json"
    assert "🔢 Baton could not read" in board and ".baton-ids.json" in board
    assert "- a — the move of a" in board and "name a task by it" not in board


def test_a_registry_of_the_wrong_shape_is_corrupt_too(tmp_path):
    root = tmp_path / "tasks"
    root.mkdir()
    (root / ".baton-ids.json").write_text(json.dumps({"a": "1"}), "utf-8")
    assert bss.ids_load(root) is None
    (root / ".baton-ids.json").write_text(json.dumps([1, 2]), "utf-8")
    assert bss.ids_load(root) is None


def test_the_registry_is_written_whole_and_in_utf8(tmp_path):
    """Through a temporary file and a replace -- the lessons register's idiom, atomic on Windows
    too. A Cyrillic folder name comes back as written."""
    root = tmp_path / "tasks"
    _task(root, "проба")
    _board(root, tmp_path)
    assert _ids(root) == {"проба": 1}
    assert "проба" in (root / ".baton-ids.json").read_text("utf-8")
    assert not list(root.glob("*.tmp"))


def test_nothing_is_written_when_no_task_is_new(tmp_path):
    """A write each session would be churn in a folder the human syncs."""
    root = tmp_path / "tasks"
    _task(root, "a")
    _board(root, tmp_path)
    reg = root / ".baton-ids.json"
    os.utime(reg, (1_000_000_000, 1_000_000_000))
    _board(root, tmp_path)
    assert reg.stat().st_mtime == 1_000_000_000


# --- the prompt hook: negatives first -----------------------------------------------------------

KNOWN = set(range(1, 101)) | {2026}     # every number in the strings below is a task, but 768/944


def _named(prompt: str) -> set:
    return bp.numbers_in(prompt) & KNOWN


def test_versions_dates_times_hashes_and_counts_name_no_task():
    for said in ("0.37.0", "v3.27.0", "b6b5c5e", "01.11", "10:30", "2026-10-28",
                 "преди 11 дни", "срокът 17.10 е минал", "1. направи това"):
        assert _named(said) == set(), said


def test_an_unknown_number_names_no_task():
    """`#944` is the marked form, but 944 is no task's number. `768 passed` starts the message --
    the rule a bare first word follows -- and is silent only because 768 is no task's number."""
    assert _named("#944") == set()
    assert _named("768 passed") == set()


def test_a_number_said_as_a_task_names_it():
    for said in ("12", "12 приключи", "към 12", "#12 е готова", "задача 12", "№12",
                 "Task 12 is finished", "отиваме към 12"):
        assert _named(said) == {12}, said


def test_a_bare_number_in_the_middle_of_a_long_message_names_nothing():
    assert _named("виж какво стана с онези 12 файла вчера") == set()
    assert _named("виж какво стана с онези файла вчера, задача 12") == {12}


def _prompt(root: Path, tmp_path: Path, prompt: str) -> str:
    env = {"BATON_HOME": str(root), "BATON_LOGBOOK": "LOGBOOK.md",
           "BATON_STATE_DIR": str(tmp_path / "state"), "PATH": "/usr/bin:/bin"}
    out = subprocess.run([sys.executable, str(ROOT / "hooks" / "baton_prompt.py")],
                         input=json.dumps({"prompt": prompt, "session_id": "s1"}),
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_n_priklyuchi_brings_the_task_and_how_to_close_it(tmp_path):
    root = tmp_path / "tasks"
    _task(root, "pokritie-shema")
    _task(root, "other")
    (root / ".baton-ids.json").write_text(json.dumps({"other": 3, "pokritie-shema": 12}), "utf-8")
    out = _prompt(root, tmp_path, "12 приключи")
    assert "pokritie-shema" in out and "other" not in out
    assert "`state: done` in the header of its LOGBOOK.md" in out
    assert "PLAN.md / PLAN-*.md" in out and "`result:`" in out


def test_a_version_string_brings_no_task(tmp_path):
    root = tmp_path / "tasks"
    _task(root, "a")
    (root / ".baton-ids.json").write_text(json.dumps({"a": 27}), "utf-8")
    assert _prompt(root, tmp_path, "v3.27.0") == ""
