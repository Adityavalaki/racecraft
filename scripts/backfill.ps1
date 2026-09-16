<#
.SYNOPSIS
    Run racecraft-ingest without letting Windows fall asleep mid-backfill.

.DESCRIPTION
    A full backfill runs for hours, most of it waiting out FastF1's hourly
    request limit. Idle sleep kills the process during those waits and the
    run stops silently. This asks Windows to stay awake until ingest exits,
    then releases that request.

    Only idle sleep is prevented. Closing the lid still sleeps the machine
    unless the lid action is changed in Windows power settings.

.EXAMPLE
    .\scripts\backfill.ps1
    .\scripts\backfill.ps1 --season 2024 2023 --prune-cache
#>

$ErrorActionPreference = "Stop"

if (-not $args -or $args.Count -eq 0) {
    $ingestArgs = @("--prune-cache")
} else {
    $ingestArgs = $args
}

Add-Type -Namespace Power -Name Sleep -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError = true)]
public static extern uint SetThreadExecutionState(uint esFlags);
'@

$ES_CONTINUOUS = [uint32]"0x80000000"
$ES_SYSTEM_REQUIRED = [uint32]"0x00000001"

$previous = [Power.Sleep]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED)
if ($previous -eq 0) {
    Write-Warning "Could not ask Windows to stay awake; the machine may sleep during the backfill."
} else {
    Write-Host "Keeping Windows awake until ingest finishes (the screen may still turn off)." -ForegroundColor Cyan
}

$ingest = Join-Path $PSScriptRoot "..\.venv\Scripts\racecraft-ingest.exe"
if (-not (Test-Path $ingest)) {
    throw "racecraft-ingest not found at $ingest. Create the venv first: python -m venv .venv; .venv\Scripts\python -m pip install -e "".[dev]"""
}

try {
    & $ingest @ingestArgs
    $code = $LASTEXITCODE
} finally {
    [void][Power.Sleep]::SetThreadExecutionState($ES_CONTINUOUS)   # release the request
    Write-Host "Sleep settings restored." -ForegroundColor Cyan
}

exit $code
