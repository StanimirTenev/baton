"""v3.47.0: optional header fields `awaiting:`, `asked:`, `model:`, and open questions for the human.

`turn:` said whose move it is, and "Waiting on YOU" mixed two different asks of the human: decide
something, or accept a result that is already delivered (ZA-OPRAVYANE rows 195 and 204, an idea
from DSH-projects; only the idea). `awaiting: <path>` names the delivered result; such a task goes
to a group of its own. `asked:` (the human's request, verbatim) and `model:` (the model for
subagents on this task) are only kept: no hook acts on them, and a header without them reads as
before. Open questions for the human are `- [ ] ...` lines in QUESTIONS.md (or VAPROSI.md, the
name /baton-plan uses); the board gives their count and the file, never their text.

Through the hook's entry point, as the harness runs it.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS))
import baton_session_start as hook  # noqa: E402


def _task(root: Path, name: str, header: str, files: dict | None = None) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "LOGBOOK.md").write_text(f"---\n{header}\n---\n\n## 2026-11-27 10:00 — entry\n\nx\n",
                                       encoding="utf-8")
    for fname, text in (files or {}).items():
        (folder / fname).write_text(text, encoding="utf-8")
    return folder


def _run(root: Path) -> tuple[str, str]:
    env = dict(os.environ, BATON_HOME=str(root), BATON_LOGBOOK="LOGBOOK.md")
    out = subprocess.run([sys.executable, str(HOOKS / "baton_session_start.py")], input="",
                         env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and not out.stderr, out.stderr
    payload = json.loads(out.stdout)
    return (payload["hookSpecificOutput"]["additionalContext"].replace(str(root), "ROOT"),
            payload.get("systemMessage", ""))


def _block(board: str, title: str) -> str:
    """The lines of one group, up to the next blank line."""
    start = board.find(title)
    assert start >= 0, f"no group {title!r} in:\n{board}"
    end = board.find("\n\n", start)
    return board[start:end if end > 0 else len(board)]


ACCEPT = "📥 Waiting for YOUR acceptance"
ON_YOU = "⏳ Waiting on YOU"


def test_a_delivered_result_is_its_own_group_not_waiting_on_you(tmp_path):
    _task(tmp_path, "report", 'state: active\nturn: us\nnext: "say yes or what to fix"\n'
                              'awaiting: "out/report-v2.pdf"')
    _task(tmp_path, "decide", 'state: active\nturn: us\nnext: "choose the region"')
    board, line = _run(tmp_path)
    accept = _block(board, ACCEPT)
    assert "report" in accept and "to accept: out/report-v2.pdf" in accept, accept
    assert "decide" not in accept
    assert "report" not in _block(board, ON_YOU)
    assert "1 to accept" in line, line


def test_awaiting_wins_over_a_turn_outside_and_keeps_the_deadline(tmp_path):
    _task(tmp_path, "t", "state: active\nturn: supplier\ntiming: 2026-01-01\n"
                         "awaiting: draft.md")
    board, _ = _run(tmp_path)
    accept = _block(board, ACCEPT)
    assert "to accept: draft.md" in accept and "deadline 2026-01-01" in accept, accept
    assert "OUTSIDE" not in board and "DEADLINE" not in board


def test_finished_and_frozen_win_over_awaiting(tmp_path):
    _task(tmp_path, "done-one", "state: finished\nturn: us\nawaiting: a.md")
    _task(tmp_path, "parked", "state: frozen\nturn: us\nawaiting: b.md")
    board, _ = _run(tmp_path)
    assert ACCEPT not in board, board


def test_an_empty_awaiting_is_no_awaiting(tmp_path):
    _task(tmp_path, "t", 'state: active\nturn: us\nawaiting: ""')
    board, line = _run(tmp_path)
    assert ACCEPT not in board and "t" in _block(board, ON_YOU)
    assert "to accept" not in line


def test_the_accepted_task_gets_a_number(tmp_path):
    _task(tmp_path, "t", "state: active\nturn: us\nawaiting: a.md")
    board, _ = _run(tmp_path)
    assert "- 1 · t" in _block(board, ACCEPT), board


def test_asked_and_model_change_nothing_on_the_board(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    plain = 'state: active\nturn: us\nnext: "run the export"\npriority: high'
    _task(a, "t", plain)
    _task(b, "t", plain + '\nasked: "he said: \\"export it all\\" #2, today"\nmodel: haiku')
    assert _run(a) == _run(b)


def test_asked_keeps_a_colon_a_hash_and_inner_quotes():
    fm = hook.parse_frontmatter('---\nasked: "make it: \\"faster\\" — see #12"\nmodel: sonnet\n---\n')
    assert fm["asked"] == 'make it: \\"faster\\" — see #12'
    assert fm["model"] == "sonnet"


QUESTIONS = """# Open questions

## For the human
- [ ] Which region is the tax region?
- [x] Do we keep the old export? — yes, 27.11
- [ ] Who signs the order?

## For research
- what does the API allow
1. a numbered one is not a checkbox
"""


def test_open_questions_for_the_human_are_counted_with_the_file(tmp_path):
    _task(tmp_path, "t", 'state: active\nturn: us\nnext: "go"', {"QUESTIONS.md": QUESTIONS})
    board, _ = _run(tmp_path)
    row = next(ln for ln in board.splitlines() if "· t" in ln)
    assert "2 open questions for you in QUESTIONS.md" in row, row
    assert "tax region" not in board, "the text of a question is not the board's"


def test_vaprosi_without_checkboxes_says_nothing(tmp_path):
    """The VAPROSI.md files written before 3.47.0 are free text: nothing in them is guessed at."""
    _task(tmp_path, "t", "state: active\nturn: us",
          {"VAPROSI.md": "# Отворени въпроси\n## За стенли\n- Р1 сума\n- ~~Р2~~ ✅\n1. кой\n"})
    board, _ = _run(tmp_path)
    assert "open question" not in board, board


def test_vaprosi_with_a_checkbox_counts_and_one_question_is_singular(tmp_path):
    _task(tmp_path, "t", "state: active\nturn: supplier",
          {"VAPROSI.md": "## За решение\n- [ ] Р4 кой инсталира на Mac\n"})
    board, _ = _run(tmp_path)
    row = next(ln for ln in board.splitlines() if "· t" in ln)
    assert "1 open question for you in VAPROSI.md" in row and "waiting on: supplier" in row, row


def test_no_questions_file_and_all_answered_say_nothing(tmp_path):
    _task(tmp_path, "a", "state: active\nturn: us")
    _task(tmp_path, "b", "state: active\nturn: us", {"QUESTIONS.md": "- [x] done\n- [X] too\n"})
    board, _ = _run(tmp_path)
    assert "open question" not in board, board


def test_open_questions_count_only_unchecked_boxes(tmp_path):
    folder = tmp_path / "t"
    folder.mkdir()
    (folder / "QUESTIONS.md").write_text(QUESTIONS, encoding="utf-8")
    assert hook.open_questions(folder) == ("QUESTIONS.md", 2)
