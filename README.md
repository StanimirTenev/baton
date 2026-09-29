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
skills into `~/.claude/skills/` (`baton-inventory`, `baton-plan`, `baton-task`), appends to
`~/.claude/CLAUDE.md`, merges three entries into `~/.claude/settings.json`, and creates
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

### Before any of it: `/baton-task`

Research answers a question; if the question was never stated, it answers the one the agent
assumed. `/baton-task` is the step before: **recognise** that a conversation has become a task
or a decision, **read back** what was already done and decided — the entries on the topic, not
the top one — **formulate** the goal and a criterion someone could check, and only then go
outward (large → `/baton-plan`).

Two hooks hold the checkable half of it, so it does not depend on the agent remembering:
- **UserPromptSubmit** (`baton_prompt.py`): a message that names a task — its folder, or one of
  the `aliases` in its header, in any alphabet, meeting endings halfway (`скенер` finds
  `скенера`) — gets that task's last entry and next step put in front of the agent, with
  "read the logbook first". Once per task per session; silent when nothing is named; never
  blocks a message.
- **Stop**: a task worked on now whose header has no `kriterii_zavarshvane` hands the turn back
  once per session: say when it is done, or ask the human — never invent one.

Measured on the day that made it (2026-09-28), against its three misses: a proposal to redo a
review finished two days earlier (the prompt hook names the task, given an alias); a
conversation that became a decision on priorities without anyone saying so (the Stop hook
asks, once the folder exists; recognising it before that is the skill's job, not a hook's);
and a comment drafted from half a post (a reading rule, out of scope here).

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
Baton — the tasks in /home/you/tasks, ordered by whose move it is and by priority:

⏳ Waiting on YOU / can continue now:
- migrate-billing [visok] — decide tax_region before the run

🔁 Ongoing:
- weekly-report [nisak] — Monday export

⛔ Waiting on someone OUTSIDE / blocked (for information):
- broken-disk [sreden] — zpool replace  (waiting on: new disk (delivery))

❄️ Frozen (not offered): old-scraper

✅ Finished (not touched): schema-audit
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

## The task header

A logbook can open with a small header. It is optional. With a header, SessionStart knows
what the task *means* right now, not only when it was last touched.

```markdown
---
state: active                # active | waiting | ongoing | frozen | finished
turn: us                     # who holds the next move: us, or a name / a condition
done_when: "migration ran, row counts match"   # one sentence a person could check
timing: any                  # any | recurring | YYYY-MM-DD (deadline)
next: "decide tax_region before the run"       # the next concrete action
priority: high               # high | medium | low
skills: [db-migration]       # optional: the skills this task needs (see below)
aliases: [migration, миграция]  # optional: words people use for it, any alphabet (prompt hook)
true_as_of: 2026-03-14       # optional: when this header was last true
review_after: 30d            # optional: how long that is expected to hold (30d, 6m)
deadline: 2026-04-01         # optional: a deadline on its own line, if you prefer it there
code: ~/dev/thing@v1.2.0     # optional: the code this record rests on (path@commit-or-tag)
---
```

`deadline:` and `timing: srok:YYYY-MM-DD` are the same deadline written two ways — the hook
reads either, so a folder can keep the date where it reads best.

| `state` | meaning |
|---|---|
| `active` | in progress |
| `waiting` | waiting on someone or something external |
| `ongoing` | recurring, never finishes |
| `frozen` | parked on purpose; listed, never offered as work (`paused` too) |
| `finished` | done; listed, not touched (`done` too) |

For `turn`, anything other than `us` / `me` / `self` (or empty) counts as "waiting on someone
else". A task waiting on someone never lands in "on us", even with a deadline. Your own name
can mean "us" too: list it under `"us"` in `baton.local.json` next to the hooks.

**The same header in Bulgarian.** Baton began as one person's tool and every field had a
Bulgarian (transliterated) name. They are read forever, so nothing written before v3.0.0 stops
working, and a header may mix the two — where both spellings of one field appear, the Bulgarian
one wins, so a half-translated header never loses what it said.

| English | Bulgarian | values |
|---|---|---|
| `state` | `sastoyanie` | active `aktivna` · waiting `chakashta` · ongoing `postoyanna` · frozen `zamrazena` · finished `priklyuchila` |
| `turn` | `na_hod` | us `nie` |
| `next` | `sledvashto` | |
| `done_when` | `kriterii_zavarshvane` | |
| `timing` | `vremevi_kriterii` | any `po_izbor` · recurring `postoyanno` |
| `priority` | `prioritet` | high `visok` · medium `sreden` · low `nisak` |
| `skills` | `umeniya` | |
| `true_as_of` | `vyarno_kum` | |
| `review_after` | `pregled_sled` | |
| `deadline` | `srok` | |
| `code` | `kod` | |
| `result` (plans) | `rezultat` | open `otvoren` · done `izpalnen` · abandoned `izostaven` |

All three hooks read the header through one parser, and the synonym map lives there
(`FIELD_SYNONYMS`, `VALUE_SYNONYMS`). Until v3.0.0 Stop and the prompt hook each had a reader
of their own, and one of them would have asked an English header for a criterion it already had.

The parser is deliberately small: `key: value` lines, quoted strings, `[a, b]` lists and
trailing ` #` comments. It is not full YAML, so Baton needs no dependencies.

## Skills a task needs

A task folder holds two things: **state** (the header) and **history** (the logbook). It
does not hold the third — *how the work is done here*. The limits that bite, the check that
has to run after the action, the number that must not be cited: that ends up scattered
through entries, and is re-derived by whoever reads them next at the cost of reading the
whole file, or is not derived at all and a paid-for mistake is repeated.

`umeniya: [name, ...]` names what the task needs (`skills:` also works). The session-start
line then carries `⟨skills: …⟩`, and the agent invokes what it needs on entering the task.

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

## A plan that was never closed leaves the task unfinished

A task holding a `PLAN.md` that does not say it is closed is reported **every session**, with no
grace period. Unlike a stale skill this is not a guess about whether something went out of date:
the plan either says it is finished or it does not.

```markdown
---
sastoyanie: izpalnen         # izpalnen (carried out) | izostaven (given up on)
rezultat: "the field went into the schema; the second proposal was dropped"
---
```

