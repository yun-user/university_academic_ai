@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m scripts.evaluate_natural %*
if errorlevel 1 (
  echo Evaluation failed. Review the output above.
  pause
  exit /b 1
)
echo Open the natural-language evaluation page in the app to review answers.
pause
