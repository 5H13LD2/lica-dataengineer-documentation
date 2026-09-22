"""Capability-surface compiler for Runtime V7 model turns.

This module maps normalized state/evidence into a safe tool surface. It does not
classify exact customer intent. Candidate tools are matched from normalized
signals, FAQ hints, and trusted context refs; selected domains are then derived
from those tools so the prompt compiler can load only relevant domain guidance.
Raw customer prose and Active Working Memory never authorize a tool or select a
domain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from runtime_v7.tool_capabilities import (
    ORDER_ENTRY_TOOL_NAMES,
    PRODUCT_ENTRY_TOOL_NAMES,
    SERVICE_ENTRY_TOOL_NAMES,
    TOOL_CAPABILITIES,
    ToolCapability,
)
from runtime_v7.state_signal_schema import (
    signal_has_durable_authority,
    signal_is_lookup_only_evidence,
)


@dataclass
class CapabilityProfile:
    """Diagnostics and final tool surface for a model turn."""

    candidate_tools: List[str] = field(default_factory=list)
    selected_domains: List[str] = field(default_factory=list)
    exposed_tools: List[str] = field(default_factory=list)
    matched_signal_keys: Dict[str, List[str]] = field(default_factory=dict)
    matched_refs: Dict[str, List[str]] = field(default_factory=dict)
    available_context_refs: Dict[str, bool] = field(default_factory=dict)
    faq_hints: List[Dict[str, Any]] = field(default_factory=list)
    order_readiness: Dict[str, Any] = field(default_factory=dict)
    advisory_cues: List[Dict[str, Any]] = field(default_factory=list)
    ambiguity_expanded: bool = False
    request_capability_used: bool = False
    selection_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable diagnostics payload."""

        return {
            "candidate_tools": list(self.candidate_tools),
            "selected_domains": list(self.selected_domains),
            "exposed_tools": list(self.exposed_tools),
            "matched_signal_keys": {key: list(value) for key, value in self.matched_signal_keys.items()},
            "matched_refs": {key: list(value) for key, value in self.matched_refs.items()},
            "available_context_refs": dict(self.available_context_refs),
            "faq_hints": list(self.faq_hints),
            "order_readiness": dict(self.order_readiness),
            "advisory_cues": list(self.advisory_cues),
            "ambiguity_expanded": bool(self.ambiguity_expanded),
            "request_capability_used": bool(self.request_capability_used),
            "selection_reasons": list(self.selection_reasons),
        }


