"""
The frozen app's entry point.

A thin wrapper so PyInstaller has a script to start from; all it does is hand
over to the normal `racecraft` console entry (racecraft.app.main:main).
"""

import sys

from racecraft.app.main import main

if __name__ == "__main__":
    sys.exit(main())
