"""ZA-OPRAVYANE row 100 (Gianpiero Puleo, 27.10): L2 counted only grep as a read of a file.

`cat`, `head`, `tail` and `sed -n` print a file; an empty answer from one is the same failed read
as an empty grep. What writes is left alone -- `cat > f`, `cat <<EOF`, `sed -i` -- and so is the
Read tool, whose image results come back as no text. Through the hook, JSON on stdin.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_batch.py"


def _fires(tmp_path, tool, command, response="(Bash completed with no output)") -> bool:
    here = tmp_path / str(abs(hash((tool, command))))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(BATON_HOME=str(here / "tasks"), HOME=str(here / "home"),
               BATON_STATE_DIR=str(here / "state"), BATON_LESSONS_STATE=str(here / "lessons.json"))
    call = {"tool_name": tool, "tool_input": {"command": command, "file_path": "/x/shot.png"},
            "tool_response": response}
    out = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, env=env,
                         input=json.dumps({"session_id": "s", "tool_calls": [call]}))
    assert out.returncode == 0, out.stderr
    return "lesson L2" in out.stdout


def test_an_empty_file_print_is_a_failed_read(tmp_path):
    for command in ("cat notes/plan.md", "head -n 20 report.csv", "tail -5 run.log",
                    "sed -n '10,20p' page.html", "cd site && cat index.html 2>/dev/null",
                    ):
        assert _fires(tmp_path, "Bash", command), command


def test_what_writes_is_not_a_read(tmp_path):
    for command in ("cat > entry.md <<'EOF'\nthe entry\nEOF", "cat <<EOF > out.txt\nx\nEOF",
                    "cat a.txt b.txt > both.txt", "cat a.txt >> log.txt", "head -c 100 /dev/urandom &> f",
                    "sed -i 's/a/b/' notes.md", "git status --short | head", "sed -n -i '1p' notes.md", "sed 's/a/b/' notes.md",
                    "mkdir -p out && cp a b", "echo cat > x"):
        assert not _fires(tmp_path, "Bash", command), command


def test_the_read_tool_is_left_alone(tmp_path):
    assert not _fires(tmp_path, "Read", "", response="")
