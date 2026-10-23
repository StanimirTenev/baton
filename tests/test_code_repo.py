"""ZA-OPRAVYANE row 73 (Rim Elouragini, 23.10: "the file is a claim, the repo is the evidence").

A logbook entry "parser fixed and committed", the repository outside the task folder with no
commit and an uncommitted change newer than the entry: Stop exited clean; the same file copied
into the task folder was handed back. The header's `code:` field names the repository; for a
logbook written this session, what it holds newer than the logbook is said to the human, once.
Headings from the clock (lesson L1).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_stop.py"
BODY = """
### What was asked
The date parser drops the time zone; fix it in the service repository.

### Done
Fixed parse_date() in parser.py so the offset is kept; committed it.

### Result
The parser is fixed and committed; the export keeps time zones now.

### Open
Nothing on the parser; the export runs again on Monday morning.
"""


def _git(repo: Path, *args, at: float | None = None):
    env = dict(os.environ)
    if at is not None:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = f"@{int(at)} +0000"
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


def _setup(tmp_path, commit_first: bool):
    repo = tmp_path / "service"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    old = time.time() - 300
    if commit_first:
        (repo / "parser.py").write_text("def parse_date(s):\n    return s\n", "utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "parser", at=old)
        os.utime(repo / "parser.py", (old, old))
    folder = tmp_path / "tasks" / "export"
    folder.mkdir(parents=True)
    book = folder / "LOGBOOK.md"
    book.write_text(f"---\nstate: active\ndone_when: \"x\"\ncode: {repo}@HEAD\n---\n\n"
                    f"## {datetime.now():%Y-%m-%d %H:%M} — parser fixed and committed\n" + BODY, "utf-8")
    at = time.time() - 120
    os.utime(book, (at, at))
    return repo


def _stop(tmp_path, session="s1"):
    transcript = tmp_path / "t.jsonl"
    start = datetime.fromtimestamp(time.time() - 600, tz=timezone.utc).isoformat()
    transcript.write_text(json.dumps({"timestamp": start}) + "\n", "utf-8")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(tmp_path / "home"), BATON_HOME=str(tmp_path / "tasks"),
               BATON_LOGBOOK="LOGBOOK.md", CLAUDE_PLUGIN_DATA=str(tmp_path / "data"),
               BATON_STATE_DIR=str(tmp_path / "st"),
               BATON_LESSONS_STATE=str(tmp_path / "data" / "baton.lessons.json"),
               BATON_BODY_STATE=str(tmp_path / "data" / "baton.bodies.json"),
               BATON_SESSION_STATE=os.environ["BATON_SESSION_STATE"])
    out = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, env=env,
                         input=json.dumps({"session_id": session, "transcript_path": str(transcript)}))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def test_an_uncommitted_change_newer_than_the_entry_is_said(tmp_path):
    repo = _setup(tmp_path, commit_first=False)                 # the probe: no commit at all
    (repo / "parser.py").write_text("def parse_date(s):\n    return s  # tz\n", "utf-8")
    said = _stop(tmp_path).get("systemMessage", "")
    assert "`code:` repository" in said and "1 uncommitted: parser.py" in said, said
    assert "uncommitted" not in _stop(tmp_path).get("systemMessage", ""), "once a session"


def test_a_commit_after_the_entry_is_named(tmp_path):
    repo = _setup(tmp_path, commit_first=True)
    (repo / "parser.py").write_text("def parse_date(s):\n    return s  # tz\n", "utf-8")
    _git(repo, "commit", "-qam", "keep the offset")
    said = _stop(tmp_path).get("systemMessage", "")
    assert "1 commit(s):" in said and "keep the offset" in said, said


def test_a_repository_with_nothing_newer_is_not_mentioned(tmp_path):
    _setup(tmp_path, commit_first=True)
    assert "`code:` repository" not in _stop(tmp_path).get("systemMessage", "")
