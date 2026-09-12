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
DATED_HEADING = re.compile(
    r"^\d{4}-\d\d-\d\d(?:[ T]\d\d:\d\d)?\s*[\u2014\u2013-]\s*(?P<title>.+)$"
)


def config() -> tuple[Path, str]:
    """Task root and logbook name: env var, then baton.local.json next to this file,
    then the defaults. The local file lets the hook command stay a plain
    `python "hook.py"` that runs under any shell, with no env prefix."""
    cfg = {}
    try:
        cfg = json.loads((Path(__file__).with_name("baton.local.json")).read_text("utf-8"))
    except Exception:
        cfg = {}
    home = os.environ.get("BATON_HOME") or cfg.get("home") or str(Path.home() / "tasks")
    logbook = os.environ.get("BATON_LOGBOOK") or cfg.get("logbook") or "LOGBOOK.md"
    return Path(home).expanduser(), logbook


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


def describe(folder: Path, name: str) -> str:
    logbook = folder / name
    if not logbook.is_file():
        return f"- {folder.name} — NO {name} (nothing was ever recorded here)"
    when = datetime.fromtimestamp(logbook.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    title = first_entry_title(logbook)
    return f"- {folder.name} — last entry {when}" + (f": {title}" if title else "")


def main() -> int:
    root, name = config()
    if not root.is_dir():
        return 0

    folders = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    if not folders:
        return 0

    folders.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    listed = [describe(p, name) for p in folders[:MAX_TASKS]]
    more = len(folders) - len(listed)

    context = (
        f"Baton — task folders in {root}, most recently touched first:\n"
        + "\n".join(listed)
        + (f"\n- ...and {more} more" if more > 0 else "")
        + f"\n\nBefore working on any of these, read its {name} first — it is the only "
        "record of what previous sessions did. When you finish a session of work on a "
        f"task, prepend an entry to that task's {name}."
    )

    json.dump(
        {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}},
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # A hook must never break the session it is trying to help.
        sys.exit(0)
