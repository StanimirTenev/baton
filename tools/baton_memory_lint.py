#!/usr/bin/env python3
"""A free structural check of a memory index (MEMORY.md or any list of pointers).

    python3 tools/baton_memory_lint.py [INDEX]      # default: `review_index` from settings

    python3 tools/baton_memory_lint.py [INDEX] --accept   # the lines named were re-read

Three questions, no model, nothing sent:
  - every link in the index leads to a file that exists;
  - every Markdown file in the index's folder (and below) has a line in the index;
  - which files changed after the line that points to them (2026-10-21). On 19.09.2026 the
    index said "we want the paper, it is behind a wall" five days after the detail file had
    recorded it as read; the first two questions passed it clean (ZA-OPRAVYANE row 29).
A file without a line is invisible: the index is what a session reads first.

The third is by file time, not by meaning: a changed file is a reason to read its line
again, not proof the line is wrong. A line's time is remembered by its text, in
`baton.memlint.json` next to the settings: unseen, it is the index's own file time, the
latest the line can have been written. `--accept` records the lines named as re-read.

It reports and never edits the index. Exit 1 when it found something. It cannot say whether a
line is still TRUE -- that is the paid review (`baton_review.py`).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

SLACK_SECONDS = 60      # a line and its file saved in the same minute are one edit

LINK = re.compile(r"\]\(\s*<?([^)>\s]+)>?\s*\)")


def links(index: Path) -> list[tuple[int, str]]:
    out = []
    for n, line in enumerate(index.read_text("utf-8", errors="replace").splitlines(), 1):
        for target in LINK.findall(line):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
                continue                                   # a URL or an anchor, not a file
            out.append((n, target.split("#", 1)[0]))
    return out


def lint(index: Path) -> tuple[list[str], list[str]]:
    base = index.parent
    broken, linked = [], set()
    for n, target in links(index):
        path = (base / target).resolve()
        linked.add(path)
        if not path.exists():
            broken.append(f"line {n}: {target}")
    unindexed = sorted(str(p.relative_to(base)) for p in base.rglob("*.md")
                       if p.resolve() != index.resolve() and p.resolve() not in linked)
    return broken, unindexed


def _corpus_config() -> dict:
    spec = importlib.util.spec_from_file_location(
        "baton_corpus", Path(__file__).resolve().parent / "baton_corpus.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.config()


def _default_index() -> Path | None:
    raw = _corpus_config()["raw"]
    value = raw.get("review_index") or raw.get("pregled_indeks")
    return Path(value).expanduser() if value else None


def _state_path() -> Path:
    return Path(os.environ.get("BATON_MEMLINT_STATE")
                or Path(_corpus_config()["where"]).parent / "baton.memlint.json")


def changed_after(index: Path, state: dict, accept: bool = False) -> list[str]:
    """Lines whose target file changed after the line was last written. Updates `state`:
    {index: {target: {line hash: time}}}, keeping only the lines the index holds now."""
    base, mine = index.parent, state.setdefault(str(index.resolve()), {})
    written = index.stat().st_mtime
    lines = index.read_text("utf-8", errors="replace").splitlines()
    kept: dict = {}
    out = []
    for n, target in links(index):
        path = (base / target).resolve()
        if not path.is_file():
            continue                                   # a dead link is the first question's
        digest = hashlib.sha1(lines[n - 1].strip().encode("utf-8")).hexdigest()[:12]
        seen = mine.get(str(path), {}).get(digest, written)
        changed = path.stat().st_mtime
        if changed > seen + SLACK_SECONDS:
            if accept:
                seen = max(time.time(), changed)     # read against this version of the file
            else:
                out.append(f"line {n}: {target} (changed {time.strftime('%Y-%m-%d %H:%M', time.localtime(changed))}, "
                           f"the line {time.strftime('%Y-%m-%d %H:%M', time.localtime(seen))})")
        kept.setdefault(str(path), {})[digest] = seen
    state[str(index.resolve())] = kept
    return out


def main(argv: list[str]) -> int:
    accept = "--accept" in argv
    argv = [a for a in argv if a != "--accept"]
    index = Path(argv[0]).expanduser() if argv else _default_index()
    if index is None or not index.is_file():
        print("No index: give its path, e.g. python3 tools/baton_memory_lint.py "
              "~/.claude/projects/<project>/memory/MEMORY.md")
        return 2
    broken, unindexed = lint(index)
    try:
        state = json.loads(_state_path().read_text("utf-8"))
    except Exception:
        state = {}
    after = changed_after(index, state, accept)
    try:
        _state_path().write_text(json.dumps(state, indent=1), "utf-8")
    except OSError:
        pass        # without memory every line takes the index's own time: stricter, not looser
    print(f"Index: {index}\n")
    print(f"Links that lead nowhere ({len(broken)}):")
    print("\n".join(f"  ❌ {b}" for b in broken) or "  (none)")
    print(f"\nFiles with no line in the index ({len(unindexed)}):")
    print("\n".join(f"  ⚠️ {u}" for u in unindexed) or "  (none)")
    print(f"\nFiles changed after their line ({len(after)}) -- read the line again:")
    print("\n".join(f"  🔁 {a}" for a in after) or "  (none)")
    if accept:
        print("\nThe lines whose files had changed are accepted as re-read.")
    print("\nNothing in the index was changed. Fix it by hand, or ask the agent to propose the lines.")
    return 1 if broken or unindexed or after else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
