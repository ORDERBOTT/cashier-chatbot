# Helper functions for chatbot
from src.chatbot.constants import ConversationState, _MENU_AVAILABILITY_STALE_SECONDS, _HARDCODED_SALES_TAX_PERCENT
from src.chatbot.constants import _MENU_CACHE_VERSION
from src.chatbot.promptsv2 import _SUMMARIZE_HISTORY_SYSTEM_PROMPT
from src.cache import cache_get, cache_set
import json
import time
from src.menu.loader import build_normalized_items


def _parse_safely(value: str | None, enum_cls):
    if not value:
        return None
    try:
        return enum_cls(value.strip().lower())
    except ValueError:
        return None

def _parse_conversation_state(value: str | None) -> ConversationState | None:
    if not value:
        return None
    try:
        return ConversationState(value.strip().lower())
    except ValueError:
        return None

def _menu_cache_key(merchant_id: str) -> str:
    return f"menu:v{_MENU_CACHE_VERSION}:{merchant_id}"


def _menu_fetched_at_key(merchant_id: str) -> str:
    return f"menu:v{_MENU_CACHE_VERSION}:fetched_at:{merchant_id}"


def _session_clover_order_redis_key(session_id: str) -> str:
    """Build the Redis key used to store the Clover order id for a chat session.

    This returns the key string only. Read the order id with ``cache_get(key)``
    and write it with ``cache_set(key, order_id, ...)``.
    """
    return f"order:session:{session_id}"


def _session_status_redis_key(session_id: str) -> str:
    return f"session:{session_id}:status"


def _session_order_state_redis_key(session_id: str) -> str:
    return f"orderstate:{session_id}"


def _session_messages_redis_key(session_id: str) -> str:
    return f"message:{session_id}"


def _session_history_summary_cache_key(session_id: str, messages_covered: int) -> str:
    return f"summary:{session_id}:{messages_covered}"

def _normalize_session_history_message(raw_message: str) -> dict | None:
    payload = json.loads(raw_message)
    if not isinstance(payload, dict):
        raise ValueError("Session history entry must be a JSON object")

    role_raw = payload.get("role")
    content = payload.get("content")
    timestamp = payload.get("timestamp")

    if not isinstance(role_raw, str):
        raise ValueError("Session history entry role must be a string")
    if not isinstance(content, str):
        raise ValueError("Session history entry content must be a string")
    if not isinstance(timestamp, str):
        raise ValueError("Session history entry timestamp must be a string")

    role = {
        "user": "customer",
        "assistant": "agent",
        "customer": "customer",
        "agent": "agent",
    }.get(role_raw)
    if role is None:
        return None

    return {
        "role": role,
        "content": content,
        "timestamp": timestamp,
    }

def _parse_cached_history_summary(raw_summary: str) -> dict:
    payload = json.loads(raw_summary)
    if not isinstance(payload, dict):
        raise ValueError("Cached summary entry must be a JSON object")

    summary = payload.get("summary")
    messages_covered = payload.get("messagesCovered")
    cached_at = payload.get("cachedAt")

    if not isinstance(summary, str):
        raise ValueError("Cached summary entry summary must be a string")
    if not isinstance(messages_covered, int):
        raise ValueError("Cached summary entry messagesCovered must be an integer")
    if not isinstance(cached_at, str):
        raise ValueError("Cached summary entry cachedAt must be a string")

    return {
        "summary": summary,
        "messagesCovered": messages_covered,
        "cachedAt": cached_at,
    }

def _serialize_cached_history_summary(
    *,
    summary: str,
    messages_covered: int,
    cached_at: str,
) -> str:
    return json.dumps(
        {
            "summary": summary,
            "messagesCovered": messages_covered,
            "cachedAt": cached_at,
        }
    )

def _summary_prompt_messages(history: list[dict]) -> list[dict[str, str]]:
    llm_history: list[dict[str, str]] = []
    for message in history:
        role = message["role"]
        if role == "customer":
            llm_role = "user"
        elif role == "agent":
            llm_role = "assistant"
        else:
            continue
        llm_history.append(
            {
                "role": llm_role,
                "content": message["content"].replace("\x00", ""),
            }
        )

    return [
        {"role": "system", "content": _SUMMARIZE_HISTORY_SYSTEM_PROMPT},
        *llm_history,
        {
            "role": "user",
            "content": (
                "Summarize the earlier conversation above in one short factual paragraph."
            ),
        },
    ]


def _collect_modifier_ids_from_item(item_row: dict) -> set[str]:
    """Return all modifier IDs reachable from a single item row.

    Handles two formats:
    - Raw Clover:      item["modifierGroups"]["elements"][group]["modifiers"]["elements"][mod]["id"]
    - Normalised list: item["modifier_groups"][group]["modifiers"][mod]["id"]
    """
    ids: set[str] = set()

    for group in item_row.get("modifierGroups", {}).get("elements", []):
        for mod in group.get("modifiers", {}).get("elements", []):
            mod_id = mod.get("id")
            if mod_id:
                ids.add(mod_id)

    for group in item_row.get("modifier_groups", []):
        for mod in group.get("modifiers", []):
            mod_id = mod.get("id")
            if mod_id:
                ids.add(mod_id)

    return ids

