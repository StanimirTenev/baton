@echo off
rem One-click: install Claude Code + Baton, fix PATH, and write a full log to the flash
rem drive (BATON-DIAGNOSTIKA.txt) that can be read afterwards to see what happened.
setlocal
set "PS1=%~dp0baton\diagnose.ps1"
if not exist "%PS1%" set "PS1=%~dp0diagnose.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
echo.
pause
