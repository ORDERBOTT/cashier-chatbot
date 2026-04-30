from __future__ import annotations

import json
from typing import Any

from src.chatbot import llm_client
from src.chatbot.guarded_tools import (
    confirmOrder_guarded,
    humanInterventionNeeded_idempotent,
)
from src.chatbot.schema import ComposerInput
from src.chatbot.tools import (
    askingForPickupTime,
    askingForWaitTime,
    getHumanProfile,
    saveHumanName,
    suggestedPickupTime,
)


_SAVE_HUMAN_NAME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "The customer's name exactly as they provided it.",
        }
    },
    "required": ["name"],
    "additionalProperties": False,
}

_NO_ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

_SUGGESTED_PICKUP_TIME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pickup_time_minutes": {
            "type": "integer",
            "minimum": 1,
            "description": (
                "Customer's suggested pickup time converted to whole minutes "
                "from now. e.g. 'an hour' -> 60, '30 minutes' -> 30."
            ),
        }
    },
    "required": ["pickup_time_minutes"],
    "additionalProperties": False,
}

_HUMAN_INTERVENTION_NEEDED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "escalation_type": {
            "type": "string",
            "enum": [
                "order_cancellation",
                "made_changes_to_order",
                "asking_for_pickup_time",
                "questions_about_their_order",
                "post_confirm_request",
                "off_topic_question",
            ],
        }
    },
    "required": ["escalation_type"],
    "additionalProperties": False,
}


def _log_tool_call_io(tool_name: str, args: dict, result: dict) -> None:
    """Mirror the executor's tool-IO logging pattern for diagnostic parity."""
    try:
        in_json = json.dumps(args, indent=2, ensure_ascii=False, default=str)
    except TypeError:
        in_json = repr(args)
    try:
        out_json = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    except TypeError:
        out_json = repr(result)
    print(f"[Composer] tool={tool_name} INPUT:\n{in_json}")
    print(f"[Composer] tool={tool_name} OUTPUT:\n{out_json}")


