#!/usr/bin/env python3
"""Review an index against the files it points at, with Jev (TypeSafe System One).

    python3 tools/baton_pregled.py --dali            # has a pointer gone stale?
    python3 tools/baton_pregled.py --koe <file>      # which claim is unsupported?
    python3 tools/baton_pregled.py --zadachi         # do the task headers still match?

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

## `--zadachi`: the header against its own logbook

Same shape, different corpus: a task header's `sledvashto` and `kriterii_zavarshvane` are
pointers, and the logbook below them is the source. A header saying "waiting for the
supplier" over a logbook whose last three entries are about something else is the same
rot as a stale index line, and equally invisible to string matching.

⚠️ **The threshold below was NOT measured on this corpus.** It was measured on a memory
index. Task headers are shorter, logbooks are longer and newest-first. Treat `--zadachi`
output as an ordering to look at, and measure your own threshold before trusting a number.

## The threshold, and the band around it

`PRAG = 0.46`, measured by hand on 14 of 19 pointers checked personally.

⚠️ It was once written here that everything ≥0.47 turned out real and everything
≤0.45 false. **Retired by measurement on 2026-09-23**: that is a 0.02 separation,
and three identical runs over 45 pointers put the spread at 0.09–0.12 in exactly
that region. The number is an ORDERING. There is no sharp edge.

That measurement is why `SIVA = (0.35, 0.60)` exists: inside the band a single draw
is partly a coin flip, so `--dali` and `--zadachi` draw three times and average.
See `stoynost()` for the numbers.

⚠️ Both are measured on ONE corpus of 19 rows, in one person's writing, in Bulgarian.
A starting point, not a constant. Run it on your own index, check what it flags by
hand, and move the numbers to where they separate yours.
"""

from __future__ import annotations

import argparse
import importlib.util
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
SIVA = (0.35, 0.60)  # the band where one draw is partly a coin flip -- measured
TEGLENIYA = 3        # draws inside that band, averaged
OTRYAZAK = 2600      # for --dali: the extract that question wants
TSYAL = 28000        # for --koe: a CEILING, not a promise; it announces itself

LINK = re.compile(r"\[([^\]]+)\]\(([^)#]+\.md)\)")

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "baton_session_start.py"

# What a task header asserts about where the work stands. These are the pointers;
# the logbook under them is the source of truth, exactly as an index line points at
# a detail file.
# `chaka` was here until 2026-09-26 and was read on every run. Measured across
# every task on the machine: not one used it. A field nobody fills is not a field,
# it is a line that makes the header look richer than it is. (`chakashta`, a value
# of `sastoyanie`, is a different thing and is in active use.)
HEADER_CLAIMS = ("sledvashto", "kriterii_zavarshvane", "sastoyanie", "na_hod")

# Control words, not claims -- `--koe` skips them; `--zadachi` still reads them.
#
# Measured 2026-09-23 across all 19 tasks: these two came back "not supported" on
# 6 of 6 reviewed tasks, 0.02-0.13 and 0.07-0.35. The deciding row is a task with a
# 42,317-character logbook and 33 entries whose three real claims scored 0.95, 0.97
# and 0.97 -- and whose own logbook "does not support" `postoyanna`.
#
# A logbook never writes "sastoyanie: postoyanna". It is the word that names where
# the work stands, not something the entries assert, so asking whether they support
# it asks for something that cannot be supported. Twelve of the 25 claims in that
# run were these two fields and every one was a false positive: the majority of the
# output, and its most visible part.
#
# ⚠️ `na_hod` sometimes carries a name rather than an enum ("Ledger (редактор
# Burley)"). That case was NOT measured separately on a full logbook -- the three
# thick-logbook rows all read `nie`. It is excluded with the field, not on evidence
# of its own.
#
# They remain in `--zadachi`, which reads the whole header together. Judging where
# the work stands is that mode's job; naming which claim broke is this one's.
KONTROLNI = ("sastoyanie", "na_hod")


def _hook():
    """The hook's own header parsing, reused rather than reimplemented.

    Two readers of one header that disagree is a defect waiting to happen, and the
    one that sends things over the network should not be the one that guessed.
    """
    spec = importlib.util.spec_from_file_location("baton_session_start", HOOK)
    module = importlib.util.module_from_spec(spec)
    sys.modules["baton_session_start"] = module
    spec.loader.exec_module(module)
    return module


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
        "logbook": (os.environ.get("BATON_LOGBOOK") or cfg.get("logbook") or "LOGBOOK.md"),
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


