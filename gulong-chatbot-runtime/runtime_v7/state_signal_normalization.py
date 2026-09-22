"""Normalization, canonicalization, and readiness shaping for V7 signals.

The model and fallback extractor produce loose candidate facts. This module is
the deterministic boundary that turns those candidates into normalized
`BackgroundSignal` objects, canonicalizes API-backed choices, and computes soft
lead/order readiness summaries for the context packet.
"""

from __future__ import annotations

import re
from copy import deepcopy
from difflib import get_close_matches
from typing import Any, Dict, List, Optional, Sequence

from runtime_v7.canonical_values import CanonicalValuesProvider
from runtime_v7.entity_resolution import canonical_vehicle_query
from runtime_v7.location_resolution import (
    RuntimeV7LocationResolver,
    compact_location_resolution,
    location_display_label,
)
from runtime_v7.location_quality import is_rejected_service_location
from runtime_v7.lead_qualification import build_lead_qualification_snapshot
from runtime_v7.order_canonicalization import (
    canonical_payment_method_with_metadata as shared_canonical_payment_method_with_metadata,
    canonical_payment_option_with_metadata as shared_canonical_payment_option_with_metadata,
    local_canonical_payment_method as shared_local_canonical_payment_method,
)
from runtime_v7.product_search import normalize_terrain_types
from runtime_v7.state_signal_schema import (
    DURABLE_SIGNAL_RELATIONS,
    KNOWN_BRANDS,
    KNOWN_LOCATIONS,
    MULTI_VALUE_KEYS,
    ORDER_READINESS_FIELDS,
    ORDER_READINESS_OPTIONAL_FIELDS,
    SIGNAL_ORDER,
    TRANSIENT_SIGNAL_RELATIONS,
    BackgroundSignal,
    signal_authority_source,
)

def _construct_background_signals(
    *,
    candidates: Sequence[Dict[str, Any]],
    latest_product_observation: Dict[str, Any],
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
    location_resolver: Optional[RuntimeV7LocationResolver] = None,
) -> List[BackgroundSignal]:
    """Normalize candidates, resolve conflicts, and return prompt-facing signals."""

    normalized: List[Dict[str, Any]] = []
    for candidate in candidates:
        normalized_candidate = _normalize_candidate(
            candidate,
            canonical_values_provider=canonical_values_provider,
            location_resolver=location_resolver,
        )
        if normalized_candidate:
            normalized.append(normalized_candidate)
    normalized = _apply_latest_semantic_relations(normalized)
    normalized = _suppress_stale_acceptable_service_locations(normalized)
    normalized = _suppress_overlapping_budget_category_candidates(normalized)

    by_key: Dict[str, Dict[str, Any]] = {}
    for candidate in normalized:
        key = candidate["key"]
        current = by_key.get(key)
        if current is not None:
            current_is_durable = _normalize_relation(current.get("relation")) in DURABLE_SIGNAL_RELATIONS
            candidate_is_durable = _normalize_relation(candidate.get("relation")) in DURABLE_SIGNAL_RELATIONS
            if current_is_durable and not candidate_is_durable:
                continue
            if candidate_is_durable and not current_is_durable:
                by_key[key] = dict(candidate)
                continue
        if key in MULTI_VALUE_KEYS:
            if current is None:
                by_key[key] = dict(candidate)
                continue
            current_score = _candidate_score(current)
            candidate_score = _candidate_score(candidate)
            should_merge = _should_merge_multi_value(current, candidate)
            if candidate_score > current_score and not should_merge:
                by_key[key] = dict(candidate)
                continue
            if candidate_score < current_score and not should_merge:
                continue
            current_values = _split_multi_value(current.get("value"))
            candidate_values = _split_multi_value(candidate.get("value"))
            current["value"] = ", ".join(_unique([*current_values, *candidate_values]))
            if candidate_score > current_score:
                current["source"] = candidate.get("source")
                current["confidence"] = candidate.get("confidence")
                current["status_hint"] = candidate.get("status_hint")
                current["relation"] = candidate.get("relation")
                current["origin"] = candidate.get("origin")
            continue
        if key == "location" and current is not None:
            if _should_keep_current_location(current, candidate):
                continue
            if _should_replace_current_location(current, candidate):
                by_key[key] = candidate
                continue
        if current is None or _candidate_score(candidate) > _candidate_score(current):
            by_key[key] = candidate

    signals = []
    for key in SIGNAL_ORDER:
        candidate = by_key.get(key)
        if not candidate:
            continue
        signals.append(_candidate_to_signal(candidate, latest_product_observation=latest_product_observation))
    return signals


