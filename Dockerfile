# ---------------------------------------------------------------------------
# Stage 1: build the frontend bundle
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend

# Cache npm install layer — only re-runs when package*.json changes
COPY frontend/package.json frontend/package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

COPY frontend/ ./
# Vite output → /app/frontend/dist
RUN npm run build


# ---------------------------------------------------------------------------
# Stage 2: backend runtime
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# Runtime system deps:
#   libgl1 + libglib2.0-0 → required by docling's rapidocr-onnxruntime path
#   libgomp1              → onnxruntime OMP runtime (used by docling)
#   curl                  → for the compose healthcheck
#   gosu                  → drop to the non-root user in the entrypoint
# Everything else (sqlite-vec, pymupdf, etc.) ships as Python wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        curl \
        gosu \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/app/data

WORKDIR /app

# Install backend Python deps first so source edits don't bust the wheel layer
COPY backend/pyproject.toml backend/
# Install CPU-only PyTorch BEFORE the backend so docling's transitive torch
# dependency resolves to the CPU build. The default PyPI torch wheel drags in
# ~4.3GB of CUDA libraries (nvidia-*, triton) this image never uses: there is
# no GPU here, and the default extractor is pymupdf (docling is opt-in via
# EXTRACTOR_BACKEND=docling). Pre-installing satisfies the constraint so the
# later `pip install ./backend` reuses it instead of pulling the CUDA wheel.
# torch/torchvision are PINNED (exact) — they are the highest-churn, largest,
# behavior-affecting binary deps and were previously unbounded. Keep these in
# sync with the floor docling resolves to (see backend/pyproject.toml docling pin).
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install hatchling \
    && pip install --index-url https://download.pytorch.org/whl/cpu torch==2.12.0 torchvision==0.27.0 \
    && pip install ./backend

# Pre-download the FlashRank reranker model into the image so it isn't fetched
# on the first request at runtime (and re-fetched every time the container is
# recreated, since /tmp isn't persisted). cache_dir='/tmp' matches the runtime
# default used by indexer/reranker.py (FlashRankReranker -> Ranker(cache_dir='/tmp')).
# Keep the model name in sync with RERANK_MODEL / config.rerank_model.
RUN python -c "from flashrank import Ranker; Ranker(model_name='ms-marco-MultiBERT-L-12', cache_dir='/tmp')"

# Now copy the actual source — this is the layer that re-builds on code edits.
# The pip install above ran before this copy (for dep-layer caching), so it
# installed the dependencies but an empty accordance package. Put the source on
# PYTHONPATH so `accordance` imports from here — mirrors pyproject's pythonpath=["src"].
COPY backend/src ./backend/src
ENV PYTHONPATH=/app/backend/src
COPY kb ./kb

# Frontend dist comes from stage 1
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Persistent run-state lives here; compose bind-mounts the host equivalent
RUN mkdir -p /app/data/pdfs

# Run the workload as a non-root user (defense-in-depth: an RCE in a native
# parsing lib — libgl / onnxruntime / pymupdf on untrusted PDFs — must not land
# as root). The entrypoint starts as root ONLY to chown the bind-mounted data
# dir (its UID comes from the host), then drops to `app` via gosu.
ENV HOME=/home/app
RUN useradd --create-home --uid 10001 app && chown -R app:app /app /home/app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]

EXPOSE 8151

# Healthcheck mirrors what compose uses
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8151/api/health || exit 1

# Use exec form so SIGTERM reaches uvicorn (clean shutdown on `docker stop`).
# --proxy-headers makes uvicorn honor X-Forwarded-Proto/For from a front proxy
# so request.url.scheme is "https" behind TLS termination (the session cookie's
# Secure flag auto-enables) and the real client IP drives login throttling.
# --forwarded-allow-ips=* trusts those headers from any upstream: correct when
# the container is only reachable through your proxy. If you instead expose this
# port directly to the internet, drop --forwarded-allow-ips and rely on
# SESSION_COOKIE_SECURE=true so forwarded headers can't be spoofed.
CMD ["uvicorn", "accordance.main:app", "--host", "0.0.0.0", "--port", "8151", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