def stoynost(api_key: str, state: str, questions: dict, etiket: str,
             dumi: list[str], kluch: str = "stale") -> tuple[float, list[float], float]:
    """One draw, or `TEGLENIYA` averaged inside the grey band.

    Measured 2026-09-23 on 45 pointers, three identical runs of the same request:
    the spread is negligible where the model is confident -- median 0.010, and 6
    of 45 rows identical all three times -- and LARGEST exactly where the decision
    is made. The two rows whose mean sat between 0.38 and 0.55 gave ±0.12 and
    ±0.09, the largest in the corpus, and one of the 45 changed sides of the
    threshold between identical runs: 0.41 / 0.47 / 0.38. It would have been
    flagged in one run out of three.

    So the model is steady where it is sure and unsteady where it is asked to
    decide, and the average hides it: 0.02 sounds calm. Inside the band the mean
    of three costs about three hundredths of a cent for the handful of rows that
    land there; outside it, a second draw buys a hundredth of a point.

    ⚠️ The band, like `PRAG`, is measured on ONE corpus. It is not a constant.

    Returns (value, draws, cost) -- `draws` so the caller can print what it paid
    for, because a mean printed alone looks exactly like a single draw.
    """
    out = pitay(api_key, state, questions, etiket, dumi)
    draws = [out["answers"][kluch]["noul"]]
    cost = out.get("usage", {}).get("cost", 0)
    if SIVA[0] <= draws[0] <= SIVA[1]:
        for _ in range(TEGLENIYA - 1):
            # No `uid`: the audit that measured all this also measured that the
            # cookbook's uid trick ADDS variance rather than revealing it.
            again = pitay(api_key, state, questions, etiket, dumi)
            draws.append(again["answers"][kluch]["noul"])
            cost += again.get("usage", {}).get("cost", 0)
    return sum(draws) / len(draws), draws, cost


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
            value, draws, cost = stoynost(api_key, state, {"stale": {
                "type": "noul",
                "instructions": ("The index line is only a pointer; the detail file is the source "
                                 "of truth. Does the index line assert anything the detail file "
                                 "contradicts, has superseded, or now reports differently?"),
                "criteria": {"true": "The index says something the file no longer supports",
                             "false": "Consistent, or asserts nothing the file covers"}}},
                target, dumi)
            izpratani += len(draws) - 1   # the band's extra draws also left
            spent += cost
            results.append((value, target))
            # The draws are printed, never only the mean: a mean of three shown
            # alone is indistinguishable from one draw, and the spread IS the
            # finding on the rows that land here.
            povtoreno = f"  ({' '.join(f'{d:.2f}' for d in draws)})" if len(draws) > 1 else ""
            print(f"  {value:<5.2f} {target}{povtoreno}")
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


def zadachi(api_key: str, cfg: dict, izbrani: set[str]) -> None:
    """Every task header against the logbook it sits on top of."""
    hook = _hook()
    root = Path(cfg["home"]).expanduser()
    # The name comes from the SAME config chain as everything else here. Taking it
    # from hook.config() read a different baton.local.json -- the source copy, which
    # has none -- and the run silently found no logbooks at all and cost $0.
    logbook_name = cfg["logbook"]
    dumi = cfg["poveritelni"]
    results, spent, zadarzhani, izpratani = [], 0.0, [], 0
    try:
        for folder in sorted(p for p in root.iterdir() if p.is_dir()
                             and not p.name.startswith(".")):
            if izbrani and not any(part in folder.name for part in izbrani):
                continue
            book = folder / logbook_name
            if not book.is_file():
                continue
            whole = book.read_text(encoding="utf-8", errors="replace")
            fm = hook.parse_frontmatter(whole)
            claims = {k: v for k, v in fm.items() if k in HEADER_CLAIMS and str(v).strip()}
            if not claims:
                print(f"  ⚠️ без хедър — {folder.name}")
                continue
            body = whole.split("---", 2)[2].strip() if whole.startswith("---") else whole
            pointer = "\n".join(f"{k}: {v}" for k, v in claims.items())
            zadarzhano = poveritelno(f"{pointer}\n{whole}", folder.name, dumi)
            if zadarzhano:
                zadarzhani.append((folder.name, zadarzhano))
                print(f"  ⛔ задържана ({zadarzhano}) — {folder.name}")
                continue
            state = (f"TASK HEADER (what it claims about where the work stands):\n{pointer}\n\n"
                     f"LOGBOOK ({logbook_name}), newest entries first, the source of truth:\n"
                     f"{body[:OTRYAZAK]}")
            izpratani += 1
            value, draws, cost = stoynost(api_key, state, {"stale": {
                "type": "noul",
                "instructions": ("The header is only a pointer; the logbook is the source of "
                                 "truth. Does the header assert anything the recent entries "
                                 "contradict, have superseded, or now report differently — a "
                                 "next step already taken, a state that has changed, someone "
                                 "who is no longer the one holding the move?"),
                "criteria": {"true": "The header says something the logbook no longer supports",
                             "false": "Consistent, or asserts nothing the entries cover"}}},
                folder.name, dumi)
            izpratani += len(draws) - 1
            spent += cost
            results.append((value, folder.name))
            povtoreno = f"  ({' '.join(f'{d:.2f}' for d in draws)})" if len(draws) > 1 else ""
            print(f"  {value:<5.2f} {folder.name}{povtoreno}")
    finally:
        zapishi(cfg["home"], "zadachi", root.name, izpratani, spent)

    if zadarzhani:
        print(f"\nЗАДЪРЖАНИ ({len(zadarzhani)}) — не са изпращани:")
        for name, duma in zadarzhani:
            print(f"  ⛔ {name} ({duma})")
    print(f"\nПОДРЕДЕНИ ПО ПОДОЗРЕНИЕ — ⚠️ прагът НЕ е мерен на този корпус:")
    for value, name in sorted(results, reverse=True):
        print(f"  {'🔴' if value >= PRAG else '  '} {value:.2f}  {name}")
    print(f"\nцена: ${spent:.6f}")


