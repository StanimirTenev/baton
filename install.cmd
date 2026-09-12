@echo off
rem Baton installer for Windows.
rem
rem Double-click this file, or run it from a terminal. It launches install.ps1 with the
rem execution policy bypassed FOR THIS ONE PROCESS ONLY — no administrator, and nothing
rem about the machine's PowerShell policy is changed. A .cmd file is not itself subject to
rem the execution policy, which is why this works where a bare .ps1 gives
rem "running scripts is disabled on this system".
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
