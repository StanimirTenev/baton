"""Lessons: a mistake caught once is counted, and a lesson that does not hold shows itself.

L1 -- the hour in a logbook heading typed by hand. Written down as a lesson on 2026-09-23,
back on 26.09, 28.09 and twice on 30.09: caught by a hook every time, prevented never.
L2 -- "it is not there" said after an empty result. Ten dated cases in one week.
Run the way the harness runs them: the hooks as processes, the tool as a command.
"""
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
ENTRY = ROOT / "tools" / "baton_entry.py"


def _env(tmp_path, tasks):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE_PLUGIN", "CLAUDE_CONFIG_DIR"))}
    env.update(BATON_HOME=str(tasks), BATON_LOGBOOK="LOGBOOK.md", HOME=str(tmp_path / "home"),
               BATON_STATE_DIR=str(tmp_path / "state"))
    return env


def _run(hook, env, payload):
    out = subprocess.run([sys.executable, str(HOOKS / hook)], input=json.dumps(payload),
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def _state(env):
    try:
        return json.loads(Path(env["BATON_LESSONS_STATE"]).read_text("utf-8"))
    except FileNotFoundError:
        return {}


def _book(tasks, heading, name="a"):
    folder = tasks / name
    folder.mkdir(parents=True, exist_ok=True)
    book = folder / "LOGBOOK.md"
    old = book.read_text("utf-8").split("\n", 2)[2] if book.exists() else ""
    book.write_text(f"# {name}\n\n{heading}\n\nbody\n\n{old}", "utf-8")
    # nothing newer than the logbook, so the "unrecorded work" check stays quiet
    return book


def _stop(env, tmp_path, n):
    return _run("baton_stop.py", env, {"session_id": f"s{n}"}).get("reason", "")


# -- L1: Stop counts each new top entry and catches an hour off the clock either way --------

def test_l1_counts_new_entries_and_catches_a_past_hour(tmp_path):
    tasks = tmp_path / "tasks"
    env = _env(tmp_path, tasks)
    now = datetime.now()
    _book(tasks, f"## {now - timedelta(days=3):%Y-%m-%d %H:%M} — old")
    assert "L1" not in _stop(env, tmp_path, 1), "the first look only remembers; history is history"
    assert "L1" not in _state(env)

    _book(tasks, f"## {now:%Y-%m-%d %H:%M} — right")
    assert "L1" not in _stop(env, tmp_path, 2)
    assert _state(env)["L1"]["fired"] == 1 and _state(env)["L1"].get("caught", 0) == 0

    _book(tasks, f"## {now - timedelta(hours=2):%Y-%m-%d %H:%M} — typed")
    reason = _stop(env, tmp_path, 3)
    assert "lesson L1" in reason and "behind the clock" in reason, (
        "an hour typed in the PAST went through the old future-only check unseen")
    assert "baton_entry.py --title" in reason, "the hand-back names the tool, not only the rule"
    assert str(ENTRY) in reason, "and where it is: an agent's working directory is not the plugin's"
    assert _state(env)["L1"]["fired"] == 2 and _state(env)["L1"]["caught"] == 1

    assert "L1" not in _stop(env, tmp_path, 4), "the same entry is not caught twice"


def test_l1_names_the_tool_where_install_sh_left_it(tmp_path):
    """install.sh copies only the four hooks; tools/ stays in the repository it records as
    `repo`. The path next to the hooks names a file that is not there (PR #2 follow-up)."""
    import shutil
    hookdir = tmp_path / "installed" / "hooks"
    hookdir.mkdir(parents=True)
    for name in ("baton_stop.py", "baton_session_start.py"):
        shutil.copy(HOOKS / name, hookdir / name)
    tasks = tmp_path / "tasks"
    env = _env(tmp_path, tasks)
    now = datetime.now()

    def stop(n):
        out = subprocess.run([sys.executable, str(hookdir / "baton_stop.py")],
                             input=json.dumps({"session_id": f"i{n}"}),
                             capture_output=True, text=True, env=env)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout).get("reason", "") if out.stdout.strip() else ""

    (hookdir / "baton.local.json").write_text(json.dumps({"repo": str(ROOT)}), "utf-8")
    _book(tasks, f"## {now - timedelta(days=3):%Y-%m-%d %H:%M} — old")
    stop(1)
    _book(tasks, f"## {now - timedelta(hours=2):%Y-%m-%d %H:%M} — typed")
    reason = stop(2)
    assert "lesson L1" in reason and str(ENTRY) in reason, "the tool where it actually is"
    assert str(tmp_path / "installed" / "tools") not in reason, "not a path that does not exist"

    (hookdir / "baton.local.json").write_text("{}", "utf-8")     # repository unknown
    _book(tasks, f"## {now - timedelta(hours=3):%Y-%m-%d %H:%M} — typed again")
    reason = stop(3)
    assert "lesson L1" in reason and str(tmp_path / "installed" / "tools") not in reason


