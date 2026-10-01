# accordance — Production Deployment & Migration Guide

This guide walks a competent engineer (who has never deployed this app) through
running **accordance** in production on a **single Linux VPS using Docker Compose**.
It matches the repository's `docker-compose.yml` + `Dockerfile`.

Every command, environment variable name, and default below is taken from the
actual source — nothing is invented.

---

## 1. Overview & architecture

accordance runs as **one FastAPI container** that serves everything:

- **API** under `/api/*` (uploads, runs, reports, auth, export, KB, traces).
- **The built React SPA** under `/` — the same container hosts the static
  frontend bundle (`frontend/dist`) and falls through to `index.html` for
  client-side routing. (See `_find_frontend_dist` / the `spa` route in
  `backend/src/accordance/main.py`.)

**State lives in Postgres** (`pgvector/pgvector:pg16` image, run as the `db`
compose service). The `db` service stores every report, run, finding, trace, user,
and session. Uploaded PDFs are stored under `./data/pdfs/` (bind-mounted into the
`app` container at `/app/data/pdfs/`). Postgres uses **pgvector** (vector search)
and a generated `tsvector` column (PG-native BM25 / FTS) for hybrid retrieval.

**External calls:** the LLM "judge" and the embedding model are network calls to
external providers (OpenAI, an OpenAI-compatible proxy, or Voyage). The reranker
(FlashRank/ONNX) runs locally on CPU and needs no GPU.

> **Single-instance by design.** Run exactly **one** `app` container against a
> given `db` service. The compose file wires `depends_on: db: condition:
> service_healthy` so the app waits for Postgres to be ready before starting.

```
                 ┌───────────────────────────────────────────┐
   Browser  ───► │  Reverse proxy (nginx/Caddy, TLS)         │
                 └───────────────┬───────────────────────────┘
                                 │  127.0.0.1:8000
                 ┌───────────────▼───────────────────────────┐
                 │  Docker container  "app" (accordance)       │
                 │  uvicorn → FastAPI                         │
                 │    /api/*  → API routers                  │
                 │    /       → React SPA (frontend/dist)    │
                 │                                           │
                 │  local:  FlashRank reranker (CPU/ONNX)    │
                 └───────┬───────────────┬───────────────────┘
                         │               │ HTTPS out
                 ┌───────▼─────────┐    ┌▼──────────────────────┐
                 │ db (Postgres)   │    │ LLM judge + embeddings │
                 │  pgvector:pg16  │    │ (OpenAI / proxy /      │
                 │  pgdata volume  │    │  Voyage)               │
                 └─────────────────┘    └────────────────────────┘
                 ┌─────────────────┐
                 │ ./data bind     │
                 │  pdfs/          │
                 └─────────────────┘
```

---

## 2. Prerequisites

- A **Linux host** (any modern distro). Recommended sizing: **≥ 2 vCPU** and
  **≥ 4–8 GB RAM**. The compose file sets `mem_limit: 4g` for the container, so
  the host needs at least that much free, plus headroom for the OS.
- **Docker Engine** + **Docker Compose v2** (the `docker compose` subcommand, not
  the legacy `docker-compose` binary).
- **Outbound HTTPS** from the host to your LLM and embedding providers
  (api.openai.com, your OpenAI-compatible proxy, or Voyage). No inbound ports are
  required for the providers.
- **Disk** for `./data` (uploaded PDFs) and for the `pgdata` Docker volume
  (Postgres data). Budget generously; sustainability reports can be tens of MB each.
- A **domain name** (optional but recommended) if you want TLS via a reverse
  proxy.

---

## 3. Get the code

Clone the repository onto the server:

```bash
git clone <your-repo-url> accordance
cd accordance
```

All subsequent commands are run from the repository root (the directory that
contains `docker-compose.yml`).

---

## 4. Configure `.env`

Copy the template and edit it. `.env` is **gitignored** (see `.dockerignore` /
`.gitignore`) — keep it off version control.

```bash
cp .env.example .env
nano .env   # or your editor of choice
```

Compose loads `.env` via `env_file:` and passes it into the container. The full
list of settings (with defaults) lives in `backend/src/accordance/config.py`.

### 4.1 Required for a real (non-`fake:`) deployment

> **Startup fails fast on missing keys.** The app's lifespan calls
> `check_required_keys` (`config.py`). If a required provider key is missing for a
> real model, the container **refuses to start** and logs:
> `accordance cannot start — missing required configuration: ...`. This is by
> design — better to fail at boot than to fail every run deep in the worker.

