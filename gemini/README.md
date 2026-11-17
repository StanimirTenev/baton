# Baton in Google Gemini CLI

Gemini CLI runs the same hooks that Claude Code runs. There is no separate copy for Gemini. This folder is a Gemini CLI *extension* whose hooks start the shared scripts in `../hooks`, and each script works out the host from what Gemini sends (`host()` in `hooks/_baton.py`). Under Gemini the prompt hook sends its task pointer as `additionalContext`, the only form Gemini passes to the model. A host the hooks do not recognise is treated exactly like Claude Code.

What this folder holds:

| File | What it is |
|---|---|
| `gemini-extension.json` | the extension manifest (name `baton`, the same version as the Claude Code plugin) |
| `hooks/hooks.json` | the four Gemini events Baton uses (SessionStart, BeforeAgent, BeforeTool, AfterAgent), each starting a hook through `../hooks/run.sh`. Timeouts are in milliseconds, which is what Gemini reads |
| `GEMINI.md.snippet` | Baton's working rules. It is a byte-for-byte copy of `templates/CLAUDE.md` (a test keeps the two identical). It is deliberately not called `GEMINI.md`: Gemini would load that file from the extension as it is, with the task root unfilled |

What has been checked against Gemini CLI 0.68.0, and how. **With a live model, headless only** (17.11, v3.38.0, Linux; `gemini -p`, Gemini 3.1 Pro preview and Gemini 3 Flash preview, an API key in `GEMINI_API_KEY`, in a scratch `HOME`): all four hooks ran in a real session; the board and the task pointer reached the model (each answered a question only that channel held, with no tool call; a control run with `-e none` got `UNKNOWN`); a new session took back a decision, the work left and the criterion of done from the logbook; a file written and left without an entry was handed back at AfterAgent once it was past Stop's 90-second grace, at most twice a turn; and an entry written after it ended the hand-backs. In the same day's three-host handoff (Claude Code, then Codex CLI, then Gemini CLI, then Claude Code on one logbook) Gemini read the other two hosts' entries and added its own without touching theirs. The interactive CLI was not run, so how the `🧭 Baton` line and a hand-back look in its screen is not known.

Before that, without a model: this folder was linked into a scratch `HOME` with the real `gemini extensions link`. The CLI's own `ExtensionManager` loaded it, Gemini's own `HookRegistry`, `HookPlanner`, `HookRunner` and `HookAggregator` (imported from the installed bundle) ran the hooks, and the folder was marked untrusted. The board reached the model's context and the human. The task pointer reached the model's context. The Stop hand-back became the next prompt, both times. No hook was killed by its timeout, and no warning was raised. What the CLI does with each hook's output after that was read in its code, not run.

## Install (one user)

1. Put Baton anywhere, for example:

   ```sh
   git clone https://github.com/StanimirTenev/baton ~/.gemini/baton
   ```

2. Say where the tasks are. Put `baton.local.json` next to the hooks:

   ```sh
   printf '{"home": "%s", "logbook": "LOGBOOK.md"}\n' "$HOME/tasks" > ~/.gemini/baton/hooks/baton.local.json
   ```

   `BATON_HOME` and `BATON_LOGBOOK` also reach the hooks, except in Gemini's strict environment mode (`GITHUB_SHA` set, or `SURFACE=Github`), which drops them. The file always works.

3. **Link** the extension. Do not install it:

   ```sh
   gemini extensions link ~/.gemini/baton/gemini
   ```

   Gemini asks you to confirm (`--consent` skips the question). A linked extension stays where it is, so its hooks find the shared scripts at `${extensionPath}/../hooks`. `gemini extensions install <path>` copies only this folder, and the hooks would then point at a `../hooks` that is not there. Installing from the Git URL does not work either: Gemini takes an extension from the repository root, and the root `hooks/hooks.json` belongs to Claude Code.

4. Add the rules. Gemini reads `~/.gemini/GEMINI.md`. Use the same script the installers use, so that your task root and logbook name are filled in and a copy of any existing file is kept:

   ```sh
   python3 ~/.gemini/baton/hooks/_install_rules.py ~/.gemini/baton/gemini/GEMINI.md.snippet \
     ~/.gemini/GEMINI.md "$HOME/tasks" LOGBOOK.md 0
   ```

5. Check it. `gemini extensions list` should show `baton` with its path and `Enabled (User): true`. Gemini's docs say `/hooks panel` in the interactive CLI lists the hooks; that was not tried.

