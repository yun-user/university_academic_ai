$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'setup.ps1을 먼저 실행하세요.' }
& $pythonExe -m streamlit run app.py --server.address 127.0.0.1
