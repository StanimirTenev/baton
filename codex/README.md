# Baton in OpenAI Codex CLI

Codex runs the same hooks that Claude Code runs. There is no separate copy for Codex. Each hook reads what Codex sends and works out the host from it (`host()` in `hooks/_baton.py`). Codex's transcript is read by its own reader, and its file edits (`apply_patch`) count as writes. A host the hooks do not recognise is treated exactly like Claude Code.

What this folder holds:

| File | What it is |
|---|---|
| `hooks.json` | the four events Codex has for Baton (SessionStart, UserPromptSubmit, PreToolUse, Stop), each one starting a hook through `hooks/run.sh` |
| `AGENTS.md.snippet` | Baton's working rules. It is a byte-for-byte copy of `templates/CLAUDE.md`, the text the installer appends to `CLAUDE.md` (a test keeps the two identical) |

What has been checked against Codex CLI 0.169.0, and how: the hooks themselves, unchanged, in a live probe of a project-level `.codex/hooks.json` (board, task pointer, Stop hand-back). Then, without a model, this `hooks.json` placed in a scratch `~/.codex`. `codex app-server` → `hooks/list` lists the four hooks, with the PreToolUse matcher, no warnings or errors, and all four `untrusted` until reviewed. Each `command`, run with `sh -c`, `HOME` pointing at that scratch directory and a real Codex payload on stdin, exits 0. The step-4 line writes the rules with the task root filled in. A full Codex session on this exact file has not been run. Nothing here changes an existing `~/.codex` for you.

## Install (one user)

1. Put Baton where the hooks file expects it:

   ```sh
   git clone https://github.com/StanimirTenev/baton ~/.codex/baton
   ```

   `hooks.json` starts each hook as `sh "$HOME/.codex/baton/hooks/run.sh" "$HOME/.codex/baton/hooks/<hook>.py"`. If you clone it somewhere else, edit those paths. Codex runs a hook with the session's directory as its working directory, so the paths have to be absolute.

2. Say where the tasks are. Put `baton.local.json` next to the hooks:

   ```sh
   printf '{"home": "%s", "logbook": "LOGBOOK.md"}\n' "$HOME/tasks" > ~/.codex/baton/hooks/baton.local.json
   ```

   The `BATON_HOME` and `BATON_LOGBOOK` environment variables do the same job, and Codex passes them through to its hooks.

3. Add the hooks. If `~/.codex/hooks.json` does not exist yet, copy this one in:

   ```sh
   cp ~/.codex/baton/codex/hooks.json ~/.codex/hooks.json
   ```

   If the file already exists, merge the four entries into its `"hooks"` object by hand.

4. Add the rules. Codex reads `AGENTS.md`, not `CLAUDE.md`. Use the same script the installers use, so that your task root and logbook name are filled in and a copy of any existing file is kept:

   ```sh
   python3 ~/.codex/baton/hooks/_install_rules.py ~/.codex/baton/codex/AGENTS.md.snippet \
     ~/.codex/AGENTS.md "$HOME/tasks" LOGBOOK.md 0
   ```

   You can paste the snippet in by hand instead. In that case, replace `$BATON_HOME` with your task root yourself.

5. **Trust the hooks once.** Start `codex`, open `/hooks`, review Baton's four hooks and trust them. Codex does not run a hook it has not been told to trust.

## Two things Codex does that you need to know

- **`codex exec` skips untrusted hooks without saying so.** No warning and no error. The run just goes ahead without Baton. If the board never shows up, open `/hooks` in the interactive CLI and check whether the hooks are trusted.
  `--dangerously-bypass-hook-trust` runs them for one invocation. It is meant for automation that already vets the hook source.
- **Editing a hook script does not trigger a new review (0.169.0).** Codex hashes the hook definition in `hooks.json` (the command, the timeout and so on), not the script that the command runs. A changed `baton_stop.py` still counts as trusted. So after a `git pull` in `~/.codex/baton`, Codex will not ask you to review anything. Read what changed (`git -C ~/.codex/baton log -p`) before the next session runs it.

## Firms: use managed hooks

Per-user trust is the wrong control when many machines need the same audited hooks. Trust follows the definition and not the script, so a script that changes after review keeps running unseen. Codex has managed hooks for this case. Define them under `[hooks]` in `requirements.toml`, with the scripts installed by your own tooling in `managed_dir` (`windows_managed_dir` on Windows). Managed hooks are trusted by policy. With `[features].hooks = true` they are enforced even for users who turned hooks off, and `allow_managed_hooks_only = true` keeps other hook sources out. Codex does not distribute the scripts, so update them the way you update anything else you sign off.

The hook commands are the same as in `hooks.json`, with absolute paths under `managed_dir`.

## What Baton does not do under Codex yet

- **The one line for the human.** At session start Baton prints a single line, "🧭 Baton: … on your move" (`systemMessage`). In `codex exec` that line was shown nowhere. The board still reaches the agent, which shows it in its first reply. The interactive CLI was not tested.
- **PostToolBatch and StopFailure.** Codex has neither event, so lesson L2 (`baton_batch.py`) and the record of a failed turn (`baton_stop_failure.py`) do not run. The Skill tool does not exist in Codex either, so skill calls are not counted.
- **Reading the transcript for chat.** The board's "messages since the last entry" count and the answer check at Stop read Claude Code's transcript format. Under Codex they find nothing and stay quiet.
- **Subagents.** Codex keeps a subagent's transcript in a separate rollout file. Stop reads only the main session's file.
- **The transcript format.** Codex calls its transcript format "not a stable interface for hooks". The reader takes the field names from Codex's own code, and only part of them has been seen in a live rollout so far. If the format changes, Stop falls back to what it did before it could read Codex at all: it counts every file saved since the session began as this session's work.
- **Windows** has not been tried under Codex.
