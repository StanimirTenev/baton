"""ZA-OPRAVYANE row 141 (10.11): Stop re-asked every turn while a background agent of this
session kept writing into a task folder.

The agent for a release wrote into `shorlist-popravki/v0.3.0/mer/` every minute. Each turn Stop
handed the folder back twice; each time the answer was "no entry needed, already described" --
8+ times in an hour. Now a folder the session let through without an entry is not handed back
again in this session while its new files stay in the directories it was let through for. A
file anywhere else in it, or a new entry in its logbook, ends that. It is said to the human once,
and the next session's board still lists the folder: per session, never a silent pass.

Through the hook's entry point, as the harness runs it.
"""
from __future__ import annotations

import os
import time

from test_handback import _counts, _setup, _stop, _entry


def _file(folder, rel, ago=600):
    path = folder / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{time.time()}", "utf-8")
    os.utime(path, (time.time() - ago, time.time() - ago))
    return path


def _decline(env, tr):
    """A turn handed back twice and let through with no entry: the agent said none is needed."""
    assert _stop(env, tr).get("decision") == "block"
    assert _stop(env, tr, active=True).get("decision") == "block"
    assert _stop(env, tr, active=True).get("decision") != "block"


def test_a_folder_let_through_is_not_handed_back_again_for_the_same_directory(tmp_path):
    env, folder, book, tr = _setup(tmp_path)
    _file(folder, "mer/run-1.json", ago=900)
    _decline(env, tr)
    _file(folder, "mer/run-2.json", ago=300)              # the background agent, a minute on
    out = _stop(env, tr)
    assert out.get("decision") != "block", out
    said = out.get("systemMessage", "")
    assert "a" in said and "mer" in said and "board" in said, out
    _file(folder, "mer/run-3.json", ago=200)
    again = _stop(env, tr)
    assert again.get("decision") != "block" and "mer" not in again.get("systemMessage", ""), \
        "said once a session"
    assert _counts(env).get("handed_back") == 1, "one hand-back, not one a turn"


def test_it_holds_while_the_writer_is_still_writing_when_the_turn_is_let_through(tmp_path):
    """The case itself: a file a minute. At the pass that lets the turn through the newest file is
    seconds old -- inside Stop's grace period, so that pass does not see the folder's files. The
    directories are taken at the first hand-back, which did."""
    env, folder, book, tr = _setup(tmp_path)
    _file(folder, "mer/run-1.json", ago=900)
    assert _stop(env, tr).get("decision") == "block"
    assert _stop(env, tr, active=True).get("decision") == "block"
    (folder / "mer" / "run-2.json").write_text("fresh", "utf-8")        # written just now
    assert _stop(env, tr, active=True).get("decision") != "block"
    _file(folder, "mer/run-3.json", ago=300)
    os.utime(folder / "mer" / "run-2.json", (time.time() - 300,) * 2)
    out = _stop(env, tr)
    assert out.get("decision") != "block", out


def test_a_file_outside_those_directories_is_handed_back(tmp_path):
    env, folder, book, tr = _setup(tmp_path)
    _file(folder, "mer/run-1.json", ago=900)
    _decline(env, tr)
    _file(folder, "mer/run-2.json", ago=300)
    _file(folder, "plan.md", ago=300)                       # work of its own, elsewhere
    out = _stop(env, tr)
    assert out.get("decision") == "block" and "plan.md" in out.get("reason", ""), out


def test_an_entry_in_the_folder_ends_it(tmp_path):
    env, folder, book, tr = _setup(tmp_path)
    _file(folder, "mer/run-1.json", ago=900)
    _decline(env, tr)
    _entry(book, "described at last")
    _stop(env, tr)                                          # sees the new entry
    old = time.time() - 700
    os.utime(book, (old, old))
    _file(folder, "mer/run-2.json", ago=300)
    assert _stop(env, tr).get("decision") == "block"


def test_another_session_is_handed_back_as_before(tmp_path):
    env, folder, book, tr = _setup(tmp_path)
    _file(folder, "mer/run-1.json", ago=900)
    _decline(env, tr)
    _file(folder, "mer/run-2.json", ago=300)
    assert _stop(env, tr, session="other").get("decision") == "block"