def tvardeniya(line: str) -> list[str]:
    """Cut a pointer line into separate claims, on the separators prose uses."""
    body = re.sub(r"^\[[^\]]*\]\([^)]*\)\s*[—-]\s*", "", line)
    body = re.sub(r"\*\*|`|⚠️|⭐|✅|⛔|🔴|⏳", "", body)
    parts = re.split(r"(?<=[.;])\s+|\s+·\s+", body)
    return [p.strip() for p in parts if len(p.strip()) > 25][:9]


def zaglavni_tvardeniya(fm: dict) -> list[tuple[str, str]]:
    """(field, claim) for every assertion a task header makes.

    A header is multi-claim by construction -- five fields, and `sledvashto`
    routinely carries two sentences ("steps 0-7 are done and checked. What
    remains is X"). `--zadachi` asks one question of the lot and answers "this
    header no longer matches"; this answers WHICH part.

    A field too short to be a sentence is its own claim: a one-line
    `kriterii_zavarshvane` names something the entries can contradict. A dash is
    not -- that is what someone types to mean "nothing here".

    ⚠️ `sastoyanie` and `na_hod` are skipped; see `KONTROLNI` for the measurement
    that took them out. It was written here first that `sastoyanie: aktivna` is an
    assertion the logbook can contradict. It is not, and running the mode over
    every task is what showed it.
    """
    out = []
    for field in HEADER_CLAIMS:
        if field in KONTROLNI:
            continue
        value = str(fm.get(field, "")).strip()
        if len(value) < 3 or not any(ch.isalnum() for ch in value):
            continue
        out.extend((field, piece) for piece in (tvardeniya(value) or [value]))
    return out


