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

DATED_HEADING = re.compile(
    r"^\d{4}-\d\d-\d\d(?:[ T]\d\d:\d\d)?\s*[\u2014\u2013-]\s*(?P<title>.+)$"
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


def _local_file(name: str) -> Path:
    """Where a settings or state file lives. Installed as a plugin, the hooks run from a
    folder replaced on every update, so these go to ${CLAUDE_PLUGIN_DATA}, which survives
    updates. Installed by install.sh, next to the hooks, as always."""
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    return Path(data) / name if data else Path(__file__).with_name(name)


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


BATON_VERSION = "3.7.1"   # bumped with every release; a test holds it to the README's top version
RELEASES = "https://api.github.com/repos/StanimirTenev/baton/releases/latest"


def _local() -> dict:
    try:
        return json.loads((_local_file("baton.local.json")).read_text("utf-8-sig"))
    except Exception:
        return {}


def _state_file() -> Path:
    return Path(os.environ.get("BATON_SESSION_STATE")
                or _local_file("baton.state.json"))


def _version(tag: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", tag)[:3])


def update_notice(today: date) -> str | None:
    """Once a week, IF the human switched it on: is there a newer Baton? Never installs.

    Off until chosen, because the README promised the hooks never touch the network, and a
    promise changed by default is a promise broken. While nobody has chosen, the agent is
    asked -- once a day -- to put the question to the human.
    """
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
    try:
        cfg = json.loads((_local_file("baton.local.json")).read_text("utf-8-sig"))
    except Exception:
        return None
    raw = os.environ.get("BATON_SOURCE") or cfg.get("source")
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
    src = source_dir()
    if src is None or not src.is_dir():
        return []
    out = []
    for name in ("baton_session_start.py", "baton_stop.py", "baton_prompt.py"):
        here, there = Path(__file__).with_name(name), src / name
        try:
            if there.is_file() and not here.is_file():
                # In the source and not running: the silent case, and the worst one.
                out.append(f"{name} (not installed)")
            elif here.is_file() and there.is_file() and here.read_bytes() != there.read_bytes():
                out.append(name)
        except OSError:
            continue
    return out


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
    raw = os.environ.get("BATON_SKILLS") or cfg.get("skills") or "~/.claude/skills"
    return Path(raw).expanduser()


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
    for name in names:
        skill = root / name / "SKILL.md"
        if not skill.is_file():
            out.append(f"{name} — MISSING in {root}")
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
    badge = f" [{p}]" if p else ""
    nxt = fm.get("next") or fm.get("done_when") or ""
    body = f" — {nxt}" if nxt else ""
    # Named, not loaded. The agent reads this and invokes what it needs; the hook
    # never reaches into the session to load anything on its behalf.
    skill_names = skills_for(fm)
    skills = f"  ⟨skills: {', '.join(skill_names)}⟩" if skill_names else ""
    return f"- {name}{badge}{body}{tail}{skills}"


def inventory_notice(today: date) -> str | None:
    """No task folders yet, but months of Claude Code behind them: offer /baton-inventory.

    Found 2026-09-29: the installer printed one line about it, and a line printed once at
    install is a line nobody acts on. Once a day while the root stays empty.
    """
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    try:
        talks = list((claude / "projects").glob("*/*.jsonl"))
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
            f"conversations (the oldest from {oldest.isoformat()}). Offer the human /baton-inventory: "
            "it maps that earlier work into task folders, and creates nothing until they confirm "
            "each one. Ask once; if they decline, leave it.")


SHOW_BOARD = (
    "The human has not seen this board. Open your first reply with the WHOLE board, translated "
    "into the human's language: every group and every line, nothing shortened or left out -- "
    "no summary, no merged lines, no \"...and the rest\", and the notes in parentheses too. "
    "Task names, file names, commands, fields in backticks and identifiers stay as they are."
)


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
        if "Installed by Baton" in (Path.home() / ".claude" / "CLAUDE.md").read_text("utf-8"):
            return None
    except OSError:
        pass
    try:
        text = (Path(root) / "templates" / "CLAUDE.md").read_text("utf-8")
    except OSError:
        return None
    tasks, logbook = config()
    return (f"Baton's working rules. Baton is installed as a plugin, so they arrive here rather "
            f"than from CLAUDE.md. On this machine the task root is {tasks} and the logbook "
            f"file in each task folder is {logbook}.\n\n{text}")


def _emit(context: str | None) -> int:
    """The one way out: whatever the hook has to say, plus the rules in plugin mode."""
    text = "\n\n".join(t for t in (context, plugin_rules()) if t)
    if text:
        json.dump({"hookSpecificOutput": {
            "hookEventName": "SessionStart", "additionalContext": text}}, sys.stdout)
    return 0


def _notices_only(notices: list[str]) -> int:
    """A board with no tasks still carries what the agent must say to the human."""
    return _emit("\n\n".join(notices) if notices else None)


def main() -> int:
    root, name = config()
    notices = [n for n in (update_notice(date.today()),) if n]
    folders = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")] \
        if root.is_dir() else []
    if not folders:
        return _notices_only(notices + [n for n in (inventory_notice(date.today()),) if n])

    overdue, recurring, on_us, external, plain, finished, frozen = [], [], [], [], [], [], []
    stale: list[str] = []
    unfinished: list[str] = []
    today = date.today()

    drifted = install_drift()
    if drifted:
        stale.append("- 🔴 THE RUNNING HOOKS ARE NOT FROM THE SOURCE: " + ", ".join(drifted)
                     + " — a fix that is not installed does not work, however tagged it is")

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

    if not blocks and not frozen and not finished and not stale:
        return _notices_only(notices)

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
    if frozen:
        blocks.append(f"❄️ Frozen (not offered): {', '.join(sorted(frozen))}")
    if finished:
        blocks.append(f"✅ Finished (not touched): {', '.join(sorted(finished))}")

    summary = (
        f"Baton — the tasks in {root}, ordered by whose move it is and by priority:\n\n"
        + "\n\n".join(blocks + notices)
    )
    context = (
        SHOW_BOARD
        + "\n\n" + summary
        + f"\n\nBefore working on one, read its {name} (the record of earlier sessions; "
        f"the front-matter header on top carries the current state). After working, add a new entry "
        f"at the top and update the header if the state has changed."
    )

    # No systemMessage: that one reaches the human as it is, in English. The agent knows the
    # human's language and the hook does not, so the agent shows the board -- translated.
    return _emit(context)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # A hook must never break the session it is trying to help -- but it must not
        # disappear either. Exiting 0 in silence is how a NameError in main() once let
        # the whole report vanish while every unit test still passed: the functions were
        # tested, the wiring was not. The traceback goes to stderr, where it costs the
        # session nothing and is there when someone wonders why Baton said nothing.
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(0)
