"""Stable tenant UUIDs shared across agent central DB and tenant services."""

import uuid

NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

TENANT_IDS: dict[str, uuid.UUID] = {
    "kfc": uuid.uuid5(NAMESPACE, "tenant:kfc"),
    "kababjees": uuid.uuid5(NAMESPACE, "tenant:kababjees"),
}
