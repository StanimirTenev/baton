# Memory layout

Baton's logbooks record what was **done**. This document is about the other half: where an
agent keeps what is **true**, so that the two do not turn into one swelling file.

Set this up once per machine. It needs nothing but a filesystem.

## The shape

```
<memory root>/
├── MEMORY.md                     ← INDEX. One line per file. No content, ever.
├── <project-a>/
│   ├── project_<name>.md         ← SHORT: what is true now
│   ├── project_<name>_history.md ← HISTORY: how it got that way
│   └── feedback_<name>.md        ← rules learned while working on this project
├── <project-b>/
│   └── ...
└── feedback_<general>.md         ← rules that apply everywhere (root, not in a project)
```

For Claude Code the memory root is `~/.claude/projects/<working-directory>/memory/`. Run
`ls ~/.claude/projects/` and take the entry matching your working directory — do not invent
it, do not rename it. Note that Claude Code binds memory to the **directory** the agent was
started from, so always start it from the same place.

**Two levels and stop.** The index is flat. Detail lives in the project folder. There is no
third level — no folder inside a project folder.

## The two kinds of file

### Short file — what is true now

Describes the **state**, not the road to it. New state *replaces* old state; what it
displaces moves to the history file rather than being deleted.

| Section | Holds |
|---|---|
| What / where | a sentence or two, plus paths to the code, machines, access |
| State | what works today, which version, what is deployed |
| Decisions | live decisions with dates and reasons — including directions rejected |
| Known problems | confirmed, unsolved |
| Outstanding | concrete next actions |
| When to open the history | the cases, listed explicitly |

That last section is not decoration. It is what stops the history file from being read for
nothing.

**Size.** Past ~150 lines, a diary has crept in. Move it to the history file.

### History file — how it got here

Chronology: sessions, commits, reviewed changes, superseded decisions with the reasoning
that produced them. No length limit. **Not read by default.**

## File format

```markdown
---
name: <short-name-with-hyphens>
description: <one sentence — this alone decides whether the file gets opened>
metadata:
  type: user | feedback | project | reference
---

Content. Link to another file with [[its-name]].
```

`description` earns its keep: it is read when the file is not.

**Types.** `user` — who the person is and how they prefer to work. `feedback` — guidance
they gave, with the reason it was given. `project` — current work, goals, constraints that
are not visible in the code. `reference` — external resources, addresses, access paths
(paths, never the secrets themselves).

## The index

Pointers only, grouped by project, one line per file:

```markdown
# Memory Index

> Each main file is short and says what is true now. Chronology lives in a separate
> `_history` file, opened only when the short one is not enough.

## <Project A>
- [Title](folder/file.md) — hook: when this file will matter
  - *history:* [what it covers](folder/file_history.md) — only if the short one falls short
```

The hook on the right is for finding the file later, not for summarising it. *"When asked
to bring up the VPN, run…"* works. *"Information about the project"* does not.

**No content in the index. Ever.**

## How this meets Baton

| | holds | read |
|---|---|---|
| memory short file | what is **true now** | every session, automatically |
| memory history file | how the **state** got here — decisions and why | when the short file is not enough |
| `LOGBOOK.md` | what was **done**, session by session, with results | when the task is picked back up |

A task folder and a project memory file usually pair one-to-one. Put the line pointing at
the task folder in `MEMORY.md` — the index is the only thing read at the start of every
session, so a folder it does not name is a folder that does not exist.
