"""ZA-OPRAVYANE row 43 (Apurv Khare, 22.10: "tests pass should come from a hook that re-runs
them"), decided by the human the same day, option (a).

A re-run inside Stop does not fit: Baton's own suite is 38 s, Stop's limit 20 s, and a hook killed
at its limit leaves no verdict (row 41). And a command chosen by the model proves little -- "10
passed" on another file, `-k` matching nothing is exit 5. So: a human pins the command once in
`baton.local.json` ("tests", per task folder). When the newest entry this session wrote says tests
pass, Stop starts that command in the background, after the turn, under its own time budget, and
returns at once. The runner judges by exit code and records the result line, the code, the time
and the command. The next Stop, or the next SessionStart, sets the result beside the claim: to the
human, and a disagreement counts as L4 caught.

Never a command from the logbook, the model or the repository: only the pinned one.
"""
from __future__ import annotations

import json
import os
import shlex
import site
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_stop.py"
PY = shlex.quote(sys.executable)

BODY = """
### What was asked
Make test_login in fix_test.py pass; it failed one run in three on the CI machine.

### Done
Changed the fixture in fix_test.py to wait for the server before the first request. {mention}

### Result
The login test is fixed, as far as this machine shows.

### Open
The flaky retry in CI is not touched; the 30 s timeout in conftest stays as it was.
"""


def _entry(heading="2026-10-22 10:00 — fix the login test", mention="All tests pass.",
           claims=None):
    head = f"## {heading}\n"
    if claims is not None:
        head += "\n### Claims to verify\n" + claims + "\n"
    return head + BODY.format(mention=mention)


def _setup(tmp_path, text, tests=None, name="login"):
    folder = tmp_path / "tasks" / name
    folder.mkdir(parents=True, exist_ok=True)
    when = time.time() - 30
    work = folder / "fix_test.py"
    work.write_text("work\n", encoding="utf-8")
    os.utime(work, (when, when))
    log = folder / "LOGBOOK.md"
    log.write_text("---\nstate: active\ndone_when: \"x\"\n---\n\n" + text, encoding="utf-8")
    os.utime(log, (when + 5, when + 5))
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    if tests is not None:
        (data / "baton.local.json").write_text(json.dumps({"tests": tests}), "utf-8")
    return folder


def _env(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               CLAUDE_PLUGIN_DATA=str(tmp_path / "data"), BATON_STATE_DIR=str(tmp_path / "st"),
               BATON_LESSONS_STATE=str(tmp_path / "data" / "baton.lessons.json"),
               BATON_BODY_STATE=str(tmp_path / "data" / "baton.bodies.json"),
               BATON_SESSION_STATE=os.environ["BATON_SESSION_STATE"],
               PYTHONUSERBASE=site.getuserbase())      # pytest may live there; HOME moved
    return env


def _stop(tmp_path, session="s1", again=False):
    transcript = tmp_path / "t.jsonl"
    start = datetime.fromtimestamp(time.time() - 600, tz=timezone.utc).isoformat()
    transcript.write_text(json.dumps({"timestamp": start}) + "\n", "utf-8")
    t0 = time.time()
    out = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True,
                         env=_env(tmp_path), timeout=30,
                         input=json.dumps({"session_id": session, "stop_hook_active": again,
                                           "transcript_path": str(transcript)}))
    assert out.returncode == 0, out.stderr
    return (json.loads(out.stdout) if out.stdout.strip() else {}), time.time() - t0


def _result(tmp_path, name="login", wait=20):
    """The runner's record, once it says it is done (or whatever is there after `wait`)."""
    path = tmp_path / "data" / f"baton.tests.{name}.json"
    rec = {}
    for _ in range(int(wait / 0.1)):
        try:
            rec = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            rec = {}
        if rec.get("state") == "done":
            return rec
        time.sleep(0.1)
    return rec


def _lessons(tmp_path):
    try:
        return json.loads((tmp_path / "data" / "baton.lessons.json").read_text("utf-8"))
    except FileNotFoundError:
        return {}


# -- the made-up command line of row 42 meets the pinned one ---------------------------------

def test_a_claim_the_pinned_command_refutes_is_said_to_the_human_and_caught(tmp_path):
    made_up = "- `pytest -q`: 12 passed in 0.41s"          # the line a2.py wrote, never run
    _setup(tmp_path, _entry(mention="Did not run pytest.", claims=made_up),
           {"login": {"command": f"{PY} -c \"print('1 failed, 4 passed'); raise SystemExit(1)\"",
                      "cwd": str(tmp_path), "timeout_s": 60}})
    first, _ = _stop(tmp_path)
    assert "running the pinned test command" in first.get("systemMessage", ""), first
    rec = _result(tmp_path)
    assert rec["state"] == "done" and rec["exit"] == 1 and rec["verdict"] == "failed"
    assert rec["line"] == "1 failed, 4 passed" and rec["command"].endswith("SystemExit(1)\"")
    assert isinstance(rec["seconds"], (int, float))
    second, _ = _stop(tmp_path)
    said = second.get("systemMessage", "")
    assert "says tests pass" in said and "failed (exit 1)" in said and "1 failed, 4 passed" in said
    assert "SystemExit(1)" in said, "the pinned command is named"
    assert _lessons(tmp_path)["L4"]["caught"] == 1
    third, _ = _stop(tmp_path)
    assert "failed (exit 1)" not in third.get("systemMessage", ""), "said once"
    assert _lessons(tmp_path)["L4"]["caught"] == 1