def test_l1_within_the_slack_is_quiet(tmp_path):
    tasks = tmp_path / "tasks"
    env = _env(tmp_path, tasks)
    now = datetime.now()
    _book(tasks, f"## {now - timedelta(days=1):%Y-%m-%d %H:%M} — old")
    _stop(env, tmp_path, 1)
    _book(tasks, f"## {now - timedelta(minutes=10):%Y-%m-%d %H:%M} — ten minutes ago")
    assert "L1" not in _stop(env, tmp_path, 2)


def test_l1_compares_with_the_save_time_not_the_stop_time(tmp_path):
    """2026-10-06: an entry headed 11:08 and saved at 11:08 by another session was first
    seen by a Stop at 13:08 and called 120 min behind. The heading was right."""
    tasks = tmp_path / "tasks"
    env = _env(tmp_path, tasks)
    now = datetime.now()
    _book(tasks, f"## {now - timedelta(days=1):%Y-%m-%d %H:%M} — old")
    _stop(env, tmp_path, 1)
    earlier = now - timedelta(hours=2)
    _book(tasks, f"## {earlier:%Y-%m-%d %H:%M} — written two hours ago, on time")
    for book in tasks.rglob("*.md"):
        os.utime(book, (earlier.timestamp(), earlier.timestamp()))
    assert "L1" not in _stop(env, tmp_path, 2)


def test_l1_leaves_an_entry_saved_before_this_session_alone(tmp_path):
    """2026-10-10 18:58: a session that had touched no task folder was handed two other
    sessions' entries to correct. An entry saved before this session began is not its
    entry: remembered as seen, so no later look reports it either, and not counted."""
    from datetime import timezone
    tasks = tmp_path / "tasks"
    env = _env(tmp_path, tasks)
    now = datetime.now()
    _book(tasks, f"## {now - timedelta(days=1):%Y-%m-%d %H:%M} — old")
    _stop(env, tmp_path, 1)
    book = _book(tasks, f"## {now - timedelta(hours=2):%Y-%m-%d %H:%M} — another session's, typed")
    saved = (now - timedelta(hours=4)).timestamp()          # two hours off its own save time
    os.utime(book, (saved, saved))
    transcript = tmp_path / "t.jsonl"
    started = datetime.fromtimestamp((now - timedelta(minutes=5)).timestamp(), timezone.utc)
    transcript.write_text(json.dumps({"type": "user", "timestamp": started.strftime("%Y-%m-%dT%H:%M:%S.000Z")})
                          + "\n", "utf-8")
    reason = _run("baton_stop.py", env, {"session_id": "s2", "transcript_path": str(transcript)}
                  ).get("reason", "")
    assert "L1" not in reason
    assert _state(env).get("L1", {}).get("fired", 0) == 0, "not this session's entry: not counted"
    assert "L1" not in _stop(env, tmp_path, 3), "seen once, it is history for every later look"


# -- L2: an empty result from a read, once per half hour, counted every time --------------

def _batch(env, calls):
    return _run("baton_batch.py", env, {"session_id": "s", "tool_calls": calls})


def _call(tool, response, command=""):
    return {"tool_name": tool, "tool_input": {"command": command}, "tool_response": response}


def test_l2_empty_read_says_so_once_and_counts_every_time(tmp_path):
    env = _env(tmp_path, tmp_path / "tasks")
    out = _batch(env, [_call("Bash", "(Bash completed with no output)", "grep -rn Featured page.html")])
    note = out["hookSpecificOutput"]["additionalContext"]
    assert "lesson L2" in note and "name the check that would have found it" in note
    assert _batch(env, [_call("WebFetch", "[]")]) == {}, "at most once every half hour"
    assert _state(env)["L2"]["fired"] == 2


def test_l2_quiet_for_writes_and_for_results_with_content(tmp_path):
    env = _env(tmp_path, tmp_path / "tasks")
    assert _batch(env, [_call("Bash", "", "mkdir -p out && cp a b")]) == {}, "not a read"
    assert _batch(env, [_call("Bash", "x.py:3: Featured", "grep -rn Featured .")]) == {}
    assert _batch(env, [_call("Edit", "")]) == {}
    assert "L2" not in _state(env)


