import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from accordance.api import admin as admin_router
from accordance.api import auth as auth_router
from accordance.api import export as export_router
from accordance.api import kb as kb_router
from accordance.api import me as me_router
from accordance.api import reports as reports_router
from accordance.api import runs as runs_router
from accordance.api import stream as stream_router
from accordance.api import traces as traces_router
from accordance.api import versioning as versioning_router
from accordance.auth.deps import require_admin, require_user


def _configure_logging() -> None:
    """Attach a stdout handler to the accordance logger if not already configured.

    Idempotent — safe to call in tests (where create_app() may be called
    multiple times). Does NOT call logging.basicConfig so uvicorn's own root
    logger setup is unaffected. propagate=False prevents double-emit when
    uvicorn attaches its own root handler.
    """
    app_logger = logging.getLogger("accordance")
    if app_logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    app_logger.setLevel(logging.INFO)
    app_logger.addHandler(handler)
    app_logger.propagate = False


def _find_frontend_dist() -> Path | None:
    """Locate the built frontend SPA, if present.

    Candidates cover the common deployment CWD layouts, in order:
      1. CWD/frontend/dist         — repo-root CWD (and the container, CWD=/app).
      2. CWD/../frontend/dist      — backend-dir CWD.
      3. <repo-root>/frontend/dist — relative to this source file.

    Returns None when no candidate has an index.html — keeps dev mode
    (where vite serves the SPA separately on :5173) working as before.
    """
    here = Path(__file__).resolve()
    candidates = [
        Path.cwd() / "frontend" / "dist",
        Path.cwd().parent / "frontend" / "dist",
        here.parents[3] / "frontend" / "dist",
    ]
    for p in candidates:
        if (p / "index.html").is_file():
            return p
    return None


def _warn_if_unpriced_model(settings, logger) -> bool:
    """Warn (and return True) when the configured LLM model resolves to no price
    entry — otherwise the $-spent dashboard silently records 0. Best-effort: the
    real cost key is the provider-returned model_name, but the configured id is a
    good proxy and catches the common "forgot to price it at all" case.
    """
    from accordance.pricing import load_prices, model_is_priced

    model = (getattr(settings, "llm_model", "") or "").strip()
    if not model:
        return False
    if model_is_priced(model, load_prices(settings)):
        return False
    logger.warning(
        "LLM model %r has no matching price entry — $ cost will record 0. "
        "Add it to MODEL_PRICES_JSON (key must match the model name the "
        "provider returns).",
        model,
    )
    return True


def _warn_if_embeddings_bypass_proxy(settings, logger) -> bool:
    """Warn (and return True) when LLM_BASE_URL is set but embeddings still go
    direct to the provider.

    LLM_BASE_URL routes the JUDGE only — embeddings have their own
    EMBEDDING_BASE_URL, and while it is unset retrieval's query embeddings call
    the provider directly with their own credentials. Reading "base URL" as
    "all model traffic" is the natural assumption and it's wrong. When the
    embedding key is exhausted, EVERY disclosure fails during retrieval while
    the proxied judge is perfectly healthy — so the failure looks like a judge
    outage and points debugging at the wrong service.
    """
    base_url = (getattr(settings, "llm_base_url", "") or "").strip()
    em = (getattr(settings, "embedding_model", "") or "").strip()
    emb_base = (getattr(settings, "embedding_base_url", "") or "").strip()
    if not base_url or emb_base or em.startswith("fake:"):
        return False
    key_name = "VOYAGE_API_KEY" if em.startswith("voyage:") else "OPENAI_API_KEY"
    logger.warning(
        "LLM_BASE_URL=%r routes the judge only — EMBEDDING_MODEL=%r still calls "
        "its provider directly using %s. If that key is missing or out of "
        "credits, every disclosure fails at RETRIEVAL even though the judge is "
        "reachable.",
        base_url,
        em,
        key_name,
    )
    return True


def _warn_if_embedding_key_leaks_to_gateway(settings, logger) -> bool:
    """Warn (and return True) when EMBEDDING_BASE_URL is set with no key of its own.

    embedding_credentials() falls back to the provider key, so pointing
    EMBEDDING_BASE_URL at a third-party gateway without EMBEDDING_API_KEY sends
    OPENAI_API_KEY / VOYAGE_API_KEY to that third party. The fallback is
    deliberate — it keeps a same-provider base URL working — so this can't be a
    hard failure, but it must not be silent either.
    """
    emb_base = (getattr(settings, "embedding_base_url", "") or "").strip()
    if not emb_base or (getattr(settings, "embedding_api_key", "") or "").strip():
        return False
    em = (getattr(settings, "embedding_model", "") or "").strip()
    key_name = "VOYAGE_API_KEY" if em.startswith("voyage:") else "OPENAI_API_KEY"
    logger.warning(
        "EMBEDDING_BASE_URL=%r is set but EMBEDDING_API_KEY is empty, so %s is "
        "being sent to that endpoint. If it is not your model provider, set "
        "EMBEDDING_API_KEY to a key scoped to it.",
        emb_base,
        key_name,
    )
    return True


_FLEX_MIN_TIMEOUT_S = 600.0


