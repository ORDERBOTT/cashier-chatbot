import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.chatbot import tools as tools_mod
from src.chatbot.tools import replaceItemInOrder

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
        "item-rings": {
            "id": "item-rings",
            "name": "Onion Rings",
            "price": 399,
            "modifierGroups": {"elements": []},
        },
    },
    "by_modifier_id": {"mod-spicy": "item-chicken"},
    "by_name": {},
    "by_category": {},
}

_FAKE_ORDER = {
    "id": "order-1",
    "total": 899,
    "lineItems": {
        "elements": [
            {
                "id": "li-fries",
                "name": "Regular Fries",
                "unitQty": 1000,
                "item": {"id": "item-fries"},
            },
            {
                "id": "li-chicken",
                "name": "Chicken Sando",
                "unitQty": 1000,
                "item": {"id": "item-chicken"},
            },
        ]
    },
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


def test_replace_by_line_item_id_success():
    doc = _mock_integration_doc()
    line_item_response = {"id": "li-rings", "price": 399}
    updated_order = {"id": "order-1", "total": 1298}

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=_FAKE_MENU),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, updated_order]),
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock) as mock_delete,
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock, return_value=line_item_response) as mock_add,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock),
        ):
            result = await replaceItemInOrder(
                "session-1",
                replacement={"itemId": "item-rings", "quantity": 1},
                lineItemId="li-fries",
            )
            mock_delete.assert_awaited_once()
            mock_add.assert_awaited_once()
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["removedItem"] == {"name": "Regular Fries", "quantity": 1}
    assert result["addedItem"]["name"] == "Onion Rings"
    assert result["addedItem"]["quantity"] == 1
    assert result["addedItem"]["modifiersApplied"] == []
    assert result["addedItem"]["lineTotal"] == 399
    assert result["updatedOrderTotal"] == 1298
    assert result["error"] is None


def test_replace_by_order_position_success():
    doc = _mock_integration_doc()
    line_item_response = {"id": "li-rings", "price": 399}
    updated_order = {"id": "order-1", "total": 1298}

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=_FAKE_MENU),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, updated_order]),
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock) as mock_delete,
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock, return_value=line_item_response),
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock),
        ):
            # orderPosition=1 → first line item = "Regular Fries" (li-fries)
            result = await replaceItemInOrder(
                "session-1",
                replacement={"itemId": "item-rings", "quantity": 1},
                orderPosition=1,
            )
            call_args = mock_delete.call_args
            assert call_args.args[4] == "li-fries"
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["removedItem"]["name"] == "Regular Fries"


def test_replace_by_name_success():
    doc = _mock_integration_doc()
    line_item_response = {"id": "li-rings", "price": 399}
    updated_order = {"id": "order-1", "total": 1298}

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=_FAKE_MENU),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, updated_order]),
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock, return_value=line_item_response),
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock),
        ):
            result = await replaceItemInOrder(
                "session-1",
                replacement={"itemId": "item-rings", "quantity": 1},
                itemName="chicken sando",
            )
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["removedItem"]["name"] == "Chicken Sando"


def test_target_not_found_returns_error():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=_FAKE_MENU),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock) as mock_delete,
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock),
        ):
            result = await replaceItemInOrder(
                "session-1",
                replacement={"itemId": "item-rings"},
                lineItemId="li-does-not-exist",
            )
            mock_delete.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is False
    assert "not found" in result["error"].lower()
    assert result["removedItem"] is None
    assert result["addedItem"] is None


def test_partial_failure_rollback():
    """Delete succeeds but add_clover_line_item raises → rollback attempted, error returned."""
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=_FAKE_MENU),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock, side_effect=Exception("Clover 500")) as mock_add,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock),
        ):
            result = await replaceItemInOrder(
                "session-1",
                replacement={"itemId": "item-rings"},
                lineItemId="li-fries",
            )
            # add called twice: once for replacement, once for rollback (best-effort)
            assert mock_add.await_count >= 1
            return result

    result = _run(_test())
    assert result["success"] is False
    assert "add failed" in result["error"]
    assert "rollback" in result["error"]
    assert result["removedItem"] == {"name": "Regular Fries", "quantity": 1}
    assert result["addedItem"] is None


def test_replacement_item_unknown():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=_FAKE_MENU),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock) as mock_delete,
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock),
        ):
            result = await replaceItemInOrder(
                "session-1",
                replacement={"itemId": "item-unknown-xyz"},
                lineItemId="li-fries",
            )
            mock_delete.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is False
    assert "not on menu" in result["error"]
    assert result["removedItem"] is None
    assert result["addedItem"] is None
