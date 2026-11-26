#!/usr/bin/env python3
"""Move the agent's world to a new computer, and check on the new one that all of it arrived.

    python3 tools/baton_move.py inventory [--out manifest.json] [--no-hash] [--transcripts]
    python3 tools/baton_move.py restore --manifest manifest.json --from <copied tree> [--home <target home>] [--dry-run] [--force]
    python3 tools/baton_move.py verify  --manifest manifest.json [--home <target home>]

On the old machine `inventory` (read-only) lists what the agent's work depends on: the task
folders file by file with SHA-256, Claude Code's instructions, settings, skills and memory
folders, the git repositories the logbooks' `code:` headers name and those under ~/dev, the
paths outside the task folder that logbooks mention, crontab and user timers, and the keys and
logins -- by name, size and SHA-256, never their content. It prints the rsync line that copies
the rest. On the new machine `restore` puts the copied tree in place, renaming Claude's memory
folder when the home path changed; `verify` compares everything with the manifest and exits
non-zero until it all matches. The old disk is wiped only after verify is clean.

Scope: the agent's world, not the whole home folder. What the inventory did not look at is in
the manifest's `not_covered`, each with the check that would find it -- an absence is stated
with the check that would find it.

Known traps, from a real move plan (2026-10-13, 2026-10-19):
- Claude's memory folder is named after the home path (`~/.claude/projects/-home-stenly/`);
  another user name is another folder, and the memory looks gone.
- crontab does not travel with files.
- some keys cannot be recreated if lost; they are carried by hand, never through a cloud.

The tasks: BATON_HOME and BATON_LOGBOOK, else baton.local.json, as for every tool.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKIP = {"node_modules", "__pycache__", ".venv", "venv", ".mypy_cache"}   # made anew, not carried
BROWSERS = {"BraveSoftware", "chromium", "google-chrome", "google-chrome-for-testing",
            "microsoft-edge", "opera", "vivaldi", "mozilla"}
SECRET_NAME = re.compile(r"(?i)(key(?!board|bind|map)|token|credential|secret|password|\.pem$|\.p12$|\.pfx$|"
                         r"^env$|\.env$|^rclone\.conf$|^hosts\.yml$)")
SECRET_FILES = (".pypirc", ".claude.json", ".claude/.credentials.json", ".netrc", ".git-credentials")
SYSTEM = ("/usr", "/bin", "/sbin", "/lib", "/etc", "/proc", "/sys", "/dev", "/run", "/var",
          "/boot", "/snap", "/tmp")
PATH_IN_TEXT = re.compile(r"(?<![\w/.~:-])(~/[^\s`'\"()<>\[\]{},;|*]+|/[A-Za-z0-9_.-][^\s`'\"()<>\[\]{},;|*]*)")
WALK_CAP = 200_000         # a mentioned folder is sized up to this many files, then "at least"
LIST = 20                  # names printed per group; the manifest holds all of them


def _load(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def encode(home: str) -> str:
    """Claude Code's name for a project folder: every character but a letter or digit is `-`."""
    return re.sub(r"[^A-Za-z0-9]", "-", home)


def rel_to(path: Path, home: Path) -> str:
    """Home-relative posix path when under home, else the absolute path."""
    try:
        return path.relative_to(home).as_posix()
    except ValueError:
        return path.as_posix()


def target(rel: str, old_home: str, new_home: Path) -> Path:
    """Where a manifest path lands on the new machine: under the new home, with a Claude
    project folder named after the old home renamed after the new one. Restore and verify
    both use this one mapping."""
    if os.path.isabs(rel):
        return Path(rel)
    parts = list(Path(rel).parts)
    if len(parts) >= 3 and parts[:2] == [".claude", "projects"]:
        parts[2] = renamed(parts[2], old_home, str(new_home))
    return Path(new_home, *parts)


def renamed(name: str, old_home: str, new_home: str) -> str:
    old, new = encode(old_home), encode(new_home)
    if name == old or (name.startswith(old) and name[len(old)] in "-."):
        return new + name[len(old):]
    return name


def run(*cmd, cwd=None) -> tuple:
    """(returncode, stdout, stderr); (None, "", why) when the command is not there."""
    try:
        done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as err:
        return None, "", str(err)
    return done.returncode, done.stdout, done.stderr


