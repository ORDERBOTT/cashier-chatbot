import asyncio

import pytest
from pydantic import ValidationError

from src.chatbot import gemini_client
from src.chatbot.exceptions import AIServiceError
from src.chatbot.orchestrator import ParsingAgent
from src.chatbot.schema import (
    CurrentOrderDetails,
    ParsedRequestsPayload,
    ParsingAgentContext,
)
from src.config import settings


def _context() -> ParsingAgentContext:
    return ParsingAgentContext(
        session_id="session-1",
        merchant_id="merchant-1",
        current_order_details=CurrentOrderDetails(
            order_id="order-1",
            line_items=[],
            order_total=0,
            raw_error=None,
        ),
        most_recent_message="add a burger and remove fries",
        latest_k_messages_by_customer=["hi", "one fries"],
        summary_of_messages_before_k_by_customer="Earlier customer summary",
    )


def test_parsing_agent_builds_prompt_with_production_sections_and_context():
    agent = ParsingAgent()

    messages = agent._build_messages(
        context=_context(),
        prompts=agent.prompts,
        strict_retry=False,
    )

    assert messages[0]["role"] == "system"
    assert "IDENTITY" in messages[0]["content"]
    assert "INPUT YOU RECEIVE" in messages[0]["content"]
    assert "YOUR OUTPUT FORMAT" in messages[0]["content"]
    assert '"Request_items"' in messages[0]["content"]
    assert "FEW-SHOT EXAMPLES" in messages[0]["content"]
    assert "FINAL REMINDERS" in messages[0]["content"]
    assert "think step by step privately" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert (
        '"most_recent_message_by_customer": "add a burger and remove fries"'
        in messages[1]["content"]
    )
    assert '"latest_k_messages_by_customer"' in messages[1]["content"]
    assert (
        '"summary_of_messages_before_k_by_customer": "Earlier customer summary"'
        in messages[1]["content"]
    )
    assert '"current_order_details"' in messages[1]["content"]


def test_parsing_agent_returns_structured_requests(monkeypatch):
    calls: list[dict] = []

    async def _fake_generate_model(messages, response_model, **kwargs):
        calls.append({"messages": messages, "kwargs": kwargs})
        return response_model.model_validate(
            {
                "Data": [
                    {
                        "Intent": "add_item",
                        "Confidence_level": "high",
                        "Request_items": {
                            "name": "burger",
                            "quantity": 2,
                            "details": "no onions",
                        },
                        "Request_details": "first request",
                    },
                    {
                        "Intent": "remove_item",
                        "Confidence_level": "low",
                        "Request_items": {
                            "name": "fries",
                            "quantity": 1,
                            "details": "",
                        },
                        "Request_details": "second request",
                    },
                ]
            }
        )

    monkeypatch.setattr(gemini_client, "generate_model", _fake_generate_model)

    result = asyncio.run(ParsingAgent().run(context=_context()))

    assert len(calls) == 1
    assert calls[0]["kwargs"]["temperature"] == 0
    assert calls[0]["kwargs"]["model"] == settings.PARSING_AGENT_GEMINI_MODEL
    assert result.context.session_id == "session-1"
    assert [item.intent for item in result.parsed_requests.data] == [
        "add_item",
        "remove_item",
    ]


def test_parsed_requests_payload_rejects_request_entities():
    with pytest.raises(ValidationError):
        ParsedRequestsPayload.model_validate(
            {
                "Data": [
                    {
                        "Intent": "add_item",
                        "Confidence_level": "high",
                        "Request_entities": {
                            "name": "burger",
                            "quantity": 1,
                            "details": "",
                        },
                        "Request_details": "bad key",
                    }
                ]
            }
        )


def test_parsing_agent_retries_once_on_parse_validation_error(monkeypatch):
    calls: list[list[dict[str, str]]] = []

    async def _fake_generate_model(messages, response_model, **kwargs):
        del kwargs
        calls.append(messages)
        if len(calls) == 1:
            raise AIServiceError(
                "Failed to parse Gemini structured response: invalid JSON"
            )
        return response_model.model_validate(
            {
                "Data": [
                    {
                        "Intent": "confirm_order",
                        "Confidence_level": "high",
                        "Request_items": {
                            "name": "",
                            "quantity": 0,
                            "details": "",
                        },
                        "Request_details": "confirm everything",
                    }
                ]
            }
        )

    monkeypatch.setattr(gemini_client, "generate_model", _fake_generate_model)

    result = asyncio.run(ParsingAgent().run(context=_context()))

    assert len(calls) == 2
    assert "RETRY INSTRUCTION" not in calls[0][0]["content"]
    assert "RETRY INSTRUCTION" in calls[1][0]["content"]
    assert result.parsed_requests.data[0].intent == "confirm_order"


def test_parsing_agent_raises_after_retry_failure(monkeypatch):
    async def _fake_generate_model(messages, response_model, **kwargs):
        del messages
        del response_model
        del kwargs
        raise AIServiceError(
            "Failed to parse Gemini structured response: still invalid"
        )

    monkeypatch.setattr(gemini_client, "generate_model", _fake_generate_model)

    with pytest.raises(AIServiceError, match="Parsing agent failed after retry"):
        asyncio.run(ParsingAgent().run(context=_context()))
