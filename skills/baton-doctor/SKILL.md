---
name: baton-doctor
description: Check that Baton's hooks actually run on this machine, not only that Baton is installed - shows when each hook last ran. Use when the human asks whether Baton is working, when the session-start board did not appear, or after installing or updating Baton.
---

# Baton doctor — installed is not running

A plugin can be installed and enabled and still never run: no Python 3.8+, or on Windows no
Git for Windows (the hooks start through Git Bash). Nothing on the screen says so. Since
v3.12.0 every hook leaves a heartbeat when it runs; this reads them. It reads only and sends
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

- **🔴 Installed but not running** — no hook left a heartbeat. Check `python3 --version` (3.8 or
  later) and, on Windows, `where bash`. A hook older than v3.12.0 leaves none either: a new
  session first, then ask again.
- **🔴 SessionStart has never run** — the board and the rules are not reaching the agent.
- **✅ Running** — say when SessionStart last ran. A single hook marked NEVER RAN is usually one
  whose moment has not come yet (Stop needs a finished turn, PostToolBatch a tool call); if it is
  still never after a turn with tool calls, it is failing.

Do not change anything to fix it without the human's yes.
