"""A claim that tests pass is put in front of a reader, with the command that showed it.

ZA-OPRAVYANE row 38 (Apurv Khare, LinkedIn, 22.10): the shape check passed an entry that said
"did not run pytest ... All tests pass." -- it measures sections and length, not truth. Decided by
the human the same day: as L3 does for public/private, an entry that says tests pass is asked once
to list the claim under `### Claims to verify` (`### За проверка`) with the command and its result
line. Measured on 1,347 real entries (22.10): 25 match, all 25 a claim that tests passed; the
first patterns matched 35, and the 10 dropped were the phrase quoted or "минават през".

Lesson L4: `fired` when Stop asks; `caught` only when a later entry's claims section says
`refuted:` about a tests claim.
"""

import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_stop.py"
spec = importlib.util.spec_from_file_location("bs_tests_claims", HOOK)
bs = importlib.util.module_from_spec(spec)
sys.modules["bs_tests_claims"] = bs
spec.loader.exec_module(bs)

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
LIE = "Did not run pytest. All tests pass."


def _entry(heading="2026-10-22 10:00 — fix the login test", mention=LIE, claims=None):
    head = f"## {heading}\n"
    if claims is not None:
        head += "\n### Claims to verify\n" + claims + "\n"
    return head + BODY.format(mention=mention)


def _folder(root: Path, text: str, name="login", age=30):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    when = time.time() - age
    work = folder / "fix_test.py"
    work.write_text("work\n", encoding="utf-8")
    os.utime(work, (when, when))
    log = folder / "LOGBOOK.md"
    log.write_text("---\nstate: active\ndone_when: \"x\"\n---\n\n" + text, encoding="utf-8")
    os.utime(log, (when + 5, when + 5))
    return folder


def _since():
    return time.time() - 600


def _asks(root):
    return bs.tests_entries(root, "LOGBOOK.md", _since())


# -- the trigger ----------------------------------------------------------------------------

def test_the_entry_that_says_all_tests_pass_is_asked_about(tmp_path):
    _folder(tmp_path, _entry())
    asks = _asks(tmp_path)
    assert len(asks) == 1 and asks[0][0] == "login"
    assert "All tests pass" in asks[0][2]


def test_the_forms_that_trigger():
    for text in ("All tests pass.", "the tests passed", "544 passed in 31.70s", "all green",
                 "**1,004 passed**, 3 skipped", "тестовете минават", "Тестовете минаха ×3",
                 "минаха всички тестовете"):
        assert bs.tests_words(text), text


def test_n_of_n_passes_is_a_claim():
    """Row 42 (the probe for the v2 reply to Apurv, 22.10): the honest entry said "5/5 passes"
    and was not asked -- the pattern knew "N passed", not "N/N passes". Only N/N: "3/5 passed"
    is a run that failed, as "1 failed, 9 passed" is."""
    for text in ("5/5 passes, output in run.log.", "12/12 passed", "5 / 5 tests pass",
                 "ran it 3 times: 3/3 passed"):
        assert bs.tests_words(text), text
    for text in ("3/5 passed", "3/5 passes", "15/5 passes", "1.5/5 passes"):
        assert not bs.tests_words(text), text


def test_mentions_that_are_not_a_claim():
    for text in ("`pytest -q` printed `544 passed`",               # code: the evidence itself
                 "hollow passes „did not run pytest … All tests pass.“",   # the phrase quoted
                 'the CTO said "Done, tests pass" is no proof',
                 "тестовете минават през хука, не през помощника",  # "go through", not "pass"
                 "1 failed, 9 passed",                              # a run that failed
                 "a test passenger", "contests passed by"):
        assert not bs.tests_words(text), text


def test_an_entry_without_a_claim_is_not_asked(tmp_path):
    _folder(tmp_path, _entry(mention="Nothing was run yet."))
    assert _asks(tmp_path) == []


def test_a_claims_section_that_lists_it_is_enough(tmp_path):
    _folder(tmp_path, _entry(claims="- 5 passed -- `pytest fix_test.py -q`, 5 runs"))
    assert _asks(tmp_path) == []


def test_a_claims_section_without_the_tests_claim_is_not_enough(tmp_path):
    _folder(tmp_path, _entry(claims="- the repository is private (its settings page)"))
    assert len(_asks(tmp_path)) == 1


def test_an_older_entry_is_not_judged(tmp_path):
    _folder(tmp_path, _entry(heading="2026-10-22 11:00 — later", mention="Wrote the notes.")
            + "\n" + _entry())
    assert _asks(tmp_path) == []


def test_an_unknown_session_start_checks_nothing(tmp_path):
    _folder(tmp_path, _entry())
    assert bs.tests_entries(tmp_path, "LOGBOOK.md", None) == []


# -- caught: a listed tests claim later marked refuted ---------------------------------------

LISTED = _entry(claims="- 5 passed -- `pytest fix_test.py -q`")
REFUTED = _entry(heading="2026-10-22 12:00 — the login test still fails",
                 mention="Ran it in CI.",
                 claims="- refuted: 5 passed -- CI says 1 failed, 4 passed")


def test_a_refuted_tests_claim_is_caught_as_l4(tmp_path):
    _folder(tmp_path, REFUTED + "\n" + LISTED)
    assert bs.refuted_claims(tmp_path, "LOGBOOK.md", _since()) == 1
    state = bs._ss().lessons_load()
    assert state["L4"]["caught"] == 1 and "L3" not in state


# -- through the hook, as the harness runs it ------------------------------------------------

def _run(tmp_path, session):
    transcript = tmp_path / "t.jsonl"
    start = datetime.fromtimestamp(time.time() - 600, tz=timezone.utc).isoformat()
    transcript.write_text(json.dumps({"timestamp": start}) + "\n", "utf-8")
    env = dict(os.environ, BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               BATON_STATE_DIR=str(tmp_path / ".state"))
    out = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, env=env,
                         input=json.dumps({"session_id": session,
                                           "transcript_path": str(transcript)}))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def _lessons():
    try:
        return json.loads(Path(os.environ["BATON_LESSONS_STATE"]).read_text("utf-8"))
    except FileNotFoundError:
        return {}


def test_the_hook_asks_once_per_entry_and_counts_it(tmp_path):
    _folder(tmp_path / "tasks", _entry())
    first = _run(tmp_path, "s1")
    assert first.get("decision") == "block"
    reason = first["reason"]
    assert reason.startswith("Baton, lesson L4"), "nothing else hands this turn back"
    assert "login" in reason and "### Claims to verify" in reason and "All tests pass" in reason
    assert "the command that showed it" in reason and "refuted:" in reason
    assert _lessons()["L4"]["fired"] == 1
    assert "Claims to verify" not in _run(tmp_path, "s1").get("reason", ""), "asked twice"
    assert "Claims to verify" not in _run(tmp_path, "s2").get("reason", ""), "asked again"
    assert _lessons()["L4"]["fired"] == 1, "one entry is one fire"
