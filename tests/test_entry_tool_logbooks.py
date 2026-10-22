"""ZA-OPRAVYANE row 65 (swarm D, 22.10; probe G13): tools/baton_entry.py -- the tool lesson L1 sends
the agent to -- refused logbooks every hook accepts.

The hooks read a logbook as `utf-8-sig` and support one with no header. The tool read `utf-8`,
required the first line to be `---` and an existing dated entry: a BOM (PowerShell 5.1, Notepad)
and a header-less logbook were "the front matter broke", a new logbook with a header and no entry
"no dated entry to insert in front of". On those the agent could only fall back to typing the
hour by hand -- the mistake L1 is about.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(path, alias):
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


be = _load(ROOT / "tools" / "baton_entry.py", "be_row65")
ss = _load(ROOT / "hooks" / "baton_session_start.py", "ss_row65")

ENTRY = "### What was asked\nx\n\n### Done\ny\n\n### Result\nz\n"
OLD = "## 2026-10-01 10:00 — first\n\nbody\n"
CASES = {
    "bom": "﻿---\nstate: active\n---\n\n" + OLD,
    "no-header": "# Report\n\n" + OLD,
    "first-entry": "---\nstate: active\nnext: start\n---\n\n",
    "no-header-no-entry": "# Report\n",
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_tool_writes_where_the_hooks_read(tmp_path, case):
    book = tmp_path / "LOGBOOK.md"
    book.write_bytes(CASES[case].encode("utf-8"))
    be.write_entry(book, ENTRY, title="added with the tool")
    raw = book.read_bytes()
    text = raw.decode("utf-8-sig")
    assert "added with the tool" in ss.first_entry_title(text), text
    assert f"## {datetime.now():%Y-%m-%d}" in text
    if "header" not in case:
        assert ss.parse_frontmatter(text).get("state") == "active", text      # the header survived
    assert raw.startswith(b"\xef\xbb\xbf") == (case == "bom"), "the BOM is kept, never added"
    if "first" in case or case == "bom":
        assert text.index("## ") > text.index("---", 3)
    if case == "no-header":
        assert text.index("added with the tool") < text.index("2026-10-01 10:00")


def test_a_broken_header_is_still_refused(tmp_path):
    book = tmp_path / "LOGBOOK.md"
    book.write_text("---\nstate: active\n\n" + OLD, "utf-8")      # never closed
    with pytest.raises(ValueError):
        be.write_entry(book, ENTRY, title="x")
