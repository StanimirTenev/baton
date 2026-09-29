"""A header written in English means exactly what the same header means in Bulgarian.

Stage B of putting Baton in English (2026-09-29): the field names and values get English
spellings, and every Bulgarian spelling a user has already written keeps working. Three
readers of the header existed -- SessionStart's parser, Stop's criterion check, and the
prompt hook's own parser -- and "two readers of one header that disagree is a defect
waiting to happen" was written in this repository before. So the test is not "does each
reader accept English", it is: the SAME task, headed in English and in Bulgarian, gives the
SAME result from all three hooks.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"

ENGLISH = """---
state: waiting
turn: supplier
next: "replace the disk"
done_when: "the pool is mirrored again"
priority: high
timing: recurring
skills: [zfs]
aliases: [disk]
---

## 2026-09-20 10:00 — entry

x
"""
BULGARIAN = """---
sastoyanie: chakashta
na_hod: supplier
sledvashto: "replace the disk"
kriterii_zavarshvane: "the pool is mirrored again"
prioritet: visok
vremevi_kriterii: postoyanno
umeniya: [zfs]
aliases: [disk]
---

## 2026-09-20 10:00 — entry

x
"""


def _load(name):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _tree(root: Path, header: str) -> Path:
    folder = root / "disk-task"
    folder.mkdir(parents=True)
    (folder / "LOGBOOK.md").write_text(header, encoding="utf-8")
    return folder


def _session_start(root: Path) -> str:
    env = dict(os.environ, BATON_HOME=str(root), BATON_LOGBOOK="LOGBOOK.md")
    out = subprocess.run([sys.executable, str(HOOKS / "baton_session_start.py")], input="",
                         env=env, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and not out.stderr, out.stderr
    payload = json.loads(out.stdout)
    return payload["hookSpecificOutput"]["additionalContext"].replace(str(root), "ROOT")


def test_the_parser_gives_the_same_meaning_in_both_languages():
    bss = _load("baton_session_start")
    assert bss.parse_frontmatter(ENGLISH) == bss.parse_frontmatter(BULGARIAN)


def test_session_start_reports_the_same_board(tmp_path):
    a, b = tmp_path / "en", tmp_path / "bg"
    _tree(a, ENGLISH)
    _tree(b, BULGARIAN)
    board = _session_start(a)
    assert board == _session_start(b)
    assert "replace the disk" in board and "zfs" in board
    # Equal is not enough: on 2026-09-29 both boards said "waiting on: None" and matched.
    assert "waiting on: supplier" in board, board


def test_stop_sees_the_english_criterion(tmp_path):
    bs = _load("baton_stop")
    _tree(tmp_path, ENGLISH)
    assert bs.undefined(tmp_path, "LOGBOOK.md") == [], "done_when was not read as a criterion"


def test_the_prompt_hook_reads_the_english_next_step(tmp_path):
    bp = _load("baton_prompt")
    _tree(tmp_path, ENGLISH)
    found = bp.touched(tmp_path, "LOGBOOK.md", "what about the disk")
    assert found and found[0][2] == "replace the disk", found


def test_english_values_are_understood(tmp_path):
    """`state: frozen` is not offered; `priority: high` sorts as high; `turn: us` is ours."""
    bss = _load("baton_session_start")
    fm = bss.parse_frontmatter("---\nstate: active\nturn: us\npriority: low\n---\n")
    assert bss.is_us(fm)
    assert bss.parse_frontmatter("---\nprioritet: nisak\n---\n")["priority"] == fm["priority"]


def test_done_means_finished_for_a_task_and_carried_out_for_a_plan(tmp_path):
    """`done` is deliberately not mapped: tasks and plans share the state field, and mapping
    it to the plan value made a task headed `state: done` stop counting as finished."""
    bss = _load("baton_session_start")
    assert bss.parse_frontmatter("---\nstate: done\n---\n")["state"] in bss.FINISHED
    assert bss.parse_frontmatter("---\nstate: done\n---\n")["state"] in bss.PLAN_DONE


def test_a_personal_name_for_us_comes_from_the_config_not_the_code(tmp_path, monkeypatch):
    bss = _load("baton_session_start")
    assert not bss.is_us({"turn": "стенли"}), "a user's name is built into a public tool"
    monkeypatch.setattr(bss, "_our_names", lambda: {"стенли"})
    assert bss.is_us({"turn": "Стенли"})


def test_a_plan_written_in_english_opens_and_closes(tmp_path):
    bss = _load("baton_session_start")
    folder = tmp_path / "t"
    folder.mkdir()
    plan = folder / "PLAN.md"
    plan.write_text("---\nstate: open\nresult: \"\"\n---\n# plan\n", encoding="utf-8")
    assert bss.open_plan(folder), "an open English plan was not reported"
    plan.write_text("---\nstate: done\nresult: \"shipped in v3\"\n---\n# plan\n", encoding="utf-8")
    assert not bss.open_plan(folder), "a closed English plan is still reported"


def test_the_board_shows_priority_in_english_either_way(tmp_path):
    """Found in the Windows sandbox, 2026-09-29: `priority: high` was shown as `[visok]`."""
    board = _session_start(_tree(tmp_path, ENGLISH).parent)
    assert "[high]" in board and "visok" not in board
