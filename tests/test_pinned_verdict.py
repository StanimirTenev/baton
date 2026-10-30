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


# -- row 77: the failing test skipped, xfailed or deleted ----------------------------------------

GOOD = "def test_ok():\n    assert 1 + 1 == 2\n"
BROKEN = "def test_export():\n    assert 'tz' in 'naive date'\n"
PYTEST = f"{PY} -m pytest -q -p no:cacheprovider ."


def _repo(tmp_path, export: str | None) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / "test_ok.py").write_text(GOOD, "utf-8")
    if export is None:
        (repo / "test_export.py").unlink(missing_ok=True)
    else:
        (repo / "test_export.py").write_text(export, "utf-8")
    return repo


@pytest.mark.parametrize("mark", ["skip(reason='flaky')", "xfail"])
def test_a_pass_with_the_failing_test_set_aside_is_not_passed(tmp_path, mark):
    repo = _repo(tmp_path, f"import pytest\n\n@pytest.mark.{mark}\n" + BROKEN)
    rec = _run(tmp_path, PYTEST, repo)
    assert rec["exit"] == 0 and rec["verdict"] == "passed, with 1 skipped or xfailed", rec


def test_a_pass_after_the_failing_test_was_deleted_is_not_passed(tmp_path):
    assert _run(tmp_path, PYTEST, _repo(tmp_path, BROKEN))["verdict"] == "failed"
    rec = _run(tmp_path, PYTEST, _repo(tmp_path, None))
    assert rec["exit"] == 0 and rec["verdict"].startswith("passed, with 1 fewer tests"), rec


def test_the_same_skip_as_the_last_run_is_passed(tmp_path):
    repo = _repo(tmp_path, "import pytest\n\n@pytest.mark.skip\n" + BROKEN)
    _run(tmp_path, PYTEST, repo)
    assert _run(tmp_path, PYTEST, repo)["verdict"] == "passed"


def test_another_command_is_not_a_baseline(tmp_path):
    _run(tmp_path, _prints("9 passed in 0.1s", 0), tmp_path)
    assert _run(tmp_path, _prints("2 passed in 0.1s", 0) + " ", tmp_path)["verdict"] == "passed"


@pytest.mark.parametrize("out", [
    "Ran 3 tests in 0.001s\n\nOK (skipped=1)",
    "Tests:       1 skipped, 2 passed, 3 total",
    "=== RUN   TestA\n--- PASS: TestA (0.00s)\n=== RUN   TestB\n    --- SKIP: TestB (0.00s)\nPASS",
], ids=["unittest", "jest", "go-v"])
def test_other_runners_skips_are_read(tmp_path, out):
    assert _run(tmp_path, _prints(out, 0), tmp_path)["verdict"] == "passed, with 1 skipped or xfailed"


# -- row 52: test files edited in the session are said beside the result -------------------------

def test_test_files_saved_since_the_session_began_are_said(tmp_path, monkeypatch):
    import importlib.util
    import time
    repo = _repo(tmp_path, None)
    old = time.time() - 3600
    os.utime(repo / "test_ok.py", (old, old))
    (repo / "test_new.py").write_text(GOOD, "utf-8")
    data = tmp_path / "data"
    data.mkdir()
    (data / "baton.tests.svc.json").write_text(json.dumps(
        {"since": time.time() - 600, "entry": "## 2026-10-23 09:00 — x", "command": PYTEST}), "utf-8")
    rec = _run(tmp_path, PYTEST, repo)
    assert rec["tests_edited"] == ["test_new.py"], rec
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    spec = importlib.util.spec_from_file_location("bss_edited", ROOT / "hooks" / "baton_session_start.py")
    ss = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ss)
    said = " ".join(ss.tests_results())
    assert "test files saved in that folder since the session began: test_new.py" in said, said


def test_a_failing_run_that_quotes_no_tests_ran_is_failed(tmp_path):
    """ZA-OPRAVYANE row 84 (agent, 23.10): the phrases were searched in the whole output at any
    exit code, so a failed run whose assertion quoted "no tests ran" was recorded as no tests
    ran. A runner that counted tests ran tests."""
    text = ("E   AssertionError: assert 'no tests ran' == 'passed'\n"
            "=========================== short test summary info ============================\n"
            "FAILED tests/test_x.py::test_verdict\n"
            "============================== 1 failed in 0.12s ===============================")
    rec = _run(tmp_path, _prints(text, 1), tmp_path)
    assert rec["verdict"] == "failed", rec
