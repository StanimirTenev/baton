#!/usr/bin/env python3
"""Prepend an entry to a logbook without corrupting it.

    python3 tools/baton_entry.py <logbook> <entry-file> [--next NEW --old OLD]
    python3 tools/baton_entry.py <logbook> --open      # open the page of the last entry

Or from Python, which is how an agent uses it:

    from baton_entry import write_entry
    write_entry("<path>/LOGBOOK.md", "<the entry>", next_line="<new line>", old_line="<old, verbatim>")

The Stop hook demands an entry at the top of the logbook. Nothing in Baton helped
write one, so it was done by hand, and doing it by hand went wrong four times in
three days. Every check below is one of those failures.

**The closing fence, glued.** `"\\n".join(lines[:cut]) + entry` does not end in a
newline when the file is `---\\n## 2026-...` with no blank line between. The result
is `---## 2026-...`, the closing fence disappears, the front-matter stops parsing,
and the task drops into the header-less fallback: no state, no priority, no next
move. Three logbooks in one afternoon. It was not spotted by reading them -- they
look fine unless you are looking at that one fence -- but by running the
session-start hook afterwards and seeing three tasks appear bare.

**A heading glued mid-file.** The first version checked only `^---##`, the case at
the front matter. A later sweep over every logbook found four headings glued to the
end of the previous line, in two folders, all from the same afternoon -- and all
invisible to any heading-based read, including the author's own `grep "^## "`.

⚠️ A quotation is not a gluing. A logbook that describes this very defect contains
the broken string verbatim; so inline code is stripped before the check. The
double-backtick form exists precisely so a span can contain single backticks, and
the first fix got that wrong -- seven unit tests passed and a real logbook was
falsely rejected. The test for it is taken from that file.

**Half a pointer replacement.** `if next_line and old_line:` means passing only the
new value is skipped in silence: the entry lands, the pointer keeps its old text,
and nothing says so. Silence is worse than refusal, because nobody looks twice.
Both or neither, or it fails.

**An hour ahead of the clock.** Entries were written with times hours ahead of the
system clock, because the hour was typed from memory rather than read from the
machine. This one only warns. A few hours can be a timezone, and a helper that
refuses a write on a guess gets worked around instead of fixed.

**The page of the entry** (ZA-OPRAVYANE row 117). After each write, `.baton-etap.html` in the
task folder is made anew: the header (state, next, done_when), the entry just written and the
work files saved since the logbook was last written. One file, overwritten every time; the dot
keeps Stop from counting it as work. The agent offers to open it only at the end of a big
stage, and `--open` opens it on this machine -- or, with no display, says the path instead.

**Two writers at once** (phase 2 of the multi-agent path, 16.11). Two agents sharing one logbook
are two processes. Each read the logbook, built its text and replaced the file through the same
`LOGBOOK.md.tmp`: the second replace dropped the first one's entry, and one writer could move the
other's half-written temporary file into place -- readers saw an empty logbook. Now the read, the
checks and the replace run under `.<logbook>.lock` beside it, made with O_CREAT|O_EXCL (the same
on Linux, macOS and Windows, no dependency); the temporary file is a dotfile of this process's
own. A lock older than LOCK_STALE_S is a writer that died holding it and is taken over; one that
cannot be had in LOCK_WAIT_S is a loud failure, never a write without it. Readers take no lock:
os.replace swaps the whole file, so they see the old text or the new one.
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import os
import re
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

# ISO or day first (row 69): `## 22.10.2026 15:30` is how the human writes a date elsewhere.
DATE = r'(?:\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})'
HEADING = re.compile(r'^## (' + DATE + r')(?: (\d{2}):(\d{2}))?')
AHEAD_MINUTES = 15       # below this, say nothing: clocks and timezones drift
PAGE = ".baton-etap.html"  # a dotfile: Stop never counts it as work (row 117)
PAGE_FILES = 40          # the page names at most this many files
SKIP_DIRS = {"node_modules", "__pycache__", "venv", "dist", "build"}
LOCK_WAIT_S = 15         # how long a writer waits for another one before it refuses
LOCK_STALE_S = 60        # a lock older than this: its writer died (a write takes well under 1 s)
REPLACE_TRIES = 50       # Windows: a reader holding the file open makes os.replace fail for a moment


def _lock(file: Path) -> Path:
    """Take `.<logbook>.lock` beside the logbook; raise TimeoutError when another writer keeps it."""
    lock = file.with_name("." + file.name + ".lock")
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except (FileExistsError, PermissionError):   # Windows: a lock being deleted refuses an open
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                    lock.unlink()     # its writer died holding it
                    continue
            except FileNotFoundError:
                continue              # released between the two calls: try again
            except OSError:
                pass                  # cannot be read or removed: wait for the deadline
            if time.monotonic() > deadline:
                raise TimeoutError(f"another writer holds {lock} (for over {LOCK_WAIT_S} s); "
                                   f"nothing was written. If no writer is running, delete it.")
            time.sleep(0.02)
            continue
        with os.fdopen(fd, "w") as fh:
            fh.write(str(os.getpid()))
        return lock


def _replace(tmp: Path, file: Path) -> None:
    """os.replace, retried: on Windows it fails while a reader has the logbook open."""
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(tmp, file)
            return
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                raise
            time.sleep(0.05)


def _without_code(text: str) -> str:
    """The text minus inline and fenced code -- those are quotations, not content."""
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    # ⚠️ A double-backtick span may CONTAIN single backticks -- that is what the
    # form is for. ``[^`]*`` does not pass through them, and that mistake made the
    # check reject a logbook that was quoting this defect correctly.
    text = re.sub(r'``.*?``', '', text, flags=re.S)
    return re.sub(r'`[^`\n]*`', '', text)


def _hours_ahead(entry: str) -> str | None:
    """How far the entry's own heading runs ahead of the system clock, if at all."""
    match = HEADING.match(entry.strip())
    if not match or not match.group(2):
        return None
    try:
        stamp = datetime.strptime(
            f"{match.group(1)} {match.group(2)}:{match.group(3)}",
            "%Y-%m-%d %H:%M" if "-" in match.group(1) else "%d.%m.%Y %H:%M")
    except ValueError:
        return None
    minutes = (stamp - datetime.now()).total_seconds() / 60
    if minutes <= AHEAD_MINUTES:
        return None
    return (f"⚠️ heading is {minutes / 60:.1f}h AHEAD of the system clock "
            f"({datetime.now():%Y-%m-%d %H:%M}). Read the hour from the machine.")


