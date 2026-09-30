"""install.sh must find a real Python 3.8+ before it writes anything, and say what it found
and how to get the right one when there is none. It took the first `python3` on PATH:
on a Mac without the developer tools that is a stand-in that opens an "install" dialog,
and on 2026-09-30 a Mac's 3.9 took the hooks down in silence (the code needed 3.10)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _bin_without_python(tmp_path: Path) -> Path:
    """Every command on this machine's PATH except any python, so the test decides which
    Python the installer can see."""
    b = tmp_path / "bin"
    b.mkdir()
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name.startswith("python") or (b / name).exists():
                continue
            src = Path(d) / name
            if src.is_file() and os.access(src, os.X_OK):
                (b / name).symlink_to(src)
    return b


def _fake(b: Path, name: str, says: str) -> None:
    (b / name).write_text(f"#!/bin/sh\necho '{says}'\nexit 0\n")
    (b / name).chmod(0o755)


def _install(tmp_path: Path, b: Path):
    cfg = tmp_path / "cfg"
    env = dict(os.environ, PATH=str(b), HOME=str(tmp_path / "home"), CLAUDE_CONFIG_DIR=str(cfg),
               BATON_HOME=str(tmp_path / "tasks"))
    out = subprocess.run(["bash", str(ROOT / "install.sh")], capture_output=True, text=True, env=env)
    return out, cfg


@pytest.mark.parametrize("says", ["Python", "old 3.7"], ids=["store-or-xcode-stand-in", "python-3.7"])
def test_an_unusable_python_stops_the_install_before_anything_is_written(tmp_path, says):
    b = _bin_without_python(tmp_path)
    _fake(b, "python3", says)
    out, cfg = _install(tmp_path, b)
    assert out.returncode == 1
    assert "Nothing has been installed" in out.stderr and "not usable" in out.stderr
    assert not cfg.exists() or not any(cfg.iterdir()), "the installer wrote before checking"


def test_no_python_at_all_says_how_to_get_one(tmp_path):
    out, cfg = _install(tmp_path, _bin_without_python(tmp_path))
    assert out.returncode == 1 and "Python 3.8 or later" in out.stderr
    assert ("python.org" in out.stderr) or ("package manager" in out.stderr)
    assert not cfg.exists() or not any(cfg.iterdir())


def test_a_real_python_is_used_even_behind_a_stand_in(tmp_path):
    b = _bin_without_python(tmp_path)
    _fake(b, "python3", "Python")                     # the stand-in comes first, as on Windows
    (b / "python").symlink_to(sys.executable)
    out, cfg = _install(tmp_path, b)
    assert out.returncode == 0, out.stderr
    settings = (cfg / "settings.json").read_text()
    assert str(b / "python3") not in settings, "the stand-in was baked into the hooks"
