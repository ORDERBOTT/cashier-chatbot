from src.chatbot.intent.resolver import ConversationStateResolver
from src.chatbot.schema import BotInteractionRequest, ChatbotResponse
from src.chatbot.visibility.handlers import StateHandlerFactory

class ChatReplyService:
    def __init__(self):
        self.handler_factory = StateHandlerFactory()
        self.chatbot = ConversationStateResolver()

    async def process_and_reply(self, Conversation: BotInteractionRequest) -> ChatbotResponse:
        return await self._build_reply(Conversation)

    async def _build_reply(self, Conversation: BotInteractionRequest) -> ChatbotResponse:

        state, extracted_name = await self.chatbot.detectConversationState(
            latest_message=Conversation.latest_message,
            message_history=Conversation.message_history,
            previous_state=Conversation.previous_state,
        )

        response = await self.handler_factory.handle(state, Conversation)
        response.previous_state, response.customer_name= state.value, extracted_name or Conversation.customer_name
        return response
