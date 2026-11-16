#!/usr/bin/env python3
"""Baton Stop hook.

Catches the failure Baton exists to prevent: work happened inside a task folder and
no logbook entry was written for it.

A folder is "unrecorded" when it holds a file newer than its own logbook. That is a
narrow test on purpose — a session that touched no task folder is never interrupted.

When something is unrecorded the turn is handed back to the agent with a note naming the
folder. A turn that answers the hand-back with no new entry is handed back once more, and
then let through: at most two hand-backs per turn, counted by Baton itself (ZA-OPRAVYANE row
115, v3.29.0), so it can never trap a session in a loop. Until v3.29.0 it was one: that was
Baton's choice, not a limit of Claude Code, whose own cap is 8 consecutive continuations,
reset each time a tool is called.
"""
from __future__ import annotations   # `str | None`, `list[str]`: Python 3.8 and 3.9 too
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


# Loaded before the patterns below, which are built from the language files at import (stage 4).
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
_LANG = Path(__file__).with_name("lang")


def _words(slot: str) -> str:
    """The alternatives for `slot` from every language file in hooks/lang: _baton.words."""
    return _baton.alternation(_baton.words(_LANG, slot)) if _baton else "(?!)"


SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache"}
# A file saved moments ago is still being worked on. This is a grace against NOW —
# not against the logbook's own timestamp, which is what it used to be compared with.
#
# 🔴 Found by an external review of v2.14.0: `work > logged + GRACE_SECONDS` meant a
# file written thirty seconds after its logbook could never be reported, however long
# it then sat there, while an old file two minutes newer kept stopping unrelated
# sessions forever. Both are the opposite of the promise. The code had drifted from
# the sentence directly above it.
GRACE_SECONDS = 90


# ZA-OPRAVYANE row 35 (2026-10-21): ~139,000 files under one task root took SessionStart and
# Stop to 19 s against the 20 s hook limit. A folder holding more work files than this is not
# read to the end, and the board and Stop say so -- never a silent pass. Measured that day:
# ~50 us a file at load 1.6, so 10,000 is ~0.5 s a walk, ~1.3 s at the load of 8.7 that took
# the hooks to 19 s; the largest folder here without its data folders holds ~3,800.
WALK_CAP = 10_000


def _lines(path: Path) -> list[str]:
    try:
        lines = path.read_text("utf-8-sig").splitlines()
    except OSError:
        return []
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def ignore_patterns(folder: Path) -> list[str]:
    """Globs from a .batonignore in the task folder (gitignore-style, one per line,
    '#' comments). Use it for files that legitimately change without needing a logbook
    entry — a live transcript, a rotating log, generated output. A line ending in `/` names a
    folder, which the walk does not enter at all. The task ROOT's .batonignore may name the
    same with a path, `<task>/<path>`: those lines count here, without the task's name."""
    own = _lines(folder / ".batonignore")
    prefix = folder.name + "/"
    return own + [ln[len(prefix):] for ln in _lines(folder.parent / ".batonignore")
                  if ln.startswith(prefix) and ln[len(prefix):].strip("/")]


def _dir_patterns(patterns: list[str]) -> list[str]:
    return [p.rstrip("/") for p in patterns if p.endswith("/") and p.rstrip("/")]


def _dir_ignored(rel: str, name: str, dirs: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, d) or fnmatch.fnmatch(name, d) for d in dirs)


def is_ignored(rel: str, name: str, patterns: list[str]) -> bool:
    if any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(name, p) for p in patterns):
        return True
    dirs = _dir_patterns(patterns)          # a file under a folder a `dir/` line names
    parts = Path(rel).parts[:-1]
    return bool(dirs) and any(_dir_ignored(os.path.join(*parts[:i + 1]), parts[i], dirs)
                              for i in range(len(parts)))


def ignored_this_session(root: Path, logbook: str, since: float | None) -> list[tuple]:
    """(folder, files) where a .batonignore saved this session -- the folder's or the root's --
    hides files saved this session (ZA-OPRAVYANE row 57, 22.10). Its lines apply the moment they
    are on disk, so an agent handed back for unrecorded work could ignore the work and pass with
    no word. Said to the human; the lines still apply, since the line may be right."""
    if since is None:
        return []

    def new(path: Path) -> bool:
        try:
            return path.stat().st_mtime >= since
        except OSError:
            return False

    root_new = new(root / ".batonignore")
    skip = _ss().not_tasks(root) if root_new else []
    out = []
    try:
        folders = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []
    for folder in folders:
        if not (root_new or new(folder / ".batonignore")):
            continue
        whole = any(fnmatch.fnmatch(folder.name, g) for g in skip)   # the folder is no task now
        patterns = ignore_patterns(folder)
        hidden, count = [], 0
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for name in filenames:
                count += 1
                if name == logbook or name.startswith(".") or count > WALK_CAP:
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, folder)
                if (whole or is_ignored(rel, name, patterns)) and new(Path(full)):
                    hidden.append(rel.replace(os.sep, "/"))
        if hidden:
            out.append((folder.name, sorted(hidden)))
    return out


PULLED_FILE = ".baton-pulled"
PULLED = {}       # folder name -> files skipped as pulled, this run


