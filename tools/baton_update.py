#!/usr/bin/env python3
"""Switch the weekly check for a newer Baton on or off.

    python3 tools/baton_update.py on    # once a week at session start, one request to GitHub
    python3 tools/baton_update.py off   # the hooks never touch the network (the default)

The check only tells: the agent names the new version and the command to update, and nothing
is installed without the human. `on` also records where this repository is, so that command
can name it.
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def local_config() -> Path:
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return claude / "baton/hooks/baton.local.json"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv not in (["on"], ["off"]):
        print(__doc__.strip())
        return 2
    path = local_config()
    if not path.is_file():
        print(f"Baton is not installed here ({path} is missing) — run the installer first.")
        return 1
    cfg = json.loads(path.read_text("utf-8-sig"))
    cfg["update_check"] = argv == ["on"]
    if cfg["update_check"]:
        cfg["repo"] = str(REPO)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, path)
    print("weekly update check: " + ("ON — one request to GitHub a week; nothing installs on its own"
                                     if cfg["update_check"] else "OFF — the hooks never touch the network"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
