"""
Keeping the lake when the filesystem does not.

Most free hosting rebuilds the container on every restart, Hugging Face Spaces
included. A lake written into that container is real until the process restarts
and then is not, which is worse than not having ingested at all: it looks like
it worked, and the failure arrives hours later with no obvious cause.

So after an ingest the lake is pushed back to the repository the Space is built
from, which is durable and versioned, and the Space rebuilds with it. This is
only affordable because a lake without telemetry is 23 MB against 1.5 GB with
it; pushing the full one anywhere on a timer would not be reasonable.

Everything here is a no-op unless configured. On a machine with its own disk —
a laptop, a VPS — the lake is already saved by having been written, and
`save_lake` says so and returns.

    RACECRAFT_PERSIST=hf         push to a Hugging Face repo
    HF_TOKEN=hf_...              a token with write access
    RACECRAFT_HF_REPO=user/name  which repo, if not inferred from the Space
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from racecraft import config

log = logging.getLogger(__name__)

MODE = os.environ.get("RACECRAFT_PERSIST", "").strip().lower()
HF_REPO = os.environ.get("RACECRAFT_HF_REPO", "").strip()
# Hugging Face sets this inside a Space; it is the repo the Space is built from.
HF_SPACE = os.environ.get("SPACE_ID", "").strip()


class NotConfigured(RuntimeError):
    """Nothing to push to, which on a machine with a disk is the normal case."""


def target_repo() -> str:
    repo = HF_REPO or HF_SPACE
    if not repo:
        raise NotConfigured("set RACECRAFT_HF_REPO, or run inside a Space")
    return repo


def enabled() -> bool:
    return MODE == "hf"


def describe() -> dict:
    """What persistence is configured, for the status endpoint to report."""
    if not enabled():
        return {"mode": "disk", "durable": True,
                "detail": "the lake is on a disk of its own; nothing to push"}
    try:
        repo = target_repo()
    except NotConfigured as error:
        return {"mode": "hf", "durable": False, "detail": str(error)}
    return {"mode": "hf", "durable": bool(os.environ.get("HF_TOKEN")), "repo": repo,
            "detail": ("pushes the lake to the Space repo after an ingest"
                       if os.environ.get("HF_TOKEN") else "no HF_TOKEN, so an ingest will not last")}


def save_lake(message: str, lake_dir: Path | None = None) -> str | None:
    """
    Push the lake so it survives a restart. Returns what it did, or None.

    Never raises for being unconfigured: a laptop is the common case and it is
    not an error there.
    """
    if not enabled():
        log.info("persistence off: the lake stays on disk")
        return None

    lake_dir = lake_dir or config.LAKE_DIR
    if not lake_dir.is_dir():
        log.warning("no lake at %s to push", lake_dir)
        return None

    token = os.environ.get("HF_TOKEN")
    if not token:
        # Loud, because an ingest without this is lost on the next restart and
        # nothing else will say so.
        log.error("RACECRAFT_PERSIST=hf but HF_TOKEN is not set; this ingest will not survive "
                  "a restart")
        return None

    from huggingface_hub import HfApi

    repo = target_repo()
    size = sum(f.stat().st_size for f in lake_dir.rglob("*.parquet"))
    log.info("pushing %.1f MB of lake to %s", size / 1e6, repo)

    HfApi(token=token).upload_folder(
        folder_path=str(lake_dir),
        path_in_repo="data/lake",
        repo_id=repo,
        repo_type="space" if (HF_SPACE and repo == HF_SPACE) else "dataset",
        commit_message=message,
    )
    log.info("pushed to %s", repo)
    return f"pushed {size / 1e6:.1f} MB to {repo}"
