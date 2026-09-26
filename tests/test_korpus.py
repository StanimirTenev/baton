"""The corpus module: one owner for the five kinds, and a scope that must be said.

Both halves of this file exist because of a measured failure, not an imagined one.

`kind()` was declared twice -- here and in a corpus builder outside the repository --
with two sets of regular expressions. Nothing had broken, which is how that ends:
one copy is fixed, the other is not, and both keep returning something plausible.
`test_kind_has_exactly_one_owner` is what stops it coming back.

`Scope` refuses `None` because on 2026-09-26 an undeclared exclusion took one corpus
from 9 duplicate-state hits to 100, and an undeclared *inclusion* put 878 of 2131
passages of imported foreign material into an edge-detection corpus -- roughly 50%
false positives on two of three detectors, and the corpus was the reason.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bkorpus = _load("baton_korpus")
bkade = _load("baton_kade")

HEADER = '---\nsastoyanie: aktivna\nsledvashto: "the price is €2 500"\n---\n\n'
ENTRY = "## 2026-09-20 10:00 — an entry\n\nthe price was €650 back then\n"


def _tree(tmp_path: Path) -> Path:
    task = tmp_path / "pricing"
    task.mkdir()
    (task / "LOGBOOK.md").write_text(HEADER + ENTRY, encoding="utf-8")
    (task / "SPEC.md").write_text("# Spec\n\n" + "Price — ACCEPTED: €650 a year. " * 8,
                                  encoding="utf-8")
    (task / "FAKTI.md").write_text(
        "| 1.1 | a claim long enough to pass the eighty character floor this row has | P |\n",
        encoding="utf-8")
    (task / "STATE_21_09.md").write_text("# Then\n\n" + "the price then was €650. " * 8,
                                         encoding="utf-8")
    vendored = task / "docs"
    vendored.mkdir()
    (vendored / "README.md").write_text("# Imported\n\n" + "somebody else wrote this. " * 8,
                                        encoding="utf-8")
    return tmp_path


# --- one owner --------------------------------------------------------------

def test_kind_has_exactly_one_owner():
    """Not "they agree" -- the SAME function object. Agreement is what rots."""
    assert bkade.kind is bkorpus.kind
    for attribute in ("ENTRY", "REGISTERS", "DATED_NAME", "SKIP"):
        assert getattr(bkade, attribute) is getattr(bkorpus, attribute), attribute


def test_the_five_kinds_are_still_the_five_kinds():
    assert bkorpus.kind(Path("FAKTI.md"), 0, "| x | P |", "LOGBOOK.md")[0] == "CLAIM"
    assert bkorpus.kind(Path("STATE_21_09.md"), 0, "t", "LOGBOOK.md")[0] == "SNAPSHOT"
    assert bkorpus.kind(Path("x_istoria.md"), 0, "t", "LOGBOOK.md")[0] == "SNAPSHOT"
    text = HEADER + ENTRY
    assert bkorpus.kind(Path("LOGBOOK.md"), text.index("€2 500"), text,
                        "LOGBOOK.md")[0] == "HEADER"
    assert bkorpus.kind(Path("LOGBOOK.md"), text.index("€650"), text,
                        "LOGBOOK.md")[0] == "RECORD"
    assert bkorpus.kind(Path("SPEC.md"), 0, "t", "LOGBOOK.md")[0] == "LIVE"


# --- the scope must be said out loud ----------------------------------------

def test_a_scope_of_none_is_refused():
    """The whole point of the class. An exclusion nobody stated is the defect."""
    with pytest.raises(ValueError, match="declare the scope"):
        bkorpus.Scope(None)


def test_an_empty_scope_is_allowed_because_it_is_an_explicit_decision():
    assert bkorpus.Scope([]).holds(Path("/a"), Path("/a/b/c.md"))


def test_walk_refuses_anything_that_is_not_a_scope(tmp_path):
    """Measured lesson: a check that is written and never called is worse than none."""
    for wrong in (None, ["docs"], "docs"):
        with pytest.raises(ValueError, match="pass a Scope"):
            list(bkorpus.walk([tmp_path], wrong))


def test_a_bare_name_excludes_that_directory_anywhere(tmp_path):
    scope = bkorpus.Scope(["docs"])
    assert not scope.holds(tmp_path, tmp_path / "t" / "docs" / "a.md")
    assert scope.holds(tmp_path, tmp_path / "t" / "SPEC.md")


def test_a_pattern_with_a_slash_is_matched_against_the_relative_path(tmp_path):
    scope = bkorpus.Scope(["*/razuznavane/*"])
    assert not scope.holds(tmp_path, tmp_path / "t" / "razuznavane" / "raw.md")
    assert scope.holds(tmp_path, tmp_path / "razuznavane.md")


def test_the_scope_is_actually_applied_not_merely_defined(tmp_path):
    """Mutation caught this class of bug once already in `baton_kade`.

    Testing `Scope.holds` and testing that `chunks` calls it are different things.
    """
    root = _tree(tmp_path)
    inside = {source for _, source, _ in
              bkorpus.chunks([root], bkorpus.Scope(["docs"]), "LOGBOOK.md")}
    assert not [s for s in inside if s.startswith("docs/")], inside
    everything = {source for _, source, _ in
                  bkorpus.chunks([root], bkorpus.Scope([]), "LOGBOOK.md")}
    assert [s for s in everything if s.startswith("docs/")], everything


def test_batonignore_is_honoured_because_the_calibration_assumed_it(tmp_path):
    task = tmp_path / "t"
    (task / "razuznavane").mkdir(parents=True)
    (task / ".batonignore").write_text("razuznavane/*\n", encoding="utf-8")
    (task / "razuznavane" / "raw.md").write_text("# Raw\n\n" + "agent output. " * 20,
                                                 encoding="utf-8")
    (task / "SPEC.md").write_text("# Spec\n\n" + "our own writing. " * 20, encoding="utf-8")
    sources = {s for _, s, _ in bkorpus.chunks([tmp_path], bkorpus.Scope([]), "LOGBOOK.md")}
    assert "t/SPEC.md" in sources
    assert "razuznavane/raw.md" not in sources


def test_describe_names_the_scope_so_a_number_can_carry_it():
    line = bkorpus.Scope(["docs", "sdks"]).describe()
    assert "docs" in line and "sdks" in line
    assert "nothing" in bkorpus.Scope([]).describe()


# --- the chunks ------------------------------------------------------------

def test_a_logbook_splits_into_its_header_and_one_chunk_per_entry(tmp_path):
    root = _tree(tmp_path)
    rows = [(s, w) for _, s, w in
            bkorpus.chunks([root], bkorpus.Scope(["docs"]), "LOGBOOK.md")]
    assert ("pricing/LOGBOOK.md [header]", "HEADER") in rows
    assert ("pricing/LOGBOOK.md [2026-09-20]", "RECORD") in rows


def test_every_kind_reaches_the_corpus(tmp_path):
    root = _tree(tmp_path)
    kinds = {w for _, _, w in bkorpus.chunks([root], bkorpus.Scope([]), "LOGBOOK.md")}
    assert kinds == {"LIVE", "HEADER", "RECORD", "SNAPSHOT", "CLAIM"}


def test_a_register_row_under_eighty_characters_is_not_a_chunk(tmp_path):
    task = tmp_path / "t"
    task.mkdir()
    (task / "FAKTI.md").write_text("| 1 | short |\n", encoding="utf-8")
    assert not list(bkorpus.chunks([tmp_path], bkorpus.Scope([]), "LOGBOOK.md"))
