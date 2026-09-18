"""
Put Racecraft on a Hugging Face Space.

    python scripts/deploy_space.py --repo you/racecraft --dry-run   # see what would go
    python scripts/deploy_space.py --repo you/racecraft             # send it

Before the first run: create the Space at huggingface.co/new-space with SDK
"Docker" and "Blank" as the template, then make a write token at
huggingface.co/settings/tokens and either pass `--token` or set `HF_TOKEN`.

What it sends, and why only this:

* `Dockerfile`, `pyproject.toml`, `src/` — the application.
* `web/dist/` — the built interface. Building it on the Space would mean a node
  stage in the image, doubling the build for a 180 KB artifact.
* `data/lake-slim/` as `data/lake-slim` — the lake without telemetry: 23 MB
  against 1.5 GB, and everything except the track map.
* `README.md` — rewritten with the YAML front matter a Space needs. This is the
  one that is easy to miss: without `sdk: docker` and `app_port: 7860`, Hugging
  Face does not know what it has been given and the Space never starts.

Afterwards, set `HF_TOKEN` as a *secret* on the Space itself, under Settings.
Without it the app runs, but anything the Fetch new races button ingests is lost
when the Space restarts — which is the failure that looks like success.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Everything the image needs, and nothing else. A Space repo is a git
# repository: the lake is in it, so it wants to stay small.
SEND = [
    "Dockerfile",
    "pyproject.toml",
    "src",
    "web/dist",
    "data/lake-slim",
]

FRONT_MATTER = """---
title: Racecraft
emoji: 🏎️
colorFrom: gray
colorTo: red
sdk: docker
app_port: 7860
pinned: false
---

"""

SPACE_README = """# Racecraft

An F1 strategy workbench. It learns tyre, pace and pit behaviour from historic
timing data, models the car state the public feed does not expose, and simulates
races to find strategy windows.

Pick a session, scrub or play. The lower-right panel carries three tabs: the
race progression chart, modelled tyre wear against what the race actually did,
and a strategy board that ranks plans two ways — as arithmetic, and over
simulated races that can be neutralised.

**No track map here.** Position data is 793 MB against 23 MB for everything
else, and it feeds only that one panel. The hosted copy leaves it out; a local
one keeps it.

**What the models will not tell you.** The race simulator cannot predict
finishing order: given pace from earlier races only it scores 3.24 mean position
error against 3.31 for simply predicting the grid. It compares plans; it does
not forecast results, and the strategy panel lists what it cannot see beside
every ranking rather than behind a link.

Source, and the measurements behind all of it:
[github.com/Adityavalaki/racecraft](https://github.com/Adityavalaki/racecraft)
"""


def check(paths: list[str]) -> list[str]:
    missing = [p for p in paths if not (ROOT / p).exists()]
    return missing


def build_prerequisites(skip_build: bool) -> None:
    """The two things the image expects to already exist."""
    if not skip_build:
        print("building the interface…")
        subprocess.run(["npm", "run", "build"], cwd=ROOT / "web", check=True, shell=True)

    print("exporting the lake without telemetry…")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "export_lake.py"),
                    "--out", str(ROOT / "data" / "lake-slim"), "--overwrite"],
                   check=True)


def size_of(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def stage(destination: Path) -> Path:
    """Assemble exactly what the Space gets, so it can be looked at before it goes."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    for item in SEND:
        source = ROOT / item
        target = destination / item
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(source, target)

    (destination / "README.md").write_text(FRONT_MATTER + SPACE_README, encoding="utf-8")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, help='the Space, as "user/name"')
    parser.add_argument("--token", default=os.environ.get("HF_TOKEN"),
                        help="a write token; defaults to HF_TOKEN")
    parser.add_argument("--dry-run", action="store_true", help="assemble and report, send nothing")
    parser.add_argument("--skip-build", action="store_true",
                        help="use web/dist as it stands instead of rebuilding")
    args = parser.parse_args(argv)

    try:
        build_prerequisites(args.skip_build)
    except subprocess.CalledProcessError as error:
        print(f"\ncould not prepare: {error}")
        return 1

    missing = check(SEND)
    if missing:
        print("\nmissing, and needed:")
        for item in missing:
            print(f"  {item}")
        print("\n  web/dist      -> cd web && npm run build")
        print("  data/lake-slim -> python scripts/export_lake.py --out data/lake-slim")
        return 1

    staged = stage(ROOT / "data" / "space-build")
    total = size_of(staged)

    print(f"\nfor {args.repo}\n")
    for item in sorted(SEND) + ["README.md"]:
        size = size_of(staged / item)
        shown = f"{size / 1e6:.1f} MB" if size >= 1e6 else f"{size / 1e3:.0f} KB"
        print(f"  {item:<22} {shown:>9}")
    print(f"  {'total':<22} {total / 1e6:>6.1f} MB")

    if args.dry_run:
        print(f"\nassembled at {staged}. Nothing sent.")
        return 0

    if not args.token:
        print("\nno token. Make one at huggingface.co/settings/tokens with write access,")
        print("then pass --token or set HF_TOKEN.")
        return 1

    from huggingface_hub import HfApi

    print(f"\nsending to {args.repo}…")
    HfApi(token=args.token).upload_folder(
        folder_path=str(staged),
        repo_id=args.repo,
        repo_type="space",
        commit_message="Deploy Racecraft",
    )
    print(f"\nsent. It builds for a few minutes, then:  https://huggingface.co/spaces/{args.repo}")
    print("\nOne thing left, in the Space's Settings: add HF_TOKEN as a secret.")
    print("Without it the app runs, but anything Fetch new races brings in is lost")
    print("on the next restart — which looks like it worked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
