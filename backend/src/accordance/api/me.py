"""Per-user lifetime usage stats for the app header."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from accordance.api.runs import _open_conn
from accordance.auth.deps import require_user
from accordance.config import Settings, get_settings
from accordance.models import MeStats

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("/stats", response_model=MeStats)
def my_stats(
    user: Annotated[dict, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Lifetime PDFs-processed count and $ spent for the logged-in user.

    Both come from append-only logs keyed by the denormalized user_id, so they
    are unaffected by report deletion. pdf_count = the user's completed runs;
    cost_usd = all the user's spend (incl. failed runs and deleted reports).
    """
    uid = user["id"]
    with _open_conn(settings) as conn:
        pdf_count = conn.execute(
            "SELECT COUNT(*) AS n FROM run_completions WHERE user_id=%s", (uid,)
        ).fetchone()["n"]
        cost = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS c FROM llm_usage WHERE user_id=%s",
            (uid,),
        ).fetchone()["c"]
    return MeStats(pdf_count=pdf_count, cost_usd=float(cost))
