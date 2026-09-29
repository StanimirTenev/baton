"""hooks/run.sh picks the interpreter for the plugin's hooks. On Windows `python3` is often
the Microsoft Store stand-in: it prints "Python" and exits 0 without running anything
(seen on the test machine, 2026-09-29). A check on the exit code alone would take it."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "hooks" / "run.sh"


def _bin(tmp_path, stub_python3=True):
    b = tmp_path / "bin"
    b.mkdir()
    if stub_python3:
        (b / "python3").write_text("#!/bin/sh\necho Python\nexit 0\n")
        (b / "python3").chmod(0o755)
    (b / "python").symlink_to(sys.executable)
    return b


def test_the_store_stand_in_is_refused_and_the_real_python_runs(tmp_path):
    script = tmp_path / "hook.py"
    script.write_text("print('ran under', 'real')\n")
    env = dict(os.environ, PATH=f"{_bin(tmp_path)}:/usr/bin:/bin")
    out = subprocess.run([shutil.which("sh"), str(RUN), str(script)], capture_output=True,
                         text=True, env=env)
    assert out.stdout.strip() == "ran under real", out


def test_no_python_says_why_and_does_not_break_the_session(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    out = subprocess.run([shutil.which("sh"), str(RUN), "x.py"], capture_output=True,
                         text=True, env=dict(os.environ, PATH=str(empty)))
    assert out.returncode == 0 and "no Python" in out.stderr