| Variable | What it does | Production value |
|---|---|---|
| `DATABASE_URL` | Postgres connection string. **Set automatically** by the compose file (`postgresql://gri:<POSTGRES_PASSWORD>@db:5432/gri`). Override only if pointing at an external Postgres. | set by compose |
| `POSTGRES_PASSWORD` | Password for the `gri` Postgres user. Defaults to `gri` (change this in production). Used by both the `db` and `app` services. | strong secret |
| `LLM_MODEL` | The judge model, in `provider:model` form (default `openai:gpt-5-mini`). | e.g. `openai:gpt-5-mini`, or `openai:cx/gpt-5.4-mini` behind a proxy. |
| `LLM_API_KEY` | API key for the judge LLM. **Required** unless `LLM_MODEL` starts with `fake:`. | your key |
| `LLM_BASE_URL` | Leave **blank** for OpenAI's real endpoint. Set **only** to route through an OpenAI-compatible proxy (must end in `/v1` if the proxy follows that convention). | blank, or `https://proxy.example.com/v1` |
| `EMBEDDING_MODEL` | Embedding model, `provider:model` form (default `openai:text-embedding-3-small`). | `openai:text-embedding-3-small` |
| `OPENAI_API_KEY` | **Required** when `EMBEDDING_MODEL` starts with `openai:`. | your key |
| `VOYAGE_API_KEY` | **Required** only when `EMBEDDING_MODEL` starts with `voyage:`. | your key (if using Voyage) |

The check logic, verbatim from `check_required_keys`:

- `LLM_MODEL` not `fake:*` **and** `LLM_API_KEY` empty → fail.
- `EMBEDDING_MODEL` starts with `openai:` **and** `OPENAI_API_KEY` empty → fail.
- `EMBEDDING_MODEL` starts with `voyage:` **and** `VOYAGE_API_KEY` empty → fail.

> **`DATA_DIR` is forced by compose.** Whatever you set for `DATA_DIR` in `.env`
> is overridden — the compose `environment:` block hardcodes `DATA_DIR=/app/data`
> and bind-mounts the host's `./data` there. Don't bother changing `DATA_DIR`;
> change the host path on the left of the `./data:/app/data` volume instead if you
> need the data elsewhere on the host.

### 4.2 Notable settings (and their defaults)

These have working defaults but you will likely want to review them for
production.

| Variable | Default | Notes |
|---|---|---|
| `LLM_TIMEOUT` | `60` | Per-request judge timeout (seconds). |
| `LLM_MAX_RETRIES` | `2` | SDK-level retries for 429/5xx. |
| `EMBEDDING_TIMEOUT` | `60` | Per-request embedding timeout (seconds). |
| `EMBEDDING_MAX_RETRIES` | `2` | SDK retries for the embedding API. |
| `MODEL_PRICES_JSON` | `""` | Cost-tracking price override — **see the gotcha below**. |
| `SESSION_TTL_DAYS` | `14` | How many days a login session lasts. |
| `SESSION_COOKIE_SECURE` | `false` | **Set `true` for any HTTPS deployment.** Also auto-enables when the app sees an HTTPS request — which now works behind a TLS proxy because the image runs uvicorn with `--proxy-headers` (it honors `X-Forwarded-Proto`). Set it explicitly anyway. See §8. |
| `LOGIN_MAX_ATTEMPTS` | `10` | Failed logins allowed **per client IP and per username** before further attempts get `429`, within `LOGIN_WINDOW_SECONDS`. A successful login resets the counter. `0` disables (not advised). |
| `LOGIN_WINDOW_SECONDS` | `300` | Rolling window (seconds) for `LOGIN_MAX_ATTEMPTS`. |
| `ADMIN_USERNAME` | _(empty)_ | Username of the admin account auto-provisioned at startup. Empty = no auto-admin. |
| `ADMIN_PASSWORD` | _(empty)_ | Password for the bootstrap admin (>= 8 chars). Applied on creation; re-asserted each boot when set. Readable in the container env — use a strong secret. |
| `MAX_UPLOAD_MB` | `100` | Max accepted PDF upload size; the upload handler aborts an over-limit read with `413`. |
| `MAX_REQUEST_MB` | `0` | Hard ceiling on the whole HTTP request body, enforced at the ASGI layer from `Content-Length` (`413` **before** the body is spooled to disk). `0` ⇒ `MAX_UPLOAD_MB + 8` (≈108 MB by default). Keep the proxy's `client_max_body_size` ≥ this. |
| `JUDGE_CONCURRENCY` | `3` | Max concurrent judge LLM calls. Lower to `2`–`3` if you hit 429s. |
| `MAX_CONCURRENT_RUNS` | `4` | Admission control — max run-worker threads running at once. Excess runs queue safely on a semaphore. |
| `MAX_INFLIGHT_RUNS_PER_USER` | `5` | Max runs one user may have in-flight (queued/extracting/indexing/judging) at once; further run-creating requests get `429`. Caps runaway worker-thread spawn and paid-LLM spend from a looping account. `0` disables. |
| `SHUTDOWN_DRAIN_SECONDS` | `25` | Graceful-shutdown drain budget (seconds). **Keep below** compose `stop_grace_period: 30s`. See §11. |
| `DOCLING_TIMEOUT_SECONDS` | `0` | Wall-clock budget for one Docling extraction pass; `0` = off (no limit). Only relevant with the docling backend. |
| `EXTRACTOR_BACKEND` | `pymupdf` | `pymupdf` (default, fast, embedded-text only) or `docling` (ML pipeline: OCR/tables, much higher memory). |
| `ASSESSOR_NAME` | `assessor` | Name recorded on assessor corrections (single-reviewer phase). |

