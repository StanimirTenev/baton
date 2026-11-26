"""Moving the agent's world to a new computer: inventory, restore, verify (tools/baton_move.py).

From the real move plan (zadachi/prehvarliane, 2026-10-13 and 2026-11-26): the memory folder is
named after the home path, so a new user name loses it; crontab does not travel with files; a
key that cannot be recreated must be carried by hand and checked by hash, never shown. And the
old disk is wiped only after a check says everything arrived -- so the check has to fail when
one file is different, or it licenses losing it.

Everything runs in a fake HOME under tmp_path, with `crontab` and `systemctl` stubbed on PATH:
the real user's would otherwise be read.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import child_env

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "baton_move.py"
KEY = "-----BEGIN OPENSSH PRIVATE KEY----- test-key-body-7f3a9c -----END-----\n"
CRON = "7 9 24 10 * echo borsa\n"


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout.strip()


def _encode(home: Path) -> str:
    return "".join(c if c.isalnum() and c.isascii() else "-" for c in str(home))


@pytest.fixture
def world(tmp_path):
    """An old home: two task folders, a logbook whose `code:` names a repo with a local bare
    remote, Claude's instructions and memory, a key, a note the logbook mentions."""
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in (("crontab", f'[ "$1" = "-l" ] && printf %s "{CRON.strip()}" && echo'),
                       ("systemctl", "exit 0")):
        (stubs / name).write_text(f"#!/bin/sh\n{body}\n", "utf-8")
        (stubs / name).chmod(0o755)
    old = tmp_path / "home" / "olduser"
    tasks = old / "tasks"
    (tasks / "alpha").mkdir(parents=True)
    (tasks / "beta" / "node_modules" / "x").mkdir(parents=True)
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    repo = old / "dev" / "tool"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.py").write_text("print(1)\n", "utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "one")
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "main")
    (old / "notes").mkdir()
    (old / "notes" / "plan.txt").write_text("outside the tasks folder\n", "utf-8")
    (tasks / "alpha" / "LOGBOOK.md").write_text(
        "---\nstate: open\ncode: ~/dev/tool@main\n---\n# alpha\n\n## 2026-11-26 10:00 — x\n"
        "See ~/notes/plan.txt for the plan.\n", "utf-8")
    (tasks / "alpha" / "data.csv").write_text("a,b\n1,2\n", "utf-8")
    (tasks / "alpha" / "live.log").write_text("changes on its own\n", "utf-8")
    (tasks / "alpha" / ".batonignore").write_text("live.log\n", "utf-8")
    (tasks / "beta" / "LOGBOOK.md").write_text("---\nstate: open\n---\n# beta\n", "utf-8")
    (tasks / "beta" / "node_modules" / "x" / "big.js").write_text("x\n", "utf-8")
    memory = old / ".claude" / "projects" / _encode(old) / "memory"
    memory.mkdir(parents=True)
    (memory / "MEMORY.md").write_text("# Memory Index\n- [alpha](a.md)\n", "utf-8")
    (old / ".claude" / "CLAUDE.md").write_text("# rules\n", "utf-8")
    skill = old / ".claude" / "skills" / "s"
    (skill / "__pycache__").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: s\n---\n", "utf-8")
    (skill / "__pycache__" / "x.pyc").write_bytes(b"made anew")
    (tasks / "alpha" / "latest").symlink_to("data.csv")
    (old / ".ssh").mkdir()
    (old / ".ssh" / "id_ed25519").write_text(KEY, "utf-8")
    (old / ".ssh" / "id_ed25519").chmod(0o600)
    return {"tmp": tmp_path, "old": old, "tasks": tasks, "repo": repo, "bare": bare,
            "memory": memory, "path": f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}"}


def _run(w, home, *args):
    env = child_env(HOME=str(home), BATON_HOME=str(home / "tasks"), BATON_LOGBOOK="LOGBOOK.md",
                    PATH=w["path"])
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                          env=env, cwd=str(w["tmp"]))


