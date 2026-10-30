[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$manifest = Get-Content -LiteralPath (Join-Path $root 'template-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$count = 0
foreach ($entry in $manifest.packaged_file_sha256.PSObject.Properties) {
    $path = Join-Path $root $entry.Name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing file: $($entry.Name)" }
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -cne $entry.Value) { throw "File differs from the delivered baseline: $($entry.Name)" }
    $count++
}
Write-Output "TEMPLATE_INTEGRITY_OK: $count files"

