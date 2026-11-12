# Makes (or finds) the self-signed code-signing test certificate in Cert:\CurrentUser\My, trusts
# it on this machine, and writes the Tauri config overlay that signs with it. A test only: a
# release needs a certificate from a certification authority. Needs an elevated shell (the
# machine stores); the private key stays in this user's store.
#
#   powershell -File test-certificate.ps1 -Overlay C:\path\signing.json
#   npx tauri build --config C:\path\signing.json

param([Parameter(Mandatory = $true)][string]$Overlay)
$ErrorActionPreference = 'Stop'

$subject = 'CN=Reframe test signing'
$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
    Where-Object { $_.Subject -eq $subject } | Select-Object -First 1
if (-not $cert) {
    $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $subject `
        -CertStoreLocation Cert:\CurrentUser\My -KeyExportPolicy NonExportable `
        -NotAfter (Get-Date).AddYears(2)
}

# The machine stores, not the user's: an import into CurrentUser\Root waits for a click.
$public = Join-Path $env:TEMP 'reframe-test-signing.cer'
Export-Certificate -Cert $cert -FilePath $public | Out-Null
foreach ($store in 'Root', 'TrustedPublisher') {
    Import-Certificate -FilePath $public -CertStoreLocation "Cert:\LocalMachine\$store" | Out-Null
}
Remove-Item $public

$json = @{ bundle = @{ windows = @{
    certificateThumbprint = $cert.Thumbprint
    digestAlgorithm = 'sha256'
} } } | ConvertTo-Json -Depth 4
# Without a byte order mark: Tauri does not read a config that starts with one.
[IO.File]::WriteAllText($Overlay, $json)
$cert.Thumbprint