def write_entry(path, entry: str, next_line: str | None = None,
                old_line: str | None = None, title: str | None = None) -> None:
    """Prepend `entry`, optionally replacing the header's pointer line.

    `old_line` is the old line verbatim, so a pointer that has already moved is a
    loud failure rather than a silent duplicate.

    With `title`, the heading is built here, from the clock: `## <now> — <title>`, and
    `entry` is only the body. Lesson L1: the hour typed by hand was caught four times and
    prevented never; the hour a tool writes cannot be typed wrong.
    """
    if title:
        if re.match(r"\s*## ", entry):
            raise ValueError("with a title the entry is the body only -- it already has a heading")
        entry = f"## {datetime.now():%Y-%m-%d %H:%M} — {title.strip()}\n\n{entry.strip()}\n"
    file = Path(path)
    lock = _lock(file)
    try:
        before, text = _write_locked(file, entry, next_line, old_line)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass

    print(f"written: {path}")
    if (note := _hours_ahead(entry)):
        print(note)
    try:
        page = stage_page(file, text, entry.strip(), before)
    except Exception as exc:        # the page is a view; never a reason to fail the write
        print(f"HTML: not made ({exc})")
    else:
        print(f"HTML: {page}")
        if (why := no_display()):
            print(f"no display here ({why}): do not offer to open it; give the path, and a "
                  f"machine with a screen can copy it (scp) and open it there")


