import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.chatbot import tools as tools_mod
from src.chatbot.tools import removeItemFromOrder

_FAKE_SETTINGS = SimpleNamespace(
    MERCHANT_ID="test-merchant-id",
    CLOVER_APP_ID=None,
    CLOVER_API_BASE_URL="https://apisandbox.dev.clover.com",
)

_FAKE_ORDER = {
    "id": "order-1",
    "total": 1249,
    "lineItems": {
        "elements": [
            {
                "id": "li-chicken",
                "name": "Chicken Sando",
                "unitQty": 1000,
                "item": {"id": "item-chicken"},
            },
            {
                "id": "li-fries",
                "name": "Regular Fries",
                "unitQty": 1000,
                "item": {"id": "item-fries"},
            },
        ]
    },
}

_AMBIGUOUS_ORDER = {
    "id": "order-2",
    "total": 1799,
    "lineItems": {
        "elements": [
            {
                "id": "li-grilled-chicken",
                "name": "Grilled Chicken",
                "unitQty": 1000,
                "item": {"id": "item-grilled-chicken"},
            },
            {
                "id": "li-crispy-chicken",
                "name": "Crispy Chicken",
                "unitQty": 1000,
                "item": {"id": "item-crispy-chicken"},
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


def test_remove_by_order_position_success():
    doc = _mock_integration_doc()
    updated_order = {"id": "order-1", "total": 350}

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, updated_order]),
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock) as mock_delete,
        ):
            result = await removeItemFromOrder("session-1", {"orderPosition": 1})
            call_args = mock_delete.call_args
            assert call_args.args[4] == "li-chicken"
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["removedItem"] == {"name": "Chicken Sando", "quantity": 1}
    assert result["remainingQuantity"] == 0
    assert result["updatedOrderTotal"] == 350
    assert result["error"] is None


def test_remove_by_name_success():
    doc = _mock_integration_doc()
    updated_order = {"id": "order-1", "total": 899}

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, updated_order]),
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock) as mock_delete,
        ):
            result = await removeItemFromOrder("session-1", {"itemName": "chicken sando"})
            mock_delete.assert_awaited_once()
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["removedItem"]["name"] == "Chicken Sando"
    assert result["remainingQuantity"] == 0


def test_target_not_found_returns_error():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock) as mock_delete,
        ):
            result = await removeItemFromOrder("session-1", {"orderPosition": 99})
            mock_delete.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is False
    assert "out of range" in result["error"]
    assert result["removedItem"] is None


def test_no_target_provided_returns_error():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock) as mock_delete,
        ):
            result = await removeItemFromOrder("session-1", {})
            mock_delete.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is False
    assert "must provide" in result["error"]
    assert result["removedItem"] is None


def test_ambiguous_name_returns_error():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-2"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_AMBIGUOUS_ORDER),
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock) as mock_delete,
        ):
            result = await removeItemFromOrder("session-2", {"itemName": "chicken"})
            mock_delete.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is False
    assert "ambiguous" in result["error"]
    assert result["removedItem"] is None


def test_remove_fails_returns_error():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock, side_effect=Exception("Clover 500")),
        ):
            return await removeItemFromOrder("session-1", {"orderPosition": 1})

    result = _run(_test())
    assert result["success"] is False
    assert result["error"] is not None
    assert result["removedItem"] is None
