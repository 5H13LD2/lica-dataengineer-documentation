"""Typed, model-facing interpretation context for tracked Runtime V7 actions.

The runtime owns only objective interaction facts: delivery validation,
ordering, structural relationships, and the set of legal interpretations.  The
model remains responsible for deciding whether the customer corrected a choice,
wants a comparison, or needs a clarification.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    NotRequired,
    Sequence,
    TypedDict,
)


INTERACTION_PACKET_VERSION = 1
DEFAULT_MAX_EVENTS = 5
DEFAULT_MAX_CHARS = 2500

DISCOVERY_LAYERS = {"promo", "price_category", "product"}
TRANSACTION_LAYERS = {
    "schedule",
    "payment_option",
    "payment_method",
}


class InteractionEventV1(TypedDict):
    """Internal normalized event contract; not an external API schema."""

    event_id: str
    idempotency_key: str
    source: str
    presentation_ref: str
    choice_ref: str
    choice_type: str
    decision_layer: str
    label: str
    occurred_at: str
    received_at: str
    processed_at: str
    validation_status: str
    delivery_status: str
    action: NotRequired[str]
    parent_code: NotRequired[str]
    province_code: NotRequired[str]


class InteractionPacketV1(TypedDict):
    """Bounded objective packet supplied to reasoning and composition."""

    schema_version: int
    batch_ref: str
    events: List[InteractionEventV1]
    runtime_relation: str
    allowed_model_interpretations: List[str]
    requires_model_interpretation: bool
    state_commit_deferred: bool
    event_count: int


def decision_layer_for_event(event: Mapping[str, Any]) -> str:
    """Return the trusted decision layer encoded by a delivered control."""

    choice_type = str(event.get("choice_type") or "").strip().casefold()
    action = str(event.get("action") or "").strip().casefold()
    if choice_type == "price_category":
        return "price_category"
    if choice_type == "product_selection":
        return "product"
    if choice_type == "serviceable_province":
        return "province"
    if choice_type == "serviceable_city":
        return "city"
    if choice_type == "schedule_selection":
        return "schedule"
    if choice_type == "payment_option_selection":
        return "payment_option"
    if choice_type == "payment_method_selection":
        return "payment_method"
    if action in {"promo_details", "about_brand"}:
        return "promo_information"
    if action:
        return "promo"
    return ""


def normalize_interaction_event(
    event: Mapping[str, Any],
    *,
    source: str,
    received_at: str = "",
    processed_at: str = "",
) -> Dict[str, Any]:
    """Normalize one promo or choice action without inferring customer meaning."""

    event_id = str(
        event.get("event_id")
        or event.get("message_id")
        or event.get("idempotency_key")
        or ""
    ).strip()
    occurred_at = _normalize_timestamp(
        event.get("click_timestamp")
        or event.get("occurred_at")
        or event.get("attempted_at")
        or ""
    )
    choice_ref = str(
        event.get("choice_ref")
        or event.get("card_ref")
        or event.get("choice_code")
        or event.get("promo_ref")
        or event.get("promo_id")
        or event.get("action")
        or ""
    ).strip()
    normalized = {
        "event_id": event_id,
        "idempotency_key": str(event.get("idempotency_key") or "").strip(),
        "source": str(source or "").strip(),
        "presentation_ref": str(
            event.get("presentation_ref")
            or event.get("catalog_version_id")
            or ""
        ).strip(),
        "choice_ref": choice_ref,
        "choice_type": str(
            event.get("choice_type")
            or ("promo_action" if event.get("action") else "")
        ).strip(),
        "action": str(event.get("action") or "").strip(),
        "label": str(
            event.get("label")
            or event.get("selected_brand")
            or event.get("value")
            or event.get("action")
            or ""
        ).strip(),
        "occurred_at": occurred_at,
        "received_at": _normalize_timestamp(
            received_at
            or event.get("received_at")
            or event.get("attempted_at")
            or ""
        ),
        "processed_at": _normalize_timestamp(
            processed_at or event.get("processed_at") or ""
        ),
        "validation_status": str(
            event.get("validation_status") or event.get("status") or ""
        ).strip(),
        "delivery_status": str(event.get("delivery_status") or "").strip(),
        "parent_code": str(event.get("parent_code") or "").strip(),
        "province_code": str(event.get("province_code") or "").strip(),
    }
    normalized["decision_layer"] = decision_layer_for_event(normalized)
    compact = {
        key: value
        for key, value in normalized.items()
        if value not in ("", None)
    }
    for key in (
        "event_id",
        "idempotency_key",
        "presentation_ref",
        "choice_ref",
        "parent_code",
        "province_code",
    ):
        if key in compact:
            compact[key] = str(compact[key])[:180]
    if "label" in compact:
        compact["label"] = str(compact["label"])[:240]
    for key in ("occurred_at", "received_at", "processed_at"):
        if key in compact:
            compact[key] = str(compact[key])[:64]
    return compact


def compile_interaction_packet(
    *,
    choice_history: Sequence[Mapping[str, Any]],
    promo_history: Sequence[Mapping[str, Any]],
    current_event_id: str = "",
    max_events: int = DEFAULT_MAX_EVENTS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> Dict[str, Any]:
    """Compile unresolved validated events into a bounded model-facing packet."""

    events = [
        normalize_interaction_event(item, source="choice_action")
        for item in choice_history or []
        if isinstance(item, Mapping)
    ]
    events.extend(
        normalize_interaction_event(item, source="promo_action")
        for item in promo_history or []
        if isinstance(item, Mapping)
    )
    current_event_id = str(current_event_id or "").strip()
    events = [
        event
        for event in events
        if _event_is_interpretable(event)
        or (
            current_event_id
            and str(event.get("event_id") or "") == current_event_id
        )
    ]
    events = _deduplicate_events(events)
    events.sort(key=_event_sort_key)
    unresolved = _events_since_last_delivered_response(events)
    limit = max(1, min(10, int(max_events or DEFAULT_MAX_EVENTS)))
    unresolved = unresolved[-limit:]
    if not unresolved:
        return {}

    relation = _runtime_relation(unresolved)
    packet = {
        "schema_version": INTERACTION_PACKET_VERSION,
        "batch_ref": _batch_ref(unresolved),
        "events": unresolved,
        "runtime_relation": relation,
        "allowed_model_interpretations": _allowed_interpretations(
            relation,
            unresolved,
        ),
        "requires_model_interpretation": relation
        in {"same_layer_distinct", "cross_layer_sequence"},
        "state_commit_deferred": relation == "same_layer_distinct",
        "event_count": len(unresolved),
    }
    return _bounded_packet(packet, max_chars=max_chars)


def default_interaction_decision(packet: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a safe fallback when the composer omits an interaction decision."""

    events = [
        item for item in packet.get("events") or [] if isinstance(item, Mapping)
    ]
    event_ids = [
        str(item.get("event_id") or "")
        for item in events
        if str(item.get("event_id") or "")
    ]
    relation = str(packet.get("runtime_relation") or "")
    if relation == "same_choice_repeat":
        interpretation = "accept_once"
    elif relation == "hierarchical_sequence":
        interpretation = "hierarchical_advance"
    elif relation == "single_valid_event":
        interpretation = "accept_latest"
    elif relation == "same_layer_distinct":
        # Validated controls are ordered customer actions. Without separate
        # free-text comparison context, the newest choice is a correction of
        # the earlier choice in the same dimension.
        interpretation = "accept_latest"
    else:
        interpretation = "clarify"
    effective = event_ids[-1:] if interpretation in {
        "accept_latest",
        "accept_once",
        "hierarchical_advance",
    } else []
    return {
        "interpretation": interpretation,
        "effective_event_ids": effective,
        "reason_code": "safe_runtime_fallback",
        "needs_clarification": interpretation == "clarify",
    }


