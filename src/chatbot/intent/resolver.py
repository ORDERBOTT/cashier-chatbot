from typing import Literal
from src.chatbot.constants import ConversationState, FoodOrderState, ModifierState
from src.chatbot.exceptions import AIServiceError
from src.chatbot.intent.ai_client import (
    analyze_food_order_intent,
    analyze_modifier_state_intent,
    detect_user_intent,
    verify_food_order_state,
    verify_modifier_state,
)
from src.chatbot.intent.transitions import (
    VALID_FOOD_ORDER_TRANSITIONS,
    VALID_TRANSITIONS,
    _ALL_FOOD_STATES,
    _ALL_STATES,
)
from src.chatbot.schema import Message
from src.chatbot.utils import _parse_food_order_state, _parse_modifier_state


class ConversationStateResolver:

    async def detectConversationState(self, latest_message: str, message_history: list[Message] | None, previous_state: ConversationState | None,) -> tuple[ConversationState, str | None]:
        analysis = await detect_user_intent(
            latest_message=latest_message,
            message_history=message_history,
            previous_state=previous_state.value if previous_state else None,
        )
        print("conversation state analysis", analysis)

        # Might be a little too strict, but we don't want to be too lenient with the state transitions.
        if await self._is_valid_intent_transition(previous_state, analysis.state, analysis.confidence):
            return analysis.state, analysis.name

        return ConversationState.VAGUE_MESSAGE, analysis.name
    
    async def _is_valid_intent_transition(self, previous: ConversationState | None, proposed: ConversationState | None, confidence: Literal["high", "medium", "low"] | None) -> bool:
        if confidence != "high":
            return False
        if proposed is ConversationState.HUMAN_ESCALATION:
            return True

        allowed = VALID_TRANSITIONS.get(previous, _ALL_STATES)
        return proposed in allowed


class FoodOrderStateResolver:
    def _is_valid_transition(
        self,
        previous: FoodOrderState | None,
        proposed: FoodOrderState | None,
    ) -> bool:
        if proposed is None:
            return False
        allowed = VALID_FOOD_ORDER_TRANSITIONS.get(previous, _ALL_FOOD_STATES)
        return proposed in allowed

    async def resolve(
        self,
        latest_message: str,
        order_state: dict,
        message_history: list[Message] | None,
        previous_food_order_state: FoodOrderState | None,
    ) -> FoodOrderState:
        analysis = await analyze_food_order_intent(
            latest_message=latest_message,
            order_state=order_state,
            message_history=message_history,
            previous_food_order_state=(
                previous_food_order_state.value if previous_food_order_state else None
            ),
        )
        print("food order analysis", analysis)

        proposed = _parse_food_order_state(analysis.state)
        transition_valid = self._is_valid_transition(previous_food_order_state, proposed)

        # Fast path
        if analysis.confidence == "high" and transition_valid and proposed is not None:
            return proposed

        # Slow path — independent verifier
        try:
            verification = await verify_food_order_state(
                latest_message=latest_message,
                order_state=order_state,
                message_history=message_history,
                proposed_state=analysis.state,
                previous_food_order_state=(
                    previous_food_order_state.value if previous_food_order_state else None
                ),
                transition_valid=transition_valid,
                analysis_reasoning=analysis.reasoning,
            )
        except AIServiceError:
            raise
        except Exception:
            verification = None

        if verification is not None:
            if verification.confirmed and proposed is not None:
                return proposed
            if verification.corrected_state:
                corrected = _parse_food_order_state(verification.corrected_state)
                if corrected is not None:
                    return corrected

        # Fallback chain: alternative → add_to_order
        if analysis.alternative:
            alt = _parse_food_order_state(analysis.alternative)
            if alt is not None:
                return alt

        return FoodOrderState.ADD_TO_ORDER


class ModifierStateResolver:
    async def resolve(
        self,
        latest_message: str,
        order_state: dict,
        message_history: list[Message] | None,
    ) -> ModifierState:
        analysis = await analyze_modifier_state_intent(
            latest_message=latest_message,
            order_state=order_state,
            message_history=message_history,
        )
        proposed = _parse_modifier_state(analysis.state)

        if analysis.confidence == "high" and proposed is not None:
            return proposed

        try:
            verification = await verify_modifier_state(
                latest_message=latest_message,
                order_state=order_state,
                message_history=message_history,
                proposed_state=analysis.state,
                analysis_reasoning=analysis.reasoning,
            )
        except AIServiceError:
            raise
        except Exception:
            verification = None

        if verification is not None:
            if verification.confirmed and proposed is not None:
                return proposed
            if verification.corrected_state:
                corrected = _parse_modifier_state(verification.corrected_state)
                if corrected is not None:
                    return corrected

        if analysis.alternative:
            alt = _parse_modifier_state(analysis.alternative)
            if alt is not None:
                return alt

        return ModifierState.NEW_MODIFIER
