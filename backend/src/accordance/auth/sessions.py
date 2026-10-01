import hashlib
import secrets
import time


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_session(conn, user_id: int, ttl_days: int) -> str:
    raw = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + ttl_days * 86400
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
        (_hash_token(raw), user_id, expires_at),
    )
    return raw


def user_for_token(conn, raw_token: str) -> dict | None:
    th = _hash_token(raw_token)
    row = conn.execute(
        "SELECT u.id, u.username, u.is_admin, s.expires_at "
        "FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = %s AND u.is_active = TRUE",
        (th,),
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] < int(time.time()):
        conn.execute("DELETE FROM sessions WHERE token_hash = %s", (th,))
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "is_admin": bool(row["is_admin"]),
    }


def delete_session(conn, raw_token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = %s", (_hash_token(raw_token),))


def delete_user_sessions(conn, user_id: int) -> int:
    cur = conn.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
    return cur.rowcount


def purge_expired(conn) -> int:
    cur = conn.execute("DELETE FROM sessions WHERE expires_at < %s", (int(time.time()),))
    return cur.rowcount