Retrieval / quality knobs (defaults are tuned — change only if you know why):

| Variable | Default | Notes |
|---|---|---|
| `RETRIEVAL_MODE` | `hybrid` | `hybrid` (dense + BM25 via RRF), `dense`, or `bm25`. |
| `RETRIEVAL_PER_ELEMENT` | `true` | Expand retrieval with element descriptions (+30–50% tokens). |
| `RETRIEVAL_TAG_AWARE` | `false` | Only enable **together with** `DOCLING_DO_TABLE_STRUCTURE=true`. |
| `RETRIEVAL_TAG_LIMIT` | `5` | Cap on tag-forced chunks. |
| `RERANK_ENABLED` | `false` | FlashRank reranker. Off by default (no measured accuracy gain; saves CPU). The model is still baked into the image. |
| `RERANK_MODEL` | `ms-marco-MultiBERT-L-12` | Keep in sync with the image's pre-downloaded model. |
| `RERANK_TOP_N` | `15` | Rerank pool size. |
| `JUDGE_REJUDGE_ON_MISSING` | `true` | Re-judge `missing` verdicts with extra queries (+1 LLM call each). |
| `PROMPT_CACHE_ENABLED` | `false` | Anthropic prompt-cache breakpoint; only helps if your proxy forwards it. |

Vision fallback (re-judge table/chart pages with a vision-capable LLM):

| Variable | Default | Notes |
|---|---|---|
| `VISION_FALLBACK_ENABLED` | `true` | Master switch for the vision re-judge pass. |
| `VISION_FALLBACK_ON_LOW_CONFIDENCE` | `true` | Escalate **any** `partial`/`missing` verdict to vision (recovers numbers locked in table-images). `false` = only escalate when the LLM self-flags (cheaper). |
| `VISION_FALLBACK_BUDGET` | `40` | Per-run cap on vision re-judge calls (each renders up to 3 page images). |

Docling memory knobs (only used when `EXTRACTOR_BACKEND=docling`):

| Variable | Default (`.env.example`) | Notes |
|---|---|---|
| `DOCLING_BATCH_SIZE` | `50` | Re-instantiate Docling every N pages to dodge `std::bad_alloc` on long PDFs; `0` disables batching. |
| `DOCLING_DO_OCR` | `false` | `true` only for scanned PDFs. |
| `DOCLING_DO_TABLE_STRUCTURE` | `false` | `true` for cell-accurate tables (slower, more memory). |
| `DOCLING_NUM_THREADS` | `1` | Native thread cap. |
| `DOCLING_IMAGES_SCALE` | `1.0` | Render scale for page bitmaps. |
| `DOCLING_LAYOUT_BATCH_SIZE` / `DOCLING_OCR_BATCH_SIZE` / `DOCLING_TABLE_BATCH_SIZE` | `1` | Per-stage batch sizes (memory). |

### 4.3 Postgres operator notes

**`DB_HOST_PORT`** — the host port the compose `db` service publishes (default
`5432`; override in `.env` when `5432` is already taken on the host machine).
Host-run tools (pytest, `psql`, `pg_dump`) then connect via
`postgresql://gri:<password>@localhost:<DB_HOST_PORT>/gri`. The container always
listens on its internal port 5432 regardless of this setting.