6. After a session, ask whether the hooks actually ran:

   ```sh
   python3 ~/.gemini/baton/tools/baton_doctor.py
   ```

   Under Gemini the hooks keep their state beside themselves, in `~/.gemini/baton/hooks`, and the doctor reads that folder when nothing under `~/.claude` has a heartbeat (since 3.39.0; before, it said NEVER RAN). On a machine that also runs Baton in Claude Code, the doctor reads Claude Code's folder first; point it at Gemini's with `CLAUDE_PLUGIN_DATA=~/.gemini/baton/hooks python3 ~/.gemini/baton/tools/baton_doctor.py`. The first line names the folder it read. The doctor uses Claude Code's event names: UserPromptSubmit is Gemini's BeforeAgent, Stop is AfterAgent. PostToolBatch and StopFailure stay "not yet", because Gemini has neither event.

Why an extension rather than hooks in `~/.gemini/settings.json`: with folder trust on, Gemini drops the hooks from settings in an untrusted folder, because it labels user hooks as project hooks. Its hook registry still runs extension hooks there (run through the registry with the folder marked untrusted; that the extension loader ignores folder trust for hooks was read in its code, not run).

Updating: `git pull` in the clone. A linked extension reads the folder in place, so the next session runs the new hooks. Read what changed (`git -C ~/.gemini/baton log -p`) before it does.

## What Baton does not do under Gemini yet

- **Lesson L1 is silent.** Gemini has no advisory channel before a tool runs. `BeforeTool` can only block a tool or rewrite its input, and Baton's L1 note is advice, never a block. `baton_pretool.py` does not read Gemini's tool names yet either (`write_file`, `replace`, `run_shell_command`). The BeforeTool hook does run on those three tools (about 0.1 s each) and says nothing. The place for the note is `AfterTool`, which is not wired up yet. Since 3.39.0 Stop does hand back, under Gemini as under the other hosts, a top entry headed more than two minutes after its logbook was saved; an hour typed behind the clock is still only L1's.
- **No subagent event.** Gemini 0.68.0 has no SubagentStop or SubagentStart. Whether its tool hooks fire for a subagent's tool calls is not known.
- **The prompt hook also fires on Baton's own hand-back.** When Stop hands a turn back, Gemini sends the reason as a new prompt and runs BeforeAgent on it. If that text names a task the session has not been pointed to yet, the pointer for it is added to the model's context. It happens once per task per session, so it cannot loop, but the pointer repeats what the hand-back already says.
- **Gemini's transcript is not read.** Stop reads it as Claude Code's format and finds no tool call in it. In 3.36.0 that meant counting every file saved since the session began as this session's work, other processes' files included, as with Codex before its reader. Since 3.37.0 a transcript that opens but holds no recognised call reads as "did nothing": a newer file beside a logbook written during the session is not handed back. Run without a model against the 3.37.0 hooks: a newer file beside a logbook nobody wrote is still handed back, as before. A subagent's transcript is `<session id>.jsonl`, Claude Code's own shape, so a hook called for a Gemini subagent (if Gemini calls any) is not known to be Gemini. The board's "messages since the last entry" count, the answer check at Stop and the prompt hook's token reminder read Claude Code's transcript format, so under Gemini they find nothing and stay quiet.
- **The board arrives as data.** Gemini's system prompt tells the model to treat `<hook_context>` as read-only data and not as commands. The board asks to be shown in the first reply; in the live run of 17.11 the model showed it, in part or whole, in four of the first five calls, and not in the one whose question asked for the answer alone.
- **PostToolBatch and StopFailure.** Gemini has neither event, so lesson L2 (`baton_batch.py`) and the record of a failed turn (`baton_stop_failure.py`) do not run.
- **A live session needs a key.** Google's free tier refuses Gemini CLI (`IneligibleTierError`); the live run of 17.11 used an API key (`GEMINI_API_KEY`). Only the headless mode has been run.
- **Another session id at AfterAgent.** In three of eight live calls Gemini sent AfterAgent with a different `session_id` than SessionStart and BeforeAgent. Why is not known. The doctor takes such a Stop as the end of the open turn before it (since 3.39.0); whether it can confuse Stop's limit of two hand-backs a turn is untested.
- **Windows** has not been tried. There Gemini runs hooks through PowerShell, and the commands here start `sh`.
