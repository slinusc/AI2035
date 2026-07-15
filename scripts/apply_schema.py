"""One-off helper: apply schema.sql to the configured database.

Usage: python scripts/apply_schema.py
Reads DATABASE_URL/SSL from config (i.e. from .env locally). Idempotent —
schema.sql uses CREATE TABLE IF NOT EXISTS.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402


async def main() -> None:
    if not config.DATABASE_URL:
        raise SystemExit("DATABASE_URL is not set")

    sql = (Path(__file__).resolve().parent.parent / "schema.sql").read_text(
        encoding="utf-8"
    )
    statements = [s.strip() for s in sql.split(";") if s.strip()]

    connect_args = {"ssl": True} if config.DATABASE_SSL else {}
    engine = create_async_engine(config.DATABASE_URL, connect_args=connect_args)

    from sqlalchemy import text

    async with engine.begin() as conn:
        for stmt in statements:
            await conn.exec_driver_sql(stmt)

    # Report the tables that now exist.
    async with engine.connect() as conn:
        rows = await conn.exec_driver_sql(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' ORDER BY tablename"
        )
        tables = [r[0] for r in rows.fetchall()]

    await engine.dispose()
    print("applied", len(statements), "statements")
    print("public tables:", ", ".join(tables))


if __name__ == "__main__":
    asyncio.run(main())