def build_capability_profile(
    *,
    current_user_message: str,
    active_working_memory: str = "",
    background_signals: Optional[Sequence[Dict[str, Any]]] = None,
    external_evidence_refs: Optional[Sequence[Dict[str, Any]]] = None,
    product_observation_headers: Optional[Sequence[Dict[str, Any]]] = None,
    service_observation_headers: Optional[Sequence[Dict[str, Any]]] = None,
    order_summary_refs: Optional[Sequence[str]] = None,
    order_payload_refs: Optional[Sequence[str]] = None,
    payment_request_refs: Optional[Sequence[str]] = None,
    faq_hints: Optional[Sequence[Dict[str, Any]]] = None,
    order_readiness: Optional[Dict[str, Any]] = None,
    guided_location_optional_reoffer_suppressed: bool = False,
    default_domains: Sequence[str] = (),
    requested_domains: Sequence[str] = (),
    registry: Mapping[str, ToolCapability] = TOOL_CAPABILITIES,
) -> CapabilityProfile:
    """Compile candidate tools, selected domains, and exposed tool schemas.

    `default_domains` is a compatibility lever for isolated slices. Product-only
    probes can pass `("product",)`, while the production full-runtime shape
    should pass an empty sequence and rely on signals, refs, FAQ hints, and
    request_capability recovery.
    """

    signals = list(background_signals or [])
    refs = list(external_evidence_refs or [])
    headers = list(product_observation_headers or [])
    hints = [dict(hint) for hint in faq_hints or [] if isinstance(hint, dict)]
    readiness = dict(order_readiness or {}) if isinstance(order_readiness, dict) else {}
    signal_keys = _signal_keys(signals)
    lookup_signal_keys = _lookup_only_signal_keys(signals)
    service_headers = list(service_observation_headers or [])
    summary_refs = [str(ref).strip() for ref in order_summary_refs or [] if str(ref).strip()]
    payload_refs = [str(ref).strip() for ref in order_payload_refs or [] if str(ref).strip()]
    payment_refs = [str(ref).strip() for ref in payment_request_refs or [] if str(ref).strip()]
    context_refs = _context_refs(
        product_observation_headers=headers,
        service_observation_headers=service_headers,
        order_summary_refs=summary_refs,
        order_payload_refs=payload_refs,
        payment_request_refs=payment_refs,
    )
    profile = CapabilityProfile(
        available_context_refs=context_refs,
        faq_hints=hints,
        order_readiness=_compact_order_readiness(readiness),
    )

    for capability in registry.values():
        if capability.name == "request_capability":
            continue
        allowed_keys = set(signal_keys)
        if capability.action_kind == "read":
            allowed_keys.update(lookup_signal_keys)
        matched_keys = sorted(set(capability.useful_signal_keys).intersection(allowed_keys))
        if matched_keys:
            _add_candidate(profile, capability.name, f"signals:{','.join(matched_keys)}")
            profile.matched_signal_keys[capability.name] = matched_keys

    _match_guided_service_location_choice(
        profile,
        signals,
        durable_signal_keys=signal_keys,
        has_delivered_product_presentation=any(
            str(header.get("presentation_ref") or "").strip()
            and int(header.get("card_count") or 0) > 0
            and header.get("presentation_delivered") is True
            for header in headers
            if isinstance(header, dict)
        ),
        optional_reoffer_suppressed=guided_location_optional_reoffer_suppressed,
        registry=registry,
    )

    _match_external_evidence(profile, refs, registry=registry)
    # Preserve FAQ hints as retrieval telemetry only. They must not choose a
    # domain or expose/withhold schemas for the main model.
    _match_product_refs_and_message(profile, current_user_message=current_user_message, product_headers=headers)
    _match_order_readiness(profile, readiness, current_user_message=current_user_message, registry=registry)
    _match_order_payload_refs(profile, readiness, current_user_message=current_user_message, registry=registry)
    _match_payment_request_refs(profile, registry=registry)
    candidate_before_default = list(profile.candidate_tools)
    domains = _domains_for_tools(candidate_before_default, registry)
    for domain in _valid_requested_domains(requested_domains, registry):
        if domain not in domains:
            domains.append(domain)
            profile.selection_reasons.append(f"requested_domain:{domain}")
    if not domains and default_domains:
        domains = sorted(set(default_domains))
        profile.ambiguity_expanded = True
        profile.selection_reasons.append("default_domains:" + ",".join(domains))

    profile.selected_domains = domains
    profile.exposed_tools = _exposed_tools_for_domains(
        domains=domains,
        context_refs=context_refs,
        order_readiness=readiness,
        candidate_tools=profile.candidate_tools,
        requested_domains=requested_domains,
        registry=registry,
    )
    for capability in registry.values():
        if capability.domain == "general" and capability.name != "request_capability":
            _append_unique(profile.exposed_tools, capability.name)
    if "request_capability" in registry:
        _append_unique(profile.exposed_tools, "request_capability")
    return profile


def _signal_keys(signals: Sequence[Dict[str, Any]]) -> set[str]:
    """Return capability-bearing signal keys after structural validation.

    In particular, a model-proposed location noun is not enough to expose
    concrete service lookups. Location must carry a resolved geographic hint
    or precision; broad location meaning remains with the main model and its
    general routing capability.
    """

    keys: set[str] = set()
    for signal in signals:
        if not isinstance(signal, dict) or not signal_has_durable_authority(signal):
            continue
        key = str(signal.get("key") or "").strip()
        value = signal.get("value")
        if key == "location" and not _location_signal_has_resolved_place(
            signal
        ):
            continue
        if key and value not in (None, "", []):
            keys.add(key)
    return keys


