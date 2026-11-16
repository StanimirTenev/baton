#!/usr/bin/env python3
"""Has an older logbook entry been edited since Baton recorded it?

    python3 tools/baton_ledger.py verify              # the ledger against the logbooks now
    python3 tools/baton_ledger.py verify --remote     # and against the copy you pushed
    python3 tools/baton_ledger.py ack --reason "the count was wrong"
    python3 tools/baton_ledger.py ack --folder alpha --heading "## 2026-10-20 09:00 — first" --reason "..."
    python3 tools/baton_ledger.py push                # to the remote you added yourself

A logbook is written newest entry on top, so it cannot be append-only. The ledger beside it
can: one line per entry -- folder, heading, the sha256 of the entry's text and of the line
before -- in a git repository of its own, appended by the Stop hook (ZA-OPRAVYANE row 153,
Musab Khiri, 16.11). `verify` recomputes every recorded entry from the logbooks as they are
and names (a) the entries whose text changed after they were recorded, (b) the recorded
entries that are gone, (c) a broken chain: a line that does not follow the one before, a
ledger shorter than Baton last wrote it, a change to it that is not committed.

`ack` is how an edit is accepted: a new line with the entry's hash now and the reason. No line
is ever edited. Without --folder or --heading it accepts every finding, the chain's too.

What it does not prove: the agent runs as you, so it can rewrite the ledger and its history
as well as the logbook. Only a copy elsewhere that refuses a rewritten history (a remote with
force-push refused, or branch protection) holds; `verify --remote` asks that copy. Baton never
adds a remote and never pushes by itself: `push` does, when you run it, and never forces.

Where: BATON_LEDGER, else `ledger` in baton.local.json, else `baton.ledger` beside Baton's
other state -- ${CLAUDE_PLUGIN_DATA} as a plugin (the skills pass it in), the hooks' folder for
a script install. The tasks: BATON_HOME and BATON_LOGBOOK, else baton.local.json, as for every
tool. The command SessionStart prints carries all three.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


core = _load("_baton", HERE.parent / "hooks" / "_baton.py")
corpus = _load("baton_corpus", HERE / "baton_corpus.py")


def where() -> tuple:
    """Task root, logbook name, ledger folder: the hook's choices, from outside the hook."""
    cfg = corpus.config()
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    base = Path(data) if data else cfg["where"].parent
    return cfg["home"], cfg["logbook"], core.ledger_dir(lambda name: base / name)


def _named(found: list) -> list:
    return [f"  {f}: {h}" + (f" (#{n + 1} of that heading)" if n else "") for f, h, n in found]


def _remote(d: Path) -> tuple:
    """(remote, branch) of the ledger's repository, or None for either."""
    out = core.ledger_git(d, "remote")
    remote = out.stdout.split()[0] if out and out.returncode == 0 and out.stdout.split() else None
    out = core.ledger_git(d, "symbolic-ref", "--short", "HEAD")
    branch = out.stdout.strip() if out and out.returncode == 0 else None
    return remote, branch


def verify(remote: bool) -> int:
    root, logbook, d = where()
    print(f"Baton ledger: {d}")
    rep = core.ledger_check(root, logbook, d)
    if rep is None:
        print("no ledger here yet: the Stop hook starts one at the end of the next turn.")
        return 0
    bad = 0
    print(f"{rep['lines']} lines, {rep['entries']} entries recorded for {root}")
    for kind, said in (("changed", "changed after they were recorded"),
                       ("gone", "recorded and gone")):
        if rep[kind]:
            bad += len(rep[kind])
            print(f"{kind}: {len(rep[kind])} {said}")
            print("\n".join(_named(rep[kind])))
    if rep["chain"]:
        bad += len(rep["chain"])
        print(f"chain: {len(rep['chain'])}")
        print("\n".join(f"  {what}" for _, what in rep["chain"]))
    if remote:
        bad += anchored(d)
    if bad:
        print("Nothing was changed. Read the entries; an edit you accept: "
              "`baton_ledger.py ack --reason \"<why>\"`.")
        return 1
    print("as recorded.")
    return 0


def anchored(d: Path) -> int:
    """Is what the remote holds still in this ledger's history? 0 when it is."""
    name, branch = _remote(d)
    if not name or not branch:
        print("remote: no remote added -- nothing outside this machine anchors the ledger")
        return 1
    out = core.ledger_git(d, "fetch", "-q", name, branch, timeout=60)
    if not out or out.returncode != 0:
        print(f"remote: could not fetch {name}: {(out.stderr.strip() if out else 'git did not run')}")
        return 1
    out = core.ledger_git(d, "merge-base", "--is-ancestor", "FETCH_HEAD", "HEAD")
    if not out or out.returncode != 0:
        print(f"remote: {name} holds history that this ledger no longer has -- it was rewritten "
              "here (or the remote has commits from elsewhere). The remote's copy is the one to believe.")
        return 1
    ahead = core.ledger_git(d, "rev-list", "--count", "FETCH_HEAD..HEAD")
    print(f"remote: {name}/{branch} is in this ledger's history"
          + (f"; {ahead.stdout.strip()} commits not pushed yet" if ahead and ahead.stdout.strip()
             not in ("", "0") else ""))
    return 0


def ack(reason: str, folder: str | None, heading: str | None) -> int:
    root, logbook, d = where()
    added = core.ledger_ack(root, logbook, d, reason, folder, heading)
    print(f"Baton ledger: {d}")
    print(f"{added} line{'' if added == 1 else 's'} added: accepted, with the reason"
          if added else "nothing to accept")
    return 0


def push() -> int:
    _, _, d = where()
    name, branch = _remote(d) if (d / ".git").exists() else (None, None)
    if not name or not branch:
        print(f"Baton ledger: {d}\nno remote: Baton never adds one. Add a private repository "
              f"yourself: git -C \"{d}\" remote add anchor <its address>")
        return 1
    out = core.ledger_git(d, "push", "-q", name, branch, timeout=120)
    if not out or out.returncode != 0:
        print(f"push to {name} refused or failed (never forced): "
              f"{out.stderr.strip() if out else 'git did not run'}")
        return 1
    print(f"pushed {branch} to {name}")
    return 0


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="Baton's ledger of logbook entries.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="the ledger against the logbooks as they are now")
    v.add_argument("--remote", action="store_true", help="and against the remote's copy")
    a = sub.add_parser("ack", help="accept what verify found, with a reason")
    a.add_argument("--reason", required=True)
    a.add_argument("--folder")
    a.add_argument("--heading")
    sub.add_parser("push", help="push the ledger to the remote you added")
    args = ap.parse_args(argv)
    if args.cmd == "verify":
        return verify(args.remote)
    if args.cmd == "ack":
        return ack(args.reason, args.folder, args.heading)
    return push()


if __name__ == "__main__":
    raise SystemExit(main())
