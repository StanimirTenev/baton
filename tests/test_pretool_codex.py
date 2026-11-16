"""L1 for Codex's apply_patch, as for Edit.

Codex edits a file with apply_patch: `tool_input.command` holds the patch, no `file_path`. In the
live probe (14.11, Codex CLI 0.169.0) the PreToolUse hook ran for it and said nothing, where the
same heading through Edit gave lesson L1. The payloads start from a real one the probe dumped
(tests/fixtures/codex/pretool_apply_patch.json).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_pretool.py"
REAL = json.loads((ROOT / "tests" / "fixtures" / "codex" / "pretool_apply_patch.json").read_text("utf-8"))


def _run(event: dict, tmp_path: Path) -> str:
    env = {"PATH": "/usr/bin:/bin", "CLAUDE_PLUGIN_DATA": str(tmp_path),
           "BATON_LOGBOOK": "LOGBOOK.md", "BATON_HOME": str(tmp_path / "tasks")}
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event).encode("utf-8"),
                         capture_output=True, env=env)
    assert out.returncode == 0, out.stderr.decode("utf-8")
    text = out.stdout.decode("utf-8").strip()
    return (json.loads(text).get("hookSpecificOutput") or {}).get("additionalContext", "") if text else ""


def _patch(body: str, **over) -> dict:
    return dict(REAL, tool_input={"command": f"*** Begin Patch\n{body}\n*** End Patch"}, **over)


TYPED = "*** Update File: /work/tasks/riba-proba/LOGBOOK.md\n@@\n ---\n+\n+## 2026-11-14 10:00 — typed hour"


def test_the_probe_s_offline_case_now_gives_l1(tmp_path):
    ctx = _run(_patch(TYPED), tmp_path)
    assert "L1" in ctx and "baton_entry.py" in ctx and "LOGBOOK.md" in ctx, ctx


def test_the_real_patch_has_no_typed_hour_and_stays_silent(tmp_path):
    """Its context line ` ## 2026-11-13 10:00 -- ...` is already in the file: not added."""
    assert _run(REAL, tmp_path) == ""


def test_an_added_file_and_a_relative_path_are_read(tmp_path):
    body = "*** Add File: tasks/nova/LOGBOOK.md\n+---\n+---\n+\n+## 2026-11-14 10:00 — x"
    assert "L1" in _run(_patch(body, cwd="/work"), tmp_path)


def test_a_typed_hour_in_another_file_of_the_patch_is_not_the_logbook_s(tmp_path):
    body = ("*** Update File: /work/notes.md\n@@\n+## 2026-11-14 10:00 — not a logbook\n"
            "*** Update File: /work/tasks/riba-proba/LOGBOOK.md\n@@\n+plain line")
    assert _run(_patch(body), tmp_path) == ""


def test_a_moved_logbook_is_read_under_its_new_name(tmp_path):
    body = ("*** Update File: /work/tasks/riba-proba/old.md\n*** Move to: /work/tasks/riba-proba/LOGBOOK.md"
            "\n@@\n+## 2026-11-14 10:00 — moved")
    assert "L1" in _run(_patch(body), tmp_path)


def test_an_unknown_host_keeps_what_it_had(tmp_path):
    """No turn_id, no rollout transcript (the probe's pt-codex.json): not known to be Codex."""
    event = {k: v for k, v in _patch(TYPED).items() if k not in ("turn_id", "transcript_path")}
    assert _run(event, tmp_path) == ""


def test_a_patch_that_re_adds_a_heading_the_logbook_holds_is_silent(tmp_path):
    """Row 161 (v3.36.0): a heading removed and added back to put a section under it is carried
    through, not typed anew; one with an hour the logbook does not hold is still L1."""
    log = tmp_path / "tasks" / "riba-proba" / "LOGBOOK.md"
    log.parent.mkdir(parents=True)
    log.write_text("## 2026-11-14 10:00 — kept\n\n### Done\nx\n", "utf-8")
    body = (f"*** Update File: {log}\n@@\n-## 2026-11-14 10:00 — kept\n+## 2026-11-14 10:00 — kept\n"
            "+\n+### Claims to verify\n+none")
    assert _run(_patch(body), tmp_path) == ""
    assert "L1" in _run(_patch(body.replace("+## 2026-11-14 10:00", "+## 2026-11-14 10:05")), tmp_path)
