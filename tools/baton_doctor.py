#!/usr/bin/env python3
"""Is Baton running here, or only installed? When each hook last ran.

    python3 tools/baton_doctor.py

Each hook leaves one small file when it finishes (`baton.beat.<hook>`, since v3.12.0; written
before the hook's work until v3.20.0), and `baton.beat.<hook>.crashed` -- the time and the
exception's class -- when it raised; since v3.21.0 each run also marks its start
(`baton.beat.<hook>.started.<pid>`), and a mark left behind is a run killed from outside: in the
plugin's data folder (${CLAUDE_PLUGIN_DATA}, which /baton-doctor passes in), or next to the
hooks of a script install. A plugin can be installed and enabled and still never run -- no
Python, no Git Bash on Windows -- and nothing on the screen says so. Reads only; sends nothing.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

HOOKS = (
    ("baton_session_start", "SessionStart", "at the start of every session"),
    ("baton_prompt", "UserPromptSubmit", "on every message"),
    ("baton_stop", "Stop", "at the end of every turn"),
    ("baton_batch", "PostToolBatch", "after the agent's tool calls"),
    ("baton_stop_failure", "StopFailure", "when a turn ends on an API error"),
)


def folder() -> Path:
    """The plugin's data folder when it is passed in; else the script install's hooks; else
    any plugin data folder of Baton's that holds heartbeats -- so a skill whose
    ${CLAUDE_PLUGIN_DATA} arrived empty does not tell a working plugin it is not running."""
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if data:
        return Path(data)
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    script = claude / "baton" / "hooks"
    if any(script.glob("baton.beat.*")):
        return script
    beating = [d for d in (claude / "plugins" / "data").glob("baton-*") if any(d.glob("baton.beat.*"))]
    if beating:
        return max(beating, key=lambda d: max(f.stat().st_mtime for f in d.glob("baton.beat.*")))
    return script


def last_run(where: Path, stem: str) -> datetime | None:
    try:
        return datetime.fromisoformat((where / f"baton.beat.{stem}").read_text("utf-8").strip())
    except (OSError, ValueError):
        return None


def crashed(where: Path, stem: str) -> tuple[datetime, str] | None:
    """When the hook last raised, and the exception's class (since v3.20.0)."""
    try:
        marker = (where / f"baton.beat.{stem}.crashed").read_text("utf-8")
        when, _, kind = marker.strip().partition(" ")
        return datetime.fromisoformat(when), kind or "unknown error"
    except (OSError, ValueError):
        return None


def order(path: Path, when: datetime) -> tuple:
    """Which marker is newer: by the file's own time, the text's time on a tie. The text is local
    time and repeats in the hour after the clocks go back (row 64, 25.10.2026)."""
    try:
        return (path.stat().st_mtime_ns, when)
    except OSError:
        return (0, when)


def stopped(where: Path, stem: str) -> tuple | None:
    """When a run that did not finish began (since v3.21.0, ZA-OPRAVYANE row 41). Each run writes
    `baton.beat.<hook>.started.<pid>` before its work and removes it when it finishes or crashes;
    one left behind whose process is gone, or older than any hook's limit, was stopped from outside
    -- killed, or timed out. A run still going in another session is not counted. Its `order`."""
    import time
    found = []
    for mark in where.glob(f"baton.beat.{stem}.started.*"):
        try:
            pid = mark.name.rsplit(".", 1)[1]
            gone = time.time() - mark.stat().st_mtime > 120
            if not gone and os.name != "nt":      # on Windows os.kill(pid, 0) is not a probe
                try:
                    os.kill(int(pid), 0)
                except ProcessLookupError:
                    gone = True
            if gone:
                found.append(order(mark, datetime.fromisoformat(mark.read_text("utf-8").strip())))
        except (OSError, ValueError):
            continue
    return max(found) if found else None


# Row 49 (Synthetixis, 22.10): each hook was looked at on its own, so a Stop last finished three
# days ago, beside the others a minute ago, showed ✅. Since v3.24.0 UserPromptSubmit, PostToolBatch,
# Stop and StopFailure each add a line to `baton.turns/<session>`: the time, the event, and for
# StopFailure the error type. Per session: was its last activity followed by a Stop or a
# StopFailure? Stop does not run when the human interrupts a turn, and an API error runs
# StopFailure instead (code.claude.com/docs/en/hooks, 23.10), so a miss is a question. Stop can
# run up to three times in a turn by design -- Baton's hand-back, at most one more (row 115), then
# the pass with `stop_hook_active` true -- so Stops are not counted: any one ends the turn. Whether and when Claude Code resets that flag
# is not documented, and nothing here depends on it. What follows what is read by the lines'
# order in the file, not by the times written in them: those are local time and repeat in the
# hour after the clocks go back (row 64, 25.10.2026).
TURN_OPEN, TURN_END = ("UserPromptSubmit", "PostToolBatch"), ("Stop", "StopFailure")
TURN_GRACE = 120          # seconds: a turn this young may still be going
TURN_SESSIONS, TURN_DAYS = 20, 7


