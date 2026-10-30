[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Run setup-local.ps1 first.' }
$data = Join-Path $root '.local-data'
$null = New-Item -ItemType Directory -Path $data -Force
$oldMode = $env:KIROTHON_AI_MODE
$oldDatabase = $env:KIROTHON_DB_PATH
Push-Location (Join-Path $root 'backend')
try {
    $env:KIROTHON_AI_MODE = 'mock'
    $env:KIROTHON_DB_PATH = Join-Path $data 'records.sqlite3'
    Write-Output 'LOCAL MOCK MODE: no AWS calls; local DB only.'
    & $python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
    if ($LASTEXITCODE -ne 0) { throw 'Local API stopped with an error.' }
} finally {
    $env:KIROTHON_AI_MODE = $oldMode
    $env:KIROTHON_DB_PATH = $oldDatabase
    Pop-Location
}
