import uuid
from unittest.mock import AsyncMock, patch

from app.core.tenant_ids import TENANT_IDS
from app.services.catalog_service import get_menu_for_tenant

KFC_ITEMS = [{"name": "Zinger Burger", "price": 520.0, "tenant_item_id": "1"}]
KABAB_ITEMS = [{"name": "Chicken Biryani", "price": 450.0, "tenant_item_id": "2"}]
ALL_TENANT_DB_ITEMS = KFC_ITEMS + KABAB_ITEMS


async def test_kfc_menu_does_not_merge_other_restaurant_items():
    kfc_id = TENANT_IDS["kfc"]

    with patch(
        "app.services.catalog_service._load_menu_from_central",
        AsyncMock(return_value=KFC_ITEMS),
    ):
        with patch(
            "app.services.catalog_service._load_menu_from_tenant_db",
            AsyncMock(return_value=ALL_TENANT_DB_ITEMS),
        ):
            items = await get_menu_for_tenant(kfc_id, force_refresh=True)

    assert len(items) == 1
    assert items[0]["name"] == "Zinger Burger"
    assert not any(i["name"] == "Chicken Biryani" for i in items)


async def test_isolated_tenant_db_preferred_over_central():
    kabab_id = TENANT_IDS["kababjees"]
    live_menu = [
        {"name": "Chicken Biryani", "price": 450.0, "tenant_item_id": "a"},
        {"name": "Beef Kabab Roll", "price": 350.0, "tenant_item_id": "b"},
    ]
    stale_central = [{"name": "Chicken Tikka", "price": 420.0, "tenant_item_id": "x"}]

    with patch(
        "app.services.catalog_service._load_menu_from_central",
        AsyncMock(return_value=stale_central),
    ):
        with patch(
            "app.services.catalog_service._load_menu_from_tenant_db",
            AsyncMock(return_value=live_menu),
        ):
            items = await get_menu_for_tenant(kabab_id, force_refresh=True)

    assert items == live_menu
