"""The Stop hook had no test file of its own. An external review of v2.14.0 said so,
and the defect it found is the kind that only an end-to-end test catches.

`unrecorded()` compared `work > logged + GRACE_SECONDS`, so a file saved thirty seconds
after the logbook was **never** reported — not a minute later, not a day later. And an
old file two minutes newer than its logbook kept stopping unrelated sessions forever.

The hook's own comment states the intent: "a file saved moments ago is still being
worked on". That is a grace against **now**, not against the logbook. The code had
drifted from its own sentence.
"""

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_stop.py"
spec = importlib.util.spec_from_file_location("bs", HOOK)
bs = importlib.util.module_from_spec(spec)
sys.modules["bs"] = bs
spec.loader.exec_module(bs)


def _task(root: Path, name: str, log_age: float, work_age: float, logbook="LOGBOOK.md"):
    """A folder whose logbook and work file are aged in seconds before now."""
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    now = time.time()
    log = folder / logbook
    log.write_text("---\nsastoyanie: aktivna\n---\n\n## 2026-01-01 00:00 — x\n\ny\n",
                   encoding="utf-8")
    os.utime(log, (now - log_age, now - log_age))
    work = folder / "draft.md"
    work.write_text("some work\n", encoding="utf-8")
    os.utime(work, (now - work_age, now - work_age))
    return folder


def test_work_saved_just_after_the_logbook_is_still_unrecorded(tmp_path):
    """🔴 The reproduction. Logbook an hour ago, file 30 s later — thirty minutes back.

    Under the old comparison this folder could never be reported, however long it sat.
    """
    _task(tmp_path, "alpha", log_age=3600, work_age=3570)
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == ["alpha (newest: draft.md)"]


def test_a_file_saved_moments_ago_is_left_alone(tmp_path):
    """The grace the comment actually describes: still being worked on, right now."""
    _task(tmp_path, "beta", log_age=3600, work_age=5)
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []


def test_a_logbook_newer_than_the_work_is_recorded(tmp_path):
    _task(tmp_path, "gama", log_age=10, work_age=3600)
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []


def test_a_folder_with_no_logbook_at_all_is_named_as_such(tmp_path):
    folder = tmp_path / "delta"
    folder.mkdir()
    work = folder / "draft.md"
    work.write_text("x\n", encoding="utf-8")
    os.utime(work, (time.time() - 600, time.time() - 600))
    out = bs.unrecorded(tmp_path, "LOGBOOK.md")
    assert out and "no LOGBOOK.md at all" in out[0]


def test_batonignore_silences_a_folder(tmp_path):
    folder = _task(tmp_path, "epsilon", log_age=3600, work_age=600)
    (folder / ".batonignore").write_text("draft.md\n", encoding="utf-8")
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []


def test_the_hook_blocks_through_its_real_entry_point(tmp_path, monkeypatch):
    """Through `main()` and its JSON, not the function — that is where it broke before."""
    _task(tmp_path, "zeta", log_age=3600, work_age=600)
    monkeypatch.setenv("BATON_HOME", str(tmp_path))
    monkeypatch.setenv("BATON_LOGBOOK", "LOGBOOK.md")
    out = subprocess.run([sys.executable, str(HOOK)], input="{}",
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout)
    assert payload.get("decision") == "block"
    assert "zeta" in payload.get("reason", "")


def test_the_reason_goes_out_as_utf8_not_escaped(tmp_path, monkeypatch):
    """v3.12.0: a Cyrillic folder name leaves as UTF-8 bytes, not \\uXXXX."""
    _task(tmp_path, "фактури", log_age=3600, work_age=600)
    monkeypatch.setenv("BATON_HOME", str(tmp_path))
    monkeypatch.setenv("BATON_LOGBOOK", "LOGBOOK.md")
    out = subprocess.run([sys.executable, str(HOOK)], input=b"{}", capture_output=True)
    assert out.returncode == 0, out.stderr
    assert "фактури".encode("utf-8") in out.stdout and b"\\u04" not in out.stdout
    assert "фактури" in json.loads(out.stdout.decode("utf-8"))["reason"]


# --- a task with no criterion of done -----------------------------------------
# 2026-09-28: a conversation that was "only thinking aloud" ended in a decision on
# priorities and was never recognised as a task. The mechanical half of that: a folder
# worked in now whose header does not say when it is finished. Asked once per session,
# never on legacy folders nobody touched.