def _apply_latest_semantic_relations(
    candidates: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Apply latest-user retractions before selecting reusable signal values."""

    retractions = [
        candidate
        for candidate in candidates
        if str(candidate.get("source") or "") == "latest_user_message"
        and _normalize_relation(candidate.get("relation")) == "rejected"
    ]
    if not retractions:
        return [dict(candidate) for candidate in candidates]

    output: List[Dict[str, Any]] = []
    for candidate in candidates:
        relation = _normalize_relation(candidate.get("relation"))
        if relation == "rejected":
            continue
        key = str(candidate.get("key") or "")
        matching = [
            tombstone
            for tombstone in retractions
            if str(tombstone.get("key") or "") == key
        ]
        if not matching:
            output.append(dict(candidate))
            continue
        retracted_values = {
            value.casefold()
            for tombstone in matching
            for value in _split_multi_value(tombstone.get("value"))
        }
        if str(candidate.get("source") or "") == "latest_user_message":
            remaining = [
                value
                for value in _split_multi_value(candidate.get("value"))
                if value.casefold() not in retracted_values
            ]
            if remaining:
                kept = dict(candidate)
                if key in MULTI_VALUE_KEYS:
                    kept["value"] = ", ".join(remaining)
                output.append(kept)
            continue
        if key not in MULTI_VALUE_KEYS:
            continue
        remaining = [
            value
            for value in _split_multi_value(candidate.get("value"))
            if value.casefold() not in retracted_values
        ]
        if remaining:
            kept = dict(candidate)
            kept["value"] = ", ".join(remaining)
            output.append(kept)
    return output


def _suppress_stale_acceptable_service_locations(
    candidates: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Clear old travel alternatives when the customer supplies a new anchor.

    Acceptable service locations are advisory consent, not parallel customer
    locations. A new latest-user anchor therefore retires carried alternatives
    unless that same turn explicitly emits a replacement alternatives list.
    """

    latest_anchor = any(
        str(candidate.get("key") or "") == "location"
        and str(candidate.get("source") or "") == "latest_user_message"
        and _normalize_relation(candidate.get("relation")) != "rejected"
        for candidate in candidates
    )
    latest_alternatives = any(
        str(candidate.get("key") or "") == "acceptable_service_locations"
        and str(candidate.get("source") or "") == "latest_user_message"
        and _normalize_relation(candidate.get("relation")) != "rejected"
        for candidate in candidates
    )
    if not latest_anchor or latest_alternatives:
        return [dict(candidate) for candidate in candidates]
    return [
        dict(candidate)
        for candidate in candidates
        if str(candidate.get("key") or "")
        != "acceptable_service_locations"
    ]


def _suppress_overlapping_budget_category_candidates(
    candidates: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Drop duplicate Budget-tier candidates that only restate a money budget."""

    numeric_budget_sources = {
        str(candidate.get("source") or "")
        for candidate in candidates
        if str(candidate.get("key") or "") == "budget"
        and _candidate_value_has_amount(candidate)
    }
    if not numeric_budget_sources:
        return list(candidates)

    filtered: List[Dict[str, Any]] = []
    for candidate in candidates:
        if (
            str(candidate.get("key") or "") == "tire_category_preference"
            and str(candidate.get("value") or "").strip().lower() == "budget"
            and str(candidate.get("source") or "") in numeric_budget_sources
            and not _candidate_has_explicit_category_selection_support(candidate)
        ):
            continue
        filtered.append(dict(candidate))
    return filtered


def _candidate_value_has_amount(candidate: Dict[str, Any]) -> bool:
    """Return true when a normalized candidate value carries a numeric amount."""

    return bool(re.search(r"\d", str(candidate.get("value") or "")))


def _candidate_has_explicit_category_selection_support(candidate: Dict[str, Any]) -> bool:
    """Keep an overlapping category only for a typed current selection.

    `status_hint` and evidence text are model-facing explanation, not an
    authorization channel.  The extractor's closed relation field already
    distinguishes an actual selection/correction from a money-budget mention.
    """

    return _normalize_relation(candidate.get("relation")) in {
        "selected",
        "corrected",
    }


def _normalize_candidates_with_failures(
    candidates: Sequence[Dict[str, Any]],
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
    location_resolver: Optional[RuntimeV7LocationResolver] = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Normalize candidates while preserving failed rows for diagnostics."""

    normalized: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    for candidate in candidates:
        normalized_candidate = _normalize_candidate(
            candidate,
            canonical_values_provider=canonical_values_provider,
            location_resolver=location_resolver,
        )
        if normalized_candidate:
            normalized.append(normalized_candidate)
            continue
        failures.append(
            {
                "key": str(candidate.get("key") or ""),
                "value": str(candidate.get("value") or "")[:160],
                "source": str(candidate.get("source") or ""),
                "confidence": str(candidate.get("confidence") or ""),
                "reason": "normalization_or_canonicalization_failed",
            }
        )
    return normalized, failures


def _build_missing_info(
    signal_map: Dict[str, BackgroundSignal],
    *,
    latest_product_observation: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute soft lead qualification and order-readiness summaries."""

    lead_snapshot = build_lead_qualification_snapshot(list(signal_map.values()))

    order_present = {
        key: signal_map[key].value
        for key in [*ORDER_READINESS_FIELDS, *ORDER_READINESS_OPTIONAL_FIELDS]
        if key in signal_map
        and signal_map[key].value
        and signal_map[key].relation not in TRANSIENT_SIGNAL_RELATIONS
        and signal_map[key].relation != "rejected"
    }
    if latest_product_observation:
        order_present["latest_product_presentation"] = latest_product_observation.get("presentation_ref")

    order_missing = [key for key in ORDER_READINESS_FIELDS if key not in order_present]
    if latest_product_observation:
        order_missing.insert(0, "customer-selected SKU/model from the latest presentation")

    return {
        "lead_qualification": lead_snapshot.to_dict(),
        "order_readiness": {
            "status": "ready" if not order_missing else "not_ready",
            "present": order_present,
            "missing": order_missing,
            "optional": ORDER_READINESS_OPTIONAL_FIELDS,
            "note": "This is the only readiness gate here and only applies before order/payment/reservation/schedule actions. Do not ask for missing order fields while the customer is still evaluating products.",
        },
    }


def _candidate_to_signal(
    candidate: Dict[str, Any],
    *,
    latest_product_observation: Dict[str, Any],
) -> BackgroundSignal:
    """Convert a normalized candidate into a BackgroundSignal object."""

    key = str(candidate.get("key") or "")
    source = _normalize_source(candidate.get("source"))
    relation = _normalize_relation(candidate.get("relation"))
    status = _status_for_candidate(
        key=key,
        source=source,
        confirmation_state=str(
            candidate.get("confirmation_state") or "unknown"
        ),
        relation=relation,
    )
    return BackgroundSignal(
        key=key,
        label=_label_for_key(key),
        value=str(candidate.get("value") or ""),
        status=status,
        confidence=_normalize_confidence(candidate.get("confidence")),
        source=source,
        relevance=_relevance_for_key(key),
        ask_timing=_ask_timing_for_key(key),
        relation=relation,
        safe_for_action=_safe_for_action(key=key, source=source, status=status, latest_product_observation=latest_product_observation),
        resolution=_resolution_for_candidate(key=key, candidate=candidate),
        metadata=dict(candidate.get("metadata") or {}),
    )


def _resolution_for_candidate(*, key: str, candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Derive validation resolution metadata for for candidate."""

    metadata = candidate.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    normalization = metadata.get("normalization")
    if not isinstance(normalization, dict):
        return {}

    status = str(normalization.get("status") or "").strip()
    if status == "checkout_metadata_deferred_product_installment_selection":
        return {
            "status": "preference_captured_not_final",
            "source": "checkout_metadata",
            "needs": "validate after product choice and fulfillment path if installment remains preferred",
            "candidate_count": len(normalization.get("candidate_payment_types") or []),
            "safe_for_action": False,
        }
    if status == "checkout_metadata_canonicalized":
        selected_ref = _canonical_payment_selected_ref(normalization)
        return {
            "status": "canonicalized",
            "source": "checkout_metadata",
            "selected_ref": selected_ref,
            "safe_for_action": False,
        }
    if status == "local_normalized_unvalidated":
        return {
            "status": "normalized_unvalidated",
            "source": "local_alias",
            "needs": "canonical validation before action",
            "safe_for_action": False,
        }
    if status == "checkout_metadata_no_match":
        return {
            "status": "unresolved",
            "source": "checkout_metadata",
            "needs": "clarify or validate allowed choice",
            "safe_for_action": False,
        }
    if status == "checkout_metadata_error":
        return {
            "status": "normalization_error",
            "source": "checkout_metadata",
            "needs": "retry validation or ask safely",
            "safe_for_action": False,
        }
    if status in {"location_resolved", "location_ambiguous"}:
        compact = normalization.get("location_resolution")
        compact = compact if isinstance(compact, dict) else {}
        ambiguous = status == "location_ambiguous" or bool(compact.get("ambiguity_status"))
        return {
            "status": "ambiguous_location" if ambiguous else "resolved_location",
            "display_label": normalization.get("display_label"),
            "city_hint": compact.get("city_hint"),
            "province_hint": compact.get("province_hint"),
            "landmark_hint": compact.get("landmark_hint"),
            "location_precision": compact.get("location_precision"),
            "coordinates_available": bool(compact.get("coordinates_available")),
            "ambiguity_reason": compact.get("ambiguity_reason"),
            "clarification_options": list(compact.get("clarification_options") or [])[:5],
            "requires_tool_validation": True,
            "safe_for_action": False,
        }
    if status == "acceptable_service_locations_resolved":
        return {
            "status": status,
            "locations": deepcopy(normalization.get("locations") or []),
            "requires_individual_tool_validation": True,
            "safe_for_action": False,
        }
    if status == "location_resolution_error":
        return {
            "status": "location_resolution_error",
            "needs": "use the raw location cautiously or ask for clarification before service lookup",
            "safe_for_action": False,
        }
    if status in {"installation_partner_canonicalized", "installation_partner_captured"}:
        return {
            "status": status,
            "display_label": normalization.get("display_label"),
            "resolution_tier": normalization.get("resolution_tier"),
            "source": normalization.get("source"),
            "needs": "validate with service tool before booking, schedule, or reservation action",
            "requires_tool_validation": True,
            "safe_for_action": False,
        }
    return {}


def _canonical_payment_selected_ref(normalization: Dict[str, Any]) -> str:
    """Canonicalize payment selected ref with aliases and provider-backed options."""

    parts: List[str] = []
    payment_type = normalization.get("payment_type")
    if isinstance(payment_type, dict) and payment_type.get("id") not in (None, ""):
        parts.append(f"payment_type_id:{payment_type.get('id')}")
    payment_option = normalization.get("payment_option")
    if isinstance(payment_option, dict):
        if payment_option.get("id") not in (None, ""):
            parts.append(f"payment_option_id:{payment_option.get('id')}")
        if payment_option.get("name"):
            parts.append(str(payment_option.get("name")))
    return ", ".join(parts)


def _normalize_candidate(
    candidate: Dict[str, Any],
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
    location_resolver: Optional[RuntimeV7LocationResolver] = None,
) -> Optional[Dict[str, Any]]:
    """Normalize candidate into the internal signal format."""

    key = _normalize_key(candidate.get("key"))
    if not key:
        return None
    # Payment stage is a closed candidate key.  Do not reinterpret a generic
    # payment_method from model explanation/evidence prose (for example,
    # because it happens to contain "reservation" or "balance").  The model
    # can emit reservation_payment_method or balance_payment_method directly.
    if _should_preserve_structured_candidate(candidate):
        value = _clean(candidate.get("value"))[:160]
        if value in (None, ""):
            return None
        return {
            "key": key,
            "value": value,
            "source": _normalize_source(candidate.get("source")),
            "confidence": _normalize_confidence(candidate.get("confidence")),
            "status_hint": str(candidate.get("status_hint") or ""),
            "confirmation_state": str(
                candidate.get("confirmation_state") or "unknown"
            ),
            "relation": _normalize_relation(candidate.get("relation")),
            "origin": str(candidate.get("origin") or "deterministic"),
            "evidence": str(candidate.get("evidence") or ""),
            "metadata": dict(candidate.get("metadata") or {}),
        }
    # Do not use model-supplied wording such as "validated" as authority.  A
    # candidate bypasses canonicalization only when its *closed provenance*
    # says it is a runtime tool observation (or an already-preserved ledger
    # record handled above).  This prevents, among other things,
    # "unvalidated" from matching a loose "validated" check.
    provider = (
        None
        if _candidate_has_structured_canonical_authority(candidate)
        else canonical_values_provider
    )
    value, normalization_metadata = _canonical_value_with_metadata(
        key,
        candidate.get("value"),
        canonical_values_provider=provider,
        location_resolver=location_resolver,
    )
    if value in (None, "") and _candidate_is_structured_state(candidate):
        value = _clean(candidate.get("value"))[:160]
        normalization_metadata = {"status": "structured_state_carry_forward"}
    if value in (None, ""):
        return None
    if key == "location" and is_rejected_service_location(value):
        return None
    metadata = dict(candidate.get("metadata") or {})
    evidence = str(candidate.get("evidence") or "").strip()
    if evidence:
        metadata["evidence"] = evidence[:240]
    if normalization_metadata:
        metadata["normalization"] = normalization_metadata
    return {
        "key": key,
        "value": value,
        "source": _normalize_source(candidate.get("source")),
        "confidence": _normalize_confidence(candidate.get("confidence")),
        "status_hint": str(candidate.get("status_hint") or ""),
        "confirmation_state": str(
            candidate.get("confirmation_state") or "unknown"
        ),
        "relation": _normalize_relation(candidate.get("relation")),
        "origin": str(candidate.get("origin") or "deterministic"),
        "evidence": str(candidate.get("evidence") or ""),
        "metadata": metadata,
    }


def _candidate_score(candidate: Dict[str, Any]) -> int:
    """Score candidates for recency, source quality, and confidence."""

    source = str(candidate.get("source") or "")
    if source == "signal_ledger":
        # The ledger is the runtime's already-resolved current state. Older
        # customer-history text may explain that state, but a model re-emission
        # of history cannot make an older value current again. A genuinely new
        # customer correction is emitted as latest_user_message and remains the
        # only prose-derived source above carried state.
        source_score = (
            800
            if signal_authority_source(candidate)
            in {
                "validated_choice_action",
                "latest_user_message",
                "customer_history",
            }
            else 300
        )
    else:
        source_score = {
            "latest_user_message": 900,
            "validated_choice_action": 850,
            "customer_history": 700,
            "human_agent_history": 650,
            "external_evidence": 500,
            "product_observation_store": 450,
            "service_observation_store": 430,
            "conversation_context": 350,
            "recent_turns": 250,
            "active_working_memory": 200,
        }.get(source, 100)
    confidence_score = {"high": 30, "medium": 20, "low": 10}.get(str(candidate.get("confidence") or ""), 0)
    deterministic_bonus = 5 if candidate.get("origin") == "deterministic" else 0
    return source_score + confidence_score + deterministic_bonus


def _should_merge_multi_value(current: Dict[str, Any], candidate: Dict[str, Any]) -> bool:
    """Decide whether multiple values for a signal should be preserved together."""

    if str(current.get("source") or "") == str(candidate.get("source") or ""):
        return True
    if _candidate_score(current) == _candidate_score(candidate):
        return True
    return False


_RELATIVE_LOCATION_TERMS = {
    "malapit",
    "near",
    "nearby",
    "near me",
    "nearest",
    "closest",
    "sa area",
    "same area",
}


def _should_keep_current_location(current: Dict[str, Any], candidate: Dict[str, Any]) -> bool:
    """Keep a concrete remembered area over a weak relative latest location."""

    return _is_concrete_location_candidate(current) and _is_weak_relative_location_candidate(candidate)


def _should_replace_current_location(current: Dict[str, Any], candidate: Dict[str, Any]) -> bool:
    """Prefer a concrete location candidate even when it has lower recency score."""

    return _is_weak_relative_location_candidate(current) and _is_concrete_location_candidate(candidate)


def _is_weak_relative_location_candidate(candidate: Dict[str, Any]) -> bool:
    if str(candidate.get("key") or "") != "location":
        return False
    resolution = _location_resolution_metadata(candidate)
    if any(
        resolution.get(key)
        for key in (
            "city_hint",
            "province_hint",
            "landmark_hint",
            "coordinates_available",
        )
    ):
        return False
    if str(resolution.get("location_precision") or "").strip():
        return False
    value = _normalize_relative_location_text(candidate.get("value"))
    if value in _RELATIVE_LOCATION_TERMS:
        return True
    return any(term in value for term in _RELATIVE_LOCATION_TERMS)


def _is_concrete_location_candidate(candidate: Dict[str, Any]) -> bool:
    if str(candidate.get("key") or "") != "location":
        return False
    if _is_weak_relative_location_candidate(candidate):
        return False
    resolution = _location_resolution_metadata(candidate)
    if any(
        resolution.get(key)
        for key in (
            "city_hint",
            "province_hint",
            "landmark_hint",
            "coordinates_available",
        )
    ):
        return True
    if str(resolution.get("location_precision") or "").strip():
        return True
    value = _normalize_relative_location_text(candidate.get("value"))
    return bool(value and value not in _RELATIVE_LOCATION_TERMS)


def _location_resolution_metadata(candidate: Dict[str, Any]) -> Dict[str, Any]:
    metadata = candidate.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    normalization = metadata.get("normalization")
    normalization = normalization if isinstance(normalization, dict) else {}
    resolution = normalization.get("location_resolution")
    if isinstance(resolution, dict):
        return resolution
    resolution = candidate.get("resolution")
    resolution = resolution if isinstance(resolution, dict) else {}
    return {
        "city_hint": resolution.get("city_hint"),
        "province_hint": resolution.get("province_hint"),
        "landmark_hint": resolution.get("landmark_hint"),
        "location_precision": resolution.get("location_precision"),
        "coordinates_available": resolution.get("coordinates_available"),
    }


def _normalize_relative_location_text(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())).strip()


def _candidate(
    key: str,
    value: Any,
    *,
    source: str,
    confidence: str = "medium",
    status_hint: str = "",
    evidence: str = "",
) -> Dict[str, Any]:
    """Create a raw deterministic fallback candidate in the shared candidate shape."""

    return {
        "key": key,
        "value": value,
        "source": source,
        "confidence": confidence,
        "status_hint": status_hint,
        "evidence": evidence,
        "origin": "deterministic",
    }


def _normalize_key(value: Any) -> str:
    """Normalize key into the internal signal format."""

    key = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    aliases = {
        "brand": "preferred_brands",
        "brands": "preferred_brands",
        "tire_brand": "preferred_brands",
        "tire_brands": "preferred_brands",
        "preferred_brand": "preferred_brands",
        "required_brand": "required_brands",
        "tire_model": "specific_sku_model",
        "sku": "specific_sku_model",
        "model": "specific_sku_model",
        "terrain": "terrain_types",
        "terrain_type": "terrain_types",
        "tire_terrain": "terrain_types",
        "usage_type": "terrain_types",
        "pattern_type": "terrain_types",
        "phone": "contact_number",
        "phone_number": "contact_number",
        "contact_no": "contact_number",
        "qty": "quantity",
        "promo": "promo_types",
        "promo_type": "promo_types",
        "promo_interest": "promo_types",
        "promotion": "promo_types",
        "promotion_type": "promo_types",
        "schedule": "chosen_schedule_slot",
        "slot": "chosen_schedule_slot",
        "address": "delivery_address",
        "payment": "payment_method",
        "payment_methods": "payment_method",
        "reservation_payment": "reservation_payment_method",
        "reservation_payment_method": "reservation_payment_method",
        "reservation_fee_payment": "reservation_payment_method",
        "deposit_payment": "reservation_payment_method",
        "balance_payment": "balance_payment_method",
        "balance_payment_method": "balance_payment_method",
        "mode_of_payment_for_balance": "balance_payment_method",
        "payment_option": "payment_option",
        "pay_option": "payment_option",
        "payment_timing": "payment_option",
        "payment_proof": "payment_proof_evidence",
        "payment_proof_ref": "payment_proof_evidence",
        "payment_proof_evidence": "payment_proof_evidence",
        "payment_screenshot": "payment_proof_evidence",
        "order_number": "order_id",
        "order_no": "order_id",
        "order_id": "order_id",
        "order_ref": "order_id",
        "email": "email_address",
        "invoice": "invoice_to_company",
        "invoice_to_company": "invoice_to_company",
        "company_invoice": "invoice_to_company",
        "official_receipt_to_company": "invoice_to_company",
        "vehicle": "car_make_model",
        "car": "car_make_model",
        "branch": "selected_installation_partner",
        "branch_name": "selected_installation_partner",
        "selected_branch": "selected_installation_partner",
        "installation_partner": "selected_installation_partner",
        "selected_installation_partner": "selected_installation_partner",
        "service": "service_type",
        "service_kind": "service_type",
        "fulfillment_type": "service_type",
        "transaction_type": "service_type",
        "branch_addon": "branch_addons",
        "branch_addons": "branch_addons",
        "addons": "branch_addons",
        "add_ons": "branch_addons",
        "selected_addons": "branch_addons",
    }
    key = aliases.get(key, key)
    return key if key in set(SIGNAL_ORDER) else ""


def _canonical_value(
    key: str,
    value: Any,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Optional[str]:
    """Canonicalize value with aliases and provider-backed options."""

    canonical, _metadata = _canonical_value_with_metadata(
        key,
        value,
        canonical_values_provider=canonical_values_provider,
    )
    return canonical


def _canonical_value_with_metadata(
    key: str,
    value: Any,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
    location_resolver: Optional[RuntimeV7LocationResolver] = None,
) -> tuple[Optional[str], Dict[str, Any]]:
    """Canonicalize value with metadata with aliases and provider-backed options."""

    text = _clean(value)
    if not text:
        return None, {}
    if _is_unfilled_order_form_placeholder(text):
        return None, {"status": "unfilled_order_form_placeholder"}
    if key == "tire_size":
        return _normalize_tire_size_with_metadata(text)
    if key == "rim_size":
        return _normalize_rim_size(text), {}
    if key in {"preferred_brands", "required_brands", "excluded_brands"}:
        brands = _canonical_brands(value, canonical_values_provider=canonical_values_provider)
        return ", ".join(brands) if brands else None, {}
    if key == "brand_match_mode":
        normalized_mode = re.sub(r"[^a-z]+", "_", text.casefold()).strip("_")
        if normalized_mode in {"strict", "only", "required", "no_alternatives"}:
            return "strict", {}
        if normalized_mode in {"prefer", "preferred", "flexible", "alternatives_allowed"}:
            return "prefer", {}
        return None, {}
    if key == "car_make_model":
        canonical_vehicle = canonical_vehicle_query(text)
        return canonical_vehicle or _extract_vehicle(text) or text, {}
    if key == "location":
        return _canonical_location_with_metadata(
            text,
            canonical_values_provider=canonical_values_provider,
            location_resolver=location_resolver,
        )
    if key == "acceptable_service_locations":
        return _canonical_acceptable_service_locations_with_metadata(
            value,
            canonical_values_provider=canonical_values_provider,
            location_resolver=location_resolver,
        )
    if key == "location_response_status":
        normalized_status = re.sub(r"[^a-z]+", "_", text.casefold()).strip("_")
        return (
            "unavailable_now"
            if normalized_status
            in {
                "unavailable_now",
                "unknown_now",
                "not_sure_yet",
                "cannot_provide_yet",
            }
            else None
        ), {}
    if key == "contact_number":
        return _normalize_contact_number(text), {}
    if key == "quantity":
        return _normalize_quantity(text), {}
    if key == "promo_types":
        promo_types = _canonical_promo_types(value)
        return ", ".join(promo_types) if promo_types else None, {}
    if key == "promo_discovery_scope":
        normalized_scope = re.sub(r"[^a-z]+", "_", text.casefold()).strip("_")
        return (
            "all_current"
            if normalized_scope
            in {
                "all_current",
                "all_current_promos",
                "all_promos",
                "current",
                "current_promos",
                "current_promo_catalog",
            }
            else None
        ), {}
    if key == "promo_alternative_scope":
        normalized_scope = re.sub(r"[^a-z]+", "_", text.casefold()).strip("_")
        return (
            normalized_scope
            if normalized_scope in {"same_mechanic", "any_current"}
            else None
        ), {}
    if key == "terrain_types":
        terrain_types = normalize_terrain_types(value)
        return ", ".join(terrain_types) if terrain_types else None, {}
    if key == "budget":
        return _normalize_budget(text), {}
    if key == "tire_category_preference":
        return _canonical_category(text, canonical_values_provider=canonical_values_provider), {}
    if key == "excluded_tire_categories":
        categories = _canonical_categories(value, canonical_values_provider=canonical_values_provider)
        return ", ".join(categories) if categories else None, {}
    if key in {"origins", "excluded_origins"}:
        origins = _canonical_origins(value)
        return ", ".join(origins) if origins else None, {}
    if key == "selected_installation_partner":
        return _canonical_installation_partner_with_metadata(
            text,
            canonical_values_provider=canonical_values_provider,
        )
    if key == "service_type":
        return _normalize_service_type_signal(text), {}
    if key == "branch_addons":
        addons = _canonical_branch_addons(value, canonical_values_provider=canonical_values_provider)
        return ", ".join(addons) if addons else None, {}
    if key == "payment_option":
        return _canonical_payment_option_with_metadata(
            text,
            canonical_values_provider=canonical_values_provider,
        )
    if key in {"payment_method", "reservation_payment_method", "balance_payment_method"}:
        return _canonical_payment_method_with_metadata(
            text,
            key=key,
            canonical_values_provider=canonical_values_provider,
        )
    if key in {"first_name", "last_name"}:
        return text.title(), {}
    if key == "email_address":
        return _extract_email(text) or text.lower(), {}
    if key == "invoice_to_company":
        return _normalize_invoice_to_company(text), {}
    if key in {"order_summary_review_confirmation", "explicit_order_confirmation"}:
        return (
            "yes"
            if text.lower() in {"yes", "true", "confirmed", "confirm", "go", "go na"}
            or _has_order_confirmation(text)
            else text
        ), {}
    return text[:160], {}


def _candidate_has_structured_canonical_authority(candidate: Dict[str, Any]) -> bool:
    """Return whether a candidate came from a closed trusted runtime source.

    This boundary intentionally does not inspect `status_hint`, `origin`, or
    free-text evidence.  Those fields may be model generated and are advisory
    only.  Ledger values with existing normalization metadata take the
    preserve path above; fresh tool-observation values are the only remaining
    candidates that may skip another canonical lookup.
    """

    return _normalize_source(candidate.get("source")) in {
        "product_observation_store",
        "service_observation_store",
    }


def _should_preserve_structured_candidate(candidate: Dict[str, Any]) -> bool:
    """Return whether a previously normalized runtime signal should not be re-resolved."""

    if str(candidate.get("source") or "") != "signal_ledger":
        return False
    metadata = candidate.get("metadata")
    if not isinstance(metadata, dict):
        return False
    normalization = metadata.get("normalization")
    if not isinstance(normalization, dict):
        return False
    return bool(str(normalization.get("status") or "").strip())


def _candidate_is_structured_state(candidate: Dict[str, Any]) -> bool:
    """Return whether a candidate already came from normalized runtime state."""

    return str(candidate.get("source") or "") in {
        "signal_ledger",
        "service_observation_store",
        "product_observation_store",
    }


def _normalize_service_type_signal(value: Any) -> Optional[str]:
    """Canonicalize a model-proposed service value through closed aliases."""

    text = re.sub(r"[\s_-]+", " ", _clean(value).casefold()).strip()
    if not text:
        return None
    aliases = {
        "installation": "installation",
        "install": "installation",
        "tire installation": "installation",
        "tyre installation": "installation",
        "mounting": "installation",
        "kabit": "installation",
        "pakabit": "installation",
        "pagkabit": "installation",
        "delivery": "delivery",
        "deliver": "delivery",
        "shipping": "delivery",
        "ship": "delivery",
        "padala": "delivery",
        "home service": "home_service",
        "home installation": "home_service",
        "home install": "home_service",
        "pickup": "pickup",
        "pick up": "pickup",
        "collection": "pickup",
    }
    return aliases.get(text)


def _status_for_candidate(
    *,
    key: str,
    source: str,
    confirmation_state: str,
    relation: str = "asserted",
) -> str:
    """Derive status from closed relation, source, and confirmation fields."""

    if key in {"latest_product_presentation", "latest_service_presentation"}:
        return "tool_grounded"
    if source == "signal_ledger":
        return "remembered_signal"
    if relation in TRANSIENT_SIGNAL_RELATIONS:
        return "mentioned_unconfirmed"
    if str(confirmation_state or "unknown").strip().lower() == "unconfirmed":
        return "mentioned_unconfirmed"
    if key == "specific_sku_model":
        return "customer_reference_needs_validation"
    if source == "active_working_memory":
        return "remembered_context"
    if source == "recent_turns":
        return "recent_context"
    if source == "human_agent_history":
        return "human_agent_context"
    if source == "customer_history":
        return "customer_history"
    if source == "external_evidence":
        return "external_evidence_unvalidated"
    if source == "latest_user_message":
        if key in {"contact_number", "first_name", "last_name", "email_address", "order_summary_review_confirmation", "explicit_order_confirmation"}:
            return "provided_by_latest_user_message"
        if (
            str(confirmation_state or "unknown").strip().lower()
            == "confirmed"
        ):
            return "confirmed_by_latest_user_message"
        return "mentioned_by_latest_user_message"
    return "recognized_context"


def _normalize_relation(value: Any) -> str:
    """Return one supported model-declared relationship to the current state."""

    relation = str(value or "asserted").strip().lower()
    if relation in {
        "asserted",
        "selected",
        "conditional",
        "question_only",
        "rejected",
        "corrected",
        "historical",
    }:
        return relation
    return "asserted"


def _safe_for_action(
    *,
    key: str,
    source: str,
    status: str,
    latest_product_observation: Dict[str, Any],
) -> bool:
    """Derive action-safety metadata for for action."""

    if key == "latest_product_presentation":
        return bool(latest_product_observation)
    if key == "latest_service_presentation":
        return True
    if key == "promo_discovery_scope":
        return source == "latest_user_message"
    if status == "mentioned_unconfirmed":
        return False
    if source != "latest_user_message":
        return False
    return key in {
        "tire_size",
        "rim_size",
        "preferred_brands",
        "required_brands",
        "brand_match_mode",
        "excluded_brands",
        "contact_number",
        "quantity",
        "promo_types",
        "promo_alternative_scope",
        "budget",
        "tire_category_preference",
        "excluded_tire_categories",
        "origins",
        "excluded_origins",
    }


def _label_for_key(key: str) -> str:
    """Return display label metadata for for key."""

    return {
        "tire_size": "Tire size",
        "rim_size": "Rim size",
        "preferred_brands": "Preferred brands",
        "required_brands": "Required brands",
        "brand_match_mode": "Brand match mode",
        "excluded_brands": "Excluded brands",
        "car_make_model": "Car make/model",
        "location": "Location",
        "acceptable_service_locations": "Acceptable service locations",
        "location_response_status": "Location response status",
        "contact_number": "Contact number",
        "quantity": "Quantity",
        "promo_types": "Promo types",
        "promo_discovery_scope": "Promo discovery scope",
        "promo_alternative_scope": "Promo alternative scope",
        "budget": "Budget",
        "tire_category_preference": "Tire category preference",
        "excluded_tire_categories": "Excluded tire categories",
        "origins": "Preferred origins",
        "excluded_origins": "Excluded origins",
        "latest_product_presentation": "Latest product presentation",
        "external_product_evidence": "External product evidence",
        "website_inquiry_evidence": "Website inquiry evidence",
        "latest_service_presentation": "Latest service presentation",
        "specific_sku_model": "Product model/query",
        "terrain_types": "Terrain/pattern type",
        "service_type": "Service type",
        "chosen_schedule_slot": "Chosen schedule/slot",
        "delivery_address": "Delivery address",
        "selected_installation_partner": "Selected installation partner",
        "branch_addons": "Branch addons",
        "reservation_payment_method": "Reservation payment method",
        "balance_payment_method": "Balance payment method",
        "payment_option": "Payment option",
        "payment_method": "Payment method",
        "payment_proof_evidence": "Payment proof evidence",
        "first_name": "First name",
        "last_name": "Last name",
        "email_address": "Email address",
        "invoice_to_company": "Invoice to company",
        "order_summary_review_confirmation": "Order summary review confirmation",
        "explicit_order_confirmation": "Explicit order confirmation",
    }.get(key, key.replace("_", " ").title())


def _relevance_for_key(key: str) -> str:
    """Return prompt relevance metadata for for key."""

    return {
        "tire_size": "Lead qualification and product discovery",
        "rim_size": "Product discovery when full tire size is not yet known",
        "preferred_brands": "Lead qualification and product-search presentation preference",
        "required_brands": "Lead qualification and active product-search brand anchor",
        "brand_match_mode": "Explicit customer-only brand restriction for product presentation",
        "excluded_brands": "Product-search brand exclusion preference",
        "car_make_model": "Optional fitment context; tire size remains stronger for product search",
        "location": "Lead qualification and later fulfillment planning; reuse if known and do not re-ask during product discovery",
        "acceptable_service_locations": "Advisory customer travel alternatives for explicit provider checks; never availability evidence or a replacement anchor",
        "location_response_status": "One-turn progression signal for offering contact follow-up when location cannot yet be provided",
        "contact_number": "Lead qualification and order readiness",
        "quantity": "Product pricing and order readiness",
        "promo_types": "Product promo preference; Buy 3 Get 1 FREE requires a four-tire path",
        "promo_discovery_scope": "Latest-turn request to browse the current reviewed promo catalog",
        "promo_alternative_scope": "Explicit customer consent for a scoped promo fallback",
        "budget": "Product-search preference and lead qualification",
        "tire_category_preference": "Product-search preference, not a fitment category",
        "excluded_tire_categories": "Product-search exclusion preference, not a fitment category",
        "origins": "Product origin preference",
        "excluded_origins": "Product origin exclusion preference",
        "latest_product_presentation": "Use refs for follow-up product questions; still requires customer choice for order",
        "external_product_evidence": "Image/OCR product context only; validate availability, price, promo, stock, warranty, or fitment through product tools",
        "website_inquiry_evidence": "Gulong-owned website, checkout, order, email, or digital-surface evidence for routing only",
        "latest_service_presentation": "Use refs for follow-up service questions; service observations are read-only and not booking confirmations",
        "specific_sku_model": "Product model or pattern query; not a selected SKU until bound to a trusted product ref",
        "terrain_types": "Product-search terrain or pattern constraint such as all-terrain, mud-terrain, highway-terrain, or rugged-terrain",
        "service_type": "Fulfillment/service preference; validate availability through service tools",
        "chosen_schedule_slot": "Installation or delivery readiness; validate slot availability before booking",
        "delivery_address": "Delivery order readiness",
        "selected_installation_partner": "Installation readiness; validate branch id and availability before booking",
        "branch_addons": "Optional branch addon choices; validate addon catalog before pricing/order summary",
        "reservation_payment_method": "Passive payment preference for later order readiness; do not push during product discovery",
        "balance_payment_method": "Passive balance payment preference for later order readiness; do not push installment during product discovery",
        "payment_option": "Order payment timing preference; clarify Pay Now vs Pay Later before payment instructions",
        "payment_method": "Passive payment preference only; validate allowed methods before order/payment instructions",
        "payment_proof_evidence": "External payment screenshot evidence only; match against payment request/order details before acknowledging proof",
        "first_name": "Order readiness",
        "last_name": "Order readiness",
        "email_address": "Order readiness",
        "invoice_to_company": "Optional invoice/order form preference",
        "order_summary_review_confirmation": "Permission to show or validate the order summary; not order submission permission",
        "explicit_order_confirmation": "Order submission guard; only valid after exact order summary or validated submit payload is shown",
    }.get(key, "")


def _ask_timing_for_key(key: str) -> str:
    """Return preferred ask timing metadata for timing for key."""

    return {
        "tire_size": "now_if_needed_for_product_discovery",
        "rim_size": "now_if_needed_for_product_discovery",
        "preferred_brands": "now_if_relevant_to_product_search",
        "required_brands": "now_if_relevant_to_product_search",
        "brand_match_mode": "now_if_relevant_to_product_search",
        "excluded_brands": "now_if_relevant_to_product_search",
        "car_make_model": "later_unless_fitment_needed",
        "location": "later_for_fulfillment_reuse_known_value",
        "acceptable_service_locations": "only_when_customer_explicitly_accepts_alternative_service_areas",
        "location_response_status": "current_turn_only_after_location_is_unavailable",
        "contact_number": "later_before_order_confirmation",
        "quantity": "now_if_needed_for_pricing",
        "promo_types": "now_if_relevant_to_product_search",
        "promo_discovery_scope": "current_promo_turn_only",
        "promo_alternative_scope": "current_promo_turn_only",
        "budget": "now_if_needed_for_product_search",
        "tire_category_preference": "now_if_relevant_to_product_search",
        "excluded_tire_categories": "now_if_relevant_to_product_search",
        "origins": "now_if_relevant_to_product_search",
        "excluded_origins": "now_if_relevant_to_product_search",
        "latest_product_presentation": "now_for_product_followups",
        "external_product_evidence": "now_if_latest_request_asks_about_visible_product_or_image",
        "website_inquiry_evidence": "routing_context_only",
        "latest_service_presentation": "now_for_service_followups",
        "specific_sku_model": "now_for_product_search_or_after_customer_product_choice",
        "terrain_types": "now_for_product_search",
        "service_type": "when_fulfillment_path_is_relevant",
        "chosen_schedule_slot": "after_fulfillment_path",
        "delivery_address": "after_delivery_path",
        "selected_installation_partner": "after_product_choice_if_installation",
        "branch_addons": "optional_after_branch_selection",
        "reservation_payment_method": "later_after_product_and_fulfillment",
        "balance_payment_method": "later_after_product_and_fulfillment",
        "payment_option": "after_product_choice_before_order_confirmation",
        "payment_method": "later_after_product_and_fulfillment",
        "payment_proof_evidence": "after_payment_request",
        "first_name": "before_order_confirmation",
        "last_name": "before_order_confirmation",
        "email_address": "before_order_confirmation",
        "invoice_to_company": "optional_before_order_confirmation",
        "order_summary_review_confirmation": "before_order_summary",
        "explicit_order_confirmation": "last_after_order_summary",
    }.get(key, "later")


def _normalize_source(value: Any) -> str:
    """Normalize source into the internal signal format."""

    source = str(value or "").strip().lower()
    aliases = {
        "latest": "latest_user_message",
        "user": "latest_user_message",
        "message": "latest_user_message",
        "memory": "active_working_memory",
        "working_memory": "active_working_memory",
        "recent": "recent_turns",
        "tool": "product_observation_store",
        "product_observation": "product_observation_store",
        "agent": "human_agent_history",
        "human_agent": "human_agent_history",
        "human_agent_context": "human_agent_history",
        "human_agent_message": "human_agent_history",
        "image": "external_evidence",
        "image_evidence": "external_evidence",
        "external_image_evidence": "external_evidence",
    }
    source = aliases.get(source, source)
    if source not in {
        "latest_user_message",
        "active_working_memory",
        "recent_turns",
        "conversation_context",
        "product_observation_store",
        "service_observation_store",
        "signal_ledger",
        "customer_history",
        "human_agent_history",
        "external_evidence",
    }:
        return "conversation_context"
    return source


def _normalize_confidence(value: Any) -> str:
    """Normalize confidence into the internal signal format."""

    confidence = str(value or "").strip().lower()
    if confidence in {"high", "medium", "low"}:
        return confidence
    return "medium"


def _turns_text(turns: Sequence[Dict[str, str]]) -> str:
    """Flatten recent turns into compact text for fallback diagnostics."""

    parts: List[str] = []
    for turn in turns[-6:]:
        content = _clean(turn.get("content"))
        if content:
            parts.append(content)
    return "\n".join(parts)


def _extract_tire_sizes(text: str) -> List[str]:
    """Extract tire sizes from text for fallback parsing."""

    sizes: List[str] = []
    for match in re.finditer(
        r"\b(?P<rim>1\d|2[0-4])\s*/\s*(?P<section>\d{3})\s*/\s*(?P<aspect>\d{2})\b",
        text or "",
    ):
        section, _correction = _normalize_metric_section_width(match.group("section"))
        sizes.append(f"{section}/{match.group('aspect')}R{match.group('rim')}")
    for match in re.finditer(r"\b(?P<section>\d{3})\s*/?\s*(?P<aspect>\d{2})\s*/?\s*[Rr]?\s*(?P<rim>\d{2})\b", text or ""):
        sizes.append(f"{match.group('section')}/{match.group('aspect')}R{match.group('rim')}")
    return sizes


def _normalize_tire_size(text: str) -> Optional[str]:
    """Normalize tire size into the internal signal format."""

    value, _metadata = _normalize_tire_size_with_metadata(text)
    return value


def _normalize_tire_size_with_metadata(text: str) -> tuple[Optional[str], Dict[str, Any]]:
    """Normalize metric tire size and flag likely one-digit section typos."""

    sizes: List[str] = []
    corrections: List[Dict[str, Any]] = []
    for match in re.finditer(
        r"\b(?P<rim>1\d|2[0-4])\s*/\s*(?P<section>\d{3})\s*/\s*(?P<aspect>\d{2})\b",
        text or "",
    ):
        raw_section = match.group("section")
        aspect = match.group("aspect")
        rim = match.group("rim")
        section, correction = _normalize_metric_section_width(raw_section)
        raw_size = f"{rim}/{raw_section}/{aspect}"
        canonical_size = f"{section}/{aspect}R{rim}"
        sizes.append(canonical_size)
        if correction:
            correction.update({"raw": raw_size, "canonical": canonical_size})
            corrections.append(correction)
    for match in re.finditer(
        r"\b(?P<section>\d{3})\s*/?\s*(?P<aspect>\d{2})\s*/?\s*[Rr]?\s*(?P<rim>\d{2})(?P<commercial>[Cc])?\b",
        text or "",
    ):
        raw_section = match.group("section")
        aspect = match.group("aspect")
        rim = f"{match.group('rim')}{(match.group('commercial') or '').upper()}"
        section, correction = _normalize_metric_section_width(raw_section)
        raw_size = f"{raw_section}/{aspect}R{rim}"
        canonical_size = f"{section}/{aspect}R{rim}"
        sizes.append(canonical_size)
        if correction:
            correction.update({"raw": raw_size, "canonical": canonical_size})
            corrections.append(correction)
    for match in re.finditer(
        r"\b(?P<diameter>\d{2}(?:\.\d+)?)\s*[Xx]\s*(?P<section>\d{1,2}(?:\.\d+)?)\s*[Rr]\s*(?P<rim>\d{2})\b",
        text or "",
    ):
        sizes.append(
            f"{_normalize_flotation_decimal(match.group('diameter'))}"
            f"X{_normalize_flotation_decimal(match.group('section'), width=True)}"
            f"R{match.group('rim')}"
        )
    for match in re.finditer(
        r"\b(?P<section>\d{3})\s*(?:/|[Rr])\s*(?P<rim>1\d|2[0-4])\s*(?P<commercial>[Cc])?\b",
        text or "",
    ):
        sizes.append(f"{match.group('section')}R{match.group('rim')}{(match.group('commercial') or '').upper()}")
    metadata: Dict[str, Any] = {}
    if corrections:
        metadata = {
            "status": "likely_metric_section_width_typo_corrected",
            "source": "local_tire_size_normalizer",
            "corrections": corrections,
            "safe_for_action": True,
        }
    return (", ".join(_unique(sizes)) if sizes else None), metadata


def _normalize_flotation_decimal(value: str, *, width: bool = False) -> str:
    """Normalize flotation tire-size decimal components without metric rounding."""

    text = str(value or "").strip()
    if not text:
        return text
    if "." not in text:
        return text
    try:
        number = float(text)
    except Exception:
        return text
    return f"{number:.2f}" if width else f"{number:g}"


def _normalize_metric_section_width(section: str) -> tuple[str, Dict[str, Any]]:
    """Correct one-off nonstandard metric section widths to the nearest 5 mm."""

    try:
        value = int(str(section or "").strip())
    except Exception:
        return str(section or ""), {}
    if not (100 <= value <= 405) or value % 5 == 0:
        return str(value), {}
    lower = (value // 5) * 5
    upper = lower + 5
    nearest = upper if (upper - value) <= (value - lower) else lower
    distance = abs(nearest - value)
    if distance > 1:
        return str(value), {
            "status": "nonstandard_metric_section_width_flagged",
            "input_section_width": str(value),
            "reason": "metric passenger tire section widths usually use 5 mm increments",
        }
    return str(nearest), {
        "status": "section_width_rounded_to_nearest_5mm",
        "input_section_width": str(value),
        "canonical_section_width": str(nearest),
        "reason": "one-off customer typo against common metric tire section-width increments",
    }


def _legacy_normalize_tire_size(text: str) -> Optional[str]:
    """Deprecated helper retained as local documentation for old parsing."""

    sizes = _extract_tire_sizes(text)
    return ", ".join(_unique(sizes)) if sizes else None


def _extract_rim_size(text: str) -> Optional[str]:
    """Extract rim size from text for fallback parsing."""

    lowered = (text or "").lower()
    if "kinse" in lowered:
        return "R15"
    bare = re.fullmatch(r"\s*([1-2]\d)C?\s*", text or "", flags=re.IGNORECASE)
    if bare:
        suffix = "C" if str(text or "").strip().upper().endswith("C") else ""
        return f"R{bare.group(1)}{suffix}"
    match = re.search(r"\b(?:rim\s*)?[Rr]\s*([1-2]\d)\b|\brim\s*([1-2]\d)\b", text or "", flags=re.IGNORECASE)
    if not match:
        return None
    rim = match.group(1) or match.group(2)
    return f"R{rim}"


def _normalize_rim_size(text: str) -> Optional[str]:
    """Normalize rim size into the internal signal format."""

    return _extract_rim_size(text)


def _extract_brands(text: str) -> List[str]:
    """Extract brands from text for fallback parsing."""

    lowered = (text or "").lower()
    found = []
    for brand in KNOWN_BRANDS:
        if brand.lower() in lowered:
            found.append(brand)
    return found


def _canonical_brand(
    text: str,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Optional[str]:
    """Canonicalize brand with aliases and provider-backed options."""

    normalized = _alnum_lower(text)
    aliases = {
        "michelan": "MICHELIN",
        "michelin": "MICHELIN",
        "michellin": "MICHELIN",
        "yoko": "YOKOHAMA",
        "yokohoma": "YOKOHAMA",
        "yokohama": "YOKOHAMA",
        "bridgeston": "BRIDGESTONE",
        "goodyr": "GOODYEAR",
        "bfgoodrich": "BFGOODRICH",
    }
    if normalized in aliases:
        return aliases[normalized]
    brand_map = {_alnum_lower(brand): brand for brand in KNOWN_BRANDS}
    if normalized in brand_map:
        return brand_map[normalized]
    matches = get_close_matches(normalized, list(brand_map.keys()), n=1, cutoff=0.78)
    if matches:
        return brand_map[matches[0]]
    return _canonical_from_provider_options(
        text,
        canonical_values_provider.brands() if canonical_values_provider else [],
        transform=lambda value: str(value or "").strip().upper(),
        cutoff=0.70,
    )


def _canonical_brands(
    value: Any,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> List[str]:
    """Canonicalize brands with aliases and provider-backed options."""

    if isinstance(value, list):
        raw_parts = [str(item or "") for item in value]
    else:
        raw = str(value or "")
        raw_parts = re.split(r"\s*(?:,|/|\||\bor\b|\band\b|o kaya)\s*", raw, flags=re.IGNORECASE)
    brands: List[str] = []
    for part in raw_parts:
        brand = _canonical_brand(part, canonical_values_provider=canonical_values_provider)
        if brand:
            brands.append(brand)
    lowered_all = _alnum_lower(" ".join(raw_parts))
    alias_scan = {
        "michelan": "MICHELIN",
        "michellin": "MICHELIN",
        "michelin": "MICHELIN",
        "yoko": "YOKOHAMA",
        "yokohoma": "YOKOHAMA",
        "yokohama": "YOKOHAMA",
        "bridgeston": "BRIDGESTONE",
    }
    for alias, brand in alias_scan.items():
        if alias in lowered_all:
            brands.append(brand)
    return _unique(brands)


def _split_multi_value(value: Any) -> List[str]:
    """Split a comma-separated multi-value signal into individual values."""

    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _extract_vehicle(text: str) -> Optional[str]:
    """Extract vehicle from text for fallback parsing."""

    lowered = (text or "").lower()
    if "wigo" in lowered or "wgo" in lowered:
        return "Toyota Wigo"
    canonical = canonical_vehicle_query(text)
    if canonical and canonical != text:
        return canonical
    match = re.search(r"\b(Toyota|Honda|Mitsubishi|Nissan|Suzuki|Ford|Hyundai|Kia|Mazda|Isuzu)\s+([A-Za-z0-9-]+)\b", text or "", flags=re.IGNORECASE)
    if not match:
        return None
    model = match.group(2)
    return f"{match.group(1).title()} {model.upper() if model.isalnum() and len(model) <= 3 else model.title()}"


def _extract_location(text: str) -> Optional[str]:
    """Extract location from text for fallback parsing."""

    for location in KNOWN_LOCATIONS:
        if re.search(rf"\b{re.escape(location)}\b", text or "", flags=re.IGNORECASE):
            return location
    return _canonical_location(text)


def _canonical_location(
    text: str,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Optional[str]:
    """Canonicalize location with aliases and provider-backed options."""

    lowered = (text or "").strip().lower()
    aliases = {
        "qc": "Quezon City",
        "quezon": "Quezon City",
        "cubao qc": "Cubao",
        "alabang": "Alabang",
    }
    if lowered in aliases:
        return aliases[lowered]
    location_map = {_alnum_lower(location): location for location in KNOWN_LOCATIONS}
    normalized = _alnum_lower(text)
    if normalized in location_map:
        return location_map[normalized]
    matches = get_close_matches(normalized, list(location_map.keys()), n=1, cutoff=0.82)
    if matches:
        return location_map[matches[0]]
    return _canonical_from_provider_options(
        text,
        canonical_values_provider.locations() if canonical_values_provider else [],
        transform=_title_clean,
        cutoff=0.80,
    )


def _canonical_location_with_metadata(
    text: str,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
    location_resolver: Optional[RuntimeV7LocationResolver] = None,
) -> tuple[Optional[str], Dict[str, Any]]:
    """Canonicalize a location signal and attach compact resolver metadata."""

    if location_resolver is None:
        return _canonical_location(text, canonical_values_provider=canonical_values_provider), {}
    try:
        resolution = location_resolver.resolve(text, allow_geocode=False)
    except TypeError:
        resolution = location_resolver.resolve(text)
    except Exception:
        fallback = _canonical_location(text, canonical_values_provider=canonical_values_provider)
        metadata = {
            "status": "location_resolution_error",
            "safe_for_action": False,
        }
        return fallback, metadata if fallback else {}

    compact = compact_location_resolution(resolution)
    display_label = location_display_label(text, resolution)
    value = display_label or _canonical_location(text, canonical_values_provider=canonical_values_provider)
    if not value:
        return None, {}
    return (
        value,
        {
            "status": (
                "location_ambiguous"
                if compact.get("ambiguity_status")
                else "location_resolved"
            ),
            "display_label": value,
            "location_resolution": compact,
            "safe_for_action": False,
        },
    )


def _canonical_acceptable_service_locations_with_metadata(
    value: Any,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
    location_resolver: Optional[RuntimeV7LocationResolver] = None,
) -> tuple[Optional[str], Dict[str, Any]]:
    """Resolve each customer-approved travel alternative independently.

    Canonical location labels commonly contain commas, so this signal never
    uses the generic comma-delimited multi-value representation. The compact
    display value uses `` | `` while structured per-location resolution stays
    in metadata for model context and later explicit provider checks.
    """

    raw_values = value if isinstance(value, list) else [value]
    locations: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_values:
        raw_text = _clean(raw)
        if not raw_text:
            continue
        canonical, metadata = _canonical_location_with_metadata(
            raw_text,
            canonical_values_provider=canonical_values_provider,
            location_resolver=location_resolver,
        )
        if not canonical or is_rejected_service_location(canonical):
            continue
        identity = _alnum_lower(canonical)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        locations.append(
            {
                "value": canonical,
                "source_value": raw_text,
                "resolution": deepcopy(metadata),
            }
        )
    if not locations:
        return None, {}
    return (
        " | ".join(str(item["value"]) for item in locations),
        {
            "status": "acceptable_service_locations_resolved",
            "locations": locations,
            "safe_for_action": False,
        },
    )


def _extract_contact_number(text: str) -> Optional[str]:
    """Extract contact number from text for fallback parsing."""

    match = re.search(r"(?<!\d)(?:\+?63|0)9\d{9}(?!\d)", text or "")
    return _normalize_contact_number(match.group(0)) if match else None


def _normalize_contact_number(text: str) -> Optional[str]:
    """Normalize only a structurally valid Philippine mobile number."""

    digits = re.sub(r"\D+", "", text or "")
    if digits.startswith("63") and len(digits) == 12:
        return "0" + digits[2:]
    if digits.startswith("09") and len(digits) == 11:
        return digits
    return None


def _extract_quantity(text: str) -> Optional[str]:
    """Extract quantity from text for fallback parsing."""

    match = re.search(r"\b([1-9]\d?)\s*(?:pcs?|pieces?|tires?|gulong)\b", text or "", flags=re.IGNORECASE)
    if match:
        return match.group(1)
    if re.search(r"\bset\s+of\s+4\b|\b4\s*set\b", text or "", flags=re.IGNORECASE):
        return "4"
    return None


def _normalize_quantity(text: str) -> Optional[str]:
    """Normalize quantity into the internal signal format."""

    extracted = _extract_quantity(text)
    if extracted:
        return extracted
    match = re.search(r"\b([1-9]\d?)\b", text or "")
    return match.group(1) if match else None


def _extract_budget(text: str) -> Optional[str]:
    """Extract budget from text for fallback parsing."""

    lowered = (text or "").lower()
    amount_pattern = r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?k)"
    match = re.search(rf"\b(?:budget|around|mga|about|php|p|worth)\s*{amount_pattern}\b", lowered)
    if not match:
        match = re.search(rf"\b{amount_pattern}\s*(?:max|budget|total|all-in|each|per tire)\b", lowered)
    if not match:
        return None
    raw = match.group(1).replace(",", "")
    amount = float(raw[:-1]) * 1000 if raw.endswith("k") else float(raw)
    scope = "per tire" if any(token in lowered for token in ["each", "per tire", "per piece"]) else "total"
    return f"about PHP {amount:,.0f} {scope}"


def _normalize_budget(text: str) -> Optional[str]:
    """Normalize budget into the internal signal format."""

    extracted = _extract_budget(text)
    if extracted:
        return extracted
    stripped = str(text or "").strip()
    if re.fullmatch(r"(?:php|p)?\s*\d[\d,]*(?:\.\d+)?\s*k?", stripped, flags=re.IGNORECASE):
        raw = re.sub(r"(?i)^(?:php|p)\s*", "", stripped).replace(",", "").strip()
        amount = float(raw[:-1]) * 1000 if raw.lower().endswith("k") else float(raw)
        return f"about PHP {amount:,.0f} total"
    return None


def _canonical_category(
    text: str,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Optional[str]:
    """Canonicalize a model-provided category value with aliases."""

    category_map = {
        "budget": "Budget",
        "budgettire": "Budget",
        "budgettires": "Budget",
        "budgetoption": "Budget",
        "budgetoptions": "Budget",
        "budgetcategory": "Budget",
        "economy": "Economy",
        "economytire": "Economy",
        "economytires": "Economy",
        "midrange": "Mid Range",
        "midrangetire": "Mid Range",
        "midrangetires": "Mid Range",
        "premium": "Premium",
        "premiumtire": "Premium",
        "premiumtires": "Premium",
    }
    normalized = _alnum_lower(text)
    if normalized in category_map:
        return category_map[normalized]
    if any(char.isdigit() for char in normalized):
        return None
    matches = get_close_matches(normalized, list(category_map.keys()), n=1, cutoff=0.8)
    if matches:
        return category_map[matches[0]]
    return _canonical_from_provider_options(
        text,
        canonical_values_provider.tire_categories() if canonical_values_provider else [],
        transform=_title_clean,
        cutoff=0.80,
    )


def _canonical_categories(
    value: Any,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> List[str]:
    """Canonicalize one or more model-supplied tire category values."""

    if isinstance(value, (list, tuple, set)):
        raw_values = [str(item or "") for item in value]
    else:
        raw_values = re.split(r"[,/;]|\band\b|\bor\b", str(value or ""), flags=re.IGNORECASE)
    categories: List[str] = []
    for raw in raw_values:
        category = _canonical_category(raw.strip(), canonical_values_provider=canonical_values_provider)
        if category and category not in categories:
            categories.append(category)
    return categories


def _canonical_promo_types(value: Any) -> List[str]:
    """Canonicalize model-supplied promo type labels into tool values."""

    if isinstance(value, (list, tuple, set)):
        raw_values = [str(item or "") for item in value]
    else:
        raw_values = re.split(r"[,/;]|\band\b|\bor\b", str(value or ""), flags=re.IGNORECASE)
    promos: List[str] = []
    for raw in raw_values:
        normalized = _alnum_lower(raw)
        if not normalized:
            continue
        if normalized in {
            "31",
            "3plus1",
            "b3g1",
            "buy3get1",
            "buy3get1free",
            "buy3take1",
            "buy3take1free",
            "buy3free1",
            "buy3getone",
            "buy3takeone",
        }:
            promos.append("buy3get1")
            continue
        if normalized in {
            "discount",
            "discounts",
            "productdiscount",
            "phpoff",
            "pesooff",
            "offpertire",
            "cashdiscount",
        }:
            promos.append("product_discount")
            continue
        if normalized in {"clearance", "clearancesale", "sale"}:
            promos.append("clearance")
            continue
        if normalized in {"promo", "promos", "promotion", "promotions", "anypromo", "anypromos"}:
            promos.append("any")
    return _unique(promos)


def _canonical_origins(value: Any) -> List[str]:
    """Canonicalize one or more model-supplied origin values."""

    if isinstance(value, (list, tuple, set)):
        raw_values = [str(item or "") for item in value]
    else:
        raw_values = re.split(r"[,/;]|\band\b|\bor\b", str(value or ""), flags=re.IGNORECASE)
    origins: List[str] = []
    aliases = {
        "china": "China",
        "chinese": "China",
        "japan": "Japan",
        "japanese": "Japan",
        "thailand": "Thailand",
        "thai": "Thailand",
        "indonesia": "Indonesia",
        "korea": "Korea",
        "south korea": "Korea",
        "usa": "USA",
        "us": "USA",
        "america": "USA",
        "europe": "Europe",
        "european": "Europe",
    }
    for raw in raw_values:
        lowered = raw.strip().lower()
        if not lowered:
            continue
        origins.append(aliases.get(lowered, raw.strip().title()))
    return _unique(origins)


def _extract_selected_product_reference(text: str) -> Optional[str]:
    """Extract selected product reference from text for fallback parsing."""

    lowered = (text or "").lower()
    if any(token in lowered for token in ["yun una", "yung una", "first one", "1st one", "card_1"]):
        return "customer referred to first shown option"
    if any(token in lowered for token in ["kunin ko", "take that", "i'll take", "reserve", "order na"]):
        return "customer may be selecting a shown option"
    return None


def _extract_schedule(text: str) -> Optional[str]:
    """Extract schedule from text for fallback parsing."""

    lowered = (text or "").lower()
    if any(token in lowered for token in ["today", "tomorrow", "bukas", "mamaya", "schedule", "slot", "appointment"]):
        return _clean(text)[:120]
    return None


def _extract_delivery_address(text: str) -> Optional[str]:
    """Extract delivery address from text for fallback parsing."""

    lowered = (text or "").lower()
    if any(token in lowered for token in ["deliver", "delivery", "ship", "address", "padala"]):
        return _clean(text)[:120]
    return None


def _extract_installation_partner(
    text: str,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Optional[str]:
    """Extract installation partner from text for fallback parsing."""

    lowered = (text or "").lower()
    if not any(
        token in lowered
        for token in ["branch", "installation partner", "install partner", "tireshakk", "roadstar", "rapide"]
    ):
        return None
    return _canonical_installation_partner(
        text,
        canonical_values_provider=canonical_values_provider,
    )


def _canonical_installation_partner(
    text: str,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Optional[str]:
    """Canonicalize installation partner with aliases and provider-backed options."""

    canonical, _metadata = _resolve_installation_partner(
        text,
        canonical_values_provider=canonical_values_provider,
    )
    return canonical


def _resolve_installation_partner(
    text: str,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> tuple[Optional[str], Dict[str, Any]]:
    """Resolve an installation partner mention without treating generic phrases as names."""

    cleaned = _clean(text)
    if not cleaned:
        return None, {}
    aliases = {
        "cubao": "TIRESHAKK (CUBAO)",
        "tireshakk cubao": "TIRESHAKK (CUBAO)",
        "roadstar": "ROADSTAR ENTERPRISES",
        "rapide": "RAPIDE",
    }
    normalized = _alnum_lower(cleaned)
    if normalized in aliases:
        return aliases[normalized], {"resolution_tier": "alias_resolved", "source": "local_alias"}
    for alias, canonical in aliases.items():
        if alias in normalized:
            return canonical, {"resolution_tier": "alias_resolved", "source": "local_alias"}
    provider_match = _canonical_from_provider_options(
        cleaned,
        canonical_values_provider.branch_names() if canonical_values_provider else [],
        transform=_clean,
        cutoff=0.72,
    )
    if provider_match:
        return provider_match, {"resolution_tier": "catalog_resolved", "source": "branch_catalog"}
    if _is_generic_installation_partner_reference(cleaned):
        return None, {
            "status": "installation_partner_generic_facility_reference",
            "resolution_tier": "generic_facility_reference",
            "source": "generic_facility_language",
        }
    return cleaned[:120], {"resolution_tier": "explicit_unresolved_name", "source": "raw_text"}


def _is_generic_installation_partner_reference(text: str) -> bool:
    """Return whether text refers to a facility category rather than a named partner."""

    lowered = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()
    if not lowered:
        return False
    tokens = lowered.split()
    facility_terms = {
        "partner",
        "partners",
        "branch",
        "branches",
        "location",
        "locations",
        "site",
        "sites",
    }
    generic_terms = facility_terms.union(
        {
            "installation",
            "install",
            "service",
            "nearest",
            "nearby",
            "closest",
            "near",
            "available",
            "any",
            "recommended",
            "suggested",
            "area",
            "me",
            "my",
            "our",
            "their",
            "sa",
            "may",
            "dito",
            "doon",
            "natin",
            "niyo",
            "ninyo",
            "nyo",
        }
    )
    if facility_terms.intersection(tokens) and all(token in generic_terms for token in tokens):
        return True
    generic_facility_patterns = [
        r"\b(nearest|nearby|closest|any|available|recommended|suggested)\b.*\b(installation partner|install partner|partner|branch|service location)\b",
        r"\b(installation partner|install partner|partner|branch|service location)\b.*\b(nearest|nearby|closest|near me|sa area|available)\b",
    ]
    return any(re.search(pattern, lowered) for pattern in generic_facility_patterns)


def _canonical_installation_partner_with_metadata(
    text: str,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> tuple[Optional[str], Dict[str, Any]]:
    """Canonicalize an explicit partner mention without selecting nearest partners."""

    canonical, resolution_metadata = _resolve_installation_partner(
        text,
        canonical_values_provider=canonical_values_provider,
    )
    if not canonical:
        return None, {}
    status = (
        "installation_partner_canonicalized"
        if canonical.strip() != _clean(text)
        else "installation_partner_captured"
    )
    return (
        canonical,
        {
            "status": status,
            "display_label": canonical,
            **resolution_metadata,
            "safe_for_action": False,
        },
    )


def _extract_branch_addons(
    text: str,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Optional[str]:
    """Extract branch addons from text for fallback parsing."""

    lowered = (text or "").lower()
    if not any(
        token in lowered
        for token in ["addon", "add-on", "alignment", "balancing", "wheel balance", "nitrogen", "camber"]
    ):
        return None
    addons = _canonical_branch_addons(
        text,
        canonical_values_provider=canonical_values_provider,
    )
    return ", ".join(addons) if addons else None


def _canonical_branch_addons(
    value: Any,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> List[str]:
    """Canonicalize branch addons with aliases and provider-backed options."""

    if isinstance(value, list):
        parts = [str(item or "") for item in value]
    else:
        parts = re.split(r"\s*(?:,|/|\||\band\b|at saka|plus)\s*", str(value or ""), flags=re.IGNORECASE)
    addons: List[str] = []
    for part in parts:
        cleaned = _clean(part)
        if not cleaned:
            continue
        local = _canonical_branch_addon_alias(cleaned)
        if local:
            addons.append(local)
            continue
        provider_match = _canonical_from_provider_options(
            cleaned,
            canonical_values_provider.branch_addon_names() if canonical_values_provider else [],
            transform=_title_clean,
            cutoff=0.78,
        )
        if provider_match:
            addons.append(provider_match)
    if not addons:
        fallback = _canonical_branch_addon_alias(str(value or ""))
        if fallback:
            addons.append(fallback)
    return _unique(addons)


def _canonical_branch_addon_alias(text: str) -> Optional[str]:
    """Canonicalize branch addon alias with aliases and provider-backed options."""

    lowered = (text or "").lower()
    if "alignment" in lowered or "align" in lowered:
        return "Wheel Alignment"
    if "balancing" in lowered or "wheel balance" in lowered:
        return "Wheel Balancing"
    if "nitrogen" in lowered or "nitro" in lowered:
        return "Nitrogen"
    if "camber" in lowered:
        return "Camber Alignment"
    return None


def _extract_payment_candidates(text: str, *, source: str) -> List[Dict[str, Any]]:
    """Extract payment candidates from text for fallback parsing."""

    lowered = (text or "").lower()
    candidates: List[Dict[str, Any]] = []
    reservation_context = any(token in lowered for token in ["reservation", "reserve", "deposit", "downpayment", "down payment"])
    balance_context = "balance" in lowered or "remaining" in lowered
    if reservation_context:
        method = _canonical_payment_method(text)
        if "gcash" in lowered:
            method = "gcash"
        if method:
            candidates.append(_candidate("reservation_payment_method", method, source=source, confidence="medium"))
    if balance_context:
        method = _canonical_payment_method(text)
        if "card" in lowered and "installment" in lowered:
            method = "credit card installment"
        if method:
            if method in {"credit card installment", "installment"} and _has_explicit_installment_terms(text):
                method = f"{method} {_installment_terms_text(text)}".strip()
            candidates.append(_candidate("balance_payment_method", method, source=source, confidence="medium"))
    if not candidates:
        methods = _extract_payment_methods(text)
        if methods:
            candidates.append(_candidate("payment_method", ", ".join(methods), source=source, confidence="medium"))
    return candidates


def _canonical_payment_method(
    text: str,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Optional[str]:
    """Canonicalize payment method with aliases and provider-backed options."""

    value, _metadata = _canonical_payment_method_with_metadata(
        text,
        key="payment_method",
        canonical_values_provider=canonical_values_provider,
    )
    return value


def _canonical_payment_option_with_metadata(
    text: str,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> tuple[Optional[str], Dict[str, Any]]:
    """Canonicalize Pay Now vs Pay Later/Pay After Service."""

    return shared_canonical_payment_option_with_metadata(
        text,
        canonical_values_provider=canonical_values_provider,
    )


def _local_canonical_payment_option(text: str) -> Optional[str]:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return None
    if "now" in lowered or "full" in lowered:
        return "Pay Now"
    if "later" in lowered or "after service" in lowered or "reservation" in lowered:
        return "Pay Later"
    return None


def _normalize_invoice_to_company(text: str) -> str:
    lowered = _clean(text).lower()
    if not lowered:
        return ""
    if lowered in {"yes", "y", "true", "oo", "opo", "company", "company invoice"}:
        return "Yes"
    if lowered in {"no", "n", "false", "hindi", "wala", "no company invoice"}:
        return "No"
    return _clean(text)[:80]


def _simple_tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def _match_checkout_payment_option(
    *,
    raw_value: str,
    local_value: Optional[str],
    payment_options: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    raw_terms = set(_simple_tokens(raw_value))
    local_terms = set(_simple_tokens(local_value or ""))
    best: Optional[Dict[str, Any]] = None
    best_score = 0
    for option in payment_options:
        text = " ".join(str(option.get(key) or "") for key in ["name", "description"])
        option_terms = set(_simple_tokens(text))
        score = len(option_terms.intersection(raw_terms)) + len(option_terms.intersection(local_terms)) * 2
        if score > best_score:
            best = option
            best_score = score
    return best if best_score > 0 else None


def _canonical_payment_method_with_metadata(
    text: str,
    *,
    key: str,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> tuple[Optional[str], Dict[str, Any]]:
    """Canonicalize payment method with metadata with aliases and provider-backed options."""

    return shared_canonical_payment_method_with_metadata(
        text,
        key=key,
        canonical_values_provider=canonical_values_provider,
    )


def _local_canonical_payment_method(text: str) -> Optional[str]:
    """Internal helper for Runtime V7 signal local canonical payment method."""

    return shared_local_canonical_payment_method(text)


def _match_checkout_payment_type(
    *,
    raw_value: str,
    local_value: Optional[str],
    key: str,
    payment_types: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Match checkout payment type against canonical metadata."""

    if not payment_types:
        return None

    candidates = list(payment_types)
    if key == "reservation_payment_method":
        pay_later_rows = [
            row for row in candidates if _int_or_none(row.get("main_payment_type_id")) == 1
        ]
        scoped = _best_payment_type_match(
            raw_value=raw_value,
            local_value=local_value,
            payment_types=pay_later_rows,
        )
        if scoped:
            return scoped

    return _best_payment_type_match(
        raw_value=raw_value,
        local_value=local_value,
        payment_types=candidates,
    )


def _best_payment_type_match(
    *,
    raw_value: str,
    local_value: Optional[str],
    payment_types: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Select the best payment type match candidate by deterministic score."""

    best_row: Optional[Dict[str, Any]] = None
    best_score = 0
    for row in payment_types:
        score = _payment_type_match_score(row, raw_value=raw_value, local_value=local_value)
        if score > best_score:
            best_score = score
            best_row = row
    return best_row if best_score >= 75 else None


def _candidate_checkout_payment_types(
    *,
    raw_value: str,
    local_value: Optional[str],
    payment_types: Sequence[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    """Internal helper for Runtime V7 signal candidate checkout payment types."""

    scored = [
        (
            _payment_type_match_score(row, raw_value=raw_value, local_value=local_value),
            row,
        )
        for row in payment_types
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for score, row in scored if score >= 75][: max(0, int(limit))]


def _payment_type_match_score(
    row: Dict[str, Any],
    *,
    raw_value: str,
    local_value: Optional[str],
) -> int:
    """Handle payment-related normalization for type match score."""

    text = _checkout_row_match_text(row)
    raw = _clean(raw_value).lower()
    local = _clean(local_value).lower()
    is_installment = _truthy(row.get("is_installment")) or "installment" in text or "0%" in text

    if local == "gcash":
        return 100 if "gcash" in text else 0
    if local == "credit card installment":
        if is_installment:
            return 100 if any(token in text for token in ["card", "credit", "debit", "cc"]) else 94
        return 0
    if local == "installment":
        return 95 if is_installment else 0
    if local == "credit card":
        if is_installment:
            return 0
        return 94 if any(token in text for token in ["credit", "debit", "card", "cc"]) else 0
    if local == "cash":
        return 90 if re.search(r"(?<!g)\bcash\b", text) else 0
    if local == "maya":
        return 90 if "maya" in text or "paymaya" in text else 0
    if local == "bank transfer":
        return 90 if "bank" in text or "transfer" in text else 0

    normalized_raw = _alnum_lower(raw)
    if normalized_raw:
        row_keys = [
            _alnum_lower(row.get("name")),
            _alnum_lower(row.get("label")),
            _alnum_lower(row.get("value")),
        ]
        if normalized_raw in row_keys:
            return 92
        if len(normalized_raw) >= 4 and any(normalized_raw in row_key for row_key in row_keys):
            return 86
        matches = get_close_matches(normalized_raw, [key for key in row_keys if key], n=1, cutoff=0.84)
        if matches:
            return 82
    return 0


def _has_explicit_installment_terms(text: str) -> bool:
    """Return whether text contains explicit installment terms language."""

    lowered = (text or "").lower()
    if re.search(r"\b\d{1,2}\s*(?:mos?|months?|month|buwan)\b", lowered):
        return True
    if re.search(r"\b\d{1,2}\s*%\b", lowered):
        return True
    return any(bank.lower() in lowered for bank in ["bpi", "bdo", "metrobank", "eastwest", "hsbc", "china bank", "chinabank"])


def _installment_terms_text(text: str) -> str:
    """Internal helper for Runtime V7 signal installment terms text."""

    lowered = (text or "").lower()
    terms: List[str] = []
    terms.extend(match.group(0) for match in re.finditer(r"\b\d{1,2}\s*(?:mos?|months?|month|buwan)\b", lowered))
    terms.extend(match.group(0) for match in re.finditer(r"\b\d{1,2}\s*%\b", lowered))
    for bank in ["BPI", "BDO", "Metrobank", "EastWest", "HSBC", "China Bank", "Chinabank"]:
        if bank.lower() in lowered:
            terms.append(bank)
    return " ".join(_unique([term.strip() for term in terms if term.strip()]))


def _checkout_row_match_text(row: Dict[str, Any]) -> str:
    """Internal helper for Runtime V7 signal checkout row match text."""

    return " ".join(
        _clean(row.get(field)).lower()
        for field in ("name", "label", "value", "payment_type", "type")
        if _clean(row.get(field))
    )


def _compact_payment_value_from_row(row: Dict[str, Any], fallback_value: str) -> str:
    """Return a compact representation of payment value from row."""

    fallback = _clean(fallback_value).lower()
    if fallback in {
        "gcash",
        "credit card",
        "credit card installment",
        "installment",
        "cash",
        "maya",
        "bank transfer",
    }:
        return fallback

    text = _checkout_row_match_text(row)
    if _truthy(row.get("is_installment")) or "installment" in text:
        return "credit card installment" if any(token in text for token in ["card", "credit", "debit", "cc"]) else "installment"
    if "gcash" in text:
        return "gcash"
    if "maya" in text or "paymaya" in text:
        return "maya"
    if "bank" in text:
        return "bank transfer"
    if any(token in text for token in ["credit", "debit", "card", "cc"]):
        return "credit card"
    if re.search(r"(?<!g)\bcash\b", text):
        return "cash"
    return _clean(row.get("label") or row.get("name") or row.get("value")).lower()


def _payment_option_for_type(
    payment_type: Dict[str, Any],
    payment_options: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Handle payment-related normalization for option for type."""

    option_id = _int_or_none(payment_type.get("main_payment_type_id"))
    if option_id is None:
        return None
    for option in payment_options:
        if _int_or_none(option.get("id")) == option_id:
            return option
    return None


def _compact_checkout_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a compact representation of checkout row."""

    if not row:
        return None
    return {
        key: row.get(key)
        for key in (
            "id",
            "main_payment_type_id",
            "name",
            "label",
            "value",
            "description",
            "is_installment",
            "direct_payment",
        )
        if row.get(key) not in (None, "")
    }


def _int_or_none(value: Any) -> Optional[int]:
    """Coerce a value to int when possible without raising."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    """Normalize common truthy payload values to a boolean."""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _extract_payment_methods(text: str) -> List[str]:
    """Extract payment methods from text for fallback parsing."""

    lowered = (text or "").lower()
    methods: List[str] = []
    if "credit card" in lowered or "card" in lowered:
        if "installment" in lowered or "installments" in lowered:
            methods.append("credit card installment")
        else:
            methods.append("credit card")
    elif "installment" in lowered or "installments" in lowered:
        methods.append("installment")
    if "gcash" in lowered:
        methods.append("gcash")
    if re.search(r"\bcash\b", lowered):
        methods.append("cash")
    return _unique(methods)


def _extract_name(text: str) -> Dict[str, str]:
    """Extract name from text for fallback parsing."""

    match = re.search(r"\b(?:name is|ako si|this is)\s+([A-Za-z]+)(?:\s+([A-Za-z]+))?\b", text or "", flags=re.IGNORECASE)
    if not match:
        return {}
    output = {"first_name": match.group(1).title()}
    if match.group(2):
        output["last_name"] = match.group(2).title()
    return output


def _extract_email(text: str) -> Optional[str]:
    """Extract email from text for fallback parsing."""

    match = re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text or "", flags=re.IGNORECASE)
    return match.group(0).lower() if match else None


def _has_order_confirmation(text: str) -> bool:
    """Return whether text contains order confirmation language."""

    lowered = (text or "").lower()
    return any(token in lowered for token in ["confirm order", "order confirmed", "go na", "proceed with order"])


def _has_confirmation_language(text: str) -> bool:
    """Return whether text contains confirmation language language."""

    lowered = (text or "").lower()
    return any(token in lowered for token in ["confirmed", "confirm", "sure", "final", "yan na"])


def _has_uncertain_size_language(text: str) -> bool:
    """Return whether text contains uncertain size language language."""

    lowered = (text or "").lower()
    has_current_size = any(token in lowered for token in ["current tire", "current size", "currently installed", "installed tire"])
    has_uncertainty = any(token in lowered for token in ["not sure", "di ko sure", "hindi sure", "not original", "original size"])
    return has_current_size and has_uncertainty


def _has_additive_value_language(text: str) -> bool:
    """Return whether text contains additive value language language."""

    lowered = (text or "").lower()
    return any(
        token in lowered
        for token in [
            "also",
            "additional",
            "add another",
            "another car",
            "second car",
            "other car",
            "pati",
            "isa pa",
            "plus",
        ]
    )


def _refers_to_older_context(text: str) -> bool:
    """Internal helper for Runtime V7 signal refers to older context."""

    lowered = (text or "").lower()
    return any(
        token in lowered
        for token in [
            "same as before",
            "same previous",
            "same as last",
            "previous",
            "earlier",
            "last time",
            "yung kanina",
            "yun kanina",
        ]
    )


def _looks_commercial(text: str) -> bool:
    """Internal helper for Runtime V7 signal looks commercial."""

    lowered = (text or "").lower()
    if _extract_tire_sizes(text) or _extract_rim_size(text):
        return True
    return any(
        token in lowered
        for token in [
            "hm",
            "how much",
            "price",
            "quote",
            "available",
            "meron",
            "may ",
            "gulong",
            "tire",
            "tires",
            "brand",
            "budget",
            "promo",
            "installment",
            "gcash",
            "reservation",
            "order",
            "deliver",
            "delivery",
            "branch",
            "schedule",
            "slot",
        ]
    )


def _has_semantic_reference_terms(text: str) -> bool:
    """Return whether text contains semantic reference terms language."""

    lowered = (text or "").lower()
    return any(
        token in lowered
        for token in [
            "yun una",
            "yung una",
            "first one",
            "1st one",
            "same as before",
            "same previous",
            "same as last",
            "previous",
            "earlier",
            "last time",
            "yung kanina",
            "yun kanina",
            "that one",
            "ito",
            "iyan",
        ]
    )


def _has_correction_terms(text: str) -> bool:
    """Return whether text contains correction terms language."""

    lowered = (text or "").lower()
    return any(
        token in lowered
        for token in [
            "change to",
            "palit",
            "instead",
            "actually",
            "hindi yan",
            "not that",
            "final size",
            "confirmed na",
            "correction",
            "mali",
        ]
    )


def _has_product_reference_terms(text: str) -> bool:
    """Return whether text contains product reference terms language."""

    lowered = (text or "").lower()
    return any(
        token in lowered
        for token in [
            "yun una",
            "yung una",
            "first one",
            "1st one",
            "second one",
            "premium option",
            "budget option",
            "best option",
            "that option",
            "that one",
            "ito",
            "iyan",
        ]
    )


def _has_brand_preference_language(text: str) -> bool:
    """Return whether text contains brand preference language language."""

    lowered = (text or "").lower()
    if "brand" in lowered or "prefer" in lowered or "preferred" in lowered:
        return True
    return any(token in lowered for token in [" sana", " ok din", "or ", " o kaya", "kahit"])


def _has_payment_language(text: str) -> bool:
    """Return whether text contains payment language language."""

    lowered = (text or "").lower()
    return any(
        token in lowered
        for token in [
            "payment",
            "pay",
            "gcash",
            "cash",
            "card",
            "installment",
            "reservation",
            "deposit",
            "balance",
            "bank",
        ]
    )


def _has_branch_or_location_language(text: str) -> bool:
    """Return whether text contains branch or location language language."""

    lowered = (text or "").lower()
    return any(
        re.search(pattern, lowered)
        for pattern in [
            r"\bbranch\b",
            r"\blocation\b",
            r"\barea\b",
            r"\bnear\b",
            r"\btaga\b",
            r"\bnasa\b",
            r"\bqc\b",
            r"\bcity\b",
            r"\bprovince\b",
            r"\binstallation partner\b",
            r"\binstall partner\b",
        ]
    )


def _has_vehicle_or_multi_car_language(text: str) -> bool:
    """Return whether text contains vehicle or multi car language language."""

    lowered = (text or "").lower()
    return any(
        token in lowered
        for token in [
            "wigo",
            "vios",
            "toyota",
            "honda",
            "mitsubishi",
            "nissan",
            "suzuki",
            "ford",
            "hyundai",
            "kia",
            "mazda",
            "isuzu",
            "car",
            "cars",
            "sasakyan",
            "other car",
            "another car",
            "second car",
        ]
    )


def _clean(value: Any) -> str:
    """Collapse whitespace and coerce optional values to clean text."""

    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_unfilled_order_form_placeholder(text: str) -> bool:
    cleaned = _clean(text)
    if not cleaned or cleaned == "-":
        return True
    normalized = _alnum_lower(cleaned.strip("[]() "))
    return normalized in _UNFILLED_ORDER_FORM_PLACEHOLDER_KEYS


_UNFILLED_ORDER_FORM_PLACEHOLDER_KEYS = {
    "optional",
    "neededbeforesubmit",
    "toconfirm",
    "tofillin",
    "name",
    "mobilenumber",
    "selectedtire",
    "tiresize",
    "quantity",
    "deliveryinstallationpickup",
    "completedeliveryaddress",
    "pickupbranch",
    "completeserviceaddress",
    "areacity",
    "installationpartner",
    "preferreddatetime",
    "paynowpayafterservice",
    "gcashcashcard",
    "yesno",
    "paymentmethod",
}


def _alnum_lower(value: Any) -> str:
    """Build a lowercase alphanumeric key for fuzzy matching."""

    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _title_clean(value: Any) -> str:
    """Clean text and return title-cased display form."""

    text = _clean(value)
    return text.title() if text else ""


def _canonical_from_provider_options(
    value: Any,
    options: Sequence[str],
    *,
    transform,
    cutoff: float,
) -> Optional[str]:
    """Canonicalize from provider options with aliases and provider-backed options."""

    normalized = _alnum_lower(value)
    if not normalized or not options:
        return None
    option_map = {
        _alnum_lower(option): transform(option)
        for option in options
        if _alnum_lower(option)
    }
    if normalized in option_map:
        return option_map[normalized]
    for key, option in option_map.items():
        if len(normalized) >= 4 and normalized in key:
            return option
        if len(key) >= 4 and key in normalized:
            return option
    matches = get_close_matches(normalized, list(option_map.keys()), n=1, cutoff=cutoff)
    return option_map[matches[0]] if matches else None


def _last(values: Sequence[str]) -> Optional[str]:
    """Return the last value from a sequence when present."""

    return values[-1] if values else None


def _unique(values: Sequence[str]) -> List[str]:
    """Return ordered unique strings without changing first-seen order."""

    seen: set[str] = set()
    output: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
