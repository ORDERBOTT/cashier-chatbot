from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from src import firebase as _firebase
from src.chatbot import gemini_client
from src.chatbot.constants import _PARSE_VALIDATION_ERROR_PREFIX
from src.chatbot.exceptions import AIServiceError
from src.chatbot.llm_messages import LLMMessage
from src.chatbot.promptsv2 import (
    DEFAULT_EXECUTION_AGENT_SYSTEM_PROMPT,
    DEFAULT_PARSING_AGENT_PROMPTS,
)
from src.chatbot.schema import (
    ChatbotV2MessageRequest,
    ChatbotV2MessageResponse,
    CurrentOrderDetails,
    CurrentOrderLineItem,
    ExecutionAgentContext,
    ExecutionAgentPromptContext,
    ExecutionAgentResult,
    ExecutionAgentToolDescriptor,
    ParsedRequestConfidenceLevel,
    ParsedRequestIntent,
    ParsedRequestItem,
    ParsedRequestsPayload,
    PreparedExecutionContext,
    ParsingAgentContext,
    ParsingAgentPromptContext,
    ParsingAgentResult,
    ParsingAgentPrompts,
)
from src.chatbot.tools import (
    addItemsToOrder,
    cancelOrder,
    changeItemQuantity,
    check_item_availability,
    confirmOrder,
    findClosestMenuItems,
    getOrderLineItems,
    getPreviousKMessages,
    prepare_clover_data,
    removeItemFromOrder,
    summarizeConversationHistory,
)
from src.config import settings

_EXECUTION_AGENT_SYSTEM_PROMPT = DEFAULT_EXECUTION_AGENT_SYSTEM_PROMPT
_OUTSIDE_SCOPE_REPLY = (
    "I can help with food orders, menu questions, and pickup details."
)
_ESCALATION_REPLY = "A human team member will need to help with that request."
_GENERIC_ORDER_REPLY = "What would you like to order?"
_GENERIC_MENU_REPLY = "Which menu item are you asking about?"
_GENERIC_RESTAURANT_REPLY = "I can help with menu items and your order. For restaurant details, please contact the store."
_GENERIC_PICKUP_REPLY = (
    "I can help with pickup timing once your order is ready to place."
)
_GENERIC_MODIFICATION_REPLY = "I need a bit more detail to update that item correctly."
_GENERIC_REPLACE_REPLY = (
    "Please tell me which current item to replace and what you want instead."
)
_GENERIC_CONFIRM_REPLY = "Please confirm if you want me to place the order."
_GENERIC_CANCEL_REPLY = "Please confirm if you want me to cancel the order."
_GENERIC_EMPTY_ORDER_CONFIRM_REPLY = "Your order is empty right now."
_UNAVAILABLE_REPLY_TEMPLATE = "{item_name} is not available right now."
_MISSING_MENU_ITEM_REPLY_TEMPLATE = "I couldn't find {item_name} on the menu."
_LOW_CONFIDENCE_REPLY_TEMPLATE = 'I want to make sure I understood "{request_details}". Can you clarify that request?'
_AMBIGUOUS_ITEM_REPLY_TEMPLATE = (
    'When you said "{item_name}", did you mean it as a separate item or as a modifier?'
)
_ACTION_ADDED_TEMPLATE = "added {quantity} x {item_name}"
_ACTION_REMOVED_TEMPLATE = "removed {item_name}"
_ACTION_CHANGED_QUANTITY_TEMPLATE = "changed {item_name} quantity to {new_quantity}"
_ACTION_CONFIRMED_ORDER = "confirmed order"
_ACTION_CANCELLED_ORDER = "cancelled order"
_CONFIRMATION_WORDS = frozenset(
    {
        "yes",
        "yeah",
        "yep",
        "yup",
        "confirm",
        "confirmed",
        "go ahead",
        "sounds good",
        "all set",
        "that is right",
        "thats right",
        "correct",
        "please do",
        "do it",
    }
)
_INGREDIENT_AMBIGUITY_NAMES = frozenset(
    {
        "bacon",
        "cheese",
        "mayo",
        "pickles",
        "onions",
        "jalapenos",
        "sauce",
        "gravy",
        "ranch",
    }
)

