#!/usr/bin/env python3
"""The task corpus: which files are in it, and what kind of place each passage is.

This module exists because both of those questions were answered twice, in two
files, with two sets of regular expressions -- and the answers had already begun
to differ.

## 1. One owner for the five kinds

Baton draws a line between a place that **claims something now** and a place that
**records what was once true**. The line is the whole reason a duplicate-state
query is not `grep`:

| where | kind | can it go stale |
|---|---|---|
| inside a logbook's front matter | **HEADER** -- claims it now | yes |
| a `## 2026-…` entry in a logbook | **RECORD** -- what was done | no, and it is never edited |
| a plan, a spec, a memory file | **LIVE** | yes |
| a file whose *name* carries a date | **SNAPSHOT** -- it says when | no |
| a row in a claims register | **CLAIM** -- dated, with a status | another check ages it |

`baton_kade.py` had this as `kind()` with `REGISTERS`/`DATED_NAME`/`ENTRY`. A corpus
builder outside the repository had the same five, as `parcheta()` with `REGISTRI`/
`S_DATA` and its own entry split. Nothing had broken yet -- both returned something
plausible, which is exactly how a duplicate rots: in one half, silently.

## 2. ⭐ A scope that is not declared is not a scope

Measured 2026-09-26, and it cost two of three results. A corpus built for edge
detection drew **878 of 2131 passages (41%)** from `docs/`, `RivicQ_CSPM_EaaS/`,
`sravnenie-1/`, `granichni/`, `kontrol/`, `negativni/`, `sdks/`, `kubernetes/` --
imported comparison fixtures and vendored material that live legitimately inside
task folders but were written by nobody here. Two of the three detectors were
useless at roughly 50% false positives, and the corpus is why.

The same defect, in the other direction, hit the duplicate-state query the same
day: a prototype silently excluded one subtree, and scoping it properly took the
same corpus from 9 duplicates to 100.

⇒ `Scope` **refuses to be constructed from `None`.** An empty scope is a decision
and is allowed -- `Scope([])` -- but it has to be made out loud. This is the rule
`baton_pregled.py` already applies to its confidential-folder list: a missing list
stops the tool.

### ⚠️ `.batonignore` answers a DIFFERENT question, and is honoured anyway

`.batonignore` means *"do not demand a logbook entry for this"* -- it is the Stop
hook's file. It does not mean *"this is not my writing"*. They overlap (raw agent
output is both) and they diverge: `prevod-razgovor` ignores its transcripts for the
Stop hook, and those transcripts are the actual work product.

It is honoured here because the duplicate-state calibration was measured with it
honoured, and dropping it would invalidate that measurement. It is **not** a
substitute for declaring `outside`.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from fnmatch import fnmatch
from pathlib import Path
import re

ENTRY = re.compile(r'^## (\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?)', re.M)
REGISTERS = {"FAKTI.md", "FACTS.md", "TVARDENIYA.md", "CLAIMS.md"}
DATED_NAME = re.compile(r'\d{4}-\d{2}-\d{2}|[_-]\d{2}[_-]\d{2}(?:\D|$)')
SKIP = {".git", "__pycache__", "node_modules", ".pytest_cache"}
SUFFIXES = (".md", ".txt")

# Ported from the corpus builder that measured them: a logbook header is a pointer
# and the top of it carries the state; an entry's first screen carries what it was
# about; a section under 120 characters is a stub, not a passage.
HEADER_CHARS, ENTRY_CHARS, SECTION_CHARS, MIN_SECTION = 2000, 3000, 3000, 120


CONFIG = "baton.local.json"


def config() -> dict:
    """The one reader of `baton.local.json` -- where the tasks are and what the logbook
    is called.

    ⚠️ There were three, in three different orders. `baton_pregled` read the repository
    copy first, `baton_kade` the installed one first, and the SessionStart hook only the
    file next to its own `__file__`. The third is why `baton_tablo` printed "no tasks
    under ~/tasks" on a machine whose tasks are elsewhere: the board loads the hook out
    of the repository, and the config does not live there -- it is deliberately outside
    git, because it holds client folder names.

    Installed first, because that is the file the hooks actually run with. The
    repository copy is a working-copy fallback. Environment wins over both.
    """
    cfg, source = {}, None
    for candidate in (Path.home() / ".claude/baton/hooks",
                      Path(__file__).resolve().parent.parent / "hooks"):
        try:
            cfg = json.loads((candidate / CONFIG).read_text("utf-8-sig"))
            source = candidate / CONFIG
            break
        except Exception:
            continue
    home = os.environ.get("BATON_HOME") or cfg.get("home") or str(Path.home() / "tasks")
    logbook = os.environ.get("BATON_LOGBOOK") or cfg.get("logbook") or "LOGBOOK.md"
    return {"home": Path(home).expanduser(), "logbook": logbook,
            "raw": cfg, "source": source}


def kind(file: Path, position: int, text: str, logbook: str) -> tuple[str, str]:
    """LIVE · HEADER · RECORD · SNAPSHOT · CLAIM, and a word on which."""
    if file.name in REGISTERS:
        return "CLAIM", "dated, carries a status"
    if DATED_NAME.search(file.stem) or file.stem.endswith(("_istoria", "_history")):
        return "SNAPSHOT", f"{file.stem} — dated in its own name"
    if text.startswith("---"):
        second = text.find("\n---", 3)
        if second != -1 and position < second:
            return "HEADER", "claims it now"
    if file.name == logbook:
        # `<=`, not `<`: an entry's own `## 2026-…` heading IS part of that entry. With
        # the strict form a chunk starting exactly at the heading came back LIVE — the
        # boundary a whole-file scan never hits, because it matches inside a line.
        before = [(m.start(), m.group(1)) for m in ENTRY.finditer(text) if m.start() <= position]
        if before:
            return "RECORD", f"entry of {before[-1][1]}"
        return "LIVE", "above the first entry"
    return "LIVE", file.name


def _stop_hook():
    """The Stop hook's own `.batonignore` reading, reused rather than rewritten."""
    spec = importlib.util.spec_from_file_location(
        "baton_stop", Path(__file__).resolve().parent.parent / "hooks" / "baton_stop.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["baton_stop"] = module
    spec.loader.exec_module(module)
    return module


class Scope:
    """What the corpus is, said out loud.

    `outside` is a list of patterns. One containing `/` is matched with `fnmatch`
    against the path relative to the root; one without is matched against any
    single part of the path, so `docs` excludes every `docs/` directory.

        Scope(["docs", "sdks", "*/razuznavane/*"])
        Scope([])                      # everything -- a decision, made explicitly

    Passing `None` raises. That is the point of the class.
    """

    def __init__(self, outside, *, batonignore: bool = True, skip=SKIP):
        if outside is None:
            raise ValueError(
                "declare the scope: Scope([...]) with what is outside the corpus, or "
                "Scope([]) for everything. A rate measured on a scope nobody declared "
                "is not a rate -- an undeclared exclusion took one corpus from 9 hits "
                "to 100 without a word.")
        self.outside = list(outside)
        self.skip = set(skip)
        self.batonignore = batonignore
        self._hook = None
        if batonignore:
            try:
                self._hook = _stop_hook()
            except Exception:
                self._hook = None

    def holds(self, root: Path, file: Path) -> bool:
        """Is this file inside the declared corpus?"""
        if any(part in self.skip for part in file.parts):
            return False
        try:
            rel = file.relative_to(root)
        except ValueError:
            return False
        rel_posix = rel.as_posix()
        for pattern in self.outside:
            if "/" in pattern:
                if fnmatch(rel_posix, pattern):
                    return False
            elif pattern in rel.parts:
                return False
        if self._hook is not None and file.parent != root and rel.parts:
            base = root / rel.parts[0]
            try:
                patterns = self._hook.ignore_patterns(base)
                if patterns and self._hook.is_ignored(
                        str(file.relative_to(base)), file.name, patterns):
                    return False
            except Exception:
                pass
        return True

    def describe(self) -> str:
        """One line, so a number can be quoted with the scope it was measured on."""
        outside = ", ".join(self.outside) if self.outside else "nothing"
        return (f"scope: outside = {outside} · skip = {len(self.skip)} names · "
                f".batonignore {'honoured' if self._hook else 'not read'}")


def walk(roots, scope: Scope, suffixes=SUFFIXES):
    """Files of the corpus, in a stable order, with the root each came from."""
    if scope is None or not isinstance(scope, Scope):
        raise ValueError("pass a Scope -- see Scope.__init__ for why it is required")
    for root in [Path(r) for r in roots if r and Path(r).is_dir()]:
        for file in sorted(root.rglob("*")):
            if file.suffix not in suffixes or not file.is_file():
                continue
            if scope.holds(root, file):
                yield root, file


def _pieces(text: str, file: Path, logbook: str):
    """(offset, text) along the file's own boundaries, offsets kept.

    ⚠️ The offset is the whole point. The first version asked `kind()` once per file
    at position 0, and every file carrying YAML front matter starts with `---`, so
    **every chunk of it came back HEADER** -- 478 of 1821 on a real tree, where only
    about twenty logbooks exist. A memory file's body is LIVE; only its front matter
    claims anything as a header. Asking at the real offset is also what makes this and
    `baton_kade.py` unable to disagree, which is why this module exists.
    """
    if file.name == logbook:
        offset = 0
        for piece in re.split(r'(?=^## \d{4}-)', text, flags=re.M):
            yield offset, piece
            offset += len(piece)
    elif file.name in REGISTERS:
        offset = 0
        for row in text.split("\n"):
            yield offset, row
            offset += len(row) + 1
    else:
        offset = 0
        for piece in re.split(r'\n(?=#{1,3} )', text):
            yield offset, piece
            offset += len(piece) + 1


def chunks(roots, scope: Scope, logbook: str, suffixes=SUFFIXES):
    """(text, source, kind) over the corpus, split on its own natural boundaries.

    A logbook becomes its header plus one chunk per entry; a claims register one chunk
    per row; anything else is split on its headings. Every kind comes from `kind()` at
    the chunk's real offset, so this and a duplicate-state query cannot disagree about
    what a place is.
    """
    for root, file in walk(roots, scope, suffixes):
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        where = f"{file.parent.name}/{file.name}"
        is_logbook, is_register = file.name == logbook, file.name in REGISTERS
        for offset, piece in _pieces(text, file, logbook):
            what, _ = kind(file, offset, text, logbook)
            if is_logbook:
                if offset == 0:
                    yield piece[:HEADER_CHARS], f"{where} [header]", what
                else:
                    stamp = re.match(r'## (\S+)', piece)
                    yield (piece[:ENTRY_CHARS],
                           f"{where} [{stamp.group(1) if stamp else '?'}]", what)
            elif is_register:
                if piece.startswith("|") and len(piece) > 80:
                    yield piece, where, what
            elif what == "HEADER" or len(piece.strip()) > MIN_SECTION:
                # Front matter is a chunk whatever its length. A memory file's
                # `description:` is a live claim -- it is the line the index rule is
                # about -- and it is routinely under the stub floor, so a length test
                # dropped exactly the claims most worth finding.
                yield piece[:SECTION_CHARS], where, what


if __name__ == "__main__":
    import argparse
    import collections
    parser = argparse.ArgumentParser(description="count the corpus under a declared scope")
    parser.add_argument("roots", nargs="+")
    parser.add_argument("--outside", nargs="*", default=None,
                        help="patterns outside the corpus; pass with no values for none")
    parser.add_argument("--logbook", default="DNEVNIK.md")
    args = parser.parse_args()
    scope = Scope(args.outside)
    counts = collections.Counter()
    words = 0
    for text, _, what in chunks(args.roots, scope, args.logbook):
        counts[what] += 1
        words += len(text.split())
    print(scope.describe())
    print(f"chunks: {sum(counts.values())} · words: {words:,}")
    for what, n in counts.most_common():
        print(f"  {what:9} {n}")
