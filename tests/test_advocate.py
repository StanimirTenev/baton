"""Lesson L5, the devil's advocate, moment 1: text going out is attacked before it leaves.

17.11.2026, three errors, all in sentences and none in code (baton-uroci/PLAN-advokat.md):
E1 "I have not read it yet" in a reply that was posted -- the letter had been read at 11:15 and
written into our own register. E2 "That is on my fix list" in a draft -- out of scope by design,
written in our own docs. E3 "availability in the EU / Bulgaria" as a condition of a research brief
-- the human's word refutes it. For E1 and E2 the refutation was on the disk; nobody looked.

Detected by class of action, not by phrase (L3's rule): the turn's final message carries a block of
prose to paste, or the turn called a sending tool (mail send/draft, `gh` issue/PR comment, `git
push`, artifact publish). Stop hands the turn back once per draft. The answer is a `### Devil's
advocate` (`### Адвокат`) section in the entry; a `refuted:` (`оборено:`) line there is `caught`,
a section without one is `nothing` -- the cost, counted, not hidden.

The fixtures in fixtures/replay/ keep the shape of the real turns (a plain ``` fence of about a
thousand characters inside a reply in Bulgarian) and the one sentence; the rest is rewritten.
"""

import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import child_env

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_stop.py"
REPLAY = Path(__file__).resolve().parent / "fixtures" / "replay"
spec = importlib.util.spec_from_file_location("bs_advocate", HOOK)
bs = importlib.util.module_from_spec(spec)
sys.modules["bs_advocate"] = bs
spec.loader.exec_module(bs)


def _stamp(records: list, path: Path) -> Path:
    """Write `records` as a transcript, a second apart, ending now."""
    now = datetime.now(timezone.utc)
    with open(path, "w", encoding="utf-8") as fh:
        for i, r in enumerate(records):
            r = dict(r, timestamp=(now - timedelta(seconds=len(records) - i)).isoformat())
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def _fixture(name: str) -> list:
    return [json.loads(x) for x in (REPLAY / name).read_text("utf-8").splitlines() if x.strip()]


def _user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _said(text):
    return {"type": "assistant", "message": {"role": "assistant",
                                             "content": [{"type": "text", "text": text}]}}


def _call(i, name, args):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": f"toolu_{i}", "name": name, "input": args}]}}


def _result(i, text="ok"):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": f"toolu_{i}", "content": text}]}}


def _tasks(tmp_path) -> Path:
    """A task root with one recorded folder: nothing else for Stop to ask about."""
    folder = tmp_path / "tasks" / "a"
    folder.mkdir(parents=True)
    book = folder / "LOGBOOK.md"
    then = datetime.now() - timedelta(hours=2)
    book.write_text(f"---\ndone_when: shipped\n---\n\n## {then:%Y-%m-%d %H:%M} — first\n\nbody\n",
                    "utf-8")
    old = time.time() - 7200
    os.utime(book, (old, old))
    return tmp_path / "tasks"


def _env(tmp_path, tasks):
    return child_env(BATON_HOME=str(tasks), BATON_LOGBOOK="LOGBOOK.md",
                     HOME=str(tmp_path / "home"), BATON_STATE_DIR=str(tmp_path / "state"))


def _stop(tmp_path, tasks, transcript, sid="s1", again=False):
    payload = {"session_id": sid, "transcript_path": str(transcript), "stop_hook_active": again}
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                         capture_output=True, text=True, env=_env(tmp_path, tasks))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def _l5(env_state=None):
    try:
        return json.loads(Path(os.environ["BATON_LESSONS_STATE"]).read_text("utf-8")).get("L5", {})
    except FileNotFoundError:
        return {}


def _run_fixture(tmp_path, name, sid="s1"):
    tasks = _tasks(tmp_path)
    transcript = _stamp(_fixture(name), tmp_path / f"{sid}.jsonl")
    return tasks, transcript, _stop(tmp_path, tasks, transcript, sid)


# -- the replay: the three errors of 17.11 -----------------------------------------------------

def test_e1_the_posted_reply_is_handed_back(tmp_path):
    """🔴 E1: a reply to paste, ~1000 characters, in a plain fence -- posted with a false claim."""
    _tasks_, _t, out = _run_fixture(tmp_path, "E1.jsonl")
    assert out.get("decision") == "block"
    assert "lesson L5" in out["reason"] and "what would refute it" in out["reason"]
    assert _l5().get("fired") == 1


