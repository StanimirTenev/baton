"""The board is a view of the logbooks, never a second source of truth.

The session-start hook already says all of this, but it says it as a wall of text
at the top of a conversation, where it is least readable. The board lays the same
state out. It reuses the hook's own parsing: two readers of one header that
disagree is a defect waiting to happen, and the board is the one that would be
believed, because it is prettier.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "baton_board.py"
spec = importlib.util.spec_from_file_location("baton_board", TOOL)
tablo = importlib.util.module_from_spec(spec)
sys.modules["baton_board"] = tablo
spec.loader.exec_module(tablo)

TODAY = date(2026, 9, 19)


def task(root: Path, name: str, header: str = "", extra: dict[str, str] | None = None) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    body = f"---\n{header}\n---\n\n## 2026-09-19 10:00 — entry\n" if header else "## entry\n"
    (folder / "LOGBOOK.md").write_text(body, encoding="utf-8")
    for filename, content in (extra or {}).items():
        (folder / filename).write_text(content, encoding="utf-8")
    return folder


def test_a_task_on_us_and_one_waiting_are_separated(tmp_path):
    task(tmp_path, "ours", "sastoyanie: aktivna\nna_hod: nie\nprioritet: visok")
    task(tmp_path, "theirs", "sastoyanie: chakashta\nna_hod: David")
    rows, _ = tablo.collect(tmp_path, "LOGBOOK.md")
    page = tablo.render(rows, tmp_path, TODAY)
    assert "Our move" in page and "Waiting on someone outside" in page
    assert page.index("Our move") < page.index("Waiting on someone outside")
    assert "waiting on: David" in page


def test_a_frozen_task_is_listed_but_not_offered(tmp_path):
    task(tmp_path, "parked", "sastoyanie: zamrazena\nna_hod: nie")
    page = tablo.render(*tablo.collect(tmp_path, "LOGBOOK.md")[:1], tmp_path, TODAY)
    assert "Frozen" in page
    assert "Our move" not in page


def test_a_shelf_life_warning_reaches_the_card(tmp_path):
    task(tmp_path, "stale",
         "sastoyanie: aktivna\nna_hod: nie\nvyarno_kum: 2026-08-01\npregled_sled: 30d")
    rows, _ = tablo.collect(tmp_path, "LOGBOOK.md")
    assert rows[0]["warnings"] and "late" in rows[0]["warnings"][0]
    assert "shelf-life" in tablo.render(rows, tmp_path, TODAY)


def test_an_unretired_constraint_reaches_the_card(tmp_path):
    task(tmp_path, "t", "sastoyanie: aktivna\nna_hod: nie", {
        "OGRANICHENIYA.md": "| id | статус | файл | текст |\n|--|--|--|--|\n"
                            "| O1 | пада | X.md | a sentence long enough to find |\n",
        "X.md": "a sentence long enough to find, still here\n"})
    rows, _ = tablo.collect(tmp_path, "LOGBOOK.md")
    assert any("still there" in w for w in rows[0]["warnings"])


def test_a_passed_deadline_is_marked_hot(tmp_path):
    task(tmp_path, "late", "sastoyanie: aktivna\nna_hod: nie\nvremevi_kriterii: srok:2026-09-01")
    rows, _ = tablo.collect(tmp_path, "LOGBOOK.md")
    page = tablo.render(rows, tmp_path, TODAY)
    assert "card hot" in page and "passed" in page


def test_a_task_without_a_header_still_appears(tmp_path):
    """A logbook nobody has given a header must not vanish from the board."""
    task(tmp_path, "plain")
    rows, _ = tablo.collect(tmp_path, "LOGBOOK.md")
    assert rows[0]["headerless"]
    assert "plain" in tablo.render(rows, tmp_path, TODAY)


def test_html_in_a_logbook_cannot_reach_the_page(tmp_path):
    """A logbook is written by hand and may contain anything at all."""
    task(tmp_path, "x", 'sastoyanie: aktivna\nna_hod: nie\nsledvashto: "<script>alert(1)</script>"')
    page = tablo.render(*tablo.collect(tmp_path, "LOGBOOK.md")[:1], tmp_path, TODAY)
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page


def test_an_empty_root_produces_no_page(tmp_path):
    rows, _ = tablo.collect(tmp_path, "LOGBOOK.md")
    assert rows == []


def test_the_board_says_it_is_generated_and_local(tmp_path):
    """It must never read as the record. The logbooks are."""
    task(tmp_path, "t", "sastoyanie: aktivna\nna_hod: nie")
    page = tablo.render(*tablo.collect(tmp_path, "LOGBOOK.md")[:1], tmp_path, TODAY)
    assert "Generated from the logbooks" in page
    assert "Nothing leaves the machine" in page


def test_a_finished_task_in_either_language_is_not_live(tmp_path):
    """v3.2.0 maps every spelling to `finished`; the board's own list of finished words did
    not know that word, so a finished task would have shown as live. Caught by hand."""
    for name, state in (("bg", "priklyuchila"), ("cy", "приключила"), ("en", "finished")):
        d = tmp_path / name
        d.mkdir()
        (d / "LOGBOOK.md").write_text(f"---\nsastoyanie: {state}\n---\n\n## 2026-09-01 — x\n",
                                      encoding="utf-8")
    rows, _ = tablo.collect(tmp_path, "LOGBOOK.md")
    page = tablo.render(rows, tmp_path, TODAY)
    assert "3 finished" in page and "0 live" in page, page[:400]


def test_each_priority_badge_is_coloured(tmp_path):
    """2026-10-03: the badge itself is red, yellow or green, not the dot of the text board."""
    for name, p in (("a", "high"), ("b", "medium"), ("c", "low")):
        task(tmp_path, name, f"state: active\nturn: us\npriority: {p}")
    page = tablo.render(*tablo.collect(tmp_path, "LOGBOOK.md")[:1], tmp_path, TODAY)
    for p, var in (("high", "--hot"), ("medium", "--warm"), ("low", "--cool")):
        assert f'class="badge prio-{p}">{p}<' in page
        assert f".badge.prio-{p}{{color:var({var})" in page


# -- Row 34: the board opens itself at session start, if asked to -------------------------

def test_the_board_speaks_bulgarian_when_asked(tmp_path):
    task(tmp_path, "ours", "sastoyanie: aktivna\nna_hod: nie\nprioritet: visok")
    task(tmp_path, "theirs", "sastoyanie: chakashta\nna_hod: David")
    task(tmp_path, "parked", "sastoyanie: zamrazena\nna_hod: nie")
    rows, _ = tablo.collect(tmp_path, "LOGBOOK.md")
    page = tablo.render(rows, tmp_path, TODAY, lang="bg")
    assert '<html lang="bg">' in page
    assert "Наш ход" in page and "Чакаме някого отвън" in page and "Замразени" in page
    assert "Our move" not in page and "Waiting on someone outside" not in page
    assert "чакаме: David" in page and "висок" in page
    assert "Our move" in tablo.render(rows, tmp_path, TODAY), "English stays the default"


def _hook_env(tmp_path, settings: dict | None, display=True):
    import json
    import os
    root = Path(__file__).resolve().parent.parent
    data = tmp_path / "data"
    data.mkdir()
    if settings is not None:
        (data / "baton.local.json").write_text(json.dumps(settings), "utf-8")
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    tasks = tmp_path / "tasks"
    task(tasks, "ours", "sastoyanie: aktivna\nna_hod: nie")
    opened = tmp_path / "opened.txt"
    browser = tmp_path / "browser.sh"
    browser.write_text(f'#!/bin/sh\necho "$1" > "{opened}"\n', "utf-8")
    browser.chmod(0o755)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR", "BATON_HOME", "DISPLAY",
                                "WAYLAND_DISPLAY"))}
    env.update(HOME=str(home), BATON_HOME=str(tasks), BATON_LOGBOOK="LOGBOOK.md",
               CLAUDE_PLUGIN_ROOT=str(root), CLAUDE_PLUGIN_DATA=str(data),
               BROWSER=f"{browser} %s")
    if display:
        env["DISPLAY"] = ":99"
    return env, opened, data


def _start(env, source):
    import subprocess
    hook = Path(__file__).resolve().parent.parent / "hooks" / "baton_session_start.py"
    out = subprocess.run([sys.executable, str(hook)], input=f'{{"source":"{source}"}}'.encode(),
                         capture_output=True, env=env, timeout=30)
    assert out.returncode == 0, out.stderr


def _wait(path, seconds=15.0):
    import time
    end = time.time() + seconds
    while time.time() < end and not path.exists():
        time.sleep(0.1)
    return path.exists()


def test_session_start_opens_the_board_when_switched_on(tmp_path):
    env, opened, data = _hook_env(tmp_path, {"board_open": True, "board_language": "bg"})
    _start(env, "startup")
    assert _wait(opened), "switched on, at startup, with a display: the board opens"
    page = data / "baton.board.html"
    assert opened.read_text("utf-8").strip() == page.resolve().as_uri()
    assert "Наш ход" in page.read_text("utf-8")


def test_the_board_opens_after_clear_too(tmp_path):
    env, opened, _ = _hook_env(tmp_path, {"board_open": True})
    _start(env, "clear")
    assert _wait(opened)


def test_never_on_compact_or_resume_or_when_off_or_without_a_display(tmp_path):
    import importlib.util
    hook = Path(__file__).resolve().parent.parent / "hooks" / "baton_session_start.py"
    spec = importlib.util.spec_from_file_location("ss_board", hook)
    ss = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ss)
    on = {"board_open": True}
    assert ss.board_wanted("startup", on, {"DISPLAY": ":0"}, "linux")
    assert ss.board_wanted("clear", on, {"WAYLAND_DISPLAY": "w"}, "linux")
    assert not ss.board_wanted("compact", on, {"DISPLAY": ":0"}, "linux")
    assert not ss.board_wanted("resume", on, {"DISPLAY": ":0"}, "linux")
    assert not ss.board_wanted(None, on, {"DISPLAY": ":0"}, "linux")
    assert not ss.board_wanted("startup", {}, {"DISPLAY": ":0"}, "linux"), "off by default"
    assert not ss.board_wanted("startup", {"board_open": "yes"}, {"DISPLAY": ":0"}, "linux")
    assert not ss.board_wanted("startup", on, {}, "linux"), "no display (SSH): silent"
    assert not ss.board_wanted("startup", on, {"SSH_CONNECTION": "x"}, "darwin")
    assert ss.board_wanted("startup", on, {}, "darwin") and ss.board_wanted("startup", on, {}, "win32")


def test_no_display_through_the_hook_opens_nothing_and_the_board_still_comes(tmp_path):
    import time
    env, opened, data = _hook_env(tmp_path, {"board_open": True}, display=False)
    _start(env, "startup")
    time.sleep(2)
    assert not opened.exists() and not (data / "baton.board.html").exists()


def test_the_board_process_gets_no_secret_from_the_session(tmp_path):
    """The board is opened in a process of its own. It gets the names it needs to find the
    tasks and to bring up a browser -- this machine's GNOME/X11 set among them -- and none of
    the session's keys or tokens (v3.19.0, before resubmitting to the plugin directory)."""
    env, opened, data = _hook_env(tmp_path, {"board_open": True})
    seen = tmp_path / "browser-env.txt"
    browser = tmp_path / "browser-env.sh"
    browser.write_text(f'#!/bin/sh\nenv > "{seen}"\necho "$1" > "{opened}"\n', "utf-8")
    browser.chmod(0o755)
    display = {"XAUTHORITY": "/run/user/1000/gdm/Xauthority", "XDG_RUNTIME_DIR": "/run/user/1000",
               "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
               "XDG_CURRENT_DESKTOP": "ubuntu:GNOME", "XDG_SESSION_TYPE": "x11",
               "WAYLAND_DISPLAY": "wayland-0"}
    secrets = {"OPENROUTER_API_KEY": "sk-or-test", "GITHUB_TOKEN": "ghp_test",
               "CLAUDE_CODE_MESSAGING_TOKEN": "t", "ANTHROPIC_API_KEY": "sk-ant-test",
               "AWS_SECRET_ACCESS_KEY": "s"}
    env.update(display, **secrets, BROWSER=f"{browser} %s")
    _start(env, "startup")
    assert _wait(opened), "the board still opens"
    assert opened.read_text("utf-8").strip() == (data / "baton.board.html").resolve().as_uri()
    got = dict(line.split("=", 1) for line in seen.read_text("utf-8").splitlines() if "=" in line)
    for name, value in {**display, "DISPLAY": ":99"}.items():
        assert got.get(name) == value, f"{name} reaches the browser"
    for name in secrets:
        assert name not in got, f"{name} is not passed to the board"
    assert got["BATON_HOME"] == env["BATON_HOME"] and got["CLAUDE_PLUGIN_DATA"] == str(data)


def test_board_env_keeps_only_the_listed_names():
    import importlib.util
    hook = Path(__file__).resolve().parent.parent / "hooks" / "_baton.py"   # since v3.29.0
    spec = importlib.util.spec_from_file_location("ss_board_env", hook)
    ss = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ss)
    env = ss.board_env({"PATH": "/bin", "HOME": "/h", "SYSTEMROOT": "C:\\Windows",
                        "OPENROUTER_API_KEY": "k", "SSH_AUTH_SOCK": "/s", "BATON_HOME": "old"},
                       Path("/tasks"), "LOGBOOK.md")
    assert env == {"PATH": "/bin", "HOME": "/h", "SYSTEMROOT": "C:\\Windows",
                   "BATON_HOME": str(Path("/tasks")), "BATON_LOGBOOK": "LOGBOOK.md"}
