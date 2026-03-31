import json
from pathlib import Path

_MENU_FILE = Path(__file__).parent.parent.parent / "tests" / "smash_n_wings_menu.json"

with _MENU_FILE.open() as f:
    _MENU_DATA: dict = json.load(f)


def get_menu_item_names() -> list[str]:
    return [
        item["name"]
        for category in _MENU_DATA.get("menu", [])
        for item in category.get("items", [])
    ]


def get_menu_context() -> str:
    lines: list[str] = []
    for category in _MENU_DATA.get("menu", []):
        lines.append(f"\nCategory: {category['category']}")
        for item in category.get("items", []):
            price = item["base_price"]
            price_str = f"${price:.2f}" if price is not None else "price varies"
            lines.append(f"  - {item['name']} ({price_str})")
            if item.get("description"):
                lines.append(f"    {item['description']}")
            for mod_name, mod in item.get("modifications", {}).items():
                required = "required" if mod.get("required") else "optional"
                opts = ", ".join(
                    f"{o['name']}" + (f" +${o['price']:.2f}" if o["price"] else "")
                    for o in mod.get("options", [])
                )
                lines.append(f"    [{required}] {mod_name}: {opts}")
    return "\n".join(lines).strip()