def _write_locked(file: Path, entry: str, next_line, old_line) -> tuple[float, str]:
    """Read, build, check and replace -- the part that runs under the lock. Returns the logbook's
    time before the write and the text written."""
    # Read as the hooks read (ZA-OPRAVYANE row 65): a BOM (PowerShell 5.1, Notepad) was "the front
    # matter broke". It is kept on the way back, never added.
    raw = file.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    header = text.startswith("---")

    # 🔴 Three defects from an external review of v2.14.0, all here:
    #   * the file was written BEFORE these checks ran, so a rejected entry was
    #     already on disk when the rejection was printed;
    #   * `old_line` was looked for in the whole file and replaced at the first hit, so a
    #     pointer surviving only in an old entry got rewritten -- editing the record,
    #     which is never edited -- while the header stayed as it was;
    #   * `assert` is stripped by `python -O`, so every barrier here vanished under a
    #     flag nobody would think to mention.
    # Build in memory, validate, then replace atomically; and raise, do not assert.

    # Half a replacement is worse than none: it keeps the old pointer and says nothing.
    if bool(next_line) != bool(old_line):
        raise ValueError(
            "pass BOTH `next_line` and `old_line`, or neither. "
            f"Got next_line={'yes' if next_line else 'no'}, "
            f"old_line={'yes' if old_line else 'no'}")
    if next_line:
        head_end = text.find("\n---", 3) + 4 if text.startswith("---") else 0
        header = text[:head_end]
        hits = header.count(old_line)
        if hits != 1:
            where = "nowhere in the front matter" if hits == 0 else f"{hits} times there"
            raise ValueError(
                f"the old pointer line must appear exactly once in the front matter; "
                f"found it {where}. A logbook entry is a record and is never edited, so "
                f"a match further down the file is refused rather than rewritten.")
        text = header.replace(old_line, next_line, 1) + text[head_end:]

    first = re.search(r'^## (?:\d{4}-|\d{1,2}\.\d{1,2}\.\d{4})', text, re.M)
    if first:
        at = first.start()
    elif header:          # a new logbook, no entry yet: right under its header (row 65)
        end = text.find("\n---", 3)
        close = text.find("\n", end + 1) if end >= 0 else -1
        cut = len(text) if close < 0 else close + 1
        head = text[:cut].rstrip("\n") + "\n\n"
        text, at = head + text[cut:].lstrip("\n"), len(head)
    else:                 # no header, no entry: after whatever is there
        text = text.rstrip("\n") + "\n\n" if text.strip() else ""
        at = len(text)
    text = text[:at] + entry.strip() + "\n\n" + text[at:]

    lines = text.split("\n")
    if header and not (lines[0] == "---" and "---" in lines[1:12]):
        raise ValueError("the front matter broke")
    # The `^---##` case is covered by the general check below -- `\S` matches the
    # dash. A separate assert for it survived every mutation, which means no test
    # pinned it, so it is gone rather than kept as decoration.
    glued = re.findall(r'\S(## ' + DATE + r'[^\n]{0,40})', _without_code(text))
    if glued:
        raise ValueError(
            f"heading glued mid-file, invisible to a heading read: {glued[:3]}")

    before = file.stat().st_mtime   # the work since this is what the new entry records
    # A dotfile of this process's own: Stop never counts it as work, and two writers never share
    # one (a shared `LOGBOOK.md.tmp` let one writer move the other's half-written text into place).
    tmp = file.with_name(f".{file.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8-sig" if bom else "utf-8")
        _replace(tmp, file)         # atomic: never a half-written logbook
    finally:
        if tmp.exists():
            tmp.unlink()
    return before, text


