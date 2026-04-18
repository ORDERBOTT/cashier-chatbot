from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.chatbot.router import v2_router
from src.chatbot.schema import (
    ExecutionAgentContext,
    ExecutionAgentResult,
    ParsedRequestConfidenceLevel,
    ParsedRequestIntent,
    ParsedRequestItem,
    ParsedRequestItems,
    ParsedRequestsPayload,
    ParsingAgentResult,
)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(v2_router)
    return TestClient(app)


def test_chatbot_v2_message_returns_minimal_contract(monkeypatch):
    from src.chatbot import orchestrator as orchestrator_mod

    async def _fake_run(self, *, context, prompts=None):
        del self
        del prompts
        return ParsingAgentResult(
            context=context,
            parsed_requests=ParsedRequestsPayload(
                data=[
                    ParsedRequestItem(
                        intent=ParsedRequestIntent.ADD_ITEM,
                        confidence_level=ParsedRequestConfidenceLevel.HIGH,
                        request_items=ParsedRequestItems(
                            name="hello there",
                            quantity=1,
                            details="",
                        ),
                        request_details="route test",
                    )
                ]
            ),
        )

    async def _fake_get_previous_messages(session_id: str, k: int | None = None):
        del session_id
        del k
        return {
            "success": True,
            "messages": [],
            "error": None,
        }

    async def _fake_summarize_history(session_id: str, k: int):
        del session_id
        del k
        return {
            "success": True,
            "summary": "",
            "messagesCovered": 0,
            "cachedAt": None,
            "error": None,
        }

    async def _fake_get_order_line_items(session_id: str):
        del session_id
        return {
            "success": True,
            "orderId": "",
            "lineItems": [],
            "orderTotal": 0,
            "error": None,
        }

    async def _fake_execution_run(
        self,
        *,
        parsed_requests,
        context_object,
        tools,
    ) -> ExecutionAgentResult:
        del self
        del parsed_requests
        del context_object
        del tools
        return ExecutionAgentResult(
            agent_reply="stubbed system response",
            session_id="session-1",
            actions_executed=[],
            pending_clarifications=[],
            order_updated=False,
        )

    async def _fake_build_execution_context(self, request):
        del self
        return ExecutionAgentContext(
            session_id=request.session_id,
            merchant_id=request.merchant_id,
            clover_creds={"merchant_id": request.merchant_id},
            clover_error=None,
        )

    monkeypatch.setattr(orchestrator_mod.ParsingAgent, "run", _fake_run)
    monkeypatch.setattr(orchestrator_mod.ExecutionAgent, "run", _fake_execution_run)
    monkeypatch.setattr(
        orchestrator_mod.Orchestrator,
        "_build_execution_context",
        _fake_build_execution_context,
    )
    monkeypatch.setattr(
        orchestrator_mod, "getPreviousKMessages", _fake_get_previous_messages
    )
    monkeypatch.setattr(
        orchestrator_mod, "summarizeConversationHistory", _fake_summarize_history
    )
    monkeypatch.setattr(
        orchestrator_mod, "getOrderLineItems", _fake_get_order_line_items
    )

    response = _client().post(
        "/chatbot/v2/message",
        json={
            "user_message": "hello there",
            "session_id": "session-1",
            "merchant_id": "merchant-1",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "system_response": "stubbed system response",
        "session_id": "session-1",
    }


def test_chatbot_v2_message_requires_all_fields():
    response = _client().post(
        "/chatbot/v2/message",
        json={
            "user_message": "hello there",
            "session_id": "session-1",
        },
    )

    assert response.status_code == 422
