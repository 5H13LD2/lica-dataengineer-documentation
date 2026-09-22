"""Passive Runtime V7 tagging signal and rule evaluation.

This module does not apply channel tags directly. It creates auditable tag
actions from normalized state and tool outcomes so a channel adapter can apply
them after the customer response is sent.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from runtime_v7.lead_qualification import INTENT_RULE_VERSION
from runtime_v7.location_quality import usable_lead_location


INFO_SIGNAL_KEYS = {
    "tire_size",
    "tire_brand",
    "preferred_brands",
    "required_brands",
    "location",
    "contact_number",
}
QUALIFICATION_SIGNAL_KEYS = (
    "tire_size",
    "tire_brand",
    "preferred_brands",
    "required_brands",
    "location",
    "contact_number",
)
QUALIFICATION_REFERENCE_KEYS = {
    "evidence_ref",
    "evidence_refs",
    "source_evidence",
    "observation_ref",
    "presentation_ref",
    "surface_ref",
    "card_ref",
    "choice_ref",
    "promo_ref",
    "product_ref",
    "item_ref",
    "order_payload_ref",
    "payment_request_ref",
}
PAYMENT_SIGNAL_KEYS = {
    "chosen_schedule_slot",
    "reservation_payment_method",
    "balance_payment_method",
    "payment_option",
    "payment_method",
}
ORDER_BOOKING_TOOL_NAMES = {
    "finalize_order_and_payment",
    "submit_order",
    "create_order",
    "book_order",
    "confirm_order_booking",
}
PAYMENT_PROOF_TOOL_NAMES = {
    "match_payment_proof",
}
WEBSITE_INQUIRY_GULONG_SURFACES = {
    "product_card",
    "product_page",
    "cart",
    "checkout",
    "order_page",
    "order_email",
    "payment_page",
}
GULONG_WEBSITE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_@.-])(?:https?://)?(?:www\.)?gulong\.ph(?::\d+)?(?:/|\b)",
    re.IGNORECASE,
)
WEBSITE_INQUIRY_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\b(?:nakita|nahanap|chineck|pinakita)\b.{0,48}\b(?:website|site|page|link)\b",
        r"\b(?:sabi|nakalagay|listed|posted)\b.{0,48}\b(?:website|site|page)\b",
        r"\b(?:sa|from|on)\s+(?:website|site)\s+(?:nyo|niyo|ninyo|natin|gulong)\b",
        r"\b(?:website|site)\s+(?:nyo|niyo|ninyo|ng gulong|gulong)\b",
        r"\bproduct\s+page\b",
        r"\blink\s+(?:sa|from|ng)\s+(?:site|website|gulong)\b",
        r"\bgulong\s+(?:website|site|page|link)\b",
        r"\b(?:nag-?order|umorder|mag-?order|order|checkout|add(?:ed)?\s+to\s+cart)\b.{0,64}\b(?:website|site|gulong[.]ph)\b",
        r"\b(?:website|site|gulong[.]ph)\b.{0,64}\b(?:order|checkout|cart)\b",
    ]
]


def evaluate_runtime_v7_tagging(
    *,
    current_user_message: str,
    assistant_response: str = "",
    background_signals: Optional[Sequence[Mapping[str, Any]]] = None,
    lead_qualification: Optional[Mapping[str, Any]] = None,
    tool_results: Optional[Sequence[Mapping[str, Any]]] = None,
    retry_events: Optional[Sequence[Mapping[str, Any]]] = None,
    selected_product_context: Optional[Mapping[str, Any]] = None,
    interaction_context: Optional[Mapping[str, Any]] = None,
    turn_count: int = 1,
    existing_tags: Optional[Sequence[str]] = None,
    error_reason: str = "",
) -> Dict[str, Any]:
    """Return passive post-turn tag actions and their evidence."""

    synthetic = build_runtime_v7_tagging_signals(
        current_user_message=current_user_message,
        assistant_response=assistant_response,
        background_signals=background_signals or [],
        lead_qualification=lead_qualification or {},
        tool_results=tool_results or [],
        retry_events=retry_events or [],
        selected_product_context=selected_product_context or {},
        turn_count=turn_count,
        error_reason=error_reason,
    )
    existing = {str(tag or "").strip() for tag in existing_tags or [] if str(tag or "").strip()}
    if "Website Inquiry" in existing:
        synthetic["website_inquiry"] = True
        synthetic["website_evidence"] = _unique(
            [*(synthetic.get("website_evidence") or []), "existing_website_inquiry_tag"]
        )
    actions = _tag_actions_from_signals(synthetic)
    tags_to_add = [action for action in actions if action.get("tag") not in existing]
    skipped_existing = [action for action in actions if action.get("tag") in existing]
    result = {
        "synthetic_signals": synthetic,
        "tags_to_add": tags_to_add,
        "tags_skipped_existing": skipped_existing,
        "tags_applied": [],
        "tags_failed": [],
        "apply_status": "not_applied",
    }
    if synthetic.get("moderate_intent"):
        # Qualification is an analytical fact. It must survive channel-routing
        # policy such as Website Inquiry, which deliberately suppresses the
        # Moderate Intent routing tag.
        result["analytical_qualifications"] = [
            _analytical_moderate_qualification(
                synthetic=synthetic,
                background_signals=background_signals or [],
                lead_qualification=lead_qualification or {},
                tool_results=tool_results or [],
                selected_product_context=selected_product_context or {},
                interaction_context=interaction_context or {},
            )
        ]
    return _refresh_analytical_qualification_outcomes(result)


def build_runtime_v7_tagging_signals(
    *,
    current_user_message: str,
    assistant_response: str,
    background_signals: Sequence[Mapping[str, Any]],
    lead_qualification: Mapping[str, Any],
    tool_results: Sequence[Mapping[str, Any]],
    retry_events: Sequence[Mapping[str, Any]],
    selected_product_context: Mapping[str, Any],
    turn_count: int,
    error_reason: str = "",
) -> Dict[str, Any]:
    """Project trusted state and tool outcomes into passive tag signals."""

    signal_values = _signal_values(background_signals)
    lead_stage = str(lead_qualification.get("lead_stage") or lead_qualification.get("status") or "incomplete")
    moderate_intent = bool(lead_qualification.get("moderate_intent") or lead_stage == "complete")
    lead_present = lead_qualification.get("present") if isinstance(lead_qualification.get("present"), Mapping) else {}
    quote_provided = _quote_provided(tool_results)
    selected_product_ref = _selected_product_ref_present(
        tool_results,
        signal_values,
        selected_product_context,
    )
    signal_location = usable_lead_location(signal_values.get("location"))
    lead_location = usable_lead_location(lead_present.get("location"))
    has_location_or_partner = bool(
        signal_location
        or lead_location
        or signal_values.get("selected_installation_partner")
        or _has_service_partner_tool_result(tool_results)
    )
    has_schedule_or_payment = bool(PAYMENT_SIGNAL_KEYS.intersection(signal_values) or _has_slot_tool_result(tool_results))
    chatbot_error = bool(error_reason or _has_runtime_error(retry_events, tool_results))
    order_booked = _has_successful_order_booking(tool_results)
    payment_proof_received = _has_payment_proof_received(tool_results)
    human_handoff_requested = _has_human_handoff_request(tool_results)
    website_evidence = _website_inquiry_evidence(current_user_message, background_signals)
    text_for_irate = " ".join(part for part in [current_user_message, assistant_response] if part)
    return {
        "lead_stage": lead_stage,
        "moderate_intent": moderate_intent,
        "has_tire_size": bool(signal_values.get("tire_size") or lead_present.get("tire_size")),
        "has_tire_brand": bool(
            signal_values.get("tire_brand")
            or signal_values.get("preferred_brands")
            or signal_values.get("required_brands")
            or lead_present.get("tire_brand")
            or selected_product_ref
        ),
        "has_location": bool(signal_location or lead_location),
        "has_contact_number": bool(signal_values.get("contact_number") or lead_present.get("contact_number")),
        "quote_provided": quote_provided,
        "selected_product_ref": selected_product_ref,
        "has_location_or_partner": has_location_or_partner,
        "has_schedule_or_payment": has_schedule_or_payment,
        "turn_count": max(1, int(turn_count or 1)),
        "irate_signal": _has_irate_signal(text_for_irate),
        "chatbot_error": chatbot_error,
        "order_booked": order_booked,
        "payment_proof_received": payment_proof_received,
        "human_handoff_requested": human_handoff_requested,
        "website_inquiry": bool(website_evidence),
        "website_evidence": website_evidence,
        "error_reason": str(error_reason or ""),
        "tool_names": [str(result.get("name") or "") for result in tool_results or [] if isinstance(result, Mapping)],
    }


def mark_runtime_v7_tags_applied(
    tagging_result: Mapping[str, Any],
    *,
    applied_tags: Optional[Sequence[str]] = None,
    failed_tags: Optional[Sequence[Mapping[str, Any]]] = None,
    apply_status: str = "",
) -> Dict[str, Any]:
    """Return a tagging result updated with channel application outcome."""

    output = dict(tagging_result or {})
    output["tags_applied"] = [str(tag) for tag in applied_tags or [] if str(tag).strip()]
    output["tags_failed"] = [dict(item) for item in failed_tags or [] if isinstance(item, Mapping)]
    if apply_status:
        output["apply_status"] = apply_status
    elif output["tags_failed"] and output["tags_applied"]:
        output["apply_status"] = "partial"
    elif output["tags_failed"]:
        output["apply_status"] = "failed"
    elif output["tags_applied"]:
        output["apply_status"] = "success"
    else:
        output["apply_status"] = output.get("apply_status") or "not_applied"
    return _refresh_analytical_qualification_outcomes(output)


def enrich_runtime_v7_analytical_qualifications(
    tagging_result: Mapping[str, Any],
    *,
    event_id: str = "",
    channel_event_id: str = "",
    message_id: str = "",
    idempotency_key: str = "",
    request_id: str = "",
    user_id: str = "",
    channel_user_id: str = "",
    session_id: str = "",
    trace_id: str = "",
    turn_id: str = "",
    channel: str = "",
    occurred_at: str = "",
    service_environment: str = "",
    runtime_host: str = "",
    release_version: str = "",
    git_sha: str = "",
    interaction_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Add durable trace identity to synthetic qualification records.

    This is intentionally called at the API trace boundary, where request,
    environment, and customer/session identifiers are available. The resulting
    ``qualification_event_id`` is stable across an idempotent replay so
    downstream SQL can deduplicate append-only trace rows without treating a
    routing tag as the definition of Moderate qualification.
    """

    output = _refresh_analytical_qualification_outcomes(deepcopy(dict(tagging_result or {})))
    qualifications = output.get("analytical_qualifications")
    if not isinstance(qualifications, list):
        return output

    resolved_event_id = str(
        event_id
        or channel_event_id
        or message_id
        or idempotency_key
        or turn_id
        or trace_id
        or request_id
        or ""
    ).strip()
    resolved_idempotency_key = str(idempotency_key or resolved_event_id).strip()
    event_identity = {
        "event_id": resolved_event_id,
        "channel_event_id": str(channel_event_id or "").strip(),
        "message_id": str(message_id or "").strip(),
        "idempotency_key": resolved_idempotency_key,
        "request_id": str(request_id or "").strip(),
    }
    context = {
        "user_id": str(user_id or "").strip(),
        "channel_user_id": str(channel_user_id or user_id or "").strip(),
        "session_id": str(session_id or "").strip(),
        "trace_id": str(trace_id or "").strip(),
        "turn_id": str(turn_id or "").strip(),
        "channel": str(channel or "").strip(),
        "runtime_version": "v7",
    }
    environment = {
        "service_environment": str(service_environment or "").strip(),
        "runtime_host": str(runtime_host or "").strip(),
        "release_version": str(release_version or "").strip(),
        "git_sha": str(git_sha or "").strip(),
    }
    correlation_context = _compact_interaction_context(interaction_context or {})
    for record in qualifications:
        if not isinstance(record, dict):
            continue
        level = str(record.get("qualification_level") or "moderate").strip().lower()
        stable_basis = {
            "channel": context["channel"],
            "user_id": context["user_id"],
            "event_id": event_identity["event_id"],
            "idempotency_key": event_identity["idempotency_key"],
            "qualification_level": level,
        }
        record["qualification_event_id"] = "aq_v1_" + _short_hash(stable_basis)
        record["event_identity"] = event_identity
        record["environment"] = environment
        record["context"] = context
        record["occurred_at"] = str(
            record.get("occurred_at") or occurred_at or ""
        ).strip()
        if correlation_context:
            record["interaction_context"] = {
                **dict(record.get("interaction_context") or {}),
                **correlation_context,
            }
    return output


