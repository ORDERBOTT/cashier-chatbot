from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
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
    ParsedRequestsPayload,
    PreparedExecutionContext,
    ParsingAgentContext,
    ParsingAgentPromptContext,
    ParsingAgentResult,
    ParsingAgentPrompts,
)
from src.chatbot.tools import (
    addItemsToOrder,
    calcOrderPrice,
    cancelOrder,
    changeItemQuantity,
    checkIfModifierOrAddOn,
    check_item_availability,
    confirmOrder,
    findClosestMenuItems,
    get_item_details,
    getMenuLink,
    getItemsNotAvailableToday,
    getOrderLineItems,
    getPreviousKMessages,
    getPreviousOrdersDetails,
    humanInterventionNeeded,
    prepare_clover_data,
    replaceItemInOrder,
    removeItemFromOrder,
    requestPickupTime,
    summarizeConversationHistory,
    updateItemInOrder,
    validateModifications,
)
from datetime import datetime, timezone

from src.cache import cache_list_append
from src.chatbot.utils import _session_messages_redis_key
from src.config import settings

_EXECUTION_AGENT_SYSTEM_PROMPT = DEFAULT_EXECUTION_AGENT_SYSTEM_PROMPT

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
_GET_ITEM_DETAILS_PARAMETERS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "itemId": {
            "type": "string",
            "description": "The Clover item id to inspect.",
        }
    },
    "required": ["itemId"],
    "additionalProperties": False,
}
_VALIDATE_MODIFICATIONS_PARAMETERS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "itemId": {
            "type": "string",
            "description": "The Clover item id for the current menu item.",
        },
        "requestedModifications": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Raw modifier phrases exactly as the customer said them.",
        },
    },
    "required": ["itemId", "requestedModifications"],
    "additionalProperties": False,
}
_CHECK_MODIFIER_OR_ADDON_PARAMETERS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "itemId": {
            "type": "string",
            "description": "The Clover item id for the current menu item.",
        },
        "requestedModification": {
            "type": "string",
            "description": "One free-text modification request from the customer.",
        },
    },
    "required": ["itemId", "requestedModification"],
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
_REPLACE_ITEM_IN_ORDER_PARAMETERS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "replacement": {
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
        "lineItemId": {"type": "string"},
        "orderPosition": {"type": "integer", "minimum": 1},
        "itemName": {"type": "string"},
    },
    "required": ["replacement"],
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
_UPDATE_ITEM_IN_ORDER_PARAMETERS_JSON_SCHEMA: dict[str, Any] = {
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
        "updates": {
            "type": "object",
            "properties": {
                "addModifiers": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "removeModifiers": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "note": {"type": ["string", "null"]},
            },
            "additionalProperties": False,
        },
    },
    "required": ["target", "updates"],
    "additionalProperties": False,
}
_NO_ARGUMENTS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
_GET_MENU_LINK_PARAMETERS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
_GET_ITEMS_NOT_AVAILABLE_TODAY_PARAMETERS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
_HUMAN_INTERVENTION_NEEDED_PARAMETERS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reason": {
            "type": "string",
            "description": "Short plain-text description of why human intervention is needed.",
        }
    },
    "required": ["reason"],
    "additionalProperties": False,
}
_GET_PREVIOUS_ORDERS_DETAILS_PARAMETERS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "limit": {
            "type": "integer",
            "description": "Maximum number of past orders to return. Defaults to 3.",
        }
    },
    "additionalProperties": False,
}
_REQUEST_PICKUP_TIME_PARAMETERS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "requested_time": {
            "type": ["string", "null"],
            "description": "Free-text pickup time from the customer, or null to read existing preference.",
        }
    },
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class ExecutionToolRuntime:
    context: ExecutionAgentContext


