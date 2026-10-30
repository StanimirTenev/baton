"""ZA-OPRAVYANE row 27: does the Stop hook's hand-back do any work?

Nothing counted it. A turn handed back, then let through on the second try with
`stop_hook_active`, left no trace (the probe of 21.10, C-D: only `tops`, the bodies and the
heartbeat in the data folder). Three numbers answer it: entries the agent wrote unasked, turns
handed back, and of those how many were recorded on the second try or passed without it.

Through the hook's entry point, as the harness runs it; /baton-doctor as a subprocess.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STOP = ROOT / "hooks" / "baton_stop.py"
DOCTOR = ROOT / "tools" / "baton_doctor.py"


def _setup(tmp_path):
    tasks = tmp_path / "tasks"
    folder = tasks / "a"
    folder.mkdir(parents=True)
    book = folder / "LOGBOOK.md"
    then = datetime.now() - timedelta(hours=2)
    book.write_text(f"---\ndone_when: shipped\n---\n\n## {then:%Y-%m-%d %H:%M} — first\n\nbody\n",
                    "utf-8")
    old = time.time() - 7200
    os.utime(book, (old, old))
    notes = folder / "notes.txt"          # older work, recorded: the folder is looked at
    notes.write_text("n", "utf-8")
    os.utime(notes, (old - 600, old - 600))
    transcript = tmp_path / "t.jsonl"
    started = (datetime.now() - timedelta(hours=1)).astimezone().isoformat()
    transcript.write_text(json.dumps({"timestamp": started}) + "\n", "utf-8")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(BATON_HOME=str(tasks), BATON_LOGBOOK="LOGBOOK.md", HOME=str(tmp_path / "home"),
               BATON_STATE_DIR=str(tmp_path / "state"))
    return env, folder, book, str(transcript)


def _work(folder):
    f = folder / "work.txt"
    f.write_text(f"{time.time()}", "utf-8")
    ten = time.time() - 600
    os.utime(f, (ten, ten))


def _entry(book, title):
    text = book.read_text("utf-8")
    head, rest = text.split("\n\n", 1)          # the header, then the entries
    book.write_text(f"{head}\n\n## {datetime.now():%Y-%m-%d %H:%M} — {title}\n\n"
                    "### What was asked\nx\n### Done\nwork.txt\n### Result\ny\n\n" + rest, "utf-8")


def _stop(env, transcript, active=False, session="s"):
    payload = {"session_id": session, "transcript_path": transcript}
    if active:
        payload["stop_hook_active"] = True
    out = subprocess.run([sys.executable, str(STOP)], input=json.dumps(payload),
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def _counts(env):
    try:
        return json.loads(Path(env["BATON_LESSONS_STATE"]).read_text("utf-8")).get("handback", {})
    except FileNotFoundError:
        return {}


def test_a_hand_back_passed_on_the_second_try_is_counted(tmp_path):
    env, folder, book, tr = _setup(tmp_path)
    _work(folder)
    assert _stop(env, tr).get("decision") == "block"
    assert _counts(env).get("handed_back") == 1
    assert _stop(env, tr, active=True).get("decision") == "block", "no entry: handed back again"
    assert _stop(env, tr, active=True) == {}, "never a third time"
    c = _counts(env)
    assert c.get("passed") == 1 and c.get("recorded_after", 0) == 0, c
    assert c.get("handed_back") == 1, "one turn handed back, not two"


def test_the_second_hand_back_names_the_folder_and_is_the_last(tmp_path):
    """ZA-OPRAVYANE row 115 (Nitin Sharma, 30.10): "once per turn" was Baton's choice, not a
    limit of Claude Code, whose cap is 8 consecutive continuations, reset by a tool call. A
    turn that answered the hand-back with no entry is handed back once more; two is Baton's
    own cap, kept in its state, so a loop cannot come from here."""
    env, folder, book, tr = _setup(tmp_path)
    _work(folder)
    assert _stop(env, tr).get("decision") == "block"
    again = _stop(env, tr, active=True)
    assert again.get("decision") == "block" and "  - a" in again["reason"], again
    assert "last" in again["reason"], again
    assert _stop(env, tr, active=True) == {}
    assert _stop(env, tr, active=True) == {}, "the state was cleared, not left to block later"


def test_a_new_turn_can_be_handed_back_twice_again(tmp_path):
    env, folder, book, tr = _setup(tmp_path)
    _work(folder)
    _stop(env, tr)
    _stop(env, tr, active=True)
    _stop(env, tr, active=True)
    _entry(book, "recorded at last")
    assert "newer than" not in _stop(env, tr).get("reason", "")
    (folder / "more.txt").write_text("m", "utf-8")
    ten = time.time() - 600
    os.utime(folder / "more.txt", (ten + 300, ten + 300))
    os.utime(book, (ten, ten))
    assert "newer than" in _stop(env, tr).get("reason", "")
    assert _stop(env, tr, active=True).get("decision") == "block", "the cap is per turn"


def test_a_hand_back_recorded_on_the_second_try_is_counted(tmp_path):
    env, folder, book, tr = _setup(tmp_path)
    _work(folder)
    assert _stop(env, tr).get("decision") == "block"
    _entry(book, "written after the hand-back")
    # Not handed back again; since row 55 its one-line entry is said to the human as hollow.
    assert "decision" not in _stop(env, tr, active=True)
    c = _counts(env)
    assert c.get("recorded_after") == 1 and c.get("passed", 0) == 0, c
    _stop(env, tr)
    assert _counts(env).get("unasked", 0) == 0, "an entry written because Stop asked is not unasked"


def test_an_entry_written_unasked_is_counted(tmp_path):
    env, folder, book, tr = _setup(tmp_path)
    assert _stop(env, tr) == {}, "nothing to record yet: the first look only remembers"
    _work(folder)
    _entry(book, "written on its own")
    assert "newer than" not in _stop(env, tr).get("reason", "")
    c = _counts(env)
    assert c.get("unasked") == 1 and c.get("handed_back", 0) == 0, c
    _stop(env, tr)
    assert _counts(env).get("unasked") == 1, "the same entry is counted once"


def test_doctor_shows_the_three_numbers(tmp_path):
    env, folder, book, tr = _setup(tmp_path)
    _work(folder)
    _stop(env, tr)
    _stop(env, tr, active=True)
    _stop(env, tr, active=True)          # handed back twice since row 115; passed on the third
    out = subprocess.run([sys.executable, str(DOCTOR)], capture_output=True, text=True, env=env)
    assert "written unasked: 0" in out.stdout and "handed back: 1" in out.stdout, out.stdout
    assert "passed without one: 1" in out.stdout, out.stdout


def test_more_work_instead_of_an_entry_is_passed_not_recorded(tmp_path):
    """Leaving the folder out of `unrecorded` is not recording it: a file saved seconds ago is
    inside the grace period. Judged by the logbook, not by Stop's verdict."""
    env, folder, book, tr = _setup(tmp_path)
    _work(folder)
    assert _stop(env, tr).get("decision") == "block"
    (folder / "draft.txt").write_text("kept working", "utf-8")          # fresh, no entry
    assert _stop(env, tr, active=True).get("decision") == "block"      # row 115: once more
    _stop(env, tr, active=True)
    c = _counts(env)
    assert c.get("passed") == 1 and c.get("recorded_after", 0) == 0, c


