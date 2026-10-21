"""ZA-OPRAVYANE row 17: after about a week of use, Baton asks once for feedback -- no telemetry.

stenly, 07.10: installs come from the comments, so ask people who try it to say, after a while,
what worked, what did not, and what they would improve. 148 installed, 10 active, 0 uninstalled
(the portal, 07.10): nobody knows why the rest never got to use it. Baton sends nothing; the
agent asks one sentence and gives the link. Through the hook's entry point.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_session_start.py"


def _run(tmp_path, state):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tasks").mkdir(exist_ok=True)
    st = tmp_path / "s.json"
    if not st.exists():
        st.write_text(json.dumps(state), "utf-8")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), BATON_HOME=str(tmp_path / "tasks"), BATON_SESSION_STATE=str(st))
    out = subprocess.run([sys.executable, str(HOOK)], input=b'{"source":"startup"}',
                         capture_output=True, env=env)
    assert out.returncode == 0, out.stderr
    ctx = json.loads(out.stdout).get("hookSpecificOutput", {}).get("additionalContext", "")
    return ctx, json.loads(st.read_text("utf-8"))


def _base(**extra):
    today = date.today().isoformat()
    return {"asked": today, "inventory_offered": today, "review_offered": today,
            "seen_version": "9.9.9", **extra}


def test_asked_once_after_a_week(tmp_path):
    week = (date.today() - timedelta(days=8)).isoformat()
    ctx, _ = _run(tmp_path, _base(first_seen=week))
    assert "what has worked, what has not, and what they would improve" in ctx, ctx
    assert "https://github.com/StanimirTenev/baton/issues" in ctx
    assert "sends nothing" in ctx
    ctx, _ = _run(tmp_path, {})
    assert "would improve" not in ctx, "asked once; declined or answered, it does not come back"


def test_not_before_a_week(tmp_path):
    ctx, _ = _run(tmp_path, _base(first_seen=(date.today() - timedelta(days=3)).isoformat()))
    assert "would improve" not in ctx


def test_the_first_start_is_remembered_and_not_asked_about(tmp_path):
    ctx, state = _run(tmp_path, _base())
    assert "would improve" not in ctx
    assert state["first_seen"] == date.today().isoformat()
