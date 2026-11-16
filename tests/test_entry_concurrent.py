"""Two agents writing one logbook at the same time (phase 2 of the multi-agent path).

v3.36.0 said it plainly: "Two agents writing one logbook at the same time was not tested;
`baton_entry.py` takes no lock." It read the logbook, built the new text in memory and replaced the
file through ONE temporary name, `LOGBOOK.md.tmp`. Two writers at once: each read the same logbook,
so the second replace dropped the first one's entry (a read-modify-write race), and both wrote the
same temporary file, so one could move the other's half-written text into place or find its own
temporary file already gone. Reproduced here with processes, not threads -- two agents are two
processes -- before the lock was written.

Now the write is serialised by `.LOGBOOK.md.lock` beside the logbook (O_CREAT|O_EXCL, so it works the
same on Linux, macOS and Windows; a lock older than LOCK_STALE_S is a writer that died holding it),
and the temporary file is a dotfile of its own per process. The format of the logbook is unchanged.
Readers never take the lock: os.replace swaps the whole file, so a reader sees the old text or the
new one, never half of it.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "baton_entry.py"
HEADER = "---\nstate: active\nnext: „следващото“ с кирилица\n---\n\n"
OLDEST = "## 2026-10-01 10:00 — най-старият запис\n\nТекст, който трябва да оцелее дума по дума.\n"
PER_WRITER = 20


def _load():
    spec = importlib.util.spec_from_file_location("be_concurrent", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _logbook(tmp_path) -> Path:
    folder = tmp_path / "задачи с интервал" / "обща задача"
    folder.mkdir(parents=True)
    book = folder / "LOGBOOK.md"
    book.write_text(HEADER + OLDEST, "utf-8")
    return book


WRITER = textwrap.dedent("""
    import importlib.util, sys, time
    spec = importlib.util.spec_from_file_location("be", sys.argv[1])
    be = importlib.util.module_from_spec(spec); spec.loader.exec_module(be)
    book, who, n, go = sys.argv[2], sys.argv[3], int(sys.argv[4]), float(sys.argv[5])
    while time.time() < go:
        pass
    for i in range(n):
        be.write_entry(book, f"## 2026-11-16 09:{i:02d} — агент {who} запис {i}\\n\\n"
                             f"### Какво\\nТяло на {who} {i}: кирилица и „кавички“.\\n")
""")

READER = textwrap.dedent("""
    import sys, time
    book, go, until, out = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
    bad, reads = [], 0
    while time.time() < go:
        pass
    while time.time() < until:
        try:
            raw = open(book, "rb").read()
        except OSError as exc:        # Windows: a replace in progress can refuse an open
            continue
        reads += 1
        text = raw.decode("utf-8")
        if not (text.startswith(sys.argv[5]) and text.rstrip().endswith(sys.argv[6].rstrip())):
            bad.append(repr(text[:80]) + " ... " + repr(text[-80:]))
    open(out, "w", encoding="utf-8").write(f"{reads}\\n" + "\\n".join(bad[:5]))
""")


def _spawn(script: str, *args) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", script, *map(str, args)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def test_two_writers_at_once_lose_no_entry_and_readers_never_see_half_a_file(tmp_path):
    book = _logbook(tmp_path)
    go = time.time() + 1.5
    writers = [_spawn(WRITER, TOOL, book, who, PER_WRITER, go) for who in ("А", "Б")]
    readers = [_spawn(READER, book, go, go + 60, tmp_path / f"r{i}.txt", HEADER, OLDEST)
               for i in range(2)]
    errors = [w.communicate(timeout=120)[1] for w in writers]
    for r in readers:           # the readers run until the writers are done, then a moment more
        r.kill()
    readers = [_spawn(READER, book, 0, time.time() + 0.5, tmp_path / f"q{i}.txt", HEADER, OLDEST)
               for i in range(2)]
    for r in readers:
        r.wait(timeout=30)
    assert all(w.returncode == 0 for w in writers), errors
    text = book.read_text("utf-8")
    for who in ("А", "Б"):
        for i in range(PER_WRITER):
            assert f"агент {who} запис {i}\n" in text, f"lost: {who} {i}"
    assert text.count("\n## 2026-11-16 ") == 2 * PER_WRITER, "an entry twice, or one lost"
    assert text.startswith(HEADER) and text.endswith(OLDEST), "header or the oldest entry changed"
    for i in range(2):
        reads, *bad = (tmp_path / f"q{i}.txt").read_text("utf-8").split("\n")
        assert int(reads) > 0 and not any(bad), bad
    leftovers = [p.name for p in book.parent.iterdir()
                 if p.name not in ("LOGBOOK.md", ".baton-etap.html")]
    assert not leftovers, f"left behind: {leftovers}"


def test_readers_during_a_burst_of_writes_never_see_half_a_file(tmp_path):
    """The readers' half on its own, from the start of the writes: they must not see a logbook
    that has lost its header or its oldest entry (a file being written in place)."""
    book = _logbook(tmp_path)
    go = time.time() + 1.5
    readers = [_spawn(READER, book, go, go + 8, tmp_path / f"r{i}.txt", HEADER, OLDEST)
               for i in range(2)]
    writers = [_spawn(WRITER, TOOL, book, who, PER_WRITER, go) for who in ("А", "Б")]
    for w in writers:
        w.wait(timeout=120)
    for r in readers:
        r.wait(timeout=30)
    for i in range(2):
        reads, *bad = (tmp_path / f"r{i}.txt").read_text("utf-8").split("\n")
        assert int(reads) > 0, "the reader never read"
        assert not any(bad), bad


def test_a_lock_left_by_a_writer_that_died_is_taken_over(tmp_path):
    be = _load()
    book = _logbook(tmp_path)
    lock = book.with_name("." + book.name + ".lock")
    lock.write_text("12345", "utf-8")
    old = time.time() - be.LOCK_STALE_S - 5
    os.utime(lock, (old, old))
    be.write_entry(book, "## 2026-11-16 09:00 — след мъртъв писач\n\n### Какво\nтяло\n")
    assert "след мъртъв писач" in book.read_text("utf-8")
    assert not lock.exists(), "the lock is released after the write"


def test_a_lock_held_by_a_live_writer_is_waited_for_then_refused_loudly(tmp_path, monkeypatch):
    be = _load()
    book = _logbook(tmp_path)
    lock = book.with_name("." + book.name + ".lock")
    lock.write_text("12345", "utf-8")
    monkeypatch.setattr(be, "LOCK_WAIT_S", 0.3)
    before = book.read_bytes()
    try:
        be.write_entry(book, "## 2026-11-16 09:00 — не бива да влезе\n\n### Какво\nтяло\n")
    except TimeoutError as exc:
        assert str(lock) in str(exc)
    else:
        raise AssertionError("written without the lock")
    assert book.read_bytes() == before and lock.exists(), "nothing written, the other's lock kept"