def turns(where: Path, now: datetime, own: str = "") -> tuple[list, list, int] | None:
    """(open, failed, judged) over the newest TURN_SESSIONS sessions of the last TURN_DAYS days:
    `open` -- (session, event, time) of a last activity with no end after it; `failed` --
    (session, error) of a last activity ended by StopFailure; `judged` -- sessions looked at.
    `own` is the session the doctor runs in, whose turn is not over (BATON_SESSION). None when
    there are no records: heartbeats from before v3.24.0 hold no session."""
    import time
    try:
        files = [f for f in (where / "baton.turns").iterdir() if f.is_file()
                 and time.time() - f.stat().st_mtime < TURN_DAYS * 86400]
    except OSError:
        return None
    files = sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)[:TURN_SESSIONS]
    if not files:
        return None
    open_, failed, judged = [], [], 0
    for f in files:
        if own and f.name == own:
            continue
        rows = []
        try:
            for line in f.read_text("utf-8", "replace").splitlines():
                parts = line.split(" ")
                try:
                    rows.append((datetime.fromisoformat(parts[0]), parts[1] if len(parts) > 1 else "",
                                 parts[2] if len(parts) > 2 else ""))
                except ValueError:
                    continue
        except OSError:
            continue
        last = max((i for i, r in enumerate(rows) if r[1] in TURN_OPEN), default=None)
        if last is None:
            continue
        ends = [r for r in rows[last + 1:] if r[1] in TURN_END]
        if not ends and (now - rows[last][0]).total_seconds() < TURN_GRACE:
            continue
        judged += 1
        if not ends:
            open_.append((f.name, rows[last][1], rows[last][0]))
        elif ends[-1][1] == "StopFailure":
            failed.append((f.name, ends[-1][2] or "unknown"))
    return open_, failed, judged


def ago(when: datetime, now: datetime) -> str:
    sec = int((now - when).total_seconds())
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if sec >= size:
            n = sec // size
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


def handback(where: Path) -> str | None:
    """Does Stop's hand-back do any work? The three numbers Stop keeps with the lessons."""
    path = Path(os.environ.get("BATON_LESSONS_STATE") or where / "baton.lessons.json")
    try:
        rec = json.loads(path.read_text("utf-8")).get("handback") or {}
    except (OSError, ValueError, AttributeError):
        return None
    if not rec:
        return None
    return (f"Logbook entries since {rec.get('since', '?')}: written unasked: "
            f"{rec.get('unasked', 0)}; handed back: {rec.get('handed_back', 0)} -- recorded on "
            f"the second try: {rec.get('recorded_after', 0)}, passed without one: "
            f"{rec.get('passed', 0)}.\n   (Counted by folder. \"Passed\" is a turn Stop asked about "
            "and let through, since it never asks twice.)")


def lesson_l2(where: Path) -> str | None:
    """Does the L2 note change what comes next? Counted since v3.20.0 (ZA-OPRAVYANE row 40)."""
    path = Path(os.environ.get("BATON_LESSONS_STATE") or where / "baton.lessons.json")
    try:
        rec = json.loads(path.read_text("utf-8")).get("L2") or {}
    except (OSError, ValueError, AttributeError):
        return None
    if not rec:
        return None
    after = rec.get("checked_after", 0) + rec.get("no_check_after", 0)
    shown = (f"since {rec['shown_since']}: shown {rec.get('shown', 0)}, followed by a check: "
             f"{rec.get('checked_after', 0)} of {after}" if rec.get("shown_since")
             else "shown and followed by a check: not counted yet (from v3.20.0 on)")
    return (f"Lesson L2 (a failed read): fired {rec.get('fired', 0)} since {rec.get('since', '?')}; "
            f"{shown}.\n   (A proxy, not proof: \"a check\" is a read in the agent's next tool "
            "calls; it may have been planned anyway.)")


