import asyncio

from src.chatbot import gemini_client
from src.chatbot import orchestrator as orchestrator_mod
from src.chatbot.gemini_client import GeminiFunctionTool
from src.chatbot.orchestrator import ExecutionAgent
from src.chatbot.schema import (
    CurrentOrderDetails,
    CurrentOrderLineItem,
    ParsedRequestConfidenceLevel,
    ParsedRequestIntent,
    ParsedRequestItem,
    ParsedRequestItems,
    ParsedRequestsPayload,
    PreparedExecutionContext,
)


def _context_object(
    *,
    latest_customer_message: str = "add a burger",
    line_items: list[CurrentOrderLineItem] | None = None,
) -> PreparedExecutionContext:
    return PreparedExecutionContext(
        session_id="session-1",
        merchant_id="merchant-1",
        latest_customer_message=latest_customer_message,
        current_order_details=CurrentOrderDetails(
            order_id="order-1",
            line_items=line_items or [],
            order_total=0,
            raw_error=None,
        ),
        latest_k_messages_by_customer=["hello"],
        summary_of_messages_before_k_by_customer="",
        clover_error=None,
    )


def _request(
    *,
    intent: ParsedRequestIntent,
    confidence: ParsedRequestConfidenceLevel = ParsedRequestConfidenceLevel.HIGH,
    name: str = "burger",
    quantity: int = 1,
    details: str = "",
    request_details: str = "test request",
) -> ParsedRequestsPayload:
    return ParsedRequestsPayload(
        data=[
            ParsedRequestItem(
                intent=intent,
                confidence_level=confidence,
                request_items=ParsedRequestItems(
                    name=name,
                    quantity=quantity,
                    details=details,
                ),
                request_details=request_details,
            )
        ]
    )


def _tool(name: str, handler, description: str = "tool") -> GeminiFunctionTool:
    return GeminiFunctionTool(
        name=name,
        description=description,
        parameters_json_schema={"type": "object", "properties": {}},
        handler=handler,
    )


def test_execution_agent_adds_exact_match_and_records_actions():
    events: list[str] = []

    async def _find_closest(*, item_name: str, details: str | None = None) -> dict:
        events.append(f"find:{item_name}:{details}")
        return {
            "exact_match": {"id": "item-1", "name": "Burger"},
            "candidates": [{"id": "item-1", "name": "Burger"}],
            "match_confidence": "exact",
        }

    async def _check_availability(*, item_id: str) -> dict:
        events.append(f"availability:{item_id}")
        return {
            "Available": True,
            "itemId": item_id,
            "itemName": "Burger",
            "unavailableReason": None,
        }

    async def _add_items(*, items: list[dict]) -> dict:
        events.append(f"add:{items[0]['itemId']}:{items[0]['quantity']}")
        return {
            "success": True,
            "addedItems": [{"name": "Burger", "quantity": 1}],
            "failedItems": [],
            "updatedOrderTotal": 1099,
        }

    agent = ExecutionAgent(system_prompt="")
    result = asyncio.run(
        agent.run(
            parsed_requests=_request(intent=ParsedRequestIntent.ADD_ITEM),
            context_object=_context_object(),
            tools=[
                _tool("findClosestMenuItems", _find_closest),
                _tool("checkItemAvailability", _check_availability),
                _tool("addItemsToOrder", _add_items),
            ],
        )
    )

    assert result.agent_reply == "Added 1 x Burger."
    assert result.session_id == "session-1"
    assert result.actions_executed == ["added 1 x Burger"]
    assert result.pending_clarifications == []
    assert result.order_updated is True
    assert events == ["find:burger:None", "availability:item-1", "add:item-1:1"]


def test_execution_agent_returns_pending_clarification_for_low_confidence():
    agent = ExecutionAgent(system_prompt="")

    result = asyncio.run(
        agent.run(
            parsed_requests=_request(
                intent=ParsedRequestIntent.ADD_ITEM,
                confidence=ParsedRequestConfidenceLevel.LOW,
                request_details="maybe the spicy thing",
            ),
            context_object=_context_object(
                latest_customer_message="maybe the spicy thing"
            ),
            tools=[],
        )
    )

    assert "Can you clarify that request?" in result.agent_reply
    assert result.actions_executed == []
    assert result.pending_clarifications == [
        'I want to make sure I understood "maybe the spicy thing". Can you clarify that request?'
    ]
    assert result.order_updated is False


def test_execution_agent_returns_multiple_candidates_for_close_match():
    async def _find_closest(*, item_name: str, details: str | None = None) -> dict:
        del item_name
        del details
        return {
            "exact_match": None,
            "candidates": [
                {"id": "1", "name": "Burger"},
                {"id": "2", "name": "Chicken Burger"},
                {"id": "3", "name": "Veggie Burger"},
            ],
            "match_confidence": "close",
        }

    agent = ExecutionAgent(system_prompt="")
    result = asyncio.run(
        agent.run(
            parsed_requests=_request(intent=ParsedRequestIntent.ADD_ITEM),
            context_object=_context_object(),
            tools=[_tool("findClosestMenuItems", _find_closest)],
        )
    )

    assert (
        result.agent_reply == "Did you mean Burger, Chicken Burger, or Veggie Burger?"
    )
    assert result.pending_clarifications == [
        "Did you mean Burger, Chicken Burger, or Veggie Burger?"
    ]
    assert result.order_updated is False


