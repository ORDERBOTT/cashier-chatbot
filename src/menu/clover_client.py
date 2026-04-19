import time
from typing import Any

import httpx

_UNSET = object()


def _modifier_group_merge_score(group: dict) -> tuple[int, int, int]:
    modifiers = group.get("modifiers")
    expanded_count = 0
    if isinstance(modifiers, dict):
        elems = modifiers.get("elements")
        if isinstance(elems, list):
            expanded_count = len(elems)

    modifier_ids = group.get("modifierIds")
    modifier_id_count = len([part for part in str(modifier_ids).split(",") if part.strip()]) if modifier_ids else 0
    return (expanded_count, modifier_id_count, int(bool(group.get("name"))))


def _access_token_expiry_epoch_seconds(creds: dict) -> float | None:
    """Normalise Firestore ``access_token_expiration`` to Unix seconds (handles ms timestamps)."""
    raw = creds.get("access_token_expiration")
    if raw is None:
        return None
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return None
    if n > 1e12:
        n /= 1000.0
    return n


def _should_refresh_access_token(creds: dict, *, buffer_seconds: int = 60) -> bool:
    """True when the access token is missing expiry or expires within ``buffer_seconds``."""
    exp = _access_token_expiry_epoch_seconds(creds)
    if exp is None:
        return False
    return time.time() >= exp - buffer_seconds


async def refresh_clover_oauth_tokens(
    base_url: str, client_id: str, refresh_token: str
) -> dict[str, Any]:
    """POST /oauth/v2/refresh; returns Clover JSON (access_token, refresh_token, expirations, ...)."""
    url = f"{base_url.rstrip('/')}/oauth/v2/refresh"
    payload = {"client_id": client_id, "refresh_token": refresh_token}
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()


async def ensure_fresh_clover_access_token(
    creds: dict,
    base_url: str,
    doc_ref: Any | None,
    *,
    app_client_id: str | None = None,
) -> str:
    """Refresh OAuth tokens when near expiry, persist to Firestore, return ``access_token`` for menu calls."""
    client_id = creds.get("client_id") or app_client_id
    refresh_token = creds.get("refresh_token")
    should_refresh = _should_refresh_access_token(creds)
    print(
        f"[ensure_fresh_clover_access_token] should_refresh={should_refresh} "
        f"has_refresh_token={bool(refresh_token)} "
        f"has_client_id={bool(client_id)}"
    )
    if should_refresh and refresh_token and client_id:
        print("[ensure_fresh_clover_access_token] attempting token refresh")
        try:
            new_tokens = await refresh_clover_oauth_tokens(
                base_url, str(client_id), str(refresh_token)
            )
            updates: dict[str, Any] = {
                "access_token": new_tokens["access_token"],
                "refresh_token": new_tokens.get("refresh_token", refresh_token),
            }
            if "access_token_expiration" in new_tokens:
                updates["access_token_expiration"] = new_tokens[
                    "access_token_expiration"
                ]
            if "refresh_token_expiration" in new_tokens:
                updates["refresh_token_expiration"] = new_tokens[
                    "refresh_token_expiration"
                ]
            creds.update(updates)
            if doc_ref is not None:
                await doc_ref.update(updates)
            print("[ensure_fresh_clover_access_token] token refresh succeeded")
        except httpx.HTTPError as exc:
            print(
                f"Clover token refresh failed ({exc!r}); continuing with existing access_token"
            )
    elif should_refresh:
        print(
            "[ensure_fresh_clover_access_token] refresh needed but skipped "
            f"(missing {'refresh_token' if not refresh_token else 'client_id'})"
        )

    token = creds.get("access_token")
    print(f"[ensure_fresh_clover_access_token] final has_token={bool(token)}")
    if not token:
        raise ValueError("Clover access_token missing after refresh attempt")
    return str(token)


