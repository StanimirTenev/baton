#!/usr/bin/env python3
"""Baton SessionStart hook.

Lists recently touched task folders and the date of each last logbook entry, and
injects that into the agent's context so a session never starts blind.

Prints nothing when there are no task folders, so a fresh machine stays quiet.
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

MAX_TASKS = 6


def logbook_name() -> str:
    """Name of the logbook file. Localisable: BATON_LOGBOOK=DNEVNIK.md works fine."""
    return os.environ.get("BATON_LOGBOOK") or "LOGBOOK.md"


def baton_home() -> Path:
    return Path(os.environ.get("BATON_HOME") or (Path.home() / "tasks")).expanduser()


DATED_HEADING = re.compile(r"^\d{4}-\d\d-\d\d(?:[ T]\d\d:\d\d)?\s*[\u2014\u2013-]\s*(?P<title>.+)$")


def first_entry_title(logbook: Path) -> str:
    """Title of the newest entry, without the date the heading already carries."""
    try:
        with logbook.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("## "):
                    heading = line[3:].strip()
                    match = DATED_HEADING.match(heading)
                    return match.group("title").strip() if match else heading
    except OSError:
        pass
    return ""


def describe(folder: Path) -> str:
    name = logbook_name()
    logbook = folder / name
    if not logbook.is_file():
        return f"- {folder.name} — NO {name} (nothing was ever recorded here)"
    when = datetime.fromtimestamp(logbook.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    title = first_entry_title(logbook)
    return f"- {folder.name} — last entry {when}" + (f": {title}" if title else "")


def main() -> int:
    root = baton_home()
    if not root.is_dir():
        return 0

    folders = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    if not folders:
        return 0

    folders.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    listed = [describe(p) for p in folders[:MAX_TASKS]]
    more = len(folders) - len(listed)

    context = (
        f"Baton — task folders in {root}, most recently touched first:\n"
        + "\n".join(listed)
        + (f"\n- ...and {more} more" if more > 0 else "")
        + f"\n\nBefore working on any of these, read its {logbook_name()} first — it "
        "is the only record of what previous sessions did. When you finish a session "
        f"of work on a task, prepend an entry to that task's {logbook_name()}."
    )

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # A hook must never break the session it is trying to help.
        sys.exit(0)