def pulled_files(folder: Path) -> dict:
    """{path: st_mtime_ns} a sync wrote after checking these files out (baton-firmi Р5, 02.11).
    A pull gives every file the checkout time, so a task handed over from another machine read as
    this session's unrecorded work. Unreadable or not an object: nothing is skipped."""
    try:
        data = json.loads((folder / PULLED_FILE).read_text("utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, int)} if isinstance(data, dict) else {}


def work_files(folder: Path, logbook: str):
    """(path relative to the folder, full path) of every work file: not the logbook, not a
    dotfile, nothing in SKIP_DIRS or a folder a `dir/` line names, nothing .batonignore matches,
    nothing a sync checked out and nobody changed since (.baton-pulled).
    Stops after WALK_CAP files and adds the folder to TRUNCATED."""
    patterns = ignore_patterns(folder)
    dirs = _dir_patterns(patterns)
    pulled = pulled_files(folder)
    count = 0
    for dirpath, dirnames, filenames in os.walk(folder):
        here = os.path.relpath(dirpath, folder)
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
                       and not (dirs and _dir_ignored(
                           d if here == "." else os.path.join(here, d), d, dirs))]
        for name in filenames:
            if name == logbook or name.startswith("."):
                continue
            rel = name if here == "." else os.path.join(here, name)
            if is_ignored(rel, name, patterns):
                continue
            key = rel.replace(os.sep, "/")
            if key in pulled:
                try:
                    same = os.stat(os.path.join(dirpath, name)).st_mtime_ns == pulled[key]
                except OSError:
                    same = False
                if same:          # as the sync left it; a change here moves the time, and counts
                    PULLED.setdefault(folder.name, set()).add(key)
                    continue
            if count == WALK_CAP:
                if folder.name not in TRUNCATED:
                    TRUNCATED.append(folder.name)
                return
            count += 1
            yield rel, os.path.join(dirpath, name)


def _local_file(name: str) -> Path:
    """Where a settings or state file lives. Installed as a plugin, the hooks run from a
    folder replaced on every update, so these go to ${CLAUDE_PLUGIN_DATA}, which survives
    updates. Installed by install.sh, next to the hooks, as always."""
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not data:
        return Path(__file__).with_name(name)
    try:
        Path(data).mkdir(parents=True, exist_ok=True)   # "created on first reference" is
    except OSError:                                     # not a promise to these hooks
        pass
    return Path(data) / name


def config() -> tuple[Path, str]:
    """Task root and logbook name: one resolution for every hook, `config` in hooks/_baton.py."""
    return _baton.config(_local_file)


def newest_work(folder: Path, logbook: str) -> tuple[float, str]:
    """Newest work-file mtime in the folder, and that file's name. Skips the logbook,
    dotfiles, SKIP_DIRS, and anything matched by the folder's .batonignore -- see work_files."""
    newest, newest_name = 0.0, ""
    for rel, path in work_files(folder, logbook):
        try:
            m = os.stat(path).st_mtime
        except OSError:
            continue
        if m > newest:
            newest, newest_name = m, rel
    return newest, newest_name


NAMED_MAX = 5      # files named per unrecorded folder (row 98); the rest are counted


def newer_files(folder: Path, logbook: str, after: float) -> list[str]:
    """The work files saved after `after`, newest first: the same files newest_work looks at."""
    found = []
    for rel, path in work_files(folder, logbook):
        try:
            m = os.stat(path).st_mtime
        except OSError:
            continue
        if m > after:
            found.append((m, rel))
    return [rel for _, rel in sorted(found, reverse=True)]


def _named(files: list[str]) -> str:
    """`a.py, b.py` -- at most NAMED_MAX, then how many more."""
    more = len(files) - NAMED_MAX
    return ", ".join(files[:NAMED_MAX]) + (f", and {more} more" if more > 0 else "")


def lost_note(lost: list[str], forgot: list[str]) -> str:
    """One message for the human, from Stop or on the board: history gone, no entry saying so."""
    out = []
    if lost:
        out.append("Baton: part of the record is gone, and no entry says so -- " + "; ".join(lost)
                   + ". Baton keeps no copy of a logbook; if this was not on purpose, restore it "
                   "from git or a backup.")
    if forgot:
        out.append(f"Baton: its memory of the logbooks ({forgot[0]}) was gone or unreadable, so it "
                   "started over. Until it has seen each logbook again, an older entry rewritten "
                   "before now cannot be told from a new one.")
    return " ".join(out)


def unread_note(folders: list[str]) -> str:
    """One sentence for the board and for Stop: which folders were not read to the end."""
    return (f"Baton: not read to the end (over {WALK_CAP:,} files) -- newer work further in "
            f"would not be seen: {', '.join(folders)}. Name the data folders in each one's "
            ".batonignore with a line ending in / (e.g. `cache/`), and the walk skips them.")


def _bodies_path() -> Path:
    return Path(os.environ.get("BATON_BODY_STATE")
                or _local_file("baton.bodies.json"))


def _body(text: str) -> str:
    """The logbook below its header -- the part a header edit does not touch."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2]
    return text


def _entries(body: str) -> list[str]:
    """A short hash of each `## ` entry, newest first as they stand in the file."""
    return [hashlib.sha1(part.rstrip().encode("utf-8")).hexdigest()[:12]
            for part in re.split(r"(?m)^(?=## )", body) if part.startswith("## ")]


def _at_the_top(old: list, new: list) -> bool:
    """Nothing older than the newest entry changed: entries were added above it, or the
    newest one itself was edited (completed, its heading corrected) -- or, in a logbook
    kept oldest-first, one was added at the end."""
    below = old[1:]
    return (not below or new[len(new) - len(below):] == below) or new[:len(old)] == old


REWRITTEN: list = []      # folders whose older entries changed during this run
GREW: list = []           # folders that gained an entry since the last look (row 27)
TOPPED: list = []         # folders whose body changed at the top since the last look
TRUNCATED: list = []      # folders not read to the end: over WALK_CAP work files (row 35)
LOST: list = []           # logbooks gone, or holding fewer entries than last seen (row 37)
FORGOT: list = []         # Baton's own memory of the logbooks was gone (row 37)


def recorded_time(folder: Path, logbook: Path, bodies: dict) -> float:
    """When the logbook BODY last changed -- not when the file was last written.

    2026-09-28: aliases were added to every task header; the rewrite moved each
    DNEVNIK.md's mtime past unrecorded work, and this hook called the work recorded, in
    Baton's own folder, the evening the feature shipped. A header edit is not an entry.
    The body is remembered by hash; while it is unchanged, the time it was first seen with
    that hash stands. With nothing remembered yet, the file time -- the old rule, so a first
    run raises no false alarm. Clock-independent on purpose: entry headings are typed by
    hand and were wrong by hours the same day.

    v3.17.0: the entries are remembered one by one, too. A change below the newest entry --
    an older one rewritten -- does not move the time, and the folder goes to REWRITTEN
    (Arthur Barbosa, 08.10: a folder the agent writes in is not an audit trail).
    """
    mtime = logbook.stat().st_mtime
    try:
        body = _body(logbook.read_text("utf-8-sig"))
    except OSError:
        return mtime
    digest = hashlib.sha1(body.encode("utf-8")).hexdigest()
    entries = _entries(body)
    key = str(folder)
    seen = bodies.get(key)
    if seen and seen[0] == digest:
        if len(seen) < 3:
            seen.append(entries)
        return min(mtime, seen[1])
    old = seen[2] if seen and len(seen) > 2 else None
    if old and len(entries) < len(old):
        # v3.20.0, row 37 (Marcelo Dantas, 22.10): entries removed -- the newest one too, which
        # _at_the_top took for a change at the top -- is not the work recorded, and is said once.
        LOST.append(f"{folder.name}: {len(old) - len(entries)} of {len(old)} entries gone "
                    f"from its {logbook.name}")
        bodies[key] = [digest, seen[1], entries]
        return min(mtime, seen[1])
    if old and entries and (old == entries or not _at_the_top(old, entries)):
        if old != entries:
            REWRITTEN.append(folder.name)
        bodies[key] = [digest, seen[1], entries]
        return min(mtime, seen[1])
    if old and len(entries) > len(old):
        GREW.append(folder.name)
    if seen:
        TOPPED.append(folder.name)
    bodies[key] = [digest, mtime, entries]
    return mtime


def session_started(transcript: str) -> float | None:
    """When this session began: the first `timestamp` in its transcript. None when it cannot
    be read -- and then Stop behaves as before, so a missing field never turns it off."""
    try:
        with open(transcript, encoding="utf-8", errors="replace") as fh:
            for _, line in zip(range(500), fh):
                if '"timestamp"' not in line:
                    continue
                stamp = json.loads(line).get("timestamp")
                if isinstance(stamp, str) and stamp:
                    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (OSError, ValueError, TypeError):
        pass
    return None


# Whose work is it? (08.11: Stop handed back twice for folders this session never touched --
# files a nightly cron wrote at 02:30 and another at 08:15 -- and on 07.11, after /clear, asked
# `done_when` for a task another session had just written in.) "Saved since the session began" is
# not "saved by this session". The session's own tool calls say what it touched, from its
# transcript and its subagents': a file counts when a Write/Edit/MultiEdit/NotebookEdit named it;
# or any other tool call that is not a look (Bash, PowerShell, an Agent's prompt, an MCP call)
# named its folder -- the path, `~/...`, or the folder's name as a word -- or ran with its `cwd`
# inside it; or it was saved while one of the session's Bash calls was running. Missed: a file a
# process started in the background (`run_in_background`, `nohup`, `&`) writes after its call
# returned, into a folder no call named. Wrongly counted: a cron that fires while a Bash call runs,
# or writes in a folder the session named. Where they conflict, a cron file handed back is the
# cheaper mistake. Without a readable transcript nothing changes; with one that holds no tool call,
# nothing changes either -- unless the logbook gained an entry since the session began, which a
# session that did nothing cannot have written (row 165): then its folder's files are FOREIGN.
# Measured 08.11 on a 46 MB transcript: 0.86 s, read only when a folder has newer work.
CALL_SLACK_S = 2
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
LOOK_TOOLS = {"Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch", "TodoWrite"}
SHELL_TOOLS = {"Bash", "PowerShell"}
_TOOL_USE = re.compile(rb'"type":\s*"tool_use"')
_CALLS: dict = {}
# Who called this run (_baton.host, set in main). Under Codex the transcript is its rollout, read
# by _baton.codex_calls, where apply_patch is the write tool; anything else reads as Claude Code.
HOST = "unknown"
FOREIGN: dict = {}      # folder name -> files newer than the logbook no call of this session touched
NEWER: dict = {}        # folder name -> this session's files newer than the logbook (row 141)


def _epoch(stamp) -> float | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def session_calls(transcript: str | None) -> dict | None:
    """What this session's tool calls touched -- {"files", "texts", "cwds", "windows"} -- read once
    per run from its transcript and its subagents' (`<transcript>/subagents/*.jsonl`). None when the
    transcript cannot be read."""
    if not transcript:
        return None
    if transcript in _CALLS:
        return _CALLS[transcript]
    if HOST == "codex" and _baton is not None:
        _CALLS[transcript] = _baton.codex_calls(transcript)
        return _CALLS[transcript]
    main = Path(transcript)
    files, texts, cwds, started, windows = set(), [], set(), {}, []
    try:
        subs = sorted(main.with_suffix("").glob("subagents/*.jsonl"))
    except OSError:
        subs = []
    for path in [main] + subs:
        try:
            fh = open(path, "rb")
        except OSError:
            if path == main:
                _CALLS[transcript] = None
                return None
            continue
        with fh:
            for raw in fh:
                use = bool(_TOOL_USE.search(raw))
                if not use and not (started and b'"tool_result"' in raw):
                    continue
                try:
                    obj = json.loads(raw.decode("utf-8", "replace"))
                    content = (obj.get("message") or {}).get("content")
                except (ValueError, AttributeError):
                    continue
                if not isinstance(content, list):
                    continue
                at = _epoch(obj.get("timestamp"))
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_result" and b.get("tool_use_id") in started:
                        begun = started.pop(b["tool_use_id"])
                        windows.append((begun, at if at is not None else begun))
                        continue
                    if b.get("type") != "tool_use":
                        continue
                    tool, args = str(b.get("name") or ""), b.get("input")
                    args = args if isinstance(args, dict) else {}
                    if tool in WRITE_TOOLS:
                        named = args.get("file_path") or args.get("notebook_path")
                        if isinstance(named, str) and named:
                            files.add(os.path.normcase(os.path.abspath(os.path.expanduser(named))))
                    elif tool not in LOOK_TOOLS:
                        texts.append(json.dumps(args, ensure_ascii=False).replace("\\\\", "\\"))
                    if tool in SHELL_TOOLS:
                        if isinstance(obj.get("cwd"), str):
                            cwds.add(os.path.normcase(os.path.abspath(obj["cwd"])))
                        if at is not None and b.get("id"):
                            started[b["id"]] = at
    windows += [(t, t + 600) for t in started.values()]      # no result recorded: ten minutes
    # A transcript with no tool call at all says nothing about whose a file is: as before,
    # everything since the start counts -- except beside an entry newer than the start (no_call).
    _CALLS[transcript] = ({"files": files, "texts": texts, "cwds": cwds, "windows": windows}
                          if files or texts or windows else None)
    return _CALLS[transcript]


def no_call(transcript: str | None) -> bool:
    """The transcript can be read and holds no tool call: this session has touched nothing yet.
    (session_calls says None for this and for a transcript it cannot read; only the first says
    whose a file is.)"""
    if not transcript or session_calls(transcript) is not None:
        return False
    try:
        with open(transcript, "rb"):
            return True
    except OSError:
        return False


def _named_folder(folder: Path, calls: dict) -> bool:
    """A call that is not a look named the folder, or a shell call ran inside it. Once a folder."""
    seen = calls.setdefault("named", {})
    if str(folder) not in seen:
        seen[str(folder)] = _names_folder(folder, calls)
    return seen[str(folder)]


def _names_folder(folder: Path, calls: dict) -> bool:
    full = os.path.normcase(os.path.abspath(str(folder)))
    if any(c == full or c.startswith(full + os.sep) for c in calls["cwds"]):
        return True
    home = os.path.normcase(str(Path.home()))
    forms = [str(folder)] + (["~" + str(folder)[len(home):]] if full.startswith(home + os.sep) else [])
    word = re.compile(r"(?<![\w.-])" + re.escape(folder.name) + r"(?![\w-])")
    return any(f in t for t in calls["texts"] for f in forms) or any(word.search(t) for t in calls["texts"])


def by_this_session(folder: Path, rel: str, calls: dict | None) -> bool:
    """Did this session's tool calls save this file? True when they cannot be read."""
    if calls is None:
        return True
    full = os.path.join(str(folder), rel)
    if os.path.normcase(os.path.abspath(full)) in calls["files"] or _named_folder(folder, calls):
        return True
    try:
        saved = os.stat(full).st_mtime
    except OSError:
        return True
    return any(a - CALL_SLACK_S <= saved <= b + CALL_SLACK_S for a, b in calls["windows"])


def unrecorded(root: Path, name: str, since: float | None = None,
               transcript: str | None = None) -> list[str]:
    """Folders whose work is newer than their logbook. With `since`, only work saved after
    it: 2026-10-01, external review of v3.10.0 -- an old unrecorded file in an unrelated task
    blocked every turn of a session that never touched it. Stop asks about this session's
    work; the older debt is listed on the board instead. With `transcript` too, only work this
    session's tool calls saved (see session_calls); the rest goes to FOREIGN."""
    out = []
    FOREIGN.clear()
    NEWER.clear()
    REWRITTEN.clear()
    GREW.clear()
    TOPPED.clear()
    TRUNCATED.clear()
    LOST.clear()
    FORGOT.clear()
    path = _bodies_path()
    try:
        bodies = json.loads(path.read_text("utf-8"))
    except Exception:
        bodies = {}
        # Row 37: the memory is a file the agent can delete. Without it Stop starts over from file
        # times, and a rewrite cannot be told from a new entry -- so it is said, once. The lessons
        # register remembers the top entry of every logbook Stop has seen ("tops"); when it knows
        # some and this file is gone or unreadable, the memory was lost, not never made. Both
        # files deleted: nothing here can tell.
        try:
            if _ss().lessons_load().get("tops"):
                FORGOT.append(path.name)
        except Exception:
            pass
    for folder in _ss().task_folders(root):
        logbook = folder / name
        work, newest_name = newest_work(folder, name)
        if work == 0.0:
            continue
        before = len(REWRITTEN)
        logged = recorded_time(folder, logbook, bodies) if logbook.is_file() else 0.0
        if since is not None and len(REWRITTEN) > before and logbook.stat().st_mtime < since:
            REWRITTEN.pop()               # rewritten before this session: not this session's
        # Newer than the logbook at all -- but leave alone what is being written now.
        if since is not None and work < since:
            continue
        if work > logged and (time.time() - work) > GRACE_SECONDS:
            # Every file newer than the record, not only the newest: a session cut short with six
            # files told the agent of one (row 98, Abuzar Zaidi, 27.10).
            files = newer_files(folder, name, max(logged, since or 0.0)) or [newest_name]
            if since is not None and transcript:
                calls = session_calls(transcript)
                # Row 165 (D6): a session with no tool call cannot have written the entry its
                # logbook gained since it began -- another agent did, and the files beside it are
                # that agent's. With no newer entry, nothing says whose, and the fallback stays.
                foreign = (calls is None and no_call(transcript) and logbook.is_file()
                           and logbook.stat().st_mtime >= since)
                mine = [] if foreign else [f for f in files if by_this_session(folder, f, calls)]
                if not mine:
                    FOREIGN[folder.name] = files
                    continue
                files = mine
            NEWER[folder.name] = files
            if logbook.is_file():
                out.append(f"{folder.name} (newest: {_named(files)})")
            else:
                out.append(f"{folder.name} (no {name} at all; newest: {_named(files)})")
    # Row 37: a logbook Baton remembered that is not there now -- said once, then forgotten.
    for key in [k for k in bodies if Path(k).parent == root]:
        folder = Path(key)
        if (folder / name).is_file():
            continue
        seen = bodies.pop(key)
        known = f"{len(seen[2])} entries" if len(seen) > 2 else "entries"
        LOST.append(f"{folder.name}: its {name} is gone, with the {known} Baton had seen"
                    if folder.is_dir() else
                    f"{folder.name}: the folder is gone (moved, renamed or deleted), with the "
                    f"{known} of its {name}")
    try:
        path.write_text(json.dumps(bodies, ensure_ascii=False), "utf-8")
    except Exception:
        pass          # memory is a courtesy; without it the file time is used, as before
    return out


# A task worked in now whose header does not say when it is finished (2026-09-28: a
# conversation became a decision on priorities and was never recognised as a task).
# "Now" is a window, not the turn: a Stop hook sees files, not turns. Legacy folders
# nobody touched are outside it, so this cannot nag on day one.
RECENT_SECONDS = 1800


_PARSER = None


def _parser():
    """SessionStart's header parser -- one reader for all three hooks. The hooks are copied
    together, so it sits next to this file both in the repository and once installed."""
    global _PARSER
    if _PARSER is None:          # once per run, not once per folder
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "baton_session_start", Path(__file__).with_name("baton_session_start.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _PARSER = mod.parse_frontmatter
    return _PARSER


def _criterion(logbook: Path) -> bool:
    """Does the header say when it is done -- `done_when` or `kriterii_zavarshvane`?
    No header is no. Read through the shared parser: a reader of its own learned only the
    Bulgarian name and would have asked for a criterion an English header already has."""
    try:
        fm = _parser()(logbook.read_text("utf-8-sig"))
    except Exception:
        return False
    return str(fm.get("done_when", "")).strip() != ""


def undefined(root: Path, name: str, transcript: str | None = None) -> list[str]:
    """Tasks worked in now with no `done_when`. With `transcript`, only those this session's tool
    calls touched: on 07.11, after /clear, one another session had just written in was asked."""
    out = []
    now = time.time()
    for folder in _ss().task_folders(root):
        logbook = folder / name
        if not logbook.is_file():
            continue          # no logbook at all is `unrecorded`'s finding, not this one
        work, newest = newest_work(folder, name)
        touched = max(work, logbook.stat().st_mtime)
        if now - touched <= RECENT_SECONDS and not _criterion(logbook):
            calls = session_calls(transcript)
            inside = os.path.normcase(os.path.abspath(str(folder))) + os.sep
            if calls is not None and not any(f.startswith(inside) for f in calls["files"]) \
                    and not any(by_this_session(folder, rel, calls)
                                for rel in ([newest] if newest else []) + [name]):
                continue
            out.append(folder.name)
    return out


# 2026-09-28, 20:04 by the clock: six logbooks' top entries were headed 22:30, 23:40 and
# "2026-09-29 00:50" -- typed by the agent, not read from a clock. A few minutes of slack
# for a heading written just before it was saved.
FUTURE_SLACK_SECONDS = 600
# ISO or day first: `## 22.10.2026 15:30` is how the human writes a date everywhere else, and a top
# entry headed so was no entry here -- every check read the older ISO one below it (row 58, 22.10).
_HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})(?:[ T](\d{1,2}):(\d{2}))?")


