#!/usr/bin/env python3
"""Baton -- PreToolUse hook: lesson L1, before the write, not only after it.

L1 (the hour in a logbook heading is read from the clock, never typed) is caught at Stop, once
the entry is already on disk. This surfaces it one step earlier: when a Write, Edit or Bash call is about
to put a `## YYYY-MM-DD HH:MM --` heading into a logbook by hand, it says -- before the write --
to use tools/baton_entry.py, which stamps the time itself. It is the first lesson keyed to the
action that is about to happen, not to one already made.

It never blocks and never auto-approves: it only adds context. A PreToolUse hook that returns
`permissionDecision` would decide whether the tool runs; this one must not -- it would be
auto-approving every write. Only `additionalContext` reaches the model (plain stdout from a
PreToolUse hook goes to debug logs), so that is all it emits. A hook that cannot be sure says
nothing and costs the session nothing.

Since v3.32.0 it also counts calls of Baton's own skills (the Skill tool; row 134) for
/baton-doctor, and says nothing about them.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# A dated heading with a typed hour -- the thing baton_entry.py would have stamped from the clock.
_TYPED_HOUR = re.compile(
    r"^## (?:\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})[ T]\d{1,2}:\d{2}\b", re.MULTILINE)

WRITERS = {"Write", "Edit", "MultiEdit"}

# Row 139 (10.11): every heading L1 caught that the transcripts here could trace was written by a
# Bash call -- `python3 - <<'EOF'` or `sed -i` -- and none by Write or Edit, so the note never ran
# on the path the mistake takes. A Bash call that names the logbook, writes (a heredoc, a redirect,
# tee, sed -i, a .write) and holds a heading with a typed hour gets the same note. A heading built
# from a variable (`## $t`, `## {now}`) read the clock: silent.
_TYPED_ANYWHERE = re.compile(
    r"## (?:\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})[ T]\d{1,2}:\d{2}\b")
_CLOCK_HEADING = re.compile(r"## [$({]")
_WRITES = re.compile(r"<<|\btee\b|\bsed\s+(?:-\w+\s+)*-i|\.write(?:_text)?\(")


def _load_baton():
    try:
        spec = importlib.util.spec_from_file_location(
            "_baton", Path(__file__).with_name("_baton.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None          # bookkeeping must never stop the hook doing its work


_baton = _load_baton()
_HEARTBEAT = _baton.Heartbeat(__file__) if _baton else None


def _start() -> None:
    if _HEARTBEAT is not None:
        _HEARTBEAT.start()


def _beat(crash: BaseException | None = None) -> None:
    if _HEARTBEAT is not None:
        _HEARTBEAT.beat(crash)


def _ss():
    spec = importlib.util.spec_from_file_location(
        "baton_session_start", Path(__file__).with_name("baton_session_start.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _written_text(tool: str, ti: dict) -> str:
    """The text this call would put into the file."""
    if tool == "Write":
        return ti.get("content") or ""
    if tool == "Edit":
        return ti.get("new_string") or ""
    if tool == "MultiEdit":
        return "\n".join(e.get("new_string") or "" for e in ti.get("edits", []) if isinstance(e, dict))
    return ""


# Row 134 (Ivan Petrakov, 09.11): a skill that does not load fails silently, and Baton counted none
# of its own. Each call of the Skill tool for one of Baton's skills is counted with its time in the
# lessons register; /baton-doctor shows them. Another skill is not counted. When one should have
# fired and did not is a different measure, made outside the hooks (row 136).
def count_skill(name: object) -> None:
    short = str(name or "").rsplit(":", 1)[-1]
    if not re.fullmatch(r"baton-[a-z]+", short):
        return
    try:
        ss = _ss()
        state = ss.lessons_load()
        rec = state.setdefault("skills", {}).setdefault(short, {})
        rec["used"] = rec.get("used", 0) + 1
        rec["last"] = datetime.now().isoformat(timespec="minutes")
        ss.lessons_save(state)
    except Exception:
        pass                          # counting is a courtesy; never a reason to fail the call


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0
    tool = event.get("tool_name") or ""
    if tool == "Skill":
        count_skill((event.get("tool_input") or {}).get("skill"))
        return 0
    if tool not in WRITERS and tool != "Bash":
        return 0
    ti = event.get("tool_input") or {}
    path = ti.get("file_path") or ""
    command = ti.get("command") if tool == "Bash" else None
    if not path and not isinstance(command, str):
        return 0
    if command is not None and not _TYPED_ANYWHERE.search(command):
        return 0                      # every Bash call comes here: the cheap test first

    try:
        ss = _ss()
        _, logbook = ss.config()
    except Exception:
        return 0
    if command is not None:
        into = re.search(r">>?\s*[\"']?\S*" + re.escape(logbook), command)
        if (logbook not in command or not (into or _WRITES.search(command))
                or not _TYPED_ANYWHERE.search(command) or _CLOCK_HEADING.search(command)):
            return 0                  # not a write of a typed hour into a logbook
        path = logbook
    elif os.path.basename(path) != logbook:
        return 0                      # only a logbook heading is read from the clock
    elif not _TYPED_HOUR.search(_written_text(tool, ti)):
        return 0                      # no typed hour: nothing baton_entry.py would change

    try:
        state = ss.lessons_load()
        ss.lesson_event(state, "L1", "surfaced_before", datetime.now())
        ss.lessons_save(state)
    except Exception:
        pass                          # a lesson that cannot count must not cost the session

    note = (f"Baton, lesson L1 -- {ss.LESSONS['L1']} This write puts a heading with a typed hour "
            f"into {os.path.basename(path)}; add the entry with tools/baton_entry.py --title "
            f"instead, so the hour comes from the clock.")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": note,
    }}))
    return 0


if __name__ == "__main__":
    if _baton is None:
        # config() lives in _baton.py, so without it there is nothing this hook can do. Said
        # on stderr with exit 1: a non-blocking error the host shows, never a block (that is 2).
        print(f"Baton: {Path(__file__).name} could not load _baton.py beside it; "
              "the hook did not run.", file=sys.stderr)
        sys.exit(1)
    _start()
    try:
        code = main()
    except BaseException as exc:      # noqa: BLE001 -- a hook must not crash the tool call
        _beat(exc)
        sys.exit(0)
    _beat()
    sys.exit(code)
