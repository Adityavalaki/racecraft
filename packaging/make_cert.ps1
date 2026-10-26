<#
Create a self-signed code-signing certificate for sideloading Racecraft.

An MSIX must be signed, and Windows will only install one whose signer it
trusts. For personal use a self-signed cert is enough: this makes one, exports
it as a .pfx (used to sign) and a .cer (installed once so Windows trusts it).

Its subject MUST equal the Publisher in AppxManifest.xml (CN=Racecraft Dev).

    powershell -ExecutionPolicy Bypass -File packaging\make_cert.ps1

Creates packaging\msix\RacecraftDev.pfx and RacecraftDev.cer. Keep the .pfx
private. The password defaults to "racecraft" — change it with -Password.
#>
param(
    [string]$Subject  = "CN=Racecraft Dev",
    [string]$Password = "racecraft",
    [string]$OutDir   = "$PSScriptRoot\msix"
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$cert = New-SelfSignedCertificate `
    -Type Custom `
    -Subject $Subject `
    -KeyUsage DigitalSignature `
    -FriendlyName "Racecraft sideload signing" `
    -CertStoreLocation "Cert:\CurrentUser\My" `
    -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}")

$pfx = Join-Path $OutDir "RacecraftDev.pfx"
$cer = Join-Path $OutDir "RacecraftDev.cer"
$secure = ConvertTo-SecureString -String $Password -Force -AsPlainText
Export-PfxCertificate -Cert "Cert:\CurrentUser\My\$($cert.Thumbprint)" -FilePath $pfx -Password $secure | Out-Null
Export-Certificate   -Cert "Cert:\CurrentUser\My\$($cert.Thumbprint)" -FilePath $cer | Out-Null

Write-Host "Certificate created."
Write-Host "  subject : $Subject   (must match AppxManifest.xml Publisher)"
Write-Host "  pfx     : $pfx   (keep private; used by build_msix.ps1)"
Write-Host "  cer     : $cer   (install once to trust it; see README)"
Write-Host "  thumb   : $($cert.Thumbprint)"
