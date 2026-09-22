"""Production-safe Runtime V7 follow-up contracts and pure policy helpers.

This module deliberately contains no delivery or persistence side effects. It
builds a source-separated case, defines the one-call model contract, validates
the model plan, and appends exact customer-facing benefit lines from delivered
evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Set

from pydantic import BaseModel, Field

from runtime.http.sync_http_client import SyncHTTPClient, SyncHTTPClientConfig
from runtime_v7.lead_qualification import build_lead_qualification_snapshot
from runtime_v7.product_search import DEFAULT_API_BASE_URL
MANILA_TZ = timezone(timedelta(hours=8))
FOLLOWUP_FIELDS = (
    "tire_size",
    "location",
    "tire_brand",
    "contact_number",
    "installation_partner",
    "schedule",
    "payment_option",
)
LEAD_QUALIFICATION_FIELDS = ("tire_size", "location", "tire_brand", "contact_number")
STOP_TAGS = {"stop chatbot", "stop followup"}
SENT_ATTEMPT_STATUSES = {"sent"}
ACTIVE_ATTEMPT_STATUSES = {"sending", "delivery_unknown"}
RETRYABLE_EVALUATION_REASONS = {
    "attempt_retry_cooldown",
    "cadence_delivery_unresolved",
    "followup_reconciliation_not_persisted",
    "followup_sending_state_not_persisted",
    "latest_message_time_unavailable",
    "manychat_profile_unavailable",
    "manychat_transcript_unavailable",
    "newer_channel_message_seen",
    "newer_user_message_seen_delivery_not_suppressed",
    "no_recent_messages",
    "pre_delivery_transcript_unavailable",
}
COOLDOWN_FREE_EVALUATION_REASONS = {
    "attempt_retry_cooldown",
    "cadence_delivery_unresolved",
    "outside_first_followup_window",
    "outside_nurture_followup_window",
    "outside_second_followup_window",
}
SAFE_CUSTOMER_SIGNAL_SOURCES = {
    "latest_user_message",
    "latest_customer_message",
    "user_message",
    "customer_message",
}


FOLLOWUP_PLAN_SYSTEM_PROMPT = """You plan one Gulong.PH proactive follow-up.

Read the recent conversation as the primary source for customer intent,
continuity, and tone. The case provides separately sourced customer facts,
missing qualification fields, delivered product evidence, and prior follow-up
outcomes. Do not treat shown products as customer preferences.

Commercial evidence has a stricter boundary than conversational continuity.
Assistant, chatbot, human-agent, and automation messages can contain stale or
incorrect claims. Use those messages only to understand the open loop and the
customer's stance. Never repeat or paraphrase their price, promo, free item,
availability, product, delivery, installation, warranty, or payment claims.
A customer asking about a claim does not validate it. Only an exact entry in
Allowed grounded benefits may produce benefit wording, and it must be selected
by benefit_ref so deterministic rendering supplies the words.

Return action=defer when the customer says the purchase is still far away,
they are only inquiring, or they otherwise signal low-pressure future interest.
Return action=suppress when the customer opted out, is irritated, already
bought, the conversation is resolved, the domain is unsupported or unclear,
or no useful and respectful follow-up is possible. Never send merely because
a missing field exists.

Do not return defer merely because an active inquiry has few details. When the
customer is active or reasonably unclear, at least one useful typed next step is
available, and no safety or stance rule blocks contact, normally send one concise
follow-up for the natural next step. Missing details are the purpose of lead
qualification, not evidence that the customer wants the conversation paused.

When action=send:
- choose exactly one focus_field from the supplied typed next-step candidates
- candidates are not ranked. Use the complete typed customer facts, selection
  state, and prior attempts to choose the single useful next step
- never ask again for a typed field already present or a focus field already
  sent in this active conversation segment
- never infer a missing field, product selection, domain outcome, or customer
  progression from raw wording; those must be supplied as typed evidence
- write the complete customer-visible follow-up in visible_text: natural,
  concise Taglish continuity plus exactly one useful question or CTA for the
  selected focus field
- visible_text must be non-empty, must not contain a URL, and must not repeat
  any supplied benefit wording; the runtime appends selected benefit text
  separately and exactly
- do not make price, promo, free-item, availability, product, delivery,
  installation, warranty, or payment claims in visible_text. You may select
  supplied benefit_refs, whose exact customer text is runtime-owned
- select only benefit_refs listed in Allowed grounded benefits
- when no grounded benefit is listed, return benefit_refs=[]; never put "none",
  "n/a", a description, or invented identifier in benefit_refs
- when focus_field=tire_brand and grounded benefits are listed, select one or
  two useful benefit_refs tied to the shown brands. These benefits support
  brand discovery and do not require an existing customer brand preference
- use tire_brand only when the customer has not already stated a preference
- use contact_number only when the conversation is ready for assistance,
  reservation, or handoff
- use installation_partner or schedule only with validated selected-product
  context and clear progression in the supplied case
- reason is internal and must be one short sentence, at most 240 characters;
  do not recap the conversation

