"""ZA-OPRAVYANE row 69 (the 3.22.0 agent, 22.10): row 58 taught Stop the day-first heading
(`## 22.10.2026 15:30`); SessionStart and the entry tool still read ISO only. The board showed such
an entry's whole heading as its title, the quiet-session note did not count it, and the entry tool
let it be glued mid-line. Headings here are from the clock (lesson L1).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from test_quiet_session import _ctx, _setup

ROOT = Path(__file__).resolve().parent.parent


def _load(path: Path, alias: str):
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("fmt", ["%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%d.%m.%Y"])
def test_the_board_title_of_either_heading(fmt):
    ss = _load(ROOT / "hooks" / "baton_session_start.py", "bss_titles")
    text = f"---\nstate: active\n---\n\n## {datetime.now():{fmt}} — fix the parser\n\nx\n"
    assert ss.first_entry_title(text) == "fix the parser"


def test_a_day_first_entry_in_the_session_is_counted(tmp_path):
    entry_at = datetime.now() - timedelta(minutes=90)            # inside the last session
    env, own = _setup(tmp_path, entry_at)
    book = tmp_path / "tasks" / "pricing" / "LOGBOOK.md"
    book.write_text(f"---\nstate: active\nturn: us\n---\n\n## {entry_at:%d.%m.%Y %H:%M} — e\n\nx\n",
                    "utf-8")
    assert "messages from the human" not in _ctx(env, own)


def test_the_entry_tool_refuses_a_day_first_heading_glued_mid_line(tmp_path):
    book = tmp_path / "LOGBOOK.md"
    book.write_text(f"## {datetime.now() - timedelta(days=1):%Y-%m-%d %H:%M} — older\n\n"
                    f"see the note## {datetime.now():%d.%m.%Y %H:%M} — glued\n", "utf-8")
    entry = tmp_path / "entry.md"
    entry.write_text("### Done\nx\n", "utf-8")
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "baton_entry.py"), str(book),
                          str(entry), "--title", "new"], capture_output=True, text=True)
    assert out.returncode != 0 and "glued" in out.stderr, (out.stdout, out.stderr)


def test_the_entry_tool_says_a_day_first_hour_ahead(tmp_path):
    be = _load(ROOT / "tools" / "baton_entry.py", "be_ahead")
    ahead = datetime.now() + timedelta(hours=2)
    assert be._hours_ahead(f"## {ahead:%d.%m.%Y %H:%M} — x\n\nbody") is not None
