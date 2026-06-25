"""One-shot: rebuild central catalog mirror for all active tenants."""

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.tenant_ids import TENANT_IDS
from app.db.central import get_central_session
from app.db.models_central import Tenant
from app.services.menu_sync import sync_tenant_menu_to_central


def _load_env_file(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        key, _, val = line.partition("=")
        os.environ[key.strip()] = val.strip()


async def _sync_slug(slug: str, env_file: Path | None) -> None:
    from app.config.settings import get_settings
    from app.db.standalone import close_standalone_db

    await close_standalone_db()
    if env_file and env_file.exists():
        _load_env_file(env_file)
    os.environ["SERVICE_MODE"] = slug
    os.environ["TENANT_ID"] = str(TENANT_IDS[slug])
    if os.environ.get("DATABASE_URL"):
        os.environ["TENANT_DATABASE_URL"] = os.environ["DATABASE_URL"]
    get_settings.cache_clear()

    async for session in get_central_session():
        result = await session.execute(select(Tenant).where(Tenant.slug == slug))
        tenant = result.scalar_one_or_none()
        if not tenant:
            print(f"SKIP {slug}: no tenant row")
            return
        count = await sync_tenant_menu_to_central(tenant.id)
        print(f"OK {slug}: synced {count} items")


async def main() -> None:
    root = Path(__file__).resolve().parent.parent
    local = root / "local"
    slugs = sys.argv[1:] if len(sys.argv) > 1 else list(TENANT_IDS.keys())
    for slug in slugs:
        env_file = local / f"{slug}.env"
        await _sync_slug(slug, env_file)


if __name__ == "__main__":
    asyncio.run(main())