def _lookup_only_signal_keys(signals: Sequence[Dict[str, Any]]) -> set[str]:
    """Return provisional evidence keys that may expose read-only validators."""

    return {
        str(signal.get("key") or "").strip()
        for signal in signals or []
        if isinstance(signal, dict)
        and signal_is_lookup_only_evidence(signal)
        and str(signal.get("key") or "").strip()
        and signal.get("value") not in (None, "", [], {})
    }


def _location_signal_has_resolved_place(signal: Mapping[str, Any]) -> bool:
    """Return whether normalized metadata identifies an actual place."""

    resolution = (
        signal.get("resolution")
        if isinstance(signal.get("resolution"), Mapping)
        else {}
    )
    metadata = (
        signal.get("metadata")
        if isinstance(signal.get("metadata"), Mapping)
        else {}
    )
    normalization = (
        metadata.get("normalization")
        if isinstance(metadata.get("normalization"), Mapping)
        else {}
    )
    normalized = (
        normalization.get("location_resolution")
        if isinstance(
            normalization.get("location_resolution"),
            Mapping,
        )
        else {}
    )
    if str(resolution.get("status") or "").strip() == "ambiguous_location":
        return False
    if str(normalization.get("status") or "").strip() == "location_ambiguous":
        return False
    if resolution.get("ambiguity_reason") or normalized.get("ambiguity_status"):
        return False
    return any(
        str(
            resolution.get(key)
            or normalized.get(key)
            or ""
        ).strip()
        for key in (
            "city_hint",
            "province_hint",
            "landmark_hint",
            "location_precision",
        )
    )


def _match_guided_service_location_choice(
    profile: CapabilityProfile,
    signals: Sequence[Dict[str, Any]],
    *,
    durable_signal_keys: set[str],
    has_delivered_product_presentation: bool,
    optional_reoffer_suppressed: bool,
    registry: Mapping[str, ToolCapability],
) -> None:
    """Expose unresolved location as an optional post-product guided move.

    The candidate is advisory: the main model still chooses the next useful
    action from the conversation, while execution guards reject delivery and
    already-resolved location states. A delivered product presentation is the
    minimum non-service signal because it proves that useful product help was
    customer-visible on an earlier turn; a hidden observation is insufficient.
    """

    tool_name = "present_serviceable_location_choices"
    if tool_name not in registry:
        return
    signal_map = {
        str(signal.get("key") or "").strip(): signal
        for signal in signals
        if isinstance(signal, dict) and str(signal.get("key") or "").strip()
    }
    service_type = str(
        (signal_map.get("service_type") or {}).get("value") or ""
    ).strip().casefold()
    active_installation = (
        "service_type" in durable_signal_keys
        and service_type == "installation"
    )
    if service_type == "delivery":
        return
    if (
        optional_reoffer_suppressed
        and not active_installation
        and has_delivered_product_presentation
    ):
        profile.selection_reasons.append(
            "present_serviceable_location_choices:"
            "deferred:prior_location_surface_or_action"
        )
        return
    if (
        not active_installation
        and not has_delivered_product_presentation
    ) or "delivery_address" in durable_signal_keys:
        return
    location_signal = signal_map.get("location") or {}
    if (
        "location" in durable_signal_keys
        and _location_signal_has_resolved_place(location_signal)
    ):
        return
    reason = (
        "active_installation_without_usable_service_location"
        if active_installation
        else "delivered_product_help_without_usable_service_location"
    )
    _add_candidate(profile, tool_name, reason)


