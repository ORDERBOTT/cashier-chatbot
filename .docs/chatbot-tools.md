# Chatbot Tools

## Overview
Agent tool functions called directly by the AI agent. All in `src/chatbot/tools.py`. All return plain `dict` (no Pydantic).

## Key Files
- `src/chatbot/tools.py` — all tool implementations
- `src/chatbot/orchestrator.py` — JSON schema + tool descriptors passed to the LLM
- `src/chatbot/utils.py` — shared helpers (`_extract_line_item_modification_records`, `_normalize_order_line_items`, etc.)

## removeItemFromOrder

### How It Works
Clover stores each ordered unit as a **separate line item** with the same name. So "3x Chicken Sando" = three distinct line items each named "Chicken Sando".

Target resolution priority:
1. `target["orderPosition"]` → deletes that specific 1-indexed line item; `removedCount=1`, `lineItemId=<id>`
2. `target["itemName"]` only → fuzzy-matches name, then **deletes ALL** line items sharing that best-matched name; `removedCount=N`, `lineItemId=None`
3. `target["itemName"]` + `target["details"]` → fuzzy-matches name first, then scores `details` against each matching item's modifier names via `_extract_line_item_modification_records`; if a modifier scores >= `NOT_FOUND_THRESHOLD` (50), only that specific item is deleted (`removedCount=1`, `lineItemId=<id>`); otherwise falls back to remove-all

### Return Fields Added (2026-04-22)
- `removedCount` (int) — total line items deleted
- `lineItemId` (str | None) — the specific Clover line item id when one specific item was deleted; None for bulk removes

### Orchestrator Schema
`_REMOVE_ITEM_FROM_ORDER_PARAMETERS_JSON_SCHEMA` in `orchestrator.py` (~line 224) includes `target.details` as an optional string with description telling the LLM when to omit vs. include it.

## 2026-04-22 - REMOVE_ITEM quantity disambiguation

**Problem:** When a customer said "remove 2 chicken sandos" with 3 in the order, the execution agent was calling `removeItemFromOrder` (removing all 3) instead of `changeItemQuantity` to reduce the count.

**Fix:** Updated two places:
1. `src/chatbot/promptsv2.py` — `DEFAULT_EXECUTION_AGENT_SYSTEM_PROMPT`, `For REMOVE_ITEM:` section now has a PRE-CHECK block instructing the agent to:
   - If specific quantity mentioned AND `requestedQty < currentQty` → call `changeItemQuantity(target, newQuantity=currentQty - requestedQty)`
   - If specific quantity mentioned AND `requestedQty >= currentQty` → call `removeItemFromOrder(target)`
   - If no specific quantity → call `removeItemFromOrder(target)` directly
2. `src/chatbot/orchestrator.py` — Updated descriptions for both `removeItemFromOrder` and `changeItemQuantity` `GeminiFunctionTool`s to reinforce this routing.

## Gotchas / Decisions
- `details` falls back to remove-all when modifier scoring is below `NOT_FOUND_THRESHOLD`. This is intentional — if the qualifier is too vague, safer to remove all matching items and let the agent tell the customer.
- Individual delete failures in the bulk-remove loop are logged but don't abort the whole operation. Only if `removedCount == 0` at the end is `success=False` returned.
- `LOW_MENU_MATCH_THRESHOLD` (65) gates the initial item name match; `NOT_FOUND_THRESHOLD` (50) gates the modifier/details match.

## 2026-04-22 - Menu Numeric Variant Merging

### Overview
Items like "Wings 6", "Wings 12", "Wings 24" all normalize to the same `by_name` key `"wings"`. Previously only the first variant was ever retrieved. Now they are merged into one item.

### How It Works (`src/chatbot/utils.py`)
- **`_merge_numeric_name_variants(norm_name, items)`** — new helper above `_normalize_item_name`. If every item in the group has a numeric token in its original name, collapses them into a single item with a synthetic `"Quantity"` required modifier group (one option per variant). Returns the list unchanged if any item lacks a number.
- **`_normalize_menu`** — stores `item["_original_name"]` before overwriting `item["name"]`, then post-processes `by_name` to call `_merge_numeric_name_variants` for any key with >1 item, then strips `_original_name` from all `by_id` entries.
- `by_id` is **unchanged** — each original variant (e.g. "Wings 6") still lives there by its real ID so `addItemsToOrder` can look it up.

### Agent Flow
1. `findClosestMenuItems("wings")` returns the merged item with `merged: True` and a `"Quantity"` modifier group.
2. Agent prompts user to choose a quantity.
3. User picks "12" → agent passes that modifier option's `id` (the original "Wings 12" item ID) as `itemId` to `addItemsToOrder`.

### Gotchas
- Non-numeric multi-variant items (e.g. two items that both normalize to the same name without numbers) are NOT merged — list stays as-is.
- Quantity modifier `id` fields are the original item IDs, not synthetic IDs, so `addItemsToOrder` needs no changes.

## 2026-04-22 - Skip "Wings" Placeholder Item

### Overview
Clover has a placeholder item with raw name exactly `"Wings"`, price 0, and no category. After normalization it collides with real bone-in wing items (e.g. "6 PC Wings" → `"wings"`). An explicit exclusion prevents it from ever entering the menu index.

### Fix (`src/chatbot/utils.py` — `_normalize_item_name`)
Added a check before the existing normalization logic:
```python
if name.strip().lower() == "wings":
    return None
```
This returns `None` (skip) only when the raw name is **exactly** "wings" (any casing). It does not affect:
- "Boneless Wings" → normalizes to `"boneless wings"` ✓
- "6 PC Wings" / "10 PC Wings" → raw name is not exactly "wings" ✓

## 2026-04-22 - Provider-Agnostic LLM Routing

### Rule
All LLM calls must go through `src/chatbot/llm_client.py`. Never import from `gemini_client` or `openai_client` directly in feature code.

### How It Works
- `src/config.py` sets `AI_MODE` (default `"chatgpt"`)
- `llm_client.py` routes `generate_text` / `generate_model` to OpenAI or Gemini based on `AI_MODE`
- Switching providers requires only changing `AI_MODE` in config — no code changes needed

### Files Updated
Swapped direct `gemini_client` imports to `llm_client` in:
- `src/chatbot/visibility/ai_client.py`
- `src/chatbot/infrastructure/summarizer.py`
- `src/chatbot/tools.py`
- `src/chatbot/clarification/ai_resolver.py`
- `src/chatbot/cart/ai_client.py`
