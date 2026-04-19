import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from src.chatbot import tools as tools_mod
from src.chatbot.tools import calcOrderPrice

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


def test_no_cached_order_returns_zero_breakdown_without_clover_call():
    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value=None) as mock_cache_get,
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock) as mock_doc,
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock) as mock_fetch,
        ):
            result = await calcOrderPrice("session-1")
            mock_cache_get.assert_awaited_once()
            mock_doc.assert_not_awaited()
            mock_fetch.assert_not_awaited()
            return result

    result = _run(_test())
    assert result == {
        "success": True,
        "lineItems": [],
        "subtotal": 0,
        "tax": 0,
        "total": 0,
        "currency": "USD",
        "error": None,
    }


def test_returns_priced_line_items_and_totals():
    doc = _mock_integration_doc()
    order_response = {
        "id": "order-1",
        "currency": "USD",
        "subtotal": 2248,
        "taxAmount": 158,
        "total": 2406,
        "lineItems": {
            "elements": [
                {
                    "id": "li-1",
                    "name": "Chicken Sando",
                    "unitQty": 2000,
                    "price": 899,
                    "priceWithModifiers": 1099,
                    "modifications": {
                        "elements": [
                            {
                                "id": "modif-1",
                                "modifier": {"id": "mod-spicy", "name": "Spicy"},
                                "amount": 100,
                            }
                        ]
                    },
                },
                {
                    "id": "li-2",
                    "name": "Regular Fries",
                    "unitQty": 1000,
                    "price": 350,
                },
            ]
        },
        "discounts": {"elements": []},
    }

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response) as mock_fetch,
        ):
            result = await calcOrderPrice("session-1")
            assert mock_fetch.call_args.kwargs["expand"] == ["lineItems", "lineItems.modifications", "discounts"]
            return result

    result = _run(_test())
    assert result == {
        "success": True,
        "lineItems": [
            {
                "lineItemId": "li-1",
                "name": "Chicken Sando",
                "quantity": 2,
                "unitPrice": 899,
                "modifierPrices": [
                    {"modifierId": "mod-spicy", "name": "Spicy", "price": 100},
                ],
                "lineTotal": 1099,
            },
            {
                "lineItemId": "li-2",
                "name": "Regular Fries",
                "quantity": 1,
                "unitPrice": 350,
                "modifierPrices": [],
                "lineTotal": 350,
            },
        ],
        "subtotal": 2248,
        "tax": 202,
        "total": 2450,
        "currency": "USD",
        "error": None,
    }


def test_uses_prediscount_subtotal_and_line_totals_when_discounts_exist():
    doc = _mock_integration_doc()
    order_response = {
        "id": "order-2",
        "currency": "USD",
        "subtotal": 1400,
        "taxAmount": 95,
        "total": 1195,
        "discounts": {"elements": [{"id": "disc-1", "name": "Lunch deal", "amount": 300}]},
        "lineItems": {
            "elements": [
                {
                    "id": "li-salad",
                    "name": "Caesar Salad",
                    "unitQty": 1000,
                    "price": 1200,
                    "priceWithModifiers": 1400,
                    "discountAmount": 300,
                    "modifications": {
                        "elements": [
                            {"id": "modif-avocado", "modifier": {"id": "mod-avocado", "name": "Avocado"}, "amount": 100},
                            {"id": "modif-tofu", "modifier": {"id": "mod-tofu", "name": "Tofu"}, "amount": 100},
                        ]
                    },
                }
            ]
        },
    }

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-2"),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response),
        ):
            return await calcOrderPrice("session-2")

    result = _run(_test())
    assert result["success"] is True
    assert result["lineItems"][0]["lineTotal"] == 1400
    assert result["subtotal"] == 1400
    assert result["tax"] == 126
    assert result["total"] == 1526


def test_missing_pricing_fields_fall_back_to_zero_and_default_currency():
    doc = _mock_integration_doc()
    order_response = {
        "id": "order-3",
        "lineItems": {
            "elements": [
                {
                    "id": "li-1",
                    "name": "Mystery Item",
                    "unitQty": 1000,
                    "modifications": {
                        "elements": [
                            {"id": "modif-1", "modifier": {"id": "mod-1", "name": "Addon"}},
                        ]
                    },
                }
            ]
        },
    }

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-3"),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response),
        ):
            return await calcOrderPrice("session-3")

    result = _run(_test())
    assert result == {
        "success": True,
        "lineItems": [
            {
                "lineItemId": "li-1",
                "name": "Mystery Item",
                "quantity": 1,
                "unitPrice": 0,
                "modifierPrices": [{"modifierId": "mod-1", "name": "Addon", "price": 0}],
                "lineTotal": 0,
            }
        ],
        "subtotal": 0,
        "tax": 0,
        "total": 0,
        "currency": "USD",
        "error": None,
    }


