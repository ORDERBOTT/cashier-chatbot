import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.chatbot import tools as tools_mod
from src.chatbot.internal_schemas import (
    ClosestModifierReference,
    ModifierAddonCheckResult,
)
from src.chatbot.tools import checkIfModifierOrAddOn

_FAKE_SETTINGS = SimpleNamespace(
    MERCHANT_ID="merchant-1",
    CLOVER_APP_ID=None,
    CLOVER_API_BASE_URL="https://apisandbox.dev.clover.com",
)

_FAKE_CREDS = {
    "merchant_id": "merchant-1",
    "token": "fake-token",
    "base_url": "https://apisandbox.dev.clover.com",
}

_RAW_BURGER = {
    "id": "item-burger",
    "name": "Classic Burger",
    "price": 1099,
    "modifierGroups": {
        "elements": [
            {
                "id": "grp-toppings",
                "name": "Toppings",
                "minRequired": 0,
                "maxAllowed": 4,
                "modifiers": {
                    "elements": [
                        {"id": "mod-onions", "name": "Onions", "price": 0},
                        {"id": "mod-pickles", "name": "Pickles", "price": 0},
                    ]
                },
            },
            {
                "id": "grp-protein",
                "name": "Patty",
                "minRequired": 1,
                "maxAllowed": 1,
                "modifiers": {
                    "elements": [
                        {"id": "mod-patty", "name": "Patty", "price": 0},
                    ]
                },
            },
        ]
    },
}

_FAKE_MENU = {
    "by_id": {
        "item-burger": _RAW_BURGER,
    },
    "by_name": {},
    "by_category": {},
    "by_modifier_id": {
        "mod-onions": "item-burger",
        "mod-pickles": "item-burger",
        "mod-patty": "item-burger",
    },
}


def _run(coro):
    return asyncio.run(coro)


def _call(
    item_id: str,
    requested_modification: str,
    *,
    merchant_id: str = "merchant-1",
    menu: dict | None = None,
) -> dict:
    with (
        patch.object(tools_mod, "settings", _FAKE_SETTINGS),
        patch(
            "src.chatbot.tools.prepare_clover_data",
            new_callable=AsyncMock,
            return_value=_FAKE_CREDS,
        ),
        patch(
            "src.chatbot.tools._menu_items_cached_or_fresh",
            new_callable=AsyncMock,
            return_value=menu or _FAKE_MENU,
        ),
    ):
        return _run(
            checkIfModifierOrAddOn(item_id, merchant_id, requested_modification)
        )


def test_check_modifier_or_addon_returns_quantity_variation_with_server_note(
    monkeypatch,
):
    async def fake_classify_modifier_or_addon_request(
        *,
        item_name: str,
        requested_modification: str,
        candidate_modifiers: list[dict],
        modifier_groups: list[dict],
    ) -> ModifierAddonCheckResult:
        assert item_name == "Classic Burger"
        assert requested_modification == "extra onions"
        assert candidate_modifiers[0]["modifierId"] == "mod-onions"
        assert modifier_groups[0]["name"] == "Toppings"
        return ModifierAddonCheckResult(
            isModifierOrAddon=True,
            classification="quantity_variation",
            closestModifier=ClosestModifierReference(
                modifierId="mod-onions", name="Onions"
            ),
            suggestedNote="ignore this",
        )

    monkeypatch.setattr(
        tools_mod,
        "classify_modifier_or_addon_request",
        fake_classify_modifier_or_addon_request,
    )

    result = _call("item-burger", "extra onions")

    assert result == {
        "isAddon": True,
        "classification": "quantity_variation",
        "closestModifier": {
            "modifierId": "mod-onions",
            "name": "Onions",
        },
        "suggestedNote": "Onions: extra onions",
    }


def test_check_modifier_or_addon_supports_cooking_preference_candidates(monkeypatch):
    async def fake_classify_modifier_or_addon_request(
        *,
        item_name: str,
        requested_modification: str,
        candidate_modifiers: list[dict],
        modifier_groups: list[dict],
    ) -> ModifierAddonCheckResult:
        assert item_name == "Classic Burger"
        assert requested_modification == "medium rare"
        assert any(
            candidate["modifierId"] == "mod-patty" for candidate in candidate_modifiers
        )
        assert any(group["name"] == "Patty" for group in modifier_groups)
        return ModifierAddonCheckResult(
            isModifierOrAddon=True,
            classification="cooking_preference",
            closestModifier=ClosestModifierReference(
                modifierId="mod-patty", name="Patty"
            ),
            suggestedNote=None,
        )

    monkeypatch.setattr(
        tools_mod,
        "classify_modifier_or_addon_request",
        fake_classify_modifier_or_addon_request,
    )

    result = _call("item-burger", "medium rare")

    assert result == {
        "isAddon": True,
        "classification": "cooking_preference",
        "closestModifier": {
            "modifierId": "mod-patty",
            "name": "Patty",
        },
        "suggestedNote": "Patty: medium rare",
    }


def test_check_modifier_or_addon_without_candidate_skips_ai(monkeypatch):
    async def fail_if_called(**kwargs):
        raise AssertionError("AI should not be called when there is no candidate")

    monkeypatch.setattr(tools_mod, "classify_modifier_or_addon_request", fail_if_called)

    result = _call("item-burger", "birthday candle")

    assert result == {
        "isAddon": False,
        "classification": "not_addon",
        "closestModifier": None,
        "suggestedNote": None,
    }


def test_check_modifier_or_addon_merchant_mismatch_fails_closed(monkeypatch):
    async def fail_if_called(**kwargs):
        raise AssertionError("AI should not be called on merchant mismatch")

    monkeypatch.setattr(tools_mod, "classify_modifier_or_addon_request", fail_if_called)

    result = _call("item-burger", "extra onions", merchant_id="wrong-merchant")

    assert result == {
        "isAddon": False,
        "classification": "not_addon",
        "closestModifier": None,
        "suggestedNote": None,
    }


def test_check_modifier_or_addon_unknown_returned_modifier_downgrades_to_not_addon(
    monkeypatch,
):
    async def fake_classify_modifier_or_addon_request(
        **kwargs,
    ) -> ModifierAddonCheckResult:
        return ModifierAddonCheckResult(
            isModifierOrAddon=True,
            classification="ingredient_variation",
            closestModifier=ClosestModifierReference(
                modifierId="mod-unknown", name="Mystery"
            ),
            suggestedNote="mystery",
        )

    monkeypatch.setattr(
        tools_mod,
        "classify_modifier_or_addon_request",
        fake_classify_modifier_or_addon_request,
    )

    result = _call("item-burger", "no mystery")

    assert result == {
        "isAddon": False,
        "classification": "not_addon",
        "closestModifier": None,
        "suggestedNote": None,
    }


def test_check_modifier_or_addon_missing_item_fails_closed(monkeypatch):
    async def fail_if_called(**kwargs):
        raise AssertionError("AI should not be called when the item is missing")

    monkeypatch.setattr(tools_mod, "classify_modifier_or_addon_request", fail_if_called)

    result = _call("item-missing", "extra onions")

    assert result == {
        "isAddon": False,
        "classification": "not_addon",
        "closestModifier": None,
        "suggestedNote": None,
    }