def _day(date: str) -> datetime:
    """The date of a heading, in either form _HEADING reads. ValueError for one that is no date."""
    return datetime.strptime(date, "%Y-%m-%d" if "-" in date else "%d.%m.%Y")


def future_dated(root: Path, name: str) -> list[str]:
    """Folders whose NEWEST entry is headed later than now. Only the top entry: an old
    mistake below it is history; the top one is what the next session trusts."""
    out = []
    now = datetime.now()
    for folder in _ss().task_folders(root):
        book = folder / name
        try:
            text = book.read_text("utf-8-sig")
        except OSError:
            continue
        for line in text.splitlines():
            m = _HEADING.match(line)
            if not m:
                continue
            try:
                day = _day(m.group(1))
            except ValueError:
                break
            if m.group(2):
                when = day.replace(hour=int(m.group(2)), minute=int(m.group(3)))
                late = (when - now).total_seconds() > FUTURE_SLACK_SECONDS
            else:
                late = day.date() > now.date()
            if late:
                out.append(f"{folder.name} (top entry: \"{line[3:40].strip()}\")")
            break
    return out


# Lesson L1 (see LESSONS in baton_session_start.py). `future_dated` above sees only an hour
# AHEAD of the clock, so an hour typed by hand that happens to lie in the past went through
# unseen. This one counts every new top entry (the trigger arose) and catches a heading more
# than L1_SLACK_MINUTES off the clock either way -- and says which tool makes it impossible.
# "The clock" is the logbook's mtime, not the time this hook runs: an entry another session
# headed correctly at 11:08 and first seen here at 13:08 was flagged 120 min behind
# (2026-10-06, prismfield-mac-ipad). The save time is when the heading should have been read.
L1_SLACK_MINUTES = 20
_SS = None


def _ss():
    """SessionStart's module: the lessons register and its counters live there."""
    global _SS
    if _SS is None:
        spec = importlib.util.spec_from_file_location(
            "baton_session_start", Path(__file__).with_name("baton_session_start.py"))
        _SS = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_SS)
    return _SS


def hand_typed_hours(root: Path, name: str, now: datetime | None = None,
                     since: float | None = None, transcript: str | None = None) -> list[str]:
    """Folders whose newest entry is NEW since the last look and headed off the clock.
    The first look at a folder only remembers its top entry: an old heading is history.

    With `since` (when this session began), an entry saved before it is another session's:
    remembered as seen, never reported here, not counted. 2026-10-10 18:58: a session that
    had touched no task folder was handed two other sessions' entries to "correct"."""
    now = now or datetime.now()
    ss = _ss()
    state = ss.lessons_load()
    tops = state.setdefault("tops", {})
    out = []
    for folder in _ss().task_folders(root):
        try:
            text = (folder / name).read_text("utf-8-sig")
            saved = datetime.fromtimestamp((folder / name).stat().st_mtime)
        except OSError:
            continue
        line = next((ln for ln in text.splitlines() if _HEADING.match(ln)), None)
        if line is None:
            continue
        key = str(folder)
        seen, tops[key] = tops.get(key), line
        if seen is None or seen == line:
            continue
        if since is not None and saved.timestamp() < since:
            continue                          # saved before this session: not its entry
        if since is not None and written_by_another(folder, name, transcript):
            continue                          # row 166: another agent's entry, not this one's
        ss.lesson_event(state, "L1", "fired", now)
        m = _HEADING.match(line)
        if not m.group(2):
            continue                          # a date without an hour: nothing to compare
        try:
            when = _day(m.group(1)).replace(hour=int(m.group(2)), minute=int(m.group(3)))
        except ValueError:
            continue
        off = (when - saved).total_seconds() / 60
        if abs(off) > L1_SLACK_MINUTES:
            ss.lesson_event(state, "L1", "caught", now)
            _fix_watch(state, "L1", folder, line, now)
            out.append(f"{folder.name}: \"{line[3:40].strip()}\" is {abs(off):.0f} min "
                       f"{'ahead of' if off > 0 else 'behind'} the clock when it was saved "
                       f"({saved:%H:%M})")
    ss.lessons_save(state)
    return out


# An entry that exists is not an entry that says anything. 2026-10-20, a question under a
# LinkedIn post about hooks: "How do you handle an agent that writes a low-effort logbook
# entry just to get past it?" Nothing did -- the check above compares file times, so one word
# under a heading passed exactly like a full entry. Two things a script can measure without
# judging the text: the entry has its sections, each with something in it, and it names at
# least one of the files saved in the folder this session. Neither proves it right.
MIN_SECTIONS = 3
MIN_ENTRY_CHARS = 200
MIN_NAME_CHARS = 3


def top_entry(text: str) -> tuple[str, str] | None:
    """The newest dated entry: its heading line and the text up to the next `## `."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if _HEADING.match(line):
            end = next((k for k in range(i + 1, len(lines)) if lines[k].startswith("## ")),
                       len(lines))
            return line, "\n".join(lines[i + 1:end])
    return None


def session_entries(text: str, since: float) -> str:
    """Every entry at the top headed at or after the session began (an hour of slack: headings
    are written by people). A session that wrote three entries named its files across all of
    them -- 2026-10-20, a dry run on real logbooks flagged the third for files the first named."""
    start = datetime.fromtimestamp(since - 3600)
    lines, out, keep = text.splitlines(), [], False
    for line in lines:
        m = _HEADING.match(line)
        if m:
            try:
                day = _day(m.group(1))
            except ValueError:
                break
            when = day.replace(hour=int(m.group(2)), minute=int(m.group(3))) if m.group(2) \
                else day.replace(hour=23, minute=59)
            if when < start:
                break
            keep = True
        if keep:
            out.append(line)
    return "\n".join(out)


def touched_since(folder: Path, logbook: str, since: float) -> list[str]:
    """Work files saved at or after `since` -- the same files `newest_work` looks at."""
    out = []
    for rel, path in work_files(folder, logbook):
        try:
            if os.stat(path).st_mtime >= since:
                out.append(rel.replace(os.sep, "/"))
        except OSError:
            continue
    return sorted(out)


def _names(rel: str) -> set:
    """What counts as naming a file: its name, its stem, or a folder it sits in."""
    p = Path(rel)
    return {n for n in (p.name, p.stem, *p.parent.parts) if len(n) >= MIN_NAME_CHARS}


# The reverse case (ZA-OPRAVYANE row 76; Kyle Bartlett, 22.09: "An agent that found nothing to do
# writes you the same confident paragraph as one that did the work"). A session that saved no file
# in the folder was asked nothing, so "Rewrote parse_date() in parser.py" passed with parser.py two
# days old. Asked only then -- no file saved here this session -- and only for a file of the folder
# whose full name stands on a line with a verb of change: measured 23.10 on the 36 top entries of
# the author's logbooks, 0 asked; without the verb, 2 (files cited as sources); asked whenever the
# file is older, 2 more (a name, cbom.json, that many subfolders hold).
_CHANGED = re.compile(r"(?i)" + _words("changed"))


# A path named whole: /x/y.py, ~/x/y.py, C:\x\y.py. Not the path part of a web address.
# On a line that deletes, moves or renames, a path is meant to be gone: not judged.
_GONE = re.compile(r"(?i)" + _words("gone"))
_ABS_PATH = re.compile(r"(?<![\w~.:/\\])(?:~?/|[A-Za-z]:\\)(?:[\w.\-]+[/\\])*[\w\-][\w.\-]*\.\w+")


def claimed_untouched(folder: Path, logbook: str, body: str,
                      since: float | None = None) -> list[str]:
    """Work files of the folder the entry says it changed. Asked only when no file of the folder
    was saved this session, so none of them was. And a path named whole, anywhere, that is not
    there or was not saved this session (row 95, Trofymenko, 25.10: the hand-back says "name
    where" when the change is somewhere else, and then nothing looked at where)."""
    lines = [ln for ln in body.splitlines() if _CHANGED.search(ln)]
    out = []
    for rel, path in (work_files(folder, logbook) if lines else ()):
        name = Path(rel).name
        if len(name) >= MIN_NAME_CHARS and any(name in ln for ln in lines):
            out.append(rel.replace(os.sep, "/"))
    for named in sorted({m for ln in lines if not _GONE.search(ln) for m in _ABS_PATH.findall(ln)}):
        if (named[1:2] == ":") != (os.name == "nt") and not named.startswith("~"):
            continue          # another system's path (work on a Windows machine, said from here)
        try:
            saved = Path(named).expanduser().stat().st_mtime
        except FileNotFoundError:
            out.append(f"{named} (not there)")
            continue
        except OSError:
            continue          # unreadable here (another user's, a drive not mounted): not judged
        if since is not None and saved < since:
            out.append(named)
    return sorted(out)


def hollow(body: str, files: list[str], session_text: str | None = None,
           claimed: list[str] = ()) -> list[str]:
    """Why an entry body looks written only to pass. Empty when nothing measurable is wrong.
    The files may be named anywhere in `session_text` (this session's entries), else in `body`.
    `claimed`: files it says it changed that were not saved this session, when none was."""
    reasons = []
    sections = re.split(r"(?m)^### .*$", body)[1:]
    filled = sum(1 for s in sections if s.strip())
    if len(sections) < MIN_SECTIONS or filled < len(sections):
        reasons.append(f"{filled} section(s) with text, {MIN_SECTIONS} or more expected "
                       "(what was asked, what was done, the result, what is open)")
    chars = len("".join(body.split()))
    if chars < MIN_ENTRY_CHARS:
        reasons.append(f"{chars} characters, under {MIN_ENTRY_CHARS}")
    where = session_text if session_text else body
    if files and not any(n in where for f in files for n in _names(f)):
        shown = ", ".join(files[:3]) + (", ..." if len(files) > 3 else "")
        reasons.append(f"names none of the files saved here this session ({shown})")
    if claimed and not files:
        shown = ", ".join(claimed[:3]) + (", ..." if len(claimed) > 3 else "")
        reasons.append(f"says it changed {shown}, and no file in this folder was saved this "
                       "session -- if the change is somewhere else, name where")
    return reasons


def written_by_another(folder: Path, name: str, transcript: str | None) -> bool:
    """Row 166: the logbook was last written by another agent or host, not this session. Stricter
    than by_this_session, because two agents share one folder: naming the folder is not enough.
    The logbook is this session's when a write of its own named the logbook itself, or when it was
    last saved while one of its calls ran (baton_entry.py from a shell; Codex's exec). A session
    with no tool call wrote nothing. False without a transcript, or with one that cannot be read:
    as before, the entry is this session's."""
    if not transcript:
        return False
    calls = session_calls(transcript)
    if calls is None:
        return no_call(transcript)
    book = os.path.join(str(folder), name)
    if os.path.normcase(os.path.abspath(book)) in calls["files"]:
        return False
    try:
        saved = os.stat(book).st_mtime
    except OSError:
        return False
    return not any(a - CALL_SLACK_S <= saved <= b + CALL_SLACK_S for a, b in calls["windows"])


def _changed_tops(root: Path, name: str, since: float | None, transcript: str | None = None):
    """(folder, text, top entry) for each logbook whose body this session changed. Without a
    session start nothing: an old entry is history, and one this session did not write is not
    its debt. With `transcript`, a logbook another agent wrote in the meantime is not this
    session's either (row 166: two agents on one logbook; see written_by_another)."""
    if since is None:
        return
    try:
        bodies = json.loads(_bodies_path().read_text("utf-8"))
    except Exception:
        bodies = {}
    for folder in _ss().task_folders(root):
        book = folder / name
        try:
            saved = book.stat().st_mtime
            text = book.read_text("utf-8-sig")
        except OSError:
            continue
        if saved < since:
            continue
        seen = bodies.get(str(folder))
        if seen and seen[1] < since and seen[0] == hashlib.sha1(
                _body(text).encode("utf-8")).hexdigest():
            continue                          # only the header changed this session
        if written_by_another(folder, name, transcript):
            continue
        top = top_entry(text)
        if top is not None:
            yield folder, text, top


def hollow_entries(root: Path, name: str, since: float | None,
                   transcript: str | None = None) -> list[tuple]:
    """(folder, heading, reasons) for each logbook whose body this session changed and whose
    newest entry looks hollow."""
    out = []
    for folder, text, top in _changed_tops(root, name, since, transcript):
        files = touched_since(folder, name, since)
        reasons = hollow(top[1], files, session_entries(text, since),
                         [] if files else claimed_untouched(folder, name, top[1], since))
        if reasons:
            out.append((folder.name, top[0], reasons))
    return out


# The repository a task's code lives in (ZA-OPRAVYANE row 73; Rim Elouragini, 23.10: "the file is
# a claim, the repo is the evidence"). Stop compares the task folder's files with its logbook; a
# repository elsewhere was never looked at -- an entry "parser fixed and committed", the repo with
# no commit and an uncommitted change newer than the entry, and Stop passed. The header's `code:`
# field (`kod:`) already names it, as `<path>@<ref>`. For each logbook this session wrote in, what
# that repository holds newer than the logbook -- uncommitted files, commits -- is named to the
# human, once a session per folder. Nothing is judged: a commit after the entry may be the one it
# describes. Only folders written in this session: git on every `code:` repository at every Stop
# would not fit its 20 s.
CODE_GIT_TIMEOUT_S = 3


def code_changes(root: Path, name: str, since: float | None,
                 transcript: str | None = None) -> list[tuple]:
    """(folder, repository, what is newer than the logbook) for the folders this session wrote in
    whose header names a `code:` repository; `what` is None when git could not say."""
    out = []
    for folder, text, _top in _changed_tops(root, name, since, transcript):
        try:
            raw = str(_parser()(text).get("code", "")).strip()
        except Exception:
            continue
        if not raw:
            continue
        repo = Path((raw.rpartition("@")[0] if "@" in raw else raw).strip()).expanduser()
        if not (repo / ".git").exists():
            continue                  # SessionStart says that one, every session (kod_drift)
        logged = (folder / name).stat().st_mtime

        def git(*args):
            done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                                  timeout=CODE_GIT_TIMEOUT_S)
            if done.returncode != 0:
                raise OSError(done.stderr.strip()[:80])
            return done.stdout
        try:
            files = []
            for line in git("status", "--porcelain", "--untracked-files=all").splitlines():
                rel = line[3:].split(" -> ")[-1].strip('"')
                try:
                    if os.stat(repo / rel).st_mtime > logged:
                        files.append(rel)
                except OSError:
                    files.append(rel)                     # deleted since: newer by definition
            commits = []
            try:
                log = git("log", "-10", "--format=%h %ct %s")
            except OSError:
                log = ""                                  # a repository with no commit yet
            for line in log.splitlines():
                sha, ct, subject = (line.split(" ", 2) + ["", ""])[:3]
                if ct.isdigit() and int(ct) > logged:
                    commits.append(f"{sha} {subject[:50]}")
        except (OSError, subprocess.SubprocessError):
            out.append((folder.name, repo, None))
            continue
        if files or commits:
            what = []
            if files:
                what.append(f"{len(files)} uncommitted: " + ", ".join(files[:3])
                            + (", ..." if len(files) > 3 else ""))
            if commits:
                more = " or more" if len(commits) == 10 else ""       # git log -10
                what.append(f"{len(commits)}{more} commit(s): " + "; ".join(commits[:3]))
            out.append((folder.name, repo, "; ".join(what)))
    return out


