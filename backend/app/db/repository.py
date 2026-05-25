"""Raw-SQL repository for the structured DB.

One function per query. Each returns dataclasses defined in `schemas.entities`
or plain dicts. We deliberately do not abstract behind a generic ORM: the
queries are few, the joins are well-known, and inspecting the SQL is the
fastest way to debug retrieval behavior.

Connections are taken from the shared pool via app.db.pool.connection().
"""

from __future__ import annotations

from typing import Any

from app.db.pool import connection
from app.schemas.entities import (
    Compatibility,
    InstallGuide,
    Model,
    Part,
    RepairStory,
    Symptom,
    SymptomFix,
)


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------

def get_part(part_id: str) -> Part | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM parts WHERE id = %s", (part_id,))
        row = cur.fetchone()
    return Part(**row) if row else None


def fuzzy_search_parts(query: str, limit: int = 5, min_similarity: float = 0.3) -> list[Part]:
    """Fuzzy SKU match via pg_trgm. Hard rule: never silent-swap; caller
    must require user confirmation before treating a fuzzy hit as canonical."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT *, similarity(id, %s) AS sim
            FROM parts
            WHERE similarity(id, %s) > %s
            ORDER BY sim DESC
            LIMIT %s
            """,
            (query, query, min_similarity, limit),
        )
        rows = cur.fetchall()
    return [Part(**{k: v for k, v in row.items() if k != "sim"}) for row in rows]


def insert_part(part: Part) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO parts (id, name, manufacturer, appliance_type, part_type,
                               price_cents, in_stock, image_url, description)
            VALUES (%(id)s, %(name)s, %(manufacturer)s, %(appliance_type)s, %(part_type)s,
                    %(price_cents)s, %(in_stock)s, %(image_url)s, %(description)s)
            ON CONFLICT (id) DO NOTHING
            """,
            part.model_dump(),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def get_model(model_id: str) -> Model | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM models WHERE id = %s", (model_id,))
        row = cur.fetchone()
    return Model(**row) if row else None


def fuzzy_search_models(query: str, limit: int = 5, min_similarity: float = 0.3) -> list[Model]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT *, similarity(id, %s) AS sim
            FROM models
            WHERE similarity(id, %s) > %s
            ORDER BY sim DESC
            LIMIT %s
            """,
            (query, query, min_similarity, limit),
        )
        rows = cur.fetchall()
    return [Model(**{k: v for k, v in row.items() if k != "sim"}) for row in rows]


def insert_model(model: Model) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO models (id, brand, appliance_type, year, series, manual_url)
            VALUES (%(id)s, %(brand)s, %(appliance_type)s, %(year)s, %(series)s, %(manual_url)s)
            ON CONFLICT (id) DO NOTHING
            """,
            model.model_dump(),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Compatibility (the workhorse edge)
# ---------------------------------------------------------------------------

def check_compat_edge(part_id: str, model_id: str) -> Compatibility | None:
    """Return the structured edge if it exists. This is the source of truth
    for check_compatibility yes/no. Inferred fallback goes through
    install_guides.series_fitment_hint, not this function."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT part_id, model_id, sub_assembly_only, requires_adapter, supersedes
            FROM compatibility
            WHERE part_id = %s AND model_id = %s
            """,
            (part_id, model_id),
        )
        row = cur.fetchone()
    return Compatibility(**row) if row else None


def list_compat_models_for_part(part_id: str) -> list[Compatibility]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT part_id, model_id, sub_assembly_only, requires_adapter, supersedes "
            "FROM compatibility WHERE part_id = %s",
            (part_id,),
        )
        rows = cur.fetchall()
    return [Compatibility(**row) for row in rows]


def insert_compat(compat: Compatibility) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO compatibility (part_id, model_id, sub_assembly_only, requires_adapter, supersedes)
            VALUES (%(part_id)s, %(model_id)s, %(sub_assembly_only)s, %(requires_adapter)s, %(supersedes)s)
            ON CONFLICT (part_id, model_id) DO NOTHING
            """,
            compat.model_dump(),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Install guides
