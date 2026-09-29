"""The weekly check for a newer Baton: off until the human chooses, and it only ever tells."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks/baton_session_start.py"
TODAY = date(2026, 9, 29)


import pytest


@pytest.fixture(autouse=True)
def _nothing_remembered():
    Path(os.environ["BATON_SESSION_STATE"]).unlink(missing_ok=True)


def _load():
    spec = importlib.util.spec_from_file_location("bss_update", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _release(tmp_path, tag):
    f = tmp_path / f"release-{tag}.json"
    f.write_text(json.dumps({"tag_name": tag, "html_url": f"https://example.org/{tag}"}), "utf-8")
    return f.as_uri()


def _no_network(*a, **k):
    raise AssertionError("the network was touched")


def test_off_never_touches_the_network(monkeypatch):
    bss = _load()
    monkeypatch.setattr(bss, "_local", lambda: {"update_check": False})
    monkeypatch.setattr("urllib.request.urlopen", _no_network)
    assert bss.update_notice(TODAY) is None


def test_not_chosen_asks_the_human_once_a_day_without_the_network(monkeypatch):
    bss = _load()
    monkeypatch.setattr(bss, "_local", lambda: {})
    monkeypatch.setattr("urllib.request.urlopen", _no_network)
    first = bss.update_notice(TODAY)
    assert first and "Ask them" in first and "baton_update.py on" in first
    assert bss.update_notice(TODAY) is None, "asked twice in one day"
    assert bss.update_notice(TODAY + timedelta(days=1))


def test_a_newer_version_is_named_with_the_command_and_kept_until_updated(tmp_path, monkeypatch):
    bss = _load()
    monkeypatch.setattr(bss, "_local", lambda: {"update_check": True, "repo": str(tmp_path)})
    monkeypatch.setenv("BATON_UPDATE_URL", _release(tmp_path, "v99.0.0"))
    note = bss.update_notice(TODAY)
    assert "v99.0.0" in note and f"cd {tmp_path} && git pull" in note and "Never update" in note
    # Within the week: no second request, but the notice stays until the human acts.
    monkeypatch.setattr("urllib.request.urlopen", _no_network)
    assert "v99.0.0" in bss.update_notice(TODAY + timedelta(days=3))


def test_the_same_version_is_silence(tmp_path, monkeypatch):
    bss = _load()
    monkeypatch.setattr(bss, "_local", lambda: {"update_check": True})
    monkeypatch.setenv("BATON_UPDATE_URL", _release(tmp_path, "v" + bss.BATON_VERSION))
    assert bss.update_notice(TODAY) is None


def test_a_failed_check_says_so_and_retries_the_next_day(tmp_path, monkeypatch):
    bss = _load()
    monkeypatch.setattr(bss, "_local", lambda: {"update_check": True})
    monkeypatch.setenv("BATON_UPDATE_URL", (tmp_path / "missing.json").as_uri())
    assert "Could not check" in bss.update_notice(TODAY)
    assert bss.update_notice(TODAY) is None
    monkeypatch.setenv("BATON_UPDATE_URL", _release(tmp_path, "v99.0.0"))
    assert "v99.0.0" in bss.update_notice(TODAY + timedelta(days=1))


def test_the_version_in_the_hook_is_the_version_released():
    """A constant nobody bumps says every release is the old one, and hides every update."""
    top = re.search(r"^## Versions\s+\*\*v(\d+\.\d+\.\d+)\*\*", (ROOT / "README.md").read_text("utf-8"),
                    re.M)
    assert top and top.group(1) == _load().BATON_VERSION


@pytest.mark.parametrize("root_exists", [True, False])
def test_the_hook_tells_the_agent_even_when_there_are_no_tasks(tmp_path, root_exists):
    """A new user has an empty task root -- exactly where the board used to print nothing."""
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    shutil.copy(HOOK, hooks)
    if root_exists:
        (tmp_path / "tasks").mkdir()
    (hooks / "baton.local.json").write_text(json.dumps(
        {"home": str(tmp_path / "tasks"), "update_check": True, "repo": str(ROOT)}), "utf-8")
    env = dict(os.environ, BATON_UPDATE_URL=_release(tmp_path, "v99.0.0"))
    env.pop("BATON_HOME", None)
    out = subprocess.run([sys.executable, str(hooks / HOOK.name)], input="", env=env,
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and not out.stderr, out.stderr
    assert "v99.0.0" in json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]


def test_the_switch_keeps_every_other_setting(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("bu", ROOT / "tools/baton_update.py")
    bu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bu)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    cfg = tmp_path / "baton/hooks/baton.local.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"home": "/x", "us": ["a"]}), "utf-8")
    assert bu.main(["on"]) == 0
    assert json.loads(cfg.read_text("utf-8")) == {"home": "/x", "us": ["a"], "update_check": True,
                                                   "repo": str(ROOT)}
    assert bu.main(["off"]) == 0 and json.loads(cfg.read_text("utf-8"))["update_check"] is False
    assert bu.main(["maybe"]) == 2


def _hook_with_empty_root(tmp_path, talks: int):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    shutil.copy(HOOK, hooks)
    (tmp_path / "tasks").mkdir()
    (hooks / "baton.local.json").write_text(json.dumps(
        {"home": str(tmp_path / "tasks"), "update_check": False}), "utf-8")
    for i in range(talks):
        f = tmp_path / f"claude/projects/-home-x/{i}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{}\n", "utf-8")
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(tmp_path / "claude"))
    env.pop("BATON_HOME", None)
    run = lambda: subprocess.run([sys.executable, str(hooks / HOOK.name)], input="", env=env,
                                 capture_output=True, text=True, timeout=30)
    return run


def test_months_of_earlier_work_and_no_tasks_offers_the_inventory_once_a_day(tmp_path):
    run = _hook_with_empty_root(tmp_path, talks=3)
    out = run()
    assert not out.stderr, out.stderr
    context = json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "/baton-inventory" in context and "3 earlier" in context
    assert run().stdout == "", "offered twice in one day"


def test_a_machine_with_no_earlier_conversations_hears_nothing(tmp_path):
    out = _hook_with_empty_root(tmp_path, talks=0)()
    assert out.returncode == 0 and out.stdout == "" and not out.stderr
