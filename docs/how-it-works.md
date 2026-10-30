# How it works

Part of the [Baton](../README.md) documentation.

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
priority. You see one English line at once (`🧭 Baton: 8 on your move, ...`); the list itself
goes to the agent, which opens its first reply with it -- whatever you write first -- translated
into your language, every group and every line. The hook does not know your language; the agent does.
What the agent gets:

```
[baton:board v3.29.0]
Baton — the tasks in /home/you/tasks, ordered by whose move it is and by priority:

⏳ Waiting on YOU / can continue now:
- 1 · migrate-billing 🔴 [high] — decide tax_region before the run

🔁 Ongoing:
- 2 · weekly-report 🟢 [low] — Monday export

⛔ Waiting on someone OUTSIDE / blocked (for information):
- 3 · broken-disk 🟡 [medium] — zpool replace  (waiting on: new disk (delivery))

❄️ Frozen (not offered): 4 · old-scraper

✅ Finished (not touched): 5 · schema-audit

(The number before a task is its own and stays: name a task by it -- "12 is finished", "go to 12".)
```

The groups mean overdue (a deadline within 3 days), on us, recurring, waiting on someone
else, frozen and done. A task with no header falls back to the v1 line: its name, the date
of its last entry, and that entry's title.

The number before each task is its own: the human can say "12 is finished" or "go to 12", and
the UserPromptSubmit hook brings that task's record as if it had been named. The numbers live in
`.baton-ids.json` at the tasks root, not in the headers. SessionStart numbers a new task max + 1
(the first time, in the board's order); a number is never changed or reused, and a renamed
folder is a new task with a new number. A bare number counts only as the first word of a
message, or the last of a short one; `#12`, `№12`, `task 12` anywhere. A version, a date or a
time (`3.27.0`, `17.10`, `10:30`) names no task.

Every task is on the board with its `next:` (or `done_when:`), including one whose name or text
holds a word from `review_confidential`: that list keeps text from being sent by the review
tools, and the hooks do not read it. Shown on purpose (decided 2026-10-22, ZA-OPRAVYANE row 66).

> The board is written in English and shown to you in your language by the agent. Header
> fields and values are English; the Bulgarian names Baton started with are still read
> (see *The same header in Bulgarian* below).

**Stop** checks whether any task folder holds a file newer than its `LOGBOOK.md`. If one
does, and that file was saved during this session (after the first timestamp of its
transcript), the turn is handed back with a note naming it. The test is deliberately narrow:
a session that touched no task folder is never interrupted (the next session start sets its
messages beside the entries written then -- see *A session that touched no task folder*), and
a turn whose hand-back produced no new entry is handed back once more and then let through --
at most two per turn, by Baton's own count kept with `stop_hook_active` (since v3.29.0,
ZA-OPRAVYANE row 115; until then it was one, Baton's choice and not a limit of Claude Code, whose
cap is 8 consecutive continuations, reset by each tool call); what came of each
hand-back is counted (see `/baton-doctor`). The entry written in answer to a hand-back gets the
same quality checks as any other -- hollow, L1, L3, L4 -- on that second pass, said to the human
in one message (`systemMessage`) and never handed back again (since v3.22.0, ZA-OPRAVYANE row 55: it was the one
entry nothing checked). Older unrecorded work — from a session that ended
without its entry — is listed on the board under 📝 instead of stopping every session after
it. Without a readable transcript Stop falls back to every folder, as before v3.10.1; a resumed
session counts from its original start.

**An entry that exists is not an entry that says anything.** Since v3.16.0, when this session
changed a logbook's body, Stop also reads its newest entry and hands the turn back once per entry
if it looks hollow. It measures two things and judges nothing: the entry has at least three `###`
sections, each with text, and 200 characters or more; and it names at least one of the files
saved in the folder this session -- by name, stem, or a folder it sits in -- anywhere in this
session's entries. A conversation that touched no file is not asked to name one -- but since
v3.23.0 (ZA-OPRAVYANE row 76, after Kyle Bartlett) it is asked when its entry says it changed a
file of the folder ("Rewrote parse_date() in parser.py": the file's full name on a line with a verb
of change -- wrote, fixed, changed, updated, added, removed..., or the Bulgarian ones) and no file
of the folder was saved this session; on the author's 36 top entries, none was asked. A change
made in another repository is said in one line. **What it does not catch:** an entry with the right shape that is wrong. A full entry saying a repository was
public when it was private passes; that one was caught by a person, two hours later. Over the
logbooks on the author's machine in the ten days before release, seven top entries would have
been asked about -- short notes without sections; the agent answers in one line when one is
right as it stands.

