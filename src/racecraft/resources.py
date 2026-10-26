"""
Where things live when Racecraft runs frozen (PyInstaller or the MSIX built
from it) rather than from a source checkout.

Frozen, the code sits read-only inside the install — an MSIX install is
read-only outright — so everything written (the lake, the caches, the logs)
goes to a per-user folder instead, and the bundled files (the built interface,
the window icon) move into PyInstaller's extraction directory. None of this
touches a normal checkout: `frozen()` is False there, the old project-relative
paths stand, and the tests see no change.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def frozen() -> bool:
    """True when running from a PyInstaller build (and so from the MSIX)."""
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """The folder holding the bundled data files: web/dist and the icon."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else Path(__file__).resolve().parents[2]


def user_data_dir() -> Path:
    """A writable per-user home for the lake, caches and logs of a frozen app."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "Racecraft"
