"""Old name, kept so nothing that loads it breaks: the tool is `baton_corpus.py` (v3.1.0).

Runs the new file in THIS module's namespace rather than importing it, so a caller that
loads this path -- by file, by `python3 tools/baton_korpus.py`, or to monkeypatch it in a
test -- gets the same functions sharing the same globals, exactly as before the rename.
"""
import pathlib as _pathlib

_new = _pathlib.Path(__file__).with_name("baton_corpus.py")
exec(compile(_new.read_text(encoding="utf-8"), str(_new), "exec"))
