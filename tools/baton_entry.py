#!/usr/bin/env python3
"""Prepend an entry to a logbook without corrupting it.

    python3 tools/baton_entry.py <logbook> <entry-file> [--next NEW --old OLD]

Or from Python, which is how an agent uses it:

    from baton_entry import vpishi
    vpishi("<path>/LOGBOOK.md", "<the entry>", sledvashto="<new line>", staro="<old, verbatim>")

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

**Half a pointer replacement.** `if sledvashto and staro:` means passing only the
new value is skipped in silence: the entry lands, the pointer keeps its old text,
and nothing says so. Silence is worse than refusal, because nobody looks twice.
Both or neither, or it fails.

**An hour ahead of the clock.** Entries were written with times hours ahead of the
system clock, because the hour was typed from memory rather than read from the
machine. This one only warns. A few hours can be a timezone, and a helper that
refuses a write on a guess gets worked around instead of fixed.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

HEADING = re.compile(r'^## (\d{4}-\d{2}-\d{2})(?: (\d{2}):(\d{2}))?')
AHEAD_MINUTES = 15       # below this, say nothing: clocks and timezones drift


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
            f"{match.group(1)} {match.group(2)}:{match.group(3)}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    minutes = (stamp - datetime.now()).total_seconds() / 60
    if minutes <= AHEAD_MINUTES:
        return None
    return (f"⚠️ heading is {minutes / 60:.1f}h AHEAD of the system clock "
            f"({datetime.now():%Y-%m-%d %H:%M}). Read the hour from the machine.")


def vpishi(path, entry: str, sledvashto: str | None = None,
           staro: str | None = None) -> None:
    """Prepend `entry`, optionally replacing the header's pointer line.

    `staro` is the old line verbatim, so a pointer that has already moved is a
    loud failure rather than a silent duplicate.
    """
    file = Path(path)
    text = file.read_text(encoding="utf-8")

    # 🔴 Three defects from an external review of v2.14.0, all here:
    #   * the file was written BEFORE these checks ran, so a rejected entry was
    #     already on disk when the rejection was printed;
    #   * `staro` was looked for in the whole file and replaced at the first hit, so a
    #     pointer surviving only in an old entry got rewritten -- editing the record,
    #     which is never edited -- while the header stayed as it was;
    #   * `assert` is stripped by `python -O`, so every barrier here vanished under a
    #     flag nobody would think to mention.
    # Build in memory, validate, then replace atomically; and raise, do not assert.

    # Half a replacement is worse than none: it keeps the old pointer and says nothing.
    if bool(sledvashto) != bool(staro):
        raise ValueError(
            "pass BOTH `sledvashto` and `staro`, or neither. "
            f"Got sledvashto={'yes' if sledvashto else 'no'}, "
            f"staro={'yes' if staro else 'no'}")
    if sledvashto:
        head_end = text.find("\n---", 3) + 4 if text.startswith("---") else 0
        header = text[:head_end]
        hits = header.count(staro)
        if hits != 1:
            where = "nowhere in the front matter" if hits == 0 else f"{hits} times there"
            raise ValueError(
                f"the old pointer line must appear exactly once in the front matter; "
                f"found it {where}. A logbook entry is a record and is never edited, so "
                f"a match further down the file is refused rather than rewritten.")
        text = header.replace(staro, sledvashto, 1) + text[head_end:]

    first = re.search(r'^## \d{4}-', text, re.M)
    if not first:
        raise ValueError("no dated entry to insert in front of")
    text = text[:first.start()] + entry.strip() + "\n\n" + text[first.start():]

    lines = text.split("\n")
    if not (lines[0] == "---" and "---" in lines[1:12]):
        raise ValueError("the front matter broke")
    # The `^---##` case is covered by the general check below -- `\S` matches the
    # dash. A separate assert for it survived every mutation, which means no test
    # pinned it, so it is gone rather than kept as decoration.
    glued = re.findall(r'\S(## \d{4}-\d{2}-\d{2}[^\n]{0,40})', _without_code(text))
    if glued:
        raise ValueError(
            f"heading glued mid-file, invisible to a heading read: {glued[:3]}")

    tmp = file.with_suffix(file.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(file)               # atomic: never a half-written logbook

    print(f"written: {path}")
    if (note := _hours_ahead(entry)):
        print(note)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("logbook")
    parser.add_argument("entry", help="file holding the entry, or - for stdin")
    parser.add_argument("--next", "--sledvashto", dest="sledvashto", help="the new pointer line, in full")
    parser.add_argument("--old", "--staro", dest="staro", help="the old pointer line, verbatim")
    args = parser.parse_args()
    entry = sys.stdin.read() if args.entry == "-" else Path(args.entry).read_text(encoding="utf-8")
    vpishi(args.logbook, entry, args.sledvashto, args.staro)


if __name__ == "__main__":
    main()