async def _normalize_menu(raw: dict) -> dict:
    """Normalize raw Clover menu data into multiple fast-access indexes.

    Returns:
        {
            "by_id": {id: item},
            "by_name": {lower_name: [items]},
            "by_category": {category_name: [items]},
            "by_modifier_id": {modifier_id: item_id}
        }
    """
    by_id: dict = {}
    by_name: dict = {}
    by_category: dict = {}
    by_modifier_id: dict = {}

    for item in build_normalized_items(raw):
        if item.get("deleted"):
            continue

        item_id = item["id"]
        by_id[item_id] = item

        by_name.setdefault(item["name"].lower(), []).append(item)

        category_name = str(item.get("category_name", "")).strip()
        if category_name:
            by_category.setdefault(category_name, []).append(item)

        for mod_id in _collect_modifier_ids_from_item(item):
            by_modifier_id[mod_id] = item_id

    return {
        "by_id": by_id,
        "by_name": by_name,
        "by_category": by_category,
        "by_modifier_id": by_modifier_id,
    }

async def _persist_menu_items_cache(merchant_id: str, items_by_name: dict) -> None:
    await cache_set(_menu_cache_key(merchant_id), json.dumps(items_by_name), ttl=300)
    await cache_set(_menu_fetched_at_key(merchant_id), str(int(time.time())), ttl=300)


async def _menu_cache_age_seconds(merchant_id: str) -> float | None:
    raw = await cache_get(_menu_fetched_at_key(merchant_id))
    if not raw:
        return None
    try:
        ts = int(raw)
    except ValueError:
        return None
    return max(0.0, time.time() - ts)


def _menu_snapshot_considered_fresh(age_seconds: float | None) -> bool:
    if age_seconds is None:
        return False
    return age_seconds < _MENU_AVAILABILITY_STALE_SECONDS

def _availability_result(
    *,
    available: bool,
    item_id: str,
    item_name: str,
    unavailable_reason: str | None,
) -> dict:
    return {
        "Available": available,
        "itemId": item_id,
        "itemName": item_name,
        "unavailableReason": unavailable_reason,
    }


def _item_not_found_result(item_id: str) -> dict:
    return _availability_result(
        available=False,
        item_id=item_id,
        item_name="",
        unavailable_reason="item not found on menu",
    )


def _normalize_order_line_items(order_data: dict) -> list[dict]:
    raw_line_items = order_data.get("lineItems") or []
    if isinstance(raw_line_items, dict):
        return raw_line_items.get("elements", [])
    if isinstance(raw_line_items, list):
        return raw_line_items
    return []


def _line_item_quantity(line_item: dict) -> int:
    return max(1, (line_item.get("unitQty") or 1000) // 1000)


def _extract_line_item_modification_records(line_item: dict) -> list[dict]:
    records: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for key in ("modifications", "modifiers"):
        raw = line_item.get(key) or []
        if isinstance(raw, dict):
            rows = raw.get("elements", [])
        elif isinstance(raw, list):
            rows = raw
        else:
            rows = []

        for row in rows:
            modifier = row.get("modifier") or {}
            modifier_id = modifier.get("id") or row.get("modifierId")
            modification_id = row.get("id") or row.get("modificationId")
            if not modifier_id or not modification_id:
                continue
            fingerprint = (modification_id, modifier_id)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            records.append(
                {
                    "modification_id": modification_id,
                    "modifier_id": modifier_id,
                    "modifier_name": modifier.get("name") or row.get("name") or "",
                    "price": row.get("amount")
                    or modifier.get("price")
                    or row.get("price")
                    or 0,
                }
            )

    return records

def _describe_update_changes(
    *, removed: int, added: int, note_action: str | None
) -> str:
    parts: list[str] = []
    if removed:
        parts.append(
            f"removed {removed} modifier"
            if removed == 1
            else f"removed {removed} modifiers"
        )
    if added:
        parts.append(
            f"added {added} modifier" if added == 1 else f"added {added} modifiers"
        )
    if note_action:
        parts.append(note_action)
    if not parts:
        return "no changes applied"
    return ", ".join(parts)


def _priced_line_item(line_item: dict) -> dict:
    quantity = _line_item_quantity(line_item)
    modifier_prices = [
        {
            "modifierId": record["modifier_id"],
            "name": record["modifier_name"],
            "price": record["price"],
        }
        for record in _extract_line_item_modification_records(line_item)
    ]

    base_line_price = line_item.get("price") or 0
    explicit_unit_price = line_item.get("unitPrice")
    item_unit_price = (line_item.get("item") or {}).get("price")
    if explicit_unit_price is not None:
        unit_price = explicit_unit_price
    elif item_unit_price is not None:
        unit_price = item_unit_price
    elif quantity > 1 and base_line_price > 0 and base_line_price % quantity == 0:
        unit_price = base_line_price // quantity
    else:
        unit_price = base_line_price

    modifier_total = sum(modifier["price"] for modifier in modifier_prices)
    line_total = line_item.get("priceWithModifiers")
    if line_total is None:
        line_total = base_line_price + modifier_total

    return {
        "lineItemId": line_item.get("id", ""),
        "name": line_item.get("name", ""),
        "quantity": quantity,
        "unitPrice": unit_price,
        "modifierPrices": modifier_prices,
        "lineTotal": line_total,
    }


def _sum_line_item_totals(line_items: list[dict]) -> int:
    return sum(int(line_item.get("lineTotal") or 0) for line_item in line_items)


def _hardcoded_sales_tax(subtotal: int) -> int:
    return ((subtotal * _HARDCODED_SALES_TAX_PERCENT) + 50) // 100


def _pricing_breakdown_from_order(order_data: dict) -> dict:
    line_items = [
        _priced_line_item(li) for li in _normalize_order_line_items(order_data)
    ]
    subtotal = order_data.get("subtotal")
    if subtotal is None:
        subtotal = _sum_line_item_totals(line_items)

    tax = _hardcoded_sales_tax(subtotal)
    total = subtotal + tax

    return {
        "lineItems": line_items,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "currency": order_data.get("currency") or "USD",
    }