def build_composer_tools(
    composer_input: ComposerInput,
    creds: dict | None,
) -> list[llm_client.GeminiFunctionTool]:
    """Build the GeminiFunctionTool list for the Composer.

    Tools close over per-turn context (session_id, phone_number, firebase_uid,
    creds) from the ComposerInput. The Composer is constructed fresh per turn,
    so closures are safe — there is no risk of stale context bleeding across
    sessions.
    """
    session_id = composer_input.snapshot  # placeholder; see below
    # Pull context fields explicitly to avoid a giant closure capturing the
    # full ComposerInput unnecessarily.
    merchant_id = composer_input.merchant_id

    # Required context not in ComposerInput — passed via the orchestrator
    # in Phase 5 by adding a ToolContext field. For Phase 3, we accept that
    # composer_input MUST carry session_id, phone_number, and firebase_uid
    # somewhere reachable. Add them now to ComposerInput. See note below.
    session_id = composer_input.session_id
    phone_number = composer_input.phone_number
    firebase_uid = composer_input.firebase_uid

    async def _save_human_name(*, name: str) -> dict[str, Any]:
        args = {"name": name}
        out = await saveHumanName(
            name=name,
            phone_number=phone_number,
            firebase_uid=firebase_uid,
        )
        _log_tool_call_io("saveHumanName", args, out)
        return out

    async def _confirm_order() -> dict[str, Any]:
        args: dict[str, Any] = {}
        out = await confirmOrder_guarded(
            session_id=session_id,
            creds=creds,
            phone_number=phone_number,
            firebase_uid=firebase_uid,
        )
        _log_tool_call_io("confirmOrder", args, out)
        return out

    async def _asking_for_pickup_time() -> dict[str, Any]:
        args: dict[str, Any] = {}
        out = await askingForPickupTime(
            session_id=session_id,
            firebase_uid=firebase_uid,
        )
        _log_tool_call_io("askingForPickupTime", args, out)
        return out

    async def _asking_for_wait_time() -> dict[str, Any]:
        args: dict[str, Any] = {}
        out = await askingForWaitTime(
            session_id=session_id,
            firebase_uid=firebase_uid,
        )
        _log_tool_call_io("askingForWaitTime", args, out)
        return out

    async def _suggested_pickup_time(*, pickup_time_minutes: int) -> dict[str, Any]:
        args = {"pickup_time_minutes": pickup_time_minutes}
        out = await suggestedPickupTime(
            session_id=session_id,
            pickup_time_minutes=pickup_time_minutes,
            firebase_uid=firebase_uid,
        )
        _log_tool_call_io("suggestedPickupTime", args, out)
        return out

    async def _human_intervention_needed(*, escalation_type: str) -> dict[str, Any]:
        args = {"escalation_type": escalation_type}
        out = await humanInterventionNeeded_idempotent(
            session_id=session_id,
            escalation_type=escalation_type,
            merchant_id=merchant_id,
        )
        _log_tool_call_io("humanInterventionNeeded", args, out)
        return out

    async def _get_human_profile() -> dict[str, Any]:
        args: dict[str, Any] = {}
        out = await getHumanProfile(
            phone_number=phone_number, firebase_uid=firebase_uid
        )
        _log_tool_call_io("getHumanProfile", args, out)
        return out

    return [
        llm_client.GeminiFunctionTool(
            name="saveHumanName",
            description=(
                "Persist the customer's name to their profile. Call when the "
                "customer just provided their name in this turn."
            ),
            parameters_json_schema=_SAVE_HUMAN_NAME_SCHEMA,
            handler=_save_human_name,
        ),
        llm_client.GeminiFunctionTool(
            name="confirmOrder",
            description=(
                "Submit the current order. Refuses if the order is already "
                "confirmed or if the name gate is unsatisfied — read the "
                "result.error field on failure and respond accordingly."
            ),
            parameters_json_schema=_NO_ARGS_SCHEMA,
            handler=_confirm_order,
        ),
        llm_client.GeminiFunctionTool(
            name="askingForPickupTime",
            description=(
                "Notify the cashier that the customer wants a pickup time. "
                "Call alongside confirmOrder for every successful confirmation, "
                "and when the customer asks 'when will my order be ready?'"
            ),
            parameters_json_schema=_NO_ARGS_SCHEMA,
            handler=_asking_for_pickup_time,
        ),
        llm_client.GeminiFunctionTool(
            name="askingForWaitTime",
            description=(
                "Notify the cashier that the customer is asking about current "
                "wait time. Use only when the customer asks specifically about "
                "wait, not pickup."
            ),
            parameters_json_schema=_NO_ARGS_SCHEMA,
            handler=_asking_for_wait_time,
        ),
        llm_client.GeminiFunctionTool(
            name="suggestedPickupTime",
            description=(
                "Record a customer-suggested pickup time. Convert phrases to "
                "whole minutes before calling."
            ),
            parameters_json_schema=_SUGGESTED_PICKUP_TIME_SCHEMA,
            handler=_suggested_pickup_time,
        ),
        llm_client.GeminiFunctionTool(
            name="humanInterventionNeeded",
            description=(
                "Escalate to a human staff member. Call for complaints, "
                "allergy questions, post-confirm requests, or when the "
                "customer asks for a person. Idempotent within a turn — "
                "calling twice with the same escalation_type no-ops."
            ),
            parameters_json_schema=_HUMAN_INTERVENTION_NEEDED_SCHEMA,
            handler=_human_intervention_needed,
        ),
        llm_client.GeminiFunctionTool(
            name="getHumanProfile",
            description=(
                "Look up the customer's profile (name, phone). Rarely needed "
                "since snapshot.name_on_file is already provided."
            ),
            parameters_json_schema=_NO_ARGS_SCHEMA,
            handler=_get_human_profile,
        ),
    ]