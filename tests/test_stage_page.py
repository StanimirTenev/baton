"""ZA-OPRAVYANE row 117: the page of an entry, made by tools/baton_entry.py right after the write.

`.baton-etap.html` in the task folder: the header (state, next, done_when), the entry just
written, the work files saved since the logbook was last written. One overwritten file whose
leading dot keeps Stop from counting it. `--open` opens it on this machine; with no display
(SSH, or Linux with neither DISPLAY nor WAYLAND_DISPLAY) it says the path and opens nothing.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

from conftest import child_env

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "baton_entry.py"
STOP = ROOT / "hooks" / "baton_stop.py"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


be = _load(TOOL, "be_row117")


def _task(tmp_path):
    folder = tmp_path / "task"
    folder.mkdir()
    book = folder / "LOGBOOK.md"
    book.write_text('---\nstate: active\nsledvashto: "send <the> plan"\ndone_when: "a & b"\n---\n\n'
                    "## 2026-11-01 10:00 — old\n\nold body\n", "utf-8")
    old = time.time() - 600
    os.utime(book, (old, old))
    (folder / "before.txt").write_text("x", "utf-8")
    os.utime(folder / "before.txt", (old - 60, old - 60))
    (folder / "sub").mkdir()
    (folder / "sub" / "after.md").write_text("y", "utf-8")
    return folder, book


def test_the_page_holds_the_header_the_entry_and_the_files_saved_since(tmp_path, capsys):
    folder, book = _task(tmp_path)
    be.write_entry(book, "the <b>body</b> & more", title="plan v2")
    out = capsys.readouterr().out
    page = folder / ".baton-etap.html"
    assert f"HTML: {page}" in out, out
    text = page.read_text("utf-8")
    assert "<strong>state:</strong> active" in text
    assert "send &lt;the&gt; plan" in text, "next, read through the hook's synonyms, escaped"
    assert "a &amp; b" in text
    assert "the &lt;b&gt;body&lt;/b&gt; &amp; more" in text and "plan v2" in text
    assert "<li>sub/after.md</li>" in text
    assert "before.txt" not in text, "saved before the last write: not this entry's work"
    assert "LOGBOOK.md</li>" not in text and "old body" not in text


def test_the_page_is_overwritten_and_never_counted_as_work(tmp_path, capsys):
    folder, book = _task(tmp_path)
    be.write_entry(book, "first", title="one")
    be.write_entry(book, "second", title="two")
    text = (folder / ".baton-etap.html").read_text("utf-8")
    assert "second" in text and "first" not in text
    assert [p.name for p in folder.glob(".baton-etap*")] == [".baton-etap.html"]
    stop = _load(STOP, "stop_row117")
    assert ".baton-etap.html" not in [rel for rel, _ in stop.work_files(folder, "LOGBOOK.md")]


def test_a_page_that_cannot_be_made_does_not_fail_the_write(tmp_path, capsys, monkeypatch):
    folder, book = _task(tmp_path)
    monkeypatch.setattr(be, "_board", lambda: (_ for _ in ()).throw(OSError("no board")))
    be.write_entry(book, "kept", title="still written")
    assert "still written" in book.read_text("utf-8")
    assert "HTML: not made (no board)" in capsys.readouterr().out


def _open(book, tmp_path, **env):
    opened = tmp_path / "opened.txt"
    browser = tmp_path / "browser.sh"
    browser.write_text(f'#!/bin/sh\necho "$1" > "{opened}"\n', "utf-8")
    browser.chmod(0o755)
    run = subprocess.run([sys.executable, str(TOOL), str(book), "--open"], capture_output=True,
                         text=True, env=child_env(BROWSER=f"{browser} %s", **env))
    return run, opened


def _wait(path, seconds=10.0):
    end = time.time() + seconds
    while time.time() < end and not path.exists():
        time.sleep(0.1)
    return path.exists()


def test_open_opens_the_page_with_a_display(tmp_path, capsys):
    if not sys.platform.startswith("linux"):
        return
    folder, book = _task(tmp_path)
    be.write_entry(book, "body", title="release")
    run, opened = _open(book, tmp_path, DISPLAY=":99")
    assert run.returncode == 0, run.stderr
    assert _wait(opened), run.stdout
    assert opened.read_text("utf-8").strip() == (folder / ".baton-etap.html").resolve().as_uri()


def test_over_ssh_it_says_the_path_and_opens_nothing(tmp_path, capsys):
    folder, book = _task(tmp_path)
    be.write_entry(book, "body", title="release")
    run, opened = _open(book, tmp_path, DISPLAY=":99", SSH_CONNECTION="10.0.0.1 1 10.0.0.2 22")
    assert run.returncode == 0, run.stderr
    assert f"HTML: {folder / '.baton-etap.html'}" in run.stdout and "not opened" in run.stdout
    time.sleep(0.5)
    assert not opened.exists()


def test_no_display_is_said_after_the_write_so_the_agent_does_not_offer(tmp_path, monkeypatch, capsys):
    folder, book = _task(tmp_path)
    monkeypatch.setenv("SSH_CONNECTION", "10.0.0.1 1 10.0.0.2 22")
    be.write_entry(book, "body", title="x")
    assert "no display here" in capsys.readouterr().out
    monkeypatch.delenv("SSH_CONNECTION")
    monkeypatch.setattr(be.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert be.no_display()
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert be.no_display() is None


def test_open_with_no_page_yet_is_refused(tmp_path):
    folder, book = _task(tmp_path)
    run, _ = _open(book, tmp_path, DISPLAY=":99")
    assert run.returncode == 1 and "no page yet" in run.stderr
