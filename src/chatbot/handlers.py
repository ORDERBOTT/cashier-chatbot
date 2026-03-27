import json

from src.cache import cache_get
from src.chatbot.chatbot_ai import ChatbotAI
from src.chatbot.constants import ConversationState
from src.chatbot.exceptions import UnhandledStateError
from src.chatbot.food_order_handlers import FoodOrderHandlerFactory
from src.chatbot.schema import BotMessageRequest, BotMessageResponse

RESTAURANT_CONTEXT_KEY = "restaurant_context:{user_id}"
RESTAURANT_CONTEXT_FALLBACK = "No specific restaurant information is available at this time."

MENU_CONTEXT_KEY = "menu_context:{user_id}"
MENU_CONTEXT_FALLBACK = "No menu information is available at this time."

RESTAURANT_NAME_LOCATION_KEY = "restaurant_name_location:{user_id}"
RESTAURANT_NAME_LOCATION_FALLBACK = "No restaurant name or location is available at this time."
RESTAURANT_CONTEXT_JSON_KEY = "restaurantContext:{user_id}"
RESTAURANT_NAME_KEY = "restaurant_name:{user_id}"
RESTAURANT_CITY_KEY = "restaurant_city:{user_id}"
RESTAURANT_PHONE_KEY = "restaurant_phone:{user_id}"
RESTAURANT_TAGLINE_KEY = "restaurant_tagline:{user_id}"
RESTAURANT_GREETING_KEY = "restaurant_greeting:{user_id}"


async def _get_restaurant_profile_fields(user_id: str) -> dict[str, str]:
    name = await cache_get(RESTAURANT_NAME_KEY.format(user_id=user_id))
    city = await cache_get(RESTAURANT_CITY_KEY.format(user_id=user_id))
    phone = await cache_get(RESTAURANT_PHONE_KEY.format(user_id=user_id))
    tagline = await cache_get(RESTAURANT_TAGLINE_KEY.format(user_id=user_id))
    greeting = await cache_get(RESTAURANT_GREETING_KEY.format(user_id=user_id))
    return {
        "restaurantName": name or "",
        "city": city or "",
        "phone": phone or "",
        "tagline": tagline or "",
        "greeting": greeting or "",
    }


async def _get_restaurant_profile_json(user_id: str) -> dict[str, str]:
    raw = await cache_get(RESTAURANT_CONTEXT_JSON_KEY.format(user_id=user_id))
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return {k: str(v) for k, v in parsed.items() if v is not None}
    return {}


def _build_name_location(profile: dict[str, str]) -> str | None:
    name_location = profile.get("nameLocation")
    if name_location:
        return name_location

    name = profile.get("restaurantName", "").strip()
    city = profile.get("city", "").strip()
    if name and city:
        return f"{name}, {city}"
    if name:
        return name
    return None


def _build_restaurant_context(profile: dict[str, str]) -> str | None:
    lines: list[str] = []
    name = profile.get("restaurantName", "").strip()
    tagline = profile.get("tagline", "").strip()
    phone = profile.get("phone", "").strip()
    city = profile.get("city", "").strip()
    greeting = profile.get("greeting", "").strip()
    name_location = _build_name_location(profile)

    if name:
        lines.append(f"Restaurant name: {name}")
    if name_location:
        lines.append(f"Location: {name_location}")
    if city:
        lines.append(f"City: {city}")
    if phone:
        lines.append(f"Phone: {phone}")
    if tagline:
        lines.append(f"Tagline: {tagline}")
    if greeting:
        lines.append(f"Greeting: {greeting}")

    if lines:
        return "\n".join(lines)
    return None