**Both endings close it.** `izpalnen` and `izostaven` are different facts, and neither is a
failure of record-keeping — a folder read six weeks later has to say which.

| ending | meaning | also accepted |
|---|---|---|
| `izpalnen` | carried out | `done`, `carried_out` |
| `izostaven` | given up on | `abandoned`, `otkazan` |
| `zatvoren` | closed, without saying which | `closed`, `priklyuchen` — kept for plans closed before the distinction existed |

**Closing requires saying what came of it.** A state with no `rezultat:` is not closed, it is a
tick — and a tick is how a check gets satisfied without the thing behind it being true.
`result:` is accepted too.

**Every plan in the folder counts, not only `PLAN.md`.** The pattern is `PLAN.md` and
`PLAN-*.md`, so a task running two efforts names them apart. ⚠️ Matching one exact filename is
what the check did first, and it missed **this project's own second plan** — the rule held for
the file it was named after and for nothing else. It is not `PLAN*`, so a folder may keep
`PLANOVE-stari.md` as notes without being told it has an unclosed plan.

> This exists because over six weeks one project ran reconnaissance, analysis and planning
> repeatedly and closed a plan **exactly never**. Nothing said so: the task looked active
> because it *was* active, and whether the plan had been carried out never came back.

## The record rests on code, and the code moves

```
kod: ~/dev/qrp-mcp@v0.18.1
kod: /home/me/work/service@8a451d5
```

The Stop hook catches a folder whose **files** are newer than its logbook. `kod:` catches
the other thing, which is quieter and lands harder: the logbook is fine — well written,
quoted at the top of every session — and the **code it describes** has moved on underneath
it.

Twice on one day in this project a memory file claimed v2.8.0 and 132 tests while the tree
stood at v2.13.1 and 194. Nothing about the record looked wrong. It was five releases stale
and perfectly readable, which is the whole problem.

SessionStart resolves the ref and says how far the repository has moved since:

> `- qrp-mcp — `kod:` qrp-mcp is **9** commits after `v0.18.1` (a1b2c3d) — the record describes
> code that has moved underneath it`

A tag, a full sha and a short sha all work. The field is optional and silence means no
opinion: not every task describes code.

⚠️ **Anything it cannot resolve is reported, never skipped.** A path that is not a
repository, a ref that does not exist there, a field with no `@`, a HEAD it could not read,
a commit that is not an ancestor — five different facts, five different lines. A check that
quietly passes on what it could not read is worse than no check, because it is then
trusted.

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
the task appears at session start under **Past its shelf life**, with how late it is. Neither
field is required, and a task without them behaves exactly as it did before.