def _inventory(w, *extra):
    out = w["tmp"] / "manifest.json"
    done = _run(w, w["old"], "inventory", "--out", str(out), *extra)
    assert done.returncode == 0, done.stderr
    return out, done


def _moved(w):
    """Inventory, then run the two rsync lines it prints -- the copy a person makes -- with
    NEWHOST:baton-move/ a local folder, and a new home for another user."""
    if not shutil.which("rsync"):
        pytest.skip("no rsync on this machine: the printed copy line cannot be run")
    manifest, done = _inventory(w)
    copy = w["tmp"] / "copy"
    copy.mkdir()
    lines = [ln.strip() for ln in done.stdout.splitlines() if ln.strip().startswith("rsync ")]
    assert len(lines) == 2, done.stdout
    for line in lines:
        cmd = line.replace(" -aHAX ", " -aH ").replace("NEWHOST:baton-move/", f"{copy}/")
        ran = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                             env=child_env(HOME=str(w["old"])))
        assert ran.returncode == 0, ran.stderr
    new = w["tmp"] / "home" / "newuser"
    new.mkdir(parents=True)
    return manifest, copy, new


def _restored(w):
    manifest, copy, new = _moved(w)
    done = _run(w, new, "restore", "--manifest", str(manifest), "--from", str(copy))
    assert done.returncode == 0, done.stdout + done.stderr
    _git(w["tmp"], "clone", "-q", str(w["bare"]), str(new / "dev" / "tool"))
    return manifest, new, done


def test_inventory_lists_everything_and_never_the_key_content(world):
    manifest, done = _inventory(world)
    text = manifest.read_text("utf-8")
    man = json.loads(text)
    paths = {e["path"] for e in man["files"]}
    assert {"tasks/alpha/LOGBOOK.md", "tasks/alpha/data.csv", "tasks/beta/LOGBOOK.md",
            ".claude/CLAUDE.md", f".claude/projects/{_encode(world['old'])}/memory/MEMORY.md"} <= paths
    assert all(len(e["sha256"]) == 64 for e in man["files"])
    # .batonignore and made-anew folders: not listed, but counted where a reader sees it.
    assert "tasks/alpha/live.log" not in paths and not any("node_modules" in p for p in paths)
    assert not any("__pycache__" in p for p in paths)       # rsync leaves it out everywhere
    assert ".claude/skills/s/SKILL.md" in paths
    assert man["tasks"]["skipped"]["files"] == 2
    assert any("node_modules" in line for line in man["not_covered"])
    repo = man["repos"][0]
    assert repo["path"] == "dev/tool" and repo["remote"] == str(world["bare"])
    assert repo["head"] == _git(world["repo"], "rev-parse", "HEAD")
    assert repo["dirty"] == 0 and repo["unpushed"] == 0
    assert [m["path"] for m in man["mentioned"]] == ["notes/plan.txt"]
    assert man["mentioned"][0]["status"] == "mentioned, not included"
    assert man["crontab"].strip() == CRON.strip()
    assert man["home"] == str(world["old"])
    # The key: its name and hash, never its content -- in the manifest or on the screen.
    import hashlib
    key = next(s for s in man["secrets"] if s["path"] == ".ssh/id_ed25519")
    assert key["sha256"] == hashlib.sha256(KEY.encode()).hexdigest()
    assert "test-key-body-7f3a9c" not in text and "test-key-body-7f3a9c" not in done.stdout
    assert ".ssh/id_ed25519" in done.stdout
    assert "rsync -aHAX -R" in done.stdout and "NOT covered" in done.stdout


def test_a_dirty_repo_and_a_remote_with_a_login_are_said_not_stored(world):
    (world["repo"] / "b.py").write_text("new\n", "utf-8")
    _git(world["repo"], "remote", "set-url", "origin", "ssh://git:hunter2@gitbox/tool.git")
    manifest, done = _inventory(world)
    repo = json.loads(manifest.read_text("utf-8"))["repos"][0]
    assert repo["dirty"] == 1 and "1 uncommitted" in done.stdout
    assert "hunter2" not in manifest.read_text("utf-8") and repo["remote"] == "ssh://git@gitbox/tool.git"