def test_rebuilds_line_and_order_totals_when_clover_omits_them():
    doc = _mock_integration_doc()
    order_response = {
        "id": "order-live-shape",
        "currency": "USD",
        "lineItems": {
            "elements": [
                {
                    "id": "DHGD4AFT6JKWG",
                    "name": "Can Diet Coke",
                    "unitQty": 1000,
                    "price": 200,
                },
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
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response),
        ):
            return await calcOrderPrice("session-live-shape")

    result = _run(_test())
    assert result == {
        "success": True,
        "lineItems": [
            {
                "lineItemId": "DHGD4AFT6JKWG",
                "name": "Can Diet Coke",
                "quantity": 1,
                "unitPrice": 200,
                "modifierPrices": [],
                "lineTotal": 200,
            },
            {
                "lineItemId": "KCMJW2QQGHJK2",
                "name": "Chicken Sando",
                "quantity": 1,
                "unitPrice": 899,
                "modifierPrices": [
                    {"modifierId": "3MWZTR3VCY4X2", "name": "Plain Fries", "price": 350},
                ],
                "lineTotal": 1249,
            },
        ],
        "subtotal": 1449,
        "tax": 130,
        "total": 1579,
        "currency": "USD",
        "error": None,
    }


def test_rebuilds_total_from_subtotal_and_tax_when_total_missing():
    doc = _mock_integration_doc()
    order_response = {
        "id": "order-tax-only",
        "currency": "USD",
        "taxAmount": 100,
        "lineItems": {
            "elements": [
                {
                    "id": "li-1",
                    "name": "Chicken Sando",
                    "unitQty": 1000,
                    "price": 899,
                    "modifications": {
                        "elements": [
                            {
                                "id": "modif-fries",
                                "modifier": {"id": "mod-fries", "name": "Plain Fries"},
                                "amount": 350,
                            }
                        ]
                    },
                }
            ]
        },
    }

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-tax-only"),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response),
        ):
            return await calcOrderPrice("session-tax-only")

    result = _run(_test())
    assert result["success"] is True
    assert result["lineItems"][0]["lineTotal"] == 1249
    assert result["subtotal"] == 1249
    assert result["tax"] == 112
    assert result["total"] == 1361


def test_fetch_order_failure_returns_error():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-4"),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=RuntimeError("network error")),
        ):
            return await calcOrderPrice("session-4")

    result = _run(_test())
    assert result == {
        "success": False,
        "lineItems": [],
        "subtotal": 0,
        "tax": 0,
        "total": 0,
        "currency": "USD",
        "error": "network error",
    }


def test_falls_back_when_discounts_expansion_is_forbidden():
    doc = _mock_integration_doc()
    order_response = {
        "id": "order-5",
        "currency": "USD",
        "subtotal": 1249,
        "taxAmount": 87,
        "total": 1336,
        "lineItems": {
            "elements": [
                {
                    "id": "li-1",
                    "name": "Chicken Sando",
                    "unitQty": 1000,
                    "price": 899,
                },
                {
                    "id": "li-2",
                    "name": "Regular Fries",
                    "unitQty": 1000,
                    "price": 350,
                },
            ]
        },
    }
    request = httpx.Request("GET", "https://apisandbox.dev.clover.com/v3/merchants/test/orders/order-5")
    response = httpx.Response(403, request=request)

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-5"),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch(
                "src.chatbot.tools.fetch_clover_order",
                new_callable=AsyncMock,
                side_effect=[
                    httpx.HTTPStatusError("forbidden", request=request, response=response),
                    order_response,
                ],
            ) as mock_fetch,
        ):
            result = await calcOrderPrice("session-5")
            first_expand = mock_fetch.await_args_list[0].kwargs["expand"]
            second_expand = mock_fetch.await_args_list[1].kwargs["expand"]
            assert first_expand == ["lineItems", "lineItems.modifications", "discounts"]
            assert second_expand == ["lineItems", "lineItems.modifications"]
            return result

    result = _run(_test())
    assert result == {
        "success": True,
        "lineItems": [
            {
                "lineItemId": "li-1",
                "name": "Chicken Sando",
                "quantity": 1,
                "unitPrice": 899,
                "modifierPrices": [],
                "lineTotal": 899,
            },
            {
                "lineItemId": "li-2",
                "name": "Regular Fries",
                "quantity": 1,
                "unitPrice": 350,
                "modifierPrices": [],
                "lineTotal": 350,
            },
        ],
        "subtotal": 1249,
        "tax": 112,
        "total": 1361,
        "currency": "USD",
        "error": None,
    }