# Lesson L3: a claim about what is public or private is checked against the source. 2026-10-17
# 11:20, borsa-analiz: "`gh` says StanimirTenev/market-swarm is PUBLIC" -- private, always had
# been, and no `gh` output in that session said otherwise; caught by the human two hours later,
# in an entry the shape check above passes. A reader proposed (20.10) a short "claims to verify"
# section at the top of an entry, so the human reads the claim, not the prose. Asked for on
# every entry it would be a form: versions and URLs are in half of all entries, visibility in
# about one in eight (measured 20.10). So only that. It cannot tell whether the claim is true;
# it puts the claim where a reader checks it. `caught` is a proven error only: a claim listed
# in such a section and later marked `refuted:` -- a re-read of a correct claim is not one.
_VISIBLE = re.compile(r"(?i)(?<![\w-])(" + _words("visible") + r")(?![\w-])")
# Senses of the word that are not a thing's visibility, and mentions that are not claims:
# a span of code (`"visibility":"PRIVATE"` pasted from a tool), a key in
# cryptography, one word in quotes (the word talked about), and the pair named as a topic
# (`public/private`). Kept to classes, not phrases: a phrase list is fitted to one machine.
# v3.36.0, ZA-OPRAVYANE row 160: the public sphere -- where information comes from (public
# sources, information, data, records), whom a service or body is open to or run by (a public
# network, sector, authority; "the public"), a private person or company. The phase-1 handoff
# test (16.11) handed back in 3 of 3 sessions of a desk-research task over "public company
# information", "a typical public source" and "not a public network": none says a thing is
# visible. Like `key`, the class is the word with the noun that gives it this sense (`sphere` in
# hooks/lang). The thing whose visibility is set -- a repo, page, post, fork -- keeps the word.
_CODE = re.compile(r"`[^`\n]*`")
_KEY = re.compile(r"(?i)" + _words("key"))
_SPHERE = re.compile(r"(?i)(?<![\w-])(?:" + _words("sphere") + r")")
_QUOTED_WORD = re.compile(r"[„“\"«']\s*\w+\s*[“”\"»']")
_PAIR = re.compile(r"\w+(?:\s*/\s*\w+)+")
_CLAIMS = re.compile(r"(?i)^###\s+(?:" + _words("claims_heading") + r")\s*:?\s*$")
_REFUTED = re.compile(r"(?i)^\s*(?:[-*]\s+)?(?:" + _words("refuted") + r")\s*:")
_SEEN_CAP = 1000


def visibility_words(text: str) -> list[str]:
    """The words in `text` that say something is public or private, as written."""
    t = _CODE.sub(" ", text)
    for rx in (_KEY, _SPHERE, _QUOTED_WORD):
        t = rx.sub(lambda m: " " if _VISIBLE.search(m.group(0)) else m.group(0), t)
    t = _PAIR.sub(lambda m: " " if len(_VISIBLE.findall(m.group(0))) >= 2 else m.group(0), t)
    return [m.group(1) for m in _VISIBLE.finditer(t)]


# Lesson L4: a claim that tests pass is listed with the command that showed it. ZA-OPRAVYANE
# row 38 (Apurv Khare, 22.10): the shape check above passed "did not run pytest ... All tests
# pass." -- decided by the human the same day: ask for it as L3 asks for visibility. Measured
# on the 1,347 dated entries in the logbooks here (22.10): 25 match, all 25 a claim that tests
# passed. A first version matched 35; the 10 it dropped were the phrase quoted (talked about, not
# claimed), "минават през" (go through), and "1 failed, 9 passed" (a run that failed). Code spans
# are not read: a pasted result line is the evidence, not the claim. It cannot tell a true
# claim from a false one; it puts the claim and its command where a reader checks them.
# v3.21.0, row 42: "5/5 passes" -- the honest entry of the probe -- was not asked. N/N only, and
# "3/5 passed" no longer reads as "5 passed": like "1 failed, 9 passed", a run that failed.
# Measured on the 1,382 dated entries here (22.10): 29 match before and after, all claims; the
# four "N/N pass" in the logbooks are the phrase quoted, talked about.
# Row 60 (22.10): the plain sentence was missed -- "tests are passing", "the suite passes", "CI is
# green", and Bulgarian without the article or with "преминаха"/"са зелени" (two real claims in
# investicii-sec, never asked).
_TESTS = re.compile(r"(?i)(?<![\w-])(" + _words("tests_pass") + r")(?![\w-])")
_QUOTE = re.compile(r"[„“\"«][^„“”\"«»\n]{1,160}[“”\"»]")


def tests_words(text: str) -> list[str]:
    """The phrases in `text` that say tests pass, as written."""
    return [m.group(1) for m in _TESTS.finditer(_QUOTE.sub(" ", _CODE.sub(" ", text)))]


def _sections(body: str) -> list[tuple[str, list[str]]]:
    """The `###` sections of an entry body: (heading line, lines under it)."""
    out = []
    for line in body.splitlines():
        if line.startswith("### "):
            out.append((line.strip(), []))
        elif out:
            out[-1][1].append(line)
    return out


def _claims(body: str) -> list[list[str]]:
    """The lines of each claims section in an entry body."""
    return [lines for head, lines in _sections(body) if _CLAIMS.match(head)]


def claims_first(body: str) -> bool:
    """The entry opens with a claims section that names something."""
    secs = _sections(body)
    return bool(secs) and bool(_CLAIMS.match(secs[0][0])) and any(x.strip() for x in secs[0][1])


def _session_tops(text: str, top: tuple, since: float) -> list[tuple]:
    """The entries this session wrote, newest first; the top one always. L3 and L4 read only the
    top, so a claim with a clean entry written above it was never asked (row 59, 22.10) -- the
    hollow check had already learned a session writes several entries (`session_entries`)."""
    entries = _all_entries(session_entries(text, since))
    return entries if entries and entries[0][0] == top[0] else [top] + entries


def visibility_entries(root: Path, name: str, since: float | None,
                       transcript: str | None = None) -> list[tuple]:
    """(folder, heading, words) for the newest entry this session wrote, in each folder, that says
    something is public or private and does not open with a claims section."""
    out = []
    for folder, text, top in _changed_tops(root, name, since, transcript):
        for heading, body in _session_tops(text, top, since):
            words = visibility_words(heading + "\n" + body)
            if words and not claims_first(body):
                out.append((folder.name, heading, list(dict.fromkeys(words))))
                break
    return out


def tests_listed(body: str) -> bool:
    """The entry opens with a claims section that lists a tests claim (what L4 asks for)."""
    return claims_first(body) and any(_TESTS.search(_CODE.sub(" ", ln)) for ln in _claims(body)[0])


def tests_entries(root: Path, name: str, since: float | None,
                  transcript: str | None = None) -> list[tuple]:
    """(folder, heading, phrases) for the newest entry this session wrote, in each folder, that
    says tests pass and does not list that claim in a claims section at its top (L4)."""
    out = []
    for folder, text, top in _changed_tops(root, name, since, transcript):
        for heading, body in _session_tops(text, top, since):
            words = tests_words(heading + "\n" + body)
            if words and not tests_listed(body):
                out.append((folder.name, heading, list(dict.fromkeys(words))))
                break
    return out


