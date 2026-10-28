"""Shared helpers for the hooks, so one copy of load-bearing logic exists, not five.

Only the heartbeat trio lives here for now -- `_start`, `_beat` and the `_clear_starts` it
calls. These were byte-for-byte copies in every hook, and this is exactly where past bugs
lived: a crash that still showed ✅ because the beat was written before main() (ZA-OPRAVYANE
row 36), and a hook killed at its time limit that left no mark (row 41). Five copies means a
fix must be made five times; this is the one place.

Each hook binds its own identity once -- `Heartbeat(__file__)` -- because the beat files are
named after the hook (`baton.beat.<hook>`). That per-hook name is why the copies could not
just be shared without passing who is calling. SessionStart also prunes old turn files on each
beat, so it passes `after=`. The hooks keep calling `_start()` / `_beat()` unchanged: thin
wrappers in each hook forward to its bound Heartbeat.

Nothing here raises: a hook must do its work even if its own bookkeeping fails.
"""

from __future__ import annotations   # `str | None`: Python 3.8 and 3.9 too

import os
import time
from datetime import datetime
from pathlib import Path


class Heartbeat:
    """The run-marker files for one hook, bound to that hook's file and name."""

    def __init__(self, hookfile: str, after=None) -> None:
        self._file = Path(hookfile)
        self._stem = self._file.stem
        self._after = after            # optional callable(folder): SessionStart's turn-pruning

    def _folder(self) -> Path:
        """Where the state files live: ${CLAUDE_PLUGIN_DATA} if set (survives plugin updates),
        else next to the hook, as install.sh lays it out."""
        data = os.environ.get("CLAUDE_PLUGIN_DATA")
        return Path(data) if data else self._file.resolve().parent

    def start(self) -> None:
        """Mark that this run began: `baton.beat.<hook>.started.<pid>`, holding the time. Removed
        when the run finishes or crashes (in `beat`). A hook killed at its time limit -- SIGTERM,
        then SIGKILL -- writes neither file of `beat`, and the doctor showed the last finish as ✅
        (ZA-OPRAVYANE row 41, 22.10); a mark left behind is that run. One per pid: two sessions
        can run the same hook at once, and one still running is not one killed. Never raises."""
        try:
            folder = self._folder()
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"baton.beat.{self._stem}.started.{os.getpid()}").write_text(
                datetime.now().isoformat(), "utf-8")
        except Exception:
            pass

    def beat(self, crash: BaseException | None = None) -> None:
        """When this hook last FINISHED, for /baton-doctor: a plugin can be installed and enabled
        and still never run (no Python, no Git Bash on Windows), and nothing on the screen says so.
        One small file per hook, next to the other state. A run that raised leaves
        `baton.beat.<hook>.crashed` instead: the time and the exception's class -- no message, no
        path. Until v3.20.0 the beat was written before main() ran, so a crash still showed ✅
        (ZA-OPRAVYANE row 36, Pawan Singh Rathore, 22.10). Never raises."""
        try:
            folder = self._folder()
            folder.mkdir(parents=True, exist_ok=True)
            beat, now = folder / f"baton.beat.{self._stem}", datetime.now()
            # To the microsecond: a crash and a finish in the same second still have an order.
            if crash is None:
                beat.write_text(now.isoformat(), "utf-8")
            else:
                beat.with_name(beat.name + ".crashed").write_text(
                    f"{now.isoformat()} {type(crash).__name__}", "utf-8")
            self._clear_starts(folder)
            if self._after is not None:
                self._after(folder)
        except Exception:
            pass

    def _clear_starts(self, folder: Path) -> None:
        """This run's start mark, and those of runs that are gone: this finish is newer than them."""
        for mark in folder.glob(f"baton.beat.{self._stem}.started.*"):
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
