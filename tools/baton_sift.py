#!/usr/bin/env python3
"""Reading order for a long candidate list, scored once and cheaply.

    baton_sift.py --question "Does this repository ship a CBOM generator?" < candidates.tsv
    baton_sift.py --question "…" --threshold 0.5 --out scores.tsv < candidates.tsv

Input is TSV on stdin: an id in the first column, the text to judge in the rest.
Output is every candidate, sorted by score, with the score.

## What this is for

A research pass reads hundreds of candidates and judges each one expensively. Measured on
this machine 2026-09-26: one agent paged 300 code-search hits and de-duplicated them by
hand; another filtered 935 + 576 arXiv entries with a title regex. A calibrated classifier
scores the same list for a fraction of a cent and puts the worthwhile ones first.

Measured on a real triage — 40 GitHub repositories, hand-labelled before the scores were
seen, "does this ship a tool that PRODUCES a cryptographic inventory":

| | |
|---|---|
| cost | **$0.00069** for 40 |
| false positives among the 11 hand-labelled NO | **0 at every threshold**; the highest NO scored 0.49 |
| medians | yes **0.84** · no **0.19** · undecidable-from-the-input 0.36 |
| ⭐ the actual win | sorted by score, **all 21 yes-es were in the top 25 of 40** |

Of the three disagreements, **two were the labeller's fault, not the model's**: one repo's
only CBOM file was a frontend graph component, another had no CBOM file at all. The third
was a real limit of the input — a repository whose description does not mention what it
does. That is a property of the description, and no scorer fixes it.

## ⛔ Reading ORDER, not a right of exclusion

Nothing is dropped, ever. `--prag` splits the list into "read first" and "read after" and
prints **both**, with counts. This is not fastidiousness: the failure it prevents was made
four times in one day on this machine — a search reported as "found X" where the truth was
"did not look at the rest". A scorer used as a filter makes the unread invisible, and an
absence written without the check that would find it is the defect this project exists to
refuse.

The threshold travels in the output for the same reason a coverage figure travels with its
denominator.

## ⚠️ What it does NOT do

It scores a well-posed question. It does not tell you the question is wrong. Every mistake
made here on 2026-09-26 was in the framing -- a regex too narrow to match `DHE_RSA`, an
evidence window that hid 59% of the text, a category asserted from an unvalidated pattern,
a baseline two dozen versions stale -- and a classifier would have answered each of those
confidently and uselessly. Use it to order reading and to cross-check a claim against a
document. Do not use it to decide what the question is.

⚠️ Measured on one kind of candidate (repository descriptions), n=40. A threshold does not
transfer; measure it again on arXiv rows or code hits. See `baton-pregled` for why.
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import sys

PREGLED = pathlib.Path(__file__).resolve().parent / "baton_review.py"


def _pregled():
    """`baton_review` owns the key, the confidentiality guard and the spend log."""
    if "baton_review" in sys.modules:
        return sys.modules["baton_review"]
    spec = importlib.util.spec_from_file_location("baton_review", PREGLED)
    module = importlib.util.module_from_spec(spec)
    sys.modules["baton_review"] = module
    spec.loader.exec_module(module)
    return module


def kandidati(lines):
    """(id, text) per non-empty line of TSV; the id is column one."""
    for line in lines:
        line = line.rstrip("\n")
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        yield parts[0], " · ".join(p for p in parts if p.strip())


def otsey(items, vapros: str, bp=None):
    """[(id, text, score)] in input order. Confidential items are kept and marked -1.0."""
    if not vapros or not vapros.strip():
        raise ValueError("pass --vapros: a typed question. A score with no question is a "
                         "number nobody can check.")
    bp = bp or _pregled()
    key, words = bp.klyuch(), bp.config()["poveritelni"]
    # The question is asked of every candidate, so it is checked once, here, before a
    # single call is made. `pitay` now reads the whole serialised body and would stop
    # this too -- on candidate one, after the run has started. Refusing up front says
    # what is wrong instead of failing mid-list.
    held_question = bp.poveritelno(vapros, "--vapros", words)
    if held_question:
        raise ValueError(f"the question itself carries „{held_question}“ and is asked of "
                         f"every candidate. It does not leave the machine.")
    question = {"otsey": {"type": "noul", "instructions": vapros.strip(),
                          "criteria": {"true": "yes", "false": "no"}}}
    out, spent, held = [], 0.0, 0
    for ident, text in items:
        if bp.poveritelno(text, ident, words):
            held += 1
            out.append((ident, text, -1.0))
            continue
        answer = bp.pitay(key, text, question, ident, words)
        spent += answer.get("usage", {}).get("cost", 0)
        out.append((ident, text, answer["answers"]["otsey"]["noul"]))
    return out, spent, held


def report(scored, prag, vapros, spent, held, stream=sys.stdout):
    """Everything, sorted, in two named groups. Nothing is ever omitted."""
    order = sorted(scored, key=lambda r: -r[2])
    print(f"question: {vapros.strip()[:110]}", file=stream)
    print(f"candidates: {len(order)} · spent ${spent:.5f}"
          + (f" · held back as confidential: {held}" if held else ""), file=stream)
    if prag is None:
        print("no threshold given — the whole list, in reading order:\n", file=stream)
        for ident, _text, score in order:
            print(f"  {score:5.2f}  {ident}", file=stream)
        return order
    first = [r for r in order if r[2] >= prag]
    later = [r for r in order if r[2] < prag]
    print(f"threshold {prag} · read first {len(first)} · "
          f"read after {len(later)} — NOT discarded\n", file=stream)
    for name, rows in (("READ FIRST", first), ("READ AFTER (nothing is dropped)", later)):
        print(f"--- {name} ({len(rows)}) ---", file=stream)
        for ident, _text, score in rows:
            print(f"  {score:5.2f}  {ident}", file=stream)
        print("", file=stream)
    print("⚠️ The second group was scored, not judged. A candidate below a threshold is one "
          "nobody\n   has read yet — saying otherwise turns 'I did not look' into 'there is "
          "nothing there'.", file=stream)
    return order


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--question", "--vapros", dest="vapros", metavar="QUESTION", required=True, help="the typed question, in English")
    parser.add_argument("--threshold", "--prag", dest="prag", metavar="THRESHOLD", type=float, default=None,
                        help="split into read-first/read-after; both are printed")
    parser.add_argument("--out", "--izhod", dest="izhod", metavar="FILE", default=None, help="also write every score as TSV")
    args = parser.parse_args(argv)

    items = list(kandidati(sys.stdin))
    if not items:
        print("no candidates on stdin", file=sys.stderr)
        return 1
    scored, spent, held = otsey(items, args.vapros)
    order = report(scored, args.prag, args.vapros, spent, held)
    if args.izhod:
        with open(args.izhod, "w", encoding="utf-8") as handle:
            handle.write(f"# vapros={args.vapros.strip()}\n# prag={args.prag}\n")
            handle.write("id\tnoul\n")
            for ident, _text, score in order:
                handle.write(f"{ident}\t{score}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