def _headed(root: Path, name: str, header: str, age: float, logbook="LOGBOOK.md"):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / logbook
    log.write_text(header + "\n## 2026-09-28 20:00 — x\n\ny\n", encoding="utf-8")
    now = time.time()
    os.utime(log, (now - age, now - age))
    return folder


def test_a_touched_task_without_a_criterion_is_named(tmp_path):
    _headed(tmp_path, "strategy", "---\nsastoyanie: aktivna\n---\n", age=60)
    assert bs.undefined(tmp_path, "LOGBOOK.md") == ["strategy"]


def test_a_touched_task_with_no_header_at_all_is_named(tmp_path):
    _headed(tmp_path, "fresh", "# just notes", age=60)
    assert bs.undefined(tmp_path, "LOGBOOK.md") == ["fresh"]


def test_a_task_with_a_criterion_is_left_alone(tmp_path):
    _headed(tmp_path, "done-able", "---\nkriterii_zavarshvane: \"the page is live\"\n---\n", age=60)
    assert bs.undefined(tmp_path, "LOGBOOK.md") == []


def test_an_empty_criterion_is_no_criterion(tmp_path):
    _headed(tmp_path, "blank", "---\nkriterii_zavarshvane: \"\"\n---\n", age=60)
    assert bs.undefined(tmp_path, "LOGBOOK.md") == ["blank"]


def test_an_untouched_legacy_folder_is_left_alone(tmp_path):
    """Not this session's work: asking about it would nag on day one."""
    _headed(tmp_path, "old", "---\nsastoyanie: aktivna\n---\n", age=3 * 3600)
    assert bs.undefined(tmp_path, "LOGBOOK.md") == []


def _run(tmp_path, monkeypatch, payload):
    monkeypatch.setenv("BATON_HOME", str(tmp_path))
    monkeypatch.setenv("BATON_LOGBOOK", "LOGBOOK.md")
    monkeypatch.setenv("BATON_STATE_DIR", str(tmp_path / ".state"))
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def test_no_criterion_blocks_once_per_session_through_the_entry_point(tmp_path, monkeypatch):
    _headed(tmp_path, "strategy", "---\nsastoyanie: aktivna\n---\n", age=60)
    first = _run(tmp_path, monkeypatch, {"session_id": "s1"})
    assert first.get("decision") == "block"
    assert "strategy" in first["reason"] and "kriterii_zavarshvane" in first["reason"]
    assert _run(tmp_path, monkeypatch, {"session_id": "s1"}) == {}, "asked twice in one session"
    assert _run(tmp_path, monkeypatch, {"session_id": "s2"}).get("decision") == "block"


def test_both_findings_arrive_in_one_block(tmp_path, monkeypatch):
    _task(tmp_path, "zeta", log_age=3600, work_age=600)
    _headed(tmp_path, "strategy", "---\nsastoyanie: aktivna\n---\n", age=60)
    out = _run(tmp_path, monkeypatch, {"session_id": "s1"})
    assert "zeta" in out["reason"] and "strategy" in out["reason"]


def test_stop_hook_active_still_wins(tmp_path, monkeypatch):
    _headed(tmp_path, "strategy", "---\nsastoyanie: aktivna\n---\n", age=60)
    assert _run(tmp_path, monkeypatch, {"session_id": "s1", "stop_hook_active": True}) == {}


# --- a header edit is not a logbook entry ------------------------------------------
# 2026-09-28: aliases were added to every task header. Adding them rewrote DNEVNIK.md, its
# mtime moved past the unrecorded work, and the Stop hook called that work recorded -- in
# Baton's own folder, the evening the feature shipped. The test is the body below the
# header, remembered by hash: a header edit leaves it unchanged, a new entry does not.

def test_a_header_edit_does_not_hide_unrecorded_work(tmp_path, monkeypatch):
    monkeypatch.setenv("BATON_BODY_STATE", str(tmp_path / ".bodies.json"))
    folder = _task(tmp_path, "baton", log_age=7200, work_age=9000)
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []            # recorded, body remembered
    work = folder / "draft.md"
    os.utime(work, (time.time() - 600, time.time() - 600))          # work after the entry
    log = folder / "LOGBOOK.md"
    log.write_text(log.read_text(encoding="utf-8").replace(
        "sastoyanie: aktivna", "sastoyanie: aktivna\naliases: [x]"), encoding="utf-8")
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == ["baton (newest: draft.md)"]


