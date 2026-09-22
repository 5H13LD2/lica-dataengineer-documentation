"""Runtime V7 follow-up decision and composition helpers.

The follow-up endpoint is a side-effect boundary, not a replacement for the
main chat turn. It builds compact context from durable session state and recent
conversation history, lets a lightweight model decide whether a proactive
follow-up is appropriate, and gives a composer model only enough context to
write one short customer-facing message.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Sequence

from pydantic import BaseModel, Field

from runtime_v7.lead_qualification import build_lead_qualification_snapshot
from runtime_v7.state_signal_normalization import _construct_background_signals


MANILA_TZ = timezone(timedelta(hours=8))
LEAD_FOLLOWUP_PRIORITY = ("tire_size", "location", "tire_brand", "contact_number")
NON_LEAD_FOLLOWUP_FIELDS = ("installation_partner", "schedule", "payment_option")
FOLLOWUP_ROTATION_MIN_MINUTES = 11 * 60
FOLLOWUP_ROTATION_MAX_MINUTES = 24 * 60


FOLLOWUP_DECISION_SYSTEM_PROMPT = """You decide whether Gulong.PH should send one proactive follow-up now.

Default to sending a follow-up when the conversation has an unresolved
sales/service/order/payment thread and the customer has not replied after a
Gulong.PH next step. A previous assistant or human-agent question waiting for a
customer reply is usually a good follow-up candidate, not a suppression reason.

Abort when:
- the latest meaningful message is from the customer and needs normal chat handling
- the customer already bought tires from Gulong.PH or another store
- the customer is irritated/angry, opted out, asked to stop, or explicitly said no
- the conversation is clearly resolved or no longer actionable
- the latest assistant message was already a follow-up with no new customer reply
- the context is too thin to write a useful sales follow-up

The deterministic_followup_goal in context is business guidance for the open
loop. Do not invent an unrelated business goal; only decide if there is a hard
reason to suppress now. Return JSON only."""


FOLLOWUP_COMPOSER_SYSTEM_PROMPT = """You compose one short Gulong.PH sales follow-up message.

Write a meaningful continuation of the existing thread. Match the full Runtime
V7 chatbot tone: concise, casual Taglish by default, friendly but
sales-oriented, with natural "po". If the recent customer or assistant messages
use Filipino/Taglish words, Philippine shorthand such as "hm" or "magkano", or
polite "po", do not write a straight English follow-up.

Lead qualification priority order:
1. tire_size
2. location
3. tire_brand
4. contact_number

Non-lead qualification fields that may be relevant after the lead context is
clear: installation_partner, schedule, payment_option.

Use the case brief in the user message this way:
- Present lead fields are already known; do not ask for them again.
- Missing lead fields show what still matters for qualification, but choose the
  most natural next question from the current conversation.
- For missing tire_size, ask for the exact sidewall size, or car model/photo if
  the customer cannot read it.
- For missing location, ask for city/barangay because it helps check
  installation availability; do not claim an installation partner is available
  in their area unless the brief says it was verified.
- For missing tire_brand after product options were shown, ask which shown
  option or preferred brand they want to check. Use the shown brands and
  grounded offer highlights from the case brief to make the follow-up more
  useful. When product options were shown and the case brief lists promos,
  financing, warranty, or protection plan highlights, the follow-up must include
  at least one concise grounded offer/benefit. Keep all shown brands visible as
  choices; do not make one brand sound like the only option unless the customer
  selected it. When shown brands are listed in the brief, name those choices in
  the CTA before or while mentioning any offer highlight tied to one eligible
  option. Do not drop the offer highlight just to ask for another missing field.
- Treat promos, financing, warranty, and protection plans as cumulative benefits
  of eligible brands/options, not choices the customer must choose between. Do
  not ask the customer to choose between benefits such as Buy 3 Get 1 FREE and
  Tire Protection Plan. Do not use "or" between benefits in a way that implies
  the customer must choose one benefit; use "may", "kasama", or "available"
  wording for cumulative benefits.
- For missing contact_number, ask only when the customer appears ready for
  reservation, handoff, or next-step assistance.
- For installation partner, schedule, or payment option, ask only when that is
  the current open loop and lead context is already clear enough.

Rules:
- one plain-text message only, target under 450 characters; prefer one compact
  paragraph
- focus the CTA on exactly one missing field: the primary focus in the case
  brief. Other missing fields are context for future follow-ups, not alternate
  asks in the same message.
- usually ask if they are still interested, especially after product options,
  service availability, or a fitment next step
- for the 45-minute to 3-hour follow-up window, write a light nudge, not a
  fresh greeting; avoid starting with "Kamusta po" unless the thread has been
  inactive long enough that a greeting feels natural
- include a clear call to action the customer can reply with now, such as
  sending the exact sidewall tire size, choosing a preferred option/category,
  sending their area/details, or replying yes if still interested
- do not only ask a passive generic question like "may tanong pa po ba"; pair
  the question with one concrete next action
- include one friendly emoji unless the customer tone makes that inappropriate
- no Markdown, HTML, bullets, tables, internal refs, or runtime words
- no product links unless the latest customer message specifically asked for a
  link
- do not end with a generic standalone "Thanks" or "Thank you"
- avoid US-style follow-up phrases like "just checking in", "had a chance",
  "perfect fit", "when you're ready", "let me know", and "Hi there"
- prefer light-nudge Gulong phrases such as "Interested pa po ba kayo dito",
  "If yes", "if gusto niyo", "send niyo lang po", "para ma-check natin", and
  "alin po gusto niyong i-check"; avoid making the follow-up feel like a new
  conversation opener
- do not mention exact price, pricing, presyo, quote, quotation, estimate,
  cost, amount, total, cheapest, mas mura, payment accounts, order totals,
  stock, or service slots
- use grounded offer highlights explicitly listed in the case
  brief, such as Buy 3 Get 1 FREE, BPI 6mo 0% interest, Tire Protection Plan,
  warranty, or installation inclusions, when product options were shown
- when an offer is tied to a specific brand or option in the case brief, keep
  that brand/offer relationship intact; do not imply Buy 3 Get 1 applies to all
  shown brands unless the brief says all shown brands are eligible
- if you mention a brand-specific offer after several brands were shown, still
  keep the other shown brands visible as choices in the same message
- do not invent or expand offers that are not listed in the brief
- use neutral next-step wording such as "options", "availability", "details",
  or "i-check natin" instead of exact-price wording
- use normalized_entities before raw transcript wording for brand, vehicle,
  size, quantity, and location; never copy raw typo text when a normalized
  value is available
- do not list possible/candidate tire sizes in the follow-up; ask the customer
  to reply with the exact sidewall size instead
- make the CTA concrete when possible: ask for size confirmation, preferred
  option, reservation, schedule area, or whether they are still interested
- treat the case brief objective and notes as business guidance, not a fixed
  script, unless the recent conversation clearly points to a safer, more
  specific continuation
- ask at most one focused question

Return JSON only with message and reason."""


class RuntimeV7FollowupDecisionModel(BaseModel):
    """Structured output from the lightweight follow-up decision model."""

    should_follow_up: bool = False
    reason: str = ""
    followup_goal: str = ""
    customer_state: str = ""
    risk: str = ""


class RuntimeV7FollowupComposerModel(BaseModel):
    """Structured output from the follow-up composition model."""

    message: str = Field(default="", description="One short plain-text follow-up message.")
    reason: str = ""


def build_followup_context(
    *,
    request_time: str,
    conversation_messages: Sequence[Mapping[str, Any]],
    session_messages: Sequence[Any],
    v7_state: Mapping[str, Any],
    hydration_metadata: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return compact context for the decision and composer model calls."""

    recent_messages = _recent_followup_messages(
        conversation_messages,
        session_messages=session_messages,
    )
    latest_message = dict(recent_messages[-1]) if recent_messages else {}
    state_signals = _followup_state_signals(v7_state)
    normalized_entities = _followup_normalized_entities(recent_messages, v7_state)
    lead_qualification = _followup_lead_qualification(v7_state, normalized_entities)
    return _compact_json(
        {
            "request_time": request_time,
            "recent_messages": recent_messages[-8:],
            "latest_message": latest_message,
            "state_signals": state_signals,
            "normalized_entities": normalized_entities,
            "lead_qualification": lead_qualification,
            "followup_state": _compact_json(v7_state.get("followup") if isinstance(v7_state, Mapping) else {}),
            "hydration": dict(hydration_metadata or {}),
        },
        max_depth=5,
        max_list_items=16,
        max_dict_items=80,
        max_string_chars=1200,
    )


