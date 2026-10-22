"""ZA-OPRAVYANE row 58 (swarm D, 22.10; probe G02): an entry headed `## 22.10.2026 15:30 — ...`
passed every quality check of Stop.

Stop's `_HEADING` knew only `## YYYY-MM-DD`. A new top entry headed day first -- the way the human
writes dates everywhere else (TVARDENIYA, CLAUDE.md; SessionStart's claims registers accept it) --
was not an entry for top_entry/_changed_tops/hand_typed_hours: the hollow check, L1, L3 and L4
all looked at the older ISO-dated entry below it and passed, while the body hash counted the new
text as the work recorded. Now both forms are headings, with or without the hour.
"""
from __future__ import annotations

import importlib.util
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
HOLLOW = "ok. All tests pass, and the repo is public now.\n"


def _age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


def _case(tmp_path, heading):
    folder = tmp_path / "tasks" / "report"
    folder.mkdir(parents=True)
    book = folder / "LOGBOOK.md"
    header = "---\nstate: active\ndone_when: report sent\n---\n\n"
    old = datetime.now() - timedelta(days=1)
    book.write_text(header + f"## {old:%Y-%m-%d %H:%M} — draft\n\n" + GOOD, "utf-8")
    _age(book, 86400)
    (folder / "report.md").write_text("work", "utf-8")
    _age(folder / "report.md", 300)
    text = book.read_text("utf-8")
    book.write_text(text.replace(header, header + f"## {heading} — done\n\n" + HOLLOW + "\n", 1),
                    "utf-8")
    _age(book, 120)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({"type": "user", "timestamp": (
        datetime.now() - timedelta(minutes=30)).astimezone().isoformat()}) + "\n", "utf-8")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_HOME", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               HOME=str(tmp_path / "home"), BATON_STATE_DIR=str(tmp_path / "state"))
    out = subprocess.run([sys.executable, str(ROOT / "hooks" / "baton_stop.py")],
                         capture_output=True, text=True, env=env,
                         input=json.dumps({"session_id": "s", "transcript_path": str(transcript)}))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


@pytest.mark.parametrize("fmt", ["%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M"])
def test_a_day_first_heading_is_checked_like_an_iso_one(tmp_path, fmt):
    out = _case(tmp_path, f"{datetime.now():{fmt}}")
    reason = out.get("reason", "")
    assert out.get("decision") == "block" and "hollow" in reason and "L4" in reason, out


def test_a_day_first_hour_is_read_for_l1(tmp_path):
    spec = importlib.util.spec_from_file_location("bs_hf", ROOT / "hooks" / "baton_stop.py")
    bs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bs)
    m = bs._HEADING.match("## 22.10.2026 15:30 — done")
    assert m and bs._day(m.group(1)) == datetime(2026, 10, 22) and m.group(2) == "15"
    assert bs.top_entry("## 22.10.2026 15:30 — done\nbody\n## 2026-10-21 10:00 — x\n")[0] \
        .startswith("## 22.10.2026")
    assert not bs._HEADING.match("## 22.10 — no year")          # not a date Baton can place
