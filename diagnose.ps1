# Baton one-click setup + diagnostic.
#
# Installs Claude Code (if missing) and Baton, FIXES the usual PATH problem, verifies
# everything, and writes a full transcript to the flash drive so it can be read afterwards.
# Per-user, no administrator.
[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"   # a diagnostic must keep going and record failures

# --- where to write the log: flash root (parent of this script), else Desktop ---
$flashRoot = Split-Path $PSScriptRoot -Parent
$log = Join-Path $flashRoot "BATON-DIAGNOSTIKA.txt"
try { "probe" | Out-File -LiteralPath $log -Encoding UTF8 -ErrorAction Stop; Remove-Item $log -ErrorAction SilentlyContinue }
catch { $log = Join-Path ([Environment]::GetFolderPath("Desktop")) "BATON-DIAGNOSTIKA.txt" }

Start-Transcript -LiteralPath $log -Force | Out-Null
function Line($m) { Write-Host $m }

Line "==================================================================="
Line "  BATON DIAGNOSTIKA   $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Line "==================================================================="
Line "user:        $env:USERNAME"
Line "profile:     $env:USERPROFILE"
Line "OS:          $([Environment]::OSVersion.VersionString)"
Line "PS version:  $($PSVersionTable.PSVersion)"
Line "script dir:  $PSScriptRoot"
Line "flash root:  $flashRoot"
Line ""

$binDir   = Join-Path $env:USERPROFILE ".local\bin"
$claudeExe = Join-Path $binDir "claude.exe"

# --- 1. Claude Code -------------------------------------------------------
Line "--- 1. Claude Code -------------------------------------------------"
if (Test-Path -LiteralPath $claudeExe) {
    Line "claude.exe FOUND at: $claudeExe"
} else {
    Line "claude.exe NOT at $claudeExe - installing Claude Code (downloads from the internet)..."
    try {
        $script = Invoke-RestMethod https://claude.ai/install.ps1
        & ([scriptblock]::Create($script))
        Line "installer finished (exit context ok)"
    } catch {
        Line "CLAUDE INSTALL ERROR: $($_.Exception.Message)"
    }
    if (Test-Path -LiteralPath $claudeExe) { Line "claude.exe now present: $claudeExe" }
    else { Line "claude.exe STILL MISSING after install - searching common spots..." ;
           Get-ChildItem -Path $env:USERPROFILE -Recurse -Filter claude.exe -ErrorAction SilentlyContinue |
             Select-Object -First 5 -ExpandProperty FullName | ForEach-Object { Line "  found: $_" } }
}
if (Test-Path -LiteralPath $claudeExe) {
    Line "version: $(& $claudeExe --version 2>&1)"
}
Line ""

# --- 2. PATH (the usual 'command not found in a new terminal' cause) -------
Line "--- 2. PATH --------------------------------------------------------"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -and ($userPath.Split(';') -contains $binDir)) {
    Line "OK: '$binDir' is already on the persisted USER PATH."
    Line "    (If a new terminal still can't find claude, it wasn't truly fresh - log out/in.)"
} else {
    Line "PROBLEM: '$binDir' is NOT on the persisted USER PATH. This is why a new terminal"
    Line "         says claude is not found. Adding it now (user scope, no administrator)..."
    try {
        $newPath = if ([string]::IsNullOrEmpty($userPath)) { $binDir } else { "$userPath;$binDir" }
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Line "FIXED: added to user PATH. After the NEXT login (or a brand-new terminal) 'claude' works."
    } catch {
        Line "PATH FIX ERROR: $($_.Exception.Message)"
    }
}
Line ""

# --- 3. Baton -------------------------------------------------------------
Line "--- 3. Baton -------------------------------------------------------"
$batonInstaller = Join-Path $PSScriptRoot "install.ps1"
if (Test-Path -LiteralPath $batonInstaller) {
    Line "running: $batonInstaller"
    & powershell -NoProfile -ExecutionPolicy Bypass -File $batonInstaller 2>&1 | ForEach-Object { Line "  $_" }
} else {
    Line "ERROR: install.ps1 not found next to this script ($batonInstaller)"
}
Line ""

# --- 4. Verify Baton is wired in -----------------------------------------
Line "--- 4. Verify ------------------------------------------------------"
$settings = Join-Path $env:USERPROFILE ".claude\settings.json"
if (Test-Path -LiteralPath $settings) {
    Line "settings.json: present"
    $raw = Get-Content -LiteralPath $settings -Raw
    if ($raw -match "baton_") { Line "  Baton hooks: present in settings.json" }
    else { Line "  Baton hooks: NOT FOUND in settings.json" }
} else {
    Line "settings.json: MISSING ($settings)"
}
$hookPy = Join-Path $env:USERPROFILE ".claude\baton\hooks\baton_stop.py"
$pyExe  = Join-Path $env:USERPROFILE ".claude\baton\python-win\python.exe"
if ((Test-Path -LiteralPath $hookPy)) {
    Line "hook script: present"
    $runner = if (Test-Path -LiteralPath $pyExe) { $pyExe } else { "python" }
    Line "running the Stop hook the way the harness would (expect JSON or empty):"
    try { Line "  $('{}' | & $runner $hookPy 2>&1)" } catch { Line "  hook run error: $($_.Exception.Message)" }
} else {
    Line "hook script: MISSING ($hookPy)"
}
Line ""
Line "==================================================================="
Line "  DONE. This whole log is saved at:"
Line "  $log"
Line "  Bring the flash drive back so it can be read, or copy the text."
Line "==================================================================="

Stop-Transcript | Out-Null
Write-Host ""
Write-Host "Log written to: $log" -ForegroundColor Green