def test_e2_the_draft_is_handed_back(tmp_path):
    """🔴 E2: the draft that said "on my fix list" for what is out of scope by design."""
    _tasks_, _t, out = _run_fixture(tmp_path, "E2.jsonl")
    assert out.get("decision") == "block" and "lesson L5" in out["reason"]
    assert _l5().get("fired") == 1


@pytest.mark.xfail(strict=True, reason="moment 3 (a condition in a plan or brief) is not built: "
                   "the brief went to a file and an Agent prompt, neither of them a sending action")
def test_e3_the_condition_in_the_brief_is_handed_back(tmp_path):
    _tasks_, _t, out = _run_fixture(tmp_path, "E3.jsonl")
    assert out.get("decision") == "block" and "lesson L5" in out["reason"]


# -- once per draft ----------------------------------------------------------------------------

def test_the_same_draft_is_asked_once(tmp_path):
    tasks, transcript, out = _run_fixture(tmp_path, "E1.jsonl")
    assert "lesson L5" in out.get("reason", "")
    assert "lesson L5" not in _stop(tmp_path, tasks, transcript).get("reason", "")
    assert "lesson L5" not in _stop(tmp_path, tasks, transcript, sid="s2").get("reason", "")
    assert _l5().get("fired") == 1


def test_the_pass_after_a_hand_back_does_not_ask(tmp_path):
    tasks = _tasks(tmp_path)
    transcript = _stamp(_fixture("E2.jsonl"), tmp_path / "s1.jsonl")
    assert "lesson L5" not in _stop(tmp_path, tasks, transcript, again=True).get("reason", "")
    assert not _l5().get("fired")


def test_a_draft_from_an_earlier_turn_is_not_this_turns(tmp_path):
    records = _fixture("E1.jsonl") + [_user("добре, благодаря"), _said("Няма защо.")]
    tasks = _tasks(tmp_path)
    out = _stop(tmp_path, tasks, _stamp(records, tmp_path / "s1.jsonl"))
    assert "lesson L5" not in out.get("reason", "")


# -- the answer: caught, or nothing ------------------------------------------------------------

def _answer(tasks, transcript, section: str):
    """The entry the hand-back asked for, written by this session's own Write call."""
    book = tasks / "a" / "LOGBOOK.md"
    text = book.read_text("utf-8")
    head, _, rest = text.partition("\n## ")
    entry = (f"## {datetime.now():%Y-%m-%d %H:%M} — the reply\n\n{section}\n"
             "### What was asked\nA reply.\n\n### Done\nDrafted it in the chat.\n\n"
             "### Result\nA draft.\n\n### Still open\nPosting it.\n\n")
    book.write_text(head + "\n" + entry + "## " + rest, "utf-8")
    records = [json.loads(x) for x in transcript.read_text("utf-8").splitlines()]
    _stamp(records + [_call(9, "Write", {"file_path": str(book)}), _result(9), _said("Записано.")],
           transcript)


def test_a_refuted_line_counts_caught_once(tmp_path):
    tasks, transcript, out = _run_fixture(tmp_path, "E1.jsonl")
    assert "lesson L5" in out["reason"]
    _answer(tasks, transcript, "### Адвокат\n- оборено: „I have not read it yet“ -- прочетено в 11:15, "
                   "REGISTAR.md раздел 2\n- „the fingerprint excludes mandates“ -- проверено днес\n")
    _stop(tmp_path, tasks, transcript, again=True)
    _stop(tmp_path, tasks, transcript, sid="s1")
    rec = _l5()
    assert rec.get("caught") == 1 and not rec.get("nothing")


def test_a_section_with_nothing_refuted_counts_nothing(tmp_path):
    tasks, transcript, out = _run_fixture(tmp_path, "E2.jsonl")
    assert "lesson L5" in out["reason"]
    _answer(tasks, transcript, "### Devil's advocate\n- \"the scan finds both keys\" -- the scan output, today\n")
    _stop(tmp_path, tasks, transcript, again=True)
    _stop(tmp_path, tasks, transcript)
    rec = _l5()
    assert rec.get("nothing") == 1 and not rec.get("caught")


def test_refuted_nothing_or_a_move_to_checked_is_a_section_with_nothing_refuted(tmp_path):
    """Row 190, the same flaw as L3's: `оборено: нищо.` and `refuted: ... -- now L` refute
    nothing, so the section is `nothing`, not `caught`."""
    tasks, transcript, out = _run_fixture(tmp_path, "E1.jsonl")
    assert "lesson L5" in out["reason"]
    _answer(tasks, transcript, "### Адвокат\n- оборено: нищо. Бележка: проверено срещу снимката\n"
                   "- refuted: (A) \"the scan finds both keys\" -- now L.\n")
    _stop(tmp_path, tasks, transcript, again=True)
    _stop(tmp_path, tasks, transcript, sid="s1")
    rec = _l5()
    assert rec.get("nothing") == 1 and not rec.get("caught"), rec


