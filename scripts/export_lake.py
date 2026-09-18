"""
Make a copy of the lake small enough to deploy.

    python scripts/export_lake.py --out data/lake-slim

Telemetry is 98.5% of the lake: position data is 793 MB and car data 717 MB,
against 23 MB for everything else across all 420 sessions. It feeds exactly one
panel — the track map — and nothing else in the project reads it: not the timing
tower, the race trace, the tyre model, the strategy board, or any of the models.

So a deployment drops it. The result is small enough to live in a git repository
and be served from a free host, and everything except the track map works
untouched. Live mode already runs this way, which is how it is known to hold: a
live recording carries no telemetry either, by the same reasoning.

`--with-telemetry` keeps everything, for copying a full lake somewhere.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from racecraft import config

# The two tables that carry telemetry, and the only ones a deployment drops.
TELEMETRY = ("car_data", "pos_data")


def export(source: Path, destination: Path, skip: tuple[str, ...] = TELEMETRY,
           overwrite: bool = False) -> dict[str, int]:
    """Copy a lake, table by table, leaving out what is not worth deploying."""
    if not source.is_dir():
        raise FileNotFoundError(f"no lake at {source}")
    if destination.exists():
        if not overwrite:
            raise FileExistsError(f"{destination} exists; pass --overwrite to replace it")
        shutil.rmtree(destination)

    copied: dict[str, int] = {}
    for table_dir in sorted(p for p in source.iterdir() if p.is_dir()):
        if table_dir.name in skip:
            continue
        target = destination / table_dir.name
        shutil.copytree(table_dir, target)
        copied[table_dir.name] = sum(f.stat().st_size for f in target.rglob("*.parquet"))
    return copied


def _size(n: int) -> str:
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=config.DATA_DIR / "lake-slim",
                        help="where to write the copy")
    parser.add_argument("--lake", type=Path, default=None, help="source lake; defaults to config")
    parser.add_argument("--with-telemetry", action="store_true",
                        help="keep car and position data, for a full copy")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    source = args.lake or config.LAKE_DIR
    skip = () if args.with_telemetry else TELEMETRY
    try:
        copied = export(source, args.out, skip=skip, overwrite=args.overwrite)
    except (FileNotFoundError, FileExistsError) as error:
        print(error)
        return 1

    total = sum(copied.values())
    original = sum(f.stat().st_size for f in source.rglob("*.parquet"))
    print(f"\n{source}  ->  {args.out}\n")
    for name, size in sorted(copied.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<18} {_size(size):>10}")
    print(f"  {'':<18} {'':>10}")
    print(f"  {'exported':<18} {_size(total):>10}")
    print(f"  {'left behind':<18} {_size(original - total):>10}"
          f"  ({', '.join(skip) if skip else 'nothing'})")
    if skip:
        print(f"\n  {100 * total / original:.1f}% of the lake, and everything but the track map.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
