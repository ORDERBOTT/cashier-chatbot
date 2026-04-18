import asyncio
import json
from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.chatbot import tools as tools_mod
from src.chatbot.tools import (
    _build_cli_parser,
    _cli_handlers,
    _cli_summarize_conversation_history,
    summarizeConversationHistory,
)

_FAKE_SETTINGS = SimpleNamespace(
    DEFAULT_PREVIOUS_MESSAGES_K=-1, MERCHANT_ID="merchant-1"
)


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


def _cached_summary(summary: str, messages_covered: int, cached_at: str) -> str:
    return json.dumps(
        {
            "summary": summary,
            "messagesCovered": messages_covered,
            "cachedAt": cached_at,
        }
    )


def test_cache_hit_returns_cached_summary_without_llm():
    cached_at = "2026-04-18T12:00:00+00:00"

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch(
                "src.chatbot.tools.cache_list_length",
                new_callable=AsyncMock,
                return_value=5,
            ),
            patch(
                "src.chatbot.tools.cache_get",
                new_callable=AsyncMock,
                return_value=_cached_summary("Customer ordered fries.", 3, cached_at),
            ),
            patch(
                "src.chatbot.tools.cache_list_range", new_callable=AsyncMock
            ) as mock_range,
            patch(
                "src.chatbot.tools.generate_text", new_callable=AsyncMock
            ) as mock_llm,
        ):
            result = await summarizeConversationHistory("session-1", 2)
            mock_range.assert_not_awaited()
            mock_llm.assert_not_awaited()
            return result

    result = _run(_test())
    assert result == {
        "success": True,
        "summary": "Customer ordered fries.",
        "messagesCovered": 3,
        "cachedAt": cached_at,
        "error": None,
    }


def test_cache_miss_summarizes_pre_k_history_and_caches():
    raw_messages = [
        _message("user", "hi", "2026-04-18T11:00:00Z"),
        _message("assistant", "hello", "2026-04-18T11:00:02Z"),
        _message("user", "one burger", "2026-04-18T11:00:05Z"),
        _message("assistant", "added burger", "2026-04-18T11:00:07Z"),
    ]

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch(
                "src.chatbot.tools.cache_list_length",
                new_callable=AsyncMock,
                return_value=4,
            ),
            patch(
                "src.chatbot.tools.cache_get",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.chatbot.tools.cache_list_range",
                new_callable=AsyncMock,
                return_value=raw_messages,
            ),
            patch(
                "src.chatbot.tools.generate_text",
                new_callable=AsyncMock,
                return_value="The customer greeted the agent and asked for a burger.",
            ) as mock_llm,
            patch(
                "src.chatbot.tools.cache_set", new_callable=AsyncMock
            ) as mock_cache_set,
        ):
            result = await summarizeConversationHistory("session-2", 2)
            llm_messages = mock_llm.await_args.args[0]
            return result, llm_messages, mock_cache_set.await_args

    result, llm_messages, cache_set_args = _run(_test())
    assert result["success"] is True
    assert result["summary"] == "The customer greeted the agent and asked for a burger."
    assert result["messagesCovered"] == 2
    assert result["cachedAt"] is not None
    assert result["error"] is None

    assert llm_messages[0]["role"] == "system"
    assert llm_messages[1:] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {
            "role": "user",
            "content": "Summarize the earlier conversation above in one short factual paragraph.",
        },
    ]

    assert cache_set_args.args[0] == "summary:session-2:2"
    cached_payload = json.loads(cache_set_args.args[1])
    assert cached_payload["summary"] == result["summary"]
    assert cached_payload["messagesCovered"] == 2
    assert cached_payload["cachedAt"] == result["cachedAt"]
    assert cache_set_args.kwargs["ttl"] == 3 * 60 * 60


def test_k_zero_summarizes_full_history():
    raw_messages = [
        _message("user", "one taco", "2026-04-18T11:00:00Z"),
        _message("assistant", "added taco", "2026-04-18T11:00:01Z"),
    ]

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch(
                "src.chatbot.tools.cache_list_length",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch(
                "src.chatbot.tools.cache_get",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.chatbot.tools.cache_list_range",
                new_callable=AsyncMock,
                return_value=raw_messages,
            ),
            patch(
                "src.chatbot.tools.generate_text",
                new_callable=AsyncMock,
                return_value="The customer ordered one taco.",
            ) as mock_llm,
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
        ):
            result = await summarizeConversationHistory("session-3", 0)
            llm_messages = mock_llm.await_args.args[0]
            return result, llm_messages

    result, llm_messages = _run(_test())
    assert result["success"] is True
    assert result["messagesCovered"] == 2
    assert llm_messages[1:3] == [
        {"role": "user", "content": "one taco"},
        {"role": "assistant", "content": "added taco"},
    ]


