"""
Put Racecraft on the Desktop and in the Start menu, and retire the old watcher.

The shortcuts point at `racecraft.exe`, the launcher pip writes for the
`racecraft` GUI entry point — a GUI-subsystem executable, so starting it opens
no console. They carry the Racecraft icon.

Installing also removes what the app replaces: the Startup-folder launcher that
ran `racecraft-ingest --watch` at every logon, and any such watcher still
running. The app syncs while it is open instead, which is what was asked for,
and two things syncing the same lake is what the locks exist to prevent.

The work is done by PowerShell (WScript.Shell for the .lnk files), because that
is what Windows ships; there is no pywin32 to depend on.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import sysconfig
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

ICON = Path(__file__).with_name("racecraft.ico")
PROJECT_ROOT = Path(__file__).resolve().parents[3]
NAME = "Racecraft"
DESCRIPTION = "F1 strategy workbench: replay, tyres, strategy and the race simulator"
OLD_STARTUP_LAUNCHER = "racecraft-ingest.cmd"


def app_executable() -> Path:
    """`racecraft.exe`, next to the Python running this."""
    scripts = Path(sysconfig.get_path("scripts"))
    return scripts / ("racecraft.exe" if sys.platform == "win32" else "racecraft")


def _quote(value: object) -> str:
    """A PowerShell single-quoted string."""
    return "'" + str(value).replace("'", "''") + "'"


def install_script(target: Path | None = None) -> str:
    target = target or app_executable()
    return "\n".join([
        "$shell = New-Object -ComObject WScript.Shell",
        "$made = @()",
        "foreach ($folder in @([Environment]::GetFolderPath('Desktop'), "
        "[Environment]::GetFolderPath('Programs'))) {",
        f"  $link = $shell.CreateShortcut((Join-Path $folder {_quote(NAME + '.lnk')}))",
        f"  $link.TargetPath = {_quote(target)}",
        f"  $link.WorkingDirectory = {_quote(PROJECT_ROOT)}",
        f"  $link.IconLocation = {_quote(str(ICON) + ',0')}",
        f"  $link.Description = {_quote(DESCRIPTION)}",
        "  $link.Save()",
        "  $made += $link.FullName",
        "}",
        # The always-on watcher the app replaces: its logon launcher, and any
        # instance of it running now. Only our own command line is matched.
        f"$old = Join-Path ([Environment]::GetFolderPath('Startup')) {_quote(OLD_STARTUP_LAUNCHER)}",
        "if (Test-Path $old) { Remove-Item $old -Force; $made += \"removed $old\" }",
        "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
        "Where-Object { $_.CommandLine -like '*racecraft.ingest.cli*--watch*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $made += \"stopped watcher $($_.ProcessId)\" }",
        "$made -join \"`n\"",
    ])


def uninstall_script() -> str:
    return "\n".join([
        "$gone = @()",
        "foreach ($folder in @([Environment]::GetFolderPath('Desktop'), "
        "[Environment]::GetFolderPath('Programs'))) {",
        f"  $path = Join-Path $folder {_quote(NAME + '.lnk')}",
        "  if (Test-Path $path) { Remove-Item $path -Force; $gone += $path }",
        "}",
        "$gone -join \"`n\"",
    ])


def _powershell(script: str, run: Callable = subprocess.run) -> list[str]:
    result = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                 capture_output=True, text=True, timeout=60,
                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "PowerShell failed").strip())
    return [line for line in (result.stdout or "").splitlines() if line.strip()]


def install(run: Callable = subprocess.run) -> list[str]:
    """Create the shortcuts and retire the old watcher. Returns what was done."""
    if not app_executable().exists() and run is subprocess.run:
        raise FileNotFoundError(f"{app_executable()} is missing: run  pip install -e .[app]  first")
    done = _powershell(install_script(), run)
    log.info("shortcuts: %s", "; ".join(done))
    return done


def uninstall(run: Callable = subprocess.run) -> list[str]:
    done = _powershell(uninstall_script(), run)
    log.info("shortcuts removed: %s", "; ".join(done))
    return done
