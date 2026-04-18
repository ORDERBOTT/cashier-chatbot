import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.chatbot import tools as tools_mod
from src.chatbot.tools import changeItemQuantity

_FAKE_SETTINGS = SimpleNamespace(
    MERCHANT_ID="test-merchant-id",
    CLOVER_APP_ID=None,
    CLOVER_API_BASE_URL="https://apisandbox.dev.clover.com",
)

_FAKE_ORDER = {
    "id": "order-1",
    "total": 2148,
    "lineItems": {
        "elements": [
            {
                "id": "li-chicken",
                "name": "Chicken Sando",
                "unitQty": 2000,
                "price": 1798,
                "note": "extra pickles",
                "item": {"id": "item-chicken"},
                "modifications": {
                    "elements": [
                        {"modifier": {"id": "mod-spicy", "name": "Spicy"}},
                    ]
                },
            },
            {
                "id": "li-fries",
                "name": "Regular Fries",
                "unitQty": 1000,
                "price": 350,
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


def test_change_quantity_by_lineitem_id_success():
    doc = _mock_integration_doc()
    updated_order = {"id": "order-1", "total": 3047}

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, updated_order]),
            patch("src.chatbot.tools.update_clover_line_item", new_callable=AsyncMock, return_value={"id": "li-chicken"}) as mock_update,
        ):
            result = await changeItemQuantity("session-1", {"lineitemId": "li-chicken"}, newQuantity=3)
            mock_update.assert_awaited_once()
            call_args = mock_update.call_args
            assert call_args.args[4] == "li-chicken"
            assert call_args.kwargs["quantity"] == 3
            return result

    result = _run(_test())
    assert result == {
        "success": True,
        "itemName": "Chicken Sando",
        "previousQuantity": 2,
        "newQuantity": 3,
        "updatedOrderTotal": 3047,
        "error": None,
    }


def test_change_quantity_by_order_position_success():
    doc = _mock_integration_doc()
    updated_order = {"id": "order-1", "total": 2697}

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, updated_order]),
            patch("src.chatbot.tools.update_clover_line_item", new_callable=AsyncMock, return_value={"id": "li-fries"}) as mock_update,
        ):
            result = await changeItemQuantity("session-1", {"orderPosition": 2}, newQuantity=2)
            assert mock_update.call_args.args[4] == "li-fries"
            assert mock_update.call_args.kwargs["quantity"] == 2
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["itemName"] == "Regular Fries"
    assert result["previousQuantity"] == 1
    assert result["newQuantity"] == 2


def test_change_quantity_by_name_success():
    doc = _mock_integration_doc()
    updated_order = {"id": "order-1", "total": 3047}

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, updated_order]),
            patch("src.chatbot.tools.update_clover_line_item", new_callable=AsyncMock, return_value={"id": "li-chicken"}) as mock_update,
        ):
            result = await changeItemQuantity("session-1", {"itemName": "chicken sando"}, newQuantity=3)
            mock_update.assert_awaited_once()
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["itemName"] == "Chicken Sando"


def test_zero_or_negative_quantity_returns_error():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.update_clover_line_item", new_callable=AsyncMock) as mock_update,
        ):
            result = await changeItemQuantity("session-1", {"lineItemId": "li-chicken"}, newQuantity=0)
            mock_update.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is False
    assert result["itemName"] == "Chicken Sando"
    assert result["previousQuantity"] == 2
    assert "greater than zero" in result["error"]


def test_unchanged_quantity_returns_success_without_mutation():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.update_clover_line_item", new_callable=AsyncMock) as mock_update,
        ):
            result = await changeItemQuantity("session-1", {"lineItemId": "li-chicken"}, newQuantity=2)
            mock_update.assert_not_awaited()
            return result

    result = _run(_test())
    assert result == {
        "success": True,
        "itemName": "Chicken Sando",
        "previousQuantity": 2,
        "newQuantity": 2,
        "updatedOrderTotal": 2148,
        "error": None,
    }


def test_missing_target_returns_error():
    async def _test():
        with patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock) as mock_fetch:
            result = await changeItemQuantity("session-1", {}, newQuantity=3)
            mock_fetch.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is False
    assert "must provide" in result["error"]
    assert result["itemName"] == ""
    assert result["previousQuantity"] == 0


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
            patch("src.chatbot.tools.update_clover_line_item", new_callable=AsyncMock) as mock_update,
        ):
            result = await changeItemQuantity("session-1", {"lineItemId": "li-missing"}, newQuantity=3)
            mock_update.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is False
    assert "not found" in result["error"].lower()


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
            patch("src.chatbot.tools.update_clover_line_item", new_callable=AsyncMock) as mock_update,
        ):
            result = await changeItemQuantity("session-2", {"itemName": "chicken"}, newQuantity=2)
            mock_update.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is False
    assert "ambiguous" in result["error"]


def test_update_failure_returns_error():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.update_clover_line_item", new_callable=AsyncMock, side_effect=Exception("Clover 500")),
        ):
            return await changeItemQuantity("session-1", {"lineItemId": "li-chicken"}, newQuantity=3)

    result = _run(_test())
    assert result["success"] is False
    assert "failed to update item quantity" in result["error"]


def test_updated_total_fetch_failure_is_non_fatal():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, RuntimeError("network error")]),
            patch("src.chatbot.tools.update_clover_line_item", new_callable=AsyncMock, return_value={"id": "li-chicken"}),
        ):
            return await changeItemQuantity("session-1", {"lineItemId": "li-chicken"}, newQuantity=3)

    result = _run(_test())
    assert result["success"] is True
    assert result["updatedOrderTotal"] == 0
    assert result["error"] is None
