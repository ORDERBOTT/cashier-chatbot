import asyncio

from src.chatbot.tools import _normalize_menu
from src.menu import clover_client
from src.menu.loader import build_items_by_name

_RAW_REFERENCE_ONLY_MENU = {
    "modifierGroups": {
        "elements": [
            {
                "id": "grp-cheese",
                "name": "Cheese",
                "modifierIds": "mod-cheddar,mod-swiss",
            }
        ]
    },
    "modifiers": {
        "elements": [
            {"id": "mod-cheddar", "name": "Cheddar", "price": 100},
            {"id": "mod-swiss", "name": "Swiss", "price": 150},
        ]
    },
    "elements": [
        {
            "id": "item-burger",
            "name": "Classic Burger",
            "price": 1099,
            "categories": {"elements": [{"id": "cat-burgers", "name": "Burgers"}]},
            "modifierGroups": {"elements": [{"id": "grp-cheese"}]},
        }
    ],
}


def test_build_items_by_name_resolves_modifier_ids_to_real_modifier_names():
    items = build_items_by_name(_RAW_REFERENCE_ONLY_MENU)

    burger = items["classic burger"]
    assert burger["modifier_groups"] == [
        {
            "id": "grp-cheese",
            "name": "Cheese",
            "min_required": 0,
            "max_allowed": 0,
            "modifiers": [
                {"id": "mod-cheddar", "name": "Cheddar", "price": 100},
                {"id": "mod-swiss", "name": "Swiss", "price": 150},
            ],
        }
    ]


def test_tool_normalize_menu_indexes_resolved_modifier_names():
    normalized = asyncio.run(_normalize_menu(_RAW_REFERENCE_ONLY_MENU))

    burger = normalized["by_id"]["item-burger"]
    assert burger["modifier_groups"][0]["modifiers"] == [
        {"id": "mod-cheddar", "name": "Cheddar", "price": 100},
        {"id": "mod-swiss", "name": "Swiss", "price": 150},
    ]
    assert normalized["by_modifier_id"]["mod-cheddar"] == "item-burger"
    assert normalized["by_modifier_id"]["mod-swiss"] == "item-burger"


class _FakeResponse:
    status_code = 200

    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class _FakeAsyncClient:
    def __init__(self, responses: list[dict]):
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url, params=None, headers=None):  # noqa: ANN001
        return _FakeResponse(self._responses.pop(0))


def test_fetch_clover_menu_keeps_top_level_modifier_groups_across_pages(monkeypatch):
    fake_client = _FakeAsyncClient(
        [
            {
                "elements": [
                    {"id": "item-1", "name": "Burger One"},
                    {"id": "item-2", "name": "Burger Two"},
                ],
                "modifierGroups": {
                    "elements": [
                        {
                            "id": "grp-cheese",
                            "name": "Cheese",
                            "modifiers": {"elements": [{"id": "mod-cheddar", "name": "Cheddar", "price": 100}]},
                        }
                    ]
                },
            },
            {
                "elements": [{"id": "item-3", "name": "Burger Three"}],
                "modifierGroups": {
                    "elements": [
                        {
                            "id": "grp-temp",
                            "name": "Cook Temp",
                            "modifiers": {"elements": [{"id": "mod-medium", "name": "Medium", "price": 0}]},
                        }
                    ]
                },
            },
        ]
    )
    monkeypatch.setattr(clover_client.httpx, "AsyncClient", lambda: fake_client)

    raw = asyncio.run(
        clover_client.fetch_clover_menu("token", "merchant-1", "https://api.clover.com", page_size=2)
    )

    assert [item["id"] for item in raw["elements"]] == ["item-1", "item-2", "item-3"]
    assert sorted(group["id"] for group in raw["modifierGroups"]["elements"]) == ["grp-cheese", "grp-temp"]


def test_fetch_clover_modifiers_keeps_all_pages(monkeypatch):
    fake_client = _FakeAsyncClient(
        [
            {
                "elements": [
                    {"id": "mod-1", "name": "Mild", "price": 0},
                    {"id": "mod-2", "name": "Spicy", "price": 0},
                ]
            },
            {
                "elements": [
                    {"id": "mod-3", "name": "Plain Fries", "price": 350},
                ]
            },
        ]
    )
    monkeypatch.setattr(clover_client.httpx, "AsyncClient", lambda: fake_client)

    raw = asyncio.run(
        clover_client.fetch_clover_modifiers("token", "merchant-1", "https://api.clover.com", page_size=2)
    )

    assert [modifier["name"] for modifier in raw["elements"]] == ["Mild", "Spicy", "Plain Fries"]
