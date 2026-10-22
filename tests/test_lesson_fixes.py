"""ZA-OPRAVYANE row 44 (from Sentry's "recovery verification", 22.10): row 40 counted, for L2 only,
whether the step after a shown note looked like a check. Now every lesson: after Stop asks about an
entry (L1 an hour off the clock, L3 a public/private claim, L4 a tests claim), the next Stops look
at that folder's newest entry -- through the same code that raised the ask -- and count
`fixed_after` when the violation is gone, `not_fixed_after` when FIX_STOPS Stops pass without it.
/baton-doctor prints "fixed after the lesson: N of M" per lesson. A proxy, not proof: a new entry
on top of the flagged one counts as the answer too.

The fix usually lands on the second pass (`stop_hook_active`): the agent answers the hand-back.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_stop.py"

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


def _write(tmp_path, heading, mention, claims=None, age=30):
    folder = tmp_path / "tasks" / "login"
    folder.mkdir(parents=True, exist_ok=True)
    when = time.time() - age
    work = folder / "fix_test.py"
    if not work.exists():
        work.write_text("work\n", encoding="utf-8")
        os.utime(work, (when, when))
    head = f"## {heading}\n" + ("" if claims is None else f"\n### Claims to verify\n{claims}\n")
    log = folder / "LOGBOOK.md"
    log.write_text("---\nstate: active\ndone_when: \"x\"\n---\n\n" + head + BODY.format(mention=mention),
                   encoding="utf-8")
    return log


def _env(tmp_path):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               HOME=str(tmp_path / "home"), BATON_STATE_DIR=str(tmp_path / "state"))
    return env


def _stop(tmp_path, session="s1", again=False):
    transcript = tmp_path / "t.jsonl"
    start = datetime.fromtimestamp(time.time() - 600, tz=timezone.utc).isoformat()
    transcript.write_text(json.dumps({"timestamp": start}) + "\n", "utf-8")
    out = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True,
                         env=_env(tmp_path),
                         input=json.dumps({"session_id": session, "stop_hook_active": again,
                                           "transcript_path": str(transcript)}))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def _rec(lesson):
    try:
        return json.loads(Path(os.environ["BATON_LESSONS_STATE"]).read_text("utf-8")).get(lesson, {})
    except FileNotFoundError:
        return {}


H = "2026-10-22 10:00 — fix the login test"


def test_l4_fixed_on_the_second_pass(tmp_path):
    _write(tmp_path, H, "All tests pass.")
    assert "lesson L4" in _stop(tmp_path).get("reason", "")
    _write(tmp_path, H, "All tests pass.", claims="- 5 passed -- `pytest fix_test.py -q`")
    _stop(tmp_path, again=True)
    rec = _rec("L4")
    assert rec.get("fixed_after") == 1 and "not_fixed_after" not in rec, rec
    _stop(tmp_path, "s2")
    assert _rec("L4").get("fixed_after") == 1, "counted once"


def test_l4_not_fixed_after_three_stops(tmp_path):
    _write(tmp_path, H, "All tests pass.")
    assert "lesson L4" in _stop(tmp_path).get("reason", "")
    for n in range(3):
        _stop(tmp_path, f"t{n}")
    rec = _rec("L4")
    assert rec.get("not_fixed_after") == 1 and "fixed_after" not in rec, rec


def test_l3_fixed_when_the_claim_is_listed(tmp_path):
    _write(tmp_path, H, "The repository is private now.")
    assert "lesson L3" in _stop(tmp_path).get("reason", "")
    _write(tmp_path, H, "The repository is private now.",
           claims="- the repository is private (its settings page)")
    _stop(tmp_path, again=True)
    assert _rec("L3").get("fixed_after") == 1, _rec("L3")


def test_l1_fixed_when_the_hour_is_corrected(tmp_path):
    now = datetime.now()
    _write(tmp_path, f"{now - timedelta(days=3):%Y-%m-%d %H:%M} — old", "Read it.")
    _stop(tmp_path, "first")                               # the first look only remembers
    _write(tmp_path, f"{now - timedelta(hours=2):%Y-%m-%d %H:%M} — typed", "Read it.")
    assert "lesson L1" in _stop(tmp_path).get("reason", "")
    _write(tmp_path, f"{datetime.now():%Y-%m-%d %H:%M} — typed", "Read it.")
    _stop(tmp_path, again=True)
    assert _rec("L1").get("fixed_after") == 1, _rec("L1")


def test_the_doctor_prints_fixed_after_the_lesson(tmp_path):
    _write(tmp_path, H, "All tests pass.")
    _stop(tmp_path)
    _write(tmp_path, H, "All tests pass.", claims="- 5 passed -- `pytest fix_test.py -q`")
    _stop(tmp_path, again=True)
    data = Path(os.environ["BATON_LESSONS_STATE"]).parent
    env = dict(_env(tmp_path), CLAUDE_PLUGIN_DATA=str(data))
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "baton_doctor.py")],
                         capture_output=True, text=True, env=env)
    assert "L4" in out.stdout and "fixed after the lesson: 1 of 1" in out.stdout, out.stdout
    assert "a proxy, not proof" in out.stdout.lower()


def test_l4_a_claims_section_without_the_tests_claim_is_not_a_fix(tmp_path):
    _write(tmp_path, H, "All tests pass.")
    assert "lesson L4" in _stop(tmp_path).get("reason", "")
    _write(tmp_path, H, "All tests pass.", claims="- the fixture waits for the token (fix_test.py)")
    _stop(tmp_path, again=True)
    assert "fixed_after" not in _rec("L4"), _rec("L4")
