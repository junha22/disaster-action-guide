[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$python = Join-Path $backend '.venv\Scripts\python.exe'

$null = Get-Command node -ErrorAction Stop
$null = Get-Command npm.cmd -ErrorAction Stop
& node -e "if (Number(process.versions.node.split('.')[0]) !== 24) process.exit(1)"
if ($LASTEXITCODE -ne 0) { throw 'Install Node.js 24.x before setup.' }

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv (Join-Path $backend '.venv')
    } else {
        $null = Get-Command python -ErrorAction Stop
        & python -c "import sys; assert sys.version_info[:2] == (3,12), 'Python 3.12 required'"
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 before setup.' }
        & python -m venv (Join-Path $backend '.venv')
    }
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 venv creation failed.' }
}
& $python -c "import sys; assert sys.version_info[:2] == (3,12), 'Python 3.12 required'"
if ($LASTEXITCODE -ne 0) { throw 'Existing venv is not Python 3.12. Do not overwrite it automatically.' }
& $python -m pip install --require-hashes -r (Join-Path $backend 'requirements.local.lock')
if ($LASTEXITCODE -ne 0) { throw 'Local Python dependency installation failed.' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Python dependency check failed.' }

Push-Location (Join-Path $root 'frontend')
try {
    & npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
} finally { Pop-Location }
Write-Output 'LOCAL_SETUP_OK'