**A claim about what is public or private is put where it gets read.** Since v3.18.0, when the
newest entry this session wrote says something is public or private -- `public`, `private`,
`publicly`, `privately`, and the Bulgarian `публичен`/`публично`/`частен`/`частно` with their
endings -- and does not open with a section for it, Stop hands the turn back once per entry and
asks for one: `### Claims to verify` (or `### За проверка`) as the **first** `###` section, one
line per claim, each checked against the source (the repository's or the page's own visibility
setting). The human reads that section instead of the prose. Adding it to the newest
entry is completing the top entry, not rewriting an older one. Not counted as a claim: a word
inside inline code (`"visibility":"PRIVATE"` pasted from a tool), a key in
cryptography (`private key`, `публичен ключ`), one word in quotes (the word talked about,
not used), and the pair named as a topic (`public/private`). "Said publicly" is left in: a
promise made in a public comment is a claim about where something is, and a list of verbs to
exclude would be fitted to one machine.

It came from the entry that motivated v3.16.0: "`gh` says StanimirTenev/market-swarm is PUBLIC",
in an entry with every section, about a repository that was private and always had been. A reader
proposed a short section of claims to verify at the top of each entry; asked for on every entry
it would be a form -- a version or a URL is in up to four entries in ten (measured 20 October) --
while a mention of visibility is in about one in eight. **What it measures:** how often the situation arises
(`fired`, lesson L3 below) and how often a listed claim proved wrong (`caught`). **What it
cannot do:** tell whether the claim is true. It puts the claim in front of a reader; a wrong
claim listed in the section passes until someone checks it. Over copies of the 34 logbooks on
the author's machine: 21 of the 195 entries since 10 October would have been asked about (165 of
1,274 in all). Read one by one, 11 of the 21 state what a repository or a page is; 5 are
borderline (a reply labelled public, twice; a note to write about something publicly; a
project required to be public; one more of the kind); 5 use the word in another sense -- public sources, public data, public contracting
authorities -- and are answered in one line.

**A claim that tests pass is listed with the command that showed it** (since v3.20.0, lesson L4
below). The same section, the same once-per-entry ask, for "tests pass", "all green", "N passed"
and „тестовете минават/минаха“: one line with the command and the result line it printed. An entry
that said "did not run pytest … All tests pass." had the right shape and passed the check above;
now it is asked about. It cannot tell a true claim from a false one either. Since v3.21.0 "5/5
passes" is read as the claim too (N/N only: "3/5 passed" is a run that failed). Since v3.22.0 the
plain sentence too -- "tests are passing", "the suite passes", "CI is green", „тестове минават“
without the article, „тестовете преминаха / са зелени“ (row 60) -- and every entry the session
wrote is read, not only the top one: a claim with a clean entry written above it was never asked
(row 59; the same for L3).

**A pinned test command sets the actual result beside the claim** (since v3.21.0, ZA-OPRAVYANE
row 43, after Apurv Khare: "tests pass" should come from a hook that re-runs them). The listed
line above is the agent's word: a made-up `pytest -q: 12 passed` passes it. So a human can pin
the command once, per task folder, in `baton.local.json` (the plugin's data folder, or next to
the script-installed hooks):

```json
{"tests": {"my-task": {"command": "python3 -m pytest -q tests", "cwd": "~/src/my-repo", "timeout_s": 600}}}
```

`my-task` is the task folder's name; `cwd` defaults to the task folder, `timeout_s` to 600,
`env` (a list of variable names to pass on) to none. When
the newest entry this session wrote in that folder says tests pass, Stop starts the pinned
command **in the background, after the turn** -- detached, its output to
`baton.tests.<folder>.log` next to the settings, under its own budget -- and returns at once; it
says so to the human in one line. Once per entry, one run at a time per folder. The verdict is
**what the runner printed, then its exit code** (since v3.23.0, ZA-OPRAVYANE rows 74, 75; it was
the exit code alone): **no tests ran** when the output says so -- pytest's "no tests ran"
(`-k` that matches nothing), unittest's "NO TESTS RAN" / "Ran 0 tests", jest's "No tests found",
vitest's "No test files found", and `go test` when every package is `[no test files]` or
`[no tests to run]` -- whatever the code (`go test` exits 0 there, jest 1); otherwise 0 passed,
any other code failed; over the budget, timed out (the process group is killed); a `cwd` that is
not there, could not start. Another runner that exits 0 having run nothing is still "passed": the
output is read for these runners' sentences only. **A pass is not "passed" when the failing test was set
aside** (since v3.23.0, row 77): the runner keeps how many tests ran and how many were skipped or
xfailed (pytest's summary, unittest's `Ran N tests` and `OK (skipped=N)`, jest's `Tests:` line,
`go test -v`'s `--- SKIP`), and compares them with the **last run of the same command**: fewer
tests is "passed, with N fewer tests than the last run"; more skipped or xfailed, "passed, with N
skipped or xfailed". Both are said as "could not say", not as caught. The first run has nothing to
compare with: a skip is said, a test deleted before it is not seen. And **test files saved since
the session began** in the pin's folder (`test_*.py`, `*_test.py`, `*_test.go`, `conftest.py`,
`*.test.js`, `*.spec.ts`...) are named beside the result (row 52, after Martin Gonella): a pass
after the expected value was rewritten shows the tests as they now stand, not the claim. The record
(`baton.tests.<folder>.json`) keeps the command, the folder it ran in, the exit code, the
duration and the last line it printed. The next Stop says the result beside the claim, once, in a
message the agent does not write; if the session ended first, the next SessionStart puts it on the
board for the agent to say in one line.
**A run that failed or ran no tests while the entry says tests pass counts as L4 caught.**

