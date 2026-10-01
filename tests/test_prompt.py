"""The UserPromptSubmit hook: a message that touches a known task brings that task's logbook
to the agent's attention before it acts.

The day that made it (2026-09-28): asked about the scanner, the agent proposed reviewing 42
candidates that had been reviewed two days earlier -- it had read one entry of the logbook.
The folder is `qrp-kachestvo`; the message said "скенера". Nothing matches that without an
alias, and nothing matches "скенера" against "скенер" without meeting the ending halfway.

It is a reminder, not a verdict: it names the task, the date of its last entry and its next
step, once per session, and says nothing at all when no task is named.
"""
from __future__ import annotations
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_prompt.py"
spec = importlib.util.spec_from_file_location("bp_hook", HOOK)
bp = importlib.util.module_from_spec(spec)
sys.modules["bp_hook"] = bp
spec.loader.exec_module(bp)


def _task(root: Path, name: str, aliases: str = "", nxt: str = "the next move"):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    head = f"---\nsastoyanie: aktivna\nsledvashto: \"{nxt}\"\n"
    if aliases:
        head += f"aliases: [{aliases}]\n"
    head += "---\n\n## 2026-09-26 18:32 — the entry that mattered\n\nx\n"
    (folder / "LOGBOOK.md").write_text(head, encoding="utf-8")
    return folder


def _run(root: Path, prompt: str, session: str = "s1", raw: str | None = None):
    env = {"BATON_HOME": str(root), "BATON_LOGBOOK": "LOGBOOK.md",
           "BATON_STATE_DIR": str(root / ".state"), "PATH": "/usr/bin:/bin"}
    data = raw if raw is not None else json.dumps({"prompt": prompt, "session_id": session})
    out = subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True,
                         text=True, env=env)
    assert out.returncode == 0, f"exit {out.returncode} would block or break the prompt: {out.stderr}"
    return out.stdout


def test_the_folder_name_is_enough(tmp_path):
    _task(tmp_path, "qrp-kachestvo")
    out = _run(tmp_path, "what is left in qrp-kachestvo?")
    assert "qrp-kachestvo" in out and "2026-09-26" in out and "the next move" in out


def test_a_cyrillic_alias_with_another_ending_matches(tmp_path):
    """P1: the folder is Latin, the message is Cyrillic and inflected."""
    _task(tmp_path, "qrp-kachestvo", aliases="скенер, етикетировач, scanner")
    out = _run(tmp_path, "за скенера ми обясни по подробно")
    assert "qrp-kachestvo" in out


def test_a_multiword_alias_needs_all_its_words(tmp_path):
    _task(tmp_path, "elkan-strategy", aliases="евро програми")
    assert "elkan-strategy" not in _run(tmp_path, "говорихме за програми", session="a")
    assert "elkan-strategy" in _run(tmp_path, "консултант по евро програмите", session="b")


def test_once_per_session(tmp_path):
    _task(tmp_path, "qrp-kachestvo")
    assert "qrp-kachestvo" in _run(tmp_path, "qrp-kachestvo again", session="s1")
    assert _run(tmp_path, "qrp-kachestvo again", session="s1").strip() == ""
    assert "qrp-kachestvo" in _run(tmp_path, "qrp-kachestvo again", session="s2")


def test_silent_when_no_task_is_named(tmp_path):
    _task(tmp_path, "qrp-kachestvo", aliases="скенер")
    for prompt in ("здравей", "докъде си", "давай", "ok"):
        assert _run(tmp_path, prompt, session=prompt).strip() == "", prompt


def test_a_short_alias_does_not_match_inside_a_longer_word(tmp_path):
    """`jev` must not fire on `jevelry`; a stem is a prefix of a WORD, not of any text."""
    _task(tmp_path, "baton", aliases="jev")
    assert _run(tmp_path, "the jewelry shop").strip() == ""


def test_garbage_on_stdin_never_breaks_the_prompt(tmp_path):
    _task(tmp_path, "qrp-kachestvo")
    assert _run(tmp_path, "", raw="not json").strip() == ""


def test_matching_is_a_pure_function(tmp_path):
    _task(tmp_path, "fleetpost", aliases="шина")
    names = [t for t, _, _ in bp.touched(tmp_path, "LOGBOOK.md", "пусни пак шината")]
    assert names == ["fleetpost"]


