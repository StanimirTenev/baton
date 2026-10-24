# Baton

**Work that survives the session.**

A coding agent forgets everything between sessions. Baton makes the note-taking structural
instead of voluntary: every task gets a folder with a `LOGBOOK.md`, and hooks run by Claude
Code -- not by the agent's judgement -- make sure the logbook is read at the start and written
at the end.

## Where it works

| Where | Works? |
|---|---|
| Claude Code in the terminal | yes |
| Claude Code IDE extensions | yes |
| Code tab of the Claude desktop app | yes |
| claude.ai chat (web, desktop, mobile) | **no** -- hooks are ignored, only the skills load, nothing is enforced |
| Cowork | loads hooks, but Baton is untested there |

**In a claude.ai chat nothing warns you:** the plugin looks installed and the skills answer,
but no hook runs ([platform support](https://claude.com/docs/plugins/platform-support)).
A plugin added from the directory on claude.ai reaches Claude Code at its next session start.

## Install

Needs Python 3.8 or later; on Windows the plugin also needs Git for Windows. One of:

```bash
claude plugin marketplace add StanimirTenev/baton && claude plugin install baton@baton
git clone https://github.com/StanimirTenev/baton ~/.baton && ~/.baton/install.sh
```

On Windows the script is `install.cmd` (or `setup-windows.cmd` on a machine with no Claude
Code). Task folders go in `~/tasks` unless you choose another. With the script, keep the
clone: the tools, including the doctor, run from it. An agent installing Baton for you reads
[docs/install.md](docs/install.md) first. Then start a new Claude Code session.

## Is it working?

The new session shows one line, `🧭 Baton is on ...` or `🧭 Baton: ...`, and the agent's first
reply opens with the board of your tasks. No line? Run `/baton-doctor` (`/baton:baton-doctor`
as a plugin): it shows when each hook last finished, or that it crashed.

## Documentation

- [Install in detail](docs/install.md) -- before installing, plugin or script, Windows and USB, updates, configuration
- [Skills](docs/skills.md) -- `/baton-inventory`, `/baton-task`, `/baton-plan`, and when a swarm is worth it
- [How it works](docs/how-it-works.md) -- the board, the task header, the hooks, `/baton-doctor`, lessons, the logbook entry, `.batonignore`
- [Review tools](docs/review-tools.md) -- the optional review of an index against its files, duplicated state, reading order, the corpus
- [Memory layout](docs/memory-layout.md) -- where an agent keeps what is true, beside the logbook of what was done
- [Why this exists, and what it does not solve](docs/why.md)

Below: [Uninstall](#uninstall), [What Baton sends over the network](#what-baton-sends-over-the-network), [Versions](#versions).

## Uninstall

**Plugin:** `claude plugin uninstall baton` (add `--keep-data` to keep its settings).

**Script install:** remove the five hook entries whose command runs a `baton_` script
(`baton_session_start.py`, `baton_stop.py`, `baton_prompt.py`, `baton_batch.py`,
`baton_stop_failure.py`) from `~/.claude/settings.json`,
delete the Baton section from `~/.claude/CLAUDE.md` (the heading
`# Baton — task folders and logbooks` and the text under it, marked
`<!-- Installed by Baton. ... -->`), and remove `~/.claude/baton`, the five skills
`~/.claude/skills/baton-inventory`, `baton-plan`, `baton-task`, `baton-key` and `baton-doctor`, and the clone
(`~/.baton`).

Either way, your task folders are plain directories of plain Markdown -- they keep working
without any of this, which is the point.

## What Baton sends over the network

| what | when | to |
|---|---|---|
| the hooks, installed as a plugin | never | -- |
| the hooks, installed by script | once a week (a failed check is retried the next day), **only if you switched the update check on** (`tools/baton_update.py on`); off until you choose | `api.github.com/repos/StanimirTenev/baton/releases/latest` -- a version number back, nothing of yours sent |
| `tools/baton_key.py` | when you run it, to check the key you give it | `openrouter.ai` |
| `tools/baton_review.py`, `tools/baton_sift.py` | when you run them | `openrouter.ai` -- the text under review; anything holding a word listed in `review_confidential` (in its path or its text) is held back before anything is sent |

`tools/baton_corpus.py` and every other tool work on your files only. Nothing runs on a
schedule except the opt-in update check above. The one command the hooks run that is not their
own is a test command **you** pinned in `baton.local.json` (lesson L4, since v3.21.0): run on this
machine after a turn whose entry says tests pass, and never without that pin.

What the hooks read, all on this machine: the task folders and their logbooks; the session's
transcript (`transcript_path`) — its first timestamp, for when the session began, and its
last answer's token count, for the restart reminder; at session start, the previous transcript
in the same project folder — the messages the human typed and its times, to set beside the
entries written then; and the text of tool results, for an empty or failed read (lesson L2). Nothing of it leaves the machine. The review tools send only with the
key given to Baton by `tools/baton_key.py` — never a key found in the environment or in
another tool's files.


## Versions

**v3.24.1** — the plugin directory accepts Baton again

- **No shipped file holds a whole key-shaped string.** The directory blocked v3.22.0–v3.24.0 with
  "Secret in a shipped file": the test for row 48 (masking a pasted key) listed fourteen fake keys
  verbatim. Each is now cut into pieces that Python joins at run time; the values the test checks
  are the same, and nothing in the hooks changes.

**v3.24.0** — a turn that ends on an API error leaves a beat; the doctor asks per session

- **A turn that ends on an API error is recorded.** Claude Code runs StopFailure instead of Stop
  then, and Baton did not register it, so such a turn looked like a Stop that did not run. A new
  hook, `baton_stop_failure.py`, records the time, the session and the error type, and prints
  nothing; the plugin and both installers register it (row 90, Synthetixis).
- **`/baton-doctor` asks whether each recent session's last turn ended.** The hooks add a line per
  run to `baton.turns/<session>`; a last message or tool call with no Stop or StopFailure after it
  is ⚠️, a question and not a failure, since Stop does not run when the human interrupts a turn.
  Two Stops in a turn are not counted (row 49, Synthetixis).

**v3.23.0** — gaps found by a probe of LinkedIn's questions, a public reply and the last release

- **`/baton-doctor` sees `"disableAllHooks": true`.** One line in a settings file switches every
  hook off, and the doctor said ✅ from the last heartbeats. It now reads the key at every scope,
  names the file, marks the hooks ⛔ and exits 1 (row 78, Amir Raza, Kumar V.).
- **A pinned run that ran no test is not "passed".** The verdict reads what the runner printed:
  `go test` with no test files (exit 0), unittest's NO TESTS RAN, jest's No tests found; and exit 5
  from a path that held "pytest" is no longer "no tests ran" (rows 74, 75, Kyle Bartlett).
- **A pass with the failing test skipped, xfailed or deleted is not "passed".** Counts are
  compared with the last run of the same command; test files edited in the session are named beside
  the result (rows 77, 52). The first run has no baseline.
- **Stop names what a `code:` repository holds newer than the logbook** -- uncommitted files,
  commits -- once a session, for logbooks written in it (row 73, Rim Elouragini).
- **An entry that says it changed a file, in a session that saved none, is asked about** (row 76,
  Kyle Bartlett). On the author's 36 top entries, none was.
- **The installer leaves a human's own hook alone** when its command holds "baton_" (row 68); it
  rewrote it into Baton's.
- Smaller: Stop given broken JSON or a non-object does nothing (row 70; it handed back old debt);
  SessionStart and the entry tool read `## 22.10.2026 15:30` headings (row 69); "fixed after the
  lesson" reads the entry Stop asked about, not the newest (row 71); the copy check compares the
  skills (row 51), and `BATON_SOURCE` compares a plugin's copy too (row 72).

**v3.22.0** — thirteen of fifteen gaps from a hostile probe of the hooks; three fixes promised publicly

- **A crash in the hour after the clocks go back is shown, not ✅.** Markers held local time and
  were ordered as text, so on 25.10.2026 a crash at 03:20 sorted before a finish at 03:50 written
  half an hour earlier (row 64). They are now ordered by the files' own times.
- **Per-session state is no longer in the shared temp folder.** It held task names and entry
  headings, 0644 in /tmp; now `sessions/` beside Baton's other state (`CLAUDE_PLUGIN_DATA` as a
  plugin, next to the hooks with the install script), each file 0600, removed after 7 days (row 53).
- **The pinned test command gets an allowlist, not the session's environment** -- three made-up
  identity variables reached it (row 47, Bernard Haddad). Extra names go in the pin's `"env"`.
- **A pasted key is masked before the quiet-session note quotes the human** (row 48, Bernard Haddad,
  Bachittarjeet Singh Sidhu): `sk-…`, GitHub, AWS, Slack, Google keys, JWTs, `token=`, long hex
  and base64 read `[masked]`. Shapes, not a proof.
- **`BATON_SOURCE` works without `baton.local.json`**, as the README said (row 50, Benjamin
  Brachert); the drift check compared nothing.
- **One unreadable task folder no longer takes the board and every Stop check with it.** It is
  left out and named (row 54).
- **The entry written in answer to a hand-back gets the quality checks too** -- hollow, L1, L3,
  L4 -- said to the human, never a second hand-back (row 55).
- **A `.batonignore` saved in the same session as the work it hides is said** (row 57); the board
  no longer offers it as the way out.
- **Stop reads `## 22.10.2026 15:30` as an entry** (row 58); L3 and L4 read every entry the session
  wrote, not only the top one (row 59); L4 reads "tests are passing", "CI is green", „тестове
  минават“ (row 60: on 1,417 real entries 33 → 35 matches, both new ones real claims).
- Smaller: a human's own hook with "baton_" in its command no longer switches the plugin off
  (row 61); deleting the hour no longer counts as L1 followed (row 62); a folder named `report
  (v2)` keeps its name in Stop's counts (row 63); `tools/baton_entry.py` writes into a logbook
  with a BOM, without a header or without entries (row 65); stdin that is not a JSON object is no
  payload, not a crash (row 67).
- Not in this version: work that arrives with its old modification time (`wget`, `cp -p`,
  `rsync -a`) is still not seen (row 56) -- reading ctime breaks how the suite fakes file ages
  and needs a decision. Confidential tasks stay on the board and in the prompt hook with their
  `next:` (row 66): the human's decision, 22.10.

**v3.21.0** — a killed hook is shown; a pinned test command answers "tests pass"

- **A hook killed at its time limit shows as not finished, not ✅.** A run stopped from outside
  (SIGTERM, then SIGKILL) wrote nothing, and `/baton-doctor` showed the run before it (row 41, the
  limit v3.20.0 stated). Each run now marks its start under its own pid and clears it when it
  finishes or crashes; a mark left behind from a process that is gone is ❌ DID NOT FINISH (killed
  or timed out?), and the next SessionStart says it. A run of the same hook still going in
  another session is not taken for one killed.
- **A test command pinned by a human sets the actual result beside "tests pass".** Pinned once per
  task folder in `baton.local.json` (`"tests"`), it runs in the background after a turn whose
  entry says tests pass, under its own budget, and is judged by exit code -- pytest's 5 is "no
  tests ran", not passed. The next Stop or SessionStart says the result once, to the human; a
  failed run beside a passing claim counts as L4 caught (Apurv Khare: "tests pass" should come
  from a hook that re-runs them). Nothing runs without the pin, and never a command from a
  logbook, the model or the repository.
- **L4 reads "5/5 passes"** -- the honest entry of the probe was not asked. N/N only; "3/5 passed"
  no longer reads as "5 passed". On 1,382 real entries: 29 matches before and after, all claims.
- **Every lesson says whether it was followed:** "fixed after the lesson: N of M" in
  `/baton-doctor` for L1, L3 and L4 -- the next three Stops look at the flagged entry with the test
  that raised the ask -- beside L2's "followed by a check". A proxy, not proof.
- **Looping was measured and not added.** Three identical failing calls in a row: 0 in 26,747
  recorded tool calls; the only pairs were the harness's own refusals. No threshold the numbers
  support, so no lesson L5.

**v3.20.0** — a crash is shown; history that disappears is said; "tests pass" goes in the claims

- **A hook that crashed shows as crashed, not ✅.** The heartbeat `/baton-doctor` reads was
  written before the hook did its work, so after a crash it said "last ran just now" (found on a
  copy with a fault injected, after a question from Pawan Singh Rathore). It is now written after
  the work; a run that raised leaves `baton.beat.<hook>.crashed` -- time and exception class, no
  message, no path -- and the doctor (❌, exit 1) and the next SessionStart say it. The
  PostToolBatch hook had no top-level guard: a malformed batch was a traceback and exit 1; now it
  exits 0 and the crash is recorded, as for the others. A hook killed at the time limit leaves
  neither file.
- **History that disappears is said, once, to the human.** A logbook Baton had seen that is gone,
  a logbook holding fewer entries than last time, and Baton's own memory of the logbooks gone or
  unreadable (Marcelo Dantas: "the agent should not control the record of its own actions"). The
  newest entry deleted no longer counts as the work recorded. Not caught: the newest entry
  rewritten -- by decision, the same edit as completing it -- and both state files deleted
  together. The real fix, a record outside the agent's reach, is outside Baton.
- **Lesson L4: "tests pass" is listed with the command that showed it.** As L3 does for public
  and private, an entry that says tests pass is asked once to list the claim under `### Claims to
  verify` with the command and its result line (Apurv Khare: "did not run pytest … All tests
  pass." passed the shape check). Matched 25 of 1,347 real entries, all 25 such claims.
- **L2 sees an error instead of a result**, not only an empty one: a short result whose every line
  is an error line (`No such file or directory`, HTTP 4xx/5xx, a DNS failure). On 5,213 recorded
  reads: 11 new fires, all failed reads (Oliver Veits). `ls` saying a path is not there is left
  alone; a half-loaded page is still not seen. `shown` is counted apart from `fired`.
- **L2 has a measure, and it is a proxy.** After a shown note, whether the agent's next tool calls
  include a read is counted -- "followed by a check: N of M" in `/baton-doctor` (Ramón Pérez
  Coronado: how many of the fires changed what the agent wrote next?). It says what the next step
  looked like, not that the note caused it.

**v3.19.0** — the hooks under 2 s on a large task root; a hand-back counted by the logbook

- **A folder too large to walk is skipped or said, not read for 19 seconds.** On a task root of
  about 139,000 files SessionStart and Stop took up to 19 s against Claude Code's 20 s limit.
  A `.batonignore` line ending in `/` now names a folder the walk does not enter (in a task
  folder, or at the task root as `<task>/<path>/`), and a folder with more than 10,000 work files
  is read that far and named -- "not read to the end" on the board and once a session from Stop,
  never a hand-back. Measured here on copies of the hooks: 7.3 s / 14.0 s before, 1.0 s / 1.7 s
  after with the lines. **The cost:** a folder over the cap is not read to the end, so its newest
  file can be missed; the `/` lines are the fix, the cap a guard. See "Ignoring files".
- **A hand-back counts as recorded only when the logbook says so.** Stop now counts what came of
  a hand-back (`unasked`, `handed_back`, `recorded_after`, `passed`, shown by `/baton-doctor`).
  It first counted a folder as recorded when its file was merely too new to be asked about; now
  recorded means the logbook changed at the top after the hand-back.
- **The last session's messages beside the entries written then.** On `startup` and `/clear`,
  the previous transcript in the project folder is read -- only what the human typed -- and three
  or more messages with no entry in their time are said once, the first five quoted. 73 MB is
  read in 0.4 s. Not on compact or resume.
- **A folder the task root's `.batonignore` names is not a task**, for SessionStart, Stop, the
  board and the review alike; the review lists it as skipped.
- **The memory lint names a file that changed after the line pointing to it** (by file time, not
  meaning; `--accept` records the lines as re-read). Logbooks, which change with every entry, are
  left out.
- **For lesson L3, a catch is the claims section working**: SessionStart says the two numbers and
  proposes nothing.
- **The HTML board can open itself** at `startup` and `/clear` with `"board_open": true` (off by
  default, only with a display), with Bulgarian labels by `"board_language": "bg"`. Its process
  gets only the environment variables it needs (`BOARD_ENV`); a key or token in the session's
  environment is not passed to it.
- **After a week of use the agent asks once for feedback** and names the issues page. Nothing is
  sent; Baton has no telemetry.
- **L3's hand-back names no command.** It said to check visibility with a GitHub CLI command; it
  now says "the repository's or the page's own visibility setting". Detection is unchanged.
- **The plugin's description is 497 characters**, under the directory's cut at 500, and says
  where the hooks run.
- README: Uninstall names four hook entries and five skills; the restart reminder stays at 200k
  (why is written down).

**v3.18.0** — a claim that something is public or private is asked to be listed at the top

- **A claim about what is public or private is put where it gets read.** The entry behind v3.16.0
  said a private repository was PUBLIC and had every section; the shape check passes it. The idea
  came from a conversation under the post about that check: a short "claims to verify" section
  at the top of an entry. Asked for on every entry it would be a form, so Stop asks only when the
  newest entry this session wrote says something is public or private and does not open with
  `### Claims to verify` / `### За проверка` -- once per entry. Dry run on copies of the 34
  logbooks here: 21 of 195 entries since 10 October (165 of 1,274 in all); of the 21, 11 state
  what a repository or page is, 5 are borderline, 5 use the word in another sense. **What it
  cannot do:** tell whether the claim is true -- it puts the claim in front of a reader.
- **Counted as lesson L3.** `fired` when Stop asks; `caught` only for a proven error -- a line
  `refuted: <the claim>` in the claims section of a later entry, under an entry that listed
  claims. A claim re-read and found right is not a catch. The counters are in
  `baton.lessons.json`, with L1 and L2.

**v3.17.0** — a rewritten older entry, a partial review and an update not running say so

- **Rewriting an older entry no longer counts as recording the work.** Arthur Barbosa, 8 October:
  a folder the agent writes in is not an audit trail. We said then that a rewritten older entry
  even counted as the logbook updated -- Stop hashed the whole body. The entries are now
  remembered one by one: a change at the top (a new entry, the newest one completed or its
  heading corrected) records the work; a change below it does not, and Stop says so once. Dry
  run on copies of the 34 logbooks here: a new entry at the top of each is not a rewrite; one
  figure changed in an older entry is. **What it does not catch:** the newest entry rewritten.
- **A partial review says PARTIAL and exits 2.** The second half of Abhillash Jadhav's point (17
  October): v3.15.0 named what it did not read and still exited 0. Now some read and some not is
  `PARTIAL: 7 of 10 … read; not read: …`, exit 2; with `review_required: true` it is `BLOCKED`,
  exit 1. Not live-run against the model after the change -- tested with the call stubbed.
- **As a plugin, the running copy is compared too.** The check that the running hooks are the
  installed ones stood down for plugins -- most installs -- while comments in public said each
  session makes it. Now SessionStart says when Claude Code has installed another version since
  this session started (restart to run it), and when the running hooks differ from the catalog's
  copy of the same version. Checked on this machine both ways. **Not compared:** whether the
  catalog copy is the newest release, `baton.local.json`, and the install script's registration in
  `settings.json` (see "The running hook is a copy").
- **A short Cyrillic alias no longer matches a longer word that starts the same.** `пост` matched
  `построй`, `построи` and `пострим` (the replay of 12 October, Ilya Gorban's method; named as
  unfixed in v3.14.3). A 3–4 letter Cyrillic alias now takes a noun's ending, not any three
  letters. Over the human prompts on this machine exactly those four matches go; `поста`,
  `постове`, `джефа`, `новата`, `парите`, `куката`, `чужди` stay.
- **L2 no longer reads a verb inside a sed script or a quoted string as a read.** A `python3 -c`
  body, a `sed`, `awk` or `perl` script, an `echo` or `printf` string: text the command carries,
  as a heredoc body has been since v3.14.1. Over the recorded Bash calls here L2's fires go from
  81 to 75 -- four logbook writes and two JSON-RPC payloads; the three `ssh host '…'` reads in
  quotes still fire. Not claimed: that the other 75 are all reads.
- **L1 names the entry tool where it is** -- from PR #2 by anandamandala12-source: an entry saved
  by another session before this one is no longer handed to this one to correct, and the
  hand-back gives the tool's full path. On top of it, the path for an install-script install,
  where the tools stay in the repository.
- **The README caught up with two things.** Compaction: seen once after a manual `/compact` (5
  October), not yet after an automatic one. "Not solved here" now names the v3.16.0 shape check,
  and still says no hook can tell whether an entry is true.

**v3.16.0** — an entry written only to pass is asked about

- **One word under a heading passed like a full entry.** Arpana Singh asked under a post about
  hooks: "How do you handle an agent that writes a low-effort logbook entry just to get past it?"
  The answer was that nothing did -- Stop compared file times. Now, for a logbook whose body this
  session changed, Stop reads the newest entry and hands the turn back once per entry when it has
  fewer than three `###` sections with text, is under 200 characters, or names none of the files
  saved in the folder this session. Found while building it: a session that wrote three entries
  named its files in the first, and the third was flagged -- names are now looked for across all
  of this session's entries. **What it does not do:** judge whether an entry is right. A wrong
  entry with the right shape passes.

**v3.15.0** — a review says what it did not read

- **Seven of ten no longer looks like ten.** Since v3.12.1 a review that read nothing stops with
  BLOCKED and names its configuration file with a hash. Abhillash Jadhav pointed out the half that
  left open: pointed at ten logbooks and reading seven, the hash matches, the input is smaller, and
  the output looks whole. `--tasks` skipped a folder without the logbook in silence. Both modes now
  end with an account -- `ACCOUNT: 10 task folders expected -- 7 reviewed, 1 held, 2 not read` --
  and name each one not read with the reason (`no DNEVNIK.md`, `no header`, `no file`), because a
  bare count lets a renamed folder and a deleted one look the same. **What it does not do:** a
  partial run still exits 0; whether seven of ten should be BLOCKED is left open, and a folder that
  was never meant to hold a logbook is named like one whose logbook went missing.

**v3.14.3** — a Latin alias matches only itself and its plural

- **"both" stopped opening the trading bots' logbook.** Ilya Gorban suggested deduplicating the
  fires to distinct triggers and reading those. Over the same 1,784 human prompts: 152 distinct
  triggers, 83 of which matched only through the prefix. Read one by one, 10 were wrong, and every
  English one came from the prefix: `sec` on `second`, `sector`, `secure`; `bot` on `both`;
  `crypto` on `cryptoscan`; `directory` on `director`. A Latin alias word now matches itself or
  its English plural (-s, -es, -y -> -ies) and nothing else. Over the replay, those 7 triggers
  went and no other changed. Each word is a pinned test case. **What it costs:** other English
  forms (`deployed` for `deploy`) and a Bulgarian alias written in Latin letters with an ending
  no longer match -- add the form as an alias. Cyrillic aliases are unchanged; the 3 wrong
  Cyrillic triggers of that replay (`пост` on `построй`) are not fixed here.

**v3.14.2** — a task alias no longer matches a different word that starts the same

- **"I restarted" stopped opening the grant application's logbook.** The prompt hook matched a
  long alias word on its first five letters, to meet Bulgarian endings halfway. The alias
  `рестак` (a grant called Restack) and `рестартирам` ("I restart") share five. Replaying 1,784
  human prompts from 48 transcripts (turns no human typed -- compaction summaries, injected and
  meta turns -- taken out first, as Ilya Gorban advised): that alias matched 43 times, 41 of
  them a restart. Now a long alias keeps all of itself but its ending (an article, -ане, a final
  vowel: `страницата` -> `страниц`) and takes an ending of up to five letters. Every word that
  made the false match is a pinned test case. Over the same prompts, task matches went from 744
  to 602 and none was added. Most removed ones were wrong (`quantum` for `quantumreadiness`,
  `cryptographic` for `crypto`, `financial` for `finansirane`). **What it costs:** a spelling
  variant (`виндоус` for `виндовс`), a typo, and a verb from a noun alias (`коментираме` for
  `коментар`) no longer match -- add the variant as an alias.

**v3.14.1** — L2 no longer fires on a logbook written through a heredoc

- **Writes stopped counting as empty reads.** Lesson L2 decided a shell command was a read when a
  read verb (`grep`, `gh`, `curl`…) appeared anywhere in it, including the body of a heredoc. A
  logbook entry written with `python3 - <<'EOF'` that mentioned grep printed nothing, and L2 took
  it for an empty read. Found by replaying 9,908 recorded Bash calls from 48 transcripts through
  the classifier (method suggested by Ilya Gorban, 12 October), starting with a known positive:
  **28 of 120 fires** were such writes. With the fix the same replay gives 92, and every removed
  fire has a heredoc. Not changed: a read verb outside the body (`cat <<'EOF' | grep x`) still
  counts. Not claimed: that the other 92 are all real reads -- a `sed` script or a quoted string
  that contains a verb fires the same way and is not handled here. The `fired` counter on
  existing installs keeps the old fires.

**v3.14.0** — every injected block names itself

- **What Baton puts into the context at session start can be attributed to Baton.** A tool that
  splits a session's context by source asked for it (10 October): context a hook injects lands in
  the turn totals with no label. One SessionStart hook injects up to two blocks that behave
  differently -- the board grows with the tasks, the rules (plugin installs only) stay fixed -- so
  each now opens with a plain first line: `[baton:board vX]`, `[baton:rules vX]`, and
  `[baton:compact vX]` after compaction. About 25 characters each. Not changed: what the blocks
  say, or the UserPromptSubmit and Stop hooks, which carry no marker.

**v3.13.0** — `/clear` instead of a restart

- **A long session no longer asks to be restarted.** From ~200k tokens Baton used to say "write
  the logbook and restart"; with work at that pace it came every hour, and quitting and relaunching
  Claude Code each time was too much (stenly, 9 October). Now the agent writes the logbook of every
  task touched in the session first, then asks for `/clear` in the same window. The fresh context
  gets the board, with a line saying the context was cleared on purpose and the logbooks were just
  written. Before building it, the tools that already do this were surveyed (Continuous-Claude,
  cc-sessions and others): all of them stop at the same place, one command typed by the human,
  because no hook can run `/clear`. Not claimed: that nothing is lost -- what the agent did not put
  in a logbook is gone after `/clear`, as it was after a restart.

**v3.12.3** — L1 compares a heading with the save time

- **A correct heading was called late when another session saw it first.** On 6 October an entry
  headed 11:08 and saved at 11:08 was reported by a Stop at 13:08 as "120 min behind the clock":
  L1 measured the heading against the moment the hook ran. It now measures it against the
  logbook's save time, and the message names that time. Found, reproduced and fixed by
  [Shane Grindle](https://github.com/TheMedpreneur) in
  [PR #1](https://github.com/StanimirTenev/baton/pull/1) -- Baton's first outside contribution,
  with a test that fails on v3.12.2. Not claimed: that every false "behind" is gone -- an edit to
  the same logbook long after the entry moves the save time, and a correct heading can still read
  as behind; that case is rarer, and the old check flagged it too.

**v3.12.2** — says where it works

- **Baton works only where plugin hooks run, and now says so before install.** On 7 October a
  Claude Desktop chat, given Baton, found only the skills: no hooks, no tools. The directory's
  usage page shows 150 installs, all from claude.ai, and 10 active accounts. Anthropic's
  [platform support](https://claude.com/docs/plugins/platform-support) table says why: in a
  claude.ai chat (web, desktop or mobile) hooks are ignored; in Claude Code -- the terminal, the IDE
  extensions and the desktop app's Code tab -- they load. The README now has *Where it works*
  above Install, and the plugin's description carries one sentence of it. No code changed.
  Not claimed: that the installs which never became active were all in the chat -- what the
  directory counts as active is not documented; and Baton has not been tested in Cowork, which
  loads hooks too.
- **The directory's checks, from the review of v3.12.1.** The README named the icon files in
  code formatting, which the pre-submission checklist asks not to do; it now describes them in
  words. The other warnings stay as they are, each for a reason: `plugin.json` names its icon
  because the listing reads it; `install.sh` is flagged, as far as can be seen, for the `bin/` in
  its `#!/usr/bin/env bash` line; the two test files copy the environment to give a test its own
  home folder and read no key; `setup-windows.cmd` downloads Claude Code's own installer from
  claude.ai when Claude Code is missing; and the hook that flags an empty read result lists
  `curl` and `wget` as words to recognise, not commands it runs.

**v3.12.1** — an empty review is not a clean one

- **A review that examined nothing now says BLOCKED and exits non-zero.** `baton_review --tasks`
  once read a different `baton.local.json` than the hooks did -- the repository copy, which names
  no logbook -- found no logbooks, printed an empty list and `cost: $0.000000`, and exited 0.
  Nothing failed: an empty set was checked and looked like a clean result. Now `--tasks` and
  `--stale` stop with `BLOCKED: 0 … examined`, the file they read, and where they looked. A run
  where every item was held back as confidential is not blocked; it already lists what it held.
- **Every review run names its settings file and a fingerprint of it.** Asked publicly on 7 October
  whether Baton compares the configuration too, or only the hook code: only the code. The
  session-start check compares the bytes of the four hooks with their source, and only when
  `source` is set. Now the review prints `config: <path> sha256:<12 hex>`, so two runs that
  disagree can be traced to the file that produced them. Not claimed: that the hooks' own
  configuration is compared with anything at session start. It is still not.

**v3.12.0** — the logbook before the summary thins it, and installed is not running

- **After compaction, the agent writes the logbook first.** Promised publicly on 3 October: Baton did nothing at
  compaction. In fact SessionStart fires then (Claude Code's documentation; Baton sets no
  matcher) -- and v3.11.0, given `source: "compact"`, answers with the whole board and the
  instruction to open the next reply with it, mid-session (run on 5 October). Now, on `source: "compact"`, the agent
  is told to write the entry of every task worked on in this session while the summary still
  holds it, is given the folders holding this session's unrecorded work, and is not shown the
  board. Not a PreCompact hook: Claude Code discards a PreCompact hook's `systemMessage` and gives
  it no `additionalContext` -- it can only block the compaction
  ([hooks reference](https://code.claude.com/docs/en/hooks#precompact)). Tested as Claude Code
  runs the hook (a subprocess, JSON on stdin), and seen once in a real session after a manual
  `/compact` (5 October, `claude -p --resume <id> "/compact"` with the plugin loaded: the
  instruction arrived, the board did not); **not yet seen after an automatic compaction**.
- **The hooks write UTF-8, not `\uXXXX`.** On the author's machine, the same board: v3.11.0 wrote 13,585
  characters of JSON for 5,685 of text, because every Cyrillic letter was escaped; v3.12.0
  writes 5,967 for the same 5,685. All four hooks write UTF-8 bytes. A LinkedIn reader worried this hit Claude Code's
  10,000-character cap. It did not: the documented cap is measured on each parsed field ("For
  JSON output, each field is measured separately", [hooks reference](https://code.claude.com/docs/en/hooks#json-output)),
  so the 5,685 characters were what counted. Not claimed: that the board can never reach the
  cap -- a machine with many tasks can, and then Claude Code shows a path and the first 2,000
  characters.
- **The review tools now work from a plugin-only install.** They "worked from the plugin" on 3 October
  only because the same machine also had the script install's settings. Alone, `baton_review`
  stopped at "NO index" and read no folder a plugin keeps across updates. It now also reads
  `baton.local.json` from `CLAUDE_PLUGIN_DATA`, and names the file it wants when settings are
  missing. `/baton-key` gives the plugin path. The v3.8.0 note saying the review tools do not
  work as a plugin is marked superseded.
- **After an update, the agent says what is new -- once.** Installed from the directory, Baton
  updates itself at the next launch, and Claude Code says only "Plugins changed"
  ([plugin loading](https://code.claude.com/docs/en/plugins/loading#synced-plugins)). Now
  SessionStart remembers the last version this machine ran and, when it changes, asks the agent
  to tell the human in a few lines what is new -- the bold leads of this section -- with the link
  to the release. No network: the notes come from the README that arrived with the update. A
  fresh install is not told it was updated; an install from before v3.12.0 is.
- **The review is offered once.** A new user never learned it existed. The first session-start
  now asks the agent to mention it once -- that it sends text to OpenRouter, that it costs money
  on their own key (about $0.0013 per index review, measured), that it never runs by itself --
  and not again. Not offered when a key is already stored (the key file's presence is checked;
  it is not read).
- **`/baton-doctor` shows whether the hooks really run.** Every hook leaves a heartbeat when it runs;
  `tools/baton_doctor.py` shows when each last ran and says "installed but not running" when
  none has. A hook that has not had its moment yet in a new session (Stop needs a finished turn,
  PostToolBatch a tool call) is shown as ⏳ not yet, not as a failure -- seen live before release. Heartbeats exist only from this version on.
- **The logbook entry gains "Corrections" (done versus asked) and "Changed: old → new".** Both left out
  when empty, and the rule that a secret is written `[secret removed]`. Templates, rules and
  README.
- **A free check of the memory index** (`tools/baton_memory_lint.py`): free, no model, nothing sent -- does every link in a memory
  index lead to a file, and does every memory file have a line. Reports, never edits. On the
  author's index (78 files, 104 links): nothing found, and a planted unlisted file in a copy was
  caught.
- Borrowed ideas, credited: the compaction reminder from claude-memory-compiler
  (`hooks/pre-compact.py`), the doctor from claude-remember (`/remember:doctor`), the entry
  sections from active-memory, the index check from claude-memory-compiler's `lint.py`.

**v3.11.0** — priority in colour, an icon the directory shows, a description people can find

- The board marks each priority with its colour: 🔴 high, 🟡 medium, 🟢 low. The board reaches
  the human as Markdown, which has no coloured text, so the colour is a dot before `[high]`; the
  HTML board (`tools/baton_board.py`) colours the badge itself. Order and wording are unchanged.
- The directory listing showed a letter "B" instead of the icon (seen in the developer portal on
  3 October 2026): the listing did not render the SVG icon. `plugin.json` now points at a PNG of
  the same drawing at 512×512; the SVG stays in the repository.
- `description` opens with what Baton is for (work that survives between sessions) before how it
  works; `keywords` gain the words people search for. The disclosure is unchanged: four local
  hooks, no network requests.

**v3.10.5** — the offer of `/baton-inventory` no longer counts this session's own transcript as
earlier work. Found on 2 October 2026 in a Claude Desktop session that ran in a cloud container:
the container held one transcript, its own, and the hook said "1 earlier conversation" and
offered an inventory of nothing. The hook now reads `session_id` and `transcript_path` from its
input and leaves that transcript out; either one alone is enough. Nothing else changed.

**v3.10.4** — links for the plugin directory listing in `plugin.json`: documentation, support
(issues), privacy (what Baton sends over the network) and terms (the MIT license). Nothing else
changed.

**v3.10.3** — an icon for the plugin directory listing (an SVG drawing of a baton passed
between two hands). Nothing else changed.

**v3.10.2** — before the plugin directory: say what runs, read only the key given to Baton

- The review tools read the OpenRouter key only from `~/.config/baton/env`, where
  `tools/baton_key.py` stores it. `OPENROUTER_API_KEY` in the environment and another tool's
  key file are no longer read: a key that is merely on the machine was not given to Baton to
  send. **If you set the key only in the environment, run `tools/baton_key.py` once.**
- The plugin's description names all four hooks and says they make no network requests;
  the README says what the hooks read (task folders, the session transcript, tool results).
- A test no longer carries real names.

**v3.10.1** — three findings of an external review of v3.10.0, each reproduced first

- **A reinstall with a new task root left `CLAUDE.md` naming the old one** — the marker alone
  ended the run, so hooks and instructions pointed at different folders. The section now has
  an end marker, and the text between the two is rewritten when the task root or logbook
  changes (after a copy). A section without the end marker — every install before this one,
  and rules rewritten by hand — is never written to; the installer warns when it names
  another root or logbook. Existing installs therefore get the warning, not the fix: edit the
  section, or delete it and run the installer again.
- **Stop blocked every turn for an old unrecorded file in a task the session never touched.**
  It now asks only about work saved during this session; the older debt is on the board
  (📝). Not changed: new unrecorded work still hands the turn back.
- **L2 counted MCP writes**: every `mcp__*` was a read, so a delete answering `{}` raised the
  lesson and counted it. Now only names that say they read. L2 counts gathered under v3.10.0
  are not comparable with those after it.

**v3.10.0** — lessons that are counted, and a reminder to restart a long session

- **Lessons L1 and L2** (section "Lessons"): a mistake caught once is counted, not just noted.
  L1 in Stop (the hour of a heading against the clock), L2 in a new PostToolBatch hook,
  `hooks/baton_batch.py` (an empty read result). Both installers and the plugin register it.
  Released after one day of the two-week pilot on Linux, by the human's decision; the pilot's
  measurement (`caught/fired` for L1, recurrences for L2) goes on, and nothing here claims the
  lessons hold yet.
- **Restart reminder** (UserPromptSubmit): every message re-sends the whole context, so a long
  session eats the usage limit — two sessions here had reached ~600k tokens. From ~200k
  (`restart_at`, then every `restart_step` = 100k) the human sees one line and the agent is
  told to write the logbooks first. Read from the last main-thread answer's `usage` in the
  transcript's tail; silent when there is no transcript. `restart_at: 0` turns it off.

**v3.9.0** — look at what is already here before installing, and keep a copy of what is changed

- **`tools/baton_survey.py`**, read-only, run before installing (step 0 of "Before installing").
  It reads what an earlier Claude setup left: `CLAUDE.md` rules about keeping a record, every
  memory folder under `~/.claude/projects/`, the hooks in `settings.json`, the folders sessions
  started in, the folders memory and instructions name -- on any drive -- dated logbook files,
  and folders that already keep a logbook (marking one older than the work beside it). It
  proposes a task root and a logbook name and lists what to ask the human.
  Found on a Windows machine that had worked with Claude for months: dated logbook files in the
  profile folder, memory under `projects/C--Windows-System32/`, work on three drives, an
  older rule for the record and two hooks of its own. **Its first run there proposed the drive
  root `D:\` as the task root** (two of its many folders kept a logbook); a drive root is now never
  proposed, and a folder is proposed only when most of its folders keep the same logbook.
- **The rules the installers add name this machine's task root and logbook.** They said
  "`$BATON_HOME` (default `~/tasks`)" -- a variable set only in the installer's window -- so the
  next session could read `~/tasks` as the task root while the tasks were elsewhere. The same
  filling now happens for the rules a plugin install carries.
- **Both installers keep a copy** of `CLAUDE.md` and `settings.json` as they were
  (`*.before-baton-<time>`) before writing to either. Nothing else changed in what they write:
  the older rules stay, other hooks stay.
- `/baton-inventory` starts from the survey, so it reads every memory folder and the places
  outside the home folder.
- `install.ps1`: Python's messages were garbled through a pipe (an agent's shell, ssh) when a
  path held Cyrillic; both sides use UTF-8 for the run now.
- Not claimed: the survey finds what Claude's own files point at. Work that nothing names is
  not found by it; `/baton-inventory` still walks the home folder for that.

**v3.8.3** — one line on the screen at start: Baton is on

- On the Mac the agent did not show the board in its first reply, and nothing on the screen said
  Baton had loaded -- so it looked as if it had not. The session-start hook now prints **one
  English line** the human sees at once: `🧭 Baton: 8 on your move, 6 ongoing, 8 waiting on
  others. Write anything and the agent opens its reply with the full board.` With no task
  folders yet it says Baton is on and where the folders go; installed twice, it says so.
  English because the hook cannot know the human's language; the board itself still reaches
  only the agent, which shows it in that language.
- The instruction to the agent is stricter: whatever the first message is -- a greeting, a
  question or a task -- the first thing in the first reply is the whole board, then the answer.
- The agent cannot speak first in an interactive session: the hooks' `initialUserMessage`
  applies to `claude -p` only (code.claude.com/docs/en/hooks). So "without being asked" means
  "whatever the human writes first".

**v3.8.2** — check the machine before installing, and ask

- **"Before installing -- for the agent doing it"**, at the top of Install: a real Python 3.8 or
  later (a stand-in does not count), Git for Windows for the plugin on Windows, whether Baton is
  already installed, and which route -- and when something is missing, the agent gives the human
  the command for their system and waits for a yes. Asked for by the author after the Mac test.
- **Both installers check Python the way `run.sh` does**: a candidate counts only if it answers
  as 3.8 or later. `install.sh` took the first `python3` on PATH -- on a Mac without the developer
  tools, the stand-in that opens a dialog; `install.ps1` accepted anything whose `-V` exited 0 --
  the Windows Store stand-in does. With none usable they now stop **before writing anything**,
  name what they found and why it was passed over, and print the command to get Python.
  Checked on Windows with only a stand-in on PATH: exit 1, nothing written.
- Tests: the Python-floor check now asks each interpreter its version (the Mac's 3.9 is plain
  `python3`, so the check had been skipped exactly there), and one review test no longer reads
  the machine's own settings -- both found by the agent on the Mac.

**v3.8.1** — Python 3.8 and 3.9, as the README promised

- **Found on a Mac by its own agent, installing Baton unaided from this repository:** the
  Mac's system Python is 3.9.6, and the SessionStart hook used `str | None` in signatures,
  which Python evaluates at definition time before 3.10. The hook died with a TypeError and
  printed nothing -- Baton was silently absent, the worst way to fail. On 3.8 all three hooks
  died (`list[str]`). Every test and every real session so far had run on 3.12 and 3.14.
- `from __future__ import annotations` in the three hooks (the tools already had it), and
  `tools/baton_review.py` no longer uses a backslash inside an f-string expression, which did
  not even parse before Python 3.12.
- The suite (350 tests) passes under Python 3.8, 3.9 and 3.12. A new test compiles every hook
  and tool with a real 3.8 or 3.9 when the machine has one, and says so when it has not;
  `ast.parse(feature_version=(3, 8))` on a newer Python was tried first and does not catch the
  f-string case.
- The plugin, with 3.9 as the only Python on the path: board, rules and reminder, through
  `run.sh`. 3.8.0's note that the 3.8 check in `run.sh` was not pinned -- this is what it was
  not catching: the check passed a Python the code could not run on.

**v3.8.0** — Baton as a Claude Code plugin

- **Install with one command**: `claude plugin marketplace add StanimirTenev/baton`, then
  `claude plugin install baton@baton`. The install script stays and works as before; nothing
  changes for a script install (the board was compared line by line at every step).
- The same three hooks and four skills. What differs as a plugin: the skills are
  `/baton:baton-…`; the rules come with the session-start board (a plugin's `CLAUDE.md` is never
  loaded); settings and state live in `${CLAUDE_PLUGIN_DATA}`; updates come through Claude Code,
  and **the hooks make no network request**.
- **Python is found at run time** by `hooks/run.sh`: `python3`, `python`, `py`, first that really
  runs. On the Windows test machine `python3` was the Microsoft Store stand-in, which prints
  "Python" and exits 0 without running anything -- a check on the exit code would have taken it.
  On Windows the plugin needs Git for Windows (Git Bash runs the start script).
- **Installed both ways**, the plugin's copy stands down and, at each session start, says which to remove.
- Found by an independent review before release, and fixed: a `CLAUDE.md` in UTF-16 or cp1251
  (PowerShell 5's default) wiped the whole board in plugin mode; three skills still read the
  script install's settings file and named `/baton-plan` without the prefix; the tests depended on
  the runner's own `CLAUDE_CONFIG_DIR`; a local state file had been committed.
- Found by running it for real, and fixed: the plugin data folder is not always created before
  the first hook runs; a session with its own `CLAUDE_CONFIG_DIR` was read as if it were
  `~/.claude` (it "saw" an installer it does not run); settings and state written next to the
  scripts would have been wiped by every plugin update.
- Script installs with `CLAUDE_CONFIG_DIR` set: the skills check now looks in that folder's `skills/`,
  where the installer puts them (it looked in `~/.claude/skills`). A fix; without the variable
  nothing changes.
- The rules text moved to `templates/CLAUDE.md` (a `CLAUDE.md` at a plugin root fails
  `claude plugin validate --strict`); both installers read it from there.
- README: installing as a plugin, **what Baton sends over the network** (a table, read against
  the code), and the Uninstall section, which had listed two hook entries and two of four skills.
- Not checked: Windows without Git for Windows. Not yet as a plugin: the review tools
  (`baton_review`, `baton_sift`, `baton_corpus`) and `/baton-key` -- use the script install for them.
  (Superseded in v3.12.0: `/baton-key` works from the plugin, and the review tools read their
  settings from the plugin's data folder.)

**v3.7.1** — the whole board, said outright

- The instruction to the agent now names the ways a board gets shortened: no summary, no merged
  lines, no "...and the rest", the notes in parentheses included. The first translated board
  shown to the author ended one group with "...(the rest as before)" — exactly that.

**v3.7.0** — the board reaches you in your language

- The session-start board was printed to the human as it is (`systemMessage`), so everything the
  hook writes itself came out in English — the group titles, and whole lines such as the unclosed
  plans and the notes past their shelf life. Only the `next` fields, copied from your headers,
  were in your language. Noticed by the author, whose board was half Bulgarian and half English.
- The hook no longer prints anything to the human. The board goes to the agent with one
  instruction: open the first reply with it, translated into the human's language — every group
  and every line, nothing shortened; task names, file names, commands and identifiers unchanged.
- Not changed: what is checked, the groups, their order. No translations are kept in Baton; the
  agent does it for any language. The cost: you see the board after your first message, not before
  it, and a board the agent is told to show in full is now only as complete as the agent makes it.

**v3.6.1** — the commands the agent hands over name the right folder, for everyone

- The installer now records where the repository is (`repo` in `baton.local.json`). Before, only
  the author's machine had a path (`source`, written by hand), so for every other user the update
  question said `<the Baton repository>` and `/baton-key` pointed at a key that did not exist.
  Found by review before any user met it. If the folder is gone, the message says where to get it.
- Windows gets `python`, not `python3`, in those commands.
- v3.6.0 said transcripts are kept "about a month" and that history survives. The first half is
  now sourced (30 days, `cleanupPeriodDays`); the second was not true as written — the
  documentation lists the prompt history in the same sweep.

**v3.6.0** — a new user with months of Claude Code behind them is offered the inventory

- While the task root is empty and `~/.claude/projects` holds earlier conversations, the session
  starts with the agent offering `/baton-inventory`, with how many there are and the oldest date.
  Once a day; nothing is created until the human confirms each task. Before, the installer
  printed one line about it, once.
- Not measured: how much of months of earlier work the inventory actually recovers. That is a
  separate measurement, and nothing here claims it.

**v3.5.0** — a weekly check for a newer version, if you want one

- At the first session the agent asks whether Baton may check once a week for a newer release.
  Until the answer, nothing reaches the network; `tools/baton_update.py on|off` records it.
- With it on: one request to GitHub a week at session start, two-second timeout. A newer release
  is named with what changed and the command to update, every session until you update. Nothing
  installs on its own. A failed check says so and retries the next day.
- The notice reaches a new user with no tasks yet: the board used to print nothing at all when the
  task root was empty, which is exactly where a new user starts.
- The hook carries its version; a test holds it to the top of this list, so a release that forgets
  to bump it fails.

**v3.4.0** — `/baton-key`: the agent walks a new user to an OpenRouter key, which never enters the conversation

- `tools/baton_key.py` asks for the key without echoing it, refuses to read it from a pipe,
  checks it with OpenRouter before storing it, and stores it mode 600 in `~/.config/baton/env`.
  `--check` reports limit and spend.
- Found on the first real run: OpenRouter's `label` for an unnamed key is the start of the key.
  It was about to be printed; it is not printed at all now, and a test holds it.
- The review reads `~/.config/baton/env` first; the older location is still read.

**v3.3.0** — the names inside the tools are English; the old function names still answer

- Every function, variable and constant inside the tools and hooks renamed to English, by token
  position (a first attempt through `untokenize` reformatted 4,400 lines and was thrown away).
  Nothing a user sees changes: same output, same flags, same header words.
- Scripts outside the repository call the tools by their old names. On the author's machine
  three do (a corpus labeller, a corpus builder, a logbook writer); they were run against this
  version. The old names are kept as aliases, each pinned by a test that fails when it is removed.
- `baton_sift --out` writes `# question=` / `# threshold=` at the top of the TSV, not
  `# vapros=` / `# prag=`.

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
