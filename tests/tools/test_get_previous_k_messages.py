import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.chatbot import tools as tools_mod
from src.chatbot.tools import getPreviousKMessages

_FAKE_SETTINGS = SimpleNamespace(DEFAULT_PREVIOUS_MESSAGES_K=-1)


def _run(coro):
    return asyncio.run(coro)


def _message(role: str, content: str, timestamp: str) -> str:
    return json.dumps(
        {
            "role": role,
            "content": content,
            "timestamp": timestamp,
        }
    )


def test_uses_default_k_from_settings():
    async def _test():
        with (
            patch.object(
                tools_mod,
                "settings",
                SimpleNamespace(DEFAULT_PREVIOUS_MESSAGES_K=2),
            ),
            patch(
                "src.chatbot.tools.cache_list_length",
                new_callable=AsyncMock,
                return_value=4,
            ),
            patch(
                "src.chatbot.tools.cache_list_range",
                new_callable=AsyncMock,
                return_value=[
                    _message("user", "add fries", "2026-04-18T11:00:00Z"),
                    _message("assistant", "added fries", "2026-04-18T11:00:05Z"),
                ],
            ) as mock_range,
        ):
            result = await getPreviousKMessages("session-1")
            mock_range.assert_awaited_once_with("message:session-1", -2, -1)
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["messages"] == [
        {
            "role": "customer",
            "content": "add fries",
            "timestamp": "2026-04-18T11:00:00Z",
        },
        {
            "role": "agent",
            "content": "added fries",
            "timestamp": "2026-04-18T11:00:05Z",
        },
    ]
    assert result["totalMessageCount"] == 4
    assert result["hasEarlierHistory"] is True
    assert result["error"] is None


def test_returns_all_messages_when_k_is_minus_one():
    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch(
                "src.chatbot.tools.cache_list_length",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch(
                "src.chatbot.tools.cache_list_range",
                new_callable=AsyncMock,
                return_value=[
                    _message("user", "hi", "2026-04-18T11:00:00Z"),
                    _message("assistant", "hello", "2026-04-18T11:00:02Z"),
                    _message("user", "one burger", "2026-04-18T11:00:06Z"),
                ],
            ) as mock_range,
        ):
            result = await getPreviousKMessages("session-2", -1)
            mock_range.assert_awaited_once_with("message:session-2", 0, -1)
            return result

    result = _run(_test())
    assert result["success"] is True
    assert [message["content"] for message in result["messages"]] == [
        "hi",
        "hello",
        "one burger",
    ]
    assert result["totalMessageCount"] == 3
    assert result["hasEarlierHistory"] is False
    assert result["error"] is None


def test_k_larger_than_total_returns_full_available_window():
    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch(
                "src.chatbot.tools.cache_list_length",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch(
                "src.chatbot.tools.cache_list_range",
                new_callable=AsyncMock,
                return_value=[
                    _message("user", "one taco", "2026-04-18T11:00:00Z"),
                    _message("assistant", "added", "2026-04-18T11:00:01Z"),
                ],
            ) as mock_range,
        ):
            result = await getPreviousKMessages("session-3", 10)
            mock_range.assert_awaited_once_with("message:session-3", -10, -1)
            return result

    result = _run(_test())
    assert result["success"] is True
    assert len(result["messages"]) == 2
    assert result["totalMessageCount"] == 2
    assert result["hasEarlierHistory"] is False
    assert result["error"] is None


def test_empty_session_returns_no_messages():
    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch(
                "src.chatbot.tools.cache_list_length",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "src.chatbot.tools.cache_list_range", new_callable=AsyncMock
            ) as mock_range,
        ):
            result = await getPreviousKMessages("session-empty")
            mock_range.assert_not_awaited()
            return result

    result = _run(_test())
    assert result == {
        "success": True,
        "messages": [],
        "totalMessageCount": 0,
        "hasEarlierHistory": False,
        "error": None,
    }


def test_skips_unsupported_roles_without_signaling_extra_history_when_fetching_all():
    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch(
                "src.chatbot.tools.cache_list_length",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch(
                "src.chatbot.tools.cache_list_range",
                new_callable=AsyncMock,
                return_value=[
                    _message("user", "what comes on it", "2026-04-18T11:00:00Z"),
                    _message("system", "summary row", "2026-04-18T11:00:04Z"),
                    _message("assistant", "lettuce and sauce", "2026-04-18T11:00:05Z"),
                ],
            ),
        ):
            return await getPreviousKMessages("session-4", -1)

    result = _run(_test())
    assert result["success"] is True
    assert result["messages"] == [
        {
            "role": "customer",
            "content": "what comes on it",
            "timestamp": "2026-04-18T11:00:00Z",
        },
        {
            "role": "agent",
            "content": "lettuce and sauce",
            "timestamp": "2026-04-18T11:00:05Z",
        },
    ]
    assert result["totalMessageCount"] == 3
    assert result["hasEarlierHistory"] is False
    assert result["error"] is None


def test_invalid_json_returns_failure():
    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch(
                "src.chatbot.tools.cache_list_length",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch(
                "src.chatbot.tools.cache_list_range",
                new_callable=AsyncMock,
                return_value=["not-json"],
            ),
        ):
            return await getPreviousKMessages("session-bad")

    result = _run(_test())
    assert result["success"] is False
    assert result["messages"] == []
    assert result["totalMessageCount"] == 0
    assert result["hasEarlierHistory"] is False
    assert "Expecting value" in (result["error"] or "")


def test_invalid_negative_k_returns_failure():
    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch(
                "src.chatbot.tools.cache_list_length", new_callable=AsyncMock
            ) as mock_length,
        ):
            result = await getPreviousKMessages("session-5", -2)
            mock_length.assert_not_awaited()
            return result

    result = _run(_test())
    assert result["success"] is False
    assert result["messages"] == []
    assert result["totalMessageCount"] == 0
    assert result["hasEarlierHistory"] is False
    assert result["error"] == "k must be -1 or a non-negative integer"
