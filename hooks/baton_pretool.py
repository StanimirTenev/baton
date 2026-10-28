#!/usr/bin/env python3
"""Baton -- PreToolUse hook: lesson L1, before the write, not only after it.

L1 (the hour in a logbook heading is read from the clock, never typed) is caught at Stop, once
the entry is already on disk. This surfaces it one step earlier: when a Write or Edit is about
to put a `## YYYY-MM-DD HH:MM --` heading into a logbook by hand, it says -- before the write --
to use tools/baton_entry.py, which stamps the time itself. It is the first lesson keyed to the
action that is about to happen, not to one already made.

It never blocks and never auto-approves: it only adds context. A PreToolUse hook that returns
`permissionDecision` would decide whether the tool runs; this one must not -- it would be
auto-approving every write. Only `additionalContext` reaches the model (plain stdout from a
PreToolUse hook goes to debug logs), so that is all it emits. A hook that cannot be sure says
nothing and costs the session nothing.
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


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0
    tool = event.get("tool_name") or ""
    if tool not in WRITERS:
        return 0
    ti = event.get("tool_input") or {}
    path = ti.get("file_path") or ""
    if not path:
        return 0

    try:
        ss = _ss()
        _, logbook = ss.config()
    except Exception:
        return 0
    if os.path.basename(path) != logbook:
        return 0                      # only a logbook heading is read from the clock

    if not _TYPED_HOUR.search(_written_text(tool, ti)):
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
    _start()
    try:
        code = main()
    except BaseException as exc:      # noqa: BLE001 -- a hook must not crash the tool call
        _beat(exc)
        sys.exit(0)
    _beat()
    sys.exit(code)