def _context_refs(
    *,
    product_observation_headers: Sequence[Dict[str, Any]],
    service_observation_headers: Sequence[Dict[str, Any]],
    order_summary_refs: Sequence[str] = (),
    order_payload_refs: Sequence[str] = (),
    payment_request_refs: Sequence[str] = (),
) -> Dict[str, bool]:
    headers = [header for header in product_observation_headers if isinstance(header, dict)]
    service_headers = [header for header in service_observation_headers if isinstance(header, dict)]
    has_product_observation = any(str(header.get("observation_ref") or "").strip() for header in headers)
    has_product_presentation = any(
        str(header.get("presentation_ref") or "").strip()
        and int(header.get("card_count") or 0) > 0
        and header.get("presentation_delivered") is not False
        for header in headers
    )
    has_service_observation = any(str(header.get("observation_ref") or "").strip() for header in service_headers)
    has_service_location = any(header.get("service_location_refs") for header in service_headers)
    has_validated_service_slot = any(
        str(header.get("availability_status") or "").strip().lower() == "slot_validated"
        for header in service_headers
    )
    return {
        "product_observation": bool(has_product_observation),
        "product_presentation": bool(has_product_presentation),
        "service_observation": bool(has_service_observation),
        "service_location": bool(has_service_location),
        "validated_service_slot": bool(has_validated_service_slot),
        "order_summary": bool(order_summary_refs),
        "order_payload": bool(order_payload_refs),
        "payment_request": bool(payment_request_refs),
    }


def _match_external_evidence(
    profile: CapabilityProfile,
    refs: Sequence[Dict[str, Any]],
    *,
    registry: Mapping[str, ToolCapability],
) -> None:
    for ref in refs:
        image_type = str(ref.get("image_type") or "").strip().lower()
        fields = ref.get("extracted_fields") if isinstance(ref.get("extracted_fields"), list) else []
        field_text = " ".join(str(field).lower() for field in fields)
        if image_type == "payment_proof":
            if "match_payment_proof" in registry:
                _add_candidate(profile, "match_payment_proof", "external_evidence:payment_proof")
            _add_advisory_cue(profile, domain="order", source="external_evidence", evidence=image_type)
        if image_type in {"tire", "website_product_card", "product_page", "conversation_screenshot"}:
            _add_advisory_cue(profile, domain="product", source="external_evidence", evidence=image_type)
        if any(token in field_text for token in ["tire_size=", "tire_brand=", "product_title=", "tire_model="]):
            _add_advisory_cue(profile, domain="product", source="external_evidence", evidence="product_field")
        if any(
            token in field_text
            for token in [
                "service_location=",
                "installation_partner=",
                "schedule_text=",
                "branch_addons=",
            ]
        ):
            _add_advisory_cue(profile, domain="service", source="external_evidence", evidence="service_field")


def _match_product_refs_and_message(
    profile: CapabilityProfile,
    *,
    current_user_message: str,
    product_headers: Sequence[Dict[str, Any]],
) -> None:
    if not profile.available_context_refs.get("product_presentation"):
        return
    # A delivered product presentation is objective authority for reference
    # resolution. Keep the tools available and let the model decide whether the
    # latest turn refers to one of those products; do not infer that from phrases.
    _add_candidate(profile, "resolve_product_reference", "product_refs_available")
    _add_candidate(profile, "get_product_details", "product_refs_available")
    profile.matched_refs["resolve_product_reference"] = ["product_presentation"]
    profile.matched_refs["get_product_details"] = ["product_presentation"]
    if product_headers:
        profile.selection_reasons.append("product_refs_available")


def _match_order_readiness(
    profile: CapabilityProfile,
    readiness: Dict[str, Any],
    *,
    current_user_message: str,
    registry: Mapping[str, ToolCapability],
) -> None:
    """Expose order-domain read tools when readiness shows order movement."""

    if not isinstance(readiness, dict) or not readiness:
        return
    status = str(readiness.get("status") or "unknown").strip() or "unknown"
    intent = str(readiness.get("customer_order_intent") or "none").strip() or "none"
    if "calculate_order_quote" in registry and _readiness_supports_order_quote(readiness):
        _add_candidate(profile, "calculate_order_quote", f"order_readiness:{status}:{intent}")
    summary_added = False
    if "build_order_summary" in registry and _readiness_supports_order_summary(readiness):
        _add_candidate(profile, "build_order_summary", f"order_readiness:{status}:{intent}")
        summary_added = True
    if (
        "build_order_payload" in registry
        and profile.available_context_refs.get("order_summary")
        and _readiness_supports_order_payload(readiness)
    ):
        if not _readiness_requires_validated_slot(readiness) or profile.available_context_refs.get("validated_service_slot"):
            _add_candidate(profile, "build_order_payload", f"order_readiness:{status}:{intent}")
        else:
            profile.selection_reasons.append("build_order_payload:deferred:validated_service_slot_required")
    if (
        not summary_added
        and "build_order_summary" in registry
        and profile.available_context_refs.get("order_summary")
        and _readiness_supports_existing_order_summary_rebuild(readiness)
    ):
        _add_candidate(profile, "build_order_summary", f"existing_order_summary:{status}:{intent}")
    if (
        not summary_added
        and "build_order_summary" in registry
        and profile.available_context_refs.get("product_presentation")
        and _readiness_has_product_options_only(readiness)
    ):
        _add_candidate(
            profile,
            "build_order_summary",
            "product_presentation_order_summary_available",
        )


