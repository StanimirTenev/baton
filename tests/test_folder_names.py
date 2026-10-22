"""ZA-OPRAVYANE row 63 (swarm D, 22.10; probe G10): a task folder named `... (something)` broke
Stop's bookkeeping.

Stop recovered the folder from its own listing by `split(" (")[0]`: "report (v2) (newest: x.md)"
became "report". So for `Договор (Кипър)`, `client (old)`, a copy Finder names `report (1)`, the
hand-back was remembered under the wrong name and a real entry written on the second try was
counted as passed without one (/baton-doctor's measure), and `flagged` missed the folder, so it was
handed back for unrecorded work AND asked about hollow/L3/L4 in the same message.
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
HEAD = "---\nstate: active\ndone_when: report sent\n---\n\n"


def _age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


def _env(tmp_path):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_HOME", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               HOME=str(tmp_path / "home"), BATON_STATE_DIR=str(tmp_path / "state"))
    return env


def _stop(tmp_path, session, transcript, again=False):
    out = subprocess.run([sys.executable, str(ROOT / "hooks" / "baton_stop.py")],
                         capture_output=True, text=True, env=_env(tmp_path),
                         input=json.dumps({"session_id": session, "transcript_path": transcript,
                                           "stop_hook_active": again}))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def _folder(tmp_path, name):
    folder = tmp_path / "tasks" / name
    folder.mkdir(parents=True)
    book = folder / "LOGBOOK.md"
    book.write_text(HEAD + f"## {datetime.now() - timedelta(days=1):%Y-%m-%d %H:%M} — draft\n\n"
                    + GOOD, "utf-8")
    _age(book, 86400)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({"type": "user", "timestamp": (
        datetime.now() - timedelta(minutes=30)).astimezone().isoformat()}) + "\n", "utf-8")
    _stop(tmp_path, "s0", str(tmp_path / "none"))        # the first look only remembers
    return folder, book, str(transcript)


def _counts():
    return json.loads(Path(os.environ["BATON_LESSONS_STATE"]).read_text("utf-8"))["handback"]


@pytest.mark.parametrize("name", ["report (v2)", "Договор (Кипър)", "report-v2"])
def test_an_entry_on_the_second_try_is_counted_as_recorded(tmp_path, name):
    folder, book, tr = _folder(tmp_path, name)
    (folder / "report.md").write_text("w", "utf-8")
    _age(folder / "report.md", 300)
    assert _stop(tmp_path, "s", tr).get("decision") == "block"
    rest = book.read_text("utf-8")[len(HEAD):]
    book.write_text(HEAD + f"## {datetime.now():%Y-%m-%d %H:%M} — report.md written\n\n" + GOOD
                    + "\n" + rest, "utf-8")
    _stop(tmp_path, "s", tr, again=True)
    hb = _counts()
    assert hb.get("recorded_after", 0) == 1 and hb.get("passed", 0) == 0, hb


def test_a_folder_handed_back_is_not_also_asked_about_its_entry(tmp_path):
    folder, book, tr = _folder(tmp_path, "client (old)")
    rest = book.read_text("utf-8")[len(HEAD):]
    book.write_text(HEAD + f"## {datetime.now():%Y-%m-%d %H:%M} — done\n\nok, all tests pass.\n\n"
                    + rest, "utf-8")
    _age(book, 900)
    (folder / "report.md").write_text("w", "utf-8")
    _age(folder / "report.md", 300)
    reason = _stop(tmp_path, "s", tr).get("reason", "")
    assert "client (old)" in reason and "newer than" in reason
    assert "hollow" not in reason and "L4" not in reason, reason
