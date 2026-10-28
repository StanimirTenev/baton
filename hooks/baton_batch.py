#!/usr/bin/env python3
"""Baton -- PostToolBatch hook: lesson L2, an empty result is a failed read.

The most frequent mistake in a month of logbooks was not a wrong command. It was the
sentence written after an empty result: "the section does not exist", "nobody records
that", "0 downloads" -- each a page that had not finished loading, a search that matched
nothing, a query that returned `[]`. Ten dated cases in one week, written down as a lesson
three times, back after each (2026-09-19..26).

The mistake comes after the tool call, so this is the one lesson where a hook that runs
after the call is in time: its note reaches the agent before the next sentence is written.
It fires only for reads (web, MCP, and shell commands that search or fetch), says one line
at most once every SHOW_EVERY_MINUTES, and counts every time the situation arose. It never
blocks anything.
"""
from __future__ import annotations   # Python 3.8 and 3.9 too

import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

SHOW_EVERY_MINUTES = 30
READ_VERBS = re.compile(
    r"\b(grep|rg|find|findstr|select-string|curl|wget|jq|gh|search|eval|text|dir|ls|"
    r"get-childitem|test-path)\b", re.I)
# The body of a heredoc is text the command carries, not the command. 2026-10-12, a replay of
# 9,908 recorded Bash calls: at least 28 of L2's 120 fires were logbook entries written through
# a heredoc that mentioned grep or gh.
HEREDOC_BODY = re.compile(r"(<<-?\s*(['\"]?)(\w+)\2[^\n]*)\n.*?\n[ \t]*\3[ \t]*(?=\n|$)", re.S)
# A quoted script or string handed to a command that only carries it -- a `sed` script, an
# `echo`, a `python3 -c` body -- is text the same way. 2026-10-20, the same replay: 6 of L2's 81
# fires had their verb only there. Left alone: quotes another command runs (`ssh host 'ls'`,
# `bash -c "grep x"`), and a `$( )` inside double quotes, which the shell does run.
QUOTED = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"", re.S)
CARRIER = re.compile(r"(?:^|[|;&(\n])\s*(?:\w+=\S*\s+)*(?:sed|echo|printf|awk|perl|python[\d.]*)\b"
                     r"[^|;&(\n]*$")
SUBST = re.compile(r"\$\([^)]*\)|(?<!\\)`[^`]*(?<!\\)`")      # \` is a literal backtick
EMPTY = {"", "[]", "{}", '""', "''", "0", "null", "none", "(bash completed with no output)",
         "(no output)", "no matches found", "no files found"}


def _text(response) -> str:
    """What the agent saw: a string, or content blocks whose text is joined."""
    if isinstance(response, str):
        return response
    if isinstance(response, list):
        return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in response)
    if isinstance(response, dict):
        return str(response.get("stdout", response.get("text", json.dumps(response))))
    return str(response)


# An MCP tool is a read only when its own name says so. 2026-10-01, external review of
# v3.10.0: every `mcp__*` counted as a read, so `mcp__files__delete` answering `{}` raised
# L2 and counted it. A write, or a name that says neither, is left alone.
MCP_READ = {"search", "query", "get", "list", "read", "fetch", "find", "lookup", "view",
            "download", "describe", "show", "scan", "export"}
MCP_WRITE = {"create", "update", "delete", "set", "send", "label", "unlabel", "trash",
             "untrash", "mark", "unmark", "share", "copy", "move", "publish", "reply",
             "forward", "apply", "remove", "add", "write", "edit", "respond"}


def _carried(command: str) -> str:
    """The command without the quoted text its sed/echo/printf/awk/perl/python carries."""
    out, last = [], 0
    for m in QUOTED.finditer(command):
        out.append(command[last:m.start()])
        last = m.end()
        text = m.group()
        if CARRIER.search("".join(out)):
            text = " ".join(SUBST.findall(text)) if text.startswith('"') else ""
        out.append(text)
    out.append(command[last:])
    return "".join(out)