def build_followup_decision_messages(context: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Build model messages for the follow-up decision call."""

    payload = {
        "task": "Decide whether to send a proactive follow-up now.",
        "context": dict(context or {}),
        "output_schema": {
            "should_follow_up": "boolean",
            "reason": "short internal reason",
            "followup_goal": "specific open loop to address if sending",
            "customer_state": "brief state label",
            "risk": "brief reason to be cautious, if any",
        },
    }
    return [
        {"role": "system", "content": FOLLOWUP_DECISION_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=True, indent=2)},
    ]


def build_followup_composer_messages(
    context: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Build model messages for the short follow-up composition call."""

    return [
        {"role": "system", "content": FOLLOWUP_COMPOSER_SYSTEM_PROMPT},
        {"role": "user", "content": _followup_composer_user_prompt(context, decision)},
    ]


def build_fallback_followup_message(
    context: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> str:
    """Return a safe no-pricing follow-up when the composer output is unusable."""

    entity_values = _followup_entity_display_values(context)
    deterministic_goal = context.get("deterministic_followup_goal") if isinstance(context, Mapping) else {}
    goal_key = str(deterministic_goal.get("goal_key") or "").strip() if isinstance(deterministic_goal, Mapping) else ""
    if goal_key == "missing_location":
        return sanitize_followup_message(
            "Interested pa po ba kayo dito? If yes, send niyo lang po city/barangay para ma-check natin yung installation availability."
        )
    if goal_key == "missing_tire_size":
        return sanitize_followup_message(
            "Kamusta po! Pa-send po ng exact tire size sa sidewall, or car model/photo, para ma-check natin yung options."
        )
    if goal_key == "missing_brand_or_budget":
        return sanitize_followup_message(
            "Kamusta po! May preferred brand or budget range po ba kayo para mas ma-filter natin yung tire options?"
        )
    if goal_key == "missing_contact_number":
        return sanitize_followup_message(
            "Interested pa po ba kayo dito? If yes, pa-send na lang po contact number para ma-assist natin sa next step."
        )
    if goal_key == "service_schedule_check":
        return sanitize_followup_message(
            "Kamusta po! I-check po natin nearest installation partner or schedule for your option? Reply YES po para ma-assist natin."
        )
    brand = str(entity_values.get("preferred_brands") or entity_values.get("required_brands") or "").strip()
    tire_size = str(entity_values.get("tire_size") or "").strip()
    vehicle = str(entity_values.get("car_make_model") or "").strip()
    latest = context.get("latest_message") if isinstance(context, Mapping) else {}
    latest_text = _normalize_policy_text(latest.get("content") if isinstance(latest, Mapping) else "")
    decision_text = _normalize_policy_text(
        " ".join(
            [
                str(decision.get("followup_goal") or ""),
                str(decision.get("reason") or ""),
                str(decision.get("customer_state") or ""),
            ]
        )
    )
    basis = f"{latest_text} {decision_text}"
    if brand and ("size" in basis or "sidewall" in basis or not tire_size):
        vehicle_phrase = f" for your {vehicle}" if vehicle else ""
        return sanitize_followup_message(
            f"Kamusta po! Interested pa po ba kayo sa {brand} tires{vehicle_phrase}? "
            "Reply niyo po yung exact tire size sa sidewall para ma-check natin yung options."
        )
    if tire_size:
        return sanitize_followup_message(
            f"Kamusta po! Interested pa po ba kayo sa {tire_size} options? "
            "Reply po kung alin gusto niyong i-check para ma-assist natin agad."
        )
    if "size" in basis or "sidewall" in basis:
        return sanitize_followup_message(
            "Kamusta po! Na-check niyo na po ba yung exact tire size? "
            "Reply niyo po yung size sa sidewall para ma-check natin yung available options."
        )
    if any(token in basis for token in ("service", "installation", "schedule", "area", "location")):
        return sanitize_followup_message(
            "Kamusta po! Interested pa po ba kayo magpa-check ng service options? "
            "Reply niyo po yung area/details para ma-check natin agad."
        )
    return sanitize_followup_message(
        "Kamusta po! Interested pa po ba kayo sa tire options natin? "
        "Reply po ng YES or send tire size/brand para ma-check natin agad."
    )


def latest_followup_customer_message(context: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the latest customer message from follow-up context, if any."""

    latest = context.get("latest_message") if isinstance(context, Mapping) else {}
    if not isinstance(latest, Mapping):
        return {}
    return dict(latest) if str(latest.get("role") or "").strip() == "user" else {}


def build_deterministic_followup_goal(context: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the business goal the model must naturalize, not choose."""

    entity_values = _followup_entity_display_values(context)
    used_focus_fields = set(_followup_used_focus_fields(context))
    lead = context.get("lead_qualification") if isinstance(context, Mapping) else {}
    lead = lead if isinstance(lead, Mapping) else {}
    next_lead_field = str(lead.get("next_best_field") or "").strip() if isinstance(lead, Mapping) else ""
    missing_lead_fields = {
        str(field or "").strip()
        for field in (lead.get("missing") or [])
        if str(field or "").strip()
    }
    tire_size = str(entity_values.get("tire_size") or "").strip()
    brand = str(entity_values.get("preferred_brands") or entity_values.get("required_brands") or "").strip()
    location = str(entity_values.get("location") or "").strip()
    product = _followup_latest_product_summary(context)
    if not brand:
        brand = str(product.get("brand") or "").strip()
    product_known = bool(product or brand)
    if not tire_size and product:
        tire_size = str(product.get("tire_size") or product.get("size") or "").strip()
    if (next_lead_field == "tire_size" or not tire_size) and "tire_size" not in used_focus_fields:
        return {
            "goal_key": "missing_tire_size",
            "missing_field": "tire_size",
            "goal": "Collect exact sidewall tire size, or car model/photo if the customer cannot read it.",
            "guidance_notes": ("ask one focused size or vehicle/photo question",),
        }
    if (
        tire_size
        and "tire_brand" in missing_lead_fields
        and "tire_brand" not in used_focus_fields
        and (_followup_product_options_visible(context) or _latest_open_loop_prefers_brand_choice(context))
        and not _latest_open_loop_prefers_location(context)
    ):
        return {
            "goal_key": "choose_presented_option",
            "missing_field": "tire_brand",
            "goal": (
                "Lightly nudge the customer to choose one of the shown tire options or name a preferred brand. "
                "Use one grounded offer highlight from the shown options when the case brief lists one."
            ),
            "guidance_notes": (
                "shown product-card brands are conversation context, not customer-selected preferences",
                "do not repeat exact amounts, savings, or product links from the product list",
                "mention one grounded offer highlight from the case brief when it supports the brand/product CTA",
                "make the primary continuation a shown-option/product choice because a product list was just shown",
                "do not ask for location in this follow-up; location can rotate into a later follow-up after tire_brand is sent",
            ),
        }
    if (next_lead_field == "location" or (tire_size and product_known and not location)) and "location" not in used_focus_fields:
        return {
            "goal_key": "missing_location",
            "missing_field": "location",
            "goal": (
                "Lightly nudge the customer to continue from the current tire inquiry and "
                "share city/barangay if they want availability or installation details checked next."
            ),
            "guidance_notes": (
                "use a slight-nudge tone suitable for about one hour after the last interaction",
                "avoid starting with a fresh greeting unless the thread context makes it natural",
                "ask one focused, optional-feeling location question",
                "do not ask for tire size, brand, or product choice because those are already known enough for this goal",
                "do not ask the customer to choose cheapest/promo/specific brand as the primary next step",
            ),
        }
    if (next_lead_field == "tire_brand" or (tire_size and not product_known)) and "tire_brand" not in used_focus_fields:
        return {
            "goal_key": "missing_brand_or_budget",
            "missing_field": "tire_brand",
            "goal": "Collect preferred tire brand or budget/category direction to narrow tire options.",
            "guidance_notes": ("ask one focused brand or budget question",),
        }
    if next_lead_field == "contact_number" and "contact_number" not in used_focus_fields:
        return {
            "goal_key": "missing_contact_number",
            "missing_field": "contact_number",
            "goal": (
                "Ask for contact number only if the conversation is moving toward assistance, reservation, "
                "or handoff; otherwise keep it as a light interest check."
            ),
            "guidance_notes": ("ask one focused contact-number question only when it feels natural from the thread",),
        }
    if location and product_known and "schedule" not in used_focus_fields:
        return {
            "goal_key": "service_schedule_check",
            "missing_field": "schedule",
            "goal": "Confirm whether the customer wants installation partner or schedule checking for the selected/known product.",
            "guidance_notes": ("ask one focused proceed-to-service question",),
        }
    return {}


def deterministic_followup_gate(context: Mapping[str, Any], *, request_time: str = "") -> Dict[str, Any]:
    """Return deterministic Last Interaction eligibility before model calls."""

    recent = context.get("recent_messages") if isinstance(context, Mapping) else []
    messages = [dict(message) for message in recent if isinstance(message, Mapping)] if isinstance(recent, Sequence) else []
    if not messages:
        return {"status": "suppress", "reason": "no_recent_messages"}
    latest = messages[-1]
    latest_role = str(latest.get("role") or "").strip()
    latest_dt = _parse_followup_datetime(latest.get("datetime"))
    request_dt = _parse_followup_datetime(
        request_time or (context.get("request_time") if isinstance(context, Mapping) else "")
    )
    age_minutes = _age_minutes(request_dt, latest_dt)
    hard_reason = deterministic_followup_suppression_reason(context)
    if hard_reason:
        return {"status": "suppress", "reason": hard_reason, "latest_role": latest_role, "age_minutes": age_minutes}
    if latest_role == "user":
        if age_minutes is not None and age_minutes > 24 * 60:
            return {"status": "suppress", "reason": "latest_customer_message_stale_gt_24h", "latest_role": latest_role, "age_minutes": age_minutes}
        return {"status": "recover_to_chat", "reason": "latest_customer_message_recovery", "latest_role": latest_role, "age_minutes": age_minutes}
    if latest_role == "human_agent":
        return {"status": "suppress", "reason": "latest_message_from_human_agent", "latest_role": latest_role, "age_minutes": age_minutes}
    if latest_role != "assistant":
        return {"status": "suppress", "reason": "latest_message_role_not_followup_eligible", "latest_role": latest_role, "age_minutes": age_minutes}
    human_reason = _human_agent_after_latest_open_loop_reason(messages)
    if human_reason:
        return {"status": "suppress", "reason": human_reason, "latest_role": latest_role, "age_minutes": age_minutes}
    if age_minutes is None:
        return {"status": "suppress", "reason": "latest_assistant_message_datetime_missing", "latest_role": latest_role, "age_minutes": age_minutes}
    if age_minutes < 45:
        return {"status": "suppress", "reason": "latest_assistant_message_too_recent_lt_45m", "latest_role": latest_role, "age_minutes": age_minutes}
    if age_minutes > 180:
        rotation = _followup_rotation_gate(context, latest=latest, age_minutes=age_minutes)
        if rotation:
            return {"status": "allow", "reason": "eligible_field_rotation_window", "latest_role": latest_role, "age_minutes": age_minutes, **rotation}
        return {"status": "suppress", "reason": "latest_assistant_message_stale_gt_3h", "latest_role": latest_role, "age_minutes": age_minutes}
    goal = context.get("deterministic_followup_goal") if isinstance(context, Mapping) else {}
    goal = goal if isinstance(goal, Mapping) else build_deterministic_followup_goal(context)
    if not goal:
        return {"status": "suppress", "reason": "no_deterministic_followup_goal", "latest_role": latest_role, "age_minutes": age_minutes}
    return {"status": "allow", "reason": "eligible_last_interaction_window", "latest_role": latest_role, "age_minutes": age_minutes}


def _followup_rotation_gate(
    context: Mapping[str, Any],
    *,
    latest: Mapping[str, Any],
    age_minutes: float | None,
) -> Dict[str, Any]:
    if age_minutes is None or age_minutes < FOLLOWUP_ROTATION_MIN_MINUTES or age_minutes > FOLLOWUP_ROTATION_MAX_MINUTES:
        return {}
    followup_state = context.get("followup_state") if isinstance(context, Mapping) else {}
    if not isinstance(followup_state, Mapping) or not followup_state:
        return {}
    current_focus = followup_target_field(context)
    last_focus = str(followup_state.get("last_sent_focus_field") or "").strip()
    if not current_focus or not last_focus or current_focus == last_focus:
        return {}
    latest_hash = followup_message_hash(latest.get("content") if isinstance(latest, Mapping) else "")
    if latest_hash != str(followup_state.get("last_message_hash") or ""):
        return {}
    return {
        "current_focus_field": current_focus,
        "previous_focus_field": last_focus,
        "rotation_min_minutes": FOLLOWUP_ROTATION_MIN_MINUTES,
        "rotation_max_minutes": FOLLOWUP_ROTATION_MAX_MINUTES,
    }


def deterministic_followup_suppression_reason(context: Mapping[str, Any]) -> str:
    """Return hard deterministic no-send reasons that do not need an LLM."""

    state = context.get("state_signals") if isinstance(context, Mapping) else {}
    if isinstance(state, Mapping):
        if state.get("latest_submitted_order_context") or state.get("latest_payment_request_ref"):
            return "order_or_payment_state_present"
        order_details = state.get("latest_order_details_context")
        if isinstance(order_details, Mapping) and order_details:
            text = _normalize_policy_text(json.dumps(order_details, ensure_ascii=True))
            if any(token in text for token in ("paid", "payment", "completed", "booked", "appointment", "proof")):
                return "completed_order_or_payment_state"
    if _has_hard_no_followup_signal({}, context):
        return "hard_customer_no_followup_signal"
    text_parts: List[str] = []
    recent = context.get("recent_messages") if isinstance(context, Mapping) else []
    if isinstance(recent, Sequence) and not isinstance(recent, (str, bytes)):
        text_parts.extend(str(message.get("content") or "") for message in recent[-8:] if isinstance(message, Mapping))
    text = _normalize_policy_text(" ".join(text_parts))
    complete_patterns = (
        "payment proof",
        "proof of payment",
        "sent proof",
        "nagbayad",
        "paid already",
        "order booked",
        "order confirmed",
        "reservation confirmed",
    )
    if any(pattern in text for pattern in complete_patterns):
        return "completed_order_or_payment_text"
    return ""


def _followup_latest_product_summary(context: Mapping[str, Any]) -> Dict[str, Any]:
    state = context.get("state_signals") if isinstance(context, Mapping) else {}
    if not isinstance(state, Mapping):
        return {}
    selected = state.get("latest_selected_product_context")
    if isinstance(selected, Mapping):
        summary = selected.get("product_summary") if isinstance(selected.get("product_summary"), Mapping) else selected
        if isinstance(summary, Mapping):
            return {str(key): value for key, value in summary.items()}
    return {}


def _followup_product_options_visible(context: Mapping[str, Any]) -> bool:
    if not isinstance(context, Mapping):
        return False
    state = context.get("state_signals")
    if isinstance(state, Mapping):
        for signal in state.get("background_signals") or []:
            if not isinstance(signal, Mapping):
                continue
            key = str(signal.get("key") or "").strip()
            if key in {"latest_product_presentation", "external_product_evidence"} and signal.get("value"):
                return True
        if state.get("latest_selected_product_context"):
            return True
    recent = context.get("recent_messages")
    if isinstance(recent, Sequence) and not isinstance(recent, (str, bytes)):
        text = _normalize_policy_text(
            " ".join(str(message.get("content") or "") for message in recent[-6:] if isinstance(message, Mapping))
        )
        return bool(
            "[premium]" in text
            or "[mid range]" in text
            or "[budget]" in text
            or "may nakita po tayong options" in text
            or "shown options" in text
            or "shown tire options" in text
            or "options for" in text
            or _latest_open_loop_prefers_brand_choice(context)
        )
    return False


def _latest_open_loop_prefers_brand_choice(context: Mapping[str, Any]) -> bool:
    latest = context.get("latest_message") if isinstance(context, Mapping) else {}
    if not isinstance(latest, Mapping):
        return False
    text = _normalize_policy_text(latest.get("content"))
    if not text:
        return False
    if _latest_open_loop_prefers_location(context):
        return False
    choice_terms = (
        "alin",
        "which",
        "choose",
        "preferred",
        "brand",
        "gusto niyong i-check",
        "gusto niyo i-check",
        "gusto nyo i-check",
    )
    if not any(term in text for term in choice_terms):
        return False
    assistant_text = "\n".join(
        str(message.get("content") or "")
        for message in (context.get("recent_messages") or [])[-8:]
        if isinstance(message, Mapping) and str(message.get("role") or "").strip() == "assistant"
    )
    return bool(_shown_product_brands(assistant_text) or "brand" in text or "option" in text)


def _latest_open_loop_prefers_location(context: Mapping[str, Any]) -> bool:
    latest = context.get("latest_message") if isinstance(context, Mapping) else {}
    if not isinstance(latest, Mapping):
        return False
    text = _normalize_policy_text(latest.get("content"))
    has_location = any(token in text for token in ("city", "barangay", "location", "area", "installation"))
    has_product_choice = any(token in text for token in ("alin", "which", "specific brand", "preferred brand", "gusto niyong i-check"))
    return bool(has_location and not has_product_choice)


def _human_agent_after_latest_open_loop_reason(messages: Sequence[Mapping[str, Any]]) -> str:
    latest_user_dt = None
    latest_assistant_dt = None
    latest_human_dt = None
    for message in messages or []:
        role = str(message.get("role") or "").strip()
        parsed = _parse_followup_datetime(message.get("datetime"))
        if parsed is None:
            continue
        if role == "user":
            latest_user_dt = parsed
        elif role == "assistant":
            latest_assistant_dt = parsed
        elif role == "human_agent":
            latest_human_dt = parsed
    if latest_human_dt is None:
        return ""
    if latest_user_dt is not None and latest_human_dt > latest_user_dt:
        return "human_agent_message_after_latest_customer"
    if latest_assistant_dt is not None and latest_human_dt > latest_assistant_dt:
        return "human_agent_message_after_latest_bot_cta"
    return ""


def _age_minutes(current_dt: datetime | None, message_dt: datetime | None) -> float | None:
    if current_dt is None or message_dt is None:
        return None
    return max(0.0, (current_dt - message_dt).total_seconds() / 60.0)


def _parse_followup_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(MANILA_TZ).replace(tzinfo=None)
        return parsed
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%B %d, %Y %I:%M %p", "%B %d %Y %I:%M %p"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def apply_sales_permissive_followup_policy(
    decision: Mapping[str, Any],
    context: Mapping[str, Any],
) -> Dict[str, Any]:
    """Apply deterministic follow-up eligibility policy on top of model output."""

    normalized = dict(decision or {})
    if bool(normalized.get("should_follow_up")):
        return normalized
    if not _latest_message_can_receive_proactive_followup(context):
        return normalized
    if _has_hard_no_followup_signal(decision, context):
        return normalized
    if not _looks_like_waiting_response_suppression(decision):
        return normalized

    original_reason = _single_line(normalized.get("reason"))
    normalized.update(
        {
            "should_follow_up": True,
            "reason": "sales_permissive_waiting_response_override",
            "followup_goal": _single_line(normalized.get("followup_goal")) or _default_sales_followup_goal(context),
            "customer_state": _single_line(normalized.get("customer_state")) or "awaiting_customer_reply",
            "risk": _single_line(normalized.get("risk")),
            "policy_override": {
                "name": "sales_permissive_waiting_response",
                "original_reason": original_reason,
            },
        }
    )
    return normalized


def parse_followup_decision(model_text: str) -> Dict[str, Any]:
    """Parse a model decision payload, defaulting to no-send on invalid JSON."""

    payload = _loads_json_object(model_text)
    if not payload:
        return {
            "should_follow_up": False,
            "reason": "invalid_decision_response",
            "followup_goal": "",
            "customer_state": "",
            "risk": "invalid_json",
        }
    return {
        "should_follow_up": bool(payload.get("should_follow_up")),
        "reason": _single_line(payload.get("reason"))[:300],
        "followup_goal": _single_line(payload.get("followup_goal"))[:300],
        "customer_state": _single_line(payload.get("customer_state"))[:120],
        "risk": _single_line(payload.get("risk"))[:200],
    }


def parse_followup_composer(model_text: str) -> Dict[str, Any]:
    """Parse a composer payload into a sanitized message and internal reason."""

    payload = _loads_json_object(model_text)
    if not payload:
        return {"message": "", "reason": "invalid_composer_response"}
    message = sanitize_followup_message(payload.get("message"))
    return {
        "message": message,
        "reason": _single_line(payload.get("reason"))[:300],
    }


def sanitize_followup_message(value: Any, *, max_chars: int = 520) -> str:
    """Return a ManyChat-safe one-message follow-up body."""

    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|text)?\s*", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*```$", "", text).strip()
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"https?://\S+", "", text).strip()
    text = re.sub(r"\*\*([^*\n][^*]*?)\*\*", r"\1", text)
    text = re.sub(r"__([^_\n][^_]*?)__", r"\1", text)
    text = re.sub(r"`([^`\n]+?)`", r"\1", text)
    lines: List[str] = []
    blank = False
    for raw_line in text.splitlines():
        line = re.sub(r"^\s*[-*]\s+", "", raw_line).strip()
        if not line:
            if not blank:
                lines.append("")
            blank = True
            continue
        lines.append(line)
        blank = False
    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = _normalize_followup_voice(cleaned)
    cleaned = _remove_unbacked_pricing_language(cleaned)
    cleaned = _strip_candidate_size_lists(cleaned)
    cleaned = _strip_standalone_thanks_lines(cleaned)
    cleaned = _strip_inline_generic_thanks(cleaned)
    cleaned = _strip_generic_followup_closer(cleaned)
    if cleaned and not _contains_emoji(cleaned):
        suffix = " \U0001f60a"
        if len(cleaned) + len(suffix) <= max_chars:
            cleaned = cleaned + suffix
    if len(cleaned) <= max_chars:
        return cleaned
    trimmed = cleaned[: max_chars + 1].rsplit(" ", 1)[0].strip()
    return trimmed.rstrip(".,;:") + "..."


