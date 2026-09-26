#!/usr/bin/env python3
"""Where else does this live -- and is that place still claiming it?

    python3 tools/baton_kade.py "2500"          # where else does this appear
    python3 tools/baton_kade.py "0\\.4[0-9]" --regex
    python3 tools/baton_kade.py --duplicates    # find them without being asked

## Why this is not grep

`grep -r` answers "here is where the string occurs". The question that actually
came up, three times in a week, is a different one: **which of those places still
CLAIM something, and which are only a record of what was once true.**

Baton already draws that line -- but only for people to read:

| where | what it is | can it go stale |
|---|---|---|
| a logbook header (inside the front matter) | **LIVE** -- claims it now | yes |
| a logbook entry (`## 2026-…`) | **RECORD** -- what was done | no, and it is never edited |
| a plan, a spec, a memory file | **LIVE** | yes |
| a file whose *name* carries a date (`STATE_21_09.md`) | **SNAPSHOT** | no -- it says when |
| a row in a claims register | **CLAIM** -- dated, with a status | tracked by another check |

⇒ A disagreement between two **LIVE** places is a defect.
   A disagreement between a live place and an old **record** is history.

Only LIVE and the header count. The other three legitimately repeat old values: a
record is not edited, a snapshot says in its own filename when it was true, and a
register row is a dated claim whose ageing the session-start hook already reports.
Counting them doubles the alarm and the first version of this tool did exactly
that -- one query went from 7 "live" places to 4 once they were separated out.

## ⚠️ It does not find contradictions. It finds DUPLICATED STATE.

Whether the duplicates disagree is the reader's call. Say it the other way round
and someone will pronounce a tree "consistent" while the same wrong number sits in
six places.

## `--duplicates`, and what it is calibrated against

Numbers living in LIVE places in two or more different task folders. Measured
2026-09-26 over 20 task folders plus a memory tree -- 149 distinct numbers -- and
every hit labelled by hand:

| kind | duplicates | relevant | noise |
|---|---|---|---|
| **money (€)** | 6 | **6** | 0 |
| **percentages with a decimal** (84.8%) | 3 | **3** | 0 |
| thresholds (`0.92`, `0.46`) | 41 | 1 | **40** |
| round percentages (100%, 30%) | 16 | 0 | **16** |
| version numbers (v1.0.0) | 11 | 0 | **11** |
| | **77** | **10** | **67** |

⚠️ The threshold row is there because the first measurement missed it. That run
excluded some folders and never saw them; scoping the tool properly took the same
corpus from 9 duplicates to 100, and the rate with it. **A rate measured on a scope
that is not declared is not a rate.**

⇒ **A number with a decimal point or a currency sign is a decision. A round number
or a version is shared vocabulary** -- it turns up everywhere because it is a word,
not a state. `100%` appeared in nine folders.

So the default is the measured setting: money and decimals only, which gave **9
hits and no false positives on that corpus**. `--all` restores the rest, which on
the same corpus was noise 27 times out of 27.

⚠️ One corpus, labelled by the author, the same day. That is exactly the position
`PRAG` is in for the review tool: a starting point, not a constant. Run it on your
own tree, label what it prints, and move the filter to where it separates yours.

## What it found on the corpus it was calibrated on

`€2500` sits in a task's own open-questions file marked *decided, 19.09* -- and in
another task's header dated **26.09**. Seven days between two live places, and
nothing would have said so. The tool reports not only the duplication but the
spread in when the places were last touched, which is the part that says how long
they have disagreed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime
from pathlib import Path

def _load_korpus():
    """One module object, not one per importer.

    ⚠️ The first version of this exec_module'd a fresh copy every time, so two
    `baton_korpus` objects sat in memory and `kade.kind is korpus.kind` was false.
    That is Baton's own oldest lesson in miniature -- the hooks run from copies, and
    v2.2.0 was written, tested and tagged while a two-day-old copy did the work.
    A single owner that is loaded twice is two owners.
    """
    if "baton_korpus" in sys.modules:
        return sys.modules["baton_korpus"]
    spec = importlib.util.spec_from_file_location(
        "baton_korpus", Path(__file__).resolve().parent / "baton_korpus.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["baton_korpus"] = module
    spec.loader.exec_module(module)
    return module


korpus = _load_korpus()

# The five kinds and the corpus scope have ONE owner -- `baton_korpus`. They used to
# be declared here as well, with a second set of regular expressions, and nothing had
# broken yet only because both copies still agreed.
ENTRY, SKIP, REGISTERS, DATED_NAME = (
    korpus.ENTRY, korpus.SKIP, korpus.REGISTERS, korpus.DATED_NAME)
kind = korpus.kind

# Money, a percentage, a threshold, a version. Dates are facts, not decisions.
NUMBERS = re.compile(
    r'(?:€\s?[\d  ,.]{2,9}\d|\b\d{1,3}[.,]\d%|\b\d{1,3}%|\b0[.,]\d\d\b|\bv\d+\.\d+\.\d+\b)')
YEARLIKE = re.compile(r'^(?:19|20)\d\d$')
# Measured twice, and the second run changed it. Money and decimal percentages are
# decisions: 9 hits, 9 relevant. Thresholds `0.xx` looked like the same class and are
# not -- they add 41 hits of which one (`0.46`, a real threshold in two places) was
# relevant. The rest come from measurement corpora, where two runs both reporting
# 0.92 is two measurements, not duplicated state. A threshold is still findable by
# name with the plain query, which is what that mode is for.
PRECISE = re.compile(r'^€|^\d{1,3}\.\d%?$')

LIVE = ("LIVE", "HEADER")


def settings() -> tuple[Path, str, Path | None]:
    """The same chain the hooks read -- not a second one that can disagree."""
    cfg = {}
    for candidate in (Path.home() / ".claude/baton/hooks",
                      Path(__file__).resolve().parent.parent / "hooks"):
        try:
            cfg = json.loads((candidate / "baton.local.json").read_text("utf-8-sig"))
            break
        except Exception:
            continue
    home = Path(cfg.get("home", Path.home() / "tasks")).expanduser()
    logbook = cfg.get("logbook", "LOGBOOK.md")
    index = cfg.get("pregled_indeks")
    return home, logbook, (Path(index).expanduser().parent if index else None)


def search(pattern: re.Pattern, home: Path, logbook: str, memory: Path | None,
           scope=None):
    """Matches with the kind of place each one sits in.

    The walk and the scope come from `baton_korpus`. `Scope([])` is this tool's
    declared corpus -- everything under the roots except `SKIP` and whatever
    `.batonignore` excludes, which is exactly what `--duplicates` was calibrated
    on. It is passed explicitly rather than defaulted inside the walker, because
    an exclusion nobody stated is the defect that took the same corpus from 9
    duplicates to 100.

    ⚠️ A `for folder in …: pass` loop stood here -- a full second traversal of the
    tree that did nothing. It is gone with the walk it was part of; it produced no
    output and nothing referenced it.
    """
    scope = scope if scope is not None else korpus.Scope([])
    for _root, file in korpus.walk([p for p in (home, memory) if p], scope,
                                   suffixes=(".md",)):
        try:
            text = file.read_text(encoding="utf-8")
        except Exception:
            continue
        for match in pattern.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            start = text.rfind("\n", 0, match.start()) + 1
            end = text.find("\n", match.start())
            yield (file, line_no, text[start:end if end != -1 else len(text)].strip(),
                   *kind(file, match.start(), text, logbook))


def normalise(value: str) -> str:
    """€1 200, €1,200 and €1.200 are one number written three ways."""
    value = value.strip().replace(" ", " ")
    if value.startswith("€"):
        return "€" + re.sub(r"[  ,.]", "", value[1:])
    return value.replace(",", ".")


def duplicates(home: Path, logbook: str, memory: Path | None,
               min_folders: int = 2, everything: bool = False):
    """Numbers living in LIVE places across `min_folders` or more folders."""
    found: dict[str, list] = {}
    # A line with two numbers comes back from `search` once per match and is then
    # scanned whole: four entries for two facts. Each line is read once.
    seen: set[tuple[Path, int]] = set()
    for file, line_no, line, what, _ in search(NUMBERS, home, logbook, memory):
        if what not in LIVE or (file, line_no) in seen:
            continue
        seen.add((file, line_no))
        for match in NUMBERS.finditer(line):
            key = normalise(match.group(0))
            if YEARLIKE.match(key) or len(key) < 3:
                continue
            found.setdefault(key, []).append((file.parent.name, file, line_no, line))
    rows = []
    for key, hits in found.items():
        folders = {h[0] for h in hits}
        if len(folders) < min_folders:
            continue
        if not everything and not PRECISE.match(key):
            continue
        stamps = [f.stat().st_mtime for _, f, _, _ in hits]
        rows.append((len(folders), (max(stamps) - min(stamps)) / 86400, key, hits))
    return sorted(rows, reverse=True), len(found)


def _report_duplicates(args, home, logbook, memory) -> None:
    rows, total = duplicates(home, logbook, memory, args.min_folders, args.all)
    print(f"Numbers in LIVE places across {args.min_folders}+ folders: "
          f"{len(rows)} of {total} distinct numbers\n")
    print("⚠️ These are not contradictions. This is DUPLICATED STATE.")
    print("   Whether the duplicates agree is yours to read.\n")
    for folders, days, key, hits in rows[:25]:
        print("=" * 74)
        print(f"  {key}   · {folders} folders · last touched {days:.0f} days apart")
        for folder, file, line_no, line in sorted(hits, key=lambda h: h[1].stat().st_mtime):
            stamp = datetime.fromtimestamp(file.stat().st_mtime).strftime("%d.%m")
            print(f"     [{stamp}] {folder}/{file.name}:{line_no}")
            print(f"            {line[:110]}")
    if len(rows) > 25:
        print(f"\n… and {len(rows) - 25} more, NOT shown. A short list is not a clean bill.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pattern", nargs="?", help="what to look for (omit with --duplicates)")
    parser.add_argument("--regex", action="store_true", help="treat the pattern as a regex")
    parser.add_argument("--live-only", action="store_true", help="hide records and snapshots")
    parser.add_argument("--duplicates", action="store_true",
                        help="find them unprompted: numbers in more than one live place")
    parser.add_argument("--min-folders", type=int, default=2)
    parser.add_argument("--all", action="store_true",
                        help="include round percentages and versions — measured: noise 27/27")
    args = parser.parse_args()

    home, logbook, memory = settings()
    if args.duplicates:
        return _report_duplicates(args, home, logbook, memory)
    if not args.pattern:
        parser.error("give something to look for, or use --duplicates")

    pattern = re.compile(args.pattern if args.regex else re.escape(args.pattern))
    live, rest = [], []
    for hit in search(pattern, home, logbook, memory):
        (live if hit[3] in LIVE else rest).append(hit)

    print(f"“{args.pattern}” — {len(live)} live, {len(rest)} records\n")
    if live:
        print("=" * 74)
        print("LIVE — these still claim something. A disagreement here is a defect.")
        print("=" * 74)
        for file, line_no, line, what, _ in live:
            where = file.parent.name if file.parent != home else file.name
            stamp = datetime.fromtimestamp(file.stat().st_mtime).strftime("%d.%m %H:%M")
            print(f"\n  [{what:6}] {where}/{file.name}:{line_no}  · touched {stamp}")
            print(f"           {line[:150]}")
    else:
        print("  (nothing live)")

    if rest and not args.live_only:
        print("\n" + "-" * 74)
        print(f"RECORDS · SNAPSHOTS · CLAIMS ({len(rest)}) — these repeat old values legitimately.")
        print("-" * 74)
        grouped: dict[str, list] = {}
        for file, line_no, line, what, detail in rest:
            grouped.setdefault(f"[{what}] {file.parent.name} {detail}", []).append(line)
        for key in sorted(grouped, reverse=True):
            print(f"\n  {key}  ({len(grouped[key])}×)")
            print(f"     {grouped[key][0][:140]}")

    if len(live) > 1:
        print(f"\n⚠️  {len(live)} LIVE places. If they do not say the same thing, one is stale —")
        print("    and nothing will announce it, because both look plausible.")


if __name__ == "__main__":
    main()
