"""A logbook entry that exists is not an entry that says anything.

2026-10-20, under a LinkedIn post about hooks: "How do you handle an agent that writes a
low-effort logbook entry just to get past it?" The honest answer was: nothing does. The Stop
check compares file times, so `## 2026-10-01 10:00 — done` with one word under it passed
exactly like a full entry.

Two things a script can measure without judging the text: the entry has its sections, each
with something in it, and it names at least one of the files saved in the folder this session.
Neither proves the entry is right; both catch an entry written only to pass.
"""

import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_stop.py"
spec = importlib.util.spec_from_file_location("bs_hollow", HOOK)
bs = importlib.util.module_from_spec(spec)
sys.modules["bs_hollow"] = bs
spec.loader.exec_module(bs)

GOOD = """## 2026-10-01 10:00 — the report draft

### What was asked
A first draft of the quarterly report for the board, in the usual layout.

### Done
Wrote report-draft.md from last quarter's numbers; the revenue table is filled in.

### Result
The draft is complete except the outlook paragraph, which needs the forecast.

### Still open
The outlook paragraph, once the forecast arrives on Friday.
"""


def _folder(root: Path, name: str, entry: str, files=("report-draft.md",), age=30):
    """A task folder whose logbook and work files were saved `age` seconds ago."""
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    when = time.time() - age
    for rel in files:
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("work\n", encoding="utf-8")
        os.utime(path, (when, when))
    log = folder / "LOGBOOK.md"
    log.write_text("---\nstate: active\n---\n\n" + entry, encoding="utf-8")
    os.utime(log, (when + 5, when + 5))
    return folder


def _since():
    return time.time() - 600


def test_a_one_word_entry_is_hollow(tmp_path):
    """🔴 The reproduction: this passed the Stop check before."""
    _folder(tmp_path, "report", "## 2026-10-01 10:00 — done\n\nok\n")
    out = bs.hollow_entries(tmp_path, "LOGBOOK.md", _since())
    assert len(out) == 1
    folder, heading, reasons = out[0]
    assert folder == "report"
    assert any("section" in r for r in reasons)
    assert any("characters" in r for r in reasons)
    assert any("report-draft.md" in r for r in reasons)


def test_a_full_entry_that_names_the_work_passes(tmp_path):
    _folder(tmp_path, "report", GOOD)
    assert bs.hollow_entries(tmp_path, "LOGBOOK.md", _since()) == []


def test_sections_filled_but_the_work_not_named(tmp_path):
    """The entry is about something else: none of this session's files appear in it."""
    _folder(tmp_path, "report", GOOD.replace("report-draft.md", "the draft"))
    out = bs.hollow_entries(tmp_path, "LOGBOOK.md", _since())
    assert len(out) == 1
    assert out[0][2] == [r for r in out[0][2] if "names none" in r]


def test_naming_the_subfolder_counts(tmp_path):
    """`msg-1..4.png` names no single file, but the folder it lives in is named."""
    entry = GOOD.replace("report-draft.md", "the screenshots in 2026-10-19/")
    _folder(tmp_path, "report", entry, files=("2026-10-19/msg-3.png",))
    assert bs.hollow_entries(tmp_path, "LOGBOOK.md", _since()) == []


def test_an_empty_section_is_hollow(tmp_path):
    entry = GOOD.replace("The outlook paragraph, once the forecast arrives on Friday.\n", "")
    _folder(tmp_path, "report", entry)
    out = bs.hollow_entries(tmp_path, "LOGBOOK.md", _since())
    assert out and any("section" in r for r in out[0][2])


def test_a_decision_with_no_files_is_not_asked_to_name_any(tmp_path):
    """A conversation that became a decision touched no file but the logbook."""
    entry = GOOD.replace("report-draft.md", "nothing yet")
    _folder(tmp_path, "report", entry, files=())
    assert bs.hollow_entries(tmp_path, "LOGBOOK.md", _since()) == []


def test_a_logbook_from_before_the_session_is_left_alone(tmp_path):
    """Old entries are history; the check is about what this session wrote."""
    _folder(tmp_path, "report", "## 2026-01-01 10:00 — done\n\nok\n", age=3600)
    assert bs.hollow_entries(tmp_path, "LOGBOOK.md", _since()) == []


def test_an_unknown_session_start_checks_nothing(tmp_path):
    _folder(tmp_path, "report", "## 2026-10-01 10:00 — done\n\nok\n")
    assert bs.hollow_entries(tmp_path, "LOGBOOK.md", None) == []


def test_a_header_edit_does_not_put_an_old_entry_on_trial(tmp_path, monkeypatch):
    """The body is the same one seen before the session began: only the header changed."""
    folder = _folder(tmp_path, "report", "## 2026-01-01 10:00 — done\n\nok\n")
    body = bs._body((folder / "LOGBOOK.md").read_text("utf-8"))
    import hashlib
    state = tmp_path / "bodies.json"
    state.write_text(json.dumps({str(folder): [hashlib.sha1(body.encode()).hexdigest(),
                                               time.time() - 7200]}), "utf-8")
    monkeypatch.setenv("BATON_BODY_STATE", str(state))
    assert bs.hollow_entries(tmp_path, "LOGBOOK.md", _since()) == []


