@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Python 3.11 or newer is required. Install Python and retry.
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements-planner.txt
if errorlevel 1 exit /b 1
echo Setup complete. Run start_planner.cmd.
pause
endlocal