def test_a_new_entry_does_record_the_work(tmp_path, monkeypatch):
    monkeypatch.setenv("BATON_BODY_STATE", str(tmp_path / ".bodies.json"))
    folder = _task(tmp_path, "baton", log_age=7200, work_age=9000)
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []
    os.utime(folder / "draft.md", (time.time() - 600, time.time() - 600))
    log = folder / "LOGBOOK.md"
    text = log.read_text(encoding="utf-8")
    log.write_text(text.replace("## 2026-01-01", "## 2026-09-28 20:05 — new\n\ndone\n\n## 2026-01-01"),
                   encoding="utf-8")
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []


def test_no_remembered_body_falls_back_to_the_file_time(tmp_path, monkeypatch):
    """First run on a machine: nothing remembered, so the old rule -- no false alarms."""
    monkeypatch.setenv("BATON_BODY_STATE", str(tmp_path / ".bodies.json"))
    _task(tmp_path, "gama", log_age=10, work_age=3600)
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []


# --- an entry dated in the future ----------------------------------------------------
# 2026-09-28, 20:04 by the clock: the top entries of six logbooks were headed 22:30,
# 23:40, and "2026-09-29 00:50". The agent typed the times instead of reading them. A
# record whose date is wrong by hours is wrong about the one thing a record is for.

def _heading(root: Path, name: str, heading: str):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "LOGBOOK.md").write_text(
        "---\nkriterii_zavarshvane: \"x\"\n---\n\n" + heading + "\n\nbody\n", encoding="utf-8")
    return folder