def _match_order_payload_refs(
    profile: CapabilityProfile,
    readiness: Dict[str, Any],
    *,
    current_user_message: str,
    registry: Mapping[str, ToolCapability],
) -> None:
    """Expose order submit only when a validated payload ref exists."""

    if "submit_order" not in registry or not profile.available_context_refs.get("order_payload"):
        return
    _add_candidate(profile, "submit_order", "validated_order_payload_ref")
    if "prepare_payment_request" in registry:
        _add_candidate(profile, "prepare_payment_request", "validated_order_payload_ref")
    if "get_order_details" in registry:
        _add_candidate(profile, "get_order_details", "post_submit_readback_available")


def _match_payment_request_refs(
    profile: CapabilityProfile,
    *,
    registry: Mapping[str, ToolCapability],
) -> None:
    """Expose safe payment helpers from a trusted payment-request reference."""

    if not profile.available_context_refs.get("payment_request"):
        return
    if "prepare_payment_request" in registry:
        _add_candidate(profile, "prepare_payment_request", "payment_request_ref")
    if "get_order_details" in registry:
        _add_candidate(profile, "get_order_details", "payment_request_ref")


def _readiness_supports_order_domain(readiness: Dict[str, Any]) -> bool:
    if not isinstance(readiness, dict) or not readiness:
        return False
    status = str(readiness.get("status") or "").strip().lower()
    collected = readiness.get("collected") if isinstance(readiness.get("collected"), dict) else {}
    has_product_context = bool(
        readiness.get("can_prepare_order_summary")
        or collected.get("Product")
        or collected.get("Trusted total")
    )
    if not has_product_context:
        return False
    return status in {"incomplete", "ready_for_summary"}


def _readiness_supports_order_quote(readiness: Dict[str, Any]) -> bool:
    if not _readiness_supports_order_domain(readiness):
        return False
    if readiness.get("can_prepare_order_summary"):
        return True
    collected = readiness.get("collected") if isinstance(readiness.get("collected"), dict) else {}
    return bool(collected.get("Product") and (collected.get("Trusted total") or collected.get("Quantity")))


def _readiness_supports_order_summary(readiness: Dict[str, Any]) -> bool:
    if not _readiness_supports_order_domain(readiness):
        return False
    if _readiness_has_missing_validated_service_slot(readiness):
        return False
    if readiness.get("can_prepare_order_summary"):
        return True
    collected = readiness.get("collected") if isinstance(readiness.get("collected"), dict) else {}
    return bool(
        collected.get("Product") or collected.get("Trusted total")
    )


def _readiness_has_missing_validated_service_slot(readiness: Dict[str, Any]) -> bool:
    missing = readiness.get("missing") if isinstance(readiness.get("missing"), list) else []
    return any(str(item or "").strip().lower() == "validated installation schedule" for item in missing)


def _readiness_supports_existing_order_summary_rebuild(readiness: Dict[str, Any]) -> bool:
    """Allow read-only summary rebuilds after a deterministic summary exists."""

    if not _readiness_supports_order_domain(readiness):
        return False
    status = str(readiness.get("status") or "").strip().lower()
    if status not in {"incomplete", "ready_for_summary"}:
        return False
    collected = readiness.get("collected") if isinstance(readiness.get("collected"), dict) else {}
    return bool(collected.get("Product") or collected.get("Trusted total") or readiness.get("can_prepare_order_summary"))


