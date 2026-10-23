"""ZA-OPRAVYANE row 36 (Pawan Singh Rathore, 22.10): the heartbeat was written before main() ran,
so after a crash /baton-doctor still showed the hook ✅ "last ran just now". A hook exits 0 whatever
happens -- it must never break the session -- so nothing else said so.

Now the heartbeat is written after main() returns, and a run that raised leaves
`baton.beat.<hook>.crashed`: the time and the exception's class, nothing else. The doctor and the
next SessionStart say it. Run the way the harness runs them: copies of the hooks with a fault
injected into main(), as the proba of 22.10 did.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ("baton_session_start", "baton_prompt", "baton_stop", "baton_batch", "baton_stop_failure")


def _env(tmp_path, data):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), BATON_HOME=str(tmp_path / "tasks"), CLAUDE_PLUGIN_DATA=str(data),
               BATON_STATE_DIR=str(tmp_path / "state"),
               BATON_LESSONS_STATE=str(data / "baton.lessons.json"))
    return env


def _broken_copy(tmp_path, hook):
    """The four hooks side by side (they load each other), with main() of one made to raise."""
    copy = tmp_path / "hooks"
    copy.mkdir(exist_ok=True)
    for h in HOOKS:
        shutil.copy(ROOT / "hooks" / f"{h}.py", copy)
    path = copy / f"{hook}.py"
    text = path.read_text("utf-8")
    assert text.count("def main() -> int:\n") == 1
    path.write_text(text.replace("def main() -> int:\n",
                                 "def main() -> int:\n    raise RuntimeError('injected /secret/path')\n"),
                    "utf-8")
    return path


def _run(path, env, payload=b"{}"):
    return subprocess.run([sys.executable, str(path)], input=payload, capture_output=True, env=env)


def test_a_crash_leaves_a_marker_and_no_heartbeat(tmp_path):
    for hook in HOOKS:
        data = tmp_path / f"data-{hook}"
        out = _run(_broken_copy(tmp_path, hook), _env(tmp_path, data))
        assert out.returncode == 0, (hook, out.stderr)          # never breaks the session
        assert not (data / f"baton.beat.{hook}").exists(), f"{hook}: a crash is not a finish"
        marker = (data / f"baton.beat.{hook}.crashed").read_text("utf-8")
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)? RuntimeError", marker), marker
        shutil.rmtree(tmp_path / "hooks")


def test_the_doctor_says_crashed_not_ran(tmp_path):
    data = tmp_path / "data"
    env = _env(tmp_path, data)
    assert _run(ROOT / "hooks" / "baton_session_start.py", env).returncode == 0
    _run(_broken_copy(tmp_path, "baton_stop"), env)
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "baton_doctor.py")],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 1, out.stdout
    assert "CRASHED" in out.stdout and "RuntimeError" in out.stdout
    assert "Crashed on its last run: Stop" in out.stdout
    assert "/secret/path" not in out.stdout, "the message is not kept, only the class"
    # A run that finishes afterwards makes the crash history.
    assert _run(ROOT / "hooks" / "baton_stop.py", env).returncode == 0
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "baton_doctor.py")],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0 and "CRASHED" not in out.stdout, out.stdout
    assert "last finished" in out.stdout


def test_the_next_session_start_says_it(tmp_path):
    data = tmp_path / "data"
    env = _env(tmp_path, data)
    _run(_broken_copy(tmp_path, "baton_stop"), env)
    out = _run(ROOT / "hooks" / "baton_session_start.py", env)
    text = out.stdout.decode("utf-8")
    assert "crashed on its last run" in text and "Stop at " in text and "RuntimeError" in text


def test_a_malformed_batch_exits_0_and_is_recorded(tmp_path):
    """baton_batch.py had no top-level guard: `{"tool_calls":[1]}` was a traceback and exit 1.
    Since row 67 (v3.22.0) a call of another shape is skipped, so the guard is shown with a fault
    injected instead; the malformed batch itself is tests/test_stdin_shape.py."""
    data = tmp_path / "data"
    out = _run(_broken_copy(tmp_path, "baton_batch"), _env(tmp_path, data), b'{"tool_calls":[1]}')
    assert out.returncode == 0, out.stderr
    assert out.stderr == b""
    assert (data / "baton.beat.baton_batch.crashed").read_text("utf-8").endswith(" RuntimeError")