def is_read(call: dict) -> bool:
    tool = str(call.get("tool_name", ""))
    if tool in ("WebFetch", "WebSearch", "Grep", "Glob"):
        return True
    if tool.startswith("mcp__"):
        words = set(re.split(r"[_\-]+", tool.rsplit("__", 1)[-1].lower()))
        return bool(words & MCP_READ) and not words & MCP_WRITE
    if tool in ("Bash", "PowerShell"):
        command = HEREDOC_BODY.sub(r"\1", str((call.get("tool_input") or {}).get("command", "")))
        return bool(READ_VERBS.search(_carried(command)))
    return False


def is_empty(call: dict) -> bool:
    text = _text(call.get("tool_response")).strip().strip("`").strip()
    return text.lower() in EMPTY


# An error that came back instead of a result is a failed read as well (ZA-OPRAVYANE row 39,
# Oliver Veits, 22.10: `grep: nofile.txt: No such file or directory` passed unseen). Kept narrow:
# a short result whose every line is an error line. A result that carries anything else -- a
# grep hit that mentions "not found", pytest output, a listing with one `ls:` complaint in it --
# is left alone, and so is `ls`/`stat` saying a path is not there: that is the check for absence
# itself, not a read that failed (2026-10-22: 4 of the first 16 fires on recorded reads). A
# half-loaded page that returns navigation text is still not seen.
ERROR_LINE = re.compile(
    r"(?i)^(?:exit code \d+"
    r"|(?!(?:ls|stat|dir): )(?:[\w./~-]+: )+.*\b(?:no such file or directory|permission denied"
    r"|cannot open\b.*|command not found|not a git repository\b.*|could not resolve host\b.*)"
    r"|(?:error|fatal)(?: \d{3})?:.*"
    r"|curl: \(\d+\).*"
    r"|.*\bhttp(?:/\d(?:\.\d)?)? [45]\d\d\b.*"
    r"|the response body was not retrieved\b.*"
    r"|[45]\d\d:? (?:not found|forbidden|unauthorized|bad request|internal server error|"
    r"bad gateway|service unavailable|too many requests|gone)\.?"
    r"|(?:page )?not found\.?"
    r"|getaddrinfo enotfound .*)\s*$")
ERROR_MAX_CHARS, ERROR_MAX_LINES = 400, 4


def is_error(call: dict) -> bool:
    """An error message where the result should be: short, and every line an error line, at least
    one of them more than an exit code."""
    text = _text(call.get("tool_response")).strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines or len(lines) > ERROR_MAX_LINES or sum(map(len, lines)) > ERROR_MAX_CHARS:
        return False
    if all(re.match(r"(?i)exit code \d+$", ln) for ln in lines):
        return False                        # a process killed or ended, with nothing said
    return all(ERROR_LINE.match(ln) for ln in lines)


