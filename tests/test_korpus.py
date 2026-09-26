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


# --- two bugs the suite did not catch, found by reading real output ----------

def test_only_the_front_matter_of_a_memory_file_is_a_header(tmp_path):
    """Found on a real tree, not here: 478 of 1821 chunks came back HEADER.

    `chunks` asked `kind()` once per file at position 0, and every file carrying YAML
    front matter starts with `---`, so the whole file was a header. A memory file's
    body is LIVE -- it is only the front matter that claims something as a header.
    """
    task = tmp_path / "t"
    task.mkdir()
    (task / "note.md").write_text(
        '---\nname: a-note\ndescription: "the price is €2 500"\n---\n\n'
        "## First\n\n" + "body text that is long enough to be a passage. " * 4 +
        "\n\n## Second\n\n" + "more body text of a similar length here. " * 4,
        encoding="utf-8")
    rows = list(bkorpus.chunks([tmp_path], bkorpus.Scope([]), "LOGBOOK.md"))
    kinds = [what for _, _, what in rows]
    assert kinds.count("HEADER") == 1, kinds
    assert kinds.count("LIVE") == 2, kinds


def test_an_entry_heading_belongs_to_its_own_entry(tmp_path):
    """The boundary a whole-file scan never reaches.

    `kind()` compared `m.start() < position`, so a chunk beginning exactly at
    `## 2026-…` had no entry "before" it and came back LIVE. A search for a number
    inside a line never hits that offset, so nothing failed until chunks did.
    """
    text = HEADER + ENTRY
    at_heading = text.index("## 2026-09-20")
    assert bkorpus.kind(Path("LOGBOOK.md"), at_heading, text, "LOGBOOK.md")[0] == "RECORD"
    assert bkorpus.kind(Path("LOGBOOK.md"), at_heading - 1, text, "LOGBOOK.md")[0] == "LIVE"


def test_the_kinds_of_a_real_shaped_tree_are_plausible(tmp_path):
    """A count nobody sanity-checks is how the header bug survived a green suite."""
    root = _tree(tmp_path)
    kinds = [w for _, _, w in bkorpus.chunks([root], bkorpus.Scope([]), "LOGBOOK.md")]
    assert kinds.count("HEADER") == 1, "one logbook, one header"
    assert kinds.count("RECORD") == 1


# --- one reader of the config -----------------------------------------------

def test_the_installed_config_wins_over_the_repository_copy(tmp_path, monkeypatch):
    """`baton_tablo` printed "no tasks under ~/tasks" on a configured machine.

    Three readers existed for one file, in three different orders: pregled tried the
    repository copy first, kade the installed one first, and the SessionStart hook only
    the file beside its own `__file__`. The board loads that hook out of the repository,
    where `baton.local.json` deliberately is not — it names client folders and stays
    outside git.

    ⚠️ The first version of this test pinned nothing. It created only the installed file,
    so repository-first fell through to it and the mutation that reverted the order still
    passed. Both files have to exist, with different values, or the order is untested.
    """
    import json as _json
    installed = tmp_path / ".claude/baton/hooks"
    installed.mkdir(parents=True)
    (installed / bkorpus.CONFIG).write_text(
        _json.dumps({"home": str(tmp_path / "from-installed"), "logbook": "DNEVNIK.md"}),
        encoding="utf-8")
    repo_hooks = tmp_path / "repo" / "hooks"
    repo_hooks.mkdir(parents=True)
    (repo_hooks / bkorpus.CONFIG).write_text(
        _json.dumps({"home": str(tmp_path / "from-repo"), "logbook": "WRONG.md"}),
        encoding="utf-8")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(bkorpus, "__file__", str(tmp_path / "repo" / "tools" / "x.py"))
    monkeypatch.delenv("BATON_HOME", raising=False)
    monkeypatch.delenv("BATON_LOGBOOK", raising=False)
    cfg = bkorpus.config()
    assert cfg["home"] == tmp_path / "from-installed", "the installed file must win"
    assert cfg["logbook"] == "DNEVNIK.md"
    assert cfg["source"] == installed / bkorpus.CONFIG


def test_the_environment_wins_over_any_file(tmp_path, monkeypatch):
    monkeypatch.setenv("BATON_HOME", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("BATON_LOGBOOK", "JOURNAL.md")
    cfg = bkorpus.config()
    assert cfg["home"] == tmp_path / "elsewhere"
    assert cfg["logbook"] == "JOURNAL.md"


def test_with_no_file_and_no_environment_the_default_is_tasks(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("BATON_HOME", raising=False)
    monkeypatch.delenv("BATON_LOGBOOK", raising=False)
    monkeypatch.setattr(bkorpus, "__file__", str(tmp_path / "nowhere" / "x.py"))
    cfg = bkorpus.config()
    assert cfg["home"] == tmp_path / "tasks" and cfg["source"] is None


def test_every_tool_reads_the_same_config_object(tmp_path):
    """Not "they agree" — the same function. Agreement is the part that decays."""
    bkade_cfg = _load("baton_kade")
    assert bkade_cfg.korpus.config is bkorpus.config


def test_the_board_finds_the_tasks_the_config_points_at(tmp_path, monkeypatch):
    """The call site, not only the function.

    A mutation reverting `baton_tablo` to `hook.config()` broke the board and failed no
    test: the hook reads the file beside its own `__file__`, which is the repository, and
    the config is not there. Nothing here sets `BATON_HOME`, because the hook reads that
    too — the environment would hide the defect instead of exposing it.
    """
    import json as _json
    tablo = _load("baton_tablo")
    installed = tmp_path / ".claude/baton/hooks"
    installed.mkdir(parents=True)
    tasks = tmp_path / "tasks-real" / "a-task"
    tasks.mkdir(parents=True)
    (tasks / "DNEVNIK.md").write_text(
        "---\nsastoyanie: aktivna\nna_hod: nie\nsledvashto: \"next\"\nprioritet: nisak\n"
        "---\n\n## 2026-09-26 10:00 — one\n\ntext\n", encoding="utf-8")
    (installed / bkorpus.CONFIG).write_text(
        _json.dumps({"home": str(tmp_path / "tasks-real"), "logbook": "DNEVNIK.md"}),
        encoding="utf-8")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("BATON_HOME", raising=False)
    monkeypatch.delenv("BATON_LOGBOOK", raising=False)
    out = tmp_path / "board.html"
    assert tablo.main(["--out", str(out)]) == 0, "the board found no tasks"
    assert "a-task" in out.read_text(encoding="utf-8")