**Managed Postgres prerequisite** — `CREATE EXTENSION IF NOT EXISTS vector` in
`ensure_schema` requires the connecting DB role to have permission to create
extensions. For the self-hosted compose `gri` superuser this is always true. On
**managed Postgres** (AWS RDS, GCP Cloud SQL, Supabase, Azure Database for
PostgreSQL) the app role typically lacks `CREATE EXTENSION`; the `vector`
extension must be **pre-created by an admin** before starting the app:
```sql
CREATE EXTENSION vector;
```
Without it, every `ensure_schema` call will fail at the `CREATE EXTENSION` line.

**HNSW dimension ceiling** — pgvector's HNSW index supports vectors up to
**2000 dimensions**. The default embedding model (`text-embedding-3-small`,
1536 dims) is well within this limit. If you switch to a higher-dim model
(e.g. `text-embedding-3-large` at 3072 dims), the `CREATE INDEX … USING hnsw`
call in `ensure_embedding_dim` will fail. In that case reduce dimensions via the
model's `dimensions` parameter (OpenAI supports this) or switch to an IVFFlat
index and update `ensure_embedding_dim` accordingly.

### 4.4 Cost-tracking gotcha (read this)

> **The `$ spent` dashboard prices usage by the model name the provider RETURNS
> in its response metadata — not the `LLM_MODEL` string you configured.**
>
> So the **`MODEL_PRICES_JSON` key must equal the returned model name**. Example:
> with `LLM_MODEL=openai:cx/gpt-5.4-mini`, the proxy typically returns
> `gpt-5.4-mini` in the response, so the price key must be **`gpt-5.4-mini`**
> (not `cx/gpt-5.4-mini`, not `openai:cx/gpt-5.4-mini`).
>
> If the returned model is **unpriced**, the app **logs a warning at startup**
> (`LLM model ... has no matching price entry — $ cost will record 0`) and records
> **$0** for that usage. **Verify the dashboard shows a non-zero cost after your
> first real run.**

`MODEL_PRICES_JSON` is **USD per 1,000,000 tokens**, shape:

```json
{"<model-name-the-provider-returns>": {"in": <num>, "out": <num>}}
```

