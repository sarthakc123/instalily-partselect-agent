"""Load the synthetic seed YAML into Postgres via the repository layer.

Idempotent: inserts use ON CONFLICT DO NOTHING. Re-run safely.

Usage:
    cd backend && python -m scripts.seed
    cd backend && python -m scripts.seed --reset    # wipe rows first
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from app.db import repository as repo
from app.db.pool import apply_schema, close_pool, connection
from app.schemas.entities import (
    Compatibility,
    InstallGuide,
    Model,
    Part,
    Symptom,
    SymptomFix,
)

SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "seed" / "seed.yaml"

TABLES_FOR_RESET = [
    "symptom_fixes",
    "compatibility",
    "install_guides",
    "repair_stories",
    "messages",
    "tickets",
    "conversations",
    "symptoms",
    "parts",
    "models",
]


def _reset() -> None:
    """Wipe all seed-able tables. Convenient for re-loading after edits."""
    with connection() as conn, conn.cursor() as cur:
        for table in TABLES_FOR_RESET:
            cur.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
        conn.commit()
    print(f"Truncated {len(TABLES_FOR_RESET)} tables.")


def _load_yaml() -> dict[str, list[dict[str, Any]]]:
    with SEED_FILE.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data


def _insert_parts(rows: list[dict[str, Any]]) -> int:
    for r in rows:
        repo.insert_part(Part(**r))
    return len(rows)


def _insert_models(rows: list[dict[str, Any]]) -> int:
    for r in rows:
        repo.insert_model(Model(**r))
    return len(rows)


def _insert_compat(rows: list[dict[str, Any]]) -> int:
    for r in rows:
        repo.insert_compat(Compatibility(**r))
    return len(rows)


def _insert_symptoms(rows: list[dict[str, Any]]) -> int:
    for r in rows:
        repo.insert_symptom(Symptom(**r))
    return len(rows)


def _insert_symptom_fixes(rows: list[dict[str, Any]]) -> int:
    for r in rows:
        repo.insert_symptom_fix(SymptomFix(**r))
    return len(rows)


def _insert_install_guides(rows: list[dict[str, Any]]) -> int:
    for r in rows:
        repo.insert_install_guide(InstallGuide(**r))
    return len(rows)


def _report_counts() -> None:
    print("\nFinal counts:")
    with connection() as conn, conn.cursor() as cur:
        for table in [
            "parts",
            "models",
            "compatibility",
            "symptoms",
            "symptom_fixes",
            "install_guides",
        ]:
            cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
            row = cur.fetchone()
            print(f"  {table:<20} {row['n']:>6}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed PartSelect Postgres from YAML.")
    parser.add_argument("--reset", action="store_true", help="Truncate before loading")
    args = parser.parse_args()

    try:
        apply_schema()
        if args.reset:
            _reset()

        data = _load_yaml()

        n_parts = _insert_parts(data.get("parts", []))
        n_models = _insert_models(data.get("models", []))
        n_compat = _insert_compat(data.get("compatibility", []))
        n_symptoms = _insert_symptoms(data.get("symptoms", []))
        n_fixes = _insert_symptom_fixes(data.get("symptom_fixes", []))
        n_guides = _insert_install_guides(data.get("install_guides", []))

        print(f"Loaded: parts={n_parts} models={n_models} compat={n_compat} "
              f"symptoms={n_symptoms} fixes={n_fixes} install_guides={n_guides}")

        _report_counts()
        return 0
    finally:
        close_pool()


if __name__ == "__main__":
    sys.exit(main())
