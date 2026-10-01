from typing import Annotated

from fastapi import Depends, HTTPException, Request

from accordance.auth.sessions import user_for_token
from accordance.config import Settings, get_settings

COOKIE_NAME = "gri_session"


def require_user(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Not authenticated")
    # Lazy import: api.runs imports require_user (Task 8), so a top-level import
    # here would be circular.
    from accordance.api.runs import _open_conn

    with _open_conn(settings) as conn:
        user = user_for_token(conn, token)
    if user is None:
        raise HTTPException(401, "Not authenticated")
    return user


def require_admin(
    user: Annotated[dict, Depends(require_user)],
) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(403, "Admin only")
    return user
