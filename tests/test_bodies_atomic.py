"""`baton.bodies.json`, Stop's memory of each logbook's body, is replaced whole, never written in
place (ZA-OPRAVYANE row 170 b).

It was `path.write_text(...)` at the end of `unrecorded`: the file is truncated, then filled. A Stop
killed in between (its 20 s timeout, a closed terminal), or two Stops of one host at once, leave it
empty or half-written; the next Stop cannot parse it, starts over from file times and says the
memory was lost (FORGOT). Now the text goes to a temporary file of this process beside it, and
os.replace swaps it in: a reader sees the old memory or the new one.
"""
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_stop.py"
spec = importlib.util.spec_from_file_location("bs_bodies", HOOK)
bs = importlib.util.module_from_spec(spec)
sys.modules["bs_bodies"] = bs
spec.loader.exec_module(bs)

BOOK = "---\nstate: active\ndone_when: \"x\"\n---\n\n## 2026-11-20 08:25 — запис\n\nтяло\n"


def _tasks(tmp_path) -> Path:
    folder = tmp_path / "tasks" / "a"
    folder.mkdir(parents=True)
    (folder / "LOGBOOK.md").write_text(BOOK, "utf-8")
    old = time.time() - 7200
    (folder / "notes.md").write_text("n", "utf-8")
    os.utime(folder / "notes.md", (old, old))
    return folder.parent


def _memory(tmp_path) -> Path:
    path = tmp_path / "bodies.json"
    path.write_text(json.dumps({"/elsewhere/kept": ["0" * 40, 1.0, []]}), "utf-8")
    return path


def test_a_crash_while_writing_leaves_the_old_memory_whole(tmp_path, monkeypatch):
    """The write dies half way: what is on disk at `path` still parses, as it was."""
    tasks, path = _tasks(tmp_path), _memory(tmp_path)
    before = path.read_text("utf-8")
    monkeypatch.setenv("BATON_BODY_STATE", str(path))
    real = Path.write_text

    def dies_half_way(self, data, *a, **kw):
        real(self, data[: len(data) // 2], *a, **kw)
        raise OSError("killed")
    monkeypatch.setattr(Path, "write_text", dies_half_way)
    bs.unrecorded(tasks, "LOGBOOK.md")
    monkeypatch.setattr(Path, "write_text", real)
    assert path.read_text("utf-8") == before
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".bodies")] == [], \
        "the temporary file is not left behind"


def test_a_replace_windows_refuses_for_a_moment_is_retried(tmp_path, monkeypatch):
    tasks, path = _tasks(tmp_path), _memory(tmp_path)
    monkeypatch.setenv("BATON_BODY_STATE", str(path))
    real, calls = os.replace, []

    def busy_once(src, dst):
        calls.append(dst)
        if len(calls) == 1:
            raise PermissionError("a reader has it open")
        real(src, dst)
    monkeypatch.setattr(bs.os, "replace", busy_once)
    bs.unrecorded(tasks, "LOGBOOK.md")
    assert len(calls) == 2
    assert str(tasks / "a") in json.loads(path.read_text("utf-8"))


def test_the_hook_replaces_the_memory_file_and_does_not_write_into_it(tmp_path):
    """As the harness runs Stop: the file after it is another file (a new inode), whole, holding
    the old key and the new logbook. Written in place, the inode would stay the same."""
    tasks, path = _tasks(tmp_path), _memory(tmp_path)
    inode = path.stat().st_ino
    keep = tmp_path / "hold"
    os.link(path, keep)            # the old file stays alive, so its inode is not reused
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "SYSTEMROOT", "LANG")}
    env.update(BATON_HOME=str(tasks), BATON_LOGBOOK="LOGBOOK.md",
               BATON_STATE_DIR=str(tmp_path / "state"), BATON_BODY_STATE=str(path),
               BATON_LESSONS_STATE=str(tmp_path / "l.json"),
               BATON_SESSION_STATE=str(tmp_path / "s.json"))
    out = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, env=env,
                         input=json.dumps({"session_id": "s"}))
    assert out.returncode == 0, out.stderr
    memory = json.loads(path.read_text("utf-8"))
    assert "/elsewhere/kept" in memory and str(tasks / "a") in memory
    assert path.stat().st_ino != inode, "written in place"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".bodies")] == []
