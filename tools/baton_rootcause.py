#!/usr/bin/env python3
"""Does a fix's test fail without the fix? Checked by running it, not by remembering to.

    python3 tools/baton_rootcause.py <base-ref> <test> [<test> ...]

ZA-OPRAVYANE row 121, after pullboard's "root cause control" (DOCTRINE T10): a fix's tests are
run on the parent, where they must fail, and on the fix, where they must pass. Until now that
was a manual step in the release skill, and a step that is remembered is a step that is skipped.

The base's files are checked out into a temporary git worktree, and the working tree's test
directory (`tests/`, or --tests) is put over the base's, together with any named test file
outside it -- so a new, uncommitted test is checked too. Each test is run there (it must fail)
and here (it must pass), one pytest run per test, judged by exit code. Verdicts:

    PINS THE FIX          fails on the base, passes here
    DOES NOT PIN IT       passes on the base too: it would not have caught the bug
    FAILS HERE            fails with the fix
    RAN NOTHING           pytest collected no test (exit 5), on either side

Exit 0 only when every test pins the fix. Needs git and pytest, nothing else.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _git(*args, cwd) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def _pytest(test: str, cwd: Path) -> int:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", test],
                          cwd=cwd, capture_output=True, text=True).returncode


def verdict(base_rc: int, head_rc: int) -> str:
    if 5 in (base_rc, head_rc):
        return "RAN NOTHING"
    if head_rc != 0:
        return "FAILS HERE"
    if base_rc == 0:
        return "DOES NOT PIN IT"
    return "PINS THE FIX" + ("" if base_rc == 1 else f" (on the base: an error, exit {base_rc})")


def check(base: str, tests: list[str], tests_dir: str = "tests", repo: Path | None = None) -> list:
    """(test, base exit, head exit, verdict) for each test."""
    repo = Path(_git("rev-parse", "--show-toplevel", cwd=repo or Path.cwd()))
    tmp = Path(tempfile.mkdtemp(prefix="baton-rootcause-"))
    where = tmp / "base"
    try:
        _git("worktree", "add", "--detach", str(where), base, cwd=repo)
        ignore = shutil.ignore_patterns("__pycache__", ".pytest_cache")
        shutil.rmtree(where / tests_dir, ignore_errors=True)
        if (repo / tests_dir).is_dir():
            shutil.copytree(repo / tests_dir, where / tests_dir, ignore=ignore)
        for test in tests:
            path = test.split("::", 1)[0]
            if (repo / path).is_file():
                (where / path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(repo / path, where / path)
        out = []
        for test in tests:
            base_rc, head_rc = _pytest(test, where), _pytest(test, repo)
            out.append((test, base_rc, head_rc, verdict(base_rc, head_rc)))
        return out
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(where)], cwd=repo,
                       capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Does each test fail on the base and pass here?")
    ap.add_argument("base", help="the commit without the fix, e.g. main or HEAD~1")
    ap.add_argument("tests", nargs="+", help="test files or ids (file::name)")
    ap.add_argument("--tests", dest="tests_dir", default="tests",
                    help="the directory taken from the working tree (default tests)")
    a = ap.parse_args(argv)
    results = check(a.base, a.tests, a.tests_dir)
    for test, base_rc, head_rc, said in results:
        print(f"{said:<16} {test}  (base exit {base_rc}, here exit {head_rc})")
    pinned = sum(r[3].startswith("PINS THE FIX") for r in results)
    print(f"\n{pinned} of {len(results)} pin the fix against {a.base}")
    return 0 if pinned == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
