#!/usr/bin/env python3
"""Baton Stop hook.

Catches the failure Baton exists to prevent: work happened inside a task folder and
no logbook entry was written for it.

A folder is "unrecorded" when it holds a file newer than its own LOGBOOK.md. That is a
narrow test on purpose — a session that touched no task folder is never interrupted.

When something is unrecorded the turn is handed back to the agent with a note naming the
folder. `stop_hook_active` is honoured, so this can block at most once per turn and can
never trap a session in a loop.
"""
import json
import os
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache"}
GRACE_SECONDS = 90  # a file saved moments ago is still being worked on


def logbook_name() -> str:
    """Name of the logbook file. Localisable: BATON_LOGBOOK=DNEVNIK.md works fine."""
    return os.environ.get("BATON_LOGBOOK") or "LOGBOOK.md"


def baton_home() -> Path:
    return Path(os.environ.get("BATON_HOME") or (Path.home() / "tasks")).expanduser()


def newest_work_mtime(folder: Path, logbook: str) -> float:
    newest = 0.0
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name == logbook or name.startswith("."):
                continue
            try:
                newest = max(newest, (Path(dirpath) / name).stat().st_mtime)
            except OSError:
                continue
    return newest


def unrecorded(root: Path) -> list[str]:
    name = logbook_name()
    out = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        logbook = folder / name
        work = newest_work_mtime(folder, name)
        if work == 0.0:
            continue
        logged = logbook.stat().st_mtime if logbook.is_file() else 0.0
        if work > logged + GRACE_SECONDS:
            out.append(folder.name if logbook.is_file() else f"{folder.name} (no {name} at all)")
    return out


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    # Already handed the turn back once — do not do it again.
    if payload.get("stop_hook_active"):
        return 0

    root = baton_home()
    if not root.is_dir():
        return 0

    stale = unrecorded(root)
    if not stale:
        return 0

    listed = "\n".join(f"  - {name}" for name in stale)
    json.dump(
        {
            "decision": "block",
            "reason": (
                f"Baton: these task folders hold work newer than their {logbook_name()}:\n"
                f"{listed}\n\n"
                f"Prepend an entry to each one's {logbook_name()} before finishing — what was "
                "asked, what was done, the result, and what is still open. Write it for "
                "the next session, which will have none of this conversation.\n\n"
                "If the change was incidental and genuinely needs no entry, say so in one "
                "line and finish."
            ),
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