# ---------------------------------------------------------------------------

def get_install_guide_by_part(part_id: str) -> InstallGuide | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM install_guides WHERE part_id = %s", (part_id,))
        row = cur.fetchone()
    return InstallGuide(**row) if row else None


def insert_install_guide(guide: InstallGuide) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO install_guides (id, part_id, difficulty, estimated_minutes,
                                        tools_required, safety_warnings, steps, video_url,
                                        series_fitment_hint)
            VALUES (%(id)s, %(part_id)s, %(difficulty)s, %(estimated_minutes)s,
                    %(tools_required)s, %(safety_warnings)s, %(steps)s, %(video_url)s,
                    %(series_fitment_hint)s)
            ON CONFLICT (id) DO NOTHING
            """,
            guide.model_dump(),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Symptoms + fixes
# ---------------------------------------------------------------------------

def get_symptom(symptom_id: str) -> Symptom | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM symptoms WHERE id = %s", (symptom_id,))
        row = cur.fetchone()
    return Symptom(**row) if row else None


def insert_symptom(symptom: Symptom) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO symptoms (id, description, canonical_label, appliance_type)
            VALUES (%(id)s, %(description)s, %(canonical_label)s, %(appliance_type)s)
            ON CONFLICT (id) DO NOTHING
            """,
            symptom.model_dump(),
        )
        conn.commit()


def insert_symptom_fix(fix: SymptomFix) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO symptom_fixes (symptom_id, part_id, likelihood, common_cause_rank)
            VALUES (%(symptom_id)s, %(part_id)s, %(likelihood)s, %(common_cause_rank)s)
            ON CONFLICT (symptom_id, part_id) DO NOTHING
            """,
            fix.model_dump(),
        )
        conn.commit()


def parts_fixing_symptom(symptom_id: str, model_id: str | None = None) -> list[dict[str, Any]]:
    """KG traversal as SQL: (symptom) -[FIXES]-> (part) -[FITS]-> (model if known).
    Returns parts ranked by common_cause_rank then likelihood DESC, with
    compatibility flag joined in when model_id is provided."""
    with connection() as conn, conn.cursor() as cur:
        if model_id is None:
            cur.execute(
                """
                SELECT p.id          AS part_id,
                       p.name        AS part_name,
                       p.price_cents,
                       p.in_stock,
                       sf.likelihood,
                       sf.common_cause_rank,
                       NULL::boolean AS fits_model
                FROM symptom_fixes sf
                JOIN parts p ON p.id = sf.part_id
                WHERE sf.symptom_id = %s
                ORDER BY sf.common_cause_rank ASC, sf.likelihood DESC
                """,
                (symptom_id,),
            )
        else:
            cur.execute(
                """
                SELECT p.id          AS part_id,
                       p.name        AS part_name,
                       p.price_cents,
                       p.in_stock,
                       sf.likelihood,
                       sf.common_cause_rank,
                       (c.part_id IS NOT NULL) AS fits_model
                FROM symptom_fixes sf
                JOIN parts p ON p.id = sf.part_id
                LEFT JOIN compatibility c
                       ON c.part_id = p.id AND c.model_id = %s
                WHERE sf.symptom_id = %s
                ORDER BY (c.part_id IS NOT NULL) DESC NULLS LAST,
                         sf.common_cause_rank ASC,
                         sf.likelihood DESC
                """,
                (model_id, symptom_id),
            )
        return list(cur.fetchall())


# ---------------------------------------------------------------------------
# Repair stories (for troubleshoot retrieval; v1 simple SQL, v2 hybrid + KG)
# ---------------------------------------------------------------------------

def insert_repair_story(story: RepairStory) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO repair_stories (id, appliance_type, brand, symptom_id, title, body, fixing_part_id)
            VALUES (%(id)s, %(appliance_type)s, %(brand)s, %(symptom_id)s, %(title)s, %(body)s, %(fixing_part_id)s)
            ON CONFLICT (id) DO NOTHING
            """,
            story.model_dump(),
        )
        conn.commit()
