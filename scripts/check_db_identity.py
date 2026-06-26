"""Print Postgres server identity for a tenant env file."""
import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import text

from app.config.settings import get_settings
from app.db.standalone import close_standalone_db, get_standalone_session


def load_env(slug: str) -> None:
    root = Path(__file__).resolve().parent.parent
    for line in (root / "local" / f"{slug}.env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()
    os.environ["SERVICE_MODE"] = slug
    os.environ["TENANT_DATABASE_URL"] = os.environ["DATABASE_URL"]


async def main() -> None:
    slug = sys.argv[1] if len(sys.argv) > 1 else "kfc"
    await close_standalone_db()
    load_env(slug)
    get_settings.cache_clear()
    session = await get_standalone_session()
    async with session:
        row = (
            await session.execute(
                text(
                    "SELECT inet_server_addr()::text, inet_server_port(), "
                    "current_database(), pg_postmaster_start_time()::text"
                )
            )
        ).one()
        items = (
            await session.execute(
                text("SELECT name FROM menu_items WHERE deleted_at IS NULL ORDER BY sort_order LIMIT 3")
            )
        ).scalars().all()
    print(f"{slug} server={row} sample_items={list(items)}")


if __name__ == "__main__":
    asyncio.run(main())