def koe_zadacha(api_key: str, cfg: dict, name: str, kniga: Path) -> None:
    """Every claim a task header makes, against the logbook under it.

    The corpus `--koe` was built for -- index lines cut into claims -- is gone.
    Measured 2026-09-23 on this machine: 0 of 45 index rows yield three claims and
    13 yield none, because the index was compressed on purpose, so that a pointer
    carries no state. That was right, and it left this mode without input: an index
    that cannot rot is an index `--koe` cannot check.

    Task headers rot by design -- that is what `sledvashto` is for -- and `--zadachi`
    already asks the whole-header version of this question against these same
    logbooks. So the corpus moves and the question stays.

    ⚠️ One thing genuinely differs from the index corpus. There, a file cut at
    `TSYAL` failed claims innocently: the evidence could sit anywhere, including
    below the cut. A logbook is NEWEST-FIRST, so the same cut keeps the newest
    entries -- which is the evidence a header's currency is judged against. The cut
    is still announced, but it no longer means "a claim may fail for nothing".
    """
    hook = _hook()
    dumi = cfg["poveritelni"]
    whole = kniga.read_text(encoding="utf-8", errors="replace")
    pairs = zaglavni_tvardeniya(hook.parse_frontmatter(whole))
    if not pairs:
        sys.exit(f"хедърът на {name} не носи твърдения, които да се проверяват")
    body = whole.split("---", 2)[2].strip() if whole.startswith("---") else whole
    pointer = "\n".join(f"{field}: {claim}" for field, claim in pairs)
    # The WHOLE logbook, not the part that fits: a client named on page four is
    # still named. Same rule as everywhere else here, and the reason is 13:20.
    zadarzhano = poveritelno(f"{pointer}\n{whole}", name, dumi)
    if zadarzhano:
        sys.exit(f"⛔ отказано: „{zadarzhano}“ се среща в {name}. Не напуска машината.")

    questions = {f"c{i}": {
        "type": "noul",
        "instructions": f"Does the logbook support this specific claim: \"{claim}\"?",
        "criteria": {"true": "The entries state or confirm it",
                     "false": "Not stated, contradicted, or reported differently"}}
        for i, (_, claim) in enumerate(pairs)}
    state = f"LOGBOOK ({kniga.name}), newest entries first:\n{body[:TSYAL]}"
    spent = 0.0
    try:
        out = pitay(api_key, state, questions, name, dumi)
        spent = out.get("usage", {}).get("cost", 0)
    finally:
        zapishi(cfg["home"], "koe-zadacha", name, len(pairs), spent)

    zapisi = body.count("\n## ") + body.startswith("## ")
    print(f"### {name} — хедърът срещу дневника си\n")
    # Said before the numbers, all three, because each changes how they read.
    print("⚠️ Границите 0.4 / 0.7 НЕ са мерени на този корпус. Подредба, не присъда.")
    # Found by the positive control, 2026-09-23: a task whose header spoke of a
    # review, a board and a submission came back "unsupported" on all four claims
    # -- correctly, because its logbook is 562 characters and one entry, and
    # mentions none of it. The criterion the model is given reads "Not stated,
    # contradicted, or reported differently", so NEVER WRITTEN DOWN and WRITTEN AND
    # THEN CONTRADICTED arrive as the same low number. They are not the same
    # finding: one says the header is wrong, the other says the logbook is thin.
    print("⚠️ „Не се подкрепя\" значи И „опровергано\", И „изобщо не се споменава\". "
          "Двете не са едно и също.")
    print(f"   Дневникът тук е {len(body)} знака, {zapisi} записа — "
          f"{'тънък, тъй че ниското значи по-скоро „не пише", отколкото „не е вярно"' if len(body) < 2000 else 'достатъчен, за да носи опровержение'}.\n")
    if len(body) > TSYAL:
        print(f"⚠️ ДНЕВНИКЪТ Е РЯЗАН на {TSYAL} от {len(body)} знака. Дневникът е "
              f"най-новите първо, тъй че отрязаното са НАЙ-СТАРИТЕ записи — точно "
              f"обратното на индекса, където срезът валеше твърдения невинно.\n")
    for value, field, claim in sorted(
            (out["answers"][f"c{i}"]["noul"], f, c) for i, (f, c) in enumerate(pairs)):
        mark = "🔴 НЕ СЕ ПОДКРЕПЯ" if value < 0.4 else (
            "🟡 неясно      " if value < 0.7 else "   подкрепено  ")
        print(f"{mark} {value:.2f}  {field}: {claim[:88]}")
    print(f"\nцена: ${spent:.6f}")


def koe(api_key: str, cfg: dict, target: str) -> None:
    # A bare task name wins over an index target. Nothing in an index resolves to
    # a task folder -- index targets carry a path, task names do not -- but the
    # rule is written down and pinned rather than left to that staying true.
    kniga = Path(cfg["home"]).expanduser() / target / cfg["logbook"]
    if kniga.is_file():
        return koe_zadacha(api_key, cfg, target, kniga)
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
    parser.add_argument("--zadachi", nargs="*", metavar="ЧАСТ",
                        help="хедърът на всяка задача срещу дневника ѝ")
    args = parser.parse_args()
    if args.dali is None and args.zadachi is None and not args.koe:
        parser.error("избери --dali, --koe или --zadachi")
    cfg = config()
    api_key = klyuch()
    if args.koe:
        koe(api_key, cfg, args.koe)
    elif args.zadachi is not None:
        zadachi(api_key, cfg, set(args.zadachi))
    else:
        dali(api_key, cfg, set(args.dali))


if __name__ == "__main__":
    main()
