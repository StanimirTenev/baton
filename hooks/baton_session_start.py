#!/usr/bin/env python3
"""Baton SessionStart hook.

Lists task folders and injects them into the agent's context so a session never
starts blind. Two modes, chosen per folder:

* A task whose logbook opens with a YAML-ish front-matter block is surfaced by
  what it MEANS right now — who is on the hook, whether a deadline is near, what
  the next action is — grouped and ordered by priority, so the agent sees *which
  task first*, not merely which was touched last.
* A task with no front-matter falls back to the original behaviour: its name, the
  date of the last entry, and that entry's title. Nothing old breaks.

Prints nothing when there are no task folders, so a fresh machine stays quiet.
"""
from __future__ import annotations   # `str | None`, `list[str]`: Python 3.8 and 3.9 too
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

MAX_PLAIN = 6                 # cap only on the fall-back (header-less) list
SOON_DAYS = 3                 # a deadline within this many days counts as "near"
US = {"us", "me", "self", ""}   # nie/ние/нас map to `us` on reading; + `us` names from baton.local.json
PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
# The board reaches the human as Markdown, which has no coloured text; the dot is the colour.
PRIORITY_DOT = {"high": "🔴", "medium": "🟡", "low": "🟢"}

# ISO or day first, as Stop's _HEADING reads them: `## 22.10.2026 15:30 — x` showed its whole
# heading on the board, date and all, as if it had no title (ZA-OPRAVYANE row 69, 22.10).
DATED_HEADING = re.compile(
    r"^(?:\d{4}-\d\d-\d\d|\d{1,2}\.\d{1,2}\.\d{4})(?:[ T]\d{1,2}:\d\d)?\s*[\u2014\u2013-]\s*"
    r"(?P<title>.+)$"
)


# A claim nobody has verified does not improve with age. After this many days an
# inference or an unchecked agent's claim is reported as a debt rather than a
# fact, because the cost of a stale one is not that it is old -- it is that it
# reads exactly like a verified one.
STALE_CLAIM_DAYS = 30

# `## Кръг 4 — 19.09.2026` or `## Round 4 — 2026-09-19`: the date a block of
# claims was written, which is the only date a claim in it can carry.
CLAIM_BLOCK = re.compile(
    r"^#{2,3}\s+.*?[\u2014\u2013-]\s*(\d{4}-\d\d-\d\d|\d\d\.\d\d\.\d{4})", re.M)

# A row in a facts table whose status column says the claim was inferred (И / I)
# or taken from an agent without independent checking (А / A).
UNVERIFIED_ROW = re.compile(r"^\s*\|.*\|\s*(И|I|А|A)\s*\|", re.M)

# Where a task keeps claims with a status. A logbook cannot hold them: it is a
# record and does not get edited, while a status is exactly the thing that
# changes when someone finally checks. So status lives in a register, for the
# same reason the constraints register is not the logbook either.
CLAIMS_FILES = ("FAKTI.md", "FACTS.md", "TVARDENIYA.md", "CLAIMS.md")

# A date, optionally with a time, anywhere in a row: a claim carries its own
# stamp instead of borrowing one from the heading above it. A register written a
# row at a time, over weeks, has no meaningful block date -- and the age of a
# claim is the whole point.
#
# The date must be a cell of its own -- a date column -- and not merely appear
# somewhere in the row. A first attempt matched anywhere and read
# `| last release 0.12.0 (14.08.2026) | А |` as a claim written on 14 August,
# which is a date inside the claim, not the date the claim was made. A detector
# that fires on the wrong thing gets switched off, and then the real ones go
# unread too.
#
# The time is allowed because a day is not always fine enough. On 19.09.2026 six
# claims were written and five were falsified within the same day, two of them
# within an hour of being written; dated only to the day, that register would
# say nothing about what followed what. Ageing stays in days -- a debt is not
# measured in hours -- but the stamp keeps the order.
ROW_DATE = re.compile(
    r"^(\d{4}-\d\d-\d\d|\d\d\.\d\d\.\d{4})(?:[ T](\d\d:\d\d))?$")


def not_tasks(root: Path) -> list[str]:
    """Globs from a `.batonignore` in the task ROOT: folders there that are not tasks (a folder
    of photos, an archive). Inside a task folder the same file names files that need no entry;
    at the root it names folders -- the same meaning, "do not demand a logbook for this".
    ZA-OPRAVYANE row 31 (2026-10-21): one stray folder made every review PARTIAL, and nothing
    let a folder say it was not a task."""
    try:
        lines = (root / ".batonignore").read_text("utf-8-sig").splitlines()
    except OSError:
        return []
    return [ln.strip().rstrip("/") for ln in lines if ln.strip() and not ln.strip().startswith("#")]


UNREADABLE: list = []   # task folders that could not be listed (row 54): named, never a crash


def task_folders(root: Path) -> list[Path]:
    """The task folders under `root`, sorted: every folder but a dotted one or one the root's
    `.batonignore` names. Every hook and tool asks this one function.

    A folder that cannot be listed (owned by root -- a docker volume, a mounted share) is left out
    and put in UNREADABLE: `is_file()` re-raises PermissionError, and one such folder crashed the
    board and every Stop check, for every task (ZA-OPRAVYANE row 54, 22.10)."""
    import fnmatch
    skip = not_tasks(root)
    try:
        found = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    except OSError:
        return []
    out = []
    UNREADABLE.clear()
    for p in sorted(p for p in found if not any(fnmatch.fnmatch(p.name, g) for g in skip)):
        try:
            with os.scandir(p) as it:
                for entry in it:
                    entry.is_file()
                    break
            out.append(p)
        except OSError:
            UNREADABLE.append(p.name)
    return out


def unreadable_note(names: list) -> str:
    return (f"Baton could not read these task folders (permission denied?), so nothing in them is "
            f"checked: {', '.join(names)}. Make them readable, or name them in the root's "
            ".batonignore if they are not tasks.")


def plugin() -> bool:
    """Installed as a Claude Code plugin: Claude Code sets CLAUDE_PLUGIN_ROOT for its hooks."""
    return bool(os.environ.get("CLAUDE_PLUGIN_ROOT"))


def claude_dir() -> Path:
    """Claude Code's configuration folder: CLAUDE_CONFIG_DIR, else ~/.claude -- the same
    rule install.sh and install.ps1 use. Reading ~/.claude regardless made a session with
    its own config see an installer it does not run (2026-09-29)."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def installed_twice() -> bool:
    """Running as a plugin while install.sh's hooks are also in ~/.claude/settings.json.

    Every hook would then run twice -- two boards, two hand-backs, two reminders. The
    plugin's copy is the one that stands down: the installed copy keeps working, and
    SessionStart says once which of the two to remove."""
    if not plugin():
        return False
    try:
        settings = json.loads((claude_dir() / "settings.json").read_text("utf-8-sig"))
    except Exception:
        return False
    # A plugin's own hooks come from its hooks.json, never from settings.json: any Baton
    # entry there is the installer's -- one of its five files by name. Any "baton_" in a
    # command was taken for it: a human's ~/bin/my_baton_notes.sh switched the plugin off (row 61).
    for groups in (settings.get("hooks") or {}).values():
        for group in groups or []:
            for h in group.get("hooks", []) or []:
                blob = str(h.get("command", "")) + " " + " ".join(map(str, h.get("args") or []))
                if re.search(r"(?:^|[\\/\s\"'])baton_(?:session_start|stop(?:_failure)?|prompt|batch)\.py(?![\w.])",
                             blob):
                    return True
    return False


def twice_message() -> str:
    """Said at each session start while both installs are present. Names the settings file
    this session actually reads, not ~/.claude when CLAUDE_CONFIG_DIR says otherwise."""
    settings = claude_dir() / "settings.json"
    return ("⚠️ Baton is installed twice on this machine: by its installer (its hook entries in "
            f"{settings}) and as a plugin. Every hook would run twice, so the plugin's copy has "
            "stood down and the installed one is doing the work. Tell the human, in their "
            "language, and ask which to keep. To keep the plugin: remove the entries whose "
            f"command runs a baton_ script from {settings} (the README's Uninstall section lists "
            "them). To keep the installer: `claude plugin uninstall baton`.")


def command(skill: str) -> str:
    """How the human invokes a Baton skill. A plugin's skills are namespaced by the plugin."""
    return f"/baton:{skill}" if plugin() else f"/{skill}"


def _local_file(name: str) -> Path:
    """Where a settings or state file lives. Installed as a plugin, the hooks run from a
    folder replaced on every update, so these go to ${CLAUDE_PLUGIN_DATA}, which survives
    updates. Installed by install.sh, next to the hooks, as always."""
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not data:
        return Path(__file__).with_name(name)
    try:
        Path(data).mkdir(parents=True, exist_ok=True)   # "created on first reference" is
    except OSError:                                     # not a promise to these hooks
        pass
    return Path(data) / name


def config() -> tuple[Path, str]:
    cfg = {}
    try:
        cfg = json.loads((_local_file("baton.local.json")).read_text("utf-8-sig"))
    except Exception:
        cfg = {}
    home = (os.environ.get("BATON_HOME") or os.environ.get("CLAUDE_PLUGIN_OPTION_TASKS_FOLDER")
            or cfg.get("home") or str(Path.home() / "tasks"))
    logbook = (os.environ.get("BATON_LOGBOOK") or os.environ.get("CLAUDE_PLUGIN_OPTION_LOGBOOK")
               or cfg.get("logbook") or "LOGBOOK.md")
    return Path(home).expanduser(), logbook


BATON_VERSION = "3.24.1"   # bumped with every release; a test holds it to the README's top version
RELEASES = "https://api.github.com/repos/StanimirTenev/baton/releases/latest"


def _local() -> dict:
    try:
        return json.loads((_local_file("baton.local.json")).read_text("utf-8-sig"))
    except Exception:
        return {}


def entry_tool() -> Path | None:
    """Where tools/baton_entry.py is on this machine, or None. A plugin carries tools/ next
    to hooks/; install.sh copies only the hooks, and tools/ stays in the repository it
    recorded as `repo`. An agent's working directory is neither (PR #2)."""
    repo = _local().get("repo")
    for base in (Path(__file__).resolve().parent.parent, Path(repo).expanduser() if repo else None):
        if base is not None and (base / "tools" / "baton_entry.py").is_file():
            return base / "tools" / "baton_entry.py"
    return None


def board_wanted(source, cfg: dict, env, platform: str) -> bool:
    """Open the HTML board now? Only when the human switched it on (`board_open: true`), only
    at `startup` and `/clear` -- never after a compaction or on `resume`, which are the same
    work going on -- and only where a browser can appear: on Linux a DISPLAY or WAYLAND_DISPLAY
    (without one, Python's browser module falls back to a text browser in the terminal), on a
    Mac not over SSH. ZA-OPRAVYANE row 34 (2026-10-21)."""
    if cfg.get("board_open") is not True or source not in ("startup", "clear"):
        return False
    if platform.startswith("win"):
        return True
    if platform == "darwin":
        return not env.get("SSH_CONNECTION")
    return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


# What the board process gets from the session's environment: where to run and what to read
# (PATH, home, temp, locale; Windows needs SYSTEMROOT to start Python at all), where Baton keeps
# its settings, and what a browser needs to appear (display, X authority, session bus, desktop,
# the human's BROWSER). Nothing else: a session's environment can hold API keys and tokens, and
# the board needs none of them. BATON_HOME and BATON_LOGBOOK are set by open_board itself.
BOARD_ENV = ("PATH", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "SYSTEMROOT", "SYSTEMDRIVE",
             "WINDIR", "COMSPEC", "PATHEXT", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR",
             "LANG", "LC_ALL", "LC_CTYPE", "CLAUDE_PLUGIN_DATA",
             "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR",
             "DBUS_SESSION_BUS_ADDRESS", "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE",
             "XDG_DATA_DIRS", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "BROWSER")