async def fetch_clover_menu(
    access_token: str,
    merchant_id: str,
    base_url: str,
    *,
    page_size: int = 1000,
) -> dict:
    """Fetch all inventory items from Clover (paginated) for ``build_items_by_name``.

    Merges each page's ``elements`` into one list. Query matches typical Clover REST usage:
    ``expand=modifierGroups,categories``, ``limit`` / ``offset``.

    Returns a dict with top-level ``elements`` (v3 list shape). Raises ``httpx.HTTPStatusError`` on errors.
    """
    base = base_url.rstrip("/")
    path = f"{base}/v3/merchants/{merchant_id}/items"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    merged: list[dict] = []
    merged_modifier_groups: dict[str, dict] = {}
    offset = 0
    async with httpx.AsyncClient() as client:
        while True:
            response = await client.get(
                path,
                params={
                    "limit": str(page_size),
                    "offset": str(offset),
                    "expand": "modifierGroups,categories",
                },
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            chunk = (
                data.get("elements") if isinstance(data.get("elements"), list) else []
            )
            merged.extend(chunk)
            modifier_groups = data.get("modifierGroups")
            if isinstance(modifier_groups, dict):
                modifier_group_elems = modifier_groups.get("elements")
                if isinstance(modifier_group_elems, list):
                    for group in modifier_group_elems:
                        if not isinstance(group, dict):
                            continue
                        group_id = group.get("id")
                        if not group_id:
                            continue
                        previous = merged_modifier_groups.get(group_id)
                        if previous is None or _modifier_group_merge_score(group) > _modifier_group_merge_score(previous):
                            merged_modifier_groups[group_id] = group
            if len(chunk) < page_size:
                break
            offset += page_size
    return {"elements": merged, "modifierGroups": {"elements": list(merged_modifier_groups.values())}}


async def fetch_clover_modifiers(
    access_token: str,
    merchant_id: str,
    base_url: str,
    *,
    page_size: int = 1000,
) -> dict:
    """Fetch all modifiers from Clover (paginated).

    Returns a dict with top-level ``elements`` for easy merging into the raw menu
    snapshot before normalization.
    """
    base = base_url.rstrip("/")
    path = f"{base}/v3/merchants/{merchant_id}/modifiers"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    merged: list[dict] = []
    offset = 0
    async with httpx.AsyncClient() as client:
        while True:
            response = await client.get(
                path,
                params={
                    "limit": str(page_size),
                    "offset": str(offset),
                },
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            chunk = data.get("elements") if isinstance(data.get("elements"), list) else []
            merged.extend(chunk)
            if len(chunk) < page_size:
                break
            offset += page_size
    return {"elements": merged}


async def fetch_clover_item(
    access_token: str,
    merchant_id: str,
    base_url: str,
    item_id: str,
) -> dict | None:
    """GET a single inventory item from Clover. Returns ``None`` on HTTP 404."""
    base = base_url.rstrip("/")
    url = f"{base}/v3/merchants/{merchant_id}/items/{item_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers=headers,
            params={"expand": "categories,modifierGroups"},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()


async def add_clover_line_item(
    access_token: str,
    merchant_id: str,
    base_url: str,
    order_id: str,
    item_id: str,
    quantity: int,
    note: str | None = None,
    price: int | None = None,
) -> dict:
    """POST a line item to an existing Clover order.

    Sends ``POST /v3/merchants/{merchant_id}/orders/{order_id}/line_items`` with
    ``item.id`` and ``unitQty`` (quantity * 1000 per Clover convention).

    ``price`` (cents) must be provided for VARIABLE-price items — Clover rejects
    the request with 400 if the field is absent for those items. Pass the item's
    menu price (even when it is 0) so Clover can accept the request; modifier
    prices are then added on top by subsequent modification calls.

    Raises ``httpx.HTTPStatusError`` on non-success HTTP status.
    """
    base = base_url.rstrip("/")
    url = f"{base}/v3/merchants/{merchant_id}/orders/{order_id}/line_items"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {"item": {"id": item_id}, "unitQty": quantity * 1000}
    if note is not None:
        body["note"] = note
    if price is not None:
        body["price"] = price
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        return response.json()


async def add_clover_modification(
    access_token: str,
    merchant_id: str,
    base_url: str,
    order_id: str,
    line_item_id: str,
    modifier_id: str,
) -> dict:
    """POST a modifier to an existing Clover line item.

    Sends ``POST /v3/merchants/{merchant_id}/orders/{order_id}/line_items/{line_item_id}/modifications``
    with ``modifier.id``.

    Raises ``httpx.HTTPStatusError`` on non-success HTTP status.
    """
    base = base_url.rstrip("/")
    url = f"{base}/v3/merchants/{merchant_id}/orders/{order_id}/line_items/{line_item_id}/modifications"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url, headers=headers, json={"modifier": {"id": modifier_id}}
        )
        response.raise_for_status()
        return response.json()


async def delete_clover_line_item(
    access_token: str,
    merchant_id: str,
    base_url: str,
    order_id: str,
    line_item_id: str,
) -> None:
    """DELETE /v3/merchants/{merchant_id}/orders/{order_id}/line_items/{line_item_id}

    Raises httpx.HTTPStatusError on non-success HTTP status.
    """
    base = base_url.rstrip("/")
    url = f"{base}/v3/merchants/{merchant_id}/orders/{order_id}/line_items/{line_item_id}"
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    async with httpx.AsyncClient() as client:
        response = await client.delete(url, headers=headers)
        response.raise_for_status()


async def delete_clover_modification(
    access_token: str,
    merchant_id: str,
    base_url: str,
    order_id: str,
    line_item_id: str,
    modification_id: str,
) -> None:
    """DELETE a previously applied modification from a Clover line item.

    Raises ``httpx.HTTPStatusError`` on non-success HTTP status.
    """
    base = base_url.rstrip("/")
    url = (
        f"{base}/v3/merchants/{merchant_id}/orders/{order_id}/line_items/"
        f"{line_item_id}/modifications/{modification_id}"
    )
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    async with httpx.AsyncClient() as client:
        response = await client.delete(url, headers=headers)
        response.raise_for_status()


async def delete_clover_order(
    access_token: str,
    merchant_id: str,
    base_url: str,
    order_id: str,
) -> None:
    """DELETE /v3/merchants/{merchant_id}/orders/{order_id}

    Raises ``httpx.HTTPStatusError`` on non-success HTTP status.
    """
    base = base_url.rstrip("/")
    url = f"{base}/v3/merchants/{merchant_id}/orders/{order_id}"
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    async with httpx.AsyncClient() as client:
        response = await client.delete(url, headers=headers)
        response.raise_for_status()


async def update_clover_line_item(
    access_token: str,
    merchant_id: str,
    base_url: str,
    order_id: str,
    line_item_id: str,
    *,
    quantity: int | None = None,
    note: str | None | object = _UNSET,
) -> dict:
    """POST an in-place update to an existing Clover line item.

    Sends ``POST /v3/merchants/{merchant_id}/orders/{order_id}/line_items/{line_item_id}``
    with any provided mutable fields such as ``quantity`` and ``note``.

    Raises ``httpx.HTTPStatusError`` on non-success HTTP status.
    """
    base = base_url.rstrip("/")
    url = f"{base}/v3/merchants/{merchant_id}/orders/{order_id}/line_items/{line_item_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {}
    if quantity is not None:
        body["quantity"] = quantity
    if note is not _UNSET:
        body["note"] = note
    if not body:
        raise ValueError("update_clover_line_item requires at least one field to update")
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        return response.json()


async def update_clover_order(
    access_token: str,
    merchant_id: str,
    base_url: str,
    order_id: str,
    *,
    state: str,
) -> dict:
    """POST an in-place update to an existing Clover order.

    Sends ``POST /v3/merchants/{merchant_id}/orders/{order_id}``
    with the provided order-level fields such as ``state``.

    Raises ``httpx.HTTPStatusError`` on non-success HTTP status.
    """
    base = base_url.rstrip("/")
    url = f"{base}/v3/merchants/{merchant_id}/orders/{order_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json={"state": state})
        response.raise_for_status()
        return response.json()


async def fetch_clover_order(
    access_token: str,
    merchant_id: str,
    base_url: str,
    order_id: str,
    *,
    expand: list[str] | None = None,
) -> dict:
    """GET a Clover order with line items expanded.

    Sends ``GET /v3/merchants/{merchant_id}/orders/{order_id}?expand=lineItems``.
    Returns the full order dict including top-level ``total`` (cents).

    Raises ``httpx.HTTPStatusError`` on non-success HTTP status.
    """
    base = base_url.rstrip("/")
    url = f"{base}/v3/merchants/{merchant_id}/orders/{order_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    expansions = expand or ["lineItems", "lineItems.modifications"]
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers=headers,
            params=[("expand", value) for value in expansions],
        )
        response.raise_for_status()
        return response.json()


async def create_clover_empty_order(
    access_token: str,
    merchant_id: str,
    base_url: str,
    *,
    currency: str = "USD",
) -> dict:
    """Create an open empty Clover order (cart) with no line items.

    Sends ``POST /v3/merchants/{merchant_id}/orders`` with body ``{"currency": ...}``
    only. Clover returns the new order JSON including ``id`` — that id is the cart /
    order id for subsequent line-item calls and payment.

    Raises ``httpx.HTTPStatusError`` on non-success HTTP status.
    """
    base = base_url.rstrip("/")
    url = f"{base}/v3/merchants/{merchant_id}/orders"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers=headers,
            json={"currency": currency},
        )
        response.raise_for_status()
        return response.json()