def test_l2_reads_content_blocks_the_way_the_agent_sees_them(tmp_path):
    env = _env(tmp_path, tmp_path / "tasks")
    out = _batch(env, [_call("mcp__x__query", [{"type": "text", "text": "[]"}])])
    assert "lesson L2" in out["hookSpecificOutput"]["additionalContext"]


# -- SessionStart: a lesson speaks only when it has earned it -------------------------------

def _ss(env):
    spec = importlib.util.spec_from_file_location("ss_lessons", HOOKS / "baton_session_start.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_notice_only_when_a_lesson_recurs_or_goes_unused(tmp_path):
    env = _env(tmp_path, tmp_path / "tasks")
    ss = _ss(env)
    now = datetime.now()
    assert ss.lessons_notice(now) is None, "silent by default: nothing loaded into every session"

    state = {}
    ss.lesson_event(state, "L1", "fired", now - timedelta(days=3))
    ss.lesson_event(state, "L1", "caught", now - timedelta(days=3))
    ss.lessons_save(state)
    assert ss.lessons_notice(now) is None, "one catch is not a pattern"

    ss.lesson_event(state, "L1", "fired", now - timedelta(days=1))
    ss.lesson_event(state, "L1", "caught", now - timedelta(days=1))
    ss.lessons_save(state)
    notice = ss.lessons_notice(now)
    assert "L1 recurred 2 times" in notice and "next rung" in notice

    ss.lessons_save({"L2": {"since": (now - timedelta(days=90)).isoformat(timespec="minutes"),
                            "last_fired": (now - timedelta(days=70)).isoformat(timespec="minutes")}})
    assert "L2 has not come up in 60 days" in ss.lessons_notice(now)


# -- the tool that makes L1 impossible -------------------------------------------------------

def test_entry_title_takes_the_hour_from_the_clock(tmp_path):
    book = tmp_path / "LOGBOOK.md"
    book.write_text("---\nstate: active\n---\n\n## 2026-01-01 10:00 — first\n\nx\n", "utf-8")
    before = datetime.now().replace(second=0, microsecond=0)
    subprocess.run([sys.executable, str(ENTRY), str(book), "-", "--title", "second"],
                   input="### Done\nsomething\n", text=True, check=True, capture_output=True)
    head = [ln for ln in book.read_text("utf-8").splitlines() if ln.startswith("## ")][0]
    stamped = datetime.strptime(head[3:19], "%Y-%m-%d %H:%M")
    assert head.endswith("— second") and abs((stamped - before).total_seconds()) < 120
    refused = subprocess.run([sys.executable, str(ENTRY), str(book), "-", "--title", "x"],
                             input="## 2026-01-01 09:00 — typed\n", text=True, capture_output=True)
    assert refused.returncode != 0, "a typed heading next to --title is refused, not merged"


def test_l2_an_mcp_write_that_answers_empty_is_not_a_failed_read(tmp_path):
    """External review of v3.10.0: `mcp__files__delete` answering `{}` raised L2 and counted.
    Each call in its own state -- the half-hour throttle would otherwise hide the answer."""
    for tool in ("mcp__files__delete", "mcp__claude_ai_Gmail__label_message",
                 "mcp__claude_ai_Google_Drive__create_file", "mcp__x__frobnicate"):
        env = _env(tmp_path / tool, tmp_path / tool / "tasks")
        env["BATON_LESSONS_STATE"] = str(tmp_path / tool / "lessons.json")
        assert _batch(env, [_call(tool, "{}")]) == {}, tool
        assert not (_state(env).get("L2") or {}).get("fired_dates"), f"{tool} was counted"


def test_l2_an_mcp_read_that_answers_empty_still_speaks(tmp_path):
    for tool in ("mcp__x__search", "mcp__claude_ai_Gmail__search_threads",
                 "mcp__claude_ai_Google_Drive__read_file_content", "mcp__x__list_events"):
        env = _env(tmp_path / tool, tmp_path / tool / "tasks")
        env["BATON_LESSONS_STATE"] = str(tmp_path / tool / "lessons.json")
        assert "L2" in json.dumps(_batch(env, [_call(tool, "[]")]), ensure_ascii=False), tool


def test_l2_a_read_verb_inside_a_heredoc_body_is_text_not_a_read(tmp_path):
    """Replay of 9,908 Bash calls from 48 transcripts, 2026-10-12: at least 28 of L2's 120
    fires were writes -- a logbook entry written through a heredoc that mentions grep or gh.
    The verb was in the text being written, not in the command."""
    writes = ("python3 - <<'EOF'\np='DNEVNIK.md'\ns='checked with grep and gh'\nEOF",
              "cd notes && cat > entry.md <<EOF\nfetched it with curl, found nothing\nEOF",
              'python3 - <<"END"\nprint("search")\nEND',
              "cat > a.txt <<-EOF\n\tls showed it\n\tEOF")
    for i, command in enumerate(writes):
        env = _env(tmp_path / str(i), tmp_path / str(i) / "tasks")
        env["BATON_LESSONS_STATE"] = str(tmp_path / str(i) / "lessons.json")
        assert _batch(env, [_call("Bash", "(Bash completed with no output)", command)]) == {}, command
        assert not (_state(env).get("L2") or {}).get("fired_dates"), f"counted: {command!r}"


def test_l2_a_read_verb_in_a_script_or_string_the_command_carries_is_text(tmp_path):
    """Replay of the recorded Bash calls here, 2026-10-20: 9 of L2's 81 fires had their verb only
    inside quotes. Six were text a command carried -- logbook entries written with `python3 -c`
    that mention gh, a `printf` of JSON-RPC with a "text" field. The same as a heredoc body."""
    carried = (
        "cd ~/zadachi/qrp-mcp; t=$(date '+%Y-%m-%d %H:%M'); python3 -c \"\nimport sys;t=sys.argv[1];"
        "p='DNEVNIK.md';s=open(p).read()\ne='## '+t+' — PR #58, checked from outside (gh pr diff)'\n"
        "open(p,'w').write(e+s)\n\" \"$t\"",
        "printf '%s\\n' '{\"jsonrpc\":\"2.0\",\"method\":\"tools/call\",\"params\":{\"text\":\"x\"}}' "
        "| timeout 60 qrp-mcp",
        "sed -i 's/grep -rn/rg -n/' notes.md",
        "echo \"nothing found by grep\" >> log.txt",
        "awk '/curl/ {n++} END {print n}' history.txt > count.txt",
        "python3 -c \"e='\\`gh issue create\\` refused'; open('DNEVNIK.md','a').write(e)\"")
    for i, command in enumerate(carried):
        env = _env(tmp_path / str(i), tmp_path / str(i) / "tasks")
        env["BATON_LESSONS_STATE"] = str(tmp_path / str(i) / "lessons.json")
        assert _batch(env, [_call("Bash", "(Bash completed with no output)", command)]) == {}, command


def test_l2_a_read_handed_to_a_shell_in_quotes_still_speaks(tmp_path):
    """The other three of those nine were reads: a command in quotes that ssh runs on another
    machine. A quoted string is text only when the command that carries it does not run it."""
    reads = (
        "timeout 25 ssh -o BatchMode=yes stenly@192.168.199.102 'powershell -NoProfile -Command "
        "\"Get-ChildItem -Path \\\"$env:USERPROFILE\\Desktop\\\" -Directory | Select-Object -ExpandProperty Name\"' 2>&1 | tail -20",
        "bash -c \"grep -rn Featured page.html\"",
        "sed -n '1,10p' page.html | grep Featured",
        "echo \"$(grep -c Featured page.html)\"")
    for i, command in enumerate(reads):
        env = _env(tmp_path / str(i), tmp_path / str(i) / "tasks")
        env["BATON_LESSONS_STATE"] = str(tmp_path / str(i) / "lessons.json")
        out = _batch(env, [_call("Bash", "(Bash completed with no output)", command)])
        assert "lesson L2" in json.dumps(out), command


def test_l2_a_read_next_to_a_heredoc_still_speaks(tmp_path):
    """The verb outside the body still makes it a read."""
    for i, command in enumerate(("cat <<'EOF' | grep -c missing\nabc\nEOF",
                                 "python3 - <<'EOF'\nprint(1)\nEOF\ngrep -rn Featured page.html")):
        env = _env(tmp_path / str(i), tmp_path / str(i) / "tasks")
        env["BATON_LESSONS_STATE"] = str(tmp_path / str(i) / "lessons.json")
        out = _batch(env, [_call("Bash", "0" if "-c" in command else "", command)])
        assert "lesson L2" in json.dumps(out), command
