---
name: baton-doctor
description: Check that Baton's hooks actually run on this machine, not only that Baton is installed - shows when each hook last finished, or that it crashed. Use when the human asks whether Baton is working, when the session-start board did not appear, or after installing or updating Baton.
---

# Baton doctor — installed is not running

A plugin can be installed and enabled and still never run: no Python 3.8+, or on Windows no
Git for Windows (the hooks start through Git Bash). Nothing on the screen says so. Since
v3.12.0 every hook leaves a heartbeat (since v3.20.0 when it finishes, and a crash marker when
it raises; since v3.21.0 a start mark, so a run killed from outside shows); this reads them. It reads only and sends
nothing.

Output in the human's language. Commands and hook names stay as they are.

## Run it

Installed as a plugin (Claude Code fills in both paths):

```
CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" python3 "${CLAUDE_PLUGIN_ROOT}/tools/baton_doctor.py"
```

If the line above still shows the literal text `${CLAUDE_PLUGIN_ROOT}`, this is a script
install: run `python3 <repo>/tools/baton_doctor.py`, where `<repo>` is `repo` in
`~/.claude/baton/hooks/baton.local.json`. On Windows use `python` for `python3`.

## Read it to the human

- **🔴 ALL HOOKS ARE SWITCHED OFF** (since v3.23.0) — `"disableAllHooks": true` is in force in a
  settings file the doctor names; no Baton hook runs, whatever the heartbeats say. Name the file
  and ask the human whether it was meant; never remove the line without their yes.
- **🔴 Installed but not running** — no hook left a heartbeat. Check `python3 --version` (3.8 or
  later) and, on Windows, `where bash`. A hook older than v3.12.0 leaves none either: a new
  session first, then ask again.
- **❌ CRASHED / 🔴 Crashed on its last run** — the hook raised; it exited 0, as a hook must, so
  its check did not happen and nothing else said so. Give the time and the exception class as
  shown, and the command the doctor prints to see the traceback.
- **❌ DID NOT FINISH / 🔴 Did not finish its last run** (since v3.21.0) — the hook started and was
  stopped from outside: killed, or at Claude Code's time limit. Give the start time as shown; it is
  a question ("killed or timed out?"), not a diagnosis. If it repeats, the doctor prints how to
  time the hook by hand.
- **🔴 SessionStart has never run** — the board and the rules are not reaching the agent.
- **✅ Running** — say when SessionStart last ran. A hook marked ⏳ not yet is one whose moment
  has not come yet (Stop needs a finished turn, PostToolBatch a tool call) -- not a failure, so
  do not report it as one. If it is still ⏳ after a turn with tool calls, it is failing.

- **Logbook entries … written unasked / handed back / recorded on the second try / passed** —
  read the four numbers as they are. Unasked against handed back says how often the agent wrote
  the entry without Stop asking; "passed" is a turn Stop asked about and then let through, since
  it never asks twice. No verdict: the human decides what the numbers mean.
- **Lesson L2 … fired / shown / followed by a check: N of M** — say it is a proxy: "a check" is a
  read among the agent's next tool calls after a shown note, which may have been planned anyway.
- **Followed? … fixed after the lesson: N of M** (since v3.21.0, per lesson) — read the numbers as
  they are and say it is a proxy: a new entry written on top of the flagged one counts as fixed.

Do not change anything to fix it without the human's yes.