Tone is concise, casual Gulong Taglish with natural "po", friendly and
sales-oriented without pressure. The model owns the complete ordinary prose
and one reasoned CTA; deterministic rendering owns only selected exact benefit
text. Return JSON only."""


class RuntimeV7FollowupPlanModel(BaseModel):
    """Structured output from the single proactive follow-up model call."""

    action: Literal["send", "defer", "suppress"] = "suppress"
    customer_stance: Literal["active", "unclear", "deferred", "closed"] = "unclear"
    focus_field: Optional[
        Literal[
            "tire_size",
            "location",
            "tire_brand",
            "contact_number",
            "installation_partner",
            "schedule",
            "payment_option",
        ]
    ] = None
    visible_text: str = Field(
        default="",
        max_length=360,
        description=(
            "Complete natural customer-visible follow-up, including exactly one useful question or CTA. "
            "Do not repeat supplied benefit wording or make commercial claims."
        ),
    )
    benefit_refs: List[str] = Field(
        default_factory=list,
        max_length=2,
        description="Zero to two exact supplied benefit_ref identifiers. Use an empty list when none are supplied.",
    )
    reason: str = Field(default="", max_length=300)


def build_followup_plan_response_model(case: Mapping[str, Any]) -> type[RuntimeV7FollowupPlanModel]:
    """Return the stable plan schema; typed case state drives valid focus choice.

    Case-specific candidates belong in the prompt and validator, not in a
    dynamically narrowed response schema that silently preselects the model's
    next step.
    """

    del case
    return RuntimeV7FollowupPlanModel


def load_current_promo_brands(
    *,
    http_client: Optional[SyncHTTPClient] = None,
) -> Dict[str, Any]:
    """Return the current Buy 3 Get 1 brand authority from Gulong API."""

    client = http_client or SyncHTTPClient(
        config=SyncHTTPClientConfig(
            base_url=os.getenv("GULONG_API_BASE_URL", DEFAULT_API_BASE_URL),
            timeout_connect_s=float(os.getenv("RUNTIME_V7_FOLLOWUP_PROMO_CONNECT_TIMEOUT_S", "2.0") or "2.0"),
            timeout_read_s=float(os.getenv("RUNTIME_V7_FOLLOWUP_PROMO_READ_TIMEOUT_S", "4.0") or "4.0"),
        )
    )
    try:
        payload = client.get_json("/promo_brands")
    except Exception as exc:
        return {
            "status": "unavailable",
            "brands": [],
            "reason": "promo_brand_lookup_failed",
            "error_type": type(exc).__name__,
        }
    if not isinstance(payload, list):
        return {"status": "unavailable", "brands": [], "reason": "promo_brand_lookup_failed"}
    brands = sorted(
        {
            str(item.get("brand") or "").strip().upper()
            for item in payload
            if isinstance(item, Mapping) and str(item.get("brand") or "").strip()
        }
    )
    return {"status": "ok", "brands": brands}


def build_followup_case(
    *,
    request_time: str,
    recent_messages: Sequence[Mapping[str, Any]],
    v7_state: Mapping[str, Any],
    profile_fields: Mapping[str, Any],
    cadence: str,
    promo_brand_result: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the minimal source-separated case supplied to the model."""

    messages = [_compact_message(item) for item in recent_messages if isinstance(item, Mapping)]
    messages = [item for item in messages if item][-12:]
    latest = dict(messages[-1]) if messages else {}
    latest_customer = next((dict(item) for item in reversed(messages) if item.get("role") == "user"), {})
    anchor_id, anchor_source = _conversation_anchor(latest_customer)
    trusted_facts = _trusted_customer_facts(v7_state, profile_fields)
    lead = _lead_qualification(trusted_facts)
    followup_state = _followup_state(v7_state)
    attempts = _attempts_for_anchor(followup_state, anchor_id)
    attempts = _reconcile_unknown_attempts(attempts, messages)
    sent_fields = _sent_focus_fields(followup_state, attempts)
    presentations = _eligible_product_presentations(v7_state, request_time=request_time)
    presented_brands = _presented_brands(presentations)
    customer_brand = str((trusted_facts.get("tire_brand") or {}).get("value") or "").strip()
    selected_product = _selected_product_context(v7_state)
    if selected_product and not _selected_product_matches_presentations(selected_product, presentations):
        selected_product = {}
    service_context = _selected_service_context(v7_state)
    domain_assessment = _typed_domain_assessment(v7_state)
    completion = _completion_context(v7_state, messages)
    next_step_candidates = _next_step_candidates(
        lead=lead,
        sent_fields=sent_fields,
        selected_product=selected_product,
        service_context=service_context,
    )
    benefits = _grounded_benefits(
        presentations,
        promo_brand_result=promo_brand_result or {},
    )
    preferred_brands = _brand_preferences(customer_brand)
    if preferred_brands:
        benefits = [
            item
            for item in benefits
            if not str(item.get("brand") or "").strip()
            or str(item.get("brand") or "").strip().upper() in preferred_brands
        ]
    return {
        "schema_version": 2,
        "request_time": str(request_time or ""),
        "cadence": _normalize_cadence(cadence),
        "route": "customer_turn_recovery" if latest.get("role") == "user" else "proactive_followup",
        "conversation_anchor_id": anchor_id,
        "conversation_anchor_source": anchor_source,
        "latest_message": latest,
        "latest_customer_message": latest_customer,
        "recent_messages": messages[-12:],
        "customer_facts": trusted_facts,
        "lead_qualification": lead,
        "next_step_candidates": next_step_candidates,
        "sent_focus_fields": sent_fields,
        "prior_attempts": attempts[-8:],
        "customer_brand_preference": customer_brand,
        "presented_brands": presented_brands,
        "product_presentations": presentations[-3:],
        "allowed_benefits": benefits,
        "promo_brand_authority": {
            "status": str((promo_brand_result or {}).get("status") or "not_loaded"),
            "checked_brands": list((promo_brand_result or {}).get("brands") or []),
        },
        "selected_product_ref": str(
            selected_product.get("item_ref")
            or selected_product.get("product_id")
            or selected_product.get("product_presentation_ref")
            or ""
        ),
        "selected_product_context": selected_product,
        "selected_installation_context": service_context,
        "schedule_readiness": bool(selected_product and service_context),
        "domain_assessment": domain_assessment,
        "domain_status": str(domain_assessment.get("status") or "unknown"),
        "completion": completion,
        "profile_status": {
            "loaded": bool(profile_fields),
            "tags": _tag_names(profile_fields),
            "assigned_agent": str(
                profile_fields.get("assigned_agent") or profile_fields.get("agent_assigned") or ""
            ).strip(),
        },
    }


