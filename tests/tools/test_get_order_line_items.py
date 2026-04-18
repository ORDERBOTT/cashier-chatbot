import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.chatbot import tools as tools_mod
from src.chatbot.tools import getOrderLineItems

_FAKE_SETTINGS = SimpleNamespace(
    MERCHANT_ID="test-merchant-id",
    CLOVER_APP_ID=None,
    CLOVER_API_BASE_URL="https://apisandbox.dev.clover.com",
)


def _mock_integration_doc() -> MagicMock:
    doc = MagicMock()
    doc.to_dict.return_value = {
        "access_token": "fake-token",
        "merchant_id": "test-merchant-id",
        "api_base_url": "https://apisandbox.dev.clover.com",
    }
    doc.reference = MagicMock()
    return doc


def _run(coro):
    return asyncio.run(coro)


def test_returns_line_items():
    doc = _mock_integration_doc()
    order_response = {
        "id": "order-1",
        "total": 1249,
        "lineItems": {
            "elements": [
                {"id": "li-1", "name": "Chicken Sando", "unitQty": 1000, "price": 899},
                {"id": "li-2", "name": "Regular Fries", "unitQty": 1000, "price": 350},
            ]
        },
    }

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response),
        ):
            return await getOrderLineItems("session-1")

    result = _run(_test())
    assert result["success"] is True
    assert result["orderId"] == "order-1"
    assert result["orderTotal"] == 1249
    assert result["error"] is None
    assert len(result["lineItems"]) == 2

    item1 = result["lineItems"][0]
    assert item1["lineItemId"] == "li-1"
    assert item1["name"] == "Chicken Sando"
    assert item1["quantity"] == 1
    assert item1["price"] == 899

    item2 = result["lineItems"][1]
    assert item2["lineItemId"] == "li-2"
    assert item2["name"] == "Regular Fries"
    assert item2["quantity"] == 1
    assert item2["price"] == 350


def test_empty_order():
    doc = _mock_integration_doc()
    order_response = {"id": "order-2", "total": 0}

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-2"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response),
        ):
            return await getOrderLineItems("session-2")

    result = _run(_test())
    assert result["success"] is True
    assert result["orderId"] == "order-2"
    assert result["lineItems"] == []
    assert result["orderTotal"] == 0
    assert result["error"] is None


def test_fetch_order_fails():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-3"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=RuntimeError("network error")),
        ):
            return await getOrderLineItems("session-3")

    result = _run(_test())
    assert result["success"] is False
    assert result["orderId"] == ""
    assert result["lineItems"] == []
    assert result["orderTotal"] == 0
    assert "network error" in result["error"]