def board_env(environ, root: Path, logbook: str) -> dict:
    """The environment of the board process: only the names in BOARD_ENV."""
    env = {k: v for k, v in environ.items() if k in BOARD_ENV}
    env.update(BATON_HOME=str(root), BATON_LOGBOOK=logbook)
    return env


def open_board(source, root: Path, logbook: str) -> None:
    """Write the HTML board and open it, in a process of its own: the hook does not wait for
    it, and nothing it does can fail the session. Off by default; silent when the board tool
    is not on this machine (install.sh copies only the hooks; then `repo` says where it is)."""
    try:
        cfg = _local()
        if not board_wanted(source, cfg, os.environ, sys.platform):
            return
        repo = cfg.get("repo")
        tool = next((b / "tools" / "baton_board.py" for b in
                     (Path(__file__).resolve().parent.parent, Path(repo).expanduser() if repo else None)
                     if b is not None and (b / "tools" / "baton_board.py").is_file()), None)
        if tool is None:
            return
        lang = str(cfg.get("board_language") or "en")
        env = board_env(os.environ, root, logbook)
        detach = ({"creationflags": 0x00000008 | 0x00000200} if os.name == "nt"   # DETACHED, NEW_GROUP
                  else {"start_new_session": True})
        subprocess.Popen([sys.executable, str(tool), "--out", str(_local_file("baton.board.html")),
                          "--open", "--lang", lang if lang in ("en", "bg") else "en"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, env=env, **detach)
    except Exception:
        pass          # a view of the board is a courtesy; never a reason to fail the session


HOOK_EVENTS = (("baton_session_start", "SessionStart"), ("baton_prompt", "UserPromptSubmit"),
               ("baton_stop", "Stop"), ("baton_batch", "PostToolBatch"),
               ("baton_stop_failure", "StopFailure"))


def marker_order(path: Path, when: str) -> tuple:
    """Which of two markers is newer. By the file's own time, not its text: the text is local
    time, and in the hour after the clocks go back (25.10.2026, 04:00 -> 03:00) a crash at 03:20
    sorted before a finish at 03:50 written half an hour earlier, and was shown as ✅ (row 64).
    The text breaks a tie -- a coarse clock can give two files the same time."""
    try:
        return (path.stat().st_mtime_ns, when)
    except OSError:
        return (0, when)


def crashed_hooks() -> list[str]:
    """The hooks whose last run raised: a `.crashed` marker newer than their last finish (row 36).
    A hook exits 0 whatever happens, so this is the only place a crash is seen."""
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    folder = Path(data) if data else Path(__file__).resolve().parent
    out = []
    for stem, event in HOOK_EVENTS:
        crash, beat = folder / f"baton.beat.{stem}.crashed", folder / f"baton.beat.{stem}"
        try:
            marker = crash.read_text("utf-8")
        except OSError:
            continue
        when, _, kind = marker.strip().partition(" ")
        try:
            done = beat.read_text("utf-8").strip()
        except OSError:
            done = ""
        if marker_order(crash, when) > marker_order(beat, done):
            out.append(f"{event} at {when.replace('T', ' ')[:16]} ({kind or 'unknown error'})")
    return out


def stopped_start(folder: Path, stem: str) -> tuple | None:
    """The newest start mark of a run that is gone without finishing or crashing (row 41): its
    pid is not running, or it is older than any hook's limit. Its `marker_order` -- the file's
    time, then the text -- or None when there is none."""
    import time
    found = []
    for mark in folder.glob(f"baton.beat.{stem}.started.*"):
        try:
            pid = mark.name.rsplit(".", 1)[1]
            gone = time.time() - mark.stat().st_mtime > 120
            if not gone and os.name != "nt" and pid != str(os.getpid()):
                try:
                    os.kill(int(pid), 0)
                except ProcessLookupError:
                    gone = True
            if gone:
                found.append(marker_order(mark, mark.read_text("utf-8").strip()))
        except (OSError, ValueError):
            continue
    return max(found) if found else None


def stopped_hooks() -> list[str]:
    """The hooks whose last run was stopped from outside: a start mark left behind, newer than
    the last finish and the last crash. A killed process writes nothing else."""
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    folder = Path(data) if data else Path(__file__).resolve().parent
    out = []
    for stem, event in HOOK_EVENTS:
        key = stopped_start(folder, stem)
        if not key:
            continue
        when = key[1]
        later = []
        for name in (f"baton.beat.{stem}", f"baton.beat.{stem}.crashed"):
            try:
                later.append(marker_order(folder / name, (folder / name).read_text("utf-8")
                                          .strip().partition(" ")[0]))
            except OSError:
                pass
        if all(key > t for t in later):
            out.append(f"{event}, started at {when.replace('T', ' ')[:16]}")
    return out


def crash_notice() -> str | None:
    found, stopped = crashed_hooks(), stopped_hooks()
    out = []
    if found:
        out.append("🔴 Baton: a hook crashed on its last run, so its check did not happen -- "
                   + "; ".join(found) + ". A hook never breaks the session, so nothing else said so.")
    if stopped:
        out.append("🔴 Baton: a hook did not finish its last run (killed or timed out?), so its "
                   "check did not happen -- " + "; ".join(stopped) + ". Claude Code stops a hook "
                   "at its time limit (20 s, PostToolBatch 10 s) and nothing else says so.")
    if not out:
        return None
    return (" ".join(out) + f" Tell the human in one line; {command('baton-doctor')} shows when "
            "each hook last finished.")


def _state_file() -> Path:
    return Path(os.environ.get("BATON_SESSION_STATE")
                or _local_file("baton.state.json"))


# -- Lessons: a mistake caught once is counted, so a lesson that does not hold shows itself --
#
# A lesson written down as a note did not stop the mistake it was about: the hour of an
# entry typed by hand was recorded as a lesson on 2026-09-23 and came back on 26.09, 28.09
# and twice on 30.09 -- caught every time by a hook, prevented never. The one mistake that
# did stop (files copied to the wrong Windows profile, three times despite a memory note)
# stopped the day the note became a command that does the copy correctly.
#
# So nothing here is loaded into every session. A lesson speaks only where its trigger
# fires, the hooks count how often it fired and how often it caught the mistake, and
# SessionStart says something only when a lesson has earned it: caught twice in two weeks
# (it is not holding -- propose the next rung), or not fired in 60 days (retire it?).
LESSONS = {
    "L1": "The hour in a logbook heading is read from the clock, never typed: write entries "
          "with tools/baton_entry.py --title, which stamps the time itself.",
    "L2": "An empty result, or an error instead of one, is a failed read until a second check "
          "shows otherwise: before saying something is absent, name the check that would have "
          "found it.",
    "L3": "A claim that something is public or private is checked against the source: list it "
          "under `### Claims to verify` at the top of the entry, and mark it `refuted:` there "
          "in a later entry if it proves wrong.",
    "L4": "A claim that tests pass is listed with the command that showed it: under `### Claims "
          "to verify` at the top of the entry, with its result line, and marked `refuted:` there "
          "in a later entry if it proves wrong.",
}
RECUR_DAYS, RECUR_MIN, RETIRE_DAYS = 14, 2, 60
# For L1 and L2 `caught` is the mistake made again. For L3 and L4 it is a listed claim later shown
# wrong: the section did its work, and two of those in a fortnight are not a lesson failing
# (ZA-OPRAVYANE row 33, 2026-10-21).
CAUGHT_IS_USE = {"L3", "L4"}


def _lessons_file() -> Path:
    return Path(os.environ.get("BATON_LESSONS_STATE") or _local_file("baton.lessons.json"))


def lessons_load() -> dict:
    try:
        return json.loads(_lessons_file().read_text("utf-8"))
    except Exception:
        return {}


def lessons_save(state: dict) -> None:
    try:
        path = _lessons_file()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(path)
    except Exception:
        pass          # counting is a courtesy; never a reason to fail a hook


def lesson_event(state: dict, lesson: str, kind: str, now: datetime | None = None) -> dict:
    """Count one `fired` (the trigger arose) or `caught` (the mistake was made and seen).
    Dates are kept for the last RETIRE_DAYS so a fortnight can be counted."""
    now = now or datetime.now()
    rec = state.setdefault(lesson, {})
    rec.setdefault("since", now.isoformat(timespec="minutes"))
    rec[kind] = rec.get(kind, 0) + 1
    rec[f"last_{kind}"] = now.isoformat(timespec="minutes")
    cutoff = (now - timedelta(days=RETIRE_DAYS)).isoformat(timespec="minutes")
    rec[f"{kind}_dates"] = [d for d in rec.get(f"{kind}_dates", []) if d >= cutoff] + \
        [now.isoformat(timespec="minutes")]
    return rec


# -- The pinned test command (L4, since v3.21.0; ZA-OPRAVYANE row 43) --------------------------
#
# A human pins a test command for a task folder in baton.local.json ("tests"). When the newest
# entry says tests pass, Stop starts that command in the background after the turn
# (baton_stop.py --run-tests); the runner leaves one record per folder, baton.tests.<folder>.json.
# Whoever comes next -- Stop or SessionStart -- sets its result beside the claim, once.

def tests_file(name: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)[:80] or "_"
    return _local_file(f"baton.tests.{safe}.json")


def tests_save(path: Path, rec: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(path)


def tests_verdict(rec: dict) -> str:
    """What the run said, by its exit code: 'failed (exit 1)', 'no tests ran (exit 5)'..."""
    verdict, code = rec.get("verdict", "?"), rec.get("exit")
    if verdict == "timed out":
        return f"timed out after {rec.get('timeout_s', '?')} s"
    return f"{verdict} (exit {code})" if code is not None else verdict


def tests_results(now: datetime | None = None) -> list[str]:
    """One sentence per pinned run that ended and has not been said yet; marked as said. A run
    that disagrees with the claim -- failed, or ran no tests -- counts as L4 caught. A run gone
    without a result is said as that: nothing is known about the claim."""
    now = now or datetime.now()
    out, caught = [], 0
    for path in sorted(_local_file("baton.local.json").parent.glob("baton.tests.*.json")):
        try:
            rec = json.loads(path.read_text("utf-8"))
        except Exception:
            continue
        if rec.get("reported"):
            continue
        folder, entry = rec.get("name", "?"), str(rec.get("entry", ""))[3:60].strip()
        cmd = f"`{rec.get('command', '')}` (in {rec.get('cwd', '?')})"
        if rec.get("state") == "running":
            try:
                started = datetime.fromisoformat(rec["started"])
                budget = float(rec.get("timeout_s") or 0)
            except (KeyError, TypeError, ValueError):
                continue
            if (now - started).total_seconds() <= budget + 120:
                continue                          # still running, as far as can be told
            out.append(f"Baton, lesson L4: the pinned test run for {folder} (started "
                       f"{started:%H:%M}, for the entry \"{entry}\") never finished -- the runner "
                       f"was stopped from outside. Nothing is known about the claim. {cmd}")
        elif rec.get("state") == "done":
            when = str(rec.get("finished", ""))[11:16]
            said = (f"{tests_verdict(rec)} in {rec.get('seconds', '?')} s at {when} -- {cmd} "
                    f"printed: {rec.get('line') or '(nothing)'}")
            edited = rec.get("tests_edited") or []
            if edited:        # row 52: a pass after the tests were edited proves the edited tests
                said += ("; test files saved in that folder since the session began: "
                         + ", ".join(edited[:5]) + (", ..." if len(edited) > 5 else "")
                         + " -- a pass shows the tests as they now stand")
            if rec.get("verdict") == "passed":
                out.append(f"Baton, lesson L4: the pinned tests for {folder} agree with the entry "
                           f"\"{entry}\": {said}.")
            else:
                agrees = rec.get("verdict") not in ("failed", "no tests ran")
                caught += not agrees
                out.append(f"Baton, lesson L4: the entry \"{entry}\" in {folder} says tests pass; "
                           f"the pinned test command {'could not say' if agrees else 'says otherwise'}"
                           f": {said}." + ("" if agrees else " Counted as caught.")
                           + (f" Full output: {rec['log']}" if rec.get("log") else ""))
        else:
            continue
        rec["reported"] = True
        try:
            tests_save(path, rec)
        except Exception:
            pass
    if caught:
        state = lessons_load()
        for _ in range(caught):
            lesson_event(state, "L4", "caught", now)
        lessons_save(state)
    return out


def tests_notice() -> str | None:
    try:
        said = tests_results()
    except Exception:
        return None
    if not said:
        return None
    return " ".join(said) + " Tell the human in one line per result, with the command as shown."


def lessons_notice(now: datetime | None = None) -> str | None:
    """At most one line per lesson, and only when it has earned one."""
    now = now or datetime.now()
    state, lines = lessons_load(), []
    recent = (now - timedelta(days=RECUR_DAYS)).isoformat(timespec="minutes")
    old = (now - timedelta(days=RETIRE_DAYS)).isoformat(timespec="minutes")
    for lid, text in LESSONS.items():
        rec = state.get(lid) or {}
        caught = [d for d in rec.get("caught_dates", []) if d >= recent]
        fired = [d for d in rec.get("fired_dates", []) if d >= recent]
        if len(caught) >= RECUR_MIN and lid in CAUGHT_IS_USE:
            lines.append(f"- {lid} caught {len(caught)} wrong claims in {RECUR_DAYS} days "
                         f"(asked {len(fired)} times): the claims section is doing its work. "
                         "Nothing to change; tell the human the two numbers if they ask.")
        elif len(caught) >= RECUR_MIN:
            lines.append(f"- {lid} recurred {len(caught)} times in {RECUR_DAYS} days "
                         f"({len(fired)} times the situation arose): \"{text}\" -- it is not "
                         "holding. Propose to the human the next rung: a check that catches it "
                         "by its result, or a tool that makes the mistake impossible.")
        elif rec.get("since", now.isoformat()) < old and rec.get("last_fired", "") < old:
            lines.append(f"- {lid} has not come up in {RETIRE_DAYS} days: \"{text}\" -- ask the "
                         "human whether to retire it.")
    if not lines:
        return None
    return "Baton -- lessons (each counted by the hook that watches for it):\n" + "\n".join(lines)


def _version(tag: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", tag)[:3])


def update_notice(today: date) -> str | None:
    """Once a week, IF the human switched it on: is there a newer Baton? Never installs.

    Off until chosen, because the README promised the hooks never touch the network, and a
    promise changed by default is a promise broken. While nobody has chosen, the agent is
    asked -- once a day -- to put the question to the human.

    Not as a plugin: Claude Code updates it (`claude plugin update`, or auto-update for the
    marketplace), and a plugin-mode hook makes no network request at all.
    """
    if plugin():
        return None
    cfg = _local()
    repo = cfg.get("repo")          # written by the installer since v3.6.1
    py = "python" if os.name == "nt" else "python3"
    known = bool(repo) and Path(repo).is_dir()
    tool = f"{py} {Path(repo) / 'tools' / 'baton_update.py'}" if known else \
        f"{py} <the Baton repository>/tools/baton_update.py"
    gone = "" if known else (" The folder Baton was installed from is not known or is gone; "
                             "it can be downloaded again from https://github.com/StanimirTenev/baton.")
    try:
        state = json.loads(_state_file().read_text("utf-8"))
    except Exception:
        state = {}

    def save():
        try:
            _state_file().write_text(json.dumps(state), "utf-8")
        except OSError:
            pass

    setting = cfg.get("update_check")
    if setting is None:
        if state.get("asked") == today.isoformat():
            return None
        state["asked"] = today.isoformat()
        save()
        return ("🔔 Baton can check once a week whether a newer version is out: one request to "
                "GitHub at session start, and nothing is ever installed on its own. It is off until "
                "the human chooses. Ask them once, in their language, then run "
                f"`{tool} on` or `{tool} off`." + gone)
    if setting is not True:
        return None

    checked = _as_date(state.get("checked"))
    wait = 1 if state.get("failed") else 7
    if checked is None or (today - checked).days >= wait:
        state["checked"] = today.isoformat()
        try:
            import urllib.request
            req = urllib.request.Request(os.environ.get("BATON_UPDATE_URL") or RELEASES,
                                         headers={"Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                rel = json.load(resp)
            state.update(latest=rel["tag_name"], url=rel.get("html_url", ""), failed=False)
        except Exception as err:
            state["failed"] = True
            save()
            return (f"🔔 Could not check for a newer Baton ({type(err).__name__}); "
                    "it will try again tomorrow.")
        save()

    latest = state.get("latest")
    if not latest or _version(latest) <= _version(BATON_VERSION):
        return None
    how = (f"`cd {repo} && git pull && {'install.cmd' if os.name == 'nt' else './install.sh'}`"
           if repo and Path(repo).is_dir() else
           "download it from the release page and run the installer again")
    return (f"⬆️ Baton {latest} is out; this machine runs v{BATON_VERSION}. Tell the human what "
            f"changed ({state.get('url') or 'the release page'}) and how to update: {how}. "
            "Never update without their yes.")


def source_dir() -> Path | None:
    """Where these hooks are developed, if this is a working copy rather than an install.

    Optional and absent for anyone who installed from a release: then there is nothing
    to compare against and nothing is reported.
    """
    raw = os.environ.get("BATON_SOURCE")       # read first: with no settings file it was never
    if not raw:                                # read at all (row 50, Benjamin Brachert, 22.10)
        try:
            raw = json.loads((_local_file("baton.local.json")).read_text("utf-8-sig")).get("source")
        except Exception:
            return None
    return Path(raw).expanduser() if raw else None


def install_drift() -> list[str]:
    """Hooks whose running copy differs from the source they are developed in.

    The failure this exists for: v2.2.0 of this project shipped a whole shelf-life
    layer -- written, tested, tagged -- and it never ran for two days, because the
    running hooks are copies and nobody copied them. The release notes said it was
    live. The repository agreed. The machine was running the previous version, and
    every session since had been told, by a hook that did not contain the feature,
    that everything was fine.

    A hook cannot verify it was installed -- but it can compare its own bytes to the
    file it was built from and say when they differ, which is the same question asked
    somewhere it can actually be answered.
    """
    # Claude Code owns the plugin's copy, and plugin_drift compares it with the catalog. Only
    # BATON_SOURCE, set by whoever develops Baton, compares it with a working copy: it was read
    # as a plugin too, and nothing was compared (row 72). The file's `source` still stands down.
    if plugin() and not os.environ.get("BATON_SOURCE"):
        return []
    src = source_dir()
    if src is None or not src.is_dir():
        return []
    pairs = [(name, Path(__file__).with_name(name), src / name)
             for name in ("baton_session_start.py", "baton_stop.py", "baton_prompt.py",
                          "baton_batch.py", "baton_stop_failure.py")
             + (("hooks.json",) if plugin() else ())]
    # The skills too (row 51, Benjamin Brachert, 22.10: a changed SKILL.md compared as nothing):
    # beside the hooks folder in the source; ~/.claude/skills for install.sh, the plugin's own.
    skills = Path(__file__).resolve().parent.parent / "skills" if plugin() else claude_dir() / "skills"
    try:
        pairs += [(f"skills/{d.name}/SKILL.md", skills / d.name / "SKILL.md", d / "SKILL.md")
                  for d in sorted((src.parent / "skills").iterdir()) if (d / "SKILL.md").is_file()]
    except OSError:
        pass
    out = []
    for name, here, there in pairs:
        try:
            if there.is_file() and not here.is_file():
                # In the source and not running: the silent case, and the worst one.
                out.append(f"{name} (not installed)")
            elif here.is_file() and there.is_file() and here.read_bytes() != there.read_bytes():
                out.append(name)
        except OSError:
            continue
    return out


def _json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text("utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def plugin_drift() -> str | None:
    """As a plugin: the running copy against what Claude Code recorded and the catalog released.

    `install_drift` stood down here, and the plugin is how most people install Baton. Two
    questions can be answered offline. Did Claude Code install another copy since this session
    started (installed_plugins.json)? Then `claude plugin update` took effect on disk and not
    here -- the v2.2.0 failure again. And is the running copy byte-for-byte the catalog's
    copy (the marketplace clone) of the same version? Whether that clone is the newest
    release is not answerable without the network, and is not asked.
    """
    if not plugin():
        return None
    root = Path(os.environ["CLAUDE_PLUGIN_ROOT"]).resolve()
    plugins = claude_dir() / "plugins"
    try:
        root.relative_to((plugins / "cache").resolve())
    except ValueError:
        return None                 # not a copy Claude Code installed: nothing recorded to compare
    own = _json(root / ".claude-plugin" / "plugin.json")
    name, version = own.get("name") or "baton", str(own.get("version") or "")
    records = _json(plugins / "installed_plugins.json")
    records = records.get("plugins", records)
    for key, entries in records.items():
        if not key.startswith(name + "@") or not isinstance(entries, list):
            continue
        paths = [(Path(str(e.get("installPath"))).expanduser().resolve(), e) for e in entries
                 if isinstance(e, dict) and e.get("installPath")]
        if not any(path == root for path, _ in paths):
            for path, entry in paths:       # the same catalog's folder: not a second install
                if path.parent == root.parent and path.is_dir():
                    return (f"- 🔴 Baton v{entry.get('version')} is installed ({key}), but this "
                            f"session runs v{version} from {root} — the update takes effect "
                            "after a restart of the session")
            continue
        place = _json(plugins / "known_marketplaces.json").get(key.split("@", 1)[1]) or {}
        clone = Path(str(place.get("installLocation") or "")).expanduser()
        listed = [p for p in _json(clone / ".claude-plugin" / "marketplace.json").get("plugins", [])
                  if isinstance(p, dict) and p.get("name") == name]
        source = listed[0].get("source") if listed else None
        if not place.get("installLocation") or not isinstance(source, str):
            return None
        release = (clone / source).resolve()
        if str(_json(release / ".claude-plugin" / "plugin.json").get("version") or "") != version:
            return None             # the catalog moved on; whether to update is the human's call
        differ = []
        for hook in ("baton_session_start.py", "baton_stop.py", "baton_prompt.py",
                     "baton_batch.py", "baton_stop_failure.py", "hooks.json"):
            here, there = root / "hooks" / hook, release / "hooks" / hook
            try:
                if here.read_bytes() != there.read_bytes():
                    differ.append(hook)
            except OSError:
                differ.append(f"{hook} (missing)")
        if differ:
            return (f"- 🔴 THE RUNNING HOOKS ARE NOT THE RELEASED v{version}: " + ", ".join(differ)
                    + f" differ from the catalog's copy in {release}")
    return None


def read_head(logbook: Path) -> str:
    try:
        return logbook.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


# The header's vocabulary. English is canonical inside the code (v3.2.0); the Bulgarian names
# every existing header uses -- transliterated or in Cyrillic -- are mapped to it on reading,
# forever. One map, read by every hook through `parse_frontmatter`: three readers that each
# learned a spelling on their own would disagree on the first field one of them forgot.
FIELD_SYNONYMS = {
    "sastoyanie": "state", "na_hod": "turn", "sledvashto": "next",
    "kriterii_zavarshvane": "done_when", "vremevi_kriterii": "timing", "prioritet": "priority",
    "umeniya": "skills", "vyarno_kum": "true_as_of", "pregled_sled": "review_after",
    "srok": "deadline", "kod": "code", "rezultat": "result",
    "вярно_към": "true_as_of", "преглед_след": "review_after",
}
VALUE_SYNONYMS = {
    "state": {"aktivna": "active", "активна": "active", "chakashta": "waiting", "чакаща": "waiting",
              "zamrazena": "frozen", "замразена": "frozen", "paused": "frozen",
              "postoyanna": "ongoing", "постоянна": "ongoing",
              "priklyuchila": "finished", "priklyuchena": "finished", "приключила": "finished",
              "приключена": "finished",
              # `done` is NOT mapped: tasks and plans share this field, and each already reads
              # `done` with its own meaning -- a task finished, a plan carried out.
              "otvoren": "open", "отворен": "open", "izpalnen": "done", "изпълнен": "done",
              "izostaven": "abandoned", "изоставен": "abandoned", "otkazan": "abandoned",
              "отказан": "abandoned", "zatvoren": "closed", "затворен": "closed",
              "priklyuchen": "closed", "приключен": "closed"},
    "turn": {"nie": "us", "ние": "us", "нас": "us"},
    "priority": {"visok": "high", "висок": "high", "sreden": "medium", "среден": "medium",
                 "nisak": "low", "нисък": "low"},
    "timing": {"po_izbor": "any", "по_избор": "any", "postoyanno": "recurring",
               "постоянно": "recurring"},
}


def _canonical(fm: dict) -> dict:
    """Bulgarian keys and values become the English ones; where both spellings of a field
    appear, the Bulgarian one wins, so a half-translated header never loses what it said."""
    out = {}
    for key, val in fm.items():                      # English (and unknown) keys first
        if key not in FIELD_SYNONYMS:
            out[key] = val
    for key, val in fm.items():                      # then the Bulgarian ones, which win
        if key in FIELD_SYNONYMS:
            out[FIELD_SYNONYMS[key]] = val
    for key, table in VALUE_SYNONYMS.items():
        val = out.get(key)
        if isinstance(val, str) and val.strip().lower() in table:
            out[key] = table[val.strip().lower()]
    return out


def parse_frontmatter(text: str) -> dict:
    """The header, with English names and values mapped to the internal ones."""
    return _canonical(_parse_raw(text))


def _parse_raw(text: str) -> dict:
    """A deliberately small parser: `key: value` lines between a leading pair of
    `---` fences. Scalars, quoted strings, `[a, b]` lists, and trailing ` #` comments.
    Not full YAML — Baton stays dependency-free."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fm
        s = line.strip()
        if not s or s.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            fm[key] = [x.strip().strip("\"'") for x in inner.split(",") if x.strip()]
            continue
        # A quoted value runs to the LAST quote on the line, and a `#` inside it
        # is text. Two truncations were found this way, both silent, because a
        # cut pointer reads exactly like a whole one: `... GitHub issue #1 ...`
        # was cut at the `#`, and then -- with a first-quote rule -- a value
        # quoting someone ("he said "wait"") was cut at the inner quote. Prose
        # with quotes in it is the normal case here; a comment after a quoted
        # value is not.
        if val[:1] in ('"', "'"):
            end = val.rfind(val[0])
            if end > 0:
                fm[key] = val[1:end]
                continue
        cut = val.find(" #")
        if cut != -1:
            val = val[:cut].strip()
        fm[key] = val.strip().strip("\"'")
    return {}  # no closing fence: not a header, just a logbook that opens with ---


def first_entry_title(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            m = DATED_HEADING.match(heading)
            return m.group("title").strip() if m else heading
    return ""


def deadline(fm: dict):
    """A date from `vremevi_kriterii: srok:YYYY-MM-DD` (or a bare `srok:` date field)."""
    for raw in (fm.get("timing", ""), fm.get("deadline", "")):
        if isinstance(raw, str) and "srok" in raw and ":" in raw:
            iso = raw.split(":", 1)[1].strip()
            try:
                return datetime.strptime(iso, "%Y-%m-%d").date()
            except ValueError:
                continue
        if isinstance(raw, str) and re.fullmatch(r"\d{4}-\d\d-\d\d", raw):
            try:
                return datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                continue
    return None


def _as_date(raw) -> date | None:
    """A date out of `2026-09-19` or `19.09.2026`, or None."""
    text = str(raw or "").strip()
    for pattern in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def review_due(fm: dict, today: date):
    """When this task's current-state header should be looked at again.

    `vyarno_kum` is the date the header was last true; `pregled_sled` is how long
    that is expected to hold ("30d", "6m"). Neither is required -- a task without
    them behaves exactly as before. The point of the pair is that a snapshot
    announces its own age instead of being read as current, which is how a
    coverage table written for one version came to be quoted three versions later.
    """
    since = _as_date(fm.get("true_as_of"))
    if since is None:
        return None
    raw = str(fm.get("review_after") or "").strip().lower()
    match = re.fullmatch(r"(\d+)\s*([dдmм])?", raw)
    if not match:
        return None
    count = int(match.group(1))
    days = count * 30 if match.group(2) in ("m", "м") else count
    due = since + timedelta(days=days)
    return (due, (today - due).days) if due <= today else None


def unverified_debt(folder: Path, today: date) -> tuple[int, int] | None:
    """Claims this task has written down and nobody has checked, and how old.

    Returns (count, age of the oldest in days). A claims register keeps a status
    column -- verified against a source, checked locally, an agent's word,
    inferred -- and the last two are debts. They are not wrong; they are unpaid.
    One of them ("auditors probably cannot take a commission") was carried for a
    day and nearly cancelled a plan before anyone read the code it claimed to
    summarise. Another ("this firm has no scanner of its own") was written with a
    note that it needed checking, and the note was the last anyone saw of it until
    it turned out to be false a day later, on the way into a letter.

    A row dates itself when it can; otherwise it takes the date of the heading
    above it. Both, because a register filled a row at a time has no block date
    and a table written in one sitting has no row dates.
    """
    for candidate in CLAIMS_FILES:
        facts = folder / candidate
        if facts.is_file():
            break
    else:
        return None
    try:
        text = facts.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None

    blocks = [(m.start(), _as_date(m.group(1))) for m in CLAIM_BLOCK.finditer(text)]
    count, oldest = 0, None
    for row in UNVERIFIED_ROW.finditer(text):
        end = text.find("\n", row.start())
        line = text[row.start():end if end != -1 else len(text)]
        written = None
        for cell in line.strip().strip("|").split("|"):
            stamp = ROW_DATE.match(cell.strip())
            if stamp:
                written = _as_date(stamp.group(1))
                break
        if written is None:
            written = next((d for start, d in reversed(blocks) if start < row.start()), None)
        if written is None:
            continue
        age = (today - written).days
        if age >= STALE_CLAIM_DAYS:
            count += 1
            oldest = age if oldest is None else max(oldest, age)
    return (count, oldest) if count else None


def _plain(text: str) -> str:
    """Lower-cased, with markdown emphasis and quotes removed.

    A sentence does not stop being the same sentence because someone bolded a
    word inside it. Comparing the raw text made `**only we** split` and
    `only we split` different strings, which is the wrong kind of exact.
    """
    return re.sub(r"[*_`\"'\u201e\u201c\u201d\u00ab\u00bb]", "", str(text)).lower().strip()


# A row of the constraints register: | id | status | file | text |
RETIRED_ROW = re.compile(
    r"^\s*\|\s*([\w.-]+)\s*\|\s*(пада|падна|falls|fallen|retired)\s*\|"
    r"\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$", re.M | re.I)


def retired_but_present(folder: Path) -> list[str]:
    """Constraints the register says have fallen, whose text is still where it said.

    Research adds; almost nothing retires. A constraint that nobody retires goes on
    steering the plan from a file no one re-reads, and writing "this one falls" in a
    register is not retiring it -- the sentence is still in the document the next
    round will quote. One project corrected such a sentence in its README, left it
    in its positioning document, and found it again a round later.

    So the register is checked against the files rather than believed: a row marked
    fallen whose text is still in the named file is reported, and stays reported
    until the text is gone.
    """
    register = folder / "OGRANICHENIYA.md"
    if not register.is_file():
        register = folder / "CONSTRAINTS.md"
        if not register.is_file():
            return []
    try:
        rows = register.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []

    still: list[str] = []
    for ident, _status, where, phrase in RETIRED_ROW.findall(rows):
        phrase = _plain(phrase)
        if len(phrase) < 8:            # too short to search for without false hits
            continue
        where = where.strip()
        name = where.split(":")[0].strip()
        target = (folder / name).expanduser()
        if not target.is_file():
            target = Path(name).expanduser()
        if not target.is_file():
            # A register naming a file that is not there is not a pass. Skipping it
            # silently is the same defect the register exists to catch: a rule that
            # looks retired because nobody could check it.
            still.append(f"{ident}: the file it names, {where}, does not exist")
            continue
        try:
            body = target.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            still.append(f"{ident}: {where} cannot be read")
            continue
        if phrase in _plain(body):
            still.append(f"{ident} in {where}")
    return still


# A pointer is one sentence: what to do next. Past this many characters it has
# stopped pointing and started holding state -- and state held in two places is
# state that goes stale in one of them.
POINTER_MAX = 240


def pointer_drift(fm: dict) -> int | None:
    """`sledvashto` that has grown from a pointer into a record.

    The field exists to say what the next move is. The logbook says what was done
    and the detail files say what is true; when those get copied into the pointer
    "so it is visible at session start", the same fact now lives in two places and
    only one of them gets corrected. One memory index carried "we are still waiting
    for the paper" for five days after the paper had arrived and been read, because
    the detail file was updated and the pointer was not.

    Length is a proxy, not the thing itself, and it is the only honest one available:
    a hook cannot tell a stale sentence from a current one. What it can tell is that
    a one-sentence field is now a paragraph, which is when the copying has happened.
    """
    text = str(fm.get("next", "")).strip()
    return len(text) if len(text) > POINTER_MAX else None


# A pointer naming a working file -- a decisions list, a questions file, a plan.
NAMED_FILE = re.compile(r"`?\b([A-Za-z0-9][A-Za-z0-9_.\-]*\.md)\b`?")


def kod_drift(fm: dict) -> str | None:
    """`kod: <path>@<ref>` -- the code this task's record rests on, and whether it moved.

    The file-mtime checks catch a folder whose files are newer than its logbook. This
    catches the other thing, which is quieter and reaches a person harder: the logbook
    is fine, well written, quoted at the top of every session -- and the code it
    describes has moved on underneath it.

    Twice on 2026-09-26 a memory file in this project claimed v2.8.0 and 132 tests while
    the tree stood at v2.13.1 and 194. Nothing about the record looked wrong. It was
    five releases stale and perfectly readable, which is the whole problem.

    ⚠️ Anything it cannot resolve is REPORTED, never skipped. A missing repository, an
    unknown ref and a malformed field are three different facts and all three are said
    out loud -- a check that quietly passes on what it could not read is worse than no
    check, because it is then trusted.

    Returns a line for the report, or None when the field is absent or the code has not
    moved. Absent means no opinion: not every task describes code.
    """
    raw = str(fm.get("code", "")).strip()
    if not raw:
        return None
    if "@" not in raw:
        return (f"`code: {raw[:60]}` has no `@` — write `code: <path to repository>@<commit "
                f"or tag>`, otherwise there is nothing to compare")
    where, _, ref = raw.rpartition("@")
    repo = Path(where.strip()).expanduser()
    ref = ref.strip()
    if not (repo / ".git").exists():
        return f"`code:` points at {repo}, which is not a repository — the record rests on nothing checkable"

    def git(*args) -> str | None:
        try:
            done = subprocess.run(["git", "-C", str(repo), *args],
                                  capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    pinned = git("rev-parse", "--verify", f"{ref}^{{commit}}")
    if not pinned:
        return (f"`code:` points at `{ref}` in {repo.name}, which is **not found** there — a deleted "
                f"branch, an unpushed commit or a mistyped tag. Not read as \"matches\"")
    head = git("rev-parse", "HEAD")
    if not head:
        return f"`code:` could not read the HEAD of {repo.name} — saying so rather than passing over it"
    if head == pinned:
        return None
    behind = git("rev-list", "--count", f"{pinned}..{head}")
    if behind is None:
        return (f"`code:` {repo.name} is on a different commit from `{ref}` ({pinned[:7]}), and the "
                f"difference could not be counted")
    if behind == "0":
        return (f"`code:` {repo.name} is on a commit that is NOT a descendant of `{ref}` ({pinned[:7]}) "
                f"— a fork or rewritten history")
    # When the ref IS the sha, naming both reads as a stutter: "after `7374660` (7374660)".
    where_ref = f"`{ref}`" if not pinned.startswith(ref.lower()) else f"`{pinned[:7]}`"
    return (f"`code:` {repo.name} is **{behind}** commits after {where_ref} — the record describes code "
            f"that has moved underneath it")


def stale_reference(folder: Path, logbook: str, fm: dict) -> list[str]:
    """A pointer sending you to a file that has not moved since the work did.

    The hooks catch a folder whose files are newer than its logbook. They do not
    catch the opposite, which turns out to be the one that actually reaches a
    person: a decisions file that is *older* than the logbook. Nothing about it
    looks wrong. It is well written, it lists open questions, and the pointer
    quotes it at the top of every session -- so it gets read first and believed.

    What it cannot know is that the questions were answered somewhere else. A
    negative corpus asked for in one task's decisions file was built two days
    later in another task's folder and shipped in a release; the question stayed
    open where it had been asked, and was handed back as unfinished work three
    sessions running before the person said so.

    So: when `sledvashto` names a file that is in this folder, and that file has
    not been touched since the logbook's last entry, say so. It is not a claim
    that the file is wrong -- only that work was recorded after it was last read,
    which is exactly when a snapshot goes stale and exactly when nobody looks.

    A name that is not a file in this folder is left alone. The pointer may
    legitimately mention the memory index or a document elsewhere, and a hook
    that cannot check something must not imply that it did.
    """
    try:
        book_day = date.fromtimestamp((folder / logbook).stat().st_mtime)
    except OSError:
        return []
    out: list[str] = []
    for name in sorted({n for n in NAMED_FILE.findall(str(fm.get("next", "")))
                        if n.lower() != logbook.lower()}):
        target = folder / name
        if not target.is_file():
            continue
        try:
            seen = date.fromtimestamp(target.stat().st_mtime)
        except OSError:
            continue
        gap = (book_day - seen).days
        if gap >= 1:
            out.append(f"{name} (last touched {seen}, the logbook runs to {book_day})")
    return out


# A skill does not go out of date because the logbook moved yesterday. The first
# version compared at a day's granularity and fired on every active task the
# morning after the skills were written, which is the failure mode of every
# detector: one that cries on a normal Tuesday gets switched off, and then the
# real signal goes with it. Weeks is the honest scale for "the task has moved on
# substantially and nobody has revisited how it is done".
SKILL_STALE_DAYS = 14


def skills_root() -> Path:
    """Where the skills live. `~/.claude/skills` unless told otherwise."""
    try:
        cfg = json.loads((_local_file("baton.local.json")).read_text("utf-8-sig"))
    except Exception:
        cfg = {}
    raw = os.environ.get("BATON_SKILLS") or cfg.get("skills")
    return Path(raw).expanduser() if raw else claude_dir() / "skills"


def skills_for(fm: dict) -> list[str]:
    """What the task's header says it needs: `umeniya: [a, b]`."""
    value = fm.get("skills") or []
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",") if v.strip()]
    return [str(v).strip() for v in value if str(v).strip()]


def skill_trouble(names: list[str], folder: Path, logbook: str) -> list[str]:
    """Skills a task asks for that are missing, or older than the work.

    A task carries state and history; it does not carry competence. Naming the
    skills it needs is how the header supplies the third one -- and this is the
    check that keeps the naming honest.

    Two failures, and the second is the dangerous one.

    **Missing** is loud: the header asks for something that is not installed, and
    nothing will load.

    **Stale** is quiet, and a stale skill is worse than a missing one, because a
    missing skill makes you think while a stale one makes you confident. A skill
    written once and re-read fifty times is exactly where knowledge goes out of
    date without anybody noticing -- the same shape as a decisions file older than
    the logbook, which is why the same comparison is used: last touched before the
    task's last entry.

    Nothing is fetched, updated or adopted here. The hook says what it sees; the
    human decides. That rule matters more for skills than anywhere else in Baton,
    because a skill is instructions, and instructions fail silently where code
    fails loudly.
    """
    if not names:
        return []
    root = skills_root()
    grace = SKILL_STALE_DAYS
    try:
        book_day = date.fromtimestamp((folder / logbook).stat().st_mtime)
    except OSError:
        return []
    out: list[str] = []
    inside = Path(os.environ["CLAUDE_PLUGIN_ROOT"]) / "skills" if plugin() else None
    for name in names:
        # A plugin's skills live inside it and may be written with its prefix.
        bare = name.split(":", 1)[1] if name.startswith("baton:") else name
        skill = root / name / "SKILL.md"
        if not skill.is_file() and inside is not None and (inside / bare / "SKILL.md").is_file():
            skill = inside / bare / "SKILL.md"
        if not skill.is_file():
            out.append(f"{name} — MISSING in {root}" + (f" and in {inside}" if inside else ""))
            continue
        try:
            seen = date.fromtimestamp(skill.stat().st_mtime)
        except OSError:
            continue
        if (book_day - seen).days >= grace:
            out.append(f"{name} — written {seen}, while the logbook runs to {book_day}")
    return out


# A plan ends in one of two ways, and they are not the same fact. "Carried out"
# and "given up on" both finish a task and leave completely different histories
# behind -- and a folder read six weeks later has to say which. `zatvoren` stays
# accepted for plans closed before the distinction existed.
# The states that mean the task itself is finished. Named once, because the plan check
# now reads them too and two spellings of the same list is how one of them rots.
FINISHED = ("finished", "done")

PLAN_DONE = {"done", "carried_out"}
PLAN_ABANDONED = {"abandoned"}
PLAN_CLOSED = PLAN_DONE | PLAN_ABANDONED | {"closed"}


def open_plan(folder: Path) -> str | None:
    """A plan that was never closed, and the task it leaves unfinished.

    Research was run, a plan was written, work was done against it -- and then the
    plan was simply never closed. Nothing said so. The task looked active because
    it *was* active, and the question of whether the plan had been carried out
    never came back. Over six weeks this project ran reconnaissance, analysis and
    planning repeatedly and closed a plan exactly never.

    So: a task holding a `PLAN.md` that does not say it is closed is unfinished,
    and it is reported every session rather than after some grace period. Unlike a
    stale skill, this is not a guess about whether something went out of date --
    the plan either says it is finished or it does not.

    **Closing requires saying what came of it.** A state with no `rezultat` is not
    closed; it is a tick, and a tick is how a check gets satisfied without the
    thing behind it being true.

    **And a plan ends in one of two ways.** `izpalnen` -- it was carried out --
    and `izostaven` -- it was given up on. Both finish the task; neither is a
    failure of record-keeping. But they are different facts, and a folder read six
    weeks later has to say which, the same way this project refuses to let
    "we read it" and "we found it" share a number.

    **Every plan in the folder counts, not just `PLAN.md`.** A task that runs two
    efforts names them apart -- `PLAN-jev.md`, `PLAN-migraciya.md` -- and matching
    one exact filename let precisely those escape. The check was written for this
    project and then missed this project's own second plan: the rule held for the
    file it was named after and for nothing else.

    The pattern is `PLAN.md` and `PLAN-*.md`, not `PLAN*`: a folder is free to keep
    `PLANOVE-stari.md` as notes without being told it has an unclosed plan.
    """
    plans = sorted(p for p in (*folder.glob("PLAN.md"), *folder.glob("PLAN-*.md"))
                   if p.is_file())
    if not plans:
        return None                      # not every task needs a plan
    problems = [note for note in (_plan_problem(p) for p in plans) if note]
    return "; ".join(problems) if problems else None


def _plan_problem(plan: Path) -> str | None:
    fm = parse_frontmatter(read_head(plan))
    try:
        age = (date.today() - date.fromtimestamp(plan.stat().st_mtime)).days
    except OSError:
        age = 0
    old_note = f", last touched {age} days ago" if age >= 1 else ""
    state = str(fm.get("state", "")).strip().lower()
    if state not in PLAN_CLOSED:
        if not fm:
            return f"{plan.name} has no header, so it was never closed{old_note}"
        return f"{plan.name} is `{state or 'no state'}`{old_note}"
    if not str(fm.get("result") or "").strip():
        return (f"{plan.name} says it is closed but not what came of it "
                "(`result:`) — a close without a result is a tick box")
    return None


def _our_names() -> set:
    """Names that mean "us" on this machine -- a person's own name in `turn:` -- from
    `us` in baton.local.json. Kept out of the code: a public tool should not carry one
    user's name as a built-in synonym (it did until v3.0.0)."""
    try:
        cfg = json.loads((_local_file("baton.local.json")).read_text("utf-8-sig"))
        return {str(n).strip().lower() for n in cfg.get("us", [])}
    except Exception:
        return set()


def is_us(fm: dict) -> bool:
    return str(fm.get("turn", "")).strip().lower() in (US | _our_names())


def prio(fm: dict) -> int:
    return PRIORITY_RANK.get(str(fm.get("priority", "")).strip().lower(), 3)


def line_for(name: str, fm: dict, tail: str = "") -> str:
    p = str(fm.get("priority", "")).strip()
    dot = PRIORITY_DOT.get(p.lower())
    badge = (f" {dot} [{p}]" if dot else f" [{p}]") if p else ""
    nxt = fm.get("next") or fm.get("done_when") or ""
    body = f" — {nxt}" if nxt else ""
    # Named, not loaded. The agent reads this and invokes what it needs; the hook
    # never reaches into the session to load anything on its behalf.
    skill_names = skills_for(fm)
    skills = f"  ⟨skills: {', '.join(skill_names)}⟩" if skill_names else ""
    return f"- {name}{badge}{body}{tail}{skills}"


def _own_session() -> dict:
    """What Claude Code says about this session on stdin: its id and its transcript. Read as
    bytes and decoded as UTF-8, as baton_prompt.py does; anything unreadable is no answer."""
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def inventory_notice(today: date, own: dict | None = None) -> str | None:
    """No task folders yet, but months of Claude Code behind them: offer /baton-inventory.

    Found 2026-09-29: the installer printed one line about it, and a line printed once at
    install is a line nobody acts on. Once a day while the root stays empty.

    This session's own transcript is not earlier work. Found 2026-10-02 in a Claude Desktop
    cloud session: an empty container held one transcript, its own, and the hook offered an
    inventory of "1 earlier conversation" that did not exist.
    """
    claude = claude_dir()
    own = own or {}
    mine = str(own.get("session_id") or "")
    path = str(own.get("transcript_path") or "")
    try:
        talks = [t for t in (claude / "projects").glob("*/*.jsonl")
                 if not (mine and t.stem == mine) and not (path and str(t) == path)]
    except OSError:
        return None
    if not talks:
        return None
    try:
        state = json.loads(_state_file().read_text("utf-8"))
    except Exception:
        state = {}
    if state.get("inventory_offered") == today.isoformat():
        return None
    state["inventory_offered"] = today.isoformat()
    try:
        _state_file().write_text(json.dumps(state), "utf-8")
    except OSError:
        pass
    oldest = date.fromtimestamp(min(t.stat().st_mtime for t in talks))
    return (f"📦 No task folders yet, but this machine has {len(talks)} earlier Claude Code "
            f"conversations (the oldest from {oldest.isoformat()}). Offer the human {command('baton-inventory')}: "
            "it maps that earlier work into task folders, and creates nothing until they confirm "
            "each one. Ask once; if they decline, leave it.")


def release_leads(version: str) -> list[str]:
    """The bold first sentence of each note under this version in the README's Versions."""
    try:
        text = (Path(__file__).resolve().parent.parent / "README.md").read_text("utf-8")
    except OSError:
        return []
    start = text.find(f"**v{version}**")
    if start < 0:
        return []
    end = text.find("\n**v", start + 1)
    section = text[start:end if end > 0 else len(text)]
    return re.findall(r"^- \*\*(.+?)\*\*", section, re.M)


def whats_new_notice() -> str | None:
    """Once after an update: what is new, from the README that came with it. No network.

    Installed from the directory, Baton updates itself at the next launch and Claude Code says
    only "Plugins changed" -- nothing tells the human what changed (stenly, 2026-10-05). The
    last version this machine ran is kept in the state file. A fresh install is not told it was
    updated; a state file without the version is an install from before v3.12.0, which is."""
    try:
        state = json.loads(_state_file().read_text("utf-8"))
    except Exception:
        state = None
    seen = (state or {}).get("seen_version")
    if seen == BATON_VERSION:
        return None
    state = state if isinstance(state, dict) else {}
    upgraded = bool(state) and (seen is None or _version(seen) < _version(BATON_VERSION))
    state["seen_version"] = BATON_VERSION
    try:
        _state_file().write_text(json.dumps(state), "utf-8")
    except OSError:
        return None                 # cannot remember it was said: better silent than every day
    if not upgraded:
        return None
    leads = release_leads(BATON_VERSION)
    since = f"from v{seen} " if seen else ""
    return (f"⬆️ Baton was updated {since}to v{BATON_VERSION} since this machine last ran it. "
            "Tell the human once, in their language, in a few short lines, what is new"
            + (": " + "; ".join(leads) if leads else "")
            + f". Full notes: https://github.com/StanimirTenev/baton/releases/tag/v{BATON_VERSION} "
            "-- this note does not come back.")


def review_notice() -> str | None:
    """The optional review, offered once ever -- never run.

    ZA-OPRAVYANE #2 (2026-10-03): installed fresh, the review appeared nowhere and the agent
    never mentioned it, so a user could not learn it exists. It costs money and sends text
    off the machine, so it is offered, with both said plainly, and the human decides. Not when
    a key is already stored (they know of it); the key file is only checked for, never read."""
    if (Path.home() / ".config" / "baton" / "env").is_file():
        return None
    try:
        state = json.loads(_state_file().read_text("utf-8"))
    except Exception:
        state = {}
    if state.get("review_offered"):
        return None
    state["review_offered"] = date.today().isoformat()
    try:
        _state_file().write_text(json.dumps(state), "utf-8")
    except OSError:
        return None                 # cannot remember the offer: better silent than every day
    return ("💡 Once, and only this once: Baton has an optional review that checks whether the "
            "lines of an index (a MEMORY.md, a list of pointers) still match the files they "
            "point to. Mention it to the human in one or two lines, in their language, with "
            "both of these: it SENDS the pointer and part of the file it points to to "
            "OpenRouter (TypeSafe's Jev model) -- folders the human lists as confidential are "
            "held back before anything is sent; and it COSTS money on their own OpenRouter key "
            "(about $0.0013 for one review of a 19-line index, measured by the author). Setting "
            f"up the key: {command('baton-key')}. It never runs by itself; do not run it without "
            "their yes. If they are not interested, drop it -- this note does not come back.")


# A session that touched no task folder is never asked about: Stop judges by file times, and a
# decision made only in chat passes clean (ZA-OPRAVYANE row 26; Jake Manis, 20.10, and four more
# conversations that week). At the next start, the last session's messages are put next to the
# entries written in that time -- two numbers, no judgement -- and the messages are named, so the
# human can tell whether any of it was a decision. A message is one the human typed: the agent's
# turns multiply in loops and subagents, tool results and command output are not anyone's word.
QUIET_MIN_MESSAGES = 3          # fewer is a question asked and answered, not a lost decision
QUIET_SLACK = timedelta(minutes=15)   # an entry written just after the last message counts
QUIET_MAX_BYTES = 16 * 1024 * 1024
_STAMP = re.compile(rb'"timestamp":\s*"([^"]+)"')
_USER = re.compile(rb'"type":\s*"user"')
# Both forms (row 69): an entry headed `## 22.10.2026 15:30` in the session's time was not counted,
# and the session was called quiet.
_ENTRY_HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})(?:[ T](\d{1,2}):(\d{2}))?",
                            re.M)


def _human(obj: dict) -> str | None:
    """The text of a message the human typed, or None."""
    if obj.get("type") != "user" or obj.get("isMeta") or obj.get("isSidechain"):
        return None
    content = (obj.get("message") or {}).get("content")
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        content = " ".join(str(b.get("text", "")) for b in content
                           if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(content, str):
        return None
    text = content.strip()
    if not text or text.startswith("<") or text.startswith("[Request interrupted"):
        return None
    return text


def _local_time(stamp) -> datetime | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


# What a pasted key looks like (ZA-OPRAVYANE row 48, Bernard Haddad and Bachittarjeet Singh Sidhu,
# 22.10, said publicly): quiet_session quotes the human's messages into the new session's context,
# and a fake key pasted into one came back verbatim. Masked before the 70-character cut, so a key
# cut in half is still seen whole. Shapes, not a proof: a key of no known shape and under 32
# characters is still quoted.
_SECRET = re.compile(
    r"(?<![A-Za-z])sk-[A-Za-z0-9_-]{8,}"                          # OpenAI, Anthropic, OpenRouter
    r"|\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"   # GitHub
    r"|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"                              # AWS
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}"                             # Slack
    r"|\bAIza[0-9A-Za-z_-]{30,}"                                   # Google
    r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"   # a JWT
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|(?i:\b(?:api[_-]?key|token|secret|password|passwd|pwd)\s*[:=]\s*\S+)"
    r"|(?i:\bbearer\s+[A-Za-z0-9._~+/-]{8,}=*)"
    r"|\b[0-9a-fA-F]{32,}\b"                                       # long hex
    # long base64: upper, lower and a digit, no separators (a file name like
    # Biznes-plan-DORA-dokument-2026-09-20 is not one; on the real logbooks, 22.10)
    r"|(?<![A-Za-z0-9+=])(?=[A-Za-z0-9+=]*\d)(?=[A-Za-z0-9+=]*[a-z])(?=[A-Za-z0-9+=]*[A-Z])"
    r"[A-Za-z0-9+=]{32,}")


def mask_secrets(text: str) -> str:
    return _SECRET.sub("[masked]", text)


def human_messages(path: Path) -> tuple[list, datetime | None, datetime | None, bool]:
    """(when, text) of every message the human typed in a transcript, its first and last time,
    and whether only its last QUIET_MAX_BYTES were read. Raises OSError when it cannot be read."""
    said, start, end, cut = [], None, None, False
    with open(path, "rb") as fh:
        size = Path(path).stat().st_size
        if size > QUIET_MAX_BYTES:
            fh.seek(size - QUIET_MAX_BYTES)
            fh.readline()
            cut = True
        for raw in fh:
            # Only a line that can be a human message is parsed; the time is cut out of the
            # rest as bytes. A 73 MB transcript took 3.5 s parsed whole (21.10, under load).
            stamp = _STAMP.search(raw)
            when = _local_time(stamp.group(1).decode("ascii", "replace")) if stamp else None
            if when is None:
                continue
            start, end = min(start or when, when), max(end or when, when)
            if not _USER.search(raw) or b'"tool_result"' in raw:
                continue
            try:
                obj = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            text = _human(obj) if isinstance(obj, dict) else None
            if text:
                said.append((when, text))
    return said, start, end, cut


def entry_times(folders: list, logbook: str):
    """(time, has an hour) of every dated entry heading in these folders' logbooks."""
    for f in folders:
        for m in _ENTRY_HEADING.finditer(read_head(Path(f) / logbook)):
            try:
                day = datetime.strptime(m.group(1), "%Y-%m-%d" if "-" in m.group(1) else "%d.%m.%Y")
            except ValueError:
                continue
            if m.group(2):
                yield day.replace(hour=int(m.group(2)), minute=int(m.group(3))), True
            else:
                yield day, False


def quote(said: list, n: int = 5) -> str:
    """The first `n` messages, masked, each cut at 70 characters."""
    return "; ".join(f"\"{mask_secrets(t)[:70]}\"" for t in said[:n]) + (" ..." if len(said) > n else "")


# The same count inside the session still going (the owner, 24.10): the next start comes after
# /clear, and /clear is what Baton itself suggests at ~200k -- so the question came one context too
# late, once the conversation was already gone. Messages typed after the last entry headed in this
# session's time; a heading with no hour covers its whole day, as in Stop's session_entries.
def chat_since_entry(transcript: str, folders: list, logbook: str) -> tuple[list, int] | None:
    """((when, text) typed since the last entry this session, how many typed this session), or
    None when the transcript cannot be read."""
    try:
        timed, start, _, _ = human_messages(Path(transcript))
    except (OSError, ValueError):
        return None
    if start is None:
        return None
    last = None
    for at, timed_heading in entry_times(folders, logbook):
        at = at if timed_heading else at.replace(hour=23, minute=59)
        if at >= start - QUIET_SLACK and (last is None or at > last):
            last = at
    return [(when, t) for when, t in timed if last is None or when > last], len(timed)


def quiet_session(own: dict, folders: list, logbook: str) -> str | None:
    """The last session in this project said things and wrote no entry: say so, once."""
    mine = Path(str(own.get("transcript_path") or ""))
    if not mine.name or not mine.parent.is_dir():
        return None
    try:
        others = [t for t in mine.parent.glob("*.jsonl")
                  if t != mine and t.stem != str(own.get("session_id") or "")]
        last = max(others, key=lambda t: t.stat().st_mtime) if others else None
    except OSError:
        return None
    if last is None:
        return None
    key = f"{last}|{int(last.stat().st_mtime)}"
    try:
        state = json.loads(_state_file().read_text("utf-8"))
    except Exception:
        state = {}
    if state.get("quiet_checked") == key:
        return None
    try:
        timed, start, end, cut = human_messages(last)
    except OSError:
        return None
    said = [text for _, text in timed]
    state["quiet_checked"] = key
    try:
        _state_file().write_text(json.dumps(state), "utf-8")
    except OSError:
        return None                 # cannot remember it was said: better silent than every time
    if len(said) < QUIET_MIN_MESSAGES or start is None:
        return None
    entries = 0
    for at, timed_heading in entry_times(folders, logbook):
        if timed_heading:
            entries += start - QUIET_SLACK <= at <= end + QUIET_SLACK
        else:
            entries += start.date() <= at.date() <= end.date()
    if entries:
        return None
    shown = quote(said)
    return (f"📝 The last session in this project ({start:%Y-%m-%d %H:%M}–{end:%H:%M}) had "
            f"{len(said)} messages from the human and 0 logbook entries headed in that time"
            + (f" (counted in its last {QUIET_MAX_BYTES >> 20} MB)" if cut else "") + ". Stop asks only about files, so "
            "a decision made only in chat leaves no trace. Its messages began: " + shown + ". "
            "Ask the human once, in their language, whether any of it should be recorded and in "
            "which task; if not, drop it. (Messages the human typed, not the agent's turns; "
            "entries by the time in their heading.)")


FEEDBACK_AFTER_DAYS = 7
ISSUES = "https://github.com/StanimirTenev/baton/issues"


def feedback_notice(today: date) -> str | None:
    """After about a week of use, once ever: ask the human what worked, what did not, and what
    they would improve -- and where to tell the author. Baton sends nothing.

    ZA-OPRAVYANE row 17 (stenly, 07.10): installs come from the comments, and nobody knows why
    most never reach real use. The week counts from the first start this state file saw, so an
    install from before this note counts from the update that brought it."""
    try:
        state = json.loads(_state_file().read_text("utf-8"))
    except Exception:
        state = {}
    if state.get("feedback_asked"):
        return None
    first = _as_date(state.get("first_seen"))
    if first is None or (today - first).days < FEEDBACK_AFTER_DAYS:
        if first is None:
            state["first_seen"] = today.isoformat()
            try:
                _state_file().write_text(json.dumps(state), "utf-8")
            except OSError:
                pass
        return None
    state["feedback_asked"] = today.isoformat()
    try:
        _state_file().write_text(json.dumps(state), "utf-8")
    except OSError:
        return None                 # cannot remember the question: better silent than every day
    return (f"💬 Once, and only this once: Baton has been running here for {(today - first).days} "
            "days. Ask the human one short question, in their language: what has worked, what has "
            "not, and what they would improve. If they want the author to hear it, the place is "
            f"{ISSUES}. Baton sends nothing itself. If they would rather not, drop it -- this note "
            "does not come back.")


SHOW_BOARD = (
    "The human has not seen this board -- only one line saying Baton is on. Whatever the "
    "human's first message is -- a greeting, a question or a task -- the first thing in your "
    "first reply is the WHOLE board, translated into the human's language; then answer them. "
    "Show every group and every line, nothing shortened or left out -- no summary, no merged lines, "
    "no \"...and the rest\", and the notes in parentheses too. Task names, file names, "
    "commands, fields in backticks and identifiers stay as they are."
)


def start_line(on_move: int = 0, ongoing: int = 0, outside: int = 0,
               root: Path | None = None, twice: bool = False, plain: int = 0) -> str:
    """The one line the human sees in the terminal at session start. English, because the hook
    cannot know the human's language; the agent shows the board itself in that language.
    Without it, a session where the agent did not show the board looked like a session without
    Baton (a Mac, 2026-09-30)."""
    if twice:
        return ("🧭 Baton is installed twice here -- write anything and the agent will say "
                "which one to remove.")
    if root is not None:
        return (f"🧭 Baton is on -- no task folders yet in {root}. Write anything and the "
                "agent will help you start one.")
    parts = [f"{n} {label}" for n, label in ((on_move, "on your move"), (ongoing, "ongoing"),
                                             (outside, "waiting on others"),
                                             (plain, "without a header")) if n]
    return ("🧭 Baton: " + (", ".join(parts) or "nothing waiting") +
            ". Write anything and the agent opens its reply with the full board.")


def plugin_rules() -> str | None:
    """Baton's rules, when installed as a plugin and nowhere else.

    install.sh appends templates/CLAUDE.md to ~/.claude/CLAUDE.md: the fallback that holds
    where a hook does not. A plugin's CLAUDE.md is never loaded, so a plugin install would
    lose the rules; they come from here instead. Not when the installer has already put
    them in CLAUDE.md -- the same marker it checks before appending -- or they would be
    read twice."""
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not root:
        return None
    try:
        # Any encoding the file may be in, never an exception: PowerShell 5 writes UTF-16,
        # older files are cp1251, and an error here once took the whole board with it.
        raw = (claude_dir() / "CLAUDE.md").read_bytes()
        mine = (raw.decode("utf-16", "replace") if raw[:2] in (b"\xff\xfe", b"\xfe\xff")
                else raw.decode("utf-8", "replace"))
        if "Installed by Baton" in mine:
            return None
    except OSError:
        pass
    try:
        text = (Path(root) / "templates" / "CLAUDE.md").read_text("utf-8")
    except (OSError, ValueError):
        return None
    tasks, logbook = config()
    # The same filling the installers do (hooks/_install_rules.py): the template's
    # "`$BATON_HOME` (default `~/tasks`)" read as a second, empty task root.
    text = text.replace("`$BATON_HOME` (default `~/tasks`)", f"`{tasks}`")
    text = text.replace("$BATON_HOME", str(tasks)).replace("LOGBOOK.md", logbook)
    return (f"Baton's working rules. Baton is installed as a plugin, so they arrive here rather "
            f"than from CLAUDE.md. On this machine the task root is {tasks} and the logbook "
            f"file in each task folder is {logbook}.\n\n"
            + re.sub(r"`/(baton-[a-z-]+)`", lambda m: f"`{command(m.group(1))}`", text))


def _marked(block: str, text: str | None) -> str | None:
    """A fixed first line naming the block, so a tool that attributes context to its source
    can tell the board (grows with the tasks) from the rules (fixed) -- asked for 2026-10-10."""
    return f"[baton:{block} v{BATON_VERSION}]\n{text}" if text else None


def _emit(context: str | None, line: str | None = None, block: str = "board") -> int:
    """The one way out: the agent's context (plus the rules in plugin mode) and the one line
    the human sees."""
    text = "\n\n".join(t for t in (_marked(block, context), _marked("rules", plugin_rules()))
                       if t)
    out: dict = {}
    if line:
        out["systemMessage"] = line
    if text:
        out["hookSpecificOutput"] = {"hookEventName": "SessionStart", "additionalContext": text}
    if out:
        _write(out)
    return 0


def _write(out: dict) -> None:
    """UTF-8 on the wire, not \\uXXXX: a Cyrillic board went out as 13,068 characters of JSON
    for 5,667 of text (2026-10-03). Claude Code's 10,000-character cap is measured on each
    parsed field, so the escaping never cut anything -- but bytes, not `print`, so a Windows
    pipe in cp1252 cannot turn the text into an exception."""
    sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
    sys.stdout.flush()


def _notices_only(notices: list[str], line: str | None = None) -> int:
    """A board with no tasks still carries what the agent must say to the human."""
    return _emit("\n\n".join(notices) if notices else None, line)


COMPACT_LINE = "🧭 Baton: context compacted -- the agent writes the logbook before going on."

CLEARED = ("Baton: the human typed /clear to continue with a fresh context -- the previous "
           "conversation is gone from it, and Baton asked for the logbooks to be written just "
           "before. Do not ask what was being done: the board below and each task's logbook "
           "hold it. Show the board as usual; the tasks touched most recently are the ones "
           "they were working on, so read the top entry of those logbooks before the human's "
           "next request.")


def compacted(own: dict) -> str:
    """What the agent is told right after compaction (SessionStart, `source: "compact"`).

    Promised publicly on 2026-10-03. A PreCompact hook cannot do this: Claude Code discards
    its `systemMessage` and gives it no `additionalContext`, only the power to block the
    compaction (code.claude.com/docs/en/hooks#precompact). So the reminder comes right after,
    while the summary still holds what was done. Not the board: before v3.12.0 this case got
    the whole board again, with the instruction to open the next reply with it."""
    root, name = config()
    folders: list[str] = []
    lost = ""
    try:
        spec = importlib.util.spec_from_file_location(
            "baton_stop", Path(__file__).with_name("baton_stop.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if root.is_dir():
            folders = mod.unrecorded(root, name,
                                     mod.session_started(str(own.get("transcript_path") or "")))
            lost = mod.lost_note(mod.LOST, mod.FORGOT) if mod.LOST or mod.FORGOT else ""
    except Exception:
        folders = []
    text = ("Baton: the conversation was just compacted. What happened before this point now "
            "exists only in the summary above, and the next compaction will thin it further. "
            f"Before going on, write the {name} entry for every task worked on in this session "
            "that its logbook does not yet record -- what was asked, what was done, the result, "
            "what is still open -- while the summary still holds it. Decisions and conversations "
            "count, not only files. Then continue with the human's work; do not show the board "
            "again.")
    if folders:
        text += ("\n\nTask folders holding this session's work, newer than their "
                 f"{name}:\n" + "\n".join(f"- {f}" for f in folders))
    if lost:
        text += "\n\n" + lost + " Tell the human in one line."
    return text


UNREAD: list = []     # the note for folders the walk did not read to the end (row 35)
LOST: list = []       # the note for history gone without an entry saying so (row 37)


def unlogged_work(root: Path, name: str) -> list[str]:
    """Folders holding work newer than their logbook -- the Stop hook's own check, without its
    session limit. Never a reason to lose the board. Folders over the Stop hook's WALK_CAP
    leave their note in UNREAD."""
    UNREAD.clear()
    LOST.clear()
    try:
        spec = importlib.util.spec_from_file_location(
            "baton_stop", Path(__file__).with_name("baton_stop.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        found = mod.unrecorded(root, name)
        if mod.TRUNCATED:
            UNREAD.append(mod.unread_note(mod.TRUNCATED))
        if mod.LOST or mod.FORGOT:
            LOST.append(mod.lost_note(mod.LOST, mod.FORGOT))
        return found
    except Exception:
        return []


def main() -> int:
    if installed_twice():
        # Not _emit(): the rules already come from the installer's CLAUDE.md.
        _write({"systemMessage": start_line(twice=True),
                "hookSpecificOutput": {"hookEventName": "SessionStart",
                                       "additionalContext": _marked("twice", twice_message())}})
        return 0
    own = _own_session()          # stdin is read once; everything below gets it from here
    if own.get("source") == "compact":
        return _emit(compacted(own), COMPACT_LINE, block="compact")
    cleared = own.get("source") == "clear"
    root, name = config()
    if os.environ.get("CLAUDE_PLUGIN_ROOT") and not root.exists() and root.parent != root:
        try:
            root.mkdir()        # as install.sh does for a script install; never a drive root
        except OSError:
            pass
    notices = [n for n in (crash_notice(), tests_notice(), whats_new_notice(), update_notice(date.today()),
                           lessons_notice(), review_notice(), feedback_notice(date.today())) if n]
    folders = task_folders(root) if root.is_dir() else []
    if folders:
        open_board(own.get("source"), root, name)
    if folders and own.get("source") in ("startup", "clear"):
        try:
            quiet = quiet_session(own, folders, name)
        except Exception:
            quiet = None            # a count that cannot be made must not cost the board
        if quiet:
            notices.append(quiet)
    if not folders:
        return _notices_only(notices + [n for n in (inventory_notice(date.today(),
                                                                     own),) if n],
                             start_line(root=root))

    overdue, recurring, on_us, external, plain, finished, frozen = [], [], [], [], [], [], []
    stale: list[str] = []
    unfinished: list[str] = []
    today = date.today()

    drifted = install_drift()
    if drifted:
        stale.append("- 🔴 THE RUNNING HOOKS ARE NOT FROM THE SOURCE: " + ", ".join(drifted)
                     + " — a fix that is not installed does not work, however tagged it is")
    as_plugin = plugin_drift()
    if as_plugin:
        stale.append(as_plugin)

    for f in folders:
        lb = f / name
        text = read_head(lb) if lb.is_file() else ""
        fm = parse_frontmatter(text) if text else {}
        if not fm:  # no header → original behaviour, sorted by mtime later
            plain.append(f)
            continue
        sast = str(fm.get("state", "")).strip().lower()
        # 🔴 An open plan is checked BEFORE the status branch, not after it. A finished
        # header used to `continue` seventeen lines before `open_plan` was called, so a
        # logbook and a plan could say opposite things about whether the work was done
        # and only one of them was ever shown. Found by an external review of v2.14.0.
        #
        # Finishing the task in the header does not close the plan. Saying it does is
        # the tick that satisfies a check without the thing behind it being true --
        # which is the same reason `rezultat:` is required to close one.
        plan_now = open_plan(f)
        if plan_now:
            unfinished.append(f"- {f.name} — {plan_now}"
                              + (" ⚠️ and the header says finished" if sast in FINISHED else ""))
        if sast in FINISHED:
            finished.append(f.name)
            continue
        if sast == "frozen":
            # parked on purpose: shown for the record, never offered as work
            frozen.append(f.name)
            continue

        # Shelf life. A frozen or finished task is skipped above on purpose: a
        # snapshot nobody is working from cannot mislead anybody.
        due = review_due(fm, today)
        if due:
            _, late = due
            stale.append(f"- {f.name} — the state review was due {late} "
                         f"{'day' if late == 1 else 'days'} ago (`true_as_of` + `review_after`)")
        debt = unverified_debt(f, today)
        if debt:
            count, age = debt
            stale.append(f"- {f.name} — {count} unverified claims (status I/A), "
                         f"the oldest {age} days old")
        moved = kod_drift(fm)
        if moved:
            stale.append(f"- {f.name} — {moved}")
        drift = pointer_drift(fm)
        if drift:
            stale.append(f"- {f.name} — `next` is {drift} characters: a pointer that has started "
                         f"carrying state. State lives in the logbook; this field holds the next move")
        bad_skills = skill_trouble(skills_for(fm), f, name)
        if bad_skills:
            stale.append(f"- {f.name} — skills the header asks for: "
                         + "; ".join(bad_skills)
                         + ". A missing skill does not load; a stale one is read with confidence")
        behind = stale_reference(f, name, fm)
        if behind:
            stale.append(f"- {f.name} — `next` points at {', '.join(behind)}. "
                         f"Work has happened since that file was last read — check whether "
                         f"part of what it asks for is already done (possibly in another folder)")
        alive = retired_but_present(f)
        if alive:
            stale.append(f"- {f.name} — a constraint marked as **retired** whose text "
                         f"is still there: {', '.join(alive)}")
        dl = deadline(fm)
        rec = {"name": f.name, "fm": fm, "dl": dl}
        if not is_us(fm) or sast == "waiting":
            # someone/something else is on the hook — a person OR a condition
            # (a disk to arrive). Never in "we can progress now", even with a deadline.
            external.append(rec)
        elif sast == "ongoing" or str(fm.get("timing", "")).lower() == "recurring":
            recurring.append(rec)
        elif dl is not None and (dl - today).days <= SOON_DAYS:
            overdue.append(rec)
        else:
            on_us.append(rec)

    for bucket in (overdue, on_us, recurring, external):
        bucket.sort(key=lambda r: (prio(r["fm"]), r["dl"] or date.max))

    blocks = []
    if overdue:
        blocks.append("⏰ DEADLINE due / passed:\n" + "\n".join(
            line_for(r["name"], r["fm"], f"  (deadline {r['dl']})") for r in overdue))
    if on_us:
        blocks.append("⏳ Waiting on YOU / can continue now:\n" + "\n".join(
            line_for(r["name"], r["fm"]) for r in on_us))
    if recurring:
        blocks.append("🔁 Ongoing:\n" + "\n".join(
            line_for(r["name"], r["fm"]) for r in recurring))
    if external:
        def ext_tail(r):
            bits = [] if is_us(r["fm"]) else [f"waiting on: {r['fm'].get('turn')}"]
            if r["dl"]:
                bits.append(f"deadline {r['dl']}")
            return f"  ({', '.join(bits)})" if bits else ""
        blocks.append("⛔ Waiting on someone OUTSIDE / blocked (for information):\n" + "\n".join(
            line_for(r["name"], r["fm"], ext_tail(r)) for r in external))
    if plain:
        plain.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        shown = plain[:MAX_PLAIN]
        rows = []
        for f in shown:
            lb = f / name
            if not lb.is_file():
                rows.append(f"- {f.name} — NO {name} (nothing was ever recorded here)")
                continue
            when = datetime.fromtimestamp(lb.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            title = first_entry_title(read_head(lb))
            rows.append(f"- {f.name} — last entry {when}" + (f": {title}" if title else ""))
        more = len(plain) - len(shown)
        block = "📋 No header (most recently touched):\n" + "\n".join(rows)
        if more > 0:
            block += f"\n- ...and {more} more"
        blocks.append(block)

    unlogged = unlogged_work(root, name)
    if (not blocks and not frozen and not finished and not stale and not unlogged and not UNREAD
            and not UNREADABLE
            and not LOST):
        return _notices_only(notices, start_line())

    if unfinished:
        # Its own block, above the shelf-life notes: an unclosed plan is not a
        # note about ageing, it is work that was never finished.
        blocks.append(
            "⛔ UNCLOSED PLANS — the task counts as not done:\n"
            + "\n".join(sorted(unfinished))
            + "\n(Close it with `state: done` OR `abandoned`, AND `result:` in PLAN.md — "
              "what came of it. An abandoned plan is closed the same way.)")
    if stale:
        blocks.append(
            "⏳ Past its shelf life — read this before relying on it:\n"
            + "\n".join(sorted(stale))
            + "\n(A claim with status I or A is not a fact — it is a debt. Either it gets checked, "
              "or it is dropped.)")
    if unlogged:
        # Stop asks only about this session's work (v3.10.1); the older debt is shown here.
        blocks.append(
            "📝 Work newer than its logbook, from before this session:\n"
            + "\n".join(f"- {u}" for u in unlogged)
            + "\n(Write the entry it is missing. A .batonignore line is for a file that changes on "
              "its own, and is the human's to add.)")
    if UNREAD:
        blocks.append("✂️ " + UNREAD[0])
    if UNREADABLE:
        blocks.append("🔒 " + unreadable_note(UNREADABLE))
    if LOST:
        blocks.append("🕳️ " + LOST[0] + " (Said once; tell the human.)")
    if frozen:
        blocks.append(f"❄️ Frozen (not offered): {', '.join(sorted(frozen))}")
    if finished:
        blocks.append(f"✅ Finished (not touched): {', '.join(sorted(finished))}")

    summary = (
        f"Baton — the tasks in {root}, ordered by whose move it is and by priority:\n\n"
        + "\n\n".join(blocks + notices)
    )
    context = (
        (CLEARED + "\n\n" if cleared else "")
        + SHOW_BOARD
        + "\n\n" + summary
        + f"\n\nBefore working on one, read its {name} (the record of earlier sessions; "
        f"the front-matter header on top carries the current state). After working, add a new entry "
        f"at the top and update the header if the state has changed."
    )

    # No systemMessage: that one reaches the human as it is, in English. The agent knows the
    # human's language and the hook does not, so the agent shows the board -- translated.
    return _emit(context, start_line(len(overdue) + len(on_us), len(recurring), len(external),
                                     plain=len(plain)))


def _start() -> None:
    """Mark that this run began: `baton.beat.<hook>.started.<pid>`, holding the time. Removed when
    the run finishes or crashes (in `_beat`). A hook killed at its time limit -- SIGTERM, then
    SIGKILL -- writes neither file of `_beat`, and the doctor showed the last finish as ✅
    (ZA-OPRAVYANE row 41, 22.10); a mark left behind is that run. One per pid: two sessions can
    run the same hook at once, and one still running is not one killed. Never raises."""
    try:
        from datetime import datetime
        data = os.environ.get("CLAUDE_PLUGIN_DATA")
        folder = Path(data) if data else Path(__file__).resolve().parent
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"baton.beat.{Path(__file__).stem}.started.{os.getpid()}").write_text(
            datetime.now().isoformat(), "utf-8")
    except Exception:
        pass


def _clear_starts(folder: Path) -> None:
    """This run's start mark, and those of runs that are gone: this finish is newer than them."""
    import time
    for mark in folder.glob(f"baton.beat.{Path(__file__).stem}.started.*"):
        try:
            pid = mark.name.rsplit(".", 1)[1]
            gone = pid == str(os.getpid()) or time.time() - mark.stat().st_mtime > 120
            if not gone and os.name != "nt":      # on Windows os.kill(pid, 0) is not a probe
                try:
                    os.kill(int(pid), 0)
                except ProcessLookupError:
                    gone = True
            if gone:
                mark.unlink()
        except (OSError, ValueError):
            continue


def _beat(crash: BaseException | None = None) -> None:
    """When this hook last FINISHED, for /baton-doctor: a plugin can be installed and enabled and
    still never run (no Python, no Git Bash on Windows), and nothing on the screen says so.
    One small file per hook, next to the other state. A run that raised leaves
    `baton.beat.<hook>.crashed` instead: the time and the exception's class -- no message, no
    path. Until v3.20.0 the beat was written before main() ran, so a crash still showed ✅
    (ZA-OPRAVYANE row 36, Pawan Singh Rathore, 22.10). Never raises."""
    try:
        data = os.environ.get("CLAUDE_PLUGIN_DATA")
        folder = Path(data) if data else Path(__file__).resolve().parent
        folder.mkdir(parents=True, exist_ok=True)
        beat, now = folder / f"baton.beat.{Path(__file__).stem}", datetime.now()
        # To the microsecond: a crash and a finish in the same second still have an order.
        if crash is None:
            beat.write_text(now.isoformat(), "utf-8")
        else:
            beat.with_name(beat.name + ".crashed").write_text(
                f"{now.isoformat()} {type(crash).__name__}", "utf-8")
        _clear_starts(folder)
        _prune_turns(folder)
    except Exception:
        pass


def _prune_turns(folder: Path, days: int = 14) -> None:
    """The per-session turn records (`baton.turns/<session>`, row 49) of sessions quiet for two
    weeks: the doctor reads the last week. Once a session, here. Never raises."""
    import time
    try:
        for f in (folder / "baton.turns").iterdir():
            try:
                if time.time() - f.stat().st_mtime > days * 86400:
                    f.unlink()
            except OSError:
                continue
    except OSError:
        pass


if __name__ == "__main__":
    _start()
    try:
        code = main()
    except Exception as exc:
        # A hook must never break the session it is trying to help -- but it must not
        # disappear either. Exiting 0 in silence is how a NameError in main() once let
        # the whole report vanish while every unit test still passed: the functions were
        # tested, the wiring was not. The traceback goes to stderr, where it costs the
        # session nothing and is there when someone wonders why Baton said nothing.
        _beat(exc)              # and for /baton-doctor and the next SessionStart (row 36)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(0)
    _beat()
    sys.exit(code)
