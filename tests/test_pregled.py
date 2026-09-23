"""The review is the one part of Baton that sends anything anywhere.

So the tests are about the barriers, not about the answers: that an unconfigured
confidential list stops the tool rather than defaulting to "send everything", that
a held word never reaches the network, that a missing or malformed reply is an
error and never reads as "clean", and that a truncated file says so.

The defect that made the two-alphabet rule: the list held only the Latin spelling
of a client's name while the notes about that client were written in Cyrillic. The
guard was structurally right and matched nothing, and a request went out.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "tools" / "baton_pregled.py"
spec = importlib.util.spec_from_file_location("bp", TOOL)
bp = importlib.util.module_from_spec(spec)
sys.modules["bp"] = bp
spec.loader.exec_module(bp)


def _cfg(tmp_path: Path, **over) -> dict:
    (tmp_path / "hooks").mkdir(exist_ok=True)
    return {"indeks": str(tmp_path / "INDEX.md"), "podbor": None,
            "home": str(tmp_path), "poveritelni": ["klient", "Клиент"], **over}


# --- the list you have to make a decision about -----------------------------

def test_a_missing_confidential_list_stops_the_tool(tmp_path, monkeypatch):
    """Absent is not empty: it means nobody was ever asked."""
    monkeypatch.setenv("BATON_PREGLED_INDEKS", str(tmp_path / "INDEX.md"))
    monkeypatch.delenv("BATON_PREGLED_POVERITELNI", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    with pytest.raises(SystemExit) as err:
        bp.config()
    assert "поверителни" in str(err.value)


def test_an_explicitly_empty_list_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("BATON_PREGLED_INDEKS", str(tmp_path / "INDEX.md"))
    monkeypatch.setenv("BATON_PREGLED_POVERITELNI", "")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert bp.config()["poveritelni"] == []


def test_no_index_stops_the_tool(tmp_path, monkeypatch):
    monkeypatch.delenv("BATON_PREGLED_INDEKS", raising=False)
    monkeypatch.setenv("BATON_PREGLED_POVERITELNI", "x")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    with pytest.raises(SystemExit) as err:
        bp.config()
    assert "индекс" in str(err.value)


# --- what never leaves ------------------------------------------------------

@pytest.mark.parametrize("text,etiket,want", [
    ("сървърът на Клиент е долу", "note.md", "Клиент"),
    ("work for klient ltd", "note.md", "klient"),
    ("", "klient/vpn.md", "klient"),
    ("an ordinary note about a scanner", "qrp/tool.md", ""),
])
def test_the_guard_reads_path_and_content(text, etiket, want):
    assert bp.poveritelno(text, etiket, ["klient", "Клиент"]) == want


def test_a_word_only_in_the_other_alphabet_is_not_found():
    """The defect itself: the Latin spelling alone does not catch Cyrillic prose."""
    assert bp.poveritelno("диск на Клиент", "n.md", ["klient"]) == ""
    assert bp.poveritelno("диск на Клиент", "n.md", ["klient", "Клиент"]) == "Клиент"


def test_a_word_far_into_the_text_is_still_found():
    """The leak: the guard read the first 4000 characters of a payload of 28000.

    Four files went out with a client's name and an unreleased product's name in
    them, every occurrence past character 4000. The part the guard read was clean,
    which is why nothing looked wrong.
    """
    text = "safe text. " * 3000 + "и после за Клиент"
    assert len(text) > 28000
    assert bp.poveritelno(text, "n.md", ["Клиент"]) == "Клиент"


def test_detail_hands_back_the_whole_file_for_the_guard(tmp_path):
    """The guard judges the document, not the bytes that happened to fit."""
    (tmp_path / "long.md").write_text("x" * 30000 + "Клиент", encoding="utf-8")
    body, whole = bp.detail(tmp_path, "long.md", 28000)
    assert len(body) == 28000 and "Клиент" not in body
    assert bp.poveritelno(whole, "long.md", ["Клиент"]) == "Клиент"


def test_a_held_text_never_reaches_the_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a request was sent")
    monkeypatch.setattr(bp.urllib.request, "urlopen", boom)
    with pytest.raises(SystemExit) as err:
        bp.pitay("k", "диск на Клиент", {"q": {}}, "x", ["Клиент"])
    assert "Клиент" in str(err.value)


# --- fail closed ------------------------------------------------------------

class _Reply:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.mark.parametrize("payload,want", [
    ({"answers": None}, "непълен отговор"),
    ({"usage": {}}, "непълен отговор"),
    ({"answers": {"a": {"noul": 0.5}}}, "непълен отговор"),
    ({"answers": {"a": {"noul": 0.5}, "b": {"noul": 0.5}, "c": {"noul": 0.5}}}, "непълен отговор"),
    ({"answers": {"a": {"noul": "0.5"}, "b": {"noul": 0.5}}}, "повреден отговор"),
    ({"answers": {"a": {}, "b": {"noul": 0.5}}}, "повреден отговор"),
])
def test_a_broken_envelope_is_an_error_not_clean(payload, want, monkeypatch):
    monkeypatch.setattr(bp.urllib.request, "urlopen", lambda *a, **k: _Reply(payload))
    with pytest.raises(SystemExit) as err:
        bp.pitay("k", "clear text", {"a": {}, "b": {}}, "x", [])
    assert want in str(err.value)


def test_a_sound_reply_passes(monkeypatch):
    payload = {"answers": {"a": {"noul": 0.5}, "b": {"noul": 0.1}}}
    monkeypatch.setattr(bp.urllib.request, "urlopen", lambda *a, **k: _Reply(payload))
    assert bp.pitay("k", "clear text", {"a": {}, "b": {}}, "x", [])["answers"]["a"]["noul"] == 0.5


# --- the cut announces itself ----------------------------------------------

def test_detail_reports_the_full_length(tmp_path):
    (tmp_path / "small.md").write_text("---\nx: 1\n---\nshort", encoding="utf-8")
    (tmp_path / "big.md").write_text("я" * 40000, encoding="utf-8")
    assert bp.detail(tmp_path, "small.md", 28000) == ("short", "short")
    body, whole = bp.detail(tmp_path, "big.md", 28000)
    assert (len(body), len(whole)) == (28000, 40000)
    assert bp.detail(tmp_path, "absent.md", 28000) == ("", "")


# --- reading an index -------------------------------------------------------

def test_pointers_come_from_any_line_that_links(tmp_path):
    (tmp_path / "INDEX.md").write_text(
        "- [One](a/one.md) — still true\n"
        "| 2 | [Two](b/two.md) | |\n"
        "no link on this line\n", encoding="utf-8")
    found = bp.pokazalci(tmp_path / "INDEX.md", None)
    assert [t for _, t in found] == ["a/one.md", "b/two.md"]
    assert found[0][0].startswith("[One]")


def test_a_shortlist_narrows_the_index(tmp_path):
    (tmp_path / "INDEX.md").write_text(
        "- [One](a/one.md) — x\n- [Two](b/two.md) — y\n", encoding="utf-8")
    (tmp_path / "SHORT.md").write_text("| 1 | [Two](b/two.md) | |\n", encoding="utf-8")
    found = bp.pokazalci(tmp_path / "INDEX.md", tmp_path / "SHORT.md")
    assert [t for _, t in found] == ["b/two.md"]
