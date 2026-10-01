<#
Pack the PyInstaller build into a signed Racecraft.msix for sideloading.

Prerequisites:
  1. The frozen app exists:  dist\Racecraft\Racecraft.exe
     Build it first:  python -m PyInstaller packaging\Racecraft.spec --noconfirm
  2. The Windows SDK is installed (for makeappx.exe and signtool.exe). Get it
     with:  winget install Microsoft.WindowsSDK.10.0.22621
  3. A signing cert exists:  packaging\msix\RacecraftDev.pfx
     Make it with:  packaging\make_cert.ps1

Then:
    powershell -ExecutionPolicy Bypass -File packaging\build_msix.ps1

Produces dist\Racecraft.msix, signed. Install it per packaging\README.md.
#>
param(
    [string]$DistApp  = "$PSScriptRoot\..\dist\Racecraft",
    [string]$Stage    = "$PSScriptRoot\..\build\msix-stage",
    [string]$Output   = "$PSScriptRoot\..\dist\Racecraft.msix",
    [string]$Pfx      = "$PSScriptRoot\msix\RacecraftDev.pfx",
    [string]$Password = "racecraft"
)

$ErrorActionPreference = "Stop"

function Find-SdkTool([string]$name) {
    $bin = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    $hit = Get-ChildItem -Path $bin -Recurse -Filter $name -ErrorAction SilentlyContinue |
           Where-Object { $_.FullName -match "\\x64\\" } |
           Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $hit) { throw "$name not found under $bin. Install the Windows SDK (see the header)." }
    return $hit.FullName
}

if (-not (Test-Path "$DistApp\Racecraft.exe")) {
    throw "No frozen app at $DistApp. Run PyInstaller first (see the header)."
}
if (-not (Test-Path $Pfx)) {
    throw "No signing certificate at $Pfx. Run make_cert.ps1 first."
}

$makeappx = Find-SdkTool "makeappx.exe"
$signtool = Find-SdkTool "signtool.exe"

# Stage: the frozen app at the package root, with the manifest and assets beside it.
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
Copy-Item "$DistApp\*" $Stage -Recurse -Force
Copy-Item "$PSScriptRoot\msix\AppxManifest.xml" $Stage -Force
Copy-Item "$PSScriptRoot\msix\Assets" $Stage -Recurse -Force

New-Item -ItemType Directory -Force -Path (Split-Path $Output) | Out-Null
if (Test-Path $Output) { Remove-Item -Force $Output }

& $makeappx pack /d $Stage /p $Output /o
if ($LASTEXITCODE -ne 0) { throw "makeappx failed ($LASTEXITCODE)" }

& $signtool sign /fd SHA256 /a /f $Pfx /p $Password $Output
if ($LASTEXITCODE -ne 0) { throw "signtool failed ($LASTEXITCODE)" }

Write-Host ""
Write-Host "Built and signed: $Output"
Write-Host "Install it with packaging\install_msix.ps1 (first trust the .cer)."
