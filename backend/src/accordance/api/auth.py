from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from accordance.api.limits import client_ip, login_limiter
from accordance.api.runs import _open_conn
from accordance.auth.deps import COOKIE_NAME, require_user
from accordance.auth.passwords import verify_password
from accordance.auth.sessions import create_session, delete_session
from accordance.config import Settings, get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
):
    limit = settings.login_max_attempts
    window = settings.login_window_seconds
    ip_key = f"ip:{client_ip(request)}"
    user_key = f"user:{body.username}"
    if limit > 0 and (
        login_limiter.is_blocked(ip_key, limit=limit, window=window)
        or login_limiter.is_blocked(user_key, limit=limit, window=window)
    ):
        raise HTTPException(429, "Too many login attempts; try again later.")

    with _open_conn(settings) as conn:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE username=%s AND is_active=TRUE",
            (body.username,),
        ).fetchone()
        if row is None or not verify_password(body.password, row["password_hash"]):
            if limit > 0:
                login_limiter.record_failure(ip_key, window=window)
                login_limiter.record_failure(user_key, window=window)
            raise HTTPException(401, "Invalid username or password")
        token = create_session(conn, row["id"], settings.session_ttl_days)

    login_limiter.reset(ip_key)
    login_limiter.reset(user_key)
    secure = settings.session_cookie_secure or request.url.scheme == "https"
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
        max_age=settings.session_ttl_days * 86400,
    )
    return {"username": body.username}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with _open_conn(settings) as conn:
            delete_session(conn, token)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: Annotated[dict, Depends(require_user)]):
    return {"username": user["username"], "is_admin": bool(user.get("is_admin"))}