def redact_followup_pricing_context(value: Any) -> Any:
    """Redact pricing and promo terms from follow-up model/log context."""

    return _redact_followup_pricing_context(value)


def followup_context_fingerprint(context: Mapping[str, Any]) -> str:
    """Return a stable hash for the visible follow-up decision context."""

    basis = {
        "recent_messages": context.get("recent_messages") if isinstance(context, Mapping) else [],
        "state_signals": context.get("state_signals") if isinstance(context, Mapping) else {},
        "normalized_entities": context.get("normalized_entities") if isinstance(context, Mapping) else {},
        "lead_qualification": context.get("lead_qualification") if isinstance(context, Mapping) else {},
        "deterministic_followup_goal": context.get("deterministic_followup_goal") if isinstance(context, Mapping) else {},
    }
    return _short_hash(basis)


def followup_message_hash(message: Any) -> str:
    """Return a stable hash for a customer-visible follow-up message."""

    return _short_hash({"message": _single_line(message)})


def prior_followup_suppression_reason(
    context: Mapping[str, Any],
    followup_state: Mapping[str, Any],
    *,
    context_fingerprint: str,
) -> str:
    """Return a deterministic duplicate-send suppression reason, if any."""

    if not isinstance(followup_state, Mapping) or not followup_state:
        return ""
    current_focus = followup_target_field(context)
    last_focus = str(followup_state.get("last_sent_focus_field") or "").strip()
    latest = context.get("latest_message") if isinstance(context, Mapping) else {}
    if isinstance(latest, Mapping) and str(latest.get("role") or "") == "assistant":
        latest_hash = followup_message_hash(latest.get("content"))
        if latest_hash and latest_hash == str(followup_state.get("last_message_hash") or ""):
            if current_focus and last_focus and current_focus != last_focus:
                return ""
            return "already_sent_latest_visible_followup"
    if context_fingerprint and context_fingerprint == str(followup_state.get("last_sent_context_fingerprint") or ""):
        return "already_sent_for_context"
    if context_fingerprint and context_fingerprint == str(followup_state.get("last_attempted_context_fingerprint") or ""):
        attempted_focus = str(followup_state.get("last_attempted_focus_field") or "").strip()
        if current_focus and attempted_focus and current_focus != attempted_focus:
            return ""
        return "already_attempted_for_context"
    return ""


