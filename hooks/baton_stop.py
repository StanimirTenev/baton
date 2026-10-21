#!/usr/bin/env python3
"""Baton Stop hook.

Catches the failure Baton exists to prevent: work happened inside a task folder and
no logbook entry was written for it.

A folder is "unrecorded" when it holds a file newer than its own logbook. That is a
narrow test on purpose — a session that touched no task folder is never interrupted.

When something is unrecorded the turn is handed back to the agent with a note naming the
folder. `stop_hook_active` is honoured, so this can block at most once per turn and can
never trap a session in a loop.
"""
from __future__ import annotations   # `str | None`, `list[str]`: Python 3.8 and 3.9 too
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

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


def ignore_patterns(folder: Path) -> list[str]:
    """Globs from a .batonignore in the task folder (gitignore-style, one per line,
    '#' comments). Use it for files that legitimately change without needing a logbook
    entry — a live transcript, a rotating log, generated output."""
    try:
        lines = (folder / ".batonignore").read_text("utf-8-sig").splitlines()
    except OSError:
        return []
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def is_ignored(rel: str, name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(name, p) for p in patterns)


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
    """Task root and logbook name: env var, then baton.local.json next to this file,
    then the defaults — the same resolution the SessionStart hook uses."""
    cfg = {}
    try:
        cfg = json.loads((_local_file("baton.local.json")).read_text("utf-8-sig"))
    except Exception:
        cfg = {}
    home = (os.environ.get("BATON_HOME") or os.environ.get("CLAUDE_PLUGIN_OPTION_TASKS_FOLDER")
            or cfg.get("home") or str(Path.home() / "tasks"))
    logbook = (os.environ.get("BATON_LOGBOOK") or os.environ.get("CLAUDE_PLUGIN_OPTION_LOGBOOK")
               or cfg.get("logbook") or "LOGBOOK.md")
    return Path(home).expanduser(), logbook


def newest_work(folder: Path, logbook: str) -> tuple[float, str]:
    """Newest work-file mtime in the folder, and that file's name. Skips the logbook,
    dotfiles, SKIP_DIRS, and anything matched by the folder's .batonignore."""
    patterns = ignore_patterns(folder)
    newest, newest_name = 0.0, ""
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name == logbook or name.startswith("."):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), folder)
            if is_ignored(rel, name, patterns):
                continue
            try:
                m = (Path(dirpath) / name).stat().st_mtime
            except OSError:
                continue
            if m > newest:
                newest, newest_name = m, rel
    return newest, newest_name


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


def unrecorded(root: Path, name: str, since: float | None = None) -> list[str]:
    """Folders whose work is newer than their logbook. With `since`, only work saved after
    it: 2026-10-01, external review of v3.10.0 -- an old unrecorded file in an unrelated task
    blocked every turn of a session that never touched it. Stop asks about this session's
    work; the older debt is listed on the board instead."""
    out = []
    REWRITTEN.clear()
    GREW.clear()
    TOPPED.clear()
    path = _bodies_path()
    try:
        bodies = json.loads(path.read_text("utf-8"))
    except Exception:
        bodies = {}
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
            if logbook.is_file():
                out.append(f"{folder.name} (newest: {newest_name})")
            else:
                out.append(f"{folder.name} (no {name} at all; newest: {newest_name})")
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


def undefined(root: Path, name: str) -> list[str]:
    out = []
    now = time.time()
    for folder in _ss().task_folders(root):
        logbook = folder / name
        if not logbook.is_file():
            continue          # no logbook at all is `unrecorded`'s finding, not this one
        work, _ = newest_work(folder, name)
        touched = max(work, logbook.stat().st_mtime)
        if now - touched <= RECENT_SECONDS and not _criterion(logbook):
            out.append(folder.name)
    return out