_FIND_CLOSEST_MENU_ITEMS_PARAMETERS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "item_name": {
            "type": "string",
            "description": "The item name exactly as the customer said it.",
        },
        "details": {
            "type": ["string", "null"],
            "description": "Optional modifiers or qualifiers that may help disambiguate the menu item.",
        },
    },
    "required": ["item_name"],
    "additionalProperties": False,
}
_CHECK_ITEM_AVAILABILITY_PARAMETERS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "item_id": {
            "type": "string",
            "description": "The Clover item id returned from menu matching.",
        }
    },
    "required": ["item_id"],
    "additionalProperties": False,
}
_ADD_ITEMS_TO_ORDER_PARAMETERS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "itemId": {"type": "string"},
                    "quantity": {"type": "integer", "minimum": 1},
                    "modifiers": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "note": {"type": ["string", "null"]},
                },
                "required": ["itemId"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}
_REMOVE_ITEM_FROM_ORDER_PARAMETERS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "target": {
            "type": "object",
            "properties": {
                "orderPosition": {"type": "integer", "minimum": 1},
                "itemName": {"type": "string"},
            },
            "additionalProperties": False,
        }
    },
    "required": ["target"],
    "additionalProperties": False,
}
_CHANGE_ITEM_QUANTITY_PARAMETERS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "target": {
            "type": "object",
            "properties": {
                "lineItemId": {"type": "string"},
                "orderPosition": {"type": "integer", "minimum": 1},
                "itemName": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "newQuantity": {"type": "integer", "minimum": 1},
    },
    "required": ["target", "newQuantity"],
    "additionalProperties": False,
}
_NO_ARGUMENTS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class ExecutionToolRuntime:
    context: ExecutionAgentContext


@dataclass(frozen=True, slots=True)
class ExecutionStepResult:
    reply_fragments: tuple[str, ...] = ()
    actions_executed: tuple[str, ...] = ()
    pending_clarifications: tuple[str, ...] = ()
    order_updated: bool = False


class Orchestrator:
    def __init__(
        self,
        *,
        parsing_agent: ParsingAgent | None = None,
        execution_agent: ExecutionAgent | None = None,
    ) -> None:
        self.parsing_agent = parsing_agent or ParsingAgent()
        self.execution_agent = execution_agent or ExecutionAgent()

    async def handle_message(
        self,
        request: ChatbotV2MessageRequest,
    ) -> ChatbotV2MessageResponse:
        context = await self._build_parsing_context(request)
        parsed_input = await self.parsing_agent.run(context=context)
        execution_context = await self._build_execution_context(request)
        prepared_context = self.prepare_agent_context(
            parsed_input=parsed_input,
            execution_context=execution_context,
        )
        tools = self.execution_agent.build_tools(
            ExecutionToolRuntime(context=execution_context)
        )
        execution_result = await self.execution_agent.run(
            parsed_requests=parsed_input.parsed_requests,
            context_object=prepared_context,
            tools=tools,
        )
        return ChatbotV2MessageResponse(
            system_response=execution_result.agent_reply,
            session_id=execution_result.session_id,
        )

    async def _build_parsing_context(
        self,
        request: ChatbotV2MessageRequest,
    ) -> ParsingAgentContext:
        current_order_details = await self._load_current_order_details(
            request.session_id
        )
        latest_k_messages_by_customer = await self._load_latest_k_customer_messages(
            request.session_id
        )
        summary_of_messages_before_k_by_customer = (
            await self._load_summary_of_messages_before_k(request.session_id)
        )
        return ParsingAgentContext(
            session_id=request.session_id,
            merchant_id=request.merchant_id,
            current_order_details=current_order_details,
            most_recent_message=request.user_message,
            latest_k_messages_by_customer=latest_k_messages_by_customer,
            summary_of_messages_before_k_by_customer=summary_of_messages_before_k_by_customer,
        )

    async def _load_current_order_details(self, session_id: str) -> CurrentOrderDetails:
        order_result = await getOrderLineItems(session_id)
        if not order_result.get("success"):
            return CurrentOrderDetails(
                order_id="",
                line_items=[],
                order_total=0,
                raw_error=order_result.get("error"),
            )

        line_items = [
            CurrentOrderLineItem(
                line_item_id=str(item.get("lineItemId", "")),
                name=str(item.get("name", "")),
                quantity=int(item.get("quantity", 0) or 0),
                price=int(item.get("price", 0) or 0),
            )
            for item in order_result.get("lineItems", [])
        ]
        return CurrentOrderDetails(
            order_id=str(order_result.get("orderId", "")),
            line_items=line_items,
            order_total=int(order_result.get("orderTotal", 0) or 0),
            raw_error=None,
        )

    async def _load_latest_k_customer_messages(self, session_id: str) -> list[str]:
        history_result = await getPreviousKMessages(
            session_id,
            settings.DEFAULT_PREVIOUS_MESSAGES_K,
        )
        if not history_result.get("success"):
            return []

        return [
            str(message.get("content", ""))
            for message in history_result.get("messages", [])
            if message.get("role") == "customer"
            and str(message.get("content", "")).strip()
        ]

    async def _load_summary_of_messages_before_k(self, session_id: str) -> str:
        summary_result = await summarizeConversationHistory(
            session_id,
            settings.DEFAULT_PREVIOUS_MESSAGES_K,
        )
        if not summary_result.get("success"):
            return ""
        return str(summary_result.get("summary", ""))

    async def _build_execution_context(
        self,
        request: ChatbotV2MessageRequest,
    ) -> ExecutionAgentContext:
        try:
            clover_creds = await prepare_clover_data(
                _firebase.firebaseDatabase, settings
            )
        except Exception as exc:
            return ExecutionAgentContext(
                session_id=request.session_id,
                merchant_id=request.merchant_id,
                clover_creds=None,
                clover_error=str(exc),
            )

        resolved_merchant_id = str(
            clover_creds.get("merchant_id") or request.merchant_id
        )
        return ExecutionAgentContext(
            session_id=request.session_id,
            merchant_id=resolved_merchant_id,
            clover_creds=clover_creds,
            clover_error=None,
        )

    def prepareAgentContext(
        self,
        *,
        parsed_input: ParsingAgentResult,
        execution_context: ExecutionAgentContext,
    ) -> PreparedExecutionContext:
        return self.prepare_agent_context(
            parsed_input=parsed_input,
            execution_context=execution_context,
        )

    def prepare_agent_context(
        self,
        *,
        parsed_input: ParsingAgentResult,
        execution_context: ExecutionAgentContext,
    ) -> PreparedExecutionContext:
        return PreparedExecutionContext(
            session_id=execution_context.session_id,
            merchant_id=execution_context.merchant_id,
            latest_customer_message=parsed_input.context.most_recent_message,
            current_order_details=parsed_input.context.current_order_details,
            latest_k_messages_by_customer=parsed_input.context.latest_k_messages_by_customer,
            summary_of_messages_before_k_by_customer=parsed_input.context.summary_of_messages_before_k_by_customer,
            clover_error=execution_context.clover_error,
        )