def no_userinfo(url: str) -> str:
    """A remote URL without `user:password@` -- a login can sit inside one."""
    return re.sub(r"(//)[^/@\s]+@", r"\1", url or "")


# --- inventory ---------------------------------------------------------------------------------

def walk_files(top: Path, skip_dir=None):
    """Regular files under `top`, symlinks not followed; (files, symlinks, unreadable dirs)."""
    files, links, unreadable = [], [], []
    for dirpath, dirnames, filenames in os.walk(top, onerror=lambda e: unreadable.append(e.filename)):
        keep = []
        for d in dirnames:
            full = Path(dirpath, d)
            if full.is_symlink():
                links.append(full)
            elif not (skip_dir and skip_dir(full)):
                keep.append(d)
        dirnames[:] = sorted(keep)
        for f in sorted(filenames):
            full = Path(dirpath, f)
            if full.is_symlink():
                links.append(full)
            elif full.is_file():
                files.append(full)
    return files, links, unreadable


def file_entry(path: Path, home: Path, group: str, hashed: bool, problems: list) -> dict | None:
    try:
        entry = {"path": rel_to(path, home), "group": group, "size": path.stat().st_size}
        if hashed:
            entry["sha256"] = sha256(path)
        return entry
    except OSError as err:
        problems.append(f"{path}: {err.strerror or err}")
        return None


def repo_info(path: Path, home: Path, source: str) -> dict:
    git = lambda *a: run("git", "-C", str(path), *a)
    info = {"path": rel_to(path, home), "from": [source]}
    code, out, _ = git("remote")
    remotes = out.split()
    info["remote"] = no_userinfo(git("remote", "get-url", "origin" if "origin" in remotes else remotes[0])[1].strip()) if remotes else ""
    info["branch"] = git("rev-parse", "--abbrev-ref", "HEAD")[1].strip()
    info["head"] = git("rev-parse", "HEAD")[1].strip()
    info["dirty"] = len(git("status", "--porcelain")[1].splitlines())
    code, out, _ = git("rev-list", "--count", "@{u}..HEAD")
    info["unpushed"] = int(out) if code == 0 and out.strip().isdigit() else None   # None: no upstream
    code, out, _ = git("rev-list", "--count", "--branches", "--not", "--remotes")
    info["unpushed_any_branch"] = int(out) if code == 0 and out.strip().isdigit() else None
    info["stashes"] = len(git("stash", "list")[1].splitlines())
    if (path / ".git").is_file():          # a worktree: branches and stashes are its main repo's
        common = git("rev-parse", "--path-format=absolute", "--git-common-dir")[1].strip()
        info["worktree_of"] = rel_to(Path(common).parent, home) if common else ""
    return info


def dir_size(path: Path) -> tuple:
    if path.is_file():
        return path.stat().st_size, False
    total, n = 0, 0
    for dirpath, _dirs, filenames in os.walk(path, onerror=lambda e: None):
        for f in filenames:
            n += 1
            if n > WALK_CAP:
                return total, True
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total, False


