@echo off
cd /d "%~dp0"
set "PY=%~dp0runtime\python\python.exe"
if not exist "%PY%" set "PY=%~dp0venv\Scripts\python.exe"
"%PY%" "%~dp0recovery.py" shortcut
pause
