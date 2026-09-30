#!/usr/bin/env python3
"""What is already on this machine -- read before Baton writes anything.

    python3 tools/baton_survey.py           # a report for the human
    python3 tools/baton_survey.py --json    # the same, for a program

Run it before installing, show the human the report, and install only after they have said
where the task root is, what the logbook is called and what happens to any older rule.
It reads and never writes: no folder, no file, no config.

## Why it exists

2026-09-30, a Windows machine that had worked with Claude for months before Baton: the record
was ~150 dated files in the profile folder, the work lived in folders on two drives named in
memory, the memory sat under a project folder nobody would guess (`C--Windows-System32`), and
`CLAUDE.md` already carried a rule for keeping a logbook. The installer would have added a
second rule pointing at an empty `~/tasks`, and the obvious `BATON_HOME=D:\\` would have turned
`Program Files` and the recycle bin into tasks. None of that was visible from the home folder,
which is all `/baton-inventory` looked at. This looks where Claude itself left traces first.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

MAX_READ = 2_000_000
# A line in an instruction file that talks about keeping a record of work.
RULE = re.compile(r"дневник|logbook|journal|diary|YYYY-MM-DD", re.I)
# A file that is somebody's logbook, by its name.
LOGNAME = re.compile(r"^(logbook|dnevnik|дневник|journal|diary|log)\.md$", re.I)
# A dated record: 2026-09-30_1130_something.md
FLAT = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[_ -]\d{3,4})?[_ -]?(.*)\.md$")
# Paths written in memory and instructions. Inside backticks or a link a path may hold spaces;
# bare, it ends at the first space.
QUOTED = re.compile(r"`([^`\n]+)`|\]\(([^)\n]+)\)")
BARE = re.compile(r"(?<![\w`])((?:[A-Za-z]:[\\/]|~[\\/]|/)[^\s`'\"<>|*?()\[\]]+)")
SYSTEM = ("/tmp", "/usr", "/etc", "/proc", "/dev", "/var", "/bin", "/sbin", "/lib", "/sys",
          "/run", "/snap", "/boot")


def read(path: Path) -> str:
    """Any encoding a file may be in, never an exception: PowerShell 5 writes UTF-16 and
    older files are cp1251."""
    try:
        raw = path.read_bytes()[:MAX_READ]
    except OSError:
        return ""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1251", "replace")


def day(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def entries(path: Path) -> list[os.DirEntry]:
    try:
        with os.scandir(path) as it:
            return list(it)
    except OSError:
        return []


# -- 1. what Claude left behind ------------------------------------------------------------

def instructions(config: Path, home: Path) -> list[dict]:
    found = []
    for p in (config / "CLAUDE.md", home / "CLAUDE.md"):
        if not p.is_file():
            continue
        text = read(p)
        rules = [(n, line.strip()[:160]) for n, line in enumerate(text.splitlines(), 1)
                 if RULE.search(line)]
        found.append({"path": str(p), "lines": text.count("\n") + 1,
                      "baton": "Installed by Baton" in text, "rules": rules[:10]})
    return found


def memories(config: Path) -> list[dict]:
    found = []
    for project in entries(config / "projects"):
        mem = Path(project.path) / "memory"
        if not mem.is_dir():
            continue
        files = list(mem.rglob("*.md"))
        if not files:
            continue
        newest = max((f.stat().st_mtime for f in files), default=0)
        found.append({"path": str(mem), "files": len(files),
                      "index": (mem / "MEMORY.md").is_file(),
                      "newest": day(newest) if newest else ""})
    return sorted(found, key=lambda m: m["newest"], reverse=True)


def hooks(config: Path) -> list[dict]:
    try:
        data = json.loads(read(config / "settings.json") or "{}")
    except ValueError:
        return [{"event": "?", "command": "settings.json is not valid JSON", "baton": False}]
    found = []
    for event, groups in (data.get("hooks") or {}).items():
        for group in groups or []:
            for h in group.get("hooks", []) or []:
                cmd = " ".join([str(h.get("command", ""))] + [str(a) for a in h.get("args") or []])
                found.append({"event": event, "command": cmd[:140], "baton": "baton_" in cmd})
    return found


def baton_config(config: Path) -> dict:
    try:
        return json.loads(read(config / "baton" / "hooks" / "baton.local.json") or "{}")
    except ValueError:
        return {}


def history(config: Path) -> Counter:
    """The folders sessions were started in."""
    seen: dict = {}
    for line in read(config / "history.jsonl").splitlines():
        try:
            row = json.loads(line)
            p = row.get("project")
        except (ValueError, AttributeError):
            continue
        if p:
            seen.setdefault(p, set()).add(row.get("sessionId") or line)
    return Counter({p: len(ids) for p, ids in seen.items()})


# -- 2. where the work lives -----------------------------------------------------------------

def mentioned(text: str) -> list[str]:
    out = [a or b for a, b in QUOTED.findall(text)]
    out += BARE.findall(QUOTED.sub(" ", text))
    return [s.strip() for s in out if re.match(r"(?:[A-Za-z]:[\\/]|~[\\/]|/)\S", s.strip())]


def place(raw: str, home: Path, config: Path) -> str | None:
    """The folder a mention points at, if it is a real folder that could hold work."""
    s = raw.rstrip(".,;:").rstrip("\\/") or raw
    p = Path(os.path.expanduser(s))
    if not p.is_absolute():
        return None
    try:
        if not p.exists():
            return None
        if not p.is_dir():
            p = p.parent
        p = p.resolve()
    except OSError:
        return None
    text = str(p)
    low = text.lower()
    if p == Path(p.anchor) or p in home.parents or p == home:
        return None
    if any(part.startswith(".") for part in p.parts):
        return None                # settings and caches, not work
    if low.startswith(str(config.resolve()).lower()):
        return None
    if os.name == "nt":
        if re.match(r"[a-z]:\\(windows|program files|programdata)", low):
            return None
    elif any(low == s or low.startswith(s + "/") for s in SYSTEM):
        return None
    return text


def places(config: Path, home: Path, sources: list[Path], starts: Counter) -> list[dict]:
    count: Counter = Counter()
    for src in sources:
        for raw in mentioned(read(src)):
            p = place(raw, home, config)
            if p:
                count[p] += 1
    sessions: Counter = Counter()
    for p, n in starts.items():
        q = place(p, home, config)
        if q:
            sessions[q] += n
            count[q] += 0          # a place sessions start in counts even unmentioned
    found = []
    for p, n in count.items():
        found.append({"path": p, "mentions": n, "sessions": sessions[p],
                      "logbook": logbook_in(Path(p))})
    found.sort(key=lambda d: (d["mentions"] + d["sessions"]), reverse=True)
    return found[:40]


# -- 3. how the record is kept today ---------------------------------------------------------

def logbook_in(folder: Path) -> dict | None:
    items = entries(folder)
    books = [e for e in items if e.is_file() and LOGNAME.match(e.name)]
    if not books:
        return None
    book = books[0]
    mine = book.stat().st_mtime
    others = [e.stat().st_mtime for e in items if e.is_file() and e.name != book.name]
    newest = max(others, default=mine)
    return {"name": book.name, "last": day(mine),
            "stale": newest - mine > 86400}


def flat_logbooks(home: Path) -> list[dict]:
    found = []
    for folder in (home, home / "Desktop", home / "Documents"):
        dated = []
        for e in entries(folder):
            m = FLAT.match(e.name) if e.is_file() else None
            if m:
                dated.append(m)
        if len(dated) < 3:
            continue
        days = sorted(m.group(1) for m in dated)
        prefixes = Counter((m.group(2).split("-")[0] or "?") for m in dated)
        found.append({"path": str(folder), "files": len(dated), "first": days[0],
                      "last": days[-1], "topics": prefixes.most_common(10)})
    return found


def roots(candidates: list[Path]) -> list[dict]:
    """A folder whose subfolders keep the same logbook -- a task root already."""
    found, seen = [], set()
    for root in candidates:
        if root in seen or not root.is_dir() or root == Path(root.anchor):
            continue               # a drive root holds Program Files and the recycle bin too
        seen.add(root)
        subs = [Path(e.path) for e in entries(root) if e.is_dir() and not e.name.startswith(".")]
        names: Counter = Counter()
        for s in subs:
            book = logbook_in(s)
            if book:
                names[book["name"]] += 1
        if names:
            name, n = names.most_common(1)[0]
            if n >= 2 and 2 * n >= len(subs):     # most of it, not two folders in a crowd
                found.append({"path": str(root), "logbook": name, "with": n, "folders": len(subs)})
    return sorted(found, key=lambda r: r["with"], reverse=True)


# -- 4. together --------------------------------------------------------------------------------

def survey(home: Path, config: Path) -> dict:
    ins = instructions(config, home)
    mems = memories(config)
    starts = history(config)
    sources = [Path(i["path"]) for i in ins]
    for m in mems:
        sources += list(Path(m["path"]).rglob("*.md"))
    where = places(config, home, sources, starts)
    candidates = [Path(e.path) for e in entries(home) if e.is_dir() and not e.name.startswith(".")]
    candidates += [Path(p["path"]).parent for p in where] + [Path(p["path"]) for p in where]
    have = baton_config(config)
    found_roots = roots(candidates)
    flats = flat_logbooks(home)

    if have.get("home"):
        proposal = {"home": have["home"], "logbook": have.get("logbook", "LOGBOOK.md"),
                    "why": "Baton is installed already; a reinstall keeps these"}
    elif found_roots:
        r = found_roots[0]
        proposal = {"home": r["path"], "logbook": r["logbook"],
                    "why": f"{r['with']} of its {r['folders']} folders already keep a {r['logbook']}"}
    else:
        proposal = {"home": str(home / "tasks"), "logbook": "LOGBOOK.md",
                    "why": "no folder here keeps tasks with a logbook yet -- the default"}

    notes = []
    old = [i for i in ins if i["rules"] and not i["baton"]]
    for i in old:
        notes.append(f"{i['path']} already has a rule about the record (lines "
                     f"{', '.join(str(n) for n, _ in i['rules'][:5])}). Baton's section would sit "
                     "next to it: ask the human whether it replaces that rule or both stay.")
    for f in flats:
        notes.append(f"{f['files']} dated logbook files in {f['path']} ({f['first']} .. {f['last']}) "
                     "are the record today. They stay where they are; /baton-inventory folds them "
                     "into task logbooks. The task root is not this folder.")
    stale = [p for p in where if p["logbook"] and p["logbook"]["stale"]]
    for p in stale:
        notes.append(f"{p['path']}: {p['logbook']['name']} last written {p['logbook']['last']}, "
                     "older than other files there -- not the current record.")
    drives = sorted({Path(p["path"]).anchor for p in where})
    if len(drives) > 1:
        notes.append(f"Work lives on {', '.join(drives)}. The task root is one folder, never a "
                     "drive root; tasks point at these places, nothing is moved.")
    others = [h for h in hooks(config) if not h["baton"]]
    if others:
        notes.append(f"{len(others)} hook(s) not from Baton are in settings.json. The installer adds "
                     "its own next to them and keeps these.")
    if not (ins or mems or flats or where):
        notes.append("Nothing from an earlier Claude setup was found.")

    return {"home": str(home), "config": str(config), "instructions": ins, "memory": mems,
            "hooks": hooks(config), "baton": have, "places": where, "flat_logbooks": flats,
            "task_roots": found_roots, "proposal": proposal, "notes": notes}


def report(s: dict) -> str:
    out = ["# What is already on this machine", "",
           f"Read from {s['config']} and {s['home']}. **Nothing was written.**", ""]
    out += ["## Claude before Baton", ""]
    for i in s["instructions"]:
        tag = " (Baton's section is in it)" if i["baton"] else ""
        out.append(f"- `{i['path']}`: {i['lines']} lines{tag}")
        out += [f"  - line {n}: {t}" for n, t in i["rules"]]
    for m in s["memory"]:
        out.append(f"- memory `{m['path']}`: {m['files']} files, last {m['newest']}"
                   + ("" if m["index"] else ", no MEMORY.md"))
    for h in s["hooks"]:
        out.append(f"- hook {h['event']}: `{h['command']}`" + (" (Baton)" if h["baton"] else ""))
    if s["baton"]:
        out.append(f"- Baton installed: task root `{s['baton'].get('home')}`, "
                   f"logbook `{s['baton'].get('logbook')}`")
    if len(out) == 6:
        out.append("- nothing")
    out += ["", "## Where the work lives", ""]
    for p in s["places"]:
        book = p["logbook"]
        tail = (f"; {book['name']} last {book['last']}" + (" (stale)" if book["stale"] else "")
                if book else "")
        out.append(f"- `{p['path']}`: named {p['mentions']}x in memory/instructions"
                   + (f", {p['sessions']} sessions started here" if p["sessions"] else "") + tail)
    if not s["places"]:
        out.append("- no folder is named in memory or instructions")
    out += ["", "## How the record is kept today", ""]
    for f in s["flat_logbooks"]:
        topics = ", ".join(f"{t} {n}" for t, n in f["topics"])
        out.append(f"- `{f['path']}`: {f['files']} dated files, {f['first']} .. {f['last']}; "
                   f"by topic: {topics}")
    for r in s["task_roots"]:
        out.append(f"- `{r['path']}`: {r['with']} of {r['folders']} folders keep a `{r['logbook']}`")
    if not (s["flat_logbooks"] or s["task_roots"]):
        out.append("- no logbooks found")
    p = s["proposal"]
    out += ["", "## Proposed", "",
            f"- task root: `{p['home']}`", f"- logbook: `{p['logbook']}`", f"- because: {p['why']}",
            "", "## Before installing, ask the human", ""]
    out += [f"- {n}" for n in s["notes"]]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only survey before installing Baton.")
    ap.add_argument("--home", default=str(Path.home()))
    ap.add_argument("--config", default=os.environ.get("CLAUDE_CONFIG_DIR")
                    or str(Path.home() / ".claude"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    s = survey(Path(a.home).expanduser(), Path(a.config).expanduser())
    text = json.dumps(s, ensure_ascii=False, indent=2) + "\n" if a.json else report(s)
    sys.stdout.buffer.write(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
