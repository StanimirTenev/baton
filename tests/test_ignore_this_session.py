"""ZA-OPRAVYANE row 57 (swarm D, 22.10; probe G04): a `.batonignore` written in the same session
silenced Stop, and nothing noticed.

Its lines apply the moment they are on disk, and the board even told the agent the way out ("or
add the file to the folder's .batonignore"). An agent handed back for unrecorded work could add `*`
-- or the file's name, to the folder's or the task root's .batonignore -- and the turn passed with
no word. Now an ignore file saved this session that hides files saved this session is said to the
human, once a session; the lines still apply (it may be right), and the board no longer offers it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GOOD = ("### What was asked\nA draft of the quarterly report in the usual layout for the board.\n\n"
        "### Done\nWrote report.md from last quarter's numbers; the revenue table is filled.\n\n"
        "### Result\nThe draft is complete except the outlook paragraph, which needs data.\n\n"
        "### Still open\nThe outlook paragraph, once the forecast arrives on Friday morning.\n")


def _age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


def _session(tmp_path):
    folder = tmp_path / "tasks" / "report"
    folder.mkdir(parents=True)
    book = folder / "LOGBOOK.md"
    book.write_text("---\nstate: active\ndone_when: report sent\n---\n\n"
                    f"## {datetime.now() - timedelta(days=1):%Y-%m-%d %H:%M} — draft\n\n" + GOOD,
                    "utf-8")
    _age(book, 86400)
    (folder / "contract-v2.md").write_text("the new contract terms", "utf-8")
    _age(folder / "contract-v2.md", 300)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({"type": "user", "timestamp": (
        datetime.now() - timedelta(minutes=30)).astimezone().isoformat()}) + "\n", "utf-8")
    return folder, str(transcript)


def _stop(tmp_path, transcript):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_HOME", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               HOME=str(tmp_path / "home"), BATON_STATE_DIR=str(tmp_path / "state"))
    out = subprocess.run([sys.executable, str(ROOT / "hooks" / "baton_stop.py")],
                         capture_output=True, text=True, env=env,
                         input=json.dumps({"session_id": "s", "transcript_path": transcript}))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


@pytest.mark.parametrize("where,line", [("folder", "*"), ("folder", "contract-v2.md"),
                                        ("root", "report/*"), ("root", "report")])
def test_an_ignore_written_this_session_is_said(tmp_path, where, line):
    folder, tr = _session(tmp_path)
    target = folder if where == "folder" else folder.parent
    (target / ".batonignore").write_text(line + "\n", "utf-8")
    out = _stop(tmp_path, tr)
    said = out.get("systemMessage", "")
    assert ".batonignore" in said and "contract-v2.md" in said and "report" in said, out
    assert ".batonignore" not in json.dumps(_stop(tmp_path, tr)), "once a session"


def test_an_ignore_from_before_the_session_is_obeyed_quietly(tmp_path):
    folder, tr = _session(tmp_path)
    (folder / ".batonignore").write_text("contract-v2.md\n", "utf-8")
    _age(folder / ".batonignore", 7200)
    assert _stop(tmp_path, tr) == {}


def test_an_ignore_written_now_that_hides_nothing_new_is_quiet(tmp_path):
    folder, tr = _session(tmp_path)
    (folder / "old.log").write_text("x", "utf-8")
    _age(folder / "old.log", 86400 * 3)
    (folder / ".batonignore").write_text("*.log\n", "utf-8")
    out = _stop(tmp_path, tr)
    assert out.get("decision") == "block" and ".batonignore" not in out.get("systemMessage", "")


def test_the_board_no_longer_offers_the_ignore_file_as_the_way_out(tmp_path):
    folder, _ = _session(tmp_path)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_HOME", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               HOME=str(tmp_path / "home"))
    out = subprocess.run([sys.executable, str(ROOT / "hooks" / "baton_session_start.py")],
                         input=b"{}", capture_output=True, env=env)
    ctx = out.stdout.decode("utf-8")
    assert "contract-v2.md" in ctx and "or add the file to the folder's .batonignore" not in ctx
