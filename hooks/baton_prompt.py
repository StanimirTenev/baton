#!/usr/bin/env python3
"""Baton UserPromptSubmit hook.

When a message names a known task -- its folder, or one of the `aliases` in its logbook
header -- the agent is told so before it acts: which task, the date of its last entry, and
its next step, with the instruction to read the logbook first.

Why it exists (2026-09-28): asked about the scanner, the agent proposed reviewing 42
candidates that had been reviewed two days earlier. It had read one entry of the logbook.
The folder is `qrp-kachestvo`; the message said "скенера". A reminder that fires on the
folder name alone would have been silent, so tasks carry aliases in any alphabet, and a
word meets its ending halfway: the first five letters of a word of five or more, the whole
word if shorter.

It is mechanical on purpose -- string matching, no judgement, no network. Deciding whether
a conversation has become a task is the job of the `baton-task` skill; this only makes
sure the record is on the table when a task is named. Once per task per session, and
silent when nothing is named: a reminder that fires on every message is not read.

It must never block or break a prompt: it always exits 0, and any failure is silence.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

MAX_TASKS = 3
_WORD = re.compile(r"\w+", re.UNICODE)


def config() -> tuple[Path, str]:
    """Task root and logbook name -- the same resolution as the other two hooks."""
    cfg = {}
    try:
        cfg = json.loads((Path(__file__).with_name("baton.local.json")).read_text("utf-8-sig"))
    except Exception:
        cfg = {}
    home = os.environ.get("BATON_HOME") or cfg.get("home") or str(Path.home() / "tasks")
    logbook = os.environ.get("BATON_LOGBOOK") or cfg.get("logbook") or "LOGBOOK.md"
    return Path(home).expanduser(), logbook


def header(text: str) -> dict:
    """The few header fields this hook reads. Not YAML: `key: value`, `[a, b]` lists."""
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    out = {}
    for line in parts[1].splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        value = value.split(" #", 1)[0].strip()
        if value.startswith("[") and value.endswith("]"):
            out[key.strip()] = [v.strip().strip("\"'") for v in value[1:-1].split(",") if v.strip()]
        else:
            out[key.strip()] = value.strip("\"'")
    return out


_PARSE = None


def _parse(text: str) -> dict:
    """SessionStart's parser when it is next to this file (repository and install alike), so
    `next`/`sledvashto` and every other synonym mean one thing in every hook; the small local
    reader otherwise. Never a reason to fail the prompt."""
    global _PARSE
    try:
        if _PARSE is None:       # once per message, not once per task folder
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "baton_session_start", Path(__file__).with_name("baton_session_start.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _PARSE = mod.parse_frontmatter
        return _PARSE(text)
    except Exception:
        return header(text)


def names_of(folder: Path, head: dict) -> list[str]:
    aliases = head.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    return [folder.name] + [a for a in aliases if a]


def _word_matches(alias_word: str, prompt_words: list) -> bool:
    """Meet the ending halfway. A long word: the same first five letters. A short one:
    a prompt word that starts with it and adds at most three letters (шина -> шината),
    so `jev` still does not fire on `jewelry` and `rsa` not on `rsasomething`."""
    if len(alias_word) >= 5:
        return any(w[:5] == alias_word[:5] for w in prompt_words if len(w) >= 5)
    return any(w.startswith(alias_word) and len(w) - len(alias_word) <= 3 for w in prompt_words)


def matches(name: str, prompt_text: str, prompt_words: list) -> bool:
    """A folder name matches as a whole token; an alias matches when all its words do."""
    if "-" in name and name.lower() in prompt_text.lower():
        return True
    words = [w for w in _WORD.findall(name.replace("-", " ").lower()) if len(w) >= 3]
    return bool(words) and all(_word_matches(w, prompt_words) for w in words)


def last_entry(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("## "):
            return line[3:].strip()
    return ""


def touched(root: Path, logbook: str, prompt: str) -> list[tuple[str, str, str]]:
    """(task, last entry heading, next step) for every task the message names."""
    found = []
    ps = _WORD.findall(prompt.lower())
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        book = folder / logbook
        if not book.is_file():
            continue
        try:
            text = book.read_text("utf-8-sig")
        except OSError:
            continue
        head = _parse(text)
        if any(matches(n, prompt, ps) for n in names_of(folder, head)):
            found.append((folder.name, last_entry(text), str(head.get("sledvashto", ""))))
    return found


def _state(session: str) -> Path:
    base = Path(os.environ.get("BATON_STATE_DIR") or tempfile.gettempdir())
    safe = "".join(ch for ch in session if ch.isalnum() or ch in "-_")[:80] or "nosession"
    return base / f"baton-prompt-{safe}.json"


def main() -> int:
    # Bytes, decoded as UTF-8 -- not `sys.stdin.read()`. On Windows a redirected stdin is
    # decoded in the locale code page (cp1251), so "за скенера" arrived as mojibake and
    # matched nothing: 0 bytes out on the Windows machine, 2026-09-28.
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except Exception:
        return 0
    prompt = str(payload.get("prompt") or "")
    session = str(payload.get("session_id") or "")
    if not prompt.strip():
        return 0
    root, logbook = config()
    if not root.is_dir():
        return 0
    try:
        seen = set(json.loads(_state(session).read_text("utf-8")))
    except Exception:
        seen = set()
    new = [t for t in touched(root, logbook, prompt) if t[0] not in seen][:MAX_TASKS]
    if not new:
        return 0
    lines = ["Baton: this message touches a task with a record. Read its logbook -- the "
             "entries on this topic, not only the top one -- before proposing or acting:"]
    for name, entry, nxt in new:
        lines.append(f"  - {name}: last entry \"{entry}\"" + (f"; next: {nxt}" if nxt else ""))
    sys.stdout.buffer.write(("\n".join(lines) + "\n").encode("utf-8"))   # same reason, outbound
    sys.stdout.flush()
    try:
        path = _state(session)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(seen | {t[0] for t in new})), "utf-8")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # A hook must never break the session it is trying to help -- and exit 2 would
        # block the user's message outright.
        sys.exit(0)
