import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from accordance.api.events import bus
from accordance.api.ownership import assert_run_access
from accordance.api.runs import _open_conn
from accordance.auth.deps import require_user
from accordance.config import Settings, get_settings

router = APIRouter(prefix="/api/runs", tags=["stream"])


@router.get("/{run_id}/stream")
async def stream_run(
    run_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    with _open_conn(settings) as conn:
        assert_run_access(conn, run_id, user)
    q = bus.subscribe(run_id)

    async def gen():
        try:
            yield "event: open\ndata: {}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=30)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get("type") in ("completed", "cancelled", "failed"):
                    return
        finally:
            bus.unsubscribe(run_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream")
