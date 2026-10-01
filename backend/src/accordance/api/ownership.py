from fastapi import HTTPException


def visible_reports_clause(user: dict) -> tuple[str, list]:
    """SQL fragment (and params) restricting reports to the caller, unless admin.
    Intended to be appended to a WHERE that already has a condition."""
    if user.get("is_admin"):
        return "", []
    return "AND reports.created_by = %s", [user["id"]]


def assert_report_access(conn, report_id: str, user: dict) -> None:
    row = conn.execute(
        "SELECT created_by FROM reports WHERE id=%s AND deleted_at IS NULL",
        (report_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Report not found")
    if not user.get("is_admin") and row["created_by"] != user["id"]:
        raise HTTPException(404, "Report not found")  # hide existence


def assert_run_access(conn, run_id: str, user: dict) -> str:
    row = conn.execute(
        "SELECT r.report_id, rep.created_by "
        "FROM runs r JOIN reports rep ON rep.id = r.report_id "
        "WHERE r.id=%s AND rep.deleted_at IS NULL",
        (run_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Run not found")
    if not user.get("is_admin") and row["created_by"] != user["id"]:
        raise HTTPException(404, "Run not found")
    return row["report_id"]
