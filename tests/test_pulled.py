"""baton-firmi Р5 (02.11): files a sync brought in are not this session's work.

A task handed over from another machine arrives by `git pull`, and every file in it gets the
time of the checkout. git writes DNEVNIK.md / LOGBOOK.md first (capitals sort first), the work
files a millisecond later, so Stop called the task unrecorded; and with that answered, it called
the other machine's entry hollow for not naming files "saved here this session". Measured with the
real hook on two clones: 3 of 5 scenarios right, both misses at a handover
(~/zadachi/baton-firmi/proba/stop_sled_pull.py).

The sync writes `.baton-pulled` in each folder it changed: {path: st_mtime_ns} of what it checked
out. A file whose time still matches is skipped; one changed here no longer matches and counts
again. A `.baton-pulled` saved this session that hides files is said to the human, once, the way a
`.batonignore` is (row 57) -- it is also a way past the check.
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
GOOD = ("### What was asked\nCarry on with the migration script on this machine from now on.\n\n"
        "### Done\nHanded over from the other machine with the script and its data.\n\n"
        "### Result\nThe script runs on the sample data; the output matches the reference.\n\n"
        "### Still open\nThe full data set, once the export arrives from the client.\n")


def _age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


def _arrived(tmp_path, pulled_age=300):
    """A task that came in by a pull 5 minutes ago, inside a session that began 30 minutes ago."""
    folder = tmp_path / "tasks" / "migration"
    folder.mkdir(parents=True)
    book = folder / "LOGBOOK.md"
    book.write_text("---\nstate: active\ndone_when: data migrated\n---\n\n"
                    f"## {datetime.now() - timedelta(minutes=6):%Y-%m-%d %H:%M} — handed over\n\n"
                    + GOOD, "utf-8")
    _age(book, 301)                       # the logbook is checked out first
    files = {}
    for name in ("script.py", "data.csv"):
        (folder / name).write_text("x", "utf-8")
        _age(folder / name, 300)
        files[name] = (folder / name).stat().st_mtime_ns
    (folder / ".baton-pulled").write_text(json.dumps(files), "utf-8")
    _age(folder / ".baton-pulled", pulled_age)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({"type": "user", "timestamp": (
        datetime.now() - timedelta(minutes=30)).astimezone().isoformat()}) + "\n", "utf-8")
    return folder, str(transcript)


def _stop(tmp_path, transcript):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_HOME", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               HOME=str(tmp_path / "home"), BATON_STATE_DIR=str(tmp_path / "state"),
               BATON_BODY_STATE=str(tmp_path / "bodies.json"))
    out = subprocess.run([sys.executable, str(ROOT / "hooks" / "baton_stop.py")],
                         capture_output=True, text=True, env=env,
                         input=json.dumps({"session_id": "s", "transcript_path": transcript}))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def test_a_task_that_arrived_by_a_pull_is_not_handed_back(tmp_path):
    folder, tr = _arrived(tmp_path)
    out = _stop(tmp_path, tr)
    assert out.get("decision") != "block", out


def test_the_human_is_told_once_what_was_not_counted(tmp_path):
    folder, tr = _arrived(tmp_path)
    said = _stop(tmp_path, tr).get("systemMessage", "")
    assert ".baton-pulled" in said and "migration" in said and "script.py" in said, said
    assert ".baton-pulled" not in json.dumps(_stop(tmp_path, tr)), "once a session"


def test_a_pulled_file_changed_here_counts_again(tmp_path):
    folder, tr = _arrived(tmp_path)
    (folder / "script.py").write_text("changed here", "utf-8")
    _age(folder / "script.py", 200)
    out = _stop(tmp_path, tr)
    assert out.get("decision") == "block" and "script.py" in out.get("reason", ""), out


def test_without_the_file_the_handover_is_still_handed_back(tmp_path):
    """The control: what this release changes is the file, nothing else."""
    folder, tr = _arrived(tmp_path)
    (folder / ".baton-pulled").unlink()
    out = _stop(tmp_path, tr)
    assert out.get("decision") == "block", out


def test_a_pulled_record_from_before_the_session_is_obeyed_quietly(tmp_path):
    folder, tr = _arrived(tmp_path, pulled_age=7200)
    out = _stop(tmp_path, tr)
    assert out.get("decision") != "block" and ".baton-pulled" not in json.dumps(out), out


def test_a_broken_pulled_file_changes_nothing(tmp_path):
    folder, tr = _arrived(tmp_path)
    (folder / ".baton-pulled").write_text("{not json", "utf-8")
    _age(folder / ".baton-pulled", 300)
    out = _stop(tmp_path, tr)
    assert out.get("decision") == "block", out
