[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend\node_modules') -PathType Container)) {
    throw 'Run setup-local.ps1 first.'
}
Push-Location (Join-Path $root 'frontend')
try {
    & npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort
    if ($LASTEXITCODE -ne 0) { throw 'Local frontend stopped with an error.' }
} finally { Pop-Location }
