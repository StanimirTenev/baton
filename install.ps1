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

function Say($m) { Write-Host "  $m" }

# Find a Python launcher on PATH. The hooks are Python; one implementation for every OS.
$BarePy = $null
foreach ($cand in @("py", "python", "python3")) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) {
        # `py` with no args can hang waiting for input on some setups; probe with -V.
        try { & $cand -V *> $null; if ($LASTEXITCODE -eq 0) { $BarePy = $cand; break } } catch {}
    }
}
if (-not $BarePy) {
    Write-Host "baton: Python was not found on PATH." -ForegroundColor Yellow
    Write-Host "Install it once, for your user only (no administrator):"
    Write-Host "    winget install -e --id Python.Python.3.12 --scope user"
    Write-Host "Open a new terminal so PATH refreshes, then run this installer again."
    exit 1
}

Write-Host "Baton"
Say "repo:     $Repo"
Say "config:   $ClaudeDir"
Say "tasks:    $Tasks"
Say "logbook:  $Logbook"
Say "python:   $BarePy"
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
$ClaudeMd = Join-Path $ClaudeDir "CLAUDE.md"
if ($DryRun) {
    Say "would append Baton section to $ClaudeMd"
} else {
    if (-not (Test-Path -LiteralPath $ClaudeDir)) { New-Item -ItemType Directory -Force -Path $ClaudeDir | Out-Null }
    if ((Test-Path -LiteralPath $ClaudeMd) -and (Select-String -LiteralPath $ClaudeMd -Pattern "Installed by Baton" -Quiet)) {
        Say "instructions already present - left as they are"
    } else {
        $body = Get-Content -LiteralPath (Join-Path $Repo "CLAUDE.md") -Raw -Encoding UTF8
        if (Test-Path -LiteralPath $ClaudeMd) { $body = "`n`n---`n`n" + $body }
        # UTF-8 without BOM, so the file reads cleanly everywhere.
        $enc = New-Object System.Text.UTF8Encoding($false)
        $existing = if (Test-Path -LiteralPath $ClaudeMd) { [IO.File]::ReadAllText($ClaudeMd, $enc) } else { "" }
        [IO.File]::WriteAllText($ClaudeMd, $existing + $body, $enc)
        Say "instructions appended to $ClaudeMd"
    }
}

# 3. copy the runtime hooks to a permanent location, so the flash drive can be removed
if ($DryRun) {
    Say "would copy hooks to $HookDir"
} else {
    New-Item -ItemType Directory -Force -Path $HookDir | Out-Null
    Copy-Item (Join-Path $Repo "hooks\baton_session_start.py") $HookDir -Force
    Copy-Item (Join-Path $Repo "hooks\baton_stop.py") $HookDir -Force
    Say "hooks copied to $HookDir"
}

# 4. local config + hooks, merged into settings.json without disturbing anything else
$dryArg = if ($DryRun) { "1" } else { "0" }
& $BarePy (Join-Path $Repo "hooks\_install_hooks.py") $Settings $HookDir $BarePy $dryArg $Tasks $Logbook

Write-Host ""
Write-Host "Done. Open /hooks once in Claude Code (or restart) so it reloads settings.json."
Write-Host "Then: make a folder in $Tasks, put a $Logbook in it, and the hooks take over."