# 2026-09-28, 20:04 by the clock: six logbooks' top entries were headed 22:30, 23:40 and
# "2026-09-29 00:50" -- typed by the agent, not read from a clock. A few minutes of slack
# for a heading written just before it was saved.
FUTURE_SLACK_SECONDS = 600
_HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}):(\d{2}))?")


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
                day = datetime.strptime(m.group(1), "%Y-%m-%d")
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
                     since: float | None = None) -> list[str]:
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
        ss.lesson_event(state, "L1", "fired", now)
        m = _HEADING.match(line)
        if not m.group(2):
            continue                          # a date without an hour: nothing to compare
        try:
            when = datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        off = (when - saved).total_seconds() / 60
        if abs(off) > L1_SLACK_MINUTES:
            ss.lesson_event(state, "L1", "caught", now)
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
                day = datetime.strptime(m.group(1), "%Y-%m-%d")
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
    patterns = ignore_patterns(folder)
    out = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name == logbook or name.startswith("."):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), folder)
            if is_ignored(rel, name, patterns):
                continue
            try:
                if (Path(dirpath) / name).stat().st_mtime >= since:
                    out.append(rel.replace(os.sep, "/"))
            except OSError:
                continue
    return sorted(out)


def _names(rel: str) -> set:
    """What counts as naming a file: its name, its stem, or a folder it sits in."""
    p = Path(rel)
    return {n for n in (p.name, p.stem, *p.parent.parts) if len(n) >= MIN_NAME_CHARS}


def hollow(body: str, files: list[str], session_text: str | None = None) -> list[str]:
    """Why an entry body looks written only to pass. Empty when nothing measurable is wrong.
    The files may be named anywhere in `session_text` (this session's entries), else in `body`."""
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
    return reasons


def _changed_tops(root: Path, name: str, since: float | None):
    """(folder, text, top entry) for each logbook whose body this session changed. Without a
    session start nothing: an old entry is history, and one this session did not write is not
    its debt."""
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
        top = top_entry(text)
        if top is not None:
            yield folder, text, top


def hollow_entries(root: Path, name: str, since: float | None) -> list[tuple]:
    """(folder, heading, reasons) for each logbook whose body this session changed and whose
    newest entry looks hollow."""
    out = []
    for folder, text, top in _changed_tops(root, name, since):
        reasons = hollow(top[1], touched_since(folder, name, since),
                         session_entries(text, since))
        if reasons:
            out.append((folder.name, top[0], reasons))
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
_VISIBLE = re.compile(r"(?i)(?<![\w-])(public(?:ly)?|private(?:ly)?|публичен|частен|"
                      r"(?:публичн|частн)(?:о|а|и|ия|ият|ото|ата|ите)?)(?![\w-])")
# Senses of the word that are not a thing's visibility, and mentions that are not claims:
# a span of code (`--private-key`, `"visibility":"PRIVATE"` pasted from a tool), a key in
# cryptography, one word in quotes (the word talked about), and the pair named as a topic
# (`public/private`). Kept to classes, not phrases: a phrase list is fitted to one machine.
_CODE = re.compile(r"`[^`\n]*`")
_KEY = re.compile(r"(?i)(?:public|private)[\s-]+keys?(?![\w-])|(?:публич|част)\w*\s+ключ")
_QUOTED_WORD = re.compile(r"[„“\"«']\s*\w+\s*[“”\"»']")
_PAIR = re.compile(r"\w+(?:\s*/\s*\w+)+")
_CLAIMS = re.compile(r"(?i)^###\s+(?:claims to verify|за проверка)\s*:?\s*$")
_REFUTED = re.compile(r"(?i)^\s*(?:[-*]\s+)?(?:refuted|оборено)\s*:")
_SEEN_CAP = 1000


def visibility_words(text: str) -> list[str]:
    """The words in `text` that say something is public or private, as written."""
    t = _CODE.sub(" ", text)
    for rx in (_KEY, _QUOTED_WORD):
        t = rx.sub(lambda m: " " if _VISIBLE.search(m.group(0)) else m.group(0), t)
    t = _PAIR.sub(lambda m: " " if len(_VISIBLE.findall(m.group(0))) >= 2 else m.group(0), t)
    return [m.group(1) for m in _VISIBLE.finditer(t)]


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