@dataclass(slots=True)
class ExecutionTracker:
    actions_executed: list[str] = field(default_factory=list)
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
        execution_result = await self.execution_agent.run(
            parsed_requests=parsed_input.parsed_requests,
            context_object=prepared_context,
        )

        now = datetime.now(timezone.utc).isoformat()
        redis_key = _session_messages_redis_key(request.session_id)
        await cache_list_append(
            redis_key,
            json.dumps({"role": "user", "content": request.user_message, "timestamp": now}),
        )
        await cache_list_append(
            redis_key,
            json.dumps({"role": "assistant", "content": execution_result.agent_reply, "timestamp": now}),
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
            clover_creds=execution_context.clover_creds,
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
    ) -> ExecutionAgentResult:
        tracker = ExecutionTracker()
        runtime = ExecutionToolRuntime(
            context=ExecutionAgentContext(
                session_id=context_object.session_id,
                merchant_id=context_object.merchant_id,
                clover_creds=context_object.clover_creds,
                clover_error=context_object.clover_error,
            )
        )
        active_tools = self._build_tools(runtime, tracker=tracker)

        pending_clarifications = [
            item.request_details.strip()
            for item in parsed_requests.data
            if item.confidence_level == ParsedRequestConfidenceLevel.LOW
            and item.request_details.strip()
        ]

        messages = self._build_messages(
            parsed_requests=parsed_requests,
            context_object=context_object,
            tools=active_tools,
        )
        agent_reply = await gemini_client.generate_text_with_tools(
            messages,
            function_tools=active_tools,
            temperature=0,
            max_tool_calls=self.max_tool_calls,
            model=self.model,
        )

        return ExecutionAgentResult(
            agent_reply=agent_reply,
            session_id=context_object.session_id,
            actions_executed=tracker.actions_executed,
            pending_clarifications=pending_clarifications,
            order_updated=tracker.order_updated,
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
        tracker: ExecutionTracker | None = None,
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

        async def _get_item_details_tool(*, itemId: str) -> dict[str, Any]:
            return await get_item_details(
                item_id=itemId,
                merchant_id=runtime.context.merchant_id,
            )

        async def _validate_modifications_tool(
            *,
            itemId: str,
            requestedModifications: list[str],
        ) -> dict[str, Any]:
            return await validateModifications(
                itemId=itemId,
                merchantId=runtime.context.merchant_id,
                requestedModifications=requestedModifications,
            )

        async def _check_modifier_or_addon_tool(
            *,
            itemId: str,
            requestedModification: str,
        ) -> dict[str, Any]:
            return await checkIfModifierOrAddOn(
                itemId=itemId,
                merchantId=runtime.context.merchant_id,
                requestedModification=requestedModification,
            )

        async def _add_items_to_order_tool(*, items: list[dict]) -> dict[str, Any]:
            result = await addItemsToOrder(runtime.context.session_id, items)
            if result.get("success") and tracker is not None:
                for added in result.get("addedItems", []):
                    name = str(added.get("name", ""))
                    qty = int(added.get("quantity", 1) or 1)
                    tracker.actions_executed.append(f"added {qty}x {name}")
                tracker.order_updated = True
            return result

        async def _replace_item_in_order_tool(
            *,
            replacement: dict,
            lineItemId: str | None = None,
            orderPosition: int | None = None,
            itemName: str | None = None,
        ) -> dict[str, Any]:
            result = await replaceItemInOrder(
                runtime.context.session_id,
                replacement,
                lineItemId=lineItemId,
                orderPosition=orderPosition,
                itemName=itemName,
            )
            if result.get("success") and tracker is not None:
                removed = str((result.get("removedItem") or {}).get("name", ""))
                added = str((result.get("addedItem") or {}).get("name", ""))
                tracker.actions_executed.append(f"replaced {removed} with {added}")
                tracker.order_updated = True
            return result

        async def _remove_item_from_order_tool(*, target: dict) -> dict[str, Any]:
            result = await removeItemFromOrder(runtime.context.session_id, target)
            if result.get("success") and tracker is not None:
                name = str((result.get("removedItem") or {}).get("name", ""))
                tracker.actions_executed.append(f"removed {name}")
                tracker.order_updated = True
            return result

        async def _change_item_quantity_tool(
            *,
            target: dict,
            newQuantity: int,
        ) -> dict[str, Any]:
            result = await changeItemQuantity(
                runtime.context.session_id,
                target,
                newQuantity,
            )
            if result.get("success") and tracker is not None:
                name = str(result.get("itemName", ""))
                qty = int(result.get("newQuantity", newQuantity) or newQuantity)
                tracker.actions_executed.append(f"changed {name} to {qty}")
                tracker.order_updated = True
            return result

        async def _update_item_in_order_tool(
            *,
            target: dict,
            updates: dict,
        ) -> dict[str, Any]:
            result = await updateItemInOrder(runtime.context.session_id, target, updates)
            if result.get("success") and tracker is not None:
                name = str(result.get("itemName", ""))
                tracker.actions_executed.append(f"updated {name}")
                tracker.order_updated = True
            return result

        async def _calc_order_price_tool() -> dict[str, Any]:
            return await calcOrderPrice(runtime.context.session_id)

        async def _confirm_order_tool() -> dict[str, Any]:
            result = await confirmOrder(runtime.context.session_id)
            if result.get("success") and tracker is not None:
                tracker.actions_executed.append("confirmed order")
                tracker.order_updated = True
            return result

        async def _cancel_order_tool() -> dict[str, Any]:
            result = await cancelOrder(runtime.context.session_id)
            if result.get("success") and tracker is not None:
                tracker.actions_executed.append("cancelled order")
                tracker.order_updated = True
            return result

        async def _get_menu_link_tool() -> dict[str, Any]:
            return await getMenuLink(
                session_id=runtime.context.session_id,
                merchant_id=runtime.context.merchant_id,
                creds=runtime.context.clover_creds,
            )

        async def _get_items_not_available_today_tool() -> dict[str, Any]:
            return await getItemsNotAvailableToday(
                merchant_id=runtime.context.merchant_id,
                creds=runtime.context.clover_creds,
            )

        async def _human_intervention_needed_tool(*, reason: str) -> dict[str, Any]:
            return await humanInterventionNeeded(
                session_id=runtime.context.session_id,
                reason=reason,
            )

        async def _get_previous_orders_details_tool(
            *,
            limit: int | None = None,
        ) -> dict[str, Any]:
            return await getPreviousOrdersDetails(
                session_id=runtime.context.session_id,
                limit=limit or 3,
            )

        async def _request_pickup_time_tool(
            *,
            requested_time: str | None = None,
        ) -> dict[str, Any]:
            return await requestPickupTime(
                session_id=runtime.context.session_id,
                requested_time=requested_time,
            )

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
                name="getItemDetails",
                description="Return display details for one concrete menu item.",
                parameters_json_schema=_GET_ITEM_DETAILS_PARAMETERS_JSON_SCHEMA,
                handler=_get_item_details_tool,
            ),
            gemini_client.GeminiFunctionTool(
                name="validateModifications",
                description="Validate free-text modifier requests against one resolved menu item.",
                parameters_json_schema=_VALIDATE_MODIFICATIONS_PARAMETERS_JSON_SCHEMA,
                handler=_validate_modifications_tool,
            ),
            gemini_client.GeminiFunctionTool(
                name="checkIfModifierOrAddOn",
                description="Classify whether a free-text change is an existing modifier or should become a note.",
                parameters_json_schema=_CHECK_MODIFIER_OR_ADDON_PARAMETERS_JSON_SCHEMA,
                handler=_check_modifier_or_addon_tool,
            ),
            gemini_client.GeminiFunctionTool(
                name="addItemsToOrder",
                description="Add one or more resolved menu items to the current order.",
                parameters_json_schema=_ADD_ITEMS_TO_ORDER_PARAMETERS_JSON_SCHEMA,
                handler=_add_items_to_order_tool,
            ),
            gemini_client.GeminiFunctionTool(
                name="replaceItemInOrder",
                description="Replace one existing order item with another resolved menu item.",
                parameters_json_schema=_REPLACE_ITEM_IN_ORDER_PARAMETERS_JSON_SCHEMA,
                handler=_replace_item_in_order_tool,
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
                name="updateItemInOrder",
                description="Update modifiers and notes for an existing line item in the current order.",
                parameters_json_schema=_UPDATE_ITEM_IN_ORDER_PARAMETERS_JSON_SCHEMA,
                handler=_update_item_in_order_tool,
            ),
            gemini_client.GeminiFunctionTool(
                name="calcOrderPrice",
                description="Calculate the current order subtotal, tax, and total before confirmation.",
                parameters_json_schema=_NO_ARGUMENTS_JSON_SCHEMA,
                handler=_calc_order_price_tool,
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
            gemini_client.GeminiFunctionTool(
                name="getMenuLink",
                description="Return a shareable URL for the full menu. Use when customer asks to see the menu.",
                parameters_json_schema=_GET_MENU_LINK_PARAMETERS_JSON_SCHEMA,
                handler=_get_menu_link_tool,
            ),
            gemini_client.GeminiFunctionTool(
                name="getItemsNotAvailableToday",
                description="Return a list of menu items that are currently unavailable.",
                parameters_json_schema=_GET_ITEMS_NOT_AVAILABLE_TODAY_PARAMETERS_JSON_SCHEMA,
                handler=_get_items_not_available_today_tool,
            ),
            gemini_client.GeminiFunctionTool(
                name="humanInterventionNeeded",
                description="Flag the session for human review when the situation cannot be resolved automatically.",
                parameters_json_schema=_HUMAN_INTERVENTION_NEEDED_PARAMETERS_JSON_SCHEMA,
                handler=_human_intervention_needed_tool,
            ),
            gemini_client.GeminiFunctionTool(
                name="getPreviousOrdersDetails",
                description="Retrieve order history for the session. Use when customer asks about past orders.",
                parameters_json_schema=_GET_PREVIOUS_ORDERS_DETAILS_PARAMETERS_JSON_SCHEMA,
                handler=_get_previous_orders_details_tool,
            ),
            gemini_client.GeminiFunctionTool(
                name="requestPickupTime",
                description="Store or retrieve a pickup time preference for the session.",
                parameters_json_schema=_REQUEST_PICKUP_TIME_PARAMETERS_JSON_SCHEMA,
                handler=_request_pickup_time_tool,
            ),
        ]