def inventory(args) -> int:
    home = Path.home()
    corpus = _load("baton_corpus", HERE / "baton_corpus.py")
    cfg = corpus.config()
    root, logbook = Path(cfg["home"]).expanduser().resolve(), cfg["logbook"]
    if not root.is_dir():
        print(f"baton_move: the tasks folder {root} does not exist (resolved from BATON_HOME, else "
              f"baton.local.json, else ~/tasks). Set BATON_HOME and BATON_LOGBOOK and run again.",
              file=sys.stderr)
        return 2
    stop = _load("baton_stop", HERE.parent / "hooks" / "baton_stop.py")
    start = _load("baton_session_start", HERE.parent / "hooks" / "baton_session_start.py")
    hashed = not args.no_hash
    problems, files, links = [], [], []
    man = {"baton_move": 1, "made": datetime.now().isoformat(timespec="seconds"),
           "host": socket.gethostname(), "user": getpass.getuser(), "home": str(home),
           "hashed": hashed}

    # The task folders. Made-anew folders and what .batonignore names are counted, not listed.
    tasks, skipped = {}, {"files": 0, "bytes": 0, "where": []}
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink()):
        patterns = stop.ignore_patterns(folder)
        dirs = stop._dir_patterns(patterns)

        def skip_dir(d, base=folder, dirs=dirs):
            if not (d.name in SKIP or (dirs and stop._dir_ignored(d.relative_to(base).as_posix(), d.name, dirs))):
                return False
            size, _ = dir_size(d)
            skipped["files"] += sum(len(fs) for _, _, fs in os.walk(d))
            skipped["bytes"] += size
            skipped["where"].append(rel_to(d, root))
            return True
        found, lk, bad = walk_files(folder, skip_dir)
        links += lk
        problems += [f"{b}: not readable" for b in bad]
        count, size = 0, 0
        for f in found:
            if patterns and stop.is_ignored(f.relative_to(folder).as_posix(), f.name, patterns):
                skipped["files"] += 1
                skipped["bytes"] += f.stat().st_size
                skipped["where"].append(rel_to(f, root))
                continue
            e = file_entry(f, home, "tasks", hashed, problems)
            if e:
                files.append(e)
                count, size = count + 1, size + e["size"]
        tasks[folder.name] = {"files": count, "bytes": size}
    for f in sorted(p for p in root.iterdir() if p.is_file() and not p.is_symlink()):
        e = file_entry(f, home, "tasks", hashed, problems)   # files at the root, e.g. an archive list
        if e:
            files.append(e)
    links += [p for p in root.iterdir() if p.is_symlink()]
    man["tasks"] = {"path": rel_to(root, home), "logbook": logbook, "folders": tasks,
                    "skipped": skipped}

    # Claude Code.
    claude = home / ".claude"
    for rel in ("CLAUDE.md", ".claude/CLAUDE.md", ".claude/settings.json", ".gitconfig"):
        p = home / rel
        if p.is_file() and not p.is_symlink():
            e = file_entry(p, home, "claude" if rel.startswith(".claude") or rel == "CLAUDE.md" else "config", hashed, problems)
            if e:
                files.append(e)
    copy_paths = [p for p in ("CLAUDE.md", ".claude/CLAUDE.md", ".claude/settings.json", ".gitconfig")
                  if (home / p).is_file()]
    if (claude / "skills").is_dir():
        found, lk, _ = walk_files(claude / "skills")
        links += lk
        files += [e for e in (file_entry(f, home, "claude", hashed, problems) for f in found) if e]
        copy_paths.append(".claude/skills")
    memory, transcripts = [], {"files": 0, "bytes": 0, "included": bool(args.transcripts)}
    projects = claude / "projects"
    if projects.is_dir():
        for proj in sorted(p for p in projects.iterdir() if p.is_dir()):
            if (proj / "memory").is_dir():
                memory.append(proj.name)
                found, lk, _ = walk_files(proj / "memory")
                links += lk
                files += [e for e in (file_entry(f, home, "claude", hashed, problems) for f in found) if e]
                if not args.transcripts:
                    copy_paths.append(f".claude/projects/{proj.name}/memory")
            for t in proj.rglob("*.jsonl"):
                if "memory" in t.relative_to(proj).parts or not t.is_file():
                    continue
                transcripts["files"] += 1
                transcripts["bytes"] += t.stat().st_size
                if args.transcripts:
                    e = file_entry(t, home, "transcripts", hashed, problems)
                    if e:
                        files.append(e)
        if args.transcripts:
            copy_paths.append(".claude/projects")
    man["claude"] = {"memory_folders": memory, "memory_folder_of_home": encode(str(home)),
                     "transcripts": transcripts}
    plugins = claude / "plugins"
    try:
        installed = json.loads((plugins / "installed_plugins.json").read_text("utf-8"))
        man["plugins"] = {name: [{"scope": i.get("scope"), "version": i.get("version")} for i in items]
                          for name, items in installed.get("plugins", {}).items()}
    except (OSError, ValueError, AttributeError) as err:
        man["plugins"] = None
        man["plugins_why"] = f"{plugins / 'installed_plugins.json'} not read: {err}"
    try:
        known = json.loads((plugins / "known_marketplaces.json").read_text("utf-8"))
        man["marketplaces"] = {n: v.get("source") for n, v in known.items() if isinstance(v, dict)}
    except (OSError, ValueError, AttributeError):
        man["marketplaces"] = None

    # Schedules: crontab and user timers. Their unit files travel as files.
    units = home / ".config" / "systemd" / "user"
    if units.is_dir():
        found, lk, _ = walk_files(units)
        files += [e for e in (file_entry(f, home, "schedules", hashed, problems) for f in found) if e]
        man["unit_links"] = [rel_to(l, home) for l in lk]
        copy_paths.append(".config/systemd/user")
    code, out, err = run("crontab", "-l")
    man["crontab"] = out if code == 0 else None
    man["crontab_why"] = "" if code == 0 else (err.strip() or "crontab not found")[:200]
    man["timers"] = run("systemctl", "--user", "list-timers", "--all", "--no-pager")[1]
    man["unit_files"] = run("systemctl", "--user", "list-unit-files", "--no-pager", "--state=enabled")[1]

    # Keys and logins: name, size, hash. The content is read only by hashlib.
    secrets = []
    candidates = []
    if (home / ".ssh").is_dir():
        candidates += walk_files(home / ".ssh")[0]
    config = home / ".config"
    if config.is_dir():
        def skip_config(d):
            rel = d.relative_to(config).parts
            return rel[0] in BROWSERS or len(rel) >= 3 or d.name.lower() in ("cache", "caches")
        candidates += [f for f in walk_files(config, skip_config)[0]
                       if SECRET_NAME.search(f.name) and "systemd" not in f.parts]
    candidates += [home / s for s in SECRET_FILES if (home / s).is_file()]
    for f in candidates:
        try:
            secrets.append({"path": rel_to(f, home), "size": f.stat().st_size, "sha256": sha256(f)})
        except OSError as err:
            problems.append(f"{rel_to(f, home)}: {err.strerror or err}")
    man["secrets"] = secrets

    # Repositories: the logbooks' `code:` headers and everything directly under ~/dev.
    repos, texts = {}, {}
    for lb in sorted(root.glob(f"*/{logbook}")):
        text = lb.read_text("utf-8", "replace")
        texts[lb.parent.name] = text
        raw = str(start.parse_frontmatter(text).get("code", "")).strip()
        if raw:
            where = Path((raw.rpartition("@")[0] if "@" in raw else raw).strip()).expanduser()
            if (where / ".git").exists():
                key = str(where.resolve())
                if key in repos:
                    repos[key]["from"].append(f"code: in {lb.parent.name}")
                else:
                    repos[key] = repo_info(where.resolve(), home, f"code: in {lb.parent.name}")
            else:
                problems.append(f"`code: {raw}` in {lb.parent.name}: not a repository on this disk")
    if (home / "dev").is_dir():
        for d in sorted((home / "dev").iterdir()):
            if (d / ".git").exists() and str(d.resolve()) not in repos:
                repos[str(d.resolve())] = repo_info(d.resolve(), home, "~/dev")
    man["repos"] = list(repos.values())

    # Paths the logbooks mention outside the task folder: listed, not carried.
    covered = [root, claude, home / ".ssh"] + [Path(r) for r in repos] + [home / s["path"] for s in secrets]
    mentioned = {}
    for task, text in texts.items():
        for m in PATH_IN_TEXT.finditer(text):
            raw = m.group(1).rstrip(".:,'")
            p = Path(os.path.normpath(os.path.expanduser(raw)))
            s = str(p)
            system = home not in p.parents and any(s == x or s.startswith(x + "/") for x in SYSTEM)
            if (s in ("/", ".") or system or p in home.parents or p == home
                    or any(p == c or c in p.parents for c in covered)):
                continue
            try:
                if not p.exists():
                    continue
            except OSError:
                continue
            mentioned.setdefault(s, set()).add(task)
    top = [s for s in mentioned if not any(Path(o) in Path(s).parents for o in mentioned)]
    out_list = []
    for s in sorted(top):
        size, capped = dir_size(Path(s))
        out_list.append({"path": rel_to(Path(s), home), "bytes": size, "at_least": capped,
                         "in": sorted(mentioned[s])[:5], "status": "mentioned, not included"})
    man["mentioned"] = out_list

    man["files"] = files
    man["symlinks_skipped"] = [rel_to(l, home) for l in links]
    man["problems"] = problems
    man["copy_paths"] = [rel_to(root, home)] + copy_paths
    man["not_covered"] = not_covered(man, home)

    out = Path(args.out) if args.out else Path("baton-move-manifest.json")
    out.write_text(json.dumps(man, ensure_ascii=False, indent=1), "utf-8")
    summary(man, out)
    return 0


