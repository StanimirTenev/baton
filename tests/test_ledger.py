"""The ledger: a record of each logbook entry that only grows (ZA-OPRAVYANE row 153).

Musab Khiri, 16.11: an agent can edit an older logbook entry and nothing records it. Stop's
memory of the bodies (v3.17.0) says so once, in that session, from a file the agent can delete.
A logbook is written newest entry on top, so it cannot itself be append-only. Beside it, Baton
now keeps a ledger in a git repository of its own: one line per entry -- folder, heading, the
sha256 of the entry's text and of the line before. Stop appends; `tools/baton_ledger.py verify`
and SessionStart compare it with the logbooks as they are; an edit the human accepts is a new
line (`ack`), never an edited one.

Run the way the harness runs the hooks: a subprocess, the hook's JSON on stdin.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import child_env

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
TOOL = ROOT / "tools" / "baton_ledger.py"
GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git is not installed")


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, HOOKS / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


core = _load("_baton_ledger", "_baton.py")

OLD = "## 2026-10-20 09:00 — first\n\nparser reads 3 formats\n"
NEW = "## 2026-10-21 09:00 — second\n\nremoved monitor.py\n"
BOOK = "---\nstate: active\ndone_when: x\n---\n\n" + NEW + "\n" + OLD


class World:
    """A task root, a ledger, a state folder, a home: all under tmp_path."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.root = tmp_path / "tasks"
        self.ledger = tmp_path / "ledger"
        self.home = tmp_path / "home"
        (self.home / ".claude").mkdir(parents=True, exist_ok=True)
        self.root.mkdir(exist_ok=True)

    def env(self, **extra):
        base = dict(HOME=str(self.home), BATON_HOME=str(self.root), BATON_LOGBOOK="LOGBOOK.md",
                    BATON_LEDGER=str(self.ledger), BATON_STATE_DIR=str(self.tmp / "sessions"),
                    CLAUDE_CONFIG_DIR=str(self.home / ".claude"),
                    CLAUDE_PLUGIN_DATA=str(self.tmp / "data"))
        base.update(extra)
        return child_env(**base)

    def task(self, name="alpha", text=BOOK):
        folder = self.root / name
        folder.mkdir(parents=True, exist_ok=True)
        log = folder / "LOGBOOK.md"
        log.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
        old = time.time() - 7200          # no work newer than the logbook: Stop says nothing
        os.utime(log, (old, old))
        return log

    def stop(self, payload=None, **extra):
        out = subprocess.run([sys.executable, str(HOOKS / "baton_stop.py")],
                             input=json.dumps(payload if payload is not None else
                                              {"session_id": "s1"}).encode("utf-8"),
                             capture_output=True, env=self.env(**extra), timeout=60)
        assert out.returncode == 0, out.stderr
        return out

    def start(self, **extra):
        out = subprocess.run([sys.executable, str(HOOKS / "baton_session_start.py")],
                             input=b'{"source":"startup"}', capture_output=True,
                             env=self.env(**extra), timeout=60)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout or b"{}").get("hookSpecificOutput", {}).get(
            "additionalContext", "")

    def tool(self, *args, **extra):
        return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True,
                              text=True, env=self.env(**extra), timeout=60)

    def lines(self):
        f = self.ledger / "ledger.jsonl"
        return f.read_bytes().splitlines() if f.is_file() else []

    def records(self):
        return [json.loads(line) for line in self.lines()]

    def commits(self):
        out = subprocess.run([GIT, "-C", str(self.ledger), "rev-list", "--count", "HEAD"],
                             capture_output=True, text=True)
        return int(out.stdout.strip() or 0)


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- what an entry is ---------------------------------------------------------------------

def test_an_entry_is_its_heading_and_body_without_the_header():
    got = core.ledger_entries(BOOK.encode("utf-8"))
    assert [(h, n) for h, n, _ in got] == [("## 2026-10-20 09:00 — first", 0),
                                          ("## 2026-10-21 09:00 — second", 0)], "oldest first"
    assert got[0][2] == _sha(OLD.rstrip())
    assert got[1][2] == _sha(NEW.rstrip())


def test_line_endings_a_bom_and_trailing_blank_lines_do_not_change_the_hash():
    plain = core.ledger_entries(BOOK.encode("utf-8"))
    crlf = core.ledger_entries(b"\xef\xbb\xbf" + BOOK.replace("\n", "\r\n").encode("utf-8") + b"\r\n\r\n")
    assert plain == crlf


