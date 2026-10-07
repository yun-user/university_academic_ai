@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if not exist ".venv\Scripts\python.exe" exit /b 1
where npm.cmd >nul 2>nul
if errorlevel 1 (
  echo Install Node.js 22.12+ or 24 LTS and retry.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-web.txt
if errorlevel 1 exit /b 1
pushd frontend
call npm.cmd ci --no-fund --no-audit
if errorlevel 1 (popd & exit /b 1)
call npm.cmd run build
if errorlevel 1 (popd & exit /b 1)
popd
echo Setup complete. Run start_web.cmd.
pause
endlocal
