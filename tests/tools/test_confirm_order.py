import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.chatbot import tools as tools_mod
from src.chatbot.tools import confirmOrder

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


def test_missing_cached_order_returns_order_is_empty():
    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value=None) as mock_cache_get,
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock) as mock_doc,
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock) as mock_fetch,
            patch("src.chatbot.tools.update_clover_order", new_callable=AsyncMock) as mock_update,
        ):
            result = await confirmOrder("session-1")
            mock_cache_get.assert_awaited_once()
            mock_doc.assert_not_awaited()
            mock_fetch.assert_not_awaited()
            mock_update.assert_not_awaited()
            return result

    result = _run(_test())
    assert result == {
        "success": False,
        "orderId": "",
        "confirmedItems": [],
        "finalTotal": 0,
        "estimatedPickuptime": None,
        "error": "order is empty",
    }


def test_empty_order_returns_order_is_empty():
    doc = _mock_integration_doc()
    order_response = {"id": "order-1", "lineItems": {"elements": []}}

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response) as mock_fetch,
            patch("src.chatbot.tools.update_clover_order", new_callable=AsyncMock) as mock_update,
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock) as mock_cache_set,
        ):
            result = await confirmOrder("session-1")
            mock_fetch.assert_awaited_once()
            mock_update.assert_not_awaited()
            mock_cache_set.assert_not_awaited()
            return result

    result = _run(_test())
    assert result == {
        "success": False,
        "orderId": "order-1",
        "confirmedItems": [],
        "finalTotal": 0,
        "estimatedPickuptime": None,
        "error": "order is empty",
    }


def test_confirm_order_success():
    doc = _mock_integration_doc()
    current_order = {
        "id": "order-1",
        "lineItems": {
            "elements": [
                {"id": "li-1", "name": "Chicken Sando", "unitQty": 1000, "price": 899},
                {"id": "li-2", "name": "Regular Fries", "unitQty": 2000, "price": 700},
            ]
        },
    }
    final_order = {
        "id": "order-1",
        "lineItems": {
            "elements": [
                {"id": "li-1", "name": "Chicken Sando", "unitQty": 1000, "price": 899},
                {"id": "li-2", "name": "Regular Fries", "unitQty": 2000, "price": 700},
            ]
        },
    }

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[current_order, final_order]),
            patch("src.chatbot.tools.update_clover_order", new_callable=AsyncMock, return_value={"id": "order-1"}) as mock_update,
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock) as mock_cache_set,
        ):
            result = await confirmOrder("session-1")
            assert mock_update.call_args.kwargs["state"] == "Open"
            mock_cache_set.assert_awaited_once_with("session:session-1:status", "confirmed")
            return result

    result = _run(_test())
    assert result == {
        "success": True,
        "orderId": "order-1",
        "confirmedItems": [
            {"lineItemId": "li-1", "name": "Chicken Sando", "quantity": 1, "price": 899, "lineTotal": 899},
            {"lineItemId": "li-2", "name": "Regular Fries", "quantity": 2, "price": 700, "lineTotal": 700},
        ],
        "finalTotal": 1743,
        "estimatedPickuptime": None,
        "error": None,
    }


def test_confirm_order_uses_calc_order_price_logic_for_modifier_backed_totals():
    doc = _mock_integration_doc()
    current_order = {
        "id": "order-live-shape",
        "lineItems": {
            "elements": [
                {"id": "li-1", "name": "Can Diet Coke", "unitQty": 1000, "price": 200},
                {"id": "li-2", "name": "Chicken Sando", "unitQty": 1000, "price": 899},
            ]
        },
    }
    final_order = {
        "id": "order-live-shape",
        "currency": "USD",
        "lineItems": {
            "elements": [
                {"id": "DHGD4AFT6JKWG", "name": "Can Diet Coke", "unitQty": 1000, "price": 200},
                {
                    "id": "KCMJW2QQGHJK2",
                    "name": "Chicken Sando",
                    "unitQty": 1000,
                    "price": 899,
                    "modifications": {
                        "elements": [
                            {
                                "id": "modif-fries",
                                "modifier": {"id": "3MWZTR3VCY4X2", "name": "Plain Fries"},
                                "amount": 350,
                            }
                        ]
                    },
                },
            ]
        },
    }

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-live-shape"),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[current_order, final_order]),
            patch("src.chatbot.tools.update_clover_order", new_callable=AsyncMock, return_value={"id": "order-live-shape"}),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
        ):
            return await confirmOrder("session-live-shape")

    result = _run(_test())
    assert result == {
        "success": True,
        "orderId": "order-live-shape",
        "confirmedItems": [
            {"lineItemId": "DHGD4AFT6JKWG", "name": "Can Diet Coke", "quantity": 1, "price": 200, "lineTotal": 200},
            {"lineItemId": "KCMJW2QQGHJK2", "name": "Chicken Sando", "quantity": 1, "price": 899, "lineTotal": 1249},
        ],
        "finalTotal": 1579,
        "estimatedPickuptime": None,
        "error": None,
    }


def test_confirm_order_update_failure_returns_error_without_setting_status():
    doc = _mock_integration_doc()
    current_order = {
        "id": "order-1",
        "lineItems": {"elements": [{"id": "li-1", "name": "Chicken Sando", "unitQty": 1000, "price": 899}]},
    }

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=current_order),
            patch("src.chatbot.tools.update_clover_order", new_callable=AsyncMock, side_effect=Exception("Clover 500")),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock) as mock_cache_set,
        ):
            result = await confirmOrder("session-1")
            mock_cache_set.assert_not_awaited()
            return result

    result = _run(_test())
    assert result == {
        "success": False,
        "orderId": "order-1",
        "confirmedItems": [],
        "finalTotal": 0,
        "estimatedPickuptime": None,
        "error": "Clover 500",
    }


def test_confirm_order_final_fetch_failure_returns_error_without_setting_status():
    doc = _mock_integration_doc()
    current_order = {
        "id": "order-1",
        "lineItems": {"elements": [{"id": "li-1", "name": "Chicken Sando", "unitQty": 1000, "price": 899}]},
    }

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[current_order, Exception("network error")]),
            patch("src.chatbot.tools.update_clover_order", new_callable=AsyncMock, return_value={"id": "order-1"}),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock) as mock_cache_set,
        ):
            result = await confirmOrder("session-1")
            mock_cache_set.assert_not_awaited()
            return result

    result = _run(_test())
    assert result == {
        "success": False,
        "orderId": "order-1",
        "confirmedItems": [],
        "finalTotal": 0,
        "estimatedPickuptime": None,
        "error": "network error",
    }
