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
            "home": str(tmp_path), "logbook": "LOGBOOK.md",
            "poveritelni": ["klient", "Клиент"], **over}


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


# --- the grey band: one draw near the threshold is partly a coin flip --------
#
# Measured 23.09.2026 on 45 pointers, three identical runs. The spread is
# negligible where the model is confident (median 0.010) and LARGEST exactly
# where the decision is made: ±0.12 and ±0.09 for the two rows whose mean sat
# between 0.38 and 0.55. One row of 45 changed sides of the threshold between
# identical runs -- 0.41 / 0.47 / 0.38 -- so it was flagged in one run of three.
#
# These tests pin the band, the averaging, the ledger, and the wiring into BOTH
# modes that ask this question. A check that is written and never called is the
# most expensive bug in this repo's history.


def _echo(value: float = 0.9, cost: float = 0.0001):
    """urlopen answering every question the request actually asked.

    A fixture with hard-coded keys passes only while the caller happens to ask for
    those keys, and `pitay` rejects a mismatched envelope -- correctly. So the mock
    reads the request it was handed.
    """
    def reply(request, *a, **k):
        asked = json.loads(request.data.decode())["questions"]
        return _Reply({"answers": {name: {"noul": value} for name in asked},
                       "usage": {"cost": cost}})
    return reply


class _Sequence:
    """urlopen returning the next value each call, and counting the calls."""

    def __init__(self, *values):
        self.values = list(values)
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        value = self.values[min(self.calls - 1, len(self.values) - 1)]
        return _Reply({"answers": {"stale": {"noul": value}},
                       "usage": {"cost": 0.0001}})


def _index(tmp_path: Path, target: str = "detail.md") -> None:
    (tmp_path / "INDEX.md").write_text(f"- [Row]({target}) — asserts a thing\n",
                                       encoding="utf-8")
    (tmp_path / target).write_text("The detail file says something else.\n",
                                   encoding="utf-8")


def test_a_value_in_the_grey_band_is_drawn_three_times_and_averaged(
        tmp_path, monkeypatch, capsys):
    """0.41 / 0.47 / 0.38 is the measured row that flipped sides. Mean 0.42."""
    _index(tmp_path)
    seq = _Sequence(0.41, 0.47, 0.38)
    monkeypatch.setattr(bp.urllib.request, "urlopen", seq)
    bp.dali("k", _cfg(tmp_path), set())
    out = capsys.readouterr().out
    assert seq.calls == 3, f"очаквани 3 тегления, направени {seq.calls}"
    assert "0.42" in out
    assert "0.41" in out and "0.47" in out and "0.38" in out, \
        "трите тегления не се показват — числото изглежда като единично"


def test_a_confident_value_is_drawn_once(tmp_path, monkeypatch, capsys):
    """Outside the band the spread is a hundredth; paying three times is waste."""
    _index(tmp_path)
    seq = _Sequence(0.12)
    monkeypatch.setattr(bp.urllib.request, "urlopen", seq)
    bp.dali("k", _cfg(tmp_path), set())
    assert seq.calls == 1, f"очаквано 1 тегление, направени {seq.calls}"


def test_a_high_value_is_drawn_once(tmp_path, monkeypatch):
    """The band has an upper edge too: 0.90 is not in doubt."""
    _index(tmp_path)
    seq = _Sequence(0.90)
    monkeypatch.setattr(bp.urllib.request, "urlopen", seq)
    bp.dali("k", _cfg(tmp_path), set())
    assert seq.calls == 1


def test_the_ledger_counts_every_draw_not_every_row(tmp_path, monkeypatch):
    """What left the machine is three requests. The ledger says what left."""
    _index(tmp_path)
    monkeypatch.setattr(bp.urllib.request, "urlopen", _Sequence(0.50, 0.50, 0.50))
    bp.dali("k", _cfg(tmp_path), set())
    ledger = (tmp_path / ".pregled-dnevnik.tsv").read_text(encoding="utf-8")
    assert "\t3\t" in ledger, f"описът не брои трите тегления:\n{ledger}"


