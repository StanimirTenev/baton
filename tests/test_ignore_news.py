"""ZA-OPRAVYANE row 97 (Iqbal, 25.10): a .batonignore written in an earlier session hid work with
no word -- Stop names only a line saved in its own session. The board now names the lines added
since the last session, and on the first look any line that hides a whole type of file."""
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_session_start.py"


def _board(tmp_path) -> str:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR", "BATON_HOME"))}
    env.update(BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               HOME=str(tmp_path / "home"))
    out = subprocess.run([sys.executable, str(HOOK)], capture_output=True, env=env,
                         input=json.dumps({"session_id": "s", "source": "startup"}).encode())
    assert out.returncode == 0, out.stderr
    return out.stdout.decode("utf-8")


def _task(tmp_path, name="parser"):
    folder = tmp_path / "tasks" / name
    folder.mkdir(parents=True)
    (folder / "LOGBOOK.md").write_text("---\nstate: active\nnext: go on\n---\n\n## 2026-11-01 10:00 — x\n", "utf-8")
    return folder


def test_a_whole_type_hidden_before_this_version_is_named(tmp_path):
    folder = _task(tmp_path)
    (folder / ".batonignore").write_text("live.log\n*.py\n", "utf-8")
    board = _board(tmp_path)
    assert "parser: `*.py`" in board and "live.log" not in board, board
    assert ".batonignore lines added" not in _board(tmp_path), "said once"


def test_a_line_added_since_the_last_session_is_named(tmp_path):
    folder = _task(tmp_path)
    (folder / ".batonignore").write_text("live.log\n", "utf-8")
    assert ".batonignore lines added" not in _board(tmp_path)
    (folder / ".batonignore").write_text("live.log\nsrc/\n", "utf-8")
    (tmp_path / "tasks" / ".batonignore").write_text("parser/out/\n", "utf-8")
    board = _board(tmp_path)
    assert "parser: `src/`" in board and "the task root: `parser/out/`" in board, board
    assert "`live.log`" not in board
