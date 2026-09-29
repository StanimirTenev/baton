"""The key is stored where the review reads it, and never shown on any path."""
import importlib.util
import stat
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
KEY = "sk-or-v1-" + "a" * 40


def _load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_stored_with_mode_600_keeping_other_lines(tmp_path, monkeypatch):
    bk = _load("baton_key")
    monkeypatch.setattr(bk, "ENV", tmp_path / "baton/env")
    bk.ENV.parent.mkdir()
    bk.ENV.write_text("OTHER=1\nOPENROUTER_API_KEY=old\n", encoding="utf-8")
    bk.store(KEY)
    assert bk.ENV.read_text(encoding="utf-8") == f"OTHER=1\nOPENROUTER_API_KEY={KEY}\n"
    assert stat.S_IMODE(bk.ENV.stat().st_mode) == 0o600
    assert bk.stored() == KEY


def test_check_prints_the_limit_and_never_the_key(tmp_path, monkeypatch, capsys):
    bk = _load("baton_key")
    monkeypatch.setattr(bk, "ENV", tmp_path / "env")
    bk.store(KEY)
    monkeypatch.setattr(bk, "info", lambda key: {"label": KEY[:14] + "...0df", "limit": 5, "usage": 0.25})
    assert bk.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "$5.00" in out and "$0.2500" in out and KEY not in out and "sk-or" not in out


def test_a_refused_key_is_not_stored_and_not_echoed(tmp_path, monkeypatch, capsys):
    bk = _load("baton_key")
    monkeypatch.setattr(bk, "ENV", tmp_path / "env")
    monkeypatch.setattr(bk.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(bk.getpass, "getpass", lambda prompt: KEY)

    def refuse(key):
        raise RuntimeError("OpenRouter refused the key (HTTP 401)")
    monkeypatch.setattr(bk, "info", refuse)
    assert bk.main([]) == 1
    assert not bk.ENV.exists()
    assert KEY not in capsys.readouterr().out


def test_without_a_terminal_it_asks_for_one_instead_of_reading_stdin(tmp_path, monkeypatch, capsys):
    """A key piped through a command the agent runs would be in the conversation."""
    bk = _load("baton_key")
    monkeypatch.setattr(bk, "ENV", tmp_path / "env")
    monkeypatch.setattr(bk.sys.stdin, "isatty", lambda: False, raising=False)
    assert bk.main([]) == 1 and not bk.ENV.exists()
    assert "own terminal" in capsys.readouterr().out


def test_the_review_reads_the_stored_key_first(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    (tmp_path / ".config/baton").mkdir(parents=True)
    (tmp_path / ".config/typesafe").mkdir(parents=True)
    (tmp_path / ".config/baton/env").write_text(f"OPENROUTER_API_KEY={KEY}\n", encoding="utf-8")
    (tmp_path / ".config/typesafe/env").write_text("OPENROUTER_API_KEY=older\n", encoding="utf-8")
    br = _load("baton_review")
    assert br.get_api_key() == KEY
    (tmp_path / ".config/baton/env").unlink()
    assert br.get_api_key() == "older", "the older file stopped being read"
