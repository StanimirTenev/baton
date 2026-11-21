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

Also here, since the core's stage 1 (2026-11-14): `config`, where the tasks are and what the
logbook is called. It was three copies of the same code in SessionStart, Stop and the prompt
hook; each hook keeps a `config()` of its own that calls this one with its own `_local_file`.
Since stage 5: `turn`, the line each hook adds to `baton.turns/<session>` (four copies before).
Since stage 4: `words` and `alternation`, the recognised words of every language file in
hooks/lang, joined into the patterns of Stop and the prompt hook.
Since stage 7: `host`, which agent host is calling -- Claude Code, Codex, or not known. One set
of hooks serves every host; anything not recognised is treated as Claude Code.
Since stage 8: what Baton reads of Codex -- `patch_files` (the files an apply_patch names and
the lines it adds), `codex_calls` and `codex_context_tokens` (its rollout transcript). Claude
Code's transcript is still read where it always was, in Stop and the prompt hook.

Also here, since v3.35.0: the ledger (ZA-OPRAVYANE row 153, Musab Khiri, 16.11) -- one line per
logbook entry in a git repository of its own, appended by Stop, read by SessionStart and by
tools/baton_ledger.py. Local git only: nothing here pushes; the tool does, when the human runs it.

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

import hashlib
import json
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


def config(local_file) -> tuple[Path, str]:
    """Task root and logbook name, for every hook. Each comes from the first that is set: the
    BATON_* variable, the plugin's option given at enable, baton.local.json (`home`, `logbook`;
    a BOM is fine, an unreadable or broken file counts as empty), then ~/tasks and LOGBOOK.md.
    `local_file(name)` is the calling hook's: where its baton.local.json lives."""
    try:
        cfg = json.loads((local_file("baton.local.json")).read_text("utf-8-sig"))
    except Exception:
        cfg = {}
    home = (os.environ.get("BATON_HOME") or os.environ.get("CLAUDE_PLUGIN_OPTION_TASKS_FOLDER")
            or cfg.get("home") or str(Path.home() / "tasks"))
    logbook = (os.environ.get("BATON_LOGBOOK") or os.environ.get("CLAUDE_PLUGIN_OPTION_LOGBOOK")
               or cfg.get("logbook") or "LOGBOOK.md")
    return Path(home).expanduser(), logbook

def turn(hookfile: str, event: str, session: object, extra: str = "") -> None:
    """One line in `baton.turns/<session>` per run: the time, the event and `extra` (row 49). The
    doctor asks of it, per session, whether the last activity was followed by a Stop or a
    StopFailure. In ${CLAUDE_PLUGIN_DATA} if set, else beside the calling hook (`hookfile`), the
    folder SessionStart's _prune_turns reads. Never raises."""
    try:
        sid = re.sub(r"[^\w-]", "", str(session or ""))[:80]
        if not sid:
            return
        data = os.environ.get("CLAUDE_PLUGIN_DATA")
        folder = (Path(data) if data else Path(hookfile).resolve().parent) / "baton.turns"
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / sid, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat()} {event} {extra}".rstrip() + "\n")
    except Exception:
        pass


# Which host is calling, from what it sends -- never from the environment. The environment is
# inherited, so it proves nothing: Codex started from a Claude Code shell carries CLAUDE_CODE_*
# and CLAUDE_PID (the live probe of 14.11, Codex CLI 0.169.0), and Codex itself sets
# CLAUDE_PLUGIN_ROOT and CLAUDE_PLUGIN_DATA for plugin hooks (its hooks docs). What does tell them
# apart, in every payload the probe dumped: Codex's transcript is
# `sessions/YYYY/MM/DD/rollout-<YYYY-MM-DDTHH-MM-SS>-<session_id>.jsonl`, and every event but
# SessionStart carries `turn_id`, which its docs call a Codex-specific extension. Claude Code's
# transcript is `<session_id>.jsonl` and it sends no `turn_id`. `model` and `permission_mode`
# are not used: Codex sends both, and so does Claude Code (`permission_mode` on most events,
# `model` on SessionStart). Evidence for more than one host, or none, is "unknown"; every caller
# treats "unknown" exactly as "claude", so only a Codex or Gemini payload changes what a hook does.
_ROLLOUT = re.compile(r"rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-(.+)\.jsonl")
# Gemini CLI (0.68.0, read in its bundle): event names no other host uses (HookEventName; its
# Notification and SessionEnd are Claude Code's names too, so they are not evidence), and the main
# session's transcript `chats/session-<YYYY-MM-DDTHH-MM>-[<n>-]<first 8 of session_id>.jsonl`
# (chatRecordingService). Its SessionStart with no transcript yet ("") carries neither: unknown.
_GEMINI_EVENTS = frozenset({"BeforeAgent", "AfterAgent", "BeforeTool", "AfterTool", "BeforeModel",
                            "AfterModel", "BeforeToolSelection", "PreCompress"})
