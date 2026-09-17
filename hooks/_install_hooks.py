#!/usr/bin/env python3
"""Shared install step for both install.sh and install.ps1.

Writes baton.local.json (task root + logbook name) next to the hooks, then merges the
two hook commands into settings.json without disturbing anything already there.

Usage: _install_hooks.py <settings.json> <hookdir> <pyexe> <dry:0|1> <home> <logbook>

`pyexe` is the ABSOLUTE path to the Python interpreter. The hooks are installed in the
exec ("args") form — `command` is that interpreter, spawned directly with the script as an
argument, no shell. That sidesteps the whole Windows tangle at once: no PATH lookup (a hook
runs in whatever environment the harness gives it, which may not carry Python on PATH), no
quoting, no space-in-path breakage, no PowerShell-vs-bash difference.
"""
import json
import os
import sys


def main() -> int:
    settings_path, hookdir, pyexe, dry_s, home, logbook = sys.argv[1:7]
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
        "SessionStart": os.path.join(hookdir, "baton_session_start.py"),
        "Stop": os.path.join(hookdir, "baton_stop.py"),
    }

    def is_baton(h):
        blob = str(h.get("command", "")) + " ".join(h.get("args", []) or [])
        return "baton_" in blob

    data = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except Exception as exc:
            print(f"  settings.json is not valid JSON ({exc}) - fix it first, nothing written",
                  file=sys.stderr)
            return 1

    hooks = data.setdefault("hooks", {})
    changed = False

    for event, script in wanted.items():
        entry = {"type": "command", "command": pyexe, "args": [script], "timeout": 20}
        groups = hooks.setdefault(event, [])
        existing = [h for group in groups for h in group.get("hooks", []) if is_baton(h)]
        if existing:
            for h in existing:
                if h.get("command") != pyexe or h.get("args") != [script]:
                    h.pop("command", None); h.pop("args", None)
                    h.update({"command": pyexe, "args": [script]})
                    changed = True
                    print(f"  {event}: hook updated")
                    break
            else:
                print(f"  {event}: hook already installed")
            continue
        groups.append({"hooks": [entry]})
        changed = True
        print(f"  {event}: hook installed")

    if dry:
        print("  (dry run - settings.json not written)")
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
