#!/usr/bin/env bash
# Baton installer (Linux / macOS). Idempotent — running it twice changes nothing.
#
#   ./install.sh                    install into ~/.claude, tasks in ~/tasks
#   BATON_HOME=~/work ./install.sh  put task folders somewhere else
#   BATON_LOGBOOK=DNEVNIK.md ...    logbook filename in your own language
#   ./install.sh --dry-run          print what would change, touch nothing
#
# On Windows use install.cmd instead — it dodges the PowerShell execution policy.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS="$CLAUDE_DIR/settings.json"
INSTALL="$CLAUDE_DIR/baton"           # hooks are copied here, so the source (a clone, a
HOOKDIR="$INSTALL/hooks"              # flash drive, a download) can go away afterwards
TASKS="${BATON_HOME:-$HOME/tasks}"
LOGBOOK="${BATON_LOGBOOK:-LOGBOOK.md}"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "baton: needs python3 on PATH (the hooks are Python, one implementation for every OS)" >&2
  exit 1
fi
# absolute interpreter path — baked into the hook so it never depends on PATH at run time
PYEXE="$("$PY" -c 'import sys; print(sys.executable)')"

say() { printf '  %s\n' "$*"; }

echo "Baton"
say "repo:     $REPO"
say "config:   $CLAUDE_DIR"
say "tasks:    $TASKS"
say "logbook:  $LOGBOOK"
[ "$DRY_RUN" = 1 ] && say "(dry run — nothing will be written)"
echo

# 1. task root
if [ -d "$TASKS" ]; then
  say "task root exists"
else
  say "create task root"
  [ "$DRY_RUN" = 1 ] || mkdir -p "$TASKS"
fi

# 2. instructions
if [ -f "$CLAUDE_DIR/CLAUDE.md" ] && grep -q 'Installed by Baton' "$CLAUDE_DIR/CLAUDE.md"; then
  say "instructions already present — left as they are"
elif [ "$DRY_RUN" = 1 ]; then
  say "would append Baton section to $CLAUDE_DIR/CLAUDE.md"
else
  mkdir -p "$CLAUDE_DIR"
  [ -f "$CLAUDE_DIR/CLAUDE.md" ] && printf '\n\n---\n\n' >> "$CLAUDE_DIR/CLAUDE.md"
  cat "$REPO/CLAUDE.md" >> "$CLAUDE_DIR/CLAUDE.md"
  say "instructions appended to $CLAUDE_DIR/CLAUDE.md"
fi

# 3. copy the runtime hooks to a permanent location, so the source can be removed
if [ "$DRY_RUN" = 1 ]; then
  say "would copy hooks to $HOOKDIR"
else
  mkdir -p "$HOOKDIR"
  cp "$REPO/hooks/baton_session_start.py" "$REPO/hooks/baton_stop.py" "$HOOKDIR/"
  say "hooks copied to $HOOKDIR"
fi

# 3b. skills — /baton-inventory (map existing work) and /baton-plan (goal → research → plan)
for skill in "$REPO"/skills/*/; do
  name="$(basename "$skill")"
  if [ "$DRY_RUN" = 1 ]; then
    say "would copy skill to $CLAUDE_DIR/skills/$name"
  else
    mkdir -p "$CLAUDE_DIR/skills/$name"
    cp "$skill/SKILL.md" "$CLAUDE_DIR/skills/$name/"
    say "skill copied to $CLAUDE_DIR/skills/$name"
  fi
done

# 4. local config + hooks, merged into settings.json without disturbing anything else
"$PY" "$REPO/hooks/_install_hooks.py" "$SETTINGS" "$HOOKDIR" "$PYEXE" "$DRY_RUN" "$TASKS" "$LOGBOOK"

echo
echo "Done. Open /hooks once (or restart) so the harness reloads settings.json."
echo "Then: make a folder in $TASKS, put a $LOGBOOK in it, and the hooks take over."
echo "Existing work on this machine? Run /baton-inventory once to map it into task folders."
echo "A big new goal? Start it with /baton-plan (research rounds, then the plan)."
