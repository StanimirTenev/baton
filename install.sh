#!/usr/bin/env bash
# Baton installer (Linux / macOS). Idempotent — running it twice changes nothing, and a
# second run keeps the task root and logbook name the first one was given.
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

# A real Python 3.8 or later, checked before anything is written. Not just the first
# `python3` on PATH: on a Mac without the developer tools that is a stand-in which opens an
# "install" dialog instead of running, and a Mac's own 3.9 once took the hooks down in
# silence because the code needed 3.10 (2026-09-30). A candidate counts only if it answers.
PY=""
SEEN=""
for cand in python3 python; do
  exe="$(command -v "$cand" 2>/dev/null || true)"
  [ -n "$exe" ] || continue
  said="$("$exe" -c 'import sys; print("baton-ok" if sys.version_info >= (3, 8) else "old %d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
  if [ "$said" = "baton-ok" ]; then PY="$exe"; break; fi
  SEEN="$SEEN
    $exe -> ${said:-did not run}"
done
if [ -z "$PY" ]; then
  echo "baton: needs Python 3.8 or later -- the hooks are Python. Nothing has been installed." >&2
  [ -n "$SEEN" ] && echo "  found, not usable:$SEEN" >&2
  case "$(uname -s)" in
    Darwin) echo "  On this Mac: install Python from https://www.python.org/downloads/macos/" >&2
            echo "  (or run: xcode-select --install -- Apple's developer tools include python3)." >&2 ;;
    *)      echo "  Install it with the system's package manager, e.g.: sudo apt install python3" >&2
            echo "  (Fedora: sudo dnf install python3; Alpine: apk add python3)." >&2 ;;
  esac
  echo "  Then run this installer again." >&2
  exit 1
fi
# absolute interpreter path — baked into the hook so it never depends on PATH at run time
PYEXE="$("$PY" -c 'import sys; print(sys.executable)')"

# A reinstall keeps the task root and logbook it was given the first time, unless new ones
# are passed. 2026-09-28: a plain `./install.sh` wrote ~/tasks and LOGBOOK.md over
# ~/zadachi and DNEVNIK.md, and every hook went quiet looking at an empty folder.
PREV="$HOOKDIR/baton.local.json"
if [ -f "$PREV" ]; then
  if [ -z "${BATON_HOME:-}" ]; then
    v="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8-sig")).get("home", ""))' "$PREV" 2>/dev/null || true)"
    [ -n "$v" ] && TASKS="$v"
  fi
  if [ -z "${BATON_LOGBOOK:-}" ]; then
    v="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8-sig")).get("logbook", ""))' "$PREV" 2>/dev/null || true)"
    [ -n "$v" ] && LOGBOOK="$v"
  fi
fi

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
# with this machine's task root and logbook written in; a copy of the old file is kept
"$PY" "$REPO/hooks/_install_rules.py" "$REPO/templates/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md" \
  "$TASKS" "$LOGBOOK" "$DRY_RUN"

# 3. copy the runtime hooks to a permanent location, so the source can be removed
if [ "$DRY_RUN" = 1 ]; then
  say "would copy hooks to $HOOKDIR"
else
  mkdir -p "$HOOKDIR"
  cp "$REPO/hooks/baton_session_start.py" "$REPO/hooks/baton_stop.py" "$REPO/hooks/baton_prompt.py" "$HOOKDIR/"
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
"$PY" "$REPO/hooks/_install_hooks.py" "$SETTINGS" "$HOOKDIR" "$PYEXE" "$DRY_RUN" "$TASKS" "$LOGBOOK" "$REPO"

echo
echo "Done. Open /hooks once (or restart) so the harness reloads settings.json."
echo "Then: make a folder in $TASKS, put a $LOGBOOK in it, and the hooks take over."
echo "Existing work on this machine? Run /baton-inventory once to map it into task folders."
echo "A big new goal? Start it with /baton-plan (research rounds, then the plan)."
