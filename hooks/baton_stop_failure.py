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
    return 0


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
        # do. Said on stderr with exit 0, as the other hooks and run.sh do.
        print(f"Baton: {Path(__file__).name} could not load _baton.py beside it; "
              "the hook did not run.", file=sys.stderr)
        sys.exit(0)
    _start()
    try:
        code = main()
    except Exception as exc:
        _beat(exc)
        sys.exit(0)
    _beat()
    sys.exit(code)
