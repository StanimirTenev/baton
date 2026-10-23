"""ZA-OPRAVYANE row 68 (the 3.22.0 agent, 22.10): the installer took any hook whose command held
`baton_` for its own and rewrote it -- a human's `~/bin/my_baton_notes.sh` under Stop became
Baton's Stop hook, and the human's hook was gone. Row 61 fixed the same test in `installed_twice`
(SessionStart); the installer kept the substring. Now both match one of the four hook files.
"""
import json
import subprocess
import sys
from pathlib import Path

INSTALL = Path(__file__).resolve().parent.parent / "hooks" / "_install_hooks.py"
MINE = {"type": "command", "command": "/home/x/bin/my_baton_notes.sh", "timeout": 5}


def _install(tmp_path, settings: dict) -> tuple[dict, str]:
    hookdir = tmp_path / "hooks"
    hookdir.mkdir(exist_ok=True)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    out = subprocess.run([sys.executable, str(INSTALL), str(path), str(hookdir), sys.executable,
                          "0", str(tmp_path / "tasks"), "LOGBOOK.md"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(path.read_text("utf-8")), out.stdout


def _commands(data: dict, event: str) -> list:
    return [(h.get("command"), h.get("args")) for g in data["hooks"][event] for h in g["hooks"]]


def test_a_humans_hook_with_baton_in_its_name_is_left_alone(tmp_path):
    data, _ = _install(tmp_path, {"hooks": {"Stop": [{"hooks": [dict(MINE)]}]}})
    stop = _commands(data, "Stop")
    assert (MINE["command"], None) in stop, stop
    assert (sys.executable, [str(tmp_path / "hooks" / "baton_stop.py")]) in stop, stop


def test_a_second_install_keeps_it_and_adds_baton_once(tmp_path):
    data, _ = _install(tmp_path, {"hooks": {"Stop": [{"hooks": [dict(MINE)]}]}})
    data, out = _install(tmp_path, data)
    stop = _commands(data, "Stop")
    assert len(stop) == 2 and (MINE["command"], None) in stop, stop
    assert "Stop: hook already installed" in out


def test_an_older_baton_entry_is_still_updated(tmp_path):
    old = {"type": "command", "command": "python3 /old/place/baton_stop.py", "timeout": 20}
    data, out = _install(tmp_path, {"hooks": {"Stop": [{"hooks": [old]}]}})
    assert _commands(data, "Stop") == [(sys.executable, [str(tmp_path / "hooks" / "baton_stop.py")])]
    assert "Stop: hook updated" in out
