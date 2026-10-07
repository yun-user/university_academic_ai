@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup_planner.cmd first.
  pause
  exit /b 1
)
set LLM_ENABLED=false
set PLANNER_LOCAL_PORTAL=1
".venv\Scripts\python.exe" -m streamlit run planner_app.py --server.address 127.0.0.1 --server.port 8503 --browser.gatherUsageStats false
endlocal
