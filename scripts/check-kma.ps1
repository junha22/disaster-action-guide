[CmdletBinding()]
param()
# Diagnose the KMA (data.go.kr) key used by the backend. Run in the window where
# $env:KMA_SERVICE_KEY is set. Prints only HTTP status and result codes, never the key.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$raw = "$env:KMA_SERVICE_KEY".Trim()
if (-not $raw) { Write-Output 'KMA_SERVICE_KEY is not set in this window.'; exit 1 }
$key = if ($raw.Contains('%')) { $raw } else { [uri]::EscapeDataString($raw) }
Write-Output ("Key: set, length {0}, form {1}" -f $raw.Length, $(if ($raw.Contains('%')) { 'Encoding' } else { 'Decoding' }))

$kst = [DateTime]::UtcNow.AddHours(9)
$obs = $kst.Date.AddHours($kst.Hour)
if ($kst.Minute -lt 40) { $obs = $obs.AddHours(-1) }
$today = $kst.ToString('yyyyMMdd')
$from = $kst.AddDays(-2).ToString('yyyyMMdd')

$ncstQuery = '&pageNo=1&numOfRows=20&dataType=JSON&base_date=' + $obs.ToString('yyyyMMdd') +
             '&base_time=' + $obs.ToString('HH') + '00&nx=58&ny=74'
$warnQuery = '&pageNo=1&numOfRows=10&dataType=JSON&fromTmFc=' + $from + '&toTmFc=' + $today + '&warningType=2'
# Same services are offered by data.go.kr (serviceKey) and by KMA API Hub (apihub.kma.go.kr, authKey).
$checks = @(
    @{ Name = 'data.go.kr  - observation (RN1)'
       Url = 'https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst?serviceKey=' + $key + $ncstQuery },
    @{ Name = 'data.go.kr  - warning codes'
       Url = 'https://apis.data.go.kr/1360000/WthrWrnInfoService/getPwnCd?serviceKey=' + $key + $warnQuery },
    @{ Name = 'API Hub     - observation (RN1)'
       Url = 'https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getUltraSrtNcst?authKey=' + $key + $ncstQuery },
    @{ Name = 'API Hub     - warning codes'
       Url = 'https://apihub.kma.go.kr/api/typ02/openApi/WthrWrnInfoService/getPwnCd?authKey=' + $key + $warnQuery }
)

foreach ($check in $checks) {
    Write-Output ''
    Write-Output "== $($check.Name)"
    $status = 0
    $body = ''
    try {
        $response = Invoke-WebRequest -Uri $check.Url -UseBasicParsing -TimeoutSec 10
        $status = [int]$response.StatusCode
        $body = $response.Content
    } catch [System.Net.WebException] {
        if ($_.Exception.Response) {
            $status = [int]$_.Exception.Response.StatusCode
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $body = $reader.ReadToEnd()
        } else {
            Write-Output "Network error: $($_.Exception.Status)"
            continue
        }
    }
    Write-Output "HTTP $status"
    $codes = [regex]::Matches($body, '"?(resultCode|resultMsg|returnAuthMsg|returnReasonCode|errMsg)"?\s*[:>]\s*"?([^"<,}]*)')
    if ($codes.Count -gt 0) {
        $codes | ForEach-Object { Write-Output ("  {0}: {1}" -f $_.Groups[1].Value, $_.Groups[2].Value.Trim()) }
    } else {
        $text = ($body -replace '\s+', ' ').Trim()
        Write-Output ("  body: " + $text.Substring(0, [Math]::Min(200, $text.Length)))
    }
    $rn1 = [regex]::Match($body, '"category"\s*:\s*"RN1"[^}]*"obsrValue"\s*:\s*"?([^",}]*)')
    if ($rn1.Success) { Write-Output "  RN1 (mm): $($rn1.Groups[1].Value)" }
}