def test_a_repeated_heading_is_counted_from_the_bottom():
    """Date-only headings repeat. Counted from the oldest, a new one on top changes no number."""
    two = "## 22.10.2026\n\nb\n\n## 22.10.2026\n\na\n"
    got = core.ledger_entries(two.encode("utf-8"))
    assert [(h, n) for h, n, _ in got] == [("## 22.10.2026", 0), ("## 22.10.2026", 1)]
    three = core.ledger_entries(("## 22.10.2026\n\nc\n\n" + two).encode("utf-8"))
    assert three[:2] == got


def test_no_entries_and_bytes_that_are_not_utf8_do_not_raise():
    assert core.ledger_entries(b"") == []
    assert core.ledger_entries(b"---\nstate: x\n---\n\nno entries yet\n") == []
    got = core.ledger_entries(b"## 2026-10-20 09:00 \xff\xfe broken\n\nbody \xc3\x28\n")
    assert len(got) == 1 and got[0][0].startswith("## 2026-10-20 09:00")


def test_the_heading_is_the_one_stop_reads():
    stop = _load("bs_ledger", "baton_stop.py")
    assert core.ENTRY_HEADING.pattern == stop._HEADING.pattern


# --- Stop records -------------------------------------------------------------------------

@needs_git
def test_stop_records_every_entry_once_silently_and_commits(w):
    w.task()
    out = w.stop()
    assert out.stdout == b"", "the ledger says nothing"
    recs = w.records()
    assert [(r["folder"], r["heading"]) for r in recs] == [
        ("alpha", "## 2026-10-20 09:00 — first"), ("alpha", "## 2026-10-21 09:00 — second")]
    assert recs[0]["sha256"] == _sha(OLD.rstrip())
    assert w.commits() == 1
    w.stop()
    assert len(w.records()) == 2 and w.commits() == 1, "nothing new: no line, no commit"


@needs_git
def test_the_chain_links_each_line_to_the_one_before(w):
    w.task()
    w.stop()
    raw = w.lines()
    assert json.loads(raw[0])["prev"] == "0" * 64
    assert json.loads(raw[1])["prev"] == hashlib.sha256(raw[0]).hexdigest()


@needs_git
def test_a_new_entry_on_top_is_appended_and_nothing_old_is_rewritten(w):
    log = w.task()
    w.stop()
    before = (w.ledger / "ledger.jsonl").read_bytes()
    log.write_text(BOOK.replace(NEW, "## 2026-10-22 09:00 — third\n\nshipped\n\n" + NEW), "utf-8")
    w.stop()
    after = (w.ledger / "ledger.jsonl").read_bytes()
    assert after.startswith(before)
    assert w.records()[-1]["heading"] == "## 2026-10-22 09:00 — third"
    assert w.commits() == 2


@needs_git
def test_an_edited_entry_is_never_recorded_again_by_stop(w):
    """The silent fix this must not be: Stop taking the edited text as the record."""
    log = w.task()
    w.stop()
    log.write_text(BOOK.replace("parser reads 3 formats", "parser reads 4 formats"), "utf-8")
    w.stop()
    assert len(w.records()) == 2
    assert w.records()[0]["sha256"] == _sha(OLD.rstrip())


@needs_git
def test_the_pass_after_a_hand_back_records_too(w):
    """The entry a hand-back asked for is written between the two Stops of one turn."""
    w.task()
    w.stop({"session_id": "s1", "stop_hook_active": True})
    assert len(w.records()) == 2


@needs_git
@pytest.mark.skipif(os.name == "nt", reason="a shell script stands in for git")
def test_with_nothing_new_stop_starts_no_git_process(w, tmp_path):
    w.task()
    w.stop()
    bin_dir, log = tmp_path / "bin", tmp_path / "git.log"
    bin_dir.mkdir()
    fake = bin_dir / "git"
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexec "{GIT}" "$@"\n', "utf-8")
    fake.chmod(0o755)
    path = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    w.stop(PATH=path)
    assert not log.exists(), log.read_text("utf-8")
    w.task(text=BOOK.replace(NEW, "## 2026-10-22 09:00 — third\n\nx\n\n" + NEW))
    w.stop(PATH=path)
    assert log.exists(), "the fake git is on the path: a new entry is committed through it"


def test_without_git_the_lines_are_still_written(w, tmp_path):
    w.task()
    empty = tmp_path / "nogit"
    empty.mkdir()
    out = w.stop(PATH=str(empty))
    assert out.stdout == b""
    assert len(w.records()) == 2