_GEMINI_CHAT = re.compile(r"session-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-(?:\d+-)?(.{1,8})\.jsonl")


def host(payload, environ=None) -> str:
    """"claude", "codex", "gemini" or "unknown" for one hook's stdin payload. `environ` is taken
    and not read (see above): the signature says it was considered."""
    if not isinstance(payload, dict):
        return "unknown"
    sid = str(payload.get("session_id") or "")
    name = os.path.basename(str(payload.get("transcript_path") or "").replace("\\", "/"))
    rollout = _ROLLOUT.fullmatch(name)
    codex = (isinstance(payload.get("turn_id"), str) and bool(payload["turn_id"])) or bool(
        rollout and (not sid or rollout.group(1) == sid))
    claude = bool(sid) and name == f"{sid}.jsonl"
    chat = _GEMINI_CHAT.fullmatch(name)
    event = payload.get("hook_event_name")
    gemini = (isinstance(event, str) and event in _GEMINI_EVENTS) or bool(
        chat and sid and chat.group(1) == sid[:8])
    found = [h for h, yes in (("codex", codex), ("claude", claude), ("gemini", gemini)) if yes]
    return found[0] if len(found) == 1 else "unknown"


# An apply_patch text (Codex's file edit): `*** Add File: <path>`, `*** Update File: <path>`,
# `*** Delete File: <path>`, and `*** Move to: <path>` under an Update, each followed by its hunks;
# a line the edit adds starts with `+`. The format is in Codex's apply_patch tool description.
_PATCH_FILE = re.compile(r"^\*\*\* (Add File|Update File|Delete File|Move to): (.+?)\s*$")


def patch_files(patch: str, cwd: str = "") -> list:
    """(path, added text) for each file an apply_patch text names, in order. A relative path is
    read against `cwd`, as Codex applies it. A moved file is named twice, old and new path, both
    with the lines the edit adds. Nothing that does not parse raises: an empty list."""
    out, lines = [], None
    for line in str(patch or "").splitlines():
        m = _PATCH_FILE.match(line)
        if m:
            path = os.path.expanduser(m.group(2))
            if cwd and not os.path.isabs(path):
                path = os.path.join(cwd, path)
            if m.group(1) != "Move to" or lines is None:
                lines = []
            out.append((path, lines))
        elif line.startswith("*** End Patch"):
            lines = None
        elif lines is not None and line.startswith("+"):
            lines.append(line[1:])
    return [(path, "\n".join(added)) for path, added in out]


def _epoch(stamp) -> float | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


# Codex's rollout (`$CODEX_HOME/sessions/.../rollout-*.jsonl`): one `{timestamp, ordinal, type,
# payload}` per line. Seen in the live probe of 14.11 (Codex CLI 0.169.0): the line types, and
# that tool calls are `response_item` lines of payload type `custom_tool_call` (`exec`) and
# `function_call` (`wait`), each answered by a `*_output`; the edit tool, apply_patch, did not
# appear as an item of its own -- `exec` runs JavaScript that calls the tools inside it. The
# fields read inside a payload (`name`, `input` / `arguments`, `call_id`, `cwd` of
# `turn_context`, `info.last_token_usage.input_tokens` of `token_count`) are Codex's names as its
# binary holds them, not a line the probe kept: the rollout carries account ids and was not
# saved. Codex calls the format "not a stable interface for hooks", so every reader here fails
# to None or 0, which is what Baton did before it read Codex at all.
_CODEX_CALLS = {"function_call", "custom_tool_call"}
_CODEX_OUTPUTS = {"function_call_output", "custom_tool_call_output"}