def _analytical_moderate_qualification(
    *,
    synthetic: Mapping[str, Any],
    background_signals: Sequence[Mapping[str, Any]],
    lead_qualification: Mapping[str, Any],
    tool_results: Sequence[Mapping[str, Any]],
    selected_product_context: Mapping[str, Any],
    interaction_context: Mapping[str, Any],
) -> Dict[str, Any]:
    """Build the routing-independent Moderate qualification trace payload."""

    decision_mode = (
        str(lead_qualification.get("decision_mode") or "deterministic").strip()
        or "deterministic"
    )
    rule_version = (
        str(lead_qualification.get("rule_version") or INTENT_RULE_VERSION).strip()
        or INTENT_RULE_VERSION
    )
    return {
        "schema_version": 1,
        "kind": "analytical_qualification",
        "qualification_level": "moderate",
        "countable": True,
        "decision_mode": decision_mode,
        "rule_version": rule_version,
        "occurred_at": "",
        "source_signals": _qualification_source_signals(
            synthetic=synthetic,
            background_signals=background_signals,
            lead_qualification=lead_qualification,
        ),
        "evidence_refs": _qualification_evidence_refs(
            background_signals,
            lead_qualification,
            tool_results,
            selected_product_context,
            interaction_context,
        ),
        "interaction_context": _compact_interaction_context(interaction_context),
    }


