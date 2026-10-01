<#
Build the standalone Racecraft app with PyInstaller.

Run from the repo root, in the project venv. Builds the interface first if it is
missing, then freezes everything into dist\Racecraft\Racecraft.exe, which needs
no Python. That folder is directly sideloadable on its own (zip and copy), and
is also what build_msix.ps1 wraps.

    powershell -ExecutionPolicy Bypass -File packaging\build_app.ps1
#>
param(
    [string]$Python = "$PSScriptRoot\..\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$repo = Resolve-Path "$PSScriptRoot\.."

if (-not (Test-Path "$repo\web\dist\index.html")) {
    Write-Host "Building the interface..."
    Push-Location "$repo\web"
    try { npm install; npm run build } finally { Pop-Location }
}

& $Python -m PyInstaller "$repo\packaging\Racecraft.spec" --noconfirm `
    --distpath "$repo\dist" --workpath "$repo\build\pyi"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }

Write-Host ""
Write-Host "Built dist\Racecraft\Racecraft.exe"
Write-Host "Run it directly, or make an MSIX with build_msix.ps1."