def lesson_fixes(where: Path) -> str | None:
    """Was each lesson followed? (since v3.21.0, ZA-OPRAVYANE row 44). L1, L3, L4: after Stop asked,
    the next three Stops looked at the entry with the test that raised the ask. L2: the next tool
    calls after a shown note (row 40)."""
    path = Path(os.environ.get("BATON_LESSONS_STATE") or where / "baton.lessons.json")
    try:
        state = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    lines = []
    for lid, what, ok, no, since in (
            ("L1", "an hour off the clock", "fixed_after", "not_fixed_after", "fixed_since"),
            ("L2", "a failed read", "checked_after", "no_check_after", "shown_since"),
            ("L3", "a public/private claim", "fixed_after", "not_fixed_after", "fixed_since"),
            ("L4", "a tests claim", "fixed_after", "not_fixed_after", "fixed_since")):
        rec = state.get(lid) if isinstance(state, dict) else None
        if not isinstance(rec, dict) or not rec.get(since):
            continue
        n, m = rec.get(ok, 0), rec.get(ok, 0) + rec.get(no, 0)
        lines.append(f"   {lid} ({what}): fixed after the lesson: {n} of {m} since {rec[since]}")
    if not lines:
        return None
    return ("Followed? (a proxy, not proof -- L1, L3, L4: the entry no longer shows what Stop asked "
            "about within three\n   Stops, a new entry on top counts too; L2: a read among the next "
            "tool calls):\n" + "\n".join(lines))


# `"disableAllHooks": true` in any settings file Claude Code reads switches every hook off, Baton's
# with them, and the heartbeats of the last run still said ✅ Running (ZA-OPRAVYANE row 78, after
# Amir Raza and Kumar V., 23.10: a line an agent can write silences the hook that watches it).
# The value that counts is the one left after settings precedence: managed, then project local,
# then shared project, then user (code.claude.com/docs/en/hooks, "Disable or remove hooks";
# docs/en/settings, "Settings precedence"). `--settings` on the command line sits between managed
# and local and cannot be seen from here.
SCOPES = {"user": 0, "project": 1, "local": 2, "managed": 3}
MANAGED = {"darwin": "/Library/Application Support/ClaudeCode",
           "win32": r"C:\Program Files\ClaudeCode"}


def settings_files() -> list:
    """(scope, path) of each settings file Claude Code reads for a session started here."""
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    here = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    # The local file sits at the repository root in a git repository (Claude Code v2.1.211+).
    roots = [here] + [p for p in (here, *here.parents) if (p / ".git").exists()][:1]
    out = [("user", claude / "settings.json")]
    for root in dict.fromkeys(roots):
        out += [("project", root / ".claude" / "settings.json"),
                ("local", root / ".claude" / "settings.local.json")]
    managed = Path(os.environ.get("BATON_MANAGED_DIR") or MANAGED.get(sys.platform, "/etc/claude-code"))
    out.append(("managed", managed / "managed-settings.json"))
    try:
        out += [("managed", f) for f in sorted((managed / "managed-settings.d").glob("*.json"))]
    except OSError:
        pass
    return out


