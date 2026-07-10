@echo off
title Whisper Typing
cd /d "%~dp0"

echo Killing any stale whisper-typing processes...
powershell.exe -NoProfile -Command "Get-Process python -ErrorAction SilentlyContinue | Where-Object { try { $_.MainModule.FileName -like '*whisper-typing*' } catch { $false } } | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }"

echo Starting Whisper Typing...
.venv\Scripts\python.exe -m whisper_typing
if errorlevel 1 (
    echo.
    echo *** Application exited with error. ***
    pause
)