Example `.env` line (single-line JSON; prices are illustrative — verify against
your provider's real rates):

```dotenv
MODEL_PRICES_JSON={"gpt-5.4-mini": {"in": 0.25, "out": 2.0}, "text-embedding-3-small": {"in": 0.02, "out": 0.0}}
```

Notes from `pricing.py`:

- The table merges your override over built-in `DEFAULT_PRICES`
  (`gpt-5-mini` and `text-embedding-3-small` are priced out of the box).
- A malformed entry (missing `in` or `out`, or a non-numeric value) is **warned
  about and skipped** — the rest still apply. Each entry needs both
  `"in"` and `"out"` as numbers.
- Matching is prefix/path-aware: a key of `gpt-5-mini` matches a dated id like
  `gpt-5-mini-2025-08-07`, and a key of `gpt-5.4-mini` matches `cx/gpt-5.4-mini`.

---

## 5. Build & launch

```bash
docker compose build
docker compose up -d
```

Compose starts the `db` service first (Postgres) and waits for its healthcheck
(`pg_isready`) before starting `app`. On the first boot Postgres initialises the
`gri` database; the app's lifespan then calls `ensure_schema` to create all tables
and indexes.

What the build does (multi-stage `Dockerfile`):

1. **Stage 1 (`frontend-build`, node:22-alpine):** `npm ci` then `npm run build`
   → Vite emits the SPA into `/app/frontend/dist`.
2. **Stage 2 (`runtime`, python:3.13-slim):** installs CPU-only PyTorch
   (`torch==2.12.0`, `torchvision==0.27.0` from the PyTorch CPU index) **before**
   the backend so docling's transitive torch resolves to the CPU build — this
   avoids dragging in ~4.3 GB of unused CUDA wheels. Then `pip install ./backend`,
   pre-downloads the **FlashRank reranker model** (`ms-marco-MultiBERT-L-12`) into
   the image, copies the source + `kb/`, and copies the frontend `dist` from
   stage 1.

> **The first build is slow.** It downloads CPU torch and the reranker model.
> Subsequent builds reuse cached layers; source-only edits rebuild only the final
> copy layers.

The container runs
`uvicorn accordance.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips *`.
It listens on **8000 inside the container**, published to host **8000** by default.

> **What `--proxy-headers` buys you.** It makes uvicorn honor `X-Forwarded-Proto`
> / `X-Forwarded-For` from a front proxy, so behind TLS the session cookie's
> `Secure` flag auto-enables and the **real client IP** drives login throttling.
> `--forwarded-allow-ips *` trusts those headers from **any** upstream — correct
> when the container is only reachable **through your proxy**. **If you instead
> expose the app port directly to the internet, drop `--forwarded-allow-ips *`**
> (a client could otherwise spoof `X-Forwarded-Proto`/`X-Forwarded-For`) and rely
> on `SESSION_COOKIE_SECURE=true`. See §8 and §13.

> **Port note.** The committed `docker-compose.override.yml` publishes on host
> **8001** instead (a machine-specific workaround where another service holds
> 8000). Compose auto-merges `docker-compose.override.yml` if present. On a clean
> production host you usually want the base mapping (`8000:8000`) — delete or
> don't copy the override file, or set the host port you actually want. The
> container always listens on 8000 internally, so the healthcheck is unaffected.

---

## 6. Bootstrap the first user (MANDATORY)

A fresh database has **no users**, and **every** API router except auth is gated
behind login (`require_user` in `main.py`). Until you create a user, **nobody can
log in** and the app is unusable.

Create the first account (you'll be prompted for a password):

```bash
docker compose exec app python -m accordance.users add <username>
```

The user CLI (`backend/src/accordance/users/__main__.py`) supports exactly these
subcommands:

```bash
# Create a user (prompts for password via getpass)
docker compose exec app python -m accordance.users add <username>

# List accounts — prints "(active)"/"(disabled)" + username
docker compose exec app python -m accordance.users list

# Disable / enable an account
docker compose exec app python -m accordance.users disable <username>
docker compose exec app python -m accordance.users enable <username>
```

Notes:

- `add` fails if the username already exists.
- There is **no `set-password` / `activate` subcommand** — the only state changes
  are `add`, `disable`, `enable`. (To rotate a password, you'd disable/recreate or
  edit the DB directly — out of scope here.)
- The CLI connects to the same Postgres instance via `DATABASE_URL`, so run it via
  `docker compose exec app` against the running stack.

### First admin account

Set `ADMIN_USERNAME` and `ADMIN_PASSWORD` in `.env` before the first boot. On
startup the app creates that account as an **active admin** (or promotes an
existing same-named account). Log in as that user; the header shows an **Admin**
link to `/admin`, where you can:

- **create accounts** (username + password, min 8 chars),
- **enable/disable accounts**,
- **view each account's lifetime PDFs processed and $ spent**.

Notes:
- The bootstrap is declarative: while `ADMIN_PASSWORD` is set, a restart
  re-enables the admin and resets its password to the env value. To stop
  re-asserting the password, blank `ADMIN_PASSWORD` after first boot (the account
  and password persist).
- You can also manage admins from the CLI without redeploying:
  `docker compose exec app python -m accordance.users promote <name>` (and
  `demote`, or `add <name> --admin`).
- Admin endpoints are gated to admins, but this release does **not** add per-user
  data isolation: a non-admin who knows another user's report/run ID can still
  reach it via the API. Treat all accounts as trusted colleagues.

---

## 7. Verify

```bash
# Container is up and healthy
docker compose ps

# Deep healthcheck — returns {"status":"ok"} (200) when DATA_DIR is writable
# AND the DB answers SELECT 1; otherwise 503 with a detail string.
curl -fsS http://localhost:8000/api/health      # use 8001 if you kept the override

# Follow logs (watch for the startup warnings / errors)
docker compose logs -f app
```

The healthcheck (`_check_health` in `main.py`) probes two things:
1. `DATA_DIR` is writable (writes and deletes a `.health_probe` file).
2. The Postgres connection pool answers `SELECT 1`.

A failure returns `503` with `{"status":"unhealthy","detail":"..."}` — e.g.
`data dir not writable: ...` or `database unavailable: ...`.

Then open the app in a browser (`http://<host>:8000`, or your proxied HTTPS URL)
and log in with the account from §6.

---

## 8. Reverse proxy + TLS

Run the app behind a TLS-terminating reverse proxy. Bind the **proxy** to the
public interface and keep the app on `127.0.0.1:8000`.

> Set **`SESSION_COOKIE_SECURE=true`** in `.env` once you're behind HTTPS, and
> forward **`X-Forwarded-Proto`** so the app sees the original scheme. The image
> already runs uvicorn with `--proxy-headers`, so a forwarded `X-Forwarded-Proto:
> https` makes the secure-cookie logic engage automatically — but set the env var
> too, so the cookie is never issued without `Secure` even if the header is lost.

### nginx

```nginx
server {
    listen 443 ssl http2;
    server_name accordance.example.com;

    ssl_certificate     /etc/letsencrypt/live/accordance.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/accordance.example.com/privkey.pem;

    # Allow large PDF uploads. Match or exceed MAX_REQUEST_MB — the app's own
    # body cap (default MAX_UPLOAD_MB + 8 ≈ 108 MB) — so the proxy never rejects
    # something the app would have accepted (and vice-versa).
    client_max_body_size 120m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;   # required for secure cookies
    }

    # Run progress is Server-Sent Events — disable buffering and allow long reads.
    location ~ ^/api/runs/.+/stream$ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;            # critical: stream events as they arrive
        proxy_cache off;
        proxy_read_timeout 1h;          # long-lived connection
        proxy_set_header Connection '';
        proxy_http_version 1.1;
    }
}

# Redirect HTTP → HTTPS
server {
    listen 80;
    server_name accordance.example.com;
    return 301 https://$host$request_uri;
}
```

> **SSE matters.** The `/api/runs/{id}/stream` endpoint is a
> `StreamingResponse` with `media_type="text/event-stream"`
> (`backend/src/accordance/api/stream.py`). If the proxy buffers it, the live run
> progress UI will appear frozen. `proxy_buffering off;` + a long
> `proxy_read_timeout` fix this.

### Caddy (simplest — auto-TLS)

```caddyfile
accordance.example.com {
    reverse_proxy 127.0.0.1:8000
    request_body {
        max_size 120MB
    }
}
```

Caddy sets `X-Forwarded-Proto` automatically and does not buffer SSE by default,
so no special block is needed for the stream endpoint. Still set
`SESSION_COOKIE_SECURE=true`.

---

## 9. Data persistence & backups

Durable state is split across two locations:

- **`pgdata` Docker volume** — the Postgres database (reports, runs, findings,
  traces, users, sessions). Managed by Docker; lives at the default Docker volume
  path on the host.
- **`./data/pdfs/`** — the uploaded source PDFs (bind-mounted into the `app`
  container at `/app/data/pdfs/`).

### Safe online backup (Postgres)

Use `pg_dump` to take a consistent snapshot while the stack is running:

```bash
# Dump the database to a SQL file on the host
docker compose exec db pg_dump -U gri gri > /backups/gri-$(date +%F).sql

# Back up the PDFs too — they are referenced by the DB:
tar czf /backups/pdfs-$(date +%F).tgz -C ./data pdfs
```

### Restore procedure

```bash
# 1. Stop the app (keep db running so we can restore into it).
docker compose stop app

# 2. Drop and recreate the database, then restore.
docker compose exec db psql -U gri -c "DROP DATABASE IF EXISTS gri;"
docker compose exec db psql -U gri -c "CREATE DATABASE gri;"
docker compose exec -T db psql -U gri gri < /backups/gri-2026-06-25.sql

# 3. Restore PDFs if needed.
tar xzf /backups/pdfs-2026-06-25.tgz -C ./data

# 4. Start the app. ensure_schema runs on boot and is idempotent.
docker compose start app

# 5. Verify.
curl -fsS http://localhost:8000/api/health
docker compose logs -f app
```

---

## 10. Upgrades / schema migrations

Standard upgrade flow:

```bash
# 0. TAKE A BACKUP FIRST (see §9). Strongly recommended before any upgrade.
docker compose exec db pg_dump -U gri gri > /backups/pre-upgrade-$(date +%F).sql

# 1. Pull new code
git pull

# 2. Rebuild and restart
docker compose build
docker compose up -d
```

**The schema auto-migrates on startup.** On first connection, `ensure_schema`
(`backend/src/accordance/db.py`) runs `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX
IF NOT EXISTS` DDL so all tables and indexes are present. The function is
**idempotent** — safe to call repeatedly. There is no automated downgrade, which is
exactly why you take a backup before upgrading.

> **Interrupted runs are auto-reconciled.** When the old container stops, any run
> left in a non-terminal status (`queued`/`extracting`/`indexing`/`judging`) is
> marked `failed` on the next boot by `reconcile_orphaned_runs`, with the error
> "Interrupted by a server restart. Click Retry to re-run." Just click **Retry**
> in the UI for those.

---

## 11. Zero-ish-downtime deploys / graceful shutdown

On `docker compose up -d` (recreate), `docker stop`, or a host shutdown, the
container receives **SIGTERM**. Because the `Dockerfile` uses the exec-form `CMD`,
SIGTERM reaches uvicorn cleanly, which triggers the lifespan shutdown
(`main.py`):

- It **cancels and joins in-progress run workers**, waiting up to
  **`SHUTDOWN_DRAIN_SECONDS`** (default `25`) so a run isn't killed mid-write
  (`drain_active_runs`).
- Compose grants **`stop_grace_period: 30s`** before SIGKILL — deliberately
  larger than the drain budget, so the drain has room to finish.

> **Keep `SHUTDOWN_DRAIN_SECONDS` < `stop_grace_period` (30s).** If you raise the
> drain budget, raise `stop_grace_period` in `docker-compose.yml` to match, or
> Docker will SIGKILL mid-drain.

Any run that is still cut off (drain timed out, or a hard crash) is reconciled to
`failed` on the next restart (§10) and can be retried from the UI. This is "near
zero-downtime" for a single instance: there is a brief gap while the container
recreates, and the user simply retries any interrupted run.

---

## 12. Resource tuning

- **`mem_limit: 4g`** (compose) caps container memory. This is generous for the
  default `pymupdf` extractor. **Raise it** if you switch to
  `EXTRACTOR_BACKEND=docling` on **200+ page PDFs** — docling can hit
  `std::bad_alloc` / OOM there. (The docling batch knobs in §4.2 exist to fight
  this; the `mem_limit` is the OOM backstop.)
- **`MAX_CONCURRENT_RUNS`** (default `4`) should be sized against CPU and memory.
  Each running run uses the shared Postgres connection pool. Excess runs queue
  safely on a semaphore before acquiring connections.
- **`MAX_INFLIGHT_RUNS_PER_USER`** (default `5`) is a per-account abuse/fairness
  cap distinct from the global `MAX_CONCURRENT_RUNS`: it stops one user from
  queueing an unbounded backlog of runs (`429` over the limit). Raise it for power
  users; lower it to tighten cost control.
- **`JUDGE_CONCURRENCY`** (default `3`) controls parallel judge LLM calls within a
  run. Raising it speeds runs **only** against a provider that allows it — a
  throttling/concurrency-capping proxy will negate the gain (and may trigger
  429s, in which case lower it).
- **Reranker CPU:** `RERANK_ENABLED` is `false` by default (no measured accuracy
  win), which keeps the onnxruntime CPU load off constrained servers. Leave it off
  unless you're explicitly evaluating it.

---

## 13. Security checklist

- [ ] **Rotate any leaked API keys.** If a key was ever committed or shared,
      revoke and reissue it. Put keys only in `.env`.
- [ ] **Keep `.env` out of version control.** It is already gitignored (and
      `.dockerignore`d). Never bake secrets into the image.
- [ ] **Run behind TLS** with **`SESSION_COOKIE_SECURE=true`** and
      `X-Forwarded-Proto` forwarded (§8).
- [ ] **The container already runs as non-root** (`uid 10001` "app"). The
      entrypoint starts as root only to chown the bind-mounted data dir, then
      drops privileges via `gosu` — defense-in-depth against an RCE in a native
      PDF-parsing lib. Don't override this to run as root.
- [ ] **Restrict who can reach port 8000.** Bind the **reverse proxy** to the
      public interface and keep the app on `127.0.0.1` (or firewall port 8000 so
      only the proxy/localhost can reach it). Don't expose the raw app port to the
      internet.
- [ ] **Cap request size.** `MAX_UPLOAD_MB` (default 100) bounds the PDF; the app
      also enforces `MAX_REQUEST_MB` (default ≈108 MB) at the ASGI layer, returning
      `413` **before** the body is spooled to disk. Set a matching
      `client_max_body_size` in the proxy.
- [ ] **Login brute-force throttling is on** — per client IP **and** per username:
      after `LOGIN_MAX_ATTEMPTS` (default 10) failures within `LOGIN_WINDOW_SECONDS`
      (default 300), further attempts get `429` until the window clears (a success
      resets it). State is in-process (fine for the single instance). Caveat: with
      the app exposed directly (no proxy), the per-IP limit can be dodged via a
      spoofed `X-Forwarded-For` — only keep `--forwarded-allow-ips *` behind a
      trusted proxy; the per-username limit still bounds per-account guessing.
- [ ] **Per-user run quota** caps in-flight runs at `MAX_INFLIGHT_RUNS_PER_USER`
      (default 5), returning `429` over the limit — bounds runaway worker-thread
      spawn and paid-LLM spend from a looping or compromised account.
- [ ] Set a strong `ADMIN_PASSWORD` (>= 8 chars); rotate by changing it and restarting. Remember it is readable in the container environment.
- [ ] **Still missing: CSRF token and per-user data isolation.** Cookie auth
      relies on `SameSite=Lax` (no CSRF token), and **any authenticated user can
      read/modify/delete every other user's reports and runs** — there is no
      per-user authorization yet. Keep the app among trusted assessors / behind
      SSO, and do **not** treat separate accounts as a data boundary. Sessions are
      DB-backed with a `SESSION_TTL_DAYS` expiry.

---

## 14. Troubleshooting

| Symptom | Likely cause & fix |
|---|---|
| Container exits at startup with **"accordance cannot start — missing required configuration"** | A required provider key is empty for a real model. Set `LLM_API_KEY` (and `OPENAI_API_KEY` or `VOYAGE_API_KEY` for the embedding provider) in `.env`, then `docker compose up -d`. (`check_required_keys`.) |
| `/api/health` returns **503** | `DATA_DIR` not writable, or the DB can't be opened. Check the `detail` field. Usually a `./data` permission problem (the entrypoint chowns it to uid 10001 — make sure the host dir is writable) or a locked/corrupt DB. |
| **`$ spent` shows 0** after a real run | `MODEL_PRICES_JSON` key doesn't match the model name the provider **returns** (not your `LLM_MODEL` string). See §4.4. Check the startup log for the "no matching price entry" warning and fix the key. |
| Postgres **connection errors** under load | Too many concurrent runs/judge calls exhausting the pool. Lower `MAX_CONCURRENT_RUNS` and/or `JUDGE_CONCURRENCY`, or increase the pool size. |
| Upload rejected with a **400** ("Uploaded file is not a valid PDF") | The file doesn't start with the `%PDF-` header (encrypted, corrupt, or not a PDF). This is intentional fail-fast behavior — re-export/repair the PDF. A wrong content type also returns 400. |
| Upload/request rejected with **413** | Body over the size cap: `MAX_UPLOAD_MB` (PDF, default 100) or the ASGI body cap `MAX_REQUEST_MB` (whole request, default ≈108 MB, enforced before spooling). Raise the relevant limit **and** the proxy's `client_max_body_size` if the file is legitimately large. |
| Login rejected with **429** ("Too many login attempts") | Login throttle tripped — too many failed logins from this IP/username. Wait out `LOGIN_WINDOW_SECONDS` (default 300s) or raise `LOGIN_MAX_ATTEMPTS`; a successful login clears it. |
| Any run-creating request — upload, retry, fork, judge-more, or new version — rejected with **429** ("You already have N run(s) in progress") | Per-user in-flight run quota (`MAX_INFLIGHT_RUNS_PER_USER`, default 5). Wait for a run to finish, or raise the limit. |
| Live run progress UI looks **frozen** | The SSE stream is being buffered by the proxy. Add `proxy_buffering off;` and a long `proxy_read_timeout` for `/api/runs/.../stream` (§8). |
| First `docker compose build` is **very slow** | Expected — it downloads CPU torch and the FlashRank reranker model. Later builds are cached. |
| Runs stuck "spinning" after a restart | They're auto-reconciled to `failed` on boot — refresh and click **Retry** (§10/§11). |

---

## Appendix — quick command reference

```bash
# Build & start
docker compose build
docker compose up -d

# First user (MANDATORY on a fresh DB)
docker compose exec app python -m accordance.users add <username>
docker compose exec app python -m accordance.users list

# Health & logs
curl -fsS http://localhost:8000/api/health
docker compose ps
docker compose logs -f app

# Backup (online, safe — Postgres pg_dump)
docker compose exec db pg_dump -U gri gri > /backups/gri-$(date +%F).sql
tar czf /backups/pdfs-$(date +%F).tgz -C ./data pdfs

# Upgrade
git pull && docker compose build && docker compose up -d

# Graceful stop (drains in-progress runs up to SHUTDOWN_DRAIN_SECONDS)
docker compose stop
```