def _board():
    """The HTML board's module, for its stylesheet and the hook's own header reader."""
    spec = importlib.util.spec_from_file_location(
        "baton_board_page", Path(__file__).resolve().parent / "baton_board.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def no_display() -> str | None:
    """Why a page cannot be opened here, or None: over SSH, or Linux with no display."""
    if os.environ.get("SSH_CONNECTION"):
        return "this session runs over SSH"
    if sys.platform.startswith("linux") and not (
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return "no DISPLAY or WAYLAND_DISPLAY"
    return None


def saved_since(folder: Path, logbook: str, since: float) -> list[str]:
    """Work files saved after `since`, as Stop counts work: not the logbook, no dotfile."""
    out = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS)
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            if name.startswith(".") or (dirpath == str(folder) and name == logbook):
                continue
            try:
                if os.stat(full).st_mtime > since:
                    out.append(os.path.relpath(full, folder).replace(os.sep, "/"))
            except OSError:
                continue
    return out


def stage_page(logbook: Path, text: str, entry: str, since: float) -> Path:
    """Write `.baton-etap.html` beside the logbook: header, the new entry, the files."""
    board = _board()
    fm = board._hook().parse_frontmatter(text)
    folder = logbook.parent
    files = saved_since(folder, logbook.name, since)
    e = html.escape
    head = "".join(f'<div class="next"><strong>{k}:</strong> {e(str(fm[k]))}</div>'
                   for k in ("state", "next", "done_when") if fm.get(k))
    listed = "".join(f"<li>{e(f)}</li>" for f in files[:PAGE_FILES])
    if len(files) > PAGE_FILES:
        listed += f"<li>... and {len(files) - PAGE_FILES} more</li>"
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{e(folder.name)}</title><style>{board.CSS}"
            "pre{white-space:pre-wrap;font:inherit;margin:0}</style></head><body>"
            f'<div class="wrap"><h1>{e(folder.name)}</h1>'
            f'<div class="sub">{e(str(logbook))}</div>'
            + (f'<div class="card">{head}</div>' if head else "")
            + f'<h2>The entry</h2><div class="card"><pre>{e(entry)}</pre></div>'
            + "<h2>Files saved since the last entry</h2>"
            + (f'<div class="card"><ul>{listed}</ul></div>' if files
               else '<div class="card quiet">none in the task folder</div>')
            + "<footer>Made from the logbook by tools/baton_entry.py. The logbook is the record; "
              "this page is a view of it. Nothing leaves the machine.</footer>"
              "</div></body></html>")
    out = folder / PAGE
    out.write_text(page, encoding="utf-8")
    return out


def open_page(logbook) -> int:
    """Open the page of the last entry on this machine, or say its path when there is no screen."""
    page = Path(logbook).parent / PAGE
    if not page.is_file():
        print(f"no page yet: {page} is made when an entry is written", file=sys.stderr)
        return 1
    why = no_display()
    if why:
        print(f"HTML: {page}\nnot opened: {why}. Copy it to a machine with a screen (scp) "
              f"and open it there.")
        return 0
    webbrowser.open(page.resolve().as_uri())
    print(f"opened: {page}")
    return 0


def vpishi(logbook, entry, sledvashto=None, staro=None):
    """The name before 3.3.0, kept for scripts outside this repository that call it."""
    return write_entry(logbook, entry, next_line=sledvashto, old_line=staro)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("logbook")
    parser.add_argument("entry", nargs="?", help="file holding the entry, or - for stdin")
    parser.add_argument("--next", "--sledvashto", dest="next_line", help="the new pointer line, in full")
    parser.add_argument("--old", "--staro", dest="old_line", help="the old pointer line, verbatim")
    parser.add_argument("--title", help="build the heading from the clock: '## <now> — TITLE'; "
                                        "the entry is then the body only")
    parser.add_argument("--open", action="store_true",
                        help=f"open {PAGE} of the last entry here (with no display: say its path)")
    args = parser.parse_args()
    if args.entry is None:
        if not args.open:
            parser.error("an entry file (or -) is needed, unless only --open is asked")
        raise SystemExit(open_page(args.logbook))
    entry = sys.stdin.read() if args.entry == "-" else Path(args.entry).read_text(encoding="utf-8")
    write_entry(args.logbook, entry, args.next_line, args.old_line, title=args.title)
    if args.open:
        raise SystemExit(open_page(args.logbook))


if __name__ == "__main__":
    main()