def validate_interaction_decision(
    packet: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> Dict[str, Any]:
    """Validate the model proposal against the packet's legal envelope."""

    allowed = {
        str(value)
        for value in packet.get("allowed_model_interpretations") or []
        if str(value)
    }
    interpretation = str(decision.get("interpretation") or "").strip()
    packet_event_ids = {
        str(item.get("event_id") or "")
        for item in packet.get("events") or []
        if isinstance(item, Mapping) and str(item.get("event_id") or "")
    }
    effective_event_ids = [
        str(value)
        for value in decision.get("effective_event_ids") or []
        if str(value)
    ]
    reasons: List[str] = []
    if interpretation not in allowed:
        reasons.append("interpretation_not_allowed")
    if any(event_id not in packet_event_ids for event_id in effective_event_ids):
        reasons.append("unknown_effective_event_id")
    if interpretation in {
        "accept_latest",
        "accept_once",
        "hierarchical_advance",
    }:
        if len(effective_event_ids) != 1:
            reasons.append("one_effective_event_required")
        elif events := [
            item
            for item in packet.get("events") or []
            if isinstance(item, Mapping)
        ]:
            latest_event_id = str(events[-1].get("event_id") or "")
            if effective_event_ids[0] != latest_event_id:
                reasons.append("effective_event_must_be_latest")
    if interpretation in {"clarify", "compare"} and effective_event_ids:
        reasons.append("effective_events_not_allowed")
    if interpretation == "clarify" and not bool(
        decision.get("needs_clarification")
    ):
        reasons.append("clarification_flag_required")
    if interpretation != "clarify" and bool(
        decision.get("needs_clarification")
    ):
        reasons.append("clarification_flag_not_allowed")
    return {
        "status": "valid" if not reasons else "invalid",
        "interpretation": interpretation,
        "effective_event_ids": effective_event_ids,
        "reason_code": str(decision.get("reason_code") or "").strip(),
        "needs_clarification": bool(
            decision.get("needs_clarification")
            or interpretation == "clarify"
        ),
        "validation_reasons": reasons,
    }


def event_for_id(
    histories: Iterable[Sequence[Mapping[str, Any]]],
    event_id: str,
) -> Dict[str, Any]:
    """Return the full stored action matching a normalized event id."""

    target = str(event_id or "").strip()
    for history in histories:
        for item in reversed(list(history or [])):
            if not isinstance(item, Mapping):
                continue
            candidate = str(
                item.get("event_id")
                or item.get("message_id")
                or item.get("idempotency_key")
                or ""
            ).strip()
            if candidate == target:
                return dict(item)
    return {}


def _event_is_interpretable(event: Mapping[str, Any]) -> bool:
    validation = str(event.get("validation_status") or "").casefold()
    return validation in {"valid", "ok", "accepted"}


def _deduplicate_events(
    events: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Collapse request retries while retaining semantic repeated clicks."""

    output: Dict[str, Dict[str, Any]] = {}
    anonymous: List[Dict[str, Any]] = []
    for event in events:
        identity = str(
            event.get("event_id") or event.get("idempotency_key") or ""
        ).strip()
        if identity:
            output[identity] = dict(event)
        else:
            anonymous.append(dict(event))
    return [*anonymous, *output.values()]


def _events_since_last_delivered_response(
    events: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    start = 0
    for index, event in enumerate(events):
        if str(event.get("delivery_status") or "").casefold() in {
            "success",
            "evaluated",
        }:
            start = index + 1
    return [dict(event) for event in events[start:]]


def _runtime_relation(events: Sequence[Mapping[str, Any]]) -> str:
    if any(
        str(event.get("validation_status") or "").casefold()
        not in {"valid", "ok", "accepted"}
        for event in events
    ):
        return "stale_or_invalid_present"
    if len(events) == 1:
        return "single_valid_event"
    choice_refs = [str(event.get("choice_ref") or "") for event in events]
    if choice_refs and len(set(choice_refs)) == 1:
        return "same_choice_repeat"
    layers = [str(event.get("decision_layer") or "") for event in events]
    if _is_hierarchical(events):
        return "hierarchical_sequence"
    if layers and len(set(layers)) == 1:
        return "same_layer_distinct"
    return "cross_layer_sequence"


def _is_hierarchical(events: Sequence[Mapping[str, Any]]) -> bool:
    if len(events) < 2:
        return False
    previous, current = events[-2], events[-1]
    if previous.get("decision_layer") != "province":
        return False
    if current.get("decision_layer") != "city":
        return False
    parent = str(current.get("parent_code") or current.get("province_code") or "")
    province = str(previous.get("choice_ref") or "")
    return bool(parent and (parent == province or province.endswith(parent)))


def _allowed_interpretations(
    relation: str,
    events: Sequence[Mapping[str, Any]],
) -> List[str]:
    if relation == "single_valid_event":
        return ["accept_latest"]
    if relation == "same_choice_repeat":
        return ["accept_once"]
    if relation == "hierarchical_sequence":
        return ["hierarchical_advance"]
    if relation == "same_layer_distinct":
        layer = str(events[-1].get("decision_layer") or "")
        if layer in DISCOVERY_LAYERS or layer == "promo_information":
            return ["accept_latest", "compare", "clarify"]
        return ["accept_latest", "clarify"]
    if relation == "cross_layer_sequence":
        return ["accept_latest", "clarify"]
    return ["clarify"]


def _event_sort_key(event: Mapping[str, Any]) -> tuple[datetime, datetime, str]:
    return (
        _parse_datetime(event.get("occurred_at")),
        _parse_datetime(event.get("received_at")),
        str(event.get("event_id") or ""),
    )


def _parse_datetime(value: Any) -> datetime:
    text = str(value or "").strip()
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except ValueError:
            pass
    return datetime.min


def _normalize_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(
            text.replace("Z", "+00:00")
        ).isoformat()
    except ValueError:
        return text


def _batch_ref(events: Sequence[Mapping[str, Any]]) -> str:
    first = str(events[0].get("event_id") or "event")
    last = str(events[-1].get("event_id") or "event")
    return f"interaction:{first}:{last}"[:180]


def _bounded_packet(packet: Dict[str, Any], *, max_chars: int) -> Dict[str, Any]:
    limit = max(800, int(max_chars or DEFAULT_MAX_CHARS))
    output = dict(packet)
    while len(json.dumps(output, ensure_ascii=False, default=str)) > limit:
        events = list(output.get("events") or [])
        if len(events) <= 1:
            break
        output["events"] = events[1:]
        output["event_count"] = len(output["events"])
        output["batch_ref"] = _batch_ref(output["events"])
    return output
