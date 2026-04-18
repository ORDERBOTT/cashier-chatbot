import os
from datetime import datetime

from fastapi import APIRouter

from src.chatbot.orchestrator import Orchestrator
from src.chatbot.infrastructure.service import ChatReplyService
from src.chatbot.schema import (
    BotInteractionRequest,
    ChatbotV2MessageRequest,
    ChatbotV2MessageResponse,
    TestResultsSaveRequest,
)

router = APIRouter(prefix="/chatbot", tags=["chatbot"])
v2_router = APIRouter(prefix="/api/bot", tags=["chatbot"])


@router.post("/message")
async def bot_message(request: BotInteractionRequest):
    chatbot = ChatReplyService()
    return await chatbot.interpret_and_respond(request)


@v2_router.post("/message", response_model=ChatbotV2MessageResponse)
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
