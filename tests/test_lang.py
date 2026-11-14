"""The words the hooks recognise live in hooks/lang/<code>.json, one file per language, and the
patterns are built by joining every installed language (core stage 4, 2026-11-14).

Rule from the owner: the software is in English, a user works in their own language, and a new
language is a new file, never a code change. The patterns below are the ones the hooks had
written into their code until then, frozen here as text: with en and bg installed, the built
patterns must find exactly what they found -- the same spans and the same groups -- on every
string the tests already use and on every line of the stage-0 snapshots.
"""
import ast
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"

OLD = {
    ("baton_stop", "_CHANGED"):
        r"(?i)\b(?:(?:re)?(?:wr[oi]te|written|fix|chang|updat|edit|creat|renam|refactor|"
        r"replac|remov|delet|patch|rework|implement)\w*|add(?:s|ed|ing)?|mov(?:e|es|ed|ing))\b"
        r"|поправ|пренаписа|промен|добав|написа|създад|обнов|изтри|преименува|замен|махна",
    ("baton_stop", "_GONE"):
        r"(?i)\b(?:delet|remov|mov(?:e|es|ed|ing)\b|renam)|изтри|премест|преименува|махна",
    ("baton_stop", "_VISIBLE"):
        r"(?i)(?<![\w-])(public(?:ly)?|private(?:ly)?|публичен|частен|"
        r"(?:публичн|частн)(?:о|а|и|ия|ият|ото|ата|ите)?)(?![\w-])",
    ("baton_stop", "_KEY"):
        r"(?i)(?:public|private)[\s-]+keys?(?![\w-])|(?:публич|част)\w*\s+ключ",
    ("baton_stop", "_CLAIMS"): r"(?i)^###\s+(?:claims to verify|за проверка)\s*:?\s*$",
    ("baton_stop", "_REFUTED"): r"(?i)^\s*(?:[-*]\s+)?(?:refuted|оборено)\s*:",
    ("baton_stop", "_TESTS"):
        r"(?i)(?<![\w-])((?:all\s+)?tests?\s+(?:all\s+)?(?:are\s+|is\s+)?pass(?:es|ed|ing)?"
        r"|(?:test\s+)?suite\s+pass(?:es|ed|ing)?|CI\s+(?:is\s+)?green|all\s+green"
        r"|(?<!failed, )(?<![\d,./])\d[\d,]*\s+passed"
        r"|(?<![\d,./])(?P<n>\d+)\s*/\s*(?P=n)\s+(?:tests?\s+)?pass(?:es|ed)?"
        r"|тестове(?:те)?\s+(?:минават|минаха|преминават|преминаха|са\s+зелени)(?!\s+през)"
        r"|минаха\s+(?:всички\s+)?тестовете)"
        r"(?![\w-])",
    ("baton_prompt", "_MARKED_ID"):
        r"(?i)(?:#|№\s?|\b(?:задача(?:та)?|task)\s+)([1-9]\d*)(?![\w.:/,\-)])",
}


