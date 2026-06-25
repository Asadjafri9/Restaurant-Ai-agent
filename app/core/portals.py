"""Portal definitions — each UI only accepts matching accounts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PortalConfig:
    name: str
    tenant_slug: str | None
    roles: frozenset[str]
    db_label: str


PORTALS: dict[str, PortalConfig] = {
    "admin": PortalConfig(
        name="Platform Admin",
        tenant_slug=None,
        roles=frozenset({"platform_admin"}),
        db_label="central (metadata only)",
    ),
    "kfc": PortalConfig(
        name="KFC",
        tenant_slug="kfc",
        roles=frozenset({"owner", "manager", "staff"}),
        db_label="tdb_kfc",
    ),
    "kababjees": PortalConfig(
        name="Kababjees",
        tenant_slug="kababjees",
        roles=frozenset({"owner", "manager", "staff"}),
        db_label="tdb_kababjees",
    ),
}


def user_matches_portal(
    *,
    role: str,
    tenant_id: str | None,
    tenant_slug: str | None,
    portal: str,
) -> bool:
    cfg = PORTALS.get(portal)
    if not cfg:
        return False
    if role not in cfg.roles:
        return False
    if cfg.tenant_slug is None:
        return tenant_id is None
    return tenant_slug == cfg.tenant_slug