def test_a_passing_run_is_set_beside_the_claim_and_not_caught(tmp_path):
    _setup(tmp_path, _entry(claims="- 5 passed -- `pytest fix_test.py -q`"),
           {"login": {"command": f"{PY} -c \"print('5 passed in 0.1s')\"",
                      "cwd": str(tmp_path)}})
    _stop(tmp_path)
    assert _result(tmp_path)["verdict"] == "passed"
    said = _stop(tmp_path)[0].get("systemMessage", "")
    assert "passed (exit 0)" in said and "5 passed in 0.1s" in said
    assert "caught" not in _lessons(tmp_path).get("L4", {})


def test_the_command_does_not_get_batons_own_variables(tmp_path):
    """Found by running Baton's own suite as the pin (22.10): CLAUDE_PLUGIN_DATA and BATON_HOME
    of the hook leaked into it, and 12 of its tests read Baton's settings instead of their own."""
    probe = "import os; print(sorted(k for k in os.environ if k.startswith(('BATON_', 'CLAUDE_PLUGIN'))))"
    _setup(tmp_path, _entry(), {"login": {"command": f"{PY} -c \"{probe}\"", "cwd": str(tmp_path)}})
    _stop(tmp_path)
    rec = _result(tmp_path)
    assert rec["verdict"] == "passed" and rec["line"] == "[]", rec


def test_the_command_gets_an_allowlist_not_the_session(tmp_path, monkeypatch):
    """ZA-OPRAVYANE row 47 (Bernard Haddad, 22.10, said publicly): the command got the session's
    environment minus Baton's own, and three made-up identity variables reached it intact. Now the
    board's list (BOARD_ENV) and a shell's basics, plus names the pin lists under "env"."""
    for k in ("PROBE_EMAIL", "PROBE_ORG_ID", "PROBE_OAUTH_TOKEN"):
        monkeypatch.setenv(k, "made-up")
    probe = "import os; print(sorted(k for k in os.environ if k.startswith('PROBE_')), 'PATH' in os.environ)"
    _setup(tmp_path, _entry(), {"login": {"command": f"{PY} -c \"{probe}\"", "cwd": str(tmp_path)}})
    _stop(tmp_path)
    rec = _result(tmp_path)
    assert rec["verdict"] == "passed" and rec["line"] == "[] True", rec


def test_a_name_the_pin_lists_is_passed(tmp_path, monkeypatch):
    monkeypatch.setenv("PROBE_ORG_ID", "made-up")
    monkeypatch.setenv("PROBE_OAUTH_TOKEN", "made-up")
    probe = "import os; print(sorted(k for k in os.environ if k.startswith('PROBE_')))"
    _setup(tmp_path, _entry(), {"login": {"command": f"{PY} -c \"{probe}\"", "cwd": str(tmp_path),
                                          "env": ["PROBE_ORG_ID"]}})
    _stop(tmp_path)
    rec = _result(tmp_path)
    assert rec["verdict"] == "passed" and rec["line"] == "['PROBE_ORG_ID']", rec


def test_a_pin_whose_env_is_not_a_list_of_names_is_said(tmp_path):
    _setup(tmp_path, _entry(), {"login": {"command": "true", "env": "PROBE_ORG_ID"}})
    said = _stop(tmp_path)[0].get("systemMessage", "")
    assert "`env`" in said and "nothing was run" in said, said