def codex_calls(transcript: str) -> dict | None:
    """What a Codex session's tool calls touched, as Stop's session_calls gives it for Claude
    Code: {"files", "texts", "cwds", "windows"}. `files`: every path an apply_patch in a call
    names (a call of its own, or inside exec's script, its newlines escaped or not); `texts`:
    each call's input, apply_patch on its own excepted, as a Write's is; `cwds`: the turn's
    working directory, for a call that runs commands; `windows`: from a call to its output,
    ten minutes when none came. None when the file cannot be read or holds no call."""
    files, texts, cwds, started, windows = set(), [], set(), {}, []
    cwd = ""
    try:
        fh = open(transcript, "rb")
    except (OSError, TypeError, ValueError):
        return None
    with fh:
        for raw in fh:
            if b'"payload"' not in raw:
                continue
            try:
                obj = json.loads(raw.decode("utf-8", "replace"))
                body = obj.get("payload")
            except (ValueError, AttributeError):
                continue
            if not isinstance(body, dict):
                continue
            if obj.get("type") == "turn_context":
                cwd = body.get("cwd") if isinstance(body.get("cwd"), str) else cwd
                continue
            if obj.get("type") != "response_item":
                continue
            kind, at, cid = body.get("type"), _epoch(obj.get("timestamp")), body.get("call_id")
            if kind in _CODEX_OUTPUTS:
                if cid in started:
                    begun = started.pop(cid)
                    windows.append((begun, at if at is not None else begun))
                continue
            if kind not in _CODEX_CALLS:
                continue
            name = str(body.get("name") or "")
            args = body.get("input") if kind == "custom_tool_call" else body.get("arguments")
            args = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
            for text in {args, args.replace("\\n", "\n")}:
                for path, _ in patch_files(text, cwd):
                    files.add(os.path.normcase(os.path.abspath(path)))
            if name == "apply_patch":
                continue
            texts.append(args)
            if cwd:
                cwds.add(os.path.normcase(os.path.abspath(cwd)))
            if at is not None and cid:
                started[cid] = at
    windows += [(t, t + 600) for t in started.values()]
    return ({"files": files, "texts": texts, "cwds": cwds, "windows": windows}
            if files or texts or windows else None)


def codex_context_tokens(transcript: str, tail_bytes: int) -> int:
    """How much context Codex's last request was sent with: `input_tokens` of the last
    `token_count` event's `last_token_usage` (cached input is part of it; Codex counts
    non-cached input as a separate figure). Only the tail is read. 0 when nothing can be."""
    try:
        path = Path(transcript)
        size = path.stat().st_size
        with path.open("rb") as f:
            f.seek(max(0, size - tail_bytes))
            tail = f.read().decode("utf-8", "replace")
    except (OSError, ValueError, TypeError):
        return 0
    for line in reversed(tail.splitlines()):
        if '"token_count"' not in line:
            continue
        try:
            body = json.loads(line)["payload"]
            if body.get("type") != "token_count":
                continue
            return int(body["info"]["last_token_usage"]["input_tokens"])
        except Exception:
            continue
    return 0


def words(lang_dir, slot: str) -> list:
    """The pattern fragments every installed language gives for `slot`, from the `words` of each
    lang_dir/<code>.json: en first, then the rest by code, each file's own order kept (an
    alternation takes the first that matches, not the longest). A file that is not a JSON object,
    a slot that is not a list, or a fragment that does not compile is skipped: one bad language
    file must not stop every hook. hooks/lang/README.md says how to add a language."""
    out = []
    try:
        files = sorted(Path(lang_dir).glob("*.json"), key=lambda f: (f.stem != "en", f.stem))
    except OSError:
        return out
    for f in files:
        try:
            got = json.loads(f.read_text("utf-8-sig")).get("words", {}).get(slot, [])
        except Exception:
            continue
        for fragment in got if isinstance(got, list) else ():
            try:
                re.compile(fragment)
            except (re.error, TypeError):
                continue
            out.append(fragment)
    return out


def alternation(fragments: list) -> str:
    """`a|b|c`; with nothing installed, a pattern that never matches. The empty one would match
    everywhere: with no lang folder, every line would read as a claim."""
    return "|".join(fragments) if fragments else "(?!)"


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


