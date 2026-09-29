#!/bin/sh
# Start a Baton hook with the first real Python 3 on this machine.
#
# A plugin has no install step to pick the interpreter, as install.sh/install.ps1 do, so
# the choice is made here, each run. On Windows this runs in Git Bash. There `python3` is
# often the Microsoft Store stand-in, which prints "Python" and exits 0 without running
# anything (seen on 2026-09-29), so a candidate counts only if it answers with this text.
for py in python3 python py; do
    if [ "$("$py" -c 'import sys; print("baton-ok" if sys.version_info >= (3, 8) else "old")' 2>/dev/null)" = "baton-ok" ]; then
        exec "$py" "$@"
    fi
done
# A hook must never break the session it is trying to help: say why, and let it go on.
echo "Baton: no Python 3.8+ found (tried python3, python, py); the hooks did not run." >&2
exit 0