def test_an_entry_headed_later_than_the_clock_is_named(tmp_path):
    from datetime import datetime, timedelta
    later = (datetime.now() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
    _heading(tmp_path, "alpha", f"## {later} — typed, not read")
    out = bs.future_dated(tmp_path, "LOGBOOK.md")
    assert out and out[0].startswith("alpha") and later in out[0]


def test_an_entry_headed_now_or_earlier_is_fine(tmp_path):
    from datetime import datetime, timedelta
    _heading(tmp_path, "beta", f"## {datetime.now().strftime('%Y-%m-%d %H:%M')} — now")
    _heading(tmp_path, "gama", f"## {(datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')} — date only")
    assert bs.future_dated(tmp_path, "LOGBOOK.md") == []


def test_a_date_only_heading_for_tomorrow_is_named(tmp_path):
    from datetime import date, timedelta
    _heading(tmp_path, "delta", f"## {(date.today() + timedelta(days=1)).isoformat()} — tomorrow")
    assert bs.future_dated(tmp_path, "LOGBOOK.md")[0].startswith("delta")


# --- only this session's work stops the turn (external review of v3.10.0) ----------------
# An old unrecorded file in an unrelated task blocked every turn of a session that never
# touched it. Stop now asks only about work saved after the session began (the first
# timestamp of its transcript); the older debt is listed on the board.

def _transcript(path: Path, started: float) -> Path:
    from datetime import datetime, timezone
    stamp = datetime.fromtimestamp(started, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    path.write_text(json.dumps({"type": "mode", "sessionId": "x"}) + "\n"
                    + json.dumps({"type": "user", "timestamp": stamp}) + "\n", "utf-8")
    return path


def _stop(tmp_path, transcript=None):
    env = dict(os.environ, BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               BATON_STATE_DIR=str(tmp_path / "state"), BATON_BODY_STATE=str(tmp_path / "b.json"))
    data = {"session_id": "s"}
    if transcript:
        data["transcript_path"] = str(transcript)
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(data),
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def test_old_unrecorded_work_does_not_stop_a_session_that_never_touched_it(tmp_path):
    _task(tmp_path / "tasks", "old", log_age=3 * 86400, work_age=2 * 86400)
    t = _transcript(tmp_path / "t.jsonl", time.time() - 3600)
    assert _stop(tmp_path, t).get("decision") != "block"


def test_work_saved_in_this_session_still_stops_it(tmp_path):
    _task(tmp_path / "tasks", "now", log_age=7200, work_age=600)
    t = _transcript(tmp_path / "t.jsonl", time.time() - 3600)
    out = _stop(tmp_path, t)
    assert out.get("decision") == "block" and "now" in out.get("reason", "")


def test_without_a_transcript_stop_behaves_as_before(tmp_path):
    _task(tmp_path / "tasks", "old", log_age=3 * 86400, work_age=2 * 86400)
    assert _stop(tmp_path).get("decision") == "block"


def test_the_older_debt_is_on_the_board(tmp_path):
    _task(tmp_path / "tasks", "old", log_age=3 * 86400, work_age=2 * 86400)
    start = HOOK.with_name("baton_session_start.py")
    env = dict(os.environ, BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               BATON_STATE_DIR=str(tmp_path / "state"), BATON_BODY_STATE=str(tmp_path / "b.json"),
               HOME=str(tmp_path / "home"))
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    out = subprocess.run([sys.executable, str(start)], input="{}", capture_output=True,
                         text=True, env=env)
    assert out.returncode == 0, out.stderr
    assert "from before this session" in out.stdout and "old (newest: draft.md)" in out.stdout


# --- an older entry rewritten is not the work recorded ---------------------------------
# Arthur Barbosa, 08.10: a folder the agent writes in is not an audit trail. Said back to him
# that day: nothing stops an agent rewriting an older entry, and a rewrite would even count
# as the logbook being updated -- the body was hashed whole. Since v3.17.0 the entries are
# remembered one by one: a change confined to the top (a new entry, the newest one edited)
# records the work; a change below it does not, and Stop says so once.

def _two_entries(tmp_path, name="baton"):
    folder = _task(tmp_path, name, log_age=7200, work_age=9000)
    log = folder / "LOGBOOK.md"
    log.write_text(log.read_text(encoding="utf-8").replace(
        "## 2026-01-01", "## 2026-01-02 09:00 — newer\n\nkept\n\n## 2026-01-01"), encoding="utf-8")
    os.utime(log, (time.time() - 7200, time.time() - 7200))
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []              # entries remembered
    os.utime(folder / "draft.md", (time.time() - 600, time.time() - 600))
    return folder, log


def test_an_older_entry_rewritten_does_not_record_the_work(tmp_path, monkeypatch):
    monkeypatch.setenv("BATON_BODY_STATE", str(tmp_path / ".bodies.json"))
    folder, log = _two_entries(tmp_path)
    log.write_text(log.read_text(encoding="utf-8").replace("\ny\n", "\ny, and it all worked\n"),
                   encoding="utf-8")
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == ["baton (newest: draft.md)"]
    assert bs.REWRITTEN == ["baton"]


@pytest.mark.parametrize("change", [
    ("## 2026-01-02 09:00", "## 2026-10-20 10:00 — one\n\na\n\n## 2026-10-20 10:30 — two\n\nb\n\n"
                            "## 2026-01-02 09:00"),                  # two new entries at once
    ("\nkept\n", "\nkept, and the step that was missing\n"),          # the newest one completed
    ("## 2026-01-02 09:00 — newer", "## 2026-01-02 08:00 — newer"),   # its heading corrected (L1)
])
def test_a_change_at_the_top_records_the_work(tmp_path, monkeypatch, change):
    monkeypatch.setenv("BATON_BODY_STATE", str(tmp_path / ".bodies.json"))
    folder, log = _two_entries(tmp_path)
    log.write_text(log.read_text(encoding="utf-8").replace(*change), encoding="utf-8")
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []
    assert bs.REWRITTEN == []


def test_an_entry_added_at_the_end_is_not_a_rewrite(tmp_path, monkeypatch):
    """A logbook kept oldest-first: nothing older changed, one entry was added."""
    monkeypatch.setenv("BATON_BODY_STATE", str(tmp_path / ".bodies.json"))
    folder, log = _two_entries(tmp_path)
    log.write_text(log.read_text(encoding="utf-8") + "\n## 2026-10-20 10:00 — later\n\nz\n",
                   encoding="utf-8")
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []
    assert bs.REWRITTEN == []


def test_a_body_remembered_by_an_older_version_still_counts_a_change(tmp_path, monkeypatch):
    """baton.bodies.json from v3.16.0 holds [hash, time] without entries: no false alarm."""
    state = tmp_path / ".bodies.json"
    monkeypatch.setenv("BATON_BODY_STATE", str(state))
    folder, log = _two_entries(tmp_path)
    state.write_text(json.dumps({k: v[:2] for k, v in json.loads(state.read_text()).items()}))
    log.write_text(log.read_text(encoding="utf-8").replace("\ny\n", "\ny, rewritten\n"),
                   encoding="utf-8")
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []


def test_a_rewritten_older_entry_is_said_once_through_the_entry_point(tmp_path, monkeypatch):
    monkeypatch.setenv("BATON_BODY_STATE", str(tmp_path / ".bodies.json"))
    folder, log = _two_entries(tmp_path)
    log.write_text(log.read_text(encoding="utf-8").replace("\ny\n", "\ny, and it all worked\n"),
                   encoding="utf-8")
    os.utime(folder / "draft.md", (time.time() - 90000, time.time() - 90000))   # no new work
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_PLUGIN", "BATON_"))}
    env.update(BATON_HOME=str(tmp_path), BATON_LOGBOOK="LOGBOOK.md",
               BATON_BODY_STATE=str(tmp_path / ".bodies.json"),
               BATON_STATE_DIR=str(tmp_path / "state"), HOME=str(tmp_path / "home"),
               BATON_LESSONS_STATE=str(tmp_path / "lessons.json"))

    def stop():
        out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"session_id": "s"}),
                             capture_output=True, text=True, env=env)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout).get("reason", "") if out.stdout.strip() else ""

    reason = stop()
    assert "older entry" in reason and "baton" in reason, reason
    assert "older entry" not in stop(), "said once"