# L4, the pinned command (v3.21.0, ZA-OPRAVYANE row 43; Apurv Khare, 22.10: "tests pass should
# come from a hook that re-runs them"). Inside Stop a re-run does not fit -- Baton's own suite is
# 38 s against Stop's 20 s, and a hook killed at its limit leaves no verdict (row 41) -- and a
# command chosen by the model proves little ("10 passed" on another file; `-k` matching nothing is
# exit 5). Decided by the human: a command pinned once in baton.local.json, by a human, run after
# the turn in the background, under its own budget, judged by its exit code. Never one from a
# logbook, the model or the repository: the runner is given a folder, and reads the command itself.
TESTS_TIMEOUT_S = 600
# What the pinned command gets from the session's environment (ZA-OPRAVYANE row 47, Bernard Haddad,
# 22.10): the board's list (BOARD_ENV, without CLAUDE_PLUGIN_DATA), what a shell and a virtualenv
# expect, and the names the pin lists under "env". It was everything but BATON_* and
# CLAUDE_PLUGIN_*: three made-up identity variables (email, org ID, OAuth token) reached it intact.
RUN_ENV = ("USER", "LOGNAME", "USERNAME", "SHELL", "TERM", "VIRTUAL_ENV")


def pinned_tests(folder: Path) -> tuple[dict | None, str | None]:
    """The test command a human pinned for this task folder -- `"tests": {"<folder>": {"command":
    "...", "cwd": "...", "timeout_s": 600}}` in baton.local.json -- and what is wrong with the pin,
    if anything. (None, None): nothing pinned, and L4 is as it was."""
    try:
        cfg = json.loads(_local_file("baton.local.json").read_text("utf-8-sig"))
    except Exception:
        return None, None
    pins = cfg.get("tests") if isinstance(cfg, dict) else None
    if not isinstance(pins, dict) or folder.name not in pins:
        return None, None
    pin = pins[folder.name]
    if not isinstance(pin, dict) or not isinstance(pin.get("command"), str) \
            or not pin["command"].strip():
        return None, f"`tests` → `{folder.name}` in baton.local.json has no `command`"
    budget = pin.get("timeout_s", TESTS_TIMEOUT_S)
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget <= 0:
        return None, f"`tests` → `{folder.name}` → `timeout_s` is not a number of seconds"
    names = pin.get("env", [])
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        return None, f"`tests` → `{folder.name}` → `env` is not a list of variable names"
    cwd = Path(str(pin.get("cwd") or folder)).expanduser()
    return {"command": pin["command"], "cwd": str(cwd), "timeout_s": budget, "env": names}, None


def pinned_runs(root: Path, name: str, since: float | None, session: str,
                transcript: str | None = None) -> tuple[list, set]:
    """Start the pinned command, in the background, for each newest entry this session wrote that
    says tests pass -- once per entry, never while a run for the folder is going. Returns what to
    tell the human, and the folders whose run has started."""
    said, started = [], set()
    asked = _already_asked(session)
    for folder, _text, (heading, body) in _changed_tops(root, name, since, transcript):
        if not tests_words(heading + "\n" + body):
            continue
        pin, problem = pinned_tests(folder)
        if problem:
            if f"pin:{folder.name}" not in asked:
                said.append(f"Baton: {problem}; nothing was run.")
                _remember(session, _already_asked(session) | {f"pin:{folder.name}"})
            continue
        if not pin:
            continue
        path = _ss().tests_file(folder.name)
        try:
            rec = json.loads(path.read_text("utf-8"))
        except Exception:
            rec = {}
        if rec.get("entry") == heading:
            continue                              # this entry has had its run
        if rec.get("state") == "running":
            try:
                age = (datetime.now() - datetime.fromisoformat(rec["started"])).total_seconds()
                if age <= float(rec.get("timeout_s") or 0) + 120:
                    continue                      # one run at a time; the next Stop starts this one
            except (KeyError, TypeError, ValueError):
                pass
        last = {"counts": rec["counts"]} if rec.get("counts") and rec.get("command") == pin["command"] \
            else {}                               # the last run's counts: row 77's baseline
        _ss().tests_save(path, {"name": folder.name, "folder": str(folder), "entry": heading,
                                "state": "running", "started": datetime.now().isoformat(),
                                "since": since, **last, **pin})
        detach = ({"creationflags": 0x00000008 | 0x00000200} if os.name == "nt"   # DETACHED, NEW_GROUP
                  else {"start_new_session": True})
        # Not this process's pipes: Claude Code waits for them to close, and would wait for the tests.
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--run-tests", str(folder)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **detach)
        started.add(folder.name)          # not said: only a result that disagrees is (30.10)
    return said, started


# What a runner prints when it ran no test (ZA-OPRAVYANE rows 74, 75; Kyle Bartlett, 23.10). The
# verdict was the exit code, and "no tests ran" was code 5 with "pytest" anywhere in the command:
# `go test` in a module with no test files exits 0 and was "passed"; unittest's "NO TESTS RAN"
# (exit 5) was "failed"; jest's "No tests found" exits 1; and any program exiting 5 from a folder
# whose path held "pytest" was "no tests ran". Now the output is read: pytest, unittest, jest and
# vitest say it in a line; go says it per package, so only when no package ran a test.
TAIL_BYTES = 64 * 1024
_NO_TESTS = re.compile(r"(?im)\bno tests ran\b|^Ran 0 tests\b|\bNo tests? (?:files )?found\b")
_GO_NONE = re.compile(r"(?m)^(?:\?\s+\S+\s+\[no test files\]|ok\s+\S+.*\[no tests to run\])\s*$")
_GO_RAN = re.compile(r"(?m)^(?:ok|FAIL|---)\s(?!.*\[no tests to run\])")


def ran_nothing(text: str) -> bool:
    """The runner's output says it ran no test."""
    return bool(_NO_TESTS.search(text)) or bool(_GO_NONE.search(text) and not _GO_RAN.search(text))


# A pass with the failing test skipped, xfailed or deleted is exit 0 too (ZA-OPRAVYANE row 77; a
# post of 01.10: "An AI coding agent hit a failing test, deleted it, and reported the task done").
# The runner keeps how many tests ran and how many were set aside, and compares them with the last
# run of the same command: fewer tests, or more set aside, is not "passed". The first run has no
# last run: a test deleted before it is not seen, a skip is said.
_PYTEST_COUNT = re.compile(r"(\d+) (passed|failed|skipped|xfailed|xpassed|errors?)\b")


def test_counts(text: str) -> dict | None:
    """{"total", "set_aside"} from what pytest, unittest, jest or `go test -v` printed; None."""
    m = list(re.finditer(r"(?m)^Ran (\d+) tests? in ", text))           # unittest
    if m:
        tail = text[m[-1].end():]
        aside = sum(int(n) for n in re.findall(r"(?:skipped|expected failures)=(\d+)", tail))
        return {"total": int(m[-1].group(1)), "set_aside": aside}
    m = list(re.finditer(r"(?m)^Tests:\s+(.*)$", text))                    # jest
    if m:
        got = {w: int(n) for n, w in re.findall(r"(\d+) (\w+)", m[-1].group(1))}
        if "total" in got:
            return {"total": got["total"], "set_aside": got.get("skipped", 0) + got.get("todo", 0)}
    go = {k: len(re.findall(rf"(?m)^\s*--- {k}: ", text)) for k in ("PASS", "FAIL", "SKIP")}
    if any(go.values()):                                                   # go test -v
        return {"total": sum(go.values()), "set_aside": go["SKIP"]}
    for line in [ln for ln in text.splitlines() if ln.strip()][-5:][::-1]:  # pytest's summary
        got = {}
        for n, w in _PYTEST_COUNT.findall(line):
            got[w.rstrip("s") if w.startswith("error") else w] = int(n)
        if got:
            return {"total": sum(got.values()), "set_aside": got.get("skipped", 0) + got.get("xfailed", 0)}
    return None


def passed_as(counts: dict | None, last: dict | None) -> str:
    """The verdict of a run that exited 0 and ran tests, against the last run's counts."""
    if not counts:
        return "passed"
    if last and counts["total"] < last.get("total", 0):
        return (f"passed, with {last['total'] - counts['total']} fewer tests than the last run "
                f"({last['total']} -> {counts['total']})")
    if counts["set_aside"] > (last.get("set_aside", 0) if last else 0):
        return (f"passed, with {counts['set_aside']} skipped or xfailed"
                + (f" (the last run: {last.get('set_aside', 0)})" if last else ""))
    return "passed"


# Row 52 (Martin Gonella, 22.10): an agent that rewrites the expected value makes the pinned run
# pass. Not a verdict -- a test edited may be a test fixed -- but said beside the result: the test
# files saved in the pin's folder since the session began.
_TEST_FILE = re.compile(r"^(?:test_.*\.py|.*_test\.(?:py|go)|conftest\.py|.*\.(?:test|spec)\.[cm]?[jt]sx?)$")


def edited_tests(cwd: Path, since: float) -> list[str]:
    out, count = [], 0
    for dirpath, dirnames, filenames in os.walk(cwd):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            count += 1
            if count > WALK_CAP:
                return sorted(out)
            full = os.path.join(dirpath, name)
            try:
                if _TEST_FILE.match(name) and os.stat(full).st_mtime >= since:
                    out.append(os.path.relpath(full, cwd).replace(os.sep, "/"))
            except OSError:
                continue
    return sorted(out)


def run_tests(folder_arg: str) -> int:
    """The background runner (`baton_stop.py --run-tests <folder>`). Runs the command pinned for
    that folder -- read here, from baton.local.json, never from the arguments -- in its own process
    group, within its budget, and records the verdict: no tests ran, when its output says so (rows
    74, 75); else 0 passed, another code failed; over budget, timed out (the group is killed)."""
    folder = Path(folder_arg)
    pin, _problem = pinned_tests(folder)
    if not pin:
        return 0
    path = _ss().tests_file(folder.name)
    try:
        rec = json.loads(path.read_text("utf-8"))
    except Exception:
        rec = {}
    log = path.with_suffix(".log")
    last = rec.get("counts") if rec.get("command") == pin["command"] else None
    rec.update({"name": folder.name, "folder": str(folder), **pin,
                "started": rec.get("started") or datetime.now().isoformat()})
    t0, code, verdict = time.time(), None, None
    group = {"creationflags": 0x00000200} if os.name == "nt" else {"start_new_session": True}
    # Only RUN_ENV's names, never Baton's own: run as the pin, Baton's suite read the hook's
    # CLAUDE_PLUGIN_DATA and BATON_HOME instead of its own, and 12 tests failed (22.10).
    board = set(_baton.BOARD_ENV) if _baton else set()      # hooks/_baton.py since v3.29.0
    allowed = (board - {"CLAUDE_PLUGIN_DATA"}) | set(RUN_ENV) | set(pin["env"])
    env = {k: v for k, v in os.environ.items() if k in allowed}
    try:
        with open(log, "wb") as out:
            proc = subprocess.Popen(pin["command"], shell=True, cwd=pin["cwd"], env=env,
                                    stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                    **group)
            try:
                code = proc.wait(timeout=pin["timeout_s"])
            except subprocess.TimeoutExpired:
                verdict = "timed out"
                if os.name == "nt":
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                                   capture_output=True)
                else:
                    import signal
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
    except Exception as exc:
        verdict = f"could not start: {type(exc).__name__}"
    try:
        with open(log, "rb") as fh:
            fh.seek(max(0, os.path.getsize(log) - TAIL_BYTES))
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        text = ""
    line = next((ln.strip() for ln in reversed(text.splitlines()) if ln.strip()), "")[:200]
    counts = test_counts(text)
    if verdict is None:
        # A runner that counted tests ran tests: a failure quoting "no tests ran" is a failure
        # (row 84, 23.10).
        nothing = ran_nothing(text) and not (counts and counts["total"] > 0)
        verdict = ("no tests ran" if nothing else passed_as(counts, last) if code == 0
                   else "failed")
    if counts:
        rec["counts"] = counts
    if isinstance(rec.get("since"), (int, float)):
        try:
            rec["tests_edited"] = edited_tests(Path(pin["cwd"]), rec["since"])
        except Exception:
            pass
    rec.update({"state": "done", "finished": datetime.now().isoformat(),
                "seconds": round(time.time() - t0, 1), "exit": None if verdict == "timed out"
                else code, "verdict": verdict, "line": line, "log": str(log), "reported": False})
    _ss().tests_save(path, rec)
    return 0