def not_covered(man: dict, home: Path) -> list:
    t, sk = man["claude"]["transcripts"], man["tasks"]["skipped"]
    out = [
        "the rest of the home folder: only the paths in this manifest were looked at -- "
        "`du -sh ~/* ~/.[!.]* | sort -h` shows what else is there",
        "browser profiles (logged-in sites): not looked at -- `du -sh ~/.config/{BraveSoftware,"
        "google-chrome,chromium} ~/.mozilla ~/.brave-* 2>/dev/null`",
        "system packages and programs (Claude Code, gh, rclone, ...): not listed -- "
        "`apt-mark showmanual > apt-manual.txt`, `snap list`, `pip list --user`",
        "logins that are bound to the machine or expire (gh auth, rclone, Claude Code): the files "
        "are listed, whether they still work is checked by logging in -- `gh auth status`, "
        "`rclone lsd <remote>:`",
        "~/.gnupg, keyrings and password managers: not looked at -- `ls ~/.gnupg ~/.local/share/keyrings`",
        f"keys and logins outside ~/.ssh, ~/.config (depth 3, browsers skipped) and {', '.join(SECRET_FILES)}: "
        "not looked for -- `grep -rlI 'PRIVATE KEY' ~ 2>/dev/null`",
        "the rest of ~/.claude (plugins' files, history, file-history, sessions): not carried -- "
        "plugins are reinstalled from the list, the others are rebuilt",
        f"in the task folders, {sk['files']} files ({sk['bytes']} bytes) under made-anew folders "
        f"({', '.join(sorted(SKIP))}, left out of the rsync line) or matched by .batonignore "
        f"(copied, never checked): not hashed, not verified -- {', '.join(sk['where'][:10]) or 'none'}",
        f"{len(man['symlinks_skipped'])} symbolic links: not followed, not verified; rsync -a "
        "copies them as links",
        "repositories outside the logbooks' `code:` headers and ~/dev: not looked for -- "
        "`find ~ -name .git -maxdepth 4 -not -path '*/.cache/*'`",
    ]
    if not t["included"]:
        out.append(f"Claude conversation transcripts: {t['files']} files, {t['bytes']} bytes, "
                   "counted but not included -- run inventory with --transcripts to carry them")
    if man.get("plugins") is None:
        out.append(man.get("plugins_why", "installed plugins: not read"))
    if man["crontab"] is None:
        out.append(f"crontab: not read ({man['crontab_why']})")
    return out


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def summary(man: dict, out: Path) -> None:
    files = man["files"]
    by = {}
    for f in files:
        g = by.setdefault(f["group"], [0, 0])
        g[0], g[1] = g[0] + 1, g[1] + f["size"]
    tasks = man["tasks"]
    print(f"Baton move -- inventory of {man['user']}@{man['host']}, home {man['home']}"
          f"{'' if man['hashed'] else ' (no hashes: verify compares sizes only)'}")
    print(f"manifest: {out}\n")
    print(f"Tasks folder {tasks['path']} ({tasks['logbook']}): {len(tasks['folders'])} folders, "
          f"{by.get('tasks', [0, 0])[0]} files, {human(by.get('tasks', [0, 0])[1])}")
    for name, t in sorted(tasks["folders"].items(), key=lambda kv: -kv[1]["bytes"])[:5]:
        print(f"  {name}: {t['files']} files, {human(t['bytes'])}")
    sk = tasks["skipped"]
    if sk["files"]:
        print(f"  ⚠️ {sk['files']} more files, {human(sk['bytes'])}, are NOT in the manifest (made-anew "
              f"folders, .batonignore): verify cannot say they arrived -- see NOT covered")
    for g in ("claude", "config", "schedules", "transcripts"):
        if g in by:
            print(f"{g}: {by[g][0]} files, {human(by[g][1])}")
    c = man["claude"]
    print(f"Claude memory folders: {', '.join(c['memory_folders']) or 'none'}"
          f" -- named after the home path; restore renames them if it changes")
    t = c["transcripts"]
    print(f"Claude transcripts: {t['files']} files, {human(t['bytes'])}"
          f" ({'included' if t['included'] else 'not included; --transcripts carries them'})")
    p = man.get("plugins")
    print(f"Claude plugins: {len(p)} installed" if p is not None else man.get("plugins_why"))
    print(f"\nRepositories: {len(man['repos'])} (cloned anew, not copied)")
    for r in man["repos"]:
        state = []
        if r["dirty"]:
            state.append(f"{r['dirty']} uncommitted")
        if r["unpushed"] is None:
            state.append("no upstream")
        elif r["unpushed"]:
            state.append(f"{r['unpushed']} unpushed")
        if r["unpushed_any_branch"] and not r.get("worktree_of"):
            state.append(f"{r['unpushed_any_branch']} unpushed on some branch")
        if r["stashes"] and not r.get("worktree_of"):
            state.append(f"{r['stashes']} stashed")
        if not r["remote"]:
            state.append("NO remote")
        wt = f" (worktree of {r['worktree_of']})" if r.get("worktree_of") else ""
        print(f"  {'✗' if state else '✓'} {r['path']}{wt} {r['branch']} {r['head'][:10]}"
              f" -- {', '.join(state) or 'clean, pushed'}")
    if any(r["dirty"] or r["unpushed"] or r["unpushed_any_branch"] or r["stashes"] or not r["remote"]
           for r in man["repos"]):
        print("  ✗ a clone does not carry uncommitted, unpushed or stashed work: commit and push it "
              "(or copy that folder too), then run inventory again")
    m = man["mentioned"]
    print(f"\nMentioned in logbooks, outside the tasks folder (not included -- you decide): {len(m)}")
    for e in sorted(m, key=lambda e: -e["bytes"])[:LIST]:
        print(f"  {e['path']} {'≥ ' if e['at_least'] else ''}{human(e['bytes'])} (in {', '.join(e['in'][:2])})")
    if len(m) > LIST:
        print(f"  ... and {len(m) - LIST} more in the manifest")
    cron = man["crontab"]
    lines = [ln for ln in (cron or "").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    print(f"\ncrontab: {len(lines)} lines (does not travel with files; restore prints it)"
          if cron is not None else f"\ncrontab: none ({man['crontab_why']})")
    if lines:
        print("  ⚠️ the manifest holds the crontab text as it is: if a line carries a key, treat the "
              "manifest like one")
    print(f"user unit files: {by.get('schedules', [0])[0]} (copied as files)")
    s = man["secrets"]
    print(f"\nKeys and logins: {len(s)} -- names only here; carry by hand, never through a cloud:")
    for e in s[:LIST * 2]:
        print(f"  ~/{e['path']} ({e['size']} B)")
    if man["problems"]:
        print(f"\nProblems ({len(man['problems'])}):")
        for line in man["problems"][:LIST]:
            print(f"  {line}")
    print("\nCopy to the new machine (lands in ~/baton-move there; then restore --from ~/baton-move):")
    excl = " ".join(f"--exclude={d}" for d in sorted(SKIP))
    srcs = " ".join(f"~/./{p}" for p in man["copy_paths"])
    print(f"  rsync -aHAX -R --info=progress2 {excl} {srcs} NEWHOST:baton-move/")
    print(f"  scp {out} NEWHOST:baton-move/")
    print("Keys and logins, separately -- USB stick or scp, never a cloud folder:")
    print(f"  rsync -aHAX -R {' '.join('~/./' + e['path'] for e in s)} NEWHOST:baton-move/" if s else "  (none found)")
    print("\nNOT covered by this inventory (manifest: not_covered):")
    for line in man["not_covered"]:
        print(f"  - {line}")


# --- restore and verify ------------------------------------------------------------------------

def load(path: str) -> dict:
    return json.loads(Path(path).read_text("utf-8"))


def same(path: Path, entry: dict) -> bool:
    if path.stat().st_size != entry["size"]:
        return False
    return "sha256" not in entry or sha256(path) == entry["sha256"]


def restore(args) -> int:
    man, src_root = load(args.manifest), Path(args.src).expanduser().resolve()
    home, old = Path(args.home).expanduser().resolve() if args.home else Path.home(), man["home"]
    act = "would" if args.dry_run else "did"
    placed, same_n, conflicts, missing, by_hand = 0, 0, [], [], []
    for entry in man["files"] + [dict(e, group="secrets") for e in man["secrets"]]:
        src = src_root / entry["path"].lstrip("/")
        dst = target(entry["path"], old, home)
        if not src.is_file():
            (by_hand if entry["group"] == "secrets" else missing).append(entry["path"])
            continue
        if dst.exists():
            if src.resolve() == dst.resolve() or same(dst, entry):
                same_n += 1
                continue
            if not args.force:
                conflicts.append(rel_to(dst, home))
                continue
        if not args.dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)           # copy2 keeps the mode: a key stays 0600
        placed += 1
    if not args.dry_run and (home / ".ssh").is_dir():
        os.chmod(home / ".ssh", 0o700)
    print(f"Baton move -- restore into {home} from {src_root}{' (dry run: nothing written)' if args.dry_run else ''}")
    print(f"  {act} place {placed} files; {same_n} already in place and the same")
    if str(home) != old:
        names = [(n, renamed(n, old, str(home))) for n in man["claude"]["memory_folders"]]
        for a, b in names:
            if a != b:
                print(f"  home path changed ({old} -> {home}): memory folder .claude/projects/{a} "
                      f"-> .claude/projects/{b}")
        print(f"  ⚠️ logbooks and memory files may still name {old}; "
              f"`grep -rl '{old}' {target(man['tasks']['path'], old, home)} {home}/.claude` lists them")
        print(f"  ⚠️ if Baton's settings name the tasks folder by its old path, point them at "
              f"{target(man['tasks']['path'], old, home)}")
    for label, items in (("CONFLICT (exists, different; --force overwrites)", conflicts),
                         ("missing from the copied tree", missing),
                         ("key or login not in the copied tree -- carry it by hand", by_hand)):
        for p in items[:LIST]:
            print(f"  ✗ {label}: {p}")
        if len(items) > LIST:
            print(f"  ✗ ... and {len(items) - LIST} more {label.split(' (')[0].lower()}")
    print("\nRepositories (cloned, never copied by restore):")
    for r in man["repos"]:
        dst = target(r["path"], old, home)
        if (dst / ".git").exists():
            print(f"  ✓ {rel_to(dst, home)} is there")
        elif r.get("worktree_of"):
            print(f"  git -C {target(r['worktree_of'], old, home)} worktree add {dst} {r['branch']}")
        else:
            print(f"  git clone {r['remote'] or '<NO remote: copy the folder>'} {dst} && "
                  f"git -C {dst} checkout {r['branch']}")
    if man.get("crontab"):
        print("\ncrontab (not installed by restore). Save the lines below as crontab.txt, check the "
              "paths, then: crontab crontab.txt")
        if str(home) != old and old in man["crontab"]:
            print(f"  ⚠️ it names the old home {old}")
        print("\n".join("  | " + ln for ln in man["crontab"].splitlines()))
    enabled = sorted({Path(l).name for l in man.get("unit_links", []) if ".wants/" in l})
    if enabled:
        print("\nuser units the old machine had enabled (their files are restored above):")
        print(f"  systemctl --user daemon-reload && systemctl --user enable {' '.join(enabled)}")
    if man.get("plugins"):
        print("\nClaude plugins, by hand:")
        for name, source in (man.get("marketplaces") or {}).items():
            repo = source.get("repo") if isinstance(source, dict) else None
            print(f"  claude plugin marketplace add {repo or json.dumps(source)}   # {name}")
        for name in man["plugins"]:
            print(f"  claude plugin install {name}")
    print("\nThen: python3 tools/baton_move.py verify --manifest <manifest>"
          f"{' --home ' + str(home) if args.home else ''}")
    return 1 if conflicts or missing else 0


