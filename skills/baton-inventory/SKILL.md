---
name: baton-inventory
description: Map the work already on this machine into Baton task folders. Use once right after installing Baton, or when asked to find where past work lives, to categorise it and to reconstruct the logbooks.
---

# Baton inventory — map the work that already exists

Baton starts empty, but the machine does not. This walks the machine once, finds the work
that was done before Baton existed, and turns it into task folders — **after the human
confirms**. Nothing is moved, and no folder is created before that confirmation.

Task root and logbook name: read `~/.claude/baton/hooks/baton.local.json`
(`home`, `logbook`; defaults `~/tasks`, `LOGBOOK.md`).

## 1. Scan — four read-only agents in parallel

Launch four read-only (Explore) agents in one message. Each returns one table row per
work item: `name (kebab) | paths | last activity | evidence | proposed state | next step | confidence`.
Tell every agent: skip `node_modules`, virtualenvs, `.git` internals, caches; never print
secrets or key contents; list the existing task folders so they are not reported as new.

1. **Repositories** — every git repo under the home directory: `git log`, branches, tags,
   `git status -sb` (unpushed / dirty work), and **whether a remote exists at all**.
2. **Loose files** — files directly in the home directory, Desktop, Documents, Downloads.
   Group related files into one item. Check what still runs: `crontab -l`, user timers.
3. **Memory and history** — the Claude Code memory directory, `~/.claude/history.jsonl`
   (sample it by date), and the transcripts under `~/.claude/projects/` (headers only —
   they are large). Also: topics that appear in history but not in memory.
4. **Project folders** — the remaining top-level folders in the home directory.

## 2. Consolidate — state comes from memory, places come from files

- **Places** (where the work lives) — trust the file agents.
- **State** (how finished it is) — trust memory and history. File dates and git logs say
  when something was touched, not whether it is done. When a file agent contradicts memory
  ("not released yet" vs memory "live since …"), memory wins; note the correction.
- States: `aktivna` · `chakashta` (someone/something external is on the hook) ·
  `postoyanna` (recurring) · `zamrazena` (parked) · `priklyuchila` (done) · junk · unclear.

Write the result to `<task root>/baton/INVENTORY-<date>.md` (create `baton/` if needed):
new tasks with a next step, recurring products, frozen, done, files that belong to
**existing** tasks, unclear items, junk candidates, and **risks found on the way** (repos
without a remote, world/group-readable private keys, stale memory claims).

## 3. Ask — the human decides the state

Show a short table grouped as above and ask. Do not proceed on your own reading of
"how finished" — that judgement belongs to the human. Typical answers: which items are
done, which unclear items to drop, whether frozen items get folders.

## 4. Apply — only what was confirmed

- One folder per confirmed item with a next step, and for recurring products. Frozen items
  may get a folder with `sastoyanie: zamrazena` (SessionStart lists them but never offers
  them as work) or go into one `<task root>/ARCHIVE.md` index — ask which.
- Each new logbook opens with the header, then **one entry marked as reconstructed**:

```markdown
---
sastoyanie: aktivna          # aktivna | chakashta | postoyanna | zamrazena | priklyuchila
na_hod: "nie"                # nie = us; otherwise who/what we wait for
kriterii_zavarshvane: "…"    # when is it done
vremevi_kriterii: po_izbor   # po_izbor | postoyanno | YYYY-MM-DD
sledvashto: "…"              # the next concrete action
prioritet: sreden            # visok | sreden | nisak
---

## YYYY-MM-DD — reconstructed from the inventory

**Reconstructed on YYYY-MM-DD** from files, git, memory and history. Not a record kept
during the work; the state was confirmed by the human on that date.

### Where the work lives
- paths (repositories stay where they are — record the path, do not move)

### Open / notes
- …
```

- For existing tasks: prepend a short "references from the inventory" entry listing the
  files that live outside their folder.
- Add one line per new folder to `MEMORY.md` (or whatever the session loads first).
- Risks (missing remote, key permissions, stale memory): report them; fix only what the
  human approves.

## 5. Verify

Run the SessionStart hook by hand and check the new folders land in the right groups:

```bash
python3 ~/.claude/baton/hooks/baton_session_start.py </dev/null
```

Then log the inventory itself in `<task root>/baton/<logbook>`.
