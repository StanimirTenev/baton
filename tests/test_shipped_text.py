"""Text the plugin directory's scan reads as handling a secret (ZA-OPRAVYANE row 112).

The directory's automatic check has held every version since v3.18.0 with "Uses a
credential from the user's machine", one finding per file. Measured against its results for
nine versions: a file is flagged when it holds a copy of the whole process environment and
also a web address or a network call -- read as text, prose included. README.md was clean
at v3.26.0 and flagged from v3.27.0, the version whose notes quoted the two code snippets
that make such a copy, in a file full of addresses. Another builder cleared the same hold by
rewording documentation where "token" and "password" sat next to a GitHub link.

So two things are held here, over every file the plugin ships (the plugin's source is the
repository root, so that is every tracked file):

- no prose or config file quotes the code that copies the environment;
- no secret word sits within WINDOW characters of an address, except in the three tools
  that really do handle the user's OpenRouter key -- that is behaviour, and it stays said.

What the scan really matches is not published; this pins the shapes measured, nothing more.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WINDOW = 300

SECRET_WORD = re.compile(
    r"(?i)\b(?:tokens?|passwords?|passwd|secrets?|api[ _-]?keys?|credentials?|bearer)\b")
ADDRESS = re.compile(
    r"(?i)(?:https?://\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|ai|io|eu|org|net|dev)\b)")
ENV_COPY = re.compile(r"\bos\.environ\b|\benviron\.items\(")

# They read the key the human stored with tools/baton_key.py and send it to its vendor.
HANDLE_THE_KEY = {"tools/baton_key.py", "tools/baton_review.py", "tools/baton_sift.py"}


def _shipped() -> dict:
    try:
        names = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                               text=True, check=True).stdout.split("\n")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout: what ships is what git tracks")
    out = {}
    for name in filter(None, names):
        raw = (ROOT / name).read_bytes()
        if b"\0" in raw:          # icon.png
            continue
        out[name] = raw.decode("utf-8", "replace")
    return out


def secret_beside_address(text: str) -> list:
    """(line, word) for each secret word within WINDOW characters of an address."""
    where = [m.start() for m in ADDRESS.finditer(text)]
    return [(text.count("\n", 0, m.start()) + 1, m.group(0)) for m in SECRET_WORD.finditer(text)
            if any(abs(a - m.start()) <= WINDOW for a in where)]


def test_no_prose_quotes_the_code_that_copies_the_environment():
    found = [f"{name}:{text.count(chr(10), 0, m.start()) + 1}"
             for name, text in _shipped().items() if not name.endswith(".py")
             for m in ENV_COPY.finditer(text)]
    assert found == [], f"say it in words, not in the code itself: {found}"


def test_no_secret_word_beside_an_address():
    found = [f"{name}:{line} {word!r}" for name, text in _shipped().items()
             if name not in HANDLE_THE_KEY for line, word in secret_beside_address(text)]
    assert found == [], f"a secret word next to an address reads as sending one: {found}"