def test_execution_agent_requires_confirmation_before_cancelling():
    async def _cancel_order() -> dict:
        raise AssertionError("cancel tool should not be called without confirmation")

    agent = ExecutionAgent(system_prompt="")
    result = asyncio.run(
        agent.run(
            parsed_requests=_request(
                intent=ParsedRequestIntent.CANCEL_ORDER,
                name="",
                quantity=0,
                request_details="cancel it",
            ),
            context_object=_context_object(
                latest_customer_message="cancel the order",
                line_items=[
                    CurrentOrderLineItem(
                        line_item_id="1", name="Burger", quantity=1, price=1000
                    )
                ],
            ),
            tools=[_tool("cancelOrder", _cancel_order)],
        )
    )

    assert result.agent_reply == "Please confirm if you want me to cancel the order."
    assert result.pending_clarifications == [
        "Please confirm if you want me to cancel the order."
    ]
    assert result.actions_executed == []
    assert result.order_updated is False


def test_execution_agent_build_tools_passes_runtime_creds_to_find_closest_menu_items(
    monkeypatch,
):
    observed: dict[str, object] = {}

    async def _fake_find_closest_menu_items(
        *,
        item_name: str,
        details: str | None = None,
        merchant_id: str | None = None,
        creds: dict | None = None,
    ) -> dict:
        observed["item_name"] = item_name
        observed["details"] = details
        observed["merchant_id"] = merchant_id
        observed["creds"] = creds
        return {
            "exact_match": {"id": "item-1", "name": "Burger"},
            "candidates": [{"id": "item-1", "name": "Burger"}],
            "match_confidence": "exact",
        }

    monkeypatch.setattr(
        orchestrator_mod, "findClosestMenuItems", _fake_find_closest_menu_items
    )

    tools = ExecutionAgent(system_prompt="").build_tools(
        orchestrator_mod.ExecutionToolRuntime(
            context=orchestrator_mod.ExecutionAgentContext(
                session_id="session-1",
                merchant_id="merchant-from-creds",
                clover_creds={"merchant_id": "merchant-from-creds", "token": "secret"},
                clover_error=None,
            )
        )
    )

    payload = asyncio.run(
        tools[0].handler(
            item_name="burger",
            details="spicy",
        )
    )

    assert observed["item_name"] == "burger"
    assert observed["details"] == "spicy"
    assert observed["merchant_id"] == "merchant-from-creds"
    assert observed["creds"] == {
        "merchant_id": "merchant-from-creds",
        "token": "secret",
    }
    assert payload["match_confidence"] == "exact"


def test_execution_agent_uses_execution_prompt_with_text_tool_calling(monkeypatch):
    observed: dict[str, object] = {}

    async def _fake_generate_text_with_tools(
        messages,
        *,
        function_tools,
        temperature: float,
        max_tool_calls: int,
        max_output_tokens=None,
        model: str | None = None,
    ) -> str:
        del max_output_tokens
        observed["messages"] = messages
        observed["function_tools"] = function_tools
        observed["temperature"] = temperature
        observed["max_tool_calls"] = max_tool_calls
        observed["model"] = model
        return "Customer-facing SMS"

    monkeypatch.setattr(
        gemini_client, "generate_text_with_tools", _fake_generate_text_with_tools
    )

    async def _unused_tool_handler(**kwargs):
        del kwargs
        return {}

    agent = ExecutionAgent()
    result = asyncio.run(
        agent.run(
            parsed_requests=_request(
                intent=ParsedRequestIntent.ADD_ITEM,
                confidence=ParsedRequestConfidenceLevel.LOW,
                request_details="maybe the spicy thing",
            ),
            context_object=_context_object(
                latest_customer_message="maybe the spicy thing"
            ),
            tools=[
                _tool(
                    "findClosestMenuItems",
                    _unused_tool_handler,
                    "Find menu items",
                )
            ],
        )
    )

    assert result.agent_reply == "Customer-facing SMS"
    assert result.pending_clarifications == [
        'I want to make sure I understood "maybe the spicy thing". Can you clarify that request?'
    ]
    assert result.order_updated is False
    assert observed["messages"][0]["role"] == "system"
    assert "You are the Order Execution Agent" in observed["messages"][0]["content"]
    assert (
        "Return ONLY a customer-facing SMS reply." in observed["messages"][0]["content"]
    )
    assert '"parsed_requests"' in observed["messages"][1]["content"]
    assert '"tools"' in observed["messages"][1]["content"]
    assert len(observed["function_tools"]) == 1