def followup_target_field(value: Mapping[str, Any]) -> str:
    """Return the lead/non-lead field targeted by a follow-up context or decision."""

    if not isinstance(value, Mapping):
        return ""
    goal = value.get("deterministic_followup_goal")
    if not isinstance(goal, Mapping) and (value.get("goal_key") or value.get("missing_field")):
        goal = value
    if not isinstance(goal, Mapping):
        return ""
    field = str(goal.get("missing_field") or "").strip()
    if field:
        return field
    key = str(goal.get("goal_key") or "").strip()
    if key.startswith("missing_"):
        return key.replace("missing_", "", 1)
    if key == "service_schedule_check":
        return "schedule"
    return key


def _latest_message_can_receive_proactive_followup(context: Mapping[str, Any]) -> bool:
    latest = context.get("latest_message") if isinstance(context, Mapping) else {}
    if not isinstance(latest, Mapping):
        return False
    role = str(latest.get("role") or "").strip()
    return role in {"assistant", "human_agent"}


def _looks_like_waiting_response_suppression(decision: Mapping[str, Any]) -> bool:
    text = _normalize_policy_text(
        " ".join(
            [
                str(decision.get("reason") or ""),
                str(decision.get("customer_state") or ""),
                str(decision.get("risk") or ""),
            ]
        )
    )
    if not text:
        return False
    waiting_patterns = (
        "latest message is from the assistant",
        "customer has not yet responded",
        "customer hasnt yet responded",
        "customer has not responded",
        "customer hasnt responded",
        "has not yet responded",
        "has not responded",
        "has not replied",
        "awaiting customer response",
        "awaiting customer reply",
        "waiting for customer",
        "requires customer response",
        "needs customer response",
        "initial information gathering",
    )
    return any(pattern in text for pattern in waiting_patterns)


