"""After an update, the agent tells the human once what is new -- without the network.

Installed from the directory, Baton updates itself on the next launch and Claude Code says only
"Plugins changed". Nothing told the human what changed (stenly, 2026-10-05). The hook remembers
the last version it ran as and, when that changes, names what is new from the README's notes.

Through the hook's entry point, as the harness runs it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_session_start.py"
sys.path.insert(0, str(ROOT / "hooks"))
import baton_session_start as hook  # noqa: E402

NOW = hook.BATON_VERSION


def _run(tmp_path, state=None):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tasks").mkdir(exist_ok=True)
    st = tmp_path / "s.json"
    if state is not None and not st.exists():
        st.write_text(json.dumps(state), "utf-8")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), BATON_HOME=str(tmp_path / "tasks"), BATON_SESSION_STATE=str(st))
    out = subprocess.run([sys.executable, str(HOOK)], input=b'{"source":"startup"}',
                         capture_output=True, env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout).get("hookSpecificOutput", {}).get("additionalContext", "")


def test_after_an_update_the_agent_is_told_what_is_new(tmp_path):
    ctx = _run(tmp_path, {"seen_version": "3.11.0"})
    assert f"updated from v3.11.0 to v{NOW}" in ctx
    assert "Baton works only where plugin hooks run, and now says so before install." in ctx   # a lead from the notes
    assert f"releases/tag/v{NOW}" in ctx
    assert "once" in ctx


def test_told_only_once(tmp_path):
    _run(tmp_path, {"seen_version": "3.11.0"})
    assert "updated from" not in _run(tmp_path)


def test_an_install_from_before_this_note_existed_is_an_update_too(tmp_path):
    """3.11.0 kept no version, but it did keep a state file: the first update must speak."""
    ctx = _run(tmp_path, {"asked": "2026-10-04"})
    assert f"updated to v{NOW}" in ctx


def test_a_fresh_install_is_not_told_it_was_updated(tmp_path):
    assert "updated" not in _run(tmp_path)
    assert json.loads((tmp_path / "s.json").read_text("utf-8"))["seen_version"] == NOW


def test_the_notes_come_from_the_readme_section_of_this_version():
    leads = hook.release_leads(NOW)
    assert leads and leads[0].startswith("Baton works only where plugin hooks run")
    assert all(len(x) < 200 for x in leads)
    assert hook.release_leads("0.0.1") == []
