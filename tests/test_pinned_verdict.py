"""The pinned run's verdict reads what the runner printed, not only its exit code.

ZA-OPRAVYANE row 74 (Kyle Bartlett, 23.10: "The send returned success ... the email went out
blank"): `go test` in a module with no test files exits 0 and was recorded "passed"; unittest's
"NO TESTS RAN" exits 5 and was "failed"; jest's "No tests found" exits 1. Row 75: "no tests ran"
was exit 5 with the substring "pytest" anywhere in the command, so another program exiting 5 from
a path holding "pytest" was "no tests ran".

The runner is called as Stop calls it, `baton_stop.py --run-tests <folder>`, synchronously here.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import site
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_stop.py"
PY = shlex.quote(sys.executable)


def _env(tmp_path, **more):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               CLAUDE_PLUGIN_DATA=str(tmp_path / "data"), PYTHONUSERBASE=site.getuserbase(), **more)
    return env


def _run(tmp_path, command, cwd, names=(), env=None) -> dict:
    folder = tmp_path / "tasks" / "svc"
    folder.mkdir(parents=True, exist_ok=True)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "baton.local.json").write_text(json.dumps({"tests": {"svc": {
        "command": command, "cwd": str(cwd), "timeout_s": 120,
        "env": ["PYTHONUSERBASE", *names]}}}), "utf-8")
    out = subprocess.run([sys.executable, str(HOOK), "--run-tests", str(folder)],
                         env=env or _env(tmp_path), capture_output=True, timeout=180)
    assert out.returncode == 0, out.stderr
    return json.loads((data / "baton.tests.svc.json").read_text("utf-8"))


def _prints(text: str, code: int) -> str:
    """A command that prints `text` and exits with `code`: a runner's output, without the runner."""
    return f"{PY} -c {shlex.quote(f'import sys; print({text!r}); sys.exit({code})')}"


# -- row 74: exit 0 (or another code) and no test ran ---------------------------------------------

def test_unittest_that_found_nothing_is_no_tests_ran(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    rec = _run(tmp_path, f"{PY} -m unittest discover -s {shlex.quote(str(empty))}", empty)
    assert rec["verdict"] == "no tests ran", rec


@pytest.mark.parametrize("out,code", [
    ("?   \texample.com/svc\t[no test files]", 0),                                   # go test ./...
    ("ok  \texample.com/svc\t0.002s [no tests to run]", 0),                         # go test -run X
    ("No tests found, exiting with code 1\nRun with `--passWithNoTests` to exit with code 0", 1),
    ("No tests found, exiting with code 0", 0),                                     # jest, passWithNoTests
    ("No test files found, exiting with code 1", 1),                                # vitest
    ("\n----------------------------------------------------------------------\n"
     "Ran 0 tests in 0.000s\n\nOK", 0),                                             # unittest < 3.12
], ids=["go-no-test-files", "go-no-tests-to-run", "jest", "jest-pass-with-none", "vitest",
        "unittest-old"])
def test_a_runner_that_says_it_ran_nothing_is_no_tests_ran(tmp_path, out, code):
    rec = _run(tmp_path, _prints(out, code), tmp_path)
    assert rec["verdict"] == "no tests ran", rec


def test_go_with_one_package_tested_is_judged_by_its_code(tmp_path):
    out = "?   \texample.com/svc/cmd\t[no test files]\nok  \texample.com/svc\t0.004s"
    assert _run(tmp_path, _prints(out, 0), tmp_path)["verdict"] == "passed"
    out = "?   \texample.com/svc/cmd\t[no test files]\nFAIL\texample.com/svc\t0.004s\nFAIL"
    assert _run(tmp_path, _prints(out, 1), tmp_path)["verdict"] == "failed"


@pytest.mark.skipif(not shutil.which("go"), reason="go not installed")
def test_real_go_with_no_test_files(tmp_path):
    mod = tmp_path / "gomod"
    mod.mkdir()
    (mod / "go.mod").write_text("module example.com/svc\n\ngo 1.20\n", "utf-8")
    (mod / "main.go").write_text("package main\n\nfunc main() {}\n", "utf-8")
    env = _env(tmp_path, GOCACHE=str(tmp_path / "gocache"), GOFLAGS="-mod=mod")
    rec = _run(tmp_path, "go test ./...", mod, names=["GOCACHE", "GOFLAGS"], env=env)
    assert rec["verdict"] == "no tests ran", rec


def test_a_real_pass_is_still_passed_and_a_real_failure_failed(tmp_path):
    assert _run(tmp_path, _prints("5 passed in 0.12s", 0), tmp_path)["verdict"] == "passed"
    assert _run(tmp_path, _prints("1 failed, 4 passed in 0.12s", 1), tmp_path)["verdict"] == "failed"


# -- row 75: "pytest" in the path is not pytest ---------------------------------------------------

def test_exit_5_from_another_program_under_a_pytest_path_is_failed(tmp_path):
    assert "pytest" in str(tmp_path)          # pytest's own tmp path: the case of the row
    rec = _run(tmp_path, f"cd {shlex.quote(str(tmp_path))} && exit 5", tmp_path)
    assert rec["exit"] == 5 and rec["verdict"] == "failed", rec