**An unverified claim is a debt.** If a task keeps a claims register — `TVARDENIYA.md`,
`CLAIMS.md`, `FAKTI.md` or `FACTS.md` — whose rows carry a status column, Baton reads it. A row
marked `I` (inferred) or `A` (an agent's claim, not independently checked) — `И` / `А` also read —
is reported once it is older than 30 days, with the count and the age of the oldest. Rows marked
anything else — checked against a source, or checked on the spot — are never reported, at any age.

A row dates itself when it can — a date, optionally with a time, in **a cell of its own** — and
otherwise takes the date of the heading above it (`## Round 2 — 2026-09-19`). Both, because a
register filled a row at a time over weeks has no meaningful block date, and a table written in
one sitting has no row dates. The date has to be its own cell: matching a date anywhere in the row
read `| last release 0.12.0 (14.08.2026) | A |` as a claim made in August, which is a date inside
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

## Writing the entry

**The time in the heading is read from the clock (`date`), never typed.** On 2026-09-28 the agent
headed six logbooks' newest entries 22:30, 23:40 and "2026-09-29 00:50" at 20:04 by the clock.
Two Stop checks came from that evening, both mechanical:
- **An entry headed later than the clock** (ten minutes' slack) hands the turn back once per
  session: correct the heading. Only the newest entry is checked — it is the one the next
  session trusts.
- **A header edit is not an entry.** Stop used to compare work against the logbook's file time,
  so adding `aliases` to every header made every folder look recorded — Baton's own included,
  the evening the prompt hook shipped. It now remembers the body below the header by hash
  (`baton.bodies.json` next to the hooks); while the body is unchanged, its first-seen time
  stands. Nothing remembered yet means the file time, as before, so a first run raises nothing.


```
python3 tools/baton_entry.py <logbook> <entry-file> [--next NEW --old OLD]
```

The Stop hook demands an entry at the top of the logbook, and until now nothing here helped
write one. So it was done by hand, and doing it by hand went wrong four times in three days.

`"\n".join(lines[:cut]) + entry` does not end in a newline when the file is `---\n## 2026-…`
with no blank line between. The result is `---## 2026-…`: the closing fence disappears, the
front matter stops parsing, and the task drops into the header-less fallback — no state, no
priority, no next move. Three logbooks in one afternoon. It was not spotted by reading them;
they look fine unless you are looking at that one fence. It was spotted by running the
session-start hook afterwards and seeing three tasks appear bare.

A later sweep found four more headings glued to the end of the previous line, in two folders —
invisible to any heading-based read, including the author's own `grep "^## "`.

So the tool inserts before the first dated heading and then checks its own output: the front
matter still parses, no heading is glued anywhere in the file, and the pointer replacement
either happened or failed loudly. `--next` requires `--old`, the old line verbatim: a
pointer that has already moved is a loud failure rather than a silent duplicate.

⚠️ It **warns** rather than refuses when the entry's own heading runs ahead of the system
clock — entries were written hours ahead because the hour was typed from memory. A few hours
can be a timezone, and a helper that refuses a write on a guess gets worked around instead of
fixed.

⚠️ A quotation is not a gluing. A logbook describing this very defect contains the broken
string verbatim, so inline code is stripped before the check. Getting that wrong is how the
first version falsely rejected a real file while nine unit tests passed — see *Versions*.

## The board

```
python3 tools/baton_board.py --out board.html --open
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
python3 tools/baton_review.py --stale          # has a pointer gone stale?
python3 tools/baton_review.py --which <file>    # which claim is unsupported?
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
  "review_index": "~/notes/INDEX.md",
  "review_shortlist": "~/notes/AT-RISK.md",
  "review_confidential": ["client-name", "Client Name", "unreleased-product"]
}
```

| | |
|---|---|
| `review_index` | the index whose pointers get checked — any file with `[title](path.md)` links |
| `review_shortlist` | optional shortlist: only the targets it names are checked, so a long index need not be paid for whole |
| `review_confidential` | substrings that must never leave the machine |

The guard reads the **whole source file**, not the part that gets sent: the question is
whether this document is about confidential matter, not whether the bytes that happened to fit
contained the word. That is deliberately conservative and it costs coverage — on the corpus
here it holds 10 of 19 rows. Holding too much is a list to narrow; holding too little is a
disclosure.

**`review_confidential` is required, and absent is not empty.** With the key missing the tool
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

### `--tasks`: the header against its own logbook

```
python3 tools/baton_review.py --tasks
```

Same shape, different corpus: a header's `sledvashto` and `kriterii_zavarshvane` are pointers,
and the logbook under them is the source. A task marked finished on a criterion its own latest
entry retracted is the same rot as a stale index line — and equally invisible to string
matching. It found exactly that on the first run here.

⚠️ **Measured, and the measurement is not flattering.** On the corpus here: 13 of 19 tasks were
held by the confidentiality guard, because interlinked projects mention each other constantly.
Of the six that ran, five scored above the memory-index threshold — a number that flags almost
everything is an ordering, not a verdict. The largest logbook scored lowest, which suggests the
score partly tracks logbook length rather than staleness; six rows is far too few to say so.

Read what it ranks. Do not carry the threshold here.

### Two questions, opposite amounts of evidence

Measured, and the easiest thing here to get backwards:

| question | evidence | what the other way does |
|---|---|---|
| has the pointer gone stale? | an **extract** (~2600 chars): the head, plus the paragraphs the pointer is about | the whole file drops real cases 0.73 → 0.43 |
| which claim is unsupported? | the **whole file** | an extract gives false ones: 0.02 against 0.97 |

One reason both ways: a summary judgement is diluted by a long text, while a single claim has
its evidence *somewhere* in it — and a cut above that evidence fails the claim innocently.

`--which` caps at 28000 characters and **says so** when it cuts, because below the cut nothing
can support anything and a low score there means "don't know", not "no".

Until v2.16.0 the extract was the first 2600 characters, and that cut is why `--stale` kept
flagging a pointer whose correction was recorded deep in the file: the fix was real, the
extract could not see it. Now the first 1000 characters always go -- these files put what is
true now at the top -- and the rest is filled with the paragraphs sharing the most words with
the pointer, in file order, each gap marked `[…]`. The size stays, because the whole file
dilutes. No paragraph shares a word: the old extract, unchanged.

Retrieval is **by words, not by meaning** -- Baton is stdlib only. Words are cut to five
letters to meet Bulgarian endings halfway, and rare words weigh more than common ones.

Measured on a control of 14 pointers into six real memory files, 12 of them with their
evidence below character 2600, half deliberately made false: **7/14 right before, 13/14
after**; false pointers rose by 0.32 on average, true ones fell by 0.23, and the two whose
evidence is in the head did not move. One false pointer stayed below the threshold in both
versions with the right paragraph in the extract -- that miss is the model's, not the
retrieval's. On the live index the three rows sent moved by at most 0.04. Fourteen rows is a
control, not a calibration: the threshold is still an ordering.

### `--which` takes a task name

`--which` cuts a pointer into separate claims and asks the source about each. Its corpus was
index lines. Measured 2026-09-23 on the index this was built against:

| | before | after |
|---|---|---|
| rows yielding **0** claims | 2 | **13** |
| rows yielding **≥3** claims | **10** | **0** |
| most claims on one row | 4 | 2 |

The index had been compressed on purpose, so that a pointer carries no state. That was
right, and it left this mode without input: **an index that cannot rot is an index `--which`
cannot check.** The two rules are in tension by design, and the tension is worth naming.

Task headers rot by design — that is what `sledvashto` is for — and `--tasks` already asks
the whole-header version of this question against the same logbooks. So `--which <task-name>`
asks it per claim:

```
$ baton_review.py --which qrp-benchmark
🔴 NOT SUPPORTED 0.14  sastoyanie: priklyuchila
🔴 NOT SUPPORTED 0.28  na_hod: nie
🟡 unclear       0.50  kriterii_zavarshvane: benchmark against the paper — done (14/30)
```

`--tasks` had flagged that task at 0.66; this says **which part**. A bare task name that
holds a logbook wins over an index target; an index path still reaches the old mode.

**`sastoyanie` and `na_hod` are not claims here.** Measured by running the mode over all 19
tasks: they came back "not supported" on 6 of 6 reviewed tasks, 0.02–0.13 and 0.07–0.35. The
deciding row is a task with a 42,317-character logbook and 33 entries whose three real claims
scored 0.95, 0.97 and 0.97 — and whose own logbook "does not support" `postoyanna`. A logbook
never writes `sastoyanie: postoyanna`: it is the word that names where the work stands, not
something the entries assert. Twelve of that run's 25 claims were these two fields and every
one was a false positive — the majority of the output, and its most visible part. They stay in
`--tasks`, which reads the whole header together; judging where the work stands is that
mode's job, and naming which claim broke is this one's.

⚠️ `na_hod` sometimes carries a name rather than an enum. That case was not measured
separately — the three thick-logbook rows all read `nie` — so it is excluded with the field,
not on evidence of its own.

**Two things this output says before the numbers, because both change how they read:**

- The 0.4 / 0.7 cutoffs come from the index corpus and have **not** been measured here.
- **"Not supported" means both "contradicted" and "never mentioned."** The criterion the
  model is given merges them, and they are not the same finding: one says the header is
  wrong, the other says the logbook is thin. Found by the positive control — a task whose
  header spoke of a review, a board and a submission came back unsupported on all four
  claims, correctly, because its logbook is 562 characters and mentions none of it. So the
  logbook's size and entry count are printed, and a thin one is named as thin.

⚠️ A logbook is **newest-first**, so the `TSYAL` cut keeps the newest entries — the evidence
a header's currency is judged against. On the index corpus the same cut fell anywhere and
failed claims innocently. Same cut, opposite meaning; the announcement says which.

⚠️ `tvardeniya()` also extracts link text and trigger phrases as "claims"
(`*history:* [sessions and commits](…)`). On the old index those were diluted by real ones; on
the new one they are most of what is left. Flagged, not fixed.

### The grey band: one draw near the threshold is partly a coin flip

Measured 2026-09-23 on 45 pointers, **three identical runs of the same request**. The model
is not deterministic — an independent audit measured 50 identical requests returning 15
distinct answers — so the question was how much that costs here:

| | |
|---|---|
| median spread across 45 rows | **0.010** |
| mean | 0.020 |
| identical in all three runs | 6 of 45 |
| **the two rows whose mean sat between 0.38 and 0.55** | **±0.12 and ±0.09** |

The spread is negligible where the model is confident and **largest exactly where the
decision is made**. The mean hides it: 0.02 sounds calm. One row of the 45 changed sides of
the threshold between identical runs — 0.41 / 0.47 / 0.38 — so it was flagged in one run of
three.

So `--stale` and `--tasks` draw **three times and average** when the first draw lands in
`SIVA = (0.35, 0.60)`, and print the draws next to the mean, because a mean shown alone is
indistinguishable from one draw. Outside the band a second draw buys a hundredth of a point
and is not paid for. On a 45-row index this cost **$0.0040 instead of $0.0034**.

⚠️ `--which` is deliberately left alone: it asks a different question, one claim at a time
against the whole file, and its spread has **not** been measured. Averaging it would carry a
number from one corpus to another — the mistake this feature exists to correct.

⚠️ The band, like the threshold, is measured on **one** corpus. Measure yours.

Two things the same probe measured, worth knowing before trusting the output:

- **The evidence does drive the answer.** Swap the detail file's body for an unrelated
  file's and the value jumps 0.21 → 0.70, ten times the row's own spread. The audit's
  "answers without reading the state" finding does not reproduce for this question shape.
- **An empty body does not raise the number** (0.23 against 0.21). The question catches
  *contradiction with present content*, not *absence of support* — a pointer whose file has
  been emptied or truncated reads as fine.

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
| id | status | file | text |
|----|--------|------|------|
| O1 | falls  | POSITION.md | only this tool separates reading from finding |
| O2 | stands | MEMORY.md   | no commercial product on the research site |
```

Three statuses and nothing else: `falls`, `stands`, `awaits check` (the Bulgarian `пада`,
`остава`, `чака проверка` are read too). The bar for retiring is the bar for asserting — a source or a measurement, never
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

## Where else does this live — and is that place still claiming it?

```
python3 tools/baton_where.py "2500"           # where else does this number appear
python3 tools/baton_where.py "0\.4[0-9]" --regex
python3 tools/baton_where.py --duplicates     # find them without being asked
```

`grep -r` answers *where a string occurs*. The question that actually comes up is a different
one: **which of those places still claim something, and which are only a record of what was
once true.** A price decided in one task and copied into another task's header is a defect. The
same number in an old logbook entry is history.

Baton already draws that line for a person to read; this reads it. A logbook header, a plan and
a memory file are **live**. An entry, a file whose name carries a date, and a row in a claims
register are not — they repeat old values legitimately, and the first version counted them,
which took one query from four live places to seven. The kinds come from
[`baton_corpus`](#the-corpus-and-saying-what-is-in-it), so the two tools cannot drift apart
about what a place is.

### ⚠️ It does not find contradictions. It finds duplicated state.

Whether the duplicates disagree is the reader's call. Put it the other way round and someone
will pronounce a tree "consistent" while the same wrong number sits in six places.

### `--duplicates`, and what it is calibrated against

Numbers living in live places in two or more task folders. Measured over 20 task folders plus a
memory tree — 149 distinct numbers, every hit labelled by hand:

| kind | duplicates | relevant | noise |
|---|---|---|---|
| **money (€)** | 6 | **6** | 0 |
| **percentages with a decimal** (84.8%) | 3 | **3** | 0 |
| thresholds (`0.92`, `0.46`) | 41 | 1 | **40** |
| round percentages (100%, 30%) | 16 | 0 | **16** |
| version numbers (v1.0.0) | 11 | 0 | **11** |

⇒ **A number with a decimal point or a currency sign is a decision. A round number or a version
is shared vocabulary** — it turns up everywhere because it is a word, not a state. `100%`
appeared in nine folders. So the default is money and decimals only, which gave **9 hits and no
false positives**; `--all` restores the rest, which was noise 27 times out of 27.

⚠️ The threshold row exists because the first measurement missed it: that run excluded some
folders and never saw them. **A rate measured on a scope that is not declared is not a rate** —
which is why `Scope` exists at all.

⚠️ One corpus, labelled by its author, on one day. Run it on your own tree, label what it
prints, and move the filter to where it separates yours.

On the corpus it was built against it reported `€2500` in one task's decisions file marked
*decided, 19.09* — and in another task's header dated **26.09**. Seven days between two live
places, and nothing would have said so. It reports the spread in when those places were last
touched, which is the part that says how long they have disagreed.

## Reading order for a long list

```
baton_sift.py --question "Does this repository ship a CBOM generator?" < candidates.tsv
baton_sift.py --question "..." --threshold 0.5 --out scores.tsv < candidates.tsv
```

A research pass reads hundreds of candidates and judges each one expensively. Measured here
on 2026-09-26: one run paged 300 code-search hits and de-duplicated them by hand, another
filtered 935 + 576 arXiv entries with a title regex. `tools/baton_sift.py` scores the same
list once with the calibrated classifier `baton_review` already talks to, and puts the
worthwhile ones first. Input is TSV on stdin — an id in column one, everything else is what
gets judged.

Measured on a real triage: 40 GitHub repositories, hand-labelled **before** the scores were
seen, question "does this ship a tool that produces a cryptographic inventory".

| | |
|---|---|
| cost | **$0.00069** for 40 |
| false positives among the 11 hand-labelled *no* | **0 at every threshold** — the highest *no* scored 0.49 |
| medians | yes **0.84** · no **0.19** · undecidable-from-the-input 0.36 |
| ⭐ the actual win | sorted by score, **all 21 yeses were in the top 25 of 40** |

⚠️ Of the three disagreements, **two were the labeller's fault**: one repository's only CBOM
file was a frontend graph component, another had none at all. The third was a real limit of
the input — a repository whose description does not say what it does — and no scorer fixes
that.

### ⛔ Reading order, not a right of exclusion

Nothing is dropped, ever. `--threshold` splits the list into **read first** and **read after**,
and prints both with counts. The threshold travels in the output for the same reason a
coverage figure travels with its denominator, and the report says in as many words that a
candidate below the line is one nobody has read yet.

This is not fastidiousness. The failure it prevents was made four times in one day here: a
search reported as "found X" where the truth was "did not look at the rest". A scorer used
as a filter makes the unread invisible, and **an absence written without the check that
would find it** is the defect this project exists to refuse.

### ⚠️ It scores a question; it does not tell you the question is wrong

Every mistake made here that day was in the framing — a regex too narrow to match
`DHE_RSA`, an evidence window that hid 59% of the text, a category asserted from an
unvalidated pattern, a baseline two dozen versions stale. A classifier would have answered
each of those confidently and uselessly. Use it to order reading and to cross-check a claim
against a document; not to decide what the claim should be.

⚠️ Measured on one kind of candidate, n=40. A threshold does not transfer — measure it again
on arXiv rows or code hits, the same way `baton-pregled` says.

## The corpus, and saying what is in it

Two questions come up in every tool that reads a whole tree of task folders: **which files
are part of the corpus**, and **what kind of place is this passage** — something that claims
a thing now, or a record of what was once true. `tools/baton_corpus.py` is the one owner of
both.

```python
from baton_corpus import Scope, chunks, kind, walk

scope = Scope(["docs", "sdks", "*/vendor/*"])      # what is OUTSIDE the corpus
for text, source, what in chunks([home], scope, "LOGBOOK.md"):
    ...                                            # what ∈ LIVE HEADER RECORD SNAPSHOT CLAIM
```

A logbook arrives as its header plus one chunk per entry; a claims register as one chunk per
row; anything else split on its headings, with a dated filename marking the whole file a
snapshot. `--duplicates` in `tools/baton_where.py` uses the same `kind()`, so the two cannot
drift apart about what a place is.

### `Scope(None)` raises, and that is the feature

An empty scope is allowed — `Scope([])` — but it has to be written down. The reason is
measured, twice in one day:

| | what an undeclared scope did |
|---|---|
| a duplicate-state prototype silently skipped one subtree | the same corpus went from **9 hits to 100** once it was scoped properly, and the false-positive rate with it |
| a corpus built for detection declared nothing | **805 of 1167 live passages (69%)** turned out to be imported comparison fixtures and vendored SDKs. Two of three detectors sat near 50% false positives, and the corpus was the reason |

**A rate measured on a scope nobody declared is not a rate.** `Scope.describe()` returns that
scope as one line, so a number can be quoted together with what it was measured over.

### ⚠️ `.batonignore` answers a different question

`.batonignore` means *"do not demand a logbook entry for this"*. It does not mean *"this is
not my writing"*. They overlap — raw agent output is both — and they diverge: a task that
ignores its live transcripts for the Stop hook has those transcripts as its actual work.

It is honoured by `Scope` because the duplicate-state calibration was measured with it
honoured, and dropping it would invalidate that measurement. It is not a substitute for
declaring what is outside.

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

**Names before v3.1.0.** The tools, their flags and the review's settings had Bulgarian names.
They all still work: `baton_pregled` → `baton_review`, `baton_kade` → `baton_where`,
`baton_tablo` → `baton_board`, `baton_vpishi` → `baton_entry`, `baton_otsey` → `baton_sift`,
`baton_korpus` → `baton_corpus` (the old files run the new ones); `--dali`/`--koe`/`--zadachi` →
`--stale`/`--which`/`--tasks`; `pregled_indeks`/`pregled_podbor`/`pregled_poveritelni` →
`review_index`/`review_shortlist`/`review_confidential`.

## Versions

**v3.2.0** — English is canonical inside the code too

- The header parser now maps every Bulgarian spelling -- transliterated or Cyrillic -- to the
  English field and value on reading (`FIELD_SYNONYMS`, `VALUE_SYNONYMS`), and the hooks and
  tools test only the English words. Before, the code tested the Bulgarian words and mapped
  English to them; the sets of accepted spellings were scattered through three files.
- The board's own list of finished words did not know `finished`; a finished task would have
  shown as live. Caught by hand, fixed, and pinned by a test.
- A regression caught before release: the "waiting on" name read the old key in single quotes,
  which a search for double-quoted keys missed; every outside task said "waiting on: None".
  The cross-language test compared the English board with the Bulgarian one, and both said None.
  It now also checks the name.
- On the author's 22 Bulgarian headers the board is identical, apart from a plan's state now
  shown as `open`.

**v3.1.0** — the tools and their flags speak English; the old names still run

- `baton_review` (was `baton_pregled`), `baton_where` (`baton_kade`), `baton_board`
  (`baton_tablo`), `baton_entry` (`baton_vpishi`), `baton_sift` (`baton_otsey`), `baton_corpus`
  (`baton_korpus`). The old files remain and run the new ones in their own namespace, so a
  script that loads them by path -- as a corpus labeller on the author's machine does -- or a
  test that monkeypatches them behaves exactly as before.
- Flags: `--stale` `--which` `--tasks` (review), `--next` `--old` (entry), `--question`
  `--threshold` `--out` (sift); the Bulgarian ones are aliases.
- Settings: `review_index`, `review_shortlist`, `review_confidential` and `BATON_REVIEW_*`;
  the `pregled_*` keys and `BATON_PREGLED_*` are still read.
- The documentation test knows a shim from a tool: each old name must run a tool that exists
  and be named in the README.
- Checked: 271 -> 274 tests x3; three scripts outside the repository that load the old files
  by path were run and work.

**v3.0.0** — the header speaks English; every Bulgarian header still works

- Header fields and values have English names: `state`, `turn`, `next`, `done_when`, `timing`,
  `priority`, `skills`, `true_as_of`, `review_after`, `deadline`, `code`, plan `result`;
  `active / waiting / ongoing / frozen / finished`, `us`, `high / medium / low`, `any / recurring`,
  plan `open / done / abandoned`. The Bulgarian names are read forever; see "The task header".
- One parser for all three hooks. Stop and the prompt hook each had a reader of their own; one
  would have asked an English header for a criterion it already had. A test runs the same task
  headed in English and in Bulgarian through all three and requires the same result.
- `done` is deliberately not mapped: tasks and plans share the state field, and both already
  accept `done` with their own meaning. Mapping it (the first attempt) broke finished tasks.
- A user's own name meaning "us" moves from the code to `"us"` in `baton.local.json`.
- The board shows priority in English whichever spelling the header used.
- Checked: on the author's 22 Bulgarian headers the board is identical apart from the field names
  quoted in messages; in a Windows sandbox all three hooks read an English header.

**v2.18.0** — Baton speaks English (stage A of four)

- Every message the hooks and tools print — the session-start board, the Stop notes, the review,
  the HTML board (`lang="en"`) — is now in English. The agent still answers in the human's
  language; the hooks are read by the agent, not by the human.
- The README examples and both skills match the new output. Claim statuses gain English letters
  (`S`, `L`, `A`, `I`); `П`, `В`, `А`, `И` are still read.
- Nothing a user has written stops working: header fields and values are unchanged in this
  release (English names arrive in v3.0.0, with the Bulgarian ones kept as synonyms).
- A client's name used as the example of a confidential word in three test files is replaced
  with a neutral one. It remains in two older commits of the history.

**v2.15.0** — the record rests on code, and the code moves

- **`kod: <path>@<commit-or-tag>`** in a task header. SessionStart resolves the ref and says
  how far the repository has moved since — a tag, a full sha and a short sha all work, and
  silence means no opinion, because not every task describes code.
- The Stop hook catches a folder whose **files** are newer than its logbook. This catches the
  other thing: the logbook is fine, well written, quoted at the top of every session, and the
  **code it describes** has moved underneath it. Twice on 2026-09-26 a memory file here
  claimed v2.8.0 and 132 tests while the tree stood at v2.13.1 and 194 — five releases stale
  and perfectly readable.
- ⚠️ **Five things it cannot resolve are five different lines**: a path that is not a
  repository, a ref that does not exist there, a field with no `@`, a HEAD it could not read,
  and a commit that is not an ancestor. A check that quietly passes on what it could not read
  is worse than no check, because it is then trusted.
- ⚠️ One of the five tests passed a mutation that deleted the repository check, because it
  asserted only that *something* came back — and the git call then produced the "ref not
  found" line instead. Two different facts a reader acts on differently. The test now asserts
  the reason.
- From a product note asking for records "linked to the actual files and results". Everything
  else that note proposed already existed here; this was the one new thing in it.

**v2.16.0** — `--dali` shows the model the part of the file the pointer is about

- The extract was the first 2600 characters. A pointer corrected deep in its file kept
  lighting (0.77 after the fix, 2026-09-23), because the evidence was never sent. Now: the
  head, plus the paragraphs sharing the most words with the pointer, within the same 2600.
- Control, 14 pointers, 12 with evidence below the old cut: 7/14 → 13/14. A true pointer the
  old cut flagged at 0.76 now reads 0.19. Live index: at most 0.04 movement.
- Lexical, stdlib only. The confidentiality barrier still reads the whole file, not the
  extract. `--koe` and `--zadachi` are unchanged: their cuts keep the newest entries.

**v2.15.1** — a sha ref printed twice

- `after \`7374660\` (7374660)` read as a stutter when the ref and the commit it resolves to
  are the same string. A tag still gets both, because there the second half says something.
- Applied to four real tasks on this machine. Three are silent; one reports three commits of
  drift, correctly — that task's last entry is from 23 September and two releases have shipped
  since.

**v2.14.1** — six findings from an external review, four of them reproduced first

- 🔴 **The confidentiality barrier read half of what it sent.** `pitay` checked `state` and
  the label; the body it builds also carries `questions`, and never looked there. Reproduced
  with a replaced `urlopen`: a term present only in a question arrived in 272 bytes of
  outgoing JSON. It bit through `baton_otsey`, shipped the night before, which puts the
  caller's `--vapros` straight into that field. The check now reads the serialised body,
  whole, and `otsey` refuses a confidential question once, up front.
- 🔴 **A reinstall took the confidentiality list with it.** The installer wrote
  `baton.local.json` from scratch with `home` and `logbook`, so `pregled_poveritelni`,
  `pregled_indeks` and `source` disappeared on a second run — and it did that *before*
  validating `settings.json`, so a broken settings file returned 1 with the config already
  gone. `baton_pregled` stops when that list is missing, so a silent reinstall turned the
  review tool off. Now: read and validate everything first, merge only the two owned fields,
  replace atomically.
- 🔴 **`vpishi` wrote before it validated**, so a rejected entry was already on disk; it
  searched `staro` in the whole file, so a pointer surviving only in an old entry was
  rewritten — editing the record, which is never edited; and every barrier was an `assert`,
  stripped by `python -O`. Now: header-only and exactly once, built in memory, `ValueError`
  rather than `assert`, atomic replace.
- 🔴 **The Stop hook's grace was measured against the wrong thing.** `work > logged + 90`
  meant a file saved thirty seconds after its logbook could **never** be reported, however
  long it sat, while an old file two minutes newer stopped unrelated sessions forever. The
  hook's own comment says "a file saved moments ago is still being worked on" — a grace
  against *now*. The code had drifted from the sentence above it. **`tests/test_stop.py` is
  new**: the hook had no test file of its own.
- **A finished task hid an open plan.** `sastoyanie: priklyuchila` hit `continue` seventeen
  lines before `open_plan` was called. The plan check now runs before the status branch and
  says both facts, because finishing the task in the header does not close the plan.
- **Windows**: `-DryRun` pointed at a copy it had just decided not to make, and
  `setup-windows.cmd` printed `Done.` whatever the installer returned. ⚠️ Fixed from a static
  read; **not executed** — no PowerShell on this machine, and the review found them the same
  way.
- ⚠️ One defect of my own on the way: a test double whose `poveritelno` read the identifier
  and not the text, so a test about a confidential question passed against the fake and would
  have failed against the real barrier.

**v2.14.0** — reading order for a long list

- **`tools/baton_otsey.py`** scores a candidate list once with the calibrated classifier
  `baton_pregled` already talks to, and puts the worthwhile ones first. Measured on 40
  hand-labelled GitHub repositories: **$0.00069**, **0 false positives** among the eleven
  labelled *no* at every threshold, and **all 21 yeses inside the top 25** once sorted.
- ⛔ **Nothing is dropped.** `--prag` splits into *read first* and *read after* and prints
  both, with counts; the threshold travels in the output and the report states that a low
  score means unread, not absent. The failure that motivates it was made four times in one
  day here — a search reported as "found X" where the truth was "did not look at the rest".
- The confidentiality barrier holds: a confidential candidate is never sent, is marked, and
  still appears in the list.
- ⚠️ Two of the three disagreements in that run were the **labeller's** fault, not the
  model's. The third was a description that does not say what the repository does, which no
  scorer fixes.
- ⚠️ It scores a well-posed question and does not tell you the question is wrong. Every
  mistake made here that day was in the framing.
- `test_documented.py`, shipped in v2.13.2, caught this tool's missing README section on the
  first full run. That is the whole reason it exists.

**v2.13.2** — a changelog is not documentation, and now a test says so

- **Three features existed only under `## Versions`.** `tools/baton_kade.py` (v2.12.0), the
  header fields `srok` and `rezultat`, and the whole **unclosed-plan check** (v2.6.0) — a thing
  SessionStart prints a dedicated section about — had no body section at all. Each now has one,
  including the accepted spellings of a closed plan (`carried_out`, `otkazan`, `zatvoren`),
  which were read by the hook and named nowhere a reader would look.
- **`tests/test_documented.py` checks it structurally.** Every `tools/baton_*.py` must be shown
  being used inside a fenced code block in the body; every header field the hooks read, and
  every plan state they accept, must be named there. Fields and states are extracted from the
  hooks, so a new one cannot be added unnoticed.
- ⚠️ That test's first version passed a mutation that deleted an entire section, because the
  file name is mentioned in passing elsewhere. **A name in a sentence is not documentation.**
  The bar is a code block.
- All 21 tags now have a GitHub release. Thirteen versions had been tagged and pushed while the
  releases page still offered **v2.1.1 from 17.09** as the latest — `feedback_publikuvane_ne_e_stigane`
  in its plainest form: a release in git is not a release in anybody's hands.

**v2.13.1** — three defects in v2.13.0, all found by looking at real output rather than at a green suite

- 🔴 **Every chunk of a file with YAML front matter came back `HEADER`.** `chunks()` asked
  `kind()` once per file at position 0, and front matter starts with `---`. On a real tree
  that was **478 of 1821 chunks**, where about twenty logbooks exist; after the fix, **85**.
  `kind()` is now asked at each chunk's real offset, which is also what makes this and
  `--duplicates` unable to disagree.
- 🔴 **A chunk starting exactly at `## 2026-…` was `LIVE`, not `RECORD`.** `kind()` compared
  `m.start() < position`, so an entry's own heading had no entry before it. A search for a
  number inside a line never reaches that offset, so nothing failed until chunks did. An
  entry's heading is part of that entry: `<=`.
- 🔴 **`baton_tablo.py` printed "no tasks under ~/tasks" on any machine configured
  elsewhere** — it loads the SessionStart hook out of the repository, and `config()` reads
  the file beside its own `__file__`, while `baton.local.json` deliberately lives outside git
  because it names client folders. There were **three readers of that one file in three
  different orders**; `baton_korpus.config()` is now the only one, installed copy first,
  environment over both.
- Front matter is a chunk whatever its length. A memory file's `description:` is a live claim
  and is routinely under the stub floor, so a length test dropped exactly the claims most
  worth finding.
- ⚠️ Two of the new tests passed for the wrong reason and were caught by mutation, not by
  review: the config-precedence test created only one of the two files, so reverting the order
  still passed; and nothing covered the board's call site, so reverting it broke the board
  silently. Both now fail when the fix is reverted.

**v2.13.0**
- **`tools/baton_korpus.py` — one owner for the corpus walk and the five kinds.** The
  LIVE/HEADER/RECORD/SNAPSHOT/CLAIM distinction was declared twice, here and in a corpus
  builder outside the repository, with two sets of regular expressions. Nothing had broken —
  which is how a duplicate rots: one copy gets fixed, both keep returning something
  plausible. `test_kind_has_exactly_one_owner` asserts the same function *object*, not that
  the two agree.
- ⚠️ Found while writing that test: `baton_kade.py` loaded its own fresh copy of the module,
  so two owners sat in memory and the assert failed. That is Baton's oldest lesson in
  miniature — **the hooks run from copies**, and v2.2.0 was tested and tagged while a
  two-day-old copy did the work. A single owner loaded twice is two owners.
- **`Scope` refuses to be constructed from `None`.** Measured: an undeclared exclusion took
  one corpus from 9 duplicate hits to 100; an undeclared *inclusion* put **805 of 1167 live
  passages (69%)** of imported fixtures and vendored SDKs into a detection corpus, and two of
  three detectors sat near 50% false positives because of it. `Scope([])` is allowed and means
  everything — a decision, made out loud. `Scope.describe()` prints it so a number can be
  quoted with its scope.
- `.batonignore` is honoured, and the README now says plainly that it answers a **different
  question** — "do not demand a logbook entry", not "this is not my writing".
- All four new guards were mutation-checked: each one reverted individually makes a test fail.
- ⚠️ Not documented in the body: `tools/baton_kade.py` shipped in v2.12.0 with its description
  only in this changelog. A changelog is not documentation.

**v2.12.1**
- **`chaka` removed from the header fields the review reads.** It sat in `HEADER_CLAIMS` and
  was read on every `--koe` and `--zadachi` run. Measured across every task on one machine:
  **not one used it.** A field nobody fills is not a field, it is a line that makes the header
  look richer than it is.
- It was found by the opposite of a feature: an edge type was proposed, measured before being
  built, and the measurement killed it — three task-to-task edges of which one pointed at a
  skill rather than a task, and no external party holding more than one task. The dead field
  turned up on the way.
- ⚠️ **`chakashta` is a different thing** — a value of `sastoyanie`, in active use, untouched.

**v2.12.0**
- **`tools/baton_kade.py` — where else does this live, and is that place still claiming it.**
  `grep` says where a string occurs; this says which of those places still *claim* it. A
  logbook header, a plan and a memory file are live. An entry, a file whose name carries a
  date, and a row in a claims register are not — they repeat old values legitimately, and the
  first version counted them, which took one query from four live places to seven.
- **`--duplicates` finds them unprompted:** numbers living in live places across two or more
  task folders. On the corpus it was built against it reported a price decided in one task on
  the 19th and reaching another task's header on the 26th — seven days, and nothing would have
  said so.
- **Calibrated, and the calibration moved once.** Over 20 task folders plus a memory tree,
  every hit labelled by hand: money 6/6 relevant, decimal percentages 3/3, round percentages
  0/16, versions 0/11, thresholds `0.xx` **1/41**. The default keeps money and decimals — 9
  hits, no false positives. `--all` restores the rest.
- ⚠️ **The threshold row exists because the first measurement was wrong about its own scope.**
  That run silently skipped folders; honouring `.batonignore` instead — the file the Stop hook
  already reads — took the same tree from 100 duplicates to 50, and then dropping thresholds
  to 9. A rate measured on a scope nobody declared is not a rate.
- ⚠️ **It does not find contradictions. It finds duplicated state.** Whether the duplicates
  disagree is the reader's call — otherwise someone pronounces a tree consistent while the
  same wrong number sits in six places.

**v2.11.0**
- **`tools/baton_vpishi.py` — write the entry the Stop hook asks for, without breaking the
  file.** The hook demanded an entry and nothing helped produce one; by hand it broke three
  front matters in an afternoon and glued four headings that no heading-based read could see.
  The tool inserts before the first dated heading and then verifies its own output.
- **Half a pointer replacement now fails.** Passing a new `sledvashto` without the old line was
  skipped in silence: the entry landed, the pointer kept its old text, and nothing said so.
  Both or neither.
- **An hour ahead of the clock warns, and still writes.** A few hours can be a timezone.
- ⚠️ **Found by positive control, not by review.** The first fix stripped double-backtick spans
  with ``` ``[^`]*`` ```, which does not pass through the single backticks such a span exists to
  contain. Nine unit tests passed while the tool rejected a real logbook that was quoting this
  defect correctly. The fixture in the test is that line.
- ⚠️ **And one test passed for the wrong reason.** The clock-warning test asserted `"ahead"`
  against captured output — and pytest's `tmp_path` is named after the test, so the word was in
  the printed path. It passed with the warning disabled. Mutation testing caught it; the unit
  test did not. It now asserts the warning's own wording.
- A redundant `^---##` assert survived every mutation, which meant no test pinned it. The
  general check covers the same input, so it was removed rather than kept as decoration.

**v2.10.1**
- **`sastoyanie` and `na_hod` are not `--koe` claims.** Running the mode over all 19 tasks
  showed them coming back "not supported" on 6 of 6, including a task with a 42K logbook whose
  other claims scored 0.95–0.97. They are control words: a logbook never writes them, so asking
  whether the entries support them asks for something that cannot be supported. Twelve of the
  run's 25 claims were these two, all false. Reviewing a healthy task now flags nothing instead
  of two rows.
- They remain in `--zadachi`, unchanged and pinned by a test.
- Found by running it, not by reading it. The field list was written in v2.10.0 with a comment
  saying a short field is still an assertion the logbook can contradict. It is not.

**v2.10.0**
- **`--koe` takes a task name.** Its old corpus is gone: 0 of 45 index rows now yield three
  claims and 13 yield none, because the index was compressed so that a pointer carries no
  state. An index that cannot rot is an index `--koe` cannot check. Task headers rot by
  design, so the corpus moves and the question stays. `--zadachi` says a header no longer
  matches; this says which claim.
- Each header field is a claim, and `sledvashto` is usually two. A field too short to be a
  sentence is its own claim; a dash is not.
- **Found by the positive control, not by review:** "not supported" covers both
  *contradicted* and *never mentioned*, and a thin logbook makes every claim look wrong. The
  output now says so, and prints the logbook's size and entry count.
- The cut means the opposite here: logbooks are newest-first, so it keeps the newest entries.
- **What this does not change:** the index mode is untouched, no threshold moved, and `--koe`
  still draws once — the 0.7 edge has not been measured for flips, so it gets no grey band.

**v2.9.0**
- **The grey band: three draws averaged near the threshold.** `--dali` and `--zadachi` draw
  once, and three times averaged when the first draw lands in 0.35–0.60. Measured, not
  assumed: three identical runs over 45 pointers put the median spread at 0.010 and the two
  rows nearest the threshold at ±0.12 and ±0.09 — steady where the model is sure, unsteady
  where it is asked to decide. One row of 45 changed sides between identical runs.
- The draws are printed beside the mean. A mean shown alone looks exactly like a single draw,
  and on the rows that land in the band the spread *is* the finding.
- The ledger counts every draw, not every row: what left the machine is three requests.
- **What this does not change:** no threshold moved, nothing is rewritten because a number was
  high, and `--koe` is untouched because its spread has not been measured. The extra draws cost
  about 15% more on a 45-row index.
- Retired by measurement: the README previously said everything ≥0.47 turned out real and
  everything ≤0.45 false. That is a 0.02 separation, inside a spread of 0.09–0.12 in exactly
  that region. The number stays as an **ordering**; the sharp edge is gone.

**v2.8.0**
- **`--zadachi`: every task header against its own logbook.** A header's `sledvashto` and
  `kriterii_zavarshvane` are pointers and the logbook under them is the source, so the same
  question applies. On its first run here it found a task marked *finished*, on a criterion its
  own latest entry had retracted — listed as done in every session since.
- The measurement is in the README next to the feature, and it is not flattering: 13 of 19 tasks
  held by the guard, five of the remaining six above a threshold measured elsewhere. An ordering
  to read, not a number to trust.
- Fixed while building it: the mode took the logbook's *name* from a second config read, found no
  logbooks at all, and reported a clean run costing $0. A check that finds nothing looks exactly
  like a check that found nothing wrong.

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
  session-start line carries `⟨skills: …⟩`. A folder already holds state and history; this is
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