def _load(name, folder=HOOKS):
    spec = importlib.util.spec_from_file_location(f"lang_{name}", folder / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _corpus() -> list:
    """Every string literal in tests/*.py, each line of it, and every line of the snapshots."""
    out = set()
    for path in sorted((ROOT / "tests").glob("*.py")):
        if path.name == Path(__file__).name:
            continue
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.add(node.value)
                out.update(node.value.splitlines())
    for path in sorted((ROOT / "tests" / "snapshots").rglob("*")):
        if path.is_file():
            text = path.read_text("utf-8", errors="replace")
            out.add(text)
            out.update(text.splitlines())
    return sorted(out)


# Words the corpus above happens not to hold in Bulgarian, so each Bulgarian alternative is met
# at least once, with its endings and with a near miss.
EXTRA = ("изтрих /tmp/old.py и преместих ~/a/b.py", "преименувах файла, махнах реда",
         "Премести го", "задача 12 приключи", "Задачата 7", "задача12", "виж задачата 3 сега",
         "Публичното хранилище", "частният ключ", "публичен ключ", "частните", "тестовете минават",
         "тестове минаха през", "минаха всички тестовете", "### За проверка:", "- оборено: да")
CORPUS = _corpus() + list(EXTRA)
MODS = {name: _load(name) for name in ("baton_stop", "baton_prompt")}


def _found(rx, text):
    return [(m.span(), m.groups()) for m in rx.finditer(text)]


@pytest.mark.parametrize("where", sorted(OLD), ids=lambda w: f"{w[0]}.{w[1]}")
def test_the_built_pattern_finds_what_the_old_one_found(where):
    old = re.compile(OLD[where])
    new = getattr(MODS[where[0]], where[1])
    assert new.flags & re.I
    latin = cyrillic = 0
    for text in CORPUS:
        assert _found(new, text) == _found(old, text), (where, text[:200])
        if old.search(text):
            latin += bool(re.search(r"[A-Za-z]", old.search(text).group(0)))
            cyrillic += bool(re.search(r"[а-яА-Я]", old.search(text).group(0)))
    assert latin, f"{where}: no English match in the corpus -- the comparison proved nothing"
    assert cyrillic, f"{where}: no Bulgarian match in the corpus -- the comparison proved nothing"


def _hooks_with(tmp_path, langs: dict):
    """The hooks beside _baton.py, with a lang folder holding exactly `langs` (name -> text)."""
    folder = tmp_path / "hooks"
    folder.mkdir()
    for path in HOOKS.glob("*.py"):
        shutil.copy(path, folder)
    (folder / "lang").mkdir()
    for name, text in langs.items():
        (folder / "lang" / name).write_text(text, "utf-8")
    return folder


def test_no_language_file_matches_nothing_not_everything(tmp_path):
    """`"|".join([])` is the empty pattern, which matches everywhere: with the lang folder gone,
    every line would read as a claim of a change. Gone, nothing is recognised instead."""
    folder = _hooks_with(tmp_path, {})
    stop, prompt = _load("baton_stop", folder), _load("baton_prompt", folder)
    for rx in (stop._CHANGED, stop._GONE, stop._VISIBLE, stop._KEY, stop._TESTS):
        assert not rx.search("updated the file, it is public, all tests pass"), rx.pattern
    assert not stop._CLAIMS.search("### Claims to verify")
    assert not stop._REFUTED.search("- refuted: x")
    assert prompt.numbers_in("#12 is done") == {12}, "the sign is not a word of any language"
    assert prompt.numbers_in("see task 12 now please, it is long enough") == set()


def test_a_broken_file_or_fragment_is_skipped_not_fatal(tmp_path):
    en = (HOOKS / "lang" / "en.json").read_text("utf-8")
    bad = {"words": {"changed": ["(unclosed", "zzpatched"], "gone": "not a list"}}
    folder = _hooks_with(tmp_path, {"en.json": en, "xx.json": "{ not json",
                                     "yy.json": json.dumps(bad)})
    stop = _load("baton_stop", folder)
    assert stop._CHANGED.search("I updated it") and stop._CHANGED.search("zzpatched")
    assert not stop._CHANGED.search("unclosed")
    out = subprocess.run([sys.executable, str(folder / "baton_stop.py")], input="{}",
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and "Traceback" not in out.stderr, out.stderr


def test_a_new_language_is_a_new_file(tmp_path):
    """A third language, no code: its words are recognised next to en and bg."""
    de = {"words": {"changed": ["geändert"], "claims_heading": ["zu prüfen"],
                    "task_word": ["aufgabe"]}}
    folder = _hooks_with(tmp_path, {"en.json": (HOOKS / "lang" / "en.json").read_text("utf-8"),
                                     "bg.json": (HOOKS / "lang" / "bg.json").read_text("utf-8"),
                                     "de.json": json.dumps(de)})
    stop, prompt = _load("baton_stop", folder), _load("baton_prompt", folder)
    assert stop._CHANGED.search("Datei geändert") and stop._CHANGED.search("поправих")
    assert stop._CLAIMS.search("### Zu prüfen") and stop._CLAIMS.search("### За проверка")
    assert prompt.numbers_in("siehe Aufgabe 12 bitte jetzt sofort ansehen") == {12}


def test_every_language_file_is_json_with_known_sections():
    files = sorted((HOOKS / "lang").glob("*.json"))
    assert {"en", "bg"} <= {p.stem for p in files}
    en = json.loads((HOOKS / "lang" / "en.json").read_text("utf-8"))
    for path in files:
        data = json.loads(path.read_text("utf-8"))
        assert set(data) <= {"board", "words"}, path.name
        assert set(data.get("board", {})) <= set(en["board"]), f"{path.name}: a key en does not have"
        assert set(data.get("words", {})) <= set(en["words"]), f"{path.name}: a slot no hook reads"


def _board():
    spec = importlib.util.spec_from_file_location("lang_board", ROOT / "tools" / "baton_board.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_board_takes_any_language_with_a_file_and_falls_back_to_en(tmp_path, monkeypatch):
    board = _board()
    assert board._t("bg", "Our move") == "Наш ход" and board._t("en", "Our move") == "Our move"
    (tmp_path / "en.json").write_text((HOOKS / "lang" / "en.json").read_text("utf-8"), "utf-8")
    (tmp_path / "de.json").write_text(json.dumps({"board": {"Our move": "Unser Zug"}}), "utf-8")
    monkeypatch.setattr(board, "LANG_DIR", tmp_path)
    monkeypatch.setattr(board, "LABELS", board._labels())
    assert board._t("de", "Our move") == "Unser Zug"
    assert board._t("de", "Frozen") == "Frozen", "a word de lacks is the English one"
    assert board._t("xx", "Frozen") == "Frozen"
    with pytest.raises(SystemExit):
        board.main(["--lang", "bg", "--out", str(tmp_path / "x.html")])   # bg has no file here


def test_session_start_passes_on_a_language_only_when_it_has_a_file(tmp_path, monkeypatch):
    """Until stage 4 the hook passed `en` or `bg` and turned every other code into `en`."""
    ss = _load("baton_session_start")
    started = []
    monkeypatch.setattr(ss, "board_wanted", lambda *a: True)
    monkeypatch.setattr(ss._baton, "start_board", lambda cmd, *a: started.append(cmd))
    for code, expect in (("bg", "bg"), ("en", "en"), ("zz", "en"), ("../en", "en")):
        monkeypatch.setattr(ss, "_local", lambda code=code: {"board_language": code})
        ss.open_board("startup", tmp_path, "LOGBOOK.md")
        assert started[-1][started[-1].index("--lang") + 1] == expect, code


def test_a_language_file_not_installed_is_named_by_the_drift_check(tmp_path, monkeypatch):
    """install.sh copies hooks/lang/ beside the hooks; a copy made before it existed has none,
    and then no word is recognised -- the silent case the drift check is there for."""
    monkeypatch.delenv("BATON_SOURCE", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    src = tmp_path / "src"
    shutil.copytree(HOOKS, src, ignore=shutil.ignore_patterns("__pycache__", "baton.*", "sessions"))
    installed = tmp_path / "installed"
    shutil.copytree(src, installed, ignore=shutil.ignore_patterns("lang"))
    (installed / "baton.local.json").write_text(json.dumps({"source": str(src)}), "utf-8")
    drift = _load("baton_session_start", installed).install_drift()
    assert "lang/bg.json (not installed)" in drift and "lang/en.json (not installed)" in drift
    shutil.copytree(src / "lang", installed / "lang")
    assert _load("baton_session_start", installed).install_drift() == []


def test_a_language_file_that_differs_from_the_release_is_named(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("lang_pd", ROOT / "tests" / "test_plugin_drift.py")
    pd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pd)
    cfg, run, clone = pd._machine(tmp_path)
    for base in (run, clone):
        shutil.copytree(HOOKS / "lang", base / "hooks" / "lang")
    assert pd._load(run, monkeypatch, cfg, tmp_path).plugin_drift() is None
    (run / "hooks" / "lang" / "bg.json").write_text("{}", "utf-8")
    (run / "hooks" / "lang" / "en.json").unlink()
    note = pd._load(run, monkeypatch, cfg, tmp_path).plugin_drift()
    assert note and "lang/bg.json" in note and "lang/en.json (missing)" in note, note
