#!/usr/bin/env python3
"""Baton Stop hook.

Catches the failure Baton exists to prevent: work happened inside a task folder and
no logbook entry was written for it.

A folder is "unrecorded" when it holds a file newer than its own logbook. That is a
narrow test on purpose — a session that touched no task folder is never interrupted.

When something is unrecorded the turn is handed back to the agent with a note naming the
folder. `stop_hook_active` is honoured, so this can block at most once per turn and can
never trap a session in a loop.
"""
import fnmatch
import json
import os
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache"}
GRACE_SECONDS = 90  # a file saved moments ago is still being worked on


def ignore_patterns(folder: Path) -> list[str]:
    """Globs from a .batonignore in the task folder (gitignore-style, one per line,
    '#' comments). Use it for files that legitimately change without needing a logbook
    entry — a live transcript, a rotating log, generated output."""
    try:
        lines = (folder / ".batonignore").read_text("utf-8").splitlines()
    except OSError:
        return []
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def is_ignored(rel: str, name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(name, p) for p in patterns)


def config() -> tuple[Path, str]:
    """Task root and logbook name: env var, then baton.local.json next to this file,
    then the defaults — the same resolution the SessionStart hook uses."""
    cfg = {}
    try:
        cfg = json.loads((Path(__file__).with_name("baton.local.json")).read_text("utf-8"))
    except Exception:
        cfg = {}
    home = os.environ.get("BATON_HOME") or cfg.get("home") or str(Path.home() / "tasks")
    logbook = os.environ.get("BATON_LOGBOOK") or cfg.get("logbook") or "LOGBOOK.md"
    return Path(home).expanduser(), logbook


def newest_work(folder: Path, logbook: str) -> tuple[float, str]:
    """Newest work-file mtime in the folder, and that file's name. Skips the logbook,
    dotfiles, SKIP_DIRS, and anything matched by the folder's .batonignore."""
    patterns = ignore_patterns(folder)
    newest, newest_name = 0.0, ""
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name == logbook or name.startswith("."):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), folder)
            if is_ignored(rel, name, patterns):
                continue
            try:
                m = (Path(dirpath) / name).stat().st_mtime
            except OSError:
                continue
            if m > newest:
                newest, newest_name = m, rel
    return newest, newest_name


def unrecorded(root: Path, name: str) -> list[str]:
    out = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        logbook = folder / name
        work, newest_name = newest_work(folder, name)
        if work == 0.0:
            continue
        logged = logbook.stat().st_mtime if logbook.is_file() else 0.0
        if work > logged + GRACE_SECONDS:
            if logbook.is_file():
                out.append(f"{folder.name} (newest: {newest_name})")
            else:
                out.append(f"{folder.name} (no {name} at all; newest: {newest_name})")
    return out


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    # Already handed the turn back once — do not do it again.
    if payload.get("stop_hook_active"):
        return 0

    root, name = config()
    if not root.is_dir():
        return 0

    stale = unrecorded(root, name)
    if not stale:
        return 0

    listed = "\n".join(f"  - {folder}" for folder in stale)
    json.dump(
        {
            "decision": "block",
            "reason": (
                f"Baton: these task folders hold work newer than their {name}:\n"
                f"{listed}\n\n"
                f"Prepend an entry to each one's {name} before finishing — what was "
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
