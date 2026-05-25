"""Build the NetworkXKG from Postgres tables.

Postgres is the source of truth; the KG is derived. Re-run this any time
seed data changes. The result can be cached to data/kg.json via
save_snapshot() for fast process restart.
"""

from __future__ import annotations

from app.db.pool import connection
from app.kg.networkx_kg import NetworkXKG


def build_kg_from_postgres() -> NetworkXKG:
    kg = NetworkXKG()

    with connection() as conn, conn.cursor() as cur:
        # Parts
        cur.execute("SELECT * FROM parts")
        for row in cur.fetchall():
            kg.add_part(
                id=row["id"],
                name=row["name"],
                manufacturer=row["manufacturer"],
                appliance_type=row["appliance_type"],
                part_type=row["part_type"],
                price_cents=row["price_cents"],
                in_stock=row["in_stock"],
                description=row["description"],
            )
            # Part -[MADE_BY]-> Brand
            kg.add_made_by(row["id"], row["manufacturer"])

        # Models
        cur.execute("SELECT * FROM models")
        for row in cur.fetchall():
            kg.add_model(
                id=row["id"],
                brand=row["brand"],
                appliance_type=row["appliance_type"],
                year=row["year"],
                series=row["series"],
                manual_url=row["manual_url"],
            )
            # Model -[MADE_BY]-> Brand and Model -[BELONGS_TO]-> ApplianceType
            kg.add_made_by(row["id"], row["brand"])
            kg.add_belongs_to(row["id"], row["appliance_type"])

        # Compatibility (Part -[FITS]-> Model)
        cur.execute("SELECT * FROM compatibility")
        for row in cur.fetchall():
            kg.add_fits(
                row["part_id"],
                row["model_id"],
                sub_assembly_only=row["sub_assembly_only"],
                requires_adapter=row["requires_adapter"],
                supersedes=row["supersedes"],
            )

        # Symptoms
        cur.execute("SELECT * FROM symptoms")
        for row in cur.fetchall():
            kg.add_symptom(
                id=row["id"],
                description=row["description"],
                canonical_label=row["canonical_label"],
                appliance_type=row["appliance_type"],
            )
            kg.add_occurs_in(row["id"], row["appliance_type"])

        # Symptom -[FIXES]<- Part
        cur.execute("SELECT * FROM symptom_fixes")
        for row in cur.fetchall():
            kg.add_fixes(
                row["part_id"],
                row["symptom_id"],
                likelihood=row["likelihood"],
                common_cause_rank=row["common_cause_rank"],
            )

        # Install guides
        cur.execute("SELECT * FROM install_guides")
        for row in cur.fetchall():
            kg.add_install_guide(
                id=row["id"],
                part_id=row["part_id"],
                difficulty=row["difficulty"],
                estimated_minutes=row["estimated_minutes"],
                tools_required=row["tools_required"],
                safety_warnings=row["safety_warnings"],
                steps=row["steps"],
                video_url=row["video_url"],
                series_fitment_hint=row["series_fitment_hint"],
            )
            kg.add_installed_via(row["part_id"], row["id"])

    return kg
