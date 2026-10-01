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
END = "<!-- End of Baton section -->"


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


def section(text: str) -> tuple[int, int] | None:
    """Where Baton's section is: from its `# Baton` heading (or the marker line) to the end
    marker. None when there is no end marker -- written before v3.10.1, or by hand."""
    mark = text.find(MARKER)
    end = text.find(END, mark)
    if mark < 0 or end < 0:
        return None
    start = text.rfind("\n", 0, mark) + 1
    heading = text.rfind("# Baton", 0, start)
    if heading >= 0 and (heading == 0 or text[heading - 1] == "\n") \
            and not text[heading:start].strip("\n").count("\n"):
        start = heading
    return start, end + len(END)


def reinstall(existing: str, template: Path, target: Path, tasks: str, logbook: str,
              dry: bool) -> int:
    """A second install. 2026-10-01, external review of v3.10.0: a reinstall with a new task
    root left CLAUDE.md naming the old one, because the marker alone ended the run -- the
    hooks and the agent's instructions then pointed at different folders.

    Between the two markers the text is Baton's: written fresh when the task root or logbook
    changed, after a copy of the file. A section without the end marker is somebody's own
    (an older Baton, or rules rewritten by hand, in another language): never written to, but
    if it does not name this task root and logbook, said so loudly."""
    span = section(existing)
    if span is None:
        home = str(Path.home())
        short = "~" + tasks[len(home):] if tasks.startswith(home) else tasks
        part = existing[existing.find(MARKER):]
        if (tasks in part or short in part) and logbook in part:
            print("  instructions already present - left as they are")
        else:
            print(f"  WARNING: the Baton section in {target} does not name {tasks} and {logbook}.\n"
                  "  It was written by an older Baton or edited by hand, so it is left as it is:\n"
                  "  edit it, or delete the section and run the installer again.")
        return 0
    body = fill(template.read_text("utf-8"), tasks, logbook).strip("\n")
    start, end = span
    if existing[start:end] == body:
        print("  instructions already present - left as they are")
        return 0
    if dry:
        print(f"  would update the Baton section in {target} (task root {tasks}, logbook {logbook})")
        return 0
    print(f"  copy of CLAUDE.md as it was: {backup(target)}")
    with target.open("w", encoding="utf-8", newline="") as fh:
        fh.write(existing[:start] + body + existing[end:])
    print(f"  Baton section updated in {target}")
    return 0


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(errors="replace")      # a Cyrillic path on a cp866 console
    template, target, tasks, logbook, dry = argv[1], Path(argv[2]), argv[3], argv[4], argv[5] == "1"
    existing = read(target) if target.is_file() else ""
    if MARKER in existing:
        return reinstall(existing, Path(template), target, tasks, logbook, dry)
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