# The page server's (tools/baton_page.py, v3.43.0): the board's names, and what its buttons need --
# Claude Code's config folder for `claude plugin update`, the identity folder, a proxy and its
# certificates for the catalog's fetch, where the box listens (BATON_BOX, BATON_BOX_UDP, v3.44.0),
# and three switches the tests use. PROGRAMDATA: Windows ssh-keygen exits 255 and prints nothing without it, so the
# page could not sign or check (21.11).
PAGE_ENV = BOARD_ENV + ("PROGRAMDATA", "ALLUSERSPROFILE", "CLAUDE_CONFIG_DIR", "BATON_IDENTITY", "BATON_PAGE_IDLE", "BATON_OPENER", "BATON_BOX", "BATON_BOX_UDP",
                        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy",
                        "no_proxy", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "SSL_CERT_DIR")


def run_page(cmd: list, timeout: float = 12) -> bytes:
    """Run the page tool with only the names in PAGE_ENV and return what it printed, which is
    for the hook to read, never the hook's own output. The server it starts is detached and
    holds none of these pipes. The caller catches anything this raises."""
    env = {k: os.environ[k] for k in PAGE_ENV if k in os.environ}
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, env=env,
                          timeout=timeout).stdout


def claude_pid() -> int | None:
    """The Claude Code process this hook runs under: the nearest ancestor named `claude`, read from
    /proc (Linux). The same across /clear, a new one after a restart. None elsewhere, or not found."""
    try:
        pid = os.getpid()
        for _ in range(8):
            with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as fh:
                stat = fh.read()
            name, rest = stat[stat.index("(") + 1:stat.rindex(")")], stat[stat.rindex(")") + 2:]
            if name == "claude" and pid != os.getpid():
                return pid
            pid = int(rest.split()[1])
            if pid <= 1:
                return None
    except (OSError, ValueError, IndexError):
        pass
    return None


def alive(pid: int) -> bool:
    """Is that process still running? False where it cannot be asked (Windows)."""
    if os.name == "nt":
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True               # someone else's: it exists
    return True


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


# --- The ledger (ZA-OPRAVYANE row 153, v3.35.0) ---------------------------------------------
# A logbook is written newest entry on top, so the file itself cannot be append-only, and an
# older entry edited left no trace but Stop's own memory of the bodies -- a file the agent can
# delete. The ledger is a second file that only grows: one JSON line per entry Baton has seen
# (root, folder, heading, which of the same headings counted from the bottom, the sha256 of the
# entry's text) and the sha256 of the line before it. It lives in a git repository of its own,
# committed as lines are added. Nothing here pushes or adds a remote; tools/baton_ledger.py
# pushes when the human runs it. Beside the repository: `<dir>.seen.json`, how many lines Baton
# last wrote and the hash of the last one (a ledger deleted or cut is said, not rebuilt clean),
# and `<dir>.lock`, so two sessions ending a turn together keep one chain.

# Stop's _HEADING, a dated entry; tests/test_ledger.py holds the two the same.
ENTRY_HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})(?:[ T](\d{1,2}):(\d{2}))?")
_ENTRY_BYTES = re.compile(ENTRY_HEADING.pattern.encode("ascii"))
LEDGER_FILE = "ledger.jsonl"
_GENESIS = "0" * 64


def ledger_dir(local_file) -> Path | None:
    """BATON_LEDGER, else `ledger` in baton.local.json, else `baton.ledger` in Baton's state
    folder. `"ledger": false` there turns the ledger off: None, and nothing records or reports.
    `local_file(name)` is the caller's, as for `config`."""
    try:
        cfg = json.loads(local_file("baton.local.json").read_text("utf-8-sig"))
    except Exception:
        cfg = {}
    cfg = cfg if isinstance(cfg, dict) else {}
    raw = os.environ.get("BATON_LEDGER")
    if not raw and cfg.get("ledger") is False:
        return None
    raw = raw or cfg.get("ledger")
    return Path(str(raw)).expanduser() if raw else Path(local_file("baton.ledger"))


