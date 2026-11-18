#!/usr/bin/env python3
"""Baton -- StopFailure hook: a beat for a turn that ended on an API error.

Claude Code runs StopFailure instead of Stop "when the turn ends due to an API error" -- rate_limit,
overloaded, server_error and the rest (code.claude.com/docs/en/hooks, read 23.10.2026). Without it
such a turn left no beat and looked like a Stop that did not run (ZA-OPRAVYANE row 90). This hook
only records it: the time, the session and the error type, for /baton-doctor. Claude Code ignores
its output and exit code, and it prints nothing.
"""
from __future__ import annotations   # Python 3.8 and 3.9 too

import json
import re
import sys
import importlib.util
from pathlib import Path


def _turn(event: str, session: object, extra: str = "") -> None:
    """One line in `baton.turns/<session>`: `turn` in hooks/_baton.py. Never raises."""
    if _baton is not None:
        _baton.turn(__file__, event, session, extra)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except Exception:
        return 0
    if not isinstance(payload, dict):     # `[]`, `null`: no payload, not a crash (row 67)
        return 0
    # `error` is the documented field; a payload without it is still a turn that failed.
    error = re.sub(r"[^\w]", "", str(payload.get("error") or ""))[:40] or "unknown"
    _turn("StopFailure", payload.get("session_id"), error)
    try:
        stub(payload, error)
    except Exception:
        pass                  # the beat is written; a stub that cannot be is no reason to fail
    return 0


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def stub(payload: dict, error: str) -> Path | None:
    """The stub entry for row 186; the logbook written, or None. Claude Code's transcript only:
    the turn is read from it (Codex and Gemini have no StopFailure)."""
    transcript = payload.get("transcript_path")
    if not isinstance(transcript, str) or not transcript or _baton.host(payload) not in (
            "claude", "unknown"):
        return None
    stop = _module(Path(__file__).with_name("baton_stop.py"), "baton_stop")
    root, name = stop.config()
    found = stop.turn_task(root, transcript) if root.is_dir() else None
    if found is None:
        return None
    folder, files = found
    book = folder / name
    tool = stop._ss().entry_tool()
    if not book.is_file() or tool is None:
        return None           # no logbook to add to, or no tool to add with: nothing is made
    body = (f"### What happened\nThe turn ended on an API error ({error}) before an entry was "
            "written. Written by Baton's StopFailure hook, not by the agent.\n\n"
            "### Files written in that turn\n"
            + ("\n".join(f"- {f}" for f in files) if files else "none (shell or other calls only)")
            + "\n\n### Still open\nThe entry for this work is still owed; Stop asks for it.\n")
    top = stop.top_entry(book.read_text("utf-8-sig"))
    if top is not None and top[1].strip() == body.strip():
        return None           # a spent quota fails every retry: one stub says it
    # Not the entry for the work: the recorded time stays, so the work still counts as unrecorded.
    path = stop._bodies_path()
    try:
        bodies = json.loads(path.read_text("utf-8"))
    except Exception:
        bodies = {}
    recorded = stop.recorded_time(folder, book, bodies)
    entry = _module(tool, "baton_entry")
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        entry.write_entry(str(book), body, title=f"turn ended on {error}")
    text = stop._body(book.read_text("utf-8-sig"))
    import hashlib
    bodies[str(folder)] = [hashlib.sha1(text.encode("utf-8")).hexdigest(), recorded,
                           stop._entries(text)]
    try:
        path.write_text(json.dumps(bodies, ensure_ascii=False), "utf-8")
    except OSError:
        pass
    return book


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







if __name__ == "__main__":
    if _baton is None:
        # The turn line is written by _baton.py, so without it there is nothing this hook can
        # do. Said on stderr with exit 1, as the other hooks do: shown, never a block.
        print(f"Baton: {Path(__file__).name} could not load _baton.py beside it; "
              "the hook did not run.", file=sys.stderr)
        sys.exit(1)
    _start()
    try:
        code = main()
    except Exception as exc:
        _beat(exc)
        sys.exit(0)
    _beat()
    sys.exit(code)
