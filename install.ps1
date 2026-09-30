# Baton installer (Windows). Per-user, no administrator, changes no machine policy.
#
# Run it through install.cmd (double-click) so the execution policy is bypassed for this
# one process. Or, from a terminal:
#     powershell -ExecutionPolicy Bypass -File .\install.ps1
#
#   $env:BATON_HOME    = "D:\tasks"      # where task folders live (default %USERPROFILE%\tasks)
#   $env:BATON_LOGBOOK = "DNEVNIK.md"    # logbook filename in your own language
#   .\install.ps1 -DryRun                # print what would change, touch nothing
[CmdletBinding()]
param([switch]$DryRun)

$ErrorActionPreference = "Stop"
$Repo      = $PSScriptRoot
$ClaudeDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME ".claude" }
$Settings  = Join-Path $ClaudeDir "settings.json"
$Install   = Join-Path $ClaudeDir "baton"     # hooks copied here, so the flash drive
$HookDir   = Join-Path $Install "hooks"       # (or clone, or download) can go away after
$Tasks     = if ($env:BATON_HOME) { $env:BATON_HOME } else { Join-Path $HOME "tasks" }
$Logbook   = if ($env:BATON_LOGBOOK) { $env:BATON_LOGBOOK } else { "LOGBOOK.md" }

# A reinstall keeps the task root and logbook it was given the first time (2026-09-28: a
# plain rerun wrote the defaults over them and every hook went quiet).
$Prev = Join-Path $HookDir "baton.local.json"
if (Test-Path $Prev) {
    try {
        $cfg = Get-Content $Prev -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $env:BATON_HOME -and $cfg.home) { $Tasks = $cfg.home }
        if (-not $env:BATON_LOGBOOK -and $cfg.logbook) { $Logbook = $cfg.logbook }
    } catch { }
}

function Say($m) { Write-Host "  $m" }

# A Python interpreter. The hooks are Python; one implementation for every OS.
# Order: one on PATH, else the copy bundled next to this script (a flash stick carries it),
# else tell the user the one-line, no-administrator winget command.
$PyLauncher = $null   # something runnable now, to run the merge step
$Seen = @()
foreach ($cand in @("py", "python", "python3")) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) {
        # A candidate counts only if it answers. The exit code is not enough: `python3` is
        # often the Microsoft Store stand-in, which prints "Python" and exits 0 without
        # running anything, and a Python older than 3.8 runs but cannot run Baton.
        $said = ""
        try {
            $said = (& $cand -c "import sys; print('baton-ok' if sys.version_info >= (3, 8) else 'old %d.%d' % sys.version_info[:2])" 2>$null | Out-String).Trim()
        } catch {}
        if ($said -eq "baton-ok") { $PyLauncher = $cand; break }
        $Seen += "    $($cmd.Source) -> $(if ($said) { $said } else { 'did not run' })"
    }
}

$Bundled = Join-Path $Repo "python-win\python.exe"
if (-not $PyLauncher -and (Test-Path -LiteralPath $Bundled)) {
    # No Python on the machine — use the bundled one, copied into the profile so it
    # outlives the flash drive.
    $BundledDst = Join-Path $Install "python-win"
    if ($DryRun) {
        # A dry run copies nothing, so it must point at the source. It used to name
        # the destination it had just decided not to create, and every later step
        # then ran against a path that does not exist -- reported by an external
        # review of v2.14.0 from a static read.
        $PyLauncher = $Bundled
    } else {
        New-Item -ItemType Directory -Force -Path $Install | Out-Null
        Copy-Item (Join-Path $Repo "python-win") $BundledDst -Recurse -Force
        $PyLauncher = Join-Path $BundledDst "python.exe"
    }
    Say "no Python on the machine - using the bundled interpreter"
}

if (-not $PyLauncher) {
    Write-Host "baton: no usable Python 3.8 or later, and no bundled copy is next to this script. Nothing has been installed." -ForegroundColor Yellow
    if ($Seen.Count) { Write-Host "  found, not usable:"; $Seen | ForEach-Object { Write-Host $_ } }
    Write-Host "Install it once, for your user only (no administrator):"
    Write-Host "    winget install -e --id Python.Python.3.12 --scope user"
    Write-Host "Open a new terminal so PATH refreshes, then run this installer again."
    Write-Host "(Or use the USB build of Baton, which carries Python with it.)"
    exit 1
}
# absolute interpreter path — baked into the hook so it never depends on PATH at run time
$PyExe = (& $PyLauncher -c "import sys; print(sys.executable)").Trim()
# The merge steps print paths in Python. Through a pipe (an agent's shell, ssh) PowerShell reads
# them in the console's code page and Python writes the ANSI one, so Cyrillic came out garbled:
# both sides agree on UTF-8 for this run, and the console gets its own back at the end.
$OldOutEnc = [Console]::OutputEncoding
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }

Write-Host "Baton"
Say "repo:     $Repo"
Say "config:   $ClaudeDir"
Say "tasks:    $Tasks"
Say "logbook:  $Logbook"
Say "python:   $PyExe"
if ($DryRun) { Say "(dry run - nothing will be written)" }
Write-Host ""

# 1. task root
if (Test-Path -LiteralPath $Tasks -PathType Container) {
    Say "task root exists"
} else {
    Say "create task root"
    if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $Tasks | Out-Null }
}

# 2. instructions
# with this machine's task root and logbook written in; a copy of the old file is kept
$dryFlag = if ($DryRun) { "1" } else { "0" }
& $PyLauncher (Join-Path $Repo "hooks\_install_rules.py") (Join-Path $Repo "templates\CLAUDE.md") (Join-Path $ClaudeDir "CLAUDE.md") $Tasks $Logbook $dryFlag

# 3. copy the runtime hooks to a permanent location, so the flash drive can be removed
if ($DryRun) {
    Say "would copy hooks to $HookDir"
} else {
    New-Item -ItemType Directory -Force -Path $HookDir | Out-Null
    Copy-Item (Join-Path $Repo "hooks\baton_session_start.py") $HookDir -Force
    Copy-Item (Join-Path $Repo "hooks\baton_stop.py") $HookDir -Force
    Copy-Item (Join-Path $Repo "hooks\baton_prompt.py") $HookDir -Force
    Say "hooks copied to $HookDir"
}

# 3b. skills — /baton-inventory (map existing work) and /baton-plan (goal -> research -> plan)
foreach ($skill in Get-ChildItem -Directory (Join-Path $Repo "skills")) {
    $SkillDir = Join-Path $ClaudeDir ("skills\" + $skill.Name)
    if ($DryRun) {
        Say "would copy skill to $SkillDir"
    } else {
        New-Item -ItemType Directory -Force -Path $SkillDir | Out-Null
        Copy-Item (Join-Path $skill.FullName "SKILL.md") $SkillDir -Force
        Say "skill copied to $SkillDir"
    }
}

# 4. local config + hooks, merged into settings.json without disturbing anything else
$dryArg = if ($DryRun) { "1" } else { "0" }
& $PyLauncher (Join-Path $Repo "hooks\_install_hooks.py") $Settings $HookDir $PyExe $dryArg $Tasks $Logbook $Repo
try { [Console]::OutputEncoding = $OldOutEnc } catch { }

Write-Host ""
Write-Host "Done. Open /hooks once in Claude Code (or restart) so it reloads settings.json."
Write-Host "Then: make a folder in $Tasks, put a $Logbook in it, and the hooks take over."
Write-Host "Existing work on this machine? Run /baton-inventory once to map it into task folders."
Write-Host "A big new goal? Start it with /baton-plan (research rounds, then the plan)."
