"""Versioning operations: chunk-copy, fork, retry-as-new-version.

Fork and Retry share one backend path: create a new ``runs`` row whose
chunks/vectors/FTS rows are copied from the parent, then kick the judge
graph. The only difference is the ``kind`` label.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from accordance.api.cancellation import registry as cancel_registry
from accordance.api.ownership import assert_report_access, assert_run_access
from accordance.api.runs import (
    _enforce_run_quota,
    _kick_off_graph,
    _open_conn,
    _read_upload_capped,
    _require_pdf_magic,
)
from accordance.auth.deps import require_user
from accordance.config import Settings, get_settings

router = APIRouter(tags=["versioning"])


def _copy_chunks_to_new_run(
    conn,
    *,
    source_run_id: str,
    target_run_id: str,
) -> None:
    """Mirror chunks (including embeddings) from source to target run.

    In Postgres, each chunk carries its embedding directly in the
    ``chunks.embedding`` column and full-text search is a generated
    ``text_tsv`` tsvector column — no separate ``chunk_vectors`` or
    ``chunks_fts`` tables to maintain. One transaction for the whole batch
    keeps atomicity; Postgres MVCC means concurrent readers are never blocked.
    """
    src_chunks = conn.execute(
        "SELECT id, page, text, embedding FROM chunks WHERE run_id=%s ORDER BY id",
        (source_run_id,),
    ).fetchall()
    with conn.transaction():
        for c in src_chunks:
            conn.execute(
                "INSERT INTO chunks (run_id, page, text, embedding) VALUES (%s, %s, %s, %s)",
                (target_run_id, c["page"], c["text"], c["embedding"]),
            )


def _create_versioned_run(
    settings: Settings,
    *,
    source_run_id: str,
    kind: str,  # 'retry' | 'fork'
    disclosure_ids_override: list[str] | None = None,
    acting_user_id=None,
) -> tuple[str, int]:
    """Create a new versioned run from a source run; copy chunks; kick judge."""
    if kind not in ("retry", "fork"):
        raise ValueError(f"Unsupported kind for _create_versioned_run: {kind}")

    with _open_conn(settings) as conn:
        src = conn.execute(
            """
            SELECT id, report_id, pdf_filename, pdf_sha256, pdf_path, status,
                   selected_disclosures, created_by
            FROM runs WHERE id=%s
            """,
            (source_run_id,),
        ).fetchone()
        if not src:
            raise HTTPException(404, "Source run not found")
        if src["status"] not in {"completed", "failed", "cancelled"}:
            raise HTTPException(
                409,
                f"Cannot {kind} a run in status '{src['status']}'; wait for it to finish.",
            )
        _enforce_run_quota(conn, acting_user_id, settings)

        next_ver = conn.execute(
            "SELECT COALESCE(MAX(version_number),0)+1 AS v FROM runs WHERE report_id=%s",
            (src["report_id"],),
        ).fetchone()["v"]

        # An explicit override (Retry-with-selection) wins; otherwise the new
        # version inherits the source run's selection (NULL = all).
        if disclosure_ids_override is not None:
            selected = disclosure_ids_override
            selected_json = json.dumps(disclosure_ids_override)
        else:
            selected_json = src["selected_disclosures"]
            selected = json.loads(selected_json) if selected_json is not None else None

        new_run_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO runs (
                id, report_id, parent_run_id, version_number, kind,
                reused_from_run_id, pdf_filename, pdf_sha256, pdf_path, status,
                selected_disclosures, created_by
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                new_run_id,
                src["report_id"],
                src["id"],
                next_ver,
                kind,
                src["id"],
                src["pdf_filename"],
                src["pdf_sha256"],
                src["pdf_path"],
                "queued",
                selected_json,
                src["created_by"],
            ),
        )

        source_id = src["id"]
        pdf_path = Path(src["pdf_path"])

    # Copy the parent's chunks/vectors/FTS in the background (it can be
    # thousands of rows) so the response — and the client's reroute to the
    # new run — returns the moment the run row exists, not after the copy.
    cancel_registry.clear(new_run_id)
    _kick_off_graph(
        new_run_id,
        pdf_path,
        settings,
        reuse_index=True,
        disclosure_ids=selected,
        prepare=lambda conn: _copy_chunks_to_new_run(
            conn, source_run_id=source_id, target_run_id=new_run_id
        ),
    )
    return new_run_id, next_ver


@router.post("/api/runs/{run_id}/fork", status_code=201, tags=["versioning"])
def fork_run(
    run_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    with _open_conn(settings) as conn:
        assert_run_access(conn, run_id, user)
    new_id, ver = _create_versioned_run(
        settings,
        source_run_id=run_id,
        kind="fork",
        acting_user_id=user["id"],
    )
    return {"run_id": new_id, "version_number": ver}


@router.post("/api/reports/{report_id}/versions", status_code=201, tags=["versioning"])
async def update_report_with_new_pdf(
    report_id: str,
    pdf: Annotated[UploadFile, File()],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    """Upload a new PDF as the next version of an existing report.

    Used when the source document has been updated (typo fix, new section,
    next year's report) and you want a fresh analysis grouped under the
    same Report as the prior versions.
    """
    if pdf.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(400, f"Unsupported content type: {pdf.content_type}")
    body = await _read_upload_capped(pdf, settings.max_upload_mb * 1024 * 1024)
    filename = pdf.filename or "upload.pdf"
    # Offload the blocking sha256 + connect + file-write + INSERT so the event
    # loop (and every concurrent SSE stream) stays responsive — see create_run.
    result = await run_in_threadpool(
        _persist_new_version, body, report_id, filename, settings, user
    )

    _kick_off_graph(result["run_id"], result["pdf_path"], settings)
    return {"run_id": result["run_id"], "version_number": result["version_number"]}


def _persist_new_version(
    body: bytes,
    report_id: str,
    filename: str,
    settings: Settings,
    user: dict,
) -> dict:
    """Blocking section of update_report_with_new_pdf (hash, dedup, write, insert)
    — run off the event loop via ``run_in_threadpool``. Raises HTTPException for
    the 404/409 cases (FastAPI still maps them to responses). Returns
    ``{"run_id", "version_number", "pdf_path"}``."""
    _require_pdf_magic(body)
    sha = hashlib.sha256(body).hexdigest()

    with _open_conn(settings) as conn:
        assert_report_access(conn, report_id, user)
        rep = conn.execute(
            "SELECT id FROM reports WHERE id=%s AND deleted_at IS NULL",
            (report_id,),
        ).fetchone()
        if not rep:
            raise HTTPException(404, "Report not found")

        dup = conn.execute(
            "SELECT version_number FROM runs WHERE report_id=%s AND pdf_sha256=%s",
            (report_id, sha),
        ).fetchone()
        if dup:
            raise HTTPException(
                409,
                f"This PDF is identical to v{dup['version_number']} in this "
                "report; use Retry instead.",
            )

        _enforce_run_quota(conn, user["id"], settings)

        next_ver = conn.execute(
            "SELECT COALESCE(MAX(version_number),0)+1 AS v FROM runs WHERE report_id=%s",
            (report_id,),
        ).fetchone()["v"]

        parent_row = conn.execute(
            "SELECT id, created_by FROM runs WHERE report_id=%s "
            "ORDER BY version_number DESC LIMIT 1",
            (report_id,),
        ).fetchone()
        parent_id = parent_row["id"] if parent_row else None
        parent_owner = parent_row["created_by"] if parent_row else None

        new_run_id = str(uuid.uuid4())
        settings.pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = settings.pdf_dir / f"{new_run_id}.pdf"
        pdf_path.write_bytes(body)

        conn.execute(
            """
            INSERT INTO runs (
                id, report_id, parent_run_id, version_number, kind,
                reused_from_run_id, pdf_filename, pdf_sha256, pdf_path, status,
                created_by
            ) VALUES (%s,%s,%s,%s,'update',NULL,%s,%s,%s,'queued',%s)
            """,
            (
                new_run_id,
                report_id,
                parent_id,
                next_ver,
                filename,
                sha,
                str(pdf_path),
                parent_owner,
            ),
        )

    return {"run_id": new_run_id, "version_number": next_ver, "pdf_path": pdf_path}
