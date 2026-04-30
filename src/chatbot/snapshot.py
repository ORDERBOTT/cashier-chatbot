from __future__ import annotations

from src.cache import cache_get
from src.chatbot.schema import (
    ActionOutcome,
    NameGateStatus,
    OrderLine,
    OrderingStage,
    PendingClarification,
    QAPair,
    SessionSnapshot,
)
from src.chatbot.tools import getHumanProfile, getOrderLineItems
from src.chatbot.utils import (
    _session_name_provided_redis_key,
    _session_status_redis_key,
    get_off_topic_count,
)

_INFORMATIONAL_INTENTS = frozenset(
    {
        "order_question",
        "menu_question",
        "restaurant_question",
        "pickuptime_question",
        "identity_question",
        "greeting",
        "introduce_name",
    }
)


def _coerce_stage(raw: str | None) -> OrderingStage:
    """Map a stored stage string to the enum. Unknown/missing -> ORDERING."""
    if not raw:
        return OrderingStage.ORDERING
    try:
        return OrderingStage(raw)
    except ValueError:
        return OrderingStage.ORDERING


def _name_gate_status(
    *, name_on_file: str | None, name_provided_this_session: bool
) -> NameGateStatus:
    if name_provided_this_session:
        return NameGateStatus.SATISFIED
    if name_on_file:
        return NameGateStatus.UNCONFIRMED_NAME_ON_FILE
    return NameGateStatus.NO_NAME_ON_FILE


async def build_session_snapshot(
    *,
    session_id: str,
    phone_number: str,
    firebase_uid: str,
    creds: dict | None,
    queue: list[dict],
    stage_raw: str,
    parsed_intents: list[dict],
    outcomes: list[ActionOutcome],
) -> SessionSnapshot:
    """Build a SessionSnapshot for the Composer.

    Inputs are raw orchestrator state (queue dicts, stage strings, parsed
    intents from this turn, outcomes already collected this turn). Returns
    a fully populated snapshot. Pure I/O wrapper - no Redis writes.
    """
    # --- Persistent state reads ---
    try:
        status_raw = await cache_get(_session_status_redis_key(session_id))
    except Exception:
        status_raw = None
    is_order_confirmed = status_raw == "confirmed"

    profile = await getHumanProfile(
        phone_number=phone_number, firebase_uid=firebase_uid
    )
    name_on_file = profile.get("name") or None  # treat empty string as None

    try:
        name_flag = await cache_get(_session_name_provided_redis_key(session_id))
    except Exception:
        name_flag = None
    name_provided_this_session = name_flag == "1"

    off_topic_count = await get_off_topic_count(session_id)

    # --- Order state ---
    order_summary: list[OrderLine] = []
    try:
        order_result = await getOrderLineItems(
            session_id=session_id, creds=creds
        )
    except Exception:
        order_result = {"success": False, "lineItems": []}
    if order_result.get("success"):
        for li in order_result.get("lineItems", []):
            order_summary.append(
                OrderLine(
                    name=str(li.get("name", "")),
                    quantity=int(li.get("quantity", 0) or 0),
                    modifiers=[],  # Phase 2 leaves modifiers empty; Phase 3
                    # can enrich if Composer prompt needs them.
                )
            )

    # --- Pending clarifications from queue ---
    pending: list[PendingClarification] = []
    for entry in queue:
        if entry.get("status") != "need_clarification":
            continue
        qa_pairs = entry.get("qa", [])
        # Only surface entries that still have unanswered questions.
        unanswered = [qa for qa in qa_pairs if qa.get("answer") is None]
        if not unanswered:
            continue
        pending.append(
            PendingClarification(
                entry_id=str(entry.get("entry_id", "")),
                questions=[
                    QAPair(question=str(qa["question"]), answer=None)
                    for qa in unanswered
                ],
                attempt_count=len(qa_pairs),
            )
        )

    # --- This-turn booleans (mirror today's orchestrator computations) ---
    parsed_intent_labels = [
        str(p.get("Intent", "")) for p in parsed_intents
    ]
    saw_confirm_intent_this_turn = "confirm_order" in parsed_intent_labels

    # all_outcomes_succeeded is vacuously True when no outcomes - match the
    # orchestrator's `all_succeeded = True` default.
    all_outcomes_succeeded = all(o.success for o in outcomes) if outcomes else True

    order_updated_this_turn = any(
        bool(o.facts.get("order_updated")) for o in outcomes
    )

    outcome_intents = {o.intent for o in outcomes}
    only_informational_this_turn = bool(outcome_intents) and outcome_intents.issubset(
        _INFORMATIONAL_INTENTS
    )
    only_greetings_this_turn = bool(outcome_intents) and outcome_intents == {"greeting"}
    escalation_fired_this_turn = "escalation" in outcome_intents or any(
        o.escalated for o in outcomes
    )

    return SessionSnapshot(
        stage=_coerce_stage(stage_raw),
        is_order_confirmed=is_order_confirmed,
        name_on_file=name_on_file,
        name_provided_this_session=name_provided_this_session,
        name_gate_status=_name_gate_status(
            name_on_file=name_on_file,
            name_provided_this_session=name_provided_this_session,
        ),
        off_topic_count=off_topic_count,
        saw_confirm_intent_this_turn=saw_confirm_intent_this_turn,
        all_outcomes_succeeded=all_outcomes_succeeded,
        order_updated_this_turn=order_updated_this_turn,
        only_informational_this_turn=only_informational_this_turn,
        only_greetings_this_turn=only_greetings_this_turn,
        escalation_fired_this_turn=escalation_fired_this_turn,
        current_order_summary=order_summary,
        pending_clarifications=pending,
    )
