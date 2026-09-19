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
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

MAX_PLAIN = 6                 # cap only on the fall-back (header-less) list
SOON_DAYS = 3                 # a deadline within this many days counts as "near"
US = {"nie", "us", "нас", "ние", "стенли", "me", "self", ""}
PRIORITY_RANK = {"visok": 0, "висок": 0, "sreden": 1, "среден": 1, "nisak": 2, "нисък": 2}

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


def config() -> tuple[Path, str]:
    cfg = {}
    try:
        cfg = json.loads((Path(__file__).with_name("baton.local.json")).read_text("utf-8-sig"))
    except Exception:
        cfg = {}
    home = os.environ.get("BATON_HOME") or cfg.get("home") or str(Path.home() / "tasks")
    logbook = os.environ.get("BATON_LOGBOOK") or cfg.get("logbook") or "LOGBOOK.md"
    return Path(home).expanduser(), logbook


def read_head(logbook: Path) -> str:
    try:
        return logbook.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def parse_frontmatter(text: str) -> dict:
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
    for raw in (fm.get("vremevi_kriterii", ""), fm.get("srok", "")):
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
    since = _as_date(fm.get("vyarno_kum") or fm.get("вярно_към"))
    if since is None:
        return None
    raw = str(fm.get("pregled_sled") or fm.get("преглед_след") or "").strip().lower()
    match = re.fullmatch(r"(\d+)\s*([dдmм])?", raw)
    if not match:
        return None
    count = int(match.group(1))
    days = count * 30 if match.group(2) in ("m", "м") else count
    due = since + timedelta(days=days)
    return (due, (today - due).days) if due <= today else None


def unverified_debt(folder: Path, today: date) -> tuple[int, int] | None:
    """Claims in this task's facts file that nobody has checked, and how old.

    Returns (count, age of the oldest block in days). A fact file keeps its
    status column -- verified against a source, checked locally, an agent's word,
    inferred -- and the last two are debts. They are not wrong; they are
    unpaid. One of them ("auditors probably cannot take a commission") was
    carried for a day and nearly cancelled a plan before anyone read the code it
    claimed to summarise.
    """
    facts = folder / "FAKTI.md"
    if not facts.is_file():
        facts = folder / "FACTS.md"
        if not facts.is_file():
            return None
    try:
        text = facts.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None

    blocks = [(m.start(), _as_date(m.group(1))) for m in CLAIM_BLOCK.finditer(text)]
    if not blocks:
        return None
    count, oldest = 0, None
    for row in UNVERIFIED_ROW.finditer(text):
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
    word inside it. Comparing the raw text made `**само ние** разделяме` and
    `само ние разделяме` different strings, which is the wrong kind of exact.
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
            still.append(f"{ident}: посоченият файл {where} го няма")
            continue
        try:
            body = target.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            still.append(f"{ident}: {where} не се чете")
            continue
        if phrase in _plain(body):
            still.append(f"{ident} в {where}")
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
    text = str(fm.get("sledvashto", "")).strip()
    return len(text) if len(text) > POINTER_MAX else None


def is_us(fm: dict) -> bool:
    return str(fm.get("na_hod", "")).strip().lower() in US


def prio(fm: dict) -> int:
    return PRIORITY_RANK.get(str(fm.get("prioritet", "")).strip().lower(), 3)


def line_for(name: str, fm: dict, tail: str = "") -> str:
    p = str(fm.get("prioritet", "")).strip()
    badge = f" [{p}]" if p else ""
    nxt = fm.get("sledvashto") or fm.get("kriterii_zavarshvane") or ""
    body = f" — {nxt}" if nxt else ""
    return f"- {name}{badge}{body}{tail}"


