"""ZA-OPRAVYANE row 53 (swarm D, 22.10; probe G06): per-session state was in the shared temp folder,
readable by every local user.

Stop, the prompt hook and PostToolBatch kept it in `tempfile.gettempdir()` -- /tmp on Linux and
macOS -- written 0644 under the usual umask: the folders Stop handed back, `hollow:<task>:<entry
heading>` verbatim, the tasks a message named (seen live: /tmp/baton-prompt-<session>.json, 664,
confidential task names). Now it is in `sessions/` beside Baton's other state -- ${CLAUDE_PLUGIN_DATA}
for the plugin, next to the hooks for install.sh -- and each file is 0600. BATON_STATE_DIR still
moves it (the tests use it).
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HEADING = "Pure Cycle Power — Pashkin's offer, 4.1M"
HOOKS = ("baton_session_start", "baton_prompt", "baton_stop", "baton_batch")


def _env(tmp_path, plugin=True):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tmp").mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), TMPDIR=str(tmp_path / "tmp"),
               BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               BATON_LESSONS_STATE=str(tmp_path / "lessons.json"),
               BATON_BODY_STATE=str(tmp_path / "bodies.json"))
    if plugin:
        env["CLAUDE_PLUGIN_DATA"] = str(tmp_path / "data")
    return env


def _hooks(tmp_path, plugin):
    """The plugin runs the hooks from the repository's copy; install.sh from its own folder."""
    if plugin:
        return ROOT / "hooks"
    copy = tmp_path / "hooks"
    copy.mkdir(exist_ok=True)
    for h in HOOKS:
        shutil.copy(ROOT / "hooks" / f"{h}.py", copy)
    return copy


def _run(hooks, hook, env, payload):
    old = os.umask(0o022)                          # the common default
    try:
        out = subprocess.run([sys.executable, str(hooks / f"{hook}.py")],
                             input=json.dumps(payload).encode("utf-8"), capture_output=True, env=env)
    finally:
        os.umask(old)
    assert out.returncode == 0, out.stderr
    return out


def _task(tmp_path):
    folder = tmp_path / "tasks" / "pure-cycle-power"
    folder.mkdir(parents=True)
    (folder / "LOGBOOK.md").write_text(
        "---\nstate: active\ndone_when: x\nnext: the offer\n---\n\n"
        f"## {datetime.now():%Y-%m-%d %H:%M} — {HEADING}\n\nok\n", "utf-8")
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({"type": "user", "timestamp": (
        datetime.now() - timedelta(minutes=30)).astimezone().isoformat()}) + "\n", "utf-8")
    return str(transcript)


def _private(where: Path, pattern: str):
    files = list(where.glob(pattern))
    assert files, f"no {pattern} in {where}"
    for f in files:
        mode = stat.S_IMODE(f.stat().st_mode)
        assert mode & 0o077 == 0, f"{f} is {oct(mode)}"
    return files


@pytest.mark.parametrize("plugin", [True, False], ids=["plugin", "install.sh"])
def test_stop_state_is_private_and_not_in_the_shared_temp(tmp_path, plugin):
    env, tr = _env(tmp_path, plugin), _task(tmp_path)
    hooks = _hooks(tmp_path, plugin)
    out = _run(hooks, "baton_stop", env, {"session_id": "abc", "transcript_path": tr})
    assert json.loads(out.stdout).get("decision") == "block"      # asked about the hollow entry
    assert not list((tmp_path / "tmp").iterdir()), "state in the shared temp folder"
    where = (tmp_path / "data" if plugin else hooks) / "sessions"
    files = _private(where, "baton-stop-*.json")
    assert "Pashkin" in files[0].read_text("utf-8")               # what the file holds
    # And it is read back: the same session is not asked twice.
    again = _run(hooks, "baton_stop", env, {"session_id": "abc", "transcript_path": tr})
    assert "Pashkin" not in again.stdout.decode("utf-8")


def test_prompt_state_is_private(tmp_path):
    env = _env(tmp_path)
    _task(tmp_path)
    out = _run(ROOT / "hooks", "baton_prompt", env,
               {"prompt": "what about pure-cycle-power?", "session_id": "abc"})
    assert "pure-cycle-power" in out.stdout.decode("utf-8")
    assert not list((tmp_path / "tmp").iterdir()), "state in the shared temp folder"
    _private(tmp_path / "data" / "sessions", "baton-prompt-*.json")


def test_batch_state_is_private(tmp_path):
    env = _env(tmp_path)
    call = {"tool_name": "Bash", "tool_input": {"command": "grep -rn Featured page.html"},
            "tool_response": "(Bash completed with no output)"}
    out = _run(ROOT / "hooks", "baton_batch", env, {"session_id": "abc", "tool_calls": [call]})
    assert "lesson L2" in out.stdout.decode("utf-8")
    assert not list((tmp_path / "tmp").iterdir()), "state in the shared temp folder"
    _private(tmp_path / "data" / "sessions", "baton-l2-*.json")


def test_a_file_left_world_readable_is_tightened(tmp_path):
    """A state file an earlier version left 0644 is made 0600 when it is written again."""
    env, tr = _env(tmp_path), _task(tmp_path)
    old = tmp_path / "data" / "sessions" / "baton-stop-abc.json"
    old.parent.mkdir(parents=True)
    old.write_text("[]", "utf-8")
    os.chmod(old, 0o644)
    _run(ROOT / "hooks", "baton_stop", env, {"session_id": "abc", "transcript_path": tr})
    _private(old.parent, "baton-stop-*.json")


def test_a_week_old_session_file_is_cleared(tmp_path):
    """The temp folder was cleaned by the system; `sessions/` is not, so Stop clears it."""
    env, tr = _env(tmp_path), _task(tmp_path)
    where = tmp_path / "data" / "sessions"
    where.mkdir(parents=True)
    stale, recent = where / "baton-prompt-old.json", where / "baton-prompt-recent.json"
    for f, days in ((stale, 8), (recent, 6)):
        f.write_text("[]", "utf-8")
        t = datetime.now().timestamp() - days * 86400
        os.utime(f, (t, t))
    _run(ROOT / "hooks", "baton_stop", env, {"session_id": "abc", "transcript_path": tr})
    assert not stale.exists() and recent.exists()
