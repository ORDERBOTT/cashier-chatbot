from enum import Enum

class ConversationState(str, Enum):
    GREETING = "greeting"
    FAREWELL = "farewell"
    VAGUE_MESSAGE = "vague_message"
    RESTAURANT_QUESTION = "restaurant_question"
    MENU_QUESTION = "menu_question"
    FOOD_ORDER = "food_order"
    PICKUP_PING = "pickup_ping"
    PICKUP_TIME_SUGGESTION = "pickup_time_suggestion"
    MISC = "misc"
    HUMAN_ESCALATION = "human_escalation"
    ORDER_COMPLETE = "order_complete"
    ORDER_REVIEW = "order_review"


SUMMARIZATION_THRESHOLD = 10          # compress when history exceeds this
SUMMARIZATION_TAIL_MESSAGES = 4       # keep this many recent messages verbatim
CONVERSATION_SUMMARY_TTL = 60 * 60 * 4  # 4 hours in seconds

_PARSE_VALIDATION_ERROR_PREFIX = "Failed to parse Gemini structured response:"

_MENU_AVAILABILITY_STALE_SECONDS = 90
_HARDCODED_SALES_TAX_PERCENT = 9
_COOKING_PREFERENCE_HINTS = (
    "rare",
    "medium",
    "well",
    "done",
    "crispy",
    "grilled",
    "fried",
    "seared",
)
_COOKING_MODIFIER_HINTS = (
    "patty",
    "cook",
    "temp",
    "temperature",
    "protein",
    "beef",
    "steak",
    "burger",
)

_MENU_CACHE_VERSION = (
    4  # bump when normalized shape changes (e.g. new index keys added)
)

# How long we keep the Clover order id in Redis for a chat session (seconds).
_SESSION_CLOVER_ORDER_REDIS_TTL_SECONDS = 3 * 60 * 60
_SUMMARIZE_HISTORY_MAX_OUTPUT_TOKENS = 180