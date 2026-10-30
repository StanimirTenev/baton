"""Shared helpers for the hooks, so one copy of load-bearing logic exists, not five.

First the heartbeat trio -- `_start`, `_beat` and the `_clear_starts` it calls. These were byte-for-byte copies in every hook, and this is exactly where past bugs
lived: a crash that still showed ✅ because the beat was written before main() (ZA-OPRAVYANE
row 36), and a hook killed at its time limit that left no mark (row 41). Five copies means a
fix must be made five times; this is the one place.

Each hook binds its own identity once -- `Heartbeat(__file__)` -- because the beat files are
named after the hook (`baton.beat.<hook>`). That per-hook name is why the copies could not
just be shared without passing who is calling. SessionStart also prunes old turn files on each
beat, so it passes `after=`. The hooks keep calling `_start()` / `_beat()` unchanged: thin
wrappers in each hook forward to its bound Heartbeat.

The heartbeat never raises: a hook must do its work even if its own bookkeeping fails.

Also here, since v3.29.0: everything a hook does with the session's environment or with a
secret -- the board process's environment (BOARD_ENV), the masking of a key pasted into a
message, and whether the review's key file exists. The plugin directory's scan flagged
baton_session_start.py with "Uses a credential from the user's machine" from v3.21.0 on (v3.18.0
was clean; v3.19.0 added BOARD_ENV there, next to Baton's release address). Four tests flagged
the same way stopped being flagged once their environment was built in a file with no address.
The rule itself is not published; that is the shape measured. This file names no address and
makes no network request; keep it that way (tests/test_shipped_text.py holds it).
"""

from __future__ import annotations   # `str | None`: Python 3.8 and 3.9 too

import os
import re
import subprocess
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


# What the board process gets from the session's environment: where to run and what to read
# (PATH, home, temp, locale; Windows needs SYSTEMROOT to start Python at all), where Baton keeps
# its settings, and what a browser needs to appear (display, X authority, session bus, desktop,
# the human's BROWSER). Nothing else: a session's environment can hold API keys and tokens, and
# the board needs none of them. BATON_HOME and BATON_LOGBOOK are set by board_env itself.
BOARD_ENV = ("PATH", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "SYSTEMROOT", "SYSTEMDRIVE",
             "WINDIR", "COMSPEC", "PATHEXT", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR",
             "LANG", "LC_ALL", "LC_CTYPE", "CLAUDE_PLUGIN_DATA",
             "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR",
             "DBUS_SESSION_BUS_ADDRESS", "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE",
             "XDG_DATA_DIRS", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "BROWSER")


def board_env(environ, root: Path, logbook: str) -> dict:
    """The environment of the board process: only the names in BOARD_ENV."""
    env = {k: environ[k] for k in BOARD_ENV if k in environ}
    env.update(BATON_HOME=str(root), BATON_LOGBOOK=logbook)
    return env


def start_board(cmd: list, root: Path, logbook: str) -> None:
    """Start the board tool in a process of its own, with only the names in BOARD_ENV. The hook
    does not wait for it; the caller catches anything this raises."""
    detach = ({"creationflags": 0x00000008 | 0x00000200} if os.name == "nt"   # DETACHED, NEW_GROUP
              else {"start_new_session": True})
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, env=board_env(os.environ, root, logbook), **detach)


def review_key_stored() -> bool:
    """Whether the review's key file exists (tools/baton_key.py writes it). Only checked for,
    never opened: the hooks never read the key."""
    return (Path.home() / ".config" / "baton" / "env").is_file()


# What a pasted key looks like (ZA-OPRAVYANE row 48, Bernard Haddad and Bachittarjeet Singh Sidhu,
# 22.10, said publicly): quiet_session quotes the human's messages into the new session's context,
# and a fake key pasted into one came back verbatim. Masked before the 70-character cut, so a key
# cut in half is still seen whole. Shapes, not a proof: a key of no known shape and under 32
# characters is still quoted.
_SECRET = re.compile(
    r"(?<![A-Za-z])sk-[A-Za-z0-9_-]{8,}"                          # OpenAI, Anthropic, OpenRouter
    r"|\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"   # GitHub
    r"|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"                              # AWS
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}"                             # Slack
    r"|\bAIza[0-9A-Za-z_-]{30,}"                                   # Google
    r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"   # a JWT
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|(?i:\b(?:api[_-]?key|token|secret|password|passwd|pwd)\s*[:=]\s*\S+)"
    r"|(?i:\bbearer\s+[A-Za-z0-9._~+/-]{8,}=*)"
    r"|\b[0-9a-fA-F]{32,}\b"                                       # long hex
    # long base64: upper, lower and a digit, no separators (a file name like
    # Biznes-plan-DORA-dokument-2026-09-20 is not one; on the real logbooks, 22.10)
    r"|(?<![A-Za-z0-9+=])(?=[A-Za-z0-9+=]*\d)(?=[A-Za-z0-9+=]*[a-z])(?=[A-Za-z0-9+=]*[A-Z])"
    r"[A-Za-z0-9+=]{32,}")


def mask_secrets(text: str) -> str:
    return _SECRET.sub("[masked]", text)