@needs_git
def test_a_logbook_that_is_not_utf8_is_recorded(w):
    """Recorded before Stop's other checks run. (Stop's `future_dated` still raises
    UnicodeDecodeError on such a logbook, as it did before the ledger: a crash marker, exit 0.)"""
    w.task(text=b"## 2026-10-20 09:00 \xff broken\n\nbody \xc3\x28\n")
    w.stop()
    assert len(w.records()) == 1
    assert w.tool("verify").returncode == 0


@needs_git
def test_a_folder_with_no_entries_and_a_root_with_no_folders_are_fine(w):
    w.stop()
    assert w.records() == []
    w.task(text="---\nstate: active\n---\n\nnothing yet\n")
    w.stop()
    assert w.records() == []


@needs_git
def test_two_stops_at_once_keep_one_chain(w):
    """Two sessions end their turns together: one lock, one chain, no entry twice."""
    for i in range(6):
        w.task(f"t{i}")
    procs = [subprocess.Popen([sys.executable, str(HOOKS / "baton_stop.py")],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=w.env())
             for _ in range(4)]
    for p in procs:
        p.communicate(json.dumps({"session_id": "s"}).encode("utf-8"), timeout=60)
        assert p.returncode == 0
    recs = w.records()
    keys = [(r["folder"], r["heading"], r["n"]) for r in recs]
    assert len(keys) == len(set(keys)) == 12
    assert w.tool("verify").returncode == 0


@needs_git
def test_a_held_lock_makes_stop_wait_and_write_nothing_rather_than_break_the_chain(w):
    w.task()
    lock = w.ledger.with_name(w.ledger.name + ".lock")
    lock.write_text("", "utf-8")              # another Stop, writing now
    w.stop()
    assert w.records() == [], "the next Stop records it"
    old = time.time() - 60                    # a Stop that died holding it
    os.utime(lock, (old, old))
    w.stop()
    assert len(w.records()) == 2 and not lock.exists()


# --- verify finds what changed --------------------------------------------------------------

@needs_git
def test_verify_is_clean_after_stop(w):
    w.task()
    w.stop()
    out = w.tool("verify")
    assert out.returncode == 0, out.stdout + out.stderr
    assert str(w.ledger) in out.stdout
    assert "2 entries" in out.stdout


@needs_git
def test_an_older_entry_edited_is_named_by_verify_and_session_start(w):
    log = w.task()
    w.stop()
    log.write_text(BOOK.replace("parser reads 3 formats", "parser reads 4 formats"), "utf-8")
    out = w.tool("verify")
    assert out.returncode == 1
    assert "changed" in out.stdout and "alpha" in out.stdout and "2026-10-20 09:00 — first" in out.stdout
    assert "second" not in out.stdout
    ctx = w.start()
    assert "ledger" in ctx and "alpha" in ctx and "2026-10-20 09:00 — first" in ctx
    assert "ack" in ctx


@needs_git
def test_a_recorded_entry_that_is_gone_is_named(w):
    log = w.task()
    w.stop()
    log.write_text(BOOK.replace(OLD, ""), "utf-8")
    out = w.tool("verify")
    assert out.returncode == 1 and "gone" in out.stdout and "first" in out.stdout
    assert "gone" in w.start()


@needs_git
def test_a_deleted_folder_is_named_as_gone(w):
    log = w.task()
    w.stop()
    shutil.rmtree(log.parent)
    out = w.tool("verify")
    assert out.returncode == 1 and "gone" in out.stdout and "alpha" in out.stdout


