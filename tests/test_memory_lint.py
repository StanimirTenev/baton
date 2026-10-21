"""#11: a free check of a memory index -- links lead somewhere, every file has a line.
Run as the human runs it (a subprocess); it must report and never edit."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "baton_memory_lint.py"


def _run(index):
    return subprocess.run([sys.executable, str(TOOL), str(index)], capture_output=True, text=True)


def _memory(tmp_path):
    mem = tmp_path / "memory"
    (mem / "qrp").mkdir(parents=True)
    (mem / "a.md").write_text("x", "utf-8")
    (mem / "qrp" / "b.md").write_text("x", "utf-8")
    (mem / "orphan.md").write_text("x", "utf-8")
    index = mem / "MEMORY.md"
    index.write_text("# Index\n- [A](a.md) — a\n- [B](qrp/b.md#top) — b\n"
                     "- [gone](missing.md) — c\n- [site](https://example.com) — d\n", "utf-8")
    return index


def test_reports_a_dead_link_and_a_file_without_a_line(tmp_path):
    index = _memory(tmp_path)
    before = index.read_bytes()
    out = _run(index)
    assert out.returncode == 1
    assert "missing.md" in out.stdout and "orphan.md" in out.stdout
    assert "a.md\n" not in out.stdout.split("no line in the index")[1]
    assert "example.com" not in out.stdout and "b.md" not in out.stdout
    assert index.read_bytes() == before                     # report, never edit


def test_a_clean_index_passes(tmp_path):
    index = _memory(tmp_path)
    (index.parent / "orphan.md").unlink()
    index.write_text("- [A](a.md)\n- [B](qrp/b.md)\n", "utf-8")
    out = _run(index)
    assert out.returncode == 0, out.stdout


DAY = 86400


def _olewinski(tmp_path):
    """The case of 19.09.2026 (ZA-OPRAVYANE row 29): the index said "we want the paper, it is
    behind a wall"; the detail file had recorded it as read five days earlier."""
    import os
    import time
    mem = tmp_path / "memory"
    mem.mkdir()
    detail = mem / "olewinski.md"
    detail.write_text("Read in full on 14.09.\n", "utf-8")
    index = mem / "MEMORY.md"
    index.write_text("- [Olewinski](olewinski.md) — ⚠️ we want the PDF, it is behind a wall\n", "utf-8")
    now = time.time()
    os.utime(index, (now - 5 * DAY, now - 5 * DAY))
    os.utime(detail, (now, now))
    return index, detail


def test_a_line_whose_file_changed_after_it_is_named(tmp_path):
    index, _ = _olewinski(tmp_path)
    out = _run(index)
    assert out.returncode == 1, out.stdout
    assert "changed after their line" in out.stdout and "line 1: olewinski.md" in out.stdout, out.stdout


def test_an_edit_elsewhere_in_the_index_does_not_hide_it(tmp_path):
    """The index's own time moves with every edit; the line's is remembered by its text."""
    import os
    import time
    index, _ = _olewinski(tmp_path)
    _run(index)
    index.write_text(index.read_text("utf-8") + "- other line\n", "utf-8")
    now = time.time()
    os.utime(index, (now + 60, now + 60))
    assert "line 1: olewinski.md" in _run(index).stdout


def test_the_line_rewritten_or_accepted_is_quiet(tmp_path):
    import os
    import time
    index, detail = _olewinski(tmp_path)
    _run(index)
    index.write_text("- [Olewinski](olewinski.md) — read in full, 14.09\n", "utf-8")
    later = time.time() + 120
    os.utime(index, (later, later))
    assert "changed after their line (0)" in _run(index).stdout, "rewritten: nothing to re-read"

    detail.write_text("Read in full on 14.09. Cited on 20.09.\n", "utf-8")
    os.utime(detail, (later + 600, later + 600))
    assert "line 1: olewinski.md" in _run(index).stdout
    accepted = subprocess.run([sys.executable, str(TOOL), str(index), "--accept"],
                              capture_output=True, text=True)
    assert "accepted" in accepted.stdout
    assert "changed after their line (0)" in _run(index).stdout, "re-read and still right"


def test_a_logbook_growing_under_its_line_is_not_named(tmp_path):
    """A logbook changes with every entry by design; its line in the index only points to it.
    Measured on the author's index (21.10): all four lines named were logbooks."""
    import os
    index, detail = _olewinski(tmp_path)
    book = detail.with_name("LOGBOOK.md")
    detail.rename(book)
    index.write_text(index.read_text("utf-8").replace("olewinski.md", "LOGBOOK.md"), "utf-8")
    os.utime(index, (book.stat().st_mtime - 5 * DAY,) * 2)
    out = subprocess.run([sys.executable, str(TOOL), str(index)], capture_output=True, text=True,
                         env={**os.environ, "BATON_LOGBOOK": "LOGBOOK.md"})
    assert "changed after their line (0)" in out.stdout, out.stdout
