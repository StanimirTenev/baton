# Baton

**Work that survives the session.**

A coding agent forgets everything between sessions. Not *some* of it — all of it. The next
session opens with your files and none of your reasoning: not what was decided, not what
was ruled out, not what was already tried and failed.

The usual answer is "write it down." That answer fails in exactly the session where it
matters most — the long, loaded one, at the end of which nobody is thinking about
note-taking.

Baton makes the note-taking structural instead of voluntary. Every task gets a folder, the
folder holds a `LOGBOOK.md`, and two hooks make sure the logbook is read at the start and
written at the end. The hooks are executed by the harness, not by the agent's judgement.

## Install

**Linux / macOS:**

```bash
git clone https://github.com/StanimirTenev/baton ~/.baton
~/.baton/install.sh
```

**Windows, fresh machine with no Claude Code** — double-click `setup-windows.cmd`. It
installs Claude Code (Anthropic's own native installer — no administrator, no Node.js, needs
internet) and then Baton, in one step.

**Windows, Claude Code already present** — double-click `install.cmd`, or from a terminal:

```
git clone https://github.com/StanimirTenev/baton %USERPROFILE%\.baton
%USERPROFILE%\.baton\install.cmd
```

No git and no internet on the target machine? Copy this folder onto a USB stick, plug it
in, and double-click `install.cmd`. The installer copies the hooks into your user profile,
so the stick can come straight back out afterwards. Put a Windows **embeddable Python**
(from python.org) in a `python-win\` folder next to `install.cmd` and the installer will
use it when the machine has no Python of its own — so the stick needs nothing installed on
the target at all.

Then open `/hooks` once (or restart) so Claude Code reloads its settings. Or just point an
agent at this repository and say: **"read the README and install it."**

### Dev tools (git, gh, node/npm, ripgrep, python)

Claude Code itself is self-contained, but real work usually wants a toolchain. `tools-windows.cmd`
installs **git, GitHub CLI, Node.js + npm, ripgrep, and Python** via winget. These install
machine-wide, so it needs administrator (accept the UAC prompts); re-running is safe. Git for
Windows gives Claude Code its Bash tool, `gh` drives PRs and issues, `node`/`npm` run MCP servers,
`rg` is fast search. It is kept separate from the Baton install, which needs no administrator.

### Why `install.cmd` and not the `.ps1` directly

On Windows a bare `.ps1` often stops with *"running scripts is disabled on this system"* —
the PowerShell execution policy. `install.cmd` sidesteps it the documented way: a `.cmd`
file is not itself governed by the execution policy, and it launches PowerShell with
`-ExecutionPolicy Bypass` **scoped to that one process**. No administrator, and the
machine's policy is left exactly as it was. It is not a security bypass — it is the
per-process scope PowerShell provides for exactly this.

### What it does, on every OS

Nothing is overwritten. The installer copies the hooks into `~/.claude/baton/` and the
skills into `~/.claude/skills/` (`baton-inventory`, `baton-plan`), appends to
`~/.claude/CLAUDE.md`, merges two entries into `~/.claude/settings.json`, and creates
`~/tasks/`. Because the hooks are copied to your profile, the source — a clone, a download,
or a USB stick — can be removed afterwards. Run it twice and the second run reports that
everything is already in place. Add `--dry-run` (or `-DryRun` on Windows) to see the
changes without making them.

Requires Python — the hooks are Python, one implementation for Linux, macOS and Windows.
The interpreter's absolute path is baked into the hook, so a hook never depends on `PATH`
at run time. On Windows without Python, the installer uses a bundled copy if one sits in
`python-win\` (the USB build carries it), otherwise it prints the one-line,
no-administrator `winget` command to add it for your user.

### Existing work: `/baton-inventory`

The installer also copies one skill, `~/.claude/skills/baton-inventory/`. Baton starts
empty, but the machine rarely does. Run `/baton-inventory` once after installing:

1. **Scan.** Four read-only agents search the machine at the same time. They cover git
   repositories, loose files, Claude Code memory and history, and project folders.
2. **Review.** The results are gathered into one inventory: tasks with a next step,
   recurring work, frozen, done, files that belong to existing tasks, and risks found on the
   way (a repository with no remote, a readable private key). **You confirm the state of
   each item.**
3. **Apply.** Only then are task folders created. Each logbook opens with an entry marked
   *reconstructed*, and nothing is moved.

When the evidence conflicts, memory and history decide the state and files decide the
location. A file date tells you when something was touched, not whether it is finished.
On its first run the file-only agents misjudged state three times, and memory was right
each time.

### Two paths, and the cheap one is the default

**The direct path** needs no skill: read the logbook, do the work, write the entry. The hooks
already enforce it. One letter, one fix, one decision, one measurement — this is most work.

**The swarm** is `/baton-plan`, and it costs. Measured on real rounds: seven agents ≈ 1.3 million
tokens and half an hour; four agents ≈ 660 thousand. Worth it when there is something to
**measure** or a written **claim to attack**; not worth it for judgement — a price, a name, a
letter — where a swarm returns opinions, and opinions do not improve by being seven.

The test: *what would the round check its answer against?* No answer, no round.

### A big new goal: `/baton-plan`

For a task that runs in several directions at once (launching a product, finding
customers), the second skill runs a loop in which **research comes before the plan**:

1. **Goal first.** You and the agent agree on the result you expect and how you will
   know you reached it. The task folder gets a `PLAN.md` v0, drafted from what the agent
   already knows and labelled as such. That draft is the yardstick for what research
   changed.
2. **Research round.** 6–10 agents run in parallel, one narrow angle each, taken from the
   open questions: competitors, prices, buyers, regulation, channels, and so on. Two agents
   run every time: one that reads your own files and memory, and a devil's advocate
   against the current plan. Each agent writes a table of claims with sources. A claim
   without a source is marked as inferred.
3. **Verify.** An independent agent checks the claims the plan rests on against primary
   sources. `FAKTI.md` records every fact with its status and source.
4. **Plan vN.** The plan is built backwards from the goal. It starts with a section on
   what changed since the last version and why. Long-lead "doors" (listings, partners,
   standards) are started first.
5. **Human checkpoint.** You make the decisions. The open questions go into the next
   round. The loop stops when nothing blocks the plan, or after three rounds.

Agents work in English. The consolidated output comes back in your language. In its first
real use, the first round changed the plan's core argument, and the second round changed
the shape of the product and caught a factual error left over from round one.

## What you get

```
~/tasks/
  migrate-billing/
    LOGBOOK.md          ← what was done, newest entry first
    schema-notes.md
    export-2026-03.csv
  broken-disk/
    LOGBOOK.md
    replacement-procedure.pdf
