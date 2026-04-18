import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.chatbot import tools as tools_mod
from src.chatbot.tools import check_item_availability


def _fake_settings():
    return SimpleNamespace(
        RESTAURANT_ID="test-user-id",
        CLOVER_APP_ID=None,
        CLOVER_API_BASE_URL="https://apisandbox.dev.clover.com",
    )


def test_check_item_availability_fresh_cache_available_no_live_fetch():
    menu = {
        "chicken sando": {
            "id": "item-1",
            "name": "Chicken Sando",
            "category_id": "c1",
            "category_name": "Sandwiches",
            "price": 899,
            "description": None,
            "modifier_groups": [],
            "available": True,
            "hidden": False,
            "deleted": False,
        },
    }
    now = str(int(time.time()))

    mock_doc = MagicMock()
    mock_doc.to_dict.return_value = {
        "access_token": "t",
        "merchant_id": "m1",
    }
    mock_doc.reference = MagicMock()

    mock_firestore = MagicMock()

    async def _run() -> dict:
        async def cache_get_side_effect(key: str):
            if key == "menu:m1":
                return json.dumps(menu)
            if key == "menu:fetched_at:m1":
                return now
            return None

        with (
            patch.object(tools_mod, "settings", _fake_settings()),
            patch("src.firebase.firebaseDatabase", mock_firestore),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock) as mock_doc_fn,
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock) as mock_cache_get,
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
            patch("src.chatbot.tools.fetch_clover_item", new_callable=AsyncMock) as mock_fetch_item,
        ):
            mock_doc_fn.return_value = mock_doc
            mock_cache_get.side_effect = cache_get_side_effect
            out = await check_item_availability("item-1", "m1")
            mock_fetch_item.assert_not_awaited()
            return out

    result = asyncio.run(_run())

    assert result["Available"] is True
    assert result["itemId"] == "item-1"
    assert result["itemName"] == "Chicken Sando"
    assert result["unavailableReason"] is None


def test_check_item_availability_merchant_mismatch():
    mock_doc = MagicMock()
    mock_doc.to_dict.return_value = {"access_token": "t", "merchant_id": "m1"}
    mock_doc.reference = MagicMock()
    mock_firestore = MagicMock()

    async def _run() -> dict:
        with (
            patch.object(tools_mod, "settings", _fake_settings()),
            patch("src.firebase.firebaseDatabase", mock_firestore),
            patch("src.chatbot.tools._clover_integration_doc", new_callable=AsyncMock) as mock_doc_fn,
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock),
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
        ):
            mock_doc_fn.return_value = mock_doc
            return await check_item_availability("item-1", "wrong-merchant")

    result = asyncio.run(_run())
    assert result["Available"] is False
    assert "merchant" in (result["unavailableReason"] or "").lower()
