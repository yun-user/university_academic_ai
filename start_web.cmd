@echo off
setlocal
cd /d "%~dp0"
if not exist "frontend\dist\index.html" (
  echo Run setup_web.cmd first.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" exit /b 1
echo Open http://127.0.0.1:8000 in your browser.
echo API documentation: http://127.0.0.1:8000/docs
echo Press Ctrl+C to stop the server.
".venv\Scripts\python.exe" -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --no-access-log
endlocal
