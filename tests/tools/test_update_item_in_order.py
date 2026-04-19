import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.chatbot import tools as tools_mod
from src.chatbot.tools import updateItemInOrder

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
                "unitQty": 1000,
                "price": 1798,
                "note": "extra pickles",
                "item": {"id": "item-chicken"},
                "modifications": {
                    "elements": [
                        {"id": "modification-spicy", "modifier": {"id": "mod-spicy", "name": "Spicy"}},
                        {"id": "modification-cheese", "modifier": {"id": "mod-cheese", "name": "Extra Cheese"}},
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


def test_update_by_lineitem_id_success():
    doc = _mock_integration_doc()
    updated_order = {"id": "order-1", "total": 2398}

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, updated_order]),
            patch("src.chatbot.tools.delete_clover_modification", new_callable=AsyncMock) as mock_delete_mod,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock) as mock_add_mod,
            patch("src.chatbot.tools.update_clover_line_item", new_callable=AsyncMock, return_value={"id": "li-chicken"}) as mock_update_line,
        ):
            result = await updateItemInOrder(
                "session-1",
                {"lineitemId": "li-chicken"},
                {
                    "removeModifiers": ["mod-spicy"],
                    "addModifiers": ["mod-bacon"],
                    "note": "sauce on side",
                },
            )
            delete_args = mock_delete_mod.call_args.args
            assert delete_args[4] == "li-chicken"
            assert delete_args[5] == "modification-spicy"
            add_args = mock_add_mod.call_args.args
            assert add_args[4] == "li-chicken"
            assert add_args[5] == "mod-bacon"
            assert mock_update_line.call_args.kwargs["note"] == "sauce on side"
            return result

    result = _run(_test())
    assert result == {
        "success": True,
        "itemName": "Chicken Sando",
        "appliedChanges": "removed 1 modifier, added 1 modifier, updated note",
        "updatedOrderTotal": 2398,
        "error": None,
    }


def test_update_by_order_position_clear_note():
    doc = _mock_integration_doc()
    updated_order = {"id": "order-1", "total": 2048}

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, updated_order]),
            patch("src.chatbot.tools.delete_clover_modification", new_callable=AsyncMock) as mock_delete_mod,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock) as mock_add_mod,
            patch("src.chatbot.tools.update_clover_line_item", new_callable=AsyncMock, return_value={"id": "li-chicken"}) as mock_update_line,
        ):
            result = await updateItemInOrder("session-1", {"orderPosition": 1}, {"note": None})
            mock_delete_mod.assert_not_awaited()
            mock_add_mod.assert_not_awaited()
            assert mock_update_line.call_args.kwargs["note"] is None
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["itemName"] == "Chicken Sando"
    assert result["appliedChanges"] == "cleared note"
    assert result["updatedOrderTotal"] == 2048
    assert result["error"] is None


def test_update_by_name_add_only_success():
    doc = _mock_integration_doc()
    updated_order = {"id": "order-1", "total": 2248}

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, updated_order]),
            patch("src.chatbot.tools.delete_clover_modification", new_callable=AsyncMock) as mock_delete_mod,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock) as mock_add_mod,
            patch("src.chatbot.tools.update_clover_line_item", new_callable=AsyncMock) as mock_update_line,
        ):
            result = await updateItemInOrder(
                "session-1",
                {"itemName": "chicken sando"},
                {"addModifiers": ["mod-avocado"]},
            )
            mock_delete_mod.assert_not_awaited()
            mock_add_mod.assert_awaited_once()
            mock_update_line.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["itemName"] == "Chicken Sando"
    assert result["appliedChanges"] == "added 1 modifier"
    assert result["updatedOrderTotal"] == 2248


def test_modifier_conflict_returns_error():
    result = _run(
        updateItemInOrder(
            "session-1",
            {"lineItemId": "li-chicken"},
            {"addModifiers": ["mod-spicy"], "removeModifiers": ["mod-spicy"]},
        )
    )
    assert result["success"] is False
    assert "cannot appear in both" in result["error"]
    assert result["itemName"] == ""
    assert result["appliedChanges"] == ""


def test_missing_target_returns_error():
    result = _run(updateItemInOrder("session-1", {}, {"addModifiers": ["mod-bacon"]}))
    assert result["success"] is False
    assert "must provide" in result["error"]
    assert result["itemName"] == ""


