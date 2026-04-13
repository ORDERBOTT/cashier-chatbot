import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.chatbot.infrastructure.service import ChatReplyService
from src.chatbot.schema import BotInteractionRequest, TestResultsSaveRequest

router = APIRouter(prefix="/api/bot", tags=["chatbot"])

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


@router.post("/message")
async def bot_message(request: BotInteractionRequest):
    chatbot = ChatReplyService()
    return await chatbot.interpret_and_respond(request)


@router.get("/auto-testing")
async def get_auto_testing():
    path = DATA_DIR / "validation_test_set.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return JSONResponse(content=data)


@router.get("/real-convo-testing")
async def get_real_convo_testing():
    path = DATA_DIR / "real_conversations_validation.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return JSONResponse(content=data)


@router.post("/save-test-results")
async def save_test_results(body: TestResultsSaveRequest):
    os.makedirs("test_results", exist_ok=True)
    filename = f"test_results/run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, "w") as f:
        f.write(body.content)
    return {"saved_to": filename}
