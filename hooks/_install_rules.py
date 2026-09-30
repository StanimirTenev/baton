"""Append Baton's rules to CLAUDE.md -- with this machine's task root and logbook written in,
and a copy of the file as it was kept next to it.

    python _install_rules.py <template> <CLAUDE.md> <task root> <logbook> <dry 0|1>

Both installers call this. Until v3.8.3 they appended the template as it is, so the rules said
"`$BATON_HOME` (default `~/tasks`)": a variable set only in the window the installer ran in.
The next session read "default ~/tasks" and could start folders there while the tasks were
somewhere else (seen on a Windows machine whose work is on D: and E:, 2026-09-30).
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

MARKER = "Installed by Baton"


def fill(text: str, tasks: str, logbook: str) -> str:
    text = text.replace("`$BATON_HOME` (default `~/tasks`)", f"`{tasks}`")
    return text.replace("$BATON_HOME", tasks).replace("LOGBOOK.md", logbook)


def read(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):       # PowerShell 5 writes UTF-16
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1251")


def backup(path: Path) -> Path:
    """A copy of a file as it was before Baton wrote to it. Never overwrites an older copy."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    copy = path.with_name(f"{path.name}.before-baton-{stamp}")
    shutil.copy2(path, copy)
    return copy


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(errors="replace")      # a Cyrillic path on a cp866 console
    template, target, tasks, logbook, dry = argv[1], Path(argv[2]), argv[3], argv[4], argv[5] == "1"
    existing = read(target) if target.is_file() else ""
    if MARKER in existing:
        print("  instructions already present - left as they are")
        return 0
    if dry:
        print(f"  would append Baton section to {target} (task root {tasks}, logbook {logbook})")
        return 0
    body = fill(Path(template).read_text("utf-8"), tasks, logbook)
    if target.is_file():
        print(f"  copy of CLAUDE.md as it was: {backup(target)}")
        body = "\n\n---\n\n" + body
    target.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8 without BOM, so the file reads cleanly everywhere; the old text is kept as read.
    with target.open("w", encoding="utf-8", newline="") as fh:   # 3.8: no newline= on write_text
        fh.write(existing + body)
    print(f"  instructions appended to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