def ledger_entries(raw: bytes) -> list:
    """(heading, n, sha256) for each dated entry of a logbook's bytes, oldest first; `n` counts
    the same heading from the bottom, so an entry added on top renumbers nothing. The text
    hashed is the heading and the body: the front matter is not part of it, a BOM and CRLF are
    not, trailing whitespace is not. Bytes that are not UTF-8 are hashed as they are."""
    text = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
    text = text.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if text.startswith(b"---"):              # the header, as Stop's _body cuts it
        parts = text.split(b"---", 2)
        if len(parts) == 3:
            text = parts[2]
    # Split where a line starts with "## ", in bytes: a regex split took half the time (5 MB, 57
    # logbooks: 88 ms with it, measured 16.11).
    chunks = (b"\n" + text).split(b"\n## ")[1:]
    out, seen = [], {}
    for chunk in reversed(chunks):
        entry = (b"## " + chunk).rstrip()
        first = entry.split(b"\n", 1)[0]
        if not _ENTRY_BYTES.match(first):
            continue
        heading = first.rstrip().decode("utf-8", "replace")
        n = seen.get(heading, 0)
        seen[heading] = n + 1
        out.append((heading, n, hashlib.sha256(entry).hexdigest()))
    return out


def _absolute(path) -> str:
    try:
        return os.path.normcase(str(Path(path).expanduser().resolve()))
    except (OSError, RuntimeError):
        return os.path.normcase(str(path))


def _root_id(root) -> str:
    """How a line names its task root: `~/<path>` when the root is under home, so a pushed
    ledger does not carry the home path; the absolute path otherwise."""
    full, home = _absolute(root), _absolute(Path.home())
    if full == home:
        return "~"
    if full.startswith(home.rstrip(os.sep) + os.sep):
        return "~/" + full[len(home.rstrip(os.sep)) + 1:].replace(os.sep, "/")
    return full


def _root_ids(root) -> set:
    """Every name a line may give this root: today's, and the absolute path lines carried before
    the root was written relative to home (v3.35.0 before its release)."""
    return {_root_id(root), _absolute(root)}


def _ledger_lines(d: Path) -> list:
    """(raw line, record or None) for each line of the ledger; [] when there is none."""
    try:
        raw = (d / LEDGER_FILE).read_bytes()
    except OSError:
        return []
    out = []
    for line in raw.split(b"\n")[:-1] if raw.endswith(b"\n") else raw.split(b"\n"):
        try:
            rec = json.loads(line.decode("utf-8"))
        except ValueError:
            rec = None
        out.append((line, rec if isinstance(rec, dict) else None))
    return out


def _expected(records: list, rids: set) -> dict:
    """(folder, heading, n) -> the hash the ledger stands by for this root: the latest entry or
    ack line of each; None for an entry acknowledged gone."""
    out = {}
    for rec in records:
        if rec and rec.get("root") in rids and "heading" in rec:
            out[(rec.get("folder"), rec.get("heading"), rec.get("n"))] = rec.get("sha256")
    return out


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _seen_file(d: Path) -> Path:
    return d.with_name(d.name + ".seen.json")


def _seen(d: Path):
    try:
        got = json.loads(_seen_file(d).read_text("utf-8"))
        return got if isinstance(got, dict) else None
    except (OSError, ValueError):
        return None


def _seen_ok(d: Path, lines: list) -> bool:
    """The ledger still holds every line Baton last wrote, the last of them unchanged."""
    seen = _seen(d)
    if not seen:
        return True
    n = seen.get("lines")
    return (isinstance(n, int) and 0 <= n <= len(lines)
            and (n == 0 or _sha(lines[n - 1][0]) == seen.get("last")))


def _seen_write(d: Path, lines: list) -> None:
    try:
        path = _seen_file(d)
        with os.fdopen(os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w",
                       encoding="utf-8") as fh:
            json.dump({"lines": len(lines), "last": _sha(lines[-1][0]) if lines else None}, fh)
    except OSError:
        pass