def test_a_windows_code_page_does_not_silence_it(tmp_path):
    """2026-09-28, on the Windows machine: 0 bytes out. Python there reads a redirected
    stdin and writes stdout in the locale code page (cp1251), so a UTF-8 "за скенера"
    arrived as mojibake, matched nothing, and the hook said nothing -- the quiet failure.
    Reproduced here by forcing the code page. The hook reads and writes UTF-8 bytes."""
    _task(tmp_path, "qrp-kachestvo", aliases="скенер", nxt="следващ ход")
    env = {"BATON_HOME": str(tmp_path), "BATON_LOGBOOK": "LOGBOOK.md",
           "BATON_STATE_DIR": str(tmp_path / ".state"), "PATH": "/usr/bin:/bin",
           "PYTHONIOENCODING": "cp1251"}
    data = json.dumps({"prompt": "за скенера ми обясни", "session_id": "w"}, ensure_ascii=False)
    out = subprocess.run([sys.executable, str(HOOK)], input=data.encode("utf-8"),
                         capture_output=True, env=env)
    assert out.returncode == 0, out.stderr
    text = out.stdout.decode("utf-8")          # must be UTF-8, whatever the code page
    assert "qrp-kachestvo" in text and "следващ ход" in text, text


# --- a long session: the restart reminder (2026-10-01) -------------------------------------
# "If the session gets very long the limit goes very fast" -- every message re-sends the whole
# context; two sessions on this machine had reached ~600k tokens.

def _transcript(path: Path, *turns):
    """turns: (tokens, sidechain) for each assistant answer, oldest first."""
    rows = [json.dumps({"type": "user", "message": {"content": "hi"}})]
    for tokens, side in turns:
        rows.append(json.dumps({"type": "assistant", "isSidechain": side, "message": {"usage": {
            "input_tokens": 2, "cache_read_input_tokens": tokens - 1002,
            "cache_creation_input_tokens": 1000, "output_tokens": 50}}}))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _say(root: Path, transcript: Path, session: str = "s1", prompt: str = "hello"):
    return _run(root, "", raw=json.dumps({"prompt": prompt, "session_id": session,
                                          "transcript_path": str(transcript)}))


def test_a_long_session_shows_the_human_a_restart_line(tmp_path):
    t = _transcript(tmp_path / "t.jsonl", (250_000, False))
    out = json.loads(_say(tmp_path, t))
    assert "250k" in out["systemMessage"] and "restart" in out["systemMessage"]
    assert "logbook" in out["hookSpecificOutput"]["additionalContext"]


def test_a_short_session_is_silent(tmp_path):
    t = _transcript(tmp_path / "t.jsonl", (120_000, False))
    assert _say(tmp_path, t) == ""


def test_a_subagent_answer_is_not_the_session(tmp_path):
    t = _transcript(tmp_path / "t.jsonl", (50_000, False), (400_000, True))
    assert _say(tmp_path, t) == ""


def test_no_transcript_is_silence_not_failure(tmp_path):
    assert _say(tmp_path, tmp_path / "missing.jsonl") == ""


def test_once_per_step_then_again_after_the_next_step(tmp_path):
    t = _transcript(tmp_path / "t.jsonl", (210_000, False))
    assert _say(tmp_path, t)
    _transcript(t, (260_000, False))
    assert _say(tmp_path, t) == ""                      # same step: said already
    _transcript(t, (310_000, False))
    assert "310k" in json.loads(_say(tmp_path, t))["systemMessage"]


def test_after_compact_the_next_climb_speaks_again(tmp_path):
    t = _transcript(tmp_path / "t.jsonl", (220_000, False))
    assert _say(tmp_path, t)
    _transcript(t, (40_000, False))
    assert _say(tmp_path, t) == ""
    _transcript(t, (205_000, False))
    assert _say(tmp_path, t)


def test_a_task_line_rides_along_with_the_restart(tmp_path):
    _task(tmp_path, "qrp-kachestvo")
    t = _transcript(tmp_path / "t.jsonl", (230_000, False))
    out = json.loads(_say(tmp_path, t, prompt="what about qrp-kachestvo?"))
    assert "qrp-kachestvo" in out["hookSpecificOutput"]["additionalContext"]
