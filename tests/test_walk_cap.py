"""ZA-OPRAVYANE row 35 (2026-10-21): SessionStart and Stop took ~19 s against the 20 s hook
limit on a machine whose task root holds ~139,000 files -- 70,000 of them in one folder of
downloaded filings, 50,000 in one of cloned repositories. Every one was stat-ed on every run,
and a `.batonignore` glob such as `build/*` was checked file by file, so it saved nothing.

Two things since: a `.batonignore` line ending in `/` names a FOLDER, and the walk does not go
into it (in the task folder, or at the task root as `<task>/<path>/`); and a folder holding more
than WALK_CAP work files is not read to the end -- which the board and Stop SAY, never a
silent pass.
"""
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
spec = importlib.util.spec_from_file_location("bs_walk", HOOKS / "baton_stop.py")
bs = importlib.util.module_from_spec(spec)
sys.modules["bs_walk"] = bs
spec.loader.exec_module(bs)


def _task(root: Path, name="alpha", data="data/raw"):
    """A recorded task whose only newer file sits under `data`."""
    folder = root / name
    (folder / data).mkdir(parents=True)
    now = time.time()
    log = folder / "LOGBOOK.md"
    log.write_text("---\nsastoyanie: aktivna\n---\n\n## 2026-01-01 00:00 — x\n\ny\n", "utf-8")
    os.utime(log, (now - 3600, now - 3600))
    f = folder / data / "chunk.gz"
    f.write_text("x", "utf-8")
    os.utime(f, (now - 600, now - 600))
    return folder


def test_without_a_line_the_data_file_is_reported(tmp_path):
    _task(tmp_path)
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == ["alpha (newest: " + os.path.join("data", "raw", "chunk.gz") + ")"]


def test_a_dir_line_in_the_task_folder_skips_the_subtree(tmp_path):
    folder = _task(tmp_path)
    (folder / ".batonignore").write_text("data/\n", "utf-8")
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []


def test_a_dir_line_names_a_folder_at_any_depth(tmp_path):
    folder = _task(tmp_path, data="krag3/kesh")
    (folder / ".batonignore").write_text("kesh/\n", "utf-8")
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []


def test_the_walk_does_not_enter_a_named_folder(tmp_path, monkeypatch):
    """The point of the line is the time: files under it are never even listed."""
    folder = _task(tmp_path)
    (folder / ".batonignore").write_text("data/\n", "utf-8")
    seen = []
    real = os.walk

    def spy(top, *a, **k):
        for dirpath, dirnames, filenames in real(top, *a, **k):
            seen.append(os.path.relpath(dirpath, top))
            yield dirpath, dirnames, filenames
    monkeypatch.setattr(bs.os, "walk", spy)
    bs.newest_work(folder, "LOGBOOK.md")
    assert seen == ["."]


def test_a_path_line_at_the_task_root_skips_the_subtree(tmp_path):
    _task(tmp_path)
    (tmp_path / ".batonignore").write_text("alpha/data/raw/\n", "utf-8")
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []


def test_a_path_line_at_the_root_does_not_make_the_task_a_non_task(tmp_path):
    _task(tmp_path)
    (tmp_path / ".batonignore").write_text("alpha/data/\n", "utf-8")
    assert [p.name for p in bs._ss().task_folders(tmp_path)] == ["alpha"]


def test_a_root_line_for_another_task_does_not_apply(tmp_path):
    _task(tmp_path)
    (tmp_path / ".batonignore").write_text("beta/data/\n", "utf-8")
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") != []


def test_a_dir_line_is_honoured_file_by_file_too(tmp_path):
    """The corpus tool asks `is_ignored` about single files; it must agree with the walk."""
    assert bs.is_ignored(os.path.join("data", "raw", "chunk.gz"), "chunk.gz", ["data/"])
    assert bs.is_ignored(os.path.join("a", "kesh", "x.parquet"), "x.parquet", ["kesh/"])
    assert not bs.is_ignored(os.path.join("datas", "x.gz"), "x.gz", ["data/"])
    assert not bs.is_ignored("data", "data", ["data/"])      # a FILE named data is not the folder


def test_touched_since_skips_the_same_folders(tmp_path):
    folder = _task(tmp_path)
    (folder / ".batonignore").write_text("data/\n", "utf-8")
    assert bs.touched_since(folder, "LOGBOOK.md", 0) == []


# --- the cap ----------------------------------------------------------------------------

def _many(root: Path, n: int):
    """A recorded task with `n` old work files and nothing newer than its logbook."""
    folder = root / "big"
    (folder / "files").mkdir(parents=True)
    old = time.time() - 7200
    for i in range(n):
        p = folder / "files" / f"{i}.txt"
        p.write_text("", "utf-8")
        os.utime(p, (old, old))
    log = folder / "LOGBOOK.md"
    log.write_text("---\nsastoyanie: aktivna\n---\n\n## 2026-01-01 00:00 — x\n\ny\n", "utf-8")
    os.utime(log, (time.time() - 3600, time.time() - 3600))
    return folder


def test_a_folder_over_the_cap_is_named_as_not_read_to_the_end(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "WALK_CAP", 5)
    _many(tmp_path, 6)
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []
    assert bs.TRUNCATED == ["big"]


def test_a_folder_at_the_cap_is_read_to_the_end(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "WALK_CAP", 5)
    _many(tmp_path, 5)
    bs.unrecorded(tmp_path, "LOGBOOK.md")
    assert bs.TRUNCATED == []


def test_skipped_folders_do_not_count_toward_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "WALK_CAP", 5)
    folder = _many(tmp_path, 6)
    (folder / ".batonignore").write_text("files/\n", "utf-8")
    bs.unrecorded(tmp_path, "LOGBOOK.md")
    assert bs.TRUNCATED == []


def _env(tmp_path):
    env = dict(os.environ, BATON_HOME=str(tmp_path / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
               BATON_STATE_DIR=str(tmp_path / "state"), BATON_BODY_STATE=str(tmp_path / "b.json"),
               HOME=str(tmp_path / "home"))
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    return env


def test_both_hooks_say_so_through_their_entry_points(tmp_path):
    """The way the harness runs them, with WALK_CAP + 1 real files: never a silent pass."""
    _many(tmp_path / "tasks", bs.WALK_CAP + 1)
    env = _env(tmp_path)
    out = subprocess.run([sys.executable, str(HOOKS / "baton_stop.py")],
                         input=json.dumps({"session_id": "s"}), capture_output=True,
                         text=True, env=env)
    assert out.returncode == 0, out.stderr
    stop = json.loads(out.stdout)
    assert stop.get("decision") != "block"                 # uncertainty is not a hand-back
    assert "not read to the end" in stop.get("systemMessage", "") and "big" in stop["systemMessage"]
    again = subprocess.run([sys.executable, str(HOOKS / "baton_stop.py")],
                           input=json.dumps({"session_id": "s"}), capture_output=True,
                           text=True, env=env)
    assert again.stdout.strip() == ""                       # said once per session
    start = subprocess.run([sys.executable, str(HOOKS / "baton_session_start.py")], input="{}",
                           capture_output=True, text=True, env=env)
    assert start.returncode == 0, start.stderr
    assert "not read to the end" in start.stdout and "big" in start.stdout
