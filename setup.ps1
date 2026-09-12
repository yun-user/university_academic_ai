$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
function Find-AcademicPython {
    $candidates = @()
    if ($env:ACADEMIC_PYTHON) {
        $candidates += [pscustomobject]@{ Exe = $env:ACADEMIC_PYTHON; Args = @() }
    }
    foreach ($commandName in @('python', 'python3', 'py')) {
        $command = Get-Command $commandName -CommandType Application -ErrorAction SilentlyContinue
        if ($command -and $command.Source -notmatch '\\Microsoft\\WindowsApps\\') {
            if ($commandName -eq 'py') {
                foreach ($version in @('-3.12', '-3.11', '-3')) {
                    $candidates += [pscustomobject]@{ Exe = $command.Source; Args = @($version) }
                }
            } else {
                $candidates += [pscustomobject]@{ Exe = $command.Source; Args = @() }
            }
        }
    }
    foreach ($registryRoot in @('HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore')) {
        foreach ($versionKey in @(Get-ChildItem -LiteralPath $registryRoot -ErrorAction SilentlyContinue)) {
            $installKey = Get-Item -LiteralPath (Join-Path $versionKey.PSPath 'InstallPath') -ErrorAction SilentlyContinue
            if ($installKey) {
                $directory = $installKey.GetValue('')
                if ($directory) {
                    $candidates += [pscustomobject]@{ Exe = (Join-Path $directory 'python.exe'); Args = @() }
                }
            }
        }
    }
    foreach ($directory in @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
        $env:ProgramFiles
    )) {
        foreach ($installation in @(Get-ChildItem -LiteralPath $directory -Directory -Filter 'Python*' -ErrorAction SilentlyContinue)) {
            $candidates += [pscustomobject]@{ Exe = (Join-Path $installation.FullName 'python.exe'); Args = @() }
        }
    }
    # Last resort on a Codex desktop installation; portable setups use normal Python above.
    $bundled = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    $candidates += [pscustomobject]@{ Exe = $bundled; Args = @() }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate.Exe -PathType Leaf)) { continue }
        try {
            $candidateArgs = @($candidate.Args)
            & $candidate.Exe @candidateArgs -c 'import sys, venv, ensurepip; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch { continue }
    }
    throw 'Python 3.11+ was not found. Install Python from https://www.python.org/downloads/windows/ or set ACADEMIC_PYTHON to python.exe, then run setup.cmd again.'
}

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    $interpreter = Find-AcademicPython
    $interpreterArgs = @($interpreter.Args)
    Write-Host ('Using Python: ' + $interpreter.Exe)
    & $interpreter.Exe @interpreterArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 이상을 설치한 뒤 다시 실행하세요.' }
}
$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $pythonExe -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
if ($LASTEXITCODE -ne 0) { throw 'Python 버전을 확인하세요.' }
& $pythonExe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw '패키지 설치에 실패했습니다.' }
& $pythonExe -m scripts.initialize
if ($LASTEXITCODE -ne 0) { throw '설정 준비에 실패했습니다.' }
& $pythonExe -m scripts.setup_ocr
if ($LASTEXITCODE -ne 0) { Write-Warning 'OCR 언어 데이터 설치 실패. 일반 PDF/CSV/TXT 검색은 계속 준비합니다.' }
& $pythonExe -m scripts.prepare
if ($LASTEXITCODE -ne 0) { throw '자료 처리 또는 검색 모델 준비에 실패했습니다.' }
Write-Host '설치 완료. start.ps1 또는 start.cmd로 실행하세요.'
