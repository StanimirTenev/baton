#!/usr/bin/env python3
"""Review an index against the files it points at, with Jev (TypeSafe System One).

    python3 tools/baton_pregled.py --dali            # has a pointer gone stale?
    python3 tools/baton_pregled.py --koe <file>      # which claim is unsupported?

Optional, and off unless you configure it. **The hooks never call this and never
touch the network.** Logbooks carry client matter; that is not a thing to send
anywhere on a schedule. This is a separate move a person makes on purpose, and it
needs an OpenRouter key -- without one, nothing here runs and the rest of Baton is
unaffected.

The problem it addresses is the one Baton cannot check with string matching: an
index line that asserts something the file it points at has since contradicted.
There is no textual signature for a contradiction. Either someone re-reads both,
or it rots. Measured here on 19 such pointers: six were wrong, two in ways no
pattern could have found.

⚠️ **The individual answer is not a verdict.** In TypeSafe's own words: calibration
is measured across groups of predictions and does not guarantee that an individual
answer is correct. This ranks and says "look here". A person opens the file and
decides. Nothing is rewritten because a number was high.

## The two questions want OPPOSITE amounts of evidence

Measured 2026-09-23, not assumed, and the easiest thing here to get backwards:

| question | evidence | what the other way does |
|---|---|---|
| "has the pointer gone stale?" | an EXTRACT (~2600 chars) | the whole file drops real cases 0.73 → 0.43 |
| "which claim is unsupported?" | the WHOLE file | an extract gives false ones: 0.02 against 0.97 |

One reason both ways: a summary judgement is DILUTED by a long text, while a single
claim has its evidence SOMEWHERE in it -- and a cut above that evidence fails the
claim innocently.

## The threshold

`PRAG = 0.46`, measured by hand: 14 of 19 pointers checked personally, everything
≥0.47 turned out real and everything ≤0.45 false.

⚠️ Measured on ONE corpus of 19 rows, in one person's writing, in Bulgarian. It is a
starting point, not a constant. Run it on your own index, check what it flags by
hand, and move the number to where it separates yours.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
MODEL = "~typesafe/jev-latest"

PRAG = 0.46          # measured, not assumed -- see the module docstring
OTRYAZAK = 2600      # for --dali: the extract that question wants
TSYAL = 28000        # for --koe: a CEILING, not a promise; it announces itself

LINK = re.compile(r"\[([^\]]+)\]\(([^)#]+\.md)\)")


def config() -> dict:
    """Settings from `baton.local.json` next to the hooks, overridable by env.

    Same file the hooks read, so there is one place to configure Baton rather than
    two that can disagree.
    """
    cfg = {}
    for candidate in (Path(__file__).resolve().parent.parent / "hooks",
                      Path.home() / ".claude/baton/hooks"):
        try:
            cfg = json.loads((candidate / "baton.local.json").read_text("utf-8-sig"))
            break
        except Exception:
            continue

    poveritelni = os.environ.get("BATON_PREGLED_POVERITELNI")
    out = {
        "indeks": os.environ.get("BATON_PREGLED_INDEKS") or cfg.get("pregled_indeks"),
        "podbor": os.environ.get("BATON_PREGLED_PODBOR") or cfg.get("pregled_podbor"),
        "home": os.environ.get("BATON_HOME") or cfg.get("home") or str(Path.home() / "tasks"),
        "poveritelni": ([w.strip() for w in poveritelni.split(",") if w.strip()]
                        if poveritelni is not None else cfg.get("pregled_poveritelni")),
    }
    if not out["indeks"]:
        sys.exit("НЯМА индекс. Сложи `pregled_indeks` в baton.local.json — файлът с\n"
                 "показалците, които да се сверят (напр. индексът на паметта ти).")
    if out["poveritelni"] is None:
        # Fail closed on a decision nobody has made. An absent list is not an empty
        # one: it means the question was never asked, and the answer matters more
        # here than anywhere else in Baton, because this is the one thing that sends.
        sys.exit(
            "НЯМА списък с поверителни думи. Това НЕ е по подразбиране празно —\n"
            "решението кое не напуска машината се взема веднъж, съзнателно.\n\n"
            "В baton.local.json:\n"
            '  "pregled_poveritelni": ["име-на-клиент", "Име На Клиент", "неиздаден-продукт"]\n\n'
            "Ако наистина нищо не се задържа, напиши изрично празен списък: []\n"
            "⚠️ Пиши всяко име на ВСЯКА азбука, която ползваш — съвпадението е по низ.")
    return out


def klyuch() -> str:
    value = os.environ.get("OPENROUTER_API_KEY", "")
    if not value:
        path = Path.home() / ".config/typesafe/env"
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("OPENROUTER_API_KEY="):
                    value = line.split("=", 1)[1].strip()
    if not value:
        sys.exit("НЯМА ключ. Този преглед иска ключ от OpenRouter:\n"
                 "  export OPENROUTER_API_KEY=...\n"
                 "или ред `OPENROUTER_API_KEY=...` в ~/.config/typesafe/env (права 600).\n\n"
                 "Без ключ прегледът не работи. Останалата част от Батон не го иска.")
    return value


def poveritelno(text: str, etiket: str, dumi: list[str]) -> str:
    """Which configured word held this back, or "" if it is clear.

    Checks the path AND the content: material can sit in an innocent folder and
    still recount a client's business. Deliberately coarse -- a false hold costs
    one question, a false send does not come back.

    **The whole text, every time.** The first version scanned the first 4000
    characters of what it was about to send, while `--koe` sends up to 28000: the
    guard inspected one seventh of the payload and passed the rest. Four files went
    out carrying a client's name and an unreleased product's name, each of them
    past character 4000. A barrier that samples is not a barrier, and the sampling
    was invisible precisely because the part it read was clean.

    Callers pass the WHOLE source file, not the truncated extract: the question is
    whether this document is about confidential matter, not whether the bytes that
    happened to fit contained the word.
    """
    lower = f"{etiket} {text}".lower()
    for duma in dumi:
        if duma.lower() in lower:
            return duma
    return ""


def pitay(api_key: str, state: str, questions: dict, etiket: str, dumi: list[str]) -> dict:
    """One call. A missing or malformed answer is an ERROR, never "clean".

    Issues closed in `jkudish/jev-mcp` for exactly this: a null `answers` envelope,
    a missing envelope, a malformed answer. Read as "no problem found", such a
    reply makes the review lie precisely when it is least able to be caught.
    """
    # Last barrier inside the only function that touches the network: callers check
    # too, but a future caller may forget, and this is the one that sends.
    zadarzhano = poveritelno(state, etiket, dumi)
    if zadarzhano:
        sys.exit(f"⛔ отказано: „{zadarzhano}“ се среща в {etiket}. "
                 f"Не напуска машината.")
    body = {"model": MODEL, "state": state, "questions": questions}
    request = urllib.request.Request(
        ENDPOINT, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            out = json.loads(response.read())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as err:
        detail = err.read().decode()[:200] if hasattr(err, "read") else str(err)
        sys.exit(f"⛔ извикването падна ({etiket}): {detail}")

    answers = out.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        sys.exit(f"⛔ непълен отговор за {etiket}: върнати {sorted(answers or [])}, "
                 f"поискани {sorted(questions)}. Не се чете като „чисто“.")
    for name, value in answers.items():
        if not isinstance(value.get("noul"), (int, float)):
            sys.exit(f"⛔ повреден отговор за {etiket}/{name}: {value}")
    return out


def zapishi(home: str, rezhim: str, koe: str, broy: int, tsena: float) -> None:
    """What was sent, when, and what it cost. Without this line the review is an
    invisible expense and nobody can say what left the machine."""
    path = Path(home).expanduser() / ".pregled-dnevnik.tsv"
    path.parent.mkdir(parents=True, exist_ok=True)
    nov = not path.exists()
    with path.open("a", encoding="utf-8") as handle:
        if nov:
            handle.write("кога\tрежим\tкакво\tвъпроси\tцена_usd\n")
        handle.write(f"{datetime.now():%Y-%m-%d %H:%M}\t{rezhim}\t{koe}\t{broy}\t{tsena:.6f}\n")


def pokazalci(indeks: Path, podbor: Path | None) -> list[tuple[str, str]]:
    """(pointer line, target) for every link in the index, optionally narrowed.

    `podbor` is any file that names some of the targets -- a shortlist of the rows
    that actually carry state, so a long index does not have to be paid for whole.
    """
    wanted = None
    if podbor is not None and podbor.is_file():
        wanted = {m.group(2) for m in LINK.finditer(podbor.read_text(encoding="utf-8"))}
    out = []
    for line in indeks.read_text(encoding="utf-8").splitlines():
        match = LINK.search(line)
        if not match:
            continue
        target = match.group(2)
        if wanted is not None and target not in wanted:
            continue
        out.append((line.strip().lstrip("- "), target))
    return out


def detail(root: Path, target: str, limit: int) -> tuple[str, str]:
    """The extract AND the whole text: the caller needs both.

    The whole text is what the confidentiality guard reads, and its length is what
    says whether the extract cut anything.

    For `--dali` the cut is the rule and stays quiet. For `--koe` it is a ceiling,
    and a silent ceiling is the very defect this tool exists for: a claim whose
    evidence sits below the cut fails innocently and looks like a finding.
    """
    path = root / target
    if not path.is_file():
        return "", ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.startswith("---"):
        parts = text.split("---", 2)
        text = parts[2] if len(parts) > 2 else text
    text = text.strip()
    return text[:limit], text


def dali(api_key: str, cfg: dict, izbrani: set[str]) -> None:
    indeks = Path(cfg["indeks"]).expanduser()
    podbor = Path(cfg["podbor"]).expanduser() if cfg.get("podbor") else None
    dumi, root = cfg["poveritelni"], indeks.parent
    results, spent, zadarzhani, izpratani = [], 0.0, [], 0
    try:
        for pointer, target in pokazalci(indeks, podbor):
            if izbrani and not any(part in target for part in izbrani):
                continue
            body, tsyalo = detail(root, target, OTRYAZAK)
            if not body:
                print(f"  ⚠️ няма файл — {target}")
                continue
            state = (f"INDEX LINE (a pointer in an index):\n{pointer}\n\n"
                     f"DETAIL FILE ({target}), the source of truth:\n{body}")
            # A confidential row stops ITSELF, not the review: otherwise the only
            # way to get a review is to remove the barrier. Judged on the WHOLE
            # file, not the extract -- a client named on page four is still named.
            zadarzhano = poveritelno(f"{pointer}\n{tsyalo}", target, dumi)
            if zadarzhano:
                zadarzhani.append((target, zadarzhano))
                print(f"  ⛔ задържан ({zadarzhano}) — {target}")
                continue
            izpratani += 1   # counted BEFORE the send: the ledger records what left
            out = pitay(api_key, state, {"stale": {
                "type": "noul",
                "instructions": ("The index line is only a pointer; the detail file is the source "
                                 "of truth. Does the index line assert anything the detail file "
                                 "contradicts, has superseded, or now reports differently?"),
                "criteria": {"true": "The index says something the file no longer supports",
                             "false": "Consistent, or asserts nothing the file covers"}}},
                target, dumi)
            value = out["answers"]["stale"]["noul"]
            spent += out.get("usage", {}).get("cost", 0)
            results.append((value, target))
            print(f"  {value:<5} {target}")
    finally:
        # Written even when the run falls over: text that left the machine does not
        # come back because the reply did not.
        zapishi(cfg["home"], "dali", indeks.name, izpratani, spent)

    if zadarzhani:
        print(f"\nЗАДЪРЖАНИ ({len(zadarzhani)}) — не са изпращани:")
        for target, duma in zadarzhani:
            print(f"  ⛔ {target} ({duma})")
    print(f"\nНАД ПРАГА ({PRAG}) — погледни ги, не им вярвай:")
    flagged = [r for r in sorted(results, reverse=True) if r[0] >= PRAG]
    for value, target in flagged:
        print(f"  🔴 {value:.2f}  {target}")
    if not flagged:
        print("  (нищо)")
    print(f"\nцена: ${spent:.6f}")


def tvardeniya(line: str) -> list[str]:
    """Cut a pointer line into separate claims, on the separators prose uses."""
    body = re.sub(r"^\[[^\]]*\]\([^)]*\)\s*[—-]\s*", "", line)
    body = re.sub(r"\*\*|`|⚠️|⭐|✅|⛔|🔴|⏳", "", body)
    parts = re.split(r"(?<=[.;])\s+|\s+·\s+", body)
    return [p.strip() for p in parts if len(p.strip()) > 25][:9]


def koe(api_key: str, cfg: dict, target: str) -> None:
    indeks = Path(cfg["indeks"]).expanduser()
    dumi, root = cfg["poveritelni"], indeks.parent
    pointer = next((p for p, t in pokazalci(indeks, None) if t == target), "")
    if not pointer:
        sys.exit(f"няма ред в {indeks.name} за {target}")
    body, tsyalo = detail(root, target, TSYAL)
    pieces = tvardeniya(pointer)
    if not pieces:
        sys.exit("не се извадиха твърдения от реда")

    questions = {f"c{i}": {
        "type": "noul",
        "instructions": f"Does the detail file support this specific claim: \"{claim}\"?",
        "criteria": {"true": "The file states or confirms it",
                     "false": "Not stated, contradicted, or reported differently"}}
        for i, claim in enumerate(pieces)}
    state = f"DETAIL FILE ({target}):\n{body}"
    zadarzhano = poveritelno(f"{pointer}\n{tsyalo}", target, dumi)
    if zadarzhano:
        # Here the whole move stops: a person named this one file.
        sys.exit(f"⛔ отказано: „{zadarzhano}“ се среща в {target}. Не напуска машината.")
    spent = 0.0
    try:
        out = pitay(api_key, state, questions, target, dumi)
        spent = out.get("usage", {}).get("cost", 0)
    finally:
        zapishi(cfg["home"], "koe", target, len(pieces), spent)

    print(f"### {target}\n")
    if len(tsyalo) > TSYAL:
        # Said BEFORE the numbers, because it changes how they read: below the cut
        # nothing can support anything, and a low score there means "don't know".
        print(f"⚠️ ФАЙЛЪТ Е РЯЗАН на {TSYAL} от {len(tsyalo)} знака "
              f"({100 - TSYAL * 100 // len(tsyalo)}% не е изпратен). "
              f"Твърдение, чието доказателство е отдолу, пада НЕВИННО.\n")
    for value, claim in sorted((out["answers"][f"c{i}"]["noul"], c)
                               for i, c in enumerate(pieces)):
        mark = "🔴 НЕ СЕ ПОДКРЕПЯ" if value < 0.4 else (
            "🟡 неясно      " if value < 0.7 else "   подкрепено  ")
        print(f"{mark} {value:.2f}  {claim[:110]}")
    print(f"\nцена: ${spent:.6f}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dali", nargs="*", metavar="ЧАСТ",
                        help="остарял ли е показалецът (по желание: части от пътища)")
    parser.add_argument("--koe", metavar="ФАЙЛ", help="кое точно не се подкрепя")
    args = parser.parse_args()
    if args.dali is None and not args.koe:
        parser.error("избери --dali или --koe")
    cfg = config()
    api_key = klyuch()
    if args.koe:
        koe(api_key, cfg, args.koe)
    else:
        dali(api_key, cfg, set(args.dali))


if __name__ == "__main__":
    main()
