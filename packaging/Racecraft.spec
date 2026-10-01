# PyInstaller spec for Racecraft: one standalone folder under dist/Racecraft.
#
# Build (from the repo root, in the venv):
#     python -m PyInstaller packaging/Racecraft.spec --noconfirm
#
# Produces dist/Racecraft/Racecraft.exe, which needs no Python. Frozen, the app
# writes its lake, caches and logs to %LOCALAPPDATA%\Racecraft (see
# racecraft.resources), so the install folder stays read-only — which is what
# MSIX requires.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve()                   # packaging/
REPO = ROOT.parent

datas = [
    (str(REPO / "web" / "dist"), "web/dist"),     # the built interface
    (str(REPO / "src" / "racecraft" / "app" / "racecraft.ico"), "racecraft/app"),
    (str(REPO / "src" / "racecraft" / "app" / "racecraft.png"), "racecraft/app"),
]
binaries = []
hiddenimports = [
    # uvicorn resolves these by name at runtime, so PyInstaller cannot see them.
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on", "uvicorn.lifespan.off",
    "websockets", "httptools",
    # pywebview picks its backend by import at runtime; name the Windows one.
    "webview.platforms.winforms",
    "clr",
]

# The heavy, native or dynamically-imported packages: take everything they ship.
for package in ("fastf1", "webview", "duckdb", "pyarrow", "pythonnet", "clr_loader"):
    extra_datas, extra_binaries, extra_hidden = collect_all(package)
    datas += extra_datas
    binaries += extra_binaries
    hiddenimports += extra_hidden

hiddenimports += collect_submodules("scipy")

a = Analysis(
    [str(ROOT / "entry.py")],
    pathex=[str(REPO / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Racecraft",
    console=False,                                # a window, not a terminal
    icon=str(REPO / "src" / "racecraft" / "app" / "racecraft.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="Racecraft")
