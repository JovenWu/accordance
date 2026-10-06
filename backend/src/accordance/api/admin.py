"""Admin-only account management.

Create accounts, view each account's lifetime PDF count + cost, and
enable/disable accounts. Every route is gated by ``require_admin`` (wired in
main.py). Per-account stats reuse the append-only ``run_completions`` /
``llm_usage`` logs (same source as /api/me/stats), aggregated per user.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from accordance.api.runs import _open_conn
from accordance.auth.deps import require_admin
from accordance.auth.sessions import delete_user_sessions
from accordance.config import Settings, get_settings
from accordance.models import (
    AdminUserDetail,
    AdminUserRun,
    AdminUserView,
    CostByKind,
    DailyUsage,
)
from accordance.users import MIN_PASSWORD_LEN, add_user, set_password

router = APIRouter(prefix="/api/admin", tags=["admin"])

_USER_STATS_SELECT = """
SELECT u.id, u.username, u.is_admin, u.is_active, u.created_at,
       COALESCE(c.n, 0)      AS pdf_count,
       COALESCE(l.cost, 0.0) AS cost_usd
FROM users u
LEFT JOIN (
    SELECT user_id, COUNT(*) AS n FROM run_completions GROUP BY user_id
) c ON c.user_id = u.id
LEFT JOIN (
    SELECT user_id, SUM(cost_usd) AS cost FROM llm_usage GROUP BY user_id
) l ON l.user_id = u.id
"""
_LIST_SQL = _USER_STATS_SELECT + " ORDER BY u.username"
_ONE_SQL = _USER_STATS_SELECT + " WHERE u.id = %s"
_LAST_ACTIVE_SQL = "SELECT MAX(completed_at) AS last_active FROM runs WHERE created_by = %s"
_COST_BY_KIND_SQL = """
SELECT kind, COUNT(*) AS call_count, COALESCE(SUM(cost_usd), 0.0) AS cost_usd
FROM llm_usage WHERE user_id = %s GROUP BY kind ORDER BY cost_usd DESC
"""
_RECENT_RUNS_SQL = """
SELECT r.id, r.pdf_filename, r.uploaded_at, r.completed_at, r.status,
       COALESCE(SUM(l.cost_usd), 0.0) AS run_cost_usd
FROM runs r LEFT JOIN llm_usage l ON l.run_id = r.id
WHERE r.created_by = %s
GROUP BY r.id, r.pdf_filename, r.uploaded_at, r.completed_at, r.status
ORDER BY r.uploaded_at DESC LIMIT 10
"""

_DISPLAY_TZ = "Asia/Jakarta"

_DAILY_USAGE_LIMIT = 90

_DAILY_USAGE_SQL = """
WITH usage_days AS (
    SELECT (created_at AT TIME ZONE %(tz)s)::date AS day,
           SUM(input_tokens)  AS input_tokens,
           SUM(output_tokens) AS output_tokens,
           SUM(cost_usd)      AS cost_usd
    FROM llm_usage WHERE user_id = %(uid)s GROUP BY 1
),
run_days AS (
    SELECT (completed_at AT TIME ZONE %(tz)s)::date AS day, COUNT(*) AS pdf_count
    FROM run_completions WHERE user_id = %(uid)s GROUP BY 1
)
SELECT COALESCE(u.day, r.day)        AS day,
       COALESCE(r.pdf_count, 0)      AS pdf_count,
       COALESCE(u.input_tokens, 0)   AS input_tokens,
       COALESCE(u.output_tokens, 0)  AS output_tokens,
       COALESCE(u.cost_usd, 0.0)     AS cost_usd
