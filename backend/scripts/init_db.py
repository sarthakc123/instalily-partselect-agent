"""Apply schema.sql against the configured DATABASE_URL and report table counts.
Idempotent: schema uses IF NOT EXISTS everywhere. Safe to run repeatedly.

Usage:
    cd backend && python -m scripts.init_db
"""

from __future__ import annotations

import sys

from app.db.pool import apply_schema, connection, close_pool


TABLES = [
    "parts",
    "models",
    "compatibility",
    "symptoms",
    "symptom_fixes",
    "install_guides",
    "repair_stories",
    "conversations",
    "messages",
    "tickets",
]


def main() -> int:
    try:
        print("Applying schema...")
        apply_schema()
        print("Schema applied.")

        with connection() as conn, conn.cursor() as cur:
            print("\nTable counts:")
            for table in TABLES:
                cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
                row = cur.fetchone()
                print(f"  {table:<20} {row['n']:>6}")

            cur.execute("SELECT extname FROM pg_extension ORDER BY extname")
            exts = [r["extname"] for r in cur.fetchall()]
            print(f"\nExtensions: {', '.join(exts)}")

        return 0
    finally:
        close_pool()


if __name__ == "__main__":
    sys.exit(main())