def _all_entries(text: str) -> list[tuple[str, str]]:
    """Every dated entry, newest first as they stand: (heading, body)."""
    out = []
    for part in re.split(r"(?m)^(?=## )", _body(text)):
        head, _, body = part.partition("\n")
        if _HEADING.match(head):
            out.append((head, body))
    return out


def refuted_claims(root: Path, name: str, since: float | None, now: datetime | None = None,
                   transcript: str | None = None) -> int:
    """Count L3 `caught`: a line `refuted: ...` (`оборено: ...`) in a claims section of the
    newest entry this session wrote, in a logbook where an older entry listed claims. Each line
    once. Returns how many were new."""
    ss = _ss()
    state = ss.lessons_load()
    seen = state.setdefault("L3_refuted", [])
    new = 0
    for folder, text, (heading, body) in _changed_tops(root, name, since, transcript):
        older = _all_entries(text)[1:]
        if not any(_claims(b) for _h, b in older):
            continue
        for lines in _claims(body):
            for line in lines:
                key = f"{folder}|{heading}|{line.strip()}"
                if _REFUTED.match(line) and key not in seen:
                    seen.append(key)
                    ss.lesson_event(state, "L4" if tests_words(line) else "L3", "caught", now)
                    new += 1
    if new:
        state["L3_refuted"] = seen[-_SEEN_CAP:]
        ss.lessons_save(state)
    return new


def first_asks(asks: list[tuple], root: Path, now: datetime | None = None,
               lesson: str = "L3") -> list[tuple]:
    """The entries never asked about before, in any session; each one counts `fired`."""
    ss = _ss()
    state = ss.lessons_load()
    seen = state.setdefault(f"{lesson}_asked", [])
    out = []
    for ask in asks:
        key = f"{root / ask[0]}|{ask[1]}"
        if key not in seen:
            seen.append(key)
            ss.lesson_event(state, lesson, "fired", now)
            _fix_watch(state, lesson, root / ask[0], ask[1], now)
            out.append(ask)
    if out:
        state[f"{lesson}_asked"] = seen[-_SEEN_CAP:]
        ss.lessons_save(state)
    return out


# Was the lesson followed? (ZA-OPRAVYANE row 44, after Sentry's "recovery verification", 22.10.)
# Row 40 measured it for L2 only. After Stop asks about an entry -- L1 an hour off the clock, L3 a
# public/private claim, L4 a tests claim -- the next FIX_STOPS Stops look at that folder's newest
# entry with the same test that raised the ask: gone counts `fixed_after`, still there after
# FIX_STOPS Stops `not_fixed_after`. A Stop, not a turn, is what the hook can count; the second pass
# after a hand-back is one. A proxy, not proof: a new entry on top of the flagged one answers too.
FIX_STOPS = 3
_FIX_CAP = 200


def _fix_watch(state: dict, lesson: str, folder: Path, heading: str, now: datetime | None) -> None:
    rec = state.setdefault(lesson, {})
    rec.setdefault("fixed_since", (now or datetime.now()).isoformat(timespec="minutes"))
    watch = state.setdefault("fix_watch", [])
    watch.append({"lesson": lesson, "folder": str(folder), "heading": heading, "stops": 0})
    state["fix_watch"] = watch[-_FIX_CAP:]


def _fixed(lesson: str, book: Path, heading: str | None = None) -> bool | None:
    """Is the violation gone from the entry Stop asked about -- found by its heading, the newest
    one when it is not there? None: the logbook cannot be read. Only the newest was read, so a
    claim fixed in the session's second entry was counted not fixed (row 71, after row 59)."""
    try:
        text = book.read_text("utf-8-sig")
        saved = datetime.fromtimestamp(book.stat().st_mtime)
    except OSError:
        return None
    top = top_entry(text)
    if top is None:
        return None
    if lesson != "L1":          # L1's fix changes the heading: the newest entry is the answer
        top = next((e for e in _all_entries(text) if e[0] == heading), top)
    heading, body = top
    if lesson == "L1":
        m = _HEADING.match(heading)
        if not m.group(2):
            return False      # the hour deleted is not the hour read from the clock (row 62)
        try:
            when = _day(m.group(1)).replace(hour=int(m.group(2)), minute=int(m.group(3)))
        except ValueError:
            return False
        return abs((when - saved).total_seconds() / 60) <= L1_SLACK_MINUTES
    if lesson == "L3":
        return claims_first(body)
    return tests_listed(body)


def fix_check(name: str, now: datetime | None = None) -> None:
    """One Stop's look at every ask still watched. Never raises."""
    try:
        ss = _ss()
        state = ss.lessons_load()
        watch = state.get("fix_watch") or []
        if not watch:
            return
        left = []
        for w in watch:
            fixed = _fixed(w.get("lesson", ""), Path(w.get("folder", "")) / name, w.get("heading"))
            w["stops"] = w.get("stops", 0) + 1
            if fixed:
                ss.lesson_event(state, w["lesson"], "fixed_after", now)
            elif w["stops"] >= FIX_STOPS:
                ss.lesson_event(state, w["lesson"], "not_fixed_after", now)
            else:
                left.append(w)
        state["fix_watch"] = left
        ss.lessons_save(state)
    except Exception:
        pass          # counting is a courtesy; never a reason to fail the session


def _state_dir() -> Path:
    """Per-session state (ZA-OPRAVYANE row 53): `sessions/` beside Baton's other state --
    ${CLAUDE_PLUGIN_DATA} for the plugin, next to the hooks for install.sh. It was the shared temp
    folder, written 0644, holding task names and entry headings any local user could read."""
    base = os.environ.get("BATON_STATE_DIR")
    return Path(base) if base else _local_file("sessions")


def _write_private(path: Path, text: str) -> None:
    """Write a state file only its owner can read (0600), a file an older version left too."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w",
                   encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, 0o600)


def _state(session: str) -> Path:
    base = _state_dir()
    safe = "".join(ch for ch in session if ch.isalnum() or ch in "-_")[:80] or "nosession"
    return base / f"baton-stop-{safe}.json"


def _already_asked(session: str) -> set:
    try:
        return set(json.loads(_state(session).read_text("utf-8")))
    except Exception:
        return set()


def _remember(session: str, asked: set) -> None:
    try:
        _write_private(_state(session), json.dumps(sorted(asked)))
        # The temp folder was cleaned by the system; this one is not. A week is past any session.
        for old in _state_dir().glob("baton-*.json"):
            if time.time() - old.stat().st_mtime > 7 * 86400:
                old.unlink()
    except Exception:
        pass          # state is a courtesy; never a reason to fail the session


# Does the hand-back do any work? (ZA-OPRAVYANE row 27, 2026-10-21.) Nothing counted it: a turn
# handed back and then let through with `stop_hook_active` left no trace. Three numbers, kept
# with the lessons: entries the agent wrote unasked; turns handed back for unrecorded work; and
# of those, recorded on the second try or passed without an entry. /baton-doctor shows them.
def _count(**kinds) -> None:
    try:
        ss = _ss()
        state = ss.lessons_load()
        rec = state.setdefault("handback", {})
        for kind, n in kinds.items():
            if n:
                rec[kind] = rec.get(kind, 0) + n
        if any(kinds.values()):
            rec.setdefault("since", datetime.now().isoformat(timespec="minutes"))
            ss.lessons_save(state)
    except Exception:
        pass          # counting is a courtesy; never a reason to fail the session


HANDED_BACK_AGAIN = "handback:2"     # in the session's asked set: this turn's second is spent


def second_try(payload: dict) -> tuple[str | None, list]:
    """The turn after a hand-back (`stop_hook_active`): was the work recorded, or passed?
    Returns (a note for the human, the folders to hand back once more). Row 115: a folder with
    no new entry after the first hand-back is handed back a second time; after the second it
    is counted as passed. Two per turn, by Baton's own count."""
    session = str(payload.get("session_id") or "")
    asked = _already_asked(session)
    pending = {a[len("blocked:"):] for a in asked if a.startswith("blocked:")}
    if not pending:
        return None, []
    root, name = config()
    if not root.is_dir():
        return None, []
    since = session_started(str(payload.get("transcript_path") or ""))
    unrecorded(root, name, since, str(payload.get("transcript_path") or ""))
    # Judged by the logbook, not by `unrecorded`'s verdict: a folder whose newest file was saved
    # seconds ago is left out of it by the grace period, recorded or not.
    wrote = set(TOPPED)
    still = sorted(pending - wrote)
    if still and HANDED_BACK_AGAIN not in asked:
        _count(recorded_after=len(pending & wrote))
        _remember(session, {a for a in asked if not a.startswith("blocked:")}
                  | {"blocked:" + f for f in still} | {HANDED_BACK_AGAIN})
        return None, still
    _count(recorded_after=len(pending & wrote), passed=len(still))
    # The directories come from the first hand-back: at this pass a writer still at work has a file
    # inside the grace period, and the folder's files are not looked at (row 141).
    seen = {"passed:" + a[len("dir:"):] for a in asked
            if a.startswith("dir:") and any(a.startswith(f"dir:{f}:") for f in still)}
    _remember(session, {a for a in asked if not a.startswith(("blocked:", "dir:"))
                        and a != HANDED_BACK_AGAIN}
              | seen | {_passed(f, rel) for f in still for rel in NEWER.get(f, [])})
    return (lost_note(LOST, FORGOT) if LOST or FORGOT else None), []


# Let through, then asked again every turn (ZA-OPRAVYANE row 141, 10.11): a background agent of the
# session wrote into `v0.3.0/mer/` every minute, and each turn handed the folder back twice for an
# answer already given -- "no entry needed, already described", 8+ times in an hour. A folder a turn
# let through without an entry keeps, for this session, the directories its new files were in. While
# its new files stay in them it is not handed back; a file anywhere else in it, or a new entry in its
# logbook, ends that. Said to the human once; the next session's board still lists the folder.
def _passed(folder: str, rel: str) -> str:
    return f"passed:{folder}:{os.path.dirname(rel).replace(os.sep, '/')}"


def let_through(stale: list, asked: set) -> tuple[list, list]:
    """(folders still to hand back, folders let through before whose new files are all where
    they were then)."""
    keep, quiet = [], []
    for item in stale:
        f = _folder_of(item)
        files = NEWER.get(f) or []
        (quiet if files and all(_passed(f, r) in asked for r in files) else keep).append(item)
    return keep, quiet


def answer_check(payload: dict) -> str | None:
    """The entry written in answer to a hand-back (ZA-OPRAVYANE row 55, 22.10): the moment an agent
    writes an entry just to get past, and the one entry nothing checked -- this pass only counted,
    and the next session's Stop skips an entry saved before it began. The first pass's quality
    checks (hollow, L1, L3, L4), said once to the human; never a second hand-back."""
    root, name = config()
    if not root.is_dir():
        return None
    transcript = str(payload.get("transcript_path") or "")
    since = session_started(transcript)
    session = str(payload.get("session_id") or "")
    asked = _already_asked(session)
    said = []
    try:
        said += [f"{t} (L1)" for t in hand_typed_hours(root, name, since=since, transcript=transcript)]
    except Exception:
        pass
    try:
        thin = [h for h in hollow_entries(root, name, since, transcript)
                if f"hollow:{h[0]}:{h[1]}" not in asked]
        said += [f"{f}: \"{h[3:60].strip()}\" looks hollow -- " + "; ".join(r) for f, h, r in thin]
        _remember(session, _already_asked(session) | {f"hollow:{f}:{h}" for f, h, _ in thin})
    except Exception:
        pass
    for lesson, find, what in (("L3", visibility_entries, "says something is public or private"),
                               ("L4", tests_entries, "says tests pass")):
        try:
            said += [f"{f}: \"{h[3:60].strip()}\" {what} ({', '.join(w[:3])}) and does not list it "
                     f"under `### Claims to verify` ({lesson})"
                     for f, h, w in first_asks(find(root, name, since, transcript), root, lesson=lesson)]
        except Exception:
            pass
    if not said:
        return None
    return ("Baton, on the entry written in answer to the hand-back (its quality is not handed "
            "back again, so this is not asked of the agent): " + "; ".join(said) + ".")


