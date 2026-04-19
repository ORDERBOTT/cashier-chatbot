import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import httpx

from src.chatbot.tools import cancelOrder


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


def test_confirmed_session_returns_error_without_cancelling():
    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, side_effect=["confirmed", "order-1"]),
            patch("src.chatbot.tools.delete_clover_order", new_callable=AsyncMock) as mock_delete,
            patch("src.chatbot.tools.cache_delete", new_callable=AsyncMock) as mock_cache_delete,
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock) as mock_cache_set,
        ):
            result = await cancelOrder("session-1")
            mock_delete.assert_not_awaited()
            mock_cache_delete.assert_not_awaited()
            mock_cache_set.assert_not_awaited()
            return result

    result = _run(_test())
    assert result == {
        "success": False,
        "cancelledOrderId": "order-1",
        "hadItems": False,
        "error": "order already confirmed and submitted",
    }


def test_no_order_returns_success_with_nothing_to_cancel():
    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, side_effect=[None, None]),
            patch("src.chatbot.tools.delete_clover_order", new_callable=AsyncMock) as mock_delete,
        ):
            result = await cancelOrder("session-1")
            mock_delete.assert_not_awaited()
            return result

    result = _run(_test())
    assert result == {
        "success": True,
        "cancelledOrderId": None,
        "hadItems": False,
        "error": None,
    }


def test_cancel_order_success_with_items():
    doc = _mock_integration_doc()
    order_response = {
        "id": "order-1",
        "lineItems": {
            "elements": [
                {"id": "li-1", "name": "Chicken Sando", "unitQty": 1000, "price": 899},
            ]
        },
    }

    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, side_effect=[None, "order-1"]),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response),
            patch("src.chatbot.tools.delete_clover_order", new_callable=AsyncMock) as mock_delete,
            patch("src.chatbot.tools.cache_delete", new_callable=AsyncMock) as mock_cache_delete,
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock) as mock_cache_set,
        ):
            result = await cancelOrder("session-1")
            mock_delete.assert_awaited_once()
            mock_cache_delete.assert_has_awaits(
                [call("orderstate:session-1"), call("order:session:session-1")]
            )
            mock_cache_set.assert_awaited_once_with("session:session-1:status", "cancelled")
            return result

    result = _run(_test())
    assert result == {
        "success": True,
        "cancelledOrderId": "order-1",
        "hadItems": True,
        "error": None,
    }


def test_cancel_order_success_with_empty_live_order_sets_had_items_false():
    doc = _mock_integration_doc()
    order_response = {"id": "order-1", "lineItems": {"elements": []}}

    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, side_effect=[None, "order-1"]),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response),
            patch("src.chatbot.tools.delete_clover_order", new_callable=AsyncMock),
            patch("src.chatbot.tools.cache_delete", new_callable=AsyncMock),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
        ):
            return await cancelOrder("session-1")

    result = _run(_test())
    assert result == {
        "success": True,
        "cancelledOrderId": "order-1",
        "hadItems": False,
        "error": None,
    }


def test_delete_404_is_treated_as_success():
    doc = _mock_integration_doc()
    order_response = {"id": "order-1", "lineItems": {"elements": []}}
    request = httpx.Request("DELETE", "https://apisandbox.dev.clover.com/v3/merchants/test/orders/order-1")
    response = httpx.Response(404, request=request)

    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, side_effect=[None, "order-1"]),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response),
            patch(
                "src.chatbot.tools.delete_clover_order",
                new_callable=AsyncMock,
                side_effect=httpx.HTTPStatusError("missing", request=request, response=response),
            ),
            patch("src.chatbot.tools.cache_delete", new_callable=AsyncMock) as mock_cache_delete,
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock) as mock_cache_set,
        ):
            result = await cancelOrder("session-1")
            mock_cache_delete.assert_has_awaits(
                [call("orderstate:session-1"), call("order:session:session-1")]
            )
            mock_cache_set.assert_awaited_once_with("session:session-1:status", "cancelled")
            return result

    result = _run(_test())
    assert result == {
        "success": True,
        "cancelledOrderId": "order-1",
        "hadItems": False,
        "error": None,
    }


def test_predelete_fetch_404_continues_with_success():
    doc = _mock_integration_doc()
    request = httpx.Request("GET", "https://apisandbox.dev.clover.com/v3/merchants/test/orders/order-1")
    response = httpx.Response(404, request=request)

    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, side_effect=[None, "order-1"]),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch(
                "src.chatbot.tools.fetch_clover_order",
                new_callable=AsyncMock,
                side_effect=httpx.HTTPStatusError("missing", request=request, response=response),
            ),
            patch("src.chatbot.tools.delete_clover_order", new_callable=AsyncMock),
            patch("src.chatbot.tools.cache_delete", new_callable=AsyncMock),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
        ):
            return await cancelOrder("session-1")

    result = _run(_test())
    assert result == {
        "success": True,
        "cancelledOrderId": "order-1",
        "hadItems": False,
        "error": None,
    }


def test_delete_failure_returns_error_without_clearing_state():
    doc = _mock_integration_doc()
    order_response = {"id": "order-1", "lineItems": {"elements": [{"id": "li-1"}]}}

    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, side_effect=[None, "order-1"]),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response),
            patch("src.chatbot.tools.delete_clover_order", new_callable=AsyncMock, side_effect=Exception("Clover 500")),
            patch("src.chatbot.tools.cache_delete", new_callable=AsyncMock) as mock_cache_delete,
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock) as mock_cache_set,
        ):
            result = await cancelOrder("session-1")
            mock_cache_delete.assert_not_awaited()
            mock_cache_set.assert_not_awaited()
            return result

    result = _run(_test())
    assert result == {
        "success": False,
        "cancelledOrderId": "order-1",
        "hadItems": False,
        "error": "Clover 500",
    }


def test_predelete_fetch_failure_returns_error_without_clearing_state():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, side_effect=[None, "order-1"]),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=Exception("network error")),
            patch("src.chatbot.tools.delete_clover_order", new_callable=AsyncMock) as mock_delete,
            patch("src.chatbot.tools.cache_delete", new_callable=AsyncMock) as mock_cache_delete,
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock) as mock_cache_set,
        ):
            result = await cancelOrder("session-1")
            mock_delete.assert_not_awaited()
            mock_cache_delete.assert_not_awaited()
            mock_cache_set.assert_not_awaited()
            return result

    result = _run(_test())
    assert result == {
        "success": False,
        "cancelledOrderId": "order-1",
        "hadItems": False,
        "error": "network error",
    }