def test_restore_into_another_user_renames_memory_and_verify_is_clean(world):
    manifest, new, done = _restored(world)
    assert (new / ".claude" / "projects" / _encode(new) / "memory" / "MEMORY.md").is_file()
    assert not (new / ".claude" / "projects" / _encode(world["old"])).exists()
    # Carried by the rsync line though not in the manifest: placed, not left in the copy.
    assert (new / "tasks" / "alpha" / "live.log").is_file()
    assert os.readlink(new / "tasks" / "alpha" / "latest") == "data.csv"
    assert "not in the manifest" in done.stdout
    assert "memory folder" in done.stdout and _encode(new) in done.stdout
    assert CRON.strip() in done.stdout and "crontab crontab.txt" in done.stdout
    assert oct((new / ".ssh" / "id_ed25519").stat().st_mode & 0o777) == "0o600"
    check = _run(world, new, "verify", "--manifest", str(manifest))
    assert check.returncode == 0, check.stdout
    assert "✗" not in check.stdout and "memory folder" in check.stdout
    assert "test-key-body-7f3a9c" not in check.stdout


def test_a_tampered_file_fails_verify_and_is_named(world):
    manifest, new, _ = _restored(world)
    (new / "tasks" / "alpha" / "data.csv").write_text("a,b\n1,3\n", "utf-8")   # same size
    check = _run(world, new, "verify", "--manifest", str(manifest))
    assert check.returncode == 1
    assert "different: tasks/alpha/data.csv" in check.stdout
    assert "Do not wipe the old disk" in check.stdout


def test_a_missing_key_fails_verify_and_is_named_not_shown(world):
    manifest, new, _ = _restored(world)
    (new / ".ssh" / "id_ed25519").unlink()
    check = _run(world, new, "verify", "--manifest", str(manifest))
    assert check.returncode == 1
    assert "missing: .ssh/id_ed25519" in check.stdout
    assert "test-key-body-7f3a9c" not in check.stdout


def test_a_repo_at_another_head_fails_verify(world):
    manifest, new, _ = _restored(world)
    clone = new / "dev" / "tool"
    (clone / "c.py").write_text("x\n", "utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "two")
    check = _run(world, new, "verify", "--manifest", str(manifest))
    assert check.returncode == 1 and "dev/tool: HEAD" in check.stdout


def test_restore_never_overwrites_a_different_file_without_force(world):
    manifest, copy, new = _moved(world)
    mine = new / "tasks" / "alpha" / "data.csv"
    mine.parent.mkdir(parents=True)
    mine.write_text("the new machine's own\n", "utf-8")
    done = _run(world, new, "restore", "--manifest", str(manifest), "--from", str(copy))
    assert done.returncode == 1 and "CONFLICT" in done.stdout and "tasks/alpha/data.csv" in done.stdout
    assert mine.read_text("utf-8") == "the new machine's own\n"
    forced = _run(world, new, "restore", "--manifest", str(manifest), "--from", str(copy), "--force")
    assert forced.returncode == 0, forced.stdout
    assert mine.read_text("utf-8") == "a,b\n1,2\n"


def test_dry_run_writes_nothing_and_prints_the_clone(world):
    manifest, copy, new = _moved(world)
    done = _run(world, new, "restore", "--manifest", str(manifest), "--from", str(copy), "--dry-run")
    assert done.returncode == 0 and "would place" in done.stdout
    assert f"git clone {world['bare']}" in done.stdout
    assert list(new.iterdir()) == []


def test_a_missing_tasks_folder_is_a_loud_failure(world, tmp_path):
    empty = tmp_path / "home" / "nobody"
    empty.mkdir(parents=True)
    done = _run(world, empty, "inventory", "--out", str(tmp_path / "m.json"))
    assert done.returncode == 2 and "does not exist" in done.stderr
