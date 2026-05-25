"""Build the NetworkX KG from Postgres and persist a JSON snapshot to disk.

Usage:
    cd backend && python -m scripts.build_kg
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.config import settings
from app.db.pool import close_pool
from app.kg.builder import build_kg_from_postgres


def main() -> int:
    try:
        print("Building KG from Postgres...")
        kg = build_kg_from_postgres()

        snapshot_path = Path(settings.kg_path).resolve()
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        kg.save_snapshot(snapshot_path)
        print(f"Snapshot written: {snapshot_path}")

        stats = kg.stats()
        print("\nKG stats:")
        for k, v in stats.items():
            print(f"  {k:<32} {v:>6}")

        return 0
    finally:
        close_pool()


if __name__ == "__main__":
    sys.exit(main())
