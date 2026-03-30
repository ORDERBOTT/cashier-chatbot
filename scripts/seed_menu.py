#!/usr/bin/env python3
"""
Seed menu data into Redis for a given user.

Usage:
    python scripts/seed_menu.py
    python scripts/seed_menu.py --menu-file test_menu.json
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import redis.asyncio as aioredis
from src.config import settings

# Default menu file for local testing. This matches the repo's large test menu dataset.
DEFAULT_MENU_FILE = Path("test_menu.json")

USER_ID = "1"
MENU_CONTEXT_KEY = f"menu_context:{USER_ID}"
MENU_ITEM_NAMES_KEY = f"menu_item_names:{USER_ID}"
RESTAURANT_NAME_LOCATION_KEY = f"restaurant_name_location:{USER_ID}"
RESTAURANT_NAME_LOCATION_STRING = "The Burger Joint, 123 Main St, Anytown, USA"


def _load_menu_payload(menu_path: Path) -> dict:
    """
    Load menu JSON robustly.
    Supports:
      1) normal JSON object: {"menu": [...]}
      2) fragment style file: "menu": [...]
    """
    raw = menu_path.read_text(encoding="utf-8").strip()
    if not raw:
        raise SystemExit(f"Menu file is empty: {menu_path}")

    decoder = json.JSONDecoder()

    def _decode_prefix(text: str):
        # Parse the first valid JSON value and allow trailing junk/text after it.
        # This makes seeding resilient to accidental extra pasted content.
        idx = 0
        while idx < len(text) and text[idx].isspace():
            idx += 1
        obj, _end = decoder.raw_decode(text, idx)
        return obj

    try:
        payload = _decode_prefix(raw)
    except json.JSONDecodeError:
        # Support fragment style: "menu": [...]
        wrapped = "{\n" + raw + "\n}"
        try:
            payload = _decode_prefix(wrapped)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid menu JSON in {menu_path}: {exc}") from exc

    if isinstance(payload, list):
        # Support files that are just an array of categories
        return {"menu": payload}

    if not isinstance(payload, dict):
        # Last fallback for fragment-style content like: "menu": [ ... ]
        marker = '"menu"'
        marker_idx = raw.find(marker)
        if marker_idx != -1:
            colon_idx = raw.find(":", marker_idx + len(marker))
            if colon_idx != -1:
                arr_src = raw[colon_idx + 1 :].strip()
                try:
                    arr = _decode_prefix(arr_src)
                    if isinstance(arr, list):
                        return {"menu": arr}
                except json.JSONDecodeError:
                    pass
        raise SystemExit(f"Menu JSON root must be an object in {menu_path}")

    return payload


def _collect_option_names_from_modifications(modifications: object) -> list[str]:
    """Flat names from all modification option lists (for fuzzy matching combo sides, sauces, etc.)."""
    names: list[str] = []
    if not isinstance(modifications, dict):
        return names
    for mod in modifications.values():
        if not isinstance(mod, dict):
            continue
        for opt in mod.get("options") or []:
            if not isinstance(opt, dict):
                continue
            n = (opt.get("name") or "").strip()
            if n:
                names.append(n)
    return names


def _build_menu_context_from_json(menu_payload: dict) -> tuple[str, list[str]]:
    """
    Convert `test_menu.json` style payload to:
      - a single plain-text context string for menu Q&A
      - a list of canonical item names for fuzzy matching
    """
    categories = menu_payload.get("menu") or []
    lines: list[str] = []
    item_names: list[str] = []

    for cat in categories:
        cat_name = (cat.get("category") or "").strip() or "Uncategorized"
        cat_desc = (cat.get("description") or "").strip()
        items = cat.get("items") or []

        lines.append(f"## {cat_name}")
        if cat_desc:
            lines.append(cat_desc)
        lines.append("")

        for item in items:
            name = (item.get("name") or "").strip()
            if not name:
                continue
            item_names.append(name)
            item_names.extend(_collect_option_names_from_modifications(item.get("modifications")))

            desc = (item.get("description") or "").strip()
            base_price = item.get("base_price", None)
            price_note = (item.get("price_note") or "").strip()
            modifications = item.get("modifications") or {}

            lines.append(f"=== {name} ===")
            if base_price is not None:
                try:
                    lines.append(f"Price: ${float(base_price):.2f}")
                except (TypeError, ValueError):
                    lines.append(f"Price: {base_price}")
            elif price_note:
                lines.append(f"Price: {price_note}")
            if desc:
                lines.append(f"Description: {desc}")

            if modifications:
                lines.append("Modifications:")
                for mod_name, mod in modifications.items():
                    mod_name = str(mod_name).strip()
                    if not mod_name:
                        continue
                    required = bool(mod.get("required", False))
                    mod_type = (mod.get("type") or "").strip()
                    select = mod.get("select", None)
                    max_select = mod.get("max_select", None)
                    opts = mod.get("options") or []

                    meta_bits: list[str] = []
                    meta_bits.append("required" if required else "optional")
                    if mod_type:
                        meta_bits.append(mod_type)
                    if select is not None:
                        meta_bits.append(f"select {select}")
                    if max_select is not None:
                        meta_bits.append(f"max {max_select}")

                    lines.append(f"- {mod_name} ({', '.join(meta_bits)})")
                    for opt in opts:
                        opt_name = (opt.get("name") or "").strip()
                        if not opt_name:
                            continue
                        opt_price = opt.get("price", None)
                        if opt_price is None:
                            lines.append(f"  - {opt_name}")
                        else:
                            try:
                                lines.append(f"  - {opt_name} (+${float(opt_price):.2f})")
                            except (TypeError, ValueError):
                                lines.append(f"  - {opt_name} (+{opt_price})")
            else:
                lines.append("Modifications: None")

            lines.append("")

        lines.append("")

    context = "\n".join(lines).strip()
    # Deduplicate while preserving order
    seen: set[str] = set()
    uniq_names: list[str] = []
    for n in item_names:
        if n not in seen:
            seen.add(n)
            uniq_names.append(n)
    return context, uniq_names


async def main():
    menu_file = DEFAULT_MENU_FILE
    if "--menu-file" in sys.argv:
        try:
            idx = sys.argv.index("--menu-file")
            menu_file = Path(sys.argv[idx + 1])
        except Exception:
            raise SystemExit("Usage: python scripts/seed_menu.py [--menu-file <path>]")

    menu_path = (Path(__file__).resolve().parent.parent / menu_file).resolve() if not menu_file.is_absolute() else menu_file
    if not menu_path.exists():
        raise SystemExit(f"Menu file not found: {menu_path}")

    menu_payload = _load_menu_payload(menu_path)
    menu_context, item_names = _build_menu_context_from_json(menu_payload)

    client = aioredis.from_url(str(settings.REDIS_URL), decode_responses=True)

    try:
        await client.ping()
        print("Connected to Redis.")

        item_names_string = ", ".join(item_names)

        await client.set(MENU_CONTEXT_KEY, menu_context)
        print(f"Saved: {MENU_CONTEXT_KEY}")

        await client.set(MENU_ITEM_NAMES_KEY, item_names_string)
        print(f"Saved: {MENU_ITEM_NAMES_KEY}")

        await client.set(RESTAURANT_NAME_LOCATION_KEY, RESTAURANT_NAME_LOCATION_STRING)
        print(f"Saved: {RESTAURANT_NAME_LOCATION_KEY}")

        print(f"\nDone. {len(item_names)} items seeded for user '{USER_ID}'.")
        print(f"Menu source: {menu_path}")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