def test_k_at_or_beyond_total_returns_empty_summary_without_llm():
    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch(
                "src.chatbot.tools.cache_list_length",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch(
                "src.chatbot.tools.cache_get", new_callable=AsyncMock
            ) as mock_cache_get,
            patch(
                "src.chatbot.tools.cache_list_range", new_callable=AsyncMock
            ) as mock_range,
            patch(
                "src.chatbot.tools.generate_text", new_callable=AsyncMock
            ) as mock_llm,
        ):
            result = await summarizeConversationHistory("session-4", 2)
            mock_cache_get.assert_not_awaited()
            mock_range.assert_not_awaited()
            mock_llm.assert_not_awaited()
            return result

    result = _run(_test())
    assert result == {
        "success": True,
        "summary": "",
        "messagesCovered": 0,
        "cachedAt": None,
        "error": None,
    }


def test_unsupported_roles_are_filtered_but_still_count_toward_messages_covered():
    raw_messages = [
        _message("user", "one salad", "2026-04-18T11:00:00Z"),
        _message("system", "summary row", "2026-04-18T11:00:01Z"),
        _message("assistant", "what dressing", "2026-04-18T11:00:03Z"),
        _message("user", "ranch", "2026-04-18T11:00:04Z"),
    ]

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch(
                "src.chatbot.tools.cache_list_length",
                new_callable=AsyncMock,
                return_value=4,
            ),
            patch(
                "src.chatbot.tools.cache_get",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.chatbot.tools.cache_list_range",
                new_callable=AsyncMock,
                return_value=raw_messages,
            ),
            patch(
                "src.chatbot.tools.generate_text",
                new_callable=AsyncMock,
                return_value="The customer ordered a salad and the agent asked about dressing.",
            ) as mock_llm,
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
        ):
            result = await summarizeConversationHistory("session-5", 1)
            llm_messages = mock_llm.await_args.args[0]
            return result, llm_messages

    result, llm_messages = _run(_test())
    assert result["success"] is True
    assert result["messagesCovered"] == 3
    assert llm_messages[1:] == [
        {"role": "user", "content": "one salad"},
        {"role": "assistant", "content": "what dressing"},
        {
            "role": "user",
            "content": "Summarize the earlier conversation above in one short factual paragraph.",
        },
    ]


def test_invalid_cached_summary_is_ignored_and_recomputed():
    raw_messages = [
        _message("user", "two fries", "2026-04-18T11:00:00Z"),
        _message("assistant", "added", "2026-04-18T11:00:01Z"),
        _message("user", "thanks", "2026-04-18T11:00:02Z"),
    ]

    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch(
                "src.chatbot.tools.cache_list_length",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch(
                "src.chatbot.tools.cache_get",
                new_callable=AsyncMock,
                return_value="not-json",
            ),
            patch(
                "src.chatbot.tools.cache_list_range",
                new_callable=AsyncMock,
                return_value=raw_messages,
            ),
            patch(
                "src.chatbot.tools.generate_text",
                new_callable=AsyncMock,
                return_value="The customer ordered fries.",
            ) as mock_llm,
            patch("src.chatbot.tools.cache_set", new_callable=AsyncMock),
        ):
            result = await summarizeConversationHistory("session-6", 1)
            mock_llm.assert_awaited_once()
            return result

    result = _run(_test())
    assert result["success"] is True
    assert result["messagesCovered"] == 2
    assert result["summary"] == "The customer ordered fries."


def test_malformed_history_row_returns_failure():
    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch(
                "src.chatbot.tools.cache_list_length",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch(
                "src.chatbot.tools.cache_get",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.chatbot.tools.cache_list_range",
                new_callable=AsyncMock,
                return_value=[
                    "not-json",
                    _message("user", "hi", "2026-04-18T11:00:00Z"),
                ],
            ),
            patch("src.chatbot.tools.generate_text", new_callable=AsyncMock),
        ):
            return await summarizeConversationHistory("session-bad", 1)

    result = _run(_test())
    assert result["success"] is False
    assert result["summary"] == ""
    assert result["messagesCovered"] == 0
    assert result["cachedAt"] is None
    assert "Expecting value" in (result["error"] or "")


def test_invalid_negative_k_returns_failure():
    async def _test():
        with (
            patch.object(tools_mod, "settings", _FAKE_SETTINGS),
            patch(
                "src.chatbot.tools.cache_list_length", new_callable=AsyncMock
            ) as mock_length,
        ):
            result = await summarizeConversationHistory("session-7", -1)
            mock_length.assert_not_awaited()
            return result

    result = _run(_test())
    assert result == {
        "success": False,
        "summary": "",
        "messagesCovered": 0,
        "cachedAt": None,
        "error": "k must be a non-negative integer",
    }


def test_cli_handler_forwards_session_id_and_k():
    async def _test():
        with patch(
            "src.chatbot.tools.summarizeConversationHistory",
            new_callable=AsyncMock,
            return_value={"success": True},
        ) as mock_summary:
            result = await _cli_summarize_conversation_history(
                Namespace(session_id="session-8", k=4)
            )
            mock_summary.assert_awaited_once_with("session-8", 4)
            return result

    result = _run(_test())
    assert result == {"success": True}


def test_cli_parser_accepts_summarize_conversation_history_command():
    with patch.object(tools_mod, "settings", _FAKE_SETTINGS):
        parser = _build_cli_parser(_cli_handlers())
        args = parser.parse_args(
            ["summarize-conversation-history", "session-9", "--k", "3"]
        )

    assert args.command == "summarize-conversation-history"
    assert args.session_id == "session-9"
    assert args.k == 3
