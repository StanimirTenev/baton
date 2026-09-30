"""README promises Python 3.8 or later. Found on a Mac, 2026-09-30: its system Python is
3.9.6, and `str | None` in a signature is evaluated at definition time before 3.10 -- the
SessionStart hook died with a TypeError and printed nothing, so Baton was silently absent.
On 3.8 all three hooks died (`list[str]`). And tools/baton_review.py did not even parse
before 3.12 (a backslash inside an f-string expression).

This runs on whatever Python runs the tests, so it cannot execute the code on 3.8; it
checks the two things that broke: the syntax, parsed as 3.8, and the annotations import
wherever the new annotation forms are used."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted([*(ROOT / "hooks").glob("*.py"), *(ROOT / "tools").glob("*.py")])
NEW_FORMS = re.compile(r"(:|->)\s*[^=\n]*(\b(list|dict|tuple|set|type)\[|\|\s*None|None\s*\|)")


def _version(exe):
    out = subprocess.run([exe, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                         capture_output=True, text=True)
    try:
        return tuple(int(n) for n in out.stdout.split())
    except ValueError:
        return None


def _oldest_python():
    """A real 3.8 or 3.9, if this machine has one. `ast.parse(feature_version=(3, 8))` on a
    newer Python does NOT reject a backslash inside an f-string expression (PEP 701 grammar):
    the check written that way passed with the 3.12-only line put back.

    Asked for its version, not found by name: on a Mac the system 3.9 is plain `python3`, and
    a search for `python3.9` skipped this check exactly where it matters (2026-09-30)."""
    names = ["python3.8", "python3.9", "python3", "python"]
    found = [shutil.which(n) for n in names]
    if shutil.which("uv"):
        for v in ("3.8", "3.9"):
            r = subprocess.run(["uv", "python", "find", "--no-python-downloads", v],
                               capture_output=True, text=True)
            found.append(r.stdout.strip() if r.returncode == 0 else None)
    for exe in filter(None, found):
        v = _version(exe)
        if v and (3, 8) <= v < (3, 10):
            return exe
    return None


def test_every_file_compiles_under_the_oldest_python_promised():
    exe = _oldest_python()
    if not exe:
        pytest.skip("no Python 3.8 or 3.9 on this machine -- this check did NOT run")
    out = subprocess.run([exe, "-m", "py_compile", *map(str, FILES)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_new_annotation_forms_come_with_the_future_import(path):
    src = path.read_text(encoding="utf-8")
    if NEW_FORMS.search(src):
        assert "from __future__ import annotations" in src, path.name
