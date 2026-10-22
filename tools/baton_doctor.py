#!/usr/bin/env python3
"""Is Baton running here, or only installed? When each hook last ran.

    python3 tools/baton_doctor.py

Each hook leaves one small file when it finishes (`baton.beat.<hook>`, since v3.12.0; written
before the hook's work until v3.20.0), and `baton.beat.<hook>.crashed` -- the time and the
exception's class -- when it raised: in the
plugin's data folder (${CLAUDE_PLUGIN_DATA}, which /baton-doctor passes in), or next to the
hooks of a script install. A plugin can be installed and enabled and still never run -- no
Python, no Git Bash on Windows -- and nothing on the screen says so. Reads only; sends nothing.
"""
from __future__ import annotations

import json
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


def crashed(where: Path, stem: str) -> tuple[datetime, str] | None:
    """When the hook last raised, and the exception's class (since v3.20.0)."""
    try:
        when, _, kind = (where / f"baton.beat.{stem}.crashed").read_text("utf-8").strip().partition(" ")
        return datetime.fromisoformat(when), kind or "unknown error"
    except (OSError, ValueError):
        return None


def ago(when: datetime, now: datetime) -> str:
    sec = int((now - when).total_seconds())
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if sec >= size:
            n = sec // size
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


def handback(where: Path) -> str | None:
    """Does Stop's hand-back do any work? The three numbers Stop keeps with the lessons."""
    path = Path(os.environ.get("BATON_LESSONS_STATE") or where / "baton.lessons.json")
    try:
        rec = json.loads(path.read_text("utf-8")).get("handback") or {}
    except (OSError, ValueError, AttributeError):
        return None
    if not rec:
        return None
    return (f"Logbook entries since {rec.get('since', '?')}: written unasked: "
            f"{rec.get('unasked', 0)}; handed back: {rec.get('handed_back', 0)} -- recorded on "
            f"the second try: {rec.get('recorded_after', 0)}, passed without one: "
            f"{rec.get('passed', 0)}.\n   (Counted by folder. \"Passed\" is a turn Stop asked about "
            "and let through, since it never asks twice.)")


def lesson_l2(where: Path) -> str | None:
    """Does the L2 note change what comes next? Counted since v3.20.0 (ZA-OPRAVYANE row 40)."""
    path = Path(os.environ.get("BATON_LESSONS_STATE") or where / "baton.lessons.json")
    try:
        rec = json.loads(path.read_text("utf-8")).get("L2") or {}
    except (OSError, ValueError, AttributeError):
        return None
    if not rec:
        return None
    after = rec.get("checked_after", 0) + rec.get("no_check_after", 0)
    return (f"Lesson L2 (a failed read) since {rec.get('since', '?')}: fired "
            f"{rec.get('fired', 0)}, shown {rec.get('shown', 0)}; followed by a check: "
            f"{rec.get('checked_after', 0)} of {after}.\n   (A proxy, not proof: \"a check\" is a "
            "read in the agent's next tool calls; it may have been planned anyway.)")


def main() -> int:
    where, now = folder(), datetime.now()
    print(f"Baton doctor -- heartbeats in {where}\n")
    seen = {stem: last_run(where, stem) for stem, _, _ in HOOKS}
    crashes = {stem: c for stem, _, _ in HOOKS
               for c in [crashed(where, stem)] if c and (seen[stem] is None or c[0] > seen[stem])}
    started = seen["baton_session_start"] is not None or "baton_session_start" in crashes
    for stem, event, when in HOOKS:
        t = seen[stem]
        if stem in crashes:
            c, kind = crashes[stem]
            last = f"{t:%Y-%m-%d %H:%M}" if t else "never"
            mark, state = "❌", (f"CRASHED {c:%Y-%m-%d %H:%M} ({ago(c, now)}): {kind}; "
                                 f"last finished {last}")
        elif t:
            mark, state = "✅", f"last finished {t:%Y-%m-%d %H:%M} ({ago(t, now)})"
        elif started:
            # SessionStart ran, so the hooks work; this one has not had its moment yet.
            mark, state = "⏳", "not yet"
        else:
            mark, state = "❌", "NEVER RAN"
        print(f"  {mark} {event:<17} {state}   -- runs {when}")
    print()
    counted = handback(where)
    if counted:
        print(counted + "\n")
    l2 = lesson_l2(where)
    if l2:
        print(l2 + "\n")
    if crashes:
        names = ", ".join(event for stem, event, _ in HOOKS if stem in crashes)
        print(f"🔴 Crashed on its last run: {names}. A hook never breaks the session, so it\n"
              "   exited 0 and its check did not happen. Run it by hand to see the traceback:\n"
              "   echo '{}' | python3 <the hooks folder>/<hook>.py")
        return 1
    if not any(seen.values()):     # nothing finished, and nothing crashed (said above)
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
