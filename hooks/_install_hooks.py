#!/usr/bin/env python3
"""Shared install step for both install.sh and install.ps1.

Writes baton.local.json (task root + logbook name) next to the hooks, then merges the
two hook commands into settings.json without disturbing anything already there.

Usage: _install_hooks.py <settings.json> <hookdir> <barepy> <dry:0|1> <home> <logbook>

`barepy` is a launcher name found on PATH (python / python3 / py) — emitted UNQUOTED so
the command runs under bash, cmd and PowerShell alike; only the script path is quoted.
"""
import json
import os
import sys


def main() -> int:
    settings_path, hookdir, barepy, dry_s, home, logbook = sys.argv[1:7]
    dry = dry_s == "1"

    # 1. local config the hooks read at runtime (so the command needs no env prefix)
    local = os.path.join(hookdir, "baton.local.json")
    if dry:
        print(f"  would write {local}")
    else:
        with open(local, "w", encoding="utf-8") as fh:
            json.dump({"home": home, "logbook": logbook}, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print("  local config written")

    wanted = {
        "SessionStart": f'{barepy} "{os.path.join(hookdir, "baton_session_start.py")}"',
        "Stop": f'{barepy} "{os.path.join(hookdir, "baton_stop.py")}"',
    }

    data = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            print(f"  settings.json is not valid JSON ({exc}) — fix it first, nothing written",
                  file=sys.stderr)
            return 1

    hooks = data.setdefault("hooks", {})
    changed = False

    for event, command in wanted.items():
        entries = hooks.setdefault(event, [])
        existing = [h for group in entries for h in group.get("hooks", [])
                    if "baton_" in str(h.get("command", ""))]
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
        os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)
        tmp = settings_path + ".baton-tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, settings_path)
        print("  settings.json written")

    return 0


if __name__ == "__main__":
    sys.exit(main())
