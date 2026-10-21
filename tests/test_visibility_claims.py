"""A claim about what is public or private is put in front of a reader before it is relied on.

2026-10-17 11:20, borsa-analiz: an entry said "`gh` says StanimirTenev/market-swarm is PUBLIC".
It was private, had always been, and no `gh` output in the session said otherwise; the human
caught it two hours later. The entry had every section and named its files -- the v3.16.0 shape
check passes it. Under the post about that check, a reader (20.10) proposed a short "claims to
verify" section at the top of an entry, so the human checks the claim instead of the prose.
Asking for it on every entry would be a form; measured on 20.10, entries mentioning versions or
URLs are half of all entries, a mention of visibility about one in eight. So only that.

Lesson L3: `fired` when Stop asks for the section; `caught` only when a claim listed in such a
section is later marked `refuted:` -- a proven error, not a re-read of a correct claim.
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
spec = importlib.util.spec_from_file_location("bs_visibility", HOOK)
bs = importlib.util.module_from_spec(spec)
sys.modules["bs_visibility"] = bs
spec.loader.exec_module(bs)

BODY = """
### What was asked
Find out why the forecast misses the sector news, and fix the prompt.

### Done
Changed prompt.md; the sector line now reaches the forecast. {mention}

### Result
The forecast reads the news and the sector.