**What runs, and from where:** only the string under `"tests"` in `baton.local.json`, through
the shell (`sh -c`; `cmd /c` on Windows), as you, with **only a short list of the session's
environment variables** (since v3.22.0, ZA-OPRAVYANE row 47, after Bernard Haddad): the board's
list (`BOARD_ENV` -- path, home, temp, locale, display) without `CLAUDE_PLUGIN_DATA`, plus `USER`,
`LOGNAME`, `USERNAME`, `SHELL`, `TERM`, `VIRTUAL_ENV`, plus the names the pin lists under `"env"`
(`"env": ["DATABASE_URL"]` -- names, never values). Before, it got everything except Baton's own
variables, and three made-up identity variables (email, org ID, OAuth token) reached it. Never a
command from a logbook, from the model's words, from the repository (AGENTS.md, a Makefile) or
from the hook's arguments: the runner is told which folder, and reads the command itself. With
nothing pinned, nothing runs and L4 is as before. A pin without a `command` is said once and
nothing runs. **Limits:** the file is on disk, and an agent with write access to it can change
the pin -- every result names the command that ran, so a changed one shows, but Baton does not
stop it. The verdict is as good as the command: a pin that runs one file says nothing about the
rest. A result arrives a turn late, and a run that outlives its budget plus two minutes without a
record is said as "never finished", with nothing known about the claim. Two sessions whose Stops
see the same entry at the same moment can each start a run; the later record wins.

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

The three hooks that read the header (SessionStart, Stop, UserPromptSubmit) share one parser, and the synonym map lives there
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

