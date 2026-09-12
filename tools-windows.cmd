@echo off
rem ============================================================================
rem  Dev tools for Claude Code on Windows: git, gh, node + npm, ripgrep, python.
rem
rem  Uses winget. These install machine-wide, so accept the UAC (administrator)
rem  prompts when they appear. Re-running is safe - winget skips what is already
rem  installed. Separate from Baton on purpose: Baton needs no administrator;
rem  this toolchain does.
rem
rem  Why these: Git for Windows gives Claude Code its Bash tool; gh is the GitHub
rem  CLI for PRs and issues; node/npm run MCP servers (npx); ripgrep is fast search;
rem  python is the common runtime (and lets Baton use a system Python).
rem ============================================================================
setlocal
echo ============================================================
echo   Dev tools for Claude Code  (accept the UAC prompts)
echo   git, gh, node + npm, ripgrep (rg), python
echo ============================================================
echo.

where winget >nul 2>nul
if errorlevel 1 (
    echo winget was not found.
    echo Install "App Installer" from the Microsoft Store, then run this again.
    echo.
    pause
    exit /b 1
)

for %%P in (Git.Git GitHub.cli OpenJS.NodeJS.LTS BurntSushi.ripgrep.MSVC Python.Python.3.12) do (
    echo.
    echo --- %%P ---------------------------------------------
    winget install -e --id %%P --accept-package-agreements --accept-source-agreements
)

echo.
echo ============================================================
echo   Done. Open a NEW terminal (or log out/in) so PATH refreshes.
echo   Verify:
echo     git --version
echo     gh --version
echo     node --version   ^&^&   npm --version
echo     rg --version
echo     python --version
echo.
echo   GitHub CLI still needs a one-time login:  gh auth login
echo ============================================================
echo.
pause