def visibility_entries(root: Path, name: str, since: float | None) -> list[tuple]:
    """(folder, heading, words) for each newest entry this session wrote that says something is
    public or private and does not open with a claims section."""
    out = []
    for folder, _text, (heading, body) in _changed_tops(root, name, since):
        words = visibility_words(heading + "\n" + body)
        if words and not claims_first(body):
            out.append((folder.name, heading, list(dict.fromkeys(words))))
    return out


def _all_entries(text: str) -> list[tuple[str, str]]:
    """Every dated entry, newest first as they stand: (heading, body)."""
    out = []
    for part in re.split(r"(?m)^(?=## )", _body(text)):
        head, _, body = part.partition("\n")
        if _HEADING.match(head):
            out.append((head, body))
    return out


def refuted_claims(root: Path, name: str, since: float | None, now: datetime | None = None) -> int:
    """Count L3 `caught`: a line `refuted: ...` (`оборено: ...`) in a claims section of the
    newest entry this session wrote, in a logbook where an older entry listed claims. Each line
    once. Returns how many were new."""
    ss = _ss()
    state = ss.lessons_load()
    seen = state.setdefault("L3_refuted", [])
    new = 0
    for folder, text, (heading, body) in _changed_tops(root, name, since):
        older = _all_entries(text)[1:]
        if not any(_claims(b) for _h, b in older):
            continue
        for lines in _claims(body):
            for line in lines:
                key = f"{folder}|{heading}|{line.strip()}"
                if _REFUTED.match(line) and key not in seen:
                    seen.append(key)
                    ss.lesson_event(state, "L3", "caught", now)
                    new += 1
    if new:
        state["L3_refuted"] = seen[-_SEEN_CAP:]
        ss.lessons_save(state)
    return new


def first_asks(asks: list[tuple], root: Path, now: datetime | None = None) -> list[tuple]:
    """The entries never asked about before, in any session; each one counts L3 `fired`."""
    ss = _ss()
    state = ss.lessons_load()
    seen = state.setdefault("L3_asked", [])
    out = []
    for ask in asks:
        key = f"{root / ask[0]}|{ask[1]}"
        if key not in seen:
            seen.append(key)
            ss.lesson_event(state, "L3", "fired", now)
            out.append(ask)
    if out:
        state["L3_asked"] = seen[-_SEEN_CAP:]
        ss.lessons_save(state)
    return out


def _state(session: str) -> Path:
    base = Path(os.environ.get("BATON_STATE_DIR") or tempfile.gettempdir())
    safe = "".join(ch for ch in session if ch.isalnum() or ch in "-_")[:80] or "nosession"
    return base / f"baton-stop-{safe}.json"


def _already_asked(session: str) -> set:
    try:
        return set(json.loads(_state(session).read_text("utf-8")))
    except Exception:
        return set()


def _remember(session: str, asked: set) -> None:
    try:
        path = _state(session)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(asked)), "utf-8")
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