def _qualification_source_signals(
    *,
    synthetic: Mapping[str, Any],
    background_signals: Sequence[Mapping[str, Any]],
    lead_qualification: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Return redacted provenance for the signals that made Moderate true."""

    output: List[Dict[str, Any]] = [
        {
            "key": "moderate_intent",
            "source": "lead_qualification",
            "present": True,
        }
    ]
    lead_stage = str(synthetic.get("lead_stage") or "").strip()
    if lead_stage:
        output.append(
            {
                "key": "lead_stage",
                "source": "lead_qualification",
                "value": lead_stage,
            }
        )
    supported_keys = {
        "tire_size": bool(synthetic.get("has_tire_size")),
        "tire_brand": bool(synthetic.get("has_tire_brand")),
        "location": bool(synthetic.get("has_location")),
        "contact_number": bool(synthetic.get("has_contact_number")),
    }
    seen = {(item["key"], item["source"]) for item in output}
    for signal in background_signals or []:
        if not isinstance(signal, Mapping):
            continue
        source_key = str(signal.get("key") or "").strip()
        canonical_key = (
            "tire_brand"
            if source_key in {"preferred_brands", "required_brands"}
            else source_key
        )
        if (
            source_key not in QUALIFICATION_SIGNAL_KEYS
            or not supported_keys.get(canonical_key)
            or signal.get("value") in (None, "", [], {})
        ):
            continue
        source = str(signal.get("source") or "background_signal").strip()
        identity = (canonical_key, source)
        if identity in seen:
            continue
        output.append(
            {
                "key": canonical_key,
                "source_key": source_key,
                "source": source,
                "present": True,
            }
        )
        seen.add(identity)
    present = (
        lead_qualification.get("present")
        if isinstance(lead_qualification.get("present"), Mapping)
        else {}
    )
    for canonical_key, is_present in supported_keys.items():
        if not is_present or canonical_key in {item["key"] for item in output}:
            continue
        if present.get(canonical_key) in (None, "", [], {}):
            continue
        output.append(
            {
                "key": canonical_key,
                "source": "lead_qualification.present",
                "present": True,
            }
        )
    return output


def _qualification_evidence_refs(*sources: Any) -> List[str]:
    """Collect bounded stable references without copying customer values."""

    refs: List[str] = []

    def visit(value: Any, *, depth: int = 0) -> None:
        """Walk only known reference containers with bounded nesting."""

        if depth > 3:
            return
        if isinstance(value, Mapping):
            for key, nested in value.items():
                normalized_key = str(key or "").strip()
                if normalized_key in QUALIFICATION_REFERENCE_KEYS:
                    if isinstance(nested, Sequence) and not isinstance(
                        nested, (str, bytes)
                    ):
                        for item in nested:
                            append_ref(item)
                    else:
                        append_ref(nested)
                elif normalized_key in {"metadata", "result", "full_result"}:
                    visit(nested, depth=depth + 1)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                visit(item, depth=depth + 1)

    def append_ref(value: Any) -> None:
        """Add one compact unique reference without retaining raw evidence."""

        item = str(value or "").strip()
        if item and item not in refs:
            refs.append(item[:240])

    for source in sources:
        visit(source)
    return refs[:32]


def _compact_interaction_context(context: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep only correlation identifiers from tracked actions or surfaces."""

    if not isinstance(context, Mapping):
        return {}
    keys = (
        "surface_type",
        "surface_ref",
        "presentation_ref",
        "presentation_ref_source",
        "card_ref",
        "card_id",
        "choice_type",
        "choice_ref",
        "action",
        "catalog_version_id",
        "promo_id",
        "promo_ref",
        "source",
        "validation_status",
    )
    output = {
        key: str(context.get(key) or "").strip()[:240]
        for key in keys
        if str(context.get(key) or "").strip()
    }
    for nested_key in ("choice", "promo"):
        nested = context.get(nested_key)
        if not isinstance(nested, Mapping):
            continue
        for key in keys:
            if key in output or not str(nested.get(key) or "").strip():
                continue
            output[key] = str(nested.get(key) or "").strip()[:240]
    return output


def _refresh_analytical_qualification_outcomes(
    tagging_result: Mapping[str, Any],
) -> Dict[str, Any]:
    """Attach routing application outcome without redefining qualification."""

    output = dict(tagging_result or {})
    qualifications = output.get("analytical_qualifications")
    if not isinstance(qualifications, list):
        return output
    signals = (
        output.get("synthetic_signals")
        if isinstance(output.get("synthetic_signals"), Mapping)
        else {}
    )
    pending_tags = {
        str(item.get("tag") or "").strip()
        for item in output.get("tags_to_add") or []
        if isinstance(item, Mapping)
    }
    existing_tags = {
        str(item.get("tag") or "").strip()
        for item in output.get("tags_skipped_existing") or []
        if isinstance(item, Mapping)
    }
    applied_tags = {
        str(item or "").strip()
        for item in output.get("tags_applied") or []
        if str(item or "").strip()
    }
    failed_tags = {
        str(item.get("tag") or "").strip()
        for item in output.get("tags_failed") or []
        if isinstance(item, Mapping)
    }
    website_exclusive = bool(signals.get("website_inquiry"))
    if website_exclusive:
        moderate_outcome = "suppressed_by_website_inquiry"
    elif "Moderate Intent" in applied_tags:
        moderate_outcome = "applied"
    elif "Moderate Intent" in failed_tags:
        moderate_outcome = "failed"
    elif "Moderate Intent" in existing_tags:
        moderate_outcome = "already_present"
    elif "Moderate Intent" in pending_tags:
        moderate_outcome = (
            "application_skipped"
            if output.get("tag_apply_skipped")
            else "pending"
        )
    else:
        moderate_outcome = "not_requested"
    application = {
        "routing_policy": (
            "website_inquiry_exclusive" if website_exclusive else "standard"
        ),
        "moderate_tag": "Moderate Intent",
        "moderate_tag_outcome": moderate_outcome,
        "apply_status": str(output.get("apply_status") or "").strip(),
        "tags_applied": sorted(applied_tags),
        "tags_failed": sorted(failed_tags),
        "tag_apply_skipped": bool(output.get("tag_apply_skipped")),
        "tag_apply_skip_reason": str(
            output.get("tag_apply_skip_reason") or ""
        ).strip(),
    }
    output["analytical_qualifications"] = [
        {
            **dict(record),
            "countable": True,
            "tag_application_outcome": application,
        }
        for record in qualifications
        if isinstance(record, Mapping)
    ]
    return output


def _short_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(value or {}), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _tag_actions_from_signals(signals: Mapping[str, Any]) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    website_inquiry = bool(signals.get("website_inquiry"))
    if website_inquiry:
        actions.append(
            _action(
                "Website Inquiry",
                "website_inquiry",
                "customer_origin_or_product_page_context",
                signals.get("website_evidence") or [],
            )
        )
    else:
        if signals.get("moderate_intent"):
            actions.append(
                _action(
                    "Moderate Intent",
                    "moderate_intent",
                    "lead_stage_complete",
                    ["tire_size + at least 2 of tire_brand/location/contact_number"],
                )
            )
        if _is_high_intent(signals):
            actions.append(
                _action(
                    "High Intent",
                    "high_intent",
                    "quote_or_product_plus_fulfillment_progress",
                    [
                        "quote/product context",
                        "tire size",
                        "brand",
                        "location or partner",
                        "schedule or payment",
                        "turn_count >= 3",
                    ],
                )
            )
    if signals.get("irate_signal"):
        actions.append(_action("Irate", "irate", "explicit_frustration_or_escalation", []))
    if signals.get("chatbot_error"):
        actions.append(_action("Chatbot Error", "chatbot_error", signals.get("error_reason") or "runtime_error", []))
    if signals.get("human_handoff_requested"):
        actions.append(
            _action(
                "Stop Chatbot",
                "human_handoff_requested",
                "model_tool_recorded_explicit_human_handoff",
                ["request_human_handoff:requested"],
            )
        )
    if signals.get("order_booked"):
        actions.append(_action("Order Booked", "order_booked", "trusted_order_booking_tool_success", []))
    if signals.get("payment_proof_received"):
        actions.append(_action("Payment Confirmation", "payment_proof_received", "payment_proof_tool_received", []))
    return actions


def _is_high_intent(signals: Mapping[str, Any]) -> bool:
    return bool(
        (signals.get("quote_provided") or signals.get("selected_product_ref"))
        and signals.get("has_tire_size")
        and signals.get("has_tire_brand")
        and signals.get("has_location_or_partner")
        and signals.get("has_schedule_or_payment")
        and int(signals.get("turn_count") or 0) >= 3
    )


def _action(tag: str, rule: str, reason: str, evidence: Sequence[str]) -> Dict[str, Any]:
    return {
        "tag": tag,
        "rule": rule,
        "reason": reason,
        "evidence": [str(item) for item in evidence or [] if str(item).strip()],
    }


def _signal_values(background_signals: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for signal in background_signals or []:
        if not isinstance(signal, Mapping):
            continue
        key = str(signal.get("key") or "").strip()
        value = signal.get("value")
        if key == "location" and not usable_lead_location(value):
            continue
        if key and value not in (None, "", [], {}):
            values[key] = str(value).strip()
    return values


def _website_inquiry_evidence(
    current_user_message: str,
    background_signals: Sequence[Mapping[str, Any]],
) -> List[str]:
    """Return evidence that the customer likely came from Gulong web context."""

    evidence: List[str] = []
    text = str(current_user_message or "")
    if GULONG_WEBSITE_PATTERN.search(text):
        evidence.append("customer_sent_gulong_url")
    if any(pattern.search(text) for pattern in WEBSITE_INQUIRY_PATTERNS):
        evidence.append("customer_referenced_website_or_site")

    for signal in background_signals or []:
        if not isinstance(signal, Mapping):
            continue
        key = str(signal.get("key") or "").strip()
        value = str(signal.get("value") or "")
        source = str(signal.get("source") or "")
        metadata = signal.get("metadata") if isinstance(signal.get("metadata"), Mapping) else {}
        source_origin = str(metadata.get("source_origin") or "").strip().lower()
        gulong_surface = str(metadata.get("gulong_surface") or "").strip().lower()
        # A branded promo/marketing image can contain a Gulong URL or product
        # text without showing a website, checkout, or order surface. Keep its
        # OCR candidates available for product assistance, but never authorize
        # the Website Inquiry routing tag from that image evidence.
        if gulong_surface == "marketing_asset":
            continue
        if (
            source == "external_evidence"
            and source_origin == "gulong_ph"
            and gulong_surface in WEBSITE_INQUIRY_GULONG_SURFACES
        ):
            evidence.append(
                f"gulong_{gulong_surface}_image"
            )
        # A generic image type or OCR-discovered Gulong URL is product context
        # only. Either may appear on a marketing creative, so image routing
        # requires the explicit Gulong surface classification above.
    return _unique(evidence)


def _unique(values: Sequence[str]) -> List[str]:
    seen = set()
    output: List[str] = []
    for value in values or []:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def _quote_provided(tool_results: Sequence[Mapping[str, Any]]) -> bool:
    for result in tool_results or []:
        name = str(result.get("name") or "")
        compact = result.get("result") if isinstance(result.get("result"), Mapping) else {}
        full = result.get("full_result") if isinstance(result.get("full_result"), Mapping) else {}
        if name == "calculate_order_quote" and str(full.get("status") or compact.get("status") or "").lower() in {"ok", "success"}:
            return True
        if name in {"product_search", "get_product_details"} and (
            full.get("product_cards")
            or full.get("selected_product_cards")
            or compact.get("product_card_headers")
        ):
            return True
    return False


def _selected_product_ref_present(
    tool_results: Sequence[Mapping[str, Any]],
    signal_values: Mapping[str, str],
    selected_product_context: Mapping[str, Any],
) -> bool:
    if signal_values.get("selected_product_ref"):
        return True
    if any(
        selected_product_context.get(key)
        for key in (
            "product_card_ref",
            "product_item_ref",
            "product_id",
            "slug",
        )
    ):
        return True
    for result in tool_results or []:
        if str(result.get("name") or "") in {"resolve_product_reference", "get_product_details", "build_order_summary"}:
            full = result.get("full_result") if isinstance(result.get("full_result"), Mapping) else {}
            if full.get("selected_product_cards") or full.get("resolved_ref") or full.get("order_summary_ref"):
                return True
    return False


def _has_service_partner_tool_result(tool_results: Sequence[Mapping[str, Any]]) -> bool:
    for result in tool_results or []:
        if str(result.get("name") or "") not in {"find_installation_partners", "find_installation_slots"}:
            continue
        full = result.get("full_result") if isinstance(result.get("full_result"), Mapping) else {}
        if full.get("installation_partner_cards") or full.get("service_location_headers"):
            return True
    return False


def _has_slot_tool_result(tool_results: Sequence[Mapping[str, Any]]) -> bool:
    for result in tool_results or []:
        name = str(result.get("name") or "")
        if name == "validate_installation_slot":
            full = result.get("full_result") if isinstance(result.get("full_result"), Mapping) else {}
            compact = result.get("result") if isinstance(result.get("result"), Mapping) else {}
            if bool(full.get("valid") or compact.get("valid")):
                return True
            continue
        if name == "find_installation_slots":
            full = result.get("full_result") if isinstance(result.get("full_result"), Mapping) else {}
            compact = result.get("result") if isinstance(result.get("result"), Mapping) else {}
            status = str(full.get("status") or compact.get("status") or "").strip().lower()
            availability = full.get("availability") if isinstance(full.get("availability"), Mapping) else {}
            compact_availability = compact.get("availability") if isinstance(compact.get("availability"), Mapping) else {}
            slot_groups = full.get("slot_groups") if isinstance(full.get("slot_groups"), list) else []
            slot_count = availability.get("slot_count")
            if slot_count in (None, ""):
                slot_count = compact_availability.get("slot_count")
            if status == "ok" and (slot_groups or _positive_int(slot_count) > 0):
                return True
    return False


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _has_successful_order_booking(tool_results: Sequence[Mapping[str, Any]]) -> bool:
    for result in tool_results or []:
        if str(result.get("name") or "") not in ORDER_BOOKING_TOOL_NAMES:
            continue
        full = result.get("full_result") if isinstance(result.get("full_result"), Mapping) else {}
        compact = result.get("result") if isinstance(result.get("result"), Mapping) else {}
        status = str(full.get("status") or compact.get("status") or "").strip().lower()
        if status in {"ok", "success", "booked", "confirmed"}:
            return True
    return False


def _has_payment_proof_received(tool_results: Sequence[Mapping[str, Any]]) -> bool:
    for result in tool_results or []:
        if str(result.get("name") or "") not in PAYMENT_PROOF_TOOL_NAMES:
            continue
        full = result.get("full_result") if isinstance(result.get("full_result"), Mapping) else {}
        compact = result.get("result") if isinstance(result.get("result"), Mapping) else {}
        status = str(full.get("status") or compact.get("status") or "").strip().lower()
        received = bool(full.get("payment_proof_received") or compact.get("payment_proof_received"))
        if received and status in {"matched_unverified", "needs_verification", "verified_paid", "not_matched"}:
            return True
    return False


def _has_human_handoff_request(
    tool_results: Sequence[Mapping[str, Any]],
) -> bool:
    """Return true only for a successfully recorded typed handoff action."""

    for result in tool_results or []:
        if str(result.get("name") or "") != "request_human_handoff":
            continue
        full = (
            result.get("full_result")
            if isinstance(result.get("full_result"), Mapping)
            else {}
        )
        compact = (
            result.get("result")
            if isinstance(result.get("result"), Mapping)
            else {}
        )
        if str(full.get("status") or compact.get("status") or "") in {
            "requested",
            "already_requested",
        }:
            return True
    return False


def _has_runtime_error(
    retry_events: Sequence[Mapping[str, Any]],
    tool_results: Sequence[Mapping[str, Any]],
) -> bool:
    for event in retry_events or []:
        event_type = str(event.get("type") or "")
        if event_type in {"empty_final_response_fallback", "tool_failure_fallback", "render_invalid_fallback"}:
            return True
    for result in tool_results or []:
        full = result.get("full_result") if isinstance(result.get("full_result"), Mapping) else {}
        compact = result.get("result") if isinstance(result.get("result"), Mapping) else {}
        error_type = str(
            full.get("error_type")
            or compact.get("error_type")
            or ""
        ).strip()
        if error_type == "tool_plan_not_authorized":
            # This is a successful runtime safety decision, not an
            # infrastructure or delivery failure. The rejected plan remains
            # observable through tool-guard telemetry.
            continue
        status = str(full.get("status") or compact.get("status") or "").strip().lower()
        if status in {"error", "failed", "timeout"}:
            return True
        if full.get("error") or error_type or compact.get("error"):
            return True
    return False


def _has_irate_signal(text: str) -> bool:
    lowered = str(text or "").lower()
    phrase_patterns = [
        r"\bbad service\b",
        r"\bpoor service\b",
        r"\bworst service\b",
        r"\bcomplain(?:t)?\b",
        r"\bireport\b",
        r"\breport ko\b",
        r"\bescalate\b",
        r"\bmanager\b",
        r"\bsupervisor\b",
        r"\bang tagal\b",
        r"\bang bagal\b",
        r"\bwalang kwenta\b",
        r"\bbwisit\b",
        r"\bgalit\b",
    ]
    return any(re.search(pattern, lowered) for pattern in phrase_patterns)


__all__ = [
    "build_runtime_v7_tagging_signals",
    "enrich_runtime_v7_analytical_qualifications",
    "evaluate_runtime_v7_tagging",
    "mark_runtime_v7_tags_applied",
]
