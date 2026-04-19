import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.chatbot import tools as tools_mod
from src.chatbot.tools import get_item_details

_FAKE_SETTINGS = SimpleNamespace(
    MERCHANT_ID="merchant-1",
    CLOVER_APP_ID=None,
    CLOVER_API_BASE_URL="https://apisandbox.dev.clover.com",
)

_FAKE_CREDS = {
    "merchant_id": "merchant-1",
    "token": "fake-token",
    "base_url": "https://apisandbox.dev.clover.com",
}

_FAKE_MENU = {
    "by_id": {
        "item-burger": {
            "id": "item-burger",
            "name": "Classic Burger",
            "alternateName": "Double patty burger",
            "price": 1099,
            "categories": {"elements": [{"id": "cat-burgers", "name": "Burgers"}]},
            "available": True,
            "modifierGroups": {"elements": []},
        }
    }
}


def _run(coro):
    return asyncio.run(coro)


def test_get_item_details_returns_menu_row_fields():
    with (
        patch.object(tools_mod, "settings", _FAKE_SETTINGS),
        patch(
            "src.chatbot.tools.prepare_clover_data",
            new_callable=AsyncMock,
            return_value=_FAKE_CREDS,
        ),
        patch(
            "src.chatbot.tools._menu_items_cached_or_fresh",
            new_callable=AsyncMock,
            return_value=_FAKE_MENU,
        ),
    ):
        result = _run(get_item_details("item-burger", "merchant-1"))

    assert result == {
        "id": "item-burger",
        "name": "Classic Burger",
        "description": "Double patty burger",
        "price": 1099,
        "modifier_groups": [],
        "categories": {"elements": [{"id": "cat-burgers", "name": "Burgers"}]},
        "available": True,
    }


def test_get_item_details_fails_closed_on_merchant_mismatch():
    with (
        patch.object(tools_mod, "settings", _FAKE_SETTINGS),
        patch(
            "src.chatbot.tools.prepare_clover_data",
            new_callable=AsyncMock,
            return_value=_FAKE_CREDS,
        ),
        patch(
            "src.chatbot.tools._menu_items_cached_or_fresh",
            new_callable=AsyncMock,
            return_value=_FAKE_MENU,
        ) as mock_menu,
    ):
        result = _run(get_item_details("item-burger", "wrong-merchant"))

    mock_menu.assert_not_awaited()
    assert result == {"available": False}


def test_get_item_details_returns_unavailable_for_missing_item():
    with (
        patch.object(tools_mod, "settings", _FAKE_SETTINGS),
        patch(
            "src.chatbot.tools.prepare_clover_data",
            new_callable=AsyncMock,
            return_value=_FAKE_CREDS,
        ),
        patch(
            "src.chatbot.tools._menu_items_cached_or_fresh",
            new_callable=AsyncMock,
            return_value={"by_id": {}},
        ),
    ):
        result = _run(get_item_details("item-missing", "merchant-1"))

    assert result == {"available": False}
