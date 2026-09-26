"""A changelog is not documentation.

`tools/baton_kade.py` shipped in v2.12.0 and was described only under `## Versions`.
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


def test_every_tool_is_shown_being_used_in_the_body():
    """Not "the name occurs" — the body has to show how to run it.

    ⚠️ The first version asked whether the stem appeared anywhere in the body, and a
    mutation deleting `baton_kade`'s whole section still passed, because another section
    mentions the file in passing. A name in a sentence is not documentation either.
    """
    body = _body()
    blocks = "\n".join(re.findall(r'```.*?```', body, re.S))
    undocumented = [p.name for p in sorted(ROOT.glob("tools/baton_*.py"))
                    if p.stem not in blocks]
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
    # English and Cyrillic spellings of the same field are aliases, documented as such
    # rather than as fields of their own.
    aliases = {"result", "skills", "state", "next", "priority", "deadline", "done"}
    fields = {f for f in fields if f.isascii()} - aliases
    missing = sorted(f for f in fields if f not in body)
    assert not missing, f"read by a hook, absent from the README body: {missing}"
    assert len(fields) >= 8, f"extraction found only {fields} — the pattern stopped matching"


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
