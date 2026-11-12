# Downloads the msedgedriver that matches this machine's WebView2 runtime (a driver of another
# major version refuses the session) into DEST and prints DEST. Microsoft publishes no checksums
# for the driver: its Authenticode signature is checked instead.
# Usage: powershell -NoProfile -File msedgedriver.ps1 -Dest C:\path\to\folder
param([Parameter(Mandatory = $true)][string]$Dest)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$runtime = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
$keys = @(
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$runtime",
    "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$runtime",
    "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$runtime"
)
$version = $keys | ForEach-Object { (Get-ItemProperty -Path $_ -Name pv -ErrorAction SilentlyContinue).pv } |
    Where-Object { $_ -and $_ -ne '0.0.0.0' } | Select-Object -First 1
if (-not $version) { throw 'The WebView2 runtime is not installed (no EdgeUpdate client key).' }

New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$driver = Join-Path $Dest 'msedgedriver.exe'
$zip = Join-Path $Dest 'edgedriver_win64.zip'
Invoke-WebRequest -UseBasicParsing -Uri "https://msedgedriver.microsoft.com/$version/edgedriver_win64.zip" -OutFile $zip
Expand-Archive -Path $zip -DestinationPath $Dest -Force
Remove-Item $zip

$signature = Get-AuthenticodeSignature -FilePath $driver
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
    throw "msedgedriver.exe is not signed by Microsoft: $($signature.Status) $($signature.SignerCertificate.Subject)"
}
$reported = & $driver --version
if ($reported -notmatch [regex]::Escape($version)) {
    throw "msedgedriver reports '$reported', the WebView2 runtime is $version"
}
Write-Output $Dest