def _readiness_supports_order_payload(readiness: Dict[str, Any]) -> bool:
    """Expose payload validation only after selected-product order context exists."""

    if not _readiness_supports_order_domain(readiness):
        return False
    collected = readiness.get("collected") if isinstance(readiness.get("collected"), dict) else {}
    return bool(readiness.get("can_prepare_order_summary") or collected.get("Product"))


def _readiness_requires_validated_slot(readiness: Dict[str, Any]) -> bool:
    collected = readiness.get("collected") if isinstance(readiness.get("collected"), dict) else {}
    fulfillment = str(collected.get("Fulfillment") or "").strip().lower()
    return any(term in fulfillment for term in ("installation", "pickup", "home service"))


def _readiness_has_product_options_only(readiness: Dict[str, Any]) -> bool:
    collected = readiness.get("collected") if isinstance(readiness.get("collected"), dict) else {}
    return bool(collected.get("Product options") and not collected.get("Product") and not collected.get("Trusted total"))


def _readiness_has_existing_order_context(readiness: Dict[str, Any]) -> bool:
    collected = readiness.get("collected") if isinstance(readiness.get("collected"), dict) else {}
    text = " ".join(f"{key} {value}" for key, value in collected.items()).lower()
    return any(
        token in text
        for token in [
            "existing order",
            "order id",
            "order no",
            "order number",
            "order url",
            "website order",
            "already purchased",
            "purchased through the website",
        ]
    )