class ParsingAgent:
    def __init__(
        self,
        *,
        model: str | None = None,
        prompts: ParsingAgentPrompts | None = None,
    ) -> None:
        self.model = model or settings.PARSING_AGENT_GEMINI_MODEL
        self.prompts = prompts or DEFAULT_PARSING_AGENT_PROMPTS

    async def run(
        self,
        *,
        context: ParsingAgentContext,
        prompts: ParsingAgentPrompts | None = None,
    ) -> ParsingAgentResult:
        active_prompts = prompts or self.prompts

        try:
            parsed_requests = await self._generate_parse(
                context=context,
                prompts=active_prompts,
                strict_retry=False,
            )
        except AIServiceError as exc:
            if not self._should_retry_on_parse_error(exc):
                raise
            try:
                parsed_requests = await self._generate_parse(
                    context=context,
                    prompts=active_prompts,
                    strict_retry=True,
                )
            except AIServiceError as retry_exc:
                raise AIServiceError(
                    f"Parsing agent failed after retry: {retry_exc}"
                ) from retry_exc

        return ParsingAgentResult(
            context=context,
            parsed_requests=parsed_requests,
        )

    async def _generate_parse(
        self,
        *,
        context: ParsingAgentContext,
        prompts: ParsingAgentPrompts,
        strict_retry: bool,
    ) -> ParsedRequestsPayload:
        messages = self._build_messages(
            context=context,
            prompts=prompts,
            strict_retry=strict_retry,
        )
        return await gemini_client.generate_model(
            messages,
            ParsedRequestsPayload,
            temperature=0,
            model=self.model,
        )

    def _build_messages(
        self,
        *,
        context: ParsingAgentContext,
        prompts: ParsingAgentPrompts,
        strict_retry: bool,
    ) -> list[LLMMessage]:
        system_sections = [
            prompts.identity_prompt,
            prompts.input_you_receive_prompt,
            prompts.output_format_prompt,
            prompts.intent_labels_prompt,
            prompts.parsing_rules_prompt,
            prompts.few_shot_examples_prompt,
            prompts.final_reminders_prompt,
            prompts.internal_validation_prompt,
        ]
        if strict_retry:
            system_sections.append(prompts.strict_retry_prompt)
        system_prompt = "\n\n".join(
            section for section in system_sections if section.strip()
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self._render_context(context)},
        ]

    def _render_context(self, context: ParsingAgentContext) -> str:
        prompt_context = ParsingAgentPromptContext(
            current_order_details=context.current_order_details.model_dump(
                mode="json",
                exclude={"raw_error"},
            ),
            most_recent_message_by_customer=context.most_recent_message,
            latest_k_messages_by_customer=context.latest_k_messages_by_customer,
            summary_of_messages_before_k_by_customer=context.summary_of_messages_before_k_by_customer,
        )
        return json.dumps(prompt_context.model_dump(mode="json"), indent=2)

    def _should_retry_on_parse_error(self, error: AIServiceError) -> bool:
        return str(error).startswith(_PARSE_VALIDATION_ERROR_PREFIX)


