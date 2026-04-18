import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

from src.chatbot.tools import find_closest_menu_items


def test_find_closest_menu_items_chicken_sando():
    """find_closest_menu_items resolves a casual spelling to the menu row."""

    row = {
        "id": "item-chicken-sando",
        "name": "Chicken Sando",
    }
    cached_menu = {
        "by_name": {"chicken sando": row},
        "by_id": {"item-chicken-sando": row},
        "by_category": {},
    }

    mock_doc = MagicMock()
    mock_doc.to_dict.return_value = {
        "access_token": "test-access-token",
        "merchant_id": "test-merchant-id",
    }
    mock_doc.reference = MagicMock()

    mock_clover_ref = MagicMock()
    mock_clover_ref.get = AsyncMock(return_value=mock_doc)

    mock_integrations = MagicMock()
    mock_integrations.document.return_value = mock_clover_ref

    mock_user_ref = MagicMock()
    mock_user_ref.collection.return_value = mock_integrations

    mock_users_col = MagicMock()
    mock_users_col.document.return_value = mock_user_ref

    mock_firestore = MagicMock()
    mock_firestore.collection.return_value = mock_users_col

    async def cache_get_side_effect(key: str) -> str | None:
        if key == "menu:fetched_at:test-merchant-id":
            return str(int(time.time()))
        if key == "menu:test-merchant-id":
            return json.dumps(cached_menu)
        return None

    async def _run() -> dict:
        with (
            patch("src.firebase.firebaseDatabase", mock_firestore),
            patch("src.chatbot.tools.cache_get", new_callable=AsyncMock) as mock_cache_get,
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
        ):
            mock_cache_get.side_effect = cache_get_side_effect
            return await find_closest_menu_items("chicken sando")

    result = asyncio.run(_run())

    assert result["match_confidence"] == "exact"
    assert result["exact_match"] is not None
    assert result["exact_match"]["name"] == "Chicken Sando"
    assert any(c["name"] == "Chicken Sando" for c in result["candidates"])
