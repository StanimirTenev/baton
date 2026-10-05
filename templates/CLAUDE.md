# Baton — task folders and logbooks

<!-- Installed by Baton. https://github.com/StanimirTenev/baton -->

Every task gets a folder. The folder holds the work. A `LOGBOOK.md` inside it holds the
record of what was done, session by session.

**Task root:** `$BATON_HOME` (default `~/tasks`).

## Before starting work on a task

1. Look for its folder: `ls -t "$BATON_HOME"` shows which task was touched most recently.
2. If the folder exists, **read `LOGBOOK.md` before doing anything else** — before
   searching the codebase, before answering, before forming a plan.
3. If it does not exist, create it: `$BATON_HOME/<short-name>/` with a `LOGBOOK.md`.

## While working

Keep the work inside the folder — drafts, scripts, exported data, generated documents,
screenshots. Not on the desktop, not in `/tmp`, not scattered across the home directory.
An artifact nobody can find is an artifact nobody has.

Code that belongs in a repository still lives in the repository. Record the path in the
logbook and move on — the rule is against *scatter*, not against version control.

## After working

Prepend an entry to `LOGBOOK.md`. Newest first, so the top of the file is the present — and read the time for its heading from the clock (`date`), never type it:

```markdown
## YYYY-MM-DD HH:mm — <short title>

### What was asked
...

### Done
| Action | Detail |
|--------|--------|
| ...    | ...    |

### Result
...

### Corrections
(only when what was done differs from what was asked: what, and why)

### Changed: old → new
(only when a value, setting or decision was replaced: `old` → `new`)

### Open / notes
...
```

The two middle sections are left out when there is nothing to put in them. **Never write a
secret** (key, password, token, private URL with a credential) into an entry: write
`[secret removed]` and say where the secret actually lives.

Write it for **the next agent**, not for the human. The next session starts with no memory
of this conversation. It gets this file and nothing else. So record what you would need in
order to continue: what was decided and why, what was verified and how, what is still
unknown, which mistakes were already made and paid for.

## Make the folder findable

A folder nothing points at is invisible. When you create one, add a line to whatever your
harness loads at the start of every session — `MEMORY.md` for Claude Code's memory
directory, otherwise the project's own index:

```markdown
- [<task>](<path to folder>) — one line on when this will matter
```

## Logbook is not memory

Two different jobs, and they must not be merged:

| | holds | read |
|---|---|---|
| **memory / state file** | what is **true now** — current state, live decisions, access paths | every session, automatically |
| **`LOGBOOK.md`** | what was **done** — session by session, in order, with results | when you pick the task back up |

New state replaces old state in the memory file. The logbook only ever grows.

## Enforcement

Three hooks ship with Baton and do not depend on the agent remembering any of the above:

- **SessionStart** lists the task folders grouped by who holds the next move and sorted by
  priority (from each logbook's header), or by last entry when a logbook has no header.
- **Stop** checks whether a task folder has files newer than its `LOGBOOK.md`, and if so
  returns the turn to the agent with a note saying which one is unrecorded.
  It also asks, once per session, for a `done_when` when a task worked on has none.
  And it names a newest entry headed later than the clock, and does not count a header-only
  edit as an entry.
- **UserPromptSubmit** names a task a message touches — by folder or `aliases` — with its last
  entry and next step, so its record is read before anything is proposed.

Work that predates Baton is mapped once with `/baton-inventory`. The skill searches the
machine, you confirm each task's state, and only then does it create folders with
reconstructed logbooks.

A large new goal starts with `/baton-plan`. The agent formulates the goal with you, then runs
research rounds with sources and a verifier. It builds the plan backwards from the goal,
and you decide at every checkpoint. Research is never skipped in favour of a plan written
from memory.

A task parked on purpose gets `state: frozen` in its header. SessionStart lists
it but never offers it as work.

The rule is the fallback. The hooks are what actually holds.

<!-- End of Baton section -->