def _lock(d: Path):
    """`<dir>.lock`, made with O_EXCL; None when it cannot be had in about 5 s. A lock older
    than 30 s is a run that died holding it."""
    try:
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        return None
    path = d.with_name(d.name + ".lock")
    for _ in range(100):
        try:
            os.close(os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
            return path
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > 30:
                    path.unlink()
                    continue
            except OSError:
                continue
            time.sleep(0.05)
        except OSError:
            return None
    return None


def _unlock(path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def ledger_git(d: Path, *args, timeout: float = 5):
    """git in the ledger's repository, never asking for anything on a terminal, with an identity
    of its own (a fresh machine has none) and no signing. None when git cannot be run."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return subprocess.run(["git", "-C", str(d), "-c", "user.name=Baton",
                               "-c", "user.email=baton@localhost", "-c", "commit.gpgsign=false",
                               *args], capture_output=True, text=True, timeout=timeout, env=env,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None


def ledger_dirty(d: Path) -> bool:
    """ledger.jsonl differs from its last commit: Baton commits every line it adds, so something
    else changed it. False when there is no repository, no commit yet, or no git."""
    if not (d / ".git").exists():
        return False
    out = ledger_git(d, "status", "--porcelain", "--", LEDGER_FILE)
    return bool(out and out.returncode == 0 and out.stdout.strip()
                and not out.stdout.startswith("??"))


def _append(d: Path, lines: list, recs: list, message: str) -> list:
    """Chain `recs` onto `lines`, append them, commit -- unless the file already held a change
    Baton did not make, which a commit of Baton's must not bury. Returns the lines now."""
    dirty = ledger_dirty(d)
    prev = _sha(lines[-1][0]) if lines else _GENESIS
    out, added = list(lines), []
    for rec in recs:
        rec = dict(rec, prev=prev)
        raw = json.dumps(rec, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        prev = _sha(raw)
        added.append(raw)
        out.append((raw, rec))
    path = d / LEDGER_FILE
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "ab") as fh:
        if fh.tell() > 0:
            with open(path, "rb") as rd:
                rd.seek(-1, os.SEEK_END)
                if rd.read(1) != b"\n":
                    fh.write(b"\n")       # a line cut short stays a line of its own
        fh.write(b"\n".join(added) + b"\n")
    if not dirty:
        if not (d / ".git").exists():
            ledger_git(d, "init", "-q")
        if (d / ".git").exists():
            ledger_git(d, "add", "--", LEDGER_FILE)
            ledger_git(d, "commit", "-q", "--no-verify", "-m", message)
    return out


def ledger_update(root: Path, logbook: str, folders: list, d: Path, host: str | None = None) -> int:
    """Stop's part: a line for every entry of `folders` the ledger has not seen. An entry it has
    seen is never recorded again, whatever its text is now -- that is for verify to say and the
    human to acknowledge. Nothing new: no lock, no git, nothing written. Returns lines added.
    `host` (row 182): `recorded_by` on each line -- the host whose Stop recorded the entry, which
    is its author only when the ledger is shared and the author's Stop saw it first."""
    rid, rids = _root_id(root), _root_ids(root)

    def missing(lines):
        known = _expected([r for _, r in lines], rids)
        out = []
        for folder in folders:
            try:
                raw = (Path(folder) / logbook).read_bytes()
            except OSError:
                continue
            for heading, n, digest in ledger_entries(raw):
                if known.get((folder.name, heading, n)) is None:
                    out.append({"at": datetime.now().isoformat(timespec="seconds"),
                                "kind": "entry", "root": rid, "folder": folder.name,
                                "heading": heading, "n": n, "sha256": digest,
                                **({"recorded_by": host} if host else {})})
        return out

    if not missing(_ledger_lines(d)):
        return 0
    lock = _lock(d)
    if lock is None:
        return 0
    try:
        lines = _ledger_lines(d)
        recs = missing(lines)            # again, inside the lock: another Stop may have written
        if not recs:
            return 0
        ok = _seen_ok(d, lines)
        names = sorted({r["folder"] for r in recs})
        lines = _append(d, lines, recs, f"{len(recs)} entr{'y' if len(recs) == 1 else 'ies'}: "
                        + ", ".join(names[:5]) + (", ..." if len(names) > 5 else ""))
        if ok:
            _seen_write(d, lines)
        return len(recs)
    finally:
        _unlock(lock)


def ledger_check(root: Path, logbook: str, d: Path) -> dict | None:
    """The ledger against the logbooks as they are now. None when there never was one here.
    `changed`, `gone`: (folder, heading, n) of recorded entries whose text differs or that are
    not there; `chain`: (line or None, what) for a line that does not parse or does not follow
    the one before, a ledger shorter than Baton last wrote it, a change not committed. Reads
    only; fixes nothing."""
    lines = _ledger_lines(d)
    if not lines and not (d / LEDGER_FILE).exists() and _seen(d) is None:
        return None
    records = [r for _, r in lines]
    rids = _root_ids(root)
    rep = {"dir": d, "lines": len(lines), "entries": 0, "changed": [], "gone": [], "chain": [],
           # lines kept for another task root: a root given wrong reads as "nothing recorded"
           "roots": sorted({r["root"] for r in records if r and r.get("root") is not None and r.get("root") not in rids}),
           # what was accepted, and why: an ack is a line anyone running as the human can add
           "acks": [r for r in records if r and r.get("kind") == "ack"
                    and r.get("root", _root_id(root)) in rids]}
    settled = {r.get("line") for r in records if r and r.get("kind") == "ack" and "line" in r}
    prev = _GENESIS
    for i, (raw, rec) in enumerate(lines, 1):
        if i not in settled:
            if rec is None:
                rep["chain"].append((i, f"line {i} is not a ledger line"))
            elif rec.get("prev") != prev:
                rep["chain"].append((i, f"line {i} does not follow line {i - 1}"))
        prev = _sha(raw)
    if not _seen_ok(d, lines):
        rep["chain"].append((None, f"the ledger has fewer lines than Baton last wrote "
                                   f"({(_seen(d) or {}).get('lines')} then, {len(lines)} now), or "
                                   "its last line then is not the same: it was deleted, cut or "
                                   "rewritten"))
    if ledger_dirty(d):
        rep["chain"].append((None, f"{LEDGER_FILE} has changes that are not committed -- Baton "
                                   "commits every line it adds, so something else changed it "
                                   f"(git -C \"{d}\" diff)"))
    books = {}
    for (folder, heading, n), digest in sorted(_expected(records, rids).items(), key=str):
        if digest is None:
            continue
        rep["entries"] += 1
        if folder not in books:
            try:
                raw = (Path(root) / str(folder) / logbook).read_bytes()
                books[folder] = {(h, k): s for h, k, s in ledger_entries(raw)}
            except OSError:
                books[folder] = None
        now = (books[folder] or {}).get((heading, n))
        if now is None:
            rep["gone"].append((folder, heading, n))
        elif now != digest:
            rep["changed"].append((folder, heading, n))
    return rep


def ledger_ack(root: Path, logbook: str, d: Path, reason: str, folder: str | None = None,
               heading: str | None = None) -> int:
    """The human accepts what verify found: a new line for each finding (the entry's hash now,
    or none for one gone; a line that broke the chain; a ledger cut), with the reason. No line is
    edited. With `folder` or `heading`, only the entries that match. Returns lines added."""
    lock = _lock(d)
    if lock is None:
        return 0
    try:
        rep = ledger_check(root, logbook, d)
        if not rep:
            return 0
        rid, recs = _root_id(root), []
        at = datetime.now().isoformat(timespec="seconds")
        want_h = {heading, f"## {heading}"} if heading else None
        books = {}
        for f, h, n in rep["changed"] + rep["gone"]:
            if (folder and f != folder) or (want_h and h not in want_h):
                continue
            if f not in books:
                try:
                    raw = (Path(root) / str(f) / logbook).read_bytes()
                    books[f] = {(eh, k): s for eh, k, s in ledger_entries(raw)}
                except OSError:
                    books[f] = {}
            recs.append({"at": at, "kind": "ack", "root": rid, "folder": f, "heading": h, "n": n,
                         "sha256": books[f].get((h, n)), "reason": reason})
        cut = False
        if not folder and not heading:
            for line, what in rep["chain"]:
                if line is not None:
                    recs.append({"at": at, "kind": "ack", "line": line, "what": what,
                                 "reason": reason})
                elif "fewer lines" in what:
                    cut = True
                    recs.append({"at": at, "kind": "ack", "cut": what, "reason": reason})
        if not recs:
            return 0
        lines = _ledger_lines(d)
        ok = _seen_ok(d, lines)
        lines = _append(d, lines, recs, f"ack, {len(recs)}: {reason}"[:200])
        if ok or cut:
            _seen_write(d, lines)
        return len(recs)
    finally:
        _unlock(lock)