def _warn_if_flex_timeout_too_short(settings, logger) -> bool:
    """Warn (and return True) when flex is requested with a short timeout.

    Flex is explicitly slower — the provider's own SDK default is 10 minutes.
    Against llm_timeout's 60s default, calls would time out constantly and read
    as "flex doesn't work" rather than "the timeout is wrong for this tier".
    """
    if (getattr(settings, "llm_service_tier", "") or "").strip() != "flex":
        return False
    timeout = float(getattr(settings, "llm_timeout", 0) or 0)
    if timeout >= _FLEX_MIN_TIMEOUT_S:
        return False
    logger.warning(
        "LLM_SERVICE_TIER=flex with LLM_TIMEOUT=%.0fs — flex is slower by "
        "design and calls will likely time out. Raise LLM_TIMEOUT to at least "
        "%.0fs.",
        timeout,
        _FLEX_MIN_TIMEOUT_S,
    )
    return True


def _check_health(settings) -> tuple[bool, str]:
    """Liveness+readiness probe: DATA_DIR writable and the DB answers SELECT 1.

    Returns (ok, detail). Never raises — turns any failure into (False, reason)
    so the endpoint can map it to 503 instead of a 500 stack trace.
    """
    from accordance.api.runs import _open_conn

    try:
        data_dir = Path(settings.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".health_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception as e:
        return False, f"data dir not writable: {e}"
    try:
        with _open_conn(settings) as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception as e:
        return False, f"database unavailable: {e}"
    return True, "ok"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup checks. Runs under uvicorn (and `with TestClient(app)`), not on a
    bare import — so it fails fast on real misconfiguration without breaking
    plain `TestClient(create_app())` usage in tests.
    """
    from accordance.api.runs import _open_conn
    from accordance.config import check_required_keys, get_settings
    from accordance.db import (
        close_pool,
        ensure_embedding_dim,
        ensure_schema,
        init_pool,
        reconcile_orphaned_runs,
    )
    from accordance.indexer.embedder import embedding_dim

    logger = logging.getLogger("accordance")
    settings = get_settings()

    problems = check_required_keys(settings)
    if problems:
        raise RuntimeError(
            "accordance cannot start — missing required configuration:\n  - "
            + "\n  - ".join(problems)
            + "\nSet the keys in .env (see .env.example) and restart."
        )

    _warn_if_unpriced_model(settings, logger)
    _warn_if_embeddings_bypass_proxy(settings, logger)
    _warn_if_embedding_key_leaks_to_gateway(settings, logger)
    _warn_if_flex_timeout_too_short(settings, logger)

    init_pool(settings)
    with _open_conn(settings) as conn:
        ensure_schema(conn)
        ensure_embedding_dim(conn, dim=embedding_dim(settings.embedding_model))

    try:
        with _open_conn(settings) as conn:
            n = reconcile_orphaned_runs(conn)
            if n:
                logger.warning(
                    "Reconciled %d run(s) left non-terminal by a previous "
                    "restart -> failed (click Retry to re-run).",
                    n,
                )
            from accordance.users import bootstrap_admin

            action = bootstrap_admin(conn, settings)
            if action == "created":
                logger.info(
                    "Bootstrapped admin account %r from ADMIN_USERNAME.",
                    settings.admin_username,
                )
            elif action == "promoted":
                logger.info(
                    "Ensured %r is an active admin (ADMIN_USERNAME).",
                    settings.admin_username,
                )
            elif action == "skipped":
                logger.warning(
                    "ADMIN_USERNAME=%r is set but the account does not exist and "
                    "ADMIN_PASSWORD is missing or shorter than 8 chars — admin "
                    "NOT created.",
                    settings.admin_username,
                )
    except Exception:
        logger.exception("startup reconciliation / admin bootstrap failed")

    yield

    try:
        from accordance.api.runs import drain_active_runs

        drained = drain_active_runs(timeout=settings.shutdown_drain_seconds)
        if drained:
            logger.warning("shutdown: drained %d in-progress run(s)", drained)
    except Exception:
        logger.exception("shutdown run-drain failed")
    try:
        close_pool()
    except Exception:
        logger.exception("pool close failed")


def create_app() -> FastAPI:
    from accordance.api.limits import MaxBodySizeMiddleware
    from accordance.config import get_settings

    _configure_logging()
    app = FastAPI(title="accordance", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(MaxBodySizeMiddleware, max_bytes=get_settings().max_request_bytes)

    @app.get("/api/health")
    def health():
        from accordance.config import get_settings

        ok, detail = _check_health(get_settings())
        if ok:
            return {"status": "ok"}
        return JSONResponse(status_code=503, content={"status": "unhealthy", "detail": detail})

    _auth = [Depends(require_user)]
    app.include_router(auth_router.router)
    app.include_router(me_router.router, dependencies=_auth)
    app.include_router(runs_router.router, dependencies=_auth)
    app.include_router(reports_router.router, dependencies=_auth)
    app.include_router(stream_router.router, dependencies=_auth)
    app.include_router(export_router.router, dependencies=_auth)
    app.include_router(export_router.reports_router, dependencies=_auth)
    app.include_router(traces_router.router, dependencies=_auth)
    app.include_router(versioning_router.router, dependencies=_auth)
    app.include_router(kb_router.router, dependencies=_auth)
    app.include_router(admin_router.router, dependencies=[Depends(require_admin)])

    dist = _find_frontend_dist()
    if dist is not None:
        app.state.frontend_dist = dist

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404)

            candidate = (dist / full_path).resolve()
            try:
                candidate.relative_to(dist.resolve())
            except ValueError:
                raise HTTPException(status_code=404) from None
            if candidate.is_file():
                return FileResponse(candidate)

            return FileResponse(dist / "index.html")

    return app


app = create_app()
