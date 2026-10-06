from accordance.auth.passwords import hash_password

MIN_PASSWORD_LEN = 8


def add_user(
    conn,
    username: str,
    password: str,
    is_admin: bool = False,
) -> int:
    exists = conn.execute(
        "SELECT 1 FROM users WHERE username=%s", (username,)
    ).fetchone()
    if exists:
        raise ValueError(f"user already exists: {username}")
    row = conn.execute(
        "INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, %s) RETURNING id",
        (username, hash_password(password), is_admin),
    ).fetchone()
    return row["id"]


def set_active(conn, username: str, active: bool) -> bool:
    cur = conn.execute(
        "UPDATE users SET is_active=%s WHERE username=%s",
        (active, username),
    )
    return cur.rowcount > 0


def set_admin(conn, username: str, admin: bool) -> bool:
    cur = conn.execute(
        "UPDATE users SET is_admin=%s WHERE username=%s",
        (admin, username),
    )
    return cur.rowcount > 0


def set_password(conn, user_id: int, password: str) -> bool:
    cur = conn.execute(
        "UPDATE users SET password_hash=%s WHERE id=%s",
        (hash_password(password), user_id),
    )
    return cur.rowcount > 0


def list_users(conn) -> list[dict]:
    return [
        {
            "username": r["username"],
            "is_active": r["is_active"],
            "is_admin": r["is_admin"],
        }
        for r in conn.execute(
            "SELECT username, is_active, is_admin FROM users ORDER BY username"
        )
    ]


def bootstrap_admin(conn, settings) -> str | None:
    """Ensure the env-configured admin account exists and is an active admin.

    Returns a short action word for logging: 'created' (new account), 'promoted'
    (existing account made admin+active), 'skipped' (account missing and no/short
    password — cannot create), or None (no ADMIN_USERNAME set). Idempotent; safe
    to run on every boot. The password is (re)set only when admin_password is a
    valid (>= MIN_PASSWORD_LEN) string, so rotation works via env but clearing
    the var won't wipe an existing password.
    """
    username = (getattr(settings, "admin_username", "") or "").strip()
    if not username:
        return None
    password = getattr(settings, "admin_password", "") or ""
    has_pw = len(password) >= MIN_PASSWORD_LEN
    row = conn.execute(
        "SELECT id FROM users WHERE username=%s", (username,)
    ).fetchone()
    if row is None:
        if not has_pw:
            return "skipped"
        conn.execute(
            "INSERT INTO users (username, password_hash, is_active, is_admin) "
            "VALUES (%s, %s, TRUE, TRUE)",
            (username, hash_password(password)),
        )
        return "created"
    if has_pw:
        conn.execute(
            "UPDATE users SET password_hash=%s, is_admin=TRUE, is_active=TRUE WHERE id=%s",
            (hash_password(password), row["id"]),
        )
    else:
        conn.execute(
            "UPDATE users SET is_admin=TRUE, is_active=TRUE WHERE id=%s", (row["id"],)
        )
    return "promoted"
