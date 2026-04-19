import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.chatbot import tools as tools_mod
from src.chatbot.tools import _normalize_menu, validateModifications

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
                "id": "grp-cheese",
                "name": "Cheese",
                "minRequired": 0,
                "maxAllowed": 2,
                "modifiers": {
                    "elements": [
                        {"id": "mod-cheddar", "name": "Cheddar", "price": 100},
                        {"id": "mod-swiss", "name": "Swiss", "price": 150},
                    ]
                },
            },
            {
                "id": "grp-temp",
                "name": "Cook Temp",
                "minRequired": 1,
                "maxAllowed": 1,
                "modifiers": {
                    "elements": [
                        {"id": "mod-medium", "name": "Medium", "price": 0},
                        {"id": "mod-well", "name": "Well Done", "price": 0},
                    ]
                },
            },
        ]
    },
}

_RAW_WINGS = {
    "id": "item-wings",
    "name": "Boneless Wings",
    "price": 1299,
    "modifierGroups": {
        "elements": [
            {
                "id": "grp-sauce",
                "name": "Sauce",
                "minRequired": 2,
                "maxAllowed": 3,
                "modifiers": {
                    "elements": [
                        {"id": "mod-bbq", "name": "BBQ", "price": 0},
                        {"id": "mod-ranch", "name": "Ranch", "price": 0},
                        {"id": "mod-hot", "name": "Hot", "price": 0},
                    ]
                },
            }
        ]
    },
}

_RAW_DRINK = {
    "id": "item-drink",
    "name": "Can Coke",
    "price": 250,
    "modifierGroups": {"elements": []},
}

_FAKE_MENU = {
    "by_id": {
        "item-burger": _RAW_BURGER,
        "item-wings": _RAW_WINGS,
        "item-drink": _RAW_DRINK,
    },
    "by_name": {},
    "by_category": {},
    "by_modifier_id": {
        "mod-cheddar": "item-burger",
        "mod-swiss": "item-burger",
        "mod-medium": "item-burger",
        "mod-well": "item-burger",
        "mod-bbq": "item-wings",
        "mod-ranch": "item-wings",
        "mod-hot": "item-wings",
    },
}

_REFERENCE_ONLY_RAW_MENU = {
    "modifierGroups": {
        "elements": [
            {
                "id": "grp-cheese",
                "name": "Cheese",
                "modifierIds": "mod-cheddar,mod-swiss",
            }
        ]
    },
    "elements": [
        {
            "id": "item-burger",
            "name": "Classic Burger",
            "price": 1099,
            "categories": {"elements": [{"id": "cat-burgers", "name": "Burgers"}]},
            "modifierGroups": {"elements": [{"id": "grp-cheese"}]},
        },
        {
            "id": "item-helper",
            "name": "Helper Burger",
            "price": 1199,
            "categories": {"elements": [{"id": "cat-burgers", "name": "Burgers"}]},
            "modifierGroups": {
                "elements": [
                    {
                        "id": "grp-cheese",
                        "name": "Cheese",
                        "modifiers": {
                            "elements": [
                                {"id": "mod-cheddar", "name": "Cheddar", "price": 100},
                                {"id": "mod-swiss", "name": "Swiss", "price": 150},
                            ]
                        },
                    }
                ]
            },
        },
    ],
}

_LIVE_STYLE_CHICKEN_SANDO_MENU = {
    "modifierGroups": {
        "elements": [
            {
                "id": "5D40H2RY6M9NR",
                "name": "Chicken Sando Seasoning",
                "minRequired": 1,
                "maxAllowed": 1,
                "modifierIds": "9YJW5D7V07QPC,BW3A5ARZGTHZ8,4XCRSWBJK0C5Y,43X18SGQV39QE",
            },
            {
                "id": "1VX2C2BPW7W14",
                "name": "Make It a Combo With Fries",
                "minRequired": 1,
                "maxAllowed": 1,
                "modifierIds": "3MWZTR3VCY4X2,39QG6VKJXD0WG,Z5D211K707CFJ,SGSFVN0DM1DZ4,6YKV008R95M5J",
            },
        ]
    },
    "modifiers": {
        "elements": [
            {"id": "9YJW5D7V07QPC", "name": "Naked", "price": 0},
            {"id": "BW3A5ARZGTHZ8", "name": "Mild", "price": 0},
            {"id": "4XCRSWBJK0C5Y", "name": "Spicy", "price": 0},
            {"id": "43X18SGQV39QE", "name": "Extra Spicy", "price": 0},
            {"id": "3MWZTR3VCY4X2", "name": "Plain Fries", "price": 350},
            {"id": "39QG6VKJXD0WG", "name": "Lemon Pepper Fries", "price": 350},
            {"id": "Z5D211K707CFJ", "name": "Cajun Fries", "price": 350},
            {"id": "SGSFVN0DM1DZ4", "name": "Nashville Seasoning Fries", "price": 350},
            {"id": "6YKV008R95M5J", "name": "No Mods", "price": 0},
        ]
    },
    "elements": [
        {
            "id": "6STZFD12K1VBC",
            "name": "Chicken Sando",
            "price": 899,
            "categories": {"elements": [{"id": "cat-1", "name": "Sandos"}]},
            "modifierGroups": {
                "elements": [
                    {"id": "5D40H2RY6M9NR"},
                    {"id": "1VX2C2BPW7W14"},
                ]
            },
        }
    ],
}


def _run(coro):
    return asyncio.run(coro)