def _ss():
    spec = importlib.util.spec_from_file_location(
        "baton_session_start", Path(__file__).with_name("baton_session_start.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Does the note change what comes next? (ZA-OPRAVYANE row 40, 22.10.) After a shown note this
# session's next batch is looked at: a read in it counts `checked_after`; anything else, or the
# turn ending first (Stop), counts `no_check_after`. A proxy, not proof: the second read may have
# been planned anyway, and a sentence written without one may be right.
def _pending(session: str) -> Path:
    # Not the shared temp folder (row 53): beside Baton's other state, as in Stop and the prompt hook.
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    base = Path(os.environ.get("BATON_STATE_DIR")
                or (Path(data) if data else Path(__file__).resolve().parent) / "sessions")
    safe = "".join(ch for ch in session if ch.isalnum() or ch in "-_")[:80] or "nosession"
    return base / f"baton-l2-{safe}.json"


def followed(session: str, calls: list | None, ss=None, state=None) -> bool:
    """Count what came after a shown note in this session, once. `calls` None: the turn ended."""
    path = _pending(session)
    if not path.is_file():
        return False
    try:
        path.unlink()
    except OSError:
        return False
    own = state is None
    ss = ss or _ss()
    state = ss.lessons_load() if own else state
    checked = bool(calls) and any(isinstance(c, dict) and is_read(c) for c in calls)
    ss.lesson_event(state, "L2", "checked_after" if checked else "no_check_after")
    if own:
        ss.lessons_save(state)
    return True


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):     # `[]`, `null`: no payload, not a crash (row 67)
        return 0
    _turn("PostToolBatch", payload.get("session_id"))
    calls = payload.get("tool_calls")
    calls = [c for c in calls if isinstance(c, dict)] if isinstance(calls, list) else []
    session = str(payload.get("session_id") or "")
    failed = [(c, "empty" if is_empty(c) else "error") for c in calls
              if is_read(c) and (is_empty(c) or is_error(c))]
    if not failed and not _pending(session).is_file():
        return 0
    try:
        ss = _ss()
        if ss.installed_twice():
            return 0
        now = datetime.now()
        state = ss.lessons_load()
        followed(session, calls, ss, state)
        if not failed:
            ss.lessons_save(state)
            return 0
        for _ in failed:
            rec = ss.lesson_event(state, "L2", "fired", now)
        shown = rec.get("last_shown", "")
        if shown and shown > (now - timedelta(minutes=SHOW_EVERY_MINUTES)).isoformat(timespec="minutes"):
            ss.lessons_save(state)
            return 0
        # `shown` and what came after are counted from v3.20.0 on, `fired` from earlier. Each says
        # its own start: a register from before reads "fired 147 since 3 Oct", not "shown 0 of 147".
        rec.setdefault("shown_since", now.isoformat(timespec="minutes"))
        ss.lesson_event(state, "L2", "shown", now)
        ss.lessons_save(state)
        try:
            path = _pending(session)
            path.parent.mkdir(parents=True, exist_ok=True)
            with os.fdopen(os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w",
                           encoding="utf-8") as f:
                f.write(now.isoformat(timespec="seconds"))
        except OSError:
            pass          # the measure is a courtesy; the note still goes out
        what = " and ".join(dict.fromkeys("an empty result" if k == "empty" else
                                          "an error instead of a result" for _, k in failed))
        tools = ", ".join(sorted({str(c.get("tool_name")) for c, _ in failed}))
        after = rec.get("checked_after", 0) + rec.get("no_check_after", 0)
        note = (f"Baton, lesson L2 -- {what} just came back ({tools}). {ss.LESSONS['L2']} "
                f"(Counted since {rec['shown_since']}: shown {rec.get('shown', 0)}, followed by a "
                f"check {rec.get('checked_after', 0)} of {after}; fired {rec.get('fired', 0)} "
                f"since {rec.get('since', '?')}.)")
    except Exception:
        return 0              # a lesson that cannot count must not cost the session
    sys.stdout.buffer.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolBatch", "additionalContext": note}},
        ensure_ascii=False).encode("utf-8"))
    sys.stdout.flush()
    return 0


def _turn(event: str, session: object, extra: str = "") -> None:
    """One line in `baton.turns/<session>` per run: the time, the event and `extra` (row 49). The
    doctor asks of it, per session, whether the last activity was followed by a Stop or a
    StopFailure. Never raises."""
    try:
        sid = re.sub(r"[^\w-]", "", str(session or ""))[:80]
        if not sid:
            return
        data = os.environ.get("CLAUDE_PLUGIN_DATA")
        folder = (Path(data) if data else Path(__file__).resolve().parent) / "baton.turns"
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / sid, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat()} {event} {extra}".rstrip() + "\n")
    except Exception:
        pass


def _load_baton():
    try:
        spec = importlib.util.spec_from_file_location(
            "_baton", Path(__file__).with_name("_baton.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None          # bookkeeping must never stop the hook doing its work


_baton = _load_baton()
_HEARTBEAT = _baton.Heartbeat(__file__) if _baton else None


def _start() -> None:
    if _HEARTBEAT is not None:
        _HEARTBEAT.start()


def _beat(crash: BaseException | None = None) -> None:
    if _HEARTBEAT is not None:
        _HEARTBEAT.beat(crash)







if __name__ == "__main__":
    _start()
    try:
        code = main()
    except Exception as exc:
        # A hook must never break the session it is trying to help -- but it must not vanish:
        # the crash is left for /baton-doctor and the next SessionStart (row 36). Stop has had
        # this top-level guard; this hook had none, so a malformed batch exited 1 with a traceback.
        _beat(exc)
        sys.exit(0)
    _beat()
    sys.exit(code)