def test_a_refuted_line_outside_the_section_is_not_l5():
    body = "### Claims to verify\n- refuted: the repo is public\n\n### Done\nx\n"
    assert bs.advocate_verdicts(body) == []


# -- the classes ---------------------------------------------------------------------------------

def _turn(tmp_path, *records):
    return str(_stamp([_user("направи го")] + list(records), tmp_path / "s1.jsonl"))


@pytest.mark.parametrize("name,args", [
    ("Bash", {"command": "cd ~/dev/x && git push origin main"}),
    ("Bash", {"command": "gh pr comment 12 --body-file reply.md"}),
    ("Bash", {"command": "gh issue comment 7 -b 'thanks, fixed in 3.2'"}),
    ("mcp__claude_ai_Gmail__create_draft", {"to": ["x@example.org"], "body": "Hello"}),
    ("mcp__claude_ai_Gmail__send_message", {"to": ["x@example.org"], "body": "Hello"}),
    ("mcp__claude_ai_Gmail__reply", {"message_id": "1", "body": "Hello"}),
    ("Artifact", {"file_path": "/tmp/page.html", "icon": "chart"}),
    ("Artifact", {"action": "publish", "file_path": "/tmp/page.html"}),
])
def test_a_sending_tool_is_text_going_out(tmp_path, name, args):
    t = _turn(tmp_path, _call(1, name, args), _result(1), _said("Готово."))
    assert len(bs.outgoing(t)) == 1


@pytest.mark.parametrize("name,args", [
    ("Bash", {"command": "cat > LOGBOOK.md <<'EOF'\nthen git push and gh pr comment\nEOF"}),
    ("Bash", {"command": "git status && git log -3"}),
    ("Artifact", {"action": "read", "url": "https://claude.ai/artifact/x"}),
    ("Artifact", {"action": "publish", "url": "u", "file_path": "a.png", "asset": True}),
    ("mcp__claude_ai_Gmail__search_threads", {"query": "from:x"}),
    ("mcp__claude_ai_Gmail__get_draft", {"draft_id": "1"}),
    ("Write", {"file_path": "/tmp/BRIEF.md", "content": "availability in the EU"}),
])
def test_other_tools_are_not(tmp_path, name, args):
    t = _turn(tmp_path, _call(1, name, args), _result(1), _said("Готово."))
    assert bs.outgoing(t) == []


def test_a_short_reply_is_not_a_draft(tmp_path):
    t = _turn(tmp_path, _said("Пуснах го. Линкът:\n\n```\nThanks, fixed in 3.2.\n```"))
    assert bs.outgoing(t) == []


def test_code_is_not_prose(tmp_path):
    code = "\n".join(f"def f{i}(x):\n    return x * {i}  # {i}" for i in range(60))
    listing = "\n".join(f"hooks/baton_stop_{i}.py  hooks/lang/bg_{i}.json" for i in range(40))
    t = _turn(tmp_path, _said(f"```python\n{code}\n```\n\n```\n{listing}\n```"))
    assert bs.outgoing(t) == []


def test_a_quoted_draft_is_prose(tmp_path):
    text = "\n".join("> " + line for line in _fixture("E2.jsonl")[-1]["message"]["content"][0]["text"]
                     .split("```")[1].strip().splitlines())
    t = _turn(tmp_path, _said("Черновата:\n\n" + text))
    assert len(bs.outgoing(t)) == 1


def test_a_command_to_paste_is_not_prose(tmp_path):
    cmd = ("cd ~/zadachi/x/plugin && gh repo create someone/plugin --public --source . --remote "
           "origin --push \\\n  --description \"The plugin. It reads the catalogue. It answers.\"")
    t = _turn(tmp_path, _said(f"```\n{cmd}\n{cmd}\n```"))
    assert bs.outgoing(t) == []


def test_a_short_reply_over_the_threshold_is_a_draft(tmp_path):
    reply = ("Thanks, Daniel. I saw it, and the credit reads well. Good that the integration and the "
             "sample report stay out of it until we agree terms. Tomorrow you will have the numbers and the draft of the joint page.")
    assert len(reply) >= bs.ADVOCATE_MIN
    t = _turn(tmp_path, _said(f"Отговорът:\n\n```\n{reply}\n```"))
    assert len(bs.outgoing(t)) == 1
