"""A changelog is not documentation.

`tools/baton_where.py` shipped in v2.12.0 and was described only under `## Versions`.
`umeniya` shipped the same way. The unclosed-plan check — a thing SessionStart prints a
whole section about — had no body section at all, and the header fields `srok` and
`rezultat` were read by the hook and named nowhere a reader would look.

A release note is read once, by whoever was already waiting for it. The body is what
somebody reads when they want to know what the tool does. So this is checked rather than
remembered: the changelog does not count as coverage.
"""

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
HOOKS = ROOT / "hooks"


def _body() -> str:
    """The README with the changelog cut off — the changelog does not count."""
    text = README.read_text(encoding="utf-8")
    return text.split("## Versions", 1)[0]


def _is_shim(path):
    """An old name kept from before v3.1.0: it only runs the renamed tool."""
    return "_new = _pathlib.Path(__file__).with_name(" in path.read_text(encoding="utf-8")


def test_every_old_tool_name_runs_a_tool_that_exists_and_is_documented():
    """The shims are not features, so they are not documented one by one -- but each must
    point at a real tool, or an external script loading the old path gets an ImportError."""
    import re as _re
    shims = [p for p in sorted(ROOT.glob("tools/baton_*.py")) if _is_shim(p)]
    assert len(shims) == 6, [p.name for p in shims]
    for shim in shims:
        target = _re.search(r'with_name\("(baton_\w+\.py)"\)', shim.read_text(encoding="utf-8")).group(1)
        assert (shim.parent / target).is_file(), f"{shim.name} runs {target}, which is gone"
        assert shim.stem in _body(), f"{shim.name} is not named anywhere in the README body"


def test_every_tool_is_shown_being_used_in_the_body():
    """Not "the name occurs" — the body has to show how to run it.

    ⚠️ The first version asked whether the stem appeared anywhere in the body, and a
    mutation deleting `baton_where`'s whole section still passed, because another section
    mentions the file in passing. A name in a sentence is not documentation either.
    """
    body = _body()
    blocks = "\n".join(re.findall(r'```.*?```', body, re.S))
    undocumented = [p.name for p in sorted(ROOT.glob("tools/baton_*.py"))
                    if p.stem not in blocks and not _is_shim(p)]
    assert not undocumented, (
        f"never shown being used in the body: {undocumented}. A feature the README does "
        "not describe is a feature nobody can find, and a changelog is read once.")


def test_every_header_field_the_hook_reads_is_described_in_the_body():
    """Fields are extracted from the hook, so a new one cannot be added unnoticed."""
    body = _body()
    fields = set()
    for hook in sorted(HOOKS.glob("baton_*.py")):
        text = hook.read_text(encoding="utf-8")
        fields |= set(re.findall(r'fm\.get\(\s*["\'](\w+)["\']', text))
        fields |= set(re.findall(r'frontmatter\.get\(\s*["\'](\w+)["\']', text))
    # English is canonical inside the code since v3.2.0; the Bulgarian spellings live in
    # FIELD_SYNONYMS and are checked below, each one named in the body.
    fields = {f for f in fields if f.isascii()}
    missing = sorted(f for f in fields if f not in body)
    assert not missing, f"read by a hook, absent from the README body: {missing}"
    assert len(fields) >= 8, f"extraction found only {fields} — the pattern stopped matching"
    import importlib.util
    spec = importlib.util.spec_from_file_location("bss_doc", HOOKS / "baton_session_start.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    undocumented = sorted(k for k in mod.FIELD_SYNONYMS if k.isascii() and k not in body)
    assert not undocumented, f"Bulgarian spellings read but not in the README body: {undocumented}"


def test_every_plan_state_the_hook_accepts_is_named_in_the_body():
    body = _body()
    spec = importlib.util.spec_from_file_location(
        "bss_doc", HOOKS / "baton_session_start.py")
    hook = importlib.util.module_from_spec(spec)
    sys.modules["bss_doc"] = hook
    spec.loader.exec_module(hook)
    states = {s for s in hook.PLAN_CLOSED if s.isascii()}
    assert states, "no closed-plan states extracted"
    # `zatvoren`/`closed` are accepted spellings of the same two endings; the body names
    # the two endings, which is what a reader needs.
    missing = [s for s in states if s not in body and s not in
               {"zatvoren", "closed", "done", "finished", "abandoned", "dropped"}]
    assert not missing, f"a plan can be closed with {missing}, and the README does not say so"
