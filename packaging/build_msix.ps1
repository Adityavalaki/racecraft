<#
Pack the PyInstaller build into a signed Racecraft.msix for sideloading.

Prerequisites:
  1. The frozen app exists:  dist\Racecraft\Racecraft.exe
     Build it first:  powershell -ExecutionPolicy Bypass -File packaging\build_app.ps1
  2. A signing cert exists:  packaging\msix\RacecraftDev.pfx
     Make it with:  powershell -ExecutionPolicy Bypass -File packaging\make_cert.ps1

The packaging tools (makeappx.exe, signtool.exe) are found automatically: if the
Windows SDK is installed they are used from there, otherwise they are downloaded
once from the official Microsoft.Windows.SDK.BuildTools NuGet package into
build\sdk-tools (no admin, no winget, no full SDK install).

Run from the repo root:
    powershell -ExecutionPolicy Bypass -File packaging\build_msix.ps1

Produces dist\Racecraft.msix, signed. Install it with install_msix.ps1.
#>
param(
    [string]$DistApp  = "$PSScriptRoot\..\dist\Racecraft",
    [string]$Stage    = "$PSScriptRoot\..\build\msix-stage",
    [string]$Output   = "$PSScriptRoot\..\dist\Racecraft.msix",
    [string]$Pfx      = "$PSScriptRoot\msix\RacecraftDev.pfx",
    [string]$Password = "racecraft",
    [string]$ToolsDir = "$PSScriptRoot\..\build\sdk-tools"
)

$ErrorActionPreference = "Stop"

function Get-SdkTools([string]$toolsDir) {
    # Already downloaded?
    $have = Get-ChildItem -Path $toolsDir -Recurse -Filter makeappx.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "\\x64\\" } | Select-Object -First 1
    if (-not $have) {
        # Installed Windows SDK?
        $kits = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
        $have = Get-ChildItem -Path $kits -Recurse -Filter makeappx.exe -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match "\\x64\\" } |
                Sort-Object FullName -Descending | Select-Object -First 1
    }
    if (-not $have) {
        Write-Host "Fetching packaging tools from NuGet (one-time)..."
        New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
        $index = Invoke-RestMethod "https://api.nuget.org/v3-flatcontainer/microsoft.windows.sdk.buildtools/index.json"
        $ver = ($index.versions | Where-Object { $_ -notmatch "-" })[-1]
        $nupkg = Join-Path $toolsDir "buildtools.zip"
        Invoke-WebRequest "https://api.nuget.org/v3-flatcontainer/microsoft.windows.sdk.buildtools/$ver/microsoft.windows.sdk.buildtools.$ver.nupkg" -OutFile $nupkg
        Expand-Archive -Path $nupkg -DestinationPath (Join-Path $toolsDir "extracted") -Force
        $have = Get-ChildItem -Path $toolsDir -Recurse -Filter makeappx.exe -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match "\\x64\\" } | Select-Object -First 1
    }
    if (-not $have) { throw "Could not find or fetch makeappx.exe." }
    $dir = Split-Path $have.FullName
    return @{ makeappx = (Join-Path $dir "makeappx.exe"); signtool = (Join-Path $dir "signtool.exe") }
}

if (-not (Test-Path "$DistApp\Racecraft.exe")) {
    throw "No frozen app at $DistApp. Run build_app.ps1 first."
}
if (-not (Test-Path $Pfx)) {
    throw "No signing certificate at $Pfx. Run make_cert.ps1 first."
}

$tools = Get-SdkTools $ToolsDir

# Stage: the frozen app at the package root, with the manifest and assets beside it.
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
Copy-Item "$DistApp\*" $Stage -Recurse -Force
Copy-Item "$PSScriptRoot\msix\AppxManifest.xml" $Stage -Force
Copy-Item "$PSScriptRoot\msix\Assets" $Stage -Recurse -Force

New-Item -ItemType Directory -Force -Path (Split-Path $Output) | Out-Null
if (Test-Path $Output) { Remove-Item -Force $Output }

& $tools.makeappx pack /d $Stage /p $Output /o
if ($LASTEXITCODE -ne 0) { throw "makeappx failed ($LASTEXITCODE)" }

& $tools.signtool sign /fd SHA256 /f $Pfx /p $Password $Output
if ($LASTEXITCODE -ne 0) { throw "signtool failed ($LASTEXITCODE)" }

Write-Host ""
Write-Host "Built and signed: $Output"
Write-Host "Install it (elevated) with:  powershell -ExecutionPolicy Bypass -File packaging\install_msix.ps1"