def build_followup_plan_messages(case: Mapping[str, Any]) -> List[Dict[str, str]]:
    """Render a compact prose case packet for the one-call model."""

    lines: List[str] = [
        f"Request time: {case.get('request_time') or 'unknown'}",
        f"Cadence: {case.get('cadence') or 'first'}",
        "Customer stance must be inferred from the conversation.",
        f"Typed domain assessment: {case.get('domain_status') or 'unknown'}",
        "",
        "Lead qualification:",
        f"- Present: {_format_fact_values((case.get('lead_qualification') or {}).get('present') or {})}",
        f"- Missing: {_format_list((case.get('lead_qualification') or {}).get('missing') or [])}",
        f"- Previously sent focus fields: {_format_list(case.get('sent_focus_fields') or [])}",
        "",
        "Customer-stated facts:",
    ]
    facts = case.get("customer_facts") if isinstance(case.get("customer_facts"), Mapping) else {}
    if facts:
        for key, item in facts.items():
            item = item if isinstance(item, Mapping) else {"value": item}
            value = "provided" if key == "contact_number" else str(item.get("value") or "")
            lines.append(
                f"- {key}: {value} (source={item.get('source') or 'unknown'}, "
                f"evidence={item.get('evidence_message_id') or 'none'}, "
                f"source_time={item.get('source_timestamp') or 'unknown'})"
            )
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "Delivered product context:",
            f"- Customer brand preference: {case.get('customer_brand_preference') or 'none'}",
            f"- Shown brands: {_format_list(case.get('presented_brands') or [])}",
            f"- Selected product ref: {case.get('selected_product_ref') or 'none'}",
            f"- Typed installation selection present: {bool(case.get('selected_installation_context'))}",
            f"- Typed schedule readiness: {bool(case.get('schedule_readiness'))}",
            f"- Typed domain evidence: {((case.get('domain_assessment') or {}).get('evidence_ref') if isinstance(case.get('domain_assessment'), Mapping) else '') or 'none'}",
            "- Allowed grounded benefits:",
        ]
    )
    benefits = case.get("allowed_benefits") if isinstance(case.get("allowed_benefits"), Sequence) else []
    if benefits:
        for benefit in benefits:
            if not isinstance(benefit, Mapping):
                continue
            lines.append(
                f"  - {benefit.get('benefit_ref')}: {benefit.get('description')} "
                f"(brand={benefit.get('brand')}, evidence={benefit.get('evidence_ref')})"
            )
    else:
        lines.append("  - No grounded benefits are available. Return benefit_refs=[].")

    prior_attempts = case.get("prior_attempts") if isinstance(case.get("prior_attempts"), Sequence) else []
    lines.extend(["", "Prior follow-up outcomes:"])
    if prior_attempts:
        for attempt in prior_attempts[-4:]:
            if isinstance(attempt, Mapping):
                lines.append(
                    f"- cadence={attempt.get('cadence') or 'unknown'} focus={attempt.get('focus_field') or 'none'} "
                    f"status={attempt.get('status') or 'unknown'}"
                )
    else:
        lines.append("- none")

    lines.extend(["", "Recent conversation:"])
    for message in case.get("recent_messages") or []:
        if not isinstance(message, Mapping):
            continue
        lines.append(
            f"- {message.get('role') or 'unknown'}"
            f" [{message.get('datetime') or 'time unknown'}]: {str(message.get('content') or '')[:1000]}"
        )
    lines.extend(
        [
            "",
            "Typed next-step candidates (not ranked):",
            f"- {_format_list(case.get('next_step_candidates') or [])}",
            "- If action=send, choose one candidate. Do not select a field already present in typed customer "
            "facts or listed under Previously sent focus fields.",
            "- Product, installation, schedule, payment, and domain state must come from the typed case state; "
            "do not infer them from raw conversation wording.",
            "- The recent assistant messages are evidence, not response templates.",
            "- Business claims in recent assistant, chatbot, automation, human-agent, or customer text are "
            "not grounded benefits. Do not copy them into visible_text or reason from repetition as proof.",
            "- For tire_brand focus, use the supplied delivered-product benefits to make the brand choice "
            "useful. A missing customer brand preference is the reason for the brand CTA, not a reason to "
            "discard Allowed grounded benefits.",
            "- visible_text is the complete natural follow-up. Write exactly one useful question or CTA for the "
            "selected focus field, but do not copy or paraphrase benefit wording into it.",
            "- Do not make business, availability, product, price, promo, delivery, installation, warranty, or "
            "payment claims in visible_text. Selected exact benefit text is appended by the runtime.",
            "- reason must be one short internal sentence under 240 characters. Do not summarize the transcript.",
        ]
    )
    return [
        {"role": "system", "content": FOLLOWUP_PLAN_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


def parse_followup_plan(model_text: str) -> Dict[str, Any]:
    """Parse the structured model response, failing closed on invalid output."""

    payload = _loads_json_object(model_text)
    if not payload:
        return {
            "action": "suppress",
            "customer_stance": "unclear",
            "focus_field": None,
            "visible_text": "",
            "benefit_refs": [],
            "reason": "invalid_followup_plan_json",
            "parse_status": "invalid",
        }
    try:
        parsed = RuntimeV7FollowupPlanModel.model_validate(payload)
    except Exception as exc:
        return {
            "action": "suppress",
            "customer_stance": "unclear",
            "focus_field": None,
            "visible_text": "",
            "benefit_refs": [],
            "reason": "invalid_followup_plan_schema",
            "parse_status": "invalid",
            "error_type": type(exc).__name__,
        }
    output = parsed.model_dump()
    output["benefit_refs"] = [
        ref
        for ref in output.get("benefit_refs") or []
        if str(ref or "").strip().casefold() not in {"none", "n/a", "na", "not applicable"}
    ]
    output["parse_status"] = "valid"
    return output


def validate_and_render_followup(
    case: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    max_chars: int = 450,
) -> Dict[str, Any]:
    """Validate structural follow-up invariants and append exact benefit lines.

    The model owns ordinary visible prose and its one reasoned CTA. Runtime
    validation deliberately does not phrase-classify or rewrite that prose.
    """

    action = str(plan.get("action") or "suppress").strip().lower()
    if action != "send":
        return {
            "status": "not_applicable",
            "action": action if action in {"defer", "suppress"} else "suppress",
            "message": "",
            "focus_field": None,
            "validation_reasons": [],
            "evidence_refs": [],
            "benefit_refs": [],
        }

    reasons: List[str] = []
    stance = str(plan.get("customer_stance") or "unclear").strip().lower()
    if stance in {"deferred", "closed"}:
        reasons.append(f"send_conflicts_with_{stance}_stance")
    focus = str(plan.get("focus_field") or "").strip()
    candidates = [str(item) for item in case.get("next_step_candidates") or [] if str(item).strip()]
    if focus not in candidates:
        reasons.append("focus_field_not_candidate")
    if focus not in FOLLOWUP_FIELDS:
        reasons.append("focus_field_invalid")
    visible_text = _clean_visible_text(plan.get("visible_text"))
    if not visible_text:
        reasons.append("visible_text_empty")
    elif len(visible_text) > 360:
        reasons.append("visible_text_too_long")

    allowed = {
        str(item.get("benefit_ref") or ""): dict(item)
        for item in case.get("allowed_benefits") or []
        if isinstance(item, Mapping) and str(item.get("benefit_ref") or "").strip()
    }
    selected_refs = [str(item) for item in plan.get("benefit_refs") or [] if str(item).strip()]
    if len(selected_refs) > 2:
        reasons.append("too_many_benefit_refs")
    invalid_refs = [ref for ref in selected_refs if ref not in allowed]
    if invalid_refs:
        reasons.append("benefit_ref_not_allowed")
    selected = [allowed[ref] for ref in selected_refs if ref in allowed][:2]
    if reasons:
        return {
            "status": "invalid",
            "action": "suppress",
            "message": "",
            "focus_field": focus or None,
            "validation_reasons": _unique(reasons),
            "evidence_refs": [],
            "benefit_refs": selected_refs,
        }

    benefit_lines = [str(item.get("customer_text") or "").strip() for item in selected]
    benefit_lines = [item for item in benefit_lines if item]
    message = _assemble_message(visible_text, benefit_lines, max_chars=max_chars)
    if not message:
        return {
            "status": "invalid",
            "action": "suppress",
            "message": "",
            "focus_field": focus,
            "validation_reasons": ["rendered_message_empty"],
            "evidence_refs": [],
            "benefit_refs": selected_refs,
        }
    return {
        "status": "valid",
        "action": "send",
        "message": message,
        "focus_field": focus,
        "validation_reasons": [],
        "evidence_refs": _unique([str(item.get("evidence_ref") or "") for item in selected]),
        "benefit_refs": selected_refs,
    }


def proactive_followup_gate(case: Mapping[str, Any]) -> Dict[str, Any]:
    """Return deterministic admission for the assistant-last proactive route."""

    latest = case.get("latest_message") if isinstance(case.get("latest_message"), Mapping) else {}
    role = str(latest.get("role") or "").strip()
    if role != "assistant":
        return {"status": "suppress", "reason": "latest_message_not_assistant"}
    domain_assessment = case.get("domain_assessment") if isinstance(case.get("domain_assessment"), Mapping) else {}
    if (
        str(domain_assessment.get("status") or "") == "unsupported_or_unresolved"
        and str(domain_assessment.get("evidence_ref") or "").strip()
    ):
        return {"status": "suppress", "reason": "unsupported_or_unresolved_domain"}
    completion = case.get("completion") if isinstance(case.get("completion"), Mapping) else {}
    if bool(completion.get("is_complete")):
        return {
            "status": "suppress",
            "reason": str(completion.get("reason") or "conversation_already_converted"),
        }
    age_minutes = _age_minutes(case.get("request_time"), latest.get("datetime"))
    if age_minutes is None:
        return {"status": "suppress", "reason": "latest_message_time_unavailable"}
    cadence = _normalize_cadence(case.get("cadence"))
    for attempt in case.get("prior_attempts") or []:
        if not isinstance(attempt, Mapping):
            continue
        stance = str(attempt.get("stance") or "")
        if stance == "closed":
            return {"status": "suppress", "reason": "customer_stance_closed", "age_minutes": age_minutes}
        if cadence in {"first", "second"} and stance == "deferred" and str(attempt.get("status") or "") == "deferred":
            return {"status": "suppress", "reason": "customer_stance_deferred", "age_minutes": age_minutes}
        if str(attempt.get("cadence") or "") != cadence:
            continue
        status = str(attempt.get("status") or "")
        attempt_reason = _attempt_reason(attempt)
        if status == "suppressed" and is_retryable_evaluation_reason(attempt_reason):
            status = "evaluated"
        if status in SENT_ATTEMPT_STATUSES:
            return {"status": "suppress", "reason": "cadence_already_sent", "age_minutes": age_minutes}
        if status in {"deferred", "suppressed"}:
            return {"status": "suppress", "reason": f"cadence_already_{status}", "age_minutes": age_minutes}
        if status in ACTIVE_ATTEMPT_STATUSES:
            return {"status": "suppress", "reason": "cadence_delivery_unresolved", "age_minutes": age_minutes}
        retryable_status = status in {"delivery_failed", "validation_failed", "evaluated"}
        cooldown_free = status == "evaluated" and attempt_reason in COOLDOWN_FREE_EVALUATION_REASONS
        if retryable_status and not cooldown_free and _attempt_in_retry_cooldown(attempt, case.get("request_time")):
            return {"status": "suppress", "reason": "attempt_retry_cooldown", "age_minutes": age_minutes}
    if cadence == "first" and not _within_window(age_minutes, "RUNTIME_V7_FOLLOWUP_FIRST_MIN_MINUTES", 45, "RUNTIME_V7_FOLLOWUP_FIRST_MAX_MINUTES", 180):
        return {"status": "suppress", "reason": "outside_first_followup_window", "age_minutes": age_minutes}
    if cadence == "second" and not _within_window(age_minutes, "RUNTIME_V7_FOLLOWUP_SECOND_MIN_MINUTES", 660, "RUNTIME_V7_FOLLOWUP_SECOND_MAX_MINUTES", 1440):
        return {"status": "suppress", "reason": "outside_second_followup_window", "age_minutes": age_minutes}
    if cadence == "nurture" and age_minutes < float(os.getenv("RUNTIME_V7_FOLLOWUP_NURTURE_MIN_MINUTES", "1440") or "1440"):
        return {"status": "suppress", "reason": "outside_nurture_followup_window", "age_minutes": age_minutes}
    if not case.get("next_step_candidates"):
        return {"status": "suppress", "reason": "no_typed_next_step_candidates", "age_minutes": age_minutes}
    return {"status": "allow", "reason": "eligible_proactive_followup", "age_minutes": age_minutes}


def customer_recovery_gate(case: Mapping[str, Any]) -> Dict[str, Any]:
    """Return deterministic admission for a customer-last recovery route."""

    latest = case.get("latest_message") if isinstance(case.get("latest_message"), Mapping) else {}
    if str(latest.get("role") or "") != "user":
        return {"status": "suppress", "reason": "latest_message_not_customer"}
    age_minutes = _age_minutes(case.get("request_time"), latest.get("datetime"))
    if age_minutes is None:
        return {"status": "suppress", "reason": "customer_message_time_unavailable"}
    max_age_minutes = float(os.getenv("RUNTIME_V7_FOLLOWUP_RECOVERY_MAX_MINUTES", "1440") or "1440")
    if age_minutes > max_age_minutes:
        return {"status": "suppress", "reason": "customer_message_recovery_stale", "age_minutes": age_minutes}
    return {"status": "allow", "reason": "eligible_customer_turn_recovery", "age_minutes": age_minutes}


def followup_stop_reason(
    *,
    profile_fields: Mapping[str, Any],
    recent_messages: Sequence[Mapping[str, Any]],
) -> str:
    """Return a trusted stop-tag or human-takeover reason."""

    tags = {item.casefold() for item in _tag_names(profile_fields)}
    stopped = sorted(STOP_TAGS.intersection(tags))
    if stopped:
        return "stop_tag:" + stopped[0].replace(" ", "_")
    if _human_agent_after_latest_customer(recent_messages):
        return "human_agent_message_after_latest_customer"
    assigned = str(profile_fields.get("assigned_agent") or profile_fields.get("agent_assigned") or "").strip()
    if assigned and _assigned_agent_is_human(assigned):
        return "human_agent_assigned"
    return ""


def build_attempt_record(
    *,
    case: Mapping[str, Any],
    plan: Mapping[str, Any],
    validation: Mapping[str, Any],
    status: str,
    request_id: str,
    delivery_result: Optional[Mapping[str, Any]] = None,
    existing_attempt_id: str = "",
) -> Dict[str, Any]:
    """Build one bounded durable follow-up attempt record."""

    now = str(case.get("request_time") or _now_manila())
    basis = {
        "anchor": case.get("conversation_anchor_id"),
        "cadence": case.get("cadence"),
        "request_id": request_id,
    }
    attempt_id = existing_attempt_id or "fu_" + _short_hash(basis, length=20)
    message = str(validation.get("message") or "")
    return {
        "attempt_id": attempt_id,
        "trigger_key": f"{case.get('conversation_anchor_id') or 'unknown'}:{case.get('cadence') or 'first'}",
        "conversation_anchor_id": str(case.get("conversation_anchor_id") or ""),
        "cadence": str(case.get("cadence") or "first"),
        "route": str(case.get("route") or "proactive_followup"),
        "action": str(plan.get("action") or validation.get("action") or "suppress"),
        "stance": str(plan.get("customer_stance") or "unclear"),
        "focus_field": str(validation.get("focus_field") or plan.get("focus_field") or ""),
        "status": str(status or "evaluated"),
        "message_hash": _short_hash({"message": message}, length=24) if message else "",
        "evidence_refs": list(validation.get("evidence_refs") or [])[:8],
        "benefit_refs": list(validation.get("benefit_refs") or [])[:4],
        "validation_status": str(validation.get("status") or "not_applicable"),
        "validation_reasons": list(validation.get("validation_reasons") or [])[:8],
        "request_id": str(request_id or ""),
        "created_at": now,
        "updated_at": now,
        "delivery_result": _compact_delivery_result(delivery_result or {}),
        "reason": str(
            (delivery_result or {}).get("reason")
            or validation.get("reason")
            or plan.get("reason")
            or ""
        )[:240],
    }


def upsert_attempt(
    followup_state: Mapping[str, Any],
    attempt: Mapping[str, Any],
    *,
    limit: int = 20,
) -> Dict[str, Any]:
    """Return follow-up state with one versioned attempt inserted or updated."""

    state = dict(followup_state or {})
    attempts = [dict(item) for item in state.get("attempts") or [] if isinstance(item, Mapping)]
    attempt_id = str(attempt.get("attempt_id") or "")
    attempts = [item for item in attempts if str(item.get("attempt_id") or "") != attempt_id]
    attempts.append(dict(attempt))
    state.update(
        {
            "version": 2,
            "attempts": attempts[-max(1, int(limit or 20)) :],
            "last_attempt_id": attempt_id,
            "last_status": str(attempt.get("status") or ""),
            "last_route": str(attempt.get("route") or ""),
            "last_action": str(attempt.get("action") or ""),
            "last_focus_field": str(attempt.get("focus_field") or ""),
            "updated_at": str(attempt.get("updated_at") or _now_manila()),
        }
    )
    sent_fields = _unique(
        [
            str(item.get("focus_field") or "")
            for item in attempts
            if str(item.get("status") or "") == "sent" and str(item.get("focus_field") or "")
        ]
    )
    state["sent_focus_fields"] = sent_fields[-8:]
    if str(attempt.get("status") or "") == "sent":
        state["last_sent_focus_field"] = str(attempt.get("focus_field") or "")
        state["last_sent_at"] = str(attempt.get("updated_at") or _now_manila())
        state["last_message_hash"] = str(attempt.get("message_hash") or "")
    return state


def _trusted_customer_facts(
    v7_state: Mapping[str, Any],
    profile_fields: Mapping[str, Any],
) -> Dict[str, Dict[str, str]]:
    """Return lead facts from durable typed signals and trusted profile fields.

    Raw transcript text is conversational context only. It must not become
    qualification state through local regex recovery or text matching here;
    the typed signal pipeline owns that interpretation boundary.
    """

    facts: Dict[str, Dict[str, str]] = {}
    key_aliases = {
        "tire_size": "tire_size",
        "location": "location",
        "contact_number": "contact_number",
        "preferred_brands": "tire_brand",
        "required_brands": "tire_brand",
        "tire_brand": "tire_brand",
    }
    signals = v7_state.get("background_signals") if isinstance(v7_state, Mapping) else []
    for signal in reversed(list(signals or [])):
        if not isinstance(signal, Mapping):
            continue
        field = key_aliases.get(str(signal.get("key") or "").strip())
        source = str(signal.get("source") or "").strip()
        value = signal.get("value")
        if not field or field in facts or value in (None, "", [], {}):
            continue
        if source not in SAFE_CUSTOMER_SIGNAL_SOURCES:
            continue
        metadata = signal.get("metadata") if isinstance(signal.get("metadata"), Mapping) else {}
        facts[field] = {
            "value": _fact_value(value),
            "source": source,
            "evidence_message_id": str(
                signal.get("message_id")
                or signal.get("source_message_id")
                or metadata.get("message_id")
                or metadata.get("source_message_id")
                or ""
            ),
            "source_timestamp": str(
                signal.get("source_timestamp")
                or signal.get("created_at")
                or ""
            ),
        }

    for field, value in _profile_lead_values(profile_fields).items():
        if field in facts or value in (None, "", [], {}):
            continue
        facts[field] = {
            "value": _fact_value(value),
            "source": "manychat_profile",
            "evidence_message_id": "profile",
            "source_timestamp": str(profile_fields.get("profile_loaded_at") or ""),
        }
    if "contact_number" in facts:
        # The follow-up planner only needs presence. Do not retain phone-number
        # PII in the case packet, tester output, or context fingerprint.
        facts["contact_number"]["value"] = "provided"
        facts["contact_number"]["display_value"] = "provided"
    return facts


def _redact_contact_numbers(value: str) -> str:
    return re.sub(
        r"(?<!\d)(?:\+?63|0)\s*9\d{2}(?:[\s.-]*\d){7}(?!\d)",
        "[contact number provided]",
        str(value or ""),
    )


def _normalized_text(value: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split())


def _lead_qualification(facts: Mapping[str, Mapping[str, str]]) -> Dict[str, Any]:
    signals = []
    for field, item in facts.items():
        key = "preferred_brands" if field == "tire_brand" else field
        signals.append({"key": key, "value": item.get("value")})
    snapshot = build_lead_qualification_snapshot(signals).to_dict()
    present = {
        field: ("provided" if field == "contact_number" else str(item.get("value") or ""))
        for field, item in facts.items()
        if field in LEAD_QUALIFICATION_FIELDS and str(item.get("value") or "").strip()
    }
    missing = [field for field in LEAD_QUALIFICATION_FIELDS if not present.get(field)]
    return {
        "status": "complete" if snapshot.get("moderate_intent") else "incomplete",
        "moderate_intent": bool(snapshot.get("moderate_intent")),
        "present": present,
        "missing": missing,
        "qualification_fields": list(LEAD_QUALIFICATION_FIELDS),
        "rule": snapshot.get("rule"),
    }


def _next_step_candidates(
    *,
    lead: Mapping[str, Any],
    sent_fields: Sequence[str],
    selected_product: Mapping[str, Any],
    service_context: Mapping[str, Any],
) -> List[str]:
    """Return all safe typed next steps without prescribing their priority."""

    sent = {str(item) for item in sent_fields}
    missing = [str(item) for item in lead.get("missing") or [] if str(item).strip()]
    eligible = [field for field in missing if field not in sent]
    if selected_product:
        if "installation_partner" not in sent and not _typed_context_has_field(service_context, "installation_partner"):
            eligible.append("installation_partner")
        if "payment_option" not in sent and not _typed_context_has_field(selected_product, "payment_option"):
            eligible.append("payment_option")
        if (
            service_context
            and "schedule" not in sent
            and not _typed_context_has_field(service_context, "schedule")
        ):
            eligible.append("schedule")
    return _unique(eligible)


def _eligible_product_presentations(
    v7_state: Mapping[str, Any],
    *,
    request_time: str,
) -> List[Dict[str, Any]]:
    now = _parse_datetime(request_time)
    ttl_hours = float(os.getenv("RUNTIME_V7_FOLLOWUP_PRESENTATION_TTL_HOURS", "24") or "24")
    output: List[Dict[str, Any]] = []
    for entry in v7_state.get("product_presentation_history") or []:
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("delivery_status") or "").strip().lower() != "success":
            continue
        delivered_at = _parse_datetime(entry.get("delivered_at") or entry.get("created_at"))
        expires_at = _parse_datetime(entry.get("expires_at"))
        if now and expires_at and now >= expires_at:
            continue
        if not expires_at and now and delivered_at and now - delivered_at > timedelta(hours=max(1.0, ttl_hours)):
            continue
        cards = [_compact_product_card(card) for card in entry.get("cards") or [] if isinstance(card, Mapping)]
        cards = [card for card in cards if card]
        if not cards:
            continue
        output.append(
            {
                "presentation_ref": str(entry.get("presentation_ref") or ""),
                "observation_ref": str(entry.get("observation_ref") or ""),
                "delivered_at": str(entry.get("delivered_at") or entry.get("created_at") or ""),
                "delivery_status": "success",
                "cards": cards[:6],
                "inclusions_text": str(entry.get("inclusions_text") or "")[:1600],
            }
        )
    return output[-3:]


def _grounded_benefits(
    presentations: Sequence[Mapping[str, Any]],
    *,
    promo_brand_result: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    current_promo_brands = {
        str(item or "").strip().upper() for item in promo_brand_result.get("brands") or [] if str(item or "").strip()
    }
    promo_ok = str(promo_brand_result.get("status") or "") == "ok"
    benefits: List[Dict[str, Any]] = []
    for presentation in presentations:
        presentation_ref = str(presentation.get("presentation_ref") or "")
        for card in presentation.get("cards") or []:
            if not isinstance(card, Mapping):
                continue
            brand = str(card.get("brand") or "").strip()
            card_ref = str(card.get("card_ref") or card.get("item_ref") or "")
            evidence_ref = f"{presentation_ref}:{card_ref}".strip(":")
            promo_text = str(card.get("promo_savings_line") or card.get("promo_label") or "")
            if promo_ok and brand.upper() in current_promo_brands and _is_buy3get1(promo_text):
                benefits.append(
                    _benefit(
                        kind="buy3get1",
                        brand=brand,
                        description=f"{brand} Buy 3 Get 1 FREE",
                        customer_text=f"May Buy 3 Get 1 FREE din po ang {brand} option.",
                        evidence_ref=evidence_ref,
                    )
                )
            installment = str(card.get("installment_text") or "").strip()
            if installment:
                benefits.append(
                    _benefit(
                        kind="installment",
                        brand=brand,
                        description=f"{brand} {installment}",
                        customer_text=f"Available din po sa {brand} ang {installment}.",
                        evidence_ref=evidence_ref,
                    )
                )
            tpp = str(card.get("tire_protection_plan") or "").strip()
            if tpp:
                benefits.append(
                    _benefit(
                        kind="tire_protection_plan",
                        brand=brand,
                        description=f"{brand} {tpp}",
                        customer_text=f"Kasama rin po sa {brand} ang {tpp}.",
                        evidence_ref=evidence_ref,
                    )
                )
            warranty = str(card.get("warranty") or "").strip()
            if warranty:
                benefits.append(
                    _benefit(
                        kind="warranty",
                        brand=brand,
                        description=f"{brand} manufacturer warranty: {warranty}",
                        customer_text=f"May {warranty} manufacturer warranty din po ang {brand}.",
                        evidence_ref=evidence_ref,
                    )
                )
        inclusions_text = str(presentation.get("inclusions_text") or "")
        if "install with our authorized installation partners" in inclusions_text.casefold():
            benefits.append(
                _benefit(
                    kind="installation_inclusions",
                    brand="",
                    description=(
                        "Authorized Installation Partner inclusions: FREE installation, mounting and balancing, "
                        "weights, and tire valves"
                    ),
                    customer_text=(
                        "Kasama rin po kapag nag-install through an authorized Installation Partner ang FREE "
                        "installation, mounting and balancing, weights, at tire valves."
                    ),
                    evidence_ref=str(presentation.get("presentation_ref") or ""),
                )
            )
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in benefits:
        ref = str(item.get("benefit_ref") or "")
        if not ref or ref in seen:
            continue
        seen.add(ref)
        deduped.append(item)
    return deduped[:16]


def _benefit(*, kind: str, brand: str, description: str, customer_text: str, evidence_ref: str) -> Dict[str, Any]:
    basis = {"kind": kind, "brand": brand, "evidence_ref": evidence_ref, "description": description}
    return {
        "benefit_ref": "benefit_" + _short_hash(basis, length=18),
        "kind": kind,
        "brand": brand,
        "description": description,
        "customer_text": customer_text,
        "evidence_ref": evidence_ref,
    }


def _assemble_message(visible_text: str, benefits: Sequence[str], *, max_chars: int) -> str:
    """Compose model-owned prose with separately grounded exact benefit lines."""

    parts = [visible_text, *[str(item).strip() for item in benefits if str(item).strip()]]
    message = "\n\n".join(parts)
    return message if len(message) <= max_chars else ""


def _compact_product_card(card: Mapping[str, Any]) -> Dict[str, Any]:
    output = {}
    for key in (
        "card_ref",
        "item_ref",
        "product_id",
        "brand",
        "sku_model",
        "tire_size",
        "promo_savings_line",
        "promo_label",
        "installment_text",
        "warranty",
        "tire_protection_plan",
    ):
        value = card.get(key)
        if value not in (None, "", [], {}):
            output[key] = value
    return output


def _compact_message(message: Mapping[str, Any]) -> Dict[str, Any]:
    content = _redact_contact_numbers(str(message.get("content") or message.get("text") or "")).strip()
    if not content:
        return {}
    role = str(message.get("role") or "").strip().lower().replace("-", "_").replace(" ", "_")
    role = {
        "customer": "user",
        "subscriber": "user",
        "client": "user",
        "chatbot": "assistant",
        "bot": "assistant",
        "agent": "human_agent",
        "human": "human_agent",
        "staff": "human_agent",
    }.get(role, role)
    output = {
        "role": role,
        "content": content[:1200],
        "datetime": str(message.get("datetime") or message.get("ts") or "").strip(),
    }
    for key in ("message_id", "sender", "source", "message_kind"):
        value = str(message.get(key) or "").strip()
        if value:
            output[key] = value
    return output


def _conversation_anchor(message: Mapping[str, Any]) -> tuple[str, str]:
    message_id = str(message.get("message_id") or "").strip()
    if message_id:
        return message_id, "manychat_message_id"
    basis = {
        "datetime": str(message.get("datetime") or ""),
        "content": " ".join(str(message.get("content") or "").split()),
    }
    return "synthetic_" + _short_hash(basis, length=24), "synthetic_message_digest"


def _followup_state(v7_state: Mapping[str, Any]) -> Dict[str, Any]:
    state = v7_state.get("followup") if isinstance(v7_state, Mapping) else {}
    return dict(state) if isinstance(state, Mapping) else {}


def _attempts_for_anchor(followup_state: Mapping[str, Any], anchor_id: str) -> List[Dict[str, Any]]:
    return [
        dict(item)
        for item in followup_state.get("attempts") or []
        if isinstance(item, Mapping) and str(item.get("conversation_anchor_id") or "") == anchor_id
    ]


def _reconcile_unknown_attempts(
    attempts: Sequence[Mapping[str, Any]],
    messages: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    assistant_hashes = {
        _short_hash({"message": str(message.get("content") or "")}, length=24)
        for message in messages or []
        if str(message.get("role") or "") == "assistant" and str(message.get("content") or "").strip()
    }
    output: List[Dict[str, Any]] = []
    for raw_attempt in attempts or []:
        attempt = dict(raw_attempt)
        attempt.pop("reconciliation_pending_persist", None)
        status = str(attempt.get("status") or "")
        message_seen = bool(str(attempt.get("message_hash") or "") in assistant_hashes)
        if status in ACTIVE_ATTEMPT_STATUSES and message_seen:
            attempt["status"] = "sent"
            attempt["reconciled_from_transcript"] = True
            attempt["reconciliation_pending_persist"] = True
            attempt["delivery_result"] = {
                "status": "success",
                "reason": "delivery_reconciled_from_transcript_hash",
            }
        elif status == "sending":
            attempt["status"] = "delivery_unknown"
            attempt["reclassified_from_interrupted_sending"] = True
            attempt["reconciliation_pending_persist"] = True
            attempt["delivery_result"] = {
                "status": "delivery_unknown",
                "reason": "interrupted_sending_attempt_not_seen_in_transcript",
            }
        output.append(attempt)
    return output


def _sent_focus_fields(followup_state: Mapping[str, Any], attempts: Sequence[Mapping[str, Any]]) -> List[str]:
    values = [
        str(item.get("focus_field") or "")
        for item in attempts
        if str(item.get("status") or "") == "sent" and str(item.get("focus_field") or "")
    ]
    if not values and not followup_state.get("attempts"):
        values.extend(str(item) for item in followup_state.get("sent_focus_fields") or [] if str(item).strip())
    return _unique(values)


def _selected_product_context(v7_state: Mapping[str, Any]) -> Dict[str, Any]:
    value = v7_state.get("latest_selected_product_context") if isinstance(v7_state, Mapping) else {}
    return dict(value) if isinstance(value, Mapping) else {}


def _selected_product_matches_presentations(
    selected_product: Mapping[str, Any],
    presentations: Sequence[Mapping[str, Any]],
) -> bool:
    selected_refs = {
        str(selected_product.get(key) or "").strip()
        for key in (
            "product_presentation_ref",
            "presentation_ref",
            "product_observation_ref",
            "observation_ref",
            "product_card_ref",
            "card_ref",
        )
        if str(selected_product.get(key) or "").strip()
    }
    if not selected_refs:
        return False
    delivered_refs = set()
    for presentation in presentations or []:
        delivered_refs.update(
            str(presentation.get(key) or "").strip()
            for key in ("presentation_ref", "observation_ref")
            if str(presentation.get(key) or "").strip()
        )
        for card in presentation.get("cards") or []:
            if not isinstance(card, Mapping):
                continue
            delivered_refs.update(
                str(card.get(key) or "").strip()
                for key in ("card_ref", "item_ref")
                if str(card.get(key) or "").strip()
            )
    return bool(selected_refs.intersection(delivered_refs))


def _selected_service_context(v7_state: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(v7_state, Mapping):
        return {}
    for key in ("latest_service_selection", "latest_service_observation", "selected_installation_context"):
        value = v7_state.get(key)
        if isinstance(value, Mapping) and value:
            return dict(value)
    return {}


def _typed_context_has_field(context: Mapping[str, Any], field: str) -> bool:
    aliases = {
        "installation_partner": ("installation_partner", "partner", "partner_id", "installation_partner_id"),
        "schedule": ("schedule", "scheduled_at", "appointment_at", "preferred_date"),
        "payment_option": ("payment_option", "payment_method", "payment_type"),
    }
    return any(str(context.get(key) or "").strip() for key in aliases.get(field, (field,)))


def _completion_context(
    v7_state: Mapping[str, Any],
    messages: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Return active-segment completion evidence from a validated submitted order."""

    submitted = v7_state.get("latest_submitted_order_context") if isinstance(v7_state, Mapping) else {}
    if not isinstance(submitted, Mapping) or not str(submitted.get("order_id") or "").strip():
        return {"is_complete": False, "reason": ""}
    submitted_at = _parse_datetime(submitted.get("submitted_at"))
    first_message_at = None
    for message in messages:
        message_at = _parse_datetime(message.get("datetime"))
        if message_at:
            first_message_at = message_at
            break
    if submitted_at and first_message_at and submitted_at < first_message_at:
        return {
            "is_complete": False,
            "reason": "submitted_order_predates_active_segment",
        }
    return {
        "is_complete": True,
        "reason": "conversation_already_converted",
        "evidence_ref": str(submitted.get("order_payload_ref") or "submitted_order"),
    }


def _profile_lead_values(profile_fields: Mapping[str, Any]) -> Dict[str, Any]:
    aliases = {
        "tire_size": "tire_size",
        "tiresize": "tire_size",
        "location": "location",
        "city": "location",
        "barangay": "location",
        "tire_brand": "tire_brand",
        "brand": "tire_brand",
        "contact_number": "contact_number",
        "contact": "contact_number",
        "phone": "contact_number",
        "mobile": "contact_number",
        "mobile_number": "contact_number",
    }
    output: Dict[str, Any] = {}
    flattened = dict(profile_fields or {})
    custom = profile_fields.get("custom_fields") if isinstance(profile_fields, Mapping) else None
    if isinstance(custom, Mapping):
        flattened.update(custom)
    elif isinstance(custom, Sequence) and not isinstance(custom, (str, bytes)):
        for item in custom:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name") or item.get("field_name") or "").strip()
            value = item.get("value")
            if name and value not in (None, "", [], {}):
                flattened[name] = value
    for raw_key, value in flattened.items():
        normalized_key = re.sub(r"[^a-z0-9]+", "_", str(raw_key or "").casefold()).strip("_")
        field = aliases.get(normalized_key)
        if field and field not in output and value not in (None, "", [], {}):
            output[field] = value
    return output


def _tag_names(profile_fields: Mapping[str, Any]) -> List[str]:
    tags = profile_fields.get("tags") if isinstance(profile_fields, Mapping) else []
    output = []
    for item in tags or []:
        if isinstance(item, Mapping):
            value = item.get("name")
        else:
            value = item
        text = str(value or "").strip()
        if text:
            output.append(text)
    return _unique(output)


def _human_agent_after_latest_customer(messages: Sequence[Mapping[str, Any]]) -> bool:
    latest_customer_index = -1
    for index, message in enumerate(messages or []):
        if str(message.get("role") or "") == "user":
            latest_customer_index = index
    if latest_customer_index < 0:
        return False
    return any(
        str(message.get("role") or "") == "human_agent"
        for message in list(messages or [])[latest_customer_index + 1 :]
    )


def _assigned_agent_is_human(value: str) -> bool:
    normalized = " ".join(str(value or "").casefold().split())
    if normalized in {"", "none", "unassigned", "unknown"}:
        return False
    bot_names = {
        item.strip().casefold()
        for item in os.getenv("RUNTIME_V7_FOLLOWUP_BOT_AGENT_NAMES", "Taira,Chatbot").split(",")
        if item.strip()
    }
    return normalized not in bot_names


def _typed_domain_assessment(v7_state: Mapping[str, Any]) -> Dict[str, str]:
    """Read only an evidenced typed domain assessment; raw prose is non-authoritative."""

    if not isinstance(v7_state, Mapping):
        return {"status": "unknown", "evidence_ref": ""}
    candidates = (
        v7_state.get("domain_assessment"),
        v7_state.get("latest_domain_assessment"),
    )
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        status = str(candidate.get("status") or candidate.get("domain_status") or "").strip()
        evidence_ref = str(candidate.get("evidence_ref") or candidate.get("observation_ref") or "").strip()
        if status in {"supported", "unsupported_or_unresolved"} and evidence_ref:
            return {"status": status, "evidence_ref": evidence_ref}
    return {"status": "unknown", "evidence_ref": ""}


def _presented_brands(presentations: Sequence[Mapping[str, Any]]) -> List[str]:
    values = []
    for presentation in presentations:
        for card in presentation.get("cards") or []:
            if isinstance(card, Mapping) and str(card.get("brand") or "").strip():
                values.append(str(card.get("brand") or "").strip())
    return _unique(values)


def _brand_preferences(value: Any) -> Set[str]:
    normalized = str(value or "").strip().upper()
    if not normalized:
        return set()
    return {
        item.strip()
        for item in re.split(r"\s*(?:,|/|\bOR\b|\bAND\b)\s*", normalized)
        if item.strip()
    }


def _normalize_cadence(value: Any) -> str:
    cadence = str(value or "first").strip().lower()
    return cadence if cadence in {"first", "second", "nurture"} else "first"


def _within_window(age: float, min_env: str, min_default: float, max_env: str, max_default: float) -> bool:
    minimum = float(os.getenv(min_env, str(min_default)) or min_default)
    maximum = float(os.getenv(max_env, str(max_default)) or max_default)
    return minimum <= age <= maximum


def _attempt_in_retry_cooldown(attempt: Mapping[str, Any], request_time: Any) -> bool:
    attempted_at = _parse_datetime(attempt.get("updated_at") or attempt.get("created_at"))
    now = _parse_datetime(request_time)
    if not attempted_at or not now:
        return True
    cooldown = float(os.getenv("RUNTIME_V7_FOLLOWUP_RETRY_COOLDOWN_MINUTES", "30") or "30")
    return now - attempted_at < timedelta(minutes=max(1.0, cooldown))


def _attempt_reason(attempt: Mapping[str, Any]) -> str:
    reason = str(attempt.get("reason") or "").strip().lower()
    if reason:
        return reason
    delivery = attempt.get("delivery_result") if isinstance(attempt.get("delivery_result"), Mapping) else {}
    return str(delivery.get("reason") or "").strip().lower()


def is_retryable_evaluation_reason(reason: Any) -> bool:
    normalized = str(reason or "").strip().lower()
    return (
        normalized in RETRYABLE_EVALUATION_REASONS
        or (
            normalized.startswith("outside_")
            and normalized.endswith("_followup_window")
        )
    )


def _age_minutes(current: Any, previous: Any) -> Optional[float]:
    current_dt = _parse_datetime(current)
    previous_dt = _parse_datetime(previous)
    if not current_dt or not previous_dt:
        return None
    return max(0.0, (current_dt - previous_dt).total_seconds() / 60.0)


def _parse_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(MANILA_TZ).replace(tzinfo=None)
        return parsed
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def _loads_json_object(value: str) -> Dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        payload = json.loads(text)
        return dict(payload) if isinstance(payload, Mapping) else {}
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(0))
            return dict(payload) if isinstance(payload, Mapping) else {}
        except Exception:
            return {}


def _clean_visible_text(value: Any) -> str:
    """Apply only whitespace and URL safety sanitation to model-visible prose."""

    text = " ".join(str(value or "").replace("\n", " ").split())
    text = re.sub(r"https?://\S+", "", text).strip()
    return text.strip()


def _fact_value(value: Any) -> str:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _format_fact_values(values: Mapping[str, Any]) -> str:
    if not values:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in values.items())


def _format_list(values: Sequence[Any]) -> str:
    cleaned = [str(item) for item in values if str(item).strip()]
    return ", ".join(cleaned) if cleaned else "none"


def _is_buy3get1(value: str) -> bool:
    return bool(re.search(r"buy\s*3\s*(?:get|take)\s*1(?:\s*free)?", str(value or ""), flags=re.IGNORECASE))


def _compact_delivery_result(value: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: value.get(key)
        for key in ("status", "status_code", "reason", "error", "error_type", "message", "delivery_mode", "route")
        if value.get(key) not in (None, "", [], {})
    }


def _short_hash(value: Any, *, length: int = 16) -> str:
    stable = json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:length]


def _unique(values: Sequence[str]) -> List[str]:
    output: List[str] = []
    seen: Set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _now_manila() -> str:
    return datetime.now(MANILA_TZ).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


__all__ = [
    "FOLLOWUP_PLAN_SYSTEM_PROMPT",
    "RuntimeV7FollowupPlanModel",
    "build_attempt_record",
    "build_followup_case",
    "build_followup_plan_messages",
    "customer_recovery_gate",
    "followup_stop_reason",
    "load_current_promo_brands",
    "parse_followup_plan",
    "proactive_followup_gate",
    "upsert_attempt",
    "validate_and_render_followup",
]
