from __future__ import annotations

from src.chatbot.schema import ChatTurn
from src.chatbot.tools import getPreviousKMessages


async def load_history_tail(*, session_id: str, n: int = 6) -> list[ChatTurn]:
    """Load the last n turns of conversation as ChatTurn objects.

    Returns chronologically ordered (oldest first). Empty list on tool failure.
    Caller should pass an n that reflects how many BOTH-SIDED messages they
    want, not how many customer-only messages - getPreviousKMessages includes
    both roles.
    """
    result = await getPreviousKMessages(session_id, n)
    if not result.get("success"):
        return []
    out: list[ChatTurn] = []
    for msg in result.get("messages", []):
        role_raw = msg.get("role", "")
        # Existing system uses "customer" for user; everything else maps to assistant.
        role = "customer" if role_raw == "customer" else "assistant"
        out.append(
            ChatTurn(
                role=role,
                content=str(msg.get("content", "")),
                timestamp=str(msg.get("timestamp", "")),
            )
        )
    return out
