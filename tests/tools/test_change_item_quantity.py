import asyncio
from unittest.mock import AsyncMock, patch

from src.chatbot import tools as tools_mod
from src.chatbot.tools import changeItemQuantity

_FAKE_CREDS = {
    "token": "fake-token",
    "merchant_id": "test-merchant-id",
    "base_url": "https://apisandbox.dev.clover.com",
}

_FAKE_ORDER = {
    "id": "order-1",
    "total": 2148,
    "lineItems": {
        "elements": [
            {
                "id": "li-chicken-1",
                "name": "Chicken Sando",
                "unitQty": 1000,
                "price": 899,
                "item": {"id": "item-chicken"},
                "modifications": {
                    "elements": [{"modifier": {"id": "mod-spicy", "name": "Spicy"}}]
                },
            },
            {
                "id": "li-chicken-2",
                "name": "Chicken Sando",
                "unitQty": 1000,
                "price": 899,
                "item": {"id": "item-chicken"},
                "modifications": {"elements": []},
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


def _run(coro):
    return asyncio.run(coro)


def test_increase_quantity_by_name():
    """2→3 Chicken Sando via itemName; resolves to li-chicken-1 (has Spicy modifier)."""
    updated_order = {"id": "order-1", "total": 3047}
    new_li = {"id": "li-chicken-new"}

    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, updated_order]),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock, return_value=new_li) as mock_add,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock) as mock_mod,
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock) as mock_del,
        ):
            result = await changeItemQuantity("session-1", {"itemName": "chicken sando"}, newQuantity=3, creds=_FAKE_CREDS)
            mock_add.assert_awaited_once()
            mock_mod.assert_awaited_once()
            call_args = mock_mod.call_args
            assert call_args.args[5] == "mod-spicy"
            mock_del.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["itemName"] == "Chicken Sando"
    assert result["previousQuantity"] == 2
    assert result["newQuantity"] == 3
    assert result["updatedOrderTotal"] == 3047
    assert result["error"] is None


def test_decrease_quantity_by_name():
    """2→1 Chicken Sando via itemName; deletes the first same-name item."""
    updated_order = {"id": "order-1", "total": 1249}

    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, updated_order]),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock) as mock_add,
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock) as mock_del,
        ):
            result = await changeItemQuantity("session-1", {"itemName": "chicken sando"}, newQuantity=1, creds=_FAKE_CREDS)
            mock_add.assert_not_awaited()
            mock_del.assert_awaited_once()
            call_args = mock_del.call_args
            assert call_args.args[4] == "li-chicken-1"
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["itemName"] == "Chicken Sando"
    assert result["previousQuantity"] == 2
    assert result["newQuantity"] == 1


def test_increase_by_lineitem_id():
    """li-chicken-1, 2→4: adds 2 line items each with the Spicy modifier."""
    new_li_a = {"id": "li-new-a"}
    new_li_b = {"id": "li-new-b"}
    updated_order = {"id": "order-1", "total": 3946}

    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, updated_order]),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock, side_effect=[new_li_a, new_li_b]) as mock_add,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock) as mock_mod,
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock) as mock_del,
        ):
            result = await changeItemQuantity("session-1", {"lineitemId": "li-chicken-1"}, newQuantity=4, creds=_FAKE_CREDS)
            assert mock_add.await_count == 2
            assert mock_mod.await_count == 2
            mock_del.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["previousQuantity"] == 2
    assert result["newQuantity"] == 4


def test_decrease_by_order_position():
    """Position 1 (li-chicken-1), 2→1: deletes one item."""
    updated_order = {"id": "order-1", "total": 1249}

    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, updated_order]),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock) as mock_add,
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock) as mock_del,
        ):
            result = await changeItemQuantity("session-1", {"orderPosition": 1}, newQuantity=1, creds=_FAKE_CREDS)
            mock_add.assert_not_awaited()
            mock_del.assert_awaited_once()
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["itemName"] == "Chicken Sando"
    assert result["previousQuantity"] == 2
    assert result["newQuantity"] == 1


def test_no_op_unchanged_quantity():
    """2→2 Chicken Sando: no API mutation calls."""
    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock) as mock_add,
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock) as mock_del,
        ):
            result = await changeItemQuantity("session-1", {"itemName": "Chicken Sando"}, newQuantity=2, creds=_FAKE_CREDS)
            mock_add.assert_not_awaited()
            mock_del.assert_not_awaited()
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


def test_zero_quantity_returns_error():
    """newQuantity=0: error without any API calls."""
    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock) as mock_add,
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock) as mock_del,
        ):
            result = await changeItemQuantity("session-1", {"lineItemId": "li-chicken-1"}, newQuantity=0, creds=_FAKE_CREDS)
            mock_add.assert_not_awaited()
            mock_del.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is False
    assert "greater than zero" in result["error"]
    assert result["itemName"] == "Chicken Sando"
    assert result["previousQuantity"] == 2


def test_missing_target_returns_error():
    """Empty target dict: error before any fetch."""
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


def test_target_not_found_by_id():
    """lineItemId not in order: returns not-found error."""
    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock) as mock_add,
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock) as mock_del,
        ):
            result = await changeItemQuantity("session-1", {"lineItemId": "li-missing"}, newQuantity=3, creds=_FAKE_CREDS)
            mock_add.assert_not_awaited()
            mock_del.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_ambiguous_name_returns_error():
    """Fuzzy name matches two distinct items: returns ambiguous error."""
    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-2"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_AMBIGUOUS_ORDER),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock) as mock_add,
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock) as mock_del,
        ):
            result = await changeItemQuantity("session-2", {"itemName": "chicken"}, newQuantity=2, creds=_FAKE_CREDS)
            mock_add.assert_not_awaited()
            mock_del.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is False
    assert "ambiguous" in result["error"]


def test_add_fails_returns_error():
    """add_clover_line_item raises: returns error with 'failed to change item quantity'."""
    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock, side_effect=Exception("Clover 500")),
        ):
            return await changeItemQuantity("session-1", {"lineItemId": "li-chicken-1"}, newQuantity=3, creds=_FAKE_CREDS)

    result = _run(_test())
    assert result["success"] is False
    assert "failed to change item quantity" in result["error"]


def test_delete_fails_returns_error():
    """delete_clover_line_item raises: returns error with 'failed to change item quantity'."""
    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.delete_clover_line_item", new_callable=AsyncMock, side_effect=Exception("Clover 500")),
        ):
            return await changeItemQuantity("session-1", {"lineItemId": "li-chicken-1"}, newQuantity=1, creds=_FAKE_CREDS)

    result = _run(_test())
    assert result["success"] is False
    assert "failed to change item quantity" in result["error"]


def test_updated_total_fetch_failure_nonfatal():
    """Second fetch_clover_order raises: success=True, updatedOrderTotal=0."""
    new_li = {"id": "li-chicken-new"}

    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, RuntimeError("network error")]),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock, return_value=new_li),
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock),
        ):
            return await changeItemQuantity("session-1", {"lineItemId": "li-chicken-1"}, newQuantity=3, creds=_FAKE_CREDS)

    result = _run(_test())
    assert result["success"] is True
    assert result["updatedOrderTotal"] == 0
    assert result["error"] is None
