"""ZA-OPRAVYANE row 37 (Marcelo Dantas, 22.10): the record could change with nothing said.

- A logbook deleted: Stop asked for a new one, and nothing said a history was lost.
- Entries removed: deleting the newest entry even counted as a change at the top -- the work
  recorded.
- Baton's own memory (baton.bodies.json) deleted: Stop started over from file times, and an older
  entry rewritten after that passed.

Now each is said once, to the human (Stop's systemMessage) or on the board (SessionStart). Not
caught, by decision (row 24, 20.10): the newest entry rewritten -- completing or correcting it is
a change at the top and counts. Both state files deleted together: nothing inside Baton can tell.
"""

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
spec = importlib.util.spec_from_file_location("bs_lost", HOOKS / "baton_stop.py")
bs = importlib.util.module_from_spec(spec)
sys.modules["bs_lost"] = bs
spec.loader.exec_module(bs)

TWO = ("---\nstate: active\n---\n\n## 2026-10-21 09:00 — second\n\nremoved monitor.py\n\n"
       "## 2026-10-20 09:00 — first\n\nparser reads 3 formats\n")


def _task(root: Path, name="alpha"):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / "LOGBOOK.md"
    log.write_text(TWO, encoding="utf-8")
    now = time.time()
    os.utime(log, (now - 7200, now - 7200))
    work = folder / "parse.py"
    work.write_text("x = 1\n", encoding="utf-8")
    os.utime(work, (now - 9000, now - 9000))
    assert bs.unrecorded(root, "LOGBOOK.md") == []          # Baton has seen the two entries
    assert bs.LOST == [] and bs.FORGOT == []
    return folder, log


def test_a_deleted_logbook_is_said_once(tmp_path):
    folder, log = _task(tmp_path)
    log.unlink()
    bs.unrecorded(tmp_path, "LOGBOOK.md")
    assert bs.LOST == ["alpha: its LOGBOOK.md is gone, with the 2 entries Baton had seen"]
    bs.unrecorded(tmp_path, "LOGBOOK.md")
    assert bs.LOST == [], "said once"


def test_a_deleted_folder_is_said_once(tmp_path):
    folder, log = _task(tmp_path)
    log.unlink()
    (folder / "parse.py").unlink()
    folder.rmdir()
    bs.unrecorded(tmp_path, "LOGBOOK.md")
    assert len(bs.LOST) == 1 and "the folder is gone" in bs.LOST[0]


def test_the_newest_entry_removed_is_said_and_does_not_record_the_work(tmp_path):
    folder, log = _task(tmp_path)
    log.write_text(TWO.replace("## 2026-10-21 09:00 — second\n\nremoved monitor.py\n\n", ""),
                   encoding="utf-8")
    os.utime(folder / "parse.py", (time.time() - 600, time.time() - 600))   # work after the entry
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == ["alpha (newest: parse.py)"]
    assert bs.LOST == ["alpha: 1 of 2 entries gone from its LOGBOOK.md"]
    assert bs.TOPPED == [], "removing an entry is not a change at the top"


def test_the_newest_entry_rewritten_still_counts_by_decision(tmp_path):
    """Row 24 (20.10): a change at the top counts -- the newest entry completed or corrected.
    A rewrite there is the same edit, and is not caught. Pinned so a change to it is a decision."""
    folder, log = _task(tmp_path)
    log.write_text(TWO.replace("removed monitor.py", "refactored the pipeline"), encoding="utf-8")
    assert bs.unrecorded(tmp_path, "LOGBOOK.md") == []
    assert bs.LOST == [] and bs.REWRITTEN == []


def test_baton_s_own_memory_deleted_is_said_once(tmp_path):
    folder, log = _task(tmp_path)
    ss = bs._ss()
    ss.lessons_save({"tops": {str(folder): "## 2026-10-21 09:00 — second"}})   # Stop has looked
    bs._bodies_path().unlink()
    bs.unrecorded(tmp_path, "LOGBOOK.md")
    assert bs.FORGOT == [bs._bodies_path().name]
    bs.unrecorded(tmp_path, "LOGBOOK.md")
    assert bs.FORGOT == [], "said once: the memory is rebuilt"


def test_a_first_run_is_not_a_lost_memory(tmp_path):
    folder, log = _task(tmp_path)          # no lessons register yet: nothing was ever remembered
    bs._bodies_path().unlink()
    bs.unrecorded(tmp_path, "LOGBOOK.md")
    assert bs.FORGOT == []


# -- through the entry points, as the harness runs them --------------------------------------

def _env(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_PLUGIN")}
    env.update(BATON_HOME=str(tmp_path), BATON_LOGBOOK="LOGBOOK.md",
               BATON_STATE_DIR=str(tmp_path / ".state"), HOME=str(tmp_path / ".home"))
    return env


def _hook(name, env, payload):
    out = subprocess.run([sys.executable, str(HOOKS / name)], input=json.dumps(payload),
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def test_stop_tells_the_human(tmp_path):
    folder, log = _task(tmp_path)
    log.unlink()
    out = _hook("baton_stop.py", _env(tmp_path), {"session_id": "s"})
    assert "part of the record is gone" in out.get("systemMessage", ""), out
    assert "alpha" in out["systemMessage"] and "2 entries" in out["systemMessage"]
    again = _hook("baton_stop.py", _env(tmp_path), {"session_id": "s2"})
    assert "record is gone" not in again.get("systemMessage", ""), "said once"


def test_stop_tells_the_human_when_its_memory_is_gone(tmp_path):
    folder, log = _task(tmp_path)
    _hook("baton_stop.py", _env(tmp_path), {"session_id": "s"})     # Stop looks once: tops kept
    bs._bodies_path().unlink()
    out = _hook("baton_stop.py", _env(tmp_path), {"session_id": "s2"})
    assert "memory of the logbooks" in out.get("systemMessage", ""), out


def test_the_board_says_it(tmp_path):
    folder, log = _task(tmp_path)
    log.write_text(TWO.split("## 2026-10-20")[0], encoding="utf-8")
    out = _hook("baton_session_start.py", _env(tmp_path), {"source": "startup"})
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "1 of 2 entries gone" in ctx and "tell the human" in ctx
