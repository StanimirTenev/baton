"""A reinstall that changes the task root updates the instructions too.

External review of v3.10.0 (2026-10-01): a second install with `second` and `SECOND.md`
rewrote baton.local.json, but CLAUDE.md still named `first` and `FIRST.md` -- the marker alone
ended the run. Hooks and instructions then pointed at different folders.

Between the two markers the text is Baton's. Without the end marker it is somebody's own --
an older install, or rules rewritten by hand (this machine's are in Bulgarian) -- and it is
never written to, only warned about.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "hooks" / "_install_rules.py"
TEMPLATE = ROOT / "templates" / "CLAUDE.md"


def _install(target, tasks, logbook, dry="0", home=None):
    env = None
    if home:
        import os
        env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    r = subprocess.run([sys.executable, str(RULES), str(TEMPLATE), str(target), tasks, logbook, dry],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_a_new_task_root_rewrites_only_batons_section(tmp_path):
    target = tmp_path / "CLAUDE.md"
    target.write_text("# my rules\n\nkeep this\n", "utf-8")
    _install(target, "/x/first", "FIRST.md")
    with target.open("a", encoding="utf-8") as fh:
        fh.write("\n# added later by hand\n")
    before = target.read_text("utf-8")
    out = _install(target, "/x/second", "SECOND.md")
    text = target.read_text("utf-8")
    assert "updated" in out
    assert "/x/second" in text and "SECOND.md" in text
    assert "/x/first" not in text and "FIRST.md" not in text
    assert text.startswith("# my rules\n\nkeep this\n") and text.endswith("# added later by hand\n")
    assert text.count("Installed by Baton") == 1 and text.count("# Baton") == 1
    copies = sorted(tmp_path.glob("CLAUDE.md.before-baton-*"))
    assert copies and copies[-1].read_text("utf-8") == before


def test_a_dry_run_says_it_would_and_writes_nothing(tmp_path):
    target = tmp_path / "CLAUDE.md"
    _install(target, "/x/first", "FIRST.md")
    before = target.read_bytes()
    out = _install(target, "/x/second", "SECOND.md", dry="1")
    assert "would update" in out and target.read_bytes() == before


def test_the_same_values_change_nothing(tmp_path):
    target = tmp_path / "CLAUDE.md"
    _install(target, "/x/first", "FIRST.md")
    before = target.read_bytes()
    assert "left as they are" in _install(target, "/x/first", "FIRST.md")
    assert target.read_bytes() == before and not list(tmp_path.glob("*.before-baton-*"))


def test_a_hand_written_section_is_never_written_to(tmp_path):
    """Like this machine's: the marker, then rules in another language, no end marker."""
    home = tmp_path / "home"
    target = tmp_path / "CLAUDE.md"
    own = ("# Глобални инструкции\n\n<!-- Installed by Baton. https://github.com/StanimirTenev/baton -->\n\n"
           f"За всяка задача — папка в `~/zadachi/` с `DNEVNIK.md` вътре.\n")
    target.write_text(own, "utf-8")
    before = target.read_bytes()
    for tasks, logbook, warned in ((str(home / "zadachi"), "DNEVNIK.md", False),
                                   ("/x/other", "OTHER.md", True)):
        for dry in ("0", "1"):
            out = _install(target, tasks, logbook, dry, home=home)
            assert target.read_bytes() == before, (tasks, dry)
            assert ("WARNING" in out) is warned, (tasks, out)
