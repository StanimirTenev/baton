"""The install's own ID: shown above the board at start and after /clear, the same every time."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "baton_session_start.py"
FORMAT = re.compile(r"🪪 This Baton's ID: BTN-[A-Z2-7]{4}-[A-Z2-7]{4}-[A-Z2-7]{4}")


def _run(tmp_path, source="startup", path=None):
    tasks = tmp_path / "tasks" / "t1"
    tasks.mkdir(parents=True, exist_ok=True)
    (tasks / "DNEVNIK.md").write_text('---\nstate: active\nturn: "us"\nnext: "x"\n---\n', "utf-8")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BATON_", "CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(HOME=str(tmp_path / "home"), BATON_HOME=str(tmp_path / "tasks"),
               BATON_SESSION_STATE=str(tmp_path / "s.json"), BATON_LOGBOOK="DNEVNIK.md")
    if path is not None:
        env["PATH"] = path
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"source": source}).encode(),
                         capture_output=True, env=env, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_id_opens_the_board_and_the_line_and_stays(tmp_path):
    first = _run(tmp_path)
    ctx = first["hookSpecificOutput"]["additionalContext"]
    m = FORMAT.search(ctx)
    assert m, ctx[:300]
    assert ctx.index(m.group()) < ctx.index("The human has not seen this board")
    assert first["systemMessage"].startswith(m.group())
    again = _run(tmp_path, source="clear")
    assert m.group() in again["hookSpecificOutput"]["additionalContext"], "a new ID after /clear"
    assert again["systemMessage"].startswith(m.group())
    key = tmp_path / "home" / ".claude" / "baton" / "identity" / "baton_ed25519"
    assert key.is_file() and oct(key.stat().st_mode & 0o777) == "0o600"


def test_a_private_key_without_its_public_half_is_never_replaced(tmp_path):
    key = tmp_path / "home" / ".claude" / "baton" / "identity" / "baton_ed25519"
    key.parent.mkdir(parents=True)
    key.write_text("precious")
    out = _run(tmp_path)
    assert key.read_text() == "precious"
    assert "Baton's ID" not in out["hookSpecificOutput"]["additionalContext"]
    assert "Baton" in out["systemMessage"], "the board line was lost with the ID"


def test_without_ssh_keygen_the_board_still_comes(tmp_path):
    empty = tmp_path / "nobin"
    empty.mkdir()
    out = _run(tmp_path, path=str(empty))
    assert "Baton's ID" not in out["hookSpecificOutput"]["additionalContext"]
    assert "The human has not seen this board" in out["hookSpecificOutput"]["additionalContext"]


def test_two_installs_get_two_ids(tmp_path):
    a = FORMAT.search(_run(tmp_path / "a")["systemMessage"]).group()
    b = FORMAT.search(_run(tmp_path / "b")["systemMessage"]).group()
    assert a != b
