@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist "BardoAI.exe" (
    start "" "BardoAI.exe"
) else (
    .\.venv\Scripts\python.exe desktop_app.py
)
