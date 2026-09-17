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
from datetime import date, datetime
from pathlib import Path

MAX_PLAIN = 6                 # cap only on the fall-back (header-less) list
SOON_DAYS = 3                 # a deadline within this many days counts as "near"
US = {"nie", "us", "нас", "ние", "стенли", "me", "self", ""}
PRIORITY_RANK = {"visok": 0, "висок": 0, "sreden": 1, "среден": 1, "nisak": 2, "нисък": 2}

DATED_HEADING = re.compile(
    r"^\d{4}-\d\d-\d\d(?:[ T]\d\d:\d\d)?\s*[\u2014\u2013-]\s*(?P<title>.+)$"
)


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

    if not blocks and not frozen and not finished:
        return 0

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
