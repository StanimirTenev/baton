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

```bash
git clone https://github.com/StanimirTenev/baton ~/.baton
~/.baton/install.sh
```

Then open `/hooks` once (or restart) so Claude Code reloads its settings.

Or just point an agent at this repository and say: **"read the README and install it."**
That is the intended path — the instructions below are written to be executed, not admired.

Nothing is overwritten. The installer appends to `~/.claude/CLAUDE.md`, merges two entries
into `~/.claude/settings.json`, and creates `~/tasks/`. Run it twice and the second run
reports that everything is already in place. `./install.sh --dry-run` shows the changes
without making them.

Requires `python3` on PATH — the hooks are Python so that one implementation covers Linux,
macOS and Windows.

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

**SessionStart** injects the recently touched task folders and the date of each last entry,
so a session never opens blind:

```
Baton — task folders in /home/you/tasks, most recently touched first:
- migrate-billing — last entry 2026-03-14 17:20: schema diff, two columns unresolved
- broken-disk — last entry 2026-03-09 20:41: disk identified, procedure written
```

**Stop** checks whether any task folder holds a file newer than its `LOGBOOK.md`. If one
does, the turn is handed back with a note naming it. The test is deliberately narrow: a
session that touched no task folder is never interrupted, and `stop_hook_active` is honoured
so it can block at most once per turn.

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

`BATON_HOME=~/work ./install.sh` bakes that path into the installed hooks.

## Uninstall

Remove the two `baton_` entries from `~/.claude/settings.json`, delete the Baton section
from `~/.claude/CLAUDE.md`, and remove `~/.baton`. Your task folders are plain directories
of plain Markdown — they keep working without any of this, which is the point.

## Not solved here

No syncing between machines. Each machine keeps its own task folders; if you work across
several, put the root on shared storage yourself, and think first about what belongs on it.

No enforcement of quality. The Stop hook can tell that a logbook was not written. It cannot
tell that what was written is any good.

MIT licensed. Issues and pull requests welcome.