**At the end of a turn, too** (since v3.23.0, ZA-OPRAVYANE row 73, after Rim Elouragini: "the
file is a claim, the repo is the evidence"). Stop compares a task folder's files with its logbook;
a repository elsewhere was never looked at, so an entry saying "parser fixed and committed" passed
while the repository held no commit and an uncommitted change newer than the entry. Now, for each
logbook this session wrote in whose header has `code:`, Stop asks git what that repository holds
newer than the logbook -- uncommitted files, commits -- and names them to the human, once a session
per folder. Nothing is judged and nothing is handed back: a commit after the entry may be exactly
the one it describes. Only folders written in this session, and git gets 3 s per call; a folder
with no `code:` field, or one not written in this session, is not looked at.

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
in, and Baton compares its own bytes against it and reports a difference at session start.
Without either, an install by `install.sh`/`install.ps1` is compared with the `hooks/` folder of
the repository it recorded as `repo` (since v3.29.0, ZA-OPRAVYANE row 103: the installer writes
`repo`, never `source`, so until then nothing was compared). A `git pull` without running the
installer again is reported the same way -- it is the same question. Since v3.23.0
(ZA-OPRAVYANE row 51, after Benjamin Brachert) the skills are compared too: each
`skills/<name>/SKILL.md` beside that directory against the copy in `~/.claude/skills/<name>/`.

**As a plugin** (since v3.17.0) there is no source of ours; Claude Code installs the copy. Two
questions are still answered at session start, without the network. Has Claude Code recorded
another install of Baton since this session started (`installed_plugins.json`)? Then
`claude plugin update` has taken effect on disk and not here, until a restart. And are the
running hooks, `hooks.json` and the skills (since v3.29.0, row 86) byte for byte the catalog's
copy of the same version (the marketplace clone Claude Code keeps)? A copy Claude Code did not install (`--plugin-dir`) is not
compared, and nor is a catalog that has moved to another version. If you develop Baton and run it
as a plugin, set **the variable** `BATON_SOURCE` (not `source` in the plugin's `baton.local.json`)
and the plugin's running hooks, `hooks.json` and skills are compared with your working copy as
above (since v3.23.0, row 72; until then the variable was read only by the install script's copy).

**What is not compared, as either install:** whether the catalog's copy is the newest release
(that needs the network); `baton.local.json`, which has nothing to be compared with -- it is
yours, and the review tools print its path and a hash of it instead; and the hook registration
in `settings.json` for the install script, because Claude Code merges hooks from several settings
files and a hook can read only some of them.

A hook cannot verify that it was installed. It can ask the same question somewhere it can be
answered.

## Is it running? `/baton-doctor`

```
python3 tools/baton_doctor.py
```

Installed is not running. A plugin can be installed and enabled and still never run -- no
Python 3.8+, or on Windows no Git for Windows -- and nothing on the screen says so. Since
v3.12.0 every hook leaves a heartbeat (`baton.beat.<hook>`, in the plugin's data
folder or next to the script-installed hooks), and `/baton-doctor` (`/baton:baton-doctor` as a
plugin) shows when each last finished. No heartbeat at all: **installed but not running**. It reads
only and sends nothing.

**Switched off** (since v3.23.0, ZA-OPRAVYANE row 78, after Amir Raza and Kumar V.): one line,
`"disableAllHooks": true`, in a settings file Claude Code reads turns every hook off, Baton's too,
and the doctor read the last heartbeats and said ✅. It now reads that key in the user file
(`~/.claude/settings.json`, or under `CLAUDE_CONFIG_DIR`), the project's `.claude/settings.json`
and `.claude/settings.local.json` (in the folder it is run from, and at its git repository's
root), and the managed `managed-settings.json` and `managed-settings.d/*.json`; names every file
that sets it; takes the value precedence leaves (managed > local > project > user); and when it is
true, marks each hook ⛔, says **ALL HOOKS ARE SWITCHED OFF** and exits 1. It cannot see a
`--settings` flag on the command line, nor an MDM or server-managed policy. An agent that can
write a settings file can still switch Baton off; the doctor makes that visible when asked, it
does not prevent it.

**A crash is shown, not a ✅** (since v3.20.0, ZA-OPRAVYANE row 36). Until then the heartbeat was
written before the hook did its work, so a hook that crashed still showed ✅ "last ran just now"
-- the health check proved the hook started, not that it finished. Now the heartbeat is written
after the work, and a run that raised leaves `baton.beat.<hook>.crashed` instead: the time and the
exception's class, nothing else (no message, no path). The doctor marks that hook ❌ CRASHED and
exits 1, and the next SessionStart tells the agent to say it in one line. A hook still never breaks
the session: it exits 0 either way, which is why this is the only place a crash shows.

**A run killed from outside is shown too** (since v3.21.0, ZA-OPRAVYANE row 41). A hook killed at
Claude Code's time limit (20 s; PostToolBatch 10 s as a plugin) -- SIGTERM, then SIGKILL -- wrote neither file,
and the doctor showed ✅ from the run before. Now each run writes `baton.beat.<hook>.started.<pid>`
(the time) before its work and removes it when it finishes or crashes. A mark left behind, newer
than the last finish and the last crash, whose process is gone -- or older than two minutes, past
any hook's limit -- is a run that did not finish: the doctor marks it ❌ DID NOT FINISH (killed or
timed out?) and exits 1, and the next SessionStart says it. One mark per pid, so the same hook
running in two sessions at once is not taken for a kill. **What it cannot see:** a kill followed
by a finish of the same hook is history, as a crash is; and on Windows, where a process cannot be
probed safely, a killed run shows only after two minutes.

**A turn with no end is asked about** (since v3.24.0, ZA-OPRAVYANE rows 49 and 90, after
Synthetixis). Each hook was looked at on its own, so a Stop last finished three days ago, beside
the others a minute ago, showed ✅. Now UserPromptSubmit, PostToolBatch, Stop and the new
**StopFailure** hook each add a line to `baton.turns/<session>` (the time and the event; for
StopFailure the error type, such as `rate_limit`), and the doctor asks of the last week's sessions
(the newest 20) whether the last message or tool call was followed by a Stop or a StopFailure.
One that was not is shown as ⚠️ **a turn with no end seen** -- a question, not a failure, and the
exit code does not change: Stop does not run when the human interrupts a turn, and an API error runs
StopFailure instead, which Baton did not register until this version. StopFailure only records;
Claude Code ignores its output. Two Stops in one turn are by design (the hand-back, then the pass
with `stop_hook_active`), so Stops are not counted: any one ends the turn. **What it cannot see:**
the session the doctor runs in (`BATON_SESSION`, which the skill fills in) and a turn younger than
two minutes are left out, since they may still be going; heartbeats from before v3.24.0 hold no
session, and the check says nothing until new ones exist.

It also shows whether Stop's hand-back does any work -- the one number that says it (ZA-OPRAVYANE
row 27, from a question about how often the agent writes the entry only because it was made to).
Stop counts, by folder, in `baton.lessons.json`: entries the agent **wrote unasked** this session,
turns **handed back** for unrecorded work, and of those how many were **recorded on the second
try** and how many **passed without one** -- Stop never asks twice, so an agent that ignores the
note gets through, and until now that left no trace.

And since v3.20.0, for lesson L2, how often its note was **shown** (it is said at most once every
30 minutes, and counted every time the situation arises: `fired`), and how often a shown note was
**followed by a check**: the agent's next tool calls in that session include a read. Anything else
-- a write, or the turn ending first -- counts as not followed. **This is a proxy, not proof.** The
second read may have been planned anyway, and a sentence written without one may be right; it says
whether the next step looked like a check, not whether the note caused it.

And since v3.21.0, the same question for every lesson (ZA-OPRAVYANE row 44, after Sentry's
"recovery verification"): **fixed after the lesson: N of M**, per lesson. After Stop asks about an
entry -- L1 an hour off the clock, L3 a public/private claim, L4 a tests claim -- the next three
Stops look at the entry it asked about (found by its heading; since v3.23.0, row 71 -- it was the
newest entry, so a claim fixed in a session's second entry counted as not fixed; L1, whose fix
changes the heading, reads the newest) with the same test that raised the ask: the violation
gone counts as fixed (`fixed_after` in `baton.lessons.json`), still there after three Stops as not
(`not_fixed_after`). The second pass after a hand-back is one of the three, and is where the
answer usually lands. A Stop, not a turn, is what the hook can count. For L2 the line is row 40's
"followed by a check". **The same proxy:** for L1, a new entry written on top of the flagged one
counts as fixed too, and a fix made because the agent would have made it anyway looks the same.

## After compaction: the agent writes the logbook first

When Claude Code compacts a long conversation, everything before that point survives only as a
summary -- and the next compaction thins it further. Right after a compaction, Baton tells the
agent to write the logbook entry of every task worked on in this session while the summary
still holds it (decisions and conversations count, not only files), names the task folders
holding this session's unrecorded work, and does **not** show the board again.

It happens at SessionStart with `source: "compact"`, not in a PreCompact hook: Claude Code
gives a PreCompact hook no way to speak to the model -- it can only block the compaction, and
its `systemMessage` is discarded ([hooks reference](https://code.claude.com/docs/en/hooks#precompact)).

## A session that touched no task folder

Stop judges by file times, so a turn that changed nothing in a task folder is never asked
about, and a decision made only in chat passes clean. At the next session start (`startup` or
`/clear`, not after a compaction or on `resume`), Baton reads the last other transcript in the
same project folder and puts two numbers side by side: the messages the human typed in it, and
the logbook entries whose heading falls inside its time (15 minutes' slack). Three messages or
more and no entry: the agent is told so, with the first five messages quoted, and asks the human
once whether any of it should be recorded. Said once per session.

**The same count, in the session still going** (24 October 2026): after `/clear` the question
came one context too late. Now, before the ~200k reminder lets the agent suggest `/clear`, the
agent asks the human whether anything decided only in chat should be recorded -- with the number
of messages typed since the last entry headed in this session's time, and the first five quoted.
`/clear` is suggested only after the answer. And Stop, on a turn that changed no task file, hands
the turn back once when six or more messages have been typed since that entry (twice the threshold
above: it is asked mid-session, again every six) -- never on a turn that saved a logbook, never
twice in a turn, and silent when the transcript cannot be read.

**Secret-shaped strings are masked before a message is quoted** (since v3.22.0, ZA-OPRAVYANE
row 48, after Bernard Haddad and Bachittarjeet Singh Sidhu): a fake key pasted into a message came
back verbatim in the new session's context. Now `sk-…`, GitHub (`ghp_…`, `github_pat_…`), AWS
(`AKIA…`), Slack (`xox…`), Google (`AIza…`) keys, a JWT, a private-key header, `key=`/`token=`/
`password:` and the value after it, `Bearer …`, 32+ hex characters, and 32+ base64 characters with
upper case, lower case and a digit read `[masked]` -- before the 70-character cut, so a key cut in
half is still seen whole. Shapes, not a proof: a short key of no known shape is still quoted.

A message is one the human typed: the agent's turns multiply in loops and subagents, and tool
results and command output are nobody's word. **What it cannot do:** say which task the
messages belonged to, or tell a decision from small talk -- it names the messages and the human
decides. With two windows open in the same project, "the last session" may be the other live
one. Subagent transcripts are not read. The idea is Jake Manis's (20 October 2026).

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
- **An older entry rewritten is not an entry** (since v3.17.0). The entries are remembered one by
  one as well. A change confined to the top records the work: new entries above the newest, the
  newest one completed or its heading corrected, or -- in a logbook kept oldest-first -- one
  added at the end. A change to anything below the newest entry does not, and Stop says once
  that an older entry changed: the logbook is a record, so what was wrong gets a new entry at
  the top. **What it does not catch:** a rewrite of the newest entry itself -- by decision, it is
  the same edit as completing or correcting it -- and a rewrite by a session before this one (it
  is remembered, not reported).
- **History that disappears is said** (since v3.20.0, ZA-OPRAVYANE row 37). A logbook Baton had
  seen that is gone, a folder gone with it, or a logbook holding fewer entries than last time (the
  newest one deleted used to count as a change at the top, the work recorded; now it does not) --
  Stop tells the human once, in a message the agent does not write, and the board says it if
  SessionStart sees it first. So does Baton's own memory (`baton.bodies.json`) when it is gone or
  unreadable while the lessons register shows Stop has looked before: until each logbook has been
  seen again, a rewrite cannot be told from a new entry. Baton keeps no copy of a logbook. **What
  it does not catch:** both state files deleted together, and a logbook deleted from a folder
  with no other file in it (the walk does not look at such a folder). A record the agent cannot
  touch has to live outside its reach -- a remote it holds no key for, or another machine.


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
first version falsely rejected a real file while nine unit tests passed — see [Versions](../README.md#versions).

## Lessons: a mistake caught once is counted

A lesson written down as a note did not stop the mistake it was about. The hour of an entry
typed by hand was recorded as a lesson on 2026-09-23 and came back on 26.09, 28.09 and twice on
30.09 — caught by a hook every time, prevented never. So no lesson is loaded into every
session; each lives in the hook that sees its trigger, and each is **counted**: `fired` when
the situation arose, `caught` when the mistake happened. The counters are in
`baton.lessons.json` next to the hooks (in `${CLAUDE_PLUGIN_DATA}` as a plugin).

- **L1 — the hour in a heading comes from the clock** (Stop). Every new top entry is counted;
  an hour more than 20 minutes off the moment the logbook was saved, either way, is caught (the
  save time, not the time Stop runs: an entry written by another session and seen hours later is
  not late), and the agent is told
  which tool makes it impossible: `tools/baton_entry.py --title`, which stamps the time itself,
  named by its full path on this machine (the plugin's folder, or the repository the install
  script recorded) since v3.17.0. Since v3.26.0 it is also said **before** the write: the
  PreToolUse hook `baton_pretool.py`, registered only for Write, Edit and MultiEdit, reads the
  text about to go into a file named as the logbook and, when it carries a `## <date> <hour>`
  heading, tells the agent to use `baton_entry.py` instead (counted as `surfaced_before`). It
  never blocks the write and returns no permission decision -- only a note; Stop still checks after.
- **L2 — an empty result, or an error instead of one, is a failed read** (`baton_batch.py`,
  PostToolBatch). After a read —
  web, a shell command that searches or fetches, or an MCP tool whose name says it reads
  (`search`, `query`, `get`, `list`, `read`, `fetch`…, and no `create`/`update`/`delete`…;
  a name that says neither is left alone; in a shell command the body of a heredoc is text being
  written, not the command, and is not searched -- nor, since v3.17.0, a quoted script or string
  that `sed`, `echo`, `printf`, `awk`, `perl` or `python -c` carries; quotes that `ssh` or
  `bash -c` runs, and a `$( )` inside double quotes, still count) — returns nothing, one line reaches
  the agent before its next sentence: name the check that would have found it before saying
  something is absent. At most once every 30 minutes; counted every time (`fired`), and since
  v3.20.0 `shown` apart. Since v3.20.0 an **error that comes back instead of a result** counts
  too: a short result whose every line is an error line -- `grep: x: No such file or directory`,
  `The server returned HTTP 404`, `getaddrinfo ENOTFOUND`, `error:`/`fatal:` lines. Kept narrow on
  purpose: a result that carries anything else (a grep hit that mentions "not found", pytest
  output) is left alone, and so is `ls`/`stat` saying a path is not there -- that is the check for
  absence, not a failed read. Replayed on the 5,213 reads in the transcripts on the author's
  machine (22 October 2026): 11 new fires, each a read that returned an error (WebFetch 403/404,
  a DNS failure, an MCP 400, grep on a missing file); none was a result. **Still not seen:** a
  half-loaded page that returns navigation text -- the plausible half-result, the worse case.
  After a shown note, whether the next step was a read is counted (see `/baton-doctor`) -- a
  proxy, not proof that the note worked.
- **L3 — a claim that something is public or private is checked against the source** (Stop,
  since v3.18.0; see *What you get*). `fired`: Stop asked for the claims section -- once per
  entry, in whichever session sees it first. `caught`: **only a proven error** -- a line that
  starts `refuted:` (or `оборено:`, after an optional `- `) inside a `### Claims to verify` /
  `### За проверка` section of a newer entry, in a logbook where an older entry listed claims.
  Each such line counts once. A claim re-read and found right is not a catch, nor is "refuted"
  written anywhere else -- a heading, the prose -- nor a refutation with no listed claim below
  it. The marker is not matched to the claim's text: the line says which claim, the human
  reads it.
- **L4 — a claim that tests pass is listed with the command that showed it** (Stop, since
  v3.20.0; ZA-OPRAVYANE row 38). The shape check passed an entry that said "did not run pytest …
  All tests pass." (Apurv Khare, 22 October 2026): it measures sections and length, not truth.
  So, as for L3: when the newest entry this session wrote says tests pass ("tests pass/passed",
  "all green", "N passed", „тестовете минават/минаха“) and its claims section at the top does not
  list that, Stop asks once per entry to list it there, with the command and the result line it
  printed. Not read as a claim: inline code (a pasted result line is the evidence), the phrase in
  quotes (talked about), "N failed, M passed" (a run that failed), „минават през“ (go through).
  Measured on the 1,347 dated entries of the author's logbooks: 25 match, all 25 a claim that
  tests passed (the first patterns matched 35; the 10 dropped were mentions). `caught` as for L3:
  a `refuted:` line about a tests claim in a later entry's claims section. It does not check that
  the command is there, nor that it ran -- it puts the claim where a reader checks it. Since
  v3.21.0 "N/N passes" counts too (row 42); measured again on the 1,382 dated entries of the
  author's logbooks: 29 match before and after the change, all claims, and the only four "N/N
  pass" in them are the phrase quoted. Since v3.22.0 (rows 59, 60) the plain sentence ("tests are
  passing", "the suite passes", "CI is green", „тестове минават“, „преминаха“, „са зелени“) and
  every entry this session wrote, not only the newest; on 1,417 dated entries 35 match, the two
  new ones both real claims („синтетичните тестове минават“, investicii-sec) that had never been
  asked. And since v3.21.0, where a human has pinned a test command
  for the folder (see *What you get*), its result is set beside the claim, and a run that failed
  or ran no tests is counted `caught` -- the one catch here that is measured, not written. `caught`
  counts both kinds, a `refuted:` line and a pinned run that disagreed, and does not tell them
  apart; a run's catch has no `fired` of its own, so "caught N of M asked" can show N above M.
- **Not a lesson: looping** (ZA-OPRAVYANE row 45, measured 22 October 2026, not added). The
  proposal: the same tool with the same input returning the same error three times in a row,
  then one note to change the approach. In the 26,747 tool calls of the 404 transcripts on the
  author's machine (subagents included): three in a row, 0; three within ten calls, 0, also with
  the error text ignored. Twice in a row: 4, all four the harness's own permission classifier
  refusing, and the retry was right. There is no threshold the numbers support -- at three
  nothing to test it against, at two only noise -- so it is not in Baton.

SessionStart says something only when a lesson has earned it: caught twice in 14 days (it is
not holding — propose the next rung: a check on the result, or a tool that makes the mistake
impossible), or silent for 60 days (ask whether to retire it). For L3 a catch is the opposite
fact -- a listed claim shown wrong means the section did its work -- so two of them say that,
with the two numbers, and propose nothing. The same holds for L4.

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

**Opened by itself at session start, if you switch it on.** Put `"board_open": true` in
`baton.local.json` and SessionStart writes the board to `baton.board.html` (next to the
settings) and opens it in the browser -- at `startup` and after `/clear`, never after a
compaction or on `resume`, which are the same work going on. Off by default: a browser that
pops up by itself is not something to switch on for anyone. Without a display (an SSH session, a
server: on Linux no `DISPLAY` or `WAYLAND_DISPLAY`, on a Mac an SSH connection) it does nothing.
It runs in a process of its own, so the session does not wait for it and a failure in it costs
nothing. That process gets only the environment variables it needs (`BOARD_ENV` in
`hooks/_baton.py`: paths, locale, Baton's settings folder, and what a browser needs to appear --
display, session bus, `BROWSER`); nothing else from the session's environment is passed to it. `"board_language": "bg"` (or `--lang bg` by hand) gives the page Bulgarian labels; the
terminal board is translated by the agent, and nobody translates a file opened in a browser.
English is the default. The idea came from
[answer-me-with-html](https://github.com/QingYunA/answer-me-with-html).

## A free check of the memory index

```
python3 tools/baton_memory_lint.py ~/.claude/projects/<project>/memory/MEMORY.md
```

Three questions, no model, nothing sent: does every link in the index lead to a file that
exists, does every Markdown file in the index's folder have a line in it, and which files
changed after the line that points to them? A memory file without a line is invisible -- the
index is what a session reads first. It reports and never edits the index; exit 1 when it found
something. Without a path it checks `review_index` from the settings.

The third question is the case of 19 September 2026: the index said "we want the paper, it is
behind a wall" five days after the detail file had recorded it as read, and the first two
questions passed it clean. It is answered by file time, not by meaning -- a changed file is a
reason to read its line again, not proof the line is wrong. A line's time is remembered by its
text (`baton.memlint.json` next to the settings); a line not seen before takes the index's own
file time, the latest it can have been written, so the first run already names a file newer
than the whole index. An edit elsewhere in the index does not reset a line; rewriting the line
does. A link to a logbook is left out: it grows under its line by design (on the author's
index all four lines first named were logbooks). `--accept` records the lines it names as
re-read. Whether a line is still *true* is the
paid [review](review-tools.md).

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

### Corrections
Asked for a dry run on staging; ran it on a copy of production instead — staging had no
`legacy_ref` rows at all.

### Changed: old → new
`MIGRATION_BATCH`: `50000` → `10000` (the 50k batch locked the table for 40 s)

### Open / notes
`tax_region` has no target column at all — ask before inventing one.
Do not trust `legacy_ref` being null to mean unused; 300 rows carry an empty string.
```

**Corrections** (done versus asked) and **Changed: old → new** appear only when there is
something to put in them: they are the two things a reader cannot reconstruct from the result
alone. **A secret never goes into an entry** — write `[secret removed]` and where it lives.

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

**A folder of data** -- downloaded filings, cloned repositories, a cache -- goes in as a line
ending in `/`. The hooks then do not walk into it at all, which is what keeps them fast: a glob
such as `build/*` still lists and checks every file under `build/`, one by one.

```
cache/                      # a folder named cache, at any depth
raw/2026/                   # this path, from the task folder
```

The task root's `.batonignore` can say the same with the task's name in front
(`investicii-sec/raw/`). In a line, `*` also crosses `/`.

**A folder bigger than 10,000 work files is not read to the end.** Every hook walks every task
folder; on 21.10.2026 one task root of ~139,000 files took SessionStart and Stop to 19 seconds
against their 20-second limit, and a hook over the limit is dropped without a word. So the walk
stops at 10,000 files, and that is never a silent pass: the board lists the folder as *not read
to the end*, and Stop says so once a session (a message, not a hand-back -- the agent cannot
settle it in that turn). Newer work further in is not seen until its data folders are named
with `dir/` lines.

**A folder that is not a task** -- photos, an archive -- goes in a `.batonignore` at the task
root, one folder name (or glob) per line. It means the same there: do not demand a logbook for
this. Such a folder is not on the board, Stop never asks about it, and the review neither expects
it nor counts it missing (it prints it as skipped). Without it, every folder in the task root is
a task, and one without a logbook is reported as one.

**A `.batonignore` saved in the same session as the work it hides is said to the human** (since
v3.22.0, ZA-OPRAVYANE row 57). Its lines apply the moment they are on disk, so an agent handed
back for unrecorded work could add `*` or the file's name and pass with no word. Stop still obeys
the line -- it may be right -- but says once a session, in a message the agent does not write,
which files saved this session it hides; the board no longer suggests it as the way out.

## Logbook is not memory

They are different jobs and must not merge:

| | holds | read |
|---|---|---|
| **memory / state file** | what is **true now** — current state, live decisions, access paths | every session, automatically |
| **`LOGBOOK.md`** | what was **done** — session by session, in order, with results | when the task is picked back up |

New state replaces old state in the memory file. The logbook only ever grows. Merge the two
and you get a file that is too long to load every session and too disordered to trust.

[`docs/memory-layout.md`](memory-layout.md) covers the other half: index, one folder
per project, a short state file under 150 lines, chronology in a separate history file.

**Names before v3.1.0.** The tools, their flags and the review's settings had Bulgarian names.
They all still work: `baton_pregled` → `baton_review`, `baton_kade` → `baton_where`,
`baton_tablo` → `baton_board`, `baton_vpishi` → `baton_entry`, `baton_otsey` → `baton_sift`,
`baton_korpus` → `baton_corpus` (the old files run the new ones); `--dali`/`--koe`/`--zadachi` →
`--stale`/`--which`/`--tasks`; `pregled_indeks`/`pregled_podbor`/`pregled_poveritelni` →
`review_index`/`review_shortlist`/`review_confidential`. Before v3.3.0 the functions a script
could call had Bulgarian names too; they still answer: `vpishi(..., sledvashto=, staro=)` →
`write_entry(..., next_line=, old_line=)`, `otsey` → `sift`, `pitay` / `poveritelno` / `klyuch` →
`ask` / `held_word` / `get_api_key`, and `config()` still carries `poveritelni` beside `confidential`.
