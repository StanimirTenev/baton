"""A record that names the code it rests on, and says when that code has moved.

From a product note of 2026-09-26 asking for records "свързан с действителните файлове и
резултати" and "сигнал за остарели записи". Everything else that note proposed already
exists; this was the one genuinely new thing in it.

It is not theory. Twice on 2026-09-26 a memory file in this project claimed v2.8.0 and
132 tests while the code stood at v2.13.1 and 194 — a record still perfectly readable,
still quoted at the top of every session, and describing a tree that had moved five
releases past it. Nothing about it looked wrong.

The file-mtime check catches a folder whose files are newer than its logbook. This
catches the other thing: the logbook is fine, and the *code it describes* has moved.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_session_start.py"
spec = importlib.util.spec_from_file_location("bss_kod", HOOK)
bss = importlib.util.module_from_spec(spec)
sys.modules["bss_kod"] = bss
spec.loader.exec_module(bss)


def _repo(path: Path, commits: int = 1) -> str:
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(a, cwd=path, capture_output=True, text=True, check=True)
    run("git", "init", "-q", "-b", "main")
    run("git", "config", "user.email", "t@t")
    run("git", "config", "user.name", "t")
    for i in range(commits):
        (path / f"f{i}.txt").write_text(str(i), encoding="utf-8")
        run("git", "add", "-A")
        run("git", "commit", "-qm", f"c{i}")
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path,
                          capture_output=True, text=True).stdout.strip()


def test_a_record_pinned_to_the_current_commit_says_nothing(tmp_path):
    repo = tmp_path / "repo"
    head = _repo(repo, 1)
    assert bss.kod_drift({"kod": f"{repo}@{head}"}) is None


def test_a_record_whose_code_has_moved_says_how_far(tmp_path):
    repo = tmp_path / "repo"
    old = _repo(repo, 1)
    _repo_more = _repo(repo, 0)  # no-op, keep the helper honest
    for i in range(3):
        (repo / f"later{i}.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", f"later{i}"], cwd=repo, check=True,
                       capture_output=True)
    note = bss.kod_drift({"kod": f"{repo}@{old}"})
    assert note and "3" in note, note
    assert old[:7] in note


def test_a_short_sha_and_a_tag_both_work(tmp_path):
    repo = tmp_path / "repo"
    head = _repo(repo, 2)
    subprocess.run(["git", "tag", "v1"], cwd=repo, check=True, capture_output=True)
    assert bss.kod_drift({"kod": f"{repo}@{head[:7]}"}) is None
    assert bss.kod_drift({"kod": f"{repo}@v1"}) is None


def test_a_reference_that_cannot_be_resolved_is_named_not_ignored(tmp_path):
    """The whole doctrine: not knowing is reported, never read as agreement."""
    repo = tmp_path / "repo"
    _repo(repo, 1)
    note = bss.kod_drift({"kod": f"{repo}@deadbeef"})
    assert note and ("deadbeef" in note or "не се намира" in note), note

    missing = bss.kod_drift({"kod": f"{tmp_path / 'nowhere'}@abc1234"})
    assert missing, "a path that is not a repository must be said, not skipped"
    # ⚠️ Mutation caught this: asserting only that *something* came back let the
    # repository check be deleted, because the git call then failed and produced the
    # "ref not found" line instead. Two different facts -- no repository here, and no
    # such ref in this repository -- and a reader acts differently on each.
    assert "не е хранилище" in missing, (
        f"a missing repository must say so, not be reported as a missing ref: {missing}")


def test_a_malformed_field_is_named(tmp_path):
    note = bss.kod_drift({"kod": "no-at-sign-here"})
    assert note and "@" in note, note


def test_no_field_means_no_opinion(tmp_path):
    assert bss.kod_drift({}) is None
    assert bss.kod_drift({"kod": ""}) is None


def test_the_drift_reaches_the_report_not_only_the_function(tmp_path, monkeypatch):
    """Three outputs leave this project and a field added to one reaches nobody.

    That cost a whole report on 2026-09-21 and a test-code marker on 2026-09-26, so the
    check walks the real entry point.
    """
    import json
    repo = tmp_path / "repo"
    old = _repo(repo, 1)
    for i in range(2):
        (repo / f"n{i}.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", f"n{i}"], cwd=repo, check=True,
                       capture_output=True)
    tasks = tmp_path / "tasks" / "zadacha"
    tasks.mkdir(parents=True)
    (tasks / "LOGBOOK.md").write_text(
        f'---\nsastoyanie: aktivna\nna_hod: nie\nsledvashto: "x"\nprioritet: visok\n'
        f'kod: {repo}@{old}\n---\n\n## 2026-09-01 10:00 — a\n\ntext\n', encoding="utf-8")
    monkeypatch.setenv("BATON_HOME", str(tmp_path / "tasks"))
    monkeypatch.setenv("BATON_LOGBOOK", "LOGBOOK.md")
    out = subprocess.run([sys.executable, str(HOOK)], input="{}",
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    message = json.loads(out.stdout).get("systemMessage", "")
    assert "zadacha" in message and "2" in message and "kod:" in message, message[-400:]


def test_a_sha_ref_is_not_printed_twice(tmp_path):
    """"след `7374660` (7374660)" -- naming the ref and the commit it resolves to reads
    as a stutter when they are the same thing. A tag still gets both."""
    repo = tmp_path / "repo"
    old = _repo(repo, 1)
    (repo / "x.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=repo, check=True, capture_output=True)

    by_sha = bss.kod_drift({"kod": f"{repo}@{old[:7]}"})
    assert by_sha.count(old[:7]) == 1, by_sha

    subprocess.run(["git", "tag", "v9", old], cwd=repo, check=True, capture_output=True)
    by_tag = bss.kod_drift({"kod": f"{repo}@v9"})
    assert "v9" in by_tag, by_tag
