#!/usr/bin/env python3
"""Is Baton running here, or only installed? When each hook last ran.

    python3 tools/baton_doctor.py

Each hook leaves one small file when it runs (`baton.beat.<hook>`, since v3.12.0): in the
plugin's data folder (${CLAUDE_PLUGIN_DATA}, which /baton-doctor passes in), or next to the
hooks of a script install. A plugin can be installed and enabled and still never run -- no
Python, no Git Bash on Windows -- and nothing on the screen says so. Reads only; sends nothing.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

HOOKS = (
    ("baton_session_start", "SessionStart", "at the start of every session"),
    ("baton_prompt", "UserPromptSubmit", "on every message"),
    ("baton_stop", "Stop", "at the end of every turn"),
    ("baton_batch", "PostToolBatch", "after the agent's tool calls"),
)


def folder() -> Path:
    """The plugin's data folder when it is passed in; else the script install's hooks; else
    any plugin data folder of Baton's that holds heartbeats -- so a skill whose
    ${CLAUDE_PLUGIN_DATA} arrived empty does not tell a working plugin it is not running."""
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if data:
        return Path(data)
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    script = claude / "baton" / "hooks"
    if any(script.glob("baton.beat.*")):
        return script
    beating = [d for d in (claude / "plugins" / "data").glob("baton-*") if any(d.glob("baton.beat.*"))]
    if beating:
        return max(beating, key=lambda d: max(f.stat().st_mtime for f in d.glob("baton.beat.*")))
    return script


def last_run(where: Path, stem: str) -> datetime | None:
    try:
        return datetime.fromisoformat((where / f"baton.beat.{stem}").read_text("utf-8").strip())
    except (OSError, ValueError):
        return None


def ago(when: datetime, now: datetime) -> str:
    sec = int((now - when).total_seconds())
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if sec >= size:
            n = sec // size
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


def main() -> int:
    where, now = folder(), datetime.now()
    print(f"Baton doctor -- heartbeats in {where}\n")
    seen = {stem: last_run(where, stem) for stem, _, _ in HOOKS}
    started = seen["baton_session_start"] is not None
    for stem, event, when in HOOKS:
        t = seen[stem]
        if t:
            mark, state = "✅", f"last ran {t:%Y-%m-%d %H:%M} ({ago(t, now)})"
        elif started:
            # SessionStart ran, so the hooks work; this one has not had its moment yet.
            mark, state = "⏳", "not yet"
        else:
            mark, state = "❌", "NEVER RAN"
        print(f"  {mark} {event:<17} {state}   -- runs {when}")
    print()
    if not any(seen.values()):
        print("🔴 Installed but not running: no Baton hook has left a heartbeat here.\n"
              "   Check that Python 3.8+ runs (`python3 --version`); on Windows, that Git for\n"
              "   Windows is installed (`where bash`). A hook from before v3.12.0 leaves no\n"
              "   heartbeat: start a new session first, then ask again.")
        return 1
    if not seen["baton_session_start"]:
        print("🔴 SessionStart has never run here: the board and the rules are not reaching the "
              "agent.")
        return 1
    print("✅ Running. A hook marked ⏳ has not had its moment yet (Stop needs a finished\n"
          "   turn, PostToolBatch a tool call). If it is still ⏳ after a turn with a tool call,\n"
          "   it is failing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