def test_completing_the_newest_entry_after_a_hand_back_counts_as_recorded(tmp_path):
    env, folder, book, tr = _setup(tmp_path)
    _work(folder)
    assert _stop(env, tr).get("decision") == "block"
    book.write_text(book.read_text("utf-8").replace("body", "body\n\nwork.txt: done"), "utf-8")
    _stop(env, tr, active=True)
    assert _counts(env).get("recorded_after") == 1, _counts(env)


def test_an_interrupted_hand_back_is_not_handed_back_in_a_later_turn(tmp_path):
    """A turn the human interrupted after the first hand-back runs no second Stop, so its
    `blocked:` mark stayed. Recorded in the next turn, that folder must not be named when a
    later turn hands back another folder: this turn's hand-back is the only pending one."""
    env, folder, book, tr = _setup(tmp_path)
    other = folder.parent / "b"
    other.mkdir()
    (other / "LOGBOOK.md").write_text(book.read_text("utf-8"), "utf-8")
    old = time.time() - 7200
    os.utime(other / "LOGBOOK.md", (old, old))
    _work(folder)
    assert "  - a" in _stop(env, tr).get("reason", "")      # interrupted: no active Stop
    _entry(book, "recorded in the next turn")
    _stop(env, tr)
    _work(other)
    assert "  - b" in _stop(env, tr).get("reason", "")
    again = _stop(env, tr, active=True)
    assert "  - b" in again.get("reason", "") and "  - a" not in again.get("reason", ""), again
