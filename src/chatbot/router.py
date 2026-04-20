import os
from datetime import datetime

from fastapi import APIRouter, Depends, Request

from src.chatbot.orchestrator import Orchestrator
from src.chatbot.infrastructure.service import ChatReplyService
from src.cache import cache_delete, cache_delete_pattern
from src.chatbot.schema import (
    BotInteractionRequest,
    ChatbotV2MessageRequest,
    ChatbotV2MessageResponse,
    ClearSessionRequest,
    TestResultsSaveRequest,
)
from src.chatbot.utils import (
    _session_clover_order_redis_key,
    _session_messages_redis_key,
    _session_order_state_redis_key,
    _session_status_redis_key,
    _session_clarification_and_intent_redis_key,
)

router = APIRouter(prefix="/api/bot", tags=["chatbot"])
v2_router = APIRouter(prefix="/chatbot/v2", tags=["chatbot"])


@router.post(
    "/message",
    response_model=ChatbotV2MessageResponse,
)
async def bot_message(request: ChatbotV2MessageRequest) -> ChatbotV2MessageResponse:
    orchestrator = Orchestrator()
    return await orchestrator.handle_message(request)


@v2_router.post(
    "/message",
    response_model=ChatbotV2MessageResponse,
)
async def bot_message_v2(request: ChatbotV2MessageRequest) -> ChatbotV2MessageResponse:
    orchestrator = Orchestrator()
    return await orchestrator.handle_message(request)


@router.post("/clear-session")
async def clear_session(body: ClearSessionRequest) -> dict:
    session_id = body.session_id
    await cache_delete(_session_clover_order_redis_key(session_id))
    await cache_delete(_session_messages_redis_key(session_id))
    await cache_delete(_session_order_state_redis_key(session_id))
    await cache_delete(_session_status_redis_key(session_id))
    await cache_delete(_session_clarification_and_intent_redis_key(session_id))
    await cache_delete_pattern(f"summary:{session_id}:*")
    return {"cleared": True, "session_id": session_id}


@router.post("/save-test-results")
async def save_test_results(body: TestResultsSaveRequest):
    os.makedirs("test_results", exist_ok=True)
    filename = f"test_results/run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, "w") as f:
        f.write(body.content)
    return {"saved_to": filename}