FROM usage_days u FULL OUTER JOIN run_days r ON r.day = u.day
ORDER BY day DESC
LIMIT %(limit)s
"""


def _row_to_view(row) -> AdminUserView:
    return AdminUserView(
        id=row["id"],
        username=row["username"],
        is_admin=bool(row["is_admin"]),
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        pdf_count=row["pdf_count"],
        cost_usd=float(row["cost_usd"]),
    )


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str


class UpdateUserRequest(BaseModel):
    is_active: bool | None = None
    is_admin: bool | None = None


class ResetPasswordRequest(BaseModel):
    password: str


@router.get("/users", response_model=list[AdminUserView])
def list_users_admin(settings: Annotated[Settings, Depends(get_settings)]):
    with _open_conn(settings) as conn:
        return [_row_to_view(r) for r in conn.execute(_LIST_SQL)]


@router.get("/users/{user_id}", response_model=AdminUserDetail)
def get_user_admin(
    user_id: int,
    settings: Annotated[Settings, Depends(get_settings)],
):
    with _open_conn(settings) as conn:
        base = conn.execute(_ONE_SQL, (user_id,)).fetchone()
        if base is None:
            raise HTTPException(404, "No such user")
        last_active = conn.execute(_LAST_ACTIVE_SQL, (user_id,)).fetchone()["last_active"]
        cost_by_kind = [
            CostByKind(kind=r["kind"], call_count=r["call_count"], cost_usd=float(r["cost_usd"]))
            for r in conn.execute(_COST_BY_KIND_SQL, (user_id,))
        ]
        recent_runs = [
            AdminUserRun(
                id=r["id"],
                pdf_filename=r["pdf_filename"],
                uploaded_at=r["uploaded_at"],
                completed_at=r["completed_at"],
                status=r["status"],
                run_cost_usd=float(r["run_cost_usd"]),
            )
            for r in conn.execute(_RECENT_RUNS_SQL, (user_id,))
        ]
        daily_usage = [
            DailyUsage(
                day=r["day"],
                pdf_count=r["pdf_count"],
                input_tokens=r["input_tokens"],
                output_tokens=r["output_tokens"],
                cost_usd=float(r["cost_usd"]),
            )
            for r in conn.execute(
                _DAILY_USAGE_SQL,
                {"uid": user_id, "tz": _DISPLAY_TZ, "limit": _DAILY_USAGE_LIMIT},
            )
        ]
        return AdminUserDetail(
            **_row_to_view(base).model_dump(),
            last_active=last_active,
            cost_by_kind=cost_by_kind,
            recent_runs=recent_runs,
            daily_usage=daily_usage,
        )


@router.post("/users", response_model=AdminUserView, status_code=201)
def create_user_admin(
    body: CreateUserRequest,
    settings: Annotated[Settings, Depends(get_settings)],
):
    if len(body.password) < MIN_PASSWORD_LEN:
        raise HTTPException(
            400, f"Password must be at least {MIN_PASSWORD_LEN} characters"
        )
    with _open_conn(settings) as conn:
        try:
            uid = add_user(conn, body.username, body.password)
        except ValueError:
            raise HTTPException(409, "Username already exists") from None
        return _row_to_view(conn.execute(_ONE_SQL, (uid,)).fetchone())


@router.patch("/users/{user_id}", response_model=AdminUserView)
def update_user_admin(
    user_id: int,
    body: UpdateUserRequest,
    admin: Annotated[dict, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    if body.is_active is None and body.is_admin is None:
        raise HTTPException(400, "No fields to update")
    if user_id == admin["id"]:
        if body.is_active is False:
            raise HTTPException(400, "You cannot disable your own account")
        if body.is_admin is False:
            raise HTTPException(400, "You cannot remove your own admin access")
    with _open_conn(settings) as conn:
        if conn.execute("SELECT 1 FROM users WHERE id=%s", (user_id,)).fetchone() is None:
            raise HTTPException(404, "No such user")
        if body.is_active is not None:
            conn.execute(
                "UPDATE users SET is_active=%s WHERE id=%s", (body.is_active, user_id)
            )
        if body.is_admin is not None:
            conn.execute(
                "UPDATE users SET is_admin=%s WHERE id=%s", (body.is_admin, user_id)
            )
        return _row_to_view(conn.execute(_ONE_SQL, (user_id,)).fetchone())


@router.post("/users/{user_id}/reset-password", status_code=204)
def reset_password_admin(
    user_id: int,
    body: ResetPasswordRequest,
    settings: Annotated[Settings, Depends(get_settings)],
):
    if len(body.password) < MIN_PASSWORD_LEN:
        raise HTTPException(
            400, f"Password must be at least {MIN_PASSWORD_LEN} characters"
        )
    with _open_conn(settings) as conn:
        if not set_password(conn, user_id, body.password):
            raise HTTPException(404, "No such user")
        delete_user_sessions(conn, user_id)
    return Response(status_code=204)
