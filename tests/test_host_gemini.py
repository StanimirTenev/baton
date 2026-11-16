"""host(): Gemini CLI is known from what it sends, and Claude Code and Codex are known as before.

The payloads in tests/fixtures/gemini/ are built, not captured: Gemini CLI 0.68.0's
HookEventHandler builds every payload from session_id, transcript_path, cwd, hook_event_name and
timestamp, plus the event's own fields (bundle chunk-RCB6BI5H.js:367374-367383, :367191-367266).
They were run through Gemini's own HookRunner on 16.11.2026 (faza2/GEMINI-FIXTURE.md); no live
Gemini session produced them. The transcript name is chatRecordingService's for a main session:
`session-<YYYY-MM-DDTHH-MM>-<first 8 of session_id>.jsonl`, with `-<n>` before the short id on a
collision (chunk :287303-287317).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "gemini"


def _core():
    spec = importlib.util.spec_from_file_location("_baton_host_gemini", ROOT / "hooks" / "_baton.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GEMINI = sorted(p.name for p in FIXTURES.glob("*.json"))
SID = "3f6c2a9e-8d41-4b7a-9c55-1e2f3a4b5c6d"
CLAUDE_ENV = {"CLAUDECODE": "1", "CLAUDE_PROJECT_DIR": "/w", "CLAUDE_PLUGIN_ROOT": "/p"}


def _load(name):
    return json.loads((FIXTURES / name).read_text("utf-8"))


@pytest.mark.parametrize("name", GEMINI)
def test_a_gemini_payload_is_gemini(name):
    assert _core().host(_load(name), {}) == "gemini"


@pytest.mark.parametrize("name", GEMINI)
def test_claude_names_in_the_environment_do_not_hide_gemini(name):
    """Gemini itself sets CLAUDE_PROJECT_DIR for every hook (hookRunner, chunk :366805-366811)."""
    assert _core().host(_load(name), CLAUDE_ENV) == "gemini"


def test_session_start_is_known_by_its_transcript_alone():
    """SessionStart is Claude Code's name too; the session-<time>-<sid[:8]>.jsonl file tells."""
    assert _core().host(_load("session_start.json"), {}) == "gemini"


def test_a_collision_numbered_transcript_is_still_gemini():
    p = _load("session_start.json")
    p["transcript_path"] = p["transcript_path"].replace("T16-20-", "T16-20-2-")
    assert _core().host(p, {}) == "gemini"


def test_a_gemini_only_event_is_enough_without_a_transcript():
    p = {"session_id": SID, "transcript_path": "", "cwd": "/w", "hook_event_name": "BeforeAgent",
         "timestamp": "2026-11-16T16:30:12.345Z", "prompt": "hi"}
    assert _core().host(p, {}) == "gemini"


def test_session_start_without_a_transcript_stays_unknown():
    """Gemini sends "" when nothing is recorded yet; SessionStart alone is no evidence."""
    p = dict(_load("session_start.json"), transcript_path="")
    assert _core().host(p, {}) == "unknown"


def test_a_transcript_of_another_session_is_not_evidence():
    p = dict(_load("session_start.json"), session_id="00000000-0000-0000-0000-000000000000")
    assert _core().host(p, {}) == "unknown"


def test_a_gemini_event_with_a_codex_turn_id_is_unknown():
    p = dict(_load("before_agent.json"), turn_id="t-1")
    assert _core().host(p, {}) == "unknown"


def test_a_gemini_event_with_claude_s_transcript_is_unknown():
    p = dict(_load("after_agent.json"),
             transcript_path=f"/home/u/.claude/projects/-home-u/{SID}.jsonl")
    assert _core().host(p, {}) == "unknown"


@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit", "PreToolUse", "Stop",
                                   "Notification", "SessionEnd", "PreCompact", "PostToolBatch"])
def test_claude_s_event_names_are_not_gemini_evidence(event):
    """Notification and SessionEnd exist in both hosts; only Gemini-only names count."""
    p = {"session_id": "s1", "transcript_path": "/tmp/proj/b.jsonl", "hook_event_name": event}
    assert _core().host(p, {}) == "unknown"


def test_the_gemini_fixtures_carry_no_account_data_or_local_paths():
    import re
    bad = re.compile(r"eyJ|sk-|AIza|access_token|refresh_token|id_token|Bearer|/tmp/claude|stenly")
    for f in FIXTURES.rglob("*"):
        if f.is_file():
            assert not bad.search(f.read_text("utf-8")), f.name
