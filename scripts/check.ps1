$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root 'venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $python = 'python'
}

& $python -m ruff check --isolated --select E4,E7,E9,F .
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& $python -m pytest -q
exit $LASTEXITCODE