class StateHandlerFactory:
    def __init__(self, ai: ChatbotAI):
        self._ai = ai
        self._food_order_factory = FoodOrderHandlerFactory(ai=ai)
        self._handlers = {
            ConversationState.GREETING: self._handle_greeting,
            ConversationState.FAREWELL: self._handle_farewell,
            ConversationState.VAGUE_MESSAGE: self._handle_vague_message,
            ConversationState.RESTAURANT_QUESTION: self._handle_restaurant_question,
            ConversationState.MENU_QUESTION: self._handle_menu_question,
            ConversationState.FOOD_ORDER: self._handle_food_order,
            ConversationState.FINALIZING_ORDER: self._handle_food_order,
            ConversationState.PICKUP_PING: self._handle_pickup_ping,
            ConversationState.MISC: self._handle_misc,
            ConversationState.HUMAN_ESCALATION: self._handle_human_escalation,
        }

    async def handle(self, state: ConversationState, request: BotMessageRequest) -> BotMessageResponse:
        handler = self._handlers.get(state)
        if handler is None:
            raise UnhandledStateError(f"No handler registered for state: '{state}'")
        return await handler(request)

    async def _handle_greeting(self, request: BotMessageRequest) -> BotMessageResponse:
        restaurant_name_location = await cache_get(
            RESTAURANT_NAME_LOCATION_KEY.format(user_id=request.user_id)
        )
        if not restaurant_name_location:
            profile_json = await _get_restaurant_profile_json(request.user_id)
            profile_fields = await _get_restaurant_profile_fields(request.user_id)
            merged_profile = {**profile_fields, **profile_json}
            restaurant_name_location = _build_name_location(merged_profile)

        restaurant_name_location = restaurant_name_location or RESTAURANT_NAME_LOCATION_FALLBACK

        parts = restaurant_name_location.split(',', 1)
        if len(parts) == 2:
            welcome_msg = f"Welcome to {parts[0].strip()} located at {parts[1].strip()}! What's your name and what can I get for you today?"
        else:
            welcome_msg = f"Welcome to {parts[0].strip()}! What's your name and what can I get for you today?"
        return BotMessageResponse(
            chatbot_message=welcome_msg,
            order_state=request.order_state,
        )

    async def _handle_farewell(self, request: BotMessageRequest) -> BotMessageResponse:
        message = await self._ai.handle_farewell(
            latest_message=request.latest_message,
            message_history=request.message_history,
        )
        return BotMessageResponse(chatbot_message=message, order_state=request.order_state)

    async def _handle_vague_message(self, request: BotMessageRequest) -> BotMessageResponse:
        message = await self._ai.ask_clarifying_question(
            latest_message=request.latest_message,
            message_history=request.message_history,
        )
        return BotMessageResponse(chatbot_message=message, order_state=request.order_state)

    async def _handle_restaurant_question(self, request: BotMessageRequest) -> BotMessageResponse:
        restaurant_context = await cache_get(
            RESTAURANT_CONTEXT_KEY.format(user_id=request.user_id)
        )
        if not restaurant_context:
            profile_json = await _get_restaurant_profile_json(request.user_id)
            profile_fields = await _get_restaurant_profile_fields(request.user_id)
            merged_profile = {**profile_fields, **profile_json}
            restaurant_context = _build_restaurant_context(merged_profile)

        restaurant_context = restaurant_context or RESTAURANT_CONTEXT_FALLBACK

        message = await self._ai.answer_restaurant_question(
            latest_message=request.latest_message,
            restaurant_context=restaurant_context,
            message_history=request.message_history,
        )
        return BotMessageResponse(chatbot_message=message, order_state=request.order_state)

    async def _handle_menu_question(self, request: BotMessageRequest) -> BotMessageResponse:
        menu_context = await cache_get(
            MENU_CONTEXT_KEY.format(user_id=request.user_id)
        ) or MENU_CONTEXT_FALLBACK

        message = await self._ai.answer_menu_question(
            latest_message=request.latest_message,
            menu_context=menu_context,
            message_history=request.message_history,
        )
        return BotMessageResponse(chatbot_message=message, order_state=request.order_state)

    async def _handle_food_order(self, request: BotMessageRequest) -> BotMessageResponse:
        response = await self._food_order_factory.handle(request)
        if not response.has_pending_clarification:
            has_items = bool((response.order_state or {}).get("items"))

            if has_items:
                try:
                    supervision = await self._ai.supervise_order_state(
                        proposed_order_state=response.order_state or {},
                        latest_message=request.latest_message,
                        message_history=request.message_history,
                        has_pending_clarification=response.has_pending_clarification,
                    )
                    if not supervision.is_correct and supervision.corrected_items is not None:
                        response.order_state = {"items": supervision.corrected_items}
                except Exception:
                    pass  # supervision failure is non-fatal; pass through unchanged

            polished = await self._ai.polish_food_order_reply(
                order_state=response.order_state or {},
                latest_message=request.latest_message,
                message_history=request.message_history,
            )
            response.chatbot_message = polished
            response.awaiting_order_confirmation = bool((response.order_state or {}).get("items"))
        return response

    async def _handle_pickup_ping(self, request: BotMessageRequest) -> BotMessageResponse:
        return BotMessageResponse(chatbot_message=ConversationState.PICKUP_PING, pickup_ping=True, order_state=request.order_state)

    async def _handle_human_escalation(self, request: BotMessageRequest) -> BotMessageResponse:
        return BotMessageResponse(
            chatbot_message="Of course! I'm calling a staff member over to help you now.",
            order_state=request.order_state,
            ping_for_human=True,
        )

    async def _handle_misc(self, request: BotMessageRequest) -> BotMessageResponse:
        message = await self._ai.handle_misc(
            latest_message=request.latest_message,
            message_history=request.message_history,
        )
        return BotMessageResponse(chatbot_message=message, order_state=request.order_state)
