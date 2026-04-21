"""Tests for drink alias fuzzy matching (ZAP-84).

Customers say "coke", "sprite", or "soda" but the menu lists container-prefixed
names like "Can Coke", "Glass Sprite". These tests verify that the alias
pipeline resolves the colloquial term to the canonical menu item.
"""
import asyncio

import pytest

from src.chatbot.clarification.fuzzy_matcher import FuzzyMatcher
from src.chatbot.schema import OrderItem
from src.menu import loader as menu_loader


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def drink_menu_state(monkeypatch):
    """Inject a small synthetic menu with drink items into the loader globals."""
    items = {
        "can coke": {
            "id": "DRK-COKE-CAN",
            "name": "Can Coke",
            "category_name": "Drinks",
            "price": 200,
        },
        "glass coke": {
            "id": "DRK-COKE-GLASS",
            "name": "Glass Coke",
            "category_name": "Drinks",
            "price": 300,
        },
        "can sprite": {
            "id": "DRK-SPRITE-CAN",
            "name": "Can Sprite",
            "category_name": "Drinks",
            "price": 200,
        },
        "chicken sando": {
            "id": "FOOD-CS",
            "name": "Chicken Sando",
            "category_name": "Sandwiches",
            "price": 899,
        },
    }
    monkeypatch.setattr(menu_loader, "_items_by_name", items)
    monkeypatch.setattr(
        menu_loader,
        "_items_name_set",
        {i["name"] for i in items.values()},
    )
    return items


def test_drink_aliases_include_container_stripped_names(drink_menu_state):
    aliases = _run(menu_loader.get_menu_item_name_aliases())
    alias_map: dict[str, set[str]] = {}
    for alias, canonical in aliases:
        alias_map.setdefault(alias.lower(), set()).add(canonical)

    # Container prefixes are stripped to produce colloquial aliases.
    assert "Can Coke" in alias_map.get("coke", set())
    assert "Glass Coke" in alias_map.get("coke", set())
    assert "Can Sprite" in alias_map.get("sprite", set())

    # Non-drink items should not contribute drink aliases.
    for aliases_for_term in alias_map.values():
        assert "Chicken Sando" not in aliases_for_term


def test_generic_soda_maps_to_all_drinks(drink_menu_state):
    aliases = _run(menu_loader.get_menu_item_name_aliases())
    soda_targets = {
        canonical for alias, canonical in aliases if alias.lower() == "soda"
    }
    assert soda_targets == {"Can Coke", "Glass Coke", "Can Sprite"}


def test_fuzzy_matcher_resolves_coke_alias(drink_menu_state, monkeypatch):
    # Stub the AI resolver so we don't need external calls for ambiguous cases.
    class _Resolution:
        confident = False
        canonical = None
        clarification_message = "Which Coke did you want?"

    async def _fake_resolve(*_args, **_kwargs):
        return _Resolution()

    monkeypatch.setattr(
        "src.chatbot.clarification.fuzzy_matcher.resolve_ambiguous_match",
        _fake_resolve,
    )

    matcher = FuzzyMatcher()
    menu_names = _run(menu_loader.get_menu_item_names())
    aliases = _run(menu_loader.get_menu_item_name_aliases())

    result = _run(
        matcher.match_item(
            OrderItem(name="coke", quantity=1),
            menu_names,
            latest_message="i'll take a coke",
            menu_name_aliases=aliases,
        )
    )

    # "coke" is an alias of two canonicals -> must surface both as candidates.
    assert result.status in {"confirmed", "ambiguous"}
    if result.status == "confirmed":
        assert result.canonical_name in {"Can Coke", "Glass Coke"}
    else:
        assert {"Can Coke", "Glass Coke"}.issubset(set(result.candidates))


def test_fuzzy_matcher_resolves_unique_sprite_alias(drink_menu_state):
    matcher = FuzzyMatcher()
    menu_names = _run(menu_loader.get_menu_item_names())
    aliases = _run(menu_loader.get_menu_item_name_aliases())

    result = _run(
        matcher.match_item(
            OrderItem(name="sprite", quantity=1),
            menu_names,
            latest_message="one sprite please",
            menu_name_aliases=aliases,
        )
    )

    # Only one drink resolves to "sprite" in this fixture -> exact-alias match.
    assert result.status == "confirmed"
    assert result.canonical_name == "Can Sprite"