def _run(tmp_path, session):
    transcript = tmp_path / "t.jsonl"
    start = datetime.fromtimestamp(time.time() - 600, tz=timezone.utc).isoformat()
    transcript.write_text(json.dumps({"timestamp": start}) + "\n", "utf-8")
    env = dict(os.environ, BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               BATON_STATE_DIR=str(tmp_path / ".state"))
    out = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, env=env,
                         input=json.dumps({"session_id": session,
                                           "transcript_path": str(transcript)}))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def test_the_hook_hands_the_turn_back_once_per_entry(tmp_path):
    entry = ("---\ndone_when: \"x\"\n---\n\n"
             "## 2026-10-01 10:00 — done\n\nok\n")
    folder = _folder(tmp_path / "tasks", "report", "")
    (folder / "LOGBOOK.md").write_text(entry, "utf-8")
    first = _run(tmp_path, "s1")
    assert first.get("decision") == "block"
    assert "report" in first["reason"] and "hollow" in first["reason"]
    again = _run(tmp_path, "s1")
    assert "hollow" not in again.get("reason", ""), "asked twice about the same entry"


def test_files_named_in_an_earlier_entry_of_the_same_session_count(tmp_path):
    """🔴 Found by a dry run on real logbooks: three entries in one session, the files named
    in the first, the third flagged for not naming them again."""
    now = datetime.now()
    earlier = GOOD.replace("2026-10-01 10:00", f"{now:%Y-%m-%d} {now:%H:%M}")
    latest = (f"## {now:%Y-%m-%d} {now:%H:%M} — the price question\n\n"
              + GOOD.split("\n", 2)[2].replace("report-draft.md", "nothing new"))
    _folder(tmp_path, "report", latest + "\n" + earlier)
    assert bs.hollow_entries(tmp_path, "LOGBOOK.md", _since()) == []


def test_an_entry_from_before_the_session_does_not_name_files_for_this_one(tmp_path):
    old = GOOD                                     # headed 2026-10-01, long before the session
    now = datetime.now()
    latest = (f"## {now:%Y-%m-%d} {now:%H:%M} — the price question\n\n"
              + GOOD.split("\n", 2)[2].replace("report-draft.md", "nothing new"))
    _folder(tmp_path, "report", latest + "\n" + old)
    out = bs.hollow_entries(tmp_path, "LOGBOOK.md", _since())
    assert out and "names none" in out[0][2][0]


def _claimed(tmp_path, entry: str, age: float):
    """GOOD's entry headed now (lesson L1), report-draft.md saved `age` seconds ago."""
    now = datetime.now()
    folder = _folder(tmp_path, "report", entry.replace("2026-10-01 10:00", f"{now:%Y-%m-%d %H:%M}"))
    os.utime(folder / "report-draft.md", (time.time() - age, time.time() - age))
    return bs.hollow_entries(tmp_path, "LOGBOOK.md", _since())


def test_an_entry_says_it_changed_a_file_no_save_shows(tmp_path):
    """ZA-OPRAVYANE row 76 (Kyle Bartlett, 22.09): no file saved this session, so nothing was
    asked -- "Wrote report-draft.md" passed with report-draft.md two days old."""
    out = _claimed(tmp_path, GOOD, 2 * 86400)
    assert out and any("says it changed report-draft.md" in r for r in out[0][2]), out


def test_the_same_entry_with_the_file_saved_now_passes(tmp_path):
    assert _claimed(tmp_path, GOOD, 30) == []


def test_naming_an_old_file_without_changing_it_is_not_asked(tmp_path):
    entry = GOOD.replace("Wrote report-draft.md", "Read report-draft.md and agreed")
    assert _claimed(tmp_path, entry, 2 * 86400) == []


def _outside_entry(tmp_path, path: str):
    """A full entry headed now, saying it changed `path`, outside the task folder; the folder's
    own file two days old. Stop run as the harness runs it."""
    now = datetime.now()
    entry = GOOD.replace("2026-10-01 10:00", f"{now:%Y-%m-%d %H:%M}") \
                .replace("Wrote report-draft.md", f"Wrote {path}")
    folder = _folder(tmp_path / "tasks", "report", entry)
    os.utime(folder / "report-draft.md", (time.time() - 2 * 86400,) * 2)
    tr = tmp_path / "t.jsonl"
    started = datetime.fromtimestamp(time.time() - 3600, timezone.utc).isoformat()
    tr.write_text(json.dumps({"timestamp": started}) + "\n", "utf-8")
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "SYSTEMROOT", "LANG")}
    env.update(BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               BATON_STATE_DIR=str(tmp_path / "state"), BATON_BODY_STATE=str(tmp_path / "b.json"),
               BATON_LESSONS_STATE=str(tmp_path / "l.json"),
               BATON_SESSION_STATE=str(tmp_path / "s.json"))
    out = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, env=env,
                         input=json.dumps({"session_id": "s", "transcript_path": str(tr)}))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout).get("reason", "") if out.stdout.strip() else ""


def test_an_entry_naming_an_outside_path_that_is_not_there_is_asked(tmp_path):
    """ZA-OPRAVYANE row 95 (Trofymenko, 25.10): an entry naming an absolute path outside the task
    root passed with nothing checked -- and the hand-back itself says "name where" when the change
    is somewhere else. A path it says it changed must be there and saved this session."""
    missing = str(tmp_path / "elsewhere" / "clean.py")
    reason = _outside_entry(tmp_path, missing)
    assert "clean.py" in reason and "not there" in reason, reason


def test_an_entry_naming_an_outside_file_saved_now_passes(tmp_path):
    real = tmp_path / "elsewhere" / "clean.py"
    real.parent.mkdir(parents=True)
    real.write_text("x\n", "utf-8")
    assert "clean.py" not in _outside_entry(tmp_path, str(real))