def _has_hard_no_followup_signal(decision: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
    text_parts: List[str] = [
        str(decision.get("reason") or ""),
        str(decision.get("customer_state") or ""),
        str(decision.get("risk") or ""),
    ]
    recent_messages = context.get("recent_messages") if isinstance(context, Mapping) else []
    if isinstance(recent_messages, Sequence) and not isinstance(recent_messages, (str, bytes)):
        for message in recent_messages[-8:]:
            if isinstance(message, Mapping):
                text_parts.append(str(message.get("content") or ""))
    text = _normalize_policy_text(" ".join(text_parts))
    if not text:
        return False
    hard_patterns = (
        "already bought",
        "already purchased",
        "bought tires",
        "purchased tires",
        "bought from another",
        "bought from other",
        "another store",
        "other store",
        "nakabili",
        "naka bili",
        "may nabili",
        "explicitly said no",
        "not interested",
        "no longer interested",
        "opted out",
        "asked to stop",
        "do not message",
        "dont message",
        "unsubscribe",
        "wag na",
        "huwag na",
        "ayaw",
        "hindi na",
        "di na",
        "irritated",
        "angry",
        "annoyed",
        "galit",
        "inis",
        "badtrip",
    )
    return any(pattern in text for pattern in hard_patterns)


def _default_sales_followup_goal(context: Mapping[str, Any]) -> str:
    latest = context.get("latest_message") if isinstance(context, Mapping) else {}
    latest_text = _normalize_policy_text(latest.get("content") if isinstance(latest, Mapping) else "")
    if "size" in latest_text:
        return "Ask if they were able to check the tire size and if they are still interested."
    if any(token in latest_text for token in ("option", "brand", "promo", "available", "availability")):
        return "Ask if they are still interested in the options or availability."
    return "Ask if they are still interested so Gulong.PH can help with tire options."


_FOLLOWUP_ENTITY_KEYS = {
    "tire_size",
    "rim_size",
    "preferred_brands",
    "required_brands",
    "excluded_brands",
    "car_make_model",
    "location",
    "contact_number",
    "quantity",
    "tire_category_preference",
    "origins",
    "excluded_origins",
    "specific_sku_model",
    "terrain_types",
    "service_type",
    "selected_installation_partner",
    "chosen_schedule_slot",
    "payment_option",
}


def _followup_normalized_entities(
    recent_messages: Sequence[Mapping[str, Any]],
    v7_state: Mapping[str, Any],
) -> Dict[str, Any]:
    """Project recent follow-up context through the central signal normalizer."""

    candidates: List[Dict[str, Any]] = []
    if isinstance(v7_state, Mapping):
        for signal in v7_state.get("background_signals") or []:
            if not isinstance(signal, Mapping):
                continue
            key = str(signal.get("key") or "").strip()
            value = signal.get("value")
            if key not in _FOLLOWUP_ENTITY_KEYS or value in (None, "", [], {}):
                continue
            candidates.append(
                {
                    "key": key,
                    "value": value,
                    "source": signal.get("source") or "signal_ledger",
                    "confidence": signal.get("confidence") or "medium",
                    "status_hint": signal.get("status") or "signal_ledger",
                }
            )
    for message in recent_messages[-8:] if isinstance(recent_messages, Sequence) else []:
        if not isinstance(message, Mapping):
            continue
        text = str(message.get("content") or "").strip()
        if not text:
            continue
        role = str(message.get("role") or "").strip()
        if role == "human_agent":
            source = "human_agent_history"
        elif role == "user":
            source = "latest_user_message"
        else:
            source = "conversation_context"
        for brand in _followup_brand_candidate_values(text):
            candidates.append(
                {
                    "key": "preferred_brands",
                    "value": brand,
                    "source": source,
                    "confidence": "medium",
                    "status_hint": "brand_mention",
                }
            )
        for vehicle in _followup_vehicle_candidate_values(text):
            candidates.append(
                {
                    "key": "car_make_model",
                    "value": vehicle,
                    "source": source,
                    "confidence": "medium",
                    "status_hint": "vehicle_mention",
                }
            )
        if role in {"user", "human_agent"}:
            candidates.append(
                {
                    "key": "tire_size",
                    "value": text,
                    "source": source,
                    "confidence": "medium",
                    "status_hint": "customer_or_agent_mention",
                }
            )
            candidates.append(
                {
                    "key": "rim_size",
                    "value": text,
                    "source": source,
                    "confidence": "medium",
                    "status_hint": "customer_or_agent_mention",
                }
            )
            for quantity in _followup_quantity_candidate_values(text):
                candidates.append(
                    {
                        "key": "quantity",
                        "value": quantity,
                        "source": source,
                        "confidence": "medium",
                        "status_hint": "quantity_mention",
                    }
                )
            if _looks_like_contact_number_text(text):
                candidates.append(
                    {
                        "key": "contact_number",
                        "value": text,
                        "source": source,
                        "confidence": "medium",
                        "status_hint": "customer_or_agent_mention",
                    }
                )
    if not candidates:
        return {}
    signals = _construct_background_signals(
        candidates=candidates,
        latest_product_observation={},
    )
    signal_dicts = [
        _compact_json(_followup_safe_signal_dict(signal.to_dict()), max_depth=3, max_dict_items=24, max_string_chars=220)
        for signal in signals
        if signal.key in _FOLLOWUP_ENTITY_KEYS and signal.value
    ]
    if not signal_dicts:
        return {}
    return _compact_json(
        {
            "source": "central_entity_normalizer",
            "note": "Use these normalized values over raw transcript typos.",
            "signals": signal_dicts,
            "display_values": _display_values_from_signals(signal_dicts),
        },
        max_depth=4,
        max_list_items=14,
        max_dict_items=40,
        max_string_chars=500,
    )


def _followup_lead_qualification(
    v7_state: Mapping[str, Any],
    normalized_entities: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return a follow-up-safe lead qualification packet for prompt guidance."""

    signals = _lead_qualification_signal_inputs(v7_state, normalized_entities)
    snapshot = build_lead_qualification_snapshot(signals).to_dict()
    present = _followup_safe_lead_present(snapshot.get("present") or {})
    raw_missing = [str(field or "").strip() for field in snapshot.get("missing") or [] if field]
    missing = [field for field in LEAD_FOLLOWUP_PRIORITY if field in set(raw_missing)]
    optional_raw = [str(field or "").strip() for field in snapshot.get("optional_missing") or [] if field]
    optional_missing = [field for field in LEAD_FOLLOWUP_PRIORITY if field in set(optional_raw)]
    next_best_field = missing[0] if missing else ""
    non_lead_present = _non_lead_followup_present(signals)
    output = {
        "lead_stage": snapshot.get("lead_stage") or snapshot.get("status") or "incomplete",
        "status": snapshot.get("status") or snapshot.get("lead_stage") or "incomplete",
        "moderate_intent": bool(snapshot.get("moderate_intent")),
        "rule": snapshot.get("rule") or "tire_size + at least 2 of tire_brand/location/contact_number",
        "priority_order": list(LEAD_FOLLOWUP_PRIORITY),
        "present": present,
        "missing": missing,
        "optional_missing": optional_missing,
        "next_best_field": next_best_field,
        "support_count": int(snapshot.get("support_count") or 0),
        "non_lead_fields": {
            "priority_order": list(NON_LEAD_FOLLOWUP_FIELDS),
            "present": non_lead_present,
            "missing": [field for field in NON_LEAD_FOLLOWUP_FIELDS if field not in non_lead_present],
            "note": "Use these only when the recent conversation is about installation, scheduling, or payment.",
        },
        "guidance": (
            "Favor the first missing lead field that fits the current open loop, but keep the follow-up natural "
            "and situational. Ask at most one field."
        ),
    }
    return _compact_json(output, max_depth=4, max_list_items=12, max_dict_items=40, max_string_chars=420)


def _lead_qualification_signal_inputs(
    v7_state: Mapping[str, Any],
    normalized_entities: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    signals: List[Dict[str, Any]] = []
    if isinstance(v7_state, Mapping):
        for signal in v7_state.get("background_signals") or []:
            if isinstance(signal, Mapping):
                signals.append(dict(signal))
    if isinstance(normalized_entities, Mapping):
        for signal in normalized_entities.get("signals") or []:
            if isinstance(signal, Mapping):
                if not _signal_safe_for_followup_lead_qualification(signal):
                    continue
                signals.append(dict(signal))
    return signals


def _signal_safe_for_followup_lead_qualification(signal: Mapping[str, Any]) -> bool:
    key = str(signal.get("key") or "").strip()
    if key not in {"tire_size", "preferred_brands", "required_brands", "location", "contact_number"}:
        return True
    source = str(signal.get("source") or "").strip()
    return source in {"latest_user_message", "human_agent_history", "active_working_memory", "signal_ledger"}


def _followup_safe_lead_present(present: Mapping[str, Any]) -> Dict[str, str]:
    output: Dict[str, str] = {}
    for key, value in (present or {}).items():
        field = str(key or "").strip()
        if field not in LEAD_FOLLOWUP_PRIORITY or value in (None, "", [], {}):
            continue
        output[field] = "provided" if field == "contact_number" else str(value).strip()
    return output


def _non_lead_followup_present(signals: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    aliases = {
        "selected_installation_partner": "installation_partner",
        "installation_partner": "installation_partner",
        "chosen_schedule_slot": "schedule",
        "schedule": "schedule",
        "payment_option": "payment_option",
    }
    output: Dict[str, str] = {}
    for signal in signals or []:
        if not isinstance(signal, Mapping):
            continue
        field = aliases.get(str(signal.get("key") or "").strip())
        value = signal.get("value")
        if field and value not in (None, "", [], {}) and field not in output:
            output[field] = str(value).strip()
    return output


def _followup_safe_signal_dict(signal: Mapping[str, Any]) -> Dict[str, Any]:
    output = dict(signal or {})
    if str(output.get("key") or "") == "contact_number" and output.get("value") not in (None, "", [], {}):
        output["value"] = "provided"
    return output


def _followup_sent_focus_fields(context: Mapping[str, Any]) -> List[str]:
    state = context.get("followup_state") if isinstance(context, Mapping) else {}
    if not isinstance(state, Mapping):
        return []
    values: List[str] = []
    for field in state.get("sent_focus_fields") or []:
        cleaned = str(field or "").strip()
        if cleaned:
            values.append(cleaned)
    last = str(state.get("last_sent_focus_field") or "").strip()
    if last:
        values.append(last)
    return _unique_strings(values)


def _followup_attempted_focus_fields(context: Mapping[str, Any]) -> List[str]:
    state = context.get("followup_state") if isinstance(context, Mapping) else {}
    if not isinstance(state, Mapping):
        return []
    values: List[str] = []
    for field in state.get("attempted_focus_fields") or []:
        cleaned = str(field or "").strip()
        if cleaned:
            values.append(cleaned)
    last = str(state.get("last_attempted_focus_field") or "").strip()
    if last:
        values.append(last)
    return _unique_strings(values)


def _followup_used_focus_fields(context: Mapping[str, Any]) -> List[str]:
    return _unique_strings([*_followup_sent_focus_fields(context), *_followup_attempted_focus_fields(context)])


def _followup_brand_candidate_values(text: str) -> List[str]:
    values: List[str] = []
    for token in re.findall(r"\b[A-Za-z][A-Za-z0-9+-]{2,}\b", str(text or "")):
        if _followup_brand_token_allowed(token):
            values.append(token)
    for match in re.finditer(r"\bBF\s*Goodrich\b", str(text or ""), flags=re.IGNORECASE):
        values.append(match.group(0))
    return _unique_strings(values)[:12]


def _followup_brand_token_allowed(token: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", str(token or "").lower())
    if len(normalized) < 4:
        return False
    stop_tokens = {
        "available",
        "availability",
        "options",
        "possible",
        "candidate",
        "confirm",
        "exact",
        "sidewall",
        "gulong",
        "tires",
        "tire",
        "message",
        "reply",
        "interested",
        "installation",
        "location",
        "salamat",
        "thank",
        "welcome",
    }
    return normalized not in stop_tokens and not normalized.isdigit()


def _followup_vehicle_candidate_values(text: str) -> List[str]:
    pattern = re.compile(
        r"\b(?:Toyota|Honda|Mitsubishi|Nissan|Suzuki|Ford|Hyundai|Kia|Mazda|Isuzu)\s+"
        r"[A-Za-z0-9][A-Za-z0-9-]*(?:\s+(?:G4|D-?Max|CR-?V|Hiace|Innova|Xpander|Avanza|Fortuner|Vios|Wigo))?",
        flags=re.IGNORECASE,
    )
    values = [match.group(0) for match in pattern.finditer(str(text or ""))]
    alias_map = {
        "dmax": "Isuzu D-Max",
        "d-max": "Isuzu D-Max",
        "xpander": "Mitsubishi Xpander",
        "avanza": "Toyota Avanza",
        "wigo": "Toyota Wigo",
        "wgo": "Toyota Wigo",
        "mirage g4": "Mitsubishi Mirage G4",
    }
    lowered = str(text or "").lower()
    for alias, canonical in alias_map.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            values.append(canonical)
    return _unique_strings(values)[:6]


def _has_explicit_quantity_phrase(text: str) -> bool:
    lowered = str(text or "").lower()
    return bool(
        re.search(r"\b\d+\s*(?:pc|pcs|piece|pieces|piraso|gulong|tire|tires)\b", lowered)
        or re.search(r"\b(?:isa|dalawa|tatlo|apat|one|two|three|four)\s+(?:pc|pcs|piraso|gulong|tire|tires)\b", lowered)
    )


def _followup_quantity_candidate_values(text: str) -> List[str]:
    values: List[str] = []
    for match in re.finditer(r"\b(?:qty|quantity)\s*[:=\-,]?\s*(\d{1,2})\b", str(text or ""), flags=re.IGNORECASE):
        values.append(match.group(1))
    for match in re.finditer(
        r"\b(\d{1,2})\s*(?:pc|pcs|piece|pieces|piraso|gulong|tire|tires)\b",
        str(text or ""),
        flags=re.IGNORECASE,
    ):
        values.append(match.group(1))
    word_quantities = {
        "isa": "1",
        "one": "1",
        "dalawa": "2",
        "two": "2",
        "tatlo": "3",
        "three": "3",
        "apat": "4",
        "four": "4",
    }
    for match in re.finditer(
        r"\b(isa|one|dalawa|two|tatlo|three|apat|four)\s+(?:pc|pcs|piraso|gulong|tire|tires)\b",
        str(text or ""),
        flags=re.IGNORECASE,
    ):
        values.append(word_quantities.get(match.group(1).lower(), ""))
    return _unique_strings([value for value in values if value])


def _looks_like_contact_number_text(text: str) -> bool:
    digits = re.sub(r"\D+", "", str(text or ""))
    return bool(re.search(r"(?:\+?63|0)\s*9\d{2}[\s.-]?\d{3}[\s.-]?\d{4}", str(text or ""))) or len(digits) >= 10


def _display_values_from_signals(signals: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for signal in signals:
        if not isinstance(signal, Mapping):
            continue
        key = str(signal.get("key") or "")
        value = str(signal.get("value") or "").strip()
        if not key or not value:
            continue
        values[key] = _display_entity_value(key, value)
    return values


def _followup_entity_display_values(context: Mapping[str, Any]) -> Dict[str, str]:
    entities = context.get("normalized_entities") if isinstance(context, Mapping) else {}
    if not isinstance(entities, Mapping):
        return {}
    display = entities.get("display_values")
    if isinstance(display, Mapping):
        return {str(key): str(value) for key, value in display.items() if value}
    return _display_values_from_signals(entities.get("signals") or [])


def _display_entity_value(key: str, value: str) -> str:
    if key == "contact_number":
        return "provided"
    if key in {"preferred_brands", "required_brands", "excluded_brands"}:
        return ", ".join(_display_brand(part) for part in _split_comma_values(value))
    if key == "car_make_model":
        return " ".join(_display_vehicle_token(part) for part in str(value or "").split())
    return str(value or "").strip()


def _display_brand(value: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())
    if normalized == "BFGOODRICH":
        return "BFGoodrich"
    if normalized in {"MICHELIN", "YOKOHAMA", "WESTLAKE", "BRIDGESTONE", "GOODYEAR"}:
        return normalized.title()
    return str(value or "").strip()


def _display_vehicle_token(value: str) -> str:
    token = str(value or "").strip()
    if re.fullmatch(r"[A-Z]?\d+[A-Z]?", token, flags=re.IGNORECASE):
        return token.upper()
    if token.upper() == "D-MAX":
        return "D-Max"
    if token.upper() in {"G4", "CR-V"}:
        return token.upper()
    return token


def _split_comma_values(value: str) -> List[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _unique_strings(values: Sequence[str]) -> List[str]:
    output: List[str] = []
    seen = set()
    for value in values:
        cleaned = str(value or "").strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
    return output


def _followup_composer_user_prompt(context: Mapping[str, Any], decision: Mapping[str, Any]) -> str:
    """Return the plain-text case packet for the follow-up composer."""

    return _followup_composer_brief(context, decision)


def _followup_composer_brief(context: Mapping[str, Any], decision: Mapping[str, Any]) -> str:
    """Render only case-specific context for the composer."""

    lines: List[str] = []
    request_time = str(context.get("request_time") or "").strip() if isinstance(context, Mapping) else ""
    if request_time:
        lines.append(f"Request time: {request_time}")

    lines.extend(_followup_lead_brief_lines(context))
    lines.extend(_followup_open_loop_brief_lines(context, decision))
    lines.extend(_followup_offer_brief_lines(context))
    lines.extend(_followup_conversation_brief_lines(context))
    return "\n".join(line for line in lines if str(line or "").strip())


def _followup_lead_brief_lines(context: Mapping[str, Any]) -> List[str]:
    lead = context.get("lead_qualification") if isinstance(context, Mapping) else {}
    if not isinstance(lead, Mapping):
        return []
    present = lead.get("present") if isinstance(lead.get("present"), Mapping) else {}
    missing = [str(field) for field in lead.get("missing") or [] if str(field or "").strip()]
    optional_missing = [str(field) for field in lead.get("optional_missing") or [] if str(field or "").strip()]
    lines = ["Lead qualification:"]
    lines.append(f"- Present: {_format_followup_mapping(present) if present else 'none'}")
    if missing:
        lines.append(f"- Missing: {', '.join(missing)}")
    if optional_missing:
        lines.append(f"- Optional missing: {', '.join(optional_missing)}")
    return lines


def _followup_open_loop_brief_lines(context: Mapping[str, Any], decision: Mapping[str, Any]) -> List[str]:
    """Render the current follow-up focus without adding a scripted CTA."""

    goal = context.get("deterministic_followup_goal") if isinstance(context, Mapping) else {}
    if not isinstance(goal, Mapping) or not goal:
        goal = decision.get("deterministic_followup_goal") if isinstance(decision, Mapping) else {}
    if not isinstance(goal, Mapping) or not goal:
        return []
    missing_field = str(goal.get("missing_field") or "").strip()
    goal_text = _single_line(goal.get("goal"))[:360]
    lines = ["Current open loop:"]
    if missing_field:
        lines.append(f"- Primary focus: {missing_field}")
    if goal_text:
        lines.append(f"- Guidance: {goal_text}")
    if missing_field == "tire_brand" and _followup_grounded_offer_highlights(context):
        lines.append(
            "- Response requirement: name the shown brand choices and include one grounded "
            "offer/benefit from the highlights below, while keeping brand-offer eligibility correct; "
            "do not ask for city, barangay, area, or location in this message"
        )
    return lines


def _followup_offer_brief_lines(context: Mapping[str, Any]) -> List[str]:
    highlights = _followup_grounded_offer_highlights(context)
    if not highlights:
        return ["Grounded offer highlights from recent assistant messages: none detected"]
    lines = ["Grounded offer highlights from recent assistant messages:"]
    lines.extend(f"- {highlight}" for highlight in highlights)
    return lines


def _followup_conversation_brief_lines(context: Mapping[str, Any]) -> List[str]:
    messages = _followup_composer_recent_messages(context)
    if not messages:
        return []
    lines = ["Recent conversation:"]
    for message in messages:
        role = str(message.get("role") or "unknown").strip()
        content = _single_line(message.get("content"))[:700]
        if content:
            lines.append(f"- {role}: {content}")
    return lines


def _followup_composer_recent_messages(context: Mapping[str, Any]) -> List[Dict[str, Any]]:
    recent_messages = context.get("recent_messages") if isinstance(context, Mapping) else []
    compact_messages: List[Dict[str, Any]] = []
    if isinstance(recent_messages, Sequence) and not isinstance(recent_messages, (str, bytes)):
        for message in recent_messages[-6:]:
            if not isinstance(message, Mapping):
                continue
            content = _redact_followup_pricing_context(_strip_urls(str(message.get("content") or "")))
            content = _redact_contact_numbers(str(content or ""))
            content = _strip_stray_question_mark_emoji_markers(str(content or ""))
            content = _normalize_followup_entity_mentions(str(content or ""), context)
            compact = {
                "role": str(message.get("role") or "").strip(),
                "content": content[:700],
            }
            datetime_value = str(message.get("datetime") or "").strip()
            if datetime_value:
                compact["datetime"] = datetime_value
            compact_messages.append(_compact_json(compact, max_depth=3, max_string_chars=700))
    return compact_messages


def _followup_grounded_offer_highlights(context: Mapping[str, Any]) -> List[str]:
    recent_messages = context.get("recent_messages") if isinstance(context, Mapping) else []
    assistant_text = "\n".join(
        str(message.get("content") or "")
        for message in recent_messages[-8:]
        if isinstance(message, Mapping) and str(message.get("role") or "").strip() == "assistant"
    )
    if not assistant_text.strip():
        return []
    normalized = _normalize_policy_text(assistant_text)
    highlights: List[str] = []
    shown_brands = _shown_product_brands(assistant_text)
    if shown_brands:
        highlights.append(f"shown tire options/brands: {', '.join(shown_brands)}")
    highlights.extend(_followup_brand_offer_highlights(assistant_text, shown_brands))
    if re.search(r"buy\s*3\s*(?:get|take)\s*1(?:\s*free)?", assistant_text, flags=re.IGNORECASE):
        highlights.append("Buy 3 Get 1 FREE was shown")
    if "bpi" in normalized and ("0%" in assistant_text or "0 percent" in normalized) and re.search(
        r"\b6\s*(?:mo|mos|month|months)\b", assistant_text, flags=re.IGNORECASE
    ):
        highlights.append("BPI 6mo 0% interest was shown")
    if "tire protection plan" in normalized or re.search(r"\btpp\b", assistant_text, flags=re.IGNORECASE):
        highlights.append("Tire Protection Plan was shown")
    if "warranty" in normalized:
        highlights.append("warranty terms were shown")
    if "free installation" in normalized or all(
        token in normalized for token in ("mounting", "balancing")
    ):
        highlights.append("installation inclusions were shown for authorized partners")
    return _unique_strings(highlights)[:12]


def _followup_brand_offer_highlights(text: str, shown_brands: Sequence[str]) -> List[str]:
    if not shown_brands:
        return []
    highlights: List[str] = []
    markers = [
        r"\[(?:premium|mid range|budget|entry level|value|performance)[^\]]*\]",
        r"\b(?:michelin|apollo|fronway|yokohama|bridgestone|goodyear|westlake|vredestein|dunlop|bf\s*goodrich|bfgoodrich|deestone|nankang|arivo|gt\s*radial)\b",
        r"warranty and inclusions",
        r"may tire protection plan",
        r"alin po",
        r"pwede niyo",
    ]
    marker_re = re.compile("|".join(f"({marker})" for marker in markers), flags=re.IGNORECASE)
    starts = [match.start() for match in marker_re.finditer(str(text or ""))]
    starts = sorted(set(starts + [len(str(text or ""))]))
    for brand in shown_brands:
        escaped_brand = re.escape(brand).replace(r"\ ", r"\s*")
        brand_pattern = re.compile(rf"\b{escaped_brand}\b", flags=re.IGNORECASE)
        match = brand_pattern.search(str(text or ""))
        if not match:
            continue
        end = next((start for start in starts if start > match.start()), len(str(text or "")))
        segment = str(text or "")[match.start():end]
        offers = _followup_offer_labels_from_text(segment)
        if offers:
            highlights.append(f"{brand} shown offer details: {', '.join(offers)}")
    return highlights


def _followup_offer_labels_from_text(text: str) -> List[str]:
    normalized = _normalize_policy_text(text)
    labels: List[str] = []
    if re.search(r"buy\s*3\s*(?:get|take)\s*1(?:\s*free)?", str(text or ""), flags=re.IGNORECASE):
        labels.append("Buy 3 Get 1 FREE")
    if "bpi" in normalized and ("0%" in str(text or "") or "0 percent" in normalized) and re.search(
        r"\b6\s*(?:mo|mos|month|months)\b", str(text or ""), flags=re.IGNORECASE
    ):
        labels.append("BPI 6mo 0% interest")
    if "tire protection plan" in normalized or re.search(r"\btpp\b", str(text or ""), flags=re.IGNORECASE):
        labels.append("Tire Protection Plan")
    if "warranty" in normalized:
        labels.append("warranty")
    return _unique_strings(labels)


def _shown_product_brands(text: str) -> List[str]:
    display_by_key = {
        "michelin": "Michelin",
        "apollo": "Apollo",
        "fronway": "Fronway",
        "yokohama": "Yokohama",
        "bridgestone": "Bridgestone",
        "goodyear": "Goodyear",
        "westlake": "Westlake",
        "bf goodrich": "BFGoodrich",
        "bfgoodrich": "BFGoodrich",
        "otani": "Otani",
        "triangle": "Triangle",
        "sailun": "Sailun",
        "gt radial": "GT Radial",
        "gtradial": "GT Radial",
    }
    lowered = str(text or "").lower()
    brands = [
        display
        for key, display in display_by_key.items()
        if re.search(rf"\b{re.escape(key)}\b", lowered)
    ]
    return _unique_strings(brands)[:6]


def _format_followup_mapping(value: Mapping[str, Any]) -> str:
    parts = []
    for key, item in value.items():
        if item in (None, "", [], {}):
            continue
        parts.append(f"{key}={item}")
    return ", ".join(parts) if parts else "none"


def _followup_composer_context(context: Mapping[str, Any]) -> Dict[str, Any]:
    compact_messages = _followup_composer_recent_messages(context)
    latest_message = compact_messages[-1] if compact_messages else {}
    return _compact_json(
        {
            "request_time": context.get("request_time") if isinstance(context, Mapping) else "",
            "recent_messages": compact_messages,
            "latest_message": latest_message,
            "deterministic_followup_goal": context.get("deterministic_followup_goal") if isinstance(context, Mapping) else {},
            "followup_priority": _followup_priority_context(context),
            "lead_qualification": context.get("lead_qualification") if isinstance(context, Mapping) else {},
            "normalized_entities": context.get("normalized_entities") if isinstance(context, Mapping) else {},
            "operational_state": _followup_composer_operational_state(context),
            "followup_state": context.get("followup_state") if isinstance(context, Mapping) else {},
            "hydration": context.get("hydration") if isinstance(context, Mapping) else {},
        },
        max_depth=4,
        max_list_items=10,
        max_dict_items=50,
        max_string_chars=700,
    )


def _followup_priority_context(context: Mapping[str, Any]) -> Dict[str, Any]:
    lead = context.get("lead_qualification") if isinstance(context, Mapping) else {}
    goal = context.get("deterministic_followup_goal") if isinstance(context, Mapping) else {}
    if not isinstance(lead, Mapping) and not isinstance(goal, Mapping):
        return {}
    lead_next = str(lead.get("next_best_field") or "").strip() if isinstance(lead, Mapping) else ""
    goal_field = str(goal.get("missing_field") or "").strip() if isinstance(goal, Mapping) else ""
    output = {
        "lead_default_next_best_field": lead_next,
        "contextual_followup_field": goal_field,
        "note": (
            "Use contextual_followup_field for this follow-up when present. "
            "lead_default_next_best_field is the generic lead rule before conversation-specific context."
        ),
    }
    return {key: value for key, value in output.items() if value not in (None, "", [], {})}


def _followup_composer_operational_state(context: Mapping[str, Any]) -> Dict[str, Any]:
    state = context.get("state_signals") if isinstance(context, Mapping) else {}
    if not isinstance(state, Mapping):
        return {}
    keys = (
        "latest_selected_product_context",
        "latest_order_summary_snapshot",
        "latest_submitted_order_context",
        "latest_order_details_context",
        "latest_payment_request_ref",
        "latest_fitment_observation",
    )
    return _compact_json(
        {key: deepcopy(state.get(key)) for key in keys if state.get(key) not in (None, "", [], {})},
        max_depth=4,
        max_list_items=8,
        max_dict_items=30,
        max_string_chars=500,
    )


def _followup_composer_decision(decision: Mapping[str, Any]) -> Dict[str, Any]:
    return _compact_json(
        _redact_followup_pricing_context(deepcopy(dict(decision or {}))),
        max_depth=4,
        max_list_items=10,
        max_dict_items=40,
        max_string_chars=500,
    )


def _normalize_followup_entity_mentions(value: str, context: Mapping[str, Any]) -> str:
    text = str(value or "")
    entities = context.get("normalized_entities") if isinstance(context, Mapping) else {}
    signals = entities.get("signals") if isinstance(entities, Mapping) else []
    brand_display_by_canonical = {
        str(signal.get("value") or "").strip().upper(): _display_entity_value(
            str(signal.get("key") or ""),
            str(signal.get("value") or ""),
        )
        for signal in signals or []
        if isinstance(signal, Mapping)
        and str(signal.get("key") or "") in {"preferred_brands", "required_brands", "excluded_brands"}
        and signal.get("value")
    }
    if not brand_display_by_canonical:
        return text
    for token in _followup_brand_candidate_values(text):
        signals_for_token = _construct_background_signals(
            candidates=[{"key": "preferred_brands", "value": token, "source": "recent_turns", "confidence": "medium"}],
            latest_product_observation={},
        )
        for signal in signals_for_token:
            display = brand_display_by_canonical.get(str(signal.value or "").strip().upper())
            if display:
                text = re.sub(rf"\b{re.escape(token)}\b", display, text, flags=re.IGNORECASE)
                break
    return text


def _followup_tone_guidance(context: Mapping[str, Any]) -> Dict[str, Any]:
    recent_messages = context.get("recent_messages") if isinstance(context, Mapping) else []
    transcript = " ".join(
        str(message.get("content") or "")
        for message in recent_messages[-8:]
        if isinstance(message, Mapping)
    )
    normalized = _normalize_policy_text(transcript)
    taglish_markers = (
        " po",
        "magkano",
        "presyo",
        "gulong",
        "pakitingnan",
        "paki",
        "niyo",
        "nyo",
        "natin",
        "tayo",
        "sige",
        "salamat",
        "bale",
        "kc",
        "kasi",
        "uwe",
        "uwi",
        "papalit",
        "hm",
    )
    if any(marker in f" {normalized}" for marker in taglish_markers):
        return {
            "language": "runtime_v7_taglish",
            "voice": "Use concise casual Gulong Taglish with natural po, matching the main chatbot.",
            "avoid": [
                "straight English",
                "just checking in",
                "had a chance",
                "perfect fit",
                "when you're ready",
                "let me know",
                "Hi there",
            ],
            "preferred_phrases": [
                "Kamusta po",
                "Interested pa po ba kayo?",
                "Na-check niyo na po ba yung exact tire size?",
                "Pa-send po para ma-check ko yung options.",
                "Alin po gusto niyong i-check?",
            ],
        }
    return {
        "language": "match_recent_conversation",
        "voice": "Use the recent conversation language, but keep the concise polite Gulong.ph sales voice.",
    }


def _strip_urls(value: str) -> str:
    return re.sub(r"https?://\S+", "", str(value or "")).strip()


def _redact_contact_numbers(value: str) -> str:
    return re.sub(r"(?:\+?63|0)\s*9\d{2}[\s.-]?\d{3}[\s.-]?\d{4}", "[contact number provided]", str(value or ""))


_FOLLOWUP_AMOUNT_RE = re.compile(
    r"(?:\bPHP\s*|\bP\s*)[\d,]+(?:\.\d+)?|\u20b1\s*[\d,]+(?:\.\d+)?",
    flags=re.IGNORECASE,
)

_FOLLOWUP_PRICING_TERMS_RE = re.compile(
    r"\b(?:price|pricing|presyo|presyu|quote|quotation|estimate|magkano|cost|amount|total|cheapest)\b"
    r"|mas\s+mura|pinaka\s*mura|lowest\s+total",
    flags=re.IGNORECASE,
)


def _remove_unbacked_pricing_language(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(
        r"para\s+ma-(?:check|quote|qoute)\s+ko(?:\s+na)?(?:\s+po)?\s+(?:yung|ang)?\s*"
        r"(?:price|pricing|presyo|quote|quotation|estimate)(?:\s+[^?.!\n]*)?",
        "para ma-check ko po yung available options",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"para\s+(?:maibigay|ma-provide|mabigay)\s+(?:ko\s+)?(?:na\s+)?(?:po\s+)?(?:yung|ang)?\s*"
        r"(?:price|pricing|presyo|quote|quotation|estimate)(?:\s+[^?.!\n]*)?",
        "para ma-check ko po yung available options",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"so\s+i\s+can\s+(?:give|provide|send|check)\s+[^?.!\n]*"
        r"(?:price|pricing|presyo|quote|quotation|estimate|cost)(?:\s+[^?.!\n]*)?",
        "para ma-check ko po yung available options",
        text,
        flags=re.IGNORECASE,
    )
    parts = re.split(r"(\n+|(?<=[.!?])\s+)", text)
    output: List[str] = []
    for index in range(0, len(parts), 2):
        sentence = parts[index].strip()
        separator = parts[index + 1] if index + 1 < len(parts) else ""
        if not sentence:
            continue
        if _FOLLOWUP_PRICING_TERMS_RE.search(sentence) or _FOLLOWUP_AMOUNT_RE.search(sentence):
            continue
        output.append(sentence + separator)
    cleaned = "".join(output).strip()
    if cleaned:
        return cleaned
    text = _FOLLOWUP_AMOUNT_RE.sub("[amount omitted]", text)
    return _FOLLOWUP_PRICING_TERMS_RE.sub("options", text).strip()


def _redact_followup_pricing_context(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _redact_followup_pricing_context(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_followup_pricing_context(item) for item in value]
    if not isinstance(value, str):
        return value
    text = _FOLLOWUP_AMOUNT_RE.sub("[amount omitted]", value)
    text = _FOLLOWUP_PRICING_TERMS_RE.sub("options", text)
    return text


def _normalize_followup_voice(value: str) -> str:
    text = str(value or "").strip()
    text = _strip_stray_question_mark_emoji_markers(text)
    text = re.sub(r"\blet\s+me\s+know\s+po\s+kung\b", "Sabihin niyo lang po kung", text, flags=re.IGNORECASE)
    text = re.sub(r"\blet\s+me\s+know\s+kung\b", "Sabihin niyo lang po kung", text, flags=re.IGNORECASE)
    text = re.sub(r"\blet\s+me\s+know\s+po\b", "Sabihin niyo lang po", text, flags=re.IGNORECASE)
    text = re.sub(r"\blet\s+me\s+know\b", "Sabihin niyo lang po", text, flags=re.IGNORECASE)
    return text


def _strip_stray_question_mark_emoji_markers(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"\s*\?{2,}\s*(?=[\U0001f300-\U0001faff\ufe0f])", " ", text)
    text = re.sub(r"(?<=[.!?])\s+\?{2,}(?=\s|$)", "", text)
    text = re.sub(r"\s+\?{2,}(?=\s|$)", "", text)
    text = re.sub(r"(?<=[.!?])\s*\?{2,}\s*$", "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _normalize_policy_text(value: Any) -> str:
    text = _single_line(value).lower()
    return text.replace("'", "").replace("\"", "")


def _strip_generic_followup_closer(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.sub(
        r"(?:\n\s*)+(?:thanks|thank you|salamat)(?:\s+po)?[.!]*\s*(?:[\U0001f300-\U0001faff\ufe0f]\s*)*$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()


def _strip_standalone_thanks_lines(value: str) -> str:
    lines: List[str] = []
    for line in str(value or "").splitlines():
        if re.fullmatch(
            r"\s*(?:thanks|thank you|salamat)(?:\s+po)?[.!]*\s*(?:[\U0001f300-\U0001faff\ufe0f]\s*)?",
            line,
            flags=re.IGNORECASE,
        ):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _strip_inline_generic_thanks(value: str) -> str:
    return re.sub(
        r"\s+(?:thanks|thank you|salamat)(?:\s+po)?[.!]*(?=\s*(?:[\U0001f300-\U0001faff\ufe0f]|\Z))",
        "",
        str(value or "").strip(),
        flags=re.IGNORECASE,
    ).strip()


def _strip_candidate_size_lists(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parts = re.split(r"(\n+|(?<=[.!?])\s+)", text)
    output: List[str] = []
    for index in range(0, len(parts), 2):
        sentence = parts[index].strip()
        separator = parts[index + 1] if index + 1 < len(parts) else ""
        if not sentence:
            continue
        size_count = len(re.findall(r"\b\d{3}/\d{2}R\d{2}[A-Z]?\b", sentence, flags=re.IGNORECASE))
        lowered = sentence.lower()
        if size_count >= 2 and any(token in lowered for token in ("possible sizes", "mga sizes", "sizes na ito")):
            continue
        output.append(sentence + separator)
    return "".join(output).strip()


def _contains_emoji(value: str) -> bool:
    return any(ord(ch) >= 0x1F300 for ch in str(value or ""))


def _recent_followup_messages(
    conversation_messages: Sequence[Mapping[str, Any]],
    *,
    session_messages: Sequence[Any],
) -> List[Dict[str, Any]]:
    messages = [
        _compact_message(message)
        for message in conversation_messages or []
        if isinstance(message, Mapping)
    ]
    messages = [message for message in messages if message]
    if not messages:
        messages = [_compact_session_message(message) for message in session_messages or []]
        messages = [message for message in messages if message]
    return messages[-12:]


def _compact_message(message: Mapping[str, Any]) -> Dict[str, Any]:
    content = str(message.get("content") or message.get("text") or "").strip()
    if not content:
        return {}
    output = {
        "role": _normalize_role(message.get("role")),
        "content": content[:1200],
        "datetime": str(message.get("datetime") or message.get("ts") or "").strip(),
        "source": str(message.get("source") or "").strip(),
    }
    message_id = str(message.get("message_id") or "").strip()
    if message_id:
        output["message_id"] = message_id
    sender = str(message.get("sender") or "").strip()
    if sender:
        output["sender"] = sender
    kind = str(message.get("message_kind") or "").strip()
    if kind:
        output["message_kind"] = kind
    return output


def _compact_session_message(message: Any) -> Dict[str, Any]:
    role = getattr(message, "role", "")
    text = getattr(message, "text", "")
    ts = getattr(message, "ts", "")
    return _compact_message({"role": role, "content": text, "datetime": ts, "source": "session_messages"})


def _followup_state_signals(v7_state: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(v7_state, Mapping):
        return {}
    active_memory = v7_state.get("active_working_memory") if isinstance(v7_state.get("active_working_memory"), Mapping) else {}
    safe_background_signals = [
        _followup_safe_signal_dict(signal)
        for signal in deepcopy(v7_state.get("background_signals") or [])[-12:]
        if isinstance(signal, Mapping)
    ]
    state = {
        "active_working_memory": str(active_memory.get("text") or "").strip(),
        "recent_turns": deepcopy(v7_state.get("recent_turns") or [])[-4:],
        "background_signals": safe_background_signals,
        "latest_selected_product_context": deepcopy(v7_state.get("latest_selected_product_context") or {}),
        "latest_order_summary_snapshot": deepcopy(v7_state.get("latest_order_summary_snapshot") or {}),
        "latest_submitted_order_context": deepcopy(v7_state.get("latest_submitted_order_context") or {}),
        "latest_order_details_context": deepcopy(v7_state.get("latest_order_details_context") or {}),
        "latest_payment_request_ref": v7_state.get("latest_payment_request_ref") or "",
        "latest_fitment_observation": deepcopy(v7_state.get("latest_fitment_observation") or {}),
    }
    return _compact_json(
        {key: value for key, value in state.items() if value not in (None, "", [], {})},
        max_depth=4,
        max_list_items=12,
        max_dict_items=60,
        max_string_chars=900,
    )


def _loads_json_object(value: Any) -> Dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        payload = json.loads(text)
    except Exception:
        payload = _loads_first_json_object(text)
    return payload if isinstance(payload, dict) else {}


def _loads_first_json_object(text: str) -> Dict[str, Any]:
    start = str(text or "").find("{")
    if start < 0:
        return {}
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    payload = json.loads(text[start : index + 1])
                except Exception:
                    return {}
                return payload if isinstance(payload, dict) else {}
    return {}


def _normalize_role(value: Any) -> str:
    role = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if role in {"customer", "subscriber", "client", "msgin"}:
        return "user"
    if role in {"bot", "chatbot", "ai", "msgout_api", "msgout_default"}:
        return "assistant"
    if role in {"agent", "human", "human_agent", "staff", "admin", "cs", "msgout_lc"}:
        return "human_agent"
    return role or "unknown"


def _single_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def _short_hash(value: Any) -> str:
    payload = json.dumps(_jsonable(value), sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _compact_json(
    value: Any,
    *,
    max_depth: int = 4,
    max_list_items: int = 12,
    max_dict_items: int = 60,
    max_string_chars: int = 900,
) -> Any:
    value = _jsonable(value)
    if max_depth <= 0:
        if isinstance(value, (dict, list)):
            return {"truncated": True, "type": type(value).__name__}
        if isinstance(value, str) and len(value) > max_string_chars:
            return value[:max_string_chars] + "...[truncated]"
        return value
    if isinstance(value, dict):
        output: Dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_dict_items:
                output["_truncated_keys"] = max(0, len(value) - max_dict_items)
                break
            output[str(key)] = _compact_json(
                item,
                max_depth=max_depth - 1,
                max_list_items=max_list_items,
                max_dict_items=max_dict_items,
                max_string_chars=max_string_chars,
            )
        return output
    if isinstance(value, list):
        output = [
            _compact_json(
                item,
                max_depth=max_depth - 1,
                max_list_items=max_list_items,
                max_dict_items=max_dict_items,
                max_string_chars=max_string_chars,
            )
            for item in value[:max_list_items]
        ]
        if len(value) > max_list_items:
            output.append({"truncated_items": len(value) - max_list_items})
        return output
    if isinstance(value, str) and len(value) > max_string_chars:
        return value[:max_string_chars] + "...[truncated]"
    return value


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        try:
            return _jsonable(value.to_dict())
        except Exception:
            pass
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump())
        except Exception:
            pass
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