def test_a_folder_the_root_batonignore_names_is_never_asked_about(tmp_path):
    """ZA-OPRAVYANE row 31: a folder of photos in the task root is not a task. Declared in a
    `.batonignore` at the root, new work in it hands nothing back and it is not on the board."""
    import os
    import subprocess
    import sys
    import time
    root = tmp_path / "tasks"
    (root / "snimki").mkdir(parents=True)
    photo = root / "snimki" / "photo.jpg"
    photo.write_bytes(b"\xff\xd8")
    old = time.time() - 600
    os.utime(photo, (old, old))
    hooks = Path(__file__).resolve().parent.parent / "hooks"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_PLUGIN", "BATON_HOME"))}
    env.update(BATON_HOME=str(root), BATON_LOGBOOK="LOGBOOK.md", BATON_STATE_DIR=str(tmp_path / "st"))

    def run(hook, payload):
        out = subprocess.run([sys.executable, str(hooks / hook)], input=payload,
                             capture_output=True, text=True, env=env)
        assert out.returncode == 0, out.stderr
        return out.stdout

    assert "snimki" in run("baton_stop.py", "{}"), "without the declaration it is a task"
    assert "snimki" in run("baton_session_start.py", '{"source":"startup"}')
    (root / ".batonignore").write_text("snimki\n", "utf-8")
    assert "snimki" not in run("baton_stop.py", "{}")
    assert "snimki" not in run("baton_session_start.py", '{"source":"startup"}')


def test_every_unrecorded_file_is_named_up_to_a_few(tmp_path):
    """ZA-OPRAVYANE row 98 (Abuzar Zaidi, 27.10): the hand-back and the board named only the
    newest file of an unrecorded folder; a session cut short with six files told the agent of
    one. Up to five are named, newest first, and the rest are counted."""
    folder = _task(tmp_path / "tasks", "big", log_age=3 * 86400, work_age=2 * 86400)
    now = time.time()
    for i in range(6):
        f = folder / f"part{i}.py"
        f.write_text("x\n", encoding="utf-8")
        os.utime(f, (now - 7200 - i * 60, now - 7200 - i * 60))
    old = folder / "kept.txt"           # older than the logbook: recorded, not named
    old.write_text("k\n", encoding="utf-8")
    os.utime(old, (now - 4 * 86400, now - 4 * 86400))
    reason = _stop(tmp_path).get("reason", "")
    assert "big (newest: part0.py" in reason, reason
    for name in ("part1.py", "part2.py", "part3.py", "part4.py"):
        assert name in reason, reason
    assert "part5.py" not in reason and "2 more" in reason, reason
    assert "kept.txt" not in reason
