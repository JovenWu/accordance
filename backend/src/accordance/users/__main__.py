import getpass
import sys

from accordance.config import get_settings
from accordance.db import connect_direct, ensure_schema
from accordance.users import add_user, list_users, set_active, set_admin


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(
            "usage: python -m accordance.users "
            "[add|disable|enable|promote|demote|list] <username> [--admin]"
        )
        return 2
    cmd, *rest = argv
    want_admin = "--admin" in rest
    rest = [a for a in rest if a != "--admin"]
    settings = get_settings()
    conn = connect_direct(settings)
    ensure_schema(conn)
    try:
        if cmd == "list":
            for u in list_users(conn):
                if u["is_admin"]:
                    marker = "(admin)"
                elif u["is_active"]:
                    marker = "(active)"
                else:
                    marker = "(disabled)"
                print(f"{marker:10} {u['username']}")
            return 0
        if not rest:
            print(f"{cmd} requires a username")
            return 2
        username = rest[0]
        if cmd == "add":
            pw = getpass.getpass(f"password for {username}: ")
            add_user(conn, username, pw, is_admin=want_admin)
            print(f"created user {username}" + (" (admin)" if want_admin else ""))
        elif cmd == "disable":
            print("disabled" if set_active(conn, username, False) else "no such user")
        elif cmd == "enable":
            print("enabled" if set_active(conn, username, True) else "no such user")
        elif cmd == "promote":
            print("promoted" if set_admin(conn, username, True) else "no such user")
        elif cmd == "demote":
            print("demoted" if set_admin(conn, username, False) else "no such user")
        else:
            print(f"unknown command: {cmd}")
            return 2
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
