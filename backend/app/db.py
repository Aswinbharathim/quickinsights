"""Real MariaDB/MySQL access for whichever DatabaseConnection the caller passes in."""
import time

import pymysql

from app.models import DatabaseConnection


def get_raw_connection(conn: DatabaseConnection):
    return pymysql.connect(
        host=conn.host,
        port=conn.port,
        user=conn.username,
        password=conn.password or "",
        database=conn.database_name,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.Cursor,
        connect_timeout=8,
    )


def ping(conn: DatabaseConnection) -> None:
    """Raises if the connection cannot be established."""
    raw = get_raw_connection(conn)
    try:
        with raw.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    finally:
        raw.close()


def run_select(conn: DatabaseConnection, sql: str, max_rows: int):
    """Execute a validated SELECT. Caller must run the guardrail first."""
    raw = get_raw_connection(conn)
    try:
        start = time.perf_counter()
        with raw.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchmany(max_rows)
            columns = [d[0] for d in cur.description] if cur.description else []
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        dict_rows = [dict(zip(columns, row)) for row in rows]
        return columns, dict_rows, elapsed_ms
    finally:
        raw.close()
