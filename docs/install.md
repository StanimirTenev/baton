# Installing Baton

Part of the [Baton](../README.md) documentation.

**Where it works.** Baton is hooks, so it works where plugin hooks run: Claude Code -- the
terminal, the IDE extensions, and the Code tab of the Claude desktop app. In a claude.ai chat
(web, desktop or mobile) only the skills load and the hooks are ignored
([platform support](https://claude.com/docs/plugins/platform-support)), so nothing is enforced
there. A plugin added from the directory on claude.ai reaches Claude Code on its own at the next
session start; use it from there. Cowork loads hooks too, but Baton has not been tested in it.


## Install

### Before installing -- for the agent doing it

An agent asked to install Baton checks the machine first and tells the human what it found. It
installs nothing else on its own: when something is missing it gives the human the command for
their system and waits for a yes.

0. **What is already here -- before anything is written.** From the clone (or the download):

   ```bash
   python3 tools/baton_survey.py          # read-only; --json for the same as data
   ```

   It reads what an earlier Claude setup left: every `CLAUDE.md` rule about keeping a record,
   every memory folder under `~/.claude/projects/`, the hooks already in `settings.json`, the
   folders memory and instructions name (on any drive), dated logbook files, and folders that
   already keep a logbook. It ends with a proposed task root and logbook name, and the questions
   to ask. **Show the human the report and agree three things before installing:** the task
   root, the logbook name, and whether Baton's rules replace an older rule or sit next to it.
   Then install with those (`BATON_HOME=… BATON_LOGBOOK=… ./install.sh`, or the plugin's two
   questions). Nothing is moved; the work stays where it is and `/baton-inventory` maps it into
   task folders afterwards. The task root is never a drive root.

   The installers keep a copy of `CLAUDE.md` and `settings.json` as they were
   (`*.before-baton-<time>`) before writing to either, and write the chosen task root and
   logbook name into the rules they add.
1. **A Python 3.8 or later that really runs.** Try `python3`, then `python`, then `py` (Windows):
   `python3 -c "import sys; print(sys.version)"` must print a version. A stand-in does not count:
   on Windows `python3` is often the Microsoft Store's, which prints `Python` and nothing else;
   on a Mac without Apple's developer tools, `/usr/bin/python3` opens an "install" dialog instead
   of running -- if a dialog appears, do not accept it on the human's behalf. If none qualifies,
   ask the human to install one:
   - Windows: `winget install -e --id Python.Python.3.12 --scope user` (no administrator)
   - Mac: from https://www.python.org/downloads/macos/, or `xcode-select --install`
   - Linux: the package manager, e.g. `sudo apt install python3`
2. **On Windows, for the plugin: Git for Windows.** `where bash` or `git --version`. If it is
   missing, ask the human to install it (`winget install -e --id Git.Git`), or use the install
   script instead, which does not need it.
3. **Is Baton already here?** A folder `~/.claude/baton/`, or entries in `~/.claude/settings.json`
   whose command runs a `baton_` script, mean the script install; `claude plugin list` showing
   `baton@baton` means the plugin. Do not add the second one -- ask which to keep.
4. **Say which route you will take** -- the plugin, or the install script -- and why, before you
   start. The script also needs `git` for the clone, unless it comes from a folder or a stick.

Both installers check Python themselves as well: with no usable Python they stop before
writing anything, say what they found, and print the command to get one.

### As a Claude Code plugin

```bash
claude plugin marketplace add StanimirTenev/baton
claude plugin install baton@baton
```

Claude Code asks for two things: the folder your task folders live in (default `~/tasks`) and the
name of the logbook file (default `LOGBOOK.md`; use a word in your own language if you prefer).
Skip the questions and the hooks use those same defaults.

**Requires Python 3.8 or later** (`python3`, `python` or `py` -- the first one that really
runs is used). **On Windows it also requires [Git for Windows](https://git-scm.com/downloads/win):**
the hooks start through a small shell script, which Claude Code runs in Git Bash. Without Git
for Windows the hooks cannot start. (Claude Code itself runs without it, so it is worth
checking: `where bash`.) Note that on Windows `python3` is often the Microsoft Store stand-in,
which does nothing; the start script recognises it and moves on to `python`.

As a plugin, Baton behaves as it does when installed by script, with these differences:

- **The skills carry the plugin's name:** `/baton:baton-task`, `/baton:baton-plan`,
  `/baton:baton-inventory`, `/baton:baton-key`, `/baton:baton-doctor`. They take the task root from the session-start
  board, which names it in both installs.
- **The rules** (what `install.sh` appends to `~/.claude/CLAUDE.md`) arrive with the
  session-start board instead, because a plugin's `CLAUDE.md` is never loaded.
- **Settings and state** live in Claude Code's plugin data folder
  (`~/.claude/plugins/data/`), which survives plugin updates.
- **Updates** come through Claude Code, and how depends on where you installed from
  ([plugin loading](https://code.claude.com/docs/en/plugins/loading)):
  - **From Anthropic's plugin directory** (claude.ai, *Discover*): updated on its own. Each time
    Claude Code starts it syncs your account's plugins in the background; when Baton changed you
    see `Plugins changed. Run /reload-plugins to activate.`, and the new version runs from the next
    start. This sync needs a session signed in with your claude.ai account -- not an API key,
    `ANTHROPIC_AUTH_TOKEN`, bare mode or `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`.
  - **From this repository's marketplace** (the two commands above): auto-update is off by
    default for marketplaces other than Anthropic's. Turn it on under `/plugin` -> *Marketplaces*,
    or run `claude plugin update baton@baton`.
  - **After an update, the agent tells you once what is new**, from the notes in this README that
    came with it -- the bold first line of each note under the new version, and a link to the
    release. The hooks do not check for a newer version themselves, so **as a plugin they make
    no network request at all.**
- **Installed both ways** (script and plugin), every hook would run twice. The plugin's copy
  notices the script's entries in `settings.json`, stands down, and at each session start says
  which to remove, until one is.
- **The optional review tools** (`baton_review`, `baton_sift`, `baton_corpus`) read their
  settings from `baton.local.json` in the plugin's data folder -- `~/.claude/plugins/data/`,
  the folder whose name starts with `baton-` -- when it is passed as `CLAUDE_PLUGIN_DATA`; Claude
  Code does not set that variable for commands the agent runs, so it goes on the command line:
  `CLAUDE_PLUGIN_DATA=~/.claude/plugins/data/baton-baton python3 <plugin folder>/tools/baton_review.py --stale`
  (`/baton:baton-key` prints both paths). Without
  settings the review stops before sending anything and names the file it wants (since v3.12.0;
  before, a plugin-only install stopped at "NO index" with nowhere lasting to put them).
  Every run prints the settings file it used and a fingerprint of its bytes
  (`config: <path> sha256:<12 hex>`, or `no config file` when only the environment set it), and a
  run that examined nothing ends with `BLOCKED` and a non-zero exit instead of an empty list
  (since v3.12.1). A run that read some and not others ends with `PARTIAL`, the ones not read
  named, and exit 2 (since v3.17.0).
  `/baton:baton-key` works the same in both installs: the key goes to `~/.config/baton/env`.
- **`/baton:baton-doctor`** says whether the hooks actually run here, not only that the plugin
  is installed (see [Is it running?](how-it-works.md#is-it-running-baton-doctor)).

Uninstall: `claude plugin uninstall baton`. Claude Code deletes the plugin's data folder with
it unless you add `--keep-data`. Your task folders are not touched.

### With the install script

**Linux / macOS:**

```bash
git clone https://github.com/StanimirTenev/baton ~/.baton
~/.baton/install.sh
```

**Windows, fresh machine with no Claude Code** — double-click `setup-windows.cmd`. It
installs Claude Code (Anthropic's own native installer — no administrator, no Node.js, needs
internet) and then Baton, in one step.

**Windows, Claude Code already present** — double-click `install.cmd`, or from a terminal:

```
git clone https://github.com/StanimirTenev/baton %USERPROFILE%\.baton
%USERPROFILE%\.baton\install.cmd
```

No git and no internet on the target machine? Copy this folder onto a USB stick, plug it
in, and double-click `install.cmd`. The installer copies the hooks into your user profile,
so the stick can come straight back out afterwards. Put a Windows **embeddable Python**
(from python.org) in a `python-win\` folder next to `install.cmd` and the installer will
use it when the machine has no Python of its own — so the stick needs nothing installed on
the target at all.

Then open `/hooks` once (or restart) so Claude Code reloads its settings. Or just point an
agent at this repository and say: **"read the README and install it."**

### Dev tools (git, gh, node/npm, ripgrep, python)

Claude Code itself is self-contained, but real work usually wants a toolchain. `tools-windows.cmd`
installs **git, GitHub CLI, Node.js + npm, ripgrep, and Python** via winget. These install
machine-wide, so it needs administrator (accept the UAC prompts); re-running is safe. Git for
Windows gives Claude Code its Bash tool, `gh` drives PRs and issues, `node`/`npm` run MCP servers,
`rg` is fast search. It is kept separate from the Baton install, which needs no administrator.

### Why `install.cmd` and not the `.ps1` directly

On Windows a bare `.ps1` often stops with *"running scripts is disabled on this system"* —
the PowerShell execution policy. `install.cmd` sidesteps it the documented way: a `.cmd`
file is not itself governed by the execution policy, and it launches PowerShell with
`-ExecutionPolicy Bypass` **scoped to that one process**. No administrator, and the
machine's policy is left exactly as it was. It is not a security bypass — it is the
per-process scope PowerShell provides for exactly this.

### What it does, on every OS

Nothing is overwritten. The installer copies the hooks into `~/.claude/baton/` and the
skills into `~/.claude/skills/` (`baton-inventory`, `baton-plan`, `baton-task`, `baton-key`, `baton-doctor`), appends to
`~/.claude/CLAUDE.md`, merges four entries into `~/.claude/settings.json`, and creates
`~/tasks/`. Because the hooks are copied to your profile, the source — a clone, a download,
or a USB stick — can be removed afterwards. Run it twice and the second run reports that
everything is already in place. Run it again with another task root or logbook
(`BATON_HOME`, `BATON_LOGBOOK`) and the Baton section in `CLAUDE.md` is rewritten to match —
only the text between `<!-- Installed by Baton. ... -->` and `<!-- End of Baton section -->`,
after a copy of the file. A section without the end marker (installed before v3.10.1, or
rewritten by hand) is never written to; if it names another task root or logbook, the
installer says so and leaves the edit to you. Add `--dry-run` (or `-DryRun` on Windows) to see the
changes without making them.

Requires Python 3.8 or later — the hooks are Python, one implementation for Linux, macOS and
Windows. The installer takes the first candidate that really answers as 3.8 or later (a stand-in
or an older Python is named and passed over); with none, it stops before writing anything.
The interpreter's absolute path is baked into the hook, so a hook never depends on `PATH`
at run time. On Windows without Python, the installer uses a bundled copy if one sits in
`python-win\` (the USB build carries it), otherwise it prints the one-line,
no-administrator `winget` command to add it for your user.

### Updates: off until you choose

At the first session after installing, the agent asks whether Baton may check once a week for a
newer version. Until you answer, **the hooks never touch the network**. Your answer:

```
python3 tools/baton_update.py on    # one request to GitHub a week, at session start
python3 tools/baton_update.py off   # never
```

With it on, a newer release is named at session start with what changed and the command to
update. Nothing is installed on its own: the hooks run in every session, and code that replaced
itself unasked would put whoever controlled the repository into every one of them. A check that
fails says so, and tries again the next day.

### After a week: one question

About a week after the first session start (counted from Baton's own state file, on this
machine; an install from before this note counts from the update that brought it), the agent
asks you once what has worked, what has not and what you would improve, and names where to tell
the author: [the issues](https://github.com/StanimirTenev/baton/issues). Baton sends nothing --
there is no telemetry; if you would rather not answer, the question does not come back.

## Configuration

| | |
|---|---|
| `BATON_HOME` | where task folders live (default `~/tasks`) |
| `CLAUDE_CONFIG_DIR` | config directory to install into (default `~/.claude`) |
| `BATON_LOGBOOK` | name of the logbook file (default `LOGBOOK.md`) — set it to a word in your own language if you prefer |
| `"tests"` in `baton.local.json` | a test command a human pins per task folder, run after a turn whose entry says tests pass (L4, since v3.21.0; see *What you get*). Only in the file, never from an environment variable |

`BATON_HOME=~/work ./install.sh` bakes that path into the installed hooks.
