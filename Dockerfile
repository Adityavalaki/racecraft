# Racecraft on Hugging Face Spaces.
#
# Spaces serve on 7860 and run as a non-root user, and their filesystem is
# rebuilt on restart — so the lake ships in the image and anything ingested
# afterwards is pushed back to the Space repo (see racecraft/deploy/persist.py).
#
# The lake copied in is the slim one: 23 MB of timing against 1.5 GB with
# telemetry, which is everything except the track map.
#
#   python scripts/export_lake.py --out data/lake-slim --overwrite
#   cd web && npm ci && npm run build
#   docker build -t racecraft .

FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci || npm install
COPY web/ ./
RUN npm run build


FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

RUN useradd -m -u 1000 user
USER user
WORKDIR /home/user/app

COPY --chown=user pyproject.toml README.md ./
COPY --chown=user src/ ./src/
RUN pip install --user --no-cache-dir -e . && pip install --user --no-cache-dir huggingface_hub

COPY --chown=user --from=web /web/dist ./web/dist
# The slim lake, built by scripts/export_lake.py before docker build.
COPY --chown=user data/lake-slim ./data/lake

# Spaces rebuild the filesystem on restart, so an ingest has to be pushed back
# to the repo to last. Set HF_TOKEN as a Space secret to turn that on.
ENV RACECRAFT_PERSIST=hf \
    RACECRAFT_DATA_DIR=/home/user/app/data \
    RACECRAFT_LAKE_DIR=/home/user/app/data/lake \
    RACECRAFT_FASTF1_CACHE=/home/user/app/data/fastf1_cache

EXPOSE 7860
CMD ["python", "-m", "uvicorn", "racecraft.api.app:app", "--host", "0.0.0.0", "--port", "7860"]
