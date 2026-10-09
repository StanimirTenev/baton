"""After compaction, the agent is told to write the logbook -- not shown the board again.

Promised publicly on 2026-10-03: Baton did nothing at compaction. The documented way in is
SessionStart with `source: "compact"`: a PreCompact hook can only block compaction, and
Claude Code discards its `systemMessage` (code.claude.com/docs/en/hooks#precompact), so
nothing it prints reaches the model. Before v3.12.0 SessionStart did fire on compaction, but
it re-sent the whole board with the instruction to open the next reply with it -- mid-session.

Run the way the harness runs it: a subprocess with the hook's JSON on stdin.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_session_start.py"


def _setup(tmp_path, *, work_in_session=True):
    root = tmp_path / "tasks"
    t = root / "billing"
    t.mkdir(parents=True)
    log = t / "LOGBOOK.md"
    log.write_text('---\nstate: active\nturn: us\nnext: "изпрати фактурата"\n---\n\n'
                   '## 2026-09-01 10:00 — a\n\nx\n', encoding="utf-8")
    now = time.time()
    os.utime(log, (now - 7200, now - 7200))
    transcript = tmp_path / "session.jsonl"
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 3600))
    transcript.write_text(json.dumps({"type": "user", "timestamp": started}) + "\n", "utf-8")
    if work_in_session:
        work = t / "invoice.md"
        work.write_text("draft", "utf-8")
        os.utime(work, (now - 600, now - 600))      # in this session, past the grace period
    return root, transcript


def _run(tmp_path, root, payload, plugin=False):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), BATON_HOME=str(root), BATON_LOGBOOK="LOGBOOK.md",
               BATON_SESSION_STATE=str(tmp_path / "s.json"),
               BATON_BODY_STATE=str(tmp_path / "bodies.json"),
               BATON_LESSONS_STATE=str(tmp_path / "lessons.json"))
    if plugin:
        env.update(CLAUDE_PLUGIN_ROOT=str(ROOT), CLAUDE_PLUGIN_DATA=str(tmp_path / "data"))
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload).encode("utf-8"),
                         capture_output=True, env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_after_compaction_the_agent_writes_the_logbook_and_does_not_reshow_the_board(tmp_path):
    root, transcript = _setup(tmp_path)
    raw = _run(tmp_path, root, {"source": "compact", "session_id": "s1",
                                "transcript_path": str(transcript)})
    out = json.loads(raw)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "compacted" in ctx
    assert "billing" in ctx                       # the folder with this session's work
    assert "WHOLE board" not in ctx               # not told to open the reply with the board
    assert "compacted" in out["systemMessage"]


def test_after_compaction_only_this_sessions_work_is_named(tmp_path):
    """An old unrecorded file in another task is the board's business, not this session's."""
    root, transcript = _setup(tmp_path)
    old = root / "archive"
    old.mkdir()
    (old / "LOGBOOK.md").write_text("## 2026-01-01 10:00 — a\n", "utf-8")
    stale = old / "notes.md"
    stale.write_text("x", "utf-8")
    then = time.time() - 30 * 86400
    os.utime(old / "LOGBOOK.md", (then - 60, then - 60))
    os.utime(stale, (then, then))
    ctx = json.loads(_run(tmp_path, root, {"source": "compact", "session_id": "s1",
                                           "transcript_path": str(transcript)})
                     )["hookSpecificOutput"]["additionalContext"]
    assert "billing" in ctx and "archive" not in ctx


def test_after_compaction_with_no_files_the_reminder_still_comes(tmp_path):
    """Work that left no file (a decision, a conversation) is not seen by the file check;
    the instruction still reaches the agent."""
    root, transcript = _setup(tmp_path, work_in_session=False)
    out = json.loads(_run(tmp_path, root, {"source": "compact", "session_id": "s1",
                                           "transcript_path": str(transcript)}))
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "compacted" in ctx and "WHOLE board" not in ctx


def test_after_compaction_in_plugin_mode_the_rules_come_back_too(tmp_path):
    """CLAUDE.md is re-read after compaction; a plugin's rules arrive only from this hook."""
    root, transcript = _setup(tmp_path)
    out = json.loads(_run(tmp_path, root, {"source": "compact", "session_id": "s1",
                                           "transcript_path": str(transcript)}, plugin=True))
    assert "Baton's working rules" in out["hookSpecificOutput"]["additionalContext"]


def test_a_new_session_still_gets_the_board(tmp_path):
    root, transcript = _setup(tmp_path)
    out = json.loads(_run(tmp_path, root, {"source": "startup", "session_id": "s1",
                                           "transcript_path": str(transcript)}))
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "WHOLE board" in ctx and "compacted" not in ctx


def test_after_clear_the_board_comes_back_with_a_word_on_why(tmp_path):
    """/clear replaces the restart Baton used to suggest (2026-10-09): the fresh context gets
    the whole board, told the logbooks were just written -- not asked what was going on."""
    root, transcript = _setup(tmp_path)
    out = json.loads(_run(tmp_path, root, {"source": "clear", "session_id": "s2",
                                           "transcript_path": str(transcript)}))
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "/clear" in ctx and "WHOLE board" in ctx and "billing" in ctx
    startup = json.loads(_run(tmp_path, root, {"source": "startup", "session_id": "s3",
                                               "transcript_path": str(transcript)}))
    assert "/clear" not in startup["hookSpecificOutput"]["additionalContext"]


def test_sessionstart_fires_on_compaction_in_both_installs():
    """No matcher on SessionStart, in the plugin's hooks.json and in what the installer
    writes: a matcher such as "startup" would silently drop the compact case."""
    plugin = json.loads((ROOT / "hooks" / "hooks.json").read_text("utf-8"))
    for group in plugin["hooks"]["SessionStart"]:
        assert group.get("matcher", "") in ("", "*")
    src = (ROOT / "hooks" / "_install_hooks.py").read_text("utf-8")
    assert '"matcher"' not in src


def test_output_is_utf8_not_escaped(tmp_path):
    """#3: Cyrillic went out as \\uXXXX -- 13,068 characters of raw JSON for 5,667 of text.
    The documented 10,000-character cap is measured on each parsed field, so this never cut
    the board; the output is written as UTF-8 anyway, at less than half the size."""
    root, transcript = _setup(tmp_path)
    raw = _run(tmp_path, root, {"source": "startup", "session_id": "s1",
                                "transcript_path": str(transcript)})
    assert "изпрати фактурата".encode("utf-8") in raw
    assert b"\\u04" not in raw
