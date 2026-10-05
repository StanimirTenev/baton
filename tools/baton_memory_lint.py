#!/usr/bin/env python3
"""A free structural check of a memory index (MEMORY.md or any list of pointers).

    python3 tools/baton_memory_lint.py [INDEX]      # default: `review_index` from settings

Two questions, no model, nothing sent:
  - every link in the index leads to a file that exists;
  - every Markdown file in the index's folder (and below) has a line in the index.
A file without a line is invisible: the index is what a session reads first.

It reports and never edits. Exit 1 when it found something. It cannot say whether a line
is still TRUE -- that is the paid review (`baton_review.py`).
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

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


def _default_index() -> Path | None:
    spec = importlib.util.spec_from_file_location(
        "baton_corpus", Path(__file__).resolve().parent / "baton_corpus.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    raw = mod.config()["raw"]
    value = raw.get("review_index") or raw.get("pregled_indeks")
    return Path(value).expanduser() if value else None


def main(argv: list[str]) -> int:
    index = Path(argv[0]).expanduser() if argv else _default_index()
    if index is None or not index.is_file():
        print("No index: give its path, e.g. python3 tools/baton_memory_lint.py "
              "~/.claude/projects/<project>/memory/MEMORY.md")
        return 2
    broken, unindexed = lint(index)
    print(f"Index: {index}\n")
    print(f"Links that lead nowhere ({len(broken)}):")
    print("\n".join(f"  ❌ {b}" for b in broken) or "  (none)")
    print(f"\nFiles with no line in the index ({len(unindexed)}):")
    print("\n".join(f"  ⚠️ {u}" for u in unindexed) or "  (none)")
    print("\nNothing was changed. Fix the index by hand, or ask the agent to propose the lines.")
    return 1 if broken or unindexed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