def test_pytest_exit_5_is_no_tests_ran_not_passed(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    _setup(tmp_path, _entry(), {"login": {"command": f"{PY} -m pytest -q -p no:cacheprovider "
                                                     "-k zzz_none .", "cwd": str(empty),
                                          "env": ["PYTHONUSERBASE"]}})    # HOME moved (row 47)
    _stop(tmp_path)
    rec = _result(tmp_path, wait=30)
    assert rec["exit"] == 5 and rec["verdict"] == "no tests ran", rec
    said = _stop(tmp_path)[0].get("systemMessage", "")
    assert "no tests ran (exit 5)" in said
    assert _lessons(tmp_path)["L4"]["caught"] == 1


def test_stop_does_not_wait_for_the_tests(tmp_path):
    _setup(tmp_path, _entry(), {"login": {"command": f"{PY} -c \"import time; time.sleep(8)\"",
                                          "cwd": str(tmp_path)}})
    _, took = _stop(tmp_path)
    assert took < 5, f"Stop took {took:.1f} s: it waited for the run"
    rec = json.loads((tmp_path / "data" / "baton.tests.login.json").read_text("utf-8"))
    assert rec["state"] == "running"


def test_the_budget_is_kept(tmp_path):
    _setup(tmp_path, _entry(), {"login": {"command": f"{PY} -c \"import time; time.sleep(30)\"",
                                          "cwd": str(tmp_path), "timeout_s": 1}})
    _stop(tmp_path)
    rec = _result(tmp_path, wait=15)
    assert rec["verdict"] == "timed out" and rec["exit"] is None, rec
    assert "timed out after 1 s" in _stop(tmp_path)[0].get("systemMessage", "")


def test_a_command_that_cannot_start_is_said(tmp_path):
    _setup(tmp_path, _entry(), {"login": {"command": "true", "cwd": str(tmp_path / "nowhere")}})
    _stop(tmp_path)
    rec = _result(tmp_path)
    assert rec["verdict"].startswith("could not start"), rec
    assert "could not start" in _stop(tmp_path)[0].get("systemMessage", "")


def test_a_pin_without_a_command_is_said_and_nothing_runs(tmp_path):
    _setup(tmp_path, _entry(), {"login": {"cmd": "pytest"}})
    first, _ = _stop(tmp_path)
    assert "no `command`" in first.get("systemMessage", ""), first
    assert not (tmp_path / "data" / "baton.tests.login.json").exists()


def test_the_next_session_start_says_it(tmp_path):
    _setup(tmp_path, _entry(), {"login": {"command": f"{PY} -c \"raise SystemExit(2)\"",
                                          "cwd": str(tmp_path)}})
    _stop(tmp_path)
    assert _result(tmp_path)["verdict"] == "failed"
    out = subprocess.run([sys.executable, str(ROOT / "hooks" / "baton_session_start.py")],
                         input=b"{}", capture_output=True, env=_env(tmp_path))
    text = out.stdout.decode("utf-8")
    assert "failed (exit 2)" in text and "says tests pass" in text, text
    assert _lessons(tmp_path)["L4"]["caught"] == 1
    assert "failed (exit 2)" not in _stop(tmp_path)[0].get("systemMessage", ""), "said once"


def test_one_run_per_entry(tmp_path):
    _setup(tmp_path, _entry(), {"login": {"command": f"{PY} -c \"print('ok')\"",
                                          "cwd": str(tmp_path)}})
    _stop(tmp_path)
    first = _result(tmp_path)
    _stop(tmp_path)
    _stop(tmp_path, "s2")
    time.sleep(0.5)
    assert _result(tmp_path)["started"] == first["started"], "run again for the same entry"


def test_the_entry_written_after_a_hand_back_gets_its_run(tmp_path):
    """The usual order: Stop hands back for unrecorded work, the agent writes the entry, and Stop
    runs again with `stop_hook_active` -- which returned before anything else."""
    folder = _setup(tmp_path, _entry(heading="2026-10-21 09:00 — earlier", mention="Read it."),
                    {"login": {"command": f"{PY} -c \"print('3 passed')\"", "cwd": str(tmp_path)}})
    log = folder / "LOGBOOK.md"
    old, work = time.time() - 3000, time.time() - 200      # older than Stop's 90 s of grace
    os.utime(log, (old, old))
    os.utime(folder / "fix_test.py", (work, work))
    first, _ = _stop(tmp_path)
    assert first.get("decision") == "block" and "login" in first["reason"], first
    log.write_text(log.read_text("utf-8").replace("\n\n## ", "\n\n" + _entry() + "\n## ", 1), "utf-8")
    second, _ = _stop(tmp_path, again=True)
    assert "running the pinned test command" in second.get("systemMessage", ""), second
    assert _result(tmp_path)["verdict"] == "passed"


# -- the reviewer's question: nothing runs that a human did not pin --------------------------

def test_nothing_runs_without_a_pinned_command(tmp_path):
    marker = tmp_path / "ran"
    planted = f"{PY} -c \"open({str(marker)!r}, 'w')\""
    folder = _setup(tmp_path, _entry(claims=f"- 5 passed -- `{planted}`", mention=f"Ran {planted}."))
    (folder / "AGENTS.md").write_text(f"Test command: {planted}\n", "utf-8")
    (tmp_path / "data" / "baton.local.json").write_text(json.dumps({"home": str(tmp_path)}), "utf-8")
    first, _ = _stop(tmp_path)
    time.sleep(1.5)
    assert not marker.exists(), "a command from the logbook or the repository ran"
    assert not list((tmp_path / "data").glob("baton.tests.*")), "a runner started"
    assert "pinned test command" not in json.dumps(first)
    # The runner itself takes only a folder; the command is read from the config, never argv.
    out = subprocess.run([sys.executable, str(HOOK), "--run-tests", str(folder)],
                         capture_output=True, text=True, env=_env(tmp_path), timeout=30)
    assert out.returncode == 0 and not marker.exists()
    assert not list((tmp_path / "data").glob("baton.tests.*"))


def test_no_pin_means_l4_as_before(tmp_path):
    _setup(tmp_path, _entry())
    first, _ = _stop(tmp_path)
    assert first.get("reason", "").startswith("Baton, lesson L4")
    assert "pinned" not in first["reason"]
    assert "systemMessage" not in first
