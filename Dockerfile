# Racecraft on Hugging Face Spaces.
#
# Spaces serve on 7860, run as a non-root user, and rebuild their filesystem on
# restart — so the lake ships in the image, and anything ingested afterwards is
# pushed back to the Space repo (see racecraft/deploy/persist.py).
#
# Two things are built before this rather than in it: the interface, because a
# node stage doubles the build for an artifact that is 180 KB; and the lake,
# because the deployable copy leaves out telemetry — 23 MB against 1.5 GB, and
# everything except the track map. `python scripts/deploy_space.py` does both
# and pushes the result.
#
#   python scripts/export_lake.py --out data/lake-slim --overwrite
#   cd web && npm run build && cd ..
#   docker build -t racecraft .

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

RUN useradd -m -u 1000 user
USER user
WORKDIR /home/user/app

# Dependencies first: they change far less often than the code, so this layer
# survives most rebuilds.
COPY --chown=user pyproject.toml README.md ./
COPY --chown=user src/ ./src/
RUN pip install --user --no-cache-dir -e . \
    && pip install --user --no-cache-dir huggingface_hub

COPY --chown=user web/dist ./web/dist
COPY --chown=user data/lake-slim ./data/lake

# The filesystem is rebuilt on restart, so an ingest has to be pushed back to
# the repo to last. Set HF_TOKEN as a Space secret to turn that on; without it
# the app still runs and says, in the logs, that a fetch will not survive.
ENV RACECRAFT_PERSIST=hf \
    RACECRAFT_DATA_DIR=/home/user/app/data \
    RACECRAFT_LAKE_DIR=/home/user/app/data/lake \
    RACECRAFT_FASTF1_CACHE=/home/user/app/data/fastf1_cache

EXPOSE 7860
CMD ["python", "-m", "uvicorn", "racecraft.api.app:app", "--host", "0.0.0.0", "--port", "7860"]
