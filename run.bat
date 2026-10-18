@echo off
rem One-click launcher: creates the virtual env on first run, then starts the app.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Setting up for the first time...
    python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto :error
)
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" app.py
goto :eof

:error
echo.
echo Setup failed. Make sure Python 3.10+ is installed and on PATH.
pause