### Still open
Nothing on the prompt.
"""
WRONG = "`gh` says StanimirTenev/market-swarm is **PUBLIC**, the memory says private fork."


def _entry(heading="2026-10-17 11:20 — market-swarm: the forecast", mention=WRONG, claims=None):
    head = f"## {heading}\n"
    if claims is not None:
        head += "\n### Claims to verify\n" + claims + "\n"
    return head + BODY.format(mention=mention)


def _folder(root: Path, text: str, name="swarm", age=30):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    when = time.time() - age
    work = folder / "prompt.md"
    work.write_text("work\n", encoding="utf-8")
    os.utime(work, (when, when))
    log = folder / "LOGBOOK.md"
    log.write_text("---\nstate: active\ndone_when: \"x\"\n---\n\n" + text, encoding="utf-8")
    os.utime(log, (when + 5, when + 5))
    return folder


def _since():
    return time.time() - 600


def _asks(root):
    return bs.visibility_entries(root, "LOGBOOK.md", _since())


# -- the trigger ----------------------------------------------------------------------------

def test_the_entry_that_said_public_is_asked_about(tmp_path):
    """🔴 The reproduction: a full entry with the wrong claim passed every check."""
    _folder(tmp_path, _entry())
    assert bs.hollow_entries(tmp_path, "LOGBOOK.md", _since()) == [], "shape is fine"
    out = _asks(tmp_path)
    assert len(out) == 1 and out[0][0] == "swarm"
    assert "PUBLIC" in out[0][2]


def test_bulgarian_forms_trigger():
    for text in ("хранилището е публично", "качено (частно)", "частни хранилища",
                 "artifact/abc (частна)", "Публичният отговор", "частен форк"):
        assert bs.visibility_words(text), text


def test_words_that_only_start_the_same_do_not():
    for text in ("в частност това", "участник в поканата", "publication date", "publish it",
                 "публикуван", "privacy policy", "частица"):
        assert not bs.visibility_words(text), text


def test_an_entry_without_a_mention_is_not_asked(tmp_path):
    _folder(tmp_path, _entry(mention="The version is 3.17.0, see https://example.org."))
    assert _asks(tmp_path) == []


def test_a_word_in_inline_code_is_not_a_claim():
    assert not bs.visibility_words("ran `gh repo view --json visibility` -> `PRIVATE`")
    assert not bs.visibility_words("signed with `--private-key`")


def test_a_cryptographic_key_is_not_visibility():
    for text in ("the private key stays on the box", "public-key signatures",
                 "публичен ключ 80 B", "частният ключ е в ~/.config", "PRIVATE KEY block"):
        assert not bs.visibility_words(text), text


def test_a_quoted_word_is_mentioned_not_used():
    assert not bs.visibility_words("the example with „публично“ stays")
    assert not bs.visibility_words('the word "private" in the README')
    assert bs.visibility_words("стенли: „трябва да е частно“"), "a quoted sentence is still a claim"


def test_the_pair_named_together_is_a_topic_not_a_claim():
    assert not bs.visibility_words("public/private 22 of 186")
    assert not bs.visibility_words("примерът публично/частно (README:384)")
    assert bs.visibility_words("public, then private"), "two claims are not a pair"


# -- the section ----------------------------------------------------------------------------

def test_a_claims_section_first_is_enough(tmp_path):
    _folder(tmp_path, _entry(claims="- market-swarm is public (gh repo view)"))
    assert _asks(tmp_path) == []


def test_the_bulgarian_heading_counts(tmp_path):
    text = _entry(claims="- market-swarm е публично").replace("### Claims to verify",
                                                              "### За проверка")
    _folder(tmp_path, text)
    assert _asks(tmp_path) == []


def test_an_empty_claims_section_is_missing(tmp_path):
    _folder(tmp_path, _entry(claims=""))
    assert len(_asks(tmp_path)) == 1


def test_a_claims_section_below_the_others_is_not_at_the_top(tmp_path):
    text = _entry() + "\n### Claims to verify\n- market-swarm is public\n"
    _folder(tmp_path, text)
    assert len(_asks(tmp_path)) == 1


def test_an_older_entry_is_not_judged(tmp_path):
    """Only the newest entry, and only one this session changed."""
    newest = _entry(heading="2026-10-17 13:32 — the sector line", mention="Nothing else.")
    _folder(tmp_path, newest + "\n" + _entry())
    assert _asks(tmp_path) == []


def test_a_logbook_from_before_the_session_is_left_alone(tmp_path):
    _folder(tmp_path, _entry(), age=7200)
    assert _asks(tmp_path) == []


def test_an_unknown_session_start_checks_nothing(tmp_path):
    _folder(tmp_path, _entry())
    assert bs.visibility_entries(tmp_path, "LOGBOOK.md", None) == []


# -- caught: only a claim that was listed and later marked refuted ---------------------------

LISTED = _entry(claims="- market-swarm is public (gh, 11:20)")
REFUTED = _entry(heading="2026-10-17 13:32 — market-swarm is private",
                 mention="Checked with gh repo view.",
                 claims="- refuted: market-swarm is public -- gh repo view says PRIVATE")


def test_a_refuted_claim_is_caught_once(tmp_path):
    _folder(tmp_path, REFUTED + "\n" + LISTED)
    assert bs.refuted_claims(tmp_path, "LOGBOOK.md", _since()) == 1
    assert bs.refuted_claims(tmp_path, "LOGBOOK.md", _since()) == 0, "counted twice"


def test_the_bulgarian_marker_counts(tmp_path):
    _folder(tmp_path, REFUTED.replace("- refuted:", "- оборено:") + "\n" + LISTED)
    assert bs.refuted_claims(tmp_path, "LOGBOOK.md", _since()) == 1


def test_a_reread_correct_claim_is_not_a_catch(tmp_path):
    checked = REFUTED.replace("- refuted: market-swarm is public -- gh repo view says PRIVATE",
                              "- market-swarm is private -- checked, gh repo view (В)")
    _folder(tmp_path, checked + "\n" + LISTED)
    assert bs.refuted_claims(tmp_path, "LOGBOOK.md", _since()) == 0


def test_refuted_without_a_listed_claim_below_is_not_counted(tmp_path):
    """The heading of 17.10 13:32 said "refuted" -- but nothing had been listed to refute."""
    _folder(tmp_path, REFUTED + "\n" + _entry())
    assert bs.refuted_claims(tmp_path, "LOGBOOK.md", _since()) == 0


def test_refuted_outside_a_claims_section_is_not_counted(tmp_path):
    loose = REFUTED.replace("### Claims to verify", "### Notes")
    _folder(tmp_path, loose + "\n" + LISTED)
    assert bs.refuted_claims(tmp_path, "LOGBOOK.md", _since()) == 0


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
    assert reason.startswith("Baton, lesson L3"), "nothing else hands this turn back"
    assert "swarm" in reason and "### Claims to verify" in reason and "PUBLIC" in reason
    assert "refuted:" in reason, "the agent is told the one marker that counts as caught"
    assert "own visibility setting" in reason
    for command in ("gh ", "--json", "curl", "api."):
        assert command not in reason, f"the hand-back names no credentialed command ({command!r})"
    assert _lessons()["L3"]["fired"] == 1
    again = _run(tmp_path, "s1")
    assert "Claims to verify" not in again.get("reason", ""), "asked twice about the same entry"
    other = _run(tmp_path, "s2")
    assert "Claims to verify" not in other.get("reason", ""), "asked again in another session"
    assert _lessons()["L3"]["fired"] == 1, "one entry is one fire"


def test_the_hook_counts_a_refuted_claim(tmp_path):
    _folder(tmp_path / "tasks", REFUTED + "\n" + LISTED)
    _run(tmp_path, "s1")
    assert _lessons()["L3"]["caught"] == 1
    _run(tmp_path, "s2")
    assert _lessons()["L3"]["caught"] == 1, "the same line is one catch"