def second_try(payload: dict) -> None:
    """The turn after a hand-back (`stop_hook_active`): was the work recorded, or passed?"""
    session = str(payload.get("session_id") or "")
    asked = _already_asked(session)
    pending = {a[len("blocked:"):] for a in asked if a.startswith("blocked:")}
    if not pending:
        return
    root, name = config()
    if not root.is_dir():
        return
    since = session_started(str(payload.get("transcript_path") or ""))
    unrecorded(root, name, since)
    # Judged by the logbook, not by `unrecorded`'s verdict: a folder whose newest file was saved
    # seconds ago is left out of it by the grace period, recorded or not.
    wrote = set(TOPPED)
    _count(recorded_after=len(pending & wrote), passed=len(pending - wrote))
    _remember(session, {a for a in asked if not a.startswith("blocked:")})


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
        payload = {}

    # Already handed the turn back once — do not do it again. Only count what came of it.
    if payload.get("stop_hook_active"):
        try:
            second_try(payload)
        except Exception:
            pass
        return 0

    root, name = config()
    if not root.is_dir():
        return 0

    since = session_started(str(payload.get("transcript_path") or ""))
    stale = unrecorded(root, name, since)
    session = str(payload.get("session_id") or "")
    asked = _already_asked(session)
    if since is not None:         # without a session start, an entry cannot be called this one's
        stale_names = {f.split(" (")[0] for f in stale}
        _count(unasked=sum(1 for f in GREW if f not in stale_names
                           and (root / f / name).stat().st_mtime >= since))
    open_ended = [f for f in undefined(root, name) if f not in asked]
    ahead = [f for f in future_dated(root, name) if f"future:{f}" not in asked]
    try:
        typed = hand_typed_hours(root, name, since=since)
    except Exception:
        typed = []            # a lesson that cannot count must not cost the session
    typed = [t for t in typed if not any(t.startswith(f.split(" (")[0] + ":") for f in ahead)]
    flagged = {f.split(" (")[0] for f in stale}
    try:
        thin = [h for h in hollow_entries(root, name, since)
                if h[0] not in flagged and f"hollow:{h[0]}:{h[1]}" not in asked]
    except Exception:
        thin = []             # a quality check that cannot read must not cost the session
    try:
        refuted_claims(root, name, since)
        claims = first_asks([v for v in visibility_entries(root, name, since)
                             if v[0] not in flagged], root)
    except Exception:
        claims = []           # a lesson that cannot count must not cost the session
    rewritten = [f for f in REWRITTEN if f"rewrite:{f}" not in asked]
    if (not stale and not open_ended and not ahead and not typed and not thin and not claims
            and not rewritten):
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
        _remember(session, _already_asked(session) | {"blocked:" + f.split(" (")[0] for f in stale})
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
            "against the source (`gh repo view --json visibility`, the page's own sharing "
            "setting) -- the human reads that section, not the prose. If a listed claim later "
            "proves wrong, the new entry's section says `refuted: <the claim>`; only that is "
            "counted as caught. If the word is not a claim here, say so in one line. "
            f"(Asked once per entry. Counted: caught {rec.get('caught', 0)} of "
            f"{rec.get('fired', 0)} asked.)")
    if rewritten:
        parts.append(
            f"Baton: an older entry changed in the {name} of " + ", ".join(rewritten) + " -- "
            "not a new entry at the top. A logbook is a record and does not get edited, so this "
            "does not count as recording the work. If something in it was wrong, leave it and add "
            "a new entry at the top that says what changed and why. (Said once.)")
        _remember(session, _already_asked(session) | {f"rewrite:{f}" for f in rewritten})
    # UTF-8, not \\uXXXX, and as bytes: a cp1252 pipe on Windows cannot raise (v3.12.0).
    sys.stdout.buffer.write(json.dumps({"decision": "block", "reason": "\n\n".join(parts)},
                                       ensure_ascii=False).encode("utf-8"))
    sys.stdout.flush()
    return 0


def _beat() -> None:
    """When this hook last ran, for /baton-doctor: a plugin can be installed and enabled and
    still never run (no Python, no Git Bash on Windows), and nothing on the screen says so.
    One small file per hook, next to the other state. Never raises."""
    try:
        data = os.environ.get("CLAUDE_PLUGIN_DATA")
        folder = Path(data) if data else Path(__file__).resolve().parent
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"baton.beat.{Path(__file__).stem}").write_text(
            datetime.now().isoformat(timespec="seconds"), "utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        _beat()
        sys.exit(main())
    except Exception:
        # A hook must never break the session it is trying to help.
        sys.exit(0)