def main() -> int:
    root, name = config()
    if not root.is_dir():
        return 0
    folders = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    if not folders:
        return 0

    overdue, recurring, on_us, external, plain, finished, frozen = [], [], [], [], [], [], []
    stale: list[str] = []
    today = date.today()

    for f in folders:
        lb = f / name
        text = read_head(lb) if lb.is_file() else ""
        fm = parse_frontmatter(text) if text else {}
        if not fm:  # no header → original behaviour, sorted by mtime later
            plain.append(f)
            continue
        sast = str(fm.get("sastoyanie", "")).strip().lower()
        if sast in ("priklyuchila", "priklyuchena", "приключила", "приключена", "done"):
            finished.append(f.name)
            continue
        if sast in ("zamrazena", "замразена", "frozen", "paused"):
            # parked on purpose: shown for the record, never offered as work
            frozen.append(f.name)
            continue

        # Shelf life. A frozen or finished task is skipped above on purpose: a
        # snapshot nobody is working from cannot mislead anybody.
        due = review_due(fm, today)
        if due:
            _, late = due
            stale.append(f"- {f.name} — прегледът на състоянието беше за преди {late} "
                         f"{'ден' if late == 1 else 'дни'} (`vyarno_kum` + `pregled_sled`)")
        debt = unverified_debt(f, today)
        if debt:
            count, age = debt
            stale.append(f"- {f.name} — {count} непроверени твърдения (статус И/А), "
                         f"най-старото на {age} дни")
        drift = pointer_drift(fm)
        if drift:
            stale.append(f"- {f.name} — `sledvashto` е {drift} знака: показалец, който вече "
                         f"носи състояние. Състоянието живее в дневника, тук стои следващият ход")
        alive = retired_but_present(f)
        if alive:
            stale.append(f"- {f.name} — ограничение, отбелязано като **паднало**, но текстът му "
                         f"е още там: {', '.join(alive)}")
        dl = deadline(fm)
        rec = {"name": f.name, "fm": fm, "dl": dl}
        if not is_us(fm) or sast in ("chakashta", "чакаща", "waiting"):
            # someone/something else is on the hook — a person OR a condition
            # (a disk to arrive). Never in "we can progress now", even with a deadline.
            external.append(rec)
        elif sast in ("postoyanna", "постоянна") or str(fm.get("vremevi_kriterii", "")).lower() in ("postoyanno", "постоянно"):
            recurring.append(rec)
        elif dl is not None and (dl - today).days <= SOON_DAYS:
            overdue.append(rec)
        else:
            on_us.append(rec)

    for bucket in (overdue, on_us, recurring, external):
        bucket.sort(key=lambda r: (prio(r["fm"]), r["dl"] or date.max))

    blocks = []
    if overdue:
        blocks.append("⏰ СРОК изтича / изтекъл:\n" + "\n".join(
            line_for(r["name"], r["fm"], f"  (срок {r['dl']})") for r in overdue))
    if on_us:
        blocks.append("⏳ Чакат ТЕБ / може да продължим сега:\n" + "\n".join(
            line_for(r["name"], r["fm"]) for r in on_us))
    if recurring:
        blocks.append("🔁 Постоянни:\n" + "\n".join(
            line_for(r["name"], r["fm"]) for r in recurring))
    if external:
        def ext_tail(r):
            bits = [] if is_us(r["fm"]) else [f"чака: {r['fm'].get('na_hod')}"]
            if r["dl"]:
                bits.append(f"срок {r['dl']}")
            return f"  ({', '.join(bits)})" if bits else ""
        blocks.append("⛔ Чакат ВЪНШЕН / блокирани (за сведение):\n" + "\n".join(
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
        block = "📋 Без хедър (последно пипани):\n" + "\n".join(rows)
        if more > 0:
            block += f"\n- ...and {more} more"
        blocks.append(block)

    if not blocks and not frozen and not finished and not stale:
        return 0

    if stale:
        blocks.append(
            "⏳ Изтекъл срок на годност — прочети това, преди да стъпиш на него:\n"
            + "\n".join(sorted(stale))
            + "\n(Твърдение със статус И или А не е факт — то е дълг. Или се проверява, "
              "или пада.)")
    if frozen:
        blocks.append(f"❄️ Замразени (не се предлагат): {', '.join(sorted(frozen))}")
    if finished:
        blocks.append(f"✅ Приключени (не се пипат): {', '.join(sorted(finished))}")

    summary = (
        f"Baton — задачите в {root}, подредени по кой е на ход и приоритет:\n\n"
        + "\n\n".join(blocks)
    )
    context = (
        summary
        + f"\n\nПреди работа по някоя — прочети нейния {name} (той е записът от предишни сесии; "
        f"front-matter хедърът горе носи текущото състояние). След работа — впиши нов запис най-отгоре "
        f"и обнови хедъра, ако състоянието се е сменило."
    )

    json.dump(
        {
            # additionalContext reaches only the agent; systemMessage is what the human sees
            "systemMessage": summary,
            "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context},
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # A hook must never break the session it is trying to help.
        sys.exit(0)
