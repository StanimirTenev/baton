"""ZA-OPRAVYANE row 123: what went outside the machine is noted by itself.

A push, a pull request or issue, a release, an upload, a message sent through an MCP tool: one
line in the task's `.baton-outside.md` (a dotfile: Stop does not count it as work), and a note to
the agent to carry it into the next entry. Never a secret. Through the hook, JSON on stdin.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"


def _env(tmp_path):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR", "BATON_HOME"))}
    env.update(BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               HOME=str(tmp_path / "home"), BATON_STATE_DIR=str(tmp_path / "state"))
    return env


def _batch(tmp_path, calls, cwd="/"):
    out = subprocess.run([sys.executable, str(HOOKS / "baton_batch.py")], capture_output=True,
                         text=True, env=_env(tmp_path),
                         input=json.dumps({"session_id": "s", "cwd": cwd, "tool_calls": calls}))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def _bash(command, response="ok"):
    return {"tool_name": "Bash", "tool_input": {"command": command}, "tool_response": response}


def _tasks(tmp_path):
    root = tmp_path / "tasks"
    for name, code in (("scanner", f"code: {tmp_path / 'dev' / 'scanner'}@main\n"), ("mail", "")):
        (root / name).mkdir(parents=True)
        (root / name / "LOGBOOK.md").write_text(f"---\nstate: active\n{code}---\n\n## 2026-11-01 10:00 — x\n",
                                               "utf-8")
    (tmp_path / "dev" / "scanner").mkdir(parents=True)
    return root


def test_a_push_from_the_task_s_repository_is_noted_in_that_task(tmp_path):
    root = _tasks(tmp_path)
    out = _batch(tmp_path, [_bash("git add -A && git commit -qm x && git push origin main")],
                 cwd=str(tmp_path / "dev" / "scanner"))
    note = (root / "scanner" / ".baton-outside.md").read_text("utf-8")
    assert note.startswith("- done outside: git push origin main, ") and note.count("\n") == 1, note
    assert "scanner/.baton-outside.md" in out["hookSpecificOutput"]["additionalContext"]


def test_each_kind_of_outward_action_is_noted(tmp_path):
    root = _tasks(tmp_path)
    _batch(tmp_path, [
        _bash(f"cd {root / 'mail'} && gh pr create --title t --body 'a long body that says what it does'"),
        _bash("gh issue comment 12 --body hi; gh release create v1.2.0 dist/*"),
        _bash("python3 -m twine upload dist/* && npm publish"),
        {"tool_name": "mcp__claude_ai_Gmail__send_message",
         "tool_input": {"to": ["a@example.invalid"], "subject": "secret plans", "body": "the body"},
         "tool_response": "{}"}], cwd="/")
    said = (root / "mail" / ".baton-outside.md").read_text("utf-8")
    assert "gh pr create" in said and "a long body" not in said
    rest = (root / ".baton-outside.md").read_text("utf-8")
    for what in ("gh issue comment 12", "gh release create v1.2.0", "twine upload", "npm publish",
                 "send_message to a@example.invalid"):
        assert what in rest, (what, rest)
    assert "secret plans" not in rest and "the body" not in rest


def test_no_secret_is_written(tmp_path):
    root = _tasks(tmp_path)
    _batch(tmp_path, [_bash("twine upload -u __token__ -p pypi-AgEIcHlwaS5vcmc dist/* && "
                            "git push " + "https" + ":" + "//me:ghp_abcdefghijklmnopqrstuvwxyz0123@git.invalid/x/y.git "
                            "&& npm publish --otp=123456 --token=npm_secret")])
    said = (root / ".baton-outside.md").read_text("utf-8")
    for secret in ("pypi-AgEI", "__token__", "ghp_abc", "me:", "123456", "npm_secret"):
        assert secret not in said, (secret, said)


def test_what_is_only_written_about_is_not_an_action(tmp_path):
    root = _tasks(tmp_path)
    out = _batch(tmp_path, [_bash("cat > entry.md <<'EOF'\ngit push went fine\ngh pr create next\nEOF"),
                            _bash("echo 'then git push' >> notes.txt"), _bash("gh pr view 3; gh release list"),
                            {"tool_name": "mcp__claude_ai_Gmail__create_draft", "tool_input": {"to": "x"}}])
    assert out == {} and not list(root.rglob(".baton-outside.md")), out


def test_the_note_is_not_counted_as_unrecorded_work(tmp_path):
    root = _tasks(tmp_path)
    _batch(tmp_path, [_bash("git push")], cwd=str(tmp_path / "dev" / "scanner"))
    note = root / "scanner" / ".baton-outside.md"
    t = time.time() - 600
    os.utime(note, (t, t))
    os.utime(root / "scanner" / "LOGBOOK.md", (t - 3600, t - 3600))
    transcript = tmp_path / "t.jsonl"
    started = datetime.now(timezone.utc) - timedelta(minutes=30)
    transcript.write_text(json.dumps({"type": "user", "timestamp": started.isoformat()}) + "\n", "utf-8")
    out = subprocess.run([sys.executable, str(HOOKS / "baton_stop.py")], capture_output=True, text=True,
                         env=_env(tmp_path), input=json.dumps({"session_id": "s", "transcript_path": str(transcript)}))
    assert "newer than their" not in out.stdout, out.stdout
