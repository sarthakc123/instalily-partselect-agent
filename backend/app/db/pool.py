"""Postgres connection pool (psycopg3, sync). One pool per process, lazy-initialized.

We use psycopg3 sync rather than asyncpg here for simplicity in v1: FastAPI can
call sync DB code in a threadpool, and our tools are LangGraph nodes that
benefit from straightforward synchronous queries. If we hit contention we can
switch to AsyncConnectionPool later without touching call sites.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _pool


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    pool = get_pool()
    with pool.connection() as conn:
        yield conn


def apply_schema() -> None:
    """Apply schema.sql idempotently. Safe to call on every startup."""
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
