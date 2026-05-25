"""Liveness + readiness checks. Reports DB connectivity and KG stats."""

from __future__ import annotations

from fastapi import APIRouter

from app.agents.graph import get_kg
from app.db.pool import connection

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    db_ok = False
    parts_count = 0
    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM parts")
            parts_count = cur.fetchone()["n"]
        db_ok = True
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "db_ok": False, "error": str(exc)}

    kg_stats = get_kg().stats()
    return {
        "status": "ok",
        "db_ok": db_ok,
        "parts_in_db": parts_count,
        "kg": kg_stats,
    }
