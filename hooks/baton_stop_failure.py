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
import os
import re
import sys
from datetime import datetime
from pathlib import Path


def _turn(event: str, session: object, extra: str = "") -> None:
    """One line in `baton.turns/<session>` per run: the time, the event and `extra` (row 49). The
    doctor asks of it, per session, whether the last activity was followed by a Stop or a
    StopFailure. Never raises."""
    try:
        sid = re.sub(r"[^\w-]", "", str(session or ""))[:80]
        if not sid:
            return
        data = os.environ.get("CLAUDE_PLUGIN_DATA")
        folder = (Path(data) if data else Path(__file__).resolve().parent) / "baton.turns"
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / sid, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat()} {event} {extra}".rstrip() + "\n")
    except Exception:
        pass


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


def _start() -> None:
    """Mark that this run began: `baton.beat.<hook>.started.<pid>`, as the other hooks do (row 41).
    Never raises."""
    try:
        data = os.environ.get("CLAUDE_PLUGIN_DATA")
        folder = Path(data) if data else Path(__file__).resolve().parent
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"baton.beat.{Path(__file__).stem}.started.{os.getpid()}").write_text(
            datetime.now().isoformat(), "utf-8")
    except Exception:
        pass


def _clear_starts(folder: Path) -> None:
    """This run's start mark, and those of runs that are gone: this finish is newer than them."""
    import time
    for mark in folder.glob(f"baton.beat.{Path(__file__).stem}.started.*"):
        try:
            pid = mark.name.rsplit(".", 1)[1]
            gone = pid == str(os.getpid()) or time.time() - mark.stat().st_mtime > 120
            if not gone and os.name != "nt":      # on Windows os.kill(pid, 0) is not a probe
                try:
                    os.kill(int(pid), 0)
                except ProcessLookupError:
                    gone = True
            if gone:
                mark.unlink()
        except (OSError, ValueError):
            continue


def _beat(crash: BaseException | None = None) -> None:
    """When this hook last finished, or `baton.beat.<hook>.crashed` when it raised -- the same
    files as the other hooks (rows 36, 41). Never raises."""
    try:
        data = os.environ.get("CLAUDE_PLUGIN_DATA")
        folder = Path(data) if data else Path(__file__).resolve().parent
        folder.mkdir(parents=True, exist_ok=True)
        beat, now = folder / f"baton.beat.{Path(__file__).stem}", datetime.now()
        if crash is None:
            beat.write_text(now.isoformat(), "utf-8")
        else:
            beat.with_name(beat.name + ".crashed").write_text(
                f"{now.isoformat()} {type(crash).__name__}", "utf-8")
        _clear_starts(folder)
    except Exception:
        pass


if __name__ == "__main__":
    _start()
    try:
        code = main()
    except Exception as exc:
        _beat(exc)
        sys.exit(0)
    _beat()
    sys.exit(code)