```

**SessionStart** tells the session which task comes first, so it never opens blind.
Tasks with a header (see below) are grouped by who holds the next move and sorted by
priority. The human sees the same list the agent gets:

```
Baton — задачите в /home/you/tasks, подредени по кой е на ход и приоритет:

⏳ Чакат ТЕБ / може да продължим сега:
- migrate-billing [visok] — decide tax_region before the run

🔁 Постоянни:
- weekly-report [nisak] — Monday export

⛔ Чакат ВЪНШЕН / блокирани (за сведение):
- broken-disk [sreden] — zpool replace  (чака: new disk (delivery))

❄️ Замразени (не се предлагат): old-scraper

✅ Приключени (не се пипат): schema-audit
```

The groups mean overdue (a deadline within 3 days), on us, recurring, waiting on someone
else, frozen and done. A task with no header falls back to the v1 line: its name, the date
of its last entry, and that entry's title.

> The group labels and header keys are Bulgarian (transliterated), because that is where
> Baton was built. English values are accepted where noted below.

**Stop** checks whether any task folder holds a file newer than its `LOGBOOK.md`. If one
does, the turn is handed back with a note naming it. The test is deliberately narrow: a
session that touched no task folder is never interrupted, and `stop_hook_active` is honoured
so it can block at most once per turn.

## The task header (v2)

A logbook can open with a small header. It is optional. With a header, SessionStart knows
what the task *means* right now, not only when it was last touched.

```markdown
---
sastoyanie: aktivna          # state
na_hod: nie                  # who holds the next move: nie (= us) or a name / a condition
kriterii_zavarshvane: "migration ran, row counts match"   # when is it done
vremevi_kriterii: po_izbor   # po_izbor (any time) | postoyanno (recurring) | YYYY-MM-DD (deadline)
sledvashto: "decide tax_region before the run"             # the next concrete action
prioritet: visok             # visok | sreden | nisak  (high | medium | low)
umeniya: [db-migration]      # optional: the skills this task needs (see below)
vyarno_kum: 2026-03-14       # optional: when this header was last true
pregled_sled: 30d            # optional: how long that is expected to hold (30d, 6m)
---
```

| `sastoyanie` | meaning | also accepted |
|---|---|---|
| `aktivna` | in progress | |
| `chakashta` | waiting on someone or something external | `waiting` |
| `postoyanna` | recurring, never finishes | |
| `zamrazena` | parked on purpose; listed, never offered as work | `frozen`, `paused` |
| `priklyuchila` | done; listed, not touched | `priklyuchena`, `done` |

For `na_hod`, anything other than `nie` / `us` / `me` / `self` (or empty) counts as "waiting
on someone else". A task waiting on someone never lands in "on us", even with a deadline.
The parser is deliberately small: `key: value` lines, quoted strings, `[a, b]` lists and
trailing ` #` comments. It is not full YAML, so Baton needs no dependencies.