def _folder_of(item: str) -> str:
    """The folder a listed item names -- "<folder> (newest: x)", "<folder> (no <logbook> at all;
    newest: x)", "<folder> (top entry: ...)". The first " (" was taken for its end, so `report (v2)`
    became `report` and the hand-back was counted against the wrong name (row 63)."""
    m = re.match(r"(.*?) \((?:newest: |no .*? at all; newest: |top entry: )", item)
    return m.group(1) if m else item


def _batch():
    """The PostToolBatch hook's module: lesson L2 and what came after its note."""
    spec = importlib.util.spec_from_file_location(
        "baton_batch", Path(__file__).with_name("baton_batch.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# A turn that changed no task file passes every check above, however much was decided in it
# (ZA-OPRAVYANE row 26; the owner, 24.10: ask in the same session, not at the next start). Six
# messages since this session's last entry, twice SessionStart's three: this one is asked
# mid-session and again every six, and a question every third message is the reminder nobody reads.
CHAT_EVERY = 6


_CHAT: dict = {}


def _chat_since_entry(transcript: str, folders: list, name: str):
    """SessionStart's chat_since_entry, read once per run: the chat file and chat_ask both ask."""
    if transcript not in _CHAT:
        _CHAT[transcript] = _ss().chat_since_entry(transcript, folders, name)
    return _CHAT[transcript]


# The chat after the last entry survives /clear and a restart (ZA-OPRAVYANE row 124, the owner,
# 07.11). Measured that day: the previous session was 48 MB, ~712,000 characters of words alone,
# 332 messages from the human -- none of it reached the next session unless an entry held it.
# At every Stop the human's messages and the agent's text replies since the last entry headed in
# this session's time -- chat_since_entry's cut, the one Stop's ask uses -- are written to
# `<task root>/.baton-chat/<session>.md`, newest CHAT_KEEP characters, masked. No tool call, no
# tool output. An entry written trims it (the part before it is recorded); nothing left after one,
# the file goes. SessionStart (startup, clear) hands it to the next session and removes it.
# Stop, not UserPromptSubmit: only Stop sees the reply that closes the turn. A turn the human
# interrupts runs no Stop, so its last exchange is missing. Claude Code's own .jsonl is only read.
CHAT_DIR = ".baton-chat"
CHAT_KEEP = 40_000


def _replies(transcript: str, after) -> list:
    """(when, text) of the agent's text replies at or after `after`, in the transcript's tail."""
    ss, out = _ss(), []
    path = Path(transcript)
    with open(path, "rb") as fh:
        size = path.stat().st_size
        if size > ss.QUIET_MAX_BYTES:
            fh.seek(size - ss.QUIET_MAX_BYTES)
            fh.readline()
        for raw in fh:
            if b'"assistant"' not in raw or b'"text"' not in raw:
                continue
            try:
                obj = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if not isinstance(obj, dict) or obj.get("type") != "assistant" or obj.get("isSidechain"):
                continue
            when = ss._local_time(obj.get("timestamp"))
            content = (obj.get("message") or {}).get("content")
            if when is None or when < after or not isinstance(content, list):
                continue
            text = "\n".join(str(b.get("text", "")) for b in content
                             if isinstance(b, dict) and b.get("type") == "text").strip()
            if text:
                out.append((when, text))
    return out


def save_chat(payload: dict) -> None:
    """Write this session's chat since its last entry to CHAT_DIR, or remove it when none is left."""
    root, name = config()
    session = re.sub(r"[^\w-]", "", str(payload.get("session_id") or ""))[:80]
    transcript = str(payload.get("transcript_path") or "")
    if not root.is_dir() or not session or not transcript or _baton is None:
        return
    path = root / CHAT_DIR / f"{session}.md"
    folders = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    found = _chat_since_entry(transcript, folders, name)
    if found is None:
        return                              # cannot read: leave what is there
    if not found[0]:
        if path.is_file():
            path.unlink()
        return
    said = [(w, "human", t) for w, t in found[0]] + \
        [(w, "agent", t) for w, t in _replies(transcript, found[0][0][0])]
    lines = [f"**{who} {w:%Y-%m-%d %H:%M}:** {_baton.mask_secrets(t)}\n"
             for w, who, t in sorted(said, key=lambda s: s[0])]
    body = "".join(lines)[-CHAT_KEEP:]
    pid = _baton.claude_pid()
    head = json.dumps({"session": session, "pid": pid, "project": str(Path(transcript).parent)},
                      ensure_ascii=False)
    _write_private(path, f"<!-- baton-chat {head} -->\n" + body)


def chat_ask(root: Path, name: str, transcript: str, session: str) -> str | None:
    """The note to hand back when the human has said CHAT_EVERY or more things since the last
    entry written in this session; None otherwise, and when the transcript cannot be read."""
    try:
        folders = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
        found = _chat_since_entry(transcript, folders, name)
        if not found or len(found[0]) < CHAT_EVERY:
            return None
        said, total = found
        # A logbook saved after the turn's message: this turn wrote an entry, whatever its heading
        # says (lesson L1 -- hand-typed hours were wrong by hours).
        if any((f / name).is_file() and (f / name).stat().st_mtime >= said[-1][0].timestamp()
               for f in folders):
            return None
        asked = _already_asked(session)
        before = max((int(a[5:]) for a in asked if a.startswith("chat:") and a[5:].isdigit()),
                     default=0)
        if total - before < CHAT_EVERY:
            return None
        _remember(session, asked | {f"chat:{total}"})
        return (f"Baton: no task file changed, and the human has typed {len(said)} messages since "
                f"the last {name} entry headed in this session's time -- a decision made only in "
                "chat leaves no trace. They began: " + _ss().quote([t for _, t in said]) + ". Ask "
                "the human once, in their language, whether any of it should be recorded and in "
                f"which task; if not, finish. (Asked once per {CHAT_EVERY} messages.)")
    except Exception:
        return None               # a count that cannot read must not cost the session


def _ledger() -> None:
    """The ledger (row 153): a line for each entry not yet in it. Only on a Stop that lets the
    turn through: an entry a hand-back of this turn asked to correct is recorded corrected, not
    as written first. Off with `"ledger": false`. Says nothing; never raises."""
    try:
        root, name = config()
        d = _baton.ledger_dir(_local_file)
        if d is not None and root.is_dir():
            _baton.ledger_update(root, name, _ss().task_folders(root), d)
    except Exception:
        pass


def _stands_down() -> bool:
    """Installed twice (see installed_twice in SessionStart): this plugin copy stays quiet."""
    try:
        spec = importlib.util.spec_from_file_location(
            "baton_session_start", Path(__file__).with_name("baton_session_start.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return bool(mod.installed_twice())
    except Exception:
        return False


def main() -> int:
    if _stands_down():
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = None
    # Broken JSON, `[]`, `null`: no payload, not a crash (row 67) -- and no run (row 70). Read as
    # `{}` it had no session start, so every folder's old debt was handed back to this turn.
    if not isinstance(payload, dict):
        return 0
    global HOST
    HOST = _baton.host(payload, os.environ)
    # "again": the pass after a hand-back (`stop_hook_active`). Any Stop counts as the end of the
    # turn; two in one turn are by design, so the doctor does not count them (row 49). Whether
    # and when Claude Code resets the flag is not documented, and nothing here depends on it.
    _turn("Stop", payload.get("session_id"), "again" if payload.get("stop_hook_active") else "")
    try:      # an L2 note shown this turn and no tool call after it: the turn ended (row 40)
        _batch().followed(str(payload.get("session_id") or ""), None)
    except Exception:
        pass
    try:      # the chat after the last entry, for the next session (row 124)
        save_chat(payload)
    except Exception:
        pass

    # Already handed back this turn: count what came of it, and hand back once more only when
    # the first produced no entry (row 115). Never a third time.
    if payload.get("stop_hook_active"):
        try:
            lost, again = second_try(payload)
        except Exception:
            lost, again = None, []
        fix_check(config()[1])        # the hand-back's answer lands here (row 44)
        try:
            checked = answer_check(payload)
        except Exception:
            checked = None            # a quality check that cannot read must not cost the session
        try:      # the entry the hand-back asked for may say tests pass: its pinned run (row 43)
            root, name = config()
            tested = _ss().tests_results() + (pinned_runs(
                root, name, session_started(str(payload.get("transcript_path") or "")),
                str(payload.get("session_id") or ""),
                str(payload.get("transcript_path") or ""))[0] if root.is_dir() else [])
        except Exception:
            tested = []
        lost = " ".join(filter(None, (lost, checked, *tested)))
        out = {"systemMessage": lost} if lost else {}
        if not again:
            _ledger()             # the turn is let through: its entries as they end it
        if again:
            listed = "\n".join(f"  - {folder}" for folder in again)
            out.update(decision="block", reason=(
                f"Baton, a second and last time this turn: these task folders still have no new "
                f"entry in their {config()[1]} after the hand-back:\n{listed}\n\n"
                "Prepend the entry now -- what was asked, what was done, the result, what is "
                "open. If you already said the change needs none, say it once more in one line "
                "and finish; the turn is let through after this either way."))
        if out:           # the quality checks: a message for the human, never their own hand-back
            sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
            sys.stdout.flush()
        return 0

    root, name = config()
    if not root.is_dir():
        return 0
    fix_check(name)               # before this Stop's own asks: they are judged from the next one

    transcript = str(payload.get("transcript_path") or "")
    since = session_started(transcript)
    stale = unrecorded(root, name, since, transcript)
    session = str(payload.get("session_id") or "")
    asked = _already_asked(session)
    ended = {a for a in asked if any(a.startswith(f"passed:{f}:") for f in TOPPED)}
    if ended:                     # a new entry in the folder: what was let through is over (row 141)
        asked -= ended
        _remember(session, asked)
    stale, quiet = let_through(stale, asked)
    quiet = [_folder_of(f) for f in quiet]
    if since is not None:         # without a session start, an entry cannot be called this one's
        stale_names = {_folder_of(f) for f in stale}
        _count(unasked=sum(1 for f in GREW if f not in stale_names
                           and (root / f / name).stat().st_mtime >= since))
    open_ended = [f for f in undefined(root, name, str(payload.get("transcript_path") or "")) if f not in asked]
    ahead = [f for f in future_dated(root, name) if f"future:{f}" not in asked]
    try:
        typed = hand_typed_hours(root, name, since=since, transcript=transcript)
    except Exception:
        typed = []            # a lesson that cannot count must not cost the session
    typed = [t for t in typed if not any(t.startswith(_folder_of(f) + ":") for f in ahead)]
    flagged = {_folder_of(f) for f in stale}
    try:
        thin = [h for h in hollow_entries(root, name, since, transcript)
                if h[0] not in flagged and f"hollow:{h[0]}:{h[1]}" not in asked]
    except Exception:
        thin = []             # a quality check that cannot read must not cost the session
    try:
        refuted_claims(root, name, since, transcript=transcript)
        claims = first_asks([v for v in visibility_entries(root, name, since, transcript)
                             if v[0] not in flagged], root)
    except Exception:
        claims = []           # a lesson that cannot count must not cost the session
    try:
        passes = first_asks([v for v in tests_entries(root, name, since, transcript)
                             if v[0] not in flagged],
                            root, lesson="L4")
    except Exception:
        passes = []           # the same
    try:      # L4 against a pinned command (row 43): results that came in, runs to start
        tested = _ss().tests_results()
        more, running = pinned_runs(root, name, since, session, transcript)
        tested += more
    except Exception:
        tested, running = [], set()   # a run that cannot start must not cost the session
    try:          # row 73: the repository a `code:` field names, beside the entry
        code = [c for c in code_changes(root, name, since, transcript) if f"code:{c[0]}" not in asked]
    except Exception:
        code = []
    if code:
        said = "; ".join(
            f"{f}: {repo} holds {what}" if what else f"{f}: git could not read {repo}"
            for f, repo, what in code)
        tested.append(f"Baton: the `code:` repository of a logbook written this session has changes "
                      f"newer than the logbook -- {said}. The entry is the claim and the repository "
                      "the evidence: read them side by side. (Said once a session per folder.)")
        _remember(session, _already_asked(session) | {f"code:{c[0]}" for c in code})
    rewritten = [f for f in REWRITTEN if f"rewrite:{f}" not in asked]
    # Row 35: a folder the walk stopped in may hold newer work than it saw. Not a hand-back --
    # the agent cannot settle it in this turn -- but never a silent pass: said once a session.
    unread = [f for f in TRUNCATED if f"unread:{f}" not in asked]
    note = {}
    if unread:
        note = {"systemMessage": unread_note(unread)}
        _remember(session, _already_asked(session) | {f"unread:{f}" for f in unread})
    try:
        hidden = [h for h in ignored_this_session(root, name, since) if f"ignore:{h[0]}" not in asked]
    except Exception:
        hidden = []           # a check that cannot read must not cost the session
    if hidden:
        listed = "; ".join(f"{f}: " + ", ".join(files[:3]) + (", ..." if len(files) > 3 else "")
                           for f, files in hidden)
        said = (f"Baton: a .batonignore saved in this session hides files saved in it, so Stop "
                f"did not ask about them -- {listed}. A .batonignore line is for a file that "
                "changes on its own; if this one was added to get past the check, the work has "
                "no entry.")
        note = {"systemMessage": " ".join(filter(None, (note.get("systemMessage"), said)))}
        _remember(session, _already_asked(session) | {f"ignore:{f}" for f, _ in hidden})
    foreign = [f for f in sorted(FOREIGN) if f"foreign:{f}" not in asked]   # never a silent pass
    if foreign:
        listed = "; ".join(f"{f}: {_named(FOREIGN[f])}" for f in foreign)
        said = (f"Baton: files saved during this session that none of its tool calls touched -- "
                f"another session, a scheduled job or an editor -- were not handed back: {listed}. "
                "If they stay without an entry, the next session's board lists them.")
        note = {"systemMessage": " ".join(filter(None, (note.get("systemMessage"), said)))}
        _remember(session, _already_asked(session) | {f"foreign:{f}" for f in foreign})
    hushed = [f for f in quiet if f"quiet:{f}" not in asked]
    if hushed:
        listed = "; ".join(f"{f}: " + ", ".join(sorted({os.path.dirname(r) or "." for r in NEWER[f]}))
                           for f in hushed)
        said = (f"Baton: not handed back again this session -- folders an earlier turn let through "
                f"without an entry keep changing in the same places ({listed}), as a background job "
                f"does. A file elsewhere in them, or a new entry, ends this; without an entry the "
                f"next session's board lists them.")
        note = {"systemMessage": " ".join(filter(None, (note.get("systemMessage"), said)))}
        _remember(session, _already_asked(session) | {f"quiet:{f}" for f in hushed})
    try:      # Р5: a .baton-pulled saved this session is also a way past the check -- said once
        fresh = [f for f in sorted(PULLED) if f"pulled:{f}" not in asked and since is not None
                 and (root / f / PULLED_FILE).stat().st_mtime >= since]
    except OSError:
        fresh = []
    if fresh:
        listed = "; ".join(f"{f}: " + ", ".join(sorted(PULLED[f])[:3])
                           + (", ..." if len(PULLED[f]) > 3 else "") for f in fresh)
        said = (f"Baton: files a sync checked out this session were not counted as this session's "
                f"work ({PULLED_FILE}) -- {listed}. A file changed here counts again; if the list "
                "was written to get past the check, the work has no entry.")
        note = {"systemMessage": " ".join(filter(None, (note.get("systemMessage"), said)))}
        _remember(session, _already_asked(session) | {f"pulled:{f}" for f in fresh})
    locked = [f for f in _ss().UNREADABLE if f"locked:{f}" not in asked]    # row 54, the same way
    if locked:
        note = {"systemMessage": " ".join(filter(None, (note.get("systemMessage"),
                                                         _ss().unreadable_note(locked))))}
        _remember(session, _already_asked(session) | {f"locked:{f}" for f in locked})
    if LOST or FORGOT:    # row 37: to the human, once (the memory has moved on); never a hand-back
        note = {"systemMessage": " ".join(filter(None, (note.get("systemMessage"),
                                                         lost_note(LOST, FORGOT))))}
    if tested:
        note = {"systemMessage": " ".join(filter(None, (note.get("systemMessage"), *tested)))}
    if (not stale and not open_ended and not ahead and not typed and not thin and not claims
            and not passes and not rewritten):
        chat = chat_ask(root, name, str(payload.get("transcript_path") or ""), session)
        if not chat:
            _ledger()             # the turn is let through: its entries as they end it
        if chat:
            sys.stdout.buffer.write(json.dumps({"decision": "block", "reason": chat, **note},
                                               ensure_ascii=False).encode("utf-8"))
            sys.stdout.flush()
            return 0
        if note:
            sys.stdout.buffer.write(json.dumps(note, ensure_ascii=False).encode("utf-8"))
            sys.stdout.flush()
        return 0

    parts = []
    if stale:
        listed = "\n".join(f"  - {folder}" for folder in stale)
        parts.append(
            f"Baton: these task folders hold work newer than their {name}:\n"
            f"{listed}\n\n"
            f"Prepend an entry to each one's {name} before finishing — what was "
            "asked, what was done, the result, and what is still open. Write it for "
            "the next session, which will have none of this conversation.\n\n"
            "If the change was incidental and genuinely needs no entry, say so in one "
            "line and finish.")
        _count(handed_back=len(stale))
        # A new turn: its hand-back is the only one pending. A turn the human interrupted after
        # its hand-back ran no second Stop, and its marks would be handed back here (row 115).
        _remember(session, {a for a in _already_asked(session)
                            if not a.startswith(("blocked:", "dir:")) and a != HANDED_BACK_AGAIN}
                  | {"blocked:" + _folder_of(f) for f in stale}
                  | {"dir:" + _passed(_folder_of(f), r)[len("passed:"):]
                     for f in stale for r in NEWER.get(_folder_of(f), [])})
    if open_ended:
        listed = "\n".join(f"  - {folder}" for folder in open_ended)
        parts.append(
            f"Baton: these tasks were worked on now, and their {name} header does not say "
            f"when they are finished:\n{listed}\n\n"
            "Add `done_when:` to the header (or `kriterii_zavarshvane:`) — one sentence a person could check. "
            "If it is not known yet, ask the human rather than inventing one. "
            "(Asked once per session.)")
        _remember(session, _already_asked(session) | set(open_ended))
    if ahead:
        listed = "\n".join(f"  - {folder}" for folder in ahead)
        parts.append(
            f"Baton: these {name} files have a newest entry headed LATER than the clock "
            f"({datetime.now():%Y-%m-%d %H:%M}):\n{listed}\n\n"
            "Read the time from the clock (`date`) and correct the heading -- a record whose "
            "date is wrong is wrong about the one thing a record is for. (Asked once per session.)")
        _remember(session, _already_asked(session) | {f"future:{f}" for f in ahead})
    if typed:
        rec = _ss().lessons_load().get("L1", {})
        listed = "\n".join(f"  - {t}" for t in typed)
        # The lesson says "tools/baton_entry.py"; an agent's working directory is not this
        # plugin's, so the hand-back gives the path that actually runs -- when there is one.
        tool = _ss().entry_tool()
        where = (f" On this machine that is\n"
                 f"  python3 \"{tool}\" <logbook> <entry-file> --title \"<title>\"\n"
                 f"(the entry file holds the body only; the heading is stamped from the clock)."
                 ) if tool else ""
        parts.append(
            f"Baton, lesson L1 -- a new entry's hour does not match the clock "
            f"({datetime.now():%Y-%m-%d %H:%M}):\n{listed}\n\n"
            f"{_ss().LESSONS['L1']}{where} "
            f"Correct the heading. "
            f"(Counted: caught {rec.get('caught', 0)} of {rec.get('fired', 0)} new entries.)")
    if thin:
        listed = "\n".join(f"  - {f}: \"{h[3:60].strip()}\" -- " + "; ".join(r)
                           for f, h, r in thin)
        parts.append(
            f"Baton: the newest entry in these {name} files looks hollow:\n{listed}\n\n"
            "A hook can see that an entry exists, not that it is good; these are the two things "
            "it can measure. Rewrite the entry so the next session can act on it: what was asked, "
            "what was done (name the files), the result, what is open. If it is right as it "
            "stands, say so in one line. (Asked once per entry.)")
        _remember(session, _already_asked(session) | {f"hollow:{f}:{h}" for f, h, _ in thin})
    if claims:
        rec = _ss().lessons_load().get("L3", {})
        listed = "\n".join(f"  - {f}: \"{h[3:60].strip()}\" says " + ", ".join(w[:3])
                           for f, h, w in claims)
        parts.append(
            f"Baton, lesson L3 -- the newest entry in these {name} files says something is public "
            f"or private:\n{listed}\n\n"
            "Open the entry with a short section, before the others: `### Claims to verify` (or "
            "`### За проверка`), one line per claim about what is public or private, each checked "
            "against the source (the repository's or the page's own visibility setting) -- the "
            "human reads that section, not the prose. If a listed claim later "
            "proves wrong, the new entry's section says `refuted: <the claim>`; only that is "
            "counted as caught. If the word is not a claim here, say so in one line. "
            f"(Asked once per entry. Counted: caught {rec.get('caught', 0)} of "
            f"{rec.get('fired', 0)} asked.)")
    if passes:
        rec = _ss().lessons_load().get("L4", {})
        listed = "\n".join(f"  - {f}: \"{h[3:60].strip()}\" says " + ", ".join(w[:3])
                           for f, h, w in passes)
        parts.append(
            f"Baton, lesson L4 -- the newest entry in these {name} files says tests pass:\n"
            f"{listed}\n\n"
            "List it in a short section at the top of the entry, before the others: `### Claims to "
            "verify` (or `### За проверка`), one line with the command that showed it and the "
            "result line it printed -- the human reads that section, not the prose. If the claim "
            "later proves wrong, the new entry's section says `refuted: <the claim>`; only that is "
            "counted as caught. If it is not a claim here, say so in one line. "
            + (f"For {', '.join(sorted(running))}, the test command a human pinned runs after "
               "this turn, and its result is set beside the claim. " if running else "")
            + f"(Asked once per entry. Counted: caught {rec.get('caught', 0)} of "
            f"{rec.get('fired', 0)} asked.)")
    if rewritten:
        parts.append(
            f"Baton: an older entry changed in the {name} of " + ", ".join(rewritten) + " -- "
            "not a new entry at the top. A logbook is a record and does not get edited, so this "
            "does not count as recording the work. If something in it was wrong, leave it and add "
            "a new entry at the top that says what changed and why. (Said once.)")
        _remember(session, _already_asked(session) | {f"rewrite:{f}" for f in rewritten})
    # UTF-8, not \\uXXXX, and as bytes: a cp1252 pipe on Windows cannot raise (v3.12.0).
    sys.stdout.buffer.write(json.dumps({"decision": "block", "reason": "\n\n".join(parts),
                                        **note}, ensure_ascii=False).encode("utf-8"))
    sys.stdout.flush()
    return 0


def _turn(event: str, session: object, extra: str = "") -> None:
    """One line in `baton.turns/<session>`: `turn` in hooks/_baton.py. Never raises."""
    if _baton is not None:
        _baton.turn(__file__, event, session, extra)


_HEARTBEAT = _baton.Heartbeat(__file__) if _baton else None


def _start() -> None:
    if _HEARTBEAT is not None:
        _HEARTBEAT.start()


def _beat(crash: BaseException | None = None) -> None:
    if _HEARTBEAT is not None:
        _HEARTBEAT.beat(crash)







if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--run-tests":
        try:                                  # the background test runner: not a run of Stop
            sys.exit(run_tests(sys.argv[2]))
        except Exception:
            sys.exit(0)
    if _baton is None:
        # config() lives in _baton.py, so without it there is nothing this hook can do. Said
        # on stderr with exit 1: a non-blocking error the host shows, never a block (that is 2).
        print(f"Baton: {Path(__file__).name} could not load _baton.py beside it; "
              "the hook did not run.", file=sys.stderr)
        sys.exit(1)
    _start()
    try:
        code = main()
    except Exception as exc:
        # A hook must never break the session it is trying to help -- but the crash is left
        # for /baton-doctor and the next SessionStart (row 36).
        _beat(exc)
        _ledger()             # a crash lets the turn through too: the ledger still records
        sys.exit(0)
    _beat()
    sys.exit(code)
