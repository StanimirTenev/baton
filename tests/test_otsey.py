"""Reading order, not a right of exclusion.

Every test here pins the one property that matters: a candidate below the threshold is
still in the output. The failure it prevents was made four times in a single day on this
machine — a search reported as "found X" when the truth was "did not look at the rest".

The measured numbers in the tool's docstring come from a hand-labelled run of 40 GitHub
repositories on 2026-09-26: 0 false positives among 11 hand-labelled NOs, and all 21 YESes
inside the top 25 once sorted. Two of the three disagreements were the labeller's fault.
"""

import importlib.util
import io
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "tools" / "baton_otsey.py"
spec = importlib.util.spec_from_file_location("bo", TOOL)
bo = importlib.util.module_from_spec(spec)
sys.modules["bo"] = bo
spec.loader.exec_module(bo)

SCORED = [("alpha", "t", 0.91), ("beta", "t", 0.55), ("gama", "t", 0.12), ("delta", "t", 0.40)]


class _Fake:
    """Stands in for `baton_pregled`: no key, no network, no spend."""

    def __init__(self, scores, confidential=()):
        self.scores, self.confidential, self.asked = scores, set(confidential), []

    def klyuch(self):
        return "k"

    def config(self):
        return {"poveritelni": ["darmi", "дарми"]}

    def poveritelno(self, text, ident, words):
        """Same shape as the real one: it reads the TEXT for a word, and the id too.

        ⚠️ The first version of this fake looked only at `ident`, so a test about a
        confidential word in the question passed against the fake and would have
        failed against the real barrier. A stand-in that is laxer than the thing it
        stands for turns a test into a formality.
        """
        if ident in self.confidential:
            return ident
        return next((w for w in words if w in (text or "")), None)

    def pitay(self, key, state, questions, label, words):
        self.asked.append((label, questions["otsey"]["instructions"]))
        return {"answers": {"otsey": {"noul": self.scores[label]}},
                "usage": {"cost": 0.0001}}


# --- the whole point --------------------------------------------------------

def test_nothing_below_the_threshold_is_dropped():
    out = io.StringIO()
    order = bo.report(SCORED, 0.5, "q", 0.001, 0, stream=out)
    assert len(order) == len(SCORED), "the returned list must hold every candidate"
    text = out.getvalue()
    for ident in ("alpha", "beta", "gama", "delta"):
        assert ident in text, f"{ident} vanished from the report"
    assert "READ AFTER" in text and "nothing is dropped" in text


def test_the_report_says_a_low_score_means_unread_not_absent():
    out = io.StringIO()
    bo.report(SCORED, 0.5, "q", 0.001, 0, stream=out)
    assert "nobody" in out.getvalue() and "has read yet" in out.getvalue(), (
        "the report must say what a low score is NOT")


def test_the_threshold_travels_with_the_numbers():
    out = io.StringIO()
    bo.report(SCORED, 0.42, "q", 0.001, 0, stream=out)
    assert "threshold 0.42" in out.getvalue()


def test_without_a_threshold_the_whole_list_comes_back_in_order():
    out = io.StringIO()
    bo.report(SCORED, None, "q", 0.0, 0, stream=out)
    body = out.getvalue()
    assert "no threshold given" in body
    assert body.index("alpha") < body.index("beta") < body.index("delta") < body.index("gama")


def test_the_order_is_by_score_not_by_input():
    order = bo.report(SCORED, None, "q", 0.0, 0, stream=io.StringIO())
    assert [i for i, _t, _s in order] == ["alpha", "beta", "delta", "gama"]


# --- the question is required -----------------------------------------------

def test_a_score_with_no_question_is_refused():
    for empty in (None, "", "   "):
        with pytest.raises(ValueError, match="a typed question"):
            bo.otsey([("a", "t")], empty, bp=_Fake({}))


def test_the_question_reaches_every_candidate_unchanged():
    fake = _Fake({"a": 0.5, "b": 0.5})
    bo.otsey([("a", "t"), ("b", "t")], "  Does it ship a scanner?  ", bp=fake)
    assert {q for _l, q in fake.asked} == {"Does it ship a scanner?"}


# --- the confidentiality barrier --------------------------------------------

def test_a_confidential_candidate_is_kept_and_marked_never_sent():
    fake = _Fake({"public": 0.8}, confidential={"secret"})
    scored, spent, held = bo.otsey([("public", "t"), ("secret", "t")], "q", bp=fake)
    assert held == 1
    assert [label for label, _q in fake.asked] == ["public"], "it must not be sent"
    assert ("secret", "t", -1.0) in scored, "and it must not vanish either"
    out = io.StringIO()
    bo.report(scored, 0.5, "q", spent, held, stream=out)
    assert "secret" in out.getvalue() and "confidential" in out.getvalue()


# --- input handling ---------------------------------------------------------

def test_blank_lines_and_comments_are_not_candidates():
    rows = list(bo.kandidati(["a\tone\n", "\n", "# note\n", "b\ttwo\n", "   \n"]))
    assert [i for i, _t in rows] == ["a", "b"]


def test_every_column_reaches_the_text_so_nothing_judged_is_unseen():
    rows = list(bo.kandidati(["repo\tdescription here\tGo\t12\n"]))
    ident, text = rows[0]
    assert ident == "repo"
    for part in ("description here", "Go", "12"):
        assert part in text, f"{part!r} was dropped from what gets judged"


def test_a_confidential_question_is_refused_before_any_candidate_is_scored():
    """The question is asked of every candidate, so it is checked once, up front.

    Found while reproducing an external review of v2.14.0: `pitay` read only `state`
    and the label, so a confidential term living only in `questions` reached the wire.
    That is fixed at the sending function. This is the second half — refusing here says
    what is wrong, instead of dying on candidate one after the run has begun.
    """
    fake = _Fake({"a": 0.5, "b": 0.5})
    with pytest.raises(ValueError, match="does not leave the machine"):
        bo.otsey([("a", "t"), ("b", "t")], "Does this mention the darmi outage?", bp=fake)
    assert not fake.asked, "not a single candidate may be scored"