## Skills a task needs

A task folder holds two things: **state** (the header) and **history** (the logbook). It
does not hold the third — *how the work is done here*. The limits that bite, the check that
has to run after the action, the number that must not be cited: that ends up scattered
through entries, and is re-derived by whoever reads them next at the cost of reading the
whole file, or is not derived at all and a paid-for mistake is repeated.

`umeniya: [name, ...]` names what the task needs (`skills:` also works). The session-start
line then carries `⟨умения: …⟩`, and the agent invokes what it needs on entering the task.

Skills are read from `~/.claude/skills/<name>/SKILL.md`; point elsewhere with `BATON_SKILLS`
or `"skills"` in `baton.local.json`.

**Named, never loaded.** Baton says what a task needs. It does not reach into the session,
and it does not fetch, update or adopt anything. That restraint matters more here than
anywhere else it applies: a skill is *instructions*, and instructions fail silently where
code fails loudly. A library that refreshed itself from a remote source would put whatever
that source says today in charge of how the work is done today — no version, no diff, no
review.

Two things are reported, and the second is the dangerous one:

- **missing** — loud: the header asks for something that is not installed, and nothing loads;
- **stale** — quiet, and worse. A missing skill makes you think; a stale one makes you
  confident. A skill written once and re-read fifty times is exactly where knowledge goes out
  of date unnoticed. Reported when the skill was last written more than **14 days** before the
  task's last entry: a skill does not go out of date because the logbook moved yesterday, and a
  detector that cries on a normal Tuesday gets switched off, taking the real signal with it.

## Shelf life

A record does not go wrong by being old. It goes wrong by being old and still reading exactly
like a current one. Three of those, on three consecutive days, produced this feature: a
comparison table written for one release quoted three releases later; a line marked at the time
as an inference — "auditors probably cannot take a commission" — carried as settled until
someone read the code of ethics it claimed to summarise, and found the opposite; two decisions
left live in memory for weeks after the work had gone the other way.

None of the three was a wrong fact. Each was a fact that had stopped being one.

**Two optional header fields.** `vyarno_kum` is the date the header was last true;
`pregled_sled` is how long that is expected to hold (`30d`, `6m`). When the period has passed,
the task appears at session start under **Изтекъл срок на годност**, with how late it is. Neither
field is required, and a task without them behaves exactly as it did before.