def test_empty_updates_returns_error():
    result = _run(updateItemInOrder("session-1", {"lineItemId": "li-chicken"}, {}))
    assert result["success"] is False
    assert "updates must include" in result["error"]


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
        ):
            return await updateItemInOrder("session-1", {"lineItemId": "li-missing"}, {"addModifiers": ["mod-bacon"]})

    result = _run(_test())
    assert result["success"] is False
    assert "not found" in result["error"]


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
        ):
            return await updateItemInOrder("session-2", {"itemName": "chicken"}, {"addModifiers": ["mod-bacon"]})

    result = _run(_test())
    assert result["success"] is False
    assert "ambiguous" in result["error"]


def test_idempotent_no_op_returns_success_without_mutation():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.delete_clover_modification", new_callable=AsyncMock) as mock_delete_mod,
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock) as mock_add_mod,
            patch("src.chatbot.tools.update_clover_line_item", new_callable=AsyncMock) as mock_update_line,
        ):
            result = await updateItemInOrder(
                "session-1",
                {"lineItemId": "li-chicken"},
                {"addModifiers": ["mod-spicy"], "removeModifiers": ["mod-missing"], "note": "extra pickles"},
            )
            mock_delete_mod.assert_not_awaited()
            mock_add_mod.assert_not_awaited()
            mock_update_line.assert_not_awaited()
            return result

    result = _run(_test())
    assert result == {
        "success": True,
        "itemName": "Chicken Sando",
        "appliedChanges": "no changes applied",
        "updatedOrderTotal": 2148,
        "error": None,
    }


def test_remove_modifier_failure_returns_error():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.delete_clover_modification", new_callable=AsyncMock, side_effect=Exception("Clover 500")),
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock),
            patch("src.chatbot.tools.update_clover_line_item", new_callable=AsyncMock),
        ):
            return await updateItemInOrder("session-1", {"lineItemId": "li-chicken"}, {"removeModifiers": ["mod-spicy"]})

    result = _run(_test())
    assert result["success"] is False
    assert "failed to remove modifier" in result["error"]
    assert result["appliedChanges"] == "no changes applied"


def test_add_modifier_failure_returns_error_after_partial_progress():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.delete_clover_modification", new_callable=AsyncMock),
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock, side_effect=Exception("Clover 500")),
            patch("src.chatbot.tools.update_clover_line_item", new_callable=AsyncMock),
        ):
            return await updateItemInOrder(
                "session-1",
                {"lineItemId": "li-chicken"},
                {"removeModifiers": ["mod-spicy"], "addModifiers": ["mod-bacon"]},
            )

    result = _run(_test())
    assert result["success"] is False
    assert "failed to add modifier" in result["error"]
    assert result["appliedChanges"] == "removed 1 modifier"


def test_note_update_failure_returns_error_after_modifier_changes():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, return_value=_FAKE_ORDER),
            patch("src.chatbot.tools.delete_clover_modification", new_callable=AsyncMock),
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock),
            patch("src.chatbot.tools.update_clover_line_item", new_callable=AsyncMock, side_effect=Exception("Clover 500")),
        ):
            return await updateItemInOrder(
                "session-1",
                {"lineItemId": "li-chicken"},
                {"removeModifiers": ["mod-spicy"], "addModifiers": ["mod-bacon"], "note": "sauce on side"},
            )

    result = _run(_test())
    assert result["success"] is False
    assert "failed to update line item note" in result["error"]
    assert result["appliedChanges"] == "removed 1 modifier, added 1 modifier"


def test_updated_total_fetch_failure_returns_zero():
    doc = _mock_integration_doc()

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock, return_value=doc),
            patch("src.chatbot.tools.ensure_fresh_clover_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value="order-1"),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_order", new_callable=AsyncMock, side_effect=[_FAKE_ORDER, Exception("network error")]),
            patch("src.chatbot.tools.delete_clover_modification", new_callable=AsyncMock),
            patch("src.chatbot.tools.add_clover_modification", new_callable=AsyncMock),
            patch("src.chatbot.tools.update_clover_line_item", new_callable=AsyncMock, return_value={"id": "li-chicken"}),
        ):
            return await updateItemInOrder("session-1", {"lineItemId": "li-chicken"}, {"note": "sauce on side"})

    result = _run(_test())
    assert result["success"] is True
    assert result["appliedChanges"] == "updated note"
    assert result["updatedOrderTotal"] == 0