def verify(args) -> int:
    man = load(args.manifest)
    home, old = Path(args.home).expanduser().resolve() if args.home else Path.home(), man["home"]
    groups, bad = {}, False
    for entry in man["files"] + [dict(e, group="secrets") for e in man["secrets"]]:
        dst = target(entry["path"], old, home)
        g = groups.setdefault(entry["group"], {"ok": 0, "missing": [], "different": []})
        try:
            if not dst.is_file():
                g["missing"].append(entry["path"])
            elif not same(dst, entry):
                g["different"].append(entry["path"])
            else:
                g["ok"] += 1
        except OSError:
            g["missing"].append(entry["path"])
    print(f"Baton move -- verify {home} against the manifest of {man['user']}@{man['host']} ({man['made']})"
          f"{'' if man['hashed'] else '; no hashes in it: sizes compared, not content'}")
    for name in ("tasks", "claude", "config", "schedules", "transcripts", "secrets"):
        if name not in groups:
            continue
        g = groups[name]
        n = g["ok"] + len(g["missing"]) + len(g["different"])
        if g["missing"] or g["different"]:
            bad = True
            print(f"✗ {name}: {len(g['missing'])} missing, {len(g['different'])} different, of {n}")
            for kind in ("missing", "different"):
                for p in g[kind][:LIST]:
                    print(f"    {kind}: {p}")
                if len(g[kind]) > LIST:
                    print(f"    ... and {len(g[kind]) - LIST} more {kind}")
        else:
            print(f"✓ {name}: all {n} {'present, same SHA-256' if man['hashed'] or name == 'secrets' else 'present, same size'}")
    want = renamed(man["claude"]["memory_folder_of_home"], old, str(home))
    if man["claude"]["memory_folder_of_home"] in man["claude"]["memory_folders"]:
        found = (home / ".claude" / "projects" / want / "memory").is_dir()
        bad = bad or not found
        print(f"{'✓' if found else '✗'} memory folder: .claude/projects/{want}/memory "
              f"{'found' if found else 'NOT found'}")
    repo_bad = []
    for r in man["repos"]:
        dst = target(r["path"], old, home)
        if not (dst / ".git").exists():
            repo_bad.append(f"missing: {rel_to(dst, home)}")
            continue
        head = run("git", "-C", str(dst), "rev-parse", "HEAD")[1].strip()
        if head != r["head"]:
            repo_bad.append(f"{rel_to(dst, home)}: HEAD {head[:10] or '?'}, the old machine had {r['head'][:10]}")
        elif r["dirty"] and len(run("git", "-C", str(dst), "status", "--porcelain")[1].splitlines()) < r["dirty"]:
            repo_bad.append(f"{rel_to(dst, home)}: {r['dirty']} uncommitted changes on the old machine are not here")
    if man["repos"]:
        bad = bad or bool(repo_bad)
        print(f"{'✗' if repo_bad else '✓'} repositories: {len(man['repos']) - len(repo_bad)} of "
              f"{len(man['repos'])} present at the same HEAD")
        for line in repo_bad[:LIST]:
            print(f"    {line}")
    if man.get("crontab"):
        old_lines = [ln.replace(old, str(home)) for ln in man["crontab"].splitlines()
                     if ln.strip() and not ln.lstrip().startswith("#")]
        code, out, _ = run("crontab", "-l")
        now = set(out.splitlines()) if code == 0 else set()
        lost = [ln for ln in old_lines if ln not in now and ln.replace(str(home), old) not in now]
        bad = bad or bool(lost)
        print(f"{'✗' if lost else '✓'} crontab: {len(old_lines) - len(lost)} of {len(old_lines)} lines installed")
    if bad:
        print("\nNOT clean. Do not wipe the old disk until verify is clean.")
        return 1
    sk = man["tasks"]["skipped"]
    print("\nClean: everything in the manifest is here and the same. The old disk may be wiped "
          "now -- but not before this said clean. Still outside the manifest: its not_covered list"
          + (f", among them {sk['files']} files ({human(sk['bytes'])}) in the task folders that were "
             "never listed (made-anew folders, .batonignore)." if sk["files"] else "."))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Move the agent's world to a new computer.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("inventory", help="list what the agent's work depends on (read-only)")
    i.add_argument("--out", help="the manifest file (default: baton-move-manifest.json)")
    i.add_argument("--no-hash", action="store_true", help="sizes only: faster, verify compares sizes")
    i.add_argument("--transcripts", action="store_true", help="include Claude's conversation transcripts")
    r = sub.add_parser("restore", help="put a copied tree in place on the new machine")
    r.add_argument("--manifest", required=True)
    r.add_argument("--from", dest="src", required=True, help="the root the tree was copied into")
    r.add_argument("--home", help="the target home (default: this user's)")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--force", action="store_true", help="overwrite an existing different file")
    v = sub.add_parser("verify", help="check on the new machine that everything arrived")
    v.add_argument("--manifest", required=True)
    v.add_argument("--home", help="the target home (default: this user's)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass
    return {"inventory": inventory, "restore": restore, "verify": verify}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
