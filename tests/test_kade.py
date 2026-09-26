"""The fixture is a hand-labelled run, not an imagined case.

On 2026-09-26 the query was run over a real tree — 20 task folders plus a memory
directory — and every hit was labelled by hand. That labelling is what these tests
encode, because a detector shipped without a measured false-positive rate is the
same mistake as a threshold measured on one corpus and then trusted.

Two of the classifications exist because the first version got them wrong and
*overstated* the alarm: a file whose name carries a date is a snapshot, and a row
in a claims register is a dated claim with a status. Counting either as live took
one query from four live places to seven.
"""

import importlib.util
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "baton_kade.py"
spec = importlib.util.spec_from_file_location("bk", TOOL)
bk = importlib.util.module_from_spec(spec)
sys.modules["bk"] = bk
spec.loader.exec_module(bk)

HEADER = '---\nsastoyanie: aktivna\nsledvashto: "price is €2 500"\n---\n\n'
ENTRY = "## 2026-09-20 10:00 — an entry\n\nthe price was €650 back then\n"


def _tree(tmp_path: Path) -> Path:
    """A small tree with one of each kind of place."""
    task = tmp_path / "pricing"
    task.mkdir()
    (task / "LOGBOOK.md").write_text(HEADER + ENTRY, encoding="utf-8")
    (task / "SPEC.md").write_text("Price — ACCEPTED: €650 a year.\n", encoding="utf-8")
    (task / "FAKTI.md").write_text("| price | €650 | A |\n", encoding="utf-8")
    (task / "STATE_21_09.md").write_text("the price then was €650\n", encoding="utf-8")
    other = tmp_path / "sales"
    other.mkdir()
    (other / "LOGBOOK.md").write_text(
        '---\nsledvashto: "price €650 still open"\n---\n\n## 2026-09-19 09:00 — old\n\ntext\n',
        encoding="utf-8")
    return tmp_path


# --- the five kinds of place ------------------------------------------------

def test_a_register_row_is_a_claim_not_live_state(tmp_path):
    """It is a dated claim with a status; another check already ages it."""
    assert bk.kind(Path("FAKTI.md"), 0, "| x | A |", "LOGBOOK.md")[0] == "CLAIM"


def test_a_filename_carrying_a_date_is_a_snapshot(tmp_path):
    """`STATE_21_09.md` says in its own name when it was true."""
    assert bk.kind(Path("STATE_21_09.md"), 0, "text", "LOGBOOK.md")[0] == "SNAPSHOT"
    assert bk.kind(Path("REPORT-2026-09-23.md"), 0, "text", "LOGBOOK.md")[0] == "SNAPSHOT"
    assert bk.kind(Path("project_x_istoria.md"), 0, "text", "LOGBOOK.md")[0] == "SNAPSHOT"


def test_the_front_matter_is_a_header_and_the_body_is_a_record(tmp_path):
    text = HEADER + ENTRY
    assert bk.kind(Path("LOGBOOK.md"), text.index("€2 500"), text, "LOGBOOK.md")[0] == "HEADER"
    what, detail = bk.kind(Path("LOGBOOK.md"), text.index("€650"), text, "LOGBOOK.md")
    assert what == "RECORD" and "2026-09-20" in detail


def test_an_ordinary_file_is_live(tmp_path):
    assert bk.kind(Path("SPEC.md"), 0, "text", "LOGBOOK.md")[0] == "LIVE"


# --- what the separation is worth -------------------------------------------

def test_records_snapshots_and_claims_stay_out_of_the_live_count(tmp_path):
    """The whole point: four places repeat €650, only two of them still claim it."""
    root = _tree(tmp_path)
    hits = list(bk.search(__import__("re").compile("€650"), root, "LOGBOOK.md", None))
    live = [h for h in hits if h[3] in bk.LIVE]
    kinds = {h[3] for h in hits}
    assert kinds == {"LIVE", "HEADER", "RECORD", "SNAPSHOT", "CLAIM"}
    assert {h[0].name for h in live} == {"SPEC.md", "LOGBOOK.md"}


# --- the measured filter ----------------------------------------------------

def test_money_and_decimals_are_kept(tmp_path):
    """Measured: 6/6 money and 3/3 decimal percentages were relevant."""
    for key in ("€2500", "84.8%", "65.8%"):
        assert bk.PRECISE.match(key), key


def test_round_percentages_and_versions_are_dropped(tmp_path):
    """Measured: 16/16 round percentages and 11/11 versions were noise.

    `100%` turned up in nine folders -- it is a word, not a state.
    """
    for key in ("100%", "30%", "v1.0.0", "v2.11.0"):
        assert not bk.PRECISE.match(key), key


def test_thresholds_are_dropped_although_they_look_like_signal(tmp_path):
    """The second measurement changed this one.

    `0.xx` reads like a decision and mostly is not: 41 duplicates, one relevant.
    The rest come from measurement corpora, where two runs both reporting 0.92 is
    two measurements, not duplicated state. A real threshold is still findable by
    name with the plain query -- `0.46` returns five live places.
    """
    for key in ("0.92", "0.46", "0.05"):
        assert not bk.PRECISE.match(key), key


def test_the_same_amount_written_three_ways_is_one_number(tmp_path):
    assert bk.normalise("€1 200") == bk.normalise("€1,200") == bk.normalise("€1.200")


def test_a_line_with_two_numbers_is_counted_once_each(tmp_path):
    """It used to come back four times: once per match, then scanned whole."""
    root = tmp_path
    task = root / "t"
    task.mkdir()
    (task / "SPEC.md").write_text("we moved from €650 to €2 500 this week\n", encoding="utf-8")
    other = root / "u"
    other.mkdir()
    (other / "SPEC.md").write_text("still €650 here and €2 500 there\n", encoding="utf-8")
    rows, _ = bk.duplicates(root, "LOGBOOK.md", None)
    counts = {key: len(hits) for _, _, key, hits in rows}
    assert counts.get("€650") == 2, counts
    assert counts.get("€2500") == 2, counts


def test_a_number_in_one_folder_only_is_not_a_duplicate(tmp_path):
    task = tmp_path / "only"
    task.mkdir()
    (task / "SPEC.md").write_text("€1 234 lives here alone\n", encoding="utf-8")
    rows, _ = bk.duplicates(tmp_path, "LOGBOOK.md", None)
    assert not [r for r in rows if r[2] == "€1234"]


def test_a_number_repeated_only_in_records_is_not_a_duplicate(tmp_path):
    """Two logbooks both remembering €650 in old entries is history, not state."""
    for name in ("a", "b"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "LOGBOOK.md").write_text(
            "---\nsastoyanie: aktivna\n---\n\n## 2026-09-20 10:00 — old\n\nit was €650\n",
            encoding="utf-8")
    rows, _ = bk.duplicates(tmp_path, "LOGBOOK.md", None)
    assert not [r for r in rows if r[2] == "€650"]


def test_the_filter_is_actually_applied_not_just_defined(tmp_path):
    """Mutation caught this: PRECISE was tested as a regex, never as a filter.

    Testing the check and testing that the check runs are different things, and
    this repository has paid for the difference once already.
    """
    for name in ("a", "b"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "SPEC.md").write_text("coverage 100% and price €650\n", encoding="utf-8")
    default, _ = bk.duplicates(tmp_path, "LOGBOOK.md", None)
    keys = {row[2] for row in default}
    assert "€650" in keys
    assert "100%" not in keys, "a round percentage is vocabulary, not state"

    everything, _ = bk.duplicates(tmp_path, "LOGBOOK.md", None, everything=True)
    assert "100%" in {row[2] for row in everything}
