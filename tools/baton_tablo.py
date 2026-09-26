#!/usr/bin/env python3
"""A board of the tasks, as one local HTML file.

    python3 tools/baton_tablo.py [--out tablo.html] [--open]

The session-start hook already says all of this, but it says it as a wall of text
at the top of a conversation, which is where it is least readable and most easily
scrolled past. The same state laid out is readable at a glance and on a phone
over the local network.

It is generated, never edited: the logbooks are the record, this is a view of
them. Nothing is uploaded and nothing leaves the machine -- which is the whole
reason it is a file and not a hosted page. The logbooks carry client matter, and
a board is not worth sending it anywhere.
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import os
import sys
import webbrowser
from datetime import date
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_session_start.py"


def _korpus():
    """One owner for where the tasks are -- see `baton_korpus.config`."""
    if "baton_korpus" in sys.modules:
        return sys.modules["baton_korpus"]
    spec = importlib.util.spec_from_file_location(
        "baton_korpus", Path(__file__).resolve().parent / "baton_korpus.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["baton_korpus"] = module
    spec.loader.exec_module(module)
    return module


def _hook():
    """The hook's own parsing, reused rather than reimplemented.

    Two readers of the same header that disagree is a defect waiting to happen,
    and the board is the one that would be believed because it is prettier.
    """
    spec = importlib.util.spec_from_file_location("baton_session_start", HOOK)
    module = importlib.util.module_from_spec(spec)
    sys.modules["baton_session_start"] = module
    spec.loader.exec_module(module)
    return module


STATE_LABEL = {
    "aktivna": "активна", "chakashta": "чака", "postoyanna": "постоянна",
    "zamrazena": "замразена", "priklyuchila": "приключила", "priklyuchena": "приключила",
    "active": "активна", "waiting": "чака", "frozen": "замразена", "paused": "замразена",
    "done": "приключила",
}
PRIORITY_LABEL = {"visok": "висок", "sreden": "среден", "nisak": "нисък"}

CSS = """
:root{--ink:#14171a;--dim:#5b6570;--line:#e3e6ea;--bg:#fbfcfd;--card:#fff;
      --hot:#b4232c;--warm:#8a6d1f;--cool:#2f6f4f}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:60rem;margin:0 auto;padding:2rem 1rem 4rem}
h1{font-size:1.5rem;margin:0 0 .25rem}
.sub{color:var(--dim);font-size:.85rem;margin-bottom:2rem}
h2{font-size:.95rem;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);
   margin:2rem 0 .75rem;font-weight:600}
.card{background:var(--card);border:1px solid var(--line);border-radius:.5rem;
      padding:.9rem 1rem;margin-bottom:.6rem}
