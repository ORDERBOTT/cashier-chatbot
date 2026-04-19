import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.chatbot import tools as tools_mod
from src.chatbot.tools import addItemsToOrder

_FAKE_SETTINGS = SimpleNamespace(
    MERCHANT_ID="test-merchant-id",
    CLOVER_APP_ID=None,
    CLOVER_API_BASE_URL="https://apisandbox.dev.clover.com",
)

_FAKE_MENU = {
    "by_id": {
        "item-chicken": {
            "id": "item-chicken",
            "name": "Chicken Sando",
            "price": 899,
            "modifierGroups": {
                "elements": [
                    {
                        "id": "grp-1",
                        "modifiers": {
                            "elements": [
                                {"id": "mod-spicy", "name": "Spicy"},
                            ]
                        },
                    }
                ]
            },
        },
        "item-fries": {
            "id": "item-fries",
            "name": "Regular Fries",
            "price": 350,
            "modifierGroups": {"elements": []},
        },
    },
    "by_modifier_id": {"mod-spicy": "item-chicken"},
    "by_name": {},
    "by_category": {},
}


def _mock_integration_doc(merchant_id: str = "test-merchant-id") -> MagicMock:
    doc = MagicMock()
    doc.to_dict.return_value = {
        "access_token": "fake-token",
        "merchant_id": merchant_id,
        "api_base_url": "https://apisandbox.dev.clover.com",
    }
    doc.reference = MagicMock()
    return doc


def _run(coro):
    return asyncio.run(coro)


def test_add_single_item_success():
    doc = _mock_integration_doc()
    line_item_response = {"id": "li-abc", "price": 899}
    order_response = {"id": "order-1", "total": 899}

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=_FAKE_MENU),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock, return_value=line_item_response) as mock_add_line,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock) as mock_add_mod,
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response),
        ):
            result = await addItemsToOrder("session-1", [{"itemId": "item-chicken", "quantity": 1}])
            mock_add_line.assert_awaited_once()
            mock_add_mod.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is True
    assert len(result["addedItems"]) == 1
    assert result["addedItems"][0]["lineItemId"] == "li-abc"
    assert result["addedItems"][0]["itemId"] == "item-chicken"
    assert result["addedItems"][0]["modifiersApplied"] == []
    assert result["updatedOrderTotal"] == 899
    assert result["failedItems"] == []


def test_add_item_with_modifier():
    doc = _mock_integration_doc()
    line_item_response = {"id": "li-abc", "price": 899}
    mod_response = {"id": "modif-1"}
    order_response = {"id": "order-1", "total": 949}

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=_FAKE_MENU),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock, return_value=line_item_response),
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock, return_value=mod_response) as mock_add_mod,
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response),
        ):
            result = await addItemsToOrder(
                "session-1",
                [{"itemId": "item-chicken", "quantity": 1, "modifiers": ["mod-spicy"]}],
            )
            mock_add_mod.assert_awaited_once()
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["addedItems"][0]["modifiersApplied"] == ["mod-spicy"]
    assert result["failedItems"] == []
    assert result["updatedOrderTotal"] == 949


def test_ambiguous_id_fails():
    doc = _mock_integration_doc()
    # Make mod-spicy also appear in by_id so it's ambiguous
    ambiguous_menu = {
        **_FAKE_MENU,
        "by_id": {
            **_FAKE_MENU["by_id"],
            "mod-spicy": {"id": "mod-spicy", "name": "Spicy Item", "price": 100},
        },
    }

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=ambiguous_menu),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock) as mock_add_line,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value={"total": 0}),
        ):
            result = await addItemsToOrder("session-1", [{"itemId": "mod-spicy"}])
            mock_add_line.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is False
    assert len(result["failedItems"]) == 1
    assert "ambiguous" in result["failedItems"][0]["reason"].lower()
    assert result["addedItems"] == []


def test_unknown_item_fails():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=_FAKE_MENU),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock) as mock_add_line,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value={"total": 0}),
        ):
            result = await addItemsToOrder("session-1", [{"itemId": "UNKNOWN-ID"}])
            mock_add_line.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is False
    assert len(result["failedItems"]) == 1
    assert "not found" in result["failedItems"][0]["reason"].lower()
    assert result["addedItems"] == []


def test_partial_success():
    doc = _mock_integration_doc()
    line_item_response = {"id": "li-abc", "price": 899}
    order_response = {"id": "order-1", "total": 899}

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=_FAKE_MENU),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock, return_value=line_item_response),
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response),
        ):
            result = await addItemsToOrder(
                "session-1",
                [{"itemId": "item-chicken"}, {"itemId": "UNKNOWN-ID"}],
            )
            return result

    result = _run(_test())
    assert result["success"] is False
    assert len(result["addedItems"]) == 1
    assert result["addedItems"][0]["itemId"] == "item-chicken"
    assert len(result["failedItems"]) == 1
    assert result["failedItems"][0]["itemId"] == "UNKNOWN-ID"


def test_no_items_returns_success():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock) as mock_add_line,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock),
        ):
            result = await addItemsToOrder("session-1", None)
            mock_add_line.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["addedItems"] == []
    assert result["failedItems"] == []
    assert result["updatedOrderTotal"] == 0