def hooks_disabled() -> tuple[list, bool]:
    """Every file that sets disableAllHooks, with its value; and whether the value in force is true."""
    found = []
    for scope, path in settings_files():
        try:
            data = json.loads(path.read_text("utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and "disableAllHooks" in data:
            found.append((scope, path, data["disableAllHooks"]))
    if not found:
        return [], False
    top = max(SCOPES[s] for s, _, _ in found)
    return found, any(v is True for s, _, v in found if SCOPES[s] == top)


def main() -> int:
    where, now = folder(), datetime.now()
    print(f"Baton doctor -- heartbeats in {where}\n")
    found, disabled = hooks_disabled()
    if disabled:
        print("🔴 ALL HOOKS ARE SWITCHED OFF: \"disableAllHooks\": true is the value in force, so\n"
              "   no Baton hook runs -- the heartbeats below are from before it was set.")
    for scope, path, value in found:
        print(f"   disableAllHooks: {json.dumps(value)} in {path} ({scope})")
    if found:
        print("   (Precedence: managed > project local > shared project > user. A --settings flag\n"
              "   on the command line is not visible here.)\n" + ("   Remove the line, or set it to "
              "false, and start a new session.\n" if disabled else ""))
    seen = {stem: last_run(where, stem) for stem, _, _ in HOOKS}
    beat = {stem: order(where / f"baton.beat.{stem}", seen[stem]) for stem, _, _ in HOOKS}
    crashes = {stem: c for stem, _, _ in HOOKS for c in [crashed(where, stem)]
               if c and (seen[stem] is None
                         or order(where / f"baton.beat.{stem}.crashed", c[0]) > beat[stem])}
    killed = {stem: k for stem, _, _ in HOOKS for k in [stopped(where, stem)]
              if k and (seen[stem] is None or k > beat[stem])
              and (stem not in crashes
                   or k > order(where / f"baton.beat.{stem}.crashed", crashes[stem][0]))}
    for stem in killed:
        crashes.pop(stem, None)
    started = (seen["baton_session_start"] is not None or "baton_session_start" in crashes
               or "baton_session_start" in killed)
    for stem, event, when in HOOKS:
        t = seen[stem]
        if stem in killed:
            last = f"{t:%Y-%m-%d %H:%M}" if t else "never"
            k = killed[stem][1]
            mark, state = "❌", (f"DID NOT FINISH: started {k:%Y-%m-%d %H:%M} "
                                 f"({ago(k, now)}), killed or timed out?; "
                                 f"last finished {last}")
        elif stem in crashes:
            c, kind = crashes[stem]
            last = f"{t:%Y-%m-%d %H:%M}" if t else "never"
            mark, state = "❌", (f"CRASHED {c:%Y-%m-%d %H:%M} ({ago(c, now)}): {kind}; "
                                 f"last finished {last}")
        elif t:
            mark, state = "✅", f"last finished {t:%Y-%m-%d %H:%M} ({ago(t, now)})"
        elif started:
            # SessionStart ran, so the hooks work; this one has not had its moment yet.
            mark, state = "⏳", "not yet"
        else:
            mark, state = "❌", "NEVER RAN"
        if disabled and mark != "❌":
            mark = "⛔"            # whatever it did last, it does not run now
        print(f"  {mark} {event:<17} {state}   -- runs {when}")
    print()
    seen_turns = turns(where, now, os.environ.get("BATON_SESSION", ""))
    if seen_turns and seen_turns[2]:
        open_, failed, judged = seen_turns
        errors = ", ".join(f"{e} ({s[:8]})" for s, e in failed)
        if open_:
            print(f"⚠️  A turn with no end seen, in {len(open_)} of the last {judged} sessions: its "
                  "last activity\n   has no Stop or StopFailure after it.")
            for s, event, t in open_:
                print(f"     {s[:8]}  {event} at {t:%Y-%m-%d %H:%M} ({ago(t, now)})")
            if errors:
                print(f"   Ended on an API error (StopFailure) instead: {errors}.")
            print("   A question, not a failure: Stop does not run when the human interrupts a "
                  "turn, or the\n   session is closed in the middle of one. If it shows after "
                  "turns that ended normally,\n   Stop is not running.\n")
        else:
            print(f"✅ Turns ended: in each of the last {judged} sessions the last activity was "
                  "followed by\n   a Stop or a StopFailure" + (f"; ended on an API error: {errors}" if errors else "")
                  + ".\n")
    counted = handback(where)
    if counted:
        print(counted + "\n")
    l2 = lesson_l2(where)
    if l2:
        print(l2 + "\n")
    fixes = lesson_fixes(where)
    if fixes:
        print(fixes + "\n")
    if killed:
        names = ", ".join(event for stem, event, _ in HOOKS if stem in killed)
        print(f"🔴 Did not finish its last run: {names}. It was stopped from outside -- killed, or\n"
              "   at Claude Code's time limit (20 s, PostToolBatch 10 s) -- so its check did not\n"
              "   happen, and a killed process leaves no other trace. If it repeats, time it by\n"
              "   hand: time (echo '{}' | python3 <the hooks folder>/<hook>.py)")
    if crashes:
        names = ", ".join(event for stem, event, _ in HOOKS if stem in crashes)
        print(f"🔴 Crashed on its last run: {names}. A hook never breaks the session, so it\n"
              "   exited 0 and its check did not happen. Run it by hand to see the traceback:\n"
              "   echo '{}' | python3 <the hooks folder>/<hook>.py")
        return 1
    if killed:
        return 1
    if disabled:
        return 1
    if not any(seen.values()):     # nothing finished, and nothing crashed (said above)
        print("🔴 Installed but not running: no Baton hook has left a heartbeat here.\n"
              "   Check that Python 3.8+ runs (`python3 --version`); on Windows, that Git for\n"
              "   Windows is installed (`where bash`). A hook from before v3.12.0 leaves no\n"
              "   heartbeat: start a new session first, then ask again.")
        return 1
    if not seen["baton_session_start"]:
        print("🔴 SessionStart has never run here: the board and the rules are not reaching the "
              "agent.")
        return 1
    print("✅ Running. A hook marked ⏳ has not had its moment yet (Stop needs a finished\n"
          "   turn, PostToolBatch a tool call, StopFailure an API error -- it may never run). If\n"
          "   Stop or PostToolBatch is still ⏳ after a turn with a tool call, it is failing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