def test_zadachi_averages_in_the_band_too(tmp_path, monkeypatch, capsys):
    """The same question on a different corpus. Wiring, not only the helper."""
    folder = tmp_path / "zadacha"
    folder.mkdir()
    (folder / "DNEVNIK.md").write_text(
        "---\nsledvashto: \"чака доставчика\"\nsastoyanie: aktivna\n---\n\n"
        "## 2026-09-23 — доставчикът отговори и работата продължи\n", encoding="utf-8")
    seq = _Sequence(0.41, 0.47, 0.38)
    monkeypatch.setattr(bp.urllib.request, "urlopen", seq)
    bp.zadachi("k", _cfg(tmp_path, home=str(tmp_path), logbook="DNEVNIK.md"), set())
    assert seq.calls == 3, f"--zadachi не усреднява: {seq.calls} тегления"
    assert "0.42" in capsys.readouterr().out


def test_koe_is_deliberately_left_alone(tmp_path, monkeypatch):
    """Three paths ask a question here; the band was measured on two of them.

    `--koe` asks a different question (one claim at a time, against the whole
    file) and its spread has NOT been measured. Averaging it would carry a number
    from one corpus to another, which is the mistake this whole feature exists to
    correct. Pinned so nobody assumes it averages -- and so that measuring it
    later is a deliberate change, not a discovery.
    """
    _index(tmp_path)
    (tmp_path / "INDEX.md").write_text(
        "- [Row](detail.md) — this pointer makes a claim long enough to be cut out\n",
        encoding="utf-8")
    calls = {"n": 0}

    echo = _echo(0.5)

    def counted(request, *a, **k):
        calls["n"] += 1
        return echo(request)

    monkeypatch.setattr(bp.urllib.request, "urlopen", counted)
    bp.koe("k", _cfg(tmp_path), "detail.md")
    assert calls["n"] == 1, "--koe е започнал да усреднява, без да е мерено"


# --- --koe gets the corpus it lost -----------------------------------------
#
# `--koe` cuts a pointer into separate claims and asks the file about each. Its
# corpus was index lines. Measured 2026-09-23 on this machine's index: 0 of 45
# rows now yield three claims and 13 yield none, because the index was compressed
# on purpose -- "a pointer carries no state". That decision was right and it left
# this mode without input: an index that cannot rot is an index `--koe` cannot
# check.
#
# Task headers are multi-claim by construction, and `--zadachi` already asks the
# whole-header version of the same question against the same logbooks. So the
# corpus moves; the question does not change.


def _zadacha(tmp_path: Path, name: str = "zadacha", header: str = None,
             body: str = "## 2026-09-23 — the supplier answered and the work went on\n") -> Path:
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    header = header or ('sledvashto: "waiting for the supplier. Then the second step follows."\n'
                        'kriterii_zavarshvane: "the bus is live on all three"\n'
                        'sastoyanie: aktivna\n'
                        'na_hod: nie\n')
    (folder / "DNEVNIK.md").write_text(f"---\n{header}---\n\n{body}", encoding="utf-8")
    return folder


def _koe_cfg(tmp_path: Path, **over) -> dict:
    return _cfg(tmp_path, home=str(tmp_path), logbook="DNEVNIK.md", **over)


def test_koe_takes_a_task_name_and_asks_its_logbook(tmp_path, monkeypatch, capsys):
    """The dispatch rule: a bare argument naming a task folder that holds a logbook."""
    _zadacha(tmp_path)
    _index(tmp_path)
    monkeypatch.setattr(bp.urllib.request, "urlopen", _echo())
    bp.koe("k", _koe_cfg(tmp_path), "zadacha")
    out = capsys.readouterr().out
    assert "zadacha" in out
    assert "sledvashto" in out, "изходът не казва кое поле носи твърдението"
    assert "kriterii_zavarshvane" in out


def test_a_header_field_with_several_sentences_becomes_several_claims(tmp_path):
    """`sledvashto` routinely carries more than one assertion; each is asked alone."""
    pairs = bp.zaglavni_tvardeniya({
        "sledvashto": "the first step is done and checked. The second waits on Monday.",
        "sastoyanie": "aktivna"})
    fields = [f for f, _ in pairs]
    assert fields.count("sledvashto") == 2, pairs


def test_a_short_field_falls_back_to_its_whole_value(tmp_path):
    """`sastoyanie: aktivna` yields no sentence; the value itself is the claim."""
    pairs = bp.zaglavni_tvardeniya({"sastoyanie": "aktivna"})
    assert pairs == [("sastoyanie", "aktivna")]


