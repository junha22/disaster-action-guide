[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ServerHost,
    [Parameter(Mandatory=$true)][string]$KeyPath,
    [string]$ProjectPath = '.',
    [ValidateSet('Check','Deploy','Rollback')][string]$Mode = 'Check',
    [string]$Release = ''
)
$ErrorActionPreference = 'Stop'
if ($ServerHost -notmatch '^[A-Za-z0-9][A-Za-z0-9.-]*$') { throw 'Invalid server host' }
$key = (Resolve-Path -LiteralPath $KeyPath).Path
$project = (Resolve-Path -LiteralPath $ProjectPath).Path.TrimEnd('\','/')
if ($key.StartsWith($project + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Keep the PEM outside the project directory before using this tool.'
}
$null = Get-Command ssh -ErrorAction Stop
$null = Get-Command scp -ErrorAction Stop
$connection = 'ubuntu@' + $ServerHost
$options = @('-i', $key, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes')
$remoteTool = '/home/ubuntu/kirothon/backend/.venv/bin/python /home/ubuntu/kirothon-tools/deploy.py'

if ($Mode -eq 'Rollback') {
    if ($Release -notmatch '^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$') { throw 'Provide a valid deployment release ID.' }
    & ssh @options $connection "$remoteTool rollback --release $Release"
    if ($LASTEXITCODE -ne 0) { throw 'Rollback failed; preserve the release and inspect the server.' }
    return
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$fileMap = @{}
$roots = @('backend/app','frontend/src','frontend/public','.kiro/steering','.kiro/specs')
foreach ($relativeRoot in $roots) {
    $directory = Join-Path $project $relativeRoot
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) { continue }
    foreach ($item in Get-ChildItem -LiteralPath $directory -Recurse -Force) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Source links are not supported.' }
        if ($item.PSIsContainer) { continue }
        $relative = $item.FullName.Substring($project.Length + 1).Replace('\','/')
        $parts = $relative.Split('/')
        if ($parts | Where-Object { $_ -in @('.git','node_modules','.venv','__pycache__','dist','data','uploads') -or $_ -like '.env*' }) { continue }
        if ($item.Extension.ToLowerInvariant() -in @('.pem','.key','.pfx','.p12','.db','.sqlite','.sqlite3','.pyc')) { continue }
        if ($relativeRoot -eq 'backend/app' -and $item.Extension -cne '.py') { continue }
        if ($relativeRoot.StartsWith('.kiro/') -and $item.Extension -cne '.md') { continue }
        if ($relativeRoot.StartsWith('frontend/') -and ($parts | Select-Object -Skip 2 | Where-Object { $_.StartsWith('.') })) { continue }
        $fileMap[$relative] = $item.FullName
    }
}
$frontFiles = @('package.json','package-lock.json','index.html','vite.config.ts',
    'tsconfig.json','tsconfig.app.json','tsconfig.node.json','components.json',
    'eslint.config.js','eslint.config.mjs','oxlint.config.json','.oxlintrc.json')
$individual = @('backend/requirements.lock') + @($frontFiles | ForEach-Object { 'frontend/' + $_ })
foreach ($relative in $individual) {
    $path = Join-Path $project $relative
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        if ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Source links are not supported.' }
        $fileMap[$relative] = $path
    }
}
foreach ($required in @('backend/app/main.py','backend/requirements.lock','frontend/src/App.tsx',
                       'frontend/package.json','frontend/package-lock.json','frontend/index.html')) {
    if (-not $fileMap.ContainsKey($required)) { throw "Missing source file: $required" }
}

$temporary = Join-Path ([IO.Path]::GetTempPath()) ('kirothon-' + [Guid]::NewGuid().ToString('N') + '.zip')
try {
    $archive = [IO.Compression.ZipFile]::Open($temporary, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($relative in ($fileMap.Keys | Sort-Object)) {
            $text = [IO.File]::ReadAllText($fileMap[$relative])
            if ($text -match '-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[A-Z0-9]{16}') { throw 'Potential embedded credential detected; packaging refused.' }
            $null = [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $fileMap[$relative], $relative)
        }
    } finally { $archive.Dispose() }
    $hash = (Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLowerInvariant()
    $remoteFile = '/home/ubuntu/kirothon-incoming/' + [Guid]::NewGuid().ToString('N') + '.zip'
    & ssh @options $connection 'install -d -m 0700 /home/ubuntu/kirothon-incoming'
    if ($LASTEXITCODE -ne 0) { throw 'SSH connection failed. Check the host fingerprint through a separate first connection.' }
    & scp @options $temporary "${connection}:$remoteFile"
    if ($LASTEXITCODE -ne 0) { throw 'Source transfer failed.' }
    $verb = $Mode.ToLowerInvariant()
    & ssh @options $connection "$remoteTool $verb --archive $remoteFile --sha256 $hash"
    if ($LASTEXITCODE -ne 0) { throw 'Server check/deployment failed. Inspect the private deployment logs.' }
} finally {
    if (Test-Path -LiteralPath $temporary -PathType Leaf) { Remove-Item -LiteralPath $temporary -Force }
}
