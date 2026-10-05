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
