"""The Stop hook demands an entry; this is the tool that writes one without breaking
the file. Every test here is a failure that happened, not a case that was imagined.

Four of them come from three days in September 2026: three logbooks whose closing
fence was glued to the first heading, four headings glued mid-file in two folders,
a pointer replacement that was skipped in silence, and entries stamped hours ahead
of the system clock.

The fifth is the one that matters most for how this repository tests: the other
seven passed while the tool falsely rejected a real logbook. It was caught by
running it against every logbook on the machine, not by adding another unit test.
"""

import datetime
import importlib.util
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "tools" / "baton_vpishi.py"
spec = importlib.util.spec_from_file_location("bv", TOOL)
bv = importlib.util.module_from_spec(spec)
sys.modules["bv"] = bv
spec.loader.exec_module(bv)

HEADER = '---\nsastoyanie: aktivna\nsledvashto: "the old one"\n---\n\n'
OLD_ENTRY = "## 2026-09-20 10:00 — an older entry\n\nsome text\n"


def _logbook(tmp_path: Path, body: str = OLD_ENTRY) -> Path:
    path = tmp_path / "LOGBOOK.md"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


# --- half a pointer replacement --------------------------------------------

def test_a_new_pointer_without_the_old_one_fails(tmp_path):
    """The worst outcome is the entry landing while the pointer keeps its old text."""
    path = _logbook(tmp_path)
    with pytest.raises(AssertionError, match="BOTH"):
        bv.vpishi(str(path), "## 2026-09-26 11:00 — new", sledvashto='sledvashto: "new"')


def test_the_old_pointer_without_a_new_one_also_fails(tmp_path):
    path = _logbook(tmp_path)
    with pytest.raises(AssertionError, match="BOTH"):
        bv.vpishi(str(path), "## 2026-09-26 11:00 — new", staro='sledvashto: "the old one"')


def test_both_together_replace_the_pointer(tmp_path):
    path = _logbook(tmp_path)
    bv.vpishi(str(path), "## 2026-09-26 11:00 — new",
              sledvashto='sledvashto: "the new one"', staro='sledvashto: "the old one"')
    text = path.read_text(encoding="utf-8")
    assert 'sledvashto: "the new one"' in text
    assert 'sledvashto: "the old one"' not in text


# --- a heading glued mid-file ----------------------------------------------

def test_a_heading_glued_to_the_previous_line_is_caught(tmp_path):
    """Invisible to any heading-based read, including the author's own grep."""
    path = _logbook(tmp_path, OLD_ENTRY + "last line## 2026-09-19 09:00 — older still\n")
    with pytest.raises(AssertionError, match="glued mid-file"):
        bv.vpishi(str(path), "## 2026-09-26 11:00 — new")


def test_a_quotation_in_inline_code_is_not_a_gluing(tmp_path):
    """A logbook describing this defect contains the broken string verbatim."""
    path = _logbook(tmp_path, OLD_ENTRY + "Line 93 read `x.## 2026-09-23 14:05` — wrong\n")
    bv.vpishi(str(path), "## 2026-09-26 11:00 — new")
    assert "## 2026-09-26 11:00" in path.read_text(encoding="utf-8")


def test_a_double_backtick_span_may_contain_single_backticks(tmp_path):
    """Found by positive control, not by review.

    Seven unit tests passed while the tool rejected a real logbook whose text was
    ``  `some_file`.## 2026-09-23 14:05  `` -- a double-backtick span containing
    single ones, which is exactly what the double form is for. ``[^`]*`` does not
    pass through them. The fixture below is that line.
    """
    quoted = "Line 93 read `` `some_file`.## 2026-09-23 14:05 `` — wrong\n"
    path = _logbook(tmp_path, OLD_ENTRY + quoted)
    bv.vpishi(str(path), "## 2026-09-26 11:10 — new")
    assert "## 2026-09-26 11:10" in path.read_text(encoding="utf-8")


# --- an hour ahead of the clock --------------------------------------------

def test_a_heading_ahead_of_the_clock_warns_and_still_writes(tmp_path, capsys):
    """It warns rather than refuses: a few hours can be a timezone, and a helper
    that refuses a write on a guess gets worked around instead of fixed."""
    ahead = (datetime.datetime.now() + datetime.timedelta(hours=5)).strftime("%Y-%m-%d %H:%M")
    path = _logbook(tmp_path)
    bv.vpishi(str(path), f"## {ahead} — from the future")
    out = capsys.readouterr().out
    # ⚠️ NOT `"ahead" in out.lower()` -- pytest's tmp_path is named after the test,
    # so that string is in the printed path and the assertion passed with the
    # warning disabled. Mutation testing caught it; the unit test did not.
    assert "AHEAD of the system clock" in out
    assert f"## {ahead}" in path.read_text(encoding="utf-8")


def test_a_normal_hour_says_nothing(tmp_path, capsys):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    path = _logbook(tmp_path)
    bv.vpishi(str(path), f"## {now} — now")
    assert "AHEAD of the system clock" not in capsys.readouterr().out


# --- the original defect, still pinned --------------------------------------

def test_the_closing_fence_never_ends_up_glued(tmp_path):
    """The failure this tool was written for: `---## 2026-...` with the fence eaten."""
    path = tmp_path / "LOGBOOK.md"
    path.write_text('---\nsastoyanie: aktivna\n---\n## 2026-09-20 10:00 — tight\n',
                    encoding="utf-8")
    bv.vpishi(str(path), "## 2026-09-26 11:00 — new")
    text = path.read_text(encoding="utf-8")
    assert "---##" not in text
    assert text.count("---") >= 2
