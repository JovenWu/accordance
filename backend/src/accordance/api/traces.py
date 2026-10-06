"""GET /api/runs/{run_id}/traces — per-disclosure judge observability.

Exposes the rows persisted to ``judge_traces`` by graph.nodes._persist_traces
so the frontend can show "what did the judge actually see for this
disclosure". Critical for diagnosing wrong verdicts: most errors turn out
to be retrieval miss (the right chunk never made it to the judge) rather
than judgment errors, and you can only tell which from the trace.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from accordance.api.ownership import assert_run_access
from accordance.api.runs import _open_conn
from accordance.auth.deps import require_user
from accordance.config import Settings, get_settings

router = APIRouter(prefix="/api/runs", tags=["traces"])


class TraceAttempt(BaseModel):
    attempt: int
    rejudged: bool
    parse_path: str
    error: str | None
    latency_ms: int | None
    prompt_hash: str
    model: str
    queries: list[str]
    chunk_ids: list[int]
    distances: list[float]
    pages: list[int]
    evidence_verified: bool | None
    created_at: str


class DisclosureTrace(BaseModel):
    disclosure_id: str
    attempts: list[TraceAttempt]


class TracesResponse(BaseModel):
    run_id: str
    traces: list[DisclosureTrace]


def _parse_json_array(value: str | None) -> list:
    if not value:
        return []
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return []


@router.get("/{run_id}/traces", response_model=TracesResponse)
def get_traces(
    run_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    with _open_conn(settings) as conn:
        assert_run_access(conn, run_id, user)

        rows = conn.execute(
            """
            SELECT disclosure_id, attempt, rejudged, parse_path, error,
                   latency_ms, prompt_hash, model, queries_json,
                   chunk_ids_json, distances_json, pages_json,
                   evidence_verified, created_at
            FROM judge_traces
            WHERE run_id=%s
            ORDER BY disclosure_id, attempt
            """,
            (run_id,),
        ).fetchall()

        grouped: dict[str, list[TraceAttempt]] = {}
        for r in rows:
            ev = r["evidence_verified"]
            attempt = TraceAttempt(
                attempt=r["attempt"],
                rejudged=bool(r["rejudged"]),
                parse_path=r["parse_path"],
                error=r["error"],
                latency_ms=r["latency_ms"],
                prompt_hash=r["prompt_hash"],
                model=r["model"],
                queries=_parse_json_array(r["queries_json"]),
                chunk_ids=_parse_json_array(r["chunk_ids_json"]),
                distances=_parse_json_array(r["distances_json"]),
                pages=_parse_json_array(r["pages_json"]),
                evidence_verified=None if ev is None else bool(ev),
                created_at=str(r["created_at"]),
            )
            grouped.setdefault(r["disclosure_id"], []).append(attempt)

        traces = [
            DisclosureTrace(disclosure_id=did, attempts=attempts)
            for did, attempts in sorted(grouped.items())
        ]
        return TracesResponse(run_id=run_id, traces=traces)
