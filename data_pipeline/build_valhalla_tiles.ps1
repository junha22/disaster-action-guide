[CmdletBinding()]
param(
    # Conda env that has pyvalhalla installed (backend runtime env).
    [string]$CondaEnv = 'disaster-action-guide',
    # Separate conda env with conda-forge osmium-tool, so the runtime env is not mixed with conda-forge.
    [string]$OsmCondaEnv = 'disaster-action-guide-osm',
    # Gwangju Metropolitan City bounding box plus about 5 km margin: minLon,minLat,maxLon,maxLat.
    [string]$BBox = '126.58,35.00,127.08,35.31',
    # Build from the whole South Korea extract instead of the Gwangju crop.
    [switch]$FullKorea,
    # Download the source pbf again even if it already exists.
    [switch]$Redownload
)
# Downloads OSM data, crops it to Gwangju and builds Valhalla tiles under .local-data/valhalla/.
# Nothing here is committed: .local-data/ is git-ignored.
# Paths given to Valhalla are relative to the project root on purpose: the project path contains
# non-ASCII characters and native Windows executables may not open such paths.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$sourceUrl = 'https://download.geofabrik.de/asia/south-korea-latest.osm.pbf'

function Get-CondaPrefix([string]$name) {
    $envs = (& conda env list --json | Out-String | ConvertFrom-Json).envs
    $prefix = $envs | Where-Object { (Split-Path $_ -Leaf) -eq $name } | Select-Object -First 1
    if (-not $prefix) { throw "Conda env '$name' not found." }
    return $prefix
}

# [IO.File] resolves relative paths against the process directory, which Push-Location does not change.
function Write-Utf8NoBom([string]$path, [string]$text) {
    [System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding $false))
}

# Windows PowerShell 5.1 turns native stderr lines into errors when output is redirected.
# Native tools log progress on stderr, so judge success by the exit code only.
function Invoke-Native([string]$exe, [string[]]$arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $exe @arguments 2>&1 | ForEach-Object { "$_" }
    } finally {
        $ErrorActionPreference = $previous
    }
}

$python = Join-Path (Get-CondaPrefix $CondaEnv) 'python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "python.exe not found in $CondaEnv." }
& $python -c "import valhalla"
if ($LASTEXITCODE -ne 0) { throw "pyvalhalla is not installed in $CondaEnv." }

Push-Location $root
try {
    $dataRel = '.local-data/valhalla'
    $null = New-Item -ItemType Directory -Path $dataRel -Force
    $sourceRel = "$dataRel/south-korea-latest.osm.pbf"
    $cropRel = "$dataRel/gwangju.osm.pbf"
    $tilesRel = "$dataRel/tiles"
    $extractRel = "$dataRel/tiles.tar"
    $configRel = "$dataRel/valhalla.json"

    # 1. Download and verify the Geofabrik extract.
    if ($Redownload -or -not (Test-Path -LiteralPath $sourceRel -PathType Leaf)) {
        Write-Output "Downloading $sourceUrl"
        Invoke-WebRequest -Uri $sourceUrl -OutFile "$sourceRel.part" -UseBasicParsing
        Move-Item -LiteralPath "$sourceRel.part" -Destination $sourceRel -Force
    }
    $md5Text = (Invoke-WebRequest -Uri "$sourceUrl.md5" -UseBasicParsing).Content
    if ($md5Text -is [byte[]]) { $md5Text = [System.Text.Encoding]::ASCII.GetString($md5Text) }
    $expected = ($md5Text.Trim() -split '\s+')[0].ToLowerInvariant()
    $actual = (Get-FileHash -LiteralPath $sourceRel -Algorithm MD5).Hash.ToLowerInvariant()
    if ($expected -ne $actual) {
        throw "MD5 mismatch for the source pbf (expected $expected, got $actual). If Geofabrik published a new file, run again with -Redownload."
    }
    Write-Output "Source pbf verified (md5 $actual)."

    # 2. Crop to Gwangju (or use the whole country).
    if ($FullKorea) {
        $buildInput = $sourceRel
    } else {
        $osmium = Join-Path (Get-CondaPrefix $OsmCondaEnv) 'Library\bin\osmium.exe'
        if (-not (Test-Path -LiteralPath $osmium -PathType Leaf)) {
            throw "osmium.exe not found. Create the env: conda create -n $OsmCondaEnv -c conda-forge --override-channels osmium-tool -y"
        }
        Invoke-Native $osmium @('extract', '--bbox', $BBox, '--strategy', 'complete_ways', '--overwrite', '-o', $cropRel, $sourceRel)
        if ($LASTEXITCODE -ne 0) { throw 'osmium extract failed. Retry with -FullKorea to skip cropping.' }
        $buildInput = $cropRel
    }

    # 3. Valhalla config. Exclude-polygon limits are raised so riverside zones fit in one request.
    # stdout is the JSON; stderr (a harmless runpy warning) is discarded so it cannot corrupt the file.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $configJson = & $python -W ignore -m valhalla.valhalla_build_config `
            --mjolnir-tile-dir $tilesRel `
            --mjolnir-tile-extract $extractRel `
            --mjolnir-data-processing-use-admin-db False `
            --mjolnir-admin "$dataRel/admins.sqlite" `
            --mjolnir-timezone "$dataRel/timezones.sqlite" `
            --service-limits-max-exclude-polygons-length 300000 `
            --service-limits-max-exclude-polygons-vertices 5000 `
            --service-limits-max-alternates 2 2>$null
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($LASTEXITCODE -ne 0) { throw 'valhalla_build_config failed.' }
    $configText = ($configJson | Out-String).Trim()
    $null = $configText | ConvertFrom-Json
    Write-Utf8NoBom (Join-Path $root $configRel) ($configText + "`n")

    # 4. Build tiles from scratch (only the tiles folder owned by this script is replaced).
    if (Test-Path -LiteralPath $tilesRel) { Remove-Item -LiteralPath $tilesRel -Recurse -Force }
    if (Test-Path -LiteralPath $extractRel) { Remove-Item -LiteralPath $extractRel -Force }
    $null = New-Item -ItemType Directory -Path $tilesRel -Force
    # pyvalhalla's CLI looks the executable up on PATH (shutil.which) before running it from its own
    # bin folder, so on Windows the bin folder has to be on PATH for this process.
    $valhallaBin = (& $python -m valhalla print_bin_path | Out-String).Trim()
    $oldPath = $env:PATH
    $env:PATH = "$valhallaBin;$oldPath"
    try {
        Invoke-Native $python @('-m', 'valhalla', 'valhalla_build_tiles', '-c', $configRel, $buildInput)
    } finally {
        $env:PATH = $oldPath
    }
    if ($LASTEXITCODE -ne 0) { throw 'valhalla_build_tiles failed.' }

    # 5. Pack tiles into one tar for faster loading. tile_dir still works if this step fails.
    Invoke-Native $python @('-W', 'ignore', '-m', 'valhalla.valhalla_build_extract', '-c', $configRel, '-v')
    if ($LASTEXITCODE -ne 0) { Write-Warning 'valhalla_build_extract failed; the backend will read tile_dir instead.' }

    $count = (Get-ChildItem -LiteralPath $tilesRel -Recurse -Filter *.gph | Measure-Object).Count
    if ($count -eq 0) { throw 'No .gph tiles were produced.' }
    Write-Output "VALHALLA_TILES_OK: $count tiles in $tilesRel, config $configRel"
} finally {
    Pop-Location
}
