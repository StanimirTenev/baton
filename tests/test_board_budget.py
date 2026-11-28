"""v3.48.0: a board that reaches the agent whole.

Claude Code keeps 10,000 characters of a hook's context field and gives the agent a path and the
first 2,000 of the rest. On the maintainer's machine the board was 18,423 characters on
28.11.2026; the preview ended at the fourth task, and every warning below it never reached the
agent. So: each check is a tag on its task's own line (`⚠plan`), one legend line names the command
for the full text, the whole field is held under 9,000 characters by collapsing from the bottom
up, sub-tasks fold into their parent (`parent:`), reminders (`remind:`) stand at the top, and a
task with no entry for 30 days is offered for freezing.

Every hook run here is a subprocess fed JSON on stdin, as the harness runs it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from conftest import child_env

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_session_start.py"
sys.path.insert(0, str(ROOT / "hooks"))
import baton_session_start as hook  # noqa: E402

DAY = 86400


def _day(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _task(root: Path, name: str, header: str, entry_days_ago: int = 1, age_s: float = DAY) -> Path:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    book = folder / "LOGBOOK.md"
    book.write_text(f"---\n{header}---\n\n## {_day(entry_days_ago)} 10:00 — an entry\n\nx\n",
                    encoding="utf-8")
    then = time.time() - age_s
    os.utime(book, (then, then))
    return folder


def _env(tmp_path: Path, root: Path, plugin: bool = False, **extra) -> dict:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = child_env(BATON_HOME=str(root), BATON_LOGBOOK="LOGBOOK.md", HOME=str(home),
                    USERPROFILE=str(home), CLAUDE_PLUGIN_DATA=str(tmp_path / "data"),
                    BATON_PAGE="off", BATON_SESSION_STATE=str(tmp_path / "s.json"),
                    BATON_BODY_STATE=str(tmp_path / "bodies.json"),
                    BATON_LESSONS_STATE=str(tmp_path / "lessons.json"),
                    BATON_IDENTITY=str(tmp_path / "identity"), LANG="C.UTF-8", **extra)
    if plugin:
        env["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
    return env


def _board(tmp_path: Path, root: Path, source: str = "startup", **kw) -> str:
    out = subprocess.run([sys.executable, str(HOOK)],
                         input=json.dumps({"source": source}).encode("utf-8"),
                         env=_env(tmp_path, root, **kw), capture_output=True, timeout=120)
    assert out.returncode == 0 and not out.stderr, out.stderr.decode("utf-8", "replace")
    return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]


def _line(board: str, name: str) -> str:
    """The board line of one task (its own, not a mention in another line)."""
    hits = [ln for ln in board.splitlines() if re.match(rf"^\s*- (\d+ · )?{re.escape(name)}\b", ln)]
    assert len(hits) == 1, (name, hits)
    return hits[0]


def _ids(root: Path) -> dict:
    return json.loads((root / ".baton-ids.json").read_text("utf-8"))


US = "state: active\nturn: us\npriority: medium\n"
OUT = "state: waiting\nturn: supplier\npriority: medium\n"


# -- 1. a check is a tag on its task's line ----------------------------------------------------

def test_an_open_plan_is_a_tag_on_its_task_line_and_the_legend_says_it_every_session(tmp_path):
    root = tmp_path / "tasks"
    f = _task(root, "billing", US + 'next: "send the invoice"\n')
    (f / "PLAN.md").write_text("---\nstate: open\n---\n", "utf-8")
    _task(root, "clean", US + 'next: "nothing wrong"\n')
    board = _board(tmp_path, root)
    assert "⚠plan" in _line(board, "billing")
    assert "⚠" not in _line(board, "clean")
    legend = next(ln for ln in board.splitlines() if ln.startswith("⚠ Tags"))
    assert "⚠plan (1)" in legend and "NOT done" in legend and "--details" in legend
    assert "UNCLOSED PLANS" not in board and "shelf life" not in board   # the long sections left


def test_every_check_has_a_tag_and_a_legend(tmp_path):
    """A tag the legend does not explain is noise; a legend entry no check uses is dead."""
    src = HOOK.read_text("utf-8")
    used = set(re.findall(r'tags\.append\(\("([\w/]+)"', src)) | {"parent"}
    assert used == set(hook.CHECKS), (used, set(hook.CHECKS))


def test_an_unverified_debt_is_counted_on_the_line(tmp_path):
    root = tmp_path / "tasks"
    f = _task(root, "claims", US + 'next: "x"\n')
    (f / "TVARDENIYA.md").write_text(
        "| claim | status | date | time |\n|---|---|---|---|\n"
        f"| a | И | {_day(45)} | 10:00 |\n| b | А | {_day(40)} | 10:00 |\n", "utf-8")
    assert "⚠I/A 2" in _line(_board(tmp_path, root), "claims")


# -- 3. the budget --------------------------------------------------------------------------

def _many(root: Path, n: int = 100) -> None:
    long_next = "the next move, written out at length as people do when they are in a hurry " * 3
    for i in range(n):
        kind = (US, OUT, "state: ongoing\nturn: us\npriority: low\n", "state: frozen\n",
                "state: finished\nresult: done\n")[i % 5]
        _task(root, f"task-{i:03d}-with-a-longish-folder-name", kind + f'next: "{long_next}{i}"\n')
    _task(root, "certs", "state: finished\nresult: x\nremind:\n"
                         f'  - "{(date.today() + timedelta(days=3)).isoformat()}: TLS of a.example expires"\n')


def _whole_lines(board: str, whole: str) -> None:
    """Never cut mid-line: each line is a line of the whole board, or that line with `next`
    shortened (ends in …), or a collapsed group or count, or the note."""
    full = whole.splitlines()
    for ln in board.splitlines():
        if ln in full or ln.startswith("✂️ Shortened") or "in the full board file" in ln:
            continue
        if ln.endswith("…"):
            assert any(f.startswith(ln[:-1].rstrip()) for f in full), ln
            continue
        if re.match(r"^\S.*: \d+ -- ", ln):                    # a group as names or numbers
            continue
        stem = ln.split("  (")[0].rstrip()
        assert any(f.split(" — ")[0] == stem for f in full), ln   # `next` dropped, rest whole


def test_a_hundred_long_tasks_fit_under_the_budget_and_the_whole_board_is_kept(tmp_path):
    root = tmp_path / "tasks"
    _many(root)
    board = _board(tmp_path, root)
    assert len(board) <= hook.BOARD_BUDGET, len(board)
    note = next(ln for ln in board.splitlines() if ln.startswith("✂️ Shortened"))
    whole_path = Path(re.search(r"the full board file is (\S+) --", note).group(1))
    assert whole_path == tmp_path / "data" / "baton.board.full.txt"
    whole = whole_path.read_text("utf-8")
    assert len(whole) > hook.BOARD_BUDGET
    for i in range(100):
        assert f"task-{i:03d}" in whole
    assert "TLS of a.example expires" in board, "a reminder is never collapsed"
    _whole_lines(board, whole)


def test_the_budget_holds_with_the_rules_and_a_clear_and_an_update_notice(tmp_path):
    """In plugin mode the rules share the field (about 5,500 characters); after /clear the board
    carries its note, and the first session of a version carries what is new."""
    root = tmp_path / "tasks"
    _many(root)
    (tmp_path / "s.json").write_text(json.dumps({"seen_version": "3.11.0"}), "utf-8")
    board = _board(tmp_path, root, source="clear", plugin=True)
    assert "Baton's working rules" in board and "/clear" in board
    assert len(board) <= hook.BOARD_BUDGET, len(board)
    assert "TLS of a.example expires" in board


def test_a_small_board_is_not_shortened(tmp_path):
    root = tmp_path / "tasks"
    _task(root, "one", US + 'next: "x"\n')
    board = _board(tmp_path, root)
    assert "✂️" not in board and not (tmp_path / "data" / "baton.board.full.txt").exists()


def test_collapse_starts_at_the_bottom(tmp_path):
    """Just over the budget, the finished list is counted first; the groups keep their `next`."""
    root = tmp_path / "tasks"
    for i in range(30):
        _task(root, f"ours-{i:02d}", US + f'next: "short move {i}"\n')
    for i in range(400):
        _task(root, f"done-{i:03d}-a-finished-task", "state: finished\nresult: x\n")
    board = _board(tmp_path, root)
    assert "✅ Finished (not touched): 400 -- in the full board file" in board
    assert "short move 7" in _line(board, "ours-07")
    assert "as far as: finished;" in board


# -- 4. parent: ----------------------------------------------------------------------------

def test_a_sub_task_folds_into_its_parents_line(tmp_path):
    root = tmp_path / "tasks"
    _task(root, "baton", US + 'priority: high\nnext: "the parent"\n')
    _task(root, "baton-firmi", OUT + "parent: baton\n" + 'next: "child outside"\n')
    _task(root, "baton-plugin", "state: ongoing\nturn: us\nparent: baton\nnext: \"child ongoing\"\n")
    board = _board(tmp_path, root)
    assert "child outside" not in board and "child ongoing" not in board
    ids = _ids(root)
    assert "baton-firmi" in ids and "baton-plugin" in ids        # still a task with its number
    line = _line(board, "baton")
    assert "(+2 sub-tasks:" in line
    assert str(ids["baton-firmi"]) in line and str(ids["baton-plugin"]) in line


def test_a_sub_task_on_the_humans_move_is_shown_under_its_parent_and_lifts_it(tmp_path):
    root = tmp_path / "tasks"
    _task(root, "supplier", OUT + 'next: "the parent waits outside"\n')
    _task(root, "decide", US + "parent: supplier\n" + 'next: "the human decides"\n')
    board = _board(tmp_path, root)
    ours = board.split("⏳ Waiting on YOU / can continue now:\n", 1)[1].split("\n\n", 1)[0]
    rows = ours.splitlines()
    assert rows[0].startswith("- ") and "supplier" in rows[0] and "(+1 sub-task:" in rows[0]
    assert rows[1].startswith("  - ") and "decide" in rows[1] and "the human decides" in rows[1]
    assert "OUTSIDE" not in board, "the parent was lifted out of the outside group"


def test_a_child_tag_shows_on_the_parents_line(tmp_path):
    root = tmp_path / "tasks"
    _task(root, "p", OUT + 'next: "x"\n')
    c = _task(root, "c", OUT + "parent: p\n" + 'next: "y"\n')
    (c / "PLAN.md").write_text("---\nstate: open\n---\n", "utf-8")
    board = _board(tmp_path, root)
    assert re.search(r"\(\+1 sub-task: \d+ ⚠plan\)", _line(board, "p")), _line(board, "p")
    assert "⚠plan (1)" in board


def test_a_parent_that_cannot_hold_it_leaves_the_child_on_its_own_tagged(tmp_path):
    root = tmp_path / "tasks"
    _task(root, "grand", US + 'next: "g"\n')
    _task(root, "mid", US + "parent: grand\n" + 'next: "m"\n')
    _task(root, "leaf", US + "parent: mid\n" + 'next: "under a sub-task"\n')
    _task(root, "orphan", US + "parent: nowhere\n" + 'next: "no such parent"\n')
    _task(root, "self", US + "parent: self\n" + 'next: "its own parent"\n')
    _task(root, "shut", "state: finished\nresult: x\n")
    _task(root, "late", US + "parent: shut\n" + 'next: "parent finished"\n')
    board = _board(tmp_path, root)
    for name in ("leaf", "orphan", "self", "late"):
        assert "⚠parent" in _line(board, name), name
    assert "(+1 sub-task:" in _line(board, "grand")             # mid folds; leaf does not


# -- 5. freeze suggestion ------------------------------------------------------------------

def test_tasks_with_no_entry_for_thirty_days_are_offered_for_freezing(tmp_path):
    root = tmp_path / "tasks"
    _task(root, "quiet-outside", OUT + 'next: "x"\n', entry_days_ago=40, age_s=60)  # fresh mtime
    _task(root, "quiet-ongoing", "state: ongoing\nturn: us\nnext: \"x\"\n", entry_days_ago=31)
    _task(root, "quiet-ours", US + 'next: "x"\n', entry_days_ago=40)           # the human's move
    _task(root, "recent-outside", OUT + 'next: "x"\n', entry_days_ago=10)
    _task(root, "parked", "state: frozen\n", entry_days_ago=90)
    board = _board(tmp_path, root)
    line = next(ln for ln in board.splitlines() if ln.startswith("💤"))
    assert line.startswith("💤 2 without an entry for 30+ days:")
    assert "quiet-outside" in line and "quiet-ongoing" in line
    for name in ("quiet-ours", "recent-outside", "parked"):
        assert name not in line
    assert "`state: frozen`" in line
    assert "state: waiting" in (root / "quiet-outside" / "LOGBOOK.md").read_text("utf-8")


# -- 6. an open plan in a finished or frozen task --------------------------------------------

def test_an_open_plan_in_a_finished_or_frozen_task_is_one_line(tmp_path):
    root = tmp_path / "tasks"
    for name, head in (("shipped", "state: finished\nresult: x\n"), ("parked", "state: frozen\n")):
        f = _task(root, name, head)
        (f / "PLAN.md").write_text("---\nstate: open\n---\n", "utf-8")
    _task(root, "other", US + 'next: "x"\n')
    board = _board(tmp_path, root)
    line = next(ln for ln in board.splitlines() if ln.startswith("⛔ An open plan"))
    ids = _ids(root)
    assert f"{ids['shipped']} · shipped" in line and f"{ids['parked']} · parked" in line
    assert "close them" in line


# -- 7. remind: ------------------------------------------------------------------------------

def test_the_header_reads_both_list_forms():
    text = ("---\nstate: active\nskills: [a, b]\naliases: [диск, 'disk']\nremind:\n"
            '  - "2026-12-09: TLS of a.com, b.com expires"\n  - 2026-12-20: plain # comment\n'
            'next: "x"\nr2: ["2026-12-09: renew, then tell Ivan", \'2027-01-01: y\']\n'
            "- stray: line\n---\n")
    fm = hook.parse_frontmatter(text)
    assert fm["remind"] == ["2026-12-09: TLS of a.com, b.com expires", "2026-12-20: plain"]
    assert fm["r2"] == ["2026-12-09: renew, then tell Ivan", "2027-01-01: y"]
    assert fm["skills"] == ["a", "b"] and fm["aliases"] == ["диск", "disk"]
    assert fm["next"] == "x" and fm["- stray"] == "line"        # outside a list, as before


def test_reminders_stand_at_the_top_near_or_past_with_the_task_number(tmp_path):
    root = tmp_path / "tasks"
    soon = (date.today() + timedelta(days=5)).isoformat()
    past = (date.today() - timedelta(days=3)).isoformat()
    far = (date.today() + timedelta(days=40)).isoformat()
    _task(root, "certs", US + 'next: "x"\nremind:\n'
                              f'  - "{soon}: TLS certificate of example.com expires"\n'
                              f'  - "{far}: far away"\n  - "sometime: no date"\n')
    _task(root, "grant", "state: finished\nresult: x\n"
                         f'remind: ["{past}: the call closes, for the partner"]\n')
    board = _board(tmp_path, root)
    ids = _ids(root)
    block = board.split("⏰ Reminders", 1)[1].split("\n\n", 1)[0]
    assert board.index("⏰ Reminders") < board.index("⏳ Waiting on YOU")
    assert "1 later" in block and "far away" not in board
    assert f"{soon}, in 5 days — TLS certificate of example.com expires  ({ids['certs']} · certs)" in block
    assert f"{past}, OVERDUE by 3 days — the call closes, for the partner  ({ids['grant']} · grant)" in block
    assert f"⚠remind {ids['certs']} · certs: cannot read \"sometime: no date\"" in block
    rows = block.splitlines()[1:]
    assert "OVERDUE" in rows[1] and "in 5 days" in rows[2]      # unreadable first, then by date


def test_only_far_reminders_leave_one_count_line(tmp_path):
    root = tmp_path / "tasks"
    far = (date.today() + timedelta(days=40)).isoformat()
    _task(root, "a", US + f'next: "x"\nremind: ["{far}: later"]\n')
    assert "⏰ Reminders (within 14 days, or past); 1 later: none now." in _board(tmp_path, root)


# -- the collapse ladder, step by step -------------------------------------------------------

def test_each_collapse_step_in_its_order(tmp_path, monkeypatch):
    """One board, the budget lowered step by step, the hook run in-process: every one of the
    eighteen steps is reached, in its order, and each does what it says. The order is the
    human's (28.11): the lessons, the ledger, the page and the tag legend shrink before any task
    loses its `next`, and `next` goes outside first, then ongoing, then the human's own. Below the
    last step, whole lines of the notices go while the reminder stays."""
    root = tmp_path / "tasks"
    long_next = ("a next move written out at some length, well past ninety characters, so that "
                 "a cut shows, number ")
    for i in range(6):
        _task(root, f"us-{i}", US + f'next: "{long_next}{i}"\n')
        _task(root, f"on-{i}", f'state: ongoing\nturn: us\nnext: "{long_next}{i}"\n')
        f = _task(root, f"out-{i}", OUT + f'next: "{long_next}{i}"\n')
        if i == 0:
            (f / "PLAN.md").write_text("---\nstate: open\n---\n", "utf-8")
    for i in range(20):
        _task(root, f"frozen-{i:02d}-a-parked-task", "state: frozen\n")
        _task(root, f"done-{i:02d}-a-finished-task", "state: finished\nresult: x\n")
    for i in range(8):
        (root / f"plain-{i}").mkdir()
        (root / f"plain-{i}" / "LOGBOOK.md").write_text(f"## {_day(1)} 10:00 — plain {i}\n", "utf-8")
    soon = (date.today() + timedelta(days=2)).isoformat()
    _task(root, "certs", f'state: finished\nresult: x\nremind: ["{soon}: the cert expires"]\n')
    env = _env(tmp_path, root)
    env["BATON_PAGE"] = ""                          # the page block is one of the steps
    for k in [k for k in os.environ if k.startswith(("BATON_", "CLAUDE_PLUGIN"))]:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    now = __import__("datetime").datetime.now()
    state: dict = {}
    for lid in ("L1", "L3"):
        for d in (3, 1):
            hook.lesson_event(state, lid, "fired", now - timedelta(days=d))
            hook.lesson_event(state, lid, "caught", now - timedelta(days=d))
    (tmp_path / "lessons.json").write_text(json.dumps(state), "utf-8")

    def fake_ledger(root_, name_):                   # a ledger with one entry changed
        full = ("🧾 Baton's ledger of logbook entries: 1 recorded entry changed after Baton recorded "
                "it -- us-0: \"2026-11-01 10:00 — a long title of an entry that was edited later, "
                "long enough that one line of counts is shorter than the whole notice by far\". "
                "An entry is a record, not edited. Tell the human. `verify` shows it.")
        hook.NOTICE_FORMS[full] = {"one": "🧾 Baton's ledger: recorded logbook entries 1 changed"}
        return full
    monkeypatch.setattr(hook, "ledger_notice", fake_ledger)
    import io
    said = {}
    monkeypatch.setattr(hook, "_write", lambda out: said.update(out))

    def run(budget: int) -> str:
        monkeypatch.setattr(hook, "BOARD_BUDGET", budget)
        (tmp_path / "s.json").write_text(json.dumps({"seen_version": "3.11.0"}), "utf-8")
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"source": "resume"}')))
        said.clear()
        hook.main()
        return said["hookSpecificOutput"]["additionalContext"]

    full = run(10 ** 6)
    assert "✂️" not in full and "⬆️ Baton was updated" in full
    assert "L1 recurred 2 times" in full and "📄 Baton page (ID" in full and "a long title" in full
    seen: dict = {}
    floor = []                                  # every board at the last step
    for budget in range(len(full), 600, -6):
        board = run(budget)
        m = re.search(r"as far as: (.+?); ", board)
        if m:
            if m.group(1) not in seen:
                seen[m.group(1)] = (budget, board)
            if m.group(1) == "every group as numbers":
                floor.append(board)
            else:
                assert len(board) <= budget, (budget, len(board), m.group(1))
    names = ["finished", "frozen", "no header", "lessons shortened", "lessons in one line",
             "ledger in one line", "page in one line", "tag legend shortened",
             "`next` of outside shortened", "`next` of ongoing shortened",
             "every `next` shortened", "`next` of outside dropped",
             "`next` of ongoing dropped", "every `next` dropped",
             "ongoing/outside as names", "every group as names",
             "ongoing/outside as numbers", "every group as numbers"]
    assert list(seen) == names, list(seen)
    b = {n: seen[n][1] for n in names}
    whole = long_next.strip()
    assert "✅ Finished (not touched): 21 -- in the full board file" in b["finished"]
    assert "frozen-00" in b["finished"]
    assert "❄️ Frozen (not offered): 20 -- in the full board file" in b["frozen"]
    assert "📋 No header (most recently touched)" in b["frozen"]
    assert "📋 No header: 8 -- in the full board file" in b["no header"]
    # 4-8: the notices and the legend shrink while every `next` is whole.
    assert "L1 recurred 2 times in 14 days: not holding" in b["lessons shortened"]
    assert "(1048" not in b["lessons shortened"] and "rung in place" in b["lessons shortened"]
    assert re.search(r"^Baton -- lessons: L1 not holding \(2/14d\), L3 doing its work \(2/14d\) "
                     r"\(the full text: `--details`, the command above\)$", b["lessons in one line"],
                     re.M)
    assert "a long title" in b["lessons in one line"]
    assert "a long title" not in b["ledger in one line"]
    assert "🧾 Baton's ledger: recorded logbook entries 1 changed" in b["ledger in one line"]
    assert "📄 Baton page (ID" in b["ledger in one line"]
    assert re.search(r"^📄 Baton page, only when the human asks: `\S+ \S+baton_page.py --open`\.$",
                     b["page in one line"], re.M)
    assert "⚠ Tags on the task lines" in b["page in one line"]
    assert "⚠ Tags (tasks): ⚠plan 1 open plan: task not done" in b["tag legend shortened"]
    assert "--details`" in b["tag legend shortened"]
    for n in names[3:8]:
        for t in ("us-0", "on-0", "out-0"):
            assert whole in _line(b[n], t), (n, t)
    # 9-14: `next` shortened, then dropped -- outside, ongoing, the human's own.
    cut = lambda board, t: _line(board, t).split("  (")[0]   # noqa: E731
    assert cut(b["`next` of outside shortened"], "out-0").endswith("…")
    assert whole in _line(b["`next` of outside shortened"], "on-0")
    assert _line(b["`next` of ongoing shortened"], "on-0").endswith("…")
    assert whole in _line(b["`next` of ongoing shortened"], "us-0")
    assert _line(b["every `next` shortened"], "us-0").endswith("…")
    assert len(_line(b["every `next` shortened"], "us-0").split(" — ")[1]) <= hook.NEXT_SHORT + 1
    assert " — " not in _line(b["`next` of outside dropped"], "out-0")
    assert _line(b["`next` of outside dropped"], "on-0").endswith("…")
    assert " — " not in _line(b["`next` of ongoing dropped"], "on-0")
    assert _line(b["`next` of ongoing dropped"], "us-0").endswith("…")
    assert " — " not in _line(b["every `next` dropped"], "us-0")
    names_line = re.compile(r"^🔁 Ongoing: 6 -- \d+ · on-")
    assert any(names_line.match(ln) for ln in b["ongoing/outside as names"].splitlines())
    assert "⏳ Waiting on YOU / can continue now:\n- " in b["ongoing/outside as names"]
    assert re.search(r"^⏳ Waiting on YOU / can continue now: 6 -- \d+ · us-", b["every group as names"], re.M)
    assert re.search(r"^🔁 Ongoing: 6 -- \d+, \d+", b["ongoing/outside as numbers"], re.M)
    assert re.search(r"^⏳ Waiting on YOU / can continue now: 6 -- \d+ · ", b["ongoing/outside as numbers"], re.M)
    assert re.search(r"^⏳ Waiting on YOU / can continue now: 6 -- \d+, \d+", b["every group as numbers"], re.M)
    # Below the last step: the notices lose whole lines from the bottom; the reminder stays.
    assert any("⬆️ Baton was updated" in x for x in floor), "the step before the notices go"
    assert "⬆️ Baton was updated" not in floor[-1]
    assert all("the cert expires" in x for x in floor)


def test_details_prints_whole_what_the_board_shortens(tmp_path):
    """Nothing is lost: the lessons, the page and the tag legend the board may shorten come out
    whole from `--details`."""
    root = tmp_path / "tasks"
    f = _task(root, "billing", US + 'next: "x"\n')
    (f / "PLAN.md").write_text("---\nstate: open\n---\n", "utf-8")
    now = __import__("datetime").datetime.now()
    state: dict = {}
    for d in (3, 1):
        hook.lesson_event(state, "L1", "fired", now - timedelta(days=d))
        hook.lesson_event(state, "L1", "caught", now - timedelta(days=d))
    (tmp_path / "lessons.json").write_text(json.dumps(state), "utf-8")
    env = _env(tmp_path, root)
    env["BATON_PAGE"] = ""
    out = subprocess.run([sys.executable, str(HOOK)], input=b'{"source":"startup"}', env=env,
                         capture_output=True, timeout=60)
    ctx = json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
    from conftest import board_details
    full = board_details(ctx, env)
    tail = full.split("Shortened on the board when it must fit, here whole:", 1)[1]
    assert "L1 recurred 2 times" in tail and "do not propose the tool" in tail
    assert "📄 Baton page (ID" in tail and "--open" in tail
    assert "⚠ Tags on the task lines (tasks): ⚠plan (1)" in tail
