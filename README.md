# Accordance

Local-first tool for analyzing sustainability-report PDFs against the GRI Standards.

See `PRODUCT.md` for the product spec and `docs/` for design notes.

## Quickstart (Docker)

```bash
cp .env.example .env
# Edit .env: set LLM_BASE_URL, LLM_API_KEY, OPENAI_API_KEY (for embeddings)

docker compose up --build
```

Open <http://localhost:8000>. The same port serves both the API (`/api/*`) and the
React dashboard (`/`).

State persists across restarts via the `./data` bind-mount (uploaded PDFs) and the
`pgdata` Docker volume (Postgres database).

The stack requires `DATABASE_URL` pointing to the `db` compose service (set
automatically by the compose file). The `db` service must be healthy before the
`app` service starts (`depends_on: db: condition: service_healthy`).

## Local dev (without Docker)

Backend (Python 3.13):

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate           # Windows; or source .venv/bin/activate
pip install -e ".[dev]"
uvicorn accordance.main:app --reload --port 8000
```

Frontend (Node 22):

```bash
cd frontend
npm install
npm run dev                      # vite serves on :5173, proxies /api → :8000
```

Open <http://localhost:5173>.

## Eval harness

```bash
cp eval/ground_truth/_template.yaml eval/ground_truth/my-report.yaml
# Hand-label disclosures you're confident about.
python -m accordance.eval eval/ground_truth/my-report.yaml
```

Markdown report lands in `eval/reports/<timestamp>__<report_id>.md` with
confusion matrix, per-class P/R/F1, coverage gap, and the system-config
section (prompt hash, models, rejudge / hallucination / vision counts) so
deltas between runs can be attributed to specific code changes.

See `eval/README.md` for the labeling workflow.

## Tests

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q
```

## Authentication

The app requires login. After starting the service, bootstrap the first admin account:

```bash
docker compose exec app python -m accordance.users add <name>
```

This prompts for a password. Once created, log in via the web UI and use the account to analyze reports.

To manage users:

```bash
# List all accounts
docker compose exec app python -m accordance.users list

# Disable/enable an account
docker compose exec app python -m accordance.users disable <name>
docker compose exec app python -m accordance.users enable <name>
```

Session behavior is controlled by `SESSION_TTL_DAYS` (how long before login expires;
default 14 days) and `SESSION_COOKIE_SECURE` (enforce HTTPS-only cookies; defaults false,
auto-enabled under HTTPS). See `.env.example` for details.
