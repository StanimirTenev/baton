"""ZA-OPRAVYANE row 41 (22.10, the probe for the v2 reply to Pawan): a hook killed at its time
limit -- SIGTERM, then SIGKILL -- left no trace, and /baton-doctor showed ✅ "last finished just
now" from the run before. The crash marker of row 36 is written by the hook itself, and a killed
process writes nothing.

Now each run writes `baton.beat.<hook>.started.<pid>` (the time) before main() and removes it
when it finishes or crashes. A marker left behind, newer than the last finish, from a process
that is gone (or older than any hook's limit) is a run that did not finish. A run of the same hook
still going in another session is not one. Run the way proba-v2.sh ran it: copies of the hooks
with a sleep injected into main(), killed from outside.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ("baton_session_start", "baton_prompt", "baton_stop", "baton_batch")

pytestmark = pytest.mark.skipif(os.name == "nt", reason="signals as Claude Code sends them on POSIX")


def _env(tmp_path, data):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(home), BATON_HOME=str(tmp_path / "tasks"), CLAUDE_PLUGIN_DATA=str(data),
               BATON_STATE_DIR=str(tmp_path / "state"),
               BATON_LESSONS_STATE=str(data / "baton.lessons.json"))
    return env


def _slow_copy(tmp_path, hook):
    """The four hooks side by side, main() of one made to sleep past any limit."""
    copy = tmp_path / "hooks"
    copy.mkdir(exist_ok=True)
    for h in HOOKS:
        shutil.copy(ROOT / "hooks" / f"{h}.py", copy)
    path = copy / f"{hook}.py"
    text = path.read_text("utf-8")
    assert text.count("def main() -> int:\n") == 1
    path.write_text(text.replace("def main() -> int:\n",
                                 "def main() -> int:\n    import time; time.sleep(30)\n"), "utf-8")
    return path


def _start(path, env):
    return subprocess.Popen([sys.executable, str(path)], stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)


def _in_main(p, data, hook):
    """Wait until the run is inside main() -- its marker is there -- or give up after 5 s (the
    code before the fix writes none, and the test must then fail on the doctor, not hang)."""
    p.stdin.write(b"{}")
    p.stdin.close()
    for _ in range(100):
        if (data / f"baton.beat.{hook}.started.{p.pid}").exists():
            time.sleep(0.2)
            return
        time.sleep(0.05)
    time.sleep(1)


def _doctor(env):
    return subprocess.run([sys.executable, str(ROOT / "tools" / "baton_doctor.py")],
                          capture_output=True, text=True, env=env)


def _finish(hook, env):
    out = subprocess.run([sys.executable, str(ROOT / "hooks" / f"{hook}.py")], input=b"{}",
                         capture_output=True, env=env)
    assert out.returncode == 0, out.stderr


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGKILL])
def test_a_killed_stop_is_not_shown_as_its_last_finish(tmp_path, sig):
    data = tmp_path / "data"
    env = _env(tmp_path, data)
    _finish("baton_session_start", env)
    _finish("baton_stop", env)                     # a normal run first, as in proba-v2.sh
    assert "✅ Stop" in _doctor(env).stdout
    p = _start(_slow_copy(tmp_path, "baton_stop"), env)
    _in_main(p, data, "baton_stop")
    p.send_signal(sig)
    p.wait(10)
    out = _doctor(env)
    assert out.returncode == 1, out.stdout
    assert "❌ Stop" in out.stdout and "DID NOT FINISH" in out.stdout, out.stdout
    assert "killed or timed out?" in out.stdout
    assert "Did not finish its last run: Stop" in out.stdout


def test_the_next_session_start_says_it(tmp_path):
    data = tmp_path / "data"
    env = _env(tmp_path, data)
    p = _start(_slow_copy(tmp_path, "baton_stop"), env)
    _in_main(p, data, "baton_stop")
    p.kill()
    p.wait(10)
    out = subprocess.run([sys.executable, str(ROOT / "hooks" / "baton_session_start.py")],
                         input=b"{}", capture_output=True, env=env)
    text = out.stdout.decode("utf-8")
    assert "did not finish its last run" in text and "Stop, started at " in text, text
    assert "killed or timed out?" in text


def test_every_hook_marks_its_start_and_clears_it_when_it_finishes(tmp_path):
    for hook in HOOKS:
        data = tmp_path / f"data-{hook}"
        env = _env(tmp_path, data)
        p = _start(_slow_copy(tmp_path, hook), env)
        _in_main(p, data, hook)
        marker = data / f"baton.beat.{hook}.started.{p.pid}"
        assert marker.is_file(), hook
        p.kill()
        p.wait(10)
        shutil.rmtree(tmp_path / "hooks")
        _finish(hook, env)
        assert not marker.exists(), "a finish clears the markers of runs that are gone"
        assert not list(data.glob(f"baton.beat.{hook}.started.*")), "and its own"
        assert (data / f"baton.beat.{hook}").is_file()


def test_a_run_still_going_is_not_called_killed(tmp_path):
    """Two sessions, the same hook at the same time: the one still running is not a kill."""
    data = tmp_path / "data"
    env = _env(tmp_path, data)
    _finish("baton_session_start", env)
    _finish("baton_stop", env)
    p = _start(_slow_copy(tmp_path, "baton_stop"), env)
    try:
        _in_main(p, data, "baton_stop")
        out = _doctor(env)
        assert out.returncode == 0 and "DID NOT FINISH" not in out.stdout, out.stdout
        # Another run of Stop starts and finishes meanwhile: it leaves the other's marker alone.
        _finish("baton_stop", env)
        assert (data / f"baton.beat.baton_stop.started.{p.pid}").is_file()
    finally:
        p.kill()
        p.wait(10)


def test_a_finish_after_the_kill_makes_it_history(tmp_path):
    data = tmp_path / "data"
    env = _env(tmp_path, data)
    _finish("baton_session_start", env)
    p = _start(_slow_copy(tmp_path, "baton_stop"), env)
    _in_main(p, data, "baton_stop")
    p.terminate()
    p.wait(10)
    assert _doctor(env).returncode == 1
    _finish("baton_stop", env)
    out = _doctor(env)
    assert out.returncode == 0 and "DID NOT FINISH" not in out.stdout, out.stdout
