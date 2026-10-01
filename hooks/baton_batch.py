#!/usr/bin/env python3
"""Baton -- PostToolBatch hook: lesson L2, an empty result is a failed read.

The most frequent mistake in a month of logbooks was not a wrong command. It was the
sentence written after an empty result: "the section does not exist", "nobody records
that", "0 downloads" -- each a page that had not finished loading, a search that matched
nothing, a query that returned `[]`. Ten dated cases in one week, written down as a lesson
three times, back after each (2026-09-19..26).

The mistake comes after the tool call, so this is the one lesson where a hook that runs
after the call is in time: its note reaches the agent before the next sentence is written.
It fires only for reads (web, MCP, and shell commands that search or fetch), says one line
at most once every SHOW_EVERY_MINUTES, and counts every time the situation arose. It never
blocks anything.
"""
from __future__ import annotations   # Python 3.8 and 3.9 too

import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

SHOW_EVERY_MINUTES = 30
READ_VERBS = re.compile(
    r"\b(grep|rg|find|findstr|select-string|curl|wget|jq|gh|search|eval|text|dir|ls|"
    r"get-childitem|test-path)\b", re.I)
EMPTY = {"", "[]", "{}", '""', "''", "0", "null", "none", "(bash completed with no output)",
         "(no output)", "no matches found", "no files found"}


def _text(response) -> str:
    """What the agent saw: a string, or content blocks whose text is joined."""
    if isinstance(response, str):
        return response
    if isinstance(response, list):
        return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in response)
    if isinstance(response, dict):
        return str(response.get("stdout", response.get("text", json.dumps(response))))
    return str(response)


# An MCP tool is a read only when its own name says so. 2026-10-01, external review of
# v3.10.0: every `mcp__*` counted as a read, so `mcp__files__delete` answering `{}` raised
# L2 and counted it. A write, or a name that says neither, is left alone.
MCP_READ = {"search", "query", "get", "list", "read", "fetch", "find", "lookup", "view",
            "download", "describe", "show", "scan", "export"}
MCP_WRITE = {"create", "update", "delete", "set", "send", "label", "unlabel", "trash",
             "untrash", "mark", "unmark", "share", "copy", "move", "publish", "reply",
             "forward", "apply", "remove", "add", "write", "edit", "respond"}


def is_read(call: dict) -> bool:
    tool = str(call.get("tool_name", ""))
    if tool in ("WebFetch", "WebSearch", "Grep", "Glob"):
        return True
    if tool.startswith("mcp__"):
        words = set(re.split(r"[_\-]+", tool.rsplit("__", 1)[-1].lower()))
        return bool(words & MCP_READ) and not words & MCP_WRITE
    if tool in ("Bash", "PowerShell"):
        return bool(READ_VERBS.search(str((call.get("tool_input") or {}).get("command", ""))))
    return False


def is_empty(call: dict) -> bool:
    text = _text(call.get("tool_response")).strip().strip("`").strip()
    return text.lower() in EMPTY


def _ss():
    spec = importlib.util.spec_from_file_location(
        "baton_session_start", Path(__file__).with_name("baton_session_start.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    empties = [c for c in payload.get("tool_calls") or [] if is_read(c) and is_empty(c)]
    if not empties:
        return 0
    try:
        ss = _ss()
        if ss.installed_twice():
            return 0
        now = datetime.now()
        state = ss.lessons_load()
        for _ in empties:
            rec = ss.lesson_event(state, "L2", "fired", now)
        shown = rec.get("last_shown", "")
        if shown and shown > (now - timedelta(minutes=SHOW_EVERY_MINUTES)).isoformat(timespec="minutes"):
            ss.lessons_save(state)
            return 0
        rec["last_shown"] = now.isoformat(timespec="minutes")
        ss.lessons_save(state)
        tools = ", ".join(sorted({str(c.get("tool_name")) for c in empties}))
        note = f"Baton, lesson L2 -- an empty result just came back ({tools}). {ss.LESSONS['L2']}"
    except Exception:
        return 0              # a lesson that cannot count must not cost the session
    json.dump({"hookSpecificOutput": {"hookEventName": "PostToolBatch",
                                      "additionalContext": note}}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
