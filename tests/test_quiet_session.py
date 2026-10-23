"""ZA-OPRAVYANE row 26: a session that touched no task folder is never asked about.

Stop judges by file times, so a decision made only in chat passes clean (the probe of 21.10:
a turn with no file touched -> exit 0, nothing). Jake Manis's idea (20.10): at session start,
put the messages of the last session next to the logbook entries written in that time -- two
numbers, no judgement -- and say so when there were messages and no entry.

A "message" is one the human typed: not a tool result, not a command's output, not the
agent's turns (those multiply in loops and subagents). Through the hook's entry point.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_session_start.py"


def _ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _setup(tmp_path, entry_at: datetime, messages=5, first=None):
    home = tmp_path / "home"
    project = home / ".claude" / "projects" / "-p"
    project.mkdir(parents=True)
    start = datetime.now() - timedelta(hours=2)
    lines = []
    for i in range(messages):
        at = start + timedelta(minutes=10 * i)
        lines.append({"type": "user", "timestamp": _ts(at),
                      "message": {"role": "user", "content": first if first and not i
                                  else f"decide the price, option {i}"}})
        lines.append({"type": "user", "timestamp": _ts(at), "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "x", "content": "ok"}]}})
        lines.append({"type": "assistant", "timestamp": _ts(at), "message": {"content": "sure"}})
    lines.append({"type": "user", "isMeta": True, "timestamp": _ts(start),
                  "message": {"content": "<local-command-caveat>x</local-command-caveat>"}})
    lines.append({"type": "user", "timestamp": _ts(start),
                  "message": {"content": "<command-name>/model</command-name>"}})
    prev = project / "prev.jsonl"
    prev.write_text("\n".join(json.dumps(x) for x in lines) + "\n", "utf-8")
    old = (datetime.now() - timedelta(minutes=30)).timestamp()
    os.utime(prev, (old, old))
    own = project / "own.jsonl"
    own.write_text(json.dumps({"type": "user", "timestamp": _ts(datetime.now())}) + "\n", "utf-8")
    tasks = tmp_path / "tasks"
    (tasks / "pricing").mkdir(parents=True)
    (tasks / "pricing" / "LOGBOOK.md").write_text(
        f"---\nstate: active\nturn: us\n---\n\n## {entry_at:%Y-%m-%d %H:%M} — e\n\nx\n", "utf-8")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR", "BATON_HOME"))}
    env.update(HOME=str(home), BATON_HOME=str(tasks), BATON_LOGBOOK="LOGBOOK.md")
    return env, str(own)


def _ctx(env, own, source="startup"):
    payload = json.dumps({"source": source, "session_id": "own", "transcript_path": own})
    out = subprocess.run([sys.executable, str(HOOK)], input=payload.encode(), capture_output=True,
                         env=env)
    assert out.returncode == 0, out.stderr
    if not out.stdout.strip():
        return ""
    return json.loads(out.stdout).get("hookSpecificOutput", {}).get("additionalContext", "")


def test_messages_and_no_entry_in_that_time_are_said(tmp_path):
    env, own = _setup(tmp_path, datetime.now() - timedelta(days=3))
    ctx = _ctx(env, own)
    assert "5 messages from the human" in ctx and "0 logbook entries" in ctx, ctx
    assert "decide the price, option 0" in ctx, "the messages are named, not only counted"
    assert "tool result" not in ctx.split("5 messages")[0][-200:]


def test_an_entry_written_in_that_time_is_enough(tmp_path):
    env, own = _setup(tmp_path, datetime.now() - timedelta(minutes=90))   # inside the session
    assert "messages from the human" not in _ctx(env, own)


def test_said_once_per_session_and_also_after_clear(tmp_path):
    env, own = _setup(tmp_path, datetime.now() - timedelta(days=3))
    assert "5 messages from the human" in _ctx(env, own, "clear")
    assert "messages from the human" not in _ctx(env, own), "the same session is said once"


def test_not_after_compaction_or_on_resume(tmp_path):
    env, own = _setup(tmp_path, datetime.now() - timedelta(days=3))
    assert "messages from the human" not in _ctx(env, own, "compact")
    assert "messages from the human" not in _ctx(env, own, "resume")


def test_a_short_exchange_is_not_a_finding(tmp_path):
    env, own = _setup(tmp_path, datetime.now() - timedelta(days=3), messages=2)
    assert "messages from the human" not in _ctx(env, own)


# -- ZA-OPRAVYANE row 48 (Haddad, Sidhu, 22.10, said publicly): a pasted key was quoted verbatim ----

SECRETS = [  # each one cut in pieces, so no shipped file holds a whole key-shaped string (the
             # directory blocked v3.22.0-v3.24.0 for "Secret in a shipped file" on this list)
    "FAKE_sk-probe-0000-not-a-real-secret",                       # the probe of 22.10
    "sk-ant-a" "pi03-AbC" "dEfGh123" "4567890",
    "sk-or-v1" "-0123456" "789abcde" "f0123",
    "ghp_ABCD" "EFGHIJKL" "MNOPQRST" "UVWXYZ01" "23456789",
    "github_p" "at_11ABC" "DEFG0123" "456789_a" "bcdefghi" "jk",
    "AKIAIOSF" "ODNN7EXA" "MPLE",
    "xoxb-123" "4567890-" "abcdefgh" "ij",
    "AIzaSyA1" "23456789" "0abcdefg" "hijklmno" "pqrstu",
    "eyJhbGci" "OiJIUzI1" "NiJ9.eyJ" "zdWIiOiI" "xMjM0NTY" "3ODkwIn0" ".dozjgNr" "yP4J3jVm" "NHl0w5N",
    "token=hu" "nter2hun" "ter2",
    "PASSWORD" ": correc" "t-horse-" "battery",
    "Bearer a" "bcdef012" "3456789",
    "9f86d081" "884c7d65" "9a2feaa0" "c55ad015" "a3bf4f1b" "2b0b822c" "d15d6c15" "b0f00a08",
    "dGhpcyBp" "cyBhIGxv" "bmcgYmFz" "ZTY0IHNl" "Y3JldCB2" "YWx1ZQ2",
]


@pytest.mark.parametrize("secret", SECRETS)
def test_a_secret_shaped_string_is_masked_before_it_is_quoted(tmp_path, secret):
    env, own = _setup(tmp_path, datetime.now() - timedelta(days=3),
                      first=f"use {secret} for it")
    ctx = _ctx(env, own)
    assert "5 messages from the human" in ctx, ctx
    assert "[masked] for it" in ctx, ctx
    for part in secret.replace(":", " ").replace("=", " ").split():
        if len(part) >= 8:
            assert part not in ctx, f"{part} quoted verbatim"


@pytest.mark.parametrize("text", ["merge the task-folder-renaming branch today",
                                  "ask-for-review on ~/zadachi/baton-plugin/izdavane-3.22.0 please",
                                  "the token is in the vault, ask the human",
                                  "skip the 2026-10-22 entry"])
def test_ordinary_words_are_not_masked(tmp_path, text):
    env, own = _setup(tmp_path, datetime.now() - timedelta(days=3), first=text)
    assert text[:70] in _ctx(env, own)
