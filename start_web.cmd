@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment is missing. Run setup_web.cmd in this folder first.
  goto failed
)
".venv\Scripts\python.exe" scripts\start_web.py
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo PATH could not start. Read the error above.
echo For missing dependencies or build files, run setup_web.cmd and retry.
if not "%PLANNER_NO_PAUSE%"=="1" pause
exit /b 1