.card.hot{border-left:3px solid var(--hot)}
.card.warm{border-left:3px solid var(--warm)}
.name{font-weight:600}
.badges{float:right;font-size:.75rem;color:var(--dim)}
.badge{display:inline-block;margin-left:.4rem;padding:.1rem .45rem;border-radius:.25rem;
       background:#f0f2f5}
.next{margin-top:.35rem;color:var(--dim);font-size:.9rem}
.warn{margin-top:.5rem;padding:.5rem .7rem;background:#fdf6ec;border-radius:.35rem;
      font-size:.85rem;color:var(--warm)}
.quiet{color:var(--dim);font-size:.85rem}
footer{margin-top:3rem;color:var(--dim);font-size:.8rem;border-top:1px solid var(--line);
       padding-top:1rem}
@media(prefers-color-scheme:dark){
 :root{--ink:#e8eaed;--dim:#9aa4b0;--line:#2a2f36;--bg:#14171a;--card:#1b1f24;
       --hot:#ef6b72;--warm:#d9b45a;--cool:#6fc39a}
 .badge{background:#252a31}.warn{background:#2a2317}}
"""


def collect(root: Path, logbook: str) -> tuple[list[dict], date]:
    hook = _hook()
    today = date.today()
    rows: list[dict] = []
    if not root.is_dir():
        return rows, today
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        book = folder / logbook
        text = hook.read_head(book) if book.is_file() else ""
        fm = hook.parse_frontmatter(text) if text else {}
        warnings: list[str] = []
        due = hook.review_due(fm, today) if fm else None
        if due:
            _, late = due
            warnings.append(f"Прегледът на състоянието закъснява с {late} "
                            f"{'ден' if late == 1 else 'дни'}.")
        debt = hook.unverified_debt(folder, today)
        if debt:
            count, age = debt
            warnings.append(f"{count} непроверени твърдения (статус И/А); "
                            f"най-старото на {age} дни.")
        for item in hook.retired_but_present(folder):
            warnings.append(f"Отбелязано като паднало, но още стои: {item}")
        state = str(fm.get("sastoyanie", "")).strip().lower()
        rows.append({
            "name": folder.name,
            "state": STATE_LABEL.get(state, state or "—"),
            "raw_state": state,
            "on_us": hook.is_us(fm) if fm else False,
            "who": str(fm.get("na_hod", "")).strip(),
            "priority": PRIORITY_LABEL.get(
                str(fm.get("prioritet", "")).strip().lower(),
                str(fm.get("prioritet", "")).strip()),
            "rank": hook.prio(fm) if fm else 3,
            "next": str(fm.get("sledvashto") or fm.get("kriterii_zavarshvane") or "").strip(),
            "deadline": hook.deadline(fm) if fm else None,
            "warnings": warnings,
            "headerless": not fm,
        })
    return rows, today


def card(row: dict, today: date) -> str:
    klass = "card"
    if row["warnings"]:
        klass += " warm"
    if row["deadline"] and row["deadline"] <= today:
        klass += " hot"
    badges = []
    if row["priority"]:
        badges.append(row["priority"])
    if row["state"] and row["state"] != "—":
        badges.append(row["state"])
    if row["deadline"]:
        left = (row["deadline"] - today).days
        badges.append(f"срок {row['deadline']}" + (f" ({left} дни)" if left >= 0 else " ⚠ мина"))
    if not row["on_us"] and row["who"]:
        badges.append(f"чака: {html.escape(row['who'])}")
    out = [f'<div class="{klass}">',
           '<span class="badges">'
           + "".join(f'<span class="badge">{html.escape(b)}</span>' for b in badges)
           + "</span>",
           f'<div class="name">{html.escape(row["name"])}</div>']
    if row["next"]:
        out.append(f'<div class="next">{html.escape(row["next"])}</div>')
    if row["headerless"]:
        out.append('<div class="next quiet">няма хедър — не се подрежда по състояние</div>')
    for w in row["warnings"]:
        out.append(f'<div class="warn">⏳ {html.escape(w)}</div>')
    out.append("</div>")
    return "\n".join(out)


def render(rows: list[dict], root: Path, today: date) -> str:
    live = [r for r in rows if r["raw_state"] not in
            ("zamrazena", "замразена", "frozen", "paused",
             "priklyuchila", "priklyuchena", "приключила", "приключена", "done")]
    frozen = [r for r in rows if r["raw_state"] in ("zamrazena", "замразена", "frozen", "paused")]
    done = [r for r in rows if r["raw_state"] in
            ("priklyuchila", "priklyuchena", "приключила", "приключена", "done")]

    def order(r):
        return (0 if r["deadline"] and r["deadline"] <= today else 1, r["rank"], r["name"])

    ours = sorted([r for r in live if r["on_us"]], key=order)
    theirs = sorted([r for r in live if not r["on_us"]], key=order)
    flagged = sum(len(r["warnings"]) for r in rows)

    parts = [f"<h1>Батон</h1>",
             f'<div class="sub">{html.escape(str(root))} · {today} · '
             f'{len(live)} живи, {len(frozen)} замразени, {len(done)} приключени'
             + (f" · <strong>{flagged} бележки за срок на годност</strong>" if flagged else "")
             + "</div>"]
    if ours:
        parts.append("<h2>На наш ход</h2>" + "\n".join(card(r, today) for r in ours))
    if theirs:
        parts.append("<h2>Чакат външен</h2>" + "\n".join(card(r, today) for r in theirs))
    if frozen:
        parts.append('<h2>Замразени</h2><div class="card quiet">'
                     + ", ".join(html.escape(r["name"]) for r in frozen) + "</div>")
    if done:
        parts.append('<h2>Приключени</h2><div class="card quiet">'
                     + ", ".join(html.escape(r["name"]) for r in done) + "</div>")
    parts.append("<footer>Генерирано от дневниците. Те са записът; това е изглед към тях. "
                 "Нищо не напуска машината.</footer>")
    return ("<!doctype html><html lang=\"bg\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Батон</title><style>" + CSS + "</style></head><body>"
            "<div class=\"wrap\">" + "\n".join(parts) + "</div></body></html>")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A board of the Baton tasks, as one local HTML file.")
    ap.add_argument("--out", default="tablo.html", help="where to write it")
    ap.add_argument("--open", action="store_true", help="open it in the browser afterwards")
    a = ap.parse_args(argv)

    hook = _hook()
    # ⚠️ NOT hook.config(): the hook reads the file next to its own __file__, and this
    # loads the hook out of the repository, where `baton.local.json` deliberately is not
    # -- it holds client folder names and stays outside git. The board therefore printed
    # "no tasks under ~/tasks" on every machine configured anywhere else.
    root, logbook = _korpus().config()["home"], _korpus().config()["logbook"]
    rows, today = collect(root, logbook)
    if not rows:
        print(f"baton: no tasks under {root}", file=sys.stderr)
        return 1
    out = Path(a.out).expanduser()
    out.write_text(render(rows, root, today), encoding="utf-8")
    print(f"wrote {out} ({len(rows)} tasks)")
    if a.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
