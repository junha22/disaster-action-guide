[CmdletBinding()]
param(
    [string]$CondaEnv = 'disaster-action-guide'
)
# Local API in the conda env (replaces dev-backend.ps1 for this project).
# Mock AI, local DB under .local-data/. Optional keys come from (first one wins):
#   1. this window's environment ($env:KAKAO_REST_API_KEY = '...')
#   2. <project>/.env, passed to uvicorn with --env-file (see .env.example)
#   3. backend/.env, read by app/__init__.py (see backend/.env.example)
# Both .env files are git-ignored and never deployed. KIROTHON_AI_MODE=mock set below always wins.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root '.env'
$backendEnvFile = Join-Path $root 'backend\.env'

function Get-KeyStatus([string]$name, [string]$missing) {
    if (Test-Path -LiteralPath "env:$name") { return 'set' }
    foreach ($file in @($envFile, $backendEnvFile)) {
        if ((Test-Path -LiteralPath $file) -and (Select-String -LiteralPath $file -Pattern "^\s*$name=\S" -Quiet)) {
            return "set ($(Split-Path -Leaf (Split-Path -Parent $file))/.env)"
        }
    }
    return $missing
}

$envs = (& conda env list --json | Out-String | ConvertFrom-Json).envs
$prefix = $envs | Where-Object { (Split-Path $_ -Leaf) -eq $CondaEnv } | Select-Object -First 1
if (-not $prefix) { throw "Conda env '$CondaEnv' not found. See design.md section 12." }
$python = Join-Path $prefix 'python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "python.exe not found in $prefix." }

$data = Join-Path $root '.local-data'
$null = New-Item -ItemType Directory -Path $data -Force
$oldMode = $env:KIROTHON_AI_MODE
$oldDatabase = $env:KIROTHON_DB_PATH
Push-Location (Join-Path $root 'backend')
try {
    $env:KIROTHON_AI_MODE = 'mock'
    $env:KIROTHON_DB_PATH = Join-Path $data 'records.sqlite3'
    $kakao = Get-KeyStatus 'KAKAO_REST_API_KEY' 'not set (demo points)'
    $kma = Get-KeyStatus 'KMA_SERVICE_KEY' 'not set (demo weather)'
    Write-Output "LOCAL MOCK MODE: no AWS calls; local DB only. Kakao key: $kakao. KMA key: $kma."
    $uvicornArgs = @('-m', 'uvicorn', 'app.main:app', '--reload', '--host', '127.0.0.1', '--port', '8000')
    if (Test-Path -LiteralPath $envFile) { $uvicornArgs += @('--env-file', $envFile) }
    & $python @uvicornArgs
    if ($LASTEXITCODE -ne 0) { throw 'Local API stopped with an error.' }
} finally {
    $env:KIROTHON_AI_MODE = $oldMode
    $env:KIROTHON_DB_PATH = $oldDatabase
    Pop-Location
}