class ExecutionAgent:
    def __init__(
        self,
        *,
        model: str | None = None,
        max_tool_calls: int | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.model = model or settings.EXECUTION_AGENT_GEMINI_MODEL
        self.max_tool_calls = (
            max_tool_calls
            if max_tool_calls is not None
            else settings.EXECUTION_AGENT_MAX_TOOL_CALLS
        )
        self.system_prompt = (
            _EXECUTION_AGENT_SYSTEM_PROMPT if system_prompt is None else system_prompt
        )

    async def run(
        self,
        *,
        parsed_requests: ParsedRequestsPayload,
        context_object: PreparedExecutionContext,
        tools: Sequence[gemini_client.GeminiFunctionTool] | None = None,
    ) -> ExecutionAgentResult:
        active_tools = list(tools or self.build_tools())
        deterministic_result = await self._run_deterministic_execution(
            parsed_requests=parsed_requests,
            context_object=context_object,
            tools=active_tools,
        )
        if not self.system_prompt.strip():
            return deterministic_result

        messages = self._build_messages(
            parsed_requests=parsed_requests,
            context_object=context_object,
            tools=active_tools,
        )
        generated_reply = await gemini_client.generate_text_with_tools(
            messages,
            function_tools=active_tools,
            temperature=0,
            max_tool_calls=self.max_tool_calls,
            model=self.model,
        )
        return ExecutionAgentResult(
            agent_reply=generated_reply,
            session_id=context_object.session_id,
            actions_executed=deterministic_result.actions_executed,
            pending_clarifications=deterministic_result.pending_clarifications,
            order_updated=deterministic_result.order_updated,
        )

    def _build_messages(
        self,
        *,
        parsed_requests: ParsedRequestsPayload,
        context_object: PreparedExecutionContext,
        tools: Sequence[gemini_client.GeminiFunctionTool],
    ) -> list[LLMMessage]:
        prompt_context = ExecutionAgentPromptContext(
            context_object=context_object.model_dump(mode="json"),
            parsed_requests=parsed_requests.model_dump(mode="json", by_alias=True)[
                "Data"
            ],
            tools=[
                ExecutionAgentToolDescriptor(
                    name=tool.name,
                    description=tool.description,
                ).model_dump(mode="json")
                for tool in tools
            ],
        )
        messages: list[LLMMessage] = [
            {
                "role": "user",
                "content": json.dumps(prompt_context.model_dump(mode="json"), indent=2),
            }
        ]
        if self.system_prompt.strip():
            messages.insert(0, {"role": "system", "content": self.system_prompt})
        return messages

    async def _run_deterministic_execution(
        self,
        *,
        parsed_requests: ParsedRequestsPayload,
        context_object: PreparedExecutionContext,
        tools: Sequence[gemini_client.GeminiFunctionTool],
    ) -> ExecutionAgentResult:
        tool_handlers = {tool.name: tool.handler for tool in tools}
        reply_fragments: list[str] = []
        actions_executed: list[str] = []
        pending_clarifications: list[str] = []
        order_updated = False

        for request in parsed_requests.data:
            step = await self._process_request(
                request=request,
                context_object=context_object,
                tool_handlers=tool_handlers,
            )
            reply_fragments.extend(step.reply_fragments)
            actions_executed.extend(step.actions_executed)
            pending_clarifications.extend(step.pending_clarifications)
            order_updated = order_updated or step.order_updated

        agent_reply = self._compose_agent_reply(
            reply_fragments=reply_fragments,
            actions_executed=actions_executed,
            pending_clarifications=pending_clarifications,
            parsed_requests=parsed_requests,
        )
        return ExecutionAgentResult(
            agent_reply=agent_reply,
            session_id=context_object.session_id,
            actions_executed=actions_executed,
            pending_clarifications=pending_clarifications,
            order_updated=order_updated,
        )

    async def _process_request(
        self,
        *,
        request: ParsedRequestItem,
        context_object: PreparedExecutionContext,
        tool_handlers: dict[str, Any],
    ) -> ExecutionStepResult:
        if request.intent == ParsedRequestIntent.OUTSIDE_AGENT_SCOPE:
            return ExecutionStepResult(reply_fragments=(_OUTSIDE_SCOPE_REPLY,))

        if request.intent == ParsedRequestIntent.ESCALATION:
            return ExecutionStepResult(reply_fragments=(_ESCALATION_REPLY,))

        if request.confidence_level == ParsedRequestConfidenceLevel.LOW:
            clarification = self._build_low_confidence_clarification(request)
            return ExecutionStepResult(
                reply_fragments=(clarification,),
                pending_clarifications=(clarification,),
            )

        if request.intent == ParsedRequestIntent.GREETING:
            return ExecutionStepResult(reply_fragments=(_GENERIC_ORDER_REPLY,))

        if request.intent == ParsedRequestIntent.MENU_QUESTION:
            return ExecutionStepResult(reply_fragments=(_GENERIC_MENU_REPLY,))

        if request.intent == ParsedRequestIntent.RESTAURANT_QUESTION:
            return ExecutionStepResult(reply_fragments=(_GENERIC_RESTAURANT_REPLY,))

        if request.intent == ParsedRequestIntent.PICKUPTIME_QUESTION:
            return ExecutionStepResult(reply_fragments=(_GENERIC_PICKUP_REPLY,))

        if request.intent == ParsedRequestIntent.MODIFY_ITEM:
            return ExecutionStepResult(reply_fragments=(_GENERIC_MODIFICATION_REPLY,))

        if request.intent == ParsedRequestIntent.REPLACE_ITEM:
            return ExecutionStepResult(reply_fragments=(_GENERIC_REPLACE_REPLY,))

        if request.intent == ParsedRequestIntent.CONFIRM_ORDER:
            return await self._handle_confirm_order(
                context_object=context_object,
                tool_handlers=tool_handlers,
            )

        if request.intent == ParsedRequestIntent.CANCEL_ORDER:
            return await self._handle_cancel_order(
                context_object=context_object,
                tool_handlers=tool_handlers,
            )

        if request.intent == ParsedRequestIntent.ADD_ITEM:
            return await self._handle_add_item(
                request=request,
                tool_handlers=tool_handlers,
            )

        if request.intent == ParsedRequestIntent.REMOVE_ITEM:
            return await self._handle_remove_item(
                request=request,
                tool_handlers=tool_handlers,
            )

        if request.intent == ParsedRequestIntent.CHANGE_ITEM_NUMBER:
            return await self._handle_change_item_number(
                request=request,
                tool_handlers=tool_handlers,
            )

        return ExecutionStepResult(reply_fragments=(_GENERIC_ORDER_REPLY,))

    async def _handle_add_item(
        self,
        *,
        request: ParsedRequestItem,
        tool_handlers: dict[str, Any],
    ) -> ExecutionStepResult:
        item_name = request.request_items.name.strip()
        if not item_name:
            clarification = self._build_low_confidence_clarification(request)
            return ExecutionStepResult(
                reply_fragments=(clarification,),
                pending_clarifications=(clarification,),
            )

        if self._needs_ingredient_clarification(item_name):
            clarification = _AMBIGUOUS_ITEM_REPLY_TEMPLATE.format(item_name=item_name)
            return ExecutionStepResult(
                reply_fragments=(clarification,),
                pending_clarifications=(clarification,),
            )

        menu_match = await tool_handlers["findClosestMenuItems"](
            item_name=item_name,
            details=request.request_items.details or None,
        )
        match_confidence = str(menu_match.get("match_confidence", "none"))
        if match_confidence == "none":
            clarification = _MISSING_MENU_ITEM_REPLY_TEMPLATE.format(
                item_name=item_name
            )
            return ExecutionStepResult(
                reply_fragments=(clarification,),
                pending_clarifications=(clarification,),
            )

        if match_confidence == "close" or menu_match.get("exact_match") is None:
            clarification = self._build_candidate_clarification(menu_match)
            return ExecutionStepResult(
                reply_fragments=(clarification,),
                pending_clarifications=(clarification,),
            )

        exact_match = menu_match.get("exact_match") or {}
        item_id = str(exact_match.get("id", "")).strip()
        if not item_id:
            clarification = _MISSING_MENU_ITEM_REPLY_TEMPLATE.format(
                item_name=item_name
            )
            return ExecutionStepResult(
                reply_fragments=(clarification,),
                pending_clarifications=(clarification,),
            )

        availability = await tool_handlers["checkItemAvailability"](item_id=item_id)
        if not availability.get("Available"):
            reply = _UNAVAILABLE_REPLY_TEMPLATE.format(
                item_name=str(availability.get("itemName") or item_name)
            )
            return ExecutionStepResult(reply_fragments=(reply,))

        quantity = max(1, int(request.request_items.quantity or 1))
        add_result = await tool_handlers["addItemsToOrder"](
            items=[
                {
                    "itemId": item_id,
                    "quantity": quantity,
                    "modifiers": [],
                    "note": request.request_items.details or None,
                }
            ]
        )
        if not add_result.get("success"):
            reply = self._tool_error_reply(
                add_result,
                fallback=f"I couldn't add {item_name} right now.",
            )
            return ExecutionStepResult(reply_fragments=(reply,))

        resolved_name = str(exact_match.get("name") or item_name)
        action = _ACTION_ADDED_TEMPLATE.format(
            quantity=quantity,
            item_name=resolved_name,
        )
        return ExecutionStepResult(
            reply_fragments=(f"Added {quantity} x {resolved_name}.",),
            actions_executed=(action,),
            order_updated=True,
        )

    async def _handle_remove_item(
        self,
        *,
        request: ParsedRequestItem,
        tool_handlers: dict[str, Any],
    ) -> ExecutionStepResult:
        item_name = request.request_items.name.strip()
        if not item_name:
            clarification = self._build_low_confidence_clarification(request)
            return ExecutionStepResult(
                reply_fragments=(clarification,),
                pending_clarifications=(clarification,),
            )

        remove_result = await tool_handlers["removeItemFromOrder"](
            target={"itemName": item_name}
        )
        if not remove_result.get("success"):
            reply = self._tool_error_reply(
                remove_result,
                fallback=f"I couldn't remove {item_name} right now.",
            )
            return ExecutionStepResult(reply_fragments=(reply,))

        removed_name = str(
            (remove_result.get("removedItem") or {}).get("name") or item_name
        )
        return ExecutionStepResult(
            reply_fragments=(f"Removed {removed_name}.",),
            actions_executed=(_ACTION_REMOVED_TEMPLATE.format(item_name=removed_name),),
            order_updated=True,
        )

    async def _handle_change_item_number(
        self,
        *,
        request: ParsedRequestItem,
        tool_handlers: dict[str, Any],
    ) -> ExecutionStepResult:
        item_name = request.request_items.name.strip()
        if not item_name:
            clarification = self._build_low_confidence_clarification(request)
            return ExecutionStepResult(
                reply_fragments=(clarification,),
                pending_clarifications=(clarification,),
            )

        quantity_result = await tool_handlers["changeItemQuantity"](
            target={"itemName": item_name},
            newQuantity=max(1, int(request.request_items.quantity or 1)),
        )
        if not quantity_result.get("success"):
            reply = self._tool_error_reply(
                quantity_result,
                fallback=f"I couldn't change the quantity for {item_name} right now.",
            )
            return ExecutionStepResult(reply_fragments=(reply,))

        resolved_name = str(quantity_result.get("itemName") or item_name)
        new_quantity = int(quantity_result.get("newQuantity") or 0)
        return ExecutionStepResult(
            reply_fragments=(f"Updated {resolved_name} to {new_quantity}.",),
            actions_executed=(
                _ACTION_CHANGED_QUANTITY_TEMPLATE.format(
                    item_name=resolved_name,
                    new_quantity=new_quantity,
                ),
            ),
            order_updated=True,
        )

    async def _handle_confirm_order(
        self,
        *,
        context_object: PreparedExecutionContext,
        tool_handlers: dict[str, Any],
    ) -> ExecutionStepResult:
        if not context_object.current_order_details.line_items:
            return ExecutionStepResult(
                reply_fragments=(_GENERIC_EMPTY_ORDER_CONFIRM_REPLY,)
            )

        if not self._is_confirmation_word(context_object.latest_customer_message):
            return ExecutionStepResult(
                reply_fragments=(_GENERIC_CONFIRM_REPLY,),
                pending_clarifications=(_GENERIC_CONFIRM_REPLY,),
            )

        confirm_result = await tool_handlers["confirmOrder"]()
        if not confirm_result.get("success"):
            reply = self._tool_error_reply(
                confirm_result,
                fallback="I couldn't place the order right now.",
            )
            return ExecutionStepResult(reply_fragments=(reply,))

        return ExecutionStepResult(
            reply_fragments=("Your order is confirmed.",),
            actions_executed=(_ACTION_CONFIRMED_ORDER,),
            order_updated=True,
        )

    async def _handle_cancel_order(
        self,
        *,
        context_object: PreparedExecutionContext,
        tool_handlers: dict[str, Any],
    ) -> ExecutionStepResult:
        if not self._is_confirmation_word(context_object.latest_customer_message):
            return ExecutionStepResult(
                reply_fragments=(_GENERIC_CANCEL_REPLY,),
                pending_clarifications=(_GENERIC_CANCEL_REPLY,),
            )

        cancel_result = await tool_handlers["cancelOrder"]()
        if not cancel_result.get("success"):
            reply = self._tool_error_reply(
                cancel_result,
                fallback="I couldn't cancel the order right now.",
            )
            return ExecutionStepResult(reply_fragments=(reply,))

        return ExecutionStepResult(
            reply_fragments=("Your order has been cancelled.",),
            actions_executed=(_ACTION_CANCELLED_ORDER,),
            order_updated=True,
        )

    def _compose_agent_reply(
        self,
        *,
        reply_fragments: list[str],
        actions_executed: list[str],
        pending_clarifications: list[str],
        parsed_requests: ParsedRequestsPayload,
    ) -> str:
        unique_fragments: list[str] = []
        for fragment in reply_fragments:
            normalized = fragment.strip()
            if normalized and normalized not in unique_fragments:
                unique_fragments.append(normalized)

        if unique_fragments:
            return " ".join(unique_fragments)

        if actions_executed:
            return "Done."

        if any(
            item.intent == ParsedRequestIntent.OUTSIDE_AGENT_SCOPE
            for item in parsed_requests.data
        ):
            return _OUTSIDE_SCOPE_REPLY

        if pending_clarifications:
            return " ".join(dict.fromkeys(pending_clarifications))

        return _GENERIC_ORDER_REPLY

    def _build_low_confidence_clarification(self, request: ParsedRequestItem) -> str:
        details = request.request_details.strip() or request.request_items.name.strip()
        return _LOW_CONFIDENCE_REPLY_TEMPLATE.format(request_details=details)

    def _build_candidate_clarification(self, menu_match: dict[str, Any]) -> str:
        candidate_names = [
            str(candidate.get("name", "")).strip()
            for candidate in menu_match.get("candidates", [])
            if str(candidate.get("name", "")).strip()
        ]
        if not candidate_names:
            return "I need a bit more detail to match that item on the menu."
        if len(candidate_names) == 1:
            return f'Did you mean "{candidate_names[0]}"?'
        joined = ", ".join(candidate_names[:-1]) + f", or {candidate_names[-1]}"
        return f"Did you mean {joined}?"

    def _tool_error_reply(self, result: dict[str, Any], *, fallback: str) -> str:
        error = str(result.get("error") or "").strip()
        return error or fallback

    def _is_confirmation_word(self, latest_message: str) -> bool:
        normalized = re.sub(r"[^a-z0-9\s]", "", latest_message.lower()).strip()
        normalized = " ".join(normalized.split())
        return normalized in _CONFIRMATION_WORDS

    def _needs_ingredient_clarification(self, item_name: str) -> bool:
        return item_name.lower().strip() in _INGREDIENT_AMBIGUITY_NAMES

    def _merge_results(
        self,
        *,
        deterministic_result: ExecutionAgentResult,
        generated_result: ExecutionAgentResult,
        session_id: str,
    ) -> ExecutionAgentResult:
        agent_reply = (
            generated_result.agent_reply.strip() or deterministic_result.agent_reply
        )
        actions_executed = list(
            dict.fromkeys(
                [
                    *deterministic_result.actions_executed,
                    *generated_result.actions_executed,
                ]
            )
        )
        pending_clarifications = list(
            dict.fromkeys(
                [
                    *deterministic_result.pending_clarifications,
                    *generated_result.pending_clarifications,
                ]
            )
        )
        return ExecutionAgentResult(
            agent_reply=agent_reply,
            session_id=session_id,
            actions_executed=actions_executed,
            pending_clarifications=pending_clarifications,
            order_updated=deterministic_result.order_updated
            or generated_result.order_updated,
        )

    def build_tools(
        self,
        runtime: ExecutionToolRuntime | None = None,
    ) -> list[gemini_client.GeminiFunctionTool]:
        runtime = runtime or ExecutionToolRuntime(
            context=ExecutionAgentContext(session_id="", merchant_id="")
        )
        return self._build_tools(runtime)

    def _build_tools(
        self,
        runtime: ExecutionToolRuntime,
    ) -> list[gemini_client.GeminiFunctionTool]:
        async def _find_closest_menu_items_tool(
            *,
            item_name: str,
            details: str | None = None,
        ) -> dict[str, Any]:
            if runtime.context.clover_creds is None:
                return {
                    "success": False,
                    "error": runtime.context.clover_error
                    or "Clover credentials unavailable.",
                    "exact_match": None,
                    "candidates": [],
                    "match_confidence": "none",
                }

            return await findClosestMenuItems(
                item_name=item_name,
                details=details,
                merchant_id=runtime.context.merchant_id,
                creds=runtime.context.clover_creds,
            )

        async def _check_item_availability_tool(*, item_id: str) -> dict[str, Any]:
            return await check_item_availability(
                item_id=item_id,
                merchant_id=runtime.context.merchant_id,
            )

        async def _add_items_to_order_tool(*, items: list[dict]) -> dict[str, Any]:
            return await addItemsToOrder(runtime.context.session_id, items)

        async def _remove_item_from_order_tool(*, target: dict) -> dict[str, Any]:
            return await removeItemFromOrder(runtime.context.session_id, target)

        async def _change_item_quantity_tool(
            *,
            target: dict,
            newQuantity: int,
        ) -> dict[str, Any]:
            return await changeItemQuantity(
                runtime.context.session_id,
                target,
                newQuantity,
            )

        async def _confirm_order_tool() -> dict[str, Any]:
            return await confirmOrder(runtime.context.session_id)

        async def _cancel_order_tool() -> dict[str, Any]:
            return await cancelOrder(runtime.context.session_id)

        return [
            gemini_client.GeminiFunctionTool(
                name="findClosestMenuItems",
                description=(
                    "Resolve a customer-mentioned food item against the live menu "
                    "and return exact or close menu matches."
                ),
                parameters_json_schema=_FIND_CLOSEST_MENU_ITEMS_PARAMETERS_JSON_SCHEMA,
                handler=_find_closest_menu_items_tool,
            ),
            gemini_client.GeminiFunctionTool(
                name="checkItemAvailability",
                description="Check whether a concrete menu item can be ordered right now.",
                parameters_json_schema=_CHECK_ITEM_AVAILABILITY_PARAMETERS_JSON_SCHEMA,
                handler=_check_item_availability_tool,
            ),
            gemini_client.GeminiFunctionTool(
                name="addItemsToOrder",
                description="Add one or more resolved menu items to the current order.",
                parameters_json_schema=_ADD_ITEMS_TO_ORDER_PARAMETERS_JSON_SCHEMA,
                handler=_add_items_to_order_tool,
            ),
            gemini_client.GeminiFunctionTool(
                name="removeItemFromOrder",
                description="Remove an existing item from the current order.",
                parameters_json_schema=_REMOVE_ITEM_FROM_ORDER_PARAMETERS_JSON_SCHEMA,
                handler=_remove_item_from_order_tool,
            ),
            gemini_client.GeminiFunctionTool(
                name="changeItemQuantity",
                description="Change the quantity of an item already in the current order.",
                parameters_json_schema=_CHANGE_ITEM_QUANTITY_PARAMETERS_JSON_SCHEMA,
                handler=_change_item_quantity_tool,
            ),
            gemini_client.GeminiFunctionTool(
                name="confirmOrder",
                description="Submit the current order after explicit customer confirmation.",
                parameters_json_schema=_NO_ARGUMENTS_JSON_SCHEMA,
                handler=_confirm_order_tool,
            ),
            gemini_client.GeminiFunctionTool(
                name="cancelOrder",
                description="Cancel the current order after explicit customer confirmation.",
                parameters_json_schema=_NO_ARGUMENTS_JSON_SCHEMA,
                handler=_cancel_order_tool,
            ),
        ]
