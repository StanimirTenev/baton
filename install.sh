#!/usr/bin/env bash
# Baton installer. Idempotent — running it twice changes nothing the second time.
#
#   ./install.sh                 install into ~/.claude, tasks in ~/tasks
#   BATON_HOME=~/work ./install.sh   put task folders somewhere else
#   ./install.sh --dry-run       print what would change, touch nothing
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS="$CLAUDE_DIR/settings.json"
TASKS="${BATON_HOME:-$HOME/tasks}"
LOGBOOK="${BATON_LOGBOOK:-LOGBOOK.md}"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "baton: needs python3 on PATH (the hooks are Python, so they run the same on Linux, macOS and Windows)" >&2
  exit 1
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
if [ "$DRY_RUN" = 1 ]; then
  say "would append Baton section to $CLAUDE_DIR/CLAUDE.md"
else
  mkdir -p "$CLAUDE_DIR"
  if [ -f "$CLAUDE_DIR/CLAUDE.md" ] && grep -q 'Installed by Baton' "$CLAUDE_DIR/CLAUDE.md"; then
    say "instructions already present — left as they are"
  else
    [ -f "$CLAUDE_DIR/CLAUDE.md" ] && printf '\n\n---\n\n' >> "$CLAUDE_DIR/CLAUDE.md"
    cat "$REPO/CLAUDE.md" >> "$CLAUDE_DIR/CLAUDE.md"
    say "instructions appended to $CLAUDE_DIR/CLAUDE.md"
  fi
fi

# 3. hooks, merged into settings.json without disturbing anything already there
"$PY" - "$SETTINGS" "$REPO" "$TASKS" "$PY" "$DRY_RUN" "$LOGBOOK" <<'PYEOF'
import json, os, sys

settings_path, repo, tasks, py, dry, logbook = sys.argv[1:7]
dry = dry == "1"

env = f'BATON_HOME="{tasks}" BATON_LOGBOOK="{logbook}"'
wanted = {
    "SessionStart": f'{env} "{py}" "{repo}/hooks/baton_session_start.py"',
    "Stop":         f'{env} "{py}" "{repo}/hooks/baton_stop.py"',
}

data = {}
if os.path.exists(settings_path):
    try:
        with open(settings_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        print(f"  settings.json is not valid JSON ({exc}) — fix it first, nothing written", file=sys.stderr)
        sys.exit(1)

hooks = data.setdefault("hooks", {})
changed = False

for event, command in wanted.items():
    entries = hooks.setdefault(event, [])
    existing = [
        h for group in entries for h in group.get("hooks", [])
        if "baton_" in str(h.get("command", ""))
    ]
    if existing:
        for h in existing:
            if h.get("command") != command:
                h["command"] = command
                changed = True
                print(f"  {event}: hook path updated")
                break
        else:
            print(f"  {event}: hook already installed")
        continue
    entries.append({"hooks": [{"type": "command", "command": command, "timeout": 20}]})
    changed = True
    print(f"  {event}: hook installed")

if dry:
    print("  (dry run — settings.json not written)")
elif changed:
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    tmp = settings_path + ".baton-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, settings_path)
    print(f"  settings.json written")
PYEOF

echo
echo "Done. Open /hooks once (or restart) so the harness reloads settings.json."
echo "Then: make a folder in $TASKS, put a $LOGBOOK in it, and the hooks take over."