def test_an_empty_or_placeholder_field_is_not_a_claim(tmp_path):
    """A dash is what someone types to mean "nothing here"."""
    assert bp.zaglavni_tvardeniya({"sledvashto": "-", "chaka": "", "na_hod": "nie"}) \
        == [("na_hod", "nie")]


def test_koe_on_a_task_holds_on_the_whole_logbook_not_the_extract(tmp_path, monkeypatch):
    """The guard reads the whole logbook: a client named on page four is still named."""
    _zadacha(tmp_path, body="x" * (bp.TSYAL + 1000) + "\nnotes about Клиент further down\n")
    monkeypatch.setattr(bp.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("изпратено въпреки преградата"))
    with pytest.raises(SystemExit) as err:
        bp.koe("k", _koe_cfg(tmp_path), "zadacha")
    assert "Клиент" in str(err.value)


def test_a_cut_logbook_says_the_cut_keeps_the_newest(tmp_path, monkeypatch, capsys):
    """Newest-first is why this cut is sound where the index corpus's was not."""
    _zadacha(tmp_path, body="y" * (bp.TSYAL + 500))
    monkeypatch.setattr(bp.urllib.request, "urlopen", _echo())
    bp.koe("k", _koe_cfg(tmp_path), "zadacha")
    out = capsys.readouterr().out
    assert "РЯЗАН" in out
    assert "НАЙ-СТАРИТЕ" in out, \
        "срезът не казва КОЕ е отпаднало; при индекса беше обратното и това е разликата"


def test_koe_on_a_task_still_draws_once(tmp_path, monkeypatch):
    """No grey band here: the 0.7 edge has not been measured for flips."""
    _zadacha(tmp_path)
    calls = {"n": 0}

    echo = _echo(0.5)

    def counted(request, *a, **k):
        calls["n"] += 1
        return echo(request)

    monkeypatch.setattr(bp.urllib.request, "urlopen", counted)
    bp.koe("k", _koe_cfg(tmp_path), "zadacha")
    assert calls["n"] == 1


def test_an_index_target_still_reaches_the_index_mode(tmp_path, monkeypatch, capsys):
    """The old corpus is degraded, not removed. Nothing about it changes here."""
    _zadacha(tmp_path)
    (tmp_path / "INDEX.md").write_text(
        "- [Row](detail.md) — this pointer makes a claim long enough to be cut out\n",
        encoding="utf-8")
    (tmp_path / "detail.md").write_text("The detail file says something.\n", encoding="utf-8")
    monkeypatch.setattr(bp.urllib.request, "urlopen", _echo())
    bp.koe("k", _koe_cfg(tmp_path), "detail.md")
    assert "detail.md" in capsys.readouterr().out


def test_a_thin_logbook_is_announced_before_the_numbers(tmp_path, monkeypatch, capsys):
    """Found by the positive control, not by review.

    A task whose header spoke of a review, a board and a submission came back
    "unsupported" on all four claims. The tool was right -- its logbook is 562
    characters and mentions none of it -- but "not supported" reads as "the header
    is wrong" when it meant "nobody wrote it down". The criterion given to the
    model merges the two, so the output has to separate them.
    """
    _zadacha(tmp_path, body="## 2026-09-17 — restored from the inventory\n")
    monkeypatch.setattr(bp.urllib.request, "urlopen", _echo(0.1))
    bp.koe("k", _koe_cfg(tmp_path), "zadacha")
    out = capsys.readouterr().out
    assert "изобщо не се споменава" in out, \
        'не разделя опровергано от никога-не-писано'
    assert "не пише" in out, "тънък дневник не е отбелязан като тънък"
    assert "1 записа" in out, "броят записи не се показва — четящият не вижда колко е тънък"


def test_a_full_logbook_is_not_called_thin(tmp_path, monkeypatch, capsys):
    """The other direction: a real logbook must not carry the warning's excuse."""
    _zadacha(tmp_path, body="## 2026-09-23 — an entry\n" + "детайли. " * 400)
    monkeypatch.setattr(bp.urllib.request, "urlopen", _echo(0.1))
    bp.koe("k", _koe_cfg(tmp_path), "zadacha")
    assert "не пише" not in capsys.readouterr().out
