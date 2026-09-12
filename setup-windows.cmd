@echo off
rem ============================================================================
rem  Baton bootstrap for a fresh Windows machine.
rem
rem  Double-click this. It installs Claude Code (if it is not already there) and
rem  then Baton. No administrator. Needs an internet connection, because Claude
rem  Code itself is downloaded from Anthropic.
rem
rem  Claude Code's own installer is used verbatim (claude.ai/install.cmd) — a
rem  native binary, no Node.js required. Baton is then installed from the folder
rem  next to this file.
rem ============================================================================
setlocal
echo ============================================================
echo   Baton setup: Claude Code + Baton
echo ============================================================
echo.

rem --- 1. Claude Code -------------------------------------------------------
where claude >nul 2>nul
if %errorlevel%==0 (
    echo [1/2] Claude Code is already installed - skipping.
) else (
    if exist "%USERPROFILE%\.local\bin\claude.exe" (
        echo [1/2] Claude Code is already installed - skipping.
    ) else (
        echo [1/2] Installing Claude Code ^(no administrator, downloads from the internet^)...
        curl -fsSL https://claude.ai/install.cmd -o "%TEMP%\claude-install.cmd"
        if errorlevel 1 (
            echo.
            echo     Could not download the Claude Code installer.
            echo     Check that this machine has an internet connection, then run this again.
            echo.
            pause
            exit /b 1
        )
        call "%TEMP%\claude-install.cmd"
        del "%TEMP%\claude-install.cmd" 2>nul
    )
)
echo.

rem --- 2. Baton ------------------------------------------------------------
rem Works whether Baton is in a "baton\" subfolder (USB layout) or right here (a clone).
set "BATON_DIR=%~dp0baton"
if not exist "%BATON_DIR%\install.ps1" set "BATON_DIR=%~dp0."
echo [2/2] Installing Baton from %BATON_DIR% ...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%BATON_DIR%\install.ps1"

echo.
echo ============================================================
echo   Done.
echo   Open a NEW terminal ^(so PATH refreshes^) and type:  claude
echo   Log in when the browser opens, then Baton is already active.
echo ============================================================
echo.
pause
