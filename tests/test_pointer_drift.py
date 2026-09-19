"""A pointer that has grown into a record.

The failure this guards: state copied into `sledvashto` "so it is visible at session
start" now lives in two places, and only one of them gets corrected.
"""

import importlib.util
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_session_start.py"
spec = importlib.util.spec_from_file_location("bss", HOOK)
bss = importlib.util.module_from_spec(spec)
sys.modules["bss"] = bss
spec.loader.exec_module(bss)


def test_a_short_pointer_is_not_drift():
    assert bss.pointer_drift({"sledvashto": "Да се пусне коментарът под поста на Campbell."}) is None


def test_an_empty_pointer_is_not_drift():
    assert bss.pointer_drift({}) is None
    assert bss.pointer_drift({"sledvashto": ""}) is None
    assert bss.pointer_drift({"sledvashto": "   "}) is None


def test_exactly_at_the_threshold_is_not_drift():
    assert bss.pointer_drift({"sledvashto": "x" * bss.POINTER_MAX}) is None


def test_one_over_the_threshold_is_drift():
    assert bss.pointer_drift({"sledvashto": "x" * (bss.POINTER_MAX + 1)}) == bss.POINTER_MAX + 1


def test_the_real_case_that_motivated_it():
    """The shape the field actually took on 19.09: three findings and a date in a
    field meant to hold the next move."""
    bloated = (
        "✅ ПУСНАТИ СА ТРИ НЕЩА НА 19.09: коментар под поста на Marin Ivezic; GitHub issue #1 "
        "в appliedquantum/cyclonedx-property-taxonomy; коментар под поста на Dr. Robert "
        "Campbell (IBM Quantum-Safe Executive). ⏳ И ТРИТЕ ЧАКАТ ОТГОВОР — следи ги, особено "
        "Campbell. Чакат още за коментар: Olewinski и студентският ECDAT."
    )
    assert bss.pointer_drift({"sledvashto": bloated}) is not None


def test_a_non_string_value_does_not_crash():
    assert bss.pointer_drift({"sledvashto": 12345}) is None
    assert bss.pointer_drift({"sledvashto": None}) is None


# --- the bug the drift check uncovered -------------------------------------

def test_a_hash_inside_a_quoted_value_is_text_not_a_comment():
    """`GitHub issue #1` was cut at the `#`, and the session start printed a
    next-move line that stopped mid-sentence. A truncated pointer reads exactly
    like a whole one, so nothing looked wrong."""
    fm = bss.parse_frontmatter(
        '---\nsledvashto: "issue #1 in appliedquantum/taxonomy is open"\n---\n')
    assert fm["sledvashto"] == "issue #1 in appliedquantum/taxonomy is open"


def test_a_trailing_comment_on_an_unquoted_value_is_still_stripped():
    fm = bss.parse_frontmatter("---\nprioritet: visok  # the old behaviour\n---\n")
    assert fm["prioritet"] == "visok"


def test_a_single_quoted_value_keeps_its_hash_too():
    fm = bss.parse_frontmatter("---\nsledvashto: 'PR #17 waits on review'\n---\n")
    assert fm["sledvashto"] == "PR #17 waits on review"


def test_an_unterminated_quote_falls_back_and_does_not_crash():
    fm = bss.parse_frontmatter('---\nsledvashto: "no closing quote here\n---\n')
    assert "sledvashto" in fm


def test_a_quote_inside_a_quoted_value_does_not_end_it():
    """The regression the first attempt at this fix introduced: a value that quotes
    someone was cut at the inner quote, losing 90% of it. Prose with quotes in it is
    the normal case in a logbook header."""
    fm = bss.parse_frontmatter(
        '---\nsledvashto: "David waits — he said "we are on a draft" — so nothing is sent"\n---\n')
    assert fm["sledvashto"].endswith("so nothing is sent")
    assert "we are on a draft" in fm["sledvashto"]


def test_both_a_hash_and_an_inner_quote_survive_together():
    fm = bss.parse_frontmatter(
        '---\nsledvashto: "issue #1 is open; he replied "not yet" on 19.09"\n---\n')
    assert fm["sledvashto"] == 'issue #1 is open; he replied "not yet" on 19.09'