**An unverified claim is a debt.** If a task keeps a claims register — `TVARDENIYA.md`,
`CLAIMS.md`, `FAKTI.md` or `FACTS.md` — whose rows carry a status column, Baton reads it. A row
marked **И**/`I` (inferred) or **А**/`A` (an agent's claim, not independently checked) is reported
once it is older than 30 days, with the count and the age of the oldest. Rows marked verified
(**П**) or checked locally (**В**) are never reported, at any age.

A row dates itself when it can — a date, optionally with a time, in **a cell of its own** — and
otherwise takes the date of the heading above it (`## Round 2 — 2026-09-19`). Both, because a
register filled a row at a time over weeks has no meaningful block date, and a table written in
one sitting has no row dates. The date has to be its own cell: matching a date anywhere in the row
read `| last release 0.12.0 (14.08.2026) | А |` as a claim made in August, which is a date inside
the claim. A detector that fires on the wrong thing gets switched off, and then the real ones go
unread too.

The time is allowed because a day is not always fine enough. On the day this was written six
claims were made and five were falsified within it, two of them within an hour; dated only to the
day, that register says nothing about what followed what. Ageing stays in days — a debt is not
measured in hours — but the stamp keeps the order.

A status cannot live in the logbook. The logbook is a record and does not get edited, while a
status is exactly the thing that changes when someone finally checks. That is the same reason the
constraints register is a file of its own.

A debt is not an error. It is a claim that has to be paid — verified, or dropped. The one that
produced this feature was a day old when it nearly cancelled a plan; at thirty days it would have
been quoted as a fact by a session that had never seen it written.

## A pointer that has grown into a record

`sledvashto` says what the next move is. When state gets copied into it so that it is visible at
session start, the same fact now lives in two places and only one of them gets corrected. Past
**240 characters** Baton reports it: the field has stopped pointing and started holding state.

Length is a proxy and the only honest one available — a hook cannot tell a stale sentence from a
current one, but it can tell that a one-sentence field has become a paragraph, which is when the
copying happened. One memory index carried "still waiting for the paper" for five days after the
paper had arrived and been read, because the detail file was updated and the pointer was not.

## The running hook is a copy

The hooks execute from wherever they were installed, not from where they are developed. v2.2.0 of
this project shipped a whole shelf-life layer — written, tested, tagged — and it never ran: the
installed copy was two days old and 217 lines behind, and every session since had been assured by
a hook that did not contain the check. The release notes said it was live. The repository agreed.
The machine did not.

Set `source` in `baton.local.json` (or `BATON_SOURCE`) to the directory the hooks are developed
in, and Baton compares its own bytes against it and reports a difference at session start. It is
optional: an install from a release configures no source and nothing is reported.

A hook cannot verify that it was installed. It can ask the same question somewhere it can be
answered.

## The board

```
python3 tools/baton_tablo.py --out tablo.html --open
```

One local HTML file: what is on your move, what waits on someone else, what is late, and every
shelf-life warning. It reuses the hook's own parsing rather than reading the headers a second
way — two readers of one header that disagree is a defect waiting to happen, and the board is
the one that would be believed, because it is prettier.

It is generated, never edited. The logbooks are the record; this is a view of them. Nothing is
uploaded and nothing leaves the machine, which is the reason it is a file rather than a hosted
page: logbooks carry client matter, and a board is not worth sending it anywhere.

## The review: does the index still match the files?

```
python3 tools/baton_pregled.py --dali          # has a pointer gone stale?
python3 tools/baton_pregled.py --koe <file>    # which claim is unsupported?
```

**Optional, off by default, and it needs a key.** Without an
[OpenRouter](https://openrouter.ai) key this does not run, and nothing else in Baton wants
one — the hooks never call it and never touch the network.

It exists for the one kind of rot Baton cannot catch by matching strings: an index line that
asserts something the file it points at has since contradicted. A contradiction has no
textual signature. Either someone re-reads both, or it stays. Measured on 19 such pointers
here: six were wrong, two in ways no pattern could have found, for **$0.0013** the run.

It sends the pointer and part of the file to a hosted model ([TypeSafe's
Jev](https://typesafe.ai), which returns calibrated probabilities rather than text). That is
the whole reason it is opt-in and separate from the hooks: logbooks carry client matter.

### Configure it before it will run

In `hooks/baton.local.json`:

```json
{
  "pregled_indeks": "~/notes/INDEX.md",
  "pregled_podbor": "~/notes/AT-RISK.md",
  "pregled_poveritelni": ["client-name", "Client Name", "unreleased-product"]
}
```

| | |
|---|---|
| `pregled_indeks` | the index whose pointers get checked — any file with `[title](path.md)` links |
| `pregled_podbor` | optional shortlist: only the targets it names are checked, so a long index need not be paid for whole |
| `pregled_poveritelni` | substrings that must never leave the machine |

The guard reads the **whole source file**, not the part that gets sent: the question is
whether this document is about confidential matter, not whether the bytes that happened to fit
contained the word. That is deliberately conservative and it costs coverage — on the corpus
here it holds 10 of 19 rows. Holding too much is a list to narrow; holding too little is a
disclosure.

**`pregled_poveritelni` is required, and absent is not empty.** With the key missing the tool
stops and tells you to decide; write `[]` if you really mean that nothing is held back. The
match is on the path *and* the content, because material sits in an innocent folder and still
recounts a client's business.

⚠️ **Write every name in every alphabet you use.** Here the list held only the Latin spelling
of a client's name while the notes about that client were written in Cyrillic. The guard was
structurally correct, matched nothing, and a request went out. A test caught it; reading the
line had not, three times.

A held row stops *itself*, not the run — otherwise the only way to get a review is to remove
the barrier. Every run appends to `$BATON_HOME/.pregled-dnevnik.tsv`: what was sent, when,
what it cost.

### Two questions, opposite amounts of evidence

Measured, and the easiest thing here to get backwards:

| question | evidence | what the other way does |
|---|---|---|
| has the pointer gone stale? | an **extract** (~2600 chars) | the whole file drops real cases 0.73 → 0.43 |
| which claim is unsupported? | the **whole file** | an extract gives false ones: 0.02 against 0.97 |

One reason both ways: a summary judgement is diluted by a long text, while a single claim has
its evidence *somewhere* in it — and a cut above that evidence fails the claim innocently.

`--koe` caps at 28000 characters and **says so** when it cuts, because below the cut nothing
can support anything and a low score there means "don't know", not "no".

The same cut is why `--dali` keeps flagging a pointer whose correction is recorded deep in the
file: the fix is real, the extract cannot see it. Read what it flags; do not trust it.

### What the number is not

`PRAG = 0.46` was measured by hand — 14 of 19 pointers checked personally, everything ≥0.47
real and everything ≤0.45 false. ⚠️ That is **one corpus of 19 rows, one person's writing, one
language.** It is a starting point. Run it on yours, check what it flags, move the number.

And in TypeSafe's own words: *calibration is measured across groups of predictions; it does
not guarantee that an individual answer is correct.* This ranks and says "look here". A person
opens the file and decides. Nothing is rewritten because a number was high.

## Retiring a constraint

Research adds. Almost nothing retires, and a rule nobody retires goes on steering the plan from a
file no one re-reads. One project's second research round found nineteen such conflicts and
retired none of them — it produced banners.

So `/baton-plan` now ends a round by re-scoring every constraint it touched, into
`OGRANICHENIYA.md` (or `CONSTRAINTS.md`), one row each:

```markdown
| id | статус | файл | текст |
|----|--------|------|-------|
| O1 | пада   | POZICIA.md | only this tool separates reading from finding |
| O2 | остава | MEMORY.md  | no commercial product on the research site |
```

Three statuses and nothing else: **пада** / `falls`, **остава** / stands, **чака проверка** /
awaits a check. The bar for retiring is the bar for asserting — a source or a measurement, never
"it feels outdated". An inconvenient constraint is the one most likely to be true.

**Baton checks the register against the files.** A row marked fallen whose text is still in the
named file is reported at session start, because it did not fall — it was written down as having
fallen. A file the register names and that is not there is reported too: skipping it quietly is
the same defect, a rule that looks retired because nobody could check it.

On its first real run this caught two sentences that a correction pass had already been through
twice — one of them in the very document whose top carried a banner saying it was wrong.

## The logbook entry

```markdown
## 2026-03-14 17:20 — schema diff before the migration

### What was asked
Check whether the new billing schema can take the old rows without loss.

### Done
| Action | Detail |
|--------|--------|
| Diffed both schemas | 41 columns match, 2 do not: `tax_region`, `legacy_ref` |
| Counted affected rows | 8,412 of 2.1M carry a non-null `legacy_ref` |

### Result
Migration is safe for 41 columns. The two outliers need a decision before it runs.

### Open / notes
`tax_region` has no target column at all — ask before inventing one.
Do not trust `legacy_ref` being null to mean unused; 300 rows carry an empty string.
```

**Write it for the next agent, not for the human.** The next session has your files and
nothing else. So record what you would need to continue: what was decided and why, what was
verified and how, what is still unknown, and which mistakes were already paid for — so they
are not paid for twice.

## Ignoring files that change on their own

Some task folders hold a file that legitimately changes without needing a new logbook entry —
a live transcript, a rotating log, generated output. Drop a `.batonignore` in the task folder
(gitignore-style: one glob per line, `#` for comments) and the Stop hook skips those when
deciding whether work went unrecorded:

```
transcript.txt
*.log
build/*
```

The Stop hook also names the newest unrecorded file, so you can see at a glance what tripped it.

## Logbook is not memory

They are different jobs and must not merge:

| | holds | read |
|---|---|---|
| **memory / state file** | what is **true now** — current state, live decisions, access paths | every session, automatically |
| **`LOGBOOK.md`** | what was **done** — session by session, in order, with results | when the task is picked back up |

New state replaces old state in the memory file. The logbook only ever grows. Merge the two
and you get a file that is too long to load every session and too disordered to trust.

[`docs/memory-layout.md`](docs/memory-layout.md) covers the other half: index, one folder
per project, a short state file under 150 lines, chronology in a separate history file.

## Versions

**v2.7.1** — security fix in `tools/baton_pregled.py`, released the day v2.7.0 shipped
- **The confidentiality guard read the first 4000 characters of a payload of up to 28000.** It
  inspected one seventh of what it sent and passed the rest. Four files went out carrying a
  client's name and an unreleased product's name, every occurrence past character 4000. The part
  the guard read was clean, which is exactly why nothing looked wrong.
- It now reads the **whole source file**, not the truncated extract: a client named on page four
  is still named. Conservative on purpose — on the corpus here it holds 10 of 19 rows, and that
  is the right direction to be wrong in.
- Found by running the tool on real files and checking afterwards what had been sent. Not by
  reading the line: the line had been read three times.
- 132 tests, two of which fail against the old window.

**v2.7.0**
- **Every plan in the folder counts, not just `PLAN.md`.** A task running two efforts names them
  apart — `PLAN-jev.md` — and matching one exact filename let precisely those escape. The check
  written for this project then missed this project's own second plan: it held for the file it was
  named after and for nothing else. The pattern is `PLAN.md` and `PLAN-*.md`, so notes named
  `PLANOVE-stari.md` are still not plans.
- **New, optional, off by default: `tools/baton_pregled.py`** — review an index against the files
  it points at. It catches the one kind of rot no string match can: a pointer that asserts
  something its file has since contradicted. On 19 pointers here it found six wrong, two of them
  unreachable by any pattern, for $0.0013.
  - Needs an OpenRouter key. Without one it does not run, and **nothing else in Baton wants one** —
    the hooks still never touch the network.
  - `pregled_poveritelni` is **required before it will run**: absent is not empty. Write every name
    in every alphabet you use — here a list holding only the Latin spelling of a client's name let
    a Cyrillic mention through, and a request went out. A test caught it; reading the line had not.
  - The threshold (0.46) is measured on **one** corpus of 19 rows in one language. Starting point,
    not a constant.
- 130 tests.

**v2.6.0**
- **A plan that was never closed leaves the task unfinished, and it is reported every session.**
  A task holding a `PLAN.md` that does not say it is closed is listed under its own heading, above
  the shelf-life notes. No grace period: this is not a guess about whether something aged — the
  plan either says it is finished or it does not.
- **Closing requires saying what came of it.** A state with an empty `rezultat` is not closed; it
  is a tick, and a tick is how a check gets satisfied without the thing behind it being true.
- **A plan ends in one of two ways, and they are not the same fact.** `izpalnen` — carried out —
  and `izostaven` — given up on. Both finish the task, and giving up is a legitimate recorded
  outcome. But a folder read six weeks later has to say *which*, and why: the reason a plan was
  abandoned is usually the most useful thing left in it.
- `/baton-plan` now writes that header from v0, so a new plan is born closable.
- The failure this exists for: a project ran reconnaissance, analysis and planning repeatedly over
  six weeks and closed a plan exactly never. On its first run the check found four.
- 107 tests.

**v2.5.1**
- **A detector that cries on a normal Tuesday gets switched off.** The staleness check for skills
  compared at a day's granularity and fired on every active task the morning after the skills were
  written. Fourteen days is the honest scale; `missing` is unchanged and still immediate.

**v2.5.0**
- **A task can name the skills it needs.** `umeniya: [name, ...]` in the header, and the
  session-start line carries `⟨умения: …⟩`. A folder already holds state and history; this is
  how it holds the third thing — how the work is done here — instead of leaving it to be
  re-derived from the logbook by whoever reads it next, or not derived at all.
- **Named, never loaded.** The hook says what a task needs; the agent invokes it. Baton does not
  reach into the session, and it does not fetch, update or adopt anything. A skill is
  instructions, and instructions fail silently where code fails loudly — so the human stays in
  the loop by construction, not by policy.
- **Missing is reported, and so is stale.** A missing skill is loud: nothing loads. A stale one
  is quiet and worse, because a missing skill makes you think and a stale one makes you
  confident. Stale is the same comparison as a drifted pointer: last written before the task's
  last entry.
- 95 tests.

**v2.4.0**
- **A pointer sending you to a file that has not moved since the work did.** The Stop hook
  catches a folder whose files are newer than its logbook. The opposite is the one that reaches
  a person: a decisions file *older* than the logbook, still listing questions that were answered
  in some other folder. It looks right, it gets quoted at every session start, and it was handed
  back as unfinished work three sessions running before the person said so.
  Its limit, stated because a check nobody knows the edge of gets trusted past it: it compares
  against *this* folder's logbook, so it is blind to work done elsewhere while nothing here was
  touched. The rule covers that half — an answered question is written back where it was asked.
- **A crash is no longer silent.** The entry point still exits 0 — a hook must not break the
  session it is helping — but it now prints the traceback to stderr. A `NameError` in `main()`
  had made the whole report vanish while every unit test passed: the checks were tested, the
  wiring that calls them was not.
- **The report is tested as a whole**, run as a subprocess over a real folder tree. That test
  fails on the wiring bug above; the unit tests do not.
- 82 tests.

**v2.3.0**
- **A pointer that has grown into a record.** `sledvashto` past 240 characters is reported: state
  copied into a pointer goes stale in one of its two homes.
- **The running hook is a copy.** Baton compares its own bytes against the source it was built
  from, after a release that was written, tested, tagged — and never ran, for two days.
- **Claims carry their own stamp.** A claims register (`TVARDENIYA.md`, `CLAIMS.md`, `FAKTI.md`)
  dates each row in a cell of its own, optionally with a time.
- Two silent truncations fixed in the header parser: `#` inside a quoted value is text, and a
  quoted value ends at the last quote on the line, not the first.
- 67 tests.

**v2.2.0**
- **The board.** `tools/baton_tablo.py` writes one local HTML file with the same state
  the session-start hook reports, laid out to be read at a glance.
- **Two paths, priced.** The direct path needs no skill; the swarm costs roughly 1.3M tokens
  for seven agents, and the README says when it is worth it.
- **Retiring a constraint.** `/baton-plan` re-scores every constraint a round touched into
  `OGRANICHENIYA.md` — stands / falls / awaits a check — and Baton checks the register against the
  files, so a constraint written down as fallen whose text is still there is reported.
- **Shelf life.** Two optional header fields, `vyarno_kum` and `pregled_sled`, make a snapshot
  announce its own age instead of reading as current; when the period passes, the task is listed
  at session start with how late the review is.
- **An unverified claim is a debt.** A `FAKTI.md` / `FACTS.md` row marked inferred or as an
  unchecked agent's claim is dated by its round heading and reported after thirty days. A row
  verified against a source, or checked locally, is never reported at any age.
- **`/baton-plan`:** two research rounds by default, then execute; every round runs an own-assets
  and a devil's-advocate agent; research ends with a task tree (`DARVO.md`) carrying a priority
  order of branches.
- **First tests.** 15 of them, running the hook as a module.

**v2.1.1**
- **Windows files with a BOM.** Logbooks, `.batonignore` and `settings.json` that start with one (as
  PowerShell 5.1's `Set-Content -Encoding UTF8` writes them) are now read correctly. Before this fix, such a
  logbook lost its header, the first ignore pattern did nothing, and the installer refused to write.
- **Installer output** uses plain hyphens, so a Windows console no longer shows garbled characters.
- **Tested on Windows PowerShell 5.1** (`install.cmd` / `install.ps1`, both hooks, Cyrillic names).

**v2.1.0**
- **`/baton-plan`:** set the goal, then run research rounds with a verifier, then a plan
  built backwards from the goal, with a human checkpoint every round.
- **Installers:** copy every skill in `skills/`.

**v2.0.0**
- **Task header.** A task can record its state, who holds the next move, a completion
  criterion, a deadline, the next action and a priority.
- **SessionStart groups by meaning.** Tasks are grouped by who holds the next move
  (overdue, on us, recurring, waiting, frozen, done) and sorted by priority. The human sees
  the list too (`systemMessage`).
- **`/baton-inventory`.** The installers ship this skill. It maps work that predates Baton
  into task folders, and you confirm each item before anything is written.
- **Fixes.** A waiting task never shows as "on us". An unclosed `---` is not read as a header.
- Header-less logbooks behave exactly as in v1.

**v1.0.0**
- **Task folders and logbooks**, with a SessionStart hook that lists recent tasks and a Stop
  hook that catches unrecorded work (`.batonignore` supported).
- **Installers.** Linux and macOS, plus Windows: `install.cmd`, one-step `setup-windows.cmd`,
  and `tools-windows.cmd` for the dev toolchain.
- **Hooks run without PATH**, and a bundled Python covers Windows machines without one.

## Why this exists

A server had a disk fail. It was diagnosed, the replacement was worked out, and a careful
three-page procedure was written: which disk to pull, which one to leave, the order to shut
down in, what to check afterwards. The remaining disk was the only copy of the data — pull
the wrong one and it is gone.

None of that reached a logbook. The procedure was saved to a desktop already holding sixty
files.

Three days later a session on another machine was asked whether the server could be shut
down remotely. It answered from scratch: no failed disk, no procedure, no idea the mirror
was running without redundancy. The advice it was about to give was wrong. The gap closed
only because the human happened to remember the file existed.

Nothing was missing except a place to write it and a reason to. The work had been done
correctly and reached no one — which, from the next session's side, is the same as not
having been done.

## Configuration

| | |
|---|---|
| `BATON_HOME` | where task folders live (default `~/tasks`) |
| `CLAUDE_CONFIG_DIR` | config directory to install into (default `~/.claude`) |
| `BATON_LOGBOOK` | name of the logbook file (default `LOGBOOK.md`) — set it to a word in your own language if you prefer |
| `OPENROUTER_API_KEY` | only for `tools/baton_pregled.py`; nothing else reads it and nothing else needs it |

`BATON_HOME=~/work ./install.sh` bakes that path into the installed hooks.

## Uninstall

Remove the two `baton_` entries from `~/.claude/settings.json`, delete the Baton section
from `~/.claude/CLAUDE.md`, and remove `~/.claude/baton`, `~/.claude/skills/baton-inventory`, `~/.claude/skills/baton-plan` and
`~/.baton`. Your task folders are plain directories
of plain Markdown — they keep working without any of this, which is the point.

## Not solved here

No syncing between machines. Each machine keeps its own task folders; if you work across
several, put the root on shared storage yourself, and think first about what belongs on it.

No enforcement of quality. The Stop hook can tell that a logbook was not written. It cannot
tell that what was written is any good.

MIT licensed. Issues and pull requests welcome.
