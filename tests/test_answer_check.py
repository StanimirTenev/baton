"""ZA-OPRAVYANE row 55 (swarm D, 22.10; probe G03): the entry written in answer to a hand-back was
the one entry nothing checked.

The hollow check exists for "an agent that writes a low-effort entry just to get past it" -- and
that moment is the second pass of Stop, after a hand-back. With `stop_hook_active` Stop only
counted what came of the hand-back; the hollow check, L1, L3 and L4 were never called, and the next
session's Stop skips an entry saved before it began. Now the second pass runs them and says what
they find to the human, in a systemMessage -- never a second hand-back.
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
    (folder / "report.md").write_text("work", "utf-8")
    _age(folder / "report.md", 300)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({"type": "user", "timestamp": (
        datetime.now() - timedelta(minutes=30)).astimezone().isoformat()}) + "\n", "utf-8")
    return book, str(transcript)


def _answer(book, body):
    head, rest = book.read_text("utf-8").split("\n\n", 1)
    book.write_text(f"{head}\n\n## {datetime.now():%Y-%m-%d %H:%M} — done\n\n{body}\n\n" + rest,
                    "utf-8")


def _stop(tmp_path, transcript, again=False):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_HOME", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               HOME=str(tmp_path / "home"), BATON_STATE_DIR=str(tmp_path / "state"))
    out = subprocess.run([sys.executable, str(ROOT / "hooks" / "baton_stop.py")],
                         capture_output=True, text=True, env=env,
                         input=json.dumps({"session_id": "s", "transcript_path": transcript,
                                           "stop_hook_active": again}))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def test_a_hollow_answer_to_a_hand_back_is_said_to_the_human(tmp_path):
    book, tr = _session(tmp_path)
    assert _stop(tmp_path, tr).get("decision") == "block"          # unrecorded work
    _answer(book, "ok, all tests pass.")
    second = _stop(tmp_path, tr, again=True)
    assert "decision" not in second, "never a second hand-back"
    said = second.get("systemMessage", "")
    assert "hollow" in said and "L4" in said, second


def test_a_good_answer_is_not_said(tmp_path):
    book, tr = _session(tmp_path)
    _stop(tmp_path, tr)
    _answer(book, GOOD.replace("Wrote report.md", "Finished report.md"))
    assert "hollow" not in _stop(tmp_path, tr, again=True).get("systemMessage", "")