@needs_git
def test_a_ledger_line_edited_breaks_the_chain(w):
    w.task()
    w.task("beta")
    w.stop()
    f = w.ledger / "ledger.jsonl"
    raw = f.read_bytes().splitlines()
    rec = json.loads(raw[1])
    rec["sha256"] = "1" * 64
    raw[1] = json.dumps(rec, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    f.write_bytes(b"\n".join(raw) + b"\n")
    out = w.tool("verify")
    assert out.returncode == 1 and "chain" in out.stdout and "line 3" in out.stdout
    assert "chain" in w.start()


@needs_git
def test_a_ledger_rewritten_whole_is_still_caught_by_the_uncommitted_change(w):
    """An agent that rewrites a line and recomputes every later prev keeps the chain whole; the
    commit Baton made does not match. Committed by the agent too, only a remote can tell."""
    log = w.task()
    w.stop()
    log.write_text(BOOK.replace("parser reads 3 formats", "parser reads 4 formats"), "utf-8")
    raw, prev, out_lines = w.lines(), "0" * 64, []
    new = {e[0]: e[2] for e in core.ledger_entries(log.read_bytes())}
    for line in raw:
        rec = json.loads(line)
        rec["sha256"], rec["prev"] = new[rec["heading"]], prev
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        prev = hashlib.sha256(line).hexdigest()
        out_lines.append(line)
    (w.ledger / "ledger.jsonl").write_bytes(b"\n".join(out_lines) + b"\n")
    out = w.tool("verify")
    assert out.returncode == 1 and "not committed" in out.stdout


@needs_git
def test_a_change_not_committed_is_not_buried_by_the_next_commit_of_stop(w):
    log = w.task()
    w.stop()
    f = w.ledger / "ledger.jsonl"
    f.write_bytes(f.read_bytes().replace(b'"n":0', b'"n": 0', 1))
    log.write_text(BOOK.replace(NEW, "## 2026-10-22 09:00 — third\n\nx\n\n" + NEW), "utf-8")
    w.stop()
    assert w.records()[-1]["heading"] == "## 2026-10-22 09:00 — third", "still recorded"
    out = w.tool("verify")
    assert out.returncode == 1 and "not committed" in out.stdout


@needs_git
def test_a_deleted_ledger_is_said_and_not_quietly_rebuilt_clean(w):
    log = w.task()
    w.stop()
    log.write_text(BOOK.replace("parser reads 3 formats", "parser reads 4 formats"), "utf-8")
    shutil.rmtree(w.ledger)
    assert "ledger" in w.start()
    w.stop()                                  # recreated, from the logbooks as they are now
    assert len(w.records()) == 2
    out = w.tool("verify")
    assert out.returncode == 1 and "fewer lines" in out.stdout
    assert "fewer lines" in w.start()


def test_no_ledger_ever_means_session_start_says_nothing_of_it(w):
    w.task()
    assert "Baton's ledger" not in w.start()


@needs_git
def test_session_start_says_nothing_when_all_is_as_recorded(w):
    w.task()
    w.stop()
    assert "Baton's ledger" not in w.start()


@needs_git
def test_session_start_never_writes_the_ledger(w):
    log = w.task()
    w.stop()
    before = (w.ledger / "ledger.jsonl").read_bytes()
    log.write_text(BOOK.replace(NEW, "## 2026-10-22 09:00 — third\n\nx\n\n" + NEW), "utf-8")
    w.start()
    assert (w.ledger / "ledger.jsonl").read_bytes() == before


# --- ack ----------------------------------------------------------------------------------

@needs_git
def test_ack_records_the_new_text_with_a_reason_and_edits_no_line(w):
    log = w.task()
    w.stop()
    before = (w.ledger / "ledger.jsonl").read_bytes()
    log.write_text(BOOK.replace("parser reads 3 formats", "parser reads 4 formats"), "utf-8")
    assert w.tool("ack").returncode != 0, "no reason, no ack"
    out = w.tool("ack", "--reason", "the count was wrong")
    assert out.returncode == 0, out.stdout + out.stderr
    after = (w.ledger / "ledger.jsonl").read_bytes()
    assert after.startswith(before)
    last = w.records()[-1]
    assert last["kind"] == "ack" and last["reason"] == "the count was wrong"
    assert last["sha256"] == _sha(OLD.replace("3 formats", "4 formats").rstrip())
    assert w.tool("verify").returncode == 0
    assert "Baton's ledger" not in w.start()
    w.stop()
    assert w.records()[-1] == last, "Stop does not record an acknowledged entry again"


@needs_git
def test_ack_takes_a_gone_entry_and_a_folder_filter(w):
    a, b = w.task("alpha"), w.task("beta")
    w.stop()
    a.write_text(BOOK.replace(OLD, ""), "utf-8")
    b.write_text(BOOK.replace(OLD, ""), "utf-8")
    assert w.tool("ack", "--folder", "alpha", "--reason", "merged").returncode == 0
    out = w.tool("verify")
    assert out.returncode == 1 and "beta" in out.stdout and "alpha" not in out.stdout
    assert w.tool("ack", "--reason", "merged").returncode == 0
    assert w.tool("verify").returncode == 0


@needs_git
def test_a_heading_corrected_is_gone_plus_new_and_one_ack_settles_it(w):
    """Stop's L1 asks for a typed hour to be corrected: the old heading goes, a new one comes."""
    log = w.task()
    w.stop()
    log.write_text(BOOK.replace("2026-10-21 09:00 — second", "2026-10-21 09:40 — second"), "utf-8")
    w.stop()
    out = w.tool("verify")
    assert out.returncode == 1 and "09:00 — second" in out.stdout
    assert w.tool("ack", "--heading", "## 2026-10-21 09:00 — second", "--reason", "hour").returncode == 0
    assert w.tool("verify").returncode == 0


@needs_git
def test_ack_settles_a_deleted_ledger(w):
    w.task()
    w.stop()
    shutil.rmtree(w.ledger)
    w.stop()
    assert w.tool("ack", "--reason", "I deleted it myself").returncode == 0
    assert w.tool("verify").returncode == 0


@needs_git
def test_ack_settles_a_broken_line_without_touching_it(w):
    w.task()
    w.stop()
    f = w.ledger / "ledger.jsonl"
    raw = f.read_bytes().splitlines()
    raw[0] = raw[0].replace(b'"n":0', b'"n":0 ')
    f.write_bytes(b"\n".join(raw) + b"\n")
    subprocess.run([GIT, "-C", str(w.ledger), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-qam", "edit"], check=True)
    assert w.tool("verify").returncode == 1
    edited = f.read_bytes()
    assert w.tool("ack", "--reason", "seen").returncode == 0
    assert f.read_bytes().startswith(edited)
    assert w.tool("verify").returncode == 0


# --- where the ledger is, and the remote -----------------------------------------------------

@needs_git
def test_the_tool_finds_the_ledger_the_plugin_hook_wrote(w, tmp_path):
    """No BATON_LEDGER: the hook puts it in ${CLAUDE_PLUGIN_DATA}; the tool, given the same
    folder as the skills give it, reads the same file."""
    w.task()
    data = tmp_path / "data"
    env = dict(CLAUDE_PLUGIN_DATA=str(data), BATON_LEDGER="")
    w.stop(**env)
    assert (data / "baton.ledger" / "ledger.jsonl").is_file()
    out = w.tool("verify", **env)
    assert out.returncode == 0 and str(data / "baton.ledger") in out.stdout


@needs_git
def test_the_ledger_setting_in_baton_local_json_moves_it(w, tmp_path):
    w.task()
    data, where = tmp_path / "data", tmp_path / "elsewhere"
    data.mkdir()
    (data / "baton.local.json").write_text(json.dumps({"ledger": str(where)}), "utf-8")
    w.stop(CLAUDE_PLUGIN_DATA=str(data), BATON_LEDGER="")
    assert (where / "ledger.jsonl").is_file()
    out = w.tool("verify", CLAUDE_PLUGIN_DATA=str(data), BATON_LEDGER="")
    assert out.returncode == 0 and str(where) in out.stdout


@needs_git
def test_baton_adds_no_remote_and_push_needs_one(w):
    w.task()
    w.stop()
    remotes = subprocess.run([GIT, "-C", str(w.ledger), "remote"], capture_output=True, text=True)
    assert remotes.stdout.strip() == ""
    out = w.tool("push")
    assert out.returncode == 1 and "no remote" in out.stdout


@needs_git
def test_push_sends_to_the_remote_the_human_added_and_verify_remote_catches_a_rewrite(w, tmp_path):
    w.task()
    w.stop()
    bare = tmp_path / "anchor.git"
    subprocess.run([GIT, "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run([GIT, "-C", str(w.ledger), "remote", "add", "anchor", str(bare)], check=True)
    out = w.tool("push")
    assert out.returncode == 0, out.stdout + out.stderr
    assert w.tool("verify", "--remote").returncode == 0
    # The history rewritten here, the file left as it was: every local check passes, so only the
    # remote can tell.
    subprocess.run([GIT, "-C", str(w.ledger), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "--amend", "-m", "rewritten"], check=True)
    assert w.tool("verify").returncode == 0
    out = w.tool("verify", "--remote")
    assert out.returncode == 1 and "holds history that this ledger no longer has" in out.stdout
    out = w.tool("push")
    assert out.returncode == 1, "never forced"
    log = subprocess.run([GIT, "--git-dir", str(bare), "log", "--format=%s"],
                         capture_output=True, text=True).stdout
    assert "rewritten" not in log
