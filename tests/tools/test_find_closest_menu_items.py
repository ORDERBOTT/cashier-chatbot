import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.chatbot.tools import find_closest_menu_items

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

_DUMMY_MENU_PATH = Path(__file__).parent.parent.parent / "data" / "dummy_clover_menu.json"
_RAW_MENU = json.loads(_DUMMY_MENU_PATH.read_text())

_CLOVER_CREDS = {"access_token": "tok", "merchant_id": "test-merchant"}


def _make_firestore_mock(creds: dict | None = _CLOVER_CREDS):
    """Return a MagicMock for firebaseDatabase whose Clover doc returns creds."""
    doc_mock = MagicMock()
    doc_mock.to_dict.return_value = creds
    get_mock = AsyncMock(return_value=doc_mock)

    clover_doc_mock = MagicMock()
    clover_doc_mock.get = get_mock

    integrations_col_mock = MagicMock()
    integrations_col_mock.document.return_value = clover_doc_mock

    user_doc_mock = MagicMock()
    user_doc_mock.collection.return_value = integrations_col_mock

    users_col_mock = MagicMock()
    users_col_mock.document.return_value = user_doc_mock

    db_mock = MagicMock()
    db_mock.collection.return_value = users_col_mock
    return db_mock


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call(item_name: str, details: str | None = None, creds: dict | None = _CLOVER_CREDS):
    with patch("src.chatbot.tools.firebaseDatabase", _make_firestore_mock(creds)), \
         patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value=None), \
         patch("src.chatbot.tools.cache_set", new_callable=AsyncMock), \
         patch("src.chatbot.tools.fetch_clover_menu", new_callable=AsyncMock, return_value=_RAW_MENU):
        return run(find_closest_menu_items(item_name, details))


# ---------------------------------------------------------------------------
# Structural / contract tests
# ---------------------------------------------------------------------------

def test_result_has_required_keys():
    result = _call("Chicken Sando")
    assert "exact_match" in result
    assert "candidates" in result
    assert "match_confidence" in result


def test_exact_match_item_has_required_fields():
    result = _call("Chicken Sando")
    item = result["exact_match"]
    assert item is not None
    for field in ("id", "name", "category_id", "category_name", "price", "modifier_groups"):
        assert field in item, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Exact match path
# ---------------------------------------------------------------------------

def test_exact_match_verbatim_name():
    result = _call("Chicken Sando")
    assert result["match_confidence"] == "exact"
    assert result["exact_match"]["name"] == "Chicken Sando"


def test_exact_match_case_insensitive():
    result = _call("chicken sando")
    assert result["match_confidence"] == "exact"


def test_exact_match_populates_candidates():
    result = _call("Chicken Sando")
    assert len(result["candidates"]) > 0


def test_exact_match_candidates_capped_at_three():
    result = _call("Chicken Sando")
    assert len(result["candidates"]) <= 3


# ---------------------------------------------------------------------------
# Close match path
# ---------------------------------------------------------------------------

def test_close_match_on_typo():
    result = _call("Chiken Sando")
    assert result["match_confidence"] == "close"
    assert result["candidates"][0]["name"] == "Chicken Sando"


def test_close_match_wings():
    result = _call("wings")
    assert result["match_confidence"] == "close"
    assert any("Wings" in c["name"] for c in result["candidates"])


def test_close_match_candidates_capped_at_three():
    result = _call("Chiken Sando")
    assert len(result["candidates"]) <= 3


# ---------------------------------------------------------------------------
# No match path
# ---------------------------------------------------------------------------

def test_no_match_unknown_item():
    result = _call("spaghetti bolognese")
    assert result["match_confidence"] == "none"
    assert result["exact_match"] is None
    assert result["candidates"] == []


# ---------------------------------------------------------------------------
# Modifier re-ranking (details parameter)
# ---------------------------------------------------------------------------

def test_details_reranks_candidates_by_modifier():
    result = _call("wings", details="lemon pepper")
    assert result["match_confidence"] == "close"
    assert len(result["candidates"]) >= 2
    assert "Wings" in result["candidates"][0]["name"]
    assert "Wings" in result["candidates"][1]["name"]


def test_details_with_no_modifiers_does_not_crash():
    result = _call("Can Coke", details="lemon pepper")
    assert result["match_confidence"] == "exact"
    assert result["exact_match"] is not None


def test_no_details_does_not_apply_modifier_reranking():
    result = _call("Chicken Sando")
    assert result["match_confidence"] == "exact"
    assert result["exact_match"]["name"] == "Chicken Sando"


# ---------------------------------------------------------------------------
# Modifier content verification
# ---------------------------------------------------------------------------

def test_regular_fries_has_lemon_pepper_modifier():
    result = _call("Regular Fries")
    assert result["match_confidence"] == "exact"
    item = result["exact_match"]
    all_modifier_names = [
        m["name"]
        for group in item.get("modifier_groups", [])
        for m in group.get("modifiers", [])
        if m.get("name")
    ]
    assert any("Lemon Pepper" in name for name in all_modifier_names), (
        f"Expected 'Lemon Pepper' modifier in Regular Fries, got: {all_modifier_names}"
    )


# ---------------------------------------------------------------------------
# Cache miss path
# ---------------------------------------------------------------------------

def test_cache_miss_fetches_from_clover_and_caches():
    cache_set_mock = AsyncMock()
    fetch_mock = AsyncMock(return_value=_RAW_MENU)
    with patch("src.chatbot.tools.firebaseDatabase", _make_firestore_mock()), \
         patch("src.chatbot.tools.cache_get", new_callable=AsyncMock, return_value=None), \
         patch("src.chatbot.tools.cache_set", cache_set_mock), \
         patch("src.chatbot.tools.fetch_clover_menu", fetch_mock):
        result = run(find_closest_menu_items("Chicken Sando"))

    assert result["match_confidence"] == "exact"
    fetch_mock.assert_called_once_with("tok", "test-merchant", "https://api.clover.com")
    cache_set_mock.assert_called_once()
    call_args = cache_set_mock.call_args
    assert call_args[0][0] == "menu:test-merchant"
    assert call_args[1].get("ttl") == 300 or call_args[0][2] == 300


def test_missing_credentials_returns_none_match():
    with patch("src.chatbot.tools.firebaseDatabase", _make_firestore_mock(creds=None)), \
         patch("src.chatbot.tools.cache_set", new_callable=AsyncMock), \
         patch("src.chatbot.tools.fetch_clover_menu", new_callable=AsyncMock):
        result = run(find_closest_menu_items("Chicken Sando"))

    assert result["match_confidence"] == "none"
    assert result["exact_match"] is None
    assert result["candidates"] == []
