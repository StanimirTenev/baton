"""host(): which agent host calls a hook, from what it sends.

The Codex payloads in tests/fixtures/codex/ are real: stdin of Baton's hooks under Codex CLI
0.169.0 (live probe, 14.11.2026), with only the scratch directory renamed to /work/codex-probe.
The Claude payloads are the shapes the other tests here send, plus one with the fields Claude
Code also sends (`permission_mode`, `model`), which must not read as Codex.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "codex"


def _core():
    spec = importlib.util.spec_from_file_location("_baton_host", HOOKS / "_baton.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CODEX = sorted(p.name for p in FIXTURES.glob("*.json"))

# What Claude Code sets and what Codex inherits when started from a Claude Code shell (the
# probe's env dumps), plus the two names Codex itself sets for plugin hooks (its docs).
CLAUDE_ENV = {"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli", "CLAUDE_PID": "1",
              "CLAUDE_PLUGIN_ROOT": "/p", "CLAUDE_PLUGIN_DATA": "/d"}

CLAUDE = [
    # Claude Code's own transcript form: ~/.claude/projects/<slug>/<session_id>.jsonl.
    {"session_id": "6f1c2a9e-0b7d-4c55-9a1e-3d2f8b7c6a10", "hook_event_name": "Stop",
     "transcript_path": "/home/u/.claude/projects/-home-u/6f1c2a9e-0b7d-4c55-9a1e-3d2f8b7c6a10.jsonl",
     "cwd": "/home/u", "permission_mode": "default", "stop_hook_active": False},
    {"session_id": "6f1c2a9e-0b7d-4c55-9a1e-3d2f8b7c6a10", "hook_event_name": "SessionStart",
     "transcript_path": "/home/u/.claude/projects/-home-u/6f1c2a9e-0b7d-4c55-9a1e-3d2f8b7c6a10.jsonl",
     "cwd": "/home/u", "source": "startup", "model": "claude-opus-5-5",
     "permission_mode": "default"},
]

# What the other tests send: no transcript of a known form, no turn_id. Unknown, as before.
BARE = [
    {"hook_event_name": "PreToolUse", "tool_name": "Write",
     "tool_input": {"file_path": "/t/demo/DNEVNIK.md", "content": "x"}},
    {"session_id": "s1", "transcript_path": "/tmp/proj/b.jsonl", "hook_event_name": "Stop"},
    {},
    None,
    "not a dict",
]


@pytest.mark.parametrize("name", CODEX)
def test_a_real_codex_payload_is_codex(name):
    payload = json.loads((FIXTURES / name).read_text("utf-8"))
    assert _core().host(payload, {}) == "codex"


@pytest.mark.parametrize("name", CODEX)
def test_claude_names_in_the_environment_do_not_hide_codex(name):
    """Inherited, as in the probe: the environment proves nothing about who calls."""
    payload = json.loads((FIXTURES / name).read_text("utf-8"))
    assert _core().host(payload, CLAUDE_ENV) == "codex"


def test_session_start_is_known_by_its_transcript_alone():
    """SessionStart carries no turn_id; the rollout file name is the evidence."""
    payload = json.loads((FIXTURES / "session_start.json").read_text("utf-8"))
    assert "turn_id" not in payload
    assert _core().host(payload, {}) == "codex"


@pytest.mark.parametrize("payload", CLAUDE)
def test_a_claude_payload_is_claude_even_with_codex_in_the_environment(payload):
    assert _core().host(payload, {"CODEX_HOME": "/c", "CODEX_MANAGED_BY_NPM": "1"}) == "claude"


@pytest.mark.parametrize("payload", BARE)
def test_no_evidence_is_unknown(payload):
    assert _core().host(payload, CLAUDE_ENV) == "unknown"


def test_conflicting_evidence_is_unknown():
    """A turn_id with Claude Code's transcript: neither is believed."""
    payload = dict(CLAUDE[0], turn_id="t-1")
    assert _core().host(payload, {}) == "unknown"


def test_a_rollout_of_another_session_is_not_evidence():
    payload = json.loads((FIXTURES / "session_start.json").read_text("utf-8"))
    payload["session_id"] = "00000000-0000-0000-0000-000000000000"
    assert _core().host(payload, {}) == "unknown"


def test_the_fixtures_carry_no_account_data():
    """Codex's rollout holds creator_user_id / creator_account_id; none of that, nor a token,
    may sit in a fixture."""
    import re
    bad = re.compile(r"eyJ|sk-|access_token|refresh_token|id_token|account_id|creator_user|Bearer"
                     r"|/tmp/claude")
    for f in FIXTURES.rglob("*"):
        if f.is_file():
            assert not bad.search(f.read_text("utf-8")), f.name