def _compact_order_readiness(readiness: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(readiness, dict) or not readiness:
        return {}
    output = {
        "status": readiness.get("status"),
        "customer_order_intent": readiness.get("customer_order_intent"),
        "can_prepare_order_summary": bool(readiness.get("can_prepare_order_summary")),
    }
    high_intent = readiness.get("high_intent_signals")
    if isinstance(high_intent, list) and high_intent:
        output["high_intent_signals"] = [str(item) for item in high_intent[:4] if str(item).strip()]
    missing = readiness.get("missing")
    if isinstance(missing, list) and missing:
        output["missing_count"] = len(missing)
    schedule_status = str(readiness.get("schedule_status") or "").strip()
    if schedule_status:
        output["schedule_status"] = schedule_status
    submission_blockers = readiness.get("submission_blockers")
    if isinstance(submission_blockers, list) and submission_blockers:
        output["submission_blocker_count"] = len(submission_blockers)
    return {key: value for key, value in output.items() if value not in (None, "", [])}


def _domains_for_tools(tool_names: Sequence[str], registry: Mapping[str, ToolCapability]) -> List[str]:
    domains = {
        registry[name].domain
        for name in tool_names
        if name in registry and registry[name].domain != "general"
    }
    return sorted(domains)


def _exposed_tools_for_domains(
    *,
    domains: Sequence[str],
    context_refs: Mapping[str, bool],
    order_readiness: Mapping[str, Any],
    candidate_tools: Sequence[str],
    requested_domains: Sequence[str],
    registry: Mapping[str, ToolCapability],
) -> List[str]:
    exposed: List[str] = []
    requested_domain_set = set(_valid_requested_domains(requested_domains, registry))
    for domain in domains:
        if domain == "product":
            for tool_name in _product_entry_tools_for_context():
                if tool_name in registry:
                    _append_unique(exposed, tool_name)
        if domain == "service":
            for tool_name in SERVICE_ENTRY_TOOL_NAMES:
                if tool_name in registry:
                    _append_unique(exposed, tool_name)
        if domain == "order":
            for tool_name in _order_entry_tools_for_context(
                readiness=order_readiness,
                candidate_tools=candidate_tools,
                context_refs=context_refs,
                force_order_faq="order" in requested_domain_set,
            ):
                if tool_name in registry:
                    _append_unique(exposed, tool_name)
        for capability in registry.values():
            if capability.domain != domain or capability.action_kind != "read":
                continue
            if (
                capability.name in PRODUCT_ENTRY_TOOL_NAMES
                or capability.name in SERVICE_ENTRY_TOOL_NAMES
                or capability.name in ORDER_ENTRY_TOOL_NAMES
            ):
                continue
            if capability.requires_context_refs and not all(context_refs.get(ref) for ref in capability.requires_context_refs):
                continue
            _append_unique(exposed, capability.name)
    return exposed


def _product_entry_tools_for_context() -> List[str]:
    """Return the complete read-only product discovery surface.

    Candidate matches establish that the product domain is relevant; they do
    not prescribe a sequence of lookups.  A customer may ask for fitment,
    brands, promos, or a product comparison while the exact wording or the
    available typed context changes across turns.  Keeping the safe read-only
    surface available lets the model choose the appropriate lookup without a
    phrase- or stage-based veto.  Tool argument validation remains the source
    of truth for any concrete search.
    """

    return list(PRODUCT_ENTRY_TOOL_NAMES)


def _order_entry_tools_for_context(
    *,
    readiness: Mapping[str, Any],
    candidate_tools: Sequence[str],
    context_refs: Mapping[str, bool],
    force_order_faq: bool = False,
) -> List[str]:
    candidates = set(candidate_tools or [])
    readiness_dict = dict(readiness or {})
    payload_builder_available = (
        "build_order_payload" in candidates
        and bool((context_refs or {}).get("order_summary"))
        and _readiness_supports_order_payload(readiness_dict)
        and (
            not _readiness_requires_validated_slot(readiness_dict)
            or bool((context_refs or {}).get("validated_service_slot"))
        )
    )
    output: List[str] = []

    def add(tool_name: str) -> None:
        if tool_name not in output:
            output.append(tool_name)

    payment_action_candidate = "match_payment_proof" in candidates or "prepare_payment_request" in candidates
    if "match_payment_proof" in candidates:
        add("match_payment_proof")
    if "prepare_payment_request" in candidates:
        add("prepare_payment_request")
    if (
        force_order_faq
        or "answer_order_faq" in candidates
        or not candidates
    ) and not payment_action_candidate:
        add("answer_order_faq")
    if "calculate_order_quote" in candidates and _readiness_supports_order_quote(readiness_dict):
        add("calculate_order_quote")
    if "build_order_summary" in candidates:
        add("build_order_summary")
    if payload_builder_available:
        add("build_order_payload")
    if "submit_order" in candidates:
        add("submit_order")
    if "prepare_payment_request" in candidates:
        add("prepare_payment_request")
    if "get_order_details" in candidates:
        add("get_order_details")
    return output


def _add_candidate(profile: CapabilityProfile, tool_name: str, reason: str) -> None:
    _append_unique(profile.candidate_tools, tool_name)
    if reason:
        profile.selection_reasons.append(f"{tool_name}:{reason}")


def _remove_candidate(profile: CapabilityProfile, tool_name: str) -> None:
    profile.candidate_tools = [name for name in profile.candidate_tools if name != tool_name]
    profile.matched_signal_keys.pop(tool_name, None)
    profile.matched_refs.pop(tool_name, None)
    profile.selection_reasons = [
        reason for reason in profile.selection_reasons if not reason.startswith(f"{tool_name}:")
    ]


def _add_advisory_cue(profile: CapabilityProfile, *, domain: str, source: str, evidence: str) -> None:
    cue = {
        "domain": str(domain or "").strip().lower(),
        "source": str(source or "").strip(),
        "evidence": str(evidence or "").strip(),
        "note": "advisory_only_not_tool_exposure",
    }
    if not cue["domain"] or not cue["source"]:
        return
    if cue not in profile.advisory_cues:
        profile.advisory_cues.append(cue)


def _append_unique(items: List[str], item: str) -> None:
    if item not in items:
        items.append(item)


def _valid_requested_domains(
    domains: Sequence[str],
    registry: Mapping[str, ToolCapability],
) -> List[str]:
    available_domains = {capability.domain for capability in registry.values() if capability.domain != "general"}
    output: List[str] = []
    for domain in domains or []:
        normalized = str(domain or "").strip().lower()
        if normalized in available_domains and normalized not in output:
            output.append(normalized)
    return output
