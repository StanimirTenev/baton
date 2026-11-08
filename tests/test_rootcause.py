"""ZA-OPRAVYANE row 121: tools/baton_rootcause.py -- a fix's test must fail on the base and pass here.

A small repository is made in tmp_path: a base commit with a bug, the fix on top, and a test
in the working tree. The tool checks the base out into a temporary worktree, puts the working
tree's tests over it, and runs each test on both sides.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "baton_rootcause.py"
spec = importlib.util.spec_from_file_location("baton_rootcause", TOOL)
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)


def _git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                           *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def _repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / "lib.py").write_text("def double(x):\n    return x + 2\n", "utf-8")     # the bug
    (repo / "tests" / "test_old.py").write_text("def test_old():\n    assert True\n", "utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "lib.py").write_text("def double(x):\n    return x * 2\n", "utf-8")     # the fix
    _git(repo, "commit", "-q", "-am", "fix")
    # The new test is not committed: the working tree's tests are the ones checked.
    (repo / "tests" / "test_double.py").write_text(
        "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent.parent))\n"
        "from lib import double\n\n"
        "def test_pins():\n    assert double(3) == 6\n\n"
        "def test_does_not_pin():\n    assert double(2) == 4\n", "utf-8")
    return repo, base


def test_a_test_that_fails_on_the_base_pins_the_fix(tmp_path):
    repo, base = _repo(tmp_path)
    out = rc.check(base, ["tests/test_double.py::test_pins"], repo=repo)
    assert [r[3] for r in out] == ["PINS THE FIX"], out
    assert "baton-rootcause-" not in _git(repo, "worktree", "list"), "the temporary worktree is removed"


def test_a_test_that_passes_on_the_base_does_not_pin_it(tmp_path):
    repo, base = _repo(tmp_path)
    out = rc.check(base, ["tests/test_double.py::test_does_not_pin", "tests/test_old.py"],
                   repo=repo)
    assert [r[3] for r in out] == ["DOES NOT PIN IT", "DOES NOT PIN IT"], out


def test_a_test_that_fails_with_the_fix_is_said(tmp_path):
    repo, base = _repo(tmp_path)
    (repo / "lib.py").write_text("def double(x):\n    return 0\n", "utf-8")
    out = rc.check(base, ["tests/test_double.py::test_pins"], repo=repo)
    assert out[0][3] == "FAILS HERE", out


def test_the_exit_code_is_zero_only_when_every_test_pins(tmp_path, monkeypatch, capsys):
    repo, base = _repo(tmp_path)
    monkeypatch.chdir(repo)
    assert rc.main([base, "tests/test_double.py::test_pins"]) == 0
    assert rc.main([base, "tests/test_double.py::test_pins", "tests/test_old.py"]) == 1
    assert "1 of 2 pin the fix" in capsys.readouterr().out


def test_verdicts():
    assert rc.verdict(1, 0) == "PINS THE FIX"
    assert rc.verdict(2, 0).startswith("PINS THE FIX (on the base: an error")
    assert rc.verdict(0, 0) == "DOES NOT PIN IT"
    assert rc.verdict(1, 1) == "FAILS HERE"
    assert rc.verdict(5, 0) == "RAN NOTHING"
