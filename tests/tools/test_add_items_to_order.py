import asyncio
from unittest.mock import AsyncMock, call, patch

from src.chatbot import tools as tools_mod
from src.chatbot.tools import addItemsToOrder

_FAKE_CREDS = {
    "token": "fake-token",
    "merchant_id": "test-merchant-id",
    "base_url": "https://apisandbox.dev.clover.com",
}

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


def _run(coro):
    return asyncio.run(coro)


def test_add_single_item_success():
    line_item_response = {"id": "li-abc", "price": 899}
    order_response = {"id": "order-1", "total": 899}

    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=_FAKE_MENU),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock, return_value=line_item_response) as mock_add_line,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock) as mock_add_mod,
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response),
        ):
            result = await addItemsToOrder(
                "session-1",
                [{"itemId": "item-chicken", "quantity": 1}],
                creds=_FAKE_CREDS,
            )
            mock_add_line.assert_awaited_once()
            mock_add_mod.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is True
    assert len(result["addedItems"]) == 1
    assert result["addedItems"][0]["lineItemId"] == "li-abc"
    assert result["addedItems"][0]["itemId"] == "item-chicken"
    assert result["addedItems"][0]["quantity"] == 1
    assert result["addedItems"][0]["modifiersApplied"] == []
    assert result["updatedOrderTotal"] == 899
    assert result["failedItems"] == []


def test_add_item_with_modifier():
    line_item_response = {"id": "li-abc", "price": 899}
    order_response = {"id": "order-1", "total": 949}

    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=_FAKE_MENU),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock, return_value=line_item_response),
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock) as mock_add_mod,
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response),
        ):
            result = await addItemsToOrder(
                "session-1",
                [{"itemId": "item-chicken", "quantity": 1, "modifiers": ["mod-spicy"]}],
                creds=_FAKE_CREDS,
            )
            mock_add_mod.assert_awaited_once()
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["addedItems"][0]["modifiersApplied"] == ["mod-spicy"]
    assert result["failedItems"] == []
    assert result["updatedOrderTotal"] == 949


def test_add_item_quantity_creates_separate_line_items():
    """quantity=3 should call add_clover_line_item 3 times, producing 3 entries each with quantity=1."""
    line_item_responses = [
        {"id": "li-1", "price": 899},
        {"id": "li-2", "price": 899},
        {"id": "li-3", "price": 899},
    ]
    order_response = {"id": "order-1", "total": 2697}

    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=_FAKE_MENU),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock, side_effect=line_item_responses) as mock_add_line,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response),
        ):
            result = await addItemsToOrder(
                "session-1",
                [{"itemId": "item-chicken", "quantity": 3}],
                creds=_FAKE_CREDS,
            )
            assert mock_add_line.await_count == 3
            return result

    result = _run(_test())
    assert result["success"] is True
    assert len(result["addedItems"]) == 3
    for entry in result["addedItems"]:
        assert entry["quantity"] == 1
        assert entry["itemId"] == "item-chicken"
    assert result["addedItems"][0]["lineItemId"] == "li-1"
    assert result["addedItems"][1]["lineItemId"] == "li-2"
    assert result["addedItems"][2]["lineItemId"] == "li-3"
    assert result["failedItems"] == []


def test_add_item_quantity_with_modifiers_per_unit():
    """quantity=2 with 1 modifier should apply the modifier to each unit independently (2 mod calls total)."""
    line_item_responses = [
        {"id": "li-1", "price": 899},
        {"id": "li-2", "price": 899},
    ]
    order_response = {"id": "order-1", "total": 1798}

    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=_FAKE_MENU),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock, side_effect=line_item_responses) as mock_add_line,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock) as mock_add_mod,
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=order_response),
        ):
            result = await addItemsToOrder(
                "session-1",
                [{"itemId": "item-chicken", "quantity": 2, "modifiers": ["mod-spicy"]}],
                creds=_FAKE_CREDS,
            )
            assert mock_add_line.await_count == 2
            assert mock_add_mod.await_count == 2
            return result

    result = _run(_test())
    assert result["success"] is True
    assert len(result["addedItems"]) == 2
    for entry in result["addedItems"]:
        assert entry["quantity"] == 1
        assert entry["modifiersApplied"] == ["mod-spicy"]
    assert result["failedItems"] == []


def test_ambiguous_id_fails():
    ambiguous_menu = {
        **_FAKE_MENU,
        "by_id": {
            **_FAKE_MENU["by_id"],
            "mod-spicy": {"id": "mod-spicy", "name": "Spicy Item", "price": 100},
        },
    }

    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=ambiguous_menu),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock) as mock_add_line,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value={"total": 0}),
        ):
            result = await addItemsToOrder("session-1", [{"itemId": "mod-spicy"}], creds=_FAKE_CREDS)
            mock_add_line.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is False
    assert len(result["failedItems"]) == 1
    assert "ambiguous" in result["failedItems"][0]["reason"].lower()
    assert result["addedItems"] == []


def test_unknown_item_fails():
    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=_FAKE_MENU),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock) as mock_add_line,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value={"total": 0}),
        ):
            result = await addItemsToOrder("session-1", [{"itemId": "UNKNOWN-ID"}], creds=_FAKE_CREDS)
            mock_add_line.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is False
    assert len(result["failedItems"]) == 1
    assert "not found" in result["failedItems"][0]["reason"].lower()
    assert result["addedItems"] == []


def test_partial_success():
    line_item_response = {"id": "li-abc", "price": 899}
    order_response = {"id": "order-1", "total": 899}

    async def _test():
        with (
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
                creds=_FAKE_CREDS,
            )
            return result

    result = _run(_test())
    assert result["success"] is False
    assert len(result["addedItems"]) == 1
    assert result["addedItems"][0]["itemId"] == "item-chicken"
    assert len(result["failedItems"]) == 1
    assert result["failedItems"][0]["itemId"] == "UNKNOWN-ID"


def test_no_items_returns_success():
    async def _test():
        with (
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock),
            patch("src.chatbot.tools.add_clover_line_item", new_callable=AsyncMock) as mock_add_line,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock),
        ):
            result = await addItemsToOrder("session-1", None, creds=_FAKE_CREDS)
            mock_add_line.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["addedItems"] == []
    assert result["failedItems"] == []
    assert result["updatedOrderTotal"] == 0
