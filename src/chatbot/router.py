import os
from datetime import datetime

from fastapi import APIRouter, Depends, Request

from src.chatbot.orchestrator import Orchestrator
from src.chatbot.infrastructure.service import ChatReplyService
from src.chatbot.schema import (
    BotInteractionRequest,
    ChatbotV2MessageRequest,
    ChatbotV2MessageResponse,
    TestResultsSaveRequest,
)

router = APIRouter(prefix="/api/bot", tags=["chatbot"])
v2_router = APIRouter(prefix="/chatbot/v2", tags=["chatbot"])


async def _log_raw_v2_message_body(request: Request) -> None:
    """Runs before Pydantic parses the body; prints raw JSON bytes."""
    raw = await request.body()
    print(f"[bot_message_v2] raw body ({len(raw)} bytes): {raw.decode(errors='replace')!r}")


@router.post("/message")
async def bot_message(request: BotInteractionRequest):
    chatbot = ChatReplyService()
    return await chatbot.interpret_and_respond(request)


@v2_router.post(
    "/message",
    response_model=ChatbotV2MessageResponse,
    dependencies=[Depends(_log_raw_v2_message_body)],
)
async def bot_message_v2(request: ChatbotV2MessageRequest) -> ChatbotV2MessageResponse:
    orchestrator = Orchestrator()
    return await orchestrator.handle_message(request)


@router.post("/save-test-results")
async def save_test_results(body: TestResultsSaveRequest):
    os.makedirs("test_results", exist_ok=True)
    filename = f"test_results/run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, "w") as f:
        f.write(body.content)
    return {"saved_to": filename}
