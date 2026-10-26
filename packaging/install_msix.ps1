<#
Trust the signing certificate and install the Racecraft MSIX.

Trusting the cert writes to the machine's Trusted People store, which needs an
elevated (Administrator) PowerShell. The install itself does not. Run this once
per machine; afterwards, new builds signed with the same cert install without
re-trusting.

    # In an elevated PowerShell:
    powershell -ExecutionPolicy Bypass -File packaging\install_msix.ps1

To update later: build a new .msix with a higher Version and run Add-AppxPackage
again (the cert is already trusted). To remove: Get-AppxPackage *Racecraft* |
Remove-AppxPackage.
#>
param(
    [string]$Cer  = "$PSScriptRoot\msix\RacecraftDev.cer",
    [string]$Msix = "$PSScriptRoot\..\dist\Racecraft.msix"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Cer))  { throw "No certificate at $Cer. Run make_cert.ps1 and build_msix.ps1 first." }
if (-not (Test-Path $Msix)) { throw "No package at $Msix. Run build_msix.ps1 first." }

$elevated = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $elevated) {
    throw "Trusting the certificate needs an elevated PowerShell. Re-run this as Administrator."
}

Import-Certificate -FilePath $Cer -CertStoreLocation "Cert:\LocalMachine\TrustedPeople" | Out-Null
Write-Host "Certificate trusted (LocalMachine\TrustedPeople)."

Add-AppxPackage -Path $Msix
Write-Host "Installed. Find Racecraft in the Start menu."
