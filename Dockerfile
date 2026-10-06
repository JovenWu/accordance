FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS runtime

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

COPY backend/pyproject.toml backend/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install hatchling \
    && pip install --index-url https://download.pytorch.org/whl/cpu torch==2.12.0 torchvision==0.27.0 \
    && pip install ./backend

RUN python -c "from flashrank import Ranker; Ranker(model_name='ms-marco-MultiBERT-L-12', cache_dir='/tmp')"

COPY backend/src ./backend/src
ENV PYTHONPATH=/app/backend/src
COPY kb ./kb

COPY --from=frontend-build /app/frontend/dist ./frontend/dist

RUN mkdir -p /app/data/pdfs

ENV HOME=/home/app
RUN useradd --create-home --uid 10001 app && chown -R app:app /app /home/app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]

EXPOSE 8151

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8151/api/health || exit 1

CMD ["uvicorn", "accordance.main:app", "--host", "0.0.0.0", "--port", "8151", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