def _call(
    item_id: str,
    requested: list[str],
    *,
    merchant_id: str = "merchant-1",
    creds: dict | None = None,
    menu: dict | None = None,
) -> dict:
    with (
        patch.object(tools_mod, "settings", _FAKE_SETTINGS),
        patch("src.chatbot.tools.prepare_clover_data", new_callable=AsyncMock, return_value=creds or _FAKE_CREDS),
        patch("src.chatbot.tools._menu_items_cached_or_fresh", new_callable=AsyncMock, return_value=menu or _FAKE_MENU),
    ):
        return _run(validateModifications(item_id, merchant_id, requested))


def test_validate_modifications_exact_and_fuzzy_matches_with_price_adjustments():
    result = _call("item-burger", ["chedar", "medium"])

    assert result["invalid"] == []
    assert result["requireChoice"] == []
    assert result["allValid"] is True
    assert result["valid"] == [
        {
            "requested": "chedar",
            "modifierId": "mod-cheddar",
            "name": "Cheddar",
            "price": 100,
            "groupId": "grp-cheese",
            "groupName": "Cheese",
        },
        {
            "requested": "medium",
            "modifierId": "mod-medium",
            "name": "Medium",
            "price": 0,
            "groupId": "grp-temp",
            "groupName": "Cook Temp",
        },
    ]


def test_validate_modifications_unmatched_requests_become_invalid():
    result = _call("item-burger", ["ranch", "medium"])

    assert result["allValid"] is False
    assert result["invalid"] == ["ranch"]
    assert [row["modifierId"] for row in result["valid"]] == ["mod-medium"]
    assert result["requireChoice"] == []


def test_validate_modifications_reports_missing_required_groups():
    result = _call("item-burger", ["swiss"])

    assert result["allValid"] is False
    assert result["invalid"] == []
    assert [row["modifierId"] for row in result["valid"]] == ["mod-swiss"]
    assert result["requireChoice"] == [
        {
            "id": "grp-temp",
            "name": "Cook Temp",
            "minRequired": 1,
            "maxAllowed": 1,
            "remainingRequired": 1,
            "modifiers": [
                {"id": "mod-medium", "name": "Medium", "price": 0},
                {"id": "mod-well", "name": "Well Done", "price": 0},
            ],
        }
    ]


def test_validate_modifications_reports_partially_satisfied_required_groups():
    result = _call("item-wings", ["ranch"])

    assert result["allValid"] is False
    assert result["invalid"] == []
    assert result["valid"] == [
        {
            "requested": "ranch",
            "modifierId": "mod-ranch",
            "name": "Ranch",
            "price": 0,
            "groupId": "grp-sauce",
            "groupName": "Sauce",
        }
    ]
    assert result["requireChoice"] == [
        {
            "id": "grp-sauce",
            "name": "Sauce",
            "minRequired": 2,
            "maxAllowed": 3,
            "remainingRequired": 1,
            "modifiers": [
                {"id": "mod-bbq", "name": "BBQ", "price": 0},
                {"id": "mod-ranch", "name": "Ranch", "price": 0},
                {"id": "mod-hot", "name": "Hot", "price": 0},
            ],
        }
    ]


def test_validate_modifications_dedupes_duplicate_requested_matches():
    result = _call("item-burger", ["swiss", "swiss", "medium"])

    assert result["allValid"] is True
    assert result["invalid"] == []
    assert [row["modifierId"] for row in result["valid"]] == ["mod-swiss", "mod-medium"]


def test_validate_modifications_item_with_no_modifiers_marks_requests_invalid():
    result = _call("item-drink", ["no ice"])

    assert result == {
        "valid": [],
        "invalid": ["no ice"],
        "requireChoice": [],
        "allValid": False,
    }


def test_validate_modifications_merchant_mismatch_fails_closed():
    result = _call("item-burger", ["medium"], merchant_id="wrong-merchant")

    assert result == {
        "valid": [],
        "invalid": ["medium"],
        "requireChoice": [],
        "allValid": False,
    }


def test_validate_modifications_missing_item_fails_closed():
    result = _call("item-missing", ["medium"])

    assert result == {
        "valid": [],
        "invalid": ["medium"],
        "requireChoice": [],
        "allValid": False,
    }


def test_validate_modifications_uses_resolved_modifier_names_from_normalized_menu():
    menu = _run(_normalize_menu(_REFERENCE_ONLY_RAW_MENU))

    result = _call("item-burger", ["chedar"], menu=menu)

    assert result["invalid"] == []
    assert result["allValid"] is True
    assert result["valid"] == [
        {
            "requested": "chedar",
            "modifierId": "mod-cheddar",
            "name": "Cheddar",
            "price": 100,
            "groupId": "grp-cheese",
            "groupName": "Cheese",
        }
    ]


def test_validate_modifications_matches_live_style_modifier_ids_using_top_level_modifier_catalog():
    menu = _run(_normalize_menu(_LIVE_STYLE_CHICKEN_SANDO_MENU))

    result = _call("6STZFD12K1VBC", ["mild", "plain fries"], menu=menu)

    assert result == {
        "valid": [
            {
                "requested": "mild",
                "modifierId": "BW3A5ARZGTHZ8",
                "name": "Mild",
                "price": 0,
                "groupId": "5D40H2RY6M9NR",
                "groupName": "Chicken Sando Seasoning",
            },
            {
                "requested": "plain fries",
                "modifierId": "3MWZTR3VCY4X2",
                "name": "Plain Fries",
                "price": 350,
                "groupId": "1VX2C2BPW7W14",
                "groupName": "Make It a Combo With Fries",
            },
        ],
        "invalid": [],
        "requireChoice": [],
        "allValid": True,
    }
