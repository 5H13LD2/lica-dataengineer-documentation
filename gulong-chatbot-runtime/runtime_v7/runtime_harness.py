"""Runtime V7 tool-loop harness for product and service probes.

This module is intentionally narrow. It exercises the model-facing context,
tool-call contract, product-search runner, product-card presentation, and
cross-turn observations without pulling in the full customer-service runtime.
"""

from __future__ import annotations

import json
import inspect
import os
import re
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Set, Tuple

from runtime_v7.brand_knowledge import BrandKnowledgeService
from runtime_v7.business_identity import (
    BUSINESS_IDENTITY_EVIDENCE_REF,
    GULONG_BUSINESS_IDENTITY_PROMPT,
    authorized_business_identity_context,
    classify_business_location_request,
    guard_business_location_response,
)
from runtime_v7.capability_profile import build_capability_profile
from runtime_v7.canonical_values import CanonicalValuesProvider, RuntimeV7CanonicalValuesProvider
from runtime_v7.commercial_claim_contract import (
    payment_claim,
    payment_claim_contract_violations,
    payment_policies_from_tool_results,
    ungrounded_payment_assertion_violations,
)
from runtime_v7.contact_policy import get_business_contact
from runtime_v7.conversation_evidence import merge_recent_turns
from runtime_v7.faq_tools import (
    answer_order_faq,
    answer_policy_faq,
    answer_product_faq,
    answer_service_faq,
    order_faq_requires_payment_scope,
    resolve_faq_id_for_payload,
)
from runtime_v7.image_evidence import ImageEvidenceExtractor
from runtime_v7.interaction_resolution import (
    default_interaction_decision,
    validate_interaction_decision,
)
from runtime_v7.model_contract import (
    COMPLETE_TURN_COMPOSITION_PROMPT,
    TurnAuthorizationEnvelopeV1,
    RuntimeV7FinalResponseModel,
    RuntimeV7HumanHandoffDecisionModel,
    RuntimeV7SemanticAnswerAuditModel,
    RuntimeV7PromoFactAuditModel,
    RuntimeV7PricingRepairResponseModel,
    build_tool_objectives,
    build_runtime_v7_context,
    build_runtime_v7_system_prompt,
    capability_profile_has_usable_product_context,
)
from runtime_v7.order_state import (
    build_order_payload,
    build_order_readiness,
    build_order_summary,
    calculate_order_quote,
    get_order_details,
    match_payment_proof,
    prepare_payment_request,
    submit_order,
)
from runtime_v7.order_canonicalization import (
    checkout_metadata,
    payment_option_label,
    payment_plan_hints_from_text,
)
from runtime_v7.preturn_intake import build_preturn_intake_context_sync
from runtime_v7.memory import (
    ActiveWorkingMemoryGenerator,
    ActiveWorkingMemoryStore,
    ActiveWorkingMemoryUpdater,
    InMemoryActiveWorkingMemoryStore,
    manila_now_text,
)
from runtime_v7.product_observations import (
    ProductObservationStore,
    ProductToolHarness,
)
from runtime_v7.lead_qualification import build_lead_qualification_snapshot
from runtime_v7.product_search import (
    DEFAULT_CANONICAL_BRANDS,
    ProductSearchRequest,
    effective_total_price,
    normalize_rim_size,
    normalize_section_width,
)
from runtime_v7.promo_catalog import (
    PromoCatalogService,
    exact_promo_title_mentioned,
    is_targeted_promo_query,
    normalize_promo_query,
    product_card_matches_promo_types,
)
from runtime_v7.service_tools import RuntimeV7ServiceTools
from runtime_v7.state_signal_ledger import InMemoryBackgroundSignalLedgerStore
from runtime_v7.state_signal_schema import (
    DURABLE_SIGNAL_RELATIONS,
    TRANSIENT_SIGNAL_RELATIONS,
    signal_authority_source,
    signal_has_durable_authority,
)
from runtime_v7.state_signals import BackgroundSignalExtractionModelClient, build_commercial_state_context
from runtime_v7.tagging import evaluate_runtime_v7_tagging, mark_runtime_v7_tags_applied
from runtime_v7.tool_capabilities import TOOL_CAPABILITIES, schemas_for_tool_names
from runtime_v7.transaction_choices import (
    signal_authority,
)
from runtime_v7.triage_seeds import build_response_seeds


FINAL_COMPOSER_MAX_TOKENS = 4096
FINAL_COMPOSER_TEMPERATURE_DEFAULT = 0.1
FACT_SCOPE_AUDIT_MAX_TOKENS = 1600
PRICING_REPAIR_MAX_TOKENS = 260
ACCEPTED_FINAL_COMPOSER_STATUSES = frozenset(
    {"used", "repaired", "service_claim_surface_sanitized"}
)
AUTHORITATIVE_FINAL_COMPOSER_SURFACE_STATUSES = frozenset(
    {
        *ACCEPTED_FINAL_COMPOSER_STATUSES,
        "provider_grounded_payment_composition",
        "payment_claim_safe_surface_fallback",
        "renderer_contract_fallback",
        "answer_goal_safe_fallback",
        "promo_fact_safe_fallback",
        "promo_fact_scoped_result",
    }
)
RUNTIME_V7_WELCOME_SPIEL_TEXT = (
    "Hi po! Welcome to Gulong.ph 😊\n"
    "We'll help you find brand-new, legit tires that fit your car, budget, and area."
)
RUNTIME_V7_FIRST_TURN_INFO_REQUEST_TEXT = (
    "Para ma-check namin yung best tires for you, pakisend lang po:\n\n"
    "1. Tire size/car info\n"
    "2. Brand or budget\n"
    "3. Location\n"
    "4. Contact Number\n\n"
    "Thank you po 😊"
)
RUNTIME_V7_FIRST_TURN_SIZE_GUIDE_TEXT = (
    "Guide lang po: tire size usually looks like 185/65R15 or 195R14.\n"
    "Makikita po ito sa side ng tire.\n\n"
    "If hindi sure sa size, okay lang po car model/year or photo ng tire sidewall."
)
RUNTIME_V7_FIRST_TURN_INTRO_MESSAGES = (
    RUNTIME_V7_WELCOME_SPIEL_TEXT,
    RUNTIME_V7_FIRST_TURN_INFO_REQUEST_TEXT,
    RUNTIME_V7_FIRST_TURN_SIZE_GUIDE_TEXT,
)
RUNTIME_V7_FIRST_TURN_INTRO_TEXT = "\n\n".join(RUNTIME_V7_FIRST_TURN_INTRO_MESSAGES)
SUPPORTING_WARRANTY_PROMO_QUERY = "The Gulong Double Warranty"
FIRST_TURN_INTRO_MODE_FULL = "full_intake"
FIRST_TURN_INTRO_MODE_WELCOME_ONLY = "welcome_only"
WELCOME_SPIEL_GUARD_EVENT_TYPE = "first_turn_welcome_spiel_inserted"
MODEL_COMPOSED_FIRST_TURN_OPENING_EVENT_TYPE = "first_turn_opening_model_composed"
SERVICE_TOOL_NAMES = {
    "answer_service_faq",
    "find_installation_partners",
    "find_service_locations",
    "get_branch_addons",
    "find_installation_slots",
    "validate_installation_slot",
}


def final_composer_output_accepted(value: Any) -> bool:
    """Return whether validated model-owned response units are authoritative.

    A contract repair is still model-composed output. Treating it as a failed
    composer path lets legacy guards rewrite prose and append surfaces the
    repaired unit plan intentionally omitted.
    """

    if isinstance(value, Mapping):
        composer = value.get("final_composer")
        if isinstance(composer, Mapping):
            value = composer.get("status")
        else:
            value = value.get("status")
    return str(value or "").strip() in ACCEPTED_FINAL_COMPOSER_STATUSES


def final_composer_surface_plan_authoritative(value: Any) -> bool:
    """Return whether structured response units own channel surface selection.

    Safe contract fallbacks are not accepted model prose, but their response
    units are still the validated surface plan. The channel renderer must not
    reattach tool surfaces that those units intentionally omitted.
    """

    if isinstance(value, Mapping):
        composer = value.get("final_composer")
        if isinstance(composer, Mapping):
            value = composer.get("status")
        else:
            value = value.get("status")
    return (
        str(value or "").strip()
        in AUTHORITATIVE_FINAL_COMPOSER_SURFACE_STATUSES
    )


def _exact_title_promo_refs(
    search_result: Mapping[str, Any],
    *,
    query: str,
) -> List[str]:
    """Keep an exact catalog-title lookup scoped to that reviewed promo.

    Vector search may return related active campaigns after the exact match.
    Those alternatives remain useful for broad discovery, but an exact title
    lookup should not silently expand the renderer-owned gallery.
    """

    normalized_query = normalize_promo_query(query)
    if not normalized_query:
        return []
    allowed_refs = {
        str(value or "").strip()
        for value in search_result.get("allowed_promo_refs") or []
        if str(value or "").strip()
    }
    matches: List[str] = []
    for candidate in search_result.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        promo_ref = str(candidate.get("promo_ref") or "").strip()
        if (
            promo_ref in allowed_refs
            and exact_promo_title_mentioned(
                normalized_query,
                str(candidate.get("title") or ""),
            )
        ):
            matches.append(promo_ref)
    return list(dict.fromkeys(matches))


def _requested_brand_promo_refs(
    search_result: Mapping[str, Any],
) -> List[str]:
    """Keep a targeted gallery within the customer's validated brand scope.

    Targeted vector retrieval intentionally retains related campaigns so the
    model can explain alternatives when a requested brand has no active offer.
    Once that brand *does* match, however, those alternatives should not leak
    into the deterministic gallery.  The reviewed catalog candidate brands and
    provider-issued allowed refs are the authority for this presentation-only
    narrowing.
    """

    requested = {
        str(value or "").strip().casefold()
        for value in search_result.get("matched_requested_brands") or []
        if str(value or "").strip()
    }
    if not requested:
        return []
    allowed_refs = {
        str(value or "").strip()
        for value in search_result.get("allowed_promo_refs") or []
        if str(value or "").strip()
    }
    matches: List[str] = []
    for candidate in search_result.get("candidates") or []:
        if not isinstance(candidate, Mapping):
            continue
        promo_ref = str(candidate.get("promo_ref") or "").strip()
        brands = {
            str(value or "").strip().casefold()
            for value in candidate.get("brands") or []
            if str(value or "").strip()
        }
        if promo_ref in allowed_refs and brands.intersection(requested):
            matches.append(promo_ref)
    return list(dict.fromkeys(matches))


class RuntimeV7ModelClient(Protocol):
    """Small model-client interface used by the Runtime V7 harness."""

    def complete(
        self,
        *,
        messages: Sequence[Dict[str, Any]],
        tools: Sequence[Dict[str, Any]],
        tool_choice: Any = "auto",
        response_format: Optional[Any] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        ...


@dataclass
class RuntimeV7Harness:
    """Run the Runtime V7 tool loop and capture turn-level artifacts."""

    model_client: RuntimeV7ModelClient
    tools: ProductToolHarness
    service_tools: RuntimeV7ServiceTools = field(default_factory=RuntimeV7ServiceTools)
    session_id: str = "runtime-v7-harness"
    memory_store: ActiveWorkingMemoryStore = field(default_factory=InMemoryActiveWorkingMemoryStore)
    memory_generator: Optional[ActiveWorkingMemoryGenerator] = None
    background_signal_model_client: Optional[BackgroundSignalExtractionModelClient] = None
    canonical_values_provider: Optional[CanonicalValuesProvider] = None
    order_http_client: Optional[Any] = None
    image_evidence_extractor: ImageEvidenceExtractor = field(default_factory=ImageEvidenceExtractor)
    background_signal_model_policy: str = "auto"
    max_tool_rounds: int = 3
    default_domains: Sequence[str] = ("product", "service", "order")
    thought_signature_mode: str = "preserve"
    profile_fields: Dict[str, Any] = field(default_factory=dict)
    tag_apply_callback: Optional[Callable[[Sequence[Dict[str, Any]], Dict[str, Any]], Dict[str, Any]]] = None
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    recent_turns: List[Dict[str, str]] = field(default_factory=list)
    turn_records: List[Dict[str, Any]] = field(default_factory=list)
    signal_ledger: InMemoryBackgroundSignalLedgerStore = field(default_factory=InMemoryBackgroundSignalLedgerStore)
    latest_order_summary_snapshot: Dict[str, Any] = field(default_factory=dict)
    latest_selected_product_context: Dict[str, Any] = field(default_factory=dict)
    order_payload_store: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    latest_order_payload_ref: str = ""
    latest_submitted_order_context: Dict[str, Any] = field(default_factory=dict)
    latest_order_details_context: Dict[str, Any] = field(default_factory=dict)
    payment_request_store: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    latest_payment_request_ref: str = ""
    external_evidence_store: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    latest_fitment_observation: Dict[str, Any] = field(default_factory=dict)
    tag_ledger: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    human_handoff_state: Dict[str, Any] = field(default_factory=dict)
    product_inclusions_sent: bool = False
    service_policy_note_ids_sent: List[str] = field(default_factory=list)
    promo_catalog: Optional[PromoCatalogService] = None
    brand_knowledge: Optional[BrandKnowledgeService] = None
    latest_promo_presentation: Dict[str, Any] = field(default_factory=dict)
    promo_presentation_history: List[Dict[str, Any]] = field(default_factory=list)
    latest_promo_action: Dict[str, Any] = field(default_factory=dict)
    promo_action_history: List[Dict[str, Any]] = field(default_factory=list)
    latest_choice_presentation: Dict[str, Any] = field(default_factory=dict)
    choice_presentation_history: List[Dict[str, Any]] = field(default_factory=list)
    latest_choice_action: Dict[str, Any] = field(default_factory=dict)
    choice_action_history: List[Dict[str, Any]] = field(default_factory=list)
    current_validated_choice_context: Dict[str, Any] = field(default_factory=dict)
    current_interaction_packet: Dict[str, Any] = field(default_factory=dict)
    turn_surface_planner: Optional[
        Callable[[Dict[str, Any]], Dict[str, Any]]
    ] = None
    location_plan_executor: Optional[
        Callable[[Dict[str, Any]], Dict[str, Any]]
    ] = None
    latest_product_presentation: Dict[str, Any] = field(default_factory=dict)
    product_presentation_history: List[Dict[str, Any]] = field(default_factory=list)
    memory_updater: ActiveWorkingMemoryUpdater = field(init=False)

    def __post_init__(self) -> None:
        self.thought_signature_mode = _normalize_thought_signature_mode(self.thought_signature_mode)
        if self.canonical_values_provider is None:
            self.canonical_values_provider = RuntimeV7CanonicalValuesProvider()
        self.memory_updater = ActiveWorkingMemoryUpdater(store=self.memory_store, generator=self.memory_generator)
        self.tools.set_canonical_values_provider(self.canonical_values_provider)
        self.service_tools.set_canonical_values_provider(self.canonical_values_provider)
        if self.order_http_client is None:
            self.order_http_client = getattr(getattr(self.tools, "runner", None), "_http", None)

    def run_turn(
        self,
        user_message: str,
        *,
        image_urls: Optional[Sequence[str]] = None,
        conversation_history: Optional[Sequence[Dict[str, Any]]] = None,
        request_time_override: Optional[str] = None,
        lead_status: str = "",
        existing_tags: Optional[Sequence[str]] = None,
        response_seed_overrides: Optional[Sequence[Dict[str, Any]]] = None,
        validated_choice_context: Optional[Dict[str, Any]] = None,
        interaction_packet: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run one user turn through context compilation, model calls, and tools."""

        self.current_validated_choice_context = (
            deepcopy(validated_choice_context)
            if isinstance(validated_choice_context, dict)
            else {}
        )
        self.current_interaction_packet = (
            deepcopy(interaction_packet)
            if isinstance(interaction_packet, dict)
            else {}
        )
        turn_index = len(self.turn_records) + 1
        request_time = str(request_time_override or "").strip() or manila_now_text()
        intake = build_preturn_intake_context_sync(
            session_id=self.session_id,
            turn_index=turn_index,
            current_user_message=user_message,
            image_urls=image_urls,
            conversation_history=conversation_history if conversation_history is not None else self.conversation_history,
            in_session_recent_turns=self.recent_turns,
            load_active_memory=lambda: self.memory_updater.load(self.session_id),
            load_latest_observation=self.tools.store.latest,
            load_latest_service_observation=self.service_tools.store.latest,
            image_evidence_extractor=self.image_evidence_extractor,
        )
        active_memory_before = intake.active_memory
        latest_observation = intake.latest_observation
        latest_service_observation = intake.latest_service_observation
        conversation_evidence = intake.conversation_evidence
        context_recent_turns = intake.context_recent_turns
        image_evidence = intake.image_evidence
        external_evidence_refs = [
            *image_evidence["external_evidence_refs"],
            *conversation_evidence["external_evidence_refs"],
        ]
        self._remember_external_evidence_refs(external_evidence_refs)
        previous_background_signals = self.signal_ledger.load(self.session_id)
        active_memory_text = str(active_memory_before.text or "").strip()
        state_context = build_commercial_state_context(
            current_user_message=user_message,
            recent_turns=context_recent_turns,
            previous_background_signals=previous_background_signals,
            active_working_memory=active_memory_text,
            latest_product_observation=latest_observation.to_public_header() if latest_observation else None,
            latest_service_observation=latest_service_observation.to_public_header() if latest_service_observation else None,
            external_evidence_refs=external_evidence_refs,
            external_evidence_candidates=image_evidence["background_signal_candidates"],
            model_client=self.background_signal_model_client,
            canonical_values_provider=self.canonical_values_provider,
            location_resolver=self.service_tools.location_resolver,
            model_extraction_policy=self.background_signal_model_policy,
        )
        _apply_validated_choice_signal_boundaries(
            state_context,
            validated_choice_context=self.current_validated_choice_context,
        )
        lead_qualification = deepcopy((state_context.get("missing_info") or {}).get("lead_qualification") or {})
        lead_qualification = _lead_qualification_with_selected_product(
            lead_qualification,
            selected_product_context=self.latest_selected_product_context,
        )
        if isinstance(state_context.get("missing_info"), dict):
            state_context["missing_info"]["lead_qualification"] = deepcopy(lead_qualification)
        first_turn_intro_mode = _first_turn_intro_mode_for_latest_turn(
            current_user_message=user_message,
        )
        effective_first_turn_intro_mode = (
            first_turn_intro_mode
            if _should_insert_first_turn_welcome(
                recent_turns=context_recent_turns,
                active_working_memory=active_memory_text,
            )
            else ""
        )
        if any(
            isinstance(seed, dict)
            and str(seed.get("type") or "") == "promo_action"
            for seed in response_seed_overrides or []
        ):
            # A valid tracked card action is already a continuation surface,
            # even when a synthetic test user has no hydrated transcript.
            effective_first_turn_intro_mode = ""
        first_turn_intro_context = _first_turn_intro_context_for_model(effective_first_turn_intro_mode)
        # FAQ phrase/vector retrieval is useful inside an explicitly selected
        # read tool, but it must not classify the turn or control which schemas
        # the main model can see. Safe product/service/order FAQ tools are
        # exposed through the capability profile instead.
        faq_hints: List[Dict[str, Any]] = []
        response_seeds = build_response_seeds(
            current_user_message=user_message,
        )
        if response_seed_overrides:
            response_seeds = [
                dict(seed)
                for seed in response_seed_overrides
                if isinstance(seed, dict)
            ] + response_seeds
        order_readiness = build_order_readiness(
            current_user_message=user_message,
            active_working_memory=active_memory_text,
            background_signals=state_context["background_signals"],
            product_observation_store=self.tools.store,
            service_observation_store=self.service_tools.store,
            selected_product_context=self.latest_selected_product_context,
            choice_action_history=self.choice_action_history,
            previous_order_summary_snapshot=self.latest_order_summary_snapshot,
            canonical_values_provider=self.canonical_values_provider,
        )
        requested_domains: List[str] = []
        active_promo_version = self.promo_catalog.active_version_id() if self.promo_catalog else ""

        def compile_model_context(stage: str) -> Dict[str, Any]:
            """Compile one stage-specific capability profile and prompt packet."""

            profile = build_capability_profile(
                current_user_message=user_message,
                active_working_memory=active_memory_text,
                background_signals=state_context["background_signals"],
                external_evidence_refs=external_evidence_refs,
                product_observation_headers=(
                    _product_observation_headers_with_delivery_state(
                        self.tools.store.headers(limit=3),
                        self.product_presentation_history,
                    )
                ),
                service_observation_headers=self.service_tools.store.headers(limit=3),
                order_summary_refs=self._order_summary_refs(),
                order_payload_refs=self._order_payload_refs(),
                payment_request_refs=self._payment_request_refs(),
                faq_hints=faq_hints,
                order_readiness=order_readiness.to_dict(),
                guided_location_optional_reoffer_suppressed=(
                    _guided_location_optional_reoffer_suppressed(
                        choice_presentation_history=self.choice_presentation_history,
                        choice_action_history=self.choice_action_history,
                    )
                ),
                requested_domains=requested_domains,
                default_domains=tuple(self.default_domains or ()),
            )
            _prune_redundant_product_tools_for_validated_choice(
                profile,
                validated_choice_context=self.current_validated_choice_context,
                selected_product_context=self.latest_selected_product_context,
            )
            _prune_irrelevant_promo_tools_for_location_product_resume(
                profile,
                validated_choice_context=self.current_validated_choice_context,
                selected_product_context=self.latest_selected_product_context,
            )
            _prune_redundant_product_faq_for_brand_knowledge(
                profile,
                selected_product_context=self.latest_selected_product_context,
            )
            _prune_fulfilled_current_promo_tools(
                profile,
                background_signals=state_context["background_signals"],
            )
            if self.brand_knowledge is None:
                profile.exposed_tools = [
                    name
                    for name in profile.exposed_tools
                    if name != "get_brand_knowledge"
                ]
            profile_payload = profile.to_dict()
            clarification_only_interaction = (
                _interaction_packet_requires_clarification_only(
                    self.current_interaction_packet
                )
            )
            business_location_disposition = (
                classify_business_location_request(user_message)
            )
            isolated_business_location = bool(
                business_location_disposition
                and not self.current_interaction_packet
                and not self.current_validated_choice_context
                and not self.latest_selected_product_context
                and (
                    business_location_disposition
                    != "ambiguous_store_location"
                    or not _has_reusable_customer_location_signal(
                        state_context["background_signals"]
                    )
                )
            )
            schemas = (
                []
                if clarification_only_interaction
                or isolated_business_location
                else schemas_for_tool_names(profile.exposed_tools)
            )
            if clarification_only_interaction:
                profile_payload["exposed_tools"] = []
                profile_payload["selection_reasons"] = [
                    *list(profile_payload.get("selection_reasons") or []),
                    "interaction_clarification_only:no_tools",
                ]
            elif isolated_business_location:
                profile_payload["exposed_tools"] = []
                profile_payload["selection_reasons"] = [
                    *list(profile_payload.get("selection_reasons") or []),
                    (
                        "business_location_boundary:no_tools:"
                        f"{business_location_disposition}"
                    ),
                ]
            context = build_runtime_v7_context(
                current_user_message=user_message,
                request_time=request_time,
                recent_turns=context_recent_turns,
                active_working_memory=active_memory_text,
                background_signals=state_context["background_signals"],
                missing_info=state_context["missing_info"],
                external_evidence_refs=external_evidence_refs,
                response_seeds=response_seeds,
                order_readiness=order_readiness.to_dict(),
                observation_store=self.tools.store,
                fitment_observation=self.latest_fitment_observation,
                service_observation_store=self.service_tools.store,
                order_payload_context=self._order_payload_context(),
                order_details_context=self._order_details_context(),
                payment_request_context=self._payment_request_context(),
                capability_profile=profile_payload,
                first_turn_intro_context=first_turn_intro_context,
                response_continuity=_final_composer_response_continuity(
                    is_ongoing_conversation=bool(
                        context_recent_turns or active_memory_text.strip()
                    ),
                    latest_customer_greeted=_customer_message_starts_with_greeting(
                        user_message
                    ),
                ),
                interaction_context={
                    "channel": str(self.profile_fields.get("channel") or "manychat"),
                    "active_promo_catalog_version": active_promo_version,
                    "validated_choice_action": deepcopy(
                        self.current_validated_choice_context
                    ),
                    "latest_promo_presentation": _compact_interaction_state(self.latest_promo_presentation),
                    "latest_promo_action": _compact_interaction_state(self.latest_promo_action),
                    "latest_choice_presentation": _compact_interaction_state(self.latest_choice_presentation),
                    "latest_choice_action": _compact_interaction_state(self.latest_choice_action),
                    "interaction_packet": deepcopy(self.current_interaction_packet),
                },
                selected_product_context=self.latest_selected_product_context,
                validated_installation_context=(
                    self.service_tools.store.latest_validated_slot_context()
                ),
            )
            system_prompt = build_runtime_v7_system_prompt(profile.selected_domains)
            return {
                "stage": stage,
                "capability_profile": profile_payload,
                "tool_schemas": schemas,
                "context_input": context,
                "system_prompt": system_prompt,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": context},
                ],
            }

        compiled_context = compile_model_context("initial")
        capability_profile = compiled_context["capability_profile"]
        tool_schemas = compiled_context["tool_schemas"]
        context_input = compiled_context["context_input"]
        messages: List[Dict[str, Any]] = compiled_context["messages"]
        record: Dict[str, Any] = {
            "turn_id": f"turn_{len(self.turn_records) + 1}",
            "user_message": user_message,
            "request_time": request_time,
            "lead_status": lead_status,
            "lead_qualification": deepcopy(lead_qualification),
            "response_seeds": deepcopy(response_seeds),
            "context_input": context_input,
            "system_prompt": compiled_context["system_prompt"],
            "active_working_memory_before_turn": active_memory_before.to_dict(),
            "previous_background_signals_before_turn": deepcopy(previous_background_signals),
            "background_signals_before_turn": deepcopy(state_context["background_signals"]),
            "missing_info_before_turn": deepcopy(state_context["missing_info"]),
            "order_readiness_before_turn": deepcopy(order_readiness.to_dict()),
            "background_signal_extraction": deepcopy(state_context.get("background_signal_extraction") or {}),
            "image_evidence": deepcopy(image_evidence),
            "conversation_evidence": deepcopy(conversation_evidence),
            "preturn_intake": deepcopy(intake.metadata),
            "faq_hints": deepcopy(faq_hints),
            "thought_signature_mode": self.thought_signature_mode,
            "capability_profile": deepcopy(capability_profile),
            "capability_profile_history": [
                {
                    "stage": "initial",
                    "profile": deepcopy(compiled_context["capability_profile"]),
                }
            ],
            "compiled_contexts": [
                {
                    "stage": "initial",
                    "selected_domains": deepcopy(compiled_context["capability_profile"].get("selected_domains") or []),
                    "exposed_tools": deepcopy(compiled_context["capability_profile"].get("exposed_tools") or []),
                    "context_input": context_input,
                    "system_prompt": compiled_context["system_prompt"],
                }
            ],
            "hydrated_recent_turns_before_turn": deepcopy(context_recent_turns),
            "product_inclusions_previously_sent": bool(self.product_inclusions_sent),
            "llm_calls": [],
            "tool_results": [],
        }

        clarification_only_interaction = (
            _interaction_packet_requires_clarification_only(
                self.current_interaction_packet
            )
        )
        promo_preload = (
            []
            if clarification_only_interaction
            else self._prepare_promo_context_for_turn(
                user_message=user_message,
                background_signals=state_context["background_signals"],
            )
        )
        if promo_preload:
            record["tool_results"].extend(deepcopy(promo_preload))
            model_promo_context = [
                {
                    "name": item.get("name"),
                    "result": item.get("result"),
                }
                for item in promo_preload
            ]
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Runtime preloaded reviewed promo catalog context for this turn. Use these source-backed "
                        "facts in the response. For a targeted promo question, answer directly from the leading "
                        "candidate's offer_summary and relevant_mechanics before mentioning related options; a "
                        "gallery does not replace the answer. If a promo gallery presentation is already included, "
                        "acknowledge the shown options without calling present_promo_gallery again. Otherwise, "
                        "select only allowed_promo_refs from the search result.\n"
                        + json.dumps(model_promo_context, ensure_ascii=False)
                    ),
                }
            )

        assistant_text = ""
        parsed_final_units: Optional[List[Dict[str, Any]]] = None
        tool_result_cache: Dict[str, Dict[str, Any]] = {}
        supports_final_composer = _model_client_supports_response_format(self.model_client)
        named_promo_context = _named_catalog_promo_tool_context(
            current_user_message=user_message,
            promo_catalog=self.promo_catalog,
            tool_schemas=tool_schemas,
        )
        next_tool_choice: Any = "auto"
        if named_promo_context:
            route_prompt = _named_catalog_promo_tool_prompt(
                user_message=user_message,
                context=named_promo_context,
            )
            messages = [*messages, {"role": "system", "content": route_prompt}]
            record.setdefault("tool_routing_events", []).append(
                {
                    "type": "named_catalog_promo_context_available",
                    "route_prompt": route_prompt,
                    "route_context": deepcopy(named_promo_context),
                    "tool_choice": "model_owned",
                }
            )
        # A safe cross-domain schema recovery recompiles the same customer turn
        # without executing the unexposed call. Give that one recovery a single
        # bounded replacement round so it cannot consume the ordinary tool
        # budget needed to satisfy the original product objective.
        unexposed_read_recovery_round_allowance = 0
        # An explicit request_capability call only recompiles schemas; it does
        # not satisfy the customer objective. Preserve one replacement round
        # even when a deployment intentionally caps ordinary tool rounds at 1.
        request_capability_recovery_round_allowance = 0
        # Empty/no-renderable output recovery is likewise a replacement round,
        # not an ordinary tool round. Deployed environments may intentionally
        # set max_tool_rounds=1, so account for the one bounded retry explicitly
        # instead of queuing its prompt and then exiting before it can run.
        empty_output_recovery_round_allowance = 0
        for round_index in range(1, self.max_tool_rounds + 4):
            if round_index > (
                self.max_tool_rounds
                + unexposed_read_recovery_round_allowance
                + request_capability_recovery_round_allowance
                + empty_output_recovery_round_allowance
            ):
                break
            model_input_messages = deepcopy(messages)
            round_tool_choice = deepcopy(next_tool_choice)
            next_tool_choice = "auto"
            response = self.model_client.complete(messages=messages, tools=tool_schemas, tool_choice=round_tool_choice)
            tool_calls = _normalize_tool_calls(response.get("tool_calls") or [])
            assistant_text = str(response.get("content") or "")
            usage_summary = _llm_usage_summary(response)
            record["llm_calls"].append(
                {
                    "round": round_index,
                    "model_input_messages": model_input_messages,
                    "tool_schemas": deepcopy(tool_schemas),
                    "model_output": deepcopy(response),
                    "content": assistant_text,
                    "tool_calls": deepcopy(tool_calls),
                    "usage": deepcopy(response.get("usage") or {}),
                    "cache_usage": deepcopy(response.get("cache_usage") or {}),
                    "request_cache": deepcopy(response.get("request_cache") or {}),
                    "cache_guard_events": deepcopy(response.get("cache_guard_events") or []),
                    "usage_summary": usage_summary,
                    "latency_ms": response.get("latency_ms"),
                    "finish_reason": response.get("finish_reason"),
                    "tool_choice": deepcopy(round_tool_choice),
                }
            )

            if not tool_calls:
                if _should_retry_empty_model_output(
                    assistant_text=assistant_text,
                    retry_events=record.get("tool_retry_events") or [],
                ):
                    retry_prompt = _empty_model_output_retry_prompt(user_message=user_message)
                    record.setdefault("tool_retry_events", []).append(
                        {
                            "round": round_index,
                            "type": "empty_model_output_retry",
                            "assistant_text": assistant_text,
                            "retry_prompt": retry_prompt,
                        }
                    )
                    empty_output_recovery_round_allowance = 1
                    messages = [*messages, {"role": "system", "content": retry_prompt}]
                    continue
                ready_order_submit = _ready_order_submit_retry_context(
                    background_signals=state_context["background_signals"],
                    tool_schemas=tool_schemas,
                    tool_results=record["tool_results"],
                    retry_events=record.get("tool_retry_events") or [],
                )
                if ready_order_submit:
                    retry_prompt = _ready_order_submit_retry_prompt(
                        user_message=user_message,
                        context=ready_order_submit,
                    )
                    record.setdefault("tool_retry_events", []).append(
                        {
                            "round": round_index,
                            "type": "ready_order_submit_tool_retry",
                            "assistant_text": assistant_text,
                            "retry_prompt": retry_prompt,
                            "retry_context": deepcopy(ready_order_submit),
                        }
                    )
                    messages = [*messages, {"role": "system", "content": retry_prompt}]
                    next_tool_choice = _forced_tool_choice("submit_order")
                    continue
                ready_payment_request = _ready_payment_request_retry_context(
                    tool_schemas=tool_schemas,
                    tool_results=record["tool_results"],
                    retry_events=record.get("tool_retry_events") or [],
                )
                if ready_payment_request:
                    retry_prompt = _ready_payment_request_retry_prompt(
                        user_message=user_message,
                        context=ready_payment_request,
                    )
                    record.setdefault("tool_retry_events", []).append(
                        {
                            "round": round_index,
                            "type": "ready_payment_request_tool_retry",
                            "assistant_text": assistant_text,
                            "retry_prompt": retry_prompt,
                            "retry_context": deepcopy(ready_payment_request),
                        }
                    )
                    messages = [*messages, {"role": "system", "content": retry_prompt}]
                    next_tool_choice = _forced_tool_choice("prepare_payment_request")
                    continue
                commercial_evidence_context = _required_commercial_evidence_retry_context(
                    capability_profile=capability_profile,
                    background_signals=state_context["background_signals"],
                    tool_schemas=tool_schemas,
                    tool_results=record["tool_results"],
                    retry_events=record.get("tool_retry_events") or [],
                    current_user_message=user_message,
                )
                if commercial_evidence_context:
                    retry_prompt = _required_commercial_evidence_retry_prompt(
                        user_message=user_message,
                        context=commercial_evidence_context,
                    )
                    record.setdefault("tool_retry_events", []).append(
                        {
                            "round": round_index,
                            "type": "commercial_evidence_tool_retry",
                            "reason": "structured_commercial_objective_unmet",
                            "assistant_text": assistant_text,
                            "retry_prompt": retry_prompt,
                            "retry_context": deepcopy(commercial_evidence_context),
                        }
                    )
                    messages = [*messages, {"role": "system", "content": retry_prompt}]
                    required_tools = [
                        str(name or "").strip()
                        for name in commercial_evidence_context.get("required_tools") or []
                        if str(name or "").strip()
                    ]
                    next_tool_choice = (
                        _forced_tool_choice(commercial_evidence_context.get("tool_name"))
                        if len(required_tools) <= 1
                        else None
                    )
                    continue
                policy_evidence_context = _required_policy_evidence_retry_context(
                    current_user_message=user_message,
                    background_signals=state_context["background_signals"],
                    tool_schemas=tool_schemas,
                    tool_results=record["tool_results"],
                    retry_events=record.get("tool_retry_events") or [],
                )
                if policy_evidence_context:
                    retry_prompt = _required_policy_evidence_retry_prompt(
                        user_message=user_message,
                        context=policy_evidence_context,
                    )
                    record.setdefault("tool_retry_events", []).append(
                        {
                            "round": round_index,
                            "type": "policy_evidence_tool_retry",
                            "reason": "structured_policy_objective_unmet",
                            "assistant_text": assistant_text,
                            "retry_prompt": retry_prompt,
                            "retry_context": deepcopy(policy_evidence_context),
                        }
                    )
                    messages = [*messages, {"role": "system", "content": retry_prompt}]
                    next_tool_choice = _forced_tool_choice(
                        policy_evidence_context["tool_name"]
                    )
                    continue
                missing_product_context = _missing_product_tool_retry_context(
                    capability_profile=capability_profile,
                    background_signals=state_context["background_signals"],
                    tool_schemas=tool_schemas,
                    tool_results=record["tool_results"],
                    retry_events=record.get("tool_retry_events") or [],
                    assistant_text=assistant_text,
                    product_observation_store=self.tools.store,
                )
                if missing_product_context:
                    retry_prompt = _missing_product_tool_retry_prompt(
                        user_message=user_message,
                        context=missing_product_context,
                    )
                    record.setdefault("tool_retry_events", []).append(
                        {
                            "round": round_index,
                            "type": "product_objective_tool_retry",
                            "reason": "structured_product_objective_unmet",
                            "assistant_text": assistant_text,
                            "retry_prompt": retry_prompt,
                            "retry_context": deepcopy(missing_product_context),
                        }
                    )
                    messages = [*messages, {"role": "system", "content": retry_prompt}]
                    continue
                if (not supports_final_composer) and _should_retry_service_card_presentation(
                    assistant_text=assistant_text,
                    tool_results=record["tool_results"],
                    retry_events=record.get("tool_retry_events") or [],
                ):
                    retry_prompt = _service_card_presentation_retry_prompt(user_message=user_message)
                    record.setdefault("tool_retry_events", []).append(
                        {
                            "round": round_index,
                            "type": "service_card_presentation_retry",
                            "assistant_text": assistant_text,
                            "retry_prompt": retry_prompt,
                        }
                    )
                    messages = [*messages, {"role": "system", "content": retry_prompt}]
                    continue
                if supports_final_composer:
                    deferred_events = _deferred_presentation_retry_events(
                        round_index=round_index,
                        assistant_text=assistant_text,
                        tool_results=record["tool_results"],
                        retry_events=record.get("tool_retry_events") or [],
                    )
                    if deferred_events:
                        record.setdefault("presentation_retry_deferred_events", []).extend(deferred_events)
                break

            if len(tool_calls) == 1 and tool_calls[0].get("name") == "request_capability":
                call = tool_calls[0]
                execution_args = _hydrate_service_tool_args(
                    call.get("name") or "",
                    call.get("args") or {},
                    state_context["background_signals"],
                    current_user_message=user_message,
                    request_time=request_time,
                    product_tools=self.tools,
                    service_tools=self.service_tools,
                    selected_product_context=self.latest_selected_product_context,
                    order_readiness=order_readiness.to_dict(),
                    normalization_events=record.setdefault("tool_arg_normalization_events", []),
                )
                tool_result, compact_result, latency_ms, reused = self._execute_tool_call_with_turn_cache(
                    call,
                    execution_args,
                    round_index=round_index,
                    record=record,
                    tool_result_cache=tool_result_cache,
                    allowed_tool_names=_tool_schema_names(tool_schemas),
                    current_user_message=user_message,
                    active_working_memory=active_memory_text,
                    background_signals=state_context["background_signals"],
                    order_readiness=order_readiness.to_dict(),
                )
                record["capability_profile"]["request_capability_used"] = True
                if not reused:
                    record["tool_results"].append(
                        {
                            "round": round_index,
                            "tool_call_id": call.get("id"),
                            "name": call.get("name"),
                            "args": deepcopy(execution_args),
                            "model_args": deepcopy(call.get("args") or {}),
                            "latency_ms": latency_ms,
                            "result": compact_result,
                            "full_result": deepcopy(tool_result),
                        }
                    )
                requested_domain = str(tool_result.get("requested_domain") or "").strip().lower()
                if tool_result.get("retry_supported") and requested_domain and requested_domain not in requested_domains:
                    requested_domains.append(requested_domain)
                    request_capability_recovery_round_allowance = 1
                    expanded_context = compile_model_context(f"request_capability:{requested_domain}")
                    tool_schemas = expanded_context["tool_schemas"]
                    messages = expanded_context["messages"]
                    context_input = expanded_context["context_input"]
                    capability_profile = deepcopy(expanded_context["capability_profile"])
                    record["capability_profile"] = deepcopy(expanded_context["capability_profile"])
                    record["capability_profile"]["request_capability_used"] = True
                    record["capability_profile_history"].append(
                        {
                            "stage": f"request_capability:{requested_domain}",
                            "request": deepcopy(call.get("args") or {}),
                            "profile": deepcopy(expanded_context["capability_profile"]),
                        }
                    )
                    record["compiled_contexts"].append(
                        {
                            "stage": f"request_capability:{requested_domain}",
                            "selected_domains": deepcopy(expanded_context["capability_profile"].get("selected_domains") or []),
                            "exposed_tools": deepcopy(expanded_context["capability_profile"].get("exposed_tools") or []),
                            "context_input": context_input,
                            "system_prompt": expanded_context["system_prompt"],
                        }
                    )
                    record["expanded_context_input"] = context_input
                    record["expanded_system_prompt"] = expanded_context["system_prompt"]
                    continue

                model_message_tool_calls, thought_events = _prepare_tool_calls_for_model_messages(
                    tool_calls,
                    mode=self.thought_signature_mode,
                )
                if thought_events:
                    record.setdefault("thought_signature_events", []).extend(
                        _thought_signature_events(round_index=round_index, events=thought_events)
                    )
                messages.append(_assistant_tool_call_message(model_message_tool_calls, assistant_text))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": model_message_tool_calls[0].get("id") or f"tool_{round_index}",
                        "name": call.get("name"),
                        "content": json.dumps(compact_result, ensure_ascii=False),
                    }
                )
                continue

            recoverable_unexposed_tools = _recoverable_unexposed_read_tool_domains(
                tool_calls,
                exposed_tool_names=_tool_schema_names(tool_schemas),
                already_requested_domains=requested_domains,
            )
            if recoverable_unexposed_tools:
                unexposed_read_recovery_round_allowance = 1
                recovered_domains = sorted(recoverable_unexposed_tools)
                active_domains = [
                    str(domain or "").strip().lower()
                    for domain in capability_profile.get("selected_domains")
                    or []
                    if str(domain or "").strip()
                ]
                for requested_domain in [*active_domains, *recovered_domains]:
                    if requested_domain not in requested_domains:
                        requested_domains.append(requested_domain)
                recovery_stage = (
                    "unexposed_read_recovery:" + ",".join(recovered_domains)
                )
                expanded_context = compile_model_context(recovery_stage)
                tool_schemas = expanded_context["tool_schemas"]
                messages = expanded_context["messages"]
                context_input = expanded_context["context_input"]
                capability_profile = deepcopy(expanded_context["capability_profile"])
                record["capability_profile"] = deepcopy(
                    expanded_context["capability_profile"]
                )
                recovery_event = {
                    "round": round_index,
                    "type": "unexposed_read_capability_recovery",
                    "domains": recovered_domains,
                    "tool_names_by_domain": deepcopy(
                        recoverable_unexposed_tools
                    ),
                    "policy": (
                        "recompile_only_registered_read_tools_without_execution"
                    ),
                }
                record.setdefault("tool_retry_events", []).append(recovery_event)
                record["capability_profile_history"].append(
                    {
                        "stage": recovery_stage,
                        "request": deepcopy(recovery_event),
                        "profile": deepcopy(expanded_context["capability_profile"]),
                    }
                )
                record["compiled_contexts"].append(
                    {
                        "stage": recovery_stage,
                        "selected_domains": deepcopy(
                            expanded_context["capability_profile"].get(
                                "selected_domains"
                            )
                            or []
                        ),
                        "exposed_tools": deepcopy(
                            expanded_context["capability_profile"].get(
                                "exposed_tools"
                            )
                            or []
                        ),
                        "context_input": context_input,
                        "system_prompt": expanded_context["system_prompt"],
                    }
                )
                record["expanded_context_input"] = context_input
                record["expanded_system_prompt"] = expanded_context[
                    "system_prompt"
                ]
                continue

            model_message_tool_calls, thought_events = _prepare_tool_calls_for_model_messages(
                tool_calls,
                mode=self.thought_signature_mode,
            )
            if thought_events:
                record.setdefault("thought_signature_events", []).extend(
                    _thought_signature_events(round_index=round_index, events=thought_events)
                )
            messages.append(_assistant_tool_call_message(model_message_tool_calls, assistant_text))
            for call_index, (call, model_message_call) in enumerate(
                zip(tool_calls, model_message_tool_calls)
            ):
                execution_args = _hydrate_service_tool_args(
                    call.get("name") or "",
                    call.get("args") or {},
                    state_context["background_signals"],
                    current_user_message=user_message,
                    request_time=request_time,
                    product_tools=self.tools,
                    service_tools=self.service_tools,
                    selected_product_context=self.latest_selected_product_context,
                    order_readiness=order_readiness.to_dict(),
                    same_turn_tool_calls=tool_calls,
                    normalization_events=record.setdefault("tool_arg_normalization_events", []),
                )
                tool_result, compact_result, latency_ms, reused = self._execute_tool_call_with_turn_cache(
                    call,
                    execution_args,
                    round_index=round_index,
                    record=record,
                    tool_result_cache=tool_result_cache,
                    allowed_tool_names=_tool_schema_names(tool_schemas),
                    current_user_message=user_message,
                    active_working_memory=active_memory_text,
                    background_signals=state_context["background_signals"],
                    order_readiness=order_readiness.to_dict(),
                )
                completed_promo_gallery: Dict[str, Any] = {}
                if (
                    not reused
                    and call.get("name") == "search_promo_catalog"
                    and not any(
                        planned_call.get("name")
                        == "present_promo_gallery"
                        for planned_call in tool_calls[call_index + 1 :]
                    )
                ):
                    completed_promo_gallery = (
                        self._complete_requested_promo_gallery(
                            search_result=tool_result,
                            search_args=execution_args,
                            round_index=round_index,
                            record=record,
                        )
                    )
                    if completed_promo_gallery:
                        compact_result = {
                            **deepcopy(compact_result),
                            "automatic_gallery": deepcopy(
                                completed_promo_gallery.get("result") or {}
                            ),
                        }
                if call.get("name") == "request_capability":
                    record["capability_profile"]["request_capability_used"] = True
                if not reused:
                    record["tool_results"].append(
                        {
                            "round": round_index,
                            "tool_call_id": call.get("id"),
                            "name": call.get("name"),
                            "args": deepcopy(execution_args),
                            "model_args": deepcopy(call.get("args") or {}),
                            "latency_ms": latency_ms,
                            "result": compact_result,
                            "full_result": deepcopy(tool_result),
                        }
                    )
                    if completed_promo_gallery:
                        record["tool_results"].append(
                            completed_promo_gallery
                        )
                tool_schemas = _expand_tool_schemas_after_order_progress(
                    tool_schemas,
                    source_tool_name=call.get("name") or "",
                    compact_result=compact_result,
                    round_index=round_index,
                    record=record,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": model_message_call.get("id") or f"tool_{round_index}",
                        "name": call.get("name"),
                        "content": json.dumps(compact_result, ensure_ascii=False),
                    }
                )

        if _tool_results_include_human_handoff(record["tool_results"]):
            effective_first_turn_intro_mode = ""
            first_turn_intro_context = _first_turn_intro_context_for_model("")
            record.setdefault("response_guard_events", []).append(
                {
                    "type": "first_turn_intro_suppressed_for_handoff",
                    "reason": "typed_human_handoff_requested",
                }
            )

        self._complete_validated_promo_gallery(record)
        self._complete_product_supporting_promo_gallery(record)

        if record["tool_results"]:
            order_readiness = build_order_readiness(
                current_user_message=user_message,
                active_working_memory=active_memory_text,
                background_signals=state_context["background_signals"],
                product_observation_store=self.tools.store,
                service_observation_store=self.service_tools.store,
                selected_product_context=self.latest_selected_product_context,
                choice_action_history=self.choice_action_history,
                previous_order_summary_snapshot=self.latest_order_summary_snapshot,
                canonical_values_provider=self.canonical_values_provider,
            )
            record["order_readiness_after_tools"] = deepcopy(
                order_readiness.to_dict()
            )
        if self.turn_surface_planner is not None:
            try:
                planned = self.turn_surface_planner(
                    {
                        **deepcopy(record),
                        "order_readiness_after_tools": deepcopy(
                            order_readiness.to_dict()
                        ),
                        "lead_qualification": deepcopy(lead_qualification),
                    }
                )
                if isinstance(planned, dict):
                    for key in (
                        "location_choice_surface",
                        "location_choice_surface_status",
                        "checkout_choice_surface",
                        "checkout_choice_surface_status",
                    ):
                        if planned.get(key) not in (None, "", [], {}):
                            record[key] = deepcopy(planned[key])
            except Exception as exc:
                record.setdefault("response_guard_events", []).append(
                    {
                        "type": "turn_surface_planning_failed",
                        "reason": exc.__class__.__name__,
                    }
                )

        if (
            effective_first_turn_intro_mode
            == FIRST_TURN_INTRO_MODE_FULL
            and (
                (
                    isinstance(record.get("location_choice_surface"), dict)
                    and record.get("location_choice_surface")
                )
                or any(
                    isinstance(item, dict)
                    and _tool_result_authorizes_customer_facts(item)
                    and str(item.get("name") or "")
                    in {
                        "get_business_contact",
                        "get_brand_knowledge",
                        "answer_product_faq",
                        "answer_policy_faq",
                        "answer_service_faq",
                        "answer_order_faq",
                    }
                    for item in record.get("tool_results") or []
                )
            )
        ):
            effective_first_turn_intro_mode = (
                FIRST_TURN_INTRO_MODE_WELCOME_ONLY
            )
            first_turn_intro_context = _first_turn_intro_context_for_model(
                effective_first_turn_intro_mode
            )
            record.setdefault("response_guard_events", []).append(
                {
                    "type": "first_turn_intro_compacted_after_model_plan",
                    "reason": "grounded_runtime_capability_selected",
                    "intro_mode": effective_first_turn_intro_mode,
                }
            )

        draft_assistant_text = assistant_text
        final_composer_response: Dict[str, Any] = {}
        parsed_final_units: Optional[List[Dict[str, Any]]] = None
        validated_installation_context = (
            self.service_tools.store.latest_validated_slot_context()
        )
        customer_turn_plan = _build_customer_turn_plan(
            record=record,
            order_readiness=order_readiness.to_dict(),
            background_signals=state_context["background_signals"],
            validated_choice_context=self.current_validated_choice_context,
            selected_product_context=self.latest_selected_product_context,
            validated_installation_context=validated_installation_context,
        )
        if customer_turn_plan:
            record["customer_turn_plan"] = deepcopy(customer_turn_plan)
        composer_order_transition = _no_tool_order_progression_requires_composer(
            background_signals=state_context["background_signals"],
            order_readiness=order_readiness.to_dict(),
        )
        composer_voice_transition = _main_response_requires_voice_composer(
            current_user_message=user_message,
            model_text=draft_assistant_text,
            recent_turns=context_recent_turns,
            active_working_memory=active_memory_text,
        )
        provider_grounded_payment_text = _provider_grounded_payment_response_text(
            record["tool_results"]
        )
        if provider_grounded_payment_text:
            parsed_final_units = [
                {
                    "type": "text",
                    "content": {"text": provider_grounded_payment_text},
                }
            ]
            assistant_text = json.dumps(
                {"response_units": parsed_final_units},
                ensure_ascii=False,
            )
            record["final_composer"] = {
                "status": "provider_grounded_payment_composition",
                "reason": "complete_typed_payment_policy_results",
                "response_format": "RuntimeV7ResponseUnits",
                "model_input_messages": [],
                "model_output": {},
                "usage_summary": {},
            }
            record.setdefault("response_guard_events", []).append(
                {
                    "type": "provider_grounded_payment_composition_used",
                    "reason": "all_payment_claims_typed_and_contract_valid",
                    "claim_count": len(
                        _final_composer_required_commercial_claims(
                            record["tool_results"]
                        )
                    ),
                }
            )
        elif (
            record["tool_results"]
            or composer_order_transition
            or composer_voice_transition
            or self.current_validated_choice_context
            or self.current_interaction_packet
            or customer_turn_plan.get("available_surfaces")
        ) and _model_client_supports_response_format(self.model_client):
            final_messages = _build_final_composer_messages(
                current_user_message=user_message,
                request_time=request_time,
                active_working_memory=active_memory_text,
                recent_turns=context_recent_turns,
                background_signals=state_context["background_signals"],
                lead_qualification=lead_qualification,
                order_readiness=order_readiness.to_dict(),
                capability_profile=capability_profile,
                tool_results=record["tool_results"],
                draft_assistant_text=draft_assistant_text,
                presentation_retry_events=record.get("presentation_retry_deferred_events") or [],
                product_observation_store=self.tools.store,
                order_details_context=self._order_details_context(),
                payment_request_context=self._payment_request_context(),
                first_turn_intro_context=first_turn_intro_context,
                selected_product_context=self.latest_selected_product_context,
                validated_installation_context=validated_installation_context,
                latest_order_summary_snapshot=self.latest_order_summary_snapshot,
                interaction_packet=self.current_interaction_packet,
                customer_turn_plan=customer_turn_plan,
                response_seeds=response_seeds,
                response_seed_overrides=response_seed_overrides,
                tracked_interaction=bool(
                    self.current_validated_choice_context
                    or self.current_interaction_packet
                ),
            )
            final_response = _complete_model_client(
                self.model_client,
                messages=final_messages,
                tools=[],
                tool_choice="none",
                response_format=RuntimeV7FinalResponseModel,
                max_tokens=FINAL_COMPOSER_MAX_TOKENS,
                temperature=_final_composer_temperature(),
            )
            final_composer_response = deepcopy(final_response)
            assistant_text = str(final_response.get("content") or "")
            parsed_final_units = _parse_structured_response_units(assistant_text)
            final_composer_round = "final_composer"
            final_composer_input_messages = final_messages
            if parsed_final_units is None:
                initial_response = deepcopy(final_response)
                initial_text = assistant_text
                initial_usage = _llm_usage_summary(initial_response)
                record["llm_calls"].append(
                    {
                        "round": "final_composer",
                        "component": "final_composer",
                        **_final_composer_attempt_observability(
                            round_name="final_composer",
                        ),
                        "model_input_messages": deepcopy(final_messages),
                        "tool_schemas": [],
                        "model_output": deepcopy(initial_response),
                        "content": initial_text,
                        "tool_calls": [],
                        "usage": deepcopy(initial_response.get("usage") or {}),
                        "cache_usage": deepcopy(
                            initial_response.get("cache_usage") or {}
                        ),
                        "request_cache": deepcopy(
                            initial_response.get("request_cache") or {}
                        ),
                        "cache_guard_events": deepcopy(
                            initial_response.get("cache_guard_events") or []
                        ),
                        "usage_summary": initial_usage,
                        "latency_ms": initial_response.get("latency_ms"),
                        "finish_reason": initial_response.get("finish_reason"),
                        "response_format": "RuntimeV7FinalResponseModel",
                    }
                )
                format_retry_messages = [
                    *final_messages,
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "type": "final_composer_format_retry",
                                "required_faq_fact_answers": (
                                    customer_turn_plan.get(
                                        "progression_context", {}
                                    ).get("required_faq_fact_answers", [])
                                ),
                                "required_commercial_claims": (
                                    _final_composer_required_commercial_claims(
                                        record["tool_results"]
                                    )
                                ),
                                "request_obligations": customer_turn_plan.get(
                                    "request_obligations", []
                                ),
                                "instruction": (
                                    "The previous call ended without a valid response-format "
                                    "object. Retry once and return the schema object immediately, "
                                    "with no analysis or prose outside it. Keep text concise. "
                                    "Return at least one response unit and map every request "
                                    "obligation in request_coverage. "
                                    "Preserve every required renderer surface, grounded FAQ "
                                    "answer, and commercial claim; cite only authorized evidence "
                                    "refs and ask at most one next question."
                                ),
                            },
                            ensure_ascii=False,
                        ),
                    },
                ]
                retry_response = _complete_model_client(
                    self.model_client,
                    messages=format_retry_messages,
                    tools=[],
                    tool_choice="none",
                    response_format=RuntimeV7FinalResponseModel,
                    max_tokens=FINAL_COMPOSER_MAX_TOKENS,
                    temperature=0.0,
                )
                final_response = retry_response
                final_composer_response = deepcopy(retry_response)
                assistant_text = str(retry_response.get("content") or "")
                parsed_final_units = _parse_structured_response_units(
                    assistant_text
                )
                final_composer_round = "final_composer_format_retry"
                final_composer_input_messages = format_retry_messages
                record.setdefault("response_guard_events", []).append(
                    {
                        "type": "final_composer_format_retry",
                        "reason": "initial_response_format_invalid",
                        "initial_finish_reason": initial_response.get(
                            "finish_reason"
                        ),
                        "retry_finish_reason": retry_response.get(
                            "finish_reason"
                        ),
                        "status": (
                            "recovered"
                            if parsed_final_units is not None
                            else "failed"
                        ),
                    }
                )
            final_composer_status = "used" if parsed_final_units is not None else "response_unit_recovery_pending"
            if parsed_final_units is None:
                record.setdefault("response_guard_events", []).append(
                    {
                        "type": "response_unit_recovery_pending",
                        "reason": "final_composer_invalid_response_format",
                        "tool_result_count": len(record["tool_results"]),
                    }
                )
                assistant_text = draft_assistant_text
            final_usage_summary = _llm_usage_summary(final_response)
            record["llm_calls"].append(
                {
                    "round": final_composer_round,
                    "component": "final_composer",
                    **_final_composer_attempt_observability(
                        round_name=final_composer_round,
                        repair_reason=(
                            "invalid_response_format"
                            if final_composer_round
                            == "final_composer_format_retry"
                            else None
                        ),
                    ),
                    "model_input_messages": deepcopy(
                        final_composer_input_messages
                    ),
                    "tool_schemas": [],
                    "model_output": deepcopy(final_response),
                    "content": assistant_text,
                    "tool_calls": [],
                    "usage": deepcopy(final_response.get("usage") or {}),
                    "cache_usage": deepcopy(final_response.get("cache_usage") or {}),
                    "request_cache": deepcopy(final_response.get("request_cache") or {}),
                    "cache_guard_events": deepcopy(final_response.get("cache_guard_events") or []),
                    "usage_summary": final_usage_summary,
                    "latency_ms": final_response.get("latency_ms"),
                    "finish_reason": final_response.get("finish_reason"),
                    "response_format": "RuntimeV7FinalResponseModel",
                }
            )
            record["final_composer"] = {
                "status": final_composer_status,
                "reason": (
                    "tool_results"
                    if record["tool_results"]
                    else "voice_continuity_repair"
                    if composer_voice_transition
                    else "structured_order_progression"
                ),
                "response_format": "RuntimeV7FinalResponseModel",
                "model_input_messages": deepcopy(
                    final_composer_input_messages
                ),
                "model_output": deepcopy(final_response),
                "usage_summary": final_usage_summary,
            }
            if parsed_final_units is not None:
                (
                    assistant_text,
                    parsed_final_units,
                    completed_supporting_surface_refs,
                ) = _complete_required_supporting_replacement_surfaces(
                    assistant_text,
                    parsed_final_units,
                    customer_turn_plan=customer_turn_plan,
                )
                if completed_supporting_surface_refs:
                    record.setdefault("response_guard_events", []).append(
                        {
                            "type": "required_supporting_surfaces_completed",
                            "reason": "renderer_owned_required_supporting_replacement",
                            "surface_refs": completed_supporting_surface_refs,
                        }
                    )
                contract_violations = _final_composer_renderer_contract_violations(
                    parsed_final_units,
                    record["tool_results"],
                    customer_turn_plan=customer_turn_plan,
                )
                contract_violations.extend(
                    _final_composer_request_coverage_contract_violations(
                        assistant_text,
                        parsed_final_units,
                        customer_turn_plan=customer_turn_plan,
                    )
                )
                contract_violations.extend(
                    _final_composer_required_faq_fact_contract_violations(
                        parsed_final_units,
                        customer_turn_plan=customer_turn_plan,
                    )
                )
                contract_violations.extend(
                    _final_composer_interaction_contract_violations(
                        assistant_text,
                        self.current_interaction_packet,
                    )
                )
                contract_violations.extend(
                    _final_composer_claim_contract_violations(
                        assistant_text,
                        customer_turn_plan,
                    )
                )
                contract_violations.extend(
                    payment_claim_contract_violations(
                        assistant_text,
                        record["tool_results"],
                    )
                )
                contract_violations.extend(
                    ungrounded_payment_assertion_violations(
                        assistant_text,
                        record["tool_results"],
                    )
                )
                contract_violations.extend(
                    _final_composer_voice_contract_violations(
                        assistant_text,
                        first_turn_intro_context=first_turn_intro_context,
                    )
                )
                contract_violations.extend(
                    _final_composer_service_action_contract_violations(
                        parsed_final_units,
                        validated_installation_context=(
                            validated_installation_context
                        ),
                        customer_turn_plan=customer_turn_plan,
                    )
                )
                record.setdefault("response_guard_events", []).append(
                    {
                        "type": "offline_semantic_audits_deferred",
                        "reason": (
                            "serving_path_uses_structured_composer_and_typed_claim_contracts"
                        ),
                        "faq_evidence_present": bool(
                            _semantic_answer_audit_context(
                                record["tool_results"]
                            )
                        ),
                        "promo_evidence_present": bool(
                            _promo_fact_audit_context(
                                record["tool_results"]
                            )
                        ),
                    }
                )
                if contract_violations and all(
                    isinstance(violation, Mapping)
                    and str(violation.get("type") or "")
                    == "duplicate_supporting_replacement_prose"
                    for violation in contract_violations
                ):
                    (
                        sanitized_text,
                        sanitized_units,
                        removed_sentence_count,
                    ) = _sanitize_duplicate_supporting_replacement_prose(
                        assistant_text,
                        parsed_final_units,
                        customer_turn_plan=customer_turn_plan,
                    )
                    sanitizer_violations = (
                        [
                            *_final_composer_renderer_contract_violations(
                                sanitized_units,
                                record["tool_results"],
                                customer_turn_plan=customer_turn_plan,
                            ),
                            *_final_composer_request_coverage_contract_violations(
                                sanitized_text,
                                sanitized_units,
                                customer_turn_plan=customer_turn_plan,
                            ),
                            *_final_composer_required_faq_fact_contract_violations(
                                sanitized_units,
                                customer_turn_plan=customer_turn_plan,
                            ),
                        ]
                        if removed_sentence_count
                        else list(contract_violations)
                    )
                    record.setdefault("response_guard_events", []).append(
                        {
                            "type": "supporting_replacement_duplicate_prose_sanitized",
                            "reason": "initial_composer_left_only_renderer_owned_supporting_copy",
                            "removed_sentence_count": removed_sentence_count,
                            "remaining_violations": deepcopy(
                                sanitizer_violations
                            ),
                        }
                    )
                    if not sanitizer_violations:
                        assistant_text = sanitized_text
                        parsed_final_units = sanitized_units
                        contract_violations = []
                if contract_violations and all(
                    isinstance(violation, Mapping)
                    and str(violation.get("type") or "")
                    == "service_availability_prose_duplicates_provider_surface"
                    for violation in contract_violations
                ):
                    (
                        sanitized_service_text,
                        sanitized_service_units,
                        removed_service_unit_count,
                    ) = _sanitize_provider_owned_service_claim_prose(
                        assistant_text,
                        customer_turn_plan=customer_turn_plan,
                    )
                    sanitizer_violations = (
                        [
                            *_final_composer_renderer_contract_violations(
                                sanitized_service_units,
                                record["tool_results"],
                                customer_turn_plan=customer_turn_plan,
                            ),
                            *_final_composer_request_coverage_contract_violations(
                                sanitized_service_text,
                                sanitized_service_units,
                                customer_turn_plan=customer_turn_plan,
                            ),
                            *_final_composer_claim_contract_violations(
                                sanitized_service_text,
                                customer_turn_plan,
                            ),
                        ]
                        if removed_service_unit_count
                        else list(contract_violations)
                    )
                    record.setdefault("response_guard_events", []).append(
                        {
                            "type": "provider_owned_service_claim_prose_sanitized",
                            "reason": (
                                "availability_fact_owned_by_exact_query_area_surface"
                            ),
                            "removed_response_unit_count": (
                                removed_service_unit_count
                            ),
                            "remaining_violations": deepcopy(
                                sanitizer_violations
                            ),
                        }
                    )
                    if not sanitizer_violations:
                        assistant_text = sanitized_service_text
                        parsed_final_units = sanitized_service_units
                        contract_violations = []
                        record["final_composer"]["status"] = (
                            "service_claim_surface_sanitized"
                        )
                if contract_violations:
                    semantic_scope_repair = any(
                        str(item.get("type") or "").startswith(
                            ("answer_goal_", "promo_fact_")
                        )
                        for item in contract_violations
                        if isinstance(item, dict)
                    )
                    if semantic_scope_repair:
                        repair_messages = _build_semantic_scope_retry_messages(
                            final_messages=final_messages,
                            semantic_scope_violations=contract_violations,
                            policy_evidence=_semantic_answer_audit_context(
                                record["tool_results"]
                            ),
                            promo_evidence=_promo_fact_audit_context(
                                record["tool_results"]
                            ),
                        )
                    else:
                        repair_messages = [
                            *final_messages,
                            {
                                "role": "assistant",
                                "content": assistant_text,
                            },
                            {
                                "role": "user",
                                "content": json.dumps(
                                    {
                                        "type": "final_composer_contract_repair",
                                        "violations": contract_violations,
                                        "decision_layer_repair": (
                                            _renderer_decision_layer_repair_contract(
                                                parsed_final_units,
                                                customer_turn_plan,
                                            )
                                        ),
                                        "required_commercial_claims": (
                                            _final_composer_required_commercial_claims(
                                                record["tool_results"]
                                            )
                                        ),
                                        "allowed_claim_evidence_refs": list(
                                            customer_turn_plan.get(
                                                "authorized_evidence_refs"
                                            )
                                            or []
                                        ),
                                        "instruction": (
                                        "The prior response is invalid and must not be repeated "
                                        "unchanged. Return the corrected structured response. "
                                        "Return at least one response unit and include exact "
                                        "request_coverage rows for customer_turn_plan.request_obligations. "
                                        "Include a valid "
                                        "interaction_decision when interaction_packet is present, "
                                        "claim_assertions for every factual assertion, plus "
                                        "response_units. Preserve grounded "
                                        "answers. Copy claim evidence refs exactly from "
                                        "allowed_claim_evidence_refs; never invent tool names, "
                                        "tool_results indexes, object paths, or new refs. "
                                        "Omit an optional factual assertion if no listed ref "
                                        "authorizes it. "
                                        "For every answer_goal_* or promo_fact_* violation, "
                                        "remove the unsupported meaning itself; never preserve "
                                        "it by changing or omitting its claim label. Treat each "
                                        "unsupported_claims item as a meaning the corrected "
                                        "response must not assert. Recompose only from the "
                                        "trusted tool results and turn plan. "
                                        "Do not drop an answer listed in "
                                        "progression_context.required_faq_fact_answers. "
                                        "For multiple_customer_decision_layers, preserve every "
                                        "decision_layer_repair.required_surface_refs because those "
                                        "cover independent grounded requests. Remove only deferred "
                                        "optional decision surfaces, and "
                                        "make any CTA ask only for the active decision; do not "
                                        "ask for a deferred city, schedule, payment, or other "
                                        "input in prose. "
                                        "For unauthorized_schedule_mutation_claim, describe the "
                                        "slot only as the customer's selected or preferred "
                                        "schedule for order review. Never describe the schedule, "
                                        "appointment, or installation as confirmed, booked, "
                                        "reserved, or secured unless submit_order is authorized; "
                                        "a later negation does not repair an earlier commitment. "
                                        "When a narrower service or schedule claim is not "
                                        "authorized, preserve the supported FAQ scope, cite its "
                                        "exact evidence_ref under faq_facts, and explicitly say "
                                        "the narrower request is not yet confirmed and still "
                                        "needs checking. Stating only the broad policy can imply "
                                        "coverage and is not enough. Do not present an unrelated "
                                        "customer input as required or sufficient to validate "
                                        "that pending fact unless current provider evidence says "
                                        "so; frame any shopping CTA as a separate optional next "
                                        "step. "
                                        "For brand_facts, list every used structured field in "
                                        "fact_fields and omit any manufacturer warranty field "
                                        "that is not authorized. "
                                        "Honor renderer ownership and the single active "
                                        "customer-input layer. Follow customer_voice_contract and "
                                        "the established friendly customer-service persona. A "
                                        "language-neutral tracked button label, such as a time or "
                                        "Choose action, is not an English-language preference; "
                                        "continue the most recent natural customer language from "
                                        "recent_turns. Otherwise use natural English for an "
                                        "entirely English message, or natural Filipino/Taglish for "
                                        "Filipino/Taglish. "
                                        "Never start with Regarding. Do not expose internal policy, resolver, allowlist, "
                                        "metadata, validation, provider, catalog-search, evidence, "
                                        "or scope wording. State each validated "
                                        "commercial fact once. Use required_commercial_claims as a "
                                        "literal completeness checklist: preserve every method, "
                                        "brand, term, outcome, and non-empty payment_option. Combine "
                                        "related facts naturally, then ask at most one useful next question. "
                                        "Do not explain the repair."
                                        ),
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        ]
                    repair_response = _complete_model_client(
                        self.model_client,
                        messages=repair_messages,
                        tools=[],
                        tool_choice="none",
                        response_format=RuntimeV7FinalResponseModel,
                        max_tokens=FINAL_COMPOSER_MAX_TOKENS,
                        temperature=_final_composer_temperature(),
                    )
                    if semantic_scope_repair:
                        record.setdefault(
                            "response_guard_events", []
                        ).append(
                            {
                                "type": (
                                    "semantic_scope_repair_context_reset"
                                ),
                                "reason": (
                                    "invalid_draft_removed_before_repair"
                                ),
                            }
                        )
                    repair_text = str(repair_response.get("content") or "")
                    repaired_units = _parse_structured_response_units(repair_text)
                    repair_round = "final_composer_repair"
                    repair_input_messages = repair_messages
                    if repaired_units is None:
                        initial_repair_response = deepcopy(repair_response)
                        initial_repair_text = repair_text
                        initial_repair_usage = _llm_usage_summary(
                            initial_repair_response
                        )
                        record["llm_calls"].append(
                            {
                                "round": "final_composer_repair",
                                "component": "final_composer",
                                **_final_composer_attempt_observability(
                                    round_name="final_composer_repair",
                                    attempt_kind=(
                                        "semantic_scope_repair"
                                        if semantic_scope_repair
                                        else None
                                    ),
                                    repair_reason=(
                                        "semantic_scope_violations"
                                        if semantic_scope_repair
                                        else "contract_violations"
                                    ),
                                    violations=contract_violations,
                                ),
                                "model_input_messages": deepcopy(
                                    repair_messages
                                ),
                                "tool_schemas": [],
                                "model_output": deepcopy(
                                    initial_repair_response
                                ),
                                "content": initial_repair_text,
                                "tool_calls": [],
                                "usage": deepcopy(
                                    initial_repair_response.get("usage") or {}
                                ),
                                "cache_usage": deepcopy(
                                    initial_repair_response.get("cache_usage")
                                    or {}
                                ),
                                "request_cache": deepcopy(
                                    initial_repair_response.get("request_cache")
                                    or {}
                                ),
                                "cache_guard_events": deepcopy(
                                    initial_repair_response.get(
                                        "cache_guard_events"
                                    )
                                    or []
                                ),
                                "usage_summary": initial_repair_usage,
                                "latency_ms": initial_repair_response.get(
                                    "latency_ms"
                                ),
                                "finish_reason": initial_repair_response.get(
                                    "finish_reason"
                                ),
                                "response_format": (
                                    "RuntimeV7FinalResponseModel"
                                ),
                            }
                        )
                        repair_format_retry_messages = [
                            *(
                                repair_messages
                                if semantic_scope_repair
                                else final_messages
                            ),
                            {
                                "role": "user",
                                "content": json.dumps(
                                    {
                                        "type": (
                                            "final_composer_contract_format_retry"
                                        ),
                                        "violations": contract_violations,
                                        "authorized_claim_categories": (
                                            customer_turn_plan.get(
                                                "authorized_claim_categories",
                                                [],
                                            )
                                        ),
                                        "allowed_claim_evidence_refs": list(
                                            customer_turn_plan.get(
                                                "authorized_evidence_refs"
                                            )
                                            or []
                                        ),
                                        "required_faq_fact_answers": (
                                            customer_turn_plan.get(
                                                "progression_context", {}
                                            ).get(
                                                "required_faq_fact_answers",
                                                [],
                                            )
                                        ),
                                        "required_commercial_claims": (
                                            _final_composer_required_commercial_claims(
                                                record["tool_results"]
                                            )
                                        ),
                                        "instruction": (
                                            "The contract repair ended without a valid schema "
                                            "object. Return one corrected object immediately, "
                                            "with no analysis outside it. Keep it concise. Remove "
                                            "or narrow every listed unauthorized claim, use only "
                                            "authorized claim categories and exact evidence refs, "
                                            "preserve required FAQ answers and renderer surfaces, "
                                            "and ask at most one next question."
                                        ),
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        ]
                        repair_response = _complete_model_client(
                            self.model_client,
                            messages=repair_format_retry_messages,
                            tools=[],
                            tool_choice="none",
                            response_format=RuntimeV7FinalResponseModel,
                            max_tokens=FINAL_COMPOSER_MAX_TOKENS,
                            temperature=0.0,
                        )
                        repair_text = str(
                            repair_response.get("content") or ""
                        )
                        repaired_units = _parse_structured_response_units(
                            repair_text
                        )
                        repair_round = (
                            "final_composer_repair_format_retry"
                        )
                        repair_input_messages = (
                            repair_format_retry_messages
                        )
                        record.setdefault(
                            "response_guard_events", []
                        ).append(
                            {
                                "type": (
                                    "final_composer_repair_format_retry"
                                ),
                                "reason": "repair_response_format_invalid",
                                "initial_finish_reason": (
                                    initial_repair_response.get(
                                        "finish_reason"
                                    )
                                ),
                                "retry_finish_reason": repair_response.get(
                                    "finish_reason"
                                ),
                                "status": (
                                    "recovered"
                                    if repaired_units is not None
                                    else "failed"
                                ),
                            }
                        )
                    remaining_violations = (
                        [
                            *_final_composer_renderer_contract_violations(
                                repaired_units,
                                record["tool_results"],
                                customer_turn_plan=customer_turn_plan,
                            ),
                            *_final_composer_request_coverage_contract_violations(
                                repair_text,
                                repaired_units,
                                customer_turn_plan=customer_turn_plan,
                            ),
                            *_final_composer_required_faq_fact_contract_violations(
                                repaired_units,
                                customer_turn_plan=customer_turn_plan,
                            ),
                            *_final_composer_interaction_contract_violations(
                                repair_text,
                                self.current_interaction_packet,
                            ),
                            *_final_composer_claim_contract_violations(
                                repair_text,
                                customer_turn_plan,
                            ),
                            *payment_claim_contract_violations(
                                repair_text,
                                record["tool_results"],
                            ),
                            *ungrounded_payment_assertion_violations(
                                repair_text,
                                record["tool_results"],
                            ),
                            *_final_composer_voice_contract_violations(
                                repair_text,
                                first_turn_intro_context=(
                                    first_turn_intro_context
                                ),
                            ),
                            *_final_composer_service_action_contract_violations(
                                repaired_units,
                                validated_installation_context=(
                                    validated_installation_context
                                ),
                                customer_turn_plan=customer_turn_plan,
                            ),
                        ]
                        if repaired_units is not None
                        else [{"type": "invalid_response_format"}]
                    )
                    (
                        sanitized_repair_text,
                        sanitized_repaired_units,
                        sanitizer_violations,
                        removed_service_unit_count,
                    ) = _sanitize_post_repair_provider_owned_service_copy(
                        repair_text,
                        repaired_units,
                        remaining_violations,
                        tool_results=record["tool_results"],
                        customer_turn_plan=customer_turn_plan,
                    )
                    if removed_service_unit_count:
                        record.setdefault("response_guard_events", []).append(
                            {
                                "type": "provider_owned_service_claim_prose_sanitized",
                                "reason": (
                                    "contract_repair_left_only_provider_owned_"
                                    "service_copy"
                                ),
                                "removed_response_unit_count": (
                                    removed_service_unit_count
                                ),
                                "remaining_violations": deepcopy(
                                    sanitizer_violations
                                ),
                            }
                        )
                        if not sanitizer_violations:
                            repair_text = sanitized_repair_text
                            repaired_units = sanitized_repaired_units
                            remaining_violations = []
                    if (
                        repaired_units is not None
                        and remaining_violations
                        and all(
                            str(violation.get("type") or "")
                            == "duplicate_supporting_replacement_prose"
                            for violation in remaining_violations
                            if isinstance(violation, dict)
                        )
                        and all(
                            isinstance(violation, dict)
                            for violation in remaining_violations
                        )
                    ):
                        (
                            sanitized_repair_text,
                            sanitized_repaired_units,
                            sanitized_sentence_count,
                        ) = _sanitize_duplicate_supporting_replacement_prose(
                            repair_text,
                            repaired_units,
                            customer_turn_plan=customer_turn_plan,
                        )
                        if sanitized_sentence_count:
                            sanitizer_violations = [
                                *_final_composer_renderer_contract_violations(
                                    sanitized_repaired_units,
                                    record["tool_results"],
                                    customer_turn_plan=customer_turn_plan,
                                ),
                                *_final_composer_request_coverage_contract_violations(
                                    sanitized_repair_text,
                                    sanitized_repaired_units,
                                    customer_turn_plan=customer_turn_plan,
                                ),
                                *_final_composer_required_faq_fact_contract_violations(
                                    sanitized_repaired_units,
                                    customer_turn_plan=customer_turn_plan,
                                ),
                            ]
                            record.setdefault(
                                "response_guard_events", []
                            ).append(
                                {
                                    "type": (
                                        "supporting_replacement_duplicate_prose_sanitized"
                                    ),
                                    "reason": (
                                        "repair_left_only_renderer_owned_supporting_copy"
                                    ),
                                    "removed_sentence_count": (
                                        sanitized_sentence_count
                                    ),
                                    "remaining_violations": deepcopy(
                                        sanitizer_violations
                                    ),
                                }
                            )
                            if not sanitizer_violations:
                                repair_text = sanitized_repair_text
                                repaired_units = sanitized_repaired_units
                                remaining_violations = []
                    if repaired_units is not None and semantic_scope_repair:
                        record.setdefault("response_guard_events", []).append(
                            {
                                "type": "semantic_repair_reaudit_skipped",
                                "reason": (
                                    "single_model_audit_then_grounded_model_repair"
                                ),
                            }
                        )
                    semantic_scope_violations = [
                        violation
                        for violation in remaining_violations
                        if isinstance(violation, dict)
                        and (
                            str(
                                violation.get("type") or ""
                            ).startswith(
                                ("answer_goal_", "promo_fact_")
                            )
                            or str(violation.get("type") or "")
                            in {
                                "unknown_claim_evidence_ref",
                                "unauthorized_claim_category",
                            }
                        )
                    ]
                    if (
                        repaired_units is not None
                        and not semantic_scope_repair
                        and any(
                            str(violation.get("type") or "").startswith(
                                ("answer_goal_", "promo_fact_")
                            )
                            for violation in semantic_scope_violations
                        )
                        and len(semantic_scope_violations)
                        == len(remaining_violations)
                    ):
                        record["llm_calls"].append(
                            {
                                "round": repair_round,
                                "component": "final_composer",
                                **_final_composer_attempt_observability(
                                    round_name=repair_round,
                                    repair_reason="contract_violations",
                                    violations=contract_violations,
                                ),
                                "model_input_messages": deepcopy(
                                    repair_input_messages
                                ),
                                "tool_schemas": [],
                                "model_output": deepcopy(repair_response),
                                "content": repair_text,
                                "tool_calls": [],
                                "usage": deepcopy(
                                    repair_response.get("usage") or {}
                                ),
                                "cache_usage": deepcopy(
                                    repair_response.get("cache_usage") or {}
                                ),
                                "request_cache": deepcopy(
                                    repair_response.get("request_cache") or {}
                                ),
                                "cache_guard_events": deepcopy(
                                    repair_response.get(
                                        "cache_guard_events"
                                    )
                                    or []
                                ),
                                "usage_summary": _llm_usage_summary(
                                    repair_response
                                ),
                                "latency_ms": repair_response.get(
                                    "latency_ms"
                                ),
                                "finish_reason": repair_response.get(
                                    "finish_reason"
                                ),
                                "response_format": (
                                    "RuntimeV7FinalResponseModel"
                                ),
                            }
                        )
                        semantic_scope_messages = (
                            _build_semantic_scope_retry_messages(
                                final_messages=final_messages,
                                semantic_scope_violations=(
                                    semantic_scope_violations
                                ),
                                policy_evidence=(
                                    _semantic_answer_audit_context(
                                        record["tool_results"]
                                    )
                                ),
                                promo_evidence=_promo_fact_audit_context(
                                    record["tool_results"]
                                ),
                            )
                        )
                        semantic_scope_response = _complete_model_client(
                            self.model_client,
                            messages=semantic_scope_messages,
                            tools=[],
                            tool_choice="none",
                            response_format=RuntimeV7FinalResponseModel,
                            max_tokens=FINAL_COMPOSER_MAX_TOKENS,
                            temperature=0.0,
                        )
                        semantic_scope_text = str(
                            semantic_scope_response.get("content") or ""
                        )
                        semantic_scope_units = (
                            _parse_structured_response_units(
                                semantic_scope_text
                            )
                        )
                        semantic_scope_remaining = (
                            [
                                *_final_composer_renderer_contract_violations(
                                    semantic_scope_units,
                                    record["tool_results"],
                                    customer_turn_plan=customer_turn_plan,
                                ),
                                *_final_composer_request_coverage_contract_violations(
                                    semantic_scope_text,
                                    semantic_scope_units,
                                    customer_turn_plan=customer_turn_plan,
                                ),
                                *_final_composer_required_faq_fact_contract_violations(
                                    semantic_scope_units,
                                    customer_turn_plan=customer_turn_plan,
                                ),
                                *_final_composer_interaction_contract_violations(
                                    semantic_scope_text,
                                    self.current_interaction_packet,
                                ),
                                *_final_composer_claim_contract_violations(
                                    semantic_scope_text,
                                    customer_turn_plan,
                                ),
                                *payment_claim_contract_violations(
                                    semantic_scope_text,
                                    record["tool_results"],
                                ),
                                *ungrounded_payment_assertion_violations(
                                    semantic_scope_text,
                                    record["tool_results"],
                                ),
                                *_final_composer_voice_contract_violations(
                                    semantic_scope_text,
                                    first_turn_intro_context=(
                                        first_turn_intro_context
                                    ),
                                ),
                                *_final_composer_service_action_contract_violations(
                                    semantic_scope_units,
                                    validated_installation_context=(
                                        validated_installation_context
                                    ),
                                    customer_turn_plan=customer_turn_plan,
                                ),
                            ]
                            if semantic_scope_units is not None
                            else [{"type": "invalid_response_format"}]
                        )
                        record.setdefault(
                            "response_guard_events", []
                        ).append(
                            {
                                "type": (
                                    "final_composer_semantic_scope_repair"
                                ),
                                "initial_violations": deepcopy(
                                    semantic_scope_violations
                                ),
                                "remaining_violations": deepcopy(
                                    semantic_scope_remaining
                                ),
                                "status": (
                                    "recovered"
                                    if not semantic_scope_remaining
                                    else "failed"
                                ),
                            }
                        )
                        repair_response = semantic_scope_response
                        repair_text = semantic_scope_text
                        repaired_units = semantic_scope_units
                        repair_round = (
                            "final_composer_semantic_scope_repair"
                        )
                        repair_input_messages = semantic_scope_messages
                        remaining_violations = semantic_scope_remaining
                    repair_usage = _llm_usage_summary(repair_response)
                    observed_repair_reason = (
                        "invalid_repair_response_format"
                        if repair_round
                        == "final_composer_repair_format_retry"
                        else "semantic_scope_violations"
                        if (
                            repair_round
                            == "final_composer_semantic_scope_repair"
                            or semantic_scope_repair
                        )
                        else "contract_violations"
                    )
                    record["llm_calls"].append(
                        {
                            "round": repair_round,
                            "component": "final_composer",
                            **_final_composer_attempt_observability(
                                round_name=repair_round,
                                attempt_kind=(
                                    "semantic_scope_repair"
                                    if semantic_scope_repair
                                    and repair_round
                                    == "final_composer_repair"
                                    else None
                                ),
                                repair_reason=observed_repair_reason,
                                violations=(
                                    semantic_scope_violations
                                    if repair_round
                                    == "final_composer_semantic_scope_repair"
                                    else contract_violations
                                ),
                            ),
                            "model_input_messages": deepcopy(
                                repair_input_messages
                            ),
                            "tool_schemas": [],
                            "model_output": deepcopy(repair_response),
                            "content": repair_text,
                            "tool_calls": [],
                            "usage": deepcopy(repair_response.get("usage") or {}),
                            "cache_usage": deepcopy(
                                repair_response.get("cache_usage") or {}
                            ),
                            "request_cache": deepcopy(
                                repair_response.get("request_cache") or {}
                            ),
                            "cache_guard_events": deepcopy(
                                repair_response.get("cache_guard_events") or []
                            ),
                            "usage_summary": repair_usage,
                            "latency_ms": repair_response.get("latency_ms"),
                            "finish_reason": repair_response.get("finish_reason"),
                            "response_format": "RuntimeV7FinalResponseModel",
                        }
                    )
                    record.setdefault("response_guard_events", []).append(
                        {
                            "type": "final_composer_contract_repair",
                            "reason": "renderer_owned_input_sequence",
                            "violations": deepcopy(contract_violations),
                            "remaining_violations": deepcopy(remaining_violations),
                        }
                    )
                    if not remaining_violations and repaired_units is not None:
                        assistant_text = repair_text
                        parsed_final_units = repaired_units
                        final_composer_response = deepcopy(repair_response)
                        record["final_composer"].update(
                            {
                                "status": "repaired",
                                "model_output": deepcopy(repair_response),
                                "usage_summary": repair_usage,
                            }
                        )
                    else:
                        policy_scope_failed = any(
                            str(item.get("type") or "").startswith(
                                "answer_goal_"
                            )
                            for item in remaining_violations
                            if isinstance(item, dict)
                        )
                        promo_scope_failed = any(
                            str(item.get("type") or "").startswith(
                                "promo_fact_"
                            )
                            for item in remaining_violations
                            if isinstance(item, dict)
                        )
                        fallback_units = (
                            _safe_semantic_answer_units(
                                record["tool_results"],
                                include_authored_answers=(
                                    _semantic_fallback_includes_authored_answers(
                                        initial_violations=contract_violations,
                                        remaining_violations=remaining_violations,
                                    )
                                ),
                            )
                            if policy_scope_failed
                            else _safe_promo_fact_units(
                                record["tool_results"]
                            )
                            if promo_scope_failed
                            else _enforce_renderer_owned_unit_contract(
                                repaired_units or [],
                                record["tool_results"],
                                customer_turn_plan=customer_turn_plan,
                                fallback_response_units=parsed_final_units,
                            )
                        )
                        if policy_scope_failed:
                            record.setdefault(
                                "response_guard_events", []
                            ).append(
                                {
                                    "type": (
                                        "answer_goal_safe_fallback_used"
                                    ),
                                    "reason": (
                                        "semantic_scope_audit_not_satisfied"
                                    ),
                                }
                            )
                        elif promo_scope_failed:
                            record.setdefault(
                                "response_guard_events", []
                            ).append(
                                {
                                    "type": "promo_fact_safe_fallback_used",
                                    "reason": (
                                        "semantic_scope_audit_not_satisfied"
                                    ),
                                }
                            )
                        assistant_text = json.dumps(
                            {"response_units": fallback_units},
                            ensure_ascii=False,
                        )
                        parsed_final_units = fallback_units
                        record["final_composer"]["status"] = (
                            "answer_goal_safe_fallback"
                            if policy_scope_failed
                            else "promo_fact_safe_fallback"
                            if promo_scope_failed
                            else "renderer_contract_fallback"
                        )
        else:
            record["final_composer"] = {
                "status": "skipped",
                "reason": "no_tool_results_or_model_client_without_response_format",
            }
            if record["tool_results"]:
                record.setdefault("response_guard_events", []).append(
                    {
                        "type": "response_unit_recovery_pending",
                        "reason": "model_client_without_response_format",
                        "tool_result_count": len(record["tool_results"]),
                    }
                )

        if _requires_provider_owned_empty_promo_result(
            record["tool_results"]
        ):
            parsed_final_units = _safe_promo_fact_units(
                record["tool_results"]
            )
            assistant_text = json.dumps(
                {"response_units": parsed_final_units},
                ensure_ascii=False,
            )
            record["final_composer"]["status"] = (
                "promo_fact_scoped_result"
            )
            record.setdefault("response_guard_events", []).append(
                {
                    "type": "promo_fact_scoped_result_rendered",
                    "reason": (
                        "provider_owned_empty_scope_and_surface_boundary"
                    ),
                }
            )

        if self.current_interaction_packet:
            proposed_decision = _parse_structured_interaction_decision(
                assistant_text
            )
            decision_validation = validate_interaction_decision(
                self.current_interaction_packet,
                proposed_decision,
            )
            if decision_validation.get("status") != "valid":
                fallback_decision = default_interaction_decision(
                    self.current_interaction_packet
                )
                decision_validation = {
                    **validate_interaction_decision(
                        self.current_interaction_packet,
                        fallback_decision,
                    ),
                    "fallback_used": True,
                    "model_validation_reasons": list(
                        decision_validation.get("validation_reasons") or []
                    ),
                }
                if decision_validation.get("needs_clarification"):
                    assistant_text = _interaction_clarification_response(
                        self.current_interaction_packet,
                        decision=fallback_decision,
                    )
            record["interaction_packet"] = deepcopy(
                self.current_interaction_packet
            )
            record["interaction_decision_validation"] = deepcopy(
                decision_validation
            )

        if not final_composer_output_accepted(record):
            fallback_payment_violations = [
                *payment_claim_contract_violations(
                    assistant_text,
                    record["tool_results"],
                ),
                *ungrounded_payment_assertion_violations(
                    assistant_text,
                    record["tool_results"],
                ),
            ]
            if fallback_payment_violations:
                record.setdefault("response_guard_events", []).append(
                    {
                        "type": "unsupported_payment_claim_fallback",
                        "reason": "structured_final_composer_unavailable_or_failed",
                        "violations": deepcopy(fallback_payment_violations),
                    }
                )
                safe_payment_text = _unsupported_payment_claim_fallback_text(
                    record["tool_results"]
                )
                if (
                    parsed_final_units is not None
                    and final_composer_surface_plan_authoritative(record)
                ):
                    parsed_final_units = _payment_fallback_response_units(
                        parsed_final_units,
                        safe_payment_text,
                    )
                    assistant_text = json.dumps(
                        {"response_units": parsed_final_units},
                        ensure_ascii=False,
                    )
                    preserved_surface_count = sum(
                        1
                        for unit in parsed_final_units
                        if isinstance(unit, dict)
                        and str(unit.get("type") or "")
                        == "render_surface"
                    )
                    record["final_composer"]["status"] = (
                        "payment_claim_safe_surface_fallback"
                    )
                    record.setdefault(
                        "response_guard_events", []
                    ).append(
                        {
                            "type": (
                                "payment_claim_safe_surface_fallback_used"
                            ),
                            "reason": (
                                "unsupported_payment_prose_replaced_with_"
                                "provider_grounded_fallback"
                            ),
                            "preserved_surface_count": (
                                preserved_surface_count
                            ),
                        }
                    )
                else:
                    assistant_text = safe_payment_text

        runtime_final_response = _compose_runtime_final_response(
            assistant_text,
            record["tool_results"],
            current_user_message=user_message,
            recent_turns=context_recent_turns,
            active_working_memory=active_memory_text,
            first_turn_intro_mode=effective_first_turn_intro_mode,
            include_product_inclusions=not bool(self.product_inclusions_sent),
            product_observation_store=self.tools.store,
            pricing_repair_callback=lambda draft, card, unsupported: self._repair_unsupported_visible_product_pricing(
                current_user_message=user_message,
                draft_response=draft,
                card=card,
                unsupported_amounts=unsupported,
                record=record,
            ),
            guard_events=record.setdefault("response_guard_events", []),
            selected_product_context=self.latest_selected_product_context,
            order_readiness=order_readiness.to_dict(),
            background_signals=state_context["background_signals"],
            customer_turn_plan=customer_turn_plan,
            model_composed_complete_turn=(
                final_composer_surface_plan_authoritative(record)
            ),
            suppress_runtime_surfaces=bool(
                (
                    record.get("interaction_decision_validation")
                    if isinstance(
                        record.get("interaction_decision_validation"),
                        dict,
                    )
                    else {}
                ).get("needs_clarification")
            ),
        )
        if _should_offer_location_contact_fallback(
            background_signals=state_context["background_signals"],
            lead_qualification=lead_qualification,
            selected_product_context=self.latest_selected_product_context,
            tool_results=record["tool_results"],
            interaction_packet=self.current_interaction_packet,
            validated_choice_context=self.current_validated_choice_context,
        ):
            runtime_final_response = _location_contact_fallback_text()
            assistant_text = runtime_final_response
            suppressed_surface_tools = {
                str(value or "").strip()
                for value in record.get("suppressed_channel_surface_tools") or []
                if str(value or "").strip()
            }
            suppressed_surface_tools.add("present_serviceable_location_choices")
            record["suppressed_channel_surface_tools"] = sorted(
                suppressed_surface_tools
            )
            record.pop("location_choice_surface", None)
            record["location_choice_surface_status"] = {
                "status": "not_attached",
                "reason": "customer_location_unavailable_contact_fallback",
                "slots_authorized": False,
            }
            record.setdefault("response_guard_events", []).append(
                {
                    "type": "location_contact_fallback_rendered",
                    "reason": "customer_cannot_provide_location_after_product_progression",
                    "location_serviceability_status": "pending",
                    "suppressed_surface_tool": "present_serviceable_location_choices",
                }
            )
        business_location_guard = guard_business_location_response(
            customer_message=user_message,
            response_text=runtime_final_response,
            customer_location_known=_has_reusable_customer_location_signal(
                state_context["background_signals"]
            ),
            isolated_goal=(
                not record["tool_results"]
                and not self.current_interaction_packet
                and not self.current_validated_choice_context
                and not self.latest_selected_product_context
                and len(customer_turn_plan.get("request_obligations") or [])
                <= 1
            ),
        )
        if business_location_guard.get("changed"):
            runtime_final_response = str(
                business_location_guard.get("response") or ""
            ).strip()
            # The channel renderer prefers assistant_text over
            # runtime_final_response when both are renderable. Synchronize the
            # accepted boundary text so a rejected model paragraph cannot be
            # reintroduced after the harness finalizes the turn.
            assistant_text = runtime_final_response
            record.setdefault("response_guard_events", []).append(
                {
                    "type": "business_location_response_boundary",
                    "classification": business_location_guard.get(
                        "classification"
                    ),
                    "reason": business_location_guard.get("reason"),
                    "evidence_ref": business_location_guard.get(
                        "evidence_ref"
                    ),
                }
            )
        if not runtime_final_response.strip():
            record.setdefault("tool_retry_events", []).append(
                {
                    "round": "finalize",
                    "type": "empty_final_response_fallback",
                    "assistant_text": assistant_text,
                }
            )
            runtime_final_response = _empty_runtime_fallback_response(user_message)
        return self._finalize_turn_record(
            record=record,
            turn_index=turn_index,
            user_message=user_message,
            assistant_text=assistant_text,
            draft_assistant_text=draft_assistant_text,
            final_composer_response=final_composer_response,
            runtime_final_response=runtime_final_response,
            conversation_evidence=conversation_evidence,
            state_context=state_context,
            external_evidence_refs=external_evidence_refs,
            existing_tags=existing_tags,
        )

    def _execute_tool_call_with_turn_cache(
        self,
        call: Dict[str, Any],
        execution_args: Dict[str, Any],
        *,
        round_index: int,
        record: Dict[str, Any],
        tool_result_cache: Dict[str, Dict[str, Any]],
        allowed_tool_names: Sequence[str],
        current_user_message: str,
        active_working_memory: str,
        background_signals: Sequence[Dict[str, Any]],
        order_readiness: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], int, bool]:
        name = str(call.get("name") or "")
        allowed = {str(tool_name or "").strip() for tool_name in allowed_tool_names or [] if str(tool_name or "").strip()}
        preloaded = _runtime_preloaded_tool_result_hit(
            name,
            record.get("tool_results") or [],
        )
        if preloaded:
            compact_reuse = _reused_tool_compact_result(
                name,
                preloaded.get("result") or {},
            )
            record.setdefault("tool_dedupe_events", []).append(
                {
                    "round": round_index,
                    "type": "runtime_preloaded_tool_call_reused",
                    "name": name,
                    "tool_call_id": call.get("id"),
                    "first_round": preloaded.get("round"),
                    "first_tool_call_id": preloaded.get("tool_call_id"),
                    "args": deepcopy(execution_args),
                    "observation_ref": compact_reuse.get("observation_ref"),
                    "presentation_ref": compact_reuse.get("presentation_ref"),
                }
            )
            return (
                deepcopy(preloaded.get("full_result") or {}),
                compact_reuse,
                0,
                True,
            )
        if name not in allowed:
            tool_result = {
                "status": "error",
                "error_type": "tool_not_exposed",
                "tool_name": name,
                "reason": "The model requested a tool that was not exposed in the current Runtime V7 tool schema.",
                "allowed_tools": sorted(allowed),
                "read_only": True,
            }
            compact_result = {
                "status": "error",
                "error_type": "tool_not_exposed",
                "tool_name": name,
                "reason": "Tool was not exposed for this turn. Use only the available tools or ask the customer the next needed step.",
                "allowed_tools": sorted(allowed),
                "read_only": True,
            }
            record.setdefault("tool_guard_events", []).append(
                {
                    "round": round_index,
                    "type": "tool_not_exposed",
                    "name": name,
                    "tool_call_id": call.get("id"),
                    "allowed_tools": sorted(allowed),
                }
            )
            return tool_result, compact_result, 0, False
        if name == "request_human_handoff":
            decision = self._evaluate_human_handoff_decision(
                current_user_message=current_user_message,
                record=record,
            )
            if decision.get("status") != "authorized":
                tool_result = {
                    "status": "not_requested",
                    "reason": decision.get("reason"),
                    "decision": decision.get("decision"),
                    "human_assignment_confirmed": False,
                    "automated_sales_replies": "continue",
                    "read_only": True,
                }
                record.setdefault("tool_guard_events", []).append(
                    {
                        "round": round_index,
                        "type": "human_handoff_not_authorized",
                        "name": name,
                        "tool_call_id": call.get("id"),
                        "decision": decision.get("decision"),
                    }
                )
                return tool_result, _compact_tool_result(name, tool_result), 0, False
        location_plan_rejection = (
            _location_tool_plan_rejection(
                name=name,
                execution_args=execution_args,
                validated_choice_context=self.current_validated_choice_context,
                background_signals=background_signals,
                order_readiness=order_readiness,
                current_user_message=current_user_message,
                has_usable_product_context=(
                    capability_profile_has_usable_product_context(
                        record.get("capability_profile") or {}
                    )
                    if isinstance(record.get("capability_profile"), dict)
                    and record.get("capability_profile")
                    else None
                ),
            )
        )
        if location_plan_rejection:
            result_status = _location_plan_rejection_result_status(
                location_plan_rejection
            )
            tool_result = {
                "status": result_status,
                "tool_name": name,
                "reason": location_plan_rejection["reason"],
                "required_decision_layer": location_plan_rejection.get(
                    "required_decision_layer",
                    "city",
                ),
                "slots_authorized": False,
                "read_only": True,
            }
            if result_status == "error":
                tool_result["error_type"] = "tool_plan_not_authorized"
            else:
                tool_result["outcome_type"] = "deterministic_progression_redirect"
            if name == "find_installation_slots":
                if (
                    location_plan_rejection.get("required_decision_layer")
                    == "service_partner_coverage"
                ):
                    tool_result["authorized_alternative_plan"] = {
                        "tool_name": "find_installation_partners",
                        "when": (
                            "Use the normalized customer anchor to check "
                            "partner coverage before slot discovery."
                        ),
                        "result_semantics": (
                            "Establishes read-only partner coverage for only "
                            "the queried area."
                        ),
                    }
                else:
                    tool_result["authorized_alternative_plan"] = {
                        "tool_name": "find_installation_slots",
                        "discovery_mode": "recommend_serviceable_cities",
                        "when": (
                            "Use when installation lookup is active but only a "
                            "validated serviceable province is known."
                        ),
                        "result_semantics": (
                            "Ranks city choices with read-only availability "
                            "previews; it does not select a city or schedule."
                        ),
                    }
            compact_result = deepcopy(tool_result)
            record.setdefault("tool_guard_events", []).append(
                {
                    "round": round_index,
                    "type": "tool_plan_rejected",
                    "name": name,
                    "tool_call_id": call.get("id"),
                    **deepcopy(location_plan_rejection),
                }
            )
            return tool_result, compact_result, 0, False
        if name == "present_promo_gallery":
            self._scope_model_promo_gallery_to_exact_catalog_title(
                execution_args,
                record=record,
                round_index=round_index,
                tool_call_id=call.get("id"),
            )
        if (
            self.current_interaction_packet.get("state_commit_deferred")
            and name
            in {
                "build_order_payload",
                "validate_installation_slot",
                "submit_order",
                "prepare_payment_request",
            }
        ):
            tool_result = {
                "status": "error",
                "error_type": "interaction_resolution_required",
                "tool_name": name,
                "reason": (
                    "A tracked choice sequence must be resolved before this "
                    "order or payment action can be authorized."
                ),
                "read_only": True,
            }
            compact_result = deepcopy(tool_result)
            record.setdefault("tool_guard_events", []).append(
                {
                    "round": round_index,
                    "type": "interaction_side_effect_deferred",
                    "name": name,
                    "tool_call_id": call.get("id"),
                    "batch_ref": self.current_interaction_packet.get(
                        "batch_ref"
                    ),
                }
            )
            return tool_result, compact_result, 0, False
        cache_key = _tool_execution_cache_key(name, execution_args)
        cached = tool_result_cache.get(cache_key)
        if not cached:
            cached = _semantic_tool_result_cache_hit(name, execution_args, tool_result_cache)
        if cached:
            compact_reuse = _reused_tool_compact_result(name, cached.get("compact_result") or {})
            record.setdefault("tool_dedupe_events", []).append(
                {
                    "round": round_index,
                    "type": "duplicate_tool_call_reused",
                    "name": name,
                    "tool_call_id": call.get("id"),
                    "first_round": cached.get("round"),
                    "first_tool_call_id": cached.get("tool_call_id"),
                    "args": deepcopy(execution_args),
                    "cache_key": cache_key,
                    "cache_match_type": cached.get("cache_match_type") or "exact",
                    "observation_ref": compact_reuse.get("observation_ref"),
                    "presentation_ref": compact_reuse.get("presentation_ref"),
                }
            )
            return (
                deepcopy(cached.get("full_result") or {}),
                compact_reuse,
                0,
                True,
            )

        tool_started = time.perf_counter()
        tool_result = self._execute_tool(
            name,
            execution_args,
            current_user_message=current_user_message,
            active_working_memory=active_working_memory,
            background_signals=background_signals,
            order_readiness=order_readiness,
        )
        latency_ms = int((time.perf_counter() - tool_started) * 1000)
        compact_result = _compact_tool_result(name, tool_result)
        tool_result_cache[cache_key] = {
            "round": round_index,
            "tool_call_id": call.get("id"),
            "name": name,
            "args": deepcopy(execution_args),
            "compact_result": deepcopy(compact_result),
            "full_result": deepcopy(tool_result),
        }
        return tool_result, compact_result, latency_ms, False

    def _scope_model_promo_gallery_to_exact_catalog_title(
        self,
        execution_args: Dict[str, Any],
        *,
        record: Dict[str, Any],
        round_index: int,
        tool_call_id: Any,
    ) -> None:
        """Keep a model-requested gallery within an exact catalog-title search.

        The model decides whether the promo surface is useful. The catalog
        remains authoritative for which reviewed campaign an exact-title
        lookup may render, including when search and presentation are emitted
        as separate model tool calls in the same round.
        """

        search_result: Mapping[str, Any] = {}
        for item in reversed(record.get("tool_results") or []):
            if not isinstance(item, dict) or item.get("name") != "search_promo_catalog":
                continue
            candidate = item.get("full_result")
            if isinstance(candidate, Mapping) and candidate.get("status") == "ok":
                search_result = candidate
                break
        if not search_result:
            return
        exact_refs = _exact_title_promo_refs(
            search_result,
            query=str(search_result.get("query") or ""),
        )
        if not exact_refs:
            return
        proposed_refs = [
            str(value or "").strip()
            for value in execution_args.get("promo_refs") or []
            if str(value or "").strip()
        ]
        if proposed_refs == exact_refs:
            return
        execution_args["promo_refs"] = exact_refs
        record.setdefault("tool_arg_normalization_events", []).append(
            {
                "round": round_index,
                "type": "exact_catalog_title_gallery_scope",
                "name": "present_promo_gallery",
                "tool_call_id": tool_call_id,
                "proposed_promo_refs": proposed_refs,
                "authorized_promo_refs": list(exact_refs),
            }
        )

    def _evaluate_human_handoff_decision(
        self,
        *,
        current_user_message: str,
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Semantically authorize takeover without raw-text keyword rules."""

        existing = record.get("human_handoff_decision")
        if isinstance(existing, dict):
            return existing
        if not _model_client_supports_response_format(self.model_client):
            decision = {
                "status": "not_authorized",
                "decision": "unclear",
                "reason": "semantic_decision_model_unavailable",
            }
            record["human_handoff_decision"] = decision
            return decision

        messages = _build_human_handoff_decision_messages(
            current_user_message=current_user_message,
            recent_turns=self.recent_turns,
        )
        started = time.perf_counter()
        response = self.model_client.complete(
            messages=messages,
            tools=[],
            tool_choice="none",
            response_format=RuntimeV7HumanHandoffDecisionModel,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        content = str(response.get("content") or "")
        usage_summary = _llm_usage_summary(response)
        record["llm_calls"].append(
            {
                "round": "human_handoff_decision",
                "component": "human_handoff_decision",
                "model_input_messages": deepcopy(messages),
                "tool_schemas": [],
                "model_output": deepcopy(response),
                "content": content,
                "tool_calls": [],
                "usage": deepcopy(response.get("usage") or {}),
                "cache_usage": deepcopy(response.get("cache_usage") or {}),
                "request_cache": deepcopy(response.get("request_cache") or {}),
                "cache_guard_events": deepcopy(
                    response.get("cache_guard_events") or []
                ),
                "usage_summary": usage_summary,
                "latency_ms": response.get("latency_ms", latency_ms),
                "finish_reason": response.get("finish_reason"),
                "response_format": "RuntimeV7HumanHandoffDecisionModel",
            }
        )
        try:
            parsed = RuntimeV7HumanHandoffDecisionModel.model_validate_json(
                content
            )
            payload = parsed.model_dump()
        except (TypeError, ValueError):
            payload = {
                "decision": "unclear",
                "explicit_human_takeover": False,
                "explicit_stop_automation": False,
                "reason": "invalid_semantic_decision",
            }
        authorized = payload.get("decision") == "request_now" and bool(
            payload.get("explicit_human_takeover")
            or payload.get("explicit_stop_automation")
        )
        decision = {
            **payload,
            "status": "authorized" if authorized else "not_authorized",
        }
        record["human_handoff_decision"] = decision
        return decision

    def run_conversation(self, messages: Sequence[str]) -> Dict[str, Any]:
        """Run a deterministic message sequence and return aggregate diagnostics."""

        for message in messages:
            self.run_turn(message)
        return {
            "turn_count": len(self.turn_records),
            "turns": deepcopy(self.turn_records),
            "llm_usage_summary": _aggregate_turn_usage(self.turn_records),
            "final_observation_headers": self.tools.store.headers(limit=5),
            "final_service_observation_headers": self.service_tools.store.headers(limit=5),
            "final_background_signal_ledger": self.signal_ledger.load(self.session_id),
            "final_order_summary_snapshot": deepcopy(self.latest_order_summary_snapshot),
            "final_order_payload_refs": self._order_payload_refs(),
            "final_submitted_order_context": deepcopy(self.latest_submitted_order_context),
            "final_order_details_context": deepcopy(self.latest_order_details_context),
            "final_payment_request_refs": self._payment_request_refs(),
            "final_recent_turns": deepcopy(self.recent_turns),
            "final_active_working_memory": self.memory_updater.load(self.session_id).to_dict(),
            "final_tag_ledger": deepcopy(self.tag_ledger),
        }


    def _repair_unsupported_visible_product_pricing(
        self,
        *,
        current_user_message: str,
        draft_response: str,
        card: Dict[str, Any],
        unsupported_amounts: Sequence[float],
        record: Dict[str, Any],
    ) -> str:
        """Use a tiny model call to repair ungrounded product-card pricing text."""

        if not _model_client_supports_response_format(self.model_client):
            return ""
        messages = _build_pricing_repair_messages(
            current_user_message=current_user_message,
            draft_response=draft_response,
            card=card,
            unsupported_amounts=unsupported_amounts,
        )
        started = time.perf_counter()
        try:
            response = _complete_model_client(
                self.model_client,
                messages=messages,
                tools=[],
                tool_choice="none",
                response_format=RuntimeV7PricingRepairResponseModel,
                max_tokens=PRICING_REPAIR_MAX_TOKENS,
            )
        except Exception as exc:  # pragma: no cover - model outages are integration-side.
            from runtime_v7.llm_gateway import RuntimeV7ProviderCallLimitExceeded

            if isinstance(exc, RuntimeV7ProviderCallLimitExceeded):
                raise
            record.setdefault("response_guard_events", []).append(
                {
                    "type": "unsupported_product_pricing_model_repair_failed",
                    "reason": "model_call_failed",
                    "error": str(exc),
                }
            )
            return ""
        latency_ms = int((time.perf_counter() - started) * 1000)
        usage_summary = _llm_usage_summary(response)
        content = str(response.get("content") or "")
        record.setdefault("llm_calls", []).append(
            {
                "round": "pricing_repair",
                "component": "pricing_repair",
                "model_input_messages": deepcopy(messages),
                "tool_schemas": [],
                "model_output": deepcopy(response),
                "content": content,
                "tool_calls": [],
                "usage": deepcopy(response.get("usage") or {}),
                "cache_usage": deepcopy(response.get("cache_usage") or {}),
                "request_cache": deepcopy(response.get("request_cache") or {}),
                "cache_guard_events": deepcopy(response.get("cache_guard_events") or []),
                "usage_summary": usage_summary,
                "latency_ms": response.get("latency_ms", latency_ms),
                "finish_reason": response.get("finish_reason"),
                "response_format": "RuntimeV7PricingRepairResponseModel",
                "max_tokens": PRICING_REPAIR_MAX_TOKENS,
            }
        )
        payload = _safe_json_loads(content)
        if isinstance(payload, dict):
            return str(payload.get("response_text") or "").strip()
        return content.strip()

    def _finalize_turn_record(
        self,
        *,
        record: Dict[str, Any],
        turn_index: int,
        user_message: str,
        assistant_text: str,
        draft_assistant_text: str,
        final_composer_response: Dict[str, Any],
        runtime_final_response: str,
        conversation_evidence: Dict[str, Any],
        state_context: Dict[str, Any],
        external_evidence_refs: Sequence[Dict[str, Any]],
        existing_tags: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Persist turn artifacts, memory, signal ledger, and passive tags."""

        if not str(runtime_final_response or "").strip():
            record.setdefault("tool_retry_events", []).append(
                {
                    "round": "finalize",
                    "type": "empty_final_response_fallback",
                    "assistant_text": assistant_text,
                }
            )
            runtime_final_response = _empty_runtime_fallback_response(user_message)
        self.recent_turns.append({"role": "user", "content": user_message})
        self.recent_turns.append(
            {
                "role": "assistant",
                "content": _compact_assistant_context_for_next_turn(runtime_final_response, record["tool_results"]),
            }
        )
        self.recent_turns = self.recent_turns[-10:]
        memory_recent_turns = merge_recent_turns(conversation_evidence["recent_turns"], self.recent_turns, limit=12)
        continuity_signals = _durable_background_signals_for_continuity(
            state_context["background_signals"]
        )
        active_memory_after = self.memory_updater.update_after_turn(
            session_id=self.session_id,
            latest_user_message=user_message,
            assistant_response=runtime_final_response,
            tool_results=record["tool_results"],
            recent_turns=memory_recent_turns,
            background_signals=continuity_signals,
            external_evidence_refs=external_evidence_refs,
        )
        self.signal_ledger.save(
            self.session_id,
            continuity_signals,
            turn_index=turn_index,
        )
        record["draft_assistant_text"] = draft_assistant_text
        record["assistant_text"] = assistant_text
        record["final_composer_response"] = final_composer_response
        record["runtime_final_response"] = runtime_final_response
        inclusions_covered_by_reviewed_surface = _surfaces_include_warranty_promo(
            _collect_runtime_presentation_surfaces(record["tool_results"])
        )
        if (
            _text_contains_product_inclusions(runtime_final_response)
            or inclusions_covered_by_reviewed_surface
        ):
            self.product_inclusions_sent = True
            record["product_inclusions_sent_after_turn"] = True
            record["product_inclusions_source"] = (
                "reviewed_warranty_gallery"
                if inclusions_covered_by_reviewed_surface
                else "structured_text"
            )
        record["welcome_spiel_inserted"] = any(
            isinstance(event, dict) and event.get("type") == WELCOME_SPIEL_GUARD_EVENT_TYPE
            for event in record.get("response_guard_events") or []
        )
        record["first_turn_opening_model_composed"] = any(
            isinstance(event, dict)
            and event.get("type") == MODEL_COMPOSED_FIRST_TURN_OPENING_EVENT_TYPE
            for event in record.get("response_guard_events") or []
        )
        record["first_turn_intro_mode"] = _first_turn_intro_mode_from_guard_events(record.get("response_guard_events") or [])
        record["active_working_memory_after_turn"] = active_memory_after.to_dict()
        supplemental_llm_calls = _supplemental_llm_usage_calls(record)
        record["supplemental_llm_calls"] = supplemental_llm_calls
        all_llm_calls = [*record["llm_calls"], *supplemental_llm_calls]
        record["llm_usage_summary"] = _aggregate_llm_usage(all_llm_calls)
        record["context_cache_summary"] = _aggregate_context_cache(all_llm_calls)
        record["observation_headers_after_turn"] = self.tools.store.headers(limit=3)
        record["service_observation_headers_after_turn"] = self.service_tools.store.headers(limit=3)
        record["recent_turns_after_turn"] = deepcopy(self.recent_turns)
        record["memory_recent_turns_after_turn"] = deepcopy(memory_recent_turns)
        record["background_signal_ledger_after_turn"] = self.signal_ledger.load(self.session_id)
        record["latest_order_summary_snapshot_after_turn"] = deepcopy(self.latest_order_summary_snapshot)
        record["latest_selected_product_context_after_turn"] = deepcopy(self.latest_selected_product_context)
        record["latest_order_payload_ref_after_turn"] = self.latest_order_payload_ref
        record["order_payload_refs_after_turn"] = self._order_payload_refs()
        record["latest_submitted_order_context_after_turn"] = deepcopy(self.latest_submitted_order_context)
        record["latest_order_details_context_after_turn"] = deepcopy(self.latest_order_details_context)
        record["latest_payment_request_ref_after_turn"] = self.latest_payment_request_ref
        record["payment_request_refs_after_turn"] = self._payment_request_refs()
        record["human_handoff_state_after_turn"] = deepcopy(
            self.human_handoff_state
        )
        record["tagging"] = self._evaluate_and_apply_tags(
            current_user_message=user_message,
            runtime_final_response=runtime_final_response,
            background_signals=state_context["background_signals"],
            lead_qualification=record.get("lead_qualification") or {},
            tool_results=record["tool_results"],
            retry_events=record.get("tool_retry_events") or [],
            turn_count=turn_index,
            existing_tags=existing_tags,
            record=record,
        )
        self.turn_records.append(record)
        return record

    def _evaluate_and_apply_tags(
        self,
        *,
        current_user_message: str,
        runtime_final_response: str,
        background_signals: Sequence[Dict[str, Any]],
        lead_qualification: Dict[str, Any],
        tool_results: Sequence[Dict[str, Any]],
        retry_events: Sequence[Dict[str, Any]],
        turn_count: int,
        existing_tags: Optional[Sequence[str]],
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        existing = [str(tag) for tag in (existing_tags or []) if str(tag).strip()]
        existing.extend(tag for tag in self.tag_ledger if tag not in existing)
        interaction_context = {
            "choice": self.current_validated_choice_context,
        }
        packet_events = self.current_interaction_packet.get("events") if isinstance(
            self.current_interaction_packet, Mapping
        ) else []
        if isinstance(packet_events, list) and packet_events:
            latest_event = packet_events[-1]
            if isinstance(latest_event, Mapping):
                interaction_context[
                    "promo"
                    if str(latest_event.get("source") or "") == "promo_action"
                    else "choice"
                ] = latest_event
        result = evaluate_runtime_v7_tagging(
            current_user_message=current_user_message,
            assistant_response=runtime_final_response,
            background_signals=background_signals,
            lead_qualification=lead_qualification,
            tool_results=tool_results,
            retry_events=retry_events,
            selected_product_context=self.latest_selected_product_context,
            interaction_context=interaction_context,
            turn_count=turn_count,
            existing_tags=existing,
        )
        actions = [dict(action) for action in result.get("tags_to_add") or [] if isinstance(action, dict)]
        if not actions:
            return mark_runtime_v7_tags_applied(result, apply_status="no_tags")
        if self.tag_apply_callback is None:
            marked = mark_runtime_v7_tags_applied(result, apply_status="dry_run_no_channel")
            self._remember_tag_actions(actions, apply_status="dry_run_no_channel")
            return marked
        try:
            outcome = self.tag_apply_callback(actions, record)
        except Exception as exc:  # pragma: no cover - callback failures are integration-side.
            failed = [{"tag": action.get("tag"), "error": str(exc)} for action in actions]
            return mark_runtime_v7_tags_applied(result, failed_tags=failed, apply_status="failed")
        if not isinstance(outcome, dict):
            outcome = {}
        applied = outcome.get("applied_tags") or outcome.get("tags_applied") or []
        failed = outcome.get("failed_tags") or outcome.get("tags_failed") or []
        marked = mark_runtime_v7_tags_applied(
            result,
            applied_tags=applied,
            failed_tags=failed,
            apply_status=str(outcome.get("apply_status") or ""),
        )
        self._remember_tag_actions(
            [action for action in actions if action.get("tag") in set(marked.get("tags_applied") or [])],
            apply_status=marked.get("apply_status") or "success",
        )
        return marked

    def _remember_tag_actions(self, actions: Sequence[Dict[str, Any]], *, apply_status: str) -> None:
        for action in actions or []:
            tag = str(action.get("tag") or "").strip()
            if not tag:
                continue
            self.tag_ledger[tag] = {
                "tag": tag,
                "rule": action.get("rule"),
                "reason": action.get("reason"),
                "apply_status": apply_status,
            }

    def _complete_requested_promo_gallery(
        self,
        *,
        search_result: Mapping[str, Any],
        search_args: Mapping[str, Any],
        round_index: int,
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Complete the model-requested promo surface from validated refs.

        The model owns whether a gallery helps by setting ``presentation_mode``
        on the catalog search. Runtime owns the mechanical second step: it may
        pass only provider-issued allowed refs to the deterministic renderer.
        Returning the compact surface beside the search result lets the model
        continue to another independent objective without spending a separate
        round selecting the same refs again.
        """

        if str(search_args.get("presentation_mode") or "") != (
            "gallery_if_available"
        ):
            return {}
        if any(
            isinstance(item, dict)
            and item.get("name") == "present_promo_gallery"
            and isinstance(item.get("full_result"), dict)
            and item["full_result"].get("status") == "ok"
            for item in record.get("tool_results") or []
        ):
            return {}
        if str(search_result.get("status") or "") != "ok":
            return {}
        allowed_refs = [
            str(value or "").strip()
            for value in search_result.get("allowed_promo_refs") or []
            if str(value or "").strip()
        ]
        if not allowed_refs:
            return {}
        trigger_mode = (
            "targeted"
            if str(search_result.get("mode") or search_args.get("mode") or "")
            == "targeted"
            else "general"
        )
        exact_title_refs = _exact_title_promo_refs(
            search_result,
            query=str(search_result.get("query") or search_args.get("query") or ""),
        )
        requested_brand_refs = _requested_brand_promo_refs(search_result)
        supporting_warranty_request = bool(
            search_args.get("supporting_context") is True
            and normalize_promo_query(
                str(search_result.get("query") or search_args.get("query") or "")
            )
            == normalize_promo_query(SUPPORTING_WARRANTY_PROMO_QUERY)
        )
        if supporting_warranty_request and not exact_title_refs:
            record.setdefault("response_guard_events", []).append(
                {
                    "type": "supporting_promo_exact_title_not_found",
                    "reason": "automatic_warranty_replacement_requires_exact_reviewed_title",
                    "query": SUPPORTING_WARRANTY_PROMO_QUERY,
                }
            )
            return {}
        primary_refs = [
            str(value or "").strip()
            for value in search_result.get("primary_promo_refs") or []
            if str(value or "").strip()
        ]
        alternative_refs = [
            str(value or "").strip()
            for value in search_result.get("alternative_promo_refs") or []
            if str(value or "").strip()
        ]
        selected_refs = (
            exact_title_refs
            or requested_brand_refs
            or primary_refs
            or alternative_refs
            or allowed_refs
        )
        supporting_warranty_surface = bool(
            supporting_warranty_request and exact_title_refs
        )
        gallery_args = {
            "promo_refs": selected_refs[: 3 if trigger_mode == "targeted" else 8],
            "trigger_mode": trigger_mode,
            "explicit_redisplay": search_args.get("explicit_redisplay") is True,
        }
        gallery_result = self._execute_tool(
            "present_promo_gallery",
            gallery_args,
        )
        gallery_record = _promo_tool_record(
            "present_promo_gallery",
            gallery_args,
            gallery_result,
        )
        gallery_record.update(
            {
                "round": round_index,
                "tool_call_id": (
                    f"runtime_completed_promo_gallery_{round_index}"
                ),
                "runtime_preloaded": False,
                "runtime_completed": True,
                "completion_source": (
                    "product_tpp_supporting_surface_policy"
                    if supporting_warranty_surface
                    else "search_presentation_mode"
                ),
            }
        )
        record.setdefault("response_guard_events", []).append(
            {
                "type": "requested_promo_surface_completed",
                "reason": "model_selected_gallery_if_available",
                "status": gallery_result.get("status"),
            }
        )
        record.setdefault("execution_efficiency_events", []).append(
            {
                "type": "promo_gallery_completed_from_search_contract",
                "model_selection_rounds_avoided": 1,
                "trigger_mode": trigger_mode,
                "promo_ref_count": len(gallery_args["promo_refs"]),
                "status": gallery_result.get("status"),
            }
        )
        return gallery_record

    def _complete_validated_promo_gallery(
        self,
        record: Dict[str, Any],
    ) -> None:
        """Complete a renderer surface already authorized by promo evidence.

        The model still decides that promo lookup is relevant. Runtime only
        completes the matching reviewed surface when the validated lookup
        proves a brandless discovery turn or a requested brand miss. This
        avoids relying on the model to repeat a second rendering tool call and
        does not infer intent from customer wording.
        """

        tool_results = [
            item
            for item in record.get("tool_results") or []
            if isinstance(item, dict)
        ]
        if any(
            item.get("name") == "present_promo_gallery"
            and isinstance(item.get("full_result"), dict)
            and item["full_result"].get("status") == "ok"
            for item in tool_results
        ):
            return
        searches = [
            item
            for item in tool_results
            if item.get("name") == "search_promo_catalog"
            and isinstance(item.get("full_result"), dict)
            and item["full_result"].get("status") == "ok"
        ]
        if not searches:
            return
        search = searches[-1]
        full = search["full_result"]
        args = search.get("args") if isinstance(search.get("args"), dict) else {}
        if str(args.get("presentation_mode") or "") == "gallery_if_available":
            search_round = search.get("round")
            gallery_record = self._complete_requested_promo_gallery(
                search_result=full,
                search_args=args,
                round_index=search_round if isinstance(search_round, int) else 0,
                record=record,
            )
            if gallery_record:
                record["tool_results"].append(gallery_record)
            return
        allowed_refs = [
            str(value or "").strip()
            for value in full.get("allowed_promo_refs") or []
            if str(value or "").strip()
        ]
        if not allowed_refs:
            return
        requested_brands = {
            str(value or "").strip().casefold()
            for value in full.get("requested_brands") or []
            if str(value or "").strip()
        }
        unmatched_brands = {
            str(value or "").strip().casefold()
            for value in full.get("unmatched_requested_brands") or []
            if str(value or "").strip()
        }
        requested_promo_types = {
            str(value or "").strip().casefold()
            for value in args.get("promo_types") or []
            if str(value or "").strip()
        }
        product_verified_brands: set[str] = set()
        for item in tool_results:
            if item.get("name") != "product_search":
                continue
            product_result = (
                item.get("full_result")
                if isinstance(item.get("full_result"), dict)
                else {}
            )
            evidence = (
                product_result.get("promo_evidence")
                if isinstance(product_result.get("promo_evidence"), dict)
                else {}
            )
            product_verified_brands.update(
                str(value or "").strip().casefold()
                for value in evidence.get("verified_brands") or []
                if str(value or "").strip()
            )
            for card in product_result.get("product_cards") or []:
                if not isinstance(card, dict):
                    continue
                if not product_card_matches_promo_types(
                    card,
                    requested_promo_types=requested_promo_types,
                ):
                    continue
                brand = str(card.get("brand") or "").strip().casefold()
                if brand:
                    product_verified_brands.add(brand)

        brandless_without_size = bool(
            not requested_brands
            and not str(
                full.get("tire_size")
                or args.get("tire_size")
                or ""
            ).strip()
        )
        unresolved_brand_miss = bool(
            unmatched_brands - product_verified_brands
        )
        if not brandless_without_size and not unresolved_brand_miss:
            return

        gallery_args = {
            "promo_refs": allowed_refs[:3],
            "trigger_mode": (
                "targeted"
                if requested_brands
                else "general"
            ),
        }
        result = self._execute_tool("present_promo_gallery", gallery_args)
        record["tool_results"].append(
            _promo_tool_record(
                "present_promo_gallery",
                gallery_args,
                result,
            )
        )
        record.setdefault("response_guard_events", []).append(
            {
                "type": "validated_promo_surface_completed",
                "reason": (
                    "unresolved_requested_brand"
                    if unresolved_brand_miss
                    else "brandless_promo_discovery"
                ),
                "status": result.get("status"),
            }
        )

    def _complete_product_supporting_promo_gallery(
        self,
        record: Dict[str, Any],
    ) -> None:
        """Reuse the reviewed promo catalog for a first TPP pricelist.

        Product cards remain the authority for exact product warranty fields.
        This policy only selects a reviewed supporting visual; the final model
        still owns the lead-in, transition, and CTA around both surfaces.
        """

        if self.promo_catalog is None or self.product_inclusions_sent:
            return
        if (
            "warranty"
            in {
                str(value or "").strip().casefold()
                for value in self.latest_promo_presentation.get("promo_types") or []
            }
            and str(
                self.latest_promo_presentation.get("delivery_status") or ""
            ).strip().lower()
            in {"success", "pending", "unknown", "delivery_unknown"}
        ):
            return
        tool_results = [
            item
            for item in record.get("tool_results") or []
            if isinstance(item, dict)
        ]
        # A failed or suppressed promo call is not a customer-visible warranty
        # surface. Only a renderable reviewed warranty gallery may replace the
        # product-inclusions fallback.
        if _surfaces_include_warranty_promo(
            _collect_runtime_presentation_surfaces(tool_results)
        ):
            return
        product_results = [
            item
            for item in tool_results
            if item.get("name") == "product_search"
            and isinstance(item.get("full_result"), dict)
        ]
        if not product_results:
            return
        product_record = product_results[-1]
        full_result = product_record["full_result"]
        cards = [
            card
            for card in full_result.get("product_cards") or []
            if isinstance(card, dict)
        ]
        if not cards or not _cards_have_tire_protection_plan(cards):
            return
        service_type = str(
            (product_record.get("args") or {}).get("service_type")
            if isinstance(product_record.get("args"), dict)
            else ""
        )
        if _service_type_is_delivery(service_type):
            return

        tire_size = str(cards[0].get("tire_size") or "").strip()
        search_args = {
            "query": SUPPORTING_WARRANTY_PROMO_QUERY,
            "mode": "targeted",
            "top_k": 1,
            "tire_size": tire_size or None,
            "presentation_mode": "gallery_if_available",
            "explicit_redisplay": False,
            "supporting_context": True,
        }
        search_result = self._execute_tool(
            "search_promo_catalog",
            search_args,
        )
        search_record = _promo_tool_record(
            "search_promo_catalog",
            search_args,
            search_result,
        )
        search_record.update(
            {
                "round": "runtime_supporting_promo",
                "tool_call_id": "runtime_supporting_warranty_promo_search",
                "runtime_preloaded": False,
                "runtime_completed": True,
                "completion_source": "product_tpp_supporting_surface_policy",
            }
        )
        record.setdefault("tool_results", []).append(search_record)
        gallery_record = self._complete_requested_promo_gallery(
            search_result=search_result,
            search_args=search_args,
            round_index=0,
            record=record,
        )
        if gallery_record:
            gallery_record["round"] = "runtime_supporting_promo"
            gallery_record["completion_source"] = (
                "product_tpp_supporting_surface_policy"
            )
            record["tool_results"].append(gallery_record)
        record.setdefault("response_guard_events", []).append(
            {
                "type": "supporting_promo_catalog_lookup",
                "reason": "first_tpp_product_pricelist",
                "status": search_result.get("status"),
                "gallery_status": (
                    (gallery_record.get("full_result") or {}).get("status")
                    if gallery_record
                    else "not_available"
                ),
            }
        )

    def _execute_tool(
        self,
        name: str,
        args: Dict[str, Any],
        *,
        current_user_message: str = "",
        active_working_memory: str = "",
        background_signals: Optional[Sequence[Dict[str, Any]]] = None,
        order_readiness: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self._remember_selected_product_context_from_args(args)
        if name == "search_promo_catalog":
            if self.promo_catalog is None:
                return {"status": "unavailable", "reason": "promo_catalog_disabled", "read_only": True}
            return self.promo_catalog.search_promo_catalog(args)
        if name == "get_brand_knowledge":
            if self.brand_knowledge is None:
                return {
                    "status": "unavailable",
                    "reason": "brand_knowledge_disabled",
                    "read_only": True,
                }
            return self.brand_knowledge.get_brand_knowledge(args)
        if name == "present_promo_gallery":
            if self.promo_catalog is None:
                return {"status": "unavailable", "reason": "promo_catalog_disabled", "read_only": True}
            if str(self.profile_fields.get("channel") or "manychat").strip().lower() not in {
                "manychat",
                "messenger",
                "facebook",
            }:
                return {"status": "suppressed", "reason": "promo_gallery_unsupported_channel", "read_only": True}
            result = self.promo_catalog.present_promo_gallery(args)
            if result.get("status") == "ok":
                explicit_redisplay = args.get("explicit_redisplay") is True
                if (
                    not explicit_redisplay
                    and str(args.get("trigger_mode") or "") == "general"
                    and str(result.get("catalog_version_id") or "")
                    == str(self.latest_promo_presentation.get("catalog_version_id") or "")
                    and str(self.latest_promo_presentation.get("delivery_status") or "").strip().lower()
                    in {"success", "pending", "unknown", "delivery_unknown"}
                ):
                    return {
                        "status": "suppressed",
                        "reason": "general_promo_catalog_already_presented",
                        "catalog_version_id": result.get("catalog_version_id"),
                        "read_only": True,
                    }
                if (
                    not explicit_redisplay
                    and str(args.get("trigger_mode") or "") == "targeted"
                    and str(result.get("selection_fingerprint") or "")
                    == str(self.latest_promo_presentation.get("selection_fingerprint") or "")
                    and str(self.latest_promo_presentation.get("delivery_status") or "").strip().lower()
                    in {"success", "pending", "unknown", "delivery_unknown"}
                ):
                    return {
                        "status": "suppressed",
                        "reason": "targeted_promo_selection_already_presented",
                        "selection_fingerprint": result.get("selection_fingerprint"),
                        "read_only": True,
                    }
                result["show_count"] = self._next_promo_gallery_show_count(
                    str(result.get("catalog_version_id") or "")
                )
                self._remember_promo_presentation(result, delivery_status="pending")
            return result
        if name == "product_search":
            result = self.tools.product_search(args)
            self._remember_selected_product_context_from_product_search(args, result)
            return result
        if name == "discover_brand_buckets":
            return self.tools.discover_brand_buckets(args)
        if name == "extract_compatible_fitment":
            args = _hydrate_fitment_tool_args(args, background_signals or [])
            result = self.tools.extract_compatible_fitment(args)
            self.latest_fitment_observation = _compact_fitment_observation(result)
            return result
        if name == "resolve_product_reference":
            invalid_plan = _invalid_model_product_selection_plan(args)
            if invalid_plan:
                return invalid_plan
            result = self.tools.resolve_product_reference(args)
            self._remember_selected_product_context_from_resolution(result)
            return result
        if name == "get_product_details":
            invalid_plan = _invalid_model_product_selection_plan(args)
            if invalid_plan:
                return invalid_plan
            result = self.tools.get_product_details(args)
            self._remember_selected_product_context_from_resolution(result)
            return result
        if name == "answer_product_faq":
            return answer_product_faq(args, embedding_gateway=self.model_client)
        if name == "answer_policy_faq":
            return answer_policy_faq(
                args,
                embedding_gateway=self.model_client,
                canonical_values_provider=self.canonical_values_provider,
            )
        if name == "answer_service_faq":
            return answer_service_faq(args, embedding_gateway=self.model_client)
        if name == "answer_order_faq":
            args = self._tool_args_with_profile_fields(args)
            return answer_order_faq(
                args,
                embedding_gateway=self.model_client,
                canonical_values_provider=self.canonical_values_provider,
            )
        if name == "get_business_contact":
            args = self._tool_args_with_profile_fields(args)
            return get_business_contact(args)
        if name == "request_human_handoff":
            prior = dict(self.human_handoff_state or {})
            if str(prior.get("status") or "").strip().lower() == "requested":
                return {
                    **prior,
                    "status": "already_requested",
                    "human_assignment_confirmed": False,
                    "automated_sales_replies": "pause_requested",
                    "read_only": False,
                }
            reason_category = str(
                args.get("reason_category") or "customer_request"
            ).strip().lower()
            if reason_category not in {
                "customer_request",
                "service_recovery",
                "complaint",
                "complex_case",
                "other",
            }:
                reason_category = "other"
            self.human_handoff_state = {
                "status": "requested",
                "requested_at": manila_now_text(),
                "evidence_ref": "human_handoff:current_request",
                "reason_category": reason_category,
                "summary": str(args.get("summary") or "").strip()[:240],
                "source": "request_human_handoff_tool",
                "human_assignment_confirmed": False,
                "automated_sales_replies": "pause_requested",
            }
            return {
                **self.human_handoff_state,
                "read_only": False,
                "customer_response_constraints": {
                    "may_say": [
                        "the request was recorded",
                        "automated sales replies will pause after this acknowledgement",
                        "a human teammate still needs to pick up the chat",
                    ],
                    "must_not_say": [
                        "a human is already connected",
                        "a human was assigned",
                        "the issue was escalated successfully",
                    ],
                },
            }
        if name == "calculate_order_quote":
            args = self._normalize_order_tool_arg_aliases(args)
            args = self._drop_unconfirmed_payment_plan(
                args,
                background_signals or [],
            )
            args = self._apply_current_validated_checkout_choice(args)
            args = self._order_args_with_selected_product_context(args)
            args = self._order_args_with_latest_summary_context(args)
            args = self._order_args_with_runtime_profile_context(args)
            return calculate_order_quote(
                payload=args,
                current_user_message=current_user_message,
                active_working_memory=active_working_memory,
                background_signals=background_signals or [],
                product_observation_store=self.tools.store,
                service_observation_store=self.service_tools.store,
                order_readiness=order_readiness or {},
                previous_order_summary_snapshot=deepcopy(self.latest_order_summary_snapshot),
            )
        if name == "build_order_summary":
            args = self._normalize_order_tool_arg_aliases(args)
            args = self._drop_unconfirmed_payment_plan(
                args,
                background_signals or [],
            )
            args = self._apply_current_validated_checkout_choice(args)
            args = self._order_args_with_selected_product_context(args)
            args = self._order_args_with_latest_summary_context(args)
            args = self._order_args_with_runtime_profile_context(args)
            result = build_order_summary(
                payload=args,
                current_user_message=current_user_message,
                active_working_memory=active_working_memory,
                background_signals=background_signals or [],
                product_observation_store=self.tools.store,
                service_observation_store=self.service_tools.store,
                order_readiness=order_readiness or {},
                previous_order_summary_snapshot=deepcopy(self.latest_order_summary_snapshot),
                canonical_values_provider=self.canonical_values_provider,
            )
            snapshot = result.get("order_summary_snapshot") if isinstance(result, dict) else None
            if isinstance(snapshot, dict) and snapshot:
                self.latest_order_summary_snapshot = deepcopy(snapshot)
            self._remember_selected_product_context_from_order_result(args, result)
            return result
        if name == "build_order_payload":
            args = self._normalize_order_tool_arg_aliases(args)
            args = self._drop_unconfirmed_payment_plan(
                args,
                background_signals or [],
            )
            args = self._apply_current_validated_checkout_choice(args)
            args = self._order_args_with_selected_product_context(args)
            args = self._order_args_with_latest_summary_context(args)
            args = self._order_args_with_runtime_profile_context(args)
            result = build_order_payload(
                payload=args,
                current_user_message=current_user_message,
                active_working_memory=active_working_memory,
                background_signals=background_signals or [],
                product_observation_store=self.tools.store,
                service_observation_store=self.service_tools.store,
                order_readiness=order_readiness or {},
                canonical_values_provider=self.canonical_values_provider,
            )
            self._remember_order_payload(result)
            return result
        if name == "submit_order":
            if not _typed_state_authorizes_order_submission(
                latest_order_summary_snapshot=self.latest_order_summary_snapshot,
                background_signals=background_signals or [],
            ):
                return {
                    "status": "needs_explicit_order_confirmation",
                    "order_payload_ref": str(
                        args.get("order_payload_ref") or ""
                    ),
                    "order_submitted": False,
                    "can_request_payment": False,
                    "reason": "latest_customer_message_did_not_confirm_submission",
                    "note": (
                        "Submitting an order requires an explicit latest-customer "
                        "confirmation after a ready order summary."
                    ),
                    "read_only": False,
                }
            self._hydrate_order_payload_store_runtime_identity()
            result = submit_order(
                payload=args,
                order_payload_store=self.order_payload_store,
                http_client=self.order_http_client,
                canonical_values_provider=self.canonical_values_provider,
            )
            self._remember_submitted_order(result)
            return result
        if name == "prepare_payment_request":
            args = self._payment_request_args_with_latest_order(args)
            result = prepare_payment_request(
                payload=args,
                order_payload_store=self.order_payload_store,
                payment_request_store=self.payment_request_store,
                http_client=self.order_http_client,
            )
            self._remember_payment_request(result)
            return result
        if name == "match_payment_proof":
            return match_payment_proof(
                payload=args,
                external_evidence_refs=list(self.external_evidence_store.values()),
                payment_request_store=self.payment_request_store,
                order_payload_store=self.order_payload_store,
                http_client=self.order_http_client,
            )
        if name == "get_order_details":
            result = get_order_details(
                payload=args,
                http_client=self.order_http_client,
            )
            self._remember_order_details(result)
            return result
        if name == "find_installation_partners":
            return self.service_tools.find_installation_partners(args)
        if name == "find_service_locations":
            return self.service_tools.find_service_locations(args)
        if name == "present_serviceable_location_choices":
            if self.location_plan_executor is None:
                return {
                    "status": "unavailable",
                    "reason": "location_choice_executor_unavailable",
                    "routing_only": True,
                    "read_only": True,
                    **authorized_business_identity_context(),
                }
            return self.location_plan_executor(
                {
                    **args,
                    "discovery_mode": "serviceable_provinces",
                }
            )
        if name == "get_branch_addons":
            return self.service_tools.get_branch_addons(args)
        if name == "find_installation_slots":
            if (
                str(args.get("discovery_mode") or "").strip()
                == "recommend_serviceable_cities"
            ):
                if self.location_plan_executor is None:
                    return {
                        "status": "unavailable",
                        "reason": "location_recommendation_executor_unavailable",
                        "read_only": True,
                    }
                return self.location_plan_executor(args)
            return self.service_tools.find_installation_slots(args)
        if name == "validate_installation_slot":
            return self.service_tools.validate_installation_slot(args)
        if name == "request_capability":
            requested_domain = str(args.get("domain") or "").strip().lower()
            retry_supported = requested_domain in {"product", "service", "order"}
            return {
                "status": "requested",
                "requested_domain": requested_domain,
                "reason": args.get("reason"),
                "needed_context": args.get("needed_context"),
                "retry_supported": retry_supported,
                "note": (
                    "Capability expansion retry will re-run this turn internally."
                    if retry_supported
                    else "Requested capability domain is not enabled in this pass."
                ),
            }
        return {"status": "error", "reason": f"unknown Runtime V7 tool: {name}"}

    def _prepare_promo_context_for_turn(
        self,
        *,
        user_message: str,
        background_signals: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Preload the current catalog only from a typed latest-turn browse scope.

        The semantic extractor owns interpretation across phrasing variants.
        Runtime owns the mechanical read-only search and provider-authorized
        surface projection. Raw customer wording never routes this path, and
        the transient question-only signal is not carried into later turns.
        """

        del user_message
        browse_requested = any(
            isinstance(signal, dict)
            and str(signal.get("key") or "").strip()
            == "promo_discovery_scope"
            and str(signal.get("value") or "").strip() == "all_current"
            and str(signal.get("source") or "").strip().casefold()
            == "latest_user_message"
            and str(signal.get("relation") or "").strip().casefold()
            == "question_only"
            for signal in background_signals or []
        )
        if not browse_requested or self.promo_catalog is None:
            return []

        search_args = {
            "query": "",
            "mode": "general",
            "top_k": 8,
            "presentation_mode": "gallery_if_available",
            "explicit_redisplay": True,
        }
        search_result = self._execute_tool(
            "search_promo_catalog",
            search_args,
        )
        search_record = _promo_tool_record(
            "search_promo_catalog",
            search_args,
            search_result,
        )
        search_record["completion_source"] = (
            "semantic_current_promo_discovery_scope"
        )
        allowed_refs = [
            str(value or "").strip()
            for value in search_result.get("allowed_promo_refs") or []
            if str(value or "").strip()
        ]
        if str(search_result.get("status") or "") != "ok" or not allowed_refs:
            return [search_record]

        gallery_args = {
            "promo_refs": allowed_refs[:8],
            "trigger_mode": "general",
            "explicit_redisplay": True,
        }
        gallery_result = self._execute_tool(
            "present_promo_gallery",
            gallery_args,
        )
        gallery_record = _promo_tool_record(
            "present_promo_gallery",
            gallery_args,
            gallery_result,
        )
        gallery_record["completion_source"] = (
            "semantic_current_promo_discovery_scope"
        )
        return [search_record, gallery_record]

    def _remember_promo_presentation(self, result: Dict[str, Any], *, delivery_status: str) -> None:
        entry = {
            "catalog_version_id": str(result.get("catalog_version_id") or ""),
            "promo_refs": list(result.get("promo_refs") or [])[:8],
            "promo_ids": list(result.get("promo_ids") or [])[:8],
            "promo_types": list(result.get("promo_types") or [])[:8],
            "promo_titles": list(result.get("promo_titles") or [])[:8],
            "card_refs": list(result.get("card_refs") or [])[:8],
            "trigger_mode": str(result.get("trigger_mode") or ""),
            "explicit_redisplay": result.get("explicit_redisplay") is True,
            "selection_fingerprint": str(result.get("selection_fingerprint") or ""),
            "presentation_ref": str(result.get("presentation_ref") or ""),
            "show_count": max(1, int(result.get("show_count") or 1)),
            "delivery_status": delivery_status,
            "attempted_at": manila_now_text(),
        }
        self.latest_promo_presentation = entry
        self.promo_presentation_history = [*self.promo_presentation_history[-9:], deepcopy(entry)]

    def _next_promo_gallery_show_count(self, catalog_version_id: str) -> int:
        """Return the next successful-delivery count for one catalog version."""

        prior_count = 0
        for entry in self.promo_presentation_history:
            if str(entry.get("catalog_version_id") or "") != str(catalog_version_id or ""):
                continue
            if str(entry.get("delivery_status") or "").strip().lower() != "success":
                continue
            try:
                entry_count = int(entry.get("show_count") or 0)
            except (TypeError, ValueError):
                entry_count = 0
            prior_count = max(prior_count, entry_count)
        return prior_count + 1

    def _tool_args_with_profile_fields(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Attach runtime-known profile fields to read-only FAQ tools."""

        if not self.profile_fields:
            return args
        output = deepcopy(args or {})
        output.setdefault("profile_fields", deepcopy(self.profile_fields))
        agent_assigned = str(self.profile_fields.get("agent_assigned") or "").strip()
        if agent_assigned:
            output.setdefault("agent_assigned", agent_assigned)
        return output

    def _normalize_order_tool_arg_aliases(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Accept model-emitted structured aliases before order validation.

        The model still decides what facts are present. This boundary only maps
        equivalent structured field names and checkout metadata IDs into the
        canonical order-tool keys expected by the V7 order helpers.
        """

        output = deepcopy(args or {})

        def present(value: Any) -> bool:
            """Return whether an alias contains a usable scalar value."""

            return value not in (None, "", [], {})

        def fill(target: str, *sources: str) -> None:
            """Copy the first usable scalar alias into one canonical key."""

            if present(output.get(target)):
                return
            for source in sources:
                value = output.get(source)
                if isinstance(value, (dict, list, tuple, set)):
                    continue
                if present(value):
                    output[target] = value
                    return

        fill("email_address", "customer_email", "email")
        fill("first_name", "customer_first_name")
        fill("last_name", "customer_last_name")
        fill("customer_name", "customer_full_name", "name")
        if not present(output.get("customer_name")) and (present(output.get("first_name")) or present(output.get("last_name"))):
            output["customer_name"] = " ".join(
                str(output.get(key) or "").strip()
                for key in ("first_name", "last_name")
                if str(output.get(key) or "").strip()
            )
        fill("contact_number", "customer_contact_number", "phone_number", "mobile_number", "contact")
        fill("location", "installation_partner_location", "installation_area", "service_area", "service_location")
        fill("delivery_address", "customer_delivery_address", "address")
        fill("schedule", "installation_slot", "appointment_schedule", "selected_schedule")

        if not present(output.get("schedule")):
            date = (
                output.get("installation_slot_date")
                or output.get("appointment_date")
                or output.get("schedule_date")
            )
            time_value = (
                output.get("installation_slot_time")
                or output.get("appointment_time")
                or output.get("schedule_time")
            )
            if present(date) and present(time_value):
                output["schedule"] = f"{str(date).strip()} {str(time_value).strip()}"
            elif present(date):
                output["schedule"] = str(date).strip()

        self._normalize_checkout_id_aliases(output)
        return output

    def _normalize_checkout_id_aliases(self, output: Dict[str, Any]) -> None:
        """Map checkout metadata IDs to canonical order arg labels when present."""

        try:
            metadata = checkout_metadata(self.canonical_values_provider)
        except Exception:
            metadata = {"payment_options": [], "payment_types": []}

        if output.get("payment_option") in (None, "", [], {}) and output.get("payment_option_id") not in (None, "", [], {}):
            option_id = str(output.get("payment_option_id") or "").strip()
            for row in metadata.get("payment_options") or []:
                if isinstance(row, dict) and str(row.get("id") or "").strip() == option_id:
                    output["payment_option"] = payment_option_label(row.get("name") or row.get("label") or row.get("description"))
                    break

        if output.get("payment_method") in (None, "", [], {}) and output.get("payment_method_id") not in (None, "", [], {}):
            method_id = str(output.get("payment_method_id") or "").strip()
            for row in metadata.get("payment_types") or []:
                if isinstance(row, dict) and str(row.get("id") or "").strip() == method_id:
                    output["payment_method"] = row.get("name") or row.get("label") or row.get("value")
                    break

    def _drop_unconfirmed_payment_plan(
        self,
        args: Dict[str, Any],
        background_signals: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Reject model-proposed checkout fields sourced only from an inquiry."""

        payment_keys = {
            "payment_option",
            "payment_method",
            "payment_method_for_submit",
            "reservation_payment_method",
            "balance_payment_method",
            "bank",
            "installment_months",
            "payment_option_id",
            "payment_method_id",
        }
        relevant = [
            signal
            for signal in background_signals or []
            if isinstance(signal, dict)
            and str(signal.get("key") or "").strip() in payment_keys
            and signal.get("value") not in (None, "", [])
        ]

        def authority(signal: Dict[str, Any]) -> tuple[str, str]:
            """Resolve original typed authority through a ledger projection."""

            source = str(signal.get("source") or "").strip()
            status = str(signal.get("status") or "").strip()
            metadata = (
                signal.get("metadata")
                if isinstance(signal.get("metadata"), dict)
                else {}
            )
            ledger = (
                metadata.get("ledger")
                if isinstance(metadata.get("ledger"), dict)
                else {}
            )
            if source == "signal_ledger":
                source = str(ledger.get("authority_source") or source).strip()
                status = str(ledger.get("authority_status") or status).strip()
            return source, status

        has_unconfirmed_inquiry = any(
            authority(signal)[1] == "mentioned_unconfirmed"
            for signal in relevant
        )
        has_customer_selection = any(
            authority(signal)[1] != "mentioned_unconfirmed"
            and authority(signal)[0]
            in {"latest_user_message", "validated_choice_action"}
            for signal in relevant
        )
        has_validated_choice = any(
            str(
                (
                    signal.get("metadata")
                    if isinstance(signal.get("metadata"), dict)
                    else {}
                ).get("choice_ref")
                or ""
            ).startswith(("option_", "method_"))
            for signal in relevant
        )
        if not has_unconfirmed_inquiry or has_customer_selection or has_validated_choice:
            return deepcopy(args or {})
        output = deepcopy(args or {})
        for key in payment_keys:
            output.pop(key, None)
        return output

    def _apply_current_validated_checkout_choice(
        self,
        args: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Bind model-proposed order args to the current validated checkout click."""

        context = self.current_validated_choice_context
        if (
            not isinstance(context, dict)
            or context.get("validation_status") != "valid"
        ):
            return deepcopy(args or {})
        choice_type = str(context.get("choice_type") or "").strip()
        if choice_type not in {
            "payment_option_selection",
            "payment_method_selection",
        }:
            return deepcopy(args or {})

        output = deepcopy(args or {})
        payment_keys = {
            "payment_option",
            "payment_method",
            "payment_method_for_submit",
            "reservation_payment_method",
            "balance_payment_method",
            "bank",
            "installment_months",
            "payment_option_id",
            "payment_method_id",
        }
        for key in payment_keys:
            output.pop(key, None)

        payment_option = str(
            context.get("payment_option")
            or (
                context.get("value")
                if choice_type == "payment_option_selection"
                else ""
            )
            or ""
        ).strip()
        if payment_option:
            output["payment_option"] = payment_option
        if choice_type == "payment_option_selection":
            return output

        method = str(
            context.get("label") or context.get("value") or ""
        ).strip()
        payment_stage = str(context.get("payment_stage") or "").strip()
        method_key = {
            "reservation_fee": "reservation_payment_method",
            "balance_payment": "balance_payment_method",
            "full_payment": "payment_method",
        }.get(payment_stage, "payment_method")
        if method:
            output[method_key] = method
        installment_months = str(
            context.get("installment_months") or ""
        ).strip()
        if installment_months:
            output["installment_months"] = installment_months
        return output

    def _order_args_with_selected_product_context(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Fill omitted trusted product refs from the last resolved selection."""

        output = deepcopy(args or {})
        context = self.latest_selected_product_context if isinstance(self.latest_selected_product_context, dict) else {}
        resolved_context = _selected_product_context_from_refs(output, self.tools)
        if not resolved_context and context:
            _normalize_selected_product_ref_aliases(output, context)
            resolved_context = _selected_product_context_from_refs(output, self.tools)
        if not resolved_context and context and _product_ref_args_overlap_context(output, context):
            resolved_context = context
        if resolved_context:
            context = resolved_context
        for key in (
            "product_observation_ref",
            "product_presentation_ref",
            "product_card_ref",
            "product_item_ref",
            "product_id",
            "slug",
        ):
            if output.get(key) in (None, "", [], {}) and context.get(key) not in (None, "", [], {}):
                output[key] = context[key]
        if context and resolved_context:
            for key in ("product_card_ref", "product_item_ref", "product_id", "slug"):
                if context.get(key) not in (None, "", [], {}):
                    output[key] = context[key]
        return output

    def _order_args_with_latest_summary_context(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Carry forward canonical payment facts resolved by the latest summary."""

        output = deepcopy(args or {})
        snapshot = self.latest_order_summary_snapshot if isinstance(self.latest_order_summary_snapshot, dict) else {}
        selection = snapshot.get("payment_selection") if isinstance(snapshot.get("payment_selection"), dict) else {}
        for key in (
            "payment_option",
            "payment_method",
            "payment_method_for_submit",
            "reservation_payment_method",
            "balance_payment_method",
            "bank",
            "installment_months",
        ):
            value = selection.get(key)
            if output.get(key) in (None, "", [], {}) and value not in (None, "", [], {}):
                output[key] = value
        return output

    def _order_args_with_runtime_profile_context(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Attach runtime identity fields needed by checkout payloads."""

        if not self.profile_fields:
            return args
        output = deepcopy(args or {})
        profile = self.profile_fields if isinstance(self.profile_fields, dict) else {}
        channel_user_id = str(profile.get("channel_user_id") or profile.get("many_chat_id") or profile.get("user_id") or "").strip()
        user_id = str(profile.get("user_id") or channel_user_id).strip()
        if channel_user_id:
            output.setdefault("channel_user_id", channel_user_id)
            output.setdefault("many_chat_id", channel_user_id)
        if user_id:
            output.setdefault("user_id", user_id)
        return output

    def _remember_selected_product_context_from_args(self, args: Dict[str, Any]) -> None:
        """Persist selected-product context when a tool call carries trusted refs."""

        context = _selected_product_context_from_refs(args or {}, self.tools)
        if context:
            self.latest_selected_product_context = context

    def _remember_selected_product_context_from_product_search(self, args: Dict[str, Any], result: Dict[str, Any]) -> None:
        """Persist a selected product when a model-narrowed search resolves one anchor.

        Product search can render exact alternatives beside a requested product.
        The visible card count is therefore not enough to infer ambiguity. This
        boundary trusts the model's structured search intent plus the trusted
        product-card metadata, not raw customer wording.
        """

        card = _selected_product_card_from_narrowed_product_search(args or {}, result or {})
        if not card:
            return
        refs = {
            "product_observation_ref": result.get("observation_ref"),
            "product_presentation_ref": result.get("presentation_ref"),
            "product_card_ref": card.get("card_ref"),
            "product_item_ref": card.get("item_ref"),
            "product_id": card.get("product_id"),
            "slug": card.get("slug"),
        }
        context = _selected_product_context_from_refs(refs, self.tools)
        if context:
            self.latest_selected_product_context = context

    def _payment_request_args_with_latest_order(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Fill omitted order refs from the latest submit/payload context."""

        output = deepcopy(args or {})
        latest_order = self.latest_submitted_order_context if isinstance(self.latest_submitted_order_context, dict) else {}
        if output.get("order_id") in (None, "", [], {}) and latest_order.get("order_id"):
            output["order_id"] = latest_order["order_id"]
        if output.get("order_payload_ref") in (None, "", [], {}) and latest_order.get("order_payload_ref"):
            output["order_payload_ref"] = latest_order["order_payload_ref"]
        if output.get("order_payload_ref") in (None, "", [], {}) and self.latest_order_payload_ref:
            output["order_payload_ref"] = self.latest_order_payload_ref
        return output

    def _remember_selected_product_context_from_order_result(self, args: Dict[str, Any], result: Dict[str, Any]) -> None:
        """Persist trusted selected-product refs after an order summary binds them."""

        if not isinstance(result, dict) or result.get("status") not in {"ready", "incomplete"}:
            return
        summary = result.get("summary_preview") if isinstance(result.get("summary_preview"), dict) else {}
        if not summary.get("Product"):
            return
        source_refs = result.get("source_refs") if isinstance(result.get("source_refs"), dict) else {}
        context = _selected_product_context_from_refs(source_refs or args, self.tools)
        if context:
            self.latest_selected_product_context = context

    def _remember_selected_product_context_from_resolution(self, result: Dict[str, Any]) -> None:
        """Persist trusted selected-product refs after a reference/detail tool resolves them."""

        if not isinstance(result, dict) or result.get("status") not in {"resolved", "ok"}:
            return
        context = _selected_product_context_from_refs(result, self.tools)
        if context:
            self.latest_selected_product_context = context

    def _remember_order_payload(self, result: Dict[str, Any]) -> None:
        """Store a submit-ready order payload behind its runtime ref."""

        if not isinstance(result, dict) or result.get("status") != "ready":
            return
        ref = str(result.get("order_payload_ref") or "").strip()
        payload = result.get("order_payload") if isinstance(result.get("order_payload"), dict) else {}
        if not ref or not payload:
            return
        payload = self._order_payload_with_runtime_identity(payload)
        self.order_payload_store[ref] = deepcopy(payload)
        self.latest_order_payload_ref = ref

    def _remember_submitted_order(self, result: Dict[str, Any]) -> None:
        """Store the latest submitted order context for payment requests."""

        if not isinstance(result, dict) or result.get("status") != "success":
            return
        order_id = str(result.get("order_id") or "").strip()
        payload_ref = str(result.get("order_payload_ref") or "").strip()
        order_payload = result.get("order_payload") if isinstance(result.get("order_payload"), dict) else {}
        if not order_id:
            return
        self.latest_submitted_order_context = _compact_unit(
            {
                "order_id": order_id,
                "order_payload_ref": payload_ref,
                "order_payload_summary": _compact_order_payload(order_payload),
                "amount_mismatch": result.get("amount_mismatch") or {},
                "submitted_at": result.get("submitted_at"),
            }
        )

    def _runtime_identity_fields(self) -> Dict[str, str]:
        profile = self.profile_fields if isinstance(self.profile_fields, dict) else {}
        channel_user_id = str(profile.get("channel_user_id") or profile.get("many_chat_id") or profile.get("user_id") or "").strip()
        user_id = str(profile.get("user_id") or channel_user_id).strip()
        return {
            "many_chat_id": channel_user_id or user_id,
            "channel_user_id": channel_user_id,
            "user_id": user_id,
        }

    def _order_payload_with_runtime_identity(self, order_payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = deepcopy(order_payload or {})
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if not data:
            return payload
        identity = self._runtime_identity_fields()
        many_chat_id = str(identity.get("many_chat_id") or "").strip()
        if many_chat_id and data.get("many_chat_id") in (None, "", [], {}):
            data["many_chat_id"] = many_chat_id
        payload["data"] = data
        return payload

    def _hydrate_order_payload_store_runtime_identity(self) -> None:
        if not self.order_payload_store:
            return
        for ref, payload in list(self.order_payload_store.items()):
            if isinstance(payload, dict):
                self.order_payload_store[ref] = self._order_payload_with_runtime_identity(payload)

    def _remember_order_details(self, result: Dict[str, Any]) -> None:
        """Store compact readback context from `/order_details` for follow-ups."""

        if not isinstance(result, dict) or result.get("status") != "ok":
            return
        order_id = str(result.get("order_id") or "").strip()
        if not order_id:
            return
        self.latest_order_details_context = _compact_unit(
            {
                "order_id": order_id,
                "order_status": result.get("order_status"),
                "payment_status": result.get("payment_status"),
                "unpaid_order_status": result.get("unpaid_order_status"),
                "transaction": result.get("transaction"),
                "fulfillment": result.get("fulfillment"),
                "payment": result.get("payment"),
                "totals": result.get("totals"),
                "items": result.get("items"),
                "source": result.get("source"),
                "read_only": True,
            }
        )

    def _remember_payment_request(self, result: Dict[str, Any]) -> None:
        """Store exact payment request data behind its runtime ref."""

        if not isinstance(result, dict) or result.get("status") not in {"ok", "payment_link_error"}:
            return
        ref = str(result.get("payment_request_ref") or "").strip()
        if not ref:
            return
        self.payment_request_store[ref] = deepcopy(
            {
                "payment_request_ref": ref,
                "order_id": result.get("order_id"),
                "order_payload_ref": result.get("order_payload_ref"),
                "payment_stage": result.get("payment_stage"),
                "expected_amount": result.get("expected_amount"),
                "payment_option": result.get("payment_option"),
                "payment_method": result.get("payment_method"),
                "amount_mismatch": result.get("amount_mismatch") or {},
                "payment_instruction_type": result.get("payment_instruction_type"),
                "primary_method": result.get("primary_method"),
            }
        )
        self.latest_payment_request_ref = ref

    def _remember_external_evidence_refs(self, refs: Sequence[Dict[str, Any]]) -> None:
        """Store latest external evidence refs by evidence_ref for later tools."""

        for ref in refs or []:
            if not isinstance(ref, dict):
                continue
            evidence_ref = str(ref.get("evidence_ref") or "").strip()
            if evidence_ref:
                self.external_evidence_store[evidence_ref] = deepcopy(ref)

    def _order_payload_refs(self) -> List[str]:
        """Return stored order payload refs in recency order."""

        refs = [ref for ref in self.order_payload_store if ref]
        if self.latest_order_payload_ref in refs:
            refs = [ref for ref in refs if ref != self.latest_order_payload_ref]
            refs.append(self.latest_order_payload_ref)
        return refs[-5:]

    def _order_summary_refs(self) -> List[str]:
        """Return latest deterministic order-summary refs in recency order."""

        snapshot = self.latest_order_summary_snapshot if isinstance(self.latest_order_summary_snapshot, dict) else {}
        ref = str(snapshot.get("order_summary_ref") or "").strip()
        return [ref] if ref else []

    def _order_payload_context(self) -> Dict[str, Any]:
        """Return compact model-facing context for stored submit payloads."""

        refs = self._order_payload_refs()
        if not refs:
            return {}
        latest_ref = refs[-1]
        latest_payload = self.order_payload_store.get(latest_ref) or {}
        return {
            "latest_order_payload_ref": latest_ref,
            "order_payload_refs": refs,
            "latest_order_payload_summary": _compact_order_payload(latest_payload),
            "note": (
                "Use submit_order with order_payload_ref only after the customer explicitly asks to submit, "
                "confirm, pay, or proceed from this validated payload."
            ),
        }

    def _order_details_context(self) -> Dict[str, Any]:
        """Return compact model-facing context for the latest order readback."""

        latest = self.latest_order_details_context if isinstance(self.latest_order_details_context, dict) else {}
        if not latest:
            return {}
        order_id = str(latest.get("order_id") or "").strip()
        if not order_id:
            return {}
        return {
            "latest_order_id": order_id,
            "latest_order_details": deepcopy(latest),
            "note": (
                "Use get_order_details again for fresh status/payment/appointment readback when the customer asks "
                "a follow-up about this order. Treat this context as read-only; do not mutate order details."
            ),
        }

    def _payment_request_refs(self) -> List[str]:
        """Return stored payment request refs in recency order."""

        refs = [ref for ref in self.payment_request_store if ref]
        if self.latest_payment_request_ref in refs:
            refs = [ref for ref in refs if ref != self.latest_payment_request_ref]
            refs.append(self.latest_payment_request_ref)
        return refs[-5:]

    def _payment_request_context(self) -> Dict[str, Any]:
        """Return compact model-facing context for stored payment requests."""

        refs = self._payment_request_refs()
        if not refs:
            return {}
        latest_ref = refs[-1]
        latest = self.payment_request_store.get(latest_ref) or {}
        return {
            "latest_payment_request_ref": latest_ref,
            "payment_request_refs": refs,
            "latest_payment_request": deepcopy(latest),
            "submitted_order_exists": bool(latest.get("order_id")),
            "payment_action_ready": bool(latest.get("order_id") and latest.get("order_payload_ref")),
            "preferred_payment_followup_tool": "prepare_payment_request",
            "note": (
                "Use prepare_payment_request to refresh QR/link/account details when the customer asks again "
                "or reports an issue, including card/installment link requests. Use match_payment_proof for payment "
                "screenshots. Do not ask for product/order basics again when this submitted order context exists. "
                "Do not claim paid/verified status unless backend order details or another trusted payment status confirms it."
            ),
        }


# Backward-compatible aliases for existing product-slice tests and scripts.
ProductAgentModelClient = RuntimeV7ModelClient
ProductAgentHarness = RuntimeV7Harness


def _durable_background_signals_for_continuity(
    signals: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Exclude turn-scoped semantic scenarios from memory and ledger state."""

    return [
        deepcopy(signal)
        for signal in signals or []
        if isinstance(signal, dict)
        and str(signal.get("relation") or "asserted").strip().lower()
        in DURABLE_SIGNAL_RELATIONS
    ]


def _apply_validated_choice_signal_boundaries(
    state_context: Dict[str, Any],
    *,
    validated_choice_context: Mapping[str, Any],
) -> None:
    """Prevent synthetic guided-action prose from becoming customer consent.

    The model still owns the conversational transition. This boundary prevents
    synthetic router prose from either downgrading a validated guided choice or
    turning a navigation-only outcome into customer consent.
    """

    if validated_choice_context.get("validation_status") != "valid":
        return
    choice_type = str(validated_choice_context.get("choice_type") or "").strip()
    if choice_type not in {"serviceable_province", "serviceable_city"}:
        return
    is_unselected_other_area = (
        choice_type == "serviceable_province"
        and str(validated_choice_context.get("choice_code") or "")
        .strip()
        .casefold()
        == "other"
        and validated_choice_context.get("service_path_selected") is False
    )
    synthetic_candidate_keys = {
        "service_type",
        "location",
        "city",
        "delivery_address",
        "selected_installation_partner",
        "chosen_schedule_slot",
        "preferred_schedule",
    }
    signals = [
        dict(signal)
        for signal in state_context.get("background_signals") or []
        if isinstance(signal, dict)
    ]

    def is_current_synthetic_candidate(signal: Dict[str, Any]) -> bool:
        """Identify only current router-prose candidates, never carried state."""

        return (
            str(signal.get("source") or "").strip().casefold()
            == "latest_user_message"
            and str(signal.get("key") or "") in synthetic_candidate_keys
        )

    if is_unselected_other_area:
        removed_keys = [
            str(signal.get("key") or "")
            for signal in signals
            if is_current_synthetic_candidate(signal)
        ]
        state_context["background_signals"] = [
            signal
            for signal in signals
            if not is_current_synthetic_candidate(signal)
        ]
        state_context["validated_choice_signal_boundary"] = {
            "status": "applied",
            "reason": "guided_other_area_synthetic_prose_is_not_customer_consent",
            "removed_keys": sorted(set(removed_keys)),
            "recommended_service_path": str(
                validated_choice_context.get("recommended_service_path") or ""
            ),
            "service_path_selected": False,
        }
        return

    label = str(validated_choice_context.get("label") or "").strip()
    province_label = str(
        validated_choice_context.get("province_label")
        or (label if choice_type == "serviceable_province" else "")
        or ""
    ).strip()
    location = (
        ", ".join(value for value in [label, province_label] if value)
        if choice_type == "serviceable_city"
        else province_label
    )
    if not location:
        return

    replaced_keys = {"location", "service_type"}
    retained = [
        signal
        for signal in signals
        if str(signal.get("key") or "") not in replaced_keys
    ]
    city_label = label if choice_type == "serviceable_city" else ""
    choice_metadata = {
        "choice_ref": str(validated_choice_context.get("choice_ref") or ""),
        "presentation_ref": str(
            validated_choice_context.get("presentation_ref") or ""
        ),
    }
    validated_signals = [
        {
            "key": "location",
            "label": "Location",
            "value": location,
            "status": "tool_grounded",
            "source": "validated_choice_action",
            "confidence": "high",
            "safe_for_action": bool(city_label),
            "requires_validation": not bool(city_label),
            "relevance": "Validated location selection",
            "ask_timing": "current_order_step",
            "relation": "selected",
            "resolution": {
                "status": "resolved_location",
                "display_label": location,
                "city_hint": city_label or None,
                "province_hint": province_label or None,
                "location_precision": (
                    "city_or_area" if city_label else "province_or_region"
                ),
                "safe_for_action": bool(city_label),
            },
            "metadata": dict(choice_metadata),
        },
        {
            "key": "service_type",
            "label": "Service type",
            "value": "installation",
            "status": "tool_grounded",
            "source": "validated_choice_action",
            "confidence": "high",
            "safe_for_action": True,
            "requires_validation": False,
            "relevance": "Validated checkout selection",
            "ask_timing": "current_order_step",
            "relation": "selected",
            "metadata": dict(choice_metadata),
        },
    ]
    state_context["background_signals"] = [*retained, *validated_signals]
    missing_info = (
        state_context.get("missing_info")
        if isinstance(state_context.get("missing_info"), dict)
        else {}
    )
    missing_info["lead_qualification"] = build_lead_qualification_snapshot(
        state_context["background_signals"]
    ).to_dict()
    state_context["missing_info"] = missing_info
    state_context["validated_choice_signal_boundary"] = {
        "status": "applied",
        "reason": "validated_location_choice_owns_current_turn_state",
        "replaced_keys": sorted(replaced_keys),
        "choice_type": choice_type,
    }


def _tool_results_include_human_handoff(
    tool_results: Sequence[Dict[str, Any]],
) -> bool:
    """Return true when the current turn recorded a typed handoff request."""

    for result in tool_results or []:
        if not isinstance(result, dict) or result.get("name") != "request_human_handoff":
            continue
        full = (
            result.get("full_result")
            if isinstance(result.get("full_result"), dict)
            else {}
        )
        compact = (
            result.get("result")
            if isinstance(result.get("result"), dict)
            else {}
        )
        if str(full.get("status") or compact.get("status") or "") in {
            "requested",
            "already_requested",
        }:
            return True
    return False


FINAL_COMPOSER_SYSTEM_PROMPT = """You are the Runtime V7 final response composer for Gulong.PH.

Tools have already run. Do not call tools, do not request tools, and do not
write ordinary prose outside the response_format object.

Highest-priority customer voice:
- First obey customer_voice_contract.language. When it says
  continue_recent_free_text_customer_language, the current user message is
  synthetic tracked-action text and is not a language sample. Continue the
  customer's most recent natural free-text language and register from
  recent_turns; this rule overrides the wording or language of the tracked
  button label and its synthetic action message.
- Otherwise match the language of the latest natural customer message. If it
  is entirely English, reply in friendly natural English without Filipino
  fillers. If it is Filipino or Taglish, reply in natural conversational
  Filipino/Taglish.
- Write like a friendly human Filipino customer-service agent, not a policy
  table. Never start with "Regarding". Never write "as payment method" or
  "bilang payment method". If a named method is unsupported, simply say it
  is not offered yet in the customer's language, then continue naturally.
- Do not attach a bank/provider to another validated method. When a shorter
  installment fact has no bank in its evidence, keep it unbranded even when a
  separate longer plan names a bank.
- Related commercial facts belong in one conversational thought with a natural
  contrast, not bullets or repeated availability sentences.
- Speak as Gulong.ph for routine grounded catalog and service results: say what
  we have or offer using natural kami/tayo/natin wording, or state the useful
  result directly. Do not narrate that the assistant or team found, saw, or
  located the result.
- Ask at most one next question. Ask the single most useful unresolved input and
  defer others. State understood details; never precede the CTA with a separate
  permission or confirmation question.
- If customer_turn_plan authorizes request_human_handoff, acknowledge that the
  request was recorded and end the automated sales turn. State that a human
  teammate still needs to pick up the chat when useful. Never claim the customer
  is already connected, assigned, transferred, or successfully escalated.

""" + GULONG_BUSINESS_IDENTITY_PROMPT + """

""" + COMPLETE_TURN_COMPOSITION_PROMPT + """

Return one structured object containing request_coverage, claim_assertions when
needed, and response_units using the schema:
- type=text with content.text for customer-facing prose.
- type=render_surface with content.surface_ref for exact runtime-rendered cards,
  partner rows, slot rows, order summaries, or payment requests.
- type=image with content.image_ref, content.url, and content.alt only when the
  image is explicitly grounded in the provided presentation surface.
response_units must contain at least one customer-visible unit. Never return an
empty list. For every customer_turn_plan.request_obligations item, return exactly
one request_coverage row using its exact obligation_id. Use its
expected_disposition when supplied; otherwise use disposition=answered because
the obligation has grounded current-turn evidence. A pending-validation
obligation must be stated explicitly in the mapped text and must not be turned
into a positive exact-case claim. Map text answers through response_unit_indexes
and renderer answers through surface_refs; do not invent IDs or refs. Supporting
replacements are not separate customer requests and must not receive their own
coverage row.
Text units must be plain ManyChat-safe text. Do not use HTML tags such as
<ul>, <li>, <br>, <p>. Do not use Markdown formatting such as **bold**,
asterisk bullets, underscores, code fences, or markdown tables. Emojis are
allowed when natural. Use short plain lines; use simple hyphen bullets only
when a list is genuinely needed.
Avoid spatial references such as "below", "above", "sa baba", or "sa taas"
because runtime-rendered surfaces may be inserted before or after text units.
Say "Pakitingnan po yung summary/details" instead of pointing to page position.

Use presentation_surfaces as read-only grounding. The runtime inserts exact
prices, promos, URLs, partner rows, slot rows, policy notes, order summary
bodies, and payment instruction bodies. Do not rewrite those bodies in text units. Use text units only for a
short lead-in, direct explanation, comparison, and useful next step.
Each surface may include customer_visible_surface_manifest. Use its
renderer_owned_message_roles to anticipate the complete outbound sequence and
avoid generic prose that merely announces content the renderer already supplies.
The manifest describes message roles, not additional fact authority, and a role
marked "may_render" can still be suppressed by channel/session conditions.
When customer_turn_plan is present, treat it as a non-prescriptive authorization
envelope: it lists facts, state changes, side effects, and renderer-owned surfaces
that are available for this turn. It does not choose a sales stage or CTA. Answer
the latest customer goal first, choose the most useful available surface when one
helps, and reason about one natural next booking step from the whole conversation.
Do not ask again for already_satisfied_fields. The renderer owns full cards and
exact surface facts.
Every available surface with required=true must be rendered exactly once. A
surface with response_role=supporting_replacement replaces duplicate explanatory
prose: render it beside its active direct-answer surface, but do not add a caption,
separate explanation, or separate CTA for that supporting topic. Keep the one
natural model-owned CTA, if useful, on the active direct-answer decision.
When known_customer_context is present inside customer_turn_plan, reuse those
customer details instead of asking for the same value again. A field marked
requires_validation is known conversational context, not action authority: use
the known value in the appropriate tool/check when needed, but do not claim that
service, fulfillment, schedule, payment, or booking is validated from it.
Treat authorized_claim_categories as a positive allowlist for factual claims in
this turn. In particular, a customer-provided area, date, time, installation
preference, or schedule preference is a request to validate later; it is not
evidence that installation, a partner, or a slot is available. Do not say or
imply service availability unless service_availability is listed, and do not
say or imply date/time availability unless schedule_availability is listed.
You may still acknowledge the preference and explain that it can be checked
after the active product or location decision is completed.
The general_tire_advisory category authorizes stable, non-commercial tire
principles and calibrated qualitative recommendations from the model's tire
expertise, including practical advice about named options when every subjective
attribute is not published in the catalog. It never authorizes an exact measured
test result, certification, fitment, stock, price, promotion, warranty,
installment, serviceability, schedule, or performance guarantee. Combine it with
product_facts or brand_facts when discussing named options, and make clear when a
conclusion is practical judgment rather than a verified laboratory result.
Use business_identity_facts for the reviewed online-first operating model,
head-office installation site, approved partner-network, and
warehouse-to-booked-site facts.
Cite the business-identity evidence ref supplied in the current tool result or
turn plan. Do not categorize those facts as business_contact_facts, and do not
extend them into exact coverage or availability.
Use faq_facts for facts stated by an authorized FAQ/policy result and cite that
result's exact FAQ evidence ref. A general delivery-process policy can establish
that delivery is offered and describe its published fulfillment paths, but it
does not establish serviceability for the customer's exact address. Categorize
an exact-address coverage claim as service_availability; omit it unless a
separate current service provider authorizes that category.
When progression_context.required_faq_fact_answers is present, each listed FAQ
is a required answer to the customer's current question, not optional context.
Answer its supported scope before the next question and cite its exact
evidence_ref under faq_facts. If the customer asked for a narrower fact that the
FAQ does not authorize, preserve the supported general answer and clearly keep
the narrower point pending validation; do not delete the whole FAQ answer.
When case_specific_scope_boundary_required=true, the mapped response text must
also state required_scope_boundary_answer in natural customer language. Do not
confirm the named place, infer that it belongs to the policy region, or use a
positive yes/no answer for exact serviceability. Do not imply that tire size,
address, checkout, or another input is what validates that pending point unless
current provider evidence explicitly says so. A tire-shopping CTA may follow
only as a separate goal. Map the corresponding scope_boundary request
obligation with disposition=pending_validation.
Return claim_assertions for factual text, mapping response-unit indexes and
current evidence refs for service, schedule, or FAQ facts. Preferences and
future checks are not availability; never omit an availability assertion. The
runtime validates typed declarations, not prose regexes. Service claims require
a service_area_claim for the queried area. If installation_partner_summary is
available, render it once and do not restate availability. Keep other answers
or the CTA separate. Honor repeat_prior_product_result.
Use only the exact evidence refs supplied in customer_turn_plan or current
results. Never invent a symbolic ref such as "validated_selected_product".
For every brand_facts assertion, fact_fields is required and must list every
published structured field used by those response units. Use only fields
listed in authorized_brand_fact_fields_by_evidence_ref for the cited evidence
refs. A manufacturer warranty duration does not authorize manufacturer
coverage, defects, start date, or claim conditions. If
gulong_guarantee.coverage is used and published conditions are available, the
same assertion must also use gulong_guarantee.conditions and the response must
preserve all of them; otherwise state only the authorized duration.
When required_commercial_claims is present, silently use it as a completeness
checklist before writing. Cover every claim exactly once while preserving its
availability, method, term, brand, and payment-option scope. Availability
values such as "puwede", "hindi_kasama", and "wala_pa" are conversational
meaning cues; translate them naturally for the customer's language. It is not
a script: combine claims that share one customer question into natural prose. A brand
established at the start of a coordinated sentence may remain the shared scope
for later "pero"/"naman"/"while" clauses; do not repeat it mechanically when
the reference stays clear.
When multiple required commercial claims share a brand or Pay Now/Pay Later
scope, say that common scope once, then weave the facts into one conversational
thought. Never emit Pay Now or Pay Later as a standalone label or repeat it for
every method.
No deterministic stage, missing-field list, or fallback CTA chooses the next
customer input. Use lead and readiness state as evidence, not instructions.
First decide whether the customer is continuing, pausing, or closing. A pause
or close without a new question/action takes precedence over sales progression:
acknowledge it without a CTA or new surface. Otherwise, after answering the
current question, choose the smallest useful next step that fits the
conversation and advances naturally toward booking. Render at most one
interactive decision layer; supporting informational surfaces may accompany it.
Treat response_seed_context as validated turn-specific context that remains
binding during final composition. For Promo Details, preserve the exact scope
of offer_summary and relevant_mechanics. A statement that a promo is applicable
to a brand's tires does not prove that every SKU, model, or size is eligible or
available; never expand it to "all", "every", or "lahat" unless the reviewed
evidence explicitly uses that universal scope. Product/size availability still
requires current product evidence.
If the customer is actively continuing and a post-surface question is useful,
it must stay on the same active_decision as the rendered choice surface. A promo
gallery may ask which promo or brand they want to check first, or whether they
want to continue with the originally requested brand without that promo;
product cards ask which product; location cards ask which location;
schedule cards ask which schedule; and payment cards ask which payment choice.
Do not jump ahead to location, schedule, payment, contact details, or order
confirmation while an earlier active choice surface is awaiting the customer.
When the customer explicitly asks to see tire/product options first and product
cards are rendered, product selection owns that turn. Keep a known province for
later, but do not ask for a city until the customer has selected a product.
Before finalizing, check each distinct subquestion in the latest customer
message against the grounded results. Answer each one briefly, including a
transparent "not listed/not yet verified" answer when the evidence lacks that
fact. Do not silently drop a subquestion just because another answer or
rendered surface is available.
When search_promo_catalog mode=targeted is present, answer the customer's promo
question directly from the leading candidate's offer_summary and
relevant_mechanics before introducing the promo_catalog render surface. State
only the mechanics relevant to the question and retain reviewed conditions such
as required quantity, eligible products, dates, and prize wording. A gallery or
Promo Details button does not replace this direct source-backed answer. Related
cards may be offered after the leading promo is explained. However, when the
rendered targeted gallery contains only that one promo, describe only that promo:
do not claim that other promos are shown, available, or covered by the CTA.
Use render_surface only with refs listed in surface_authorization.available_surfaces. Card,
bucket, item, partner, branch, or slot refs identify customer choices inside a
surface; they are not renderable surface refs. They are also not customer-facing
selection labels. Do not ask the customer to choose by "card number"; ask for
the brand, product/model, promo direction, or visible option instead. Do not
refer to products as "card 1", "card 2", or similar in customer-facing prose.
There may be more than one product render surface in the same turn, such as
current-quantity brand options plus separate 3+1 promo options. If the customer
asked for both and both surfaces are present, render both and use short text to
separate the comparison. If an order-summary or payment surface is present,
avoid rendering selected-product detail surfaces just to repeat product facts;
answer the detail briefly in text and let the order/payment surface carry the
exact body.
When current trusted state makes an order summary differ from an older
snapshot, present the current detail neutrally and ask for confirmation. Do
not tell the customer that the runtime corrected, reconciled, or updated an
internal field unless the customer explicitly changed that detail.
Do not write "ito ang summary", "details below", "order form", or similar
summary/body-introducing wording unless an order-summary render_surface or a
current build_order_summary tool result is present in the provided inputs. If
only quote, FAQ, product, or service tools ran, ask for the next missing order
detail directly or say you can prepare the summary once the missing detail is
provided.
For brand_menu_cards, the runtime owns the category cards and legend. Render the
surface, then use choice_summary only to write a natural short lead-in or CTA.
Do not rewrite category rows, brand lists, marker legends, counts, prices, or
promo markers in text units. Do not claim that a category fulfills a qualitative
preference, warranty, Tire Protection Plan, or promo unless separate current
product or brand evidence authorizes that fact. Keep the CTA aligned with the
actual control: category buttons ask for the category, not a brand hidden inside
that category. Invite the customer to choose by brand/category or ask to search
exact options when suggested_next_tool points to product_search.
For fitment_candidate_sizes, the runtime owns the possible size list. Render the
surface when it is present instead of asking only for sidewall confirmation.
Use text units to briefly explain that the sizes are candidates only and ask
the customer to confirm the exact tire sidewall size before product cards.
Do not copy renderer-owned legend, policy, card, partner, slot,
order-summary body, payment link, QR URL, account number, or payment amount
into text units.
Keep coherent lead-in sentences together before the render_surface when they
introduce the rendered options. Do not move an introductory sentence after the
cards just because it mentions visible brands, categories, or product headers.
Use the post-surface text unit for decision guidance or the next question.
Treat draft_assistant_text as the starting point for surrounding prose. You may
split, trim, or order it around render surfaces, and you may use provided
background signals, lead qualification, order readiness, and compact tool
results for next-step wording. Do not introduce factual claims that are absent
from those provided inputs.
Apply customer_voice_contract after reading draft_assistant_text. The contract
controls register and synthesis, while required_commercial_claims controls
facts. Discard draft wording that conflicts with the voice contract; the draft
is never authority for phrasing.
When interaction_packet is present, interpret the complete timestamped event
sequence together with the latest customer message and recent conversation.
runtime_relation describes only objective structure; it does not decide whether
the customer corrected a choice, wants a comparison, or needs clarification.
Return interaction_decision using only an interpretation listed in
allowed_model_interpretations and only event IDs present in the packet.
- For accept_latest, accept_once, or hierarchical_advance, include the one
  effective event ID whose trusted state should be applied.
- For compare or clarify, effective_event_ids must be empty.
- For a button-only sequence of different validated choices in the same layer,
  treat the newest action as the customer's current correction. Use compare
  only when customer-authored conversational context explicitly asks to compare;
  use clarify only when the event ordering or target is genuinely ambiguous.
- When clarify is the only allowed interpretation, return text response units
  only. Do not render product, promo, location, schedule, or payment surfaces
  until the customer resolves the choice.
- Informational promo actions never select a brand, SKU, location, schedule, or
  payment field.
Do not mention event IDs, timestamps, packets, interpretations, or validation
to the customer.
Service availability, installation-partner availability, branch availability,
and slot availability require a service tool result in the current provided
inputs. If service_action_state says no service tool result is present, discard
service availability/unavailability claims from draft_assistant_text. You may
acknowledge the customer area as noted for later service lookup or ask whether
they want installation checked after product selection.
When explaining Pay Now vs Pay Later around an order summary, adapt the wording
to the summary's Service/fulfillment. Delivery Pay Later/COD wording can mention
delivery only for delivery orders. Installation Pay Later/Pay After Service
means the reservation fee secures the tires and schedule, and the balance is
paid after/upon installation or service; do not say "upon delivery" for
installation, pickup, or home-service summaries.
If the latest customer message asks both a product-specific question and a
service/order next step, answer both from the provided grounded inputs. Use
visible product selection candidates for product-specific comparisons such as
warranty, TPP, origin, DOT, stock, promo, or price when those fields are
present. Then connect the CTA to the current service/order progress instead of
dropping the product answer.
For a DOT or manufacturing-date question about an offered, visible, or selected
tire, give that product's exact grounded DOT value directly. Do not explain the
DOT digit format unless the customer explicitly asks what DOT means or how to
read it. If no exact product is identifiable, ask for the size/product needed
to check the offered tire rather than substituting generic DOT education. If
the exact product is identified but the DOT field is empty, say it is not
listed in the product details for that option and offer to verify the actual
stock; do not claim that Gulong.ph generally lacks access to DOT data.
If the current conversation is anchored on one exact visible/selected product
and the latest customer asks a price, payment, or confirmation follow-up about
that product, do not preserve or create a CTA asking for preferred brand,
category, or which option. Product choice is already the active context. Use
the CTA for the next relevant step, such as checking delivery/installation area,
comparing a different option only if requested, or proceeding toward order
details.
If validated_selected_product is present, that exact product is already
selected for this turn. Never ask which product, brand, tire, option, or SKU
the customer wants. Continue with the latest requested service/order question
or the next unresolved field instead.
visible_product_context contains compact headers from recent product results for
continuity only. It does not prescribe a comparison, selection question, or CTA;
use it only when it helps answer the customer's latest goal.
Recognize the customer's conversational disposition from the complete latest
message and context. If the customer clearly pauses, defers a decision, says
they will return/update later, or otherwise closes the current exchange without
a new question, acknowledge that naturally and leave the door open. Do not
repeat the previous CTA and do not render another choice surface. This is a
semantic judgment, not phrase matching. If the same message still asks a new
question or requests an action, answer or perform that current goal instead.
Customer preferences guide the recommendation but are not live catalog fields.
For quietness, comfort, durability, wet grip, value, refinement, and similar
subjective questions, use stable tire expertise and learned brand/model knowledge
to give a useful, calibrated comparison or recommendation even when the catalog
does not publish that attribute. Do not turn such advice into a measured score,
certification, exact specification, or guarantee, and do not bluff when the model
does not genuinely know the named tire.
If validated_installation_selection is present, that exact partner and schedule
are already selected from trusted slot-validation evidence for order review.
Do not ask which partner or schedule again, and do not render a general partner
or slot discovery surface unless the customer explicitly asked to change or
recheck the selection. When the customer asks where installation will happen,
state the exact partner name and address from this context, preserve the
read-only/not-booked boundary, and continue with the next unresolved order
field.
When validated_installation_selection is present, treat that partner and
schedule as settled evidence. Do not ask for them again; choose the next useful
step from the customer's latest goal and the remaining factual blockers.
When a validated service no-match fallback already asks for the delivery
area/address, that is the single next input. Do not append a second permission
question such as whether delivery is okay or whether the product should be
checked for delivery.
If a service surface says service_policy_notes_will_be_inserted=true, do not
restate those policy notes in text units; let the runtime insert them. Keep any
CTA in its own text unit when possible.
For existing-order change requests, such as moving an appointment or changing
payment details, remember that current order/service tools are read-only unless
a tool explicitly confirms a mutation. You may show current details or possible
available slots, but the CTA must make clear the customer is choosing/requesting
an option for team confirmation, not that the order appointment/payment has
already been changed.
Use order_details_context when present as the read-only existing-order anchor.
If the latest customer message asks to move, reschedule, change payment, or
otherwise alter that existing order, and the tool result only shows available
options, include one explicit sentence that the order is not changed yet and
the chosen option still needs team confirmation/update. Phrase the CTA as a
request to forward or confirm the preferred option with the team, not as a
normal new-booking choice.
For service slot surfaces, preserve the tool result's schedule semantics. If
the requested day/time had no slots and the surface is showing fallback or next
available slots, describe them as the next available options and do not say or
imply that the requested day/time is available. If the status is unclear, avoid
same-day/date claims and ask the customer to choose from the shown slot options.
If the slot lookup answered an explicit availability question but the exact
tire size or SKU is still unresolved, show the source-backed availability as
provisional and make the product/size confirmation the only next requested
input. Do not simultaneously ask the customer to choose a schedule, brand, and
size. Schedule selection can resume after the product layer is resolved.
validate_installation_slot is read-only. It can ground that a visible slot,
partner, or selected schedule is available for order review, but it does not
confirm, reserve, book, secure, or submit that schedule, appointment, or
installation. Use wording like "available", "selected schedule", or "pwede
gamitin sa summary"; do not say that the schedule, appointment, or installation
is "confirmed", "reserved", "booked", or "secured" unless a separate order
submission or mutation tool explicitly confirms that state. A natural
acknowledgement of the customer's preferred date and time is welcome, but it
must not imply that Gulong.ph has completed the booking.
If service_action_state is present, it is higher priority than
draft_assistant_text for booking/reservation wording. If the draft says a slot,
schedule, branch, or partner is confirmed/reserved/booked/secured but
service_action_state says read_only or not_booked, rewrite the text to
availability or selected-for-review wording.
Use schedule_semantics when present: availability_status=next_slots_found or
fallback_or_next_available_only=true means the requested date/window was not
available in the visible rows; say the shown rows are next available schedules.
availability_status=slots_found means the visible rows are the matched slot
options. If same_day_requested=true but same_day_available=false, do not write
"available today", "pwede today", or similar wording.
If schedule_semantics has slot_availability_checked=false or
availability_status=partner_lookup_only, treat the surface as partner coverage
only. You may say there are partner options around the shown area, but do not
say whether today, same-day, a date/time, or a slot is available or unavailable.
Ask to check slots or choose a shown option only when that matches the current
customer goal.
Serviceable province/city choice cards and partner counts authorize installation
network discovery only. Do not describe those choices as delivery coverage or
delivery serviceability unless a separate current delivery-policy or provider
result authorizes that claim.
Do not render a broad promo gallery beside a product, location, schedule, or
payment decision surface unless the customer explicitly asked about promos in
the latest turn. A gallery with tracked buttons is another decision layer, not
passive decoration. When the customer did not ask about promos, do not mention
broad promo-search results in the surrounding prose either; keep the visible turn
focused on the active decision and retain promo context for a later relevant
turn.
When no current product_search or trusted product result is present, acknowledge
the requested tire size and quantity as the customer's request only. Do not turn
"need 4 tires" into an availability claim such as "may 4 tires tayo" before
product lookup.
If the current service surface/tool result is only find_installation_partners
and no find_installation_slots result is present, do not preserve draft claims
about slot availability, unavailable schedules, exact dates, or times. Partner
lookup can ground nearby installation coverage only; slot availability needs a
slot tool result.
When that partner lookup is coverage-only and no trusted product is selected,
answer the customer's coverage question first. Anonymous area-only partner rows
may be intentionally withheld and must not be described as visible choices.
Unless the customer explicitly asked to check a date/time now, do not jump from
coverage to a scheduling question. Continue naturally toward the unresolved tire
size or product choice, while reusing the already known location. If a trusted
product is already selected, the model may instead offer to check slots for that
known location. When asking for tire size or product after a coverage-only
answer, describe it as the input needed to show or choose a suitable tire before
schedule lookup; do not imply that tire size alone is the final missing input for
an available installation schedule. Until a trusted product is selected, keep
that CTA entirely on tire/product discovery: do not mention checking slots,
schedules, dates, or times in the same question. This is a semantic composition
boundary for the model, not a post-model phrase filter.

Match the main assistant voice: concise, helpful, natural Taglish when the
customer uses Taglish, and lightly sales-oriented. A light emoji is okay when it
fits the customer-facing surface, but avoid overdoing it. Avoid stiff wording
like "prioritize" in customer-facing CTAs; prefer natural phrasing such as
"alin gusto niyo i-check?", "alin unahin natin?", or "gusto niyo yung mas mura
or yung may promo?". For product cards, use grounded card headers to guide the
CTA toward cheapest/value, promo, category, or brand when those hooks are
visible. If product_search reports a quantity_promo_context, keep the wording
clear: Buy 3 Get 1 FREE is a four-tire path, so do not describe it as applying
to a smaller current quantity.

Do a conversational synthesis pass before returning response_units. Grounded
claim objects are facts to preserve, not sentences or policy rows to transcribe.
Group facts that answer one customer question into one coherent thought:
- Lead with the direct answer, then connect related positive and negative facts
  with natural transitions such as "naman", "pero", "while", or "though" when
  they fit the customer's language.
- Do not use one bullet, paragraph, or repeated sentence template per fact.
  Two or three closely related facts normally belong in one short paragraph.
- In Filipino/Taglish, use everyday chat forms such as "yung", "wala pa",
  "puwede", "natin", and contracted phrasing where natural. Use "po"
  respectfully but not in every clause. Do not force these words or copy a
  fixed template.
- Avoid policy-manual wording such as "bilang payment method", "under the
  active checkout options", "eligible/not eligible", "regarding", or
  meta-answer prefaces such as "para sa tanong ninyo tungkol sa". Start with
  the useful subject and answer directly. For a product-specific payment answer,
  a natural shape is "Sa [product/brand] po, available/hindi available..." and
  then the one pending sales decision when the customer is still continuing.
  "compatible payment methods when you are ready" unless the
  customer explicitly asks for formal policy wording. Prefer ordinary customer
  language such as "puwede", "kasama", or "wala pa".
- Keep the customer's requested scope together. Never attach a bank/provider
  to an unbranded installment row, and never generalize one unavailable plan
  into the whole bank or all payment methods being unsupported.
- Make the next question feel connected to what the customer is considering.
  Refer naturally to the current product, brand, service, or comparison instead
  of resetting to a generic intake script.
- Keep a provider and term adjacent when both identify one method, such as a
  bank plus a six-month term. For a separate installment method that has no
  provider in its validated claim, do not borrow a provider from another claim.
Naturalness must never soften, omit, or alter a validated fact. If a warmer
sentence would make the method, term, brand, payment timing, or outcome
ambiguous, keep the fact explicit and rewrite the surrounding sentence instead.

For payment compatibility answers, keep every validated method, term, brand,
and Pay Now/Pay Later scope the customer asked about, but synthesize them in
the conversational style above. Answer all related payment facts before asking
the one useful next input. Do not ask which bank or plan they mean when the
validated results already answer the named alternatives.
For a generic payment-method question, summarize only the authoritative catalog
results using payment_policy.customer_method_categories when present. Prefer
that compact list over active_methods_by_option; do not dump internal checkout
labels, IDs, or every implementation variant. If
the customer asked about a specific method, provider, bank, term, brand, or
payment-path restriction, preserve that exact grounded restriction rather than
generalizing from the category summary.
End with at most one grammatical question and one question mark. Do not offer
two alternative follow-up questions in the same turn, including two questions
joined by "or". If the customer wrote entirely in English, reply in friendly
natural English; do not force Filipino or Taglish.
For a compound payment question, answer only the payment methods and banks the
customer asked about. Do not introduce additional bank/provider names merely
because they appear elsewhere in checkout metadata.
When payment_policy.applicable_installment_options is present, it is the exact
source-backed list for this customer's generic installment question. State every
listed term and its adjacent provider association naturally; do not reduce the
list to the first checkout row and do not add another bank/provider. When
payment_policy.reservation_fee_guidance is present, treat the customer's clear
informal term or shorthand as the reservation fee, explain its grounded purpose
directly, and never invent an amount when amount_available is false. Silently use
the correct term in the answer: do not quote, echo, name, define, contrast, or
explicitly correct the customer's wording. Do not say the customer's term is
"called" reservation fee or use constructions such as "ang tawag", "tinatawag",
"ibig sabihin", or "equivalent to". Start directly with the business fact, such
as "May reservation fee po para ma-secure ang slot." If the exact amount is not available yet, do not expose
a source/data gap; connect the customer to the next grounded selection or quote
step needed to confirm it. Apply the same natural normalization to obvious shorthand,
minor typos, and informal equivalents throughout the response. Ask for
clarification only when multiple plausible meanings would materially change the
answer or action.
When an item in payment_policy.applicable_installment_options has eligible_brands
and no exact product/brand is selected, describe that term as limited to eligible
or selected brands. Do not imply it applies to every product card; the exact
installment line on each deterministic product card owns that tire's eligibility.
If product_search reports preferred_brand_presentation_status, treat it as
advisory explanation for remembered brand preferences. Do not claim the
preferred brand matched the latest filter unless it is in the rendered cards.
If useful, briefly say the shown options better fit the latest budget/category
request and offer to check the remembered brand separately.
If product_search requested_brand_status has a brand in missing, do not say
that requested brand is available for the requested size/filter set. If
available_outside_requested_filters names that brand, say it appears only
outside the requested size/filter set and present the rendered alternatives.
For match_payment_proof results with status=matched_unverified, acknowledge the
proof was received and matched to the request, but say it still needs backend or
team verification. Do not ask unrelated missing order fields after a proof
match unless the latest customer also asked to change/order something else.
For prepare_payment_request results, do not say "new QR code" or "new link"
unless the tool explicitly says it generated a new one; say "ito ulit yung
payment details" or "ito yung payment request" instead.
prepare_payment_request does not mutate the saved order payment method by
itself. When it is used because the customer asks for credit card, installment,
QR, or account details, do not say the payment method was updated, changed, or
applied to the order unless a separate mutation tool confirms that. Say that
the payment request/link/details for that route are shown.
When prepare_payment_request rendered a payment surface, or
payment_request_context says payment_action_ready=true, treat the submitted
order/payment request as already established. Do not ask for tire size, product,
contact, address, branch, or other intake fields unless the latest customer
explicitly asks to edit them or the payment tool says they are required for the
payment request. The useful next step is payment-specific, such as asking the
customer to proceed with the shown route, send proof/reference after paying, or
say which payment method they prefer if they asked for alternatives.
Only say an order was submitted, booked, created, or has an order ID when the
current tool results include submit_order status=success or order_details_context
already contains that submitted order. Only say payment details, QR, account
details, or payment link are shown when the current tool results include
prepare_payment_request status=ok or payment_request_context already contains a
payment request. If only build_order_payload ran, the correct state is
validated and ready to submit, not submitted or payment-ready.
When the customer finalizes only a product, quantity, or promo choice, describe
that product selection as final/noted and continue to the next missing booking
step. Do not say "final na ang order", "confirmed na ang order", or equivalent
until the submission authority above exists.
If only build_order_summary ran, the correct state is summary/review, not
payload-validated, submitted, processing, booked, or payment-ready. Do not say
"isusubmit na", "ipoproseso na", "ipapadala ang payment link", or similar
future-payment promises after only an order summary. Ask the customer to confirm
that the shown summary details are correct before the runtime can validate and
submit the order.
If the order summary surface is incomplete, it is still valid to render as
"order details so far" or collected details for review. Do not say it is ready,
submitted, booked, or payment-ready. If the remaining blockers are several
low-friction booking details such as the customer's full name, contact number,
email, and Pay Now/Pay Later preference, it is reasonable to request them
together in one compact message so the customer can finish in one reply. Match
the customer's language and keep the request conversational; never switch to a
formal all-English form spiel in an otherwise Taglish conversation. For larger
decisions or facts that require separate validation, ask only the one most useful
next question.
When build_order_payload returns status=ready or can_submit_order=true, it has
validated a submit-ready payload but has not created the order. If you ask the
customer to review or confirm submission, include the key validated details from
order_payload_summary in text: product, quantity, fulfillment/branch or delivery
details, schedule when present, payment option/method, and total. Do not say
"review the details" or "tama ang details" without showing or summarizing those
details. Then ask one clear confirmation to submit/create the order.
For payment link/QR/account surfaces, prefer a concrete CTA like sending proof
or reference number after payment over a generic "let me know if you have
questions" close.
When submit_order and prepare_payment_request both succeeded in the current
turn, keep the surrounding text in natural Gulong Taglish. Prefer wording like
"Placed na po yung order" and "Pakisend na lang po yung proof/reference after
payment" instead of stiff English such as "Your order has been placed" or "You
may now proceed." Do not rewrite renderer-owned payment links, account numbers,
QR URLs, or amounts.
Use response_continuity when present. If it says fresh_greeting_allowed=false,
continue directly and do not open with "Hello", "Hi", "Good day", or similar
greetings because the customer is already mid-thread. Treat leading greetings
in draft_assistant_text as discardable; discard draft greetings instead of
preserving them unless the latest customer message itself greets again or the
context clearly indicates a new conversation after a long gap. Start with the
actual continuation, answer, or next step instead.
Use first_turn_intro_context when present. mode=full_intake remains a runtime-
owned three-bubble guided intake: do not repeat its greeting, info request, or
tire-size guide, and write only a non-greeting continuation. For mode=welcome_only,
model_will_compose=true means you own the complete first customer-facing text
bubble. Open naturally for the customer's language and context, identify
Gulong.ph, acknowledge or answer the actual request, and place that complete text
unit before any render_surface. Vary the wording and rhythm when appropriate;
do not copy the fixed fallback welcome or mechanically attach a generic greeting
to a bare lead-in. Runtime uses fixed welcome copy only if a valid model-composed
opening is unavailable.
For a first turn with no usable tire, vehicle, brand, preference, or location
detail and no specific service, policy, business, or order request, do not dump a
multi-field intake list or ask permission to check information. Acknowledge the
exact entry goal and ask only one connected discovery question, commonly tire
size or vehicle. For tire-help, lead with help and make that discovery input the
main next step. For a bare greeting, use a compact welcome plus one discovery
question. An already-authorized reviewed promo catalog may accompany a generic
availability, ambiguous-price, or tire-help entry when it is genuinely useful,
but it must not replace the answer or discovery question. If the tool loop did
not supply a useful surface, or the catalog was already shown recently, do not
mention, promise, or invite the customer to browse current promos. When the
customer already supplied meaningful details or asked a specific question,
answer and use it before choosing the next step rather than restarting intake.
This is not permission to insert or repeat a promo surface regardless of context.
If the draft is straight English but the customer uses Filipino/Taglish words,
short Taglish shopping phrasing, or a form-like intake with local terms such as
"basta", "po", "hm", "magkano", "non china", or Philippine locations, rewrite
the lead-in and CTA into natural Gulong Taglish. Avoid repeating the same stock
opening across simple "hm <size>" turns. Ground the lead-in in what the visible
cards actually show, such as premium-to-budget spread, cheapest option, promo,
warranty/TPP, requested brand, or exact size. Useful phrasing can be "Meron po
tayo for <size>", "Ito po yung options natin for <size>", "May premium to
budget choices po tayo", or "Pinaka-value yung may promo"; choose one that fits
the current cards instead of copying a template. Keep CTAs natural, such as
"alin gusto niyo i-check?", "alin unahin natin?", or "gusto niyo yung mas mura
or yung may promo?", and avoid straight English phrases like "Here are some
options" or "Which one would you like to check out?".
When trusted catalog or service results show what Gulong.ph offers, write as a
Gulong.ph representative using natural collective language such as
"kami", "tayo", or "natin". Avoid routine lead-ins that sound like an outside
assistant reporting that it "found" somebody else's inventory, and avoid
narrating visible UI organization with phrases equivalent to "grouped as
requested". State the useful availability, range, benefit, or distinction
directly. This never authorizes an inventory or service claim that the trusted
results do not support.
Never use search-intermediary lead-ins such as "may nakita po ako/kami/tayo",
"nakahanap po ako/kami/tayo", "I found", or "we found" for routine grounded
catalog or service results. Say "meron po kami/tayo", "ito po yung options
natin", or state the result directly in wording that fits the turn. For tire
quantity, use "pcs" or "tires"; do not translate it to "piraso" unless the
customer personally used that word in their natural free-text message.
For a simple price-tier/category surface, one direct availability sentence is
enough before the cards. Let the cards carry counts, brands, ranges, promos, and
TPP markers; do not narrate their grouping or summarize every marker. Ask which
price range they want to check first using everyday wording such as "tingnan"
or "unahin", not abstract verbs such as "explore" or "prioritize".

For extract_compatible_fitment results, candidate sizes are not confirmed
fitment. Describe them as possible/candidate sizes, ask the customer to confirm
the exact sidewall tire size, and never ask for vehicle year/model year. Rewrite
draft wording such as "perfect fit" or "common tire sizes" into provisional
language like "para sure tayo" and "possible sizes". If lead qualification is
incomplete and tire_brand or location is missing, include one short add-on such
as asking the customer to send preferred brand or location too, but keep size
confirmation as the main CTA.

Keep the customer's language and tone. Use casual Taglish when appropriate.
Never expose internal refs, tool names, runtime fields, schemas, or diagnostics
to the customer. Never claim fitment, stock, order, reservation, payment, or
slot confirmation unless the provided tool results explicitly ground that claim.
"""

PAYMENT_POLICY_COMPOSER_SYSTEM_PROMPT = """You are the Runtime V7 final response composer for a Gulong.PH payment inquiry.

Tools have already run. Return only the response_format object with
response_units. Use type=text and content.text. Do not call tools, add a
renderer surface, or expose policy/resolver/validation terminology.

Write as a friendly human Filipino customer-service agent:
- Match the latest customer's language. Use natural conversational
  Filipino/Taglish for Filipino or Taglish input, and natural English for an
  entirely English message.
- Preserve every item in required_commercial_claims exactly once: method,
  availability, brand, term, and non-empty Pay Now/Pay Later scope.
- Treat required_faq_fact_answers as direct answer obligations. Answer the
  latest payment question from those authored facts before any optional CTA.
- Say a shared brand and Pay Now/Pay Later scope once, then connect related
  facts naturally with "naman", "pero", "while", or another fitting contrast.
- Do not write a policy row per fact. Do not use bullets for related payment
  facts. Avoid stiff phrases such as "bilang payment method", "eligible",
  "not eligible", "under the active checkout options", or "Regarding".
- Prefer compact, spoken chat phrasing such as "wala pa tayong", "puwede yung",
  and "hindi kasama yung" when it fits the customer's language. Use "po"
  lightly, not in every sentence.
- Do not repeat the greeting when first_turn_intro_context says the runtime
  will prepend it.
- Answer all explicit payment questions first, then ask at most one short,
  context-linked next question. It is valid to end after the complete answer.
  Do not ask for location, product, or service information as if it validates
  a general payment answer, and do not ask a known brand again.
- First determine whether the customer is actively continuing, temporarily
  pausing, or closing. A pause, deferment, or decision not to continue without
  another question takes precedence over sales progression: acknowledge it
  naturally without repeating the prior product CTA or surface. If the same
  message asks a new question, answer that question without reviving the old CTA.
- Receipts, invoices, and quotations are transaction documents, not payment
  methods. Answer document and payment questions as separate parts from their
  respective grounded facts. Never describe a document as an unsupported
  payment option or infer a payment choice from a document request.
- When recent_turns show that product cards were presented but no tire was
  selected, and the payment answer says exact compatibility depends on that
  choice, and the customer is actively continuing, continue the existing sales thread with one brief question asking
  which shown tire the customer wants to proceed with. Do not recite the method
  catalog or restart tire discovery.

Before returning, silently compare the completed prose with
required_commercial_claims. If any fact or Pay Now/Pay Later scope is missing,
rewrite the answer. Facts come only from the supplied payload; naturalness
must never change their meaning.
"""


HUMAN_HANDOFF_DECISION_SYSTEM_PROMPT = """You are the semantic authorization gate for human takeover in a customer-service chat.

Decide what the latest customer turn means as a whole, using the short recent
conversation only for references such as "yes, please". Authorize request_now
only when the customer is asking for a human to take over this conversation now
or asking automated replies to stop now. A question about whether human support
exists, its hours, or how it works is availability_question unless the customer
also asks for takeover. Complaint, frustration, disagreement, or a request to
recheck an answer alone is not_requested. Use unclear when the turn cannot be
resolved safely from context.

Set explicit_human_takeover or explicit_stop_automation true only when that
meaning is present. Do not infer takeover merely because the words human,
agent, chatbot, bot, customer service, complaint, or mistake appear. Return the
typed response only; do not write customer-facing text.
"""


def _model_client_supports_response_format(model_client: RuntimeV7ModelClient) -> bool:
    try:
        parameters = inspect.signature(model_client.complete).parameters
    except (TypeError, ValueError):
        return False
    return "response_format" in parameters


def _model_client_supports_max_tokens(model_client: RuntimeV7ModelClient) -> bool:
    try:
        parameters = inspect.signature(model_client.complete).parameters
    except (TypeError, ValueError):
        return False
    return "max_tokens" in parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    )


def _model_client_supports_temperature(
    model_client: RuntimeV7ModelClient,
) -> bool:
    """Return whether one call may override the gateway temperature."""

    try:
        parameters = inspect.signature(model_client.complete).parameters
    except (TypeError, ValueError):
        return False
    return "temperature" in parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


def _final_composer_temperature() -> float:
    """Use a low-variance setting for last-mile instruction adherence."""

    raw = os.getenv(
        "RUNTIME_V7_FINAL_COMPOSER_TEMPERATURE",
        str(FINAL_COMPOSER_TEMPERATURE_DEFAULT),
    )
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return FINAL_COMPOSER_TEMPERATURE_DEFAULT
    return min(2.0, max(0.0, value))


def _complete_model_client(
    model_client: RuntimeV7ModelClient,
    *,
    messages: Sequence[Dict[str, Any]],
    tools: Sequence[Dict[str, Any]],
    tool_choice: str = "auto",
    response_format: Optional[Any] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "messages": messages,
        "tools": tools,
        "tool_choice": tool_choice,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    if max_tokens is not None and _model_client_supports_max_tokens(model_client):
        kwargs["max_tokens"] = max_tokens
    if (
        temperature is not None
        and _model_client_supports_temperature(model_client)
    ):
        kwargs["temperature"] = temperature
    return model_client.complete(**kwargs)


PRICING_REPAIR_SYSTEM_PROMPT = """You repair one customer-facing Gulong.PH pricing reply.

Keep the answer natural Taglish/Filipino if the customer used Taglish. Be short.
The trusted product-card pricing facts are authoritative.
Use only allowed PHP amounts from the trusted facts. Do not introduce a new
payable total, do not do new arithmetic, and do not subtract savings again.
If the draft has a wrong payable total, replace that claim with a corrected
clarification. Preserve only useful non-price next steps.
Return JSON only with response_text, used_amounts, and reason."""


def _build_pricing_repair_messages(
    *,
    current_user_message: str,
    draft_response: str,
    card: Dict[str, Any],
    unsupported_amounts: Sequence[float],
) -> List[Dict[str, Any]]:
    facts = card.get("pricing_facts") if isinstance(card.get("pricing_facts"), dict) else {}
    allowed_amounts = _authorized_pricing_amounts([card])
    payload = {
        "customer_message": str(current_user_message or "").strip(),
        "draft_response_with_unsupported_pricing": str(draft_response or "").strip(),
        "unsupported_amounts": [f"PHP {amount:,.2f}" for amount in unsupported_amounts or []],
        "trusted_product_card": {
            "brand": card.get("brand"),
            "sku_model": card.get("sku_model"),
            "tire_size": card.get("tire_size"),
            "quantity": facts.get("quantity") or card.get("quantity"),
            "payable_total": facts.get("payable_total_text") or _format_repair_money(facts.get("payable_total")),
            "total_savings": facts.get("total_savings_text") or _format_repair_money(facts.get("total_savings")),
            "unit_price": facts.get("unit_price_text") or _format_repair_money(facts.get("unit_price")),
            "pre_discount_total": facts.get("pre_discount_total_text")
            or _format_repair_money(facts.get("pre_discount_total")),
            "included_promos": facts.get("included_promos") or [],
            "payable_total_already_includes_savings": bool(
                facts.get("payable_total_already_includes_savings")
            ),
        },
        "allowed_php_amounts": [f"PHP {amount:,.2f}" for amount in allowed_amounts],
        "required_meaning": (
            "The payable total is already discounted. Savings/promos are already included in that total."
        ),
    }
    return [
        {"role": "system", "content": PRICING_REPAIR_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
    ]


def _format_repair_money(value: Any) -> str:
    amount = _coerce_amount(value)
    return f"PHP {amount:,.2f}" if amount is not None else ""


def _compact_interaction_state(value: Any) -> Dict[str, Any]:
    """Keep only model-useful delivered surface and explicit choice state."""

    if not isinstance(value, dict):
        return {}
    allowed = {
        "catalog_version_id",
        "presentation_ref",
        "surface_type",
        "promo_ids",
        "promo_types",
        "promo_titles",
        "trigger_mode",
        "selection_fingerprint",
        "choices",
        "tire_size",
        "delivery_status",
        "delivered_at",
        "validation_status",
        "choice_ref",
        "choice_type",
        "category",
        "promo_id",
        "action",
        "selected_brand",
    }
    return {
        key: deepcopy(item)
        for key, item in value.items()
        if key in allowed and item not in (None, "", [], {})
    }








def _first_turn_intro_mode_for_latest_turn(
    *,
    current_user_message: str,
) -> str:
    """Use model-owned composition for every substantive new customer turn.

    Full intake is reserved for an empty or malformed input/failure path.
    """

    if not str(current_user_message or "").strip():
        return FIRST_TURN_INTRO_MODE_FULL
    return FIRST_TURN_INTRO_MODE_WELCOME_ONLY


def _signal_values_by_key(background_signals: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for signal in background_signals or []:
        if not isinstance(signal, dict):
            continue
        key = str(signal.get("key") or "").strip()
        value = signal.get("value")
        if not key or value in (None, "", [], {}):
            continue
        values[key] = value
    return values


def _hydrate_fitment_tool_args(
    args: Dict[str, Any],
    background_signals: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Use normalized vehicle signals for fitment lookup while preserving raw model args."""

    hydrated = dict(args or {})
    values = _signal_values_by_key(background_signals)
    car_make_model = str(values.get("car_make_model") or "").strip()
    if not car_make_model:
        return hydrated
    raw_vehicle_query = str(hydrated.get("vehicle_query") or "").strip()
    if raw_vehicle_query and raw_vehicle_query != car_make_model and not hydrated.get("raw_vehicle_query"):
        hydrated["raw_vehicle_query"] = raw_vehicle_query
    hydrated["car_make_model"] = car_make_model
    hydrated["vehicle_query"] = car_make_model
    return hydrated




def _build_human_handoff_decision_messages(
    *,
    current_user_message: str,
    recent_turns: Sequence[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Build a bounded semantic-decision packet for proposed takeover."""

    payload = {
        "latest_customer_message": str(current_user_message or "").strip(),
        "recent_turns": [
            {
                "role": str(turn.get("role") or ""),
                "content": str(turn.get("content") or "")[:500],
            }
            for turn in (recent_turns or [])[-4:]
            if isinstance(turn, dict)
        ],
    }
    return [
        {"role": "system", "content": HUMAN_HANDOFF_DECISION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False),
        },
    ]


def _build_final_composer_messages(
    *,
    current_user_message: str,
    request_time: str,
    active_working_memory: str,
    recent_turns: Optional[Sequence[Dict[str, str]]] = None,
    background_signals: Sequence[Dict[str, Any]],
    lead_qualification: Dict[str, Any],
    order_readiness: Dict[str, Any],
    capability_profile: Dict[str, Any],
    tool_results: Sequence[Dict[str, Any]],
    draft_assistant_text: str,
    presentation_retry_events: Optional[Sequence[Dict[str, Any]]] = None,
    product_observation_store: Optional[ProductObservationStore] = None,
    order_details_context: Optional[Dict[str, Any]] = None,
    payment_request_context: Optional[Dict[str, Any]] = None,
    first_turn_intro_context: Optional[Dict[str, Any]] = None,
    selected_product_context: Optional[Dict[str, Any]] = None,
    validated_installation_context: Optional[Dict[str, Any]] = None,
    latest_order_summary_snapshot: Optional[Dict[str, Any]] = None,
    interaction_packet: Optional[Dict[str, Any]] = None,
    customer_turn_plan: Optional[Dict[str, Any]] = None,
    response_seeds: Optional[Sequence[Dict[str, Any]]] = None,
    response_seed_overrides: Optional[Sequence[Dict[str, Any]]] = None,
    tracked_interaction: bool = False,
) -> List[Dict[str, Any]]:
    promo_response_contract = _promo_fact_audit_context(tool_results)
    compact_turn_plan = deepcopy(customer_turn_plan or {})
    compact_turn_plan.pop("available_surfaces", None)
    progression = compact_turn_plan.get("progression_context")
    if isinstance(progression, dict):
        progression.pop("promo_response_contract", None)
    presentation_surfaces = _final_composer_presentation_surfaces(
        tool_results,
        customer_turn_plan=customer_turn_plan,
    )
    is_ongoing_conversation = bool(recent_turns or str(active_working_memory or "").strip())
    latest_customer_greeted = _customer_message_starts_with_greeting(current_user_message)
    response_continuity = _final_composer_response_continuity(
        is_ongoing_conversation=is_ongoing_conversation,
        latest_customer_greeted=latest_customer_greeted,
    )
    effective_order_readiness = _final_composer_effective_order_readiness(
        order_readiness,
        tool_results=tool_results,
    )
    readiness_missing = effective_order_readiness.get("missing") or []
    readiness_collected = (
        effective_order_readiness.get("collected")
        if isinstance(effective_order_readiness.get("collected"), dict)
        else {}
    )
    visible_product_context = _final_composer_visible_product_selection_candidates(
        product_observation_store,
        missing_fields=readiness_missing,
        collected_fields=readiness_collected,
    )
    required_commercial_claims = _final_composer_required_commercial_claims(
        tool_results
    )
    answer_only_turn = _answer_only_composer_turn(
        tool_results=tool_results,
        presentation_surfaces=presentation_surfaces,
        interaction_packet=interaction_packet,
        selected_product_context=selected_product_context,
        order_readiness=effective_order_readiness,
    )
    pure_payment_policy_turn = bool(
        answer_only_turn
        and all(
            isinstance(item, dict)
            and item.get("name") == "answer_order_faq"
            and _order_faq_result_is_payment_scoped(item)
            for item in tool_results
        )
    )
    payload = {
        "current_customer_message": current_user_message,
        "request_time": request_time,
        "recent_turns": [dict(turn) for turn in (recent_turns or [])[-4:]],
        "conversation_state": {
            "is_ongoing_conversation": is_ongoing_conversation,
            "latest_customer_greeted": latest_customer_greeted,
            "fresh_greeting_allowed": (not is_ongoing_conversation) or latest_customer_greeted,
        },
        "response_continuity": response_continuity,
        "first_turn_intro_context": deepcopy(first_turn_intro_context or {}),
        "active_working_memory": active_working_memory,
        "background_signals": _compact_final_composer_signals(background_signals),
        "lead_qualification": deepcopy(lead_qualification),
        "surface_authorization": _final_composer_surface_authorization(
            presentation_surfaces,
            customer_turn_plan=customer_turn_plan or {},
        ),
        "validated_selected_product": _compact_unit(
            deepcopy(selected_product_context or {})
        ),
        "validated_installation_selection": _compact_unit(
            deepcopy(validated_installation_context or {})
        ),
        "order_readiness": effective_order_readiness,
        "visible_product_context": visible_product_context,
        "order_details_context": _final_composer_order_details_context(order_details_context or {}),
        "payment_request_context": _final_composer_payment_request_context(payment_request_context or {}),
        "service_action_state": _final_composer_service_action_state(
            tool_results,
            trusted_product_selected=bool(selected_product_context),
        ),
        "interaction_packet": deepcopy(interaction_packet or {}),
        "customer_turn_plan": compact_turn_plan,
        "promo_response_contract": promo_response_contract,
        "response_seed_context": _final_composer_response_seed_context(
            response_seeds if response_seeds is not None else response_seed_overrides or []
        ),
        "draft_assistant_text": _final_composer_draft_text(
            draft_assistant_text,
            tool_results=tool_results,
        ),
        "presentation_surfaces": presentation_surfaces,
        "tool_results": _final_composer_tool_results(tool_results),
        "required_commercial_claims": required_commercial_claims,
        "customer_voice_contract": _final_composer_voice_contract(
            first_turn_intro_context=first_turn_intro_context or {},
            tracked_interaction=bool(
                tracked_interaction or interaction_packet
            ),
        ),
        "presentation_retry_context": _final_composer_retry_context(
            presentation_retry_events or [],
            tool_results,
        ),
    }
    payload = {key: value for key, value in payload.items() if value not in (None, "", [], {})}
    if answer_only_turn:
        payload = _compact_answer_only_composer_payload(payload)
    return [
        {
            "role": "system",
            "content": (
                PAYMENT_POLICY_COMPOSER_SYSTEM_PROMPT
                if pure_payment_policy_turn
                else FINAL_COMPOSER_SYSTEM_PROMPT
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def _answer_only_composer_turn(
    *,
    tool_results: Sequence[Dict[str, Any]],
    presentation_surfaces: Sequence[Dict[str, Any]],
    interaction_packet: Optional[Dict[str, Any]],
    selected_product_context: Optional[Dict[str, Any]] = None,
    order_readiness: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return whether trusted answer tools fully own this composition turn.

    The selected tools are the model-led interpretation of the latest goal.
    When they contain only FAQ or business-contact answers, prior sales-stage
    progression must not compete with that answer or imply an unrelated
    validation step. Mixed product, service, order, or renderer turns retain
    the complete composition packet.
    """

    answer_tools = {
        "answer_product_faq",
        "answer_policy_faq",
        "answer_service_faq",
        "answer_order_faq",
        "get_business_contact",
    }
    readiness = order_readiness if isinstance(order_readiness, dict) else {}
    active_order_context = bool(
        selected_product_context
        or readiness.get("collected")
        or readiness.get("high_intent_signals")
        or str(readiness.get("customer_order_intent") or "")
        in {"possible", "explicit"}
    )
    return bool(
        tool_results
        and not presentation_surfaces
        and not interaction_packet
        and not active_order_context
        and all(
            isinstance(item, dict)
            and str(item.get("name") or "") in answer_tools
            for item in tool_results
        )
    )


def _order_faq_result_is_payment_scoped(
    tool_result: Mapping[str, Any],
) -> bool:
    """Use the payment composer only for typed payment-owned FAQ evidence.

    `answer_order_faq` also owns delivery, quotation, cancellation, and other
    order questions. Tool identity alone is therefore too broad. A validated
    payment-policy object or an authored FAQ id/typed query plan must establish
    payment scope; raw customer wording is never inspected here.
    """

    for key in ("full_result", "result"):
        result = tool_result.get(key)
        if not isinstance(result, Mapping):
            continue
        if isinstance(result.get("payment_policy"), Mapping):
            return True
        faq_id = str(result.get("faq_id") or "").strip()
        if faq_id and order_faq_requires_payment_scope({"faq_id": faq_id}):
            return True
    args = tool_result.get("args")
    return bool(
        isinstance(args, Mapping)
        and order_faq_requires_payment_scope(args)
    )


def _compact_answer_only_composer_payload(
    payload: Mapping[str, Any],
) -> Dict[str, Any]:
    """Keep only current-answer authority and conversational continuity.

    Answer-only turns do not need product/service progression, lead-stage
    prompts, raw working memory, or a generated draft. Removing those parallel
    representations prevents stale CTAs from competing with the latest FAQ
    goal and materially reduces the composer prompt without weakening trusted
    fact, evidence, voice, or continuity contracts.
    """

    retained_keys = {
        "current_customer_message",
        "request_time",
        "recent_turns",
        "conversation_state",
        "response_continuity",
        "first_turn_intro_context",
        "customer_turn_plan",
        "tool_results",
        "required_commercial_claims",
        "customer_voice_contract",
        "promo_response_contract",
    }
    compact = {
        key: deepcopy(value)
        for key, value in payload.items()
        if key in retained_keys
    }
    turn_plan = compact.get("customer_turn_plan")
    if isinstance(turn_plan, dict):
        progression = turn_plan.get("progression_context")
        compact_progression = {}
        if isinstance(progression, dict):
            for key in (
                "authorized_evidence_refs_by_claim_category",
                "required_faq_fact_answers",
                "service_availability_claims_authorized",
                "schedule_availability_claims_authorized",
            ):
                if progression.get(key) not in (None, "", [], {}):
                    compact_progression[key] = deepcopy(
                        progression[key]
                    )
        compact_plan = {
            key: deepcopy(turn_plan[key])
            for key in (
                "turn_goal",
                "authorized_evidence_refs",
                "authorized_claim_categories",
                "request_obligations",
            )
            if turn_plan.get(key) not in (None, "", [], {})
        }
        if compact_progression:
            compact_plan["progression_context"] = compact_progression
        compact["customer_turn_plan"] = compact_plan
    return {
        key: value
        for key, value in compact.items()
        if value not in (None, "", [], {})
    }


def _semantic_scope_repair_base_messages(
    final_messages: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Remove invalid generated prose while retaining typed repair authority.

    Semantic scope violations mean the draft's factual meaning is unsafe. The
    repair therefore starts again from provider results, the turn plan, and
    renderer surfaces instead of anchoring on either generated draft field.
    """

    messages = deepcopy(list(final_messages or []))
    for message in reversed(messages):
        if str(message.get("role") or "") != "user":
            continue
        content = str(message.get("content") or "").strip()
        if not content.startswith("{"):
            continue
        try:
            payload = json.loads(content)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        payload.pop("draft_assistant_text", None)
        turn_plan = payload.get("customer_turn_plan")
        if isinstance(turn_plan, dict):
            turn_plan = deepcopy(turn_plan)
            turn_plan.pop("draft_conversational_content", None)
            payload["customer_turn_plan"] = turn_plan
        message["content"] = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        break
    return messages


def _final_composer_attempt_observability(
    *,
    round_name: str,
    attempt_kind: Optional[str] = None,
    repair_reason: Optional[str] = None,
    violations: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    """Return stable analytics labels for an existing composer model call."""

    attempt_kinds = {
        "final_composer": "initial",
        "final_composer_format_retry": "format_retry",
        "final_composer_repair": "contract_repair",
        "final_composer_repair_format_retry": "repair_format_retry",
        "final_composer_semantic_scope_repair": "semantic_scope_repair",
    }
    metadata: Dict[str, Any] = {
        "attempt_kind": attempt_kind or attempt_kinds.get(round_name, "unknown"),
    }
    if repair_reason:
        metadata["repair_reason"] = repair_reason
    violation_types = sorted(
        {
            str(violation.get("type") or "").strip()
            for violation in violations
            if isinstance(violation, Mapping)
            and str(violation.get("type") or "").strip()
        }
    )
    if violation_types:
        metadata["violation_types"] = violation_types
    return metadata


def _build_semantic_scope_retry_messages(
    *,
    final_messages: Sequence[Dict[str, Any]],
    semantic_scope_violations: Sequence[Mapping[str, Any]],
    policy_evidence: Sequence[Dict[str, Any]],
    promo_evidence: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Build one evidence-only repair after a semantic audit rejects meaning.

    The original customer wording and generated prose are useful during normal
    composition, but they can anchor repair to an unverified case-specific
    fact. The repair keeps typed response and renderer contracts while exposing
    only provider-authorized fact scopes. A failed repaired response falls back
    safely instead of entering another semantic composition cycle.
    """

    normalized_violation_types = [
        str(violation.get("type") or "").strip()
        for violation in semantic_scope_violations
        if isinstance(violation, Mapping)
        and str(violation.get("type") or "").strip()
    ]
    model_repair_contracts = [
        deepcopy(dict(contract))
        for violation in semantic_scope_violations
        if isinstance(violation, Mapping)
        for contract in [violation.get("repair_contract")]
        if isinstance(contract, Mapping) and contract
    ]
    semantic_scope_constraints: Dict[str, Any] = {}
    if any(
        violation_type.startswith("answer_goal_")
        for violation_type in normalized_violation_types
    ):
        misaligned = any(
            str(violation.get("answer_goal_alignment") or "") == "misaligned"
            for violation in semantic_scope_violations
            if isinstance(violation, Mapping)
        )
        has_general_policy = any(
            str(item.get("applicability") or "") == "policy_general"
            for item in policy_evidence
            if isinstance(item, Mapping)
        )
        semantic_scope_constraints["answer_goal_scope"] = {
            "allowed_answer_scope": (
                "authored FAQ facts that directly answer the customer request"
            ),
            "unrelated_faq_answers": "omit",
            **(
                {
                    "required_action": (
                        "ask one concise clarification without repeating the "
                        "unrelated FAQ answer"
                    )
                }
                if misaligned
                else {}
            ),
            **(
                {
                    "customer_origin_details": "omit unless separately authorized",
                    "exact_case_status": "not confirmed and still pending",
                    "broad_policy_alone_is_insufficient": True,
                    "direct_case_answer": "do_not_answer_yes_or_no",
                }
                if has_general_policy
                and "answer_goal_unsupported" in normalized_violation_types
                else {}
            ),
        }

    promo_searches = [
        search
        for search in promo_evidence.get("promo_searches") or []
        if isinstance(search, dict)
    ]
    category_surfaces = [
        surface
        for surface in promo_evidence.get("category_choice_surfaces") or []
        if isinstance(surface, dict)
    ]
    if promo_searches and all(
        search.get("provider_available") is True
        and not search.get("applicable_promo_refs")
        for search in promo_searches
    ):
        scoped_negative_results = [
            {
                "tire_size": search.get("tire_size"),
                "requested_brands": list(search.get("requested_brands") or []),
                "unmatched_requested_brands": list(
                    search.get("unmatched_requested_brands") or []
                ),
                "applicable_promo_count": 0,
            }
            for search in promo_searches
        ]
        semantic_scope_constraints["empty_promo_search_scope"] = {
            "required_scoped_negative_results": scoped_negative_results,
            "required_negative_answer": "state every scoped negative result",
            "verified_alternative_promo_count": 0,
            "alternative_promo_availability": "none_verified",
            "promo_alternative_result": (
                "no verified applicable alternative was returned by this search"
            ),
            "required_alternative_answer": (
                "state that no verified applicable alternative was returned"
            ),
            "category_surface_role": (
                "non-promo shopping continuation" if category_surfaces else "none"
            ),
            "required_category_surface_meaning": (
                "choose a price category to continue ordinary product shopping"
                if category_surfaces
                else "none"
            ),
            "allowed_promo_claim_scope": (
                "only the requested-brand negative results listed above"
            ),
            "other_brand_promo_claims": "forbidden_without_verified_promo_refs",
            "forbidden_category_implication": (
                "promo, discount, bundle, free item, or eligibility"
            ),
            "required_customer_answer_meanings": [
                {
                    "meaning": "requested search scope has no matching promo",
                    "scopes": scoped_negative_results,
                },
                {
                    "meaning": "no verified promo alternative was returned",
                    "verified_alternative_promo_count": 0,
                },
                *(
                    [
                        {
                            "meaning": (
                                "price categories are ordinary product shopping "
                                "choices, not promo alternatives"
                            )
                        }
                    ]
                    if category_surfaces
                    else []
                ),
            ],
        }

    trusted_payload: Dict[str, Any] = {}
    base_messages = _semantic_scope_repair_base_messages(final_messages)
    for message in reversed(base_messages):
        if str(message.get("role") or "") != "user":
            continue
        content = str(message.get("content") or "").strip()
        if not content.startswith("{"):
            continue
        try:
            candidate = json.loads(content)
        except (TypeError, ValueError):
            continue
        if isinstance(candidate, dict):
            trusted_payload = candidate
            break

    compact_turn_plan = deepcopy(
        trusted_payload.get("customer_turn_plan") or {}
    )
    progression = compact_turn_plan.get("progression_context")
    if isinstance(progression, dict):
        progression.pop("promo_response_contract", None)
    trusted_promo_contract = (
        trusted_payload.get("promo_response_contract")
        if isinstance(
            trusted_payload.get("promo_response_contract"), Mapping
        )
        else promo_evidence
    )
    retry_payload = {
        "type": "final_composer_semantic_scope_evidence_retry",
        "violation_types": normalized_violation_types,
        "model_semantic_repair_contracts": model_repair_contracts,
        "semantic_scope_constraints": semantic_scope_constraints,
        "general_policy_evidence": list(policy_evidence or []),
        "promo_response_contract": deepcopy(
            dict(trusted_promo_contract or {})
        ),
        "conversation_state": deepcopy(
            trusted_payload.get("conversation_state") or {}
        ),
        "response_continuity": deepcopy(
            trusted_payload.get("response_continuity") or {}
        ),
        "first_turn_intro_context": deepcopy(
            trusted_payload.get("first_turn_intro_context") or {}
        ),
        "customer_turn_plan": compact_turn_plan,
        "interaction_packet": deepcopy(
            trusted_payload.get("interaction_packet") or {}
        ),
        "surface_authorization": deepcopy(
            trusted_payload.get("surface_authorization") or {}
        ),
        "presentation_surfaces": deepcopy(
            trusted_payload.get("presentation_surfaces") or []
        ),
        "required_commercial_claims": deepcopy(
            trusted_payload.get("required_commercial_claims") or []
        ),
        "customer_voice_contract": deepcopy(
            trusted_payload.get("customer_voice_contract") or {}
        ),
        "instruction": (
            "Return one concise final schema object using only the fact "
            "evidence in this packet. The source customer wording and prior "
            "drafts are deliberately omitted because they contain context, "
            "not factual authority. Do not reconstruct, name, acknowledge, "
            "or affirm a customer-specific entity or outcome unless it is "
            "explicitly present in authorized evidence. State a general "
            "policy only as general policy. Apply semantic_scope_constraints "
            "literally to the response meaning. When the constraint requires "
            "an explicit exact-case status, include a clear natural customer-"
            "visible sentence that the case is not yet confirmed and still "
            "needs checking without a yes/no case answer; broad policy alone "
            "is invalid. A successful empty promo "
            "search may support only its scoped negative result; it does not "
            "authorize an absent offer. Apply semantic_scope_constraints "
            "literally to the response meaning, including every required "
            "answer and prohibited implication. Also satisfy each model "
            "semantic repair contract; those contracts describe the auditor's "
            "whole-response resolution and do not supply customer copy. Never "
            "present another "
            "customer input "
            "as required or sufficient to validate a pending policy fact "
            "unless the packet authorizes that process; keep any shopping "
            "CTA separate and optional. Preserve required renderer surfaces, "
            "exact evidence refs, natural customer-service language, and at "
            "most one useful next question. Do not mention evidence, audits, "
            "validation, repair, or internal rules."
        ),
    }
    retry_payload = {
        key: value
        for key, value in retry_payload.items()
        if value not in (None, "", [], {})
    }
    original_system = next(
        (
            str(message.get("content") or "")
            for message in base_messages
            if str(message.get("role") or "") == "system"
        ),
        FINAL_COMPOSER_SYSTEM_PROMPT,
    )
    return [
        {"role": "system", "content": original_system},
        {
            "role": "user",
            "content": json.dumps(
                retry_payload,
                ensure_ascii=False,
                indent=2,
            ),
        },
    ]


def _final_composer_response_seed_context(
    seeds: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Keep validated turn-specific guidance available to final composition."""

    output: List[Dict[str, Any]] = []
    for seed in seeds[:4]:
        if not isinstance(seed, dict):
            continue
        item = {
            "type": str(seed.get("type") or "").strip(),
            "priority": str(seed.get("priority") or "").strip(),
            "guidance": str(seed.get("guidance") or "").strip()[:3000],
        }
        evidence = seed.get("evidence")
        if isinstance(evidence, Mapping):
            item["evidence"] = _compact_unit(deepcopy(dict(evidence)))
        output.append(
            {
                key: value
                for key, value in item.items()
                if value not in (None, "", [], {})
            }
        )
    return output


def _final_composer_required_commercial_claims(
    tool_results: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Translate validated payment facts into composer-safe constraints."""

    output: List[Dict[str, Any]] = []
    for policy in payment_policies_from_tool_results(tool_results):
        claim = payment_claim(policy)
        if not claim:
            continue
        availability = {
            "eligible": "puwede",
            "not_eligible": "hindi_kasama",
            "unsupported": "wala_pa",
        }.get(str(claim.get("outcome") or ""))
        if not availability:
            continue
        output.append(
            {
                "availability": availability,
                "method": _final_composer_payment_method_label(
                    claim.get("method")
                ),
                "brand": claim.get("brand") or "",
                "payment_option": (
                    payment_option_label(claim.get("payment_option"))
                    or claim.get("payment_option")
                    or ""
                ),
                "source": claim.get("source") or "",
                "source_updated_at": claim.get("source_updated_at"),
            }
        )
    return output


def _final_composer_voice_contract(
    *,
    first_turn_intro_context: Dict[str, Any],
    tracked_interaction: bool = False,
) -> Dict[str, Any]:
    """Return only turn-specific voice deltas not already in the system prompt."""

    contract = {
        "register": "friendly_human_customer_chat",
        "language": (
            "continue_recent_free_text_customer_language"
            if tracked_interaction
            else "match_the_current_customer_message"
        ),
        "language_boundary": (
            "tracked action text is synthetic; use the latest natural customer "
            "message in recent_turns as the language sample"
            if tracked_interaction
            else "English stays English; Filipino or Taglish may use natural Taglish"
        ),
        "continuity": (
            "compose_first_turn_opening"
            if first_turn_intro_context.get("model_will_compose")
            else (
                "runtime_prepends_opening_do_not_repeat"
                if first_turn_intro_context.get("runtime_will_prepend")
                else "continue_naturally"
            )
        ),
    }
    if tracked_interaction:
        contract["synthetic_action_text_is_language_sample"] = False
    return contract


def _final_composer_commercial_answer_contract(
    tool_results: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Group validated claims so the composer can synthesize shared scope."""

    claims = _final_composer_required_commercial_claims(tool_results)
    if not claims:
        return {}
    scoped_brands = {
        str(item.get("brand") or "").strip()
        for item in claims
        if str(item.get("brand") or "").strip()
    }
    scoped_options = {
        str(item.get("payment_option") or "").strip()
        for item in claims
        if str(item.get("payment_option") or "").strip()
    }
    single_unsupported = (
        len(claims) == 1
        and claims[0].get("availability") == "wala_pa"
    )
    return {
        "shared_scope": {
            "brand": (
                next(iter(scoped_brands))
                if len(scoped_brands) == 1
                else ""
            ),
            "payment_option": (
                next(iter(scoped_options))
                if len(scoped_options) == 1
                else ""
            ),
        },
        "shared_scope_usage": (
            "Say each non-empty shared scope once in customer-facing prose. "
            "In particular, Pay Now or Pay Later is a required factual "
            "qualifier, not an internal label."
        ),
        "facts": [
            {
                "method": item.get("method") or "",
                "availability": item.get("availability") or "",
                "wording_hint": (
                    "use a short wala pa statement without adding as/bilang "
                    "payment method"
                    if item.get("availability") == "wala_pa"
                    else "state the scoped availability conversationally"
                ),
                "brand": (
                    ""
                    if len(scoped_brands) == 1
                    else item.get("brand") or ""
                ),
                "payment_option": (
                    ""
                    if len(scoped_options) == 1
                    else item.get("payment_option") or ""
                ),
            }
            for item in claims
        ],
        "allowed_methods": [
            item.get("method") or ""
            for item in claims
            if item.get("method")
        ],
        "style_shape": (
            "Wala pa po tayong {unsupported}. {one tire-size question}"
            if single_unsupported
            else (
                "Sa current options natin, wala pa yung {unsupported}. For "
                "{shared_scope} naman, puwede yung {available}, pero hindi "
                "kasama yung {unavailable}. "
                "{one context-linked question}"
            )
        ),
        "do_not_copy_style_shape": True,
        "next_question_context": {
            "known_brand": (
                next(iter(scoped_brands))
                if len(scoped_brands) == 1
                else ""
            ),
            "do_not_reask_known_brand": len(scoped_brands) == 1,
            "preferred_focus_if_needed": "tire_size",
            "do_not_add_other_missing_fields": True,
        },
    }


def _final_composer_draft_text(
    draft_assistant_text: str,
    *,
    tool_results: Sequence[Dict[str, Any]],
) -> str:
    """Drop a policy-row draft only when claims fully own a pure FAQ turn."""

    results = [item for item in tool_results if isinstance(item, dict)]
    if (
        results
        and _final_composer_required_commercial_claims(results)
        and all(item.get("name") == "answer_order_faq" for item in results)
    ):
        return ""
    return draft_assistant_text


def _no_tool_order_progression_requires_composer(
    *,
    background_signals: Sequence[Dict[str, Any]],
    order_readiness: Dict[str, Any],
) -> bool:
    """Use the final composer for a validated order choice even without a tool."""

    collected = (
        order_readiness.get("collected")
        if isinstance(order_readiness.get("collected"), dict)
        else {}
    )
    if not str(collected.get("Product") or "").strip():
        return False
    latest_keys = {
        str(signal.get("key") or "").strip()
        for signal in background_signals or []
        if isinstance(signal, dict)
        and str(signal.get("source") or "").strip() == "latest_user_message"
        and signal.get("value") not in (None, "", [])
        and _latest_customer_signal_is_accepted(signal)
    }
    return bool(
        latest_keys.intersection(
            {
                "payment_option",
                "payment_method",
                "bank",
                "installment_months",
            }
        )
    )


def _latest_customer_signal_is_accepted(signal: Dict[str, Any]) -> bool:
    """Exclude unresolved model proposals from accepted-field progression."""

    status = str(signal.get("status") or "").strip().casefold()
    return status not in {
        "mentioned_unconfirmed",
        "invalid",
        "rejected",
        "superseded",
        "customer_reference_needs_validation",
    }




def _final_composer_response_continuity(
    *,
    is_ongoing_conversation: bool,
    latest_customer_greeted: bool,
) -> Dict[str, Any]:
    fresh_greeting_allowed = (not is_ongoing_conversation) or latest_customer_greeted
    if fresh_greeting_allowed:
        return {
            "state": "new_or_greeted_turn",
            "fresh_greeting_allowed": True,
            "instruction": "A brief greeting is allowed only if it fits the customer's wording.",
        }
    return {
        "state": "ongoing_thread",
        "fresh_greeting_allowed": False,
        "instruction": (
            "Continue directly with the answer or next step. Do not open with Hello, Hi, "
            "Good day, or similar greetings because the latest customer did not greet."
        ),
    }


def _final_composer_service_action_state(
    tool_results: Sequence[Dict[str, Any]],
    *,
    trusted_product_selected: bool = False,
) -> Dict[str, Any]:
    """Expose service tool mutation state so composer can override unsafe draft wording."""

    states: List[Dict[str, Any]] = []
    service_tool_seen = False
    successful_service_tools: List[str] = []
    rejected_service_plans: List[Dict[str, Any]] = []
    for tool_result in tool_results or []:
        tool_name = str(tool_result.get("name") or "")
        result = (
            tool_result.get("full_result")
            if isinstance(tool_result.get("full_result"), dict)
            else {}
        )
        compact = (
            tool_result.get("result")
            if isinstance(tool_result.get("result"), dict)
            else {}
        )
        if tool_name in SERVICE_TOOL_NAMES:
            if (
                result.get("error_type")
                or compact.get("error_type")
            ) == "tool_plan_not_authorized":
                rejected_service_plans.append(
                    {
                        "tool": tool_name,
                        "reason": (
                            result.get("reason")
                            or compact.get("reason")
                        ),
                    }
                )
            else:
                service_tool_seen = True
                successful_service_tools.append(tool_name)
        if tool_name != "validate_installation_slot":
            continue
        selected_slot = result.get("selected_slot") if isinstance(result.get("selected_slot"), dict) else compact.get("selected_slot")
        states.append(
            _compact_unit(
                {
                    "tool": "validate_installation_slot",
                    "status": result.get("status") or compact.get("status"),
                    "valid": result.get("valid") if result.get("valid") is not None else compact.get("valid"),
                    "selected_slot": selected_slot,
                    "mutation_state": "read_only",
                    "booking_state": "not_booked_not_reserved_not_submitted",
                    "customer_commitment_state": (
                        "selected_available_slot_for_order_review_only"
                    ),
                    "commitment_scope": [
                        "schedule",
                        "slot",
                        "appointment",
                        "installation",
                    ],
                    "allowed_customer_wording": [
                        "available selected schedule",
                        "selected schedule for order review",
                        "slot can be used in the order summary",
                        "customer preferred date and time noted for order review",
                    ],
                    "disallowed_customer_wording": [
                        "schedule or slot is confirmed, reserved, booked, or secured",
                        "appointment or installation is confirmed, reserved, booked, or secured",
                    ],
                    "draft_conflict_resolution": (
                        "If draft_assistant_text says the slot, schedule, appointment, or installation "
                        "is confirmed, reserved, booked, or secured, treat that draft wording as stale "
                        "and rewrite to read-only selection or availability."
                    ),
                }
            )
        )
    if not service_tool_seen:
        return {
            "service_lookup_state": (
                "service_tool_plan_rejected"
                if rejected_service_plans
                else "no_service_tool_result_this_turn"
            ),
            "rejected_service_plans": rejected_service_plans,
            "instruction": (
                "No authorized service tool result is available in this final-composer packet. "
                "Do not claim installation, branch, partner, or slot availability or unavailability. "
                "Acknowledge the request without inventing availability, then "
                "choose a useful validation step from the available evidence "
                "and surfaces."
            ),
        }
    if not states:
        partner_coverage_only = bool(
            successful_service_tools
            and set(successful_service_tools) == {"find_installation_partners"}
        )
        if partner_coverage_only:
            return {
                "service_lookup_state": "service_tool_result_present",
                "lookup_scope": "partner_coverage_only",
                "slot_availability_checked": False,
                "trusted_product_selected": trusted_product_selected,
                "instruction": (
                    "This turn establishes installation-partner coverage only; "
                    "no slot, date, or time lookup ran. Answer the coverage goal "
                    "directly. If no trusted product is selected and the customer "
                    "did not explicitly ask about a schedule, keep the next step "
                    "entirely on tire or product discovery. Do not describe tire "
                    "size or product choice as the final input needed to check or "
                    "book a schedule. The model still chooses the natural wording "
                    "and next product-discovery question."
                ),
            }
        return {
            "service_lookup_state": "service_tool_result_present",
            "instruction": (
                "Service facts may be used only to the extent grounded by the provided service tool results."
            ),
        }
    return {
        "service_lookup_state": "service_tool_result_present",
        "service_actions": states,
        "instruction": (
            "Service validation tools are read-only unless a separate mutation/submission tool says otherwise. "
            "Use this state over draft_assistant_text when they conflict."
        ),
    }


def _final_composer_effective_order_readiness(
    order_readiness: Optional[Dict[str, Any]],
    *,
    tool_results: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Apply same-turn trusted selections before building composer CTA context."""

    if not isinstance(order_readiness, dict) or not order_readiness:
        return {}
    readiness = deepcopy(order_readiness)
    selected_product = _final_composer_selected_product_from_tool_results(tool_results)
    if not selected_product:
        return readiness
    missing = [
        str(item).strip()
        for item in readiness.get("missing") or []
        if str(item or "").strip()
    ]
    if not any(item.lower() == "selected product/sku" for item in missing):
        return readiness
    readiness["missing"] = [
        item
        for item in missing
        if item.lower() != "selected product/sku"
    ]
    collected = readiness.get("collected") if isinstance(readiness.get("collected"), dict) else {}
    collected = dict(collected)
    product_label = _final_composer_selected_product_label(selected_product)
    if product_label:
        collected["Product"] = product_label
        collected.pop("Product options", None)
    readiness["collected"] = collected
    validation = [
        str(item).strip()
        for item in readiness.get("validation") or []
        if str(item or "").strip()
    ]
    validation.append("Product was resolved from a trusted visible product reference in this turn.")
    readiness["validation"] = _unique_strings(validation)
    return readiness


def _final_composer_selected_product_from_tool_results(tool_results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a compact selected product if same-turn tools resolved one."""

    for tool_result in reversed(list(tool_results or [])):
        if not isinstance(tool_result, dict):
            continue
        name = str(tool_result.get("name") or "").strip()
        if name not in {"resolve_product_reference", "get_product_details", "build_order_summary"}:
            continue
        result = tool_result.get("result") if isinstance(tool_result.get("result"), dict) else {}
        status = str(result.get("status") or "").strip()
        if name in {"resolve_product_reference", "get_product_details"} and status not in {"resolved", "ok"}:
            continue
        if name == "build_order_summary" and status not in {"ready", "incomplete"}:
            continue
        product = result.get("product_summary") if isinstance(result.get("product_summary"), dict) else {}
        if not product and isinstance(result.get("selected_product"), dict):
            product = result.get("selected_product") or {}
        if not product and isinstance(result.get("product"), dict):
            product = result.get("product") or {}
        if not product and isinstance(result.get("summary_preview"), dict):
            product = {"sku_model": (result.get("summary_preview") or {}).get("Product")}
        if product:
            return _compact_unit(
                {
                    "brand": product.get("brand"),
                    "category": product.get("category"),
                    "sku_model": product.get("sku_model") or product.get("label") or product.get("model"),
                    "tire_size": product.get("tire_size"),
                    "deal_price_line": product.get("deal_price_line"),
                    "promo_savings_line": product.get("promo_savings_line"),
                    "url": product.get("url"),
                }
            )
    return {}


def _final_composer_selected_product_label(product: Dict[str, Any]) -> str:
    label = str(product.get("sku_model") or product.get("label") or "").strip()
    if label:
        return label
    brand = str(product.get("brand") or "").strip()
    model = str(product.get("model") or "").strip()
    tire_size = str(product.get("tire_size") or "").strip()
    return " ".join(part for part in [brand, model, tire_size] if part).strip()


def _unique_strings(items: Sequence[str]) -> List[str]:
    output: List[str] = []
    seen = set()
    for item in items or []:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output






def _final_composer_visible_product_selection_candidates(
    store: Optional[ProductObservationStore],
    *,
    missing_fields: Sequence[str],
    collected_fields: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return latest visible product card headers when product selection is pending."""

    if store is None:
        return []
    missing_text = " | ".join(str(item or "").lower() for item in missing_fields)
    product_selection_missing = any(
        token in missing_text
        for token in [
            "selected product",
            "selected sku",
            "product/sku",
            "final product",
            "product choice",
        ]
    )
    has_product_options = any(
        str(key or "").strip().lower() in {"product options", "products", "visible products"}
        for key in collected_fields
    )
    if not product_selection_missing and not has_product_options:
        return []
    observation = store.latest()
    if observation is None or not observation.product_cards:
        return []
    headers = _product_selection_candidate_headers(observation.product_cards)
    if not headers:
        return []
    return [
        _compact_unit(
            {
                "observation_ref": observation.observation_ref,
                "presentation_ref": observation.presentation_ref,
                "selection_context": _final_composer_product_selection_context(observation.query_basis),
                "cards": headers[:4],
            }
        )
    ]


def _product_selection_candidate_headers(cards: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    headers: List[Dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        headers.append(
            _compact_unit(
                {
                    "brand": card.get("brand"),
                    "category": card.get("category"),
                    "sku_model": card.get("sku_model"),
                    "deal_price_line": card.get("deal_price_line"),
                    "promo_savings_line": card.get("promo_savings_line"),
                    "installment_text": card.get("installment_text"),
                    "warranty": card.get("warranty"),
                    "tire_protection_plan": card.get("tire_protection_plan"),
                    "quantity": card.get("quantity"),
                    "why_shown": card.get("why_shown"),
                }
            )
        )
    return headers


def _final_composer_order_details_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """Return compact read-only order details for final response composition."""

    if not isinstance(context, dict) or not context:
        return {}
    latest = context.get("latest_order_details") if isinstance(context.get("latest_order_details"), dict) else {}
    if not latest:
        return {}
    fulfillment = latest.get("fulfillment") if isinstance(latest.get("fulfillment"), dict) else {}
    payment = latest.get("payment") if isinstance(latest.get("payment"), dict) else {}
    totals = latest.get("totals") if isinstance(latest.get("totals"), dict) else {}
    items = latest.get("items") if isinstance(latest.get("items"), list) else []
    compact_items: List[Dict[str, Any]] = []
    for item in items[:2]:
        if not isinstance(item, dict):
            continue
        compact_items.append(
            _compact_unit(
                {
                    "sku": item.get("sku"),
                    "slug": item.get("slug"),
                    "quantity": item.get("quantity"),
                    "product_id": item.get("product_id"),
                }
            )
        )
    return _compact_unit(
        {
            "order_id": latest.get("order_id") or context.get("latest_order_id"),
            "order_status": latest.get("order_status"),
            "payment_status": latest.get("payment_status"),
            "fulfillment": _compact_unit(
                {
                    "branch_name": fulfillment.get("branch_name"),
                    "branch_location": fulfillment.get("branch_location"),
                    "appointment_date": fulfillment.get("appointment_date"),
                }
            ),
            "payment": _compact_unit(
                {
                    "payment_name": payment.get("payment_name"),
                    "payment_option": payment.get("payment_option"),
                    "payment_status": payment.get("payment_status"),
                }
            ),
            "totals": _compact_unit(
                {
                    "total_quantity": totals.get("total_quantity"),
                    "overall_total": totals.get("overall_total"),
                    "delivery_fee": totals.get("delivery_fee"),
                }
            ),
            "items": compact_items,
            "read_only": True,
            "mutation_allowed": False,
            "change_request_instruction": (
                "If the customer asks to move/change an existing order appointment or payment detail, "
                "say the shown option can be requested/forwarded for team confirmation and do not imply the order was changed."
            ),
        }
    )


def _final_composer_payment_request_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """Return compact payment request state for final response composition."""

    if not isinstance(context, dict) or not context:
        return {}
    latest = context.get("latest_payment_request") if isinstance(context.get("latest_payment_request"), dict) else {}
    return _compact_unit(
        {
            "latest_payment_request_ref": context.get("latest_payment_request_ref"),
            "submitted_order_exists": context.get("submitted_order_exists"),
            "payment_action_ready": context.get("payment_action_ready"),
            "latest_payment_request": _compact_unit(
                {
                    "order_id": latest.get("order_id"),
                    "order_payload_ref": latest.get("order_payload_ref"),
                    "payment_stage": latest.get("payment_stage"),
                    "expected_amount": latest.get("expected_amount"),
                    "payment_option": latest.get("payment_option"),
                    "payment_method": latest.get("payment_method"),
                    "amount_mismatch": latest.get("amount_mismatch") or {},
                    "payment_instruction_type": latest.get("payment_instruction_type"),
                    "primary_method": latest.get("primary_method"),
                }
            ),
        }
    )


def _final_composer_product_selection_context(query_basis: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only product filters useful for composing a selection CTA."""

    filters = query_basis.get("normalized_filters") if isinstance(query_basis, dict) else {}
    if not isinstance(filters, dict):
        return {}
    return _compact_unit(
        {
            "tire_size": _join_tire_size_parts(
                filters.get("section_width"),
                filters.get("aspect_ratio"),
                filters.get("rim_size"),
            ),
            "quantity": filters.get("quantity"),
            "tire_categories": filters.get("tire_categories") or [],
            "budget_max": filters.get("budget_max"),
            "budget_scope": filters.get("budget_scope"),
            "promo_only": filters.get("promo_only"),
        }
    )


def _join_tire_size_parts(section_width: Any, aspect_ratio: Any, rim_size: Any) -> str:
    section = str(section_width or "").strip()
    aspect = str(aspect_ratio or "").strip()
    rim = str(rim_size or "").strip()
    if section and aspect and rim:
        return f"{section}/{aspect}{rim}"
    if section and rim:
        return f"{section}{rim}"
    return rim or section


def _compact_final_composer_signals(signals: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    compact: List[Dict[str, Any]] = []
    for signal in signals or []:
        if not isinstance(signal, dict):
            continue
        compact.append(
            _compact_unit(
                {
                    "key": signal.get("key"),
                    "value": signal.get("value"),
                    "status": signal.get("status"),
                    "confidence": signal.get("confidence"),
                    "display_label": ((signal.get("resolution") or {}).get("display_label") if isinstance(signal.get("resolution"), dict) else None),
                }
            )
        )
    return compact


def _final_composer_tool_results(tool_results: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    compact: List[Dict[str, Any]] = []
    for tool_result in tool_results or []:
        if not isinstance(tool_result, dict):
            continue
        if (
            str(tool_result.get("completion_source") or "").strip()
            == "product_tpp_supporting_surface_policy"
        ):
            # The composer receives the typed supporting-replacement surface.
            # Withhold its catalog payload so it cannot turn the renderer-owned
            # visual back into a warranty spiel or separate promo CTA.
            continue
        name = str(tool_result.get("name") or "").strip()
        compact.append(
            _compact_unit(
                {
                    "round": tool_result.get("round"),
                    "name": name,
                    "args": _final_composer_tool_args(name, tool_result.get("args") or {}),
                    "result": _final_composer_tool_result_payload(name, tool_result.get("result") or {}),
                }
            )
        )
    return compact


def _final_composer_tool_args(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    if name == "get_brand_knowledge":
        return {
            "query": str(args.get("query") or "")[:300],
            "brands": list(args.get("brands") or [])[:4],
        }
    if name in {"find_installation_partners", "find_service_locations", "find_installation_slots"}:
        output = _model_visible_service_query_basis(args)
        candidates = args.get("trusted_order_total_candidates")
        if isinstance(candidates, list) and candidates:
            output["trusted_order_total_candidate_count"] = len(candidates)
            first = candidates[0] if isinstance(candidates[0], dict) else {}
            if first.get("presentation_ref"):
                output["trusted_product_presentation_ref"] = first.get("presentation_ref")
        return output
    return deepcopy(args)


def _final_composer_tool_result_payload(name: str, result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    payload = deepcopy(result)
    if name in {"answer_order_faq", "answer_policy_faq"} and isinstance(
        payload.get("payment_policy"),
        dict,
    ):
        claim = payment_claim(payload["payment_policy"])
        payload["payment_policy"] = (
            _final_composer_claim_from_validated_claim(claim)
            if claim
            else _compact_payment_policy_for_composer(
                payload["payment_policy"]
            )
        )
    if "checkout_plan" in payload:
        payload["checkout_validation"] = _model_visible_checkout_validation(payload.get("checkout_plan"))
        payload.pop("checkout_plan", None)
    for key in (
        "product_card_headers",
        "bucket_card_headers",
        "selected_product_cards",
        "installation_partner_card_headers",
        "installation_partner_headers",
        "service_location_headers",
        "presentation_units",
        "presentation_surfaces",
        "cards_will_be_inserted_by_runtime",
        "card_runtime_insert",
        "service_policy_notes",
        "slot_group_headers",
    ):
        payload.pop(key, None)
    if name in {"product_search", "discover_brand_buckets", "get_product_details"}:
        payload["query_basis"] = _model_visible_product_query_basis(payload.get("query_basis"))
    if name in {"find_installation_partners", "find_service_locations", "find_installation_slots"}:
        payload["query_basis"] = _model_visible_service_query_basis(payload.get("query_basis"))
        payload["service_policy_notes_will_be_inserted"] = bool(result.get("service_policy_notes"))
    if name == "search_promo_catalog":
        for key in (
            "candidates",
            "query",
            "negative_match_guidance",
            "composition_guidance",
            "applicability_summary",
        ):
            payload.pop(key, None)
        payload["promo_response_contract_is_top_level"] = True
    return _compact_unit(payload)


def _final_composer_claim_from_validated_claim(
    claim: Dict[str, Any],
) -> Dict[str, Any]:
    availability = {
        "eligible": "puwede",
        "not_eligible": "hindi_kasama",
        "unsupported": "wala_pa",
    }.get(str(claim.get("outcome") or ""), "")
    return {
        "availability": availability,
        "method": _final_composer_payment_method_label(
            claim.get("method")
        ),
        "brand": claim.get("brand") or "",
        "payment_option": claim.get("payment_option") or "",
        "source": claim.get("source") or "",
        "source_updated_at": claim.get("source_updated_at"),
    }


def _final_composer_payment_method_label(value: Any) -> str:
    """Normalize checkout row names for model-visible customer wording."""

    text = str(value or "").strip()
    text = re.sub(
        r"\b(\d{1,2})\s+months?\s+installment\s+0%\s+interest\b",
        lambda match: f"{match.group(1)}-month 0%",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(\d{1,2})\s*-\s*mos?\b",
        lambda match: f"{match.group(1)}-month",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*installment\s*\(\s*0%\s*interest\s*\)",
        " 0% installment",
        text,
        flags=re.IGNORECASE,
    )
    return " ".join(text.split())


def _model_visible_checkout_validation(plan: Any) -> Dict[str, Any]:
    """Expose checkout compatibility as facts, not routing instructions."""

    if not isinstance(plan, dict) or not plan:
        return {}
    return _compact_unit(
        {
            "status": plan.get("status"),
            "can_build_payload": plan.get("can_build_payload"),
            "blocking_issues": _model_visible_checkout_issues(plan.get("blockers")),
            "advisories": _model_visible_checkout_issues(plan.get("advisories")),
            "compatibility": plan.get("compatibility") if isinstance(plan.get("compatibility"), dict) else {},
        }
    )


def _model_visible_checkout_issues(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    output: List[Dict[str, Any]] = []
    for item in items[:6]:
        if not isinstance(item, dict):
            continue
        output.append(
            _compact_unit(
                {
                    "field": item.get("field"),
                    "value": item.get("value"),
                    "reason": item.get("reason"),
                }
            )
        )
    return output


def _model_visible_product_query_basis(query_basis: Any) -> Dict[str, Any]:
    if not isinstance(query_basis, dict):
        return {}
    filters = query_basis.get("normalized_filters") if isinstance(query_basis.get("normalized_filters"), dict) else {}
    visible_filters = {
        key: deepcopy(filters.get(key))
        for key in (
            "section_width",
            "aspect_ratio",
            "rim_size",
            "brands",
            "brand_match_mode",
            "preferred_brands",
            "excluded_brands",
            "model_or_pattern",
            "budget_max",
            "budget_scope",
            "promo_only",
            "promo_types",
            "ev_compatible",
            "gulong_guarantee_only",
            "gulong_guarantee_tiers",
            "tire_categories",
            "excluded_tire_categories",
            "terrain_types",
            "origins",
            "excluded_origins",
            "warranty_years",
            "availability",
            "installment_only",
            "installment_banks",
            "installment_months",
            "installment_max_interest",
            "quantity",
            "sort",
            "top_k",
            "semantic_query",
            "soft_preferences",
        )
        if filters.get(key) not in (None, "", [], {})
    }
    return _compact_unit(
        {
            "normalized_filters": visible_filters,
            "partial_match": query_basis.get("partial_match"),
            "stopped_reason": query_basis.get("stopped_reason"),
        }
    )


def _final_composer_retry_context(
    presentation_retry_events: Sequence[Dict[str, Any]],
    tool_results: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    events = [event for event in presentation_retry_events or [] if isinstance(event, dict)]
    if not events:
        return {}
    executed_tools: List[Dict[str, Any]] = []
    for result in tool_results or []:
        if not isinstance(result, dict):
            continue
        compact_result = result.get("result") if isinstance(result.get("result"), dict) else {}
        executed_tools.append(
            _compact_unit(
                {
                    "round": result.get("round"),
                    "name": result.get("name"),
                    "observation_ref": compact_result.get("observation_ref"),
                    "presentation_ref": compact_result.get("presentation_ref"),
                    "status": compact_result.get("status"),
                }
            )
        )
    return {
        "status": "presentation_cleanup_deferred_to_final_composer",
        "reason": (
            "A prior draft looked like it might duplicate renderer-owned presentation or policy text. "
            "Tools already ran; do not call tools or request tools. Reuse the provided tool results, "
            "presentation_surfaces and surface_authorization, then compose only surrounding text."
        ),
        "deferred_events": [
            _compact_unit(
                {
                    "round": event.get("round"),
                    "type": event.get("type"),
                    "reason": event.get("reason"),
                }
            )
            for event in events
        ],
        "executed_tools": executed_tools,
    }


def _prune_redundant_product_tools_for_validated_choice(
    profile: Any,
    *,
    validated_choice_context: Mapping[str, Any],
    selected_product_context: Mapping[str, Any],
) -> None:
    """Keep an exact product click from being resolved or searched a second time.

    The tracked-choice endpoint has already matched the click to a delivered
    product card and populated ``selected_product_context`` before the model
    turn. Re-exposing discovery and reference tools invites a second,
    contradictory selection plan instead of letting the model use the remaining
    service/order tools. This changes only the legal tool surface; it does not
    prescribe customer wording or the next conversational action.
    """

    if (
        not isinstance(validated_choice_context, Mapping)
        or validated_choice_context.get("validation_status") != "valid"
        or validated_choice_context.get("choice_type") != "product_selection"
        or not isinstance(selected_product_context, Mapping)
        or not selected_product_context
    ):
        return

    redundant_tools = {
        "search_promo_catalog",
        "present_promo_gallery",
        "product_search",
        "discover_brand_buckets",
        "extract_compatible_fitment",
        "answer_product_faq",
        "answer_service_faq",
        "resolve_product_reference",
        "get_product_details",
    }
    exposed = list(getattr(profile, "exposed_tools", []) or [])
    pruned = [name for name in exposed if name not in redundant_tools]
    if len(pruned) == len(exposed):
        return
    profile.exposed_tools = pruned
    profile.selection_reasons = [
        *list(getattr(profile, "selection_reasons", []) or []),
        "validated_product_click:product_resolution_satisfied",
    ]


def _prune_redundant_product_faq_for_brand_knowledge(
    profile: Any,
    *,
    selected_product_context: Optional[Dict[str, Any]] = None,
) -> None:
    """Prefer the published brand authority over an unrelated product FAQ.

    Brand signals can expose the full product domain for recovery. That broad
    surface must not let a generic FAQ add warranty scope when the exact brand
    publication is already the grounded candidate. Keep the FAQ when a
    selected product/observation exists.
    """

    candidate_tools = set(
        getattr(profile, "candidate_tools", []) or []
    )
    if "get_brand_knowledge" not in candidate_tools:
        return
    context_refs = (
        getattr(profile, "available_context_refs", {}) or {}
    )
    if (
        selected_product_context
        or context_refs.get("product_observation")
        or context_refs.get("product_presentation")
    ):
        return
    exposed = list(getattr(profile, "exposed_tools", []) or [])
    if "answer_product_faq" not in exposed:
        return
    profile.exposed_tools = [
        name for name in exposed if name != "answer_product_faq"
    ]
    profile.selection_reasons = [
        *list(getattr(profile, "selection_reasons", []) or []),
        "brand_knowledge:generic_product_faq_redundant",
    ]


def _prune_fulfilled_current_promo_tools(
    profile: Any,
    *,
    background_signals: Sequence[Dict[str, Any]],
) -> None:
    """Hide only promo tools already fulfilled by typed runtime preload.

    Broad current-promo discovery is interpreted semantically before the main
    tool loop and deterministically loads both provider search and gallery
    evidence. Re-exposing those same tools invites duplicate model rounds and
    cannot add authority. Named brand, campaign, mechanic, historic, and
    asserted scopes do not satisfy this boundary and keep their normal tools.
    """

    fulfilled = any(
        isinstance(signal, dict)
        and str(signal.get("key") or "").strip()
        == "promo_discovery_scope"
        and str(signal.get("value") or "").strip() == "all_current"
        and str(signal.get("source") or "").strip().casefold()
        == "latest_user_message"
        and str(signal.get("relation") or "").strip().casefold()
        == "question_only"
        for signal in background_signals or []
    )
    if not fulfilled:
        return

    redundant_tools = {"search_promo_catalog", "present_promo_gallery"}
    exposed = list(getattr(profile, "exposed_tools", []) or [])
    pruned = [name for name in exposed if name not in redundant_tools]
    if len(pruned) == len(exposed):
        return
    profile.exposed_tools = pruned
    profile.selection_reasons = [
        *list(getattr(profile, "selection_reasons", []) or []),
        "typed_current_promo_discovery:catalog_and_gallery_preloaded",
    ]


def _known_customer_context_for_turn(
    background_signals: Sequence[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Return reusable customer facts without promoting them to action truth.

    The composer needs a compact distinction between "already known" and
    "validated for a guarded action." A recognized location from a service
    observation, for example, should not be requested again, but it still does
    not prove fulfillment, serviceability, or a booking. The model owns how to
    continue; this packet only removes duplicate representations and preserves
    provenance/validation boundaries.
    """

    reusable_keys = {
        "tire_size",
        "rim_size",
        "car_make_model",
        "required_brands",
        "preferred_brands",
        "specific_sku_model",
        "quantity",
        "budget",
        "tire_category_preference",
        "location",
        "delivery_address",
        "service_type",
        "chosen_schedule_slot",
        "selected_installation_partner",
        "payment_option",
        "payment_method",
        "reservation_payment_method",
        "balance_payment_method",
    }
    output: Dict[str, Dict[str, Any]] = {}
    for signal in background_signals or []:
        if not isinstance(signal, dict):
            continue
        key = str(signal.get("key") or "").strip()
        value = signal.get("value")
        relation = str(signal.get("relation") or "asserted").strip()
        if (
            key not in reusable_keys
            or key in output
            or value in (None, "", [], {})
            or relation in {"negated", "conditional", "question_only"}
        ):
            continue
        output[key] = _compact_unit(
            {
                "value": value,
                "status": signal.get("status"),
                "source": signal.get("source"),
                "requires_validation": bool(
                    signal.get("requires_validation")
                ),
                "safe_for_action": bool(signal.get("safe_for_action")),
            }
        )
    return output


def _has_unvalidated_specific_location_signal(
    background_signals: Sequence[Dict[str, Any]],
) -> bool:
    """Return whether the latest turn names a destination needing validation.

    ``safe_for_action`` only means that a location label can be passed to a
    lookup; it does not prove delivery serviceability. Any current customer
    destination therefore keeps a general policy FAQ from becoming exact-case
    authority. The caller separately checks for provider-backed service claims.
    """

    for signal in background_signals or []:
        if not isinstance(signal, Mapping):
            continue
        if str(signal.get("key") or "") not in {"location", "city"}:
            continue
        if str(signal.get("source") or "") != "latest_user_message":
            continue
        if signal.get("value") not in (None, "", [], {}):
            return True
    return False


def _has_reusable_customer_location_signal(
    background_signals: Sequence[Dict[str, Any]],
) -> bool:
    """Return whether the turn already carries a concrete customer area."""

    generic_values = {
        "branch",
        "location",
        "outlet",
        "shop",
        "store",
        "tindahan",
    }
    for signal in reversed(list(background_signals or [])):
        if not isinstance(signal, Mapping):
            continue
        if str(signal.get("key") or "").strip() not in {"city", "location"}:
            continue
        if str(signal.get("relation") or "asserted").strip() in {
            "conditional",
            "negated",
            "question_only",
        }:
            continue
        value = " ".join(str(signal.get("value") or "").casefold().split())
        if not value or value in generic_values:
            continue
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
        if (
            str(resolution.get("status") or "").strip()
            == "ambiguous_location"
            or str(normalization.get("status") or "").strip()
            == "location_ambiguous"
            or resolution.get("ambiguity_reason")
        ):
            continue
        return True
    return False


def _build_customer_turn_plan(
    *,
    record: Dict[str, Any],
    order_readiness: Dict[str, Any],
    background_signals: Sequence[Dict[str, Any]] = (),
    draft_assistant_text: str = "",
    validated_choice_context: Optional[Dict[str, Any]] = None,
    selected_product_context: Optional[Dict[str, Any]] = None,
    validated_installation_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compile the positive authorization contract for the visible turn."""

    # Kept only for direct test/caller compatibility. Generated draft prose is
    # intentionally not duplicated inside the typed authorization envelope.
    del draft_assistant_text

    action = (
        validated_choice_context
        if isinstance(validated_choice_context, dict)
        and validated_choice_context.get("validation_status") == "valid"
        else {}
    )
    choice_type = str(action.get("choice_type") or "")
    collected = (
        order_readiness.get("collected")
        if isinstance(order_readiness.get("collected"), dict)
        else {}
    )
    already_satisfied = [
        str(key)
        for key, value in collected.items()
        if value not in (None, "", [], {})
    ]
    schedule_status = str(
        order_readiness.get("schedule_status") or ""
    ).strip()
    if schedule_status not in {
        "exact_validated",
        "flexible_preference",
    }:
        already_satisfied = [
            field
            for field in already_satisfied
            if str(field).strip().casefold()
            != "preferred installation schedule"
        ]
    available_surfaces: List[Dict[str, Any]] = []

    tool_surfaces = _final_composer_presentation_surfaces(
        record.get("tool_results") or []
    )
    latest_signal_keys = {
        str(signal.get("key") or "").strip()
        for signal in background_signals or []
        if isinstance(signal, dict)
        and str(signal.get("source") or "").strip() == "latest_user_message"
        and str(signal.get("key") or "").strip()
        and signal.get("value") not in (None, "", [], {})
    }
    has_unvalidated_specific_location = (
        _has_unvalidated_specific_location_signal(background_signals)
    )
    latest_turn_requests_promo = "promo_types" in latest_signal_keys
    has_non_promo_surface = any(
        str(surface.get("domain") or "").strip() != "promo"
        for surface in tool_surfaces
        if isinstance(surface, dict)
    )
    for surface in tool_surfaces:
        is_supporting_replacement = bool(surface.get("supporting_context"))
        is_text_only_direct_answer = bool(
            str(surface.get("type") or "").strip()
            == "service_no_match_context"
        )
        is_optional_broad_promo = bool(
            str(surface.get("domain") or "").strip() == "promo"
            and has_non_promo_surface
            and not latest_turn_requests_promo
            and not is_supporting_replacement
        )
        metadata = _planned_tool_surface_metadata(
            surface,
            required=not is_optional_broad_promo and not is_text_only_direct_answer,
            response_role=(
                "supporting_replacement"
                if is_supporting_replacement
                else "optional_context"
                if is_optional_broad_promo
                else "direct_answer"
            ),
        )
        if not metadata:
            continue
        available_surfaces.append(metadata)

    location_surface = (
        record.get("location_choice_surface")
        if isinstance(record.get("location_choice_surface"), dict)
        else {}
    )
    if location_surface:
        location_metadata = _planned_choice_surface_metadata(
            location_surface,
            decision_layer=str(
                location_surface.get("level") or "location"
            ),
            required=True,
            response_role="direct_answer",
        )
        available_surfaces.append(location_metadata)
    checkout_surface = (
        record.get("checkout_choice_surface")
        if isinstance(record.get("checkout_choice_surface"), dict)
        else {}
    )
    if checkout_surface:
        checkout_metadata = _planned_choice_surface_metadata(
            checkout_surface,
            decision_layer=(
                "payment_option"
                if checkout_surface.get("choice_type")
                == "payment_option_selection"
                else "payment_method"
            ),
            required=True,
            response_role="direct_answer",
        )
        available_surfaces.append(checkout_metadata)

        # An incomplete order summary and its immediate checkout choice are one
        # customer interaction, not competing next steps.  The deterministic
        # summary remains visible context while the checkout buttons own the
        # decision.  Keeping this relationship in the turn plan lets the model
        # compose the acknowledgement and CTA in the customer's language
        # without weakening any renderer-owned order facts.
        for planned_surface in available_surfaces:
            if (
                planned_surface.get("surface_type") == "order_summary"
                and planned_surface.get("missing_fields")
            ):
                planned_surface["supporting_context"] = True

    available_surfaces = [
        surface for surface in available_surfaces if surface
    ]
    accepted_changes: List[str] = []
    progression_context: Dict[str, Any] = {}
    if choice_type:
        accepted_changes.append(choice_type)
    if choice_type == "serviceable_province":
        progression_context.update(
            {
                "location_precision": "province_only",
                "slots_authorized": False,
                "province": str(action.get("label") or ""),
            }
        )
    elif choice_type == "serviceable_city":
        progression_context.update(
            {
                "location_precision": "city",
                "city": str(action.get("label") or ""),
                "province": str(
                    action.get("province_label")
                    or action.get("parent_label")
                    or ""
                ),
            }
        )
    elif location_surface and str(location_surface.get("level") or "") == "city":
        progression_context.update(
            {
                "location_precision": "province_only",
                "slots_authorized": False,
                "province": str(
                    location_surface.get("parent_label") or ""
                ),
            }
        )

    evidence_refs = [BUSINESS_IDENTITY_EVIDENCE_REF]
    claim_evidence_refs = _validated_response_seed_claim_evidence(record)
    claim_evidence_refs.setdefault("business_identity_facts", []).append(
        BUSINESS_IDENTITY_EVIDENCE_REF
    )
    selected_context = (
        selected_product_context
        if isinstance(selected_product_context, dict)
        else {}
    )
    selected_summary = (
        selected_context.get("product_summary")
        if isinstance(selected_context.get("product_summary"), dict)
        else {}
    )
    selected_product_refs = []
    for value in (
        selected_context.get("product_observation_ref"),
        selected_context.get("product_presentation_ref"),
    ):
        ref = str(value or "").strip()
        if ref and ref not in selected_product_refs:
            selected_product_refs.append(ref)
    if selected_product_refs:
        for category in ("product_facts", "validated_state"):
            claim_evidence_refs.setdefault(category, []).extend(
                selected_product_refs
            )
        progression_context["selected_product_transition"] = {
            "brand": str(selected_summary.get("brand") or ""),
            "sku_model": str(selected_summary.get("sku_model") or ""),
            "tire_size": str(selected_summary.get("tire_size") or ""),
            "evidence_refs": list(selected_product_refs),
        }
    if isinstance(validated_installation_context, Mapping) and (
        validated_installation_context
    ):
        installation_evidence_ref = "validated_installation_selection"
        for category in ("validated_state", "order_facts"):
            claim_evidence_refs.setdefault(category, []).append(
                installation_evidence_ref
            )
        progression_context["validated_installation_transition"] = {
            "evidence_refs": [installation_evidence_ref],
            "validation_status": str(
                validated_installation_context.get("validation_status") or ""
            ),
        }
    brand_fact_fields_by_ref: Dict[str, List[str]] = {}
    required_faq_fact_answers: List[Dict[str, Any]] = []
    for seed in record.get("response_seeds") or []:
        if (
            not isinstance(seed, dict)
            or str(seed.get("type") or "") != "promo_action"
        ):
            continue
        seed_evidence = (
            seed.get("evidence")
            if isinstance(seed.get("evidence"), dict)
            else {}
        )
        if (
            str(seed_evidence.get("status") or "") != "valid"
            or str(seed_evidence.get("action") or "").strip().lower()
            != "about_brand"
        ):
            continue
        brand_profile = (
            seed_evidence.get("brand_profile")
            if isinstance(seed_evidence.get("brand_profile"), dict)
            else {}
        )
        profile_fact_fields = _authorized_brand_profile_fact_fields(
            brand_profile
        )
        for value in (
            brand_profile.get("profile_ref"),
            *(brand_profile.get("evidence_refs") or []),
        ):
            ref = str(value or "").strip()
            if ref:
                brand_fact_fields_by_ref[ref] = list(
                    profile_fact_fields
                )
    for values in claim_evidence_refs.values():
        for value in values:
            if value not in evidence_refs:
                evidence_refs.append(value)
    for surface in available_surfaces:
        for key in ("surface_ref", "source_version"):
            value = str(surface.get(key) or "").strip()
            if value and value not in evidence_refs:
                evidence_refs.append(value)
    authorized_side_effects: List[str] = []
    service_claims_pre_authorized = (
        "service_availability"
        in _authorized_turn_claim_categories(record.get("tool_results") or [])
    )
    for tool_result in record.get("tool_results") or []:
        if not isinstance(tool_result, dict):
            continue
        full = (
            tool_result.get("full_result")
            if isinstance(tool_result.get("full_result"), dict)
            else {}
        )
        compact = (
            tool_result.get("result")
            if isinstance(tool_result.get("result"), dict)
            else {}
        )
        usable_for_claims = _tool_result_authorizes_customer_facts(
            tool_result
        )
        tool_name = str(tool_result.get("name") or "").strip()
        current_tool_refs: List[str] = []
        for key in (
            "evidence_ref",
            "observation_ref",
            "presentation_ref",
            "quote_ref",
            "order_summary_ref",
            "order_payload_ref",
            "payment_request_ref",
        ):
            value = str(
                full.get(key) or compact.get(key) or ""
            ).strip()
            if value and usable_for_claims:
                if value not in evidence_refs:
                    evidence_refs.append(value)
                current_tool_refs.append(value)
        if usable_for_claims and tool_name == "find_installation_slots":
            location_choice_surface = (
                full.get("location_choice_surface")
                if isinstance(
                    full.get("location_choice_surface"), dict
                )
                else compact.get("location_choice_surface")
                if isinstance(
                    compact.get("location_choice_surface"), dict
                )
                else {}
            )
            for value in (
                *(full.get("preview_observation_refs") or []),
                *(compact.get("preview_observation_refs") or []),
                location_choice_surface.get("presentation_ref"),
                location_choice_surface.get("source_version"),
            ):
                ref = str(value or "").strip()
                if not ref:
                    continue
                if ref not in evidence_refs:
                    evidence_refs.append(ref)
                if ref not in current_tool_refs:
                    current_tool_refs.append(ref)
        if usable_for_claims and tool_name == "get_brand_knowledge":
            for profile in full.get("profiles") or compact.get(
                "profiles"
            ) or []:
                if not isinstance(profile, dict):
                    continue
                profile_fact_fields = (
                    _authorized_brand_profile_fact_fields(profile)
                )
                for value in (
                    profile.get("profile_ref"),
                    *(profile.get("evidence_refs") or []),
                ):
                    ref = str(value or "").strip()
                    if not ref:
                        continue
                    if ref not in evidence_refs:
                        evidence_refs.append(ref)
                    if ref not in current_tool_refs:
                        current_tool_refs.append(ref)
                    brand_fact_fields_by_ref[ref] = list(
                        profile_fact_fields
                    )
        if usable_for_claims and tool_name == "search_promo_catalog":
            # Promo identities are provider-issued evidence refs, not model
            # aliases. Register them beside the search-scope ref so the
            # composer and claim validator consume the same authority set.
            for value in (
                *(full.get("allowed_promo_refs") or []),
                *(compact.get("allowed_promo_refs") or []),
            ):
                ref = str(value or "").strip()
                if not ref:
                    continue
                if ref not in evidence_refs:
                    evidence_refs.append(ref)
                if ref not in current_tool_refs:
                    current_tool_refs.append(ref)
        if usable_for_claims and current_tool_refs:
            for category in _claim_categories_for_tool_name(tool_name):
                category_refs = claim_evidence_refs.setdefault(
                    category, []
                )
                for value in current_tool_refs:
                    if value not in category_refs:
                        category_refs.append(value)
            if (
                tool_name == "product_search"
                and _product_search_result_has_validated_promo_facts(
                    full or compact
                )
            ):
                promo_refs = claim_evidence_refs.setdefault(
                    "promo_facts",
                    [],
                )
                for value in current_tool_refs:
                    if value not in promo_refs:
                        promo_refs.append(value)
            if tool_name in {
                "answer_product_faq",
                "answer_policy_faq",
                "answer_service_faq",
                "answer_order_faq",
            }:
                faq_policy_type = str(
                    full.get("policy_type")
                    or compact.get("policy_type")
                    or ""
                )
                faq_applicability = str(
                    full.get("applicability")
                    or compact.get("applicability")
                    or ""
                )
                case_specific_scope_boundary_required = bool(
                    faq_policy_type == "delivery_process"
                    and faq_applicability == "policy_general"
                    and has_unvalidated_specific_location
                    and not service_claims_pre_authorized
                )
                required_faq_answer = {
                        "faq_id": str(
                            full.get("faq_id")
                            or compact.get("faq_id")
                            or ""
                        ),
                        "domain": str(
                            full.get("matched_domain")
                            or full.get("domain")
                            or compact.get("matched_domain")
                            or compact.get("domain")
                            or ""
                        ),
                        "policy_type": faq_policy_type,
                        "applicability": faq_applicability,
                        "evidence_ref": current_tool_refs[0],
                        "authored_answer": str(
                            full.get("answer")
                            or compact.get("answer")
                            or full.get("answer_basis")
                            or compact.get("answer_basis")
                            or ""
                        ),
                        "answer_required": True,
                        "scope_boundary": (
                            "Use only the facts in this FAQ result. A general "
                            "policy does not authorize a narrower current "
                            "service, schedule, product, or order fact."
                        ),
                    }
                required_answer_facts = deepcopy(
                    full.get("required_answer_facts")
                    or compact.get("required_answer_facts")
                    or []
                )
                if required_answer_facts:
                    required_faq_answer["required_answer_facts"] = (
                        required_answer_facts
                    )
                if case_specific_scope_boundary_required:
                    required_faq_answer.update(
                        {
                            "case_specific_scope_boundary_required": True,
                            "required_scope_boundary_answer": (
                                "State explicitly that the general delivery "
                                "policy does not yet confirm serviceability "
                                "for the customer's named location or exact "
                                "address. Do not answer yes to that narrower "
                                "case or invent a validation process, required "
                                "input, or promised confirmation path."
                            ),
                        }
                    )
                required_faq_fact_answers.append(required_faq_answer)
        if (
            tool_name in {"submit_order", "prepare_payment_request"}
            and str(full.get("status") or compact.get("status") or "")
            not in {
                "",
                "error",
                "blocked",
                "needs_explicit_order_confirmation",
            }
        ):
            authorized_side_effects.append(tool_name)
        if (
            tool_name == "request_human_handoff"
            and str(full.get("status") or compact.get("status") or "")
            in {"requested", "already_requested"}
        ):
            authorized_side_effects.append(tool_name)
            progression_context["human_handoff"] = {
                "status": str(
                    full.get("status") or compact.get("status") or ""
                ),
                "human_assignment_confirmed": False,
                "automated_sales_replies": "pause_requested",
                "response_boundary": (
                    "Acknowledge the recorded request and pause. Do not claim "
                    "that a human is connected, assigned, or has replied."
                ),
            }
    authorized_claim_categories = _authorized_turn_claim_categories(
        record.get("tool_results") or []
    )
    authorized_claim_categories = sorted(
        {
            *authorized_claim_categories,
            *claim_evidence_refs,
        }
    )
    service_claims_authorized = (
        "service_availability" in authorized_claim_categories
    )
    schedule_claims_authorized = (
        "schedule_availability" in authorized_claim_categories
    )
    service_claim_scopes = _authorized_service_area_claim_scopes(
        record.get("tool_results") or []
    )
    if service_claim_scopes:
        progression_context[
            "authorized_service_area_claims_by_evidence_ref"
        ] = service_claim_scopes
        latest_product_request_keys = {
            "tire_size",
            "rim_size",
            "required_brands",
            "preferred_brands",
            "specific_sku_model",
            "budget",
            "quantity",
            "promo_types",
            "tire_category_preference",
            "origins",
            "excluded_origins",
        }
        progression_context["current_service_answer_scope"] = {
            "answer_current_service_goal_only": True,
            "repeat_prior_product_result": bool(
                latest_signal_keys.intersection(
                    latest_product_request_keys
                )
            ),
        }
    progression_context.update(
        {
            "service_availability_claims_authorized": (
                service_claims_authorized
            ),
            "schedule_availability_claims_authorized": (
                schedule_claims_authorized
            ),
            "authorized_evidence_refs_by_claim_category": (
                claim_evidence_refs
            ),
            "authorized_brand_fact_fields_by_evidence_ref": (
                brand_fact_fields_by_ref
            ),
            "required_faq_fact_answers": required_faq_fact_answers,
        }
    )
    promo_response_contract = _promo_fact_audit_context(
        record.get("tool_results") or []
    )
    if promo_response_contract:
        progression_context["promo_response_contract"] = (
            promo_response_contract
        )
    if not service_claims_authorized:
        progression_context["service_evidence_instruction"] = (
            "The customer may have supplied an installation area, date, or "
            "time as a preference. That input is not service-availability "
            "evidence. Do not say or imply that installation, a partner, or "
            "a schedule is available until a current authorized service tool "
            "result is present."
        )
    required_claim_fact_answers: List[Dict[str, Any]] = []
    schedule_request_keys = {
        "preferred_schedule",
        "chosen_schedule_slot",
    }
    service_request_keys = {
        "location",
        "city",
        "province",
        "service_type",
        *schedule_request_keys,
    }
    required_surface_layers = {
        str(surface.get("decision_layer") or "").strip()
        for surface in available_surfaces
        if isinstance(surface, dict) and surface.get("required") is True
    }
    required_surface_types = {
        str(surface.get("surface_type") or "").strip()
        for surface in available_surfaces
        if isinstance(surface, dict) and surface.get("required") is True
    }
    if (
        schedule_claims_authorized
        and latest_signal_keys.intersection(schedule_request_keys)
        and "schedule" not in required_surface_layers
    ):
        schedule_answer = {
            "category": "schedule_availability",
            "objective": "schedule_availability",
            "evidence_refs": list(
                claim_evidence_refs.get("schedule_availability") or []
            ),
        }
        if progression_context.get("slots_authorized") is False:
            schedule_answer["expected_disposition"] = "pending_validation"
        required_claim_fact_answers.append(schedule_answer)
    elif (
        service_claims_authorized
        and latest_signal_keys.intersection(service_request_keys)
        and not required_surface_layers.intersection({"location", "service"})
        and "service_no_match_context" not in required_surface_types
    ):
        required_claim_fact_answers.append(
            {
                "category": "service_availability",
                "objective": "service_availability",
                "evidence_refs": list(
                    claim_evidence_refs.get("service_availability") or []
                ),
            }
        )
    request_obligations = _request_obligations_for_turn(
        available_surfaces=available_surfaces,
        required_faq_fact_answers=required_faq_fact_answers,
        required_claim_fact_answers=required_claim_fact_answers,
    )
    payload = {
        "accepted_state_changes": accepted_changes,
        "already_satisfied_fields": already_satisfied,
        "known_customer_context": _known_customer_context_for_turn(
            background_signals
        ),
        "authorized_evidence_refs": evidence_refs,
        "available_surfaces": available_surfaces,
        "request_obligations": request_obligations,
        "authorized_claim_categories": authorized_claim_categories,
        "authorized_side_effects": authorized_side_effects,
        "progression_context": progression_context,
    }
    model = TurnAuthorizationEnvelopeV1(**payload)
    return (
        model.model_dump(exclude_none=True)
        if hasattr(model, "model_dump")
        else model.dict(exclude_none=True)
    )


def _authorized_brand_profile_fact_fields(
    profile: Mapping[str, Any],
) -> List[str]:
    """Return exact published brand-profile fields allowed in prose."""

    fields: List[str] = []
    for key in (
        "brand",
        "about_brand",
        "origin_country",
        "market_segment",
    ):
        if profile.get(key) not in (None, "", [], {}):
            fields.append(key)
    manufacturer = (
        profile.get("manufacturer_warranty")
        if isinstance(profile.get("manufacturer_warranty"), Mapping)
        else {}
    )
    authorized_manufacturer = {
        str(value).strip()
        for value in manufacturer.get("authorized_fields") or []
        if str(value).strip()
    }
    for key in sorted(authorized_manufacturer):
        if manufacturer.get(key) not in (None, "", [], {}):
            fields.append(f"manufacturer_warranty.{key}")
    guarantee = (
        profile.get("gulong_guarantee")
        if isinstance(profile.get("gulong_guarantee"), Mapping)
        else {}
    )
    for key in (
        "duration_years",
        "period_text",
        "coverage",
        "conditions",
        "scope",
    ):
        if guarantee.get(key) not in (None, "", [], {}):
            fields.append(f"gulong_guarantee.{key}")
    return fields


def _product_search_result_has_validated_promo_facts(
    result: Mapping[str, Any],
) -> bool:
    """Return whether a trusted product result carries current promo facts."""

    promo_evidence = (
        result.get("promo_evidence")
        if isinstance(result.get("promo_evidence"), Mapping)
        else {}
    )
    if promo_evidence.get("verified_brands"):
        return True
    cards = [
        card
        for key in (
            "product_cards",
            "presented_products",
            "best_products",
        )
        for card in result.get(key) or []
        if isinstance(card, Mapping)
    ]
    return any(
        card.get("promo_type")
        or card.get("promo_eligibility")
        or (
            isinstance(card.get("pricing_facts"), Mapping)
            and card["pricing_facts"].get("included_promos")
        )
        for card in cards
    )


def _authorized_turn_claim_categories(
    tool_results: Sequence[Dict[str, Any]],
) -> List[str]:
    """Return positive factual-claim authority from current-turn evidence.

    Customer text and readiness state can describe requested service context,
    but they cannot authorize an availability claim. Keeping this list
    positive makes the composer distinguish a proposed future check from a
    fact already established by a trusted provider.
    """

    categories = {
        "business_identity_facts",
        "general_tire_advisory",
        "renderer_owned_facts",
        "validated_state",
    }
    usable_results = [
        item
        for item in tool_results or []
        if isinstance(item, dict)
        and _tool_result_authorizes_customer_facts(item)
    ]
    for item in usable_results:
        categories.update(
            _claim_categories_for_tool_name(
                str(item.get("name") or "").strip()
            )
        )
    return sorted(categories)


def _validated_response_seed_claim_evidence(
    record: Mapping[str, Any],
) -> Dict[str, List[str]]:
    """Expose trusted tracked-action evidence to the composer contract."""

    output: Dict[str, List[str]] = {}
    for seed in record.get("response_seeds") or []:
        if (
            not isinstance(seed, dict)
            or str(seed.get("type") or "") != "promo_action"
        ):
            continue
        evidence = (
            seed.get("evidence")
            if isinstance(seed.get("evidence"), dict)
            else {}
        )
        if str(evidence.get("status") or "") != "valid":
            continue
        action = str(evidence.get("action") or "").strip().lower()
        category = (
            "promo_facts"
            if action == "promo_details"
            else "brand_facts"
            if action == "about_brand"
            else ""
        )
        if not category:
            continue
        refs: List[str] = []
        catalog_version = str(
            evidence.get("catalog_version_id") or ""
        ).strip()
        promo = (
            evidence.get("promo")
            if isinstance(evidence.get("promo"), dict)
            else {}
        )
        brand_profile = (
            evidence.get("brand_profile")
            if isinstance(evidence.get("brand_profile"), dict)
            else {}
        )
        for value in (
            promo.get("promo_ref"),
            catalog_version,
            brand_profile.get("profile_ref"),
            *(promo.get("evidence_refs") or []),
            *(brand_profile.get("evidence_refs") or []),
        ):
            text = str(value or "").strip()
            if text and text not in refs:
                refs.append(text)
        for mechanic in promo.get("relevant_mechanics") or []:
            if not isinstance(mechanic, dict):
                continue
            for value in mechanic.get("evidence_refs") or []:
                text = str(value or "").strip()
                if text and text not in refs:
                    refs.append(text)
        brand = str(
            brand_profile.get("brand")
            or evidence.get("selected_brand")
            or ""
        ).strip()
        if (
            category == "brand_facts"
            and catalog_version
            and brand
            and not brand_profile.get("profile_ref")
        ):
            profile_ref = (
                f"brand_profile:{catalog_version}:{brand.casefold()}"
            )
            if profile_ref not in refs:
                refs.append(profile_ref)
        if refs:
            output[category] = refs
    return output


def _claim_categories_for_tool_name(tool_name: str) -> set[str]:
    """Map a trusted provider result to the factual scopes it can support."""

    categories: set[str] = set()
    if tool_name in {
        "product_search",
        "get_product_details",
        "resolve_product_reference",
        "discover_brand_buckets",
    }:
        categories.add("product_facts")
    if tool_name in {
        "search_promo_catalog",
        "present_promo_gallery",
    }:
        categories.add("promo_facts")
    if tool_name == "get_brand_knowledge":
        categories.add("brand_facts")
    if tool_name in {
        "answer_product_faq",
        "answer_policy_faq",
        "answer_service_faq",
        "answer_order_faq",
    }:
        categories.add("faq_facts")
    if tool_name == "answer_order_faq":
        categories.add("payment_facts")
    if tool_name == "get_business_contact":
        categories.add("business_contact_facts")
    if tool_name == "present_serviceable_location_choices":
        categories.add("business_identity_facts")
    if tool_name == "request_human_handoff":
        categories.add("validated_state")
    if tool_name in {
        "find_installation_partners",
        "find_installation_slots",
        "validate_installation_slot",
        "get_branch_addons",
    }:
        categories.add("service_availability")
    if tool_name in {
        "find_installation_slots",
        "validate_installation_slot",
    }:
        categories.add("schedule_availability")
    if tool_name in {
        "build_order_summary",
        "submit_order",
        "prepare_payment_request",
    }:
        categories.add("order_facts")
    if tool_name == "prepare_payment_request":
        categories.add("payment_facts")
    return categories


def _authorized_service_area_claim_scopes(
    tool_results: Sequence[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Return exact query-area scopes for positive service claims.

    One provider call can establish options around only its normalized query
    area. Nearby city labels in returned rows remain renderer-owned details and
    customer-mentioned alternatives remain unverified until separately queried.
    """

    output: Dict[str, List[Dict[str, Any]]] = {}
    service_tools = {
        "find_installation_partners",
        "find_installation_slots",
        "validate_installation_slot",
    }
    for item in tool_results or []:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("name") or "").strip()
        if (
            tool_name not in service_tools
            or not _tool_result_authorizes_customer_facts(item)
        ):
            continue
        full = (
            item.get("full_result")
            if isinstance(item.get("full_result"), dict)
            else {}
        )
        compact = (
            item.get("result")
            if isinstance(item.get("result"), dict)
            else {}
        )
        source = full or compact
        query_basis = (
            source.get("query_basis")
            if isinstance(source.get("query_basis"), dict)
            else {}
        )
        coverage = (
            source.get("coverage_assessment")
            if isinstance(source.get("coverage_assessment"), dict)
            else {}
        )
        queried_location = str(
            query_basis.get("customer_location_label")
            or coverage.get("customer_location_label")
            or query_basis.get("location")
            or ""
        ).strip()
        if not queried_location:
            continue
        status = str(source.get("status") or "").strip().lower()
        if status == "below_order_threshold":
            outcome = "delivery_recommended"
        elif tool_name == "find_installation_slots":
            availability = (
                source.get("availability")
                if isinstance(source.get("availability"), dict)
                else {}
            )
            if not (
                source.get("slot_groups")
                or availability.get("earliest_available_slot")
            ):
                continue
            outcome = "schedule_options_found"
        else:
            partners = (
                source.get("installation_partners")
                or source.get("service_locations")
                or source.get("installation_partner_headers")
                or source.get("service_location_headers")
                or []
            )
            if status != "ok" or not partners:
                continue
            outcome = "partner_options_found"
        evidence_refs = []
        for key in ("observation_ref", "presentation_ref", "evidence_ref"):
            ref = str(full.get(key) or compact.get(key) or "").strip()
            if ref and ref not in evidence_refs:
                evidence_refs.append(ref)
        if not evidence_refs:
            continue
        primary_ref = evidence_refs[0]
        scope = {
            "scope_ref": f"service_query_area:{primary_ref}",
            "queried_location": queried_location,
            "outcome": outcome,
            "scope_boundary": (
                "Only this queried area is authorized. Other mentioned "
                "locations require separate provider lookups."
            ),
        }
        for evidence_ref in evidence_refs:
            output.setdefault(evidence_ref, []).append(deepcopy(scope))
    return output


def _tool_result_authorizes_customer_facts(
    tool_result: Mapping[str, Any],
) -> bool:
    """Exclude rejected or failed query plans from factual authority."""

    full = (
        tool_result.get("full_result")
        if isinstance(tool_result.get("full_result"), dict)
        else {}
    )
    compact = (
        tool_result.get("result")
        if isinstance(tool_result.get("result"), dict)
        else {}
    )
    error_type = str(
        full.get("error_type") or compact.get("error_type") or ""
    ).strip()
    if error_type:
        return False
    status = str(
        full.get("status") or compact.get("status") or ""
    ).strip().lower()
    return status not in {
        "error",
        "blocked",
        "invalid",
        "rejected",
        "suppressed",
        "superseded",
        "not_requested",
        "not_applicable",
        "no_match",
    }


def _planned_tool_surface_metadata(
    surface: Dict[str, Any],
    *,
    required: bool,
    response_role: str = "direct_answer",
) -> Dict[str, Any]:
    surface_ref = str(surface.get("surface_ref") or "").strip()
    if not surface_ref:
        return {}
    labels: List[str] = []
    for card in surface.get("cards") or surface.get("card_headers") or []:
        if not isinstance(card, dict):
            continue
        label = str(
            card.get("title")
            or card.get("label")
            or card.get("brand")
            or card.get("sku_model")
            or ""
        ).strip()
        if label:
            labels.append(label)
    metadata = {
        "surface_ref": surface_ref,
        "surface_type": str(
            surface.get("type") or surface.get("domain") or ""
        ),
        "decision_layer": _surface_decision_layer(surface),
        "visible_labels": labels[:8],
        "visible_count": len(labels),
        "source": str(surface.get("source") or surface.get("tool") or ""),
        "source_version": str(surface.get("source_version") or ""),
        "required": required,
        "response_role": response_role,
    }
    if surface.get("supporting_context") is True:
        metadata["supporting_context"] = True
    if metadata["surface_type"] == "order_summary":
        metadata["missing_fields"] = [
            str(field).strip()
            for field in surface.get("missing_fields") or []
            if str(field or "").strip()
        ][:8]
    return metadata


def _planned_choice_surface_metadata(
    surface: Dict[str, Any],
    *,
    decision_layer: str,
    required: bool,
    response_role: str = "direct_answer",
) -> Dict[str, Any]:
    surface_ref = str(
        surface.get("presentation_ref") or surface.get("surface_ref") or ""
    ).strip()
    choices = [
        choice
        for choice in surface.get("choices") or []
        if isinstance(choice, dict)
    ]
    return {
        "surface_ref": surface_ref,
        "surface_type": str(surface.get("surface_type") or ""),
        "decision_layer": decision_layer,
        "visible_labels": [
            str(choice.get("label") or "")
            for choice in choices[:8]
            if str(choice.get("label") or "").strip()
        ],
        "visible_count": len(choices),
        "selection_state": "awaiting_customer_choice",
        "source": str(surface.get("source") or ""),
        "source_version": str(surface.get("source_version") or ""),
        "required": required,
        "response_role": response_role,
    }


def _request_obligations_for_turn(
    *,
    available_surfaces: Sequence[Dict[str, Any]],
    required_faq_fact_answers: Sequence[Dict[str, Any]],
    required_claim_fact_answers: Sequence[Dict[str, Any]] = (),
) -> List[Dict[str, Any]]:
    """Compile grounded visible-answer obligations without interpreting prose.

    Tool and choice surfaces marked as direct answers must be represented in the
    final unit plan. Supporting replacements, such as the automatic TPP warranty
    gallery, remain required renderer blocks but do not create a second customer
    request. FAQ obligations reuse the existing provider-backed answer contract.
    """

    obligations: List[Dict[str, Any]] = []
    for surface in available_surfaces or []:
        if not isinstance(surface, dict):
            continue
        surface_ref = str(surface.get("surface_ref") or "").strip()
        response_role = str(
            surface.get("response_role") or "direct_answer"
        ).strip()
        text_only_direct_answer = bool(
            str(surface.get("surface_type") or "").strip()
            == "service_no_match_context"
        )
        if not surface_ref or response_role != "direct_answer" or (
            not bool(surface.get("required")) and not text_only_direct_answer
        ):
            continue
        obligations.append(
            {
                "obligation_id": (
                    f"text:{surface_ref}"
                    if text_only_direct_answer
                    else f"surface:{surface_ref}"
                ),
                "objective": str(
                    surface.get("decision_layer")
                    or surface.get("surface_type")
                    or "grounded_answer"
                ),
                "required_response_modes": [
                    "text" if text_only_direct_answer else "surface"
                ],
                "authorized_surface_refs": (
                    [] if text_only_direct_answer else [surface_ref]
                ),
            }
        )
    for index, answer in enumerate(required_faq_fact_answers or []):
        if not isinstance(answer, dict) or not answer.get("answer_required"):
            continue
        evidence_ref = str(answer.get("evidence_ref") or "").strip()
        identity = evidence_ref or str(answer.get("faq_id") or "").strip()
        obligations.append(
            {
                "obligation_id": _canonical_faq_obligation_id(
                    identity or str(index + 1)
                ),
                "objective": str(
                    answer.get("domain")
                    or answer.get("policy_type")
                    or "faq_answer"
                ),
                "required_response_modes": ["text"],
                "authorized_surface_refs": [],
            }
        )
        if answer.get("case_specific_scope_boundary_required"):
            obligations.append(
                {
                    "obligation_id": (
                        "scope_boundary:"
                        + _canonical_faq_obligation_id(
                            identity or str(index + 1)
                        )
                    ),
                    "objective": "exact_delivery_serviceability",
                    "required_response_modes": ["text"],
                    "authorized_surface_refs": [],
                    "expected_disposition": "pending_validation",
                }
            )
    for index, answer in enumerate(required_claim_fact_answers or []):
        if not isinstance(answer, dict):
            continue
        evidence_refs = [
            str(value or "").strip()
            for value in answer.get("evidence_refs") or []
            if str(value or "").strip()
        ]
        category = str(answer.get("category") or "grounded_fact").strip()
        identity = evidence_refs[0] if evidence_refs else str(index + 1)
        obligation = {
            "obligation_id": f"claim:{category}:{identity}",
            "objective": str(answer.get("objective") or category).strip(),
            "required_response_modes": ["text"],
            "authorized_surface_refs": [],
        }
        if answer.get("expected_disposition"):
            obligation["expected_disposition"] = str(
                answer["expected_disposition"]
            ).strip()
        obligations.append(obligation)
    return _deduplicate_request_obligations(obligations)


def _canonical_faq_obligation_id(identity: Any) -> str:
    """Return one stable FAQ obligation ID without double prefixes."""

    value = str(identity or "").strip()
    if value.casefold().startswith("faq:"):
        return value
    return f"faq:{value}"


def _deduplicate_request_obligations(
    obligations: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge repeated provider identities into one composer obligation."""

    output: List[Dict[str, Any]] = []
    by_id: Dict[str, Dict[str, Any]] = {}
    for obligation in obligations or []:
        if not isinstance(obligation, Mapping):
            continue
        obligation_id = str(obligation.get("obligation_id") or "").strip()
        if not obligation_id:
            continue
        current = by_id.get(obligation_id)
        if current is None:
            current = deepcopy(dict(obligation))
            by_id[obligation_id] = current
            output.append(current)
            continue
        for key in ("required_response_modes", "authorized_surface_refs"):
            merged = [
                str(value or "").strip()
                for value in [
                    *(current.get(key) or []),
                    *(obligation.get(key) or []),
                ]
                if str(value or "").strip()
            ]
            current[key] = list(dict.fromkeys(merged))
    return output


def _surface_decision_layer(surface: Dict[str, Any]) -> str:
    surface_type = str(
        surface.get("type") or surface.get("domain") or ""
    ).strip()
    if (
        surface_type == "promo_catalog"
        and surface.get("supporting_context") is True
    ):
        return "product"
    if surface_type in {
        "product_cards",
        "selected_product_cards",
        "product",
    }:
        return "product"
    if surface_type in {"brand_menu_cards", "price_category"}:
        return "price_category"
    if surface_type in {"installation_slot_cards", "schedule"}:
        return "schedule"
    if surface_type in {
        "installation_partner_cards",
        "installation_partner_summary",
        "service",
    }:
        return "location"
    if surface_type in {"payment_request", "payment"}:
        return "payment"
    return surface_type


def _final_composer_presentation_surfaces(
    tool_results: Sequence[Dict[str, Any]],
    *,
    customer_turn_plan: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    surfaces: List[Dict[str, Any]] = []
    collected_surfaces = _collect_runtime_presentation_surfaces(tool_results)
    has_supporting_warranty_replacement = any(
        surface_type == "promo"
        and bool(surface.get("supporting_context"))
        for surface_type, surface in collected_surfaces
        if isinstance(surface, dict)
    )
    for surface_type, surface in collected_surfaces:
        tool = str(surface.get("tool") or "")
        full_result = surface.get("full_result") if isinstance(surface.get("full_result"), dict) else {}
        cards = [card for card in surface.get("cards") or [] if isinstance(card, dict)]
        surface_ref = str(surface.get("surface_ref") or "").strip()
        if not surface_ref:
            continue
        payload: Dict[str, Any] = {
            "surface_ref": surface_ref,
            "domain": surface_type,
            "tool": tool,
            "render_policy": "runtime_inserts_exact_cards_or_body",
        }
        if surface_type == "promo":
            supporting_replacement = bool(surface.get("supporting_context"))
            payload.update(
                _compact_unit(
                    {
                        "type": "promo_catalog",
                        "supporting_context": supporting_replacement,
                        "promo_refs": (
                            []
                            if supporting_replacement
                            else list(full_result.get("promo_refs") or [])
                        ),
                        "card_refs": (
                            []
                            if supporting_replacement
                            else list(full_result.get("card_refs") or [])
                        ),
                        "card_headers": (
                            []
                            if supporting_replacement
                            else [
                                {
                                    "title": str(card.get("title") or ""),
                                    "subtitle": str(card.get("subtitle") or ""),
                                }
                                for card in cards[:8]
                            ]
                        ),
                    "composer_guidance": (
                        (
                            "Render this reviewed promo gallery as a replacement for separate warranty prose. "
                            "Do not write a warranty caption, explanation, or promo-details CTA. If the customer is actively continuing "
                            "and a next question is useful, keep it on the active product choice. "
                            if surface.get("supporting_context") is True
                            else "Render this reviewed promo gallery. Write only a short natural lead-in or next-step question; "
                        )
                        + "Do not rewrite card titles, mechanics, images, buttons, URLs, or field actions."
                    ),
                    }
                )
            )
        elif surface_type == "fitment":
            payload.update(
                {
                    "type": "fitment_candidate_sizes",
                    "vehicle_query": full_result.get("vehicle_query"),
                    "raw_vehicle_query": full_result.get("raw_vehicle_query"),
                    "source": full_result.get("source"),
                    "candidate_sizes": [header.get("size") for header in _fitment_candidate_headers(full_result.get("candidate_sizes") or [])],
                    "requires_customer_confirmation": bool(full_result.get("requires_customer_confirmation")),
                    "composer_guidance": (
                        "Render this surface when candidate sizes exist. These are possible sizes only; "
                        "ask the customer to confirm the exact sidewall size before product cards."
                    ),
                }
            )
        elif surface_type == "product" and tool == "product_search":
            payload.update(
                {
                    "type": "product_cards",
                    "cards": _product_card_headers(
                        cards,
                        include_warranty_context=(
                            not has_supporting_warranty_replacement
                        ),
                    ),
                    "preferred_brand_presentation_status": full_result.get("preferred_brand_presentation_status"),
                }
            )
        elif surface_type == "product" and tool == "discover_brand_buckets":
            payload.update(
                {
                    "type": "brand_menu_cards",
                    "cards": _bucket_card_headers(cards),
                    "legend_text": full_result.get("legend_text"),
                    "choice_summary": _brand_menu_choice_summary(full_result, cards),
                    "composer_guidance": (
                        "Render this surface for exact brand/category menu cards. Use the "
                        "choice_summary only for a natural lead-in or CTA; do not rewrite "
                        "category rows, brand lists, legend text, counts, prices, or promo markers."
                    ),
                }
            )
        elif surface_type == "product" and tool == "get_product_details":
            payload.update({"type": "selected_product_cards", "cards": _selected_product_card_headers(cards)})
        elif surface_type == "service" and tool == "find_installation_partners_no_match":
            payload.update(
                {
                    "type": "service_no_match_context",
                    "renderer_owns_next_input": False,
                    "coverage_assessment": _model_visible_coverage_assessment(full_result.get("coverage_assessment")),
                    "customer_explanation_hints": full_result.get("customer_explanation_hints") or [],
                    "composer_guidance": (
                        "This context has no customer-visible renderer body. Compose the grounded "
                        "outcome and one natural next step in model-owned text."
                    ),
                }
            )
        elif surface_type == "service":
            surface_kind = (
                "installation_slot_cards"
                if tool == "find_installation_slots"
                and bool(full_result.get("slot_groups"))
                or _cards_include_slot_summaries(cards)
                else "installation_partner_cards"
            )
            if tool == "find_installation_partners_summary":
                surface_kind = "installation_partner_summary"
            payload.update(
                {
                    "type": surface_kind,
                    "cards": _installation_partner_card_headers(cards),
                    "coverage_assessment": _model_visible_coverage_assessment(full_result.get("coverage_assessment")),
                    "schedule_semantics": (
                        _installation_slot_schedule_semantics(full_result)
                        if surface_kind == "installation_slot_cards"
                        else _partner_lookup_schedule_semantics(full_result)
                    ),
                    "service_policy_notes_will_be_inserted": bool(full_result.get("service_policy_notes")),
                    "composer_guidance": (
                        "Render this provider-owned area summary exactly once. Do not restate, "
                        "expand, or aggregate installation availability in model-owned text. "
                        "Text may answer a separate customer question and ask one natural next "
                        "question, but other mentioned locations remain unchecked."
                        if surface_kind == "installation_partner_summary"
                        else ""
                    ),
                }
            )
        elif surface_type == "order":
            payload.update(
                {
                    "type": "order_summary",
                    "summary_status": full_result.get("status"),
                    "can_submit_order": bool(full_result.get("can_submit_order")),
                    "rendered_as": "order_details_so_far"
                    if full_result.get("status") == "incomplete"
                    else "order_summary",
                    "summary_preview": full_result.get("summary_preview") or {},
                    "missing_fields": full_result.get("missing_fields") or [],
                    "assumptions": full_result.get("assumptions") or [],
                }
            )
        elif surface_type == "payment":
            payload.update(
                {
                    "type": "payment_request",
                    "order_id": full_result.get("order_id"),
                    "payment_stage": full_result.get("payment_stage"),
                    "expected_amount_text": full_result.get("expected_amount_text"),
                    "primary_method": full_result.get("primary_method"),
                    "payment_instruction_type": full_result.get("payment_instruction_type"),
                    "has_qr_image": bool((full_result.get("qr_image") or {}).get("url"))
                    if isinstance(full_result.get("qr_image"), dict)
                    else False,
                    "has_payment_link": bool((full_result.get("payment_link") or {}).get("url"))
                    if isinstance(full_result.get("payment_link"), dict)
                    else False,
                    "has_manual_details": bool(full_result.get("manual_details")),
                    "can_accept_payment_proof": bool(full_result.get("can_accept_payment_proof")),
                }
            )
        manifest = _customer_visible_surface_manifest(
            surface_type=surface_type,
            tool=tool,
            full_result=full_result,
            cards=cards,
        )
        if manifest:
            payload["customer_visible_surface_manifest"] = manifest
        surfaces.append(_compact_unit(payload))
    known_refs = {
        str(surface.get("surface_ref") or "").strip()
        for surface in surfaces
        if str(surface.get("surface_ref") or "").strip()
    }
    for planned in (customer_turn_plan or {}).get("available_surfaces") or []:
        if not isinstance(planned, dict):
            continue
        surface_ref = str(planned.get("surface_ref") or "").strip()
        if not surface_ref or surface_ref in known_refs:
            continue
        surfaces.append(
                _compact_unit(
                    {
                        "surface_ref": surface_ref,
                        "domain": str(
                            planned.get("decision_layer")
                            or planned.get("surface_type")
                            or ""
                        ),
                        "type": str(planned.get("surface_type") or ""),
                        "visible_labels": list(
                            planned.get("visible_labels") or []
                        )[:8],
                        "visible_count": planned.get("visible_count"),
                        "selection_state": planned.get("selection_state"),
                        "source": planned.get("source"),
                        "source_version": planned.get("source_version"),
                        "render_policy": (
                            "runtime_inserts_exact_cards_or_body"
                        ),
                        "composer_guidance": (
                            "Place this renderer-owned surface exactly once. "
                            "Use the visible labels only to write a concise "
                            "lead-in or one next question."
                        ),
                    }
                )
        )
        known_refs.add(surface_ref)
    return surfaces


def _customer_visible_surface_manifest(
    *,
    surface_type: str,
    tool: str,
    full_result: Dict[str, Any],
    cards: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Describe renderer-owned message roles without copying rendered bodies.

    This is advisory composition context only. Exact commercial facts remain in
    provider-backed surface fields, and channel/session conditions may suppress
    roles explicitly labeled as optional.
    """

    roles: List[str] = []
    if surface_type == "promo":
        roles.append("reviewed_promo_gallery_cards")
    elif surface_type == "fitment":
        roles.append("candidate_fitment_size_surface")
    elif surface_type == "product" and tool == "discover_brand_buckets":
        roles.append("guided_brand_or_price_category_cards")
    elif surface_type == "product" and tool in {"product_search", "get_product_details"}:
        roles.append("exact_product_price_or_detail_text")
        if len(cards) > 1:
            roles.append("product_selection_cards_may_render_for_image_backed_options")
        if any(
            card.get("warranty")
            or card.get("tire_protection_plan")
            or card.get("inclusions")
            for card in cards
            if isinstance(card, dict)
        ):
            roles.append("one_time_warranty_and_inclusions_text_may_render")
    elif surface_type == "service":
        roles.append(
            "installation_schedule_cards"
            if _cards_include_slot_summaries(cards)
            else "installation_partner_or_coverage_surface"
        )
        if full_result.get("service_policy_notes"):
            roles.append("service_policy_notes_may_render")
        if tool == "find_installation_partners_no_match":
            roles.append("model_owned_service_outcome_and_next_step")
    elif surface_type == "order":
        roles.append("order_summary_or_details_so_far_body")
    elif surface_type == "payment":
        roles.append("payment_instruction_body")
        if isinstance(full_result.get("qr_image"), dict) and (full_result.get("qr_image") or {}).get("url"):
            roles.append("payment_qr_image")
        if isinstance(full_result.get("payment_link"), dict) and (full_result.get("payment_link") or {}).get("url"):
            roles.append("payment_link")
    if not roles:
        return {}
    return {
        "renderer_owned_message_roles": roles,
        "composition_instruction": (
            "Treat this surface as one exact block at its render_surface position. "
            "Write only customer-specific context the block does not already carry, "
            "plus at most one connected next step when authorized."
        ),
    }


def _location_tool_plan_rejection(
    *,
    name: str,
    execution_args: Optional[Dict[str, Any]] = None,
    validated_choice_context: Dict[str, Any],
    background_signals: Sequence[Dict[str, Any]],
    order_readiness: Optional[Dict[str, Any]] = None,
    current_user_message: str = "",
    has_usable_product_context: Optional[bool] = None,
) -> Dict[str, Any]:
    """Reject location plans that conflict with structured turn state.

    Customer meaning remains model-owned. This function only prevents a
    proposed plan from discarding a validated choice, normalized location, or
    delivery state already present in the turn.
    """

    if name not in {
        "find_installation_partners",
        "find_service_locations",
        "find_installation_slots",
        "validate_installation_slot",
        "present_serviceable_location_choices",
    }:
        return {}
    if (
        name == "present_serviceable_location_choices"
        and _current_turn_location_unavailable(background_signals)
    ):
        return {
            "reason": (
                "The customer cannot provide an installation or delivery location "
                "yet. Do not force a province or city choice; continue with the "
                "reviewed contact-follow-up path."
            ),
            "required_decision_layer": "contact_followup",
            "source": "semantic_current_turn_location_response_status",
        }
    action = (
        validated_choice_context
        if isinstance(validated_choice_context, dict)
        else {}
    )
    if (
        action.get("validation_status") == "valid"
        and action.get("choice_type") == "serviceable_city"
        and name != "present_serviceable_location_choices"
    ):
        # The current delivered city choice is more authoritative than stale
        # province-only or ambiguous context carried from an earlier turn.
        return {}
    ambiguous_location = _ambiguous_location_signal_context(background_signals)
    if ambiguous_location:
        return {
            "reason": (
                "The customer location matches multiple city or municipality "
                "records. Ask which province/location they mean before partner "
                "or schedule discovery."
            ),
            "location_precision": "ambiguous_city",
            "clarification_options": ambiguous_location.get(
                "clarification_options"
            ) or [],
            "source": (
                "normalized_latest_customer_location"
                if ambiguous_location.get("signal_source")
                == "latest_user_message"
                else "validated_location_state"
            ),
        }
    if (
        name == "find_installation_slots"
        and has_usable_product_context is False
        and not _background_signals_have_schedule_constraint(
            background_signals
        )
    ):
        return {
            "reason": (
                "Slot discovery requires a delivered or validated product, "
                "or a typed customer schedule constraint. Use partner "
                "coverage for the normalized area first."
            ),
            "required_decision_layer": "service_partner_coverage",
            "source": "typed_service_slot_prerequisites",
        }
    if (
        name == "find_installation_slots"
        and str(
            (execution_args or {}).get("discovery_mode") or ""
        ).strip()
        == "recommend_serviceable_cities"
    ):
        # This plan is read-only and cannot select a city or schedule. The
        # model owns the conversational interpretation; runtime validates the
        # resulting preview state instead of reinterpreting customer prose.
        return {}
    if name == "present_serviceable_location_choices":
        collected = (
            (order_readiness or {}).get("collected")
            if isinstance((order_readiness or {}).get("collected"), dict)
            else {}
        )
        if (
            str(collected.get("Fulfillment") or "").strip().casefold()
            == "delivery"
            or str(collected.get("Delivery address") or "").strip()
        ):
            return {
                "reason": (
                    "A delivery path is already active, so installation "
                    "province choices are not a compatible next step."
                ),
                "required_decision_layer": "delivery_address",
                "source": "validated_order_readiness",
            }
        active_delivery_signal = _active_delivery_signal_context(background_signals)
        if active_delivery_signal:
            return {
                "reason": (
                    "A delivery path is already active in durable customer state, "
                    "so installation province choices are not compatible."
                ),
                "required_decision_layer": "delivery_address",
                "source": active_delivery_signal["source"],
                "signal_key": active_delivery_signal["key"],
            }
        if (
            action.get("validation_status") == "valid"
            and action.get("choice_type")
            in {"serviceable_province", "serviceable_city"}
        ):
            return {
                "reason": (
                    "A tracked location choice is already validated. Continue "
                    "from that choice instead of restarting province selection."
                ),
                "required_decision_layer": (
                    "city"
                    if action.get("choice_type") == "serviceable_province"
                    else "service_lookup"
                ),
                "source": "validated_choice_metadata",
            }
    if (
        action.get("validation_status") == "valid"
        and action.get("choice_type") == "serviceable_province"
    ):
        return {
            "reason": (
                "The serviceable province remains valid context, but an exact "
                "partner or schedule still needs a city. Use serviceable-city "
                "recommendation mode instead of discarding the province."
            ),
            "location_precision": "province_only",
            "source": "validated_choice_metadata",
        }
    for signal in reversed(list(background_signals or [])):
        if not isinstance(signal, dict):
            continue
        if str(signal.get("key") or "").strip() != "location":
            continue
        signal_source = str(signal.get("source") or "").strip()
        if signal_source not in {
            "latest_user_message",
            "validated_choice_action",
            "signal_ledger",
        }:
            continue
        resolution = (
            signal.get("resolution")
            if isinstance(signal.get("resolution"), dict)
            else {}
        )
        metadata = (
            signal.get("metadata")
            if isinstance(signal.get("metadata"), dict)
            else {}
        )
        normalization = (
            metadata.get("normalization")
            if isinstance(metadata.get("normalization"), dict)
            else {}
        )
        normalized_resolution = (
            normalization.get("location_resolution")
            if isinstance(
                normalization.get("location_resolution"),
                dict,
            )
            else {}
        )
        province = str(
            resolution.get("province_hint")
            or normalized_resolution.get("province_hint")
            or ""
        ).strip()
        city = str(
            resolution.get("city_hint")
            or normalized_resolution.get("city_hint")
            or ""
        ).strip()
        precision = str(
            resolution.get("location_precision")
            or normalized_resolution.get("location_precision")
            or ""
        ).strip()
        if name == "present_serviceable_location_choices":
            if city or precision in {
                "city",
                "municipality",
                "barangay",
                "street_or_address",
                "address",
            }:
                return {
                    "reason": (
                        "A concrete customer area is already normalized. Use "
                        "that area for service lookup instead of asking for a "
                        "province again."
                    ),
                    "required_decision_layer": "service_lookup",
                    "location_precision": precision or "city",
                    "source": (
                        "normalized_latest_customer_location"
                        if signal_source == "latest_user_message"
                        else "validated_location_state"
                    ),
                }
            if province and not city:
                return {
                    "reason": (
                        "A province is already normalized. Continue to a "
                        "serviceable-city decision instead of restarting "
                        "province selection."
                    ),
                    "required_decision_layer": "city",
                    "location_precision": precision or "province_only",
                    "source": (
                        "normalized_latest_customer_location"
                        if signal_source == "latest_user_message"
                        else "validated_location_state"
                    ),
                }
        if province and not city and precision in {
            "",
            "province",
            "province_only",
            "province_or_region",
        }:
            return {
                "reason": (
                    "The latest location resolves only to a province. Ask for "
                    "or recommend a serviceable city before partner or "
                    "schedule discovery."
                ),
                "location_precision": "province_only",
                "source": (
                    "normalized_latest_customer_location"
                    if signal_source == "latest_user_message"
                    else "validated_location_state"
                ),
            }
        break
    return {}


def _location_plan_rejection_result_status(
    rejection: Mapping[str, Any],
) -> str:
    """Classify an expected progression redirect separately from tool errors."""

    if (
        str(rejection.get("required_decision_layer") or "").strip()
        == "contact_followup"
        and str(rejection.get("source") or "").strip()
        == "semantic_current_turn_location_response_status"
    ):
        return "not_applicable"
    if (
        str(rejection.get("required_decision_layer") or "").strip()
        == "service_partner_coverage"
        and str(rejection.get("source") or "").strip()
        == "typed_service_slot_prerequisites"
    ):
        return "not_applicable"
    return "error"


def _background_signals_have_schedule_constraint(
    background_signals: Sequence[Dict[str, Any]],
) -> bool:
    """Return whether typed state carries a customer schedule constraint."""

    accepted_sources = {
        "latest_user_message",
        "customer_history",
        "validated_choice_action",
        "signal_ledger",
    }
    for signal in reversed(list(background_signals or [])):
        if not isinstance(signal, dict):
            continue
        if str(signal.get("key") or "").strip() != "chosen_schedule_slot":
            continue
        source, status = signal_authority(signal)
        return bool(
            source in accepted_sources
            and status not in {"invalid", "rejected", "superseded"}
            and str(signal.get("value") or "").strip()
        )
    return False


def _active_delivery_signal_context(
    background_signals: Sequence[Dict[str, Any]],
) -> Dict[str, str]:
    """Return accepted durable delivery state that suppresses installation UI."""

    accepted_sources = {
        "latest_user_message",
        "validated_choice_action",
        "signal_ledger",
    }
    rejected_statuses = {
        "invalid",
        "rejected",
        "superseded",
        "customer_reference_needs_validation",
    }
    empty_values = {
        "",
        "unknown",
        "none",
        "n/a",
        "not specified",
        "not_provided_in_chat",
    }
    latest_by_key: Dict[str, Dict[str, Any]] = {}
    for signal in reversed(list(background_signals or [])):
        if not isinstance(signal, dict):
            continue
        key = str(signal.get("key") or "").strip()
        if key not in {"service_type", "delivery_address"} or key in latest_by_key:
            continue
        latest_by_key[key] = signal
    for key in ("service_type", "delivery_address"):
        signal = latest_by_key.get(key) or {}
        source, status = signal_authority(signal)
        if source not in accepted_sources or status in rejected_statuses:
            continue
        value = " ".join(str(signal.get("value") or "").casefold().split())
        if key == "service_type" and value == "delivery":
            return {"key": key, "source": f"durable_{source}"}
        if key == "delivery_address" and value not in empty_values:
            return {"key": key, "source": f"durable_{source}"}
    return {}


def _ambiguous_location_signal_context(
    background_signals: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return the latest unresolved duplicate-place context, if any."""

    for signal in reversed(list(background_signals or [])):
        if not isinstance(signal, dict):
            continue
        if str(signal.get("key") or "").strip() != "location":
            continue
        signal_source = str(signal.get("source") or "").strip()
        if signal_source not in {
            "latest_user_message",
            "validated_choice_action",
            "signal_ledger",
        }:
            continue
        resolution = (
            signal.get("resolution")
            if isinstance(signal.get("resolution"), dict)
            else {}
        )
        metadata = (
            signal.get("metadata")
            if isinstance(signal.get("metadata"), dict)
            else {}
        )
        normalization = (
            metadata.get("normalization")
            if isinstance(metadata.get("normalization"), dict)
            else {}
        )
        normalized_resolution = (
            normalization.get("location_resolution")
            if isinstance(normalization.get("location_resolution"), dict)
            else {}
        )
        ambiguous = (
            str(resolution.get("status") or "").strip()
            == "ambiguous_location"
            or str(normalization.get("status") or "").strip()
            == "location_ambiguous"
            or bool(resolution.get("ambiguity_reason"))
            or bool(normalized_resolution.get("ambiguity_status"))
        )
        if not ambiguous:
            return {}
        options = (
            resolution.get("clarification_options")
            or normalized_resolution.get("clarification_options")
            or []
        )
        return {
            "signal_source": signal_source,
            "clarification_options": [
                str(item).strip()
                for item in options
                if str(item).strip()
            ][:5],
        }
    return {}


class ScriptedRuntimeV7Model:
    """Deterministic model double for local Runtime V7 loop tests."""

    def complete(
        self,
        *,
        messages: Sequence[Dict[str, Any]],
        tools: Sequence[Dict[str, Any]],
        tool_choice: str = "auto",
    ) -> Dict[str, Any]:
        latest = messages[-1] if messages else {}
        if latest.get("role") == "tool":
            return self._final_from_tool(latest)
        user_context = _latest_user_content(messages)
        customer_message = _extract_context_section(user_context, "Current Customer Message")
        lower = customer_message.lower()
        if "una" in lower or "first" in lower:
            return _model_response(
                tool_calls=[
                    {
                        "id": "call_get_details_1",
                        "name": "get_product_details",
                        "args": {
                            "reference_text": customer_message,
                            "selection_basis": "ordinal",
                            "ordinal": 1,
                        },
                    }
                ]
            )
        if "mura" in lower or "cheaper" in lower or "ibang brand" in lower:
            return _model_response(
                tool_calls=[
                    {
                        "id": "call_product_search_2",
                        "name": "product_search",
                        "args": {
                            "section_width": "185",
                            "aspect_ratio": "60",
                            "rim_size": "R15",
                            "budget_max": 5000,
                            "budget_scope": "per_tire",
                            "top_k": 3,
                            "sort": "best_value",
                        },
                    }
                ]
            )
        return _model_response(
            tool_calls=[
                {
                    "id": "call_product_search_1",
                    "name": "product_search",
                    "args": {
                        "section_width": "185" if "185" in lower else None,
                        "aspect_ratio": "60" if "60" in lower else None,
                        "rim_size": "R15" if "r15" in lower or " 15" in lower else None,
                        "brands": ["YOKOHAMA"] if "yokohama" in lower else [],
                        "budget_max": 5000 if "5000" in lower or "budget" in lower else None,
                        "budget_scope": "per_tire",
                        "top_k": 3,
                        "sort": "best_value",
                    },
                }
            ]
        )

    def _final_from_tool(self, tool_message: Dict[str, Any]) -> Dict[str, Any]:
        result = _safe_json_loads(tool_message.get("content") or "{}")
        if tool_message.get("name") == "product_search":
            cards = result.get("product_card_headers") or []
            if cards:
                content = "Meron po akong nakita na options for the requested tire size. Ipapakita ko po yung best options below."
            else:
                content = "Iche-check ko pa po yung closest available options for this request."
            return _model_response(content=content)
        if tool_message.get("name") == "get_product_details":
            product = result.get("product") or {}
            card = result.get("card") or {}
            installment = product.get("installment_text") or "walang installment detail sa stored product data"
            content = (
                f"Yung option na tinutukoy niyo ay {_format_brand_model(card.get('brand'), card.get('sku_model'))}.\n"
                f"Installment: {installment}."
            ).strip()
            return _model_response(content=content)
        return _model_response(content="May product tool result na po ako, pero kailangan ko pang i-check ulit.")


# Backward-compatible model-double name for older product-slice tests.
ScriptedProductAgentModel = ScriptedRuntimeV7Model


def _model_response(
    *,
    content: str = "",
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    usage: Optional[Dict[str, Any]] = None,
    latency_ms: int = 0,
    finish_reason: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "content": content,
        "tool_calls": tool_calls or [],
        "usage": usage or {},
        "latency_ms": latency_ms,
        "finish_reason": finish_reason,
    }


def _normalize_tool_calls(raw_calls: Sequence[Any]) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    for index, call in enumerate(raw_calls or []):
        if isinstance(call, dict):
            function = call.get("function") if isinstance(call.get("function"), dict) else {}
            name = call.get("name") or function.get("name")
            args = call.get("args")
            if args is None:
                args = function.get("arguments")
            calls.append(
                {
                    "id": call.get("id") or f"call_{index + 1}",
                    "name": name,
                    "args": _safe_json_loads(args),
                }
            )
            continue
        function = getattr(call, "function", None)
        name = getattr(call, "name", None) or getattr(function, "name", None)
        args = getattr(call, "args", None)
        if args is None:
            args = getattr(function, "arguments", None)
        calls.append(
            {
                "id": getattr(call, "id", None) or f"call_{index + 1}",
                "name": name,
                "args": _safe_json_loads(args),
            }
        )
    return calls


def _tool_execution_cache_key(name: str, args: Dict[str, Any]) -> str:
    """Return a stable same-turn key for idempotent duplicate tool-call reuse."""

    if str(name or "").strip() == "product_search":
        key_payload = _normalized_product_search_cache_payload(args)
        return f"product_search:{json.dumps(key_payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
    faq_domains = {
        "answer_product_faq": "product",
        "answer_policy_faq": "policy",
        "answer_service_faq": "service",
        "answer_order_faq": "order",
    }
    if str(name or "").strip() in faq_domains:
        faq_id = resolve_faq_id_for_payload(args or {}, domain=faq_domains[str(name or "").strip()])
        if faq_id:
            if str(name or "").strip() in {"answer_order_faq", "answer_policy_faq"}:
                scoped = {
                    "question_topics": sorted(
                        {
                            str(value or "").strip()
                            for value in (args.get("question_topics") or [])
                            if str(value or "").strip()
                        }
                    ),
                    "requested_payment_method": str(
                        args.get("requested_payment_method") or ""
                    ).strip(),
                    "requested_payment_category": str(
                        args.get("requested_payment_category") or ""
                    ).strip(),
                    "requested_product_brand": str(
                        args.get("requested_product_brand") or ""
                    ).strip(),
                    "payment_option": str(args.get("payment_option") or "").strip(),
                    "service_type": str(
                        args.get("service_type")
                        or args.get("fulfillment_path")
                        or ""
                    ).strip(),
                }
                scoped = {
                    key: value
                    for key, value in scoped.items()
                    if value not in (None, "", [], {})
                }
                if scoped:
                    return (
                        f"{str(name or '').strip()}:scope:"
                        + json.dumps(
                            {"faq_id": faq_id, **scoped},
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    )
            return f"{str(name or '').strip()}:faq_id:{faq_id}"
    try:
        args_text = json.dumps(args or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        args_text = str(args or {})
    return f"{str(name or '').strip()}:{args_text}"


def _normalized_product_search_cache_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    """Return the effective product-search fields that determine same-turn output."""

    request = ProductSearchRequest.from_mapping(args).normalized()
    payload = request.to_public_dict()
    payload.pop("brand_corrections", None)
    payload.pop("size_corrections", None)
    payload["soft_preferences"] = _cache_relevant_soft_preferences(payload)
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def _semantic_tool_result_cache_hit(
    name: str,
    args: Dict[str, Any],
    tool_result_cache: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    if name != "find_installation_slots":
        return {}
    requested_date = str((args or {}).get("preferred_date") or "").strip()
    if not requested_date:
        return {}
    requested_key = _installation_slot_semantic_context_key(args)
    if not requested_key:
        return {}
    for cached in tool_result_cache.values():
        if not isinstance(cached, dict) or cached.get("name") != "find_installation_slots":
            continue
        full_result = cached.get("full_result") if isinstance(cached.get("full_result"), dict) else {}
        cached_args = cached.get("args") if isinstance(cached.get("args"), dict) else {}
        if _installation_slot_semantic_context_key(cached_args) != requested_key:
            continue
        if not _slot_result_contains_date(full_result, requested_date):
            continue
        reused = deepcopy(cached)
        reused["cache_match_type"] = "semantic_slots_date_already_returned"
        return reused
    return {}


def _runtime_preloaded_tool_result_hit(
    name: str,
    tool_results: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Reuse successful deterministic evidence when the model requests it again.

    Some typed customer intents are fulfilled before the model loop so the
    corresponding provider tools are intentionally absent from the exposed
    schema. A model can still repeat a tool name learned from prior context.
    That repetition must consume the already-authoritative result, not become
    a false provider failure. Only the exact read-only promo tools currently
    supported by deterministic preload are eligible, and unsuccessful or
    malformed preload records are never reused.
    """

    if name not in {"search_promo_catalog", "present_promo_gallery"}:
        return {}
    for result in reversed(tool_results or []):
        if (
            not isinstance(result, Mapping)
            or result.get("runtime_preloaded") is not True
            or str(result.get("name") or "").strip() != name
        ):
            continue
        full_result = (
            result.get("full_result")
            if isinstance(result.get("full_result"), Mapping)
            else {}
        )
        compact_result = (
            result.get("result")
            if isinstance(result.get("result"), Mapping)
            else {}
        )
        if (
            str(full_result.get("status") or "").strip() != "ok"
            or str(compact_result.get("status") or "").strip() != "ok"
        ):
            continue
        return deepcopy(dict(result))
    return {}


def _installation_slot_semantic_context_key(args: Dict[str, Any]) -> str:
    if not isinstance(args, dict):
        return ""
    payload = {
        "location": _normalize_match_text(args.get("location") or args.get("area")),
        "service_type": _normalize_match_text(args.get("service_type")),
        "section_width": normalize_section_width(args.get("section_width")),
        "aspect_ratio": _normalize_match_text(args.get("aspect_ratio")),
        "rim_size": _normalize_match_text(normalize_rim_size(args.get("rim_size"))),
        "installation_partner_ref": _normalize_match_text(args.get("installation_partner_ref")),
        "service_location_ref": _normalize_match_text(args.get("service_location_ref")),
        "preferred_time_window": _normalize_match_text(args.get("preferred_time_window")),
    }
    payload = {key: value for key, value in payload.items() if value not in (None, "", [], {})}
    if not payload.get("location") and not (payload.get("installation_partner_ref") or payload.get("service_location_ref")):
        return ""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _slot_result_contains_date(result: Dict[str, Any], requested_date: str) -> bool:
    if not isinstance(result, dict) or not requested_date:
        return False
    for group in result.get("slot_groups") or []:
        if not isinstance(group, dict):
            continue
        for slot in group.get("slots") or []:
            if isinstance(slot, dict) and str(slot.get("date") or "").strip() == requested_date:
                return True
    availability = result.get("availability") if isinstance(result.get("availability"), dict) else {}
    earliest = availability.get("earliest_available_slot") if isinstance(availability.get("earliest_available_slot"), dict) else {}
    return str(earliest.get("date") or "").strip() == requested_date


def _cache_relevant_soft_preferences(payload: Dict[str, Any]) -> List[str]:
    soft_preferences = [
        str(item or "").strip().lower()
        for item in payload.get("soft_preferences") or []
        if str(item or "").strip()
    ]
    if not soft_preferences:
        return []
    redundant_terms: set[str] = set()
    categories = {str(item or "").strip().upper() for item in payload.get("tire_categories") or []}
    if "BUDGET" in categories or payload.get("budget_max") is not None:
        redundant_terms.update({"budget", "budget-friendly", "cheap", "cheaper", "mura", "affordable"})
    if payload.get("promo_only") is True or payload.get("promo_types"):
        redundant_terms.update({"promo", "promos", "discount", "sale"})
    if payload.get("brands") or payload.get("preferred_brands"):
        redundant_terms.update({str(brand or "").strip().lower() for brand in payload.get("brands") or []})
        redundant_terms.update({str(brand or "").strip().lower() for brand in payload.get("preferred_brands") or []})
    return [preference for preference in soft_preferences if preference not in redundant_terms]


def _reused_tool_compact_result(name: str, compact_result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(compact_result, dict):
        compact_result = {}
    output = {
        "status": compact_result.get("status") or "ok",
        "reused_tool_result": True,
        "reused_result_note": "Same effective tool request already ran in this turn. Use the referenced prior result instead of calling again.",
        "observation_ref": compact_result.get("observation_ref"),
        "presentation_ref": compact_result.get("presentation_ref"),
        "order_summary_ref": compact_result.get("order_summary_ref"),
        "result_level": compact_result.get("result_level"),
        "query_basis": compact_result.get("query_basis"),
    }
    if name in {"product_search", "discover_brand_buckets", "get_product_details"}:
        output["result"] = _final_composer_tool_result_payload(name, compact_result)
    return _compact_unit(output)


def _llm_usage_summary(response: Dict[str, Any]) -> Dict[str, Any]:
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    cache_usage = response.get("cache_usage") if isinstance(response.get("cache_usage"), dict) else {}
    prompt_tokens = _int_or_zero(usage.get("prompt_tokens"))
    completion_tokens = _int_or_zero(usage.get("completion_tokens"))
    total_tokens = _int_or_zero(usage.get("total_tokens"))
    cache_read_input_tokens = _int_or_zero(
        cache_usage.get("cache_read_input_tokens")
        or usage.get("cache_read_input_tokens")
        or _nested_get(usage, "prompt_tokens_details", "cached_tokens")
    )
    uncached_prompt_tokens = max(prompt_tokens - cache_read_input_tokens, 0)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cache_read_input_tokens": cache_read_input_tokens,
        "uncached_prompt_tokens": uncached_prompt_tokens,
        "cache_hit_rate": _ratio(cache_read_input_tokens, prompt_tokens),
        "latency_ms": _int_or_zero(response.get("latency_ms")),
        "reasoning_tokens": _int_or_zero(
            cache_usage.get("reasoning_tokens")
            or usage.get("reasoning_tokens")
            or _nested_get(usage, "completion_tokens_details", "reasoning_tokens")
        ),
    }


def _supplemental_llm_usage_calls(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Project model-backed pre/post-turn work into the complete usage ledger."""

    calls: List[Dict[str, Any]] = []
    extraction = record.get("background_signal_extraction")
    if isinstance(extraction, dict) and extraction.get("model_used"):
        calls.append(
            _supplemental_llm_usage_call(
                component="background_signal_extraction",
                usage=extraction.get("model_usage"),
                cache_usage=extraction.get("model_cache_usage"),
                request_cache=extraction.get("model_request_cache"),
                latency_ms=extraction.get("model_latency_ms"),
                finish_reason=extraction.get("status"),
                model=extraction.get("model"),
                provider_call_count=extraction.get("model_attempts"),
                metered_provider_call_count=extraction.get(
                    "model_metered_attempts"
                ),
                retry_errors=extraction.get("model_retry_errors"),
            )
        )

    memory = record.get("active_working_memory_after_turn")
    memory_meta = memory.get("metadata") if isinstance(memory, dict) else {}
    if isinstance(memory_meta, dict) and (
        memory_meta.get("usage")
        or memory_meta.get("model_attempts")
        or memory_meta.get("model")
    ):
        calls.append(
            _supplemental_llm_usage_call(
                component="active_working_memory",
                usage=memory_meta.get("usage"),
                cache_usage=memory_meta.get("cache_usage"),
                request_cache=memory_meta.get("request_cache"),
                latency_ms=memory_meta.get("latency_ms"),
                finish_reason=memory_meta.get("finish_reason"),
                model=memory_meta.get("model"),
                provider_call_count=memory_meta.get("model_attempts"),
                retry_errors=memory_meta.get("model_retry_errors"),
            )
        )

    image_evidence = record.get("image_evidence")
    evidence_refs = (
        image_evidence.get("external_evidence_refs")
        if isinstance(image_evidence, dict)
        else []
    )
    for ref in evidence_refs or []:
        if not isinstance(ref, dict):
            continue
        response = ref.get("model_response")
        if not isinstance(response, dict) or not (
            response.get("usage") or response.get("model")
        ):
            continue
        calls.append(
            _supplemental_llm_usage_call(
                component="image_evidence",
                usage=response.get("usage"),
                cache_usage=response.get("cache_usage"),
                request_cache=response.get("request_cache"),
                latency_ms=response.get("latency_ms"),
                finish_reason=response.get("finish_reason"),
                model=response.get("model"),
                provider_call_count=response.get("model_attempts"),
                retry_errors=response.get("model_retry_errors"),
            )
        )
    return calls


def _supplemental_llm_usage_call(
    *,
    component: str,
    usage: Any,
    cache_usage: Any,
    request_cache: Any,
    latency_ms: Any,
    finish_reason: Any,
    model: Any,
    provider_call_count: Any,
    retry_errors: Any,
    metered_provider_call_count: Any = None,
) -> Dict[str, Any]:
    usage_payload = deepcopy(usage) if isinstance(usage, dict) else {}
    cache_payload = deepcopy(cache_usage) if isinstance(cache_usage, dict) else {}
    request_cache_payload = (
        deepcopy(request_cache) if isinstance(request_cache, dict) else {}
    )
    attempts = max(1, _int_or_zero(provider_call_count))
    response = {
        "usage": usage_payload,
        "cache_usage": cache_payload,
        "latency_ms": latency_ms,
    }
    return {
        "component": component,
        "round": component,
        "model": str(model or ""),
        "usage": usage_payload,
        "cache_usage": cache_payload,
        "request_cache": request_cache_payload,
        "usage_summary": _llm_usage_summary(response),
        "latency_ms": latency_ms,
        "finish_reason": str(finish_reason or ""),
        "provider_call_count": attempts,
        "metered_provider_call_count": (
            max(0, min(_int_or_zero(metered_provider_call_count), attempts))
            if metered_provider_call_count is not None
            else None
        ),
        "retry_errors": deepcopy(retry_errors)
        if isinstance(retry_errors, list)
        else [],
        "supplemental_usage_record": True,
    }


def _aggregate_llm_usage(calls: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {
        "llm_call_count": 0,
        "logical_llm_call_count": len(calls),
        "metered_llm_call_count": 0,
        "missing_usage_call_count": 0,
        "unmetered_retry_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cache_read_input_tokens": 0,
        "uncached_prompt_tokens": 0,
        "latency_ms": 0,
        "reasoning_tokens": 0,
    }
    for call in calls:
        usage_summary = call.get("usage_summary") if isinstance(call.get("usage_summary"), dict) else {}
        provider_call_count = max(1, _int_or_zero(call.get("provider_call_count")))
        explicit_metered_count = call.get("metered_provider_call_count")
        if explicit_metered_count is None:
            metered_provider_call_count = (
                1 if _int_or_zero(usage_summary.get("total_tokens")) > 0 else 0
            )
        else:
            metered_provider_call_count = max(
                0,
                min(_int_or_zero(explicit_metered_count), provider_call_count),
            )
        summary["llm_call_count"] += provider_call_count
        summary["metered_llm_call_count"] += metered_provider_call_count
        summary["missing_usage_call_count"] += max(
            provider_call_count - metered_provider_call_count,
            0,
        )
        summary["unmetered_retry_count"] += min(
            max(provider_call_count - metered_provider_call_count, 0),
            max(provider_call_count - 1, 0),
        )
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "cache_read_input_tokens",
            "uncached_prompt_tokens",
            "latency_ms",
            "reasoning_tokens",
        ):
            summary[key] += _int_or_zero(usage_summary.get(key))
    summary["cache_hit_rate"] = _ratio(summary["cache_read_input_tokens"], summary["prompt_tokens"])
    return summary


def _aggregate_turn_usage(turns: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {
        "turn_count": len(turns),
        "llm_call_count": 0,
        "logical_llm_call_count": 0,
        "metered_llm_call_count": 0,
        "missing_usage_call_count": 0,
        "unmetered_retry_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cache_read_input_tokens": 0,
        "uncached_prompt_tokens": 0,
        "latency_ms": 0,
        "reasoning_tokens": 0,
    }
    for turn in turns:
        turn_summary = turn.get("llm_usage_summary") if isinstance(turn.get("llm_usage_summary"), dict) else {}
        for key in summary:
            if key == "turn_count":
                continue
            summary[key] += _int_or_zero(turn_summary.get(key))
    summary["cache_hit_rate"] = _ratio(summary["cache_read_input_tokens"], summary["prompt_tokens"])
    return summary


def _aggregate_context_cache(calls: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "llm_call_count": len(calls or []),
        "explicit_cache_enabled_call_count": 0,
        "explicit_cache_disabled_call_count": 0,
        "cache_guard_event_count": 0,
        "skipped_reasons": {},
        "ttl_values": [],
        "components": {},
    }
    ttl_values = set()
    for call in calls or []:
        if not isinstance(call, dict):
            continue
        component = str(call.get("component") or "main_tool_loop")
        component_summary = summary["components"].setdefault(
            component,
            {"llm_call_count": 0, "explicit_cache_enabled_call_count": 0, "explicit_cache_disabled_call_count": 0},
        )
        component_summary["llm_call_count"] += 1
        request_cache = call.get("request_cache") if isinstance(call.get("request_cache"), dict) else {}
        if request_cache:
            ttl = request_cache.get("ttl")
            if ttl:
                ttl_values.add(str(ttl))
            if bool(request_cache.get("enabled")):
                summary["explicit_cache_enabled_call_count"] += 1
                component_summary["explicit_cache_enabled_call_count"] += 1
            else:
                summary["explicit_cache_disabled_call_count"] += 1
                component_summary["explicit_cache_disabled_call_count"] += 1
                reason = str(request_cache.get("skipped_reason") or "disabled_without_reason")
                summary["skipped_reasons"][reason] = _int_or_zero(summary["skipped_reasons"].get(reason)) + 1
        summary["cache_guard_event_count"] += len(call.get("cache_guard_events") or [])
    summary["ttl_values"] = sorted(ttl_values)
    return summary


def _nested_get(mapping: Dict[str, Any], *keys: str) -> Any:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _int_or_zero(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except Exception:
        return 0


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _normalize_thought_signature_mode(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"strip", "stripped", "remove", "off"}:
        return "strip"
    return "preserve"


def _strip_litellm_thought_signature_id(value: Any) -> str:
    text = str(value or "")
    return text.split("__thought__", 1)[0] if "__thought__" in text else text


def _prepare_tool_calls_for_model_messages(
    tool_calls: Sequence[Dict[str, Any]],
    *,
    mode: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    prepared = deepcopy(list(tool_calls or []))
    events: List[Dict[str, Any]] = []
    if _normalize_thought_signature_mode(mode) != "strip":
        return prepared, events
    for index, call in enumerate(prepared):
        original_id = str(call.get("id") or "")
        stripped_id = _strip_litellm_thought_signature_id(original_id)
        if not original_id or stripped_id == original_id:
            continue
        signature = original_id.split("__thought__", 1)[1]
        call["id"] = stripped_id
        events.append(
            {
                "tool_call_index": index,
                "tool_name": call.get("name"),
                "stripped_tool_call_id": stripped_id,
                "signature_length": len(signature),
            }
        )
    return prepared, events


def _thought_signature_events(*, round_index: int, events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "round": round_index,
            "type": "thought_signature_stripped",
            **dict(event),
        }
        for event in events
    ]


def _assistant_tool_call_message(tool_calls: Sequence[Dict[str, Any]], content: str) -> Dict[str, Any]:
    return {
        "role": "assistant",
        "content": content or None,
        "tool_calls": [
            {
                "id": call.get("id") or str(uuid.uuid4()),
                "type": "function",
                "function": {
                    "name": call.get("name"),
                    "arguments": json.dumps(call.get("args") or {}, ensure_ascii=False),
                },
            }
            for call in tool_calls
        ],
    }


def _invalid_model_product_selection_plan(
    args: Mapping[str, Any],
) -> Dict[str, Any]:
    """Reject untyped model selection refs before they can mutate state."""

    basis = str(args.get("selection_basis") or "").strip()
    if basis:
        return {}
    return {
        "status": "invalid_selection_plan",
        "reason": (
            "Model product-reference calls require selection_basis so runtime "
            "can validate ambiguity before accepting a visible product."
        ),
        "accepted_selection_basis": [
            "exact_ref",
            "ordinal",
            "brand",
            "model",
            "attribute",
        ],
        "read_only": True,
    }


def _compact_payment_policy_for_composer(value: Any) -> Dict[str, Any]:
    """Expose only payment facts useful for concise, grounded composition."""

    policy = value if isinstance(value, Mapping) else {}
    keys = (
        "customer_method_categories",
        "requested_payment_method",
        "requested_payment_category",
        "category_methods",
        "requested_payment_status",
        "requested_product_brand",
        "requested_brand_eligibility",
        "requested_payment_name",
        "payment_option",
        "service_path",
        "applicable_installment_options",
        "reservation_fee_guidance",
    )
    return {
        key: deepcopy(policy.get(key))
        for key in keys
        if policy.get(key) not in (None, "", [], {})
    }


def _compact_tool_result(name: str, result: Dict[str, Any]) -> Dict[str, Any]:
    if name == "get_brand_knowledge":
        return {
            "status": result.get("status"),
            "reason": result.get("reason"),
            "brand_knowledge_version_id": result.get(
                "brand_knowledge_version_id"
            ),
            "profiles": list(result.get("profiles") or [])[:4],
            "missing_brands": list(result.get("missing_brands") or [])[:4],
            "rejected_proposed_brands": list(
                result.get("rejected_proposed_brands") or []
            )[:4],
            "query": str(result.get("query") or "")[:300],
            "source_type": "published_brand_knowledge",
            "composition_guidance": (
                "Use the published brand background for friendly explanation "
                "or comparison. Answer general brand information before any "
                "optional tire-size CTA; size is required only for product "
                "fit, stock, exact price, or size-specific promo checks. Keep "
                "manufacturer/product warranty separate "
                "from the Gulong.ph unconditional-damage warranty. Exact "
                "warranty claims must come from their own structured fields; "
                "never transfer the Gulong.ph purchase-date start, coverage, "
                "or conditions to the manufacturer warranty. If explaining "
                "Gulong.ph damage coverage, include every published "
                "eligibility condition in that coverage record; otherwise "
                "state only its duration and do not summarize the coverage. "
                "Do not mention retrieval, embeddings, records, or refs."
            ),
        }
    if name == "search_promo_catalog":
        tire_size = str(result.get("tire_size") or "").strip()
        allowed_refs = list(result.get("allowed_promo_refs") or [])
        primary_refs = list(
            result.get("primary_promo_refs")
            if "primary_promo_refs" in result
            else allowed_refs
            or []
        )
        alternative_refs = list(result.get("alternative_promo_refs") or [])
        provider_available = str(result.get("status") or "") not in {
            "unavailable",
            "error",
        }
        return {
            "status": result.get("status"),
            "reason": result.get("reason"),
            "provider_available": provider_available,
            "catalog_version_id": result.get("catalog_version_id"),
            "evidence_ref": result.get("evidence_ref"),
            "mode": result.get("mode"),
            "query": result.get("query"),
            "tire_size": tire_size or None,
            "candidate_count": result.get("candidate_count"),
            "published_candidate_count": result.get(
                "published_candidate_count"
            ),
            "current_candidate_count": result.get(
                "current_candidate_count"
            ),
            "expired_candidate_count": result.get(
                "expired_candidate_count"
            ),
            "eligible_candidate_count": result.get("eligible_candidate_count"),
            "alternative_candidate_count": result.get(
                "alternative_candidate_count"
            ),
            "gallery_eligible_candidate_count": result.get(
                "gallery_eligible_candidate_count"
            ),
            "candidates": [
                _compact_promo_contract_candidate(candidate)
                for candidate in result.get("candidates") or []
                if isinstance(candidate, Mapping)
            ][:8],
            "allowed_promo_refs": allowed_refs,
            "primary_promo_refs": primary_refs,
            "alternative_promo_refs": alternative_refs,
            "alternative_scope": result.get("alternative_scope"),
            "requested_brands": list(result.get("requested_brands") or []),
            "matched_requested_brands": list(
                result.get("matched_requested_brands") or []
            ),
            "unmatched_requested_brands": list(
                result.get("unmatched_requested_brands") or []
            ),
            "exact_requested_brand_match": result.get("exact_requested_brand_match"),
            "negative_match_guidance": result.get("negative_match_guidance"),
            "composition_guidance": (
                "The reviewed promo provider is unavailable. This is not evidence "
                "that no promo exists. Say current promo eligibility cannot be "
                "verified right now; offer an exact price/product check or retry."
                if not provider_available
                else
                "No reviewed promo is eligible for the supplied tire size. Do not describe candidates as applicable "
                "to that size and do not enumerate them as offers. Use discover_brand_buckets for interactive "
                "price-category choices unless the customer explicitly asked for a different next step."
                if tire_size and not primary_refs and not alternative_refs
                else (
                    "No reviewed campaign matched this exact catalog search. "
                    "State only that scoped result. The campaign catalog does "
                    "not authorize denying product-level quantity, bundle, "
                    "voucher, discount, price, or SKU promos; those require an "
                    "exact-size product_search result. Ask for the tire size "
                    "when exact promo price or applicability is requested. "
                    "Without a tire size and exact product evidence, do not "
                    "say that no product-level promo was found or is active; "
                    "keep availability, applicability, and price pending and "
                    "ask for the exact size. "
                    "In customer-facing wording, say only what can be "
                    "confirmed now and what size is needed next; never mention "
                    "catalog, search, provider, evidence, scope, review, or "
                    "validation terminology."
                    if not allowed_refs
                    else (
                        "Use primary_promo_refs for scoped applicability claims. "
                        "Use alternative_promo_refs only as explicitly requested fallback offers, "
                        "without transferring the requested brand, mechanic, or size eligibility. "
                        "Use only allowed_promo_refs for gallery selection."
                    )
                )
            ),
            "latency_ms": result.get("latency_ms"),
            "read_only": True,
        }
    if name == "present_promo_gallery":
        cards = [card for card in result.get("cards") or [] if isinstance(card, dict)]
        return {
            "status": result.get("status"),
            "reason": result.get("reason"),
            "catalog_version_id": result.get("catalog_version_id"),
            "presentation_ref": result.get("presentation_ref"),
            "promo_refs": list(result.get("promo_refs") or []),
            "card_refs": list(result.get("card_refs") or []),
            "selection_fingerprint": result.get("selection_fingerprint"),
            "trigger_mode": result.get("trigger_mode"),
            "explicit_redisplay": result.get("explicit_redisplay") is True,
            "cards_will_be_inserted_by_runtime": bool(cards),
            "card_runtime_insert": bool(cards),
            "presentation_surfaces": (
                [
                    {
                        "surface_ref": result.get("presentation_ref"),
                        "type": "promo_catalog",
                        "promo_refs": list(result.get("promo_refs") or []),
                        "card_refs": list(result.get("card_refs") or []),
                        "render_policy": "runtime_inserts_reviewed_gallery",
                    }
                ]
                if cards
                else []
            ),
            "read_only": True,
        }
    if name == "product_search":
        product_cards = result.get("product_cards") or []
        product_headers = _product_card_headers(product_cards)
        compact = {
            "status": result.get("status"),
            "result_level": result.get("result_level"),
            "observation_ref": result.get("observation_ref"),
            "presentation_ref": result.get("presentation_ref"),
            "query_basis": result.get("query_basis"),
            "result_pool_summary": result.get("result_pool_summary"),
            "presentation_strategy": result.get("presentation_strategy"),
            "requested_brand_status": result.get("requested_brand_status"),
            "preferred_brand_status": result.get("preferred_brand_status"),
            "preferred_brand_presentation_status": result.get("preferred_brand_presentation_status"),
            "cards_will_be_inserted_by_runtime": bool(product_cards),
            "card_runtime_insert": bool(product_cards),
            "product_card_headers": product_headers,
            "presentation_units": _product_presentation_units(product_cards),
            "presentation_surfaces": _presentation_surfaces_from_headers(
                surface_ref=result.get("presentation_ref"),
                surface_type="product_cards",
                headers=product_headers,
            ),
        }
        if result.get("status") != "ok":
            compact.update(
                {
                    "reason": result.get("reason"),
                    "suggested_next_step": result.get("suggested_next_step"),
                    "suggested_tool": result.get("suggested_tool"),
                    "recovery_options": result.get("recovery_options") or [],
                }
            )
        return compact
    if name == "discover_brand_buckets":
        bucket_cards = result.get("bucket_cards") or []
        bucket_headers = _bucket_card_headers(bucket_cards)
        compact = {
            "status": result.get("status"),
            "query_basis": result.get("query_basis"),
            "bucket_summary": result.get("bucket_summary"),
            "legend_text": result.get("legend_text"),
            "result_pool_summary": result.get("result_pool_summary"),
            "requested_brand_status": result.get("requested_brand_status"),
            "preferred_brand_status": result.get("preferred_brand_status"),
            "total_brand_count": result.get("total_brand_count"),
            "suggested_next_tool": result.get("suggested_next_tool"),
            "cards_will_be_inserted_by_runtime": bool(bucket_cards),
            "card_runtime_insert": bool(bucket_cards),
            "bucket_card_headers": bucket_headers,
            "presentation_units": _bucket_presentation_units(bucket_cards),
            "presentation_surfaces": _presentation_surfaces_from_headers(
                surface_ref=result.get("presentation_ref"),
                surface_type="brand_menu_cards",
                headers=bucket_headers,
            ),
        }
        if result.get("status") != "ok":
            compact["reason"] = result.get("reason")
        return compact
    if name == "extract_compatible_fitment":
        candidate_headers = _fitment_candidate_headers(result.get("candidate_sizes") or [])
        return {
            "status": result.get("status"),
            "vehicle_query": result.get("vehicle_query"),
            "raw_vehicle_query": result.get("raw_vehicle_query"),
            "presentation_ref": result.get("presentation_ref"),
            "source": result.get("source"),
            "candidate_sizes": result.get("candidate_sizes"),
            "requires_customer_confirmation": result.get("requires_customer_confirmation"),
            "cards_will_be_inserted_by_runtime": bool(candidate_headers),
            "card_runtime_insert": bool(candidate_headers),
            "fitment_candidate_headers": candidate_headers,
            "presentation_surfaces": _presentation_surfaces_from_headers(
                surface_ref=result.get("presentation_ref"),
                surface_type="fitment_candidate_sizes",
                headers=candidate_headers,
            ),
            "note": result.get("note"),
        }
    if name == "resolve_product_reference":
        return deepcopy(result)
    if name == "get_product_details":
        compact = {
            "status": result.get("status"),
            "observation_ref": result.get("observation_ref"),
            "presentation_ref": result.get("presentation_ref"),
            "matched_by": result.get("matched_by"),
            "item_ref": result.get("item_ref"),
            "card_ref": result.get("card_ref"),
            "product": result.get("product"),
            "selected_product_cards": _selected_product_card_headers(result.get("selected_product_cards") or []),
            "card_runtime_insert": bool(result.get("card_runtime_insert") and result.get("selected_product_cards")),
            "presentation_units": _selected_product_presentation_units(result.get("selected_product_cards") or []),
        }
        if result.get("status") != "ok":
            compact["reason"] = result.get("reason")
            compact["resolution"] = result.get("resolution")
        compact["presentation_surfaces"] = _presentation_surfaces_from_headers(
            surface_ref=result.get("presentation_ref"),
            surface_type="selected_product_cards",
            headers=compact.get("selected_product_cards") or [],
        )
        return compact
    if name in {"answer_product_faq", "answer_policy_faq", "answer_service_faq", "answer_order_faq"}:
        policy_type = result.get("policy_type")
        answer = result.get("answer")
        answer_basis = result.get("answer_basis")
        payment_policy = (
            _compact_payment_policy_for_composer(result.get("payment_policy"))
            if name in {"answer_policy_faq", "answer_order_faq"}
            else {}
        )
        if name == "answer_policy_faq" and policy_type == "delivery_fee":
            answer = None
            answer_basis = None
        return {
            "status": result.get("status"),
            "domain": result.get("domain"),
            "matched_domain": result.get("matched_domain"),
            "policy_type": policy_type,
            "applicability": result.get("applicability"),
            "requires_context": result.get("requires_context") or [],
            "answer_basis": answer_basis,
            "policy_facts": result.get("policy_facts"),
            "context_policy_application": result.get("context_policy_application"),
            "composition_hint": result.get("composition_hint"),
            "source_type": "faq",
            "composition_guidance": (
                "Use this retrieved FAQ/policy result as grounding for the customer's specific query. "
                "Tailor the reply to their wording and situation; do not simply restate the stored answer. "
                "Do not mention retrieval, embeddings, RAG, corpus, or internal tool details."
            ),
            "faq_id": result.get("faq_id"),
            "evidence_ref": result.get("evidence_ref"),
            "question": result.get("question"),
            "answer": answer,
            "payment_policy": payment_policy,
            "reason": result.get("reason"),
            "ttl_seconds": result.get("ttl_seconds"),
        }
    if name == "get_business_contact":
        return {
            "status": result.get("status"),
            "domain": result.get("domain"),
            "source_type": "contact_policy",
            "composition_guidance": (
                "Use these runtime-owned contact details exactly. Do not rewrite phone numbers."
            ),
            "question": result.get("question"),
            "answer": result.get("answer"),
            "evidence_ref": result.get("evidence_ref"),
            "ttl_seconds": result.get("ttl_seconds"),
        }
    if name == "calculate_order_quote":
        compact = {
            "status": result.get("status"),
            "quote_ref": result.get("quote_ref"),
            "order_readiness_status": result.get("order_readiness_status"),
            "customer_order_intent": result.get("customer_order_intent"),
            "selected_product": result.get("selected_product") or {},
            "candidate_quotes": result.get("candidate_quotes") or [],
            "quantity": result.get("quantity"),
            "quantity_defaulted": result.get("quantity_defaulted"),
            "service_path": result.get("service_path"),
            "payment_option": result.get("payment_option"),
            "quote_summary": result.get("quote_summary") or {},
            "missing_fields": result.get("missing_fields") or [],
            "invalid_fields": result.get("invalid_fields") or [],
            "assumptions": result.get("assumptions") or [],
            "validation": result.get("validation") or [],
            "customer_explanation_hints": result.get("customer_explanation_hints") or [],
            "read_only": result.get("read_only"),
            "can_submit_order": result.get("can_submit_order"),
        }
        return {key: value for key, value in compact.items() if value not in (None, "", [], {})}
    if name == "build_order_summary":
        order_surface_ref = result.get("order_summary_ref")
        compact = {
            "status": result.get("status"),
            "order_readiness_status": result.get("order_readiness_status"),
            "customer_order_intent": result.get("customer_order_intent"),
            "can_prepare_order_summary": result.get("can_prepare_order_summary"),
            "order_summary_ref": order_surface_ref,
            "card_runtime_insert": bool(result.get("card_runtime_insert")),
            "runtime_renders_body": bool(result.get("runtime_renders_body")),
            "summary_preview": result.get("summary_preview") or {},
            "quote_summary": result.get("quote_summary") or {},
            "source_refs": result.get("source_refs") or {},
            "summary_update": result.get("summary_update") or {},
            "can_build_order_payload": result.get("can_build_order_payload"),
            "recommended_next_tool": result.get("recommended_next_tool"),
            "payment_method": result.get("payment_method"),
            "payment_bank": result.get("payment_bank"),
            "installment_months": result.get("installment_months"),
            "missing_fields": result.get("missing_fields") or [],
            "submission_blockers": result.get("submission_blockers") or [],
            "schedule_status": result.get("schedule_status"),
            "assumptions": result.get("assumptions") or [],
            "validation": result.get("validation") or [],
            "customer_explanation_hints": result.get("customer_explanation_hints") or [],
            "order_faq_suggestions": result.get("order_faq_suggestions") or [],
            "supporting_policy_context": result.get("supporting_policy_context") or [],
            "presentation_units": _order_summary_presentation_units(result),
            "read_only": result.get("read_only"),
            "can_submit_order": result.get("can_submit_order"),
        }
        if result.get("card_runtime_insert"):
            compact["presentation_surfaces"] = [
                _compact_unit(
                    {
                        "surface_ref": order_surface_ref,
                        "type": "order_summary",
                        "summary_status": result.get("status"),
                        "can_submit_order": result.get("can_submit_order"),
                        "rendered_as": "order_details_so_far"
                        if result.get("status") == "incomplete"
                        else "order_summary",
                        "render_policy": "runtime_inserts_exact_body",
                        "summary": result.get("summary_preview") or {},
                        "missing_fields": result.get("missing_fields") or [],
                        "submission_blockers": result.get("submission_blockers") or [],
                        "schedule_status": result.get("schedule_status"),
                        "assumptions": result.get("assumptions") or [],
                    }
                )
            ]
        return {key: value for key, value in compact.items() if value not in (None, "", [], {})}
    if name == "build_order_payload":
        compact = {
            "status": result.get("status"),
            "order_payload_ref": result.get("order_payload_ref"),
            "order_readiness_status": result.get("order_readiness_status"),
            "customer_order_intent": result.get("customer_order_intent"),
            "selected_product": result.get("selected_product") or {},
            "quantity": result.get("quantity"),
            "quantity_defaulted": result.get("quantity_defaulted"),
            "service_path": result.get("service_path"),
            "payment_option": result.get("payment_option"),
            "payment_method": result.get("payment_method"),
            "payment_bank": result.get("payment_bank"),
            "installment_months": result.get("installment_months"),
            "quote_summary": result.get("quote_summary") or {},
            "missing_fields": result.get("missing_fields") or [],
            "invalid_fields": result.get("invalid_fields") or [],
            "assumptions": result.get("assumptions") or [],
            "validation": result.get("validation") or [],
            "customer_explanation_hints": result.get("customer_explanation_hints") or [],
            "order_payload_summary": _compact_order_payload(result.get("order_payload") or {}),
            "read_only": result.get("read_only"),
            "can_submit_order": result.get("can_submit_order"),
        }
        return {key: value for key, value in compact.items() if value not in (None, "", [], {})}
    if name == "submit_order":
        api_response = result.get("api_response") if isinstance(result.get("api_response"), dict) else {}
        compact = {
            "status": result.get("status"),
            "order_payload_ref": result.get("order_payload_ref"),
            "order_id": result.get("order_id"),
            "api_status": api_response.get("status") or api_response.get("result"),
            "submitted_at": result.get("submitted_at"),
            "can_request_payment": result.get("can_request_payment"),
            "order_submitted": result.get("order_submitted"),
            "amount_mismatch": result.get("amount_mismatch") or {},
            "message": result.get("message"),
            "error_type": result.get("error_type"),
            "missing_fields": result.get("missing_fields") or [],
            "invalid_fields": result.get("invalid_fields") or [],
            "read_only": result.get("read_only"),
        }
        return {key: value for key, value in compact.items() if value not in (None, "", [], {})}
    if name == "prepare_payment_request":
        compact = {
            "status": result.get("status"),
            "payment_request_ref": result.get("payment_request_ref"),
            "presentation_ref": result.get("presentation_ref"),
            "order_id": result.get("order_id"),
            "order_payload_ref": result.get("order_payload_ref"),
            "payment_stage": result.get("payment_stage"),
            "expected_amount_text": result.get("expected_amount_text"),
            "payment_option": result.get("payment_option"),
            "payment_method": result.get("payment_method"),
            "payment_bank": result.get("payment_bank"),
            "installment_months": result.get("installment_months"),
            "payment_instruction_type": result.get("payment_instruction_type"),
            "primary_method": result.get("primary_method"),
            "amount_mismatch": result.get("amount_mismatch") or {},
            "payment_link_available": bool((result.get("payment_link") or {}).get("url"))
            if isinstance(result.get("payment_link"), dict)
            else False,
            "qr_image": result.get("qr_image") or {},
            "manual_detail_methods": [
                row.get("method")
                for row in result.get("manual_details") or []
                if isinstance(row, dict) and row.get("method")
            ],
            "link_error": result.get("link_error"),
            "can_accept_payment_proof": result.get("can_accept_payment_proof"),
            "runtime_renders_body": result.get("runtime_renders_body"),
            "presentation_surfaces": [
                _compact_unit(
                    {
                        "surface_ref": result.get("presentation_ref"),
                        "type": "payment_request",
                        "render_policy": "runtime_inserts_exact_payment_body",
                        "order_id": result.get("order_id"),
                        "payment_stage": result.get("payment_stage"),
                        "expected_amount_text": result.get("expected_amount_text"),
                        "amount_mismatch": result.get("amount_mismatch") or {},
                    }
                )
            ]
            if result.get("presentation_ref")
            else [],
            "read_only": result.get("read_only"),
        }
        return {key: value for key, value in compact.items() if value not in (None, "", [], {})}
    if name == "match_payment_proof":
        compact = {
            "status": result.get("status"),
            "payment_proof_received": result.get("payment_proof_received"),
            "evidence_ref": result.get("evidence_ref"),
            "order_id": result.get("order_id"),
            "payment_request_ref": result.get("payment_request_ref"),
            "payment_stage": result.get("payment_stage"),
            "expected_amount_text": result.get("expected_amount_text"),
            "extracted_amount_text": result.get("extracted_amount_text"),
            "amount_match": result.get("amount_match"),
            "payment_method": result.get("payment_method"),
            "reference_no": result.get("reference_no"),
            "paid_at": result.get("paid_at"),
            "backend_payment_status": result.get("backend_payment_status"),
            "missing_fields": result.get("missing_fields") or [],
            "mismatches": result.get("mismatches") or [],
            "customer_explanation_hints": result.get("customer_explanation_hints") or [],
            "read_only": result.get("read_only"),
        }
        return {key: value for key, value in compact.items() if value not in (None, "", [], {})}
    if name == "get_order_details":
        compact = {
            "status": result.get("status"),
            "order_id": result.get("order_id"),
            "order_status": result.get("order_status"),
            "payment_status": result.get("payment_status"),
            "unpaid_order_status": result.get("unpaid_order_status"),
            "transaction": result.get("transaction") or {},
            "fulfillment": result.get("fulfillment") or {},
            "payment": result.get("payment") or {},
            "totals": result.get("totals") or {},
            "items": result.get("items") or [],
            "source": result.get("source"),
            "message": result.get("message"),
            "error_type": result.get("error_type"),
            "missing_fields": result.get("missing_fields") or [],
            "read_only": result.get("read_only"),
        }
        return {key: value for key, value in compact.items() if value not in (None, "", [], {})}
    if name == "present_serviceable_location_choices":
        surface = (
            result.get("location_choice_surface")
            if isinstance(result.get("location_choice_surface"), dict)
            else {}
        )
        if str(result.get("status") or "") != "ok" or not surface:
            identity_context = authorized_business_identity_context()
            return {
                "status": result.get("status"),
                "reason": result.get("reason"),
                "decision": result.get("decision"),
                "cards_will_be_inserted_by_runtime": False,
                "routing_only": True,
                "read_only": True,
                **identity_context,
                "note": (
                    "The reviewed operating-identity facts remain authorized even though no location "
                    "choices loaded. Answer a general head-office, online-store, physical-shop, or "
                    "walk-in question directly from those facts. Do not claim that choices are shown "
                    "or that any partner, coverage area, schedule, stock, booking, or reservation is "
                    "available. Ask one city/area question only when checking an installation option "
                    "would be the useful next step."
                ),
            }
        return {
            "status": result.get("status"),
            "choice_level": surface.get("level") or "province",
            "choice_count": len(
                [
                    choice
                    for choice in surface.get("choices") or []
                    if isinstance(choice, dict)
                ]
            ),
            "cards_will_be_inserted_by_runtime": bool(surface),
            "routing_only": True,
            "read_only": True,
            **authorized_business_identity_context(),
            "note": (
                "The runtime will insert trusted province choices. Briefly explain that "
                "Gulong.PH is an online store with reservation-based installation partners, "
                "then ask the customer to choose one visible province. Do not list or rewrite "
                "the choices, claim availability, infer the customer's location, or add another CTA."
            ),
        }
    if name in {"find_installation_partners", "find_service_locations"}:
        partner_cards = result.get("installation_partner_cards") or []
        partner_detail_level = str(result.get("partner_detail_level") or "").strip()
        partner_headers = _installation_partner_card_headers(
            partner_cards,
            partner_detail_level=partner_detail_level,
        )
        suppress_anonymous_cards = _should_suppress_anonymous_partner_cards(name, result, partner_cards)
        render_partner_headers = [] if suppress_anonymous_cards else partner_headers
        model_status = _model_visible_service_status(result)
        compact = {
            "status": model_status,
            "observation_ref": result.get("observation_ref"),
            "presentation_ref": result.get("presentation_ref"),
            "query_basis": _model_visible_service_query_basis(result.get("query_basis")),
            "partner_detail_level": partner_detail_level or None,
            "detail_disclosure": _model_visible_service_detail_disclosure(result),
            "cards_will_be_inserted_by_runtime": bool(partner_cards) and not suppress_anonymous_cards,
            "card_runtime_insert": bool(partner_cards) and not suppress_anonymous_cards,
            "installation_partner_card_headers": partner_headers,
            "presentation_units": _installation_partner_presentation_units(
                [] if suppress_anonymous_cards else partner_cards,
                partner_detail_level=partner_detail_level,
            ),
            "presentation_surfaces": _presentation_surfaces_from_headers(
                surface_ref=result.get("presentation_ref"),
                surface_type="installation_partner_cards",
                headers=render_partner_headers,
            ),
            "installation_partner_headers": _service_location_headers(
                result.get("installation_partners") or result.get("service_locations") or [],
                partner_detail_level=partner_detail_level,
            ),
            "service_location_headers": _service_location_headers(
                result.get("service_locations") or [],
                partner_detail_level=partner_detail_level,
            ),
            "coverage_assessment": _model_visible_coverage_assessment(
                result.get("coverage_assessment"),
                query_basis=result.get("query_basis"),
            ),
            "service_claim_scope": _model_visible_service_claim_scope(
                result,
                lookup_type="partner_coverage",
            ),
            "customer_explanation_hints": result.get("customer_explanation_hints"),
            "service_policy_notes": result.get("service_policy_notes"),
            "schedule_semantics": _partner_lookup_schedule_semantics(result),
            "read_only": result.get("read_only"),
            "note": _model_visible_service_note(result, model_status=model_status),
        }
        if suppress_anonymous_cards:
            compact["anonymous_partner_cards_suppressed"] = True
            compact["suppressed_card_reason"] = (
                "Area-only partner rows are internal coverage proof and are not "
                "customer-visible partner choices."
            )
            compact.pop("presentation_surfaces", None)
        return compact
    if name == "find_installation_slots":
        if (
            result.get("recommendation_mode") == "serviceable_city"
            and isinstance(result.get("location_choice_surface"), dict)
        ):
            surface = result["location_choice_surface"]
            return {
                "status": result.get("status"),
                "recommendation_mode": "serviceable_city",
                "province": surface.get("parent_label"),
                "serviceable_city_labels": [
                    str(choice.get("label") or "")
                    for choice in surface.get("choices") or []
                    if isinstance(choice, dict)
                    and str(choice.get("label") or "").strip()
                ][:8],
                "preview_count": len(
                    [
                        choice
                        for choice in surface.get("choices") or []
                        if isinstance(choice, dict)
                        and choice.get("earliest_slot_preview")
                    ]
                ),
                "city_selection_required": True,
                "slots_authorized": False,
                "read_only": True,
                "note": (
                    "These are city ranking previews only. Do not claim a "
                    "selected city, partner, or schedule. Ask the customer to "
                    "choose a city from the runtime-rendered surface."
                ),
            }
        partner_cards = result.get("installation_partner_cards") or []
        partner_detail_level = str(result.get("partner_detail_level") or "").strip()
        partner_headers = _installation_partner_card_headers(
            partner_cards,
            partner_detail_level=partner_detail_level,
        )
        model_status = _model_visible_service_status(result)
        compact = {
            "status": model_status,
            "observation_ref": result.get("observation_ref"),
            "presentation_ref": result.get("presentation_ref"),
            "query_basis": _model_visible_service_query_basis(result.get("query_basis")),
            "partner_detail_level": partner_detail_level or None,
            "detail_disclosure": _model_visible_service_detail_disclosure(result),
            "cards_will_be_inserted_by_runtime": bool(partner_cards),
            "card_runtime_insert": bool(partner_cards),
            "installation_partner_card_headers": partner_headers,
            "presentation_units": _installation_partner_presentation_units(
                partner_cards,
                partner_detail_level=partner_detail_level,
            ),
            "presentation_surfaces": _presentation_surfaces_from_headers(
                surface_ref=result.get("presentation_ref"),
                surface_type="installation_slot_cards",
                headers=partner_headers,
            ),
            "installation_partner_headers": _service_location_headers(
                result.get("installation_partners") or result.get("service_locations") or [],
                partner_detail_level=partner_detail_level,
            ),
            "service_location_headers": _service_location_headers(
                result.get("service_locations") or [],
                partner_detail_level=partner_detail_level,
            ),
            "coverage_assessment": _model_visible_coverage_assessment(
                result.get("coverage_assessment"),
                query_basis=result.get("query_basis"),
            ),
            "service_claim_scope": _model_visible_service_claim_scope(
                result,
                lookup_type="schedule_options",
            ),
            "customer_explanation_hints": result.get("customer_explanation_hints"),
            "service_policy_notes": result.get("service_policy_notes"),
            "slot_group_headers": _slot_group_headers(
                result.get("slot_groups") or [],
                partner_detail_level=partner_detail_level,
            ),
            "schedule_semantics": _installation_slot_schedule_semantics(result),
            "read_only": result.get("read_only"),
            "note": _model_visible_service_note(result, model_status=model_status),
        }
        if model_status != "delivery_recommended":
            compact["availability"] = result.get("availability")
        return compact
    if name == "get_branch_addons":
        return {
            "status": result.get("status"),
            "observation_ref": result.get("observation_ref"),
            "query_basis": result.get("query_basis"),
            "addon_groups": result.get("addon_groups"),
            "lookup_observation_ref": result.get("lookup_observation_ref"),
            "read_only": result.get("read_only"),
            "can_confirm_booking": result.get("can_confirm_booking"),
            "source": result.get("source"),
            "generated_at": result.get("generated_at"),
            "ttl_seconds": result.get("ttl_seconds"),
            "note": result.get("note"),
        }
    if name == "validate_installation_slot":
        selected_partner = result.get("selected_installation_partner") if isinstance(result.get("selected_installation_partner"), dict) else {}
        selected_partner_header = (
            _service_location_headers([selected_partner], partner_detail_level="area_only")[0]
            if selected_partner
            else {}
        )
        return {
            "status": result.get("status"),
            "valid": result.get("valid"),
            "reason": result.get("reason"),
            "source_observation_ref": result.get("source_observation_ref"),
            "observation_ref": result.get("observation_ref"),
            "selected_slot": result.get("selected_slot"),
            "selected_installation_area": selected_partner_header,
            "available_slot_refs": result.get("available_slot_refs"),
            "read_only": result.get("read_only"),
            "can_confirm_booking": result.get("can_confirm_booking"),
            "note": (
                "Read-only slot validation. Keep exact partner name/address hidden until order summary or "
                "confirmed proceed context."
            ),
        }
    if name == "request_capability":
        return {
            "status": result.get("status"),
            "requested_domain": result.get("requested_domain"),
            "retry_supported": result.get("retry_supported"),
            "note": result.get("note"),
        }
    if name == "request_human_handoff":
        return {
            "status": result.get("status"),
            "requested_at": result.get("requested_at"),
            "evidence_ref": result.get("evidence_ref"),
            "reason_category": result.get("reason_category"),
            "decision": result.get("decision"),
            "reason": result.get("reason"),
            "human_assignment_confirmed": result.get(
                "human_assignment_confirmed"
            ),
            "automated_sales_replies": result.get(
                "automated_sales_replies"
            ),
            "customer_response_constraints": result.get(
                "customer_response_constraints"
            ),
            "read_only": result.get("read_only"),
        }
    return deepcopy(result)


def _compact_fitment_observation(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict) or result.get("status") not in {"ok", "partial"}:
        return {}
    candidate_sizes: List[str] = []
    for row in result.get("candidate_sizes") or []:
        if not isinstance(row, dict):
            continue
        size = str(row.get("size") or "").strip()
        if size and size not in candidate_sizes:
            candidate_sizes.append(size)
    if not candidate_sizes:
        return {}
    return {
        "status": result.get("status"),
        "vehicle_query": result.get("vehicle_query"),
        "source": result.get("source"),
        "candidate_sizes": candidate_sizes[:8],
        "requires_customer_confirmation": bool(result.get("requires_customer_confirmation")),
    }


def _selected_product_context_from_refs(
    refs: Dict[str, Any],
    product_tools: Optional[ProductToolHarness],
) -> Dict[str, Any]:
    """Return a validated selected-product context from trusted product refs."""

    if product_tools is None or not isinstance(refs, dict):
        return {}
    payload = {
        "observation_ref": refs.get("product_observation_ref") or refs.get("observation_ref"),
        "presentation_ref": refs.get("product_presentation_ref") or refs.get("presentation_ref"),
        "card_ref": refs.get("product_card_ref") or refs.get("card_ref"),
        "item_ref": refs.get("product_item_ref") or refs.get("item_ref"),
        "product_id": refs.get("product_id"),
        "slug": refs.get("slug"),
    }
    if not any(payload.get(key) for key in ("card_ref", "item_ref", "product_id", "slug")):
        return {}
    if not payload.get("observation_ref") and not payload.get("presentation_ref"):
        latest = product_tools.store.latest()
        if latest is not None:
            payload["observation_ref"] = latest.observation_ref
            payload["presentation_ref"] = latest.presentation_ref
    resolution = product_tools.resolve_product_reference(payload)
    if resolution.get("status") != "resolved":
        return {}
    return _compact_unit(
        {
            "product_observation_ref": resolution.get("observation_ref"),
            "product_presentation_ref": resolution.get("presentation_ref"),
            "product_card_ref": resolution.get("card_ref"),
            "product_item_ref": resolution.get("item_ref"),
            "product_id": resolution.get("product_id"),
            "slug": resolution.get("slug"),
            "product_summary": resolution.get("product_summary"),
            "selection_source": "trusted_product_reference",
        }
    )


def _selected_product_card_from_narrowed_product_search(args: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    """Auto-select only an unambiguous single visible product card."""

    if not isinstance(result, dict) or result.get("status") != "ok":
        return {}
    cards = [card for card in result.get("product_cards") or [] if isinstance(card, dict)]
    if not cards:
        return {}
    if len(cards) == 1:
        return cards[0]
    return {}


def _coerce_positive_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _normalize_selected_product_ref_aliases(output: Dict[str, Any], context: Dict[str, Any]) -> None:
    """Correct swapped card/item refs against an already trusted product context."""

    if not isinstance(output, dict) or not isinstance(context, dict):
        return
    card_ref = str(context.get("product_card_ref") or "").strip()
    item_ref = str(context.get("product_item_ref") or "").strip()
    output_card_ref = str(output.get("product_card_ref") or output.get("card_ref") or "").strip()
    output_item_ref = str(output.get("product_item_ref") or output.get("item_ref") or "").strip()
    if item_ref and output_card_ref == item_ref:
        output["product_item_ref"] = item_ref
        output["product_card_ref"] = card_ref
    if card_ref and output_item_ref == card_ref:
        output["product_card_ref"] = card_ref
        output["product_item_ref"] = item_ref


def _product_ref_args_overlap_context(output: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """Return true when model refs are aliases/subsets of selected context."""

    if not isinstance(output, dict) or not isinstance(context, dict):
        return False
    context_values = {
        str(context.get("product_card_ref") or "").strip(),
        str(context.get("product_item_ref") or "").strip(),
        str(context.get("product_id") or "").strip(),
        str(context.get("slug") or "").strip(),
    }
    context_values.discard("")
    if not context_values:
        return False
    seen_ref = False
    for key in ("product_card_ref", "card_ref", "product_item_ref", "item_ref", "product_id", "slug"):
        output_value = str(output.get(key) or "").strip()
        if not output_value:
            continue
        seen_ref = True
        if output_value not in context_values:
            return False
    return seen_ref


def _hydrate_service_tool_args(
    name: str,
    args: Dict[str, Any],
    background_signals: Sequence[Dict[str, Any]],
    *,
    current_user_message: str = "",
    request_time: str = "",
    product_tools: Optional[ProductToolHarness] = None,
    service_tools: Optional[RuntimeV7ServiceTools] = None,
    selected_product_context: Optional[Dict[str, Any]] = None,
    order_readiness: Optional[Dict[str, Any]] = None,
    same_turn_tool_calls: Sequence[Mapping[str, Any]] = (),
    normalization_events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Fill service tool args from already-normalized Background Signals."""

    signals = _signals_by_key(background_signals)
    if name == "get_brand_knowledge":
        hydrated = deepcopy(args or {})
        hydrated["_customer_query_text"] = str(
            current_user_message or ""
        ).strip()
        hydrated["_trusted_brands"] = _explicit_latest_brand_signal_values(
            signals
        )
        return hydrated
    if name == "search_promo_catalog":
        hydrated = deepcopy(args or {})
        proposed_alternative_scope = str(
            hydrated.get("alternative_scope") or "none"
        ).strip().casefold()
        alternative_signal = signals.get("promo_alternative_scope") or {}
        trusted_alternative_scope = (
            str(alternative_signal.get("value") or "").strip().casefold()
            if str(alternative_signal.get("source") or "").strip()
            == "latest_user_message"
            else ""
        )
        hydrated["alternative_scope"] = (
            trusted_alternative_scope
            if trusted_alternative_scope in {"same_mechanic", "any_current"}
            else "none"
        )
        if (
            proposed_alternative_scope != hydrated["alternative_scope"]
            and normalization_events is not None
        ):
            normalization_events.append(
                {
                    "type": "promo_alternative_scope_grounded",
                    "tool_name": name,
                    "proposed_value": proposed_alternative_scope,
                    "normalized_value": hydrated["alternative_scope"],
                    "signal_source": str(
                        alternative_signal.get("source") or ""
                    ).strip(),
                }
            )
        # A one-result model plan cannot support negative-match alternatives or
        # "which current brands" answers. Five is already the catalog's
        # targeted default and keeps retrieval bounded while preserving enough
        # evidence for the composer to answer the whole customer question.
        hydrated["top_k"] = max(
            5,
            min(int(hydrated.get("top_k") or 5), 8),
        )
        tire_size = _single_signal_value(signals, "tire_size")
        if tire_size and not hydrated.get("tire_size"):
            parts = _tire_size_parts(tire_size)
            if parts.get("section_width") and parts.get("aspect_ratio") and parts.get("rim_size"):
                hydrated["tire_size"] = (
                    f"{parts['section_width']}/{parts['aspect_ratio']}{parts['rim_size']}"
                )
        explicit_brands = _explicit_latest_brand_signal_values(signals)
        query = str(hydrated.get("query") or "").strip()
        normalized_query = " ".join(
            re.findall(r"[a-z0-9]+", query.casefold())
        )
        missing_brands = []
        for brand in explicit_brands:
            normalized_brand = " ".join(
                re.findall(r"[a-z0-9]+", brand.casefold())
            )
            if (
                normalized_brand
                and not re.search(
                    rf"(?:^|\s){re.escape(normalized_brand)}(?:\s|$)",
                    normalized_query,
                )
            ):
                missing_brands.append(brand)
        if missing_brands:
            hydrated["query"] = " ".join(
                value
                for value in (query, *missing_brands)
                if value
            )
        # Model arguments are proposed retrieval plans. Preserve the exact
        # customer-authored text and normalized latest-turn brands separately
        # so the catalog can reject brands introduced only by the model.
        hydrated["_customer_query_text"] = str(current_user_message or "").strip()
        hydrated["_customer_requested_brands"] = explicit_brands
        return hydrated
    if name in {"product_search", "discover_brand_buckets"}:
        hydrated = deepcopy(args or {})
        service_type = _authoritative_service_path_signal_value(signals)
        if service_type:
            _replace_conflicting_tool_arg_from_signal(
                hydrated,
                key="service_type",
                authoritative_value=service_type,
                signal_key="service_type",
                tool_name=name,
                normalization_events=normalization_events,
            )
        _hydrate_product_size_args_from_signals(
            hydrated,
            signals,
            tool_name=name,
            normalization_events=normalization_events,
        )
        if name == "product_search":
            _hydrate_product_query_args_from_latest_signals(
                hydrated,
                signals,
                current_user_message=current_user_message,
                normalization_events=normalization_events,
            )
            _hydrate_product_quantity_args_from_signals(
                hydrated,
                signals,
                product_tools=product_tools,
                service_tools=service_tools,
                normalization_events=normalization_events,
            )
        return hydrated
    if name == "get_product_details":
        hydrated = deepcopy(args or {})
        service_type = _authoritative_service_path_signal_value(signals)
        if service_type:
            _replace_conflicting_tool_arg_from_signal(
                hydrated,
                key="service_type",
                authoritative_value=service_type,
                signal_key="service_type",
                tool_name=name,
                normalization_events=normalization_events,
            )
        return hydrated
    if name == "answer_policy_faq":
        hydrated = deepcopy(args or {})
        service_type = (
            _authoritative_service_path_signal_value(signals)
            or _latest_policy_query_signal_value(signals, "service_type")
        )
        if service_type:
            hydrated["service_type"] = service_type
        if not str(hydrated.get("question") or "").strip():
            hydrated["question"] = str(current_user_message or "").strip()
        return hydrated
    if name == "answer_order_faq":
        hydrated = deepcopy(args or {})
        same_tool_call_count = sum(
            1
            for call in same_turn_tool_calls or []
            if isinstance(call, Mapping)
            and str(call.get("name") or "").strip() == "answer_order_faq"
        )
        raw_proposed_method = str(
            hydrated.get("requested_payment_method") or ""
        ).strip()
        proposed_method = _customer_backed_proposed_payment_scope_value(
            hydrated,
            key="requested_payment_method",
            current_user_message=current_user_message,
        )
        explicit_installment_scopes = _explicit_customer_installment_plan_scopes(
            current_user_message
        )
        call_scoped_brand = _customer_backed_proposed_payment_brand(
            hydrated,
            current_user_message=current_user_message,
            same_turn_tool_calls=same_turn_tool_calls,
        )
        call_scoped_option = _customer_backed_proposed_payment_scope_value(
            hydrated,
            key="payment_option",
            current_user_message=current_user_message,
        )
        explicit_method_scope = _unique_explicit_installment_scope_for_call(
            proposed_method=raw_proposed_method,
            proposed_brand=call_scoped_brand,
            proposed_option=call_scoped_option,
            scopes=explicit_installment_scopes,
        )
        if explicit_method_scope:
            # A model plan may preserve the provider and interest marker while
            # dropping a customer-authored term (for example, ``BPI 0%`` for
            # ``BPI 6mos 0%``).  Once the partial proposal identifies exactly
            # one customer-authored installment scope, carry the complete
            # scope into provider execution and the cache key.  Ambiguous
            # repeated terms still produce no unique match and are never
            # promoted here.
            proposed_method = str(
                explicit_method_scope.get("requested_payment_method") or ""
            ).strip()
        scope_completed_method = bool(
            explicit_method_scope
            and _normalize_match_text(raw_proposed_method)
            != _normalize_match_text(proposed_method)
        )
        proposed_method_matches_explicit_plan = any(
            _contains_ordered_local_token_span(
                _payment_scope_distinctive_tokens(proposed_method),
                _payment_scope_distinctive_tokens(
                    scope.get("requested_payment_method")
                ),
            )
            for scope in explicit_installment_scopes
        )
        has_compound_call_plan = (
            same_tool_call_count > 1
            or len(explicit_installment_scopes) > 1
            or bool(
                explicit_installment_scopes
                and proposed_method
                and not proposed_method_matches_explicit_plan
            )
        )
        payment_method = _authoritative_payment_query_signal_value(
            signals,
            "payment_method",
        )
        payment_method_signal = signals.get("payment_method") or {}
        _payment_method_source, payment_method_status = signal_authority(
            payment_method_signal
        )
        bank = _authoritative_payment_query_signal_value(signals, "bank")
        months = _authoritative_payment_query_signal_value(
            signals,
            "installment_months",
        )
        specific_method = (
            payment_method
            if payment_method
            and (
                payment_method_status == "mentioned_unconfirmed"
                # `installment` is a broad typed payment category, not a
                # settled provider/route. It may scope a read-only FAQ even if
                # the extractor marked the current mention as confirmed.
                or " ".join(payment_method.casefold().split()) == "installment"
            )
            and not _payment_method_value_is_option_only(payment_method)
            else ""
        )
        requested_parts = [
            bank,
            f"{months} months" if months else "",
            "installment" if bank or months else specific_method,
        ]
        grounded_requested_method = " ".join(
            part for part in requested_parts if part
        )
        if proposed_method:
            hydrated["requested_payment_method"] = proposed_method
        elif has_compound_call_plan and (
            scoped_question_method := _customer_backed_call_question_payment_method(
                hydrated,
                current_user_message=current_user_message,
            )
        ):
            hydrated["requested_payment_method"] = scoped_question_method
        elif grounded_requested_method and not has_compound_call_plan:
            hydrated["requested_payment_method"] = grounded_requested_method
        else:
            # A model-proposed method is only a lookup plan. Customer-backed
            # typed signals own the named method/provider passed to policy.
            hydrated.pop("requested_payment_method", None)
        resolved_call_scoped_brand = _customer_backed_proposed_payment_brand(
            hydrated,
            current_user_message=current_user_message,
            same_turn_tool_calls=same_turn_tool_calls,
        )
        scope_brand = str(
            explicit_method_scope.get("requested_product_brand") or ""
        ).strip()
        requested_brand = (
            scope_brand
            if scope_completed_method and scope_brand
            else resolved_call_scoped_brand or scope_brand
        )
        if not requested_brand and not has_compound_call_plan:
            requested_brand = _explicit_latest_brand_signal_value(signals)
        selected_brand = _selected_product_brand(
            selected_product_context
            if isinstance(selected_product_context, dict)
            else {}
        )
        if requested_brand:
            hydrated["requested_product_brand"] = requested_brand
        elif selected_brand and not has_compound_call_plan:
            hydrated["requested_product_brand"] = selected_brand
        else:
            hydrated.pop("requested_product_brand", None)

        resolved_call_scoped_option = _customer_backed_proposed_payment_scope_value(
            hydrated,
            key="payment_option",
            current_user_message=current_user_message,
        )
        scoped_option = str(
            explicit_method_scope.get("payment_option") or ""
        ).strip() or resolved_call_scoped_option
        signal_option = _authoritative_payment_query_signal_value(
            signals,
            "payment_option",
        )
        proposed_option = (
            "" if has_compound_call_plan else signal_option
        )
        collected = (
            order_readiness.get("collected")
            if isinstance(order_readiness, dict)
            and isinstance(order_readiness.get("collected"), dict)
            else {}
        )
        payment_option = str(
            scoped_option
            or proposed_option
            or collected.get("Payment option")
            or ""
        ).strip()
        if has_compound_call_plan and not scoped_option:
            payment_option = ""
        if payment_option:
            hydrated["payment_option"] = payment_option
        else:
            hydrated.pop("payment_option", None)

        service_path = _authoritative_service_path_signal_value(signals)
        if not service_path:
            service_path = str(collected.get("Fulfillment") or "").strip()
        service_keys = (
            "service_type",
            "fulfillment_path",
            "fulfillment",
            "transaction_type",
            "service_path",
            "order_type",
        )
        for key in service_keys:
            hydrated.pop(key, None)
        if service_path:
            hydrated["service_type"] = service_path
        if has_compound_call_plan and hydrated.get("requested_payment_method"):
            scoped_question = str(
                explicit_method_scope.get("question") or ""
            ).strip() or _customer_payment_question_segment(
                hydrated.get("requested_payment_method"), current_user_message
            )
            if scoped_question:
                hydrated["question"] = scoped_question
        return hydrated

    if name not in {
        "find_installation_partners",
        "find_service_locations",
        "get_branch_addons",
        "find_installation_slots",
        "validate_installation_slot",
    }:
        return deepcopy(args or {})

    hydrated = deepcopy(args or {})
    if name == "find_installation_slots" and request_time and not hydrated.get("request_time"):
        hydrated["request_time"] = request_time
    location = _location_signal_value(signals)
    has_partner_ref = any(
        hydrated.get(key)
        for key in (
            "installation_partner_ref",
            "service_location_ref",
            "installation_partner_name",
            "partner_name",
        )
    )
    if location and not has_partner_ref:
        proposed_area = hydrated.pop("area", None)
        _replace_conflicting_tool_arg_from_signal(
            hydrated,
            key="location",
            authoritative_value=location,
            signal_key="location",
            tool_name=name,
            normalization_events=normalization_events,
        )
        if proposed_area not in (None, "", location) and normalization_events is not None:
            normalization_events.append(
                {
                    "type": "tool_arg_restored_from_authoritative_signal",
                    "tool_name": name,
                    "signal_key": "location",
                    "argument": "area",
                    "model_value": proposed_area,
                    "authoritative_value": location,
                }
            )

    selected_partner_signal = signals.get("selected_installation_partner") or {}
    selected_partner = _single_signal_value(signals, "selected_installation_partner")
    if selected_partner and _selected_partner_signal_can_hydrate(selected_partner_signal) and not any(
        hydrated.get(key)
        for key in ("installation_partner_ref", "service_location_ref", "installation_partner_name", "partner_name")
    ):
        hydrated["installation_partner_name"] = selected_partner

    service_type = _authoritative_service_path_signal_value(signals)
    if service_type:
        _replace_conflicting_tool_arg_from_signal(
            hydrated,
            key="service_type",
            authoritative_value=service_type,
            signal_key="service_type",
            tool_name=name,
            normalization_events=normalization_events,
        )
    addons = _signal_values(signals, "branch_addons")
    if addons and not hydrated.get("requested_addons") and not hydrated.get("branch_addons"):
        hydrated["requested_addons"] = addons

    has_explicit_product_ref = _service_args_have_explicit_product_ref(hydrated)
    sku_or_model = _single_signal_value(signals, "specific_sku_model")
    if has_explicit_product_ref and sku_or_model and not hydrated.get("model_query") and not hydrated.get("model_or_pattern"):
        hydrated["model_query"] = sku_or_model

    explicit_brand = _explicit_latest_brand_signal_value(signals)
    if explicit_brand and not hydrated.get("tire_brand") and not hydrated.get("brand"):
        hydrated["tire_brand"] = explicit_brand

    rim_size = _single_signal_value(signals, "rim_size")
    if rim_size and not hydrated.get("rim_size"):
        hydrated["rim_size"] = normalize_rim_size(rim_size)

    tire_size = _single_signal_value(signals, "tire_size")
    if tire_size:
        parts = _tire_size_parts(tire_size)
        if parts.get("section_width") and not hydrated.get("section_width"):
            hydrated["section_width"] = parts["section_width"]
        if parts.get("aspect_ratio") and not hydrated.get("aspect_ratio"):
            hydrated["aspect_ratio"] = parts["aspect_ratio"]
        if parts.get("rim_size") and not hydrated.get("rim_size"):
            hydrated["rim_size"] = parts["rim_size"]

    schedule = _single_signal_value(signals, "chosen_schedule_slot")
    if schedule and name == "find_installation_slots":
        if not hydrated.get("source_schedule_phrase") and not hydrated.get("schedule_phrase"):
            hydrated["source_schedule_phrase"] = schedule
        if (
            not hydrated.get("preferred_schedule_candidates")
            and not hydrated.get("preferred_date")
            and not hydrated.get("preferred_time_window")
        ):
            hydrated["preferred_date"] = schedule
    if schedule and name == "validate_installation_slot" and not any(
        hydrated.get(key)
        for key in (
            "slot_ref",
            "slot_ordinal",
            "datetime",
            "schedule",
            "date",
            "preferred_date",
            "time",
            "preferred_time",
        )
    ):
        hydrated["schedule"] = schedule
    _hydrate_trusted_product_service_context(hydrated, product_tools=product_tools, signals=signals)
    return hydrated


def _service_type_is_delivery(value: Any) -> bool:
    return "deliver" in str(value or "").strip().lower()


def _hydrate_product_size_args_from_signals(
    hydrated: Dict[str, Any],
    signals: Dict[str, Dict[str, Any]],
    *,
    tool_name: str = "product_search",
    normalization_events: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Make authoritative retained tire size binding on product retrieval.

    Model tool arguments are retrieval proposals. A complete typed size with
    durable customer or validated-choice provenance is the current state and
    therefore replaces conflicting proposed size components.
    """

    tire_size_signal = signals.get("tire_size") or {}
    if (
        not signal_has_durable_authority(tire_size_signal)
        and signal_authority_source(tire_size_signal)
        not in {"human_agent_history", "external_evidence"}
    ):
        return
    tire_size = _single_signal_value(signals, "tire_size")
    if not tire_size:
        return
    parts = _tire_size_parts(tire_size)
    if not parts:
        return
    signal_section = parts.get("section_width")
    replacements = {
        "section_width": signal_section,
        "aspect_ratio": parts.get("aspect_ratio"),
        "rim_size": parts.get("rim_size"),
    }
    changed: Dict[str, Dict[str, Any]] = {}
    for key, authoritative_value in replacements.items():
        if not authoritative_value:
            continue
        proposed_value = hydrated.get(key)
        normalized_proposed = (
            normalize_section_width(proposed_value)
            if key == "section_width" and proposed_value
            else normalize_rim_size(
                proposed_value,
                section_width=signal_section,
            )
            if key == "rim_size" and proposed_value
            else str(proposed_value or "").strip()
        )
        normalized_authoritative = (
            normalize_section_width(authoritative_value)
            if key == "section_width"
            else normalize_rim_size(
                authoritative_value,
                section_width=signal_section,
            )
            if key == "rim_size"
            else str(authoritative_value).strip()
        )
        if normalized_proposed != normalized_authoritative:
            changed[key] = {
                "model_value": proposed_value,
                "authoritative_value": authoritative_value,
            }
        hydrated[key] = authoritative_value
    if changed and normalization_events is not None:
        normalization_events.append(
            {
                "type": "tool_args_restored_from_authoritative_tire_size",
                "tool_name": tool_name,
                "signal_key": "tire_size",
                "tire_size": tire_size,
                "replacements": changed,
            }
        )


def _replace_conflicting_tool_arg_from_signal(
    hydrated: Dict[str, Any],
    *,
    key: str,
    authoritative_value: Any,
    signal_key: str,
    tool_name: str,
    normalization_events: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Replace one model-proposed arg with current customer-backed state."""

    if authoritative_value in (None, "", [], {}):
        return
    proposed_value = hydrated.get(key)
    if proposed_value == authoritative_value:
        return
    hydrated[key] = authoritative_value
    if normalization_events is not None:
        normalization_events.append(
            {
                "type": "tool_arg_restored_from_authoritative_signal",
                "tool_name": tool_name,
                "signal_key": signal_key,
                "argument": key,
                "model_value": proposed_value,
                "authoritative_value": authoritative_value,
            }
        )


def _hydrate_product_query_args_from_latest_signals(
    hydrated: Dict[str, Any],
    signals: Dict[str, Dict[str, Any]],
    *,
    current_user_message: str,
    normalization_events: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Restore customer-authored product constraints omitted by the model.

    The main model still chooses whether product search is useful. Once it
    chooses that provider, the latest customer's explicit brand, model,
    terrain, origin, promo, and category constraints must survive into the
    executed query. Older ledger preferences remain advisory and cannot
    silently narrow a new search.
    """

    def latest_values(signal_key: str) -> List[str]:
        """Return only values explicitly extracted from the latest user turn."""

        signal = signals.get(signal_key) or {}
        if str(signal.get("source") or "").strip() != "latest_user_message":
            return []
        return _signal_values(signals, signal_key)

    explicit_required_brands = latest_values("required_brands")
    if not explicit_required_brands:
        explicit_required_brands = _canonical_brand_mentions_in_text(
            current_user_message
        )
    if explicit_required_brands:
        _replace_conflicting_tool_arg_from_signal(
            hydrated,
            key="required_brands",
            authoritative_value=list(dict.fromkeys(explicit_required_brands)),
            signal_key="required_brands",
            tool_name="product_search",
            normalization_events=normalization_events,
        )
        explicit_brand_match_mode = latest_values("brand_match_mode")
        if explicit_brand_match_mode:
            _replace_conflicting_tool_arg_from_signal(
                hydrated,
                key="brand_match_mode",
                authoritative_value=explicit_brand_match_mode[-1],
                signal_key="brand_match_mode",
                tool_name="product_search",
                normalization_events=normalization_events,
            )
        else:
            # A brand mention alone is a preference, not a prohibition. Keep an
            # explicit strict tool argument when the main model recognized
            # exclusivity, but never manufacture strictness during hydration.
            hydrated.setdefault("brand_match_mode", "prefer")
    else:
        preferred_brands = latest_values("preferred_brands")
        if preferred_brands:
            _replace_conflicting_tool_arg_from_signal(
                hydrated,
                key="preferred_brands",
                authoritative_value=list(dict.fromkeys(preferred_brands)),
                signal_key="preferred_brands",
                tool_name="product_search",
                normalization_events=normalization_events,
            )

    list_signal_args = {
        "excluded_brands": "excluded_brands",
        "origins": "origins",
        "excluded_origins": "excluded_origins",
        "promo_types": "promo_types",
        "excluded_tire_categories": "excluded_tire_categories",
        "tire_category_preference": "tire_categories",
    }
    for signal_key, argument in list_signal_args.items():
        values = latest_values(signal_key)
        if not values:
            continue
        _replace_conflicting_tool_arg_from_signal(
            hydrated,
            key=argument,
            authoritative_value=list(dict.fromkeys(values)),
            signal_key=signal_key,
            tool_name="product_search",
            normalization_events=normalization_events,
        )

    explicit_terrain_types = latest_values("terrain_types")
    if not explicit_terrain_types:
        # Terrain abbreviations are canonical product-filter syntax, not
        # customer-facing phrase matching. Restore them directly from the
        # current customer turn when probabilistic signal extraction omits a
        # clear A/T, M/T, H/T, R/T, or full terrain-class expression.
        explicit_terrain_types = _explicit_terrain_types_from_customer_text(
            current_user_message
        )
    if explicit_terrain_types:
        _replace_conflicting_tool_arg_from_signal(
            hydrated,
            key="terrain_types",
            authoritative_value=list(dict.fromkeys(explicit_terrain_types)),
            signal_key="terrain_types",
            tool_name="product_search",
            normalization_events=normalization_events,
        )

    specific_model = latest_values("specific_sku_model")
    model_scope_brands = explicit_required_brands or latest_values(
        "preferred_brands"
    )
    if len(specific_model) == 1 and not _model_query_is_only_brand_terrain_size(
        specific_model[0],
        brands=model_scope_brands,
    ):
        _replace_conflicting_tool_arg_from_signal(
            hydrated,
            key="model_or_pattern",
            authoritative_value=specific_model[0],
            signal_key="specific_sku_model",
            tool_name="product_search",
            normalization_events=normalization_events,
        )
    elif _model_query_is_only_brand_terrain_size(
        hydrated.get("model_or_pattern"),
        brands=model_scope_brands,
    ):
        removed_value = hydrated.pop("model_or_pattern", None)
        if removed_value and normalization_events is not None:
            normalization_events.append(
                {
                    "type": "tool_arg_removed_non_model_filter_alias",
                    "tool_name": "product_search",
                    "argument": "model_or_pattern",
                    "model_value": removed_value,
                    "reason": "brand_terrain_size_only",
                }
            )


def _explicit_terrain_types_from_customer_text(value: str) -> List[str]:
    """Parse unambiguous customer-authored terrain filter syntax.

    Plain conversational ``at`` must not become all-terrain. Compact ``AT``
    without punctuation is accepted only beside a complete tire size, while
    full terrain names and slash/hyphen abbreviations are self-scoping.
    """

    text = str(value or "").strip().upper().replace("_", " ")
    if not text:
        return []
    has_tire_size = bool(_canonical_tire_size_from_text(text))
    patterns = {
        "ALL_TERRAIN": [
            r"\bALL[\s-]?TERRAIN\b",
            r"\bA\s*/\s*T\b",
            r"\bA-T\b",
            r"\bAT(?:2|3|4|5)?\b" if has_tire_size else r"(?!)",
        ],
        "MUD_TERRAIN": [
            r"\bMUD[\s-]?TERRAIN\b",
            r"\bM\s*/\s*T\b",
            r"\bM-T\b",
            r"\bMT(?:2|3|4|5|6|7|8|9)?\b" if has_tire_size else r"(?!)",
        ],
        "HIGHWAY_TERRAIN": [
            r"\bHIGHWAY[\s-]?TERRAIN\b",
            r"\bH\s*/\s*T\b",
            r"\bH-T\b",
            r"\bHT(?:2|3|4|5|6|7|8|9)?\b" if has_tire_size else r"(?!)",
        ],
        "RUGGED_TERRAIN": [
            r"\b(?:RUGGED|ROUGH|TRAIL)[\s-]?TERRAIN\b",
            r"\bR\s*/\s*T\b",
            r"\bR-T\b",
            r"\bRT(?:2|3|4|5|6|7|8|9)?\b" if has_tire_size else r"(?!)",
        ],
    }
    return [
        terrain_type
        for terrain_type, candidates in patterns.items()
        if any(re.search(pattern, text) for pattern in candidates)
    ]


def _model_query_is_only_brand_terrain_size(
    value: Any,
    *,
    brands: Sequence[str],
) -> bool:
    """Return whether a proposed model query contains no model identity."""

    text = str(value or "").strip().upper()
    if not text:
        return False
    text = re.sub(
        r"\b\d{3}\s*/?\s*\d{2}\s*/?\s*R?\s*\d{2}\b",
        " ",
        text,
    )
    for brand in brands or []:
        normalized_brand = re.escape(str(brand or "").strip().upper())
        if normalized_brand:
            text = re.sub(rf"\b{normalized_brand}\b", " ", text)
    terrain_patterns = [
        r"\b(?:ALL|MUD|HIGHWAY|RUGGED|ROUGH|TRAIL)[\s-]?TERRAIN\b",
        r"\b[AMHR]\s*/\s*T\b",
        r"\b[AMHR]-T\b",
        r"\b(?:AT|MT|HT|RT)(?:2|3|4|5|6|7|8|9)?\b",
    ]
    for pattern in terrain_patterns:
        text = re.sub(pattern, " ", text)
    text = re.sub(r"\b(?:TIRE|TIRES|TYRE|TYRES|GULONG|SIZE|PO)\b", " ", text)
    return not re.sub(r"[^A-Z0-9]+", "", text)


def _hydrate_product_quantity_args_from_signals(
    hydrated: Dict[str, Any],
    signals: Dict[str, Dict[str, Any]],
    *,
    product_tools: Optional[ProductToolHarness] = None,
    service_tools: Optional[RuntimeV7ServiceTools] = None,
    normalization_events: Optional[List[Dict[str, Any]]] = None,
) -> None:
    if hydrated.get("quantity") not in (None, "", [], {}):
        _normalize_model_supplied_product_quantity_from_context(
            hydrated,
            signals,
            product_tools=product_tools,
            service_tools=service_tools,
            normalization_events=normalization_events,
        )
        return
    raw_quantity = _single_signal_value(signals, "quantity")
    if not raw_quantity:
        return
    try:
        quantity = int(str(raw_quantity).strip())
    except (TypeError, ValueError):
        return
    if 1 <= quantity <= 12:
        hydrated["quantity"] = quantity


def _normalize_model_supplied_product_quantity_from_context(
    hydrated: Dict[str, Any],
    signals: Dict[str, Dict[str, Any]],
    *,
    product_tools: Optional[ProductToolHarness] = None,
    service_tools: Optional[RuntimeV7ServiceTools] = None,
    normalization_events: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Resolve ambiguous product-search quantities against trusted turn context.

    This only handles a narrow conflict: the model supplied a product quantity
    that matches a visible service-slot day number, while the latest product
    cards have a different single trusted pricing quantity and no latest
    quantity signal overrides it.
    """

    try:
        model_quantity = int(str(hydrated.get("quantity") or "").strip())
    except (TypeError, ValueError):
        return
    if not (1 <= model_quantity <= 12):
        return
    quantity_signal = signals.get("quantity") or {}
    if _quantity_signal_is_latest_user_value(quantity_signal):
        return
    trusted_quantity = _latest_product_observation_single_quantity(product_tools)
    if not trusted_quantity or trusted_quantity == model_quantity:
        return
    slot_day_numbers = _latest_service_slot_day_numbers(service_tools)
    if model_quantity not in slot_day_numbers:
        return
    hydrated["quantity"] = trusted_quantity
    if normalization_events is not None:
        normalization_events.append(
            {
                "type": "product_quantity_restored_from_visible_product_context",
                "model_quantity": model_quantity,
                "restored_quantity": trusted_quantity,
                "reason": "model_quantity_matched_visible_service_slot_day_number",
                "slot_day_numbers": sorted(slot_day_numbers),
            }
        )


def _quantity_signal_is_latest_user_value(signal: Dict[str, Any]) -> bool:
    if not isinstance(signal, dict) or not signal.get("value"):
        return False
    source = str(signal.get("source") or "").strip().lower()
    status = str(signal.get("status") or "").strip().lower()
    return source == "latest_user_message" or "latest_user_message" in status


def _latest_product_observation_single_quantity(product_tools: Optional[ProductToolHarness]) -> Optional[int]:
    if product_tools is None or not getattr(product_tools, "store", None):
        return None
    latest = product_tools.store.latest()
    if latest is None:
        return None
    quantities: set[int] = set()
    for card in latest.product_cards or []:
        if not isinstance(card, dict):
            continue
        try:
            quantity = int(str(card.get("quantity") or "").strip())
        except (TypeError, ValueError):
            continue
        if 1 <= quantity <= 12:
            quantities.add(quantity)
    if len(quantities) == 1:
        return next(iter(quantities))
    return None


def _latest_service_slot_day_numbers(service_tools: Optional[RuntimeV7ServiceTools]) -> set[int]:
    if service_tools is None or not getattr(service_tools, "store", None):
        return set()
    latest = service_tools.store.latest()
    if latest is None or latest.result_type != "installation_slots":
        return set()
    days: set[int] = set()
    for group in latest.slot_groups or []:
        if not isinstance(group, dict):
            continue
        for slot in list(group.get("slots") or []) + [group.get("fallback_next_open_slot")]:
            if not isinstance(slot, dict):
                continue
            date_text = str(slot.get("date") or slot.get("schedule_date") or slot.get("preferred_date") or "").strip()
            match = re.match(r"^\d{4}-\d{2}-(\d{2})$", date_text)
            if not match:
                continue
            try:
                days.add(int(match.group(1)))
            except ValueError:
                continue
    return days


def _selected_partner_signal_can_hydrate(signal: Dict[str, Any]) -> bool:
    """Return whether a selected-partner signal is specific enough for tool args."""

    if not isinstance(signal, dict):
        return False
    resolution = signal.get("resolution")
    resolution = resolution if isinstance(resolution, dict) else {}
    tier = str(resolution.get("resolution_tier") or "").strip()
    if tier in {"catalog_resolved", "alias_resolved"}:
        return True
    if tier == "generic_facility_reference":
        return False
    if tier == "explicit_unresolved_name":
        return str(signal.get("source") or "") not in {"external_evidence"}
    status = str(resolution.get("status") or "").strip()
    return status == "installation_partner_canonicalized"


def _hydrate_trusted_product_service_context(
    hydrated: Dict[str, Any],
    *,
    product_tools: Optional[ProductToolHarness],
    signals: Dict[str, Dict[str, Any]],
) -> None:
    """Attach product-derived service args only after resolving trusted product refs."""

    has_explicit_product_ref = _service_args_have_explicit_product_ref(hydrated)
    if product_tools is None:
        if not has_explicit_product_ref:
            _remove_unselected_product_service_args(hydrated)
        hydrated.pop("trusted_order_total", None)
        return
    product = _trusted_product_from_service_args(hydrated, product_tools) if has_explicit_product_ref else {}
    if not product:
        candidates = _trusted_product_candidates_from_latest_observation(hydrated, product_tools, signals)
        if has_explicit_product_ref and len(candidates) == 1:
            product = candidates[0]["product"]
            hydrated["product_observation_ref"] = candidates[0]["observation_ref"]
            hydrated["product_presentation_ref"] = candidates[0]["presentation_ref"]
            if candidates[0].get("card_ref"):
                hydrated["product_card_ref"] = candidates[0]["card_ref"]
            if candidates[0].get("item_ref"):
                hydrated["product_item_ref"] = candidates[0]["item_ref"]
        elif candidates:
            hydrated.pop("trusted_order_total", None)
            if not has_explicit_product_ref:
                _remove_unselected_product_service_args(hydrated)
            hydrated["trusted_order_total_candidates"] = [
                {key: value for key, value in candidate.items() if key != "product"}
                for candidate in candidates[:4]
            ]
            return
    if not product:
        if not has_explicit_product_ref:
            _remove_unselected_product_service_args(hydrated)
        hydrated.pop("trusted_order_total", None)
        return

    quantity = _service_quantity(hydrated, signals)
    total = _trusted_product_total(product, quantity=quantity)
    if total is not None:
        hydrated["trusted_order_total"] = total
        hydrated["quantity"] = quantity
        hydrated["trusted_order_total_source"] = "trusted_product_observation"
    if product.get("brand") and not hydrated.get("tire_brand") and not hydrated.get("brand"):
        hydrated["tire_brand"] = product.get("brand")
    model = product.get("pattern") or product.get("model")
    if model and not hydrated.get("model_query") and not hydrated.get("model_or_pattern"):
        hydrated["model_query"] = model
    if product.get("section_width") and not hydrated.get("section_width"):
        hydrated["section_width"] = product.get("section_width")
    if product.get("aspect_ratio") and not hydrated.get("aspect_ratio"):
        hydrated["aspect_ratio"] = product.get("aspect_ratio")
    if product.get("rim_size") and not hydrated.get("rim_size"):
        hydrated["rim_size"] = product.get("rim_size")


def _service_args_have_explicit_product_ref(hydrated: Dict[str, Any]) -> bool:
    """Return whether service args carry a customer-selected product reference."""

    return any(
        hydrated.get(key)
        for key in (
            "product_observation_ref",
            "product_presentation_ref",
            "product_card_ref",
            "product_item_ref",
            "product_id",
            "slug",
            "product_ordinal",
        )
    )


def _remove_unselected_product_service_args(hydrated: Dict[str, Any]) -> None:
    """Keep service lookup generic when no visible product/card has been selected."""

    hydrated.pop("trusted_order_total", None)
    hydrated.pop("trusted_order_total_source", None)
    hydrated.pop("product_observation_ref", None)
    hydrated.pop("product_presentation_ref", None)
    hydrated.pop("product_card_ref", None)
    hydrated.pop("product_item_ref", None)
    hydrated.pop("product_ordinal", None)
    hydrated.pop("product_id", None)
    hydrated.pop("slug", None)
    hydrated.pop("model_query", None)
    hydrated.pop("model_or_pattern", None)


def _trusted_product_from_service_args(
    hydrated: Dict[str, Any],
    product_tools: ProductToolHarness,
) -> Dict[str, Any]:
    if not _service_args_have_explicit_product_ref(hydrated):
        return {}
    resolution = product_tools.resolve_product_reference(
        {
            "observation_ref": hydrated.get("product_observation_ref"),
            "presentation_ref": hydrated.get("product_presentation_ref"),
            "card_ref": hydrated.get("product_card_ref"),
            "item_ref": hydrated.get("product_item_ref"),
            "product_id": hydrated.get("product_id"),
            "slug": hydrated.get("slug"),
            "ordinal": hydrated.get("product_ordinal"),
        }
    )
    if resolution.get("status") != "resolved":
        return {}
    observation = product_tools.store.get(observation_ref=resolution.get("observation_ref"))
    if observation is None:
        return {}
    item_ref = str(resolution.get("item_ref") or "").strip()
    for product in [*observation.presented_products, *observation.best_products]:
        if isinstance(product, dict) and str(product.get("item_ref") or "").strip() == item_ref:
            return deepcopy(product)
    return {}


def _service_quantity(hydrated: Dict[str, Any], signals: Dict[str, Dict[str, Any]]) -> int:
    raw_quantity = hydrated.get("quantity") or _single_signal_value(signals, "quantity")
    try:
        quantity = int(str(raw_quantity or "").strip())
    except Exception:
        quantity = 4
    return max(1, min(quantity, 12))


def _trusted_product_total(product: Dict[str, Any], *, quantity: int) -> Optional[float]:
    total = effective_total_price(product, quantity)
    if total is None:
        price = _coerce_float(product.get("price"))
        total = round(price * quantity, 2) if price is not None else None
    return round(float(total), 2) if total is not None else None


def _trusted_product_candidates_from_latest_observation(
    hydrated: Dict[str, Any],
    product_tools: ProductToolHarness,
    signals: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Find visible product-card candidates matching service context.

    This is deliberately conservative. It can derive a single trusted order
    total only when the latest visible product observation clearly matches the
    service args/signals. Multiple matches are passed as candidates so the model
    can explain threshold differences without the runtime silently choosing a
    SKU.
    """

    observation = product_tools.store.latest()
    if observation is None:
        return []
    brand = _normalize_match_text(hydrated.get("tire_brand") or hydrated.get("brand"))
    section = _normalize_match_text(hydrated.get("section_width") or _single_signal_value(signals, "section_width"))
    aspect = _normalize_match_text(hydrated.get("aspect_ratio") or _single_signal_value(signals, "aspect_ratio"))
    rim = _normalize_match_text(hydrated.get("rim_size") or _single_signal_value(signals, "rim_size")).lstrip("r")
    model = _normalize_match_text(hydrated.get("model_query") or hydrated.get("model_or_pattern"))
    if not any([brand, section, aspect, rim, model]):
        return []

    base_quantity = _service_quantity(hydrated, signals)
    model_supplied_quantity = hydrated.get("quantity") not in (None, "", [], {})
    cards_by_item = {
        str(card.get("item_ref") or "").strip(): card
        for card in observation.product_cards
        if isinstance(card, dict) and str(card.get("item_ref") or "").strip()
    }
    rows: List[Dict[str, Any]] = []
    for product in observation.presented_products or observation.best_products:
        if not isinstance(product, dict):
            continue
        if not _product_matches_service_context(
            product,
            brand=brand,
            section=section,
            aspect=aspect,
            rim=rim,
            model=model,
        ):
            continue
        item_ref = str(product.get("item_ref") or "").strip()
        card = cards_by_item.get(item_ref) or {}
        quantity = base_quantity
        if not model_supplied_quantity:
            card_quantity = _card_quantity({**product, **card})
            if card_quantity > 0:
                quantity = card_quantity
        total = _trusted_product_total(product, quantity=quantity)
        if total is None:
            continue
        rows.append(
            {
                "observation_ref": observation.observation_ref,
                "presentation_ref": observation.presentation_ref,
                "card_ref": card.get("card_ref"),
                "item_ref": item_ref or None,
                "product_id": product.get("product_id") or product.get("id"),
                "slug": product.get("slug"),
                "brand": product.get("brand"),
                "model": product.get("pattern") or product.get("model"),
                "tire_size": _product_tire_size_label(product),
                "quantity": quantity,
                "trusted_order_total": total,
                "trusted_order_total_source": "visible_product_observation_candidate",
                "product": deepcopy(product),
            }
        )
    return rows[:4]


def _card_quantity(card: Dict[str, Any]) -> int:
    if not _card_quantity_is_binding(card):
        return 0
    try:
        quantity = int(str(card.get("quantity") or "").strip())
    except Exception:
        quantity = 0
    return max(0, min(quantity, 12))


def _card_quantity_is_binding(card: Dict[str, Any]) -> bool:
    pricing_basis = str(card.get("pricing_basis") or "").strip().lower()
    if pricing_basis == "buy3get1":
        return True
    promo_line = str(card.get("promo_savings_line") or card.get("promo_line") or "").strip().lower()
    if "buy 3 get 1" in promo_line:
        return True
    try:
        quantity = int(str(card.get("quantity") or "").strip())
    except Exception:
        quantity = 0
    return quantity == 4 and bool(card.get("buy3get1_eligible"))


def _explicit_latest_brand_signal_value(signals: Dict[str, Dict[str, Any]]) -> str:
    """Return latest-user brand signal only; ledger preferences stay advisory."""

    for key in ("required_brands", "preferred_brands"):
        signal = signals.get(key) or {}
        if str(signal.get("source") or "") != "latest_user_message":
            continue
        value = _single_signal_value(signals, key)
        if value:
            return value
    return ""


def _explicit_latest_brand_signal_values(
    signals: Dict[str, Dict[str, Any]],
) -> List[str]:
    """Return every distinct latest-turn brand for promo query validation."""

    values: List[str] = []
    for key in ("required_brands", "preferred_brands"):
        signal = signals.get(key) or {}
        if str(signal.get("source") or "") != "latest_user_message":
            continue
        values.extend(_signal_values(signals, key))
    return list(dict.fromkeys(values))


def _customer_backed_proposed_payment_brand(
    args: Dict[str, Any],
    *,
    current_user_message: str = "",
    same_turn_tool_calls: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Keep a model-proposed brand only when the current question says it.

    Compound payment questions are not guaranteed to produce a separate brand
    signal. The model's argument remains a query plan, so runtime accepts it
    only when its normalized value is explicitly present in customer-backed
    question/context text.
    """

    proposed = str(args.get("requested_product_brand") or "").strip()
    if not proposed:
        return ""
    context = str(current_user_message or "").strip() or " ".join(
        str(args.get(key) or "").strip()
        for key in ("question", "customer_context")
        if str(args.get(key) or "").strip()
    )
    proposed_normalized = " ".join(
        re.findall(r"[a-z0-9]+", proposed.casefold())
    )
    if not proposed_normalized or not context:
        return ""
    method_tokens = _payment_scope_distinctive_tokens(
        args.get("requested_payment_method")
    )
    proposed_peer_brands = {
        " ".join(
            re.findall(
                r"[a-z0-9]+",
                str(
                    (call.get("args") or {}).get("requested_product_brand")
                    or ""
                ).casefold(),
            )
        )
        for call in same_turn_tool_calls or []
        if isinstance(call, Mapping)
        and isinstance(call.get("args"), Mapping)
        and str(
            (call.get("args") or {}).get("requested_product_brand") or ""
        ).strip()
    }
    proposed_peer_brands.discard("")
    customer_brand_mentions = {
        " ".join(re.findall(r"[a-z0-9]+", brand.casefold()))
        for brand in _canonical_brand_mentions_in_text(context)
    }
    # One customer brand can govern coordinated sibling terms in the same
    # sentence. With multiple explicit brands, require local clause association
    # so one brand cannot bleed into another brand's payment term.
    segments = (
        _customer_payment_method_segments(context)
        if len(proposed_peer_brands | customer_brand_mentions) > 1
        else _customer_payment_scope_segments(context)
    )
    for segment in segments:
        segment_normalized = " ".join(
            re.findall(r"[a-z0-9]+", segment.casefold())
        )
        if not re.search(
            rf"(?:^|\s){re.escape(proposed_normalized)}(?:\s|$)",
            segment_normalized,
        ):
            continue
        if method_tokens and not _contains_ordered_local_token_span(
            _payment_scope_distinctive_tokens(segment),
            method_tokens,
        ):
            continue
        return proposed
    return ""


def _canonical_brand_mentions_in_text(value: Any) -> List[str]:
    """Return exact canonical catalog-brand mentions from customer text."""

    normalized = " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))
    mentions: List[str] = []
    for brand in DEFAULT_CANONICAL_BRANDS:
        normalized_brand = " ".join(
            re.findall(r"[a-z0-9]+", brand.casefold())
        )
        if normalized_brand and re.search(
            rf"(?:^|\s){re.escape(normalized_brand)}(?:\s|$)",
            normalized,
        ):
            mentions.append(brand)
    return mentions


def _customer_backed_proposed_payment_scope_value(
    args: Mapping[str, Any],
    *,
    key: str,
    current_user_message: str = "",
) -> str:
    """Keep a per-call payment scope only when the customer supplied it.

    The main model may split a compound question into several FAQ calls. Each
    call's method and option are therefore authoritative as *query scope* only
    after their distinctive tokens are found in the complete latest message.
    Generic payment words are ignored so normalized forms such as
    ``3 months installment`` can match ``3-month 0%`` without authorizing an
    invented provider, bank, or term.
    """

    proposed = str((args or {}).get(key) or "").strip()
    if not proposed:
        return ""
    if key == "requested_payment_method" and _payment_method_value_is_option_only(
        proposed
    ):
        return ""
    context = str(current_user_message or "").strip() or " ".join(
        str((args or {}).get(field) or "").strip()
        for field in ("question", "customer_context")
        if str((args or {}).get(field) or "").strip()
    )
    proposed_tokens = _payment_scope_distinctive_tokens(proposed)
    if not proposed_tokens or len(proposed_tokens) > 6:
        return ""
    if key == "requested_payment_method" and current_user_message:
        model_local_context = " ".join(
            str((args or {}).get(field) or "").strip()
            for field in ("question", "customer_context")
            if str((args or {}).get(field) or "").strip()
        )
        if not _contains_ordered_local_token_span(
            _payment_scope_distinctive_tokens(model_local_context),
            proposed_tokens,
        ):
            return ""
    anchor_tokens: List[str] = []
    if key == "payment_option":
        anchor_tokens = _payment_scope_distinctive_tokens(
            (args or {}).get("requested_payment_method")
        )
        if not anchor_tokens:
            anchor_tokens = _payment_scope_distinctive_tokens(
                (args or {}).get("requested_product_brand")
            )
    segments = (
        _customer_payment_method_segments(context)
        if key == "requested_payment_method"
        else _customer_payment_scope_segments(context)
    )
    for segment in segments:
        context_tokens = _payment_scope_distinctive_tokens(segment)
        if not _contains_ordered_local_token_span(
            context_tokens,
            proposed_tokens,
        ):
            continue
        if anchor_tokens and not _contains_ordered_local_token_span(
            context_tokens,
            anchor_tokens,
        ):
            continue
        return proposed
    return ""


def _payment_scope_distinctive_tokens(value: Any) -> List[str]:
    """Return customer-distinguishing tokens for a payment lookup scope."""

    generic = {
        "installment",
        "installments",
        "interest",
        "method",
        "methods",
        "month",
        "months",
        "mos",
        "option",
        "options",
        "payment",
        "payments",
    }
    return [
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if token not in generic
    ]


def _customer_backed_call_question_payment_method(
    args: Mapping[str, Any],
    *,
    current_user_message: str,
) -> str:
    """Recover one unambiguous installment scope from its isolated question."""

    question = str((args or {}).get("question") or "").strip()
    if not question:
        return ""
    months = list(
        dict.fromkeys(
            re.findall(
                r"\b(\d{1,2})\s*(?:-|\s)?(?:month|months|mos|mo)\b",
                question.casefold(),
            )
        )
    )
    if len(months) != 1:
        return ""
    hints = payment_plan_hints_from_text(question)
    bank = str(hints.get("bank") or "").strip()
    candidates = [
        " ".join(
            part
            for part in (bank, f"{months[0]} months", "installment")
            if part
        )
    ]
    if bank:
        candidates.append(f"{months[0]} months installment")
    for candidate in candidates:
        grounded = _customer_backed_proposed_payment_scope_value(
            {**dict(args or {}), "requested_payment_method": candidate},
            key="requested_payment_method",
            current_user_message=current_user_message,
        )
        if grounded:
            return grounded
    return ""


def _customer_payment_scope_segments(value: Any) -> List[str]:
    """Split customer text at hard sentence boundaries for scope validation."""

    return [
        segment.strip()
        for segment in re.split(r"[?!;\n]+|(?<=[a-z0-9])\.(?:\s|$)", str(value or ""), flags=re.IGNORECASE)
        if segment.strip()
    ]


def _customer_payment_method_segments(value: Any) -> List[str]:
    """Split coordinated payment methods while retaining outer shared scope."""

    output: List[str] = []
    for sentence in _customer_payment_scope_segments(value):
        output.extend(
            segment.strip(" ,")
            for segment in re.split(
                r"\b(?:and|at|but|o|or|pero|while)\b",
                sentence,
                flags=re.IGNORECASE,
            )
            if segment.strip(" ,")
        )
    return output


def _customer_payment_question_segment(
    payment_method: Any,
    current_user_message: Any,
) -> str:
    """Return the customer clause that actually contains one payment scope."""

    method_tokens = _payment_scope_distinctive_tokens(payment_method)
    if not method_tokens:
        return ""
    for segment in _customer_payment_method_segments(current_user_message):
        if _contains_ordered_local_token_span(
            _payment_scope_distinctive_tokens(segment),
            method_tokens,
        ):
            return segment.strip()
    return ""


def _explicit_customer_installment_plan_scopes(value: Any) -> List[Dict[str, str]]:
    """Extract distinct customer-authored numeric installment lookup scopes."""

    scopes: List[Dict[str, str]] = []
    seen_scopes: Set[Tuple[str, str, str]] = set()
    for sentence in _customer_payment_scope_segments(value):
        sentence_brands = _canonical_brand_mentions_in_text(sentence)
        option_matches = list(
            re.finditer(
                r"\bpay\s+(later|now)\b",
                sentence,
                flags=re.IGNORECASE,
            )
        )
        sentence_option = (
            f"Pay {option_matches[0].group(1).title()}"
            if len(option_matches) == 1
            else ""
        )
        brand_positions = [
            position
            for brand in sentence_brands
            if (position := sentence.casefold().find(brand.casefold())) >= 0
        ]
        sentence_option_is_global = bool(
            sentence_option
            and (
                not brand_positions
                or option_matches[0].start() < min(brand_positions)
            )
        )
        for segment in _customer_payment_method_segments(sentence):
            segment_brands = _canonical_brand_mentions_in_text(segment)
            brand = (
                segment_brands[0]
                if len(segment_brands) == 1
                else sentence_brands[0]
                if not segment_brands and len(sentence_brands) == 1
                else ""
            )
            local_segment_option = (
                "Pay Later"
                if re.search(
                    r"\bpay\s+later\b", segment, flags=re.IGNORECASE
                )
                else "Pay Now"
                if re.search(
                    r"\bpay\s+now\b", segment, flags=re.IGNORECASE
                )
                else ""
            )
            segment_option = (
                local_segment_option
                or (
                    sentence_option
                    if sentence_option_is_global or len(sentence_brands) <= 1
                    else ""
                )
            )
            for match in re.finditer(
                r"\b(\d{1,2})\s*(?:-|\s)?(?:month|months|mos|mo)\b",
                segment,
                flags=re.IGNORECASE,
            ):
                months = match.group(1)
                prefix = segment[: match.start()]
                bank_match = re.search(r"\b([A-Z]{2,10})\s*$", prefix)
                bank = bank_match.group(1) if bank_match else ""
                suffix = segment[match.end() :]
                zero_interest = bool(
                    re.match(r"\s*0\s*%", suffix, flags=re.IGNORECASE)
                )
                method = " ".join(
                    part
                    for part in (
                        bank,
                        f"{months} months installment",
                        "0% interest" if zero_interest else "",
                    )
                    if part
                )
                scope_key = (
                    " ".join(method.casefold().split()),
                    brand.casefold(),
                    segment_option.casefold(),
                )
                if scope_key in seen_scopes:
                    continue
                seen_scopes.add(scope_key)
                scope = {
                    "requested_payment_method": method,
                    "question": segment.strip(),
                }
                if brand:
                    scope["requested_product_brand"] = brand
                if segment_option:
                    scope["payment_option"] = segment_option
                scopes.append(scope)
    return scopes


def _model_merged_cross_clause_payment_scopes(
    value: Any,
    *,
    background_signals: Sequence[Mapping[str, Any]],
    tool_results: Sequence[Mapping[str, Any]],
) -> List[Dict[str, str]]:
    """Recover customer-backed named methods merged with a sibling clause.

    A model can occasionally combine two independent payment questions into
    one ``requested_payment_method`` proposal. Hydration correctly refuses to
    pass that cross-clause value through unchanged, but the named-method clause
    must still receive its own canonical provider lookup. This helper derives
    only the portion of the model proposal that is present in a separate hard
    customer clause; it does not maintain a provider, bank, or brand phrase
    list and it never decides support or eligibility.
    """

    customer_segments = _customer_payment_scope_segments(value)
    if len(customer_segments) < 2:
        return []
    segment_tokens = [
        _payment_scope_distinctive_tokens(segment)
        for segment in customer_segments
    ]
    grounded_single_token_methods = {
        tokens[0]
        for signal in background_signals or []
        if isinstance(signal, Mapping)
        and str(signal.get("source") or "") == "latest_user_message"
        and str(signal.get("key") or "") == "payment_method"
        and str(signal.get("status") or "") == "mentioned_unconfirmed"
        and len(
            tokens := _payment_scope_distinctive_tokens(signal.get("value"))
        )
        == 1
        and not _payment_method_value_is_option_only(signal.get("value"))
        and any(
            _contains_ordered_local_token_span(
                _payment_scope_distinctive_tokens(segment),
                tokens,
            )
            for segment in customer_segments
        )
    }
    output: List[Dict[str, str]] = []
    seen: Set[Tuple[str, str, str]] = set()
    for result in tool_results or []:
        if (
            not isinstance(result, Mapping)
            or str(result.get("name") or "") != "answer_order_faq"
        ):
            continue
        model_args = (
            result.get("model_args")
            if isinstance(result.get("model_args"), Mapping)
            else {}
        )
        proposed = str(model_args.get("requested_payment_method") or "").strip()
        proposed_tokens = _payment_scope_distinctive_tokens(proposed)
        if not proposed_tokens or len(proposed_tokens) > 6:
            continue
        overlapping_segments = [
            index
            for index, tokens in enumerate(segment_tokens)
            if set(tokens).intersection(proposed_tokens)
        ]
        if len(overlapping_segments) < 2:
            continue
        for index in overlapping_segments:
            segment = customer_segments[index]
            if re.search(
                r"\b\d{1,2}\s*(?:-|\s)?(?:month|months|mos|mo)\b",
                segment,
                flags=re.IGNORECASE,
            ):
                continue
            local_tokens = segment_tokens[index]
            candidate_tokens: List[str] = []
            for start in range(len(proposed_tokens)):
                for end in range(len(proposed_tokens), start, -1):
                    candidate = proposed_tokens[start:end]
                    if _contains_ordered_local_token_span(local_tokens, candidate):
                        candidate_tokens = candidate
                        break
                if candidate_tokens:
                    break
            if not candidate_tokens or all(token.isdigit() for token in candidate_tokens):
                continue
            if (
                len(candidate_tokens) == 1
                and candidate_tokens[0] not in grounded_single_token_methods
            ):
                continue
            method = " ".join(candidate_tokens)
            if _payment_method_value_is_option_only(method):
                continue
            method = _payment_method_case_from_proposal(proposed, candidate_tokens)
            brand_mentions = _canonical_brand_mentions_in_text(segment)
            payment_option = (
                "Pay Later"
                if re.search(r"\bpay\s+later\b", segment, flags=re.IGNORECASE)
                else "Pay Now"
                if re.search(r"\bpay\s+now\b", segment, flags=re.IGNORECASE)
                else ""
            )
            identity = (
                " ".join(method.casefold().split()),
                brand_mentions[0].casefold() if len(brand_mentions) == 1 else "",
                payment_option.casefold(),
            )
            if identity in seen:
                continue
            seen.add(identity)
            scope = {
                "requested_payment_method": method,
                "question": segment.strip(),
            }
            if len(brand_mentions) == 1:
                scope["requested_product_brand"] = brand_mentions[0]
            if payment_option:
                scope["payment_option"] = payment_option
            output.append(scope)
    return [
        scope
        for scope in output
        if not any(
            set(_payment_scope_distinctive_tokens(scope["requested_payment_method"]))
            < set(
                _payment_scope_distinctive_tokens(
                    peer["requested_payment_method"]
                )
            )
            for peer in output
            if peer is not scope
        )
    ]


def _payment_method_case_from_proposal(
    proposed: str,
    candidate_tokens: Sequence[str],
) -> str:
    """Preserve model-proposed casing for a validated contiguous token span."""

    source_tokens = re.findall(r"[A-Za-z0-9]+", str(proposed or ""))
    normalized_source = [token.casefold() for token in source_tokens]
    normalized_candidate = [str(token).casefold() for token in candidate_tokens]
    width = len(normalized_candidate)
    for start in range(0, len(normalized_source) - width + 1):
        if normalized_source[start : start + width] == normalized_candidate:
            return " ".join(source_tokens[start : start + width])
    return " ".join(str(token) for token in candidate_tokens)


def _unique_explicit_installment_scope_for_method(
    proposed_method: Any,
    scopes: Sequence[Mapping[str, Any]],
) -> Dict[str, str]:
    """Return one customer-authored installment scope matching a tool method.

    Shared brand and Pay Now/Pay Later wording can govern multiple coordinated
    terms even when the model omits that scope from one sibling call. Runtime
    may fill the omission only when the numeric/provider method identifies one
    unambiguous customer-authored scope; repeated identical terms under
    different brands remain unresolved.
    """

    return _unique_explicit_installment_scope_for_call(
        proposed_method=proposed_method,
        scopes=scopes,
    )


def _unique_explicit_installment_scope_for_call(
    *,
    proposed_method: Any = "",
    proposed_brand: Any = "",
    proposed_option: Any = "",
    scopes: Sequence[Mapping[str, Any]],
) -> Dict[str, str]:
    """Resolve one customer-authored plan from all grounded per-call scope.

    Method tokens remain the strongest discriminator. When a model emits only
    a generic category such as ``installment``, a unique customer-backed brand
    and/or Pay Now/Pay Later option may still identify the exact authored plan.
    No dimension is inferred: every supplied brand or option must match, and
    multiple matching plans remain unresolved.
    """

    proposed_tokens = _payment_scope_distinctive_tokens(proposed_method)
    proposed_brand_key = _normalize_match_text(proposed_brand)
    proposed_option_key = _normalize_match_text(proposed_option)
    if not (proposed_tokens or proposed_brand_key or proposed_option_key):
        return {}
    matches: List[Dict[str, str]] = []
    for scope in scopes or []:
        if not isinstance(scope, Mapping):
            continue
        scope_tokens = _payment_scope_distinctive_tokens(
            scope.get("requested_payment_method")
        )
        if not scope_tokens:
            continue
        if proposed_tokens and not (
            _contains_ordered_local_token_span(scope_tokens, proposed_tokens)
            or _contains_ordered_local_token_span(proposed_tokens, scope_tokens)
        ):
            continue
        if proposed_brand_key and _normalize_match_text(
            scope.get("requested_product_brand")
        ) != proposed_brand_key:
            continue
        if proposed_option_key and _normalize_match_text(
            scope.get("payment_option")
        ) != proposed_option_key:
            continue
        matches.append(
            {
                str(key): str(value)
                for key, value in scope.items()
                if str(value or "").strip()
            }
        )
    return matches[0] if len(matches) == 1 else {}


def _contains_ordered_local_token_span(
    context_tokens: Sequence[str],
    proposed_tokens: Sequence[str],
    *,
    max_span: int = 12,
) -> bool:
    """Require proposed scope tokens in customer order and a bounded window."""

    if not context_tokens or not proposed_tokens:
        return False
    first = proposed_tokens[0]
    for start, token in enumerate(context_tokens):
        if token != first:
            continue
        if len(proposed_tokens) == 1:
            return True
        matched = 1
        end_limit = min(len(context_tokens), start + max_span)
        for index in range(start + 1, end_limit):
            if context_tokens[index] != proposed_tokens[matched]:
                continue
            matched += 1
            if matched == len(proposed_tokens):
                return True
    return False


def _authoritative_payment_query_signal_value(
    signals: Dict[str, Dict[str, Any]],
    key: str,
) -> str:
    """Return a customer-authored payment fact for read-only policy lookup.

    ``mentioned_unconfirmed`` is intentionally accepted here: it authorizes a
    lookup scope such as "If Pay Later", but it still cannot become checkout
    state or authorize an order action.
    """

    signal = signals.get(key) or {}
    source, status = signal_authority(signal)
    if source not in {"latest_user_message", "validated_choice_action"}:
        return ""
    if status in {"invalid", "rejected", "superseded"}:
        return ""
    value = _single_signal_value(signals, key)
    # Extraction uses "unknown" as a confidence placeholder.  It is not a
    # customer-provided payment term and must not become "unknown months" in
    # a policy lookup prompt.
    if " ".join(str(value or "").casefold().split()) in {
        "unknown",
        "none",
        "n/a",
        "not specified",
    }:
        return ""
    if key == "installment_months":
        # This typed field is numeric by contract. Generic phrases such as
        # "credit card installment" are extractor mistakes, not a term.
        match = re.fullmatch(
            r"\s*(\d{1,2})(?:\s*(?:months?|mos?))?\s*",
            str(value or ""),
            flags=re.IGNORECASE,
        )
        return match.group(1) if match else ""
    if key == "bank":
        normalized = " ".join(str(value or "").casefold().split())
        if any(
            token in normalized
            for token in (
                "installment",
                "credit card",
                "debit card",
                "payment method",
                "months",
            )
        ):
            return ""
    return value


def _latest_policy_query_signal_value(
    signals: Dict[str, Dict[str, Any]],
    key: str,
) -> str:
    """Return latest customer scope for read-only policy retrieval only."""

    signal = signals.get(key) or {}
    if str(signal.get("source") or "") != "latest_user_message":
        return ""
    if str(signal.get("status") or "").strip().lower() in {
        "invalid",
        "rejected",
        "superseded",
    }:
        return ""
    return _single_signal_value(signals, key)


def _payment_method_value_is_option_only(value: Any) -> bool:
    """Reject Pay Now/Pay Later labels misclassified as a payment method."""

    normalized = " ".join(str(value or "").casefold().split())
    return normalized in {
        "pay now",
        "pay later",
        "pay after service",
        "pay later / pay after service",
    }


def _authoritative_service_path_signal_value(
    signals: Dict[str, Dict[str, Any]],
) -> str:
    """Return customer-backed fulfillment context for a policy query."""

    signal = signals.get("service_type") or {}
    source, status = signal_authority(signal)
    if source not in {"latest_user_message", "validated_choice_action"}:
        return ""
    if status in {"invalid", "rejected", "superseded", "mentioned_unconfirmed"}:
        return ""
    return _single_signal_value(signals, "service_type")


def _lead_qualification_with_selected_product(
    lead_qualification: Dict[str, Any],
    *,
    selected_product_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Count a trusted selected product as lead support without inventing facts."""

    output = deepcopy(lead_qualification or {})
    if not selected_product_context:
        return output
    present = dict(output.get("present") or {})
    brand = _selected_product_brand(selected_product_context)
    tire_size = _selected_product_tire_size(selected_product_context)
    if brand and not present.get("tire_brand"):
        present["tire_brand"] = brand
        output["selected_product_brand_source"] = "trusted_selected_product_context"
    if tire_size and not present.get("tire_size"):
        present["tire_size"] = tire_size
        output["selected_product_tire_size_source"] = "trusted_selected_product_context"
    if present == dict((lead_qualification or {}).get("present") or {}):
        return output
    output["present"] = present
    support_count = sum(1 for key in ("tire_brand", "location", "contact_number") if present.get(key))
    output["support_count"] = support_count
    moderate_intent = bool(present.get("tire_size") and support_count >= 2)
    output["moderate_intent"] = moderate_intent
    output["lead_stage"] = "complete" if moderate_intent else "incomplete"
    output["status"] = output["lead_stage"]
    if moderate_intent:
        output["missing"] = []
        output["optional_missing"] = [key for key in ("tire_size", "tire_brand", "location", "contact_number") if not present.get(key)]
    else:
        missing = [
            item
            for item in output.get("missing") or []
            if not (item == "tire_brand" and present.get("tire_brand"))
            and not (item == "tire_size" and present.get("tire_size"))
        ]
        if not present.get("tire_size") and "tire_size" not in missing:
            missing.insert(0, "tire_size")
        if not present.get("tire_brand") and "tire_brand" not in missing:
            missing.append("tire_brand")
        output["missing"] = missing
    return output


def _selected_product_brand(selected_product_context: Dict[str, Any]) -> str:
    summary = selected_product_context.get("product_summary")
    if isinstance(summary, dict):
        brand = str(summary.get("brand") or "").strip()
        if brand:
            return brand
        sku_model = str(summary.get("sku_model") or "").strip()
        if sku_model:
            return sku_model.split()[0].upper()
    return ""


def _selected_product_tire_size(selected_product_context: Dict[str, Any]) -> str:
    summary = selected_product_context.get("product_summary")
    if not isinstance(summary, dict):
        return ""
    for key in ("tire_size", "size"):
        value = _canonical_tire_size_from_text(str(summary.get(key) or ""))
        if value:
            return value
    for key in ("sku_model", "model", "title"):
        value = _canonical_tire_size_from_text(str(summary.get(key) or ""))
        if value:
            return value
    return ""


def _canonical_tire_size_from_text(value: str) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    metric = re.search(
        r"\b(?P<section>\d{3})\s*/?\s*(?P<aspect>\d{2})\s*/?\s*R?\s*(?P<rim>\d{2})\b",
        text,
    )
    if metric:
        section = normalize_section_width(metric.group("section")) or metric.group("section")
        return f"{section}/{metric.group('aspect')}R{metric.group('rim')}"
    commercial = re.search(r"\b(?P<section>\d{3})\s*R\s*(?P<rim>\d{2})\s*C?\b", text)
    if commercial:
        section = normalize_section_width(commercial.group("section")) or commercial.group("section")
        suffix = "C" if text[commercial.end() - 1 : commercial.end()] == "C" else ""
        return f"{section}R{commercial.group('rim')}{suffix}"
    return ""


def _product_matches_service_context(
    product: Dict[str, Any],
    *,
    brand: str,
    section: str,
    aspect: str,
    rim: str,
    model: str,
) -> bool:
    if brand and _normalize_match_text(product.get("brand")) != brand:
        return False
    if section and _normalize_match_text(product.get("section_width")) != section:
        return False
    if aspect and _normalize_match_text(product.get("aspect_ratio")) != aspect:
        return False
    if rim and _normalize_match_text(product.get("rim_size")).lstrip("r") != rim:
        return False
    if model:
        haystack = _normalize_match_text(
            " ".join(
                str(product.get(key) or "")
                for key in ("pattern", "model", "name", "title", "sku_name", "slug")
            )
        )
        if model not in haystack:
            return False
    return True


def _product_tire_size_label(product: Dict[str, Any]) -> str:
    section = str(product.get("section_width") or "").strip()
    aspect = str(product.get("aspect_ratio") or "").strip()
    rim = str(product.get("rim_size") or "").strip()
    if section and aspect and rim:
        return f"{section}/{aspect}{rim if rim.upper().startswith('R') else 'R' + rim}"
    if section and rim:
        return f"{section}{rim if rim.upper().startswith('R') else 'R' + rim}"
    return " ".join(part for part in [section, aspect, rim] if part)


def _normalize_match_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _coerce_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _signals_by_key(signals: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    output: Dict[str, Dict[str, Any]] = {}
    for signal in signals or []:
        if not isinstance(signal, dict):
            continue
        key = str(signal.get("key") or "").strip()
        if key and key not in output:
            output[key] = signal
    return output


def _single_signal_value(signals: Dict[str, Dict[str, Any]], key: str) -> str:
    values = _signal_values(signals, key)
    return values[0] if len(values) == 1 else ""


def _location_signal_value(signals: Dict[str, Dict[str, Any]]) -> str:
    """Return the location display value without comma-splitting city/province labels."""

    signal = signals.get("location") or signals.get("delivery_address") or {}
    value = signal.get("value")
    if value in (None, ""):
        return ""
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item or "").strip()]
        return cleaned[0] if len(cleaned) == 1 else ""
    return str(value).strip()


def _signal_values(signals: Dict[str, Dict[str, Any]], key: str) -> List[str]:
    signal = signals.get(key) or {}
    value = signal.get("value")
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _tire_size_parts(value: str) -> Dict[str, str]:
    text = str(value or "").strip().upper().replace(" ", "")
    match = re.search(r"(?P<section>\d{3})/(?P<aspect>\d{2})R?(?P<rim>\d{2})", text)
    if match:
        section = normalize_section_width(match.group("section")) or match.group("section")
        return {
            "section_width": section,
            "aspect_ratio": match.group("aspect"),
            "rim_size": normalize_rim_size(f"R{match.group('rim')}", section_width=section) or f"R{match.group('rim')}",
        }
    commercial = re.search(r"(?P<section>\d{3})R(?P<rim>\d{2})C?", text)
    if commercial:
        section = normalize_section_width(commercial.group("section")) or commercial.group("section")
        return {
            "section_width": section,
            "aspect_ratio": "",
            "rim_size": normalize_rim_size(f"R{commercial.group('rim')}C", section_width=section)
            or f"R{commercial.group('rim')}C",
        }
    return {}


def _latest_user_content(messages: Sequence[Dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _extract_context_section(context: str, title: str) -> str:
    marker = f"## {title}"
    if marker not in context:
        return context
    after_marker = context.split(marker, 1)[1]
    section = after_marker.split("\n## ", 1)[0]
    lines = section.splitlines()
    content_lines = [line for line in lines if not line.startswith("How to use:")]
    return "\n".join(content_lines).strip()


def _safe_json_loads(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return {}
    try:
        loaded = json.loads(str(value))
    except Exception:
        return {"raw": value}
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _fallback_card_text(card: Dict[str, Any]) -> str:
    parts = [
        f"[{card.get('category')}]" if card.get("category") else "",
        str(card.get("sku_model") or "").strip(),
        str(card.get("deal_price_line") or "").strip(),
        str(card.get("promo_savings_line") or "").strip(),
        str(card.get("url") or "").strip(),
    ]
    return "\n".join(part for part in parts if part)


def _card_image_header(card: Dict[str, Any]) -> Dict[str, Any]:
    image = card.get("image") if isinstance(card.get("image"), dict) else {}
    url = str(
        image.get("url")
        or card.get("image_url")
        or card.get("thumbnail_url")
        or card.get("photo_url")
        or card.get("product_image_url")
        or ""
    ).strip()
    if not url:
        return {}
    image_ref = str(image.get("image_ref") or card.get("image_ref") or "").strip()
    if not image_ref:
        base_ref = str(card.get("card_ref") or card.get("item_ref") or card.get("slug") or "product").strip()
        image_ref = f"img_{base_ref}"
    alt = str(image.get("alt") or card.get("image_alt") or card.get("sku_model") or card.get("brand") or "Tire image").strip()
    return _compact_unit({"image_ref": image_ref, "url": url, "alt": alt})


def _presentation_surfaces_from_headers(
    *,
    surface_ref: Any,
    surface_type: str,
    headers: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    ref = str(surface_ref or "").strip()
    visible_headers = [header for header in headers or [] if isinstance(header, dict)]
    if not ref or not visible_headers:
        return []
    return [
        _compact_unit(
            {
                "surface_ref": ref,
                "type": surface_type,
                "render_policy": "runtime_inserts_exact_cards",
                "cards": visible_headers,
            }
        )
    ]


def _fitment_candidate_headers(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    headers: List[Dict[str, Any]] = []
    for index, candidate in enumerate(candidates or [], start=1):
        if not isinstance(candidate, dict):
            continue
        size = str(candidate.get("size") or "").strip()
        if not size:
            continue
        headers.append(
            _compact_unit(
                {
                    "candidate_ref": f"fitment_size_{index}",
                    "size": size,
                    "confidence": candidate.get("confidence"),
                    "source": candidate.get("source"),
                    "requires_customer_confirmation": True,
                    "matched_preferences": (
                        (candidate.get("size_preference_match") or {}).get("matched")
                        if isinstance(candidate.get("size_preference_match"), dict)
                        else []
                    ),
                }
            )
        )
    return headers


def _product_card_headers(
    cards: Sequence[Dict[str, Any]],
    *,
    include_warranty_context: bool = True,
) -> List[Dict[str, Any]]:
    headers: List[Dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        headers.append(
            _compact_unit(
                {
                    "card_ref": card.get("card_ref"),
                    "item_ref": card.get("item_ref"),
                    "product_id": card.get("product_id"),
                    "slug": card.get("slug"),
                    "brand": card.get("brand"),
                    "category": card.get("category"),
                    "sku_model": card.get("sku_model"),
                    "deal_price_line": card.get("deal_price_line"),
                    "promo_savings_line": card.get("promo_savings_line"),
                    "pricing_facts": card.get("pricing_facts"),
                    "warranty": (
                        card.get("warranty")
                        if include_warranty_context
                        else None
                    ),
                    "tire_protection_plan": (
                        card.get("tire_protection_plan")
                        if include_warranty_context
                        else None
                    ),
                    "quantity": card.get("quantity"),
                    "pricing_basis": card.get("pricing_basis"),
                    "why_shown": card.get("why_shown"),
                    "presentation_scope": card.get("presentation_scope"),
                    "image": _card_image_header(card),
                }
            )
        )
    return headers


def _product_presentation_units(cards: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    units: List[Dict[str, Any]] = []
    for header in _product_card_headers(cards):
        units.append(
            _compact_unit(
                {
                    "unit_type": "product_card",
                    "runtime_renders_body": True,
                    "card_ref": header.get("card_ref"),
                    "item_ref": header.get("item_ref"),
                    "product_id": header.get("product_id"),
                    "slug": header.get("slug"),
                    "brand": header.get("brand"),
                    "category": header.get("category"),
                    "title": header.get("sku_model"),
                    "price_line": header.get("deal_price_line"),
                    "promo_line": header.get("promo_savings_line"),
                    "pricing_facts": header.get("pricing_facts"),
                    "installment_text": header.get("installment_text"),
                    "warranty": header.get("warranty"),
                    "tire_protection_plan": header.get("tire_protection_plan"),
                    "quantity": header.get("quantity"),
                    "pricing_basis": header.get("pricing_basis"),
                    "why_shown": header.get("why_shown"),
                    "presentation_scope": header.get("presentation_scope"),
                }
            )
        )
    return units


def _selected_product_card_headers(cards: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    headers: List[Dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        headers.append(
            _compact_unit(
                {
                    "card_ref": card.get("card_ref"),
                    "item_ref": card.get("item_ref"),
                    "product_id": card.get("product_id"),
                    "slug": card.get("slug"),
                    "brand": card.get("brand"),
                    "category": card.get("category"),
                    "sku_model": card.get("sku_model"),
                    "customer_price_line": card.get("customer_price_line"),
                    "promo_line": card.get("promo_line"),
                    "pricing_facts": card.get("pricing_facts"),
                    "stock_status": card.get("stock_status"),
                    "installment_text": card.get("installment_text"),
                    "warranty": card.get("warranty"),
                    "tire_protection_plan": card.get("tire_protection_plan"),
                    "dot": card.get("dot"),
                    "origin": card.get("origin"),
                    "url": card.get("url"),
                    "image": _card_image_header(card),
                }
            )
        )
    return headers


def _selected_product_presentation_units(cards: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    units: List[Dict[str, Any]] = []
    for header in _selected_product_card_headers(cards):
        units.append(
            _compact_unit(
                {
                    "unit_type": "selected_product_card",
                    "runtime_renders_body": True,
                    "card_ref": header.get("card_ref"),
                    "item_ref": header.get("item_ref"),
                    "product_id": header.get("product_id"),
                    "slug": header.get("slug"),
                    "brand": header.get("brand"),
                    "category": header.get("category"),
                    "title": header.get("sku_model"),
                    "price_line": header.get("customer_price_line"),
                    "promo_line": header.get("promo_line"),
                    "pricing_facts": header.get("pricing_facts"),
                    "stock_status": header.get("stock_status"),
                    "installment_text": header.get("installment_text"),
                    "warranty": header.get("warranty"),
                    "tire_protection_plan": header.get("tire_protection_plan"),
                    "dot": header.get("dot"),
                    "origin": header.get("origin"),
                }
            )
        )
    return units


def _bucket_card_headers(cards: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    headers: List[Dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        headers.append(
            {
                "bucket_ref": card.get("bucket_ref"),
                "bucket": card.get("bucket"),
                "label": card.get("label"),
                "brands": card.get("brands"),
                "promo_brands": card.get("promo_brands"),
                "marker_legend_keys": card.get("marker_legend_keys"),
                "markers_by_brand": card.get("markers_by_brand"),
            }
        )
    return headers


def _brand_menu_choice_summary(full_result: Dict[str, Any], cards: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Expose compact brand-menu decision hooks without asking the model to rewrite cards."""

    bucket_summary = full_result.get("bucket_summary") if isinstance(full_result, dict) else {}
    categories: List[Dict[str, Any]] = []
    for header in _bucket_card_headers(cards):
        if not isinstance(header, dict):
            continue
        categories.append(
            _compact_unit(
                {
                    "label": header.get("label") or header.get("bucket"),
                    "brand_count": len(header.get("brands") or []),
                    "promo_brands": header.get("promo_brands") or [],
                    "marker_legend_keys": header.get("marker_legend_keys") or [],
                }
            )
        )
    return _compact_unit(
        {
            "total_brand_count": full_result.get("total_brand_count") if isinstance(full_result, dict) else None,
            "suggested_next_tool": full_result.get("suggested_next_tool") if isinstance(full_result, dict) else None,
            "requested_brand_status": full_result.get("requested_brand_status") if isinstance(full_result, dict) else None,
            "preferred_brand_status": full_result.get("preferred_brand_status") if isinstance(full_result, dict) else None,
            "bucket_summary": bucket_summary if isinstance(bucket_summary, dict) else {},
            "visible_categories": categories,
        }
    )


def _bucket_presentation_units(cards: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    units: List[Dict[str, Any]] = []
    for header in _bucket_card_headers(cards):
        units.append(
            _compact_unit(
                {
                    "unit_type": "brand_menu_card",
                    "runtime_renders_body": True,
                    "bucket_ref": header.get("bucket_ref"),
                    "category": header.get("bucket"),
                    "label": header.get("label"),
                    "brands": header.get("brands"),
                    "promo_brands": header.get("promo_brands"),
                    "marker_legend_keys": header.get("marker_legend_keys"),
                }
            )
        )
    return units


def _service_location_headers(
    locations: Sequence[Dict[str, Any]],
    *,
    partner_detail_level: str = "",
) -> List[Dict[str, Any]]:
    headers: List[Dict[str, Any]] = []
    reveal_names = _partner_detail_reveals_names(partner_detail_level)
    reveal_addresses = _partner_detail_reveals_addresses(partner_detail_level)
    for location in locations:
        if not isinstance(location, dict):
            continue
        header = {
            "installation_partner_ref": location.get("installation_partner_ref"),
            "service_location_ref": location.get("service_location_ref"),
            "branch_id": location.get("branch_id"),
            "area": location.get("area"),
            "city": location.get("city"),
            "municipality_city": location.get("municipality_city"),
            "service_types": location.get("service_types"),
            "same_day_possible": location.get("same_day_possible"),
        }
        if reveal_names:
            header["name"] = location.get("name")
        if reveal_addresses:
            header["address"] = location.get("address")
        headers.append(header)
    return headers


def _installation_partner_card_headers(
    cards: Sequence[Dict[str, Any]],
    *,
    partner_detail_level: str = "",
) -> List[Dict[str, Any]]:
    headers: List[Dict[str, Any]] = []
    reveal_names = _partner_detail_reveals_names(partner_detail_level)
    reveal_addresses = _partner_detail_reveals_addresses(partner_detail_level)
    for card in cards:
        if not isinstance(card, dict):
            continue
        header = {
            "card_ref": card.get("card_ref"),
            "installation_partner_ref": card.get("installation_partner_ref"),
            "service_location_ref": card.get("service_location_ref"),
            "display_name": card.get("display_name"),
            "municipality_city": card.get("municipality_city"),
            "partner_detail_level": card.get("partner_detail_level") or partner_detail_level,
            "partner_count": card.get("partner_count"),
            "slot_summary_lines": card.get("slot_summary_lines"),
            "slot_refs": card.get("slot_refs"),
        }
        if card.get("candidate_installation_partner_refs"):
            header["candidate_installation_partner_refs"] = card.get("candidate_installation_partner_refs")
        if card.get("candidate_service_location_refs"):
            header["candidate_service_location_refs"] = card.get("candidate_service_location_refs")
        if reveal_names:
            header["name"] = card.get("name")
        if reveal_addresses:
            header["address"] = card.get("address")
        headers.append(_compact_unit(header))
    return headers


def _installation_partner_presentation_units(
    cards: Sequence[Dict[str, Any]],
    *,
    partner_detail_level: str = "",
) -> List[Dict[str, Any]]:
    units: List[Dict[str, Any]] = []
    for header in _installation_partner_card_headers(cards, partner_detail_level=partner_detail_level):
        units.append(
            _compact_unit(
                {
                    "unit_type": "installation_partner_card",
                    "runtime_renders_body": True,
                    "card_ref": header.get("card_ref"),
                    "installation_partner_ref": header.get("installation_partner_ref"),
                    "service_location_ref": header.get("service_location_ref"),
                    "display_name": header.get("display_name"),
                    "name": header.get("name"),
                    "municipality_city": header.get("municipality_city"),
                    "partner_detail_level": header.get("partner_detail_level"),
                    "partner_count": header.get("partner_count"),
                    "slot_summary_lines": header.get("slot_summary_lines"),
                    "slot_refs": header.get("slot_refs"),
                }
            )
        )
    return units


def _partner_detail_reveals_names(detail_level: Any) -> bool:
    return str(detail_level or "").strip().lower() in {"name_only", "full_address"}


def _partner_detail_reveals_addresses(detail_level: Any) -> bool:
    return str(detail_level or "").strip().lower() == "full_address"


def _order_summary_presentation_units(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(result, dict) or not result.get("card_runtime_insert"):
        return []
    return [
        _compact_unit(
            {
                "unit_type": "order_summary",
                "runtime_renders_body": True,
                "order_summary_ref": result.get("order_summary_ref"),
                "status": result.get("status"),
                "rendered_as": "order_details_so_far"
                if result.get("status") == "incomplete"
                else "order_summary",
                "can_submit_order": result.get("can_submit_order"),
                "summary_preview": result.get("summary_preview") or {},
                "missing_fields": result.get("missing_fields") or [],
                "assumptions": result.get("assumptions") or [],
            }
        )
    ]


def _compact_unit(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def _compact_order_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        return {}
    if isinstance(payload.get("data"), dict) and isinstance(payload.get("newCartItems"), list):
        data = payload.get("data") or {}
        items = payload.get("newCartItems") or []
        item = items[0] if items and isinstance(items[0], dict) else {}
        selected_branch = data.get("selectedBranch") if isinstance(data.get("selectedBranch"), dict) else {}
        return _compact_unit(
            {
                "payload_shape": "gulong_order_api_v1",
                "product": _compact_unit(
                    {
                        "model": item.get("model"),
                        "tire_size": _join_tire_size_parts(
                            item.get("section_width"),
                            item.get("aspect_ratio"),
                            item.get("rim_size"),
                        ),
                        "quantity": item.get("quantity") or item.get("selected_quantity"),
                        "product_id": item.get("product_id") or item.get("id"),
                        "slug": item.get("slug"),
                    }
                ),
                "fulfillment": _compact_unit(
                    {
                        "transaction_type": (data.get("transaction_type_details") or {}).get("name")
                        if isinstance(data.get("transaction_type_details"), dict)
                        else data.get("transaction_type"),
                        "branch": selected_branch.get("name") or data.get("branch"),
                        "delivery_date": data.get("delivery_date"),
                        "delivery_time": data.get("delivery_time"),
                        "address": data.get("address_1"),
                    }
                ),
                "payment": _compact_unit(
                    {
                        "payment_option": (data.get("payment_option_details") or {}).get("name")
                        if isinstance(data.get("payment_option_details"), dict)
                        else data.get("payment_option"),
                        "payment_method": (data.get("payment_type_details") or {}).get("name")
                        if isinstance(data.get("payment_type_details"), dict)
                        else data.get("payment_type"),
                    }
                ),
                "totals": _compact_unit(
                    {
                        "total": data.get("total"),
                        "total_dp": data.get("total_dp"),
                        "delivery_fee": data.get("delivery_fee"),
                        "service_fee": data.get("service_fee"),
                    }
                ),
            }
        )
    product = payload.get("product") if isinstance(payload.get("product"), dict) else {}
    fulfillment = payload.get("fulfillment") if isinstance(payload.get("fulfillment"), dict) else {}
    payment = payload.get("payment") if isinstance(payload.get("payment"), dict) else {}
    totals = payload.get("totals") if isinstance(payload.get("totals"), dict) else {}
    return _compact_unit(
        {
            "payload_version": payload.get("payload_version"),
            "product": _compact_unit(
                {
                    "label": product.get("label"),
                    "tire_size": product.get("tire_size"),
                    "quantity": product.get("quantity"),
                    "product_id": product.get("product_id"),
                    "slug": product.get("slug"),
                    "item_ref": product.get("item_ref"),
                }
            ),
            "fulfillment": _compact_unit(
                {
                    "service_path": fulfillment.get("service_path"),
                    "location": fulfillment.get("location"),
                    "delivery_address": fulfillment.get("delivery_address"),
                    "installation_partner": fulfillment.get("installation_partner"),
                    "schedule": fulfillment.get("schedule"),
                }
            ),
            "payment": _compact_unit(
                {
                    "payment_option": payment.get("payment_option"),
                    "payment_method": payment.get("payment_method"),
                }
            ),
            "totals": _compact_unit(
                {
                    "order_total": totals.get("order_total_text"),
                    "amount_due_now": totals.get("amount_due_now_text"),
                    "balance_due": totals.get("balance_due_text"),
                }
            ),
        }
    )


def _slot_group_headers(
    groups: Sequence[Dict[str, Any]],
    *,
    partner_detail_level: str = "",
) -> List[Dict[str, Any]]:
    headers: List[Dict[str, Any]] = []
    reveal_names = _partner_detail_reveals_names(partner_detail_level)
    for group in groups[:4]:
        if not isinstance(group, dict):
            continue
        slots = [slot for slot in group.get("slots") or [] if isinstance(slot, dict)]
        header = {
            "installation_partner_ref": group.get("installation_partner_ref"),
            "service_location_ref": group.get("service_location_ref"),
            "branch_id": group.get("branch_id"),
            "municipality_city": group.get("municipality_city"),
            "status": group.get("status"),
            "gating_reason": group.get("gating_reason"),
            "earliest_allowed": group.get("earliest_allowed"),
            "selected_schedule_candidate": group.get("selected_schedule_candidate"),
            "slot_count": len(slots),
            "slots": slots[:3],
            "fallback_next_open_slot": group.get("fallback_next_open_slot"),
        }
        if reveal_names:
            header["name"] = group.get("name")
        headers.append(header)
    return headers


def _partner_lookup_schedule_semantics(result: Dict[str, Any]) -> Dict[str, Any]:
    """Expose that partner lookup found coverage but did not check slot availability."""

    if not isinstance(result, dict):
        return {}
    query_basis = result.get("query_basis") if isinstance(result.get("query_basis"), dict) else {}
    return _compact_unit(
        {
            "slot_availability_checked": False,
            "availability_status": "partner_lookup_only",
            "source_schedule_phrase": query_basis.get("source_schedule_phrase"),
            "requested_date": query_basis.get("preferred_date") or query_basis.get("preferred_date_start"),
            "allowed_claims": [
                "nearby installation partner coverage",
                "shown municipality/city area labels",
            ],
            "forbidden_claims": [
                "same-day availability",
                "exact date or time availability",
                "slot unavailable",
                "slot confirmed",
            ],
            "composer_grounding_note": (
                "This result did not check installation slots. Mention nearby partner coverage only; "
                "use find_installation_slots before saying whether a date/time is available or unavailable."
            ),
        }
    )


def _installation_slot_schedule_semantics(result: Dict[str, Any]) -> Dict[str, Any]:
    """Expose requested-vs-returned slot semantics for composer grounding."""

    if not isinstance(result, dict):
        return {}
    availability = result.get("availability") if isinstance(result.get("availability"), dict) else {}
    query_basis = result.get("query_basis") if isinstance(result.get("query_basis"), dict) else {}
    slot_search = query_basis.get("slot_search") if isinstance(query_basis.get("slot_search"), dict) else {}
    requested_date = (
        slot_search.get("preferred_date")
        or query_basis.get("preferred_date")
        or query_basis.get("preferred_date_start")
        or ""
    )
    source_phrase = query_basis.get("source_schedule_phrase") or slot_search.get("source_schedule_phrase") or ""
    slot_dates, fallback_dates = _installation_slot_result_dates(result.get("slot_groups") or [])
    availability_status = str(availability.get("availability_status") or "").strip()
    if str(result.get("status") or "").strip() == "not_applicable_for_delivery" or availability_status == "not_applicable_for_delivery":
        return _compact_unit(
            {
                "availability_status": "not_applicable_for_delivery",
                "source_schedule_phrase": source_phrase,
                "slot_availability_checked": False,
                "allowed_claims": [
                    "delivery fee/process should use order policy or quote tools",
                    "installation slots require a separate lookup with service_type=installation",
                ],
                "forbidden_claims": [
                    "no installation partner matched",
                    "delivery is unavailable",
                    "installation slot unavailable",
                    "slot confirmed",
                ],
                "composer_grounding_note": (
                    "This tool was not applicable because the request was delivery. Do not treat it as an "
                    "installation partner or slot miss. Use order policy/quote for delivery; run a separate "
                    "installation lookup with service_type=installation only when the conversation needs it."
                ),
            }
        )
    requested_date_text = str(requested_date or "").strip()
    requested_date_returned = bool(requested_date_text and requested_date_text in set(slot_dates))
    fallback_only = bool(
        availability_status == "next_slots_found"
        or (fallback_dates and not slot_dates)
        or (requested_date_text and slot_dates and not requested_date_returned)
        or (
            availability.get("same_day_requested") is True
            and availability.get("same_day_available") is False
            and not requested_date_returned
        )
    )
    return _compact_unit(
        {
            "availability_status": availability_status,
            "same_day_requested": availability.get("same_day_requested"),
            "same_day_available": availability.get("same_day_available"),
            "requested_date": requested_date_text,
            "source_schedule_phrase": source_phrase,
            "requested_date_returned": requested_date_returned,
            "fallback_or_next_available_only": bool(fallback_only),
            "visible_slot_dates": slot_dates[:6],
            "visible_fallback_dates": fallback_dates[:6],
            "earliest_available_slot": availability.get("earliest_available_slot"),
            "composer_grounding_note": (
                "The requested schedule did not have matching visible slots; describe shown rows as next available."
                if fallback_only
                else "Visible slots match the requested schedule."
                if requested_date_returned or availability_status == "slots_found"
                else ""
            ),
        }
    )


def _installation_slot_result_dates(groups: Sequence[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    slot_dates: List[str] = []
    fallback_dates: List[str] = []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        for slot in group.get("slots") or []:
            if isinstance(slot, dict):
                date = str(slot.get("date") or "").strip()
                if date and date not in slot_dates:
                    slot_dates.append(date)
        fallback = group.get("fallback_next_open_slot")
        if isinstance(fallback, dict):
            date = str(fallback.get("date") or "").strip()
            if date and date not in fallback_dates:
                fallback_dates.append(date)
    return slot_dates, fallback_dates


def _model_visible_service_status(result: Dict[str, Any]) -> Any:
    """Return model-facing service status without internal policy vocabulary."""

    raw_status = str((result or {}).get("status") or "").strip()
    coverage = (result or {}).get("coverage_assessment") if isinstance((result or {}).get("coverage_assessment"), dict) else {}
    service_area_status = str((coverage or {}).get("installation_service_area_status") or "").strip()
    if raw_status == "below_order_threshold" or service_area_status == "below_order_threshold_delivery_recommended":
        return "delivery_recommended"
    return (result or {}).get("status")


def _model_visible_service_claim_scope(
    result: Dict[str, Any],
    *,
    lookup_type: str,
) -> Dict[str, Any]:
    """Expose the exact area boundary of one service-provider lookup."""

    query_basis = (
        result.get("query_basis")
        if isinstance(result.get("query_basis"), dict)
        else {}
    )
    coverage = (
        result.get("coverage_assessment")
        if isinstance(result.get("coverage_assessment"), dict)
        else {}
    )
    queried_location = str(
        query_basis.get("customer_location_label")
        or coverage.get("customer_location_label")
        or query_basis.get("location")
        or ""
    ).strip()
    if (
        not queried_location
        or str(query_basis.get("location_input_status") or "").strip()
        == "generic_non_location"
    ):
        return {}
    return {
        "queried_location": queried_location,
        "lookup_type": lookup_type,
        "schedule_checked": lookup_type == "schedule_options",
        "other_mentioned_locations_verified": False,
        "scope_boundary": (
            "This result applies only to the queried location. Do not extend "
            "positive or negative availability to other customer-mentioned "
            "areas without separate provider results."
        ),
    }


def _model_visible_service_query_basis(query_basis: Any) -> Dict[str, Any]:
    if not isinstance(query_basis, dict):
        return {}
    allowed = {
        "service_location_ref",
        "installation_partner_ref",
        "location",
        "service_type",
        "preferred_date",
        "preferred_date_start",
        "preferred_date_end",
        "preferred_time_window",
        "source_schedule_phrase",
        "preferred_schedule_candidates",
        "request_time",
        "section_width",
        "aspect_ratio",
        "rim_size",
        "model_query",
        "raw_model_query",
        "tire_brand",
        "quantity",
        "customer_location_label",
        "customer_requested_walk_in",
        "location_input_status",
        "location_resolution",
        "service_type_was_defaulted",
        "partner_catalog_filter",
        "partner_detail_level",
    }
    output = {key: deepcopy(value) for key, value in query_basis.items() if key in allowed}
    if str(output.get("location_input_status") or "").strip() == "generic_non_location":
        output.pop("location", None)
        output.pop("customer_location_label", None)
        output.pop("location_resolution", None)
    partner_filter = output.get("partner_catalog_filter")
    if isinstance(partner_filter, dict):
        output["partner_catalog_filter"] = {
            key: deepcopy(value)
            for key, value in partner_filter.items()
            if key
            in {
                "requested",
                "status",
                "verified_by_filtered_partner_catalog",
                "compatibility_status",
                "filters",
            }
        }
    return output


def _model_visible_service_detail_disclosure(result: Dict[str, Any]) -> Dict[str, Any]:
    detail = deepcopy((result or {}).get("detail_disclosure") or {})
    if not isinstance(detail, dict):
        return {}
    query_basis = (result or {}).get("query_basis") if isinstance((result or {}).get("query_basis"), dict) else {}
    if str(query_basis.get("location_input_status") or "").strip() == "generic_non_location":
        detail.pop("customer_location_label", None)
    return detail


def _model_visible_service_note(result: Dict[str, Any], *, model_status: Any) -> Any:
    if str((result or {}).get("status") or "").strip() == "not_applicable_for_delivery":
        return (
            "This is not a failed installation lookup. Do not say no installation partner matched "
            "and do not say delivery is unavailable. Use order policy or quote tools for delivery "
            "fee/process. Installation slots require a separate lookup with service_type=installation."
        )
    if model_status == "delivery_recommended":
        return "Use customer_explanation_hints for the customer explanation."
    return (result or {}).get("note")


def _model_visible_coverage_assessment(coverage: Any, *, query_basis: Any = None) -> Dict[str, Any]:
    if not isinstance(coverage, dict):
        return {}
    invalid_location_input = (
        isinstance(query_basis, dict)
        and str(query_basis.get("location_input_status") or "").strip() == "generic_non_location"
    )
    service_area_status = str(coverage.get("installation_service_area_status") or "").strip()
    if service_area_status == "not_applicable_for_delivery":
        output = {
            "customer_location_label": coverage.get("customer_location_label"),
            "service_outcome": "not_applicable_for_delivery",
            "delivery_fallback_relevant": False,
            "customer_explanation": (
                "The slot tool was not applicable because the request was delivery, not installation."
            ),
        }
        if invalid_location_input:
            output.pop("customer_location_label", None)
        return output
    if service_area_status == "below_order_threshold_delivery_recommended":
        output = {
            "delivery_fallback_relevant": True,
            "customer_location_label": coverage.get("customer_location_label"),
            "service_outcome": "delivery_recommended_for_current_order_details",
            "customer_explanation": "Delivery is the practical option for the current validated order details.",
        }
        if invalid_location_input:
            output.pop("customer_location_label", None)
        return output
    output = {
        "presentable_partner_count": coverage.get("presentable_partner_count"),
        "location_precision": coverage.get("location_precision"),
        "presentation_confidence": coverage.get("presentation_confidence"),
        "clarification_recommended": coverage.get("clarification_recommended"),
        "clarification_reason": coverage.get("clarification_reason"),
        "delivery_fallback_relevant": coverage.get("delivery_fallback_relevant"),
        "customer_location_label": coverage.get("customer_location_label"),
        "match_source": coverage.get("match_source"),
        "location_resolution": coverage.get("location_resolution"),
    }
    if service_area_status:
        output["service_outcome"] = service_area_status
    if invalid_location_input:
        output.pop("customer_location_label", None)
    return {key: value for key, value in output.items() if value not in (None, "", [])}


def _compose_runtime_final_response(
    model_text: str,
    tool_results: Sequence[Dict[str, Any]],
    *,
    current_user_message: str = "",
    recent_turns: Optional[Sequence[Dict[str, str]]] = None,
    active_working_memory: str = "",
    allow_first_turn_welcome: bool = False,
    first_turn_intro_mode: str = "",
    include_product_inclusions: bool = True,
    product_observation_store: Optional[ProductObservationStore] = None,
    pricing_repair_callback: Optional[Callable[[str, Dict[str, Any], Sequence[float]], str]] = None,
    guard_events: Optional[List[Dict[str, Any]]] = None,
    selected_product_context: Optional[Dict[str, Any]] = None,
    order_readiness: Optional[Dict[str, Any]] = None,
    background_signals: Optional[Sequence[Dict[str, Any]]] = None,
    customer_turn_plan: Optional[Dict[str, Any]] = None,
    model_composed_complete_turn: bool = False,
    suppress_runtime_surfaces: bool = False,
) -> str:
    intro_mode = _normalize_first_turn_intro_mode(first_turn_intro_mode)
    if not intro_mode and allow_first_turn_welcome:
        intro_mode = FIRST_TURN_INTRO_MODE_FULL
    structured_units = _parse_structured_response_units(model_text)
    active_surfaces = _collect_runtime_presentation_surfaces(tool_results)
    if structured_units is not None:
        structured_units = _guard_unsupported_visible_product_pricing_units(
            structured_units,
            product_observation_store=product_observation_store,
            tool_results=tool_results,
            pricing_repair_callback=pricing_repair_callback,
            guard_events=guard_events,
        )
        rendered = _render_structured_response_units(
            structured_units,
            active_surfaces,
            strip_leading_greeting=False,
            include_product_inclusions=include_product_inclusions,
            guard_events=guard_events,
            render_runtime_surfaces=not suppress_runtime_surfaces,
            append_unrendered_surfaces=not model_composed_complete_turn,
        )
        if rendered.strip():
            model_opening_present = _structured_response_starts_with_nonempty_text(
                structured_units
            )
            if suppress_runtime_surfaces:
                return _maybe_prepend_first_turn_welcome(
                    rendered.strip(),
                    recent_turns=recent_turns or [],
                    active_working_memory=active_working_memory,
                    intro_mode=intro_mode,
                    model_opening_present=model_opening_present,
                    guard_events=guard_events,
                )
            return _maybe_prepend_first_turn_welcome(
                rendered.strip(),
                recent_turns=recent_turns or [],
                active_working_memory=active_working_memory,
                intro_mode=intro_mode,
                model_opening_present=model_opening_present,
                guard_events=guard_events,
            )
    recovery_units = _recover_response_units_from_plain_model_text(model_text)
    recovery_units = _guard_unsupported_visible_product_pricing_units(
        recovery_units,
        product_observation_store=product_observation_store,
        tool_results=tool_results,
        pricing_repair_callback=pricing_repair_callback,
        guard_events=guard_events,
    )
    recovered_response = _render_structured_response_units(
        recovery_units,
        active_surfaces,
        strip_leading_greeting=False,
        include_product_inclusions=include_product_inclusions,
        guard_events=guard_events,
        render_runtime_surfaces=not suppress_runtime_surfaces,
    )
    _append_response_guard_event(
        guard_events,
        type="response_unit_recovery",
        reason=(
            "structured_units_rendered_empty"
            if structured_units is not None
            else "no_structured_response_units"
        ),
        plain_text_recovered=bool(recovery_units),
        surface_count=len(active_surfaces),
    )
    return _maybe_prepend_first_turn_welcome(
        recovered_response,
        recent_turns=recent_turns or [],
        active_working_memory=active_working_memory,
        intro_mode=intro_mode,
        guard_events=guard_events,
    )


def _recover_response_units_from_plain_model_text(model_text: str) -> List[Dict[str, Any]]:
    """Recover only safe model prose; the normal renderer appends trusted surfaces.

    This is a format-failure path, not a second conversation architecture. It
    does not classify a stage, split or rewrite a CTA, or synthesize visible
    copy. JSON-like and internal runtime output fail closed.
    """

    text = str(model_text or "").strip()
    if not text or text.startswith(("{", "[", "```")):
        return []
    lowered = text.casefold()
    if (
        len(text) > 3000
        or _has_internal_runtime_leakage(text)
        or _installation_partner_intro_has_renderer_owned_details(lowered)
        or _has_unvalidated_service_action_claim(lowered)
        or _has_customer_unsafe_service_policy_term(lowered)
    ):
        return []
    return [{"type": "text", "content": {"text": text}}]


def _final_composer_surface_authorization(
    presentation_surfaces: Sequence[Dict[str, Any]],
    *,
    customer_turn_plan: Mapping[str, Any],
) -> Dict[str, Any]:
    """Expose renderable facts without prescribing a sales stage or CTA.

    A surface is deterministic evidence: it says which exact controls can be
    rendered and what decision family they belong to.  The composer decides
    whether a surface is useful now, where it belongs in the response, and
    which natural next step follows.  Runtime validation still rejects unknown
    refs, duplicate surfaces, and more than one interactive decision layer.
    """

    planned_by_ref = {
        str(surface.get("surface_ref") or "").strip(): surface
        for surface in customer_turn_plan.get("available_surfaces") or []
        if isinstance(surface, Mapping)
        and str(surface.get("surface_ref") or "").strip()
    }
    available: List[Dict[str, Any]] = []
    for surface in presentation_surfaces or []:
        surface_ref = str(surface.get("surface_ref") or "").strip()
        if not surface_ref:
            continue
        planned = planned_by_ref.get(surface_ref) or {}
        available.append(
            _compact_unit(
                {
                    "surface_ref": surface_ref,
                    "surface_type": surface.get("type"),
                    "domain": surface.get("domain"),
                    "decision_layer": (
                        planned.get("decision_layer")
                        or _surface_decision_layer(surface)
                    ),
                    "visible_labels": (
                        planned.get("visible_labels")
                        or surface.get("visible_labels")
                    ),
                    "visible_count": (
                        planned.get("visible_count")
                        or len(surface.get("cards") or [])
                    ),
                    "supporting_context": bool(
                        surface.get("supporting_context")
                    ),
                    "required": bool(planned.get("required")),
                    "response_role": str(
                        planned.get("response_role") or "direct_answer"
                    ),
                    "renderer_owns_next_input": bool(
                        surface.get("renderer_owns_next_input")
                    ),
                }
            )
        )
    return {
        "available_surfaces": available,
        "selection_policy": (
            "Render every required surface exactly once. Optional surfaces may be "
            "omitted and must not compete with a required answer. Use at most one "
            "optional interactive decision layer; multiple required direct-answer "
            "surfaces may coexist when they cover independent grounded requests. "
            "A supporting_replacement surface accompanies its direct answer without "
            "a separate caption, explanation, or CTA. Do not refer to a surface as "
            "shown unless its render_surface unit is included."
        ),
        "authority": (
            "Runtime owns exact surface content and validates refs. The model "
            "owns conversational sequencing, transitions, and the next CTA."
        ),
    }


_PESO_AMOUNT_RE = re.compile(
    r"PHP\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)",
    flags=re.IGNORECASE,
)


def _guard_unsupported_visible_product_pricing_units(
    response_units: Sequence[Dict[str, Any]],
    *,
    product_observation_store: Optional[ProductObservationStore],
    tool_results: Sequence[Dict[str, Any]] = (),
    pricing_repair_callback: Optional[
        Callable[[str, Dict[str, Any], Sequence[float]], str]
    ] = None,
    guard_events: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Audit model-authored pricing without re-auditing renderer-owned surfaces."""

    guarded_units: List[Dict[str, Any]] = []
    for unit in response_units or []:
        guarded_unit = deepcopy(unit)
        if str(guarded_unit.get("type") or "").strip().lower() == "text":
            content = (
                guarded_unit.get("content")
                if isinstance(guarded_unit.get("content"), dict)
                else {}
            )
            content = deepcopy(content)
            content["text"] = _guard_unsupported_visible_product_pricing(
                str(content.get("text") or ""),
                product_observation_store=product_observation_store,
                tool_results=tool_results,
                pricing_repair_callback=pricing_repair_callback,
                guard_events=guard_events,
            )
            guarded_unit["content"] = content
        guarded_units.append(guarded_unit)
    return guarded_units


def _guard_unsupported_visible_product_pricing(
    response_text: str,
    *,
    product_observation_store: Optional[ProductObservationStore],
    tool_results: Sequence[Dict[str, Any]] = (),
    pricing_repair_callback: Optional[Callable[[str, Dict[str, Any], Sequence[float]], str]] = None,
    guard_events: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Repair unsupported payable arithmetic against the latest card total."""

    text = str(response_text or "").strip()
    if not text or product_observation_store is None:
        return text
    if _same_turn_tool_results_can_introduce_amounts(tool_results):
        return text
    observation = product_observation_store.latest()
    if observation is None or not observation.product_cards:
        return text
    amount_values = _peso_amounts_from_text(text)
    if not amount_values:
        return text
    authoritative_cards = _cards_with_pricing_facts(observation.product_cards)
    if not authoritative_cards:
        return text
    authorized_amounts = _authorized_pricing_amounts(authoritative_cards)
    unsupported = [
        amount
        for amount in amount_values
        if not _amount_matches_any(amount, authorized_amounts)
    ]
    if not unsupported:
        return text
    if not _looks_like_payable_total_claim(text):
        return text
    card = _best_pricing_card_for_response(text, authoritative_cards)
    facts = card.get("pricing_facts") if isinstance(card.get("pricing_facts"), dict) else {}
    payable = _coerce_amount(facts.get("payable_total"))
    if payable is None:
        return text
    if pricing_repair_callback is not None:
        _append_response_guard_event(
            guard_events,
            type="unsupported_product_pricing_repair_requested",
            reason="response_introduced_payable_amount_not_in_trusted_card_pricing_facts",
            unsupported_amounts=[round(amount, 2) for amount in unsupported],
            authoritative_payable_total=round(payable, 2),
            presentation_ref=observation.presentation_ref,
            card_ref=card.get("card_ref"),
            item_ref=card.get("item_ref"),
        )
        try:
            repaired = str(pricing_repair_callback(text, card, unsupported) or "").strip()
        except Exception as exc:  # pragma: no cover - callback failures are integration-side.
            repaired = ""
            _append_response_guard_event(
                guard_events,
                type="unsupported_product_pricing_model_repair_failed",
                reason="repair_callback_failed",
                error=str(exc),
                presentation_ref=observation.presentation_ref,
                card_ref=card.get("card_ref"),
                item_ref=card.get("item_ref"),
            )
        if repaired:
            repaired_amounts = _peso_amounts_from_text(repaired)
            repaired_unsupported = [
                amount
                for amount in repaired_amounts
                if not _amount_matches_any(amount, authorized_amounts)
            ]
            if not repaired_unsupported:
                _append_response_guard_event(
                    guard_events,
                    type="unsupported_product_pricing_model_repaired",
                    reason="model_repair_output_passed_pricing_amount_validation",
                    used_amounts=[round(amount, 2) for amount in repaired_amounts],
                    presentation_ref=observation.presentation_ref,
                    card_ref=card.get("card_ref"),
                    item_ref=card.get("item_ref"),
                )
                return repaired
            _append_response_guard_event(
                guard_events,
                type="unsupported_product_pricing_model_repair_rejected",
                reason="model_repair_output_still_contains_unsupported_pricing",
                unsupported_amounts=[round(amount, 2) for amount in repaired_unsupported],
                presentation_ref=observation.presentation_ref,
                card_ref=card.get("card_ref"),
                item_ref=card.get("item_ref"),
            )
    replacement = _authoritative_card_pricing_clarification(card)
    _append_response_guard_event(
        guard_events,
        type="unsupported_product_pricing_safe_fallback_used",
        reason="model_repair_unavailable_or_failed_validation",
        unsupported_amounts=[round(amount, 2) for amount in unsupported],
        authoritative_payable_total=round(payable, 2),
        presentation_ref=observation.presentation_ref,
        card_ref=card.get("card_ref"),
        item_ref=card.get("item_ref"),
    )
    return replacement


def _same_turn_tool_results_can_introduce_amounts(tool_results: Sequence[Dict[str, Any]]) -> bool:
    amount_grounding_tools = {
        "build_order_summary",
        "calculate_order_quote",
        "prepare_payment_request",
        "get_order_details",
        "submit_order",
        "answer_order_faq",
        "answer_policy_faq",
    }
    for result in tool_results or []:
        if not isinstance(result, dict):
            continue
        name = str(result.get("name") or "").strip()
        if name in amount_grounding_tools:
            return True
    return False


def _cards_with_pricing_facts(cards: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output = []
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        facts = card.get("pricing_facts") if isinstance(card.get("pricing_facts"), dict) else {}
        if _coerce_amount(facts.get("payable_total")) is not None:
            output.append(card)
    return output


def _authorized_pricing_amounts(cards: Sequence[Dict[str, Any]]) -> List[float]:
    amounts: List[float] = []
    for card in cards or []:
        facts = card.get("pricing_facts") if isinstance(card.get("pricing_facts"), dict) else {}
        for key in [
            "unit_price",
            "payable_total",
            "pre_discount_total",
            "total_savings",
            "sale_discount_per_tire",
        ]:
            amount = _coerce_amount(facts.get(key))
            if amount is not None:
                amounts.append(amount)
    return amounts


def _peso_amounts_from_text(text: str) -> List[float]:
    amounts: List[float] = []
    for match in _PESO_AMOUNT_RE.finditer(str(text or "")):
        amount = _coerce_amount(match.group(1))
        if amount is not None:
            amounts.append(amount)
    return amounts


def _coerce_amount(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return round(float(str(value).replace(",", "")), 2)
    except Exception:
        return None


def _amount_matches_any(amount: float, candidates: Sequence[float]) -> bool:
    return any(abs(float(amount) - float(candidate)) < 0.01 for candidate in candidates)


def _looks_like_payable_total_claim(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        token in lowered
        for token in [
            "babayaran",
            "payable",
            "pay ",
            "payment",
            "total",
            "final price",
            "final amount",
            "amount due",
            "presyo",
        ]
    )


def _best_pricing_card_for_response(text: str, cards: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    lowered = str(text or "").lower()
    for card in cards or []:
        candidates = [
            card.get("sku_model"),
            card.get("brand"),
            card.get("slug"),
            card.get("tire_size"),
        ]
        if any(str(value or "").strip() and str(value).lower() in lowered for value in candidates):
            return card
    return dict(cards[0] or {})


def _authoritative_card_pricing_clarification(card: Dict[str, Any]) -> str:
    facts = card.get("pricing_facts") if isinstance(card.get("pricing_facts"), dict) else {}
    sku_model = str(card.get("sku_model") or "shown product").strip()
    quantity = facts.get("quantity") or card.get("quantity") or 4
    payable_text = str(facts.get("payable_total_text") or "").strip()
    if not payable_text:
        payable = _coerce_amount(facts.get("payable_total"))
        payable_text = f"PHP {payable:,.2f} for {quantity} tires" if payable is not None else ""
    savings_text = str(facts.get("total_savings_text") or "").strip()
    lines = [
        f"For {sku_model}, {payable_text} na po ang discounted total for {quantity} tires.".strip(),
    ]
    if savings_text:
        lines.append(f"Hindi na po ibabawas ulit yung {savings_text}; included na po yung savings sa total na iyon.")
    else:
        lines.append("Hindi na po ibabawas ulit yung displayed savings; included na po iyon sa shown total.")
    return "\n\n".join(line for line in lines if line)


_UNCLEAR_GENERIC_CLARIFICATION_RE = re.compile(
    r"\bpara\s+saan\s+po\s+"
    r"(?:[^\w\s.!?]*(?:yan|yun|iyon|ito)[^\w\s.!?]*|(?:(?:ang|yung|yong)\s+)?(?:location|price|presyo))"
    r"[^.!?\n]*(?:[.!?]+|$)",
    flags=re.IGNORECASE,
)
_UNCLEAR_GENERIC_PALA_PREFIX_RE = re.compile(
    r"\bpara\s+saan\s+po\s+pala\s*,?\s*",
    flags=re.IGNORECASE,
)
_UNCLEAR_PRICE_SIZE_PREFIX_RE = re.compile(
    r"^\s*para\s+sa\s+(anong\s+tire\s+size\b)",
    flags=re.IGNORECASE,
)


def _maybe_prepend_first_turn_welcome(
    response_text: str,
    *,
    recent_turns: Sequence[Dict[str, Any]],
    active_working_memory: str = "",
    intro_mode: str = "",
    model_opening_present: Optional[bool] = None,
    guard_events: Optional[List[Dict[str, Any]]] = None,
) -> str:
    response = str(response_text or "").strip()
    mode = _normalize_first_turn_intro_mode(intro_mode)
    if not mode:
        return response
    if not _should_insert_first_turn_welcome(
        recent_turns=recent_turns,
        active_working_memory=active_working_memory,
    ):
        return response
    opening_present = (
        bool(response)
        if model_opening_present is None
        else bool(model_opening_present and response)
    )
    if mode == FIRST_TURN_INTRO_MODE_WELCOME_ONLY and opening_present:
        _append_response_guard_event(
            guard_events,
            type=MODEL_COMPOSED_FIRST_TURN_OPENING_EVENT_TYPE,
            reason="model_owned_first_turn_text_preserved",
            intro_mode=mode,
        )
        return response
    if mode == FIRST_TURN_INTRO_MODE_WELCOME_ONLY:
        # A substantive first turn is model-owned. Missing model prose is an
        # output failure for the normal retry/finalization path, not authority
        # for the runtime to substitute a generic scripted sales response.
        return response
    if _response_has_welcome_spiel(response):
        return response
    _append_response_guard_event(
        guard_events,
        type=WELCOME_SPIEL_GUARD_EVENT_TYPE,
        reason=(
            "model_opening_missing_fixed_fallback_used"
            if mode == FIRST_TURN_INTRO_MODE_WELCOME_ONLY
            else "first_turn_intro_applicable_no_prior_outbound"
        ),
        intro_mode=mode,
    )
    intro_text = _first_turn_intro_text_for_mode(mode)
    return f"{intro_text}\n\n{response}".strip() if response else intro_text


def _normalize_first_turn_intro_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode in {FIRST_TURN_INTRO_MODE_FULL, "full", "intro", "intake"}:
        return FIRST_TURN_INTRO_MODE_FULL
    if mode in {FIRST_TURN_INTRO_MODE_WELCOME_ONLY, "welcome", "welcome_spiel"}:
        return FIRST_TURN_INTRO_MODE_WELCOME_ONLY
    return ""


def _first_turn_intro_text_for_mode(mode: str) -> str:
    normalized = _normalize_first_turn_intro_mode(mode)
    if normalized == FIRST_TURN_INTRO_MODE_WELCOME_ONLY:
        return RUNTIME_V7_WELCOME_SPIEL_TEXT
    if normalized == FIRST_TURN_INTRO_MODE_FULL:
        return RUNTIME_V7_FIRST_TURN_INTRO_TEXT
    return ""


def _first_turn_intro_context_for_model(mode: str) -> Dict[str, Any]:
    normalized = _normalize_first_turn_intro_mode(mode)
    if not normalized:
        return {}
    if normalized == FIRST_TURN_INTRO_MODE_FULL:
        summary = "three bubbles: Welcome to Gulong.ph, lead info request, tire-size guide"
        instruction = (
            "Runtime will prepend the full first-turn intro. Do not open with another greeting such as Hi po, Hello, "
            "Good day, or Welcome to Gulong.ph. Do not repeat the info-request or tire-size guide; write only the "
            "continuation after those bubbles. If the customer only greeted, start with a non-greeting action phrase "
            "such as Send niyo lang po or Pwede niyo pong."
        )
    else:
        summary = "one model-composed opening bubble before any guided or deterministic surface"
        instruction = (
            "Compose the complete first customer-facing text bubble yourself. Open naturally for the customer's "
            "language and context, identify Gulong.ph, acknowledge or directly answer the request, and place that "
            "complete text unit before any render_surface. Vary the greeting and phrasing when useful; do not copy a "
            "fixed script or write a generic lead-in. If this is a low-information shopping turn with no usable tire, "
            "vehicle, brand, preference, or location detail and no specific service, policy, business, or order "
            "request, acknowledge the exact entry goal and ask one connected discovery question, commonly tire "
            "size or vehicle. A supplied reviewed promo catalog may accompany a generic availability, ambiguous-price, "
            "or tire-help entry when useful, but it must not replace that answer or discovery step. For a bare greeting, "
            "use a compact welcome plus one discovery question instead of forcing a gallery. If no useful "
            "surface is supplied or it was already shown recently, do not mention or promise current promo cards; "
            "ask the one most useful detail directly. Do not ask permission to "
            "perform a safe read-only check or show an available surface. If the customer provided meaningful details "
            "or asked a specific question, answer and use those details "
            "instead of restarting generic intake. The runtime will not synthesize a replacement opening."
        )
    return {
        "runtime_will_prepend": normalized == FIRST_TURN_INTRO_MODE_FULL,
        "model_will_compose": normalized == FIRST_TURN_INTRO_MODE_WELCOME_ONLY,
        "opening_required": True,
        "mode": normalized,
        "composition": (
            "model_composes_complete_first_text_before_surfaces"
            if normalized == FIRST_TURN_INTRO_MODE_WELCOME_ONLY
            else "prepend_separate_full_intake_bubbles"
        ),
        "customer_visible_intro_summary": summary,
        "model_instruction": instruction,
    }


def _first_turn_intro_mode_from_guard_events(guard_events: Sequence[Dict[str, Any]]) -> str:
    for event in guard_events or []:
        if not isinstance(event, dict) or event.get("type") not in {
            WELCOME_SPIEL_GUARD_EVENT_TYPE,
            MODEL_COMPOSED_FIRST_TURN_OPENING_EVENT_TYPE,
        }:
            continue
        mode = _normalize_first_turn_intro_mode(event.get("intro_mode"))
        if mode:
            return mode
        return FIRST_TURN_INTRO_MODE_FULL
    return ""


def _should_insert_first_turn_welcome(
    *,
    recent_turns: Sequence[Dict[str, Any]],
    active_working_memory: str = "",
) -> bool:
    if str(active_working_memory or "").strip():
        return False
    return not _has_prior_agent_chatbot_or_automation_turn(recent_turns)


def _has_prior_agent_chatbot_or_automation_turn(recent_turns: Sequence[Dict[str, Any]]) -> bool:
    outbound_roles = {
        "assistant",
        "ai",
        "bot",
        "chatbot",
        "human_agent",
        "agent",
        "staff",
        "admin",
        "page_admin",
        "cs",
    }
    for turn in recent_turns or []:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or turn.get("sender_role") or turn.get("type") or "").strip().lower()
        message_kind = str(turn.get("message_kind") or "").strip().lower()
        message_type = str(turn.get("type") or turn.get("message_type") or "").strip().lower()
        if role in outbound_roles:
            return True
        if message_kind in {"manychat_automation", "automation", "automated"}:
            return True
        if bool(turn.get("is_automated")):
            return True
        if message_type.startswith("msgout_default"):
            return True
    return False


def _response_has_welcome_spiel(text: str) -> bool:
    normalized = " ".join(str(text or "").lower().split())
    return "welcome to gulong.ph" in normalized or "welcome to gulong ph" in normalized


def _structured_response_starts_with_nonempty_text(
    units: Sequence[Dict[str, Any]],
) -> bool:
    """Return whether structured output begins with customer-facing text."""

    first_unit = next(
        (unit for unit in units or [] if isinstance(unit, dict)),
        {},
    )
    return bool(
        str(first_unit.get("type") or "") == "text"
        and str((first_unit.get("content") or {}).get("text") or "").strip()
    )


def _collect_runtime_presentation_surfaces(
    tool_results: Sequence[Dict[str, Any]],
) -> List[Tuple[str, Dict[str, Any]]]:
    product_surfaces: List[Tuple[str, Dict[str, Any]]] = []
    service_surface: Dict[str, Any] = {}
    order_surface: Dict[str, Any] = {}
    payment_surface: Dict[str, Any] = {}
    promo_surfaces: List[Tuple[str, Dict[str, Any]]] = []
    for order, tool_result in enumerate(tool_results or []):
        full_result = tool_result.get("full_result") or {}
        if tool_result.get("name") == "present_promo_gallery":
            cards = [card for card in full_result.get("cards") or [] if isinstance(card, dict)]
            if cards and full_result.get("card_runtime_insert"):
                promo_surfaces.append(
                    (
                        "promo",
                        {
                            "order": order,
                            "tool": "present_promo_gallery",
                            "supporting_context": (
                                str(tool_result.get("completion_source") or "")
                                == "product_tpp_supporting_surface_policy"
                            ),
                            "surface_ref": _runtime_surface_ref("promo", tool_result, full_result, order),
                            "cards": cards,
                            "full_result": full_result,
                        },
                    )
                )
            continue
        if tool_result.get("name") == "extract_compatible_fitment":
            candidates = [row for row in full_result.get("candidate_sizes") or [] if isinstance(row, dict)]
            if candidates and full_result.get("card_runtime_insert"):
                product_surfaces.append(
                    (
                        "fitment",
                        {
                            "order": order,
                            "tool": "extract_compatible_fitment",
                            "surface_ref": _runtime_surface_ref("fitment", tool_result, full_result, order),
                            "cards": _fitment_candidate_headers(candidates),
                            "full_result": full_result,
                        },
                    )
                )
                continue
        if (
            tool_result.get("name") == "build_order_summary"
            and full_result.get("status") in {"ready", "incomplete"}
            and full_result.get("card_runtime_insert")
        ):
            order_surface = {
                "order": order,
                "tool": "build_order_summary",
                "surface_ref": _runtime_surface_ref("order", tool_result, full_result, order),
                "full_result": full_result if isinstance(full_result, dict) else {},
            }
            continue
        if tool_result.get("name") == "prepare_payment_request" and full_result.get("payment_instruction_block"):
            payment_surface = {
                "order": order,
                "tool": "prepare_payment_request",
                "surface_ref": _runtime_surface_ref("payment", tool_result, full_result, order),
                "full_result": full_result if isinstance(full_result, dict) else {},
            }
            continue
        if tool_result.get("name") == "get_product_details":
            cards = [card for card in full_result.get("selected_product_cards") or [] if isinstance(card, dict)]
            if cards and full_result.get("card_runtime_insert"):
                rendered_cards = _latest_selected_product_cards(tool_results, round_value=tool_result.get("round")) or cards
                product_surfaces.append(
                    (
                        "product",
                        {
                            "order": order,
                            "tool": "get_product_details",
                            "surface_ref": _runtime_surface_ref("product", tool_result, full_result, order),
                            "surface_dedupe_key": _product_surface_dedupe_key(rendered_cards),
                            "cards": rendered_cards,
                            "tool_args": dict(tool_result.get("args") or {}),
                            "full_result": full_result,
                        },
                    )
                )
                continue
        if tool_result.get("name") == "product_search":
            cards = [card for card in full_result.get("product_cards") or [] if isinstance(card, dict)]
            if cards:
                product_surfaces.append(
                    (
                        "product",
                        {
                            "order": order,
                            "tool": "product_search",
                            "surface_ref": _runtime_surface_ref("product", tool_result, full_result, order),
                            "surface_dedupe_key": _product_surface_dedupe_key(cards),
                            "cards": cards,
                            "tool_args": dict(tool_result.get("args") or {}),
                            "full_result": full_result,
                        },
                    )
                )
                continue
        if tool_result.get("name") == "discover_brand_buckets":
            cards = [card for card in full_result.get("bucket_cards") or [] if isinstance(card, dict)]
            if cards:
                product_surfaces.append(
                    (
                        "product",
                        {
                            "order": order,
                            "tool": "discover_brand_buckets",
                            "surface_ref": _runtime_surface_ref("product", tool_result, full_result, order),
                            "surface_dedupe_key": _product_surface_dedupe_key(cards),
                            "cards": cards,
                            "full_result": full_result,
                        },
                    )
                )
                continue
        tool_name = str(tool_result.get("name") or "")
        if tool_name in {
            "find_installation_partners",
            "find_service_locations",
            "find_installation_slots",
        }:
            cards = [
                card for card in full_result.get("installation_partner_cards") or [] if isinstance(card, dict)
            ]
            status = str(full_result.get("status") or "").strip()
            if status in {"no_match", "below_order_threshold"} or (
                tool_name == "find_installation_slots"
                and status == "no_service_location"
                and isinstance(full_result.get("coverage_assessment"), dict)
                and full_result.get("coverage_assessment")
            ):
                service_surface = {
                    "order": order,
                    "tool": "find_installation_partners_no_match",
                    "surface_ref": _runtime_surface_ref("service", tool_result, full_result, order),
                    "cards": [],
                    "full_result": full_result if isinstance(full_result, dict) else {},
                }
                continue
            if cards:
                if tool_name == "find_installation_slots":
                    cards = _latest_installation_slot_cards(
                        tool_results,
                        round_value=tool_result.get("round"),
                    )
                elif _should_suppress_anonymous_partner_cards(tool_name, full_result, cards):
                    service_surface = {
                        "order": order,
                        "tool": "find_installation_partners_summary",
                        "surface_ref": _runtime_surface_ref(
                            "service", tool_result, full_result, order
                        ),
                        "cards": [],
                        "full_result": (
                            full_result if isinstance(full_result, dict) else {}
                        ),
                    }
                    continue
                service_surface = {
                    "order": order,
                    "tool": tool_name if tool_name == "find_installation_slots" else "find_installation_partners",
                    "surface_ref": _runtime_surface_ref("service", tool_result, full_result, order),
                    "cards": cards,
                    "full_result": full_result if isinstance(full_result, dict) else {},
                }
                continue
    if order_surface or payment_surface:
        product_surfaces = [
            item
            for item in product_surfaces
            if str(item[1].get("tool") or "") not in {"get_product_details"}
        ]
    surfaces = [
        *promo_surfaces,
        *product_surfaces,
        ("service", service_surface),
        ("order", order_surface),
        ("payment", payment_surface),
    ]
    return sorted(
        [(surface_type, surface) for surface_type, surface in surfaces if surface],
        key=lambda item: int(item[1].get("order") or 0),
    )


def _surfaces_include_warranty_promo(
    surfaces: Sequence[Tuple[str, Dict[str, Any]]],
) -> bool:
    """Return whether a reviewed promo gallery already explains warranty.

    The decision uses catalog metadata instead of a hard-coded promo ID, image
    URL, brand, SKU, or month.
    """

    for surface_type, surface in surfaces or []:
        if surface_type != "promo":
            continue
        full_result = (
            surface.get("full_result")
            if isinstance(surface.get("full_result"), dict)
            else {}
        )
        if not _promo_gallery_surface_has_renderable_card(surface, full_result):
            continue
        if any(
            str(value or "").strip().casefold() == "warranty"
            for value in full_result.get("promo_types") or []
        ):
            return True
    return False


def _promo_gallery_surface_has_renderable_card(
    surface: Mapping[str, Any],
    full_result: Mapping[str, Any],
) -> bool:
    """Mirror the immutable minimum required by the ManyChat card renderer."""

    if (
        str(full_result.get("status") or "").strip() != "ok"
        or full_result.get("card_runtime_insert") is not True
    ):
        return False
    for card in surface.get("cards") or full_result.get("cards") or []:
        if not isinstance(card, Mapping):
            continue
        title = str(card.get("title") or "").strip()
        image_url = str(card.get("image_url") or "").strip()
        if (
            not title
            or not image_url.startswith("https://storage.googleapis.com/")
            or "?" in image_url
        ):
            continue
        for button in card.get("buttons") or []:
            if not isinstance(button, Mapping):
                continue
            caption = str(button.get("caption") or "").strip()
            targets = button.get("targets") if isinstance(button.get("targets"), Mapping) else {}
            has_target = bool(
                str(button.get("target") or "").strip()
                or any(str(value or "").strip() for value in targets.values())
            )
            has_click_action = any(
                isinstance(action, Mapping)
                and str(action.get("action") or "").strip() == "set_field_value"
                and str(action.get("field_name") or "").strip()
                == "promo_selected_id"
                and str(action.get("value") or "").strip()
                for action in button.get("actions") or []
            )
            if caption and len(caption) <= 20 and has_target and has_click_action:
                return True
    return False


def _promo_tool_record(name: str, args: Dict[str, Any], full_result: Dict[str, Any]) -> Dict[str, Any]:
    """Build the same trace shape used for model-requested promo tools."""

    latency_ms = full_result.get("latency_ms")
    if not isinstance(latency_ms, (int, float)) and name == "present_promo_gallery":
        # This is an in-process deterministic surface projection. Provider-backed
        # promo searches retain their measured latency from the service result.
        latency_ms = 0
    return {
        "round": 0,
        "tool_call_id": f"runtime_preload_{name}",
        "name": name,
        "args": deepcopy(args),
        "model_args": {},
        "latency_ms": latency_ms,
        "result": _compact_tool_result(name, full_result),
        "full_result": deepcopy(full_result),
        "runtime_preloaded": True,
    }


def _should_suppress_anonymous_partner_cards(
    tool_name: str,
    full_result: Dict[str, Any],
    cards: Sequence[Dict[str, Any]],
) -> bool:
    """Treat hidden area-only partner rows as internal proof, not visible options."""

    if str(tool_name or "") == "find_installation_slots":
        return False
    if str(full_result.get("partner_detail_level") or "") not in {"area_only", "availability_summary"}:
        return False
    return not any(str(card.get("name") or "").strip() for card in cards or [] if isinstance(card, dict))


def _append_response_guard_event(
    guard_events: Optional[List[Dict[str, Any]]],
    **event: Any,
) -> None:
    """Append optional response-composition telemetry without affecting delivery."""

    if guard_events is None:
        return
    guard_events.append(_compact_unit(event))


def _runtime_surface_ref(
    surface_type: str,
    tool_result: Dict[str, Any],
    full_result: Dict[str, Any],
    order: int,
) -> str:
    result = tool_result.get("result") if isinstance(tool_result.get("result"), dict) else {}
    ref = str(
        full_result.get("presentation_ref")
        or full_result.get("order_summary_ref")
        or full_result.get("payment_request_ref")
        or result.get("presentation_ref")
        or result.get("order_summary_ref")
        or result.get("payment_request_ref")
        or ""
    ).strip()
    if ref:
        return ref
    tool_name = str(tool_result.get("name") or "surface").strip() or "surface"
    return f"pres_{surface_type}_{tool_name}_{order + 1}"


def _parse_structured_response_units(model_text: str) -> Optional[List[Dict[str, Any]]]:
    payload = _parse_structured_final_response_payload(model_text)
    units = payload.get("response_units")
    if not isinstance(units, list):
        return None
    return [unit for unit in units if isinstance(unit, dict)]


def _parse_structured_final_response_payload(model_text: str) -> Dict[str, Any]:
    """Parse the structured composer envelope without accepting loose JSON."""

    text = str(model_text or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*```$", "", text).strip()
    if not text.startswith("{"):
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _parse_structured_interaction_decision(model_text: str) -> Dict[str, Any]:
    """Read the model's proposed interaction meaning from structured output."""

    text = str(model_text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*```$", "", text).strip()
    if not text.startswith("{"):
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    decision = payload.get("interaction_decision") if isinstance(payload, dict) else {}
    return dict(decision) if isinstance(decision, dict) else {}


def _semantic_answer_audit_context(
    tool_results: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return authored FAQ/contact answers for goal and scope review."""

    contexts: List[Dict[str, Any]] = []
    answer_tools = {
        "answer_product_faq",
        "answer_policy_faq",
        "answer_service_faq",
        "answer_order_faq",
        "get_business_contact",
    }
    for tool_result in tool_results or []:
        if not isinstance(tool_result, dict):
            continue
        name = str(tool_result.get("name") or "").strip()
        if name not in answer_tools:
            continue
        full = (
            tool_result.get("full_result")
            if isinstance(tool_result.get("full_result"), dict)
            else {}
        )
        compact = (
            tool_result.get("result")
            if isinstance(tool_result.get("result"), dict)
            else {}
        )
        status = str(full.get("status") or compact.get("status") or "")
        applicability = str(
            full.get("applicability")
            or compact.get("applicability")
            or ""
        ).strip()
        evidence_ref = str(
            full.get("evidence_ref")
            or compact.get("evidence_ref")
            or ""
        ).strip()
        answer = str(
            full.get("answer")
            or compact.get("answer")
            or full.get("answer_basis")
            or compact.get("answer_basis")
            or ""
        ).strip()
        if (
            status != "ok"
            or not evidence_ref
            or not answer
        ):
            continue
        policy_type = str(
            full.get("policy_type")
            or compact.get("policy_type")
            or ""
        )
        answer_goal = str(
            full.get("question")
            or compact.get("question")
            or full.get("title")
            or compact.get("title")
            or ""
        )
        if policy_type == "delivery_process":
            answer_goal = (
                "Explain whether delivery is offered generally, the published "
                "delivery paths, and expected delivery time without confirming "
                "an exact-location serviceability result."
            )
        contexts.append(
            {
                "tool": name,
                "faq_id": str(
                    full.get("faq_id") or compact.get("faq_id") or ""
                ),
                "policy_type": policy_type,
                "applicability": applicability,
                "answer_goal": answer_goal,
                "evidence_ref": evidence_ref,
                "authored_answer": answer,
                "composition_boundary": str(
                    full.get("composition_hint")
                    or compact.get("composition_hint")
                    or (
                        "This authored answer authorizes only its visible facts "
                        "and does not prove a narrower current product, service, "
                        "schedule, payment, or order fact."
                    )
                ),
            }
        )
    return contexts


def _audit_semantic_answer_goal(
    *,
    model_client: Any,
    current_user_message: str,
    model_text: str,
    parsed_units: Sequence[Dict[str, Any]],
    tool_results: Sequence[Dict[str, Any]],
    customer_turn_plan: Mapping[str, Any],
    record: Dict[str, Any],
    round_name: str,
) -> Optional[Dict[str, Any]]:
    """Audit whether an FAQ result and composed response answer the user."""

    policy_context = _semantic_answer_audit_context(tool_results)
    if not policy_context or not _model_client_supports_response_format(
        model_client
    ):
        return None
    progression_context = (
        customer_turn_plan.get("progression_context")
        if isinstance(customer_turn_plan.get("progression_context"), dict)
        else {}
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You audit customer-service answers against authored FAQ and "
                "policy evidence. Judge meaning, not keywords. First compare "
                "the customer's actual request with each FAQ answer_goal and "
                "authored_answer. Set answer_goal_alignment=misaligned when the "
                "retrieved FAQ is unrelated to the request, even if the visible "
                "response accurately repeats that FAQ. Use partial when it "
                "answers only part of a compound request. A customer's stated "
                "location, product, date, payment preference, or order claim "
                "is a request, not proof. A policy_general FAQ authorizes its "
                "published general facts only; other FAQ applicability values "
                "remain limited to their authored answer. No FAQ proves narrower "
                "case-specific availability, eligibility, serviceability, "
                "schedule, payment, product, or order state unless the input "
                "explicitly says that category is separately authorized. "
                "Do not infer that a customer-named city, district, barangay, "
                "landmark, or address is covered merely because it may belong "
                "to a broader region named by the policy. Confirming that "
                "named place as included or serviceable is still a narrower "
                "case-specific claim. "
                "A statement that another customer input is required or "
                "sufficient to verify, enable, or decide the pending policy "
                "outcome is also a factual process claim and needs authored "
                "or provider authority. A separate optional shopping CTA is "
                "allowed, but it must not be framed as that validation step. "
                "Distinguish that from an epistemic scope boundary: saying "
                "that an exact case is not yet confirmed or still needs "
                "checking is allowed when general evidence cannot authorize "
                "the narrower fact. That statement alone does not assert a "
                "validation workflow, required customer input, responsible "
                "party, or guaranteed outcome; classify its validation process "
                "as none. Only a concrete how, who, required input, or promised "
                "verification path needs separate process authority. "
                "A dependency of the form 'to verify or confirm outcome X, "
                "provide input Y' is a concrete validation-process claim even "
                "when input Y could be useful for a different legitimate goal. "
                "Classify that dependency as unsupported unless the evidence "
                "authorizes it. Treat a follow-up as a separate optional CTA "
                "only when the response clearly says it serves another goal "
                "and does not imply that it verifies the pending policy case. "
                "Return supported only when answer_goal_alignment=aligned, the "
                "visible answer covers the customer's requested goal and the "
                "required FAQ answer, and contains no fact beyond its "
                "authorized scope. Use incomplete for a missing required "
                "answer, unsupported for any overclaim, and unclear only when "
                "the evidence comparison truly cannot be resolved. Always "
                "classify customer_request_scope, case_specific_handling, and "
                "validation_process_handling independently of decision. For "
                "any non-supported result, return a repair_contract with "
                "required_meanings, forbidden_meanings, and allowed_evidence_refs. "
                "Describe semantic obligations, not suggested customer copy."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "customer_message": current_user_message,
                    "customer_visible_response_units": list(parsed_units),
                    "semantic_answer_evidence": policy_context,
                    "required_faq_fact_answers": progression_context.get(
                        "required_faq_fact_answers", []
                    ),
                    "service_availability_separately_authorized": bool(
                        progression_context.get(
                            "service_availability_claims_authorized"
                        )
                    ),
                    "schedule_availability_separately_authorized": bool(
                        progression_context.get(
                            "schedule_availability_claims_authorized"
                        )
                    ),
                    "declared_claim_assertions": (
                        _parse_structured_claim_assertions(model_text)
                    ),
                },
                ensure_ascii=False,
            ),
        },
    ]
    started = time.perf_counter()
    response = _complete_model_client(
        model_client,
        messages=messages,
        tools=[],
        tool_choice="none",
        response_format=RuntimeV7SemanticAnswerAuditModel,
        max_tokens=FACT_SCOPE_AUDIT_MAX_TOKENS,
        temperature=0.0,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    content = str(response.get("content") or "")
    usage_summary = _llm_usage_summary(response)
    record.setdefault("llm_calls", []).append(
        {
            "round": round_name,
            "component": "semantic_answer_goal_audit",
            "model_input_messages": deepcopy(messages),
            "tool_schemas": [],
            "model_output": deepcopy(response),
            "content": content,
            "tool_calls": [],
            "usage": deepcopy(response.get("usage") or {}),
            "cache_usage": deepcopy(response.get("cache_usage") or {}),
            "request_cache": deepcopy(response.get("request_cache") or {}),
            "cache_guard_events": deepcopy(
                response.get("cache_guard_events") or []
            ),
            "usage_summary": usage_summary,
            "latency_ms": response.get("latency_ms", latency_ms),
            "finish_reason": response.get("finish_reason"),
            "response_format": "RuntimeV7SemanticAnswerAuditModel",
        }
    )
    try:
        audit = RuntimeV7SemanticAnswerAuditModel.model_validate_json(
            content
        ).model_dump()
    except (TypeError, ValueError):
        audit = {
            "decision": "unclear",
            "unsupported_claims": [],
            "missing_answers": [],
            "answer_goal_alignment": "not_applicable",
            "reason": "invalid_semantic_answer_goal_audit",
        }
    answer_goal_alignment = str(
        audit.get("answer_goal_alignment") or "not_applicable"
    )
    if answer_goal_alignment == "misaligned":
        audit["decision"] = "unsupported"
    elif (
        answer_goal_alignment == "partial"
        and audit.get("decision") == "supported"
    ):
        audit["decision"] = "incomplete"
    has_general_policy_evidence = any(
        str(item.get("applicability") or "") == "policy_general"
        for item in policy_context
        if isinstance(item, Mapping)
    )
    if (
        has_general_policy_evidence
        and audit.get("customer_request_scope") == "case_specific"
        and not (
            progression_context.get("service_availability_claims_authorized")
            or progression_context.get(
                "schedule_availability_claims_authorized"
            )
        )
    ):
        case_handling = str(audit.get("case_specific_handling") or "")
        if case_handling == "implied_or_confirmed":
            audit["decision"] = "unsupported"
        elif case_handling != "explicitly_pending":
            audit["decision"] = "incomplete"
    if audit.get("validation_process_handling") == "unsupported":
        audit["decision"] = "unsupported"
    record.setdefault("semantic_answer_goal_audits", []).append(
        {
            "round": round_name,
            **deepcopy(audit),
        }
    )
    if audit.get("decision") == "supported":
        return None
    return {
        "type": f"answer_goal_{audit.get('decision') or 'unclear'}",
        "answer_goal_alignment": answer_goal_alignment,
        "unsupported_claims": list(
            audit.get("unsupported_claims") or []
        )[:8],
        "missing_answers": list(audit.get("missing_answers") or [])[:8],
        "reason": str(audit.get("reason") or "")[:500],
        "repair_contract": deepcopy(audit.get("repair_contract") or {}),
        "authorized_policy_evidence": policy_context,
    }


def _compact_promo_contract_candidate(
    candidate: Mapping[str, Any],
) -> Dict[str, Any]:
    """Project one reviewed campaign into shared composition authority.

    Retrieval diagnostics and duplicate source metadata stay in the full tool
    artifact. Composer and audit need only exact customer-visible facts,
    applicability, and the provider-issued promo ref.
    """

    mechanics = [
        str(row.get("text") or "").strip()
        for row in candidate.get("relevant_mechanics") or []
        if isinstance(row, Mapping)
        and str(row.get("text") or "").strip()
    ]
    return _compact_unit(
        {
            "promo_ref": candidate.get("promo_ref"),
            "title": candidate.get("title"),
            "brands": list(candidate.get("brands") or [])[:4],
            "offer_summary": candidate.get("offer_summary"),
            "valid_from": candidate.get("valid_from"),
            "valid_until": candidate.get("valid_until"),
            "relevant_mechanics": mechanics[:4],
            "applicability": deepcopy(candidate.get("applicability") or {}),
            "has_visual_cards": candidate.get("has_visual_cards") is True,
        }
    )


def _promo_fact_audit_context(
    tool_results: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build one compact promo contract shared by composer and audit.

    Campaign search, product pricing, and renderer surfaces remain distinct
    authorities. The returned packet deliberately contains no retrieval scores,
    full cards, or duplicated tool guidance, so every model stage reasons over
    the same closed fact set without copying the catalog payload repeatedly.
    """

    searches: List[Dict[str, Any]] = []
    verified_product_promos: List[Dict[str, Any]] = []
    category_choice_surfaces: List[Dict[str, Any]] = []
    promo_gallery_surfaces: List[Dict[str, Any]] = []
    product_search_performed = False
    for tool_result in tool_results or []:
        if not isinstance(tool_result, dict):
            continue
        if (
            str(tool_result.get("completion_source") or "").strip()
            == "product_tpp_supporting_surface_policy"
        ):
            continue
        name = str(tool_result.get("name") or "")
        full = (
            tool_result.get("full_result")
            if isinstance(tool_result.get("full_result"), dict)
            else {}
        )
        compact = (
            tool_result.get("result")
            if isinstance(tool_result.get("result"), dict)
            else {}
        )
        payload = full or compact
        if name == "search_promo_catalog":
            status = str(payload.get("status") or "")
            allowed_refs = {
                str(value or "").strip()
                for value in payload.get("allowed_promo_refs") or []
                if str(value or "").strip()
            }
            applicable_promos = [
                _compact_promo_contract_candidate(candidate)
                for candidate in payload.get("candidates") or []
                if isinstance(candidate, dict)
                and str(candidate.get("promo_ref") or "").strip()
                in allowed_refs
            ][:5]
            searches.append(
                {
                    "status": status,
                    "mode": payload.get("mode"),
                    "evidence_ref": payload.get("evidence_ref"),
                    "provider_available": status
                    not in {"unavailable", "error"},
                    "tire_size": payload.get("tire_size"),
                    "requested_brands": list(
                        payload.get("requested_brands") or []
                    )[:8],
                    "matched_requested_brands": list(
                        payload.get("matched_requested_brands") or []
                    )[:8],
                    "unmatched_requested_brands": list(
                        payload.get("unmatched_requested_brands") or []
                    )[:8],
                    "applicable_promo_refs": sorted(allowed_refs)[:8],
                    "applicable_promos": applicable_promos,
                    "reviewed_search_scope_outcome": (
                        "no_verified_applicable_promo_returned"
                        if status == "ok"
                        and payload.get("evidence_ref")
                        and not allowed_refs
                        else "verified_applicable_promos_returned"
                        if status == "ok" and allowed_refs
                        else None
                    ),
                    "search_scope_boundary": (
                        "This result covers only the exact reviewed search "
                        "scope represented by evidence_ref. It is not a "
                        "global claim about every catalog promo and cannot "
                        "deny product-level quantity, bundle, voucher, "
                        "discount, price, or SKU promo facts owned by an "
                        "exact product search."
                    ),
                }
            )
        elif name == "product_search":
            product_search_performed = True
            for card in payload.get("product_cards") or []:
                if not isinstance(card, dict):
                    continue
                pricing = (
                    card.get("pricing_facts")
                    if isinstance(card.get("pricing_facts"), dict)
                    else {}
                )
                included = list(pricing.get("included_promos") or [])
                promo_line = str(card.get("promo_savings_line") or "").strip()
                if not included and not promo_line:
                    continue
                verified_product_promos.append(
                    {
                        "brand": card.get("brand"),
                        "tire_size": card.get("tire_size"),
                        "sku_model": card.get("sku_model"),
                        "promo_savings_line": promo_line,
                        "pricing_basis": pricing.get("pricing_basis"),
                        "included_promos": included[:8],
                    }
                )
        elif name == "present_promo_gallery":
            if payload.get("presentation_ref"):
                promo_gallery_surfaces.append(
                    {
                        "presentation_ref": payload.get(
                            "presentation_ref"
                        ),
                        "promo_refs": list(payload.get("promo_refs") or [])[:8],
                        "renderer_owned": True,
                    }
                )
        elif name == "discover_brand_buckets":
            cards = [
                card
                for card in payload.get("bucket_cards") or []
                if isinstance(card, dict)
            ]
            if cards:
                category_choice_surfaces.append(
                    {
                        "presentation_ref": payload.get(
                            "presentation_ref"
                        ),
                        "categories": [
                            str(card.get("label") or card.get("bucket") or "")
                            for card in cards[:8]
                        ],
                        "authority_boundary": (
                            "This surface proves only current product/category "
                            "choices. It does not prove any promo, discount, "
                            "bundle, free-item mechanic, or promo eligibility."
                        ),
                    }
                )
    if not searches:
        return {}
    requested_answer_scope = (
        "targeted_promo_answer"
        if any(
            str(search.get("mode") or "") == "targeted"
            or bool(search.get("requested_brands"))
            for search in searches
        )
        else "general_promo_discovery"
    )
    return {
        "version": "promo_response_contract_v1",
        "promo_searches": searches,
        "verified_product_promos": verified_product_promos[:12],
        "category_choice_surfaces": category_choice_surfaces[:4],
        "promo_gallery_surfaces": promo_gallery_surfaces[:4],
        "answer_contract": {
            "requested_answer_scope": requested_answer_scope,
            "campaign_claim_scope": "exact_search_result_only",
            "product_promo_claim_scope": (
                "verified_presented_products_only"
                if product_search_performed
                else "pending_exact_product_search"
            ),
            "renderer_surfaces_are_claim_authority": False,
            "negative_campaign_result_is_global": False,
        },
    }


def _audit_promo_fact_answer(
    *,
    model_client: Any,
    current_user_message: str,
    model_text: str,
    parsed_units: Sequence[Dict[str, Any]],
    tool_results: Sequence[Dict[str, Any]],
    record: Dict[str, Any],
    round_name: str,
) -> Optional[Dict[str, Any]]:
    """Audit complete visible promo meaning against current typed evidence."""

    promo_context = _promo_fact_audit_context(tool_results)
    if not promo_context or not _model_client_supports_response_format(
        model_client
    ):
        return None
    if not _requires_promo_fact_semantic_audit(
        current_user_message=current_user_message,
        parsed_units=parsed_units,
    ):
        record.setdefault("promo_fact_scope_audits", []).append(
            {
                "round": round_name,
                "decision": "skipped",
                "reason": "proactive_renderer_owned_promo_without_commercial_prose",
            }
        )

        return None
    messages = [
        {
            "role": "system",
            "content": (
                "You audit a complete customer-service response against "
                "current typed promo evidence. Judge meaning as a whole, not "
                "keywords or declared claim labels. Positive promo, discount, "
                "bundle, free-item, price, and eligibility claims require an "
                "exact applicable promo or verified product-promo fact in the "
                "packet. An unmatched requested brand supports only the "
                "corresponding negative result when the provider is available. "
                "A product/category choice surface never proves that its "
                "brands have promos. A provider error proves neither presence "
                "nor absence. A successful search with a result-level "
                "evidence_ref and reviewed_search_scope_outcome="
                "no_verified_applicable_promo_returned supports saying that "
                "no verified applicable promo or requested promo alternative "
                "was returned for that exact reviewed scope. It does not "
                "support a global no-promo claim outside that scope. The "
                "reviewed campaign catalog and exact product search are "
                "separate providers: a campaign-catalog no-match never "
                "authorizes denying product-level quantity, bundle, voucher, "
                "discount, price, or SKU promos. Those facts require an "
                "exact-size product_search result and remain pending without "
                "one. When promo_evidence has no tire_size and no "
                "verified_product_promos, any statement that no such "
                "product-level promo was found or is active is still an "
                "overgeneralized cross-provider negative; the response must "
                "keep availability, applicability, and price pending and ask "
                "for exact size. Classify any cross-provider negative as "
                "negative_promo_scope_handling="
                "overgeneralized_across_providers. When no "
                "verified alternative was returned, explicitly saying so is "
                "a complete truthful answer to a request for alternatives; "
                "do not require the response to invent or provide an offer. "
                "Return supported only when the visible answer "
                "answers the requested promo fact and contains no unsupported "
                "promo meaning. Use incomplete for an omitted requested fact, "
                "unsupported for any overclaim, and unclear only when the "
                "evidence comparison truly cannot be resolved. Always "
                "set customer_requested_promo_fact from the latest customer "
                "goal. Keep it false when an authorized promo is presented "
                "proactively during another product or service turn. In that "
                "case requested_promo_result_handling=not_requested is valid "
                "and is not incomplete by itself; still audit every visible "
                "promo claim against the supplied evidence. Always "
                "classify requested_promo_result_handling, whether the "
                "customer requested alternatives, alternative_promo_handling, "
                "and category_surface_handling independently of decision. For "
                "any non-supported result, return a repair_contract with "
                "required_meanings, forbidden_meanings, allowed_promo_refs, "
                "and renderer_surface_roles. Describe semantic obligations, "
                "not suggested customer copy. Express boundaries through the "
                "customer's known brand, tire size, promo type, and what still "
                "needs checking; never require customer-visible catalog, "
                "search, provider, evidence, scope, review, or validation "
                "terminology."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "customer_message": current_user_message,
                    "customer_visible_response_units": list(parsed_units),
                    "promo_evidence": promo_context,
                    "declared_claim_assertions": (
                        _parse_structured_claim_assertions(model_text)
                    ),
                },
                ensure_ascii=False,
            ),
        },
    ]
    started = time.perf_counter()
    response = _complete_model_client(
        model_client,
        messages=messages,
        tools=[],
        tool_choice="none",
        response_format=RuntimeV7PromoFactAuditModel,
        max_tokens=FACT_SCOPE_AUDIT_MAX_TOKENS,
        temperature=0.0,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    content = str(response.get("content") or "")
    record.setdefault("llm_calls", []).append(
        {
            "round": round_name,
            "component": "promo_fact_scope_audit",
            "model_input_messages": deepcopy(messages),
            "tool_schemas": [],
            "model_output": deepcopy(response),
            "content": content,
            "tool_calls": [],
            "usage": deepcopy(response.get("usage") or {}),
            "cache_usage": deepcopy(response.get("cache_usage") or {}),
            "request_cache": deepcopy(response.get("request_cache") or {}),
            "cache_guard_events": deepcopy(
                response.get("cache_guard_events") or []
            ),
            "usage_summary": _llm_usage_summary(response),
            "latency_ms": response.get("latency_ms", latency_ms),
            "finish_reason": response.get("finish_reason"),
            "response_format": "RuntimeV7PromoFactAuditModel",
        }
    )
    try:
        audit = RuntimeV7PromoFactAuditModel.model_validate_json(
            content
        ).model_dump()
    except (TypeError, ValueError):
        audit = {
            "decision": "unclear",
            "unsupported_claims": [],
            "missing_answers": [],
            "customer_requested_promo_fact": False,
            "reason": "invalid_promo_fact_semantic_audit",
        }
    customer_requested_promo_fact = bool(
        audit.get("customer_requested_promo_fact")
    )
    requested_result_handling = str(
        audit.get("requested_promo_result_handling") or ""
    )
    if requested_result_handling == "overgeneralized":
        audit["decision"] = "unsupported"
    elif requested_result_handling == "omitted":
        audit["decision"] = "incomplete"
    elif (
        requested_result_handling == "not_requested"
        and customer_requested_promo_fact
    ):
        audit["decision"] = "incomplete"

    verified_alternative_count = sum(
        len(search.get("applicable_promo_refs") or [])
        for search in promo_context.get("promo_searches") or []
        if isinstance(search, dict)
    ) + len(promo_context.get("verified_product_promos") or [])
    alternative_handling = str(
        audit.get("alternative_promo_handling") or ""
    )
    if audit.get("customer_requested_alternatives"):
        if alternative_handling == "unverified_positive":
            audit["decision"] = "unsupported"
        elif (
            verified_alternative_count == 0
            and alternative_handling != "explicitly_none_verified"
        ):
            audit["decision"] = "incomplete"
    category_choice_surfaces = list(
        promo_context.get("category_choice_surfaces") or []
    )
    if not category_choice_surfaces:
        # The semantic auditor can occasionally classify a promo gallery as a
        # product-category surface. Do not let that hallucinated auxiliary
        # label discard an otherwise grounded renderer-owned promo gallery.
        audit["category_surface_handling"] = "not_present"
    elif audit.get("category_surface_handling") == "used_as_promo_evidence":
        audit["decision"] = "unsupported"
    if (
        audit.get("negative_promo_scope_handling")
        == "overgeneralized_across_providers"
    ):
        audit["decision"] = "unsupported"
    if (
        not customer_requested_promo_fact
        and not audit.get("customer_requested_alternatives")
        and requested_result_handling == "not_requested"
        and not audit.get("unsupported_claims")
        and not audit.get("missing_answers")
        and alternative_handling != "unverified_positive"
        and audit.get("category_surface_handling")
        != "used_as_promo_evidence"
    ):
        # A proactive, provider-authorized promo can be a useful secondary
        # surface even when the customer did not request promo information.
        # The semantic audit still verifies its claims; absence of a promo
        # question alone must not manufacture a repair loop.
        audit["decision"] = "supported"
    record.setdefault("promo_fact_scope_audits", []).append(
        {"round": round_name, **deepcopy(audit)}
    )
    if audit.get("decision") == "supported":
        return None
    return {
        "type": f"promo_fact_{audit.get('decision') or 'unclear'}",
        "unsupported_claims": list(
            audit.get("unsupported_claims") or []
        )[:8],
        "missing_answers": list(audit.get("missing_answers") or [])[:8],
        "reason": str(audit.get("reason") or "")[:500],
        "repair_contract": deepcopy(audit.get("repair_contract") or {}),
        "authorized_promo_evidence": promo_context,
    }


def _requires_promo_fact_semantic_audit(
    *,
    current_user_message: str,
    parsed_units: Sequence[Dict[str, Any]],
) -> bool:
    """Reserve the paid semantic audit for customer-requested or prose claims.

    A reviewed promo gallery can support a product turn without another model
    judging the renderer-owned image. Exact campaign mechanics, amounts,
    eligibility, validity, or savings written in model prose still receive the
    semantic audit, as does every explicit customer promo question.
    """

    if is_targeted_promo_query(current_user_message):
        return True
    visible_text = " ".join(
        str(
            (
                unit.get("content")
                if isinstance(unit.get("content"), dict)
                else {}
            ).get("text")
            or ""
        )
        for unit in parsed_units or []
        if str(unit.get("type") or "").strip() == "text"
    ).casefold()
    if not visible_text:
        return False
    return bool(
        re.search(
            r"(?:\bpromos?\b|\bbuy\s*\d+\b|\bget\s*\d+\b|\bfree\b|\bdiscount\b|"
            r"\bcashback\b|\bsave\b|\boff\b|\bvalid\b|\buntil\b|"
            r"\beligib|\bapplicab|\bqualif|\binstallment\b|\binterest\b|"
            r"\b(?:month|year)s?\b|php\s*\d|₱\s*\d|\d+\s*%)",
            visible_text,
        )
    )


def _safe_semantic_answer_units(
    tool_results: Sequence[Dict[str, Any]],
    *,
    include_authored_answers: bool = True,
) -> List[Dict[str, Any]]:
    """Fail closed without repeating a semantically unrelated FAQ answer."""

    contexts = _semantic_answer_audit_context(tool_results)
    answers: List[str] = []
    if include_authored_answers:
        for context in contexts:
            answer = str(context.get("authored_answer") or "").strip()
            if answer and answer not in answers:
                answers.append(answer)
    if not answers:
        answers.append(
            "Para tama po ang maibigay ko, paki-clarify lang yung exact concern niyo."
        )
    else:
        answers.append(
            "Yung exact details para sa request niyo, kailangan pa pong "
            "i-check."
        )
    return [
        {"type": "text", "content": {"text": "\n\n".join(answers)}}
    ]


def _semantic_fallback_includes_authored_answers(
    *,
    initial_violations: Sequence[Mapping[str, Any]],
    remaining_violations: Sequence[Mapping[str, Any]],
) -> bool:
    """Preserve a relevant authored answer when repair auditing drifts.

    The first audit sees normal customer-facing composition and decides whether
    the selected authored answer is aligned with the request. A later
    evidence-only repair audit may disagree about implication while still
    requiring that same general-policy answer. Keep provider-authored facts
    when the first audit classified them as aligned or partially aligned; omit
    them only when the first audit itself found the answer goal unrelated.
    """

    initial_alignments = [
        str(item.get("answer_goal_alignment") or "").strip()
        for item in initial_violations
        if isinstance(item, Mapping)
        and str(item.get("type") or "").startswith("answer_goal_")
        and str(item.get("answer_goal_alignment") or "").strip()
    ]
    if initial_alignments:
        return any(
            alignment != "misaligned"
            for alignment in initial_alignments
        )
    return not any(
        isinstance(item, Mapping)
        and str(item.get("type") or "").startswith("answer_goal_")
        and str(item.get("answer_goal_alignment") or "").strip()
        == "misaligned"
        for item in remaining_violations
    )


def _safe_promo_fact_units(
    tool_results: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Render only typed promo-search facts after semantic repair fails.

    Normal customer copy remains model-owned. This bounded fallback activates
    only after repeated whole-response audits fail, so provider-backed negative
    scope and renderer-owned shopping controls survive without turning ordinary
    product categories into promo evidence.
    """

    context = _promo_fact_audit_context(tool_results)
    empty_searches = [
        search
        for search in context.get("promo_searches") or []
        if isinstance(search, dict)
        and search.get("provider_available") is True
        and search.get("reviewed_search_scope_outcome")
        == "no_verified_applicable_promo_returned"
    ]
    statements: List[str] = []
    for search in empty_searches:
        brands = [
            str(value or "").strip()
            for value in search.get("unmatched_requested_brands") or []
            if str(value or "").strip()
        ]
        tire_size = str(search.get("tire_size") or "").strip()
        brand_text = ", ".join(brands)
        scope_text = (
            f"{brand_text}, size {tire_size}"
            if brand_text and tire_size
            else brand_text
            or (f"size {tire_size}" if tire_size else "")
        )
        if scope_text:
            statements.append(
                "Sa current reviewed promos, wala pong verified promo na "
                f"tugma para sa {scope_text}."
            )
        else:
            statements.append(
                "Sa current reviewed promos, wala pong verified promo na "
                "bumalik para sa exact search na ito."
            )
    if empty_searches:
        statements.append(
            "Wala rin pong verified promo alternative na bumalik para sa "
            "exact search na ito."
        )
    else:
        statements.append(
            "Hindi ko pa po ma-verify ang promo result para sa exact search "
            "na ito."
        )

    units: List[Dict[str, Any]] = [
        {
            "type": "text",
            "content": {"text": " ".join(dict.fromkeys(statements))},
        }
    ]
    category_refs = [
        str(surface.get("presentation_ref") or "").strip()
        for surface in context.get("category_choice_surfaces") or []
        if isinstance(surface, dict)
        and str(surface.get("presentation_ref") or "").strip()
    ]
    if category_refs:
        units.append(
            {
                "type": "text",
                "content": {
                    "text": (
                        "Puwede pa rin po kayong tumingin ng regular tire "
                        "options ayon sa price category. Hindi po promo "
                        "alternatives ang mga category na ito."
                    )
                },
            }
        )
        units.extend(
            {
                "type": "render_surface",
                "content": {"surface_ref": surface_ref},
            }
            for surface_ref in dict.fromkeys(category_refs)
        )
    return units


def _requires_provider_owned_empty_promo_result(
    tool_results: Sequence[Dict[str, Any]],
) -> bool:
    """Return whether typed empty promo facts must own the visible result."""

    context = _promo_fact_audit_context(tool_results)
    has_category_surface = any(
        isinstance(surface, dict)
        and str(surface.get("presentation_ref") or "").strip()
        for surface in context.get("category_choice_surfaces") or []
    )
    has_unmatched_empty_scope = any(
        isinstance(search, dict)
        and search.get("provider_available") is True
        and bool(search.get("unmatched_requested_brands"))
        and search.get("reviewed_search_scope_outcome")
        == "no_verified_applicable_promo_returned"
        for search in context.get("promo_searches") or []
    )
    return bool(has_category_surface and has_unmatched_empty_scope)


def _parse_structured_claim_assertions(
    model_text: str,
) -> List[Dict[str, Any]]:
    """Read composer-declared factual meaning without inspecting prose."""

    text = str(model_text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*```$", "", text).strip()
    if not text.startswith("{"):
        return []
    try:
        payload = json.loads(text)
    except Exception:
        return []
    assertions = (
        payload.get("claim_assertions")
        if isinstance(payload, dict)
        else []
    )
    if not isinstance(assertions, list):
        return []
    return [item for item in assertions if isinstance(item, dict)]


def _sanitize_provider_owned_service_claim_prose(
    model_text: str,
    *,
    customer_turn_plan: Mapping[str, Any],
) -> Tuple[str, List[Dict[str, Any]], int]:
    """Remove text units whose service fact is owned by a required surface.

    The composer declares which response-unit indexes contain each factual
    assertion. When a deterministic installation summary is required, this
    allows the runtime to remove a duplicated service claim without matching
    customer wording. If the model combined another assertion into that same
    unit, the complete unit and its now-unmapped assertions are removed; the
    required provider surface is the safe direct answer.
    """

    provider_summary_refs = {
        str(surface.get("surface_ref") or "").strip()
        for surface in customer_turn_plan.get("available_surfaces") or []
        if isinstance(surface, Mapping)
        and surface.get("required") is True
        and str(surface.get("surface_type") or "").strip()
        == "installation_partner_summary"
        and str(surface.get("surface_ref") or "").strip()
    }
    payload = _parse_structured_final_response_payload(model_text)
    units = payload.get("response_units")
    assertions = payload.get("claim_assertions")
    if (
        not provider_summary_refs
        or not isinstance(units, list)
        or not isinstance(assertions, list)
    ):
        return model_text, list(units or []) if isinstance(units, list) else [], 0

    service_indexes = {
        index
        for assertion in assertions
        if isinstance(assertion, Mapping)
        and str(assertion.get("category") or "").strip()
        == "service_availability"
        for index in assertion.get("response_unit_indexes") or []
        if type(index) is int and 0 <= index < len(units)
    }
    removable_indexes = service_indexes
    if not removable_indexes:
        return model_text, [dict(unit) for unit in units if isinstance(unit, dict)], 0

    old_to_new: Dict[int, int] = {}
    sanitized_units: List[Dict[str, Any]] = []
    for old_index, unit in enumerate(units):
        if old_index in removable_indexes or not isinstance(unit, dict):
            continue
        old_to_new[old_index] = len(sanitized_units)
        sanitized_units.append(deepcopy(unit))
    rendered_refs = {
        str((unit.get("content") or {}).get("surface_ref") or "").strip()
        for unit in sanitized_units
        if str(unit.get("type") or "").strip() == "render_surface"
        and isinstance(unit.get("content"), Mapping)
    }
    if not provider_summary_refs.issubset(rendered_refs):
        return model_text, [dict(unit) for unit in units if isinstance(unit, dict)], 0

    sanitized_assertions: List[Dict[str, Any]] = []
    for assertion in assertions:
        if not isinstance(assertion, Mapping):
            continue
        if str(assertion.get("category") or "").strip() == "service_availability":
            continue
        row = deepcopy(dict(assertion))
        row["response_unit_indexes"] = [
            old_to_new[index]
            for index in row.get("response_unit_indexes") or []
            if index in old_to_new
        ]
        if row["response_unit_indexes"]:
            sanitized_assertions.append(row)

    sanitized_coverage: List[Dict[str, Any]] = []
    for coverage in payload.get("request_coverage") or []:
        if not isinstance(coverage, Mapping):
            continue
        row = deepcopy(dict(coverage))
        row["response_unit_indexes"] = [
            old_to_new[index]
            for index in row.get("response_unit_indexes") or []
            if index in old_to_new
        ]
        sanitized_coverage.append(row)
    payload["claim_assertions"] = sanitized_assertions
    payload["request_coverage"] = sanitized_coverage
    payload["response_units"] = sanitized_units
    return (
        json.dumps(payload, ensure_ascii=False),
        sanitized_units,
        len(removable_indexes),
    )


def _sanitize_post_repair_provider_owned_service_copy(
    model_text: str,
    response_units: Optional[Sequence[Dict[str, Any]]],
    violations: Sequence[Dict[str, Any]],
    *,
    tool_results: Sequence[Dict[str, Any]],
    customer_turn_plan: Mapping[str, Any],
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]], int]:
    """Apply the existing provider-surface sanitizer after model repair."""

    original_units = [
        deepcopy(unit) for unit in response_units or [] if isinstance(unit, dict)
    ]
    original_violations = [
        deepcopy(violation)
        for violation in violations or []
        if isinstance(violation, dict)
    ]
    if not response_units or not violations or not all(
        isinstance(violation, Mapping)
        and str(violation.get("type") or "")
        == "service_availability_prose_duplicates_provider_surface"
        for violation in violations
    ):
        return model_text, original_units, original_violations, 0
    sanitized_text, sanitized_units, removed_count = (
        _sanitize_provider_owned_service_claim_prose(
            model_text,
            customer_turn_plan=customer_turn_plan,
        )
    )
    if not removed_count:
        return model_text, original_units, original_violations, 0
    remaining = [
        *_final_composer_renderer_contract_violations(
            sanitized_units,
            tool_results,
            customer_turn_plan=dict(customer_turn_plan),
        ),
        *_final_composer_request_coverage_contract_violations(
            sanitized_text,
            sanitized_units,
            customer_turn_plan=dict(customer_turn_plan),
        ),
        *_final_composer_claim_contract_violations(
            sanitized_text,
            customer_turn_plan,
        ),
    ]
    return sanitized_text, sanitized_units, remaining, removed_count


def _final_composer_claim_contract_violations(
    model_text: str,
    customer_turn_plan: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Validate typed composer claims against current-turn evidence authority."""

    if (
        "authorized_claim_categories" not in customer_turn_plan
        and "authorized_evidence_refs" not in customer_turn_plan
    ):
        return []

    allowed_categories = {
        str(value).strip()
        for value in (
            customer_turn_plan.get("authorized_claim_categories") or []
        )
        if str(value).strip()
    }
    allowed_refs = {
        str(value).strip()
        for value in (
            customer_turn_plan.get("authorized_evidence_refs") or []
        )
        if str(value).strip()
    }
    progression_context = (
        customer_turn_plan.get("progression_context")
        if isinstance(
            customer_turn_plan.get("progression_context"), dict
        )
        else {}
    )
    refs_by_category = (
        progression_context.get(
            "authorized_evidence_refs_by_claim_category"
        )
        if isinstance(
            progression_context.get(
                "authorized_evidence_refs_by_claim_category"
            ),
            dict,
        )
        else {}
    )
    brand_fields_by_ref = (
        progression_context.get(
            "authorized_brand_fact_fields_by_evidence_ref"
        )
        if isinstance(
            progression_context.get(
                "authorized_brand_fact_fields_by_evidence_ref"
            ),
            dict,
        )
        else {}
    )
    service_scopes_by_ref = (
        progression_context.get(
            "authorized_service_area_claims_by_evidence_ref"
        )
        if isinstance(
            progression_context.get(
                "authorized_service_area_claims_by_evidence_ref"
            ),
            dict,
        )
        else {}
    )
    provider_owned_service_summary_present = any(
        isinstance(surface, Mapping)
        and surface.get("required") is True
        and str(surface.get("surface_type") or "").strip()
        == "installation_partner_summary"
        for surface in customer_turn_plan.get("available_surfaces") or []
    )
    violations: List[Dict[str, Any]] = []
    for index, assertion in enumerate(
        _parse_structured_claim_assertions(model_text)
    ):
        category = str(assertion.get("category") or "").strip()
        refs = {
            str(value).strip()
            for value in (assertion.get("evidence_refs") or [])
            if str(value).strip()
        }
        fact_fields = {
            str(value).strip()
            for value in (assertion.get("fact_fields") or [])
            if str(value).strip()
        }
        declared_service_scopes = {
            (
                str(value.get("scope_ref") or "").strip(),
                str(value.get("outcome") or "").strip(),
            )
            for value in (assertion.get("service_area_claims") or [])
            if isinstance(value, dict)
            and str(value.get("scope_ref") or "").strip()
            and str(value.get("outcome") or "").strip()
        }
        if category not in allowed_categories:
            violations.append(
                {
                    "type": "unauthorized_claim_category",
                    "assertion_index": index,
                    "category": category,
                    "allowed_categories": sorted(allowed_categories),
                }
            )
        unknown_refs = sorted(refs - allowed_refs)
        if unknown_refs:
            violations.append(
                {
                    "type": "unknown_claim_evidence_ref",
                    "assertion_index": index,
                    "category": category,
                    "evidence_refs": unknown_refs,
                }
            )
        category_refs = {
            str(value).strip()
            for value in (refs_by_category.get(category) or [])
            if str(value).strip()
        }
        if category in {
            "service_availability",
            "schedule_availability",
        } and not refs.intersection(category_refs):
            violations.append(
                {
                    "type": "availability_claim_missing_current_evidence",
                    "assertion_index": index,
                    "category": category,
                }
            )
        if category == "service_availability" and service_scopes_by_ref:
            allowed_service_scopes = {
                (
                    str(scope.get("scope_ref") or "").strip(),
                    str(scope.get("outcome") or "").strip(),
                )
                for ref in refs
                for scope in (service_scopes_by_ref.get(ref) or [])
                if isinstance(scope, dict)
                and str(scope.get("scope_ref") or "").strip()
                and str(scope.get("outcome") or "").strip()
            }
            if not declared_service_scopes:
                violations.append(
                    {
                        "type": "service_claim_missing_query_area_scope",
                        "assertion_index": index,
                        "category": category,
                    }
                )
            unknown_service_scopes = sorted(
                declared_service_scopes - allowed_service_scopes
            )
            if unknown_service_scopes:
                violations.append(
                    {
                        "type": "unauthorized_service_query_area_scope",
                        "assertion_index": index,
                        "category": category,
                        "service_area_claims": [
                            {
                                "scope_ref": scope_ref,
                                "outcome": outcome,
                            }
                            for scope_ref, outcome in unknown_service_scopes
                        ],
                    }
                )
            if (
                provider_owned_service_summary_present
                and assertion.get("response_unit_indexes")
            ):
                violations.append(
                    {
                        "type": (
                            "service_availability_prose_duplicates_"
                            "provider_surface"
                        ),
                        "assertion_index": index,
                        "category": category,
                        "response_unit_indexes": list(
                            assertion.get("response_unit_indexes") or []
                        )[:8],
                    }
                )
        if category == "faq_facts" and not refs.intersection(category_refs):
            violations.append(
                {
                    "type": "faq_claim_missing_current_evidence",
                    "assertion_index": index,
                    "category": category,
                }
            )
        if category == "brand_facts":
            allowed_brand_fields = {
                str(field).strip()
                for ref in refs
                for field in (brand_fields_by_ref.get(ref) or [])
                if str(field).strip()
            }
            if not fact_fields:
                violations.append(
                    {
                        "type": "brand_claim_missing_fact_fields",
                        "assertion_index": index,
                    }
                )
            unknown_fields = sorted(
                fact_fields - allowed_brand_fields
            )
            if unknown_fields:
                violations.append(
                    {
                        "type": "unauthorized_brand_fact_fields",
                        "assertion_index": index,
                        "fact_fields": unknown_fields,
                        "allowed_fact_fields": sorted(
                            allowed_brand_fields
                        ),
                    }
                )
            if (
                "gulong_guarantee.coverage" in fact_fields
                and "gulong_guarantee.conditions"
                in allowed_brand_fields
                and "gulong_guarantee.conditions" not in fact_fields
            ):
                violations.append(
                    {
                        "type": (
                            "gulong_coverage_missing_published_conditions"
                        ),
                        "assertion_index": index,
                    }
                )
    return violations


def _final_composer_voice_contract_violations(
    model_text: str,
    *,
    first_turn_intro_context: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Require composer continuity when runtime prepends the first-turn intro."""

    intro = (
        first_turn_intro_context
        if isinstance(first_turn_intro_context, dict)
        else {}
    )
    units = _parse_structured_response_units(model_text) or []
    violations: List[Dict[str, Any]] = []
    if intro.get("model_will_compose"):
        first_unit = next(
            (unit for unit in units if isinstance(unit, dict)),
            {},
        )
        if not _structured_response_starts_with_nonempty_text([first_unit]):
            violations.append(
                {
                    "type": "first_turn_model_opening_missing_before_surface",
                    "instruction": (
                        "Write one complete natural first-turn opening text unit "
                        "before any renderer surface. "
                        "Choose the greeting, acknowledgement, answer, tone, and "
                        "wording for this customer; do not copy a fixed script."
                    ),
                }
            )
    elif intro.get("runtime_will_prepend"):
        first_text = next(
            (
                str((unit.get("content") or {}).get("text") or "").strip()
                for unit in units
                if isinstance(unit, dict)
                and unit.get("type") == "text"
                and str((unit.get("content") or {}).get("text") or "").strip()
            ),
            "",
        )
        if re.match(
            r"^(?:hi|hello|good day|welcome)(?:\b|[!.?,])",
            first_text,
            flags=re.IGNORECASE,
        ):
            violations.append(
                {
                    "type": "duplicate_greeting_after_runtime_intro",
                    "instruction": (
                        "Runtime already prepends the welcome bubble. Remove the "
                        "composer greeting and continue directly with the answer."
                    ),
                }
            )

    customer_text = "\n".join(
        str((unit.get("content") or {}).get("text") or "").strip()
        for unit in units
        if isinstance(unit, dict) and unit.get("type") == "text"
    )
    search_intermediary_pattern = (
        r"\b(?:may\s+nakita|nakahanap)\s+(?:po\s+)?"
        r"(?:ako(?:ng)?|kami(?:ng)?|tayo(?:ng)?)\b|"
        r"\b(?:i|we)\s+found\b"
    )
    if re.search(search_intermediary_pattern, customer_text, flags=re.IGNORECASE):
        violations.append(
            {
                "type": "search_intermediary_brand_voice",
                "instruction": (
                    "Rewrite as a Gulong.ph representative: say what we have "
                    "or offer using natural kami/tayo/natin wording, or state "
                    "the useful result directly. Do not say that you or the "
                    "team found the routine catalog or service result."
                ),
            }
        )
    return violations


def _final_composer_interaction_contract_violations(
    model_text: str,
    interaction_packet: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Validate only the typed decision, never the customer's response wording."""

    if not interaction_packet:
        return []
    validation = validate_interaction_decision(
        interaction_packet,
        _parse_structured_interaction_decision(model_text),
    )
    if validation.get("status") != "valid":
        return [
            {
                "type": "invalid_interaction_decision",
                "validation_reasons": list(
                    validation.get("validation_reasons") or []
                ),
            }
        ]
    if validation.get("needs_clarification"):
        units = _parse_structured_response_units(model_text) or []
        return [
            {
                "type": "surface_not_allowed_while_clarifying",
                "unit_index": index,
                "unit_type": str(unit.get("type") or "").strip(),
            }
            for index, unit in enumerate(units)
            if str(unit.get("type") or "").strip() != "text"
        ]
    return []


def _final_composer_service_action_contract_violations(
    response_units: Optional[Sequence[Dict[str, Any]]],
    *,
    validated_installation_context: Mapping[str, Any],
    customer_turn_plan: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Reject schedule mutation claims when the turn only validated a slot.

    This is a side-effect authorization check, not a conversational style
    evaluator. A validated slot is read-only evidence for order review. Only an
    explicitly authorized order submission may let the composer describe the
    schedule, appointment, or installation as booked, reserved, secured, or
    confirmed.
    """

    if not response_units or not validated_installation_context:
        return []
    if "submit_order" in set(
        customer_turn_plan.get("authorized_side_effects") or []
    ):
        return []

    safe_read_only_markers = (
        "not confirmed",
        "not yet confirmed",
        "not booked",
        "not reserved",
        "not secured",
        "hindi pa confirmed",
        "hindi pa booked",
        "hindi pa reserved",
        "for order review",
        "for review",
        "para sa order review",
    )
    commitment_pattern = (
        r"\b(?:confirmed|booked|reserved|secured|"
        r"na-confirm|na-book|naka-book|na-reserve)\b"
    )
    service_context_pattern = (
        r"\b(?:slot|schedule|appointment|installation|"
        r"installation\s+partner)\b"
    )
    for index, unit in enumerate(response_units):
        if str(unit.get("type") or "").strip() != "text":
            continue
        content = unit.get("content") if isinstance(unit.get("content"), dict) else {}
        text = str(content.get("text") or "").strip()
        if not text:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            lowered = sentence.casefold().strip()
            if not lowered or any(marker in lowered for marker in safe_read_only_markers):
                continue
            if (
                re.search(commitment_pattern, lowered)
                and re.search(service_context_pattern, lowered)
            ):
                return [
                    {
                        "type": "unauthorized_schedule_mutation_claim",
                        "unit_index": index,
                        "instruction": (
                            "The selected schedule, appointment, or installation "
                            "is validated only for order review. Describe the "
                            "customer's preferred slot as selected or available, "
                            "and do not imply that the booking is complete."
                        ),
                    }
                ]
    return []


def _interaction_packet_requires_clarification_only(
    packet: Mapping[str, Any],
) -> bool:
    """Return whether runtime legality permits only a no-state clarification."""

    if not packet:
        return False
    allowed = [
        str(value or "").strip()
        for value in packet.get("allowed_model_interpretations") or []
        if str(value or "").strip()
    ]
    return allowed == ["clarify"]


def _interaction_clarification_response(
    packet: Mapping[str, Any],
    *,
    decision: Mapping[str, Any],
) -> str:
    """Return the last-resort safe response after composer repair also fails."""

    labels = [
        str(event.get("label") or event.get("choice_ref") or "").strip()
        for event in packet.get("events") or []
        if isinstance(event, Mapping)
    ]
    labels = list(dict.fromkeys(label for label in labels if label))[-3:]
    choices = " or ".join(labels)
    if choices:
        text = (
            f"I noticed more than one choice: {choices}. "
            "Which one should I use for the next step?"
        )
    else:
        text = "Which of the choices you tapped should I use for the next step?"
    return json.dumps(
        {
            "interaction_decision": dict(decision),
            "response_units": [
                {"type": "text", "content": {"text": text}},
            ],
        },
        ensure_ascii=False,
    )


def _renderer_owned_input_surface_contract(
    tool_results: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return a structural contract for a surface that owns the next input."""

    surfaces = _final_composer_presentation_surfaces(tool_results)
    active = next(
        (
            surface
            for surface in surfaces
            if surface.get("type") == "service_no_match"
            and surface.get("renderer_owns_next_input")
        ),
        {},
    )
    active_ref = str(active.get("surface_ref") or "").strip()
    if not active_ref:
        return {}
    return {
        "active_surface_ref": active_ref,
        "deferred_surface_refs": [
            str(surface.get("surface_ref") or "").strip()
            for surface in surfaces
            if str(surface.get("surface_ref") or "").strip()
            and str(surface.get("surface_ref") or "").strip() != active_ref
        ],
        "next_input": str(active.get("renderer_next_input") or "").strip(),
    }


def _final_composer_request_coverage_contract_violations(
    model_text: str,
    response_units: Optional[Sequence[Dict[str, Any]]],
    *,
    customer_turn_plan: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Validate typed request coverage without judging customer-facing prose."""

    obligations = [
        item
        for item in (customer_turn_plan or {}).get("request_obligations") or []
        if isinstance(item, dict)
        and str(item.get("obligation_id") or "").strip()
    ]
    if not obligations:
        return []
    payload = _parse_structured_final_response_payload(model_text)
    coverage_rows = [
        item
        for item in payload.get("request_coverage") or []
        if isinstance(item, dict)
    ]
    rows_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for row in coverage_rows:
        obligation_id = str(row.get("obligation_id") or "").strip()
        if obligation_id:
            rows_by_id.setdefault(obligation_id, []).append(row)

    units = list(response_units or [])
    rendered_surface_refs = {
        str((unit.get("content") or {}).get("surface_ref") or "").strip()
        for unit in units
        if isinstance(unit, dict)
        and str(unit.get("type") or "").strip() == "render_surface"
        and str((unit.get("content") or {}).get("surface_ref") or "").strip()
    }
    expected_ids = {
        str(item.get("obligation_id") or "").strip() for item in obligations
    }
    violations: List[Dict[str, Any]] = []
    for obligation in obligations:
        obligation_id = str(obligation.get("obligation_id") or "").strip()
        rows = rows_by_id.get(obligation_id) or []
        if len(rows) != 1:
            violations.append(
                {
                    "type": (
                        "request_coverage_missing"
                        if not rows
                        else "request_coverage_duplicated"
                    ),
                    "obligation_id": obligation_id,
                }
            )
            continue
        row = rows[0]
        expected_disposition = str(
            obligation.get("expected_disposition") or "answered"
        ).strip()
        actual_disposition = str(row.get("disposition") or "").strip()
        if actual_disposition != expected_disposition:
            violations.append(
                {
                    "type": "request_coverage_disposition_mismatch",
                    "obligation_id": obligation_id,
                    "expected_disposition": expected_disposition,
                    "disposition": actual_disposition,
                }
            )
            continue
        indexes = [
            value
            for value in row.get("response_unit_indexes") or []
            if isinstance(value, int) and not isinstance(value, bool)
        ]
        mapped_units = [units[index] for index in indexes if 0 <= index < len(units)]
        mapped_text = any(
            str(unit.get("type") or "").strip() == "text"
            and str((unit.get("content") or {}).get("text") or "").strip()
            for unit in mapped_units
            if isinstance(unit, dict)
        )
        mapped_surface_refs = {
            str(value or "").strip()
            for value in row.get("surface_refs") or []
            if str(value or "").strip()
        }
        authorized_surface_refs = {
            str(value or "").strip()
            for value in obligation.get("authorized_surface_refs") or []
            if str(value or "").strip()
        }
        modes = {
            str(value or "").strip()
            for value in obligation.get("required_response_modes") or []
            if str(value or "").strip()
        }
        if "text" in modes and not mapped_text:
            violations.append(
                {
                    "type": "request_coverage_text_mapping_invalid",
                    "obligation_id": obligation_id,
                }
            )
        if "surface" in modes and not (
            mapped_surface_refs
            and mapped_surface_refs.issubset(authorized_surface_refs)
            and mapped_surface_refs.issubset(rendered_surface_refs)
        ):
            violations.append(
                {
                    "type": "request_coverage_surface_mapping_invalid",
                    "obligation_id": obligation_id,
                    "authorized_surface_refs": sorted(authorized_surface_refs),
                }
            )
    for extra_id in sorted(set(rows_by_id) - expected_ids):
        violations.append(
            {
                "type": "unknown_request_coverage_obligation",
                "obligation_id": extra_id,
            }
        )
    return violations


def _final_composer_renderer_contract_violations(
    response_units: Optional[Sequence[Dict[str, Any]]],
    tool_results: Sequence[Dict[str, Any]],
    *,
    customer_turn_plan: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Validate response-unit order without inspecting conversational wording."""

    if customer_turn_plan:
        valid_refs = {
            str(surface.get("surface_ref") or "").strip()
            for surface in customer_turn_plan.get("available_surfaces") or []
            if isinstance(surface, dict)
            and str(surface.get("surface_ref") or "").strip()
        }
        counts: Dict[str, int] = {}
        violations: List[Dict[str, Any]] = []
        resolvable_unit_count = 0
        for index, unit in enumerate(response_units or []):
            unit_type = str(unit.get("type") or "").strip()
            content = (
                unit.get("content") if isinstance(unit.get("content"), dict) else {}
            )
            if unit_type == "text":
                if str(content.get("text") or "").strip():
                    resolvable_unit_count += 1
                else:
                    violations.append(
                        {"type": "empty_text_response_unit", "unit_index": index}
                    )
                continue
            if unit_type == "image":
                if str(content.get("url") or content.get("image_ref") or "").strip():
                    resolvable_unit_count += 1
                else:
                    violations.append(
                        {"type": "empty_image_response_unit", "unit_index": index}
                    )
                continue
            if unit_type != "render_surface":
                violations.append(
                    {
                        "type": "unsupported_response_unit_type",
                        "unit_index": index,
                        "unit_type": unit_type,
                    }
                )
                continue
            surface_ref = str(content.get("surface_ref") or "").strip()
            if surface_ref not in valid_refs:
                violations.append(
                    {
                        "type": "unknown_renderer_surface",
                        "unit_index": index,
                        "surface_ref": surface_ref,
                    }
                )
                continue
            counts[surface_ref] = counts.get(surface_ref, 0) + 1
            resolvable_unit_count += 1
        if not response_units:
            violations.append({"type": "empty_response_units"})
        if not resolvable_unit_count:
            violations.append({"type": "no_resolvable_response_unit"})
        for surface_ref, count in sorted(counts.items()):
            if count > 1:
                violations.append(
                    {
                        "type": "renderer_surface_duplicated",
                        "surface_ref": surface_ref,
                        "count": count,
                    }
                )
        for surface in customer_turn_plan.get("available_surfaces") or []:
            if not isinstance(surface, dict) or not bool(surface.get("required")):
                continue
            surface_ref = str(surface.get("surface_ref") or "").strip()
            if surface_ref and not counts.get(surface_ref):
                violations.append(
                    {
                        "type": "required_renderer_surface_missing",
                        "surface_ref": surface_ref,
                        "response_role": str(
                            surface.get("response_role") or "direct_answer"
                        ),
                    }
                )
        violations.extend(
            _supporting_replacement_text_contract_violations(
                response_units or [],
                customer_turn_plan=customer_turn_plan,
                rendered_surface_counts=counts,
            )
        )
        required_layers = {
            str(surface.get("decision_layer") or "").strip()
            for surface in customer_turn_plan.get("available_surfaces") or []
            if isinstance(surface, dict)
            and counts.get(
                str(surface.get("surface_ref") or "").strip(),
                0,
            )
            and not bool(surface.get("supporting_context"))
            and bool(surface.get("required"))
            and str(surface.get("decision_layer") or "").strip()
        }
        optional_layers = {
            str(surface.get("decision_layer") or "").strip()
            for surface in customer_turn_plan.get("available_surfaces") or []
            if isinstance(surface, dict)
            and counts.get(
                str(surface.get("surface_ref") or "").strip(),
                0,
            )
            and not bool(surface.get("supporting_context"))
            and not bool(surface.get("required"))
            and str(surface.get("decision_layer") or "").strip()
        }
        competing_optional_layers = (
            optional_layers - required_layers if required_layers else optional_layers
        )
        if len(competing_optional_layers) > (0 if required_layers else 1):
            violations.append(
                {
                    "type": "multiple_customer_decision_layers",
                    "decision_layers": sorted(
                        required_layers | competing_optional_layers
                    ),
                }
            )
        return violations

    contract = _renderer_owned_input_surface_contract(tool_results)
    if not contract or response_units is None:
        return []
    active_ref = contract["active_surface_ref"]
    deferred_refs = set(contract.get("deferred_surface_refs") or [])
    active_indexes = [
        index
        for index, unit in enumerate(response_units)
        if str(unit.get("type") or "").strip() == "render_surface"
        and str((unit.get("content") or {}).get("surface_ref") or "").strip()
        == active_ref
    ]
    violations: List[Dict[str, Any]] = []
    if not active_indexes:
        violations.append(
            {
                "type": "required_renderer_surface_missing",
                "surface_ref": active_ref,
            }
        )
        active_index = len(response_units)
    else:
        active_index = active_indexes[0]
    for index, unit in enumerate(response_units):
        unit_type = str(unit.get("type") or "").strip()
        content = unit.get("content") if isinstance(unit.get("content"), dict) else {}
        if unit_type == "render_surface":
            surface_ref = str(content.get("surface_ref") or "").strip()
            if surface_ref in deferred_refs:
                violations.append(
                    {
                        "type": "deferred_surface_rendered",
                        "unit_index": index,
                        "surface_ref": surface_ref,
                    }
                )
        elif index > active_index and unit_type in {"text", "image"}:
            violations.append(
                {
                    "type": "unit_after_renderer_owned_next_input",
                    "unit_index": index,
                    "unit_type": unit_type,
                    "active_surface_ref": active_ref,
                }
            )
    return violations


def _supporting_replacement_text_contract_violations(
    response_units: Sequence[Dict[str, Any]],
    *,
    customer_turn_plan: Mapping[str, Any],
    rendered_surface_counts: Mapping[str, int],
) -> List[Dict[str, Any]]:
    """Prevent an automatic warranty replacement from creating a second spiel.

    This guard is intentionally narrow: it runs only when a rendered surface is
    explicitly typed ``supporting_replacement`` and the current turn has no
    grounded warranty FAQ obligation. It does not grade general relevance or
    conversational prose.
    """

    supporting_refs = {
        str(surface.get("surface_ref") or "").strip()
        for surface in customer_turn_plan.get("available_surfaces") or []
        if isinstance(surface, Mapping)
        and str(surface.get("response_role") or "").strip()
        == "supporting_replacement"
        and rendered_surface_counts.get(
            str(surface.get("surface_ref") or "").strip(),
            0,
        )
    }
    if not supporting_refs:
        return []

    progression = (
        customer_turn_plan.get("progression_context")
        if isinstance(customer_turn_plan.get("progression_context"), Mapping)
        else {}
    )
    required_faq_answers = progression.get("required_faq_fact_answers") or []
    warranty_answer_required = any(
        re.search(
            r"\b(?:warranty|guarantee|tire protection|tpp|garantiya)\b",
            " ".join(
                str(answer.get(key) or "")
                for key in (
                    "faq_id",
                    "domain",
                    "policy_type",
                    "applicability",
                    "authored_answer",
                )
            ),
            flags=re.IGNORECASE,
        )
        for answer in required_faq_answers
        if isinstance(answer, Mapping)
    )
    duplicate_pattern = (
        re.compile(
            r"(?:\b(?:gusto|would you like|do you want|shall i|pwede|"
            r"check|i-check|tingnan|view|learn more)\b.{0,60}"
            r"\b(?:promo|warranty|coverage|details|mechanics|nito)\b)|"
            r"(?:\b(?:promo|warranty|coverage)\s+(?:details|mechanics)\b"
            r".{0,60}\b(?:gusto|check|i-check|tingnan|view)\b)",
            flags=re.IGNORECASE,
        )
        if warranty_answer_required
        else re.compile(
            r"\b(?:double warranty|warranty|guarantee|tire protection plan|tpp|garantiya)\b",
            flags=re.IGNORECASE,
        )
    )
    violations: List[Dict[str, Any]] = []
    for index, unit in enumerate(response_units or []):
        if not isinstance(unit, Mapping) or str(unit.get("type") or "") != "text":
            continue
        content = unit.get("content") if isinstance(unit.get("content"), Mapping) else {}
        text = str(content.get("text") or "").strip()
        if text and duplicate_pattern.search(text):
            violations.append(
                {
                    "type": "duplicate_supporting_replacement_prose",
                    "unit_index": index,
                    "supporting_surface_refs": sorted(supporting_refs),
                    "instruction": (
                        "Remove the separate warranty explanation or CTA. The "
                        "required supporting replacement already carries that "
                        "information; keep text focused on the product answer "
                        "and its one active next step."
                    ),
                }
            )
    return violations


def _final_composer_required_faq_fact_contract_violations(
    response_units: Sequence[Dict[str, Any]],
    *,
    customer_turn_plan: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Require provider-typed FAQ facts while allowing prose variation."""

    progression = (
        customer_turn_plan.get("progression_context")
        if isinstance(customer_turn_plan.get("progression_context"), Mapping)
        else {}
    )
    required_answers = progression.get("required_faq_fact_answers") or []
    visible_text = "\n".join(
        str(
            (
                unit.get("content")
                if isinstance(unit.get("content"), Mapping)
                else {}
            ).get("text")
            or ""
        )
        for unit in response_units or []
        if isinstance(unit, Mapping)
        and str(unit.get("type") or "").strip() == "text"
    )
    normalized_text = " ".join(visible_text.casefold().split())
    violations: List[Dict[str, Any]] = []
    for answer in required_answers:
        if not isinstance(answer, Mapping):
            continue
        evidence_ref = str(answer.get("evidence_ref") or "").strip()
        for fact in answer.get("required_answer_facts") or []:
            if not isinstance(fact, Mapping):
                continue
            regex = str(fact.get("regex") or "").strip()
            all_terms = [
                " ".join(str(term or "").casefold().split())
                for term in fact.get("all_terms") or []
                if str(term or "").strip()
            ]
            matched = bool(
                regex
                and re.search(regex, visible_text, flags=re.IGNORECASE)
            ) or bool(
                all_terms
                and all(term in normalized_text for term in all_terms)
            )
            if matched:
                continue
            violations.append(
                {
                    "type": "answer_goal_required_faq_fact_missing",
                    "fact_id": str(fact.get("fact_id") or "").strip(),
                    "evidence_ref": evidence_ref,
                    "canonical_text": str(
                        fact.get("canonical_text") or ""
                    ).strip(),
                    "instruction": (
                        "Preserve this provider-required FAQ fact in natural "
                        "customer-facing prose and cite its FAQ evidence ref."
                    ),
                }
            )
    return violations


def _sanitize_duplicate_supporting_replacement_prose(
    model_text: str,
    response_units: Sequence[Dict[str, Any]],
    *,
    customer_turn_plan: Mapping[str, Any],
) -> Tuple[str, List[Dict[str, Any]], int]:
    """Remove only duplicate supporting-copy sentences after model repair.

    The supporting replacement surface already owns the warranty/promo copy.
    This deterministic final guard is intentionally bounded to text units that
    the renderer contract has already identified as duplicates. It preserves
    the unit indexes used by request coverage and declines to rewrite a unit
    when no non-duplicate sentence would remain.
    """

    units = [deepcopy(unit) for unit in response_units or []]
    rendered_counts: Dict[str, int] = {}
    for unit in units:
        if not isinstance(unit, Mapping) or str(unit.get("type") or "") != "render_surface":
            continue
        content = unit.get("content") if isinstance(unit.get("content"), Mapping) else {}
        surface_ref = str(content.get("surface_ref") or "").strip()
        if surface_ref:
            rendered_counts[surface_ref] = rendered_counts.get(surface_ref, 0) + 1
    violations = _supporting_replacement_text_contract_violations(
        units,
        customer_turn_plan=customer_turn_plan,
        rendered_surface_counts=rendered_counts,
    )
    target_indexes = {
        int(violation["unit_index"])
        for violation in violations
        if isinstance(violation, Mapping)
        and isinstance(violation.get("unit_index"), int)
    }
    removed = 0
    for index in sorted(target_indexes):
        if index < 0 or index >= len(units):
            continue
        unit = units[index]
        content = unit.get("content") if isinstance(unit.get("content"), Mapping) else {}
        original_text = str(content.get("text") or "").strip()
        parts = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+|\n+", original_text)
            if part.strip()
        ]
        kept: List[str] = []
        for part in parts:
            part_violations = _supporting_replacement_text_contract_violations(
                [{"type": "text", "content": {"text": part}}],
                customer_turn_plan=customer_turn_plan,
                rendered_surface_counts=rendered_counts,
            )
            if part_violations:
                removed += 1
            else:
                kept.append(part)
        if not kept:
            return model_text, [deepcopy(unit) for unit in response_units or []], 0
        unit["content"] = {**dict(content), "text": " ".join(kept)}

    if not removed:
        return model_text, units, 0
    payload = _parse_structured_final_response_payload(model_text)
    if not payload:
        return model_text, [deepcopy(unit) for unit in response_units or []], 0
    payload["response_units"] = units
    return json.dumps(payload, ensure_ascii=False), units, removed


def _complete_required_supporting_replacement_surfaces(
    model_text: str,
    response_units: Sequence[Dict[str, Any]],
    *,
    customer_turn_plan: Mapping[str, Any],
) -> Tuple[str, List[Dict[str, Any]], List[str]]:
    """Append omitted renderer-owned required supporting surfaces.

    Supporting replacements are deterministic output owned by the renderer,
    not a model-selected customer decision. Completing only exact authorized
    refs avoids a second model call while preserving the model's prose and
    active decision surface.
    """

    units = [deepcopy(unit) for unit in response_units or []]
    rendered_refs = {
        str((unit.get("content") or {}).get("surface_ref") or "").strip()
        for unit in units
        if isinstance(unit, Mapping)
        and str(unit.get("type") or "").strip() == "render_surface"
        and isinstance(unit.get("content"), Mapping)
        and str((unit.get("content") or {}).get("surface_ref") or "").strip()
    }
    missing_refs: List[str] = []
    for surface in customer_turn_plan.get("available_surfaces") or []:
        if not isinstance(surface, Mapping):
            continue
        surface_ref = str(surface.get("surface_ref") or "").strip()
        if (
            surface_ref
            and surface_ref not in rendered_refs
            and surface.get("required") is True
            and str(surface.get("response_role") or "").strip()
            == "supporting_replacement"
        ):
            missing_refs.append(surface_ref)
            rendered_refs.add(surface_ref)
            units.append(
                {
                    "type": "render_surface",
                    "content": {"surface_ref": surface_ref},
                }
            )
    if not missing_refs:
        return model_text, units, []
    payload = _parse_structured_final_response_payload(model_text)
    if not payload:
        return model_text, [deepcopy(unit) for unit in response_units or []], []
    payload["response_units"] = units
    return json.dumps(payload, ensure_ascii=False), units, missing_refs


def _renderer_decision_layer_repair_contract(
    response_units: Optional[Sequence[Dict[str, Any]]],
    customer_turn_plan: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Tell model repair which already-rendered decision layer remains active."""

    if not customer_turn_plan:
        return {}
    planned_by_ref = {
        str(surface.get("surface_ref") or "").strip(): surface
        for surface in customer_turn_plan.get("available_surfaces") or []
        if isinstance(surface, dict)
        and str(surface.get("surface_ref") or "").strip()
    }
    required_layers: List[str] = []
    optional_layers: List[str] = []
    required_surface_refs: List[str] = []
    for unit in response_units or []:
        if str(unit.get("type") or "").strip() != "render_surface":
            continue
        content = unit.get("content") if isinstance(unit.get("content"), dict) else {}
        planned = planned_by_ref.get(
            str(content.get("surface_ref") or "").strip()
        ) or {}
        if planned.get("supporting_context"):
            continue
        layer = str(planned.get("decision_layer") or "").strip()
        surface_ref = str(content.get("surface_ref") or "").strip()
        if planned.get("required"):
            if layer and layer not in required_layers:
                required_layers.append(layer)
            if surface_ref and surface_ref not in required_surface_refs:
                required_surface_refs.append(surface_ref)
        elif layer and layer not in optional_layers:
            optional_layers.append(layer)
    ordered_layers = [*required_layers, *optional_layers]
    if not ordered_layers:
        return {}
    active_layer = required_layers[0] if required_layers else optional_layers[0]
    return _compact_unit(
        {
            "active_decision_layer": active_layer,
            "required_direct_answer_layers": required_layers,
            "required_surface_refs": required_surface_refs,
            "deferred_decision_layers": [
                layer
                for layer in optional_layers
                if layer not in required_layers and layer != active_layer
            ],
            "cta_rule": "ask_only_for_the_active_decision_layer",
        }
    )


def _enforce_renderer_owned_unit_contract(
    response_units: Sequence[Dict[str, Any]],
    tool_results: Sequence[Dict[str, Any]],
    *,
    customer_turn_plan: Optional[Dict[str, Any]] = None,
    fallback_response_units: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Keep grounded pretext plus the renderer-owned input surface as fallback."""

    if customer_turn_plan:
        planned_by_ref = {
            str(surface.get("surface_ref") or "").strip(): surface
            for surface in customer_turn_plan.get("available_surfaces") or []
            if isinstance(surface, dict)
            and str(surface.get("surface_ref") or "").strip()
        }
        def _filtered(candidate_units: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
            output: List[Dict[str, Any]] = []
            rendered_refs: set[str] = set()
            active_decision_layer = ""
            for unit in candidate_units or []:
                unit_type = str(unit.get("type") or "").strip()
                content = (
                    unit.get("content")
                    if isinstance(unit.get("content"), dict)
                    else {}
                )
                if unit_type == "text":
                    if str(content.get("text") or "").strip():
                        output.append(deepcopy(unit))
                    continue
                if unit_type == "image":
                    if str(content.get("url") or content.get("image_ref") or "").strip():
                        output.append(deepcopy(unit))
                    continue
                if unit_type != "render_surface":
                    continue
                surface_ref = str(content.get("surface_ref") or "").strip()
                planned = planned_by_ref.get(surface_ref)
                if not planned or surface_ref in rendered_refs:
                    continue
                decision_layer = str(
                    planned.get("decision_layer") or ""
                ).strip()
                supporting_context = bool(planned.get("supporting_context"))
                required = bool(planned.get("required"))
                if (
                    decision_layer
                    and not supporting_context
                    and not required
                    and active_decision_layer
                    and decision_layer != active_decision_layer
                ):
                    continue
                if decision_layer and not supporting_context and not active_decision_layer:
                    active_decision_layer = decision_layer
                output.append(deepcopy(unit))
                rendered_refs.add(surface_ref)
            return output

        output = _filtered(response_units or [])
        if not output:
            output = _filtered(fallback_response_units or [])
        rendered_refs = {
            str((unit.get("content") or {}).get("surface_ref") or "").strip()
            for unit in output
            if isinstance(unit, dict)
            and str(unit.get("type") or "").strip() == "render_surface"
        }
        for planned in customer_turn_plan.get("available_surfaces") or []:
            if not isinstance(planned, dict) or not bool(planned.get("required")):
                continue
            surface_ref = str(planned.get("surface_ref") or "").strip()
            if not surface_ref or surface_ref in rendered_refs:
                continue
            output.append(
                {
                    "type": "render_surface",
                    "content": {"surface_ref": surface_ref},
                }
            )
            rendered_refs.add(surface_ref)
        return output

    contract = _renderer_owned_input_surface_contract(tool_results)
    if not contract:
        return [deepcopy(unit) for unit in response_units or []]
    active_ref = contract["active_surface_ref"]
    deferred_refs = set(contract.get("deferred_surface_refs") or [])
    output: List[Dict[str, Any]] = []
    active_seen = False
    for unit in response_units or []:
        unit_type = str(unit.get("type") or "").strip()
        content = unit.get("content") if isinstance(unit.get("content"), dict) else {}
        if unit_type == "render_surface":
            surface_ref = str(content.get("surface_ref") or "").strip()
            if surface_ref in deferred_refs:
                continue
            if surface_ref == active_ref:
                if not active_seen:
                    output.append(deepcopy(unit))
                    active_seen = True
                continue
        if active_seen:
            continue
        output.append(deepcopy(unit))
    if not active_seen:
        output.append(
            {
                "type": "render_surface",
                "content": {"surface_ref": active_ref},
            }
        )
    return output


def _should_strip_midthread_greeting(
    *,
    current_user_message: str,
    recent_turns: Sequence[Dict[str, str]],
    active_working_memory: str,
) -> bool:
    if _customer_message_starts_with_greeting(current_user_message):
        return False
    return bool(recent_turns or str(active_working_memory or "").strip())


def _main_response_requires_voice_composer(
    *,
    current_user_message: str,
    model_text: str,
    recent_turns: Sequence[Dict[str, str]],
    active_working_memory: str,
) -> bool:
    """Route a greeting reset through model composition instead of deletion."""

    if not _should_strip_midthread_greeting(
        current_user_message=current_user_message,
        recent_turns=recent_turns,
        active_working_memory=active_working_memory,
    ):
        return False
    return _strip_leading_greeting(model_text) != str(model_text or "").lstrip()


def _customer_message_starts_with_greeting(text: str) -> bool:
    return bool(
        re.match(
            r"^\s*(hi|hello|hey|good\s*(?:morning|afternoon|evening|day)|magandang\s+(?:araw|umaga|hapon|gabi))\b",
            str(text or "").strip(),
            flags=re.IGNORECASE,
        )
    )


def _strip_leading_greeting(text: str) -> str:
    cleaned = str(text or "").lstrip()
    return re.sub(
        r"^(?:(?:hello|hi|hey)\b|good\s*(?:morning|afternoon|evening|day)\b|magandang\s+(?:araw|umaga|hapon|gabi)\b)"
        r"(?:\s+(?:po|boss|sir|ma'?am|mam))?[!.,\s:;-]*",
        "",
        cleaned,
        count=1,
        flags=re.IGNORECASE,
    ).lstrip()


def _render_structured_response_units(
    response_units: Sequence[Dict[str, Any]],
    active_surfaces: Sequence[Tuple[str, Dict[str, Any]]],
    *,
    strip_leading_greeting: bool = False,
    include_product_inclusions: bool = True,
    guard_events: Optional[List[Dict[str, Any]]] = None,
    render_runtime_surfaces: bool = True,
    append_unrendered_surfaces: bool = True,
) -> str:
    surface_by_ref = _surface_index(active_surfaces)
    include_product_inclusions = bool(
        include_product_inclusions
        and not _surfaces_include_warranty_promo(active_surfaces)
    )
    rendered_surface_refs: set[str] = set()
    rendered_surface_dedupe_keys: set[str] = set()
    parts: List[str] = []
    for unit in response_units or []:
        unit_type = str(unit.get("type") or "").strip().lower()
        content = unit.get("content") if isinstance(unit.get("content"), dict) else {}
        if unit_type == "text":
            text = _sanitize_structured_text_unit(
                str(content.get("text") or ""),
                active_surfaces,
                guard_events=guard_events,
            )
            if strip_leading_greeting and not parts:
                before_strip = text
                text = _strip_leading_greeting(text)
                if text != before_strip:
                    _append_response_guard_event(
                        guard_events,
                        type="structured_text_transformed",
                        reason="mid_thread_greeting_removed",
                    )
            if text:
                parts.append(text)
            continue
        if unit_type == "render_surface":
            if not render_runtime_surfaces:
                _append_response_guard_event(
                    guard_events,
                    type="runtime_surface_suppressed",
                    reason="interaction_clarification_required",
                )
                continue
            surface_ref = str(content.get("surface_ref") or "").strip()
            surface_entry = surface_by_ref.get(surface_ref)
            if surface_entry:
                canonical_ref = str(surface_entry[1].get("surface_ref") or surface_ref).strip()
                dedupe_key = _runtime_surface_dedupe_key(surface_entry[0], surface_entry[1])
                if canonical_ref and canonical_ref in rendered_surface_refs:
                    continue
                if dedupe_key and dedupe_key in rendered_surface_dedupe_keys:
                    continue
                body = _render_runtime_surface_body(
                    surface_entry[0],
                    surface_entry[1],
                    include_product_inclusions=include_product_inclusions,
                )
                if body:
                    parts.append(body)
                    rendered_surface_refs.add(canonical_ref or surface_ref)
                    if dedupe_key:
                        rendered_surface_dedupe_keys.add(dedupe_key)
            continue
        if unit_type == "image":
            image_text = _render_image_response_unit(content)
            if image_text:
                parts.append(image_text)

    if not render_runtime_surfaces or not append_unrendered_surfaces:
        return "\n\n".join(
            part for part in parts if str(part or "").strip()
        ).strip()

    for surface_type, surface in sorted(active_surfaces, key=lambda item: int(item[1].get("order") or 0)):
        surface_ref = str(surface.get("surface_ref") or "").strip()
        dedupe_key = _runtime_surface_dedupe_key(surface_type, surface)
        if surface_ref and surface_ref in rendered_surface_refs:
            continue
        if dedupe_key and dedupe_key in rendered_surface_dedupe_keys:
            continue
        body = _render_runtime_surface_body(
            surface_type,
            surface,
            include_product_inclusions=include_product_inclusions,
        )
        if body:
            parts.append(body)
            if surface_ref:
                rendered_surface_refs.add(surface_ref)
            if dedupe_key:
                rendered_surface_dedupe_keys.add(dedupe_key)
    return "\n\n".join(part for part in parts if str(part or "").strip()).strip()


def _surface_index(
    active_surfaces: Sequence[Tuple[str, Dict[str, Any]]],
) -> Dict[str, Tuple[str, Dict[str, Any]]]:
    index: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for surface_type, surface in active_surfaces or []:
        refs = _runtime_surface_refs(surface_type, surface)
        for ref in refs:
            normalized_ref = str(ref or "").strip()
            if normalized_ref:
                index[normalized_ref] = (surface_type, surface)
    return index


def _runtime_surface_refs(surface_type: str, surface: Dict[str, Any]) -> List[Any]:
    """Return parent and child refs that should resolve to the same surface."""

    refs: List[Any] = [surface.get("surface_ref")]
    full_result = surface.get("full_result") if isinstance(surface.get("full_result"), dict) else {}
    refs.extend([full_result.get("presentation_ref"), full_result.get("order_summary_ref"), full_result.get("payment_request_ref")])
    for card in surface.get("cards") or []:
        if not isinstance(card, dict):
            continue
        for key in [
            "card_ref",
            "item_ref",
            "product_id",
            "slug",
            "bucket_ref",
            "installation_partner_ref",
            "service_location_ref",
            "branch_id",
            "order_summary_ref",
        ]:
            value = card.get(key)
            if value not in (None, "", [], {}):
                refs.append(value)
        slot_refs = card.get("slot_refs")
        if isinstance(slot_refs, list):
            refs.extend(ref for ref in slot_refs if ref not in (None, "", [], {}))
    return refs


def _runtime_surface_dedupe_key(surface_type: str, surface: Dict[str, Any]) -> str:
    """Return a stable visible-content key for duplicate runtime surfaces."""

    key = str(surface.get("surface_dedupe_key") or "").strip()
    if key:
        return key
    if surface_type != "product":
        return ""
    return _product_surface_dedupe_key(surface.get("cards") or [])


def _product_surface_dedupe_key(cards: Sequence[Dict[str, Any]]) -> str:
    identities = [
        _product_surface_card_identity(card)
        for card in cards or []
        if isinstance(card, dict)
    ]
    identities = [identity for identity in identities if identity]
    if not identities:
        return ""
    return "product_cards:" + "|".join(sorted(identities))


def _product_surface_card_identity(card: Dict[str, Any]) -> str:
    identifier = ""
    for key in ["product_id", "slug", "item_ref", "card_ref"]:
        value = str(card.get(key) or "").strip()
        if value:
            identifier = f"{key}:{value.lower()}"
            break
    if not identifier:
        descriptor = "|".join(
            str(card.get(key) or "").strip().lower()
            for key in ["brand", "sku_model", "tire_size"]
            if str(card.get(key) or "").strip()
        )
        if not descriptor:
            return ""
        identifier = f"descriptor:{descriptor}"

    pricing_facts = card.get("pricing_facts") if isinstance(card.get("pricing_facts"), dict) else {}
    quantity = pricing_facts.get("quantity") or card.get("quantity")
    pricing_basis = pricing_facts.get("pricing_basis") or card.get("pricing_basis")
    payable_total = pricing_facts.get("payable_total")
    if payable_total in (None, ""):
        payable_total = card.get("total_price")
    pricing_parts = [
        f"qty:{quantity}" if quantity not in (None, "") else "",
        f"basis:{str(pricing_basis).strip().lower()}" if pricing_basis not in (None, "") else "",
        f"payable:{_surface_dedupe_money(payable_total)}" if payable_total not in (None, "") else "",
    ]
    pricing_key = "|".join(part for part in pricing_parts if part)
    return f"{identifier}|{pricing_key}" if pricing_key else identifier


def _surface_dedupe_money(value: Any) -> str:
    amount = _coerce_amount(value)
    if amount is None:
        return str(value or "").strip().lower()
    return f"{amount:.2f}"


def _sanitize_structured_text_unit(
    text: str,
    active_surfaces: Sequence[Tuple[str, Dict[str, Any]]],
    *,
    guard_events: Optional[List[Dict[str, Any]]] = None,
) -> str:
    cleaned = _drop_internal_runtime_leakage(str(text or "")).strip()
    markup_cleaned = _strip_customer_markup(cleaned).strip()
    if markup_cleaned != cleaned:
        _append_response_guard_event(
            guard_events,
            type="structured_text_transformed",
            reason="customer_markup_removed",
        )
        cleaned = markup_cleaned
    if not cleaned:
        if str(text or "").strip():
            _append_response_guard_event(
                guard_events,
                type="structured_text_unit_dropped",
                reason="internal_runtime_leakage",
            )
        return ""
    cleaned = _strip_renderer_owned_text(cleaned, active_surfaces).strip()
    if not cleaned:
        _append_response_guard_event(
            guard_events,
            type="structured_text_unit_dropped",
            reason="renderer_owned_duplicate_text",
        )
        return ""
    if len(cleaned) > 900:
        _append_response_guard_event(
            guard_events,
            type="structured_text_unit_dropped",
            reason="text_unit_too_long",
        )
        return ""
    if _has_internal_runtime_leakage(cleaned):
        _append_response_guard_event(
            guard_events,
            type="structured_text_unit_dropped",
            reason="internal_runtime_leakage",
        )
        return ""
    # Semantic conflicts are part of the structured composer contract and its
    # repair loop. The renderer only performs hygiene and exact surface-text
    # deduplication; it must not phrase-classify a whole model-authored unit and
    # silently delete its acknowledgement, explanation, or CTA.
    return _clean_structured_text(cleaned)


def _strip_renderer_owned_text(
    text: str,
    active_surfaces: Sequence[Tuple[str, Dict[str, Any]]],
) -> str:
    """Remove exact renderer-owned paragraphs/lines from model text units."""

    owned = _renderer_owned_text_units(active_surfaces)
    if not owned:
        return str(text or "")
    owned_list_identifiers = _renderer_owned_list_identifiers(active_surfaces)
    has_product_surface = any(
        surface_type == "product"
        for surface_type, _surface in active_surfaces or []
    )
    kept_paragraphs: List[str] = []
    for paragraph in re.split(r"\n\s*\n", str(text or "")):
        if not paragraph.strip():
            continue
        if _normalized_owned_text(paragraph) in owned:
            continue
        kept_lines = [
            line.rstrip()
            for line in paragraph.splitlines()
            if line.strip()
            and _normalized_owned_text(line) not in owned
            and not _is_exact_renderer_owned_list_line(
                line,
                owned_list_identifiers,
            )
            and not (
                has_product_surface
                and re.match(
                    r"^\s*(?:[-*â€¢]\s*)?(?:PHP|â‚±|₱)\s*[0-9]",
                    line,
                    flags=re.IGNORECASE,
                )
            )
        ]
        if kept_lines:
            kept_paragraphs.append("\n".join(kept_lines).strip())
    return "\n\n".join(part for part in kept_paragraphs if part.strip())


def _renderer_owned_text_units(active_surfaces: Sequence[Tuple[str, Dict[str, Any]]]) -> set[str]:
    owned: set[str] = set()
    for surface_type, surface in active_surfaces or []:
        body = _render_runtime_surface_body(surface_type, surface)
        for part in _split_renderer_owned_text(body):
            normalized = _normalized_owned_text(part)
            if normalized:
                owned.add(normalized)
        full_result = surface.get("full_result") if isinstance(surface.get("full_result"), dict) else {}
        for key in ["legend_text", "order_summary_block", "payment_instruction_block"]:
            normalized = _normalized_owned_text(full_result.get(key))
            if normalized:
                owned.add(normalized)
        for key in ("service_policy_notes", "suppressed_service_policy_notes"):
            for note in full_result.get(key) or []:
                if isinstance(note, dict):
                    normalized = _normalized_owned_text(note.get("text"))
                    if normalized:
                        owned.add(normalized)
    return owned


def _renderer_owned_list_identifiers(
    active_surfaces: Sequence[Tuple[str, Dict[str, Any]]],
) -> set[str]:
    """Return exact card identities used only for structural list dedupe."""

    identifiers: set[str] = set()
    for _surface_type, surface in active_surfaces or []:
        for card in surface.get("cards") or []:
            if not isinstance(card, dict):
                continue
            for key in ("sku_model", "title", "name", "display_name"):
                normalized = _normalized_owned_text(card.get(key))
                if len(normalized) >= 8:
                    identifiers.add(normalized)
    return identifiers


def _is_exact_renderer_owned_list_line(
    line: str,
    identifiers: set[str],
) -> bool:
    """Deduplicate only list/card rows containing an exact rendered identity."""

    if not identifiers or not re.match(r"^\s*(?:[-*â€¢]|\d+[.)])\s+", str(line or "")):
        return False
    normalized = _normalized_owned_text(line).replace("**", "")
    return any(identifier in normalized for identifier in identifiers)


def _split_renderer_owned_text(text: str) -> List[str]:
    parts: List[str] = []
    for paragraph in re.split(r"\n\s*\n", str(text or "")):
        if not paragraph.strip():
            continue
        parts.append(paragraph)
        parts.extend(line for line in paragraph.splitlines() if line.strip())
    return parts


def _normalized_owned_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _clean_structured_text(text: str) -> str:
    paragraphs: List[str] = []
    for part in re.split(r"\n\s*\n", str(text or "")):
        if not part.strip():
            continue
        if _looks_like_list_or_card(part):
            lines = [_clean_inline_text(line) for line in part.splitlines() if line.strip()]
            paragraphs.append("\n".join(lines))
            continue
        paragraphs.append(_clean_inline_text(part))
    return "\n\n".join(part for part in paragraphs if part)


def _render_runtime_surface_body(
    surface_type: str,
    surface: Dict[str, Any],
    *,
    include_product_inclusions: bool = True,
) -> str:
    tool = str(surface.get("tool") or "")
    full_result = surface.get("full_result") if isinstance(surface.get("full_result"), dict) else {}
    cards = [card for card in surface.get("cards") or [] if isinstance(card, dict)]
    if surface_type == "fitment":
        return _render_fitment_surface_body(full_result, cards)
    if surface_type == "product":
        if tool == "product_search":
            match_scope_notice = _provider_owned_product_match_scope_notice(
                full_result
            )
            card_block = "\n\n".join(
                str(card.get("card_text") or _fallback_card_text(card)).strip()
                for card in cards
                if str(card.get("card_text") or _fallback_card_text(card)).strip()
            )
            inclusions = (
                _product_inclusions_spiel(cards, service_type=_surface_service_type(surface, full_result))
                if include_product_inclusions
                else ""
            )
            return "\n\n".join(
                part
                for part in [match_scope_notice, card_block, inclusions]
                if part
            )
        if tool == "get_product_details":
            card_block = "\n\n".join(
                str(card.get("card_text") or "").strip()
                for card in cards
                if str(card.get("card_text") or "").strip()
            )
            inclusions = (
                _product_inclusions_spiel(cards, service_type=_surface_service_type(surface, full_result))
                if include_product_inclusions
                else ""
            )
            return "\n\n".join(part for part in [card_block, inclusions] if part)
        if tool == "discover_brand_buckets":
            card_block = "\n\n".join(
                str(card.get("card_text") or "").strip()
                for card in cards
                if str(card.get("card_text") or "").strip()
            )
            legend_text = str(full_result.get("legend_text") or "").strip()
            return "\n\n".join(part for part in [card_block, legend_text] if part)
    if surface_type == "service":
        if tool == "find_installation_partners_no_match":
            return ""
        if tool == "find_installation_partners_summary":
            return _provider_owned_installation_partner_summary(full_result)
        card_block = "\n".join(
            str(card.get("card_text") or "").strip()
            for card in cards
            if str(card.get("card_text") or "").strip()
        )
        policy_notes = [note for note in full_result.get("service_policy_notes") or [] if isinstance(note, dict)]
        policy_block = _service_policy_note_block(policy_notes, "")
        return "\n\n".join(part for part in [card_block, policy_block] if part)
    if surface_type == "order":
        summary_block = str(full_result.get("order_summary_block") or "").strip()
        if summary_block:
            return summary_block
    if surface_type == "payment":
        payment_block = str(full_result.get("payment_instruction_block") or "").strip()
        if payment_block:
            return payment_block
    return ""


def _provider_owned_product_match_scope_notice(
    full_result: Mapping[str, Any],
) -> str:
    """State mechanically when rendered products relax requested filters."""

    if (
        str(full_result.get("status") or "").strip() != "partial_match"
        or not full_result.get("product_cards")
    ):
        return ""
    presentation_strategy = (
        full_result.get("presentation_strategy")
        if isinstance(full_result.get("presentation_strategy"), Mapping)
        else {}
    )
    relaxation = (
        presentation_strategy.get("relaxation")
        if isinstance(presentation_strategy.get("relaxation"), Mapping)
        else {}
    )
    missing_filters = set(relaxation.get("shown_cards_missing_filters") or [])
    query_basis = (
        full_result.get("query_basis")
        if isinstance(full_result.get("query_basis"), Mapping)
        else {}
    )
    filters = (
        query_basis.get("normalized_filters")
        if isinstance(query_basis.get("normalized_filters"), Mapping)
        else {}
    )
    cards = [
        card
        for card in full_result.get("product_cards") or []
        if isinstance(card, Mapping)
    ]
    if missing_filters == {"terrain_type"}:
        requested_brands = [
            str(value or "").strip().upper()
            for value in filters.get("brands") or []
            if str(value or "").strip()
        ]
        terrain_labels = _customer_terrain_labels(filters.get("terrain_types"))
        tire_size = _normalized_product_filter_size(filters)
        card_brands = {
            str(card.get("brand") or "").strip().upper()
            for card in cards
            if str(card.get("brand") or "").strip()
        }
        card_sizes = {
            str(card.get("tire_size") or "").strip().upper().replace("/R", "R")
            for card in cards
            if str(card.get("tire_size") or "").strip()
        }
        normalized_size = tire_size.upper().replace("/R", "") if tire_size else ""
        same_required_brand = bool(requested_brands) and card_brands.issubset(
            set(requested_brands)
        )
        same_exact_size = bool(normalized_size) and card_sizes == {
            normalized_size
        }
        if same_required_brand and same_exact_size and terrain_labels:
            brand_text = " o ".join(requested_brands)
            terrain_text = " o ".join(terrain_labels)
            return (
                f"Walang {brand_text} option na verified as {terrain_text} sa "
                f"{tire_size}. May available na {brand_text} options sa parehong "
                f"size, pero hindi {terrain_text}-verified ang mga ito sa catalog:"
            )
    mismatch_labels = list(
        dict.fromkeys(
            str(label or "").strip()
            for card in cards
            for label in card.get("preference_mismatch_labels") or []
            if str(label or "").strip()
        )
    )
    tire_size = _normalized_product_filter_size(filters)
    mismatch_text = ", ".join(mismatch_labels)
    if tire_size and mismatch_text:
        return (
            f"Walang option na tugma sa lahat ng preferences para sa {tire_size}. "
            f"Parehong exact tire size ang options sa ibaba, pero may hindi tugma sa: "
            f"{mismatch_text}. Promo, stock, at payment details ay applicable lang "
            "kapag nakalagay sa mismong option:"
        )
    return (
        "Walang exact match sa lahat ng hiningi ninyong filters; ito po ang "
        "pinakamalapit na available options."
    )


def _customer_terrain_labels(values: Any) -> List[str]:
    """Return compact customer-facing labels for canonical terrain filters."""

    labels = {
        "ALL_TERRAIN": "A/T",
        "MUD_TERRAIN": "M/T",
        "HIGHWAY_TERRAIN": "H/T",
        "RUGGED_TERRAIN": "R/T",
    }
    return list(
        dict.fromkeys(
            labels.get(str(value or "").strip().upper(), str(value or "").strip())
            for value in values or []
            if str(value or "").strip()
        )
    )


def _normalized_product_filter_size(filters: Mapping[str, Any]) -> str:
    """Return the exact normalized tire-size label from product filters."""

    section = str(filters.get("section_width") or "").strip()
    aspect = str(filters.get("aspect_ratio") or "").strip()
    rim = str(filters.get("rim_size") or "").strip().upper()
    if not (section and aspect and rim):
        return ""
    return f"{section}/{aspect}{rim}"


def _provider_owned_installation_partner_summary(
    full_result: Mapping[str, Any],
) -> str:
    """Render a positive partner result without widening its query area.

    Hidden area-only rows are useful provider evidence but are not selectable
    customer options. Their summary therefore remains deterministic and names
    only the exact normalized query area; separately mentioned alternatives
    remain pending until their own lookup runs.
    """

    query_basis = (
        full_result.get("query_basis")
        if isinstance(full_result.get("query_basis"), Mapping)
        else {}
    )
    coverage = (
        full_result.get("coverage_assessment")
        if isinstance(full_result.get("coverage_assessment"), Mapping)
        else {}
    )
    location = str(
        query_basis.get("customer_location_label")
        or coverage.get("customer_location_label")
        or query_basis.get("location")
        or ""
    ).strip()
    count = coverage.get("presentable_partner_count")
    if not location or type(count) is not int or count <= 0:
        return ""
    option_label = "option" if count == 1 else "options"
    return (
        f"May {count} current installation partner {option_label} po para sa "
        f"{location}. Ang result na ito ay para lang sa {location}; hiwalay "
        "munang kailangang i-check ang iba pa ninyong nabanggit na lugar."
    )


def _render_fitment_surface_body(full_result: Dict[str, Any], headers: Sequence[Dict[str, Any]]) -> str:
    vehicle = str(full_result.get("vehicle_query") or "").strip()
    title = f"Possible tire sizes for {vehicle}:" if vehicle else "Possible tire sizes:"
    size_lines: List[str] = []
    for header in headers or []:
        if not isinstance(header, dict):
            continue
        size = str(header.get("size") or "").strip()
        if size and size not in size_lines:
            size_lines.append(size)
    if not size_lines:
        return ""
    body = "\n".join(f"- {size}" for size in size_lines[:8])
    note = "Candidate sizes pa lang po ito. Pa-confirm po yung exact size sa tire sidewall bago tayo mag-show ng product options."
    return "\n".join([title, body, note]).strip()


def _render_image_response_unit(content: Dict[str, Any]) -> str:
    url = str(content.get("url") or "").strip()
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        return ""
    alt = _clean_inline_text(content.get("alt") or "")
    return "\n".join(part for part in [alt, url] if part)


def _surface_service_type(surface: Dict[str, Any], full_result: Dict[str, Any]) -> str:
    tool_args = surface.get("tool_args") if isinstance(surface.get("tool_args"), dict) else {}
    for value in [
        tool_args.get("service_type"),
        tool_args.get("fulfillment_type"),
        tool_args.get("fulfillment"),
        (full_result.get("query_basis") or {}).get("service_type") if isinstance(full_result.get("query_basis"), dict) else "",
        (full_result.get("query_basis") or {}).get("fulfillment_type") if isinstance(full_result.get("query_basis"), dict) else "",
    ]:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _product_inclusions_spiel(cards: Sequence[Dict[str, Any]], *, service_type: str = "") -> str:
    visible_cards = [card for card in cards or [] if isinstance(card, dict)]
    if not visible_cards:
        return ""
    lines: List[str] = ["Warranty and inclusions:"]
    tpp_line = _tire_protection_plan_line(visible_cards)
    if tpp_line:
        lines.append(f"- {tpp_line}")
    if not _service_type_is_delivery(service_type):
        lines.append(_installation_inclusions_block(visible_cards))
    return "\n".join(lines).strip() if len(lines) > 1 else ""


def _text_contains_product_inclusions(value: Any) -> bool:
    return "warranty and inclusions:" in str(value or "").lower()


def _tire_protection_plan_line(cards: Sequence[Dict[str, Any]]) -> str:
    if not _cards_have_tire_protection_plan(cards):
        return ""
    return (
        "The Gulong Tire Protection Plan is an unconditional warranty "
        "on all types of tire damage, regardless of the cause. Kapag nabutas, napako, "
        "or nasira ang sidewall, papalitan agad. We change your tires, no questions asked."
    )


def _installation_inclusions_block(cards: Sequence[Dict[str, Any]]) -> str:
    brand_new_line = "  • 100% brand new with Manufacturer's Warranty"
    if _cards_have_tire_protection_plan(cards):
        brand_new_line += " & Tire Protection Plan"
    return "\n".join(
        [
            "- Install with our authorized Installation Partners and get:",
            "  • FREE installation",
            "  • FREE mounting & balancing",
            "  • FREE weights & tire valves",
            f"{brand_new_line} 💯",
        ]
    )


def _cards_have_tire_protection_plan(cards: Sequence[Dict[str, Any]]) -> bool:
    return any(_clean_inline_text(card.get("tire_protection_plan") or "") for card in cards or [])


def _latest_installation_slot_cards(
    tool_results: Sequence[Dict[str, Any]],
    *,
    round_value: Any,
) -> List[Dict[str, Any]]:
    """Merge slot cards from multiple slot tool calls in the same turn.

    The model may call `find_installation_slots` once per visible partner. The
    calls can happen in one tool round or sequentially across tool rounds. The
    deterministic renderer should present the combined slot choices, not only
    whichever tool call happened last.
    """

    cards: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for tool_result in tool_results or []:
        if tool_result.get("name") != "find_installation_slots":
            continue
        full_result = tool_result.get("full_result") or {}
        for card in full_result.get("installation_partner_cards") or []:
            if not isinstance(card, dict):
                continue
            key = (
                str(card.get("installation_partner_ref") or ""),
                str(card.get("service_location_ref") or ""),
                str(card.get("name") or ""),
                str(card.get("card_text") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            copied = deepcopy(card)
            copied["card_ref"] = f"partner_card_{len(cards) + 1}"
            cards.append(copied)
    return cards


def _latest_selected_product_cards(
    tool_results: Sequence[Dict[str, Any]],
    *,
    round_value: Any,
) -> List[Dict[str, Any]]:
    cards: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for tool_result in tool_results or []:
        if tool_result.get("name") != "get_product_details":
            continue
        if round_value not in (None, "") and tool_result.get("round") != round_value:
            continue
        full_result = tool_result.get("full_result") or {}
        if not full_result.get("card_runtime_insert"):
            continue
        for card in full_result.get("selected_product_cards") or []:
            if not isinstance(card, dict):
                continue
            key = (
                str(card.get("card_ref") or ""),
                str(card.get("item_ref") or ""),
                str(card.get("slug") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            cards.append(card)
            if len(cards) >= 3:
                return cards
    return cards


def _service_customer_location_label(result: Dict[str, Any]) -> str:
    coverage = result.get("coverage_assessment") if isinstance(result, dict) else {}
    query_basis = result.get("query_basis") if isinstance(result, dict) else {}
    return str(
        (query_basis or {}).get("customer_location_label")
        or (coverage or {}).get("customer_location_label")
        or (query_basis or {}).get("location")
        or ""
    ).strip()


def _has_customer_unsafe_service_policy_term(lowered_text: str) -> bool:
    return any(
        token in lowered_text
        for token in [
            "installation threshold",
            "order threshold",
            "below threshold",
            "minimum threshold",
        ]
    )


def _cards_include_slot_summaries(cards: Sequence[Dict[str, Any]]) -> bool:
    return any(isinstance(card, dict) and bool(card.get("slot_summary_lines")) for card in cards or [])


def _required_policy_evidence_retry_context(
    *,
    current_user_message: str,
    background_signals: Sequence[Dict[str, Any]],
    tool_schemas: Sequence[Dict[str, Any]],
    tool_results: Sequence[Dict[str, Any]],
    retry_events: Sequence[Dict[str, Any]],
) -> Dict[str, str]:
    """Require authored policy evidence for a typed delivery question.

    This is deliberately not an FAQ phrase matcher. Background extraction owns
    the fulfillment concept, while a broad question-act check distinguishes a
    policy question from a fulfillment selection such as ``delivery na lang``.
    The FAQ provider then uses the typed ``service_type`` scope to retrieve the
    authored general policy. Exact-location serviceability remains outside that
    authority.
    """

    if any(
        isinstance(event, Mapping)
        and event.get("type") == "policy_evidence_tool_retry"
        for event in retry_events or []
    ):
        return {}
    if "answer_policy_faq" not in _tool_schema_names(tool_schemas):
        return {}
    if any(
        isinstance(result, Mapping)
        and str(result.get("name") or "")
        in {"answer_policy_faq", "answer_order_faq"}
        and str(
            (
                result.get("full_result")
                if isinstance(result.get("full_result"), Mapping)
                else result.get("result")
                if isinstance(result.get("result"), Mapping)
                else {}
            ).get("policy_type")
            or ""
        )
        == "delivery_process"
        for result in tool_results or []
    ):
        return {}
    signal = next(
        (
            item
            for item in reversed(list(background_signals or []))
            if isinstance(item, Mapping)
            and str(item.get("key") or "") == "service_type"
            and str(item.get("source") or "") == "latest_user_message"
        ),
        {},
    )
    if not _service_type_is_delivery(signal.get("value")):
        return {}
    relation = str(signal.get("relation") or "").strip().lower()
    if relation in {"conditional", "negated"}:
        return {}
    if relation != "question_only" and not _looks_like_customer_question(
        current_user_message
    ):
        return {}
    return {
        "tool_name": "answer_policy_faq",
        "service_type": "delivery",
        "policy_scope": "general_delivery_process",
    }


def _looks_like_customer_question(text: str) -> bool:
    """Recognize a broad question act without selecting an FAQ answer."""

    raw = str(text or "").strip()
    if not raw:
        return False
    if "?" in raw:
        return True
    normalized = " ".join(re.findall(r"[a-z0-9]+", raw.casefold()))
    return bool(
        re.search(r"(?:^|\s)ba(?:\s|$)", normalized)
        or re.match(
            r"^(?:ano|can|could|gaano|how|kelan|magkano|paano|pede|pwede|"
            r"saan|what|when|where|whether|would)(?:\s|$)",
            normalized,
        )
        or re.match(
            r"^(?:do|does)\s+(?:i|we|you|they|he|she|it)(?:\s|$)",
            normalized,
        )
    )


def _missing_product_tool_retry_context(
    *,
    capability_profile: Dict[str, Any],
    background_signals: Sequence[Dict[str, Any]],
    tool_schemas: Sequence[Dict[str, Any]],
    tool_results: Sequence[Dict[str, Any]],
    retry_events: Sequence[Dict[str, Any]],
    assistant_text: str = "",
    product_observation_store: Optional[ProductObservationStore] = None,
) -> Dict[str, Any]:
    """Return retry context when structured Tool Objectives need a product tool."""

    if any(
        event.get("type") == "product_objective_tool_retry"
        for event in retry_events or []
    ):
        return {}
    tool_names = _tool_schema_names(tool_schemas)
    exposed_product_tools = {
        "product_search",
        "discover_brand_buckets",
        "extract_compatible_fitment",
        "resolve_product_reference",
        "get_product_details",
    }.intersection(tool_names)
    if not exposed_product_tools:
        return {}
    executed_tools = {
        str(result.get("name") or "").strip()
        for result in tool_results or []
        if isinstance(result, dict)
    }
    objectives = build_tool_objectives(
        background_signals=background_signals,
        capability_profile=capability_profile,
    )
    product_objectives: List[Dict[str, str]] = []
    for objective in objectives:
        if str(objective.get("priority") or "").strip() not in {"primary", "also_primary"}:
            continue
        tool_text = str(objective.get("tool") or "")
        objective_tools = {
            tool for tool in exposed_product_tools if tool in tool_text
        }
        if not objective_tools:
            continue
        if objective_tools.intersection(executed_tools):
            continue
        objective_name = str(objective.get("objective") or "")
        if not objective_name.startswith("product") and not objective_name.startswith("visible_product"):
            continue
        product_objectives.append(dict(objective))
    if not product_objectives:
        return {}
    available_context_refs = (
        capability_profile.get("available_context_refs")
        if isinstance(capability_profile.get("available_context_refs"), dict)
        else {}
    )
    if (
        all(
            str(objective.get("objective") or "") == "product_discovery"
            for objective in product_objectives
        )
        and _latest_product_filter_signal_keys(background_signals)
        == {"tire_category_preference"}
        and available_context_refs.get("product_observation") is True
        and _assistant_text_anchors_latest_product_observation(
            assistant_text,
            product_observation_store,
        )
    ):
        return {}
    return {
        "status": "structured_product_objective_unmet",
        "product_objectives": product_objectives[:3],
        "exposed_product_tools": sorted(exposed_product_tools),
    }


def _assistant_text_anchors_latest_product_observation(
    assistant_text: str,
    product_observation_store: Optional[ProductObservationStore],
) -> bool:
    """Recognize a direct answer anchored to an already visible exact card.

    This prevents the generic missing-tool retry from replacing a valid
    follow-up selection with a new discovery search.  Exact commercial amounts
    remain subject to the normal pricing guard later in composition.
    """

    text_norm = _normalize_product_reference_text(assistant_text)
    if not text_norm or product_observation_store is None:
        return False
    observation = product_observation_store.latest()
    if observation is None:
        return False
    for card in observation.product_cards or []:
        if not isinstance(card, dict):
            continue
        sku_norm = _normalize_product_reference_text(card.get("sku_model"))
        if sku_norm and sku_norm in text_norm:
            return True
        if _assistant_text_anchors_product_card(assistant_text, card):
            return True
    return False


def _normalize_product_reference_text(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def _assistant_text_anchors_product_card(
    assistant_text: str,
    card: Dict[str, Any],
) -> bool:
    """Match brand plus distinctive model identity without requiring size prose."""

    text_tokens = set(re.findall(r"[A-Z0-9]+", str(assistant_text or "").upper()))
    sku_tokens = re.findall(r"[A-Z0-9]+", str(card.get("sku_model") or "").upper())
    brand_tokens = set(re.findall(r"[A-Z0-9]+", str(card.get("brand") or "").upper()))
    if not text_tokens or not sku_tokens or not brand_tokens:
        return False
    if not brand_tokens.issubset(text_tokens):
        return False
    size_tokens = set(
        re.findall(r"[A-Z0-9]+", str(card.get("tire_size") or "").upper())
    )
    size_match = re.search(
        r"\b(\d{3})\s*[/X-]\s*(\d{2,3})\s*[/X-]?\s*R\s*(\d{2})\b",
        str(card.get("tire_size") or card.get("sku_model") or "").upper(),
    )
    if size_match:
        size_tokens.update(
            {size_match.group(1), size_match.group(2), f"R{size_match.group(3)}"}
        )
    pattern_tokens = set(
        re.findall(r"[A-Z0-9]+", str(card.get("pattern") or "").upper())
    )
    identity_tokens = pattern_tokens or {
        token
        for token in sku_tokens
        if token not in brand_tokens
        and token not in size_tokens
        and not re.fullmatch(r"R\d{2}", token)
        and not re.fullmatch(r"\d{2,3}[A-Z]", token)
    }
    if not identity_tokens:
        return False
    matched_identity = identity_tokens.intersection(text_tokens)
    required_matches = 1 if len(identity_tokens) == 1 else 2
    return len(matched_identity) >= required_matches


def _latest_product_filter_signal_keys(
    background_signals: Sequence[Dict[str, Any]],
) -> Set[str]:
    """Return latest-message product refinements that can require discovery."""

    product_filter_keys = {
        "tire_size",
        "rim_size",
        "required_brands",
        "brand_match_mode",
        "preferred_brands",
        "specific_sku_model",
        "budget",
        "quantity",
        "promo_types",
        "tire_category_preference",
        "excluded_tire_categories",
        "origins",
        "excluded_origins",
        "payment_method",
    }
    return {
        str(signal.get("key") or "").strip()
        for signal in background_signals or []
        if isinstance(signal, dict)
        and str(signal.get("source") or "").strip() == "latest_user_message"
        and str(signal.get("key") or "").strip() in product_filter_keys
    }


def _required_commercial_evidence_retry_context(
    *,
    capability_profile: Dict[str, Any],
    background_signals: Sequence[Dict[str, Any]],
    tool_schemas: Sequence[Dict[str, Any]],
    tool_results: Sequence[Dict[str, Any]],
    retry_events: Sequence[Dict[str, Any]],
    current_user_message: str = "",
) -> Dict[str, Any]:
    """Require the relevant authority when a typed commercial objective is unmet."""

    tool_names = _tool_schema_names(tool_schemas)
    candidate_tools = {
        str(name or "").strip()
        for name in capability_profile.get("candidate_tools") or []
        if str(name or "").strip()
    }
    matched_signal_keys = (
        capability_profile.get("matched_signal_keys")
        if isinstance(capability_profile.get("matched_signal_keys"), dict)
        else {}
    )
    executed_tools = {
        str(result.get("name") or "").strip()
        for result in tool_results or []
        if isinstance(result, dict)
    }
    retried_tools: Set[str] = set()
    commercial_retry_contexts: List[Dict[str, Any]] = []
    for event in retry_events or []:
        if (
            not isinstance(event, dict)
            or event.get("type") != "commercial_evidence_tool_retry"
            or not isinstance(event.get("retry_context"), dict)
        ):
            continue
        retry_context = {
            **event["retry_context"],
            "_retry_round": event.get("round"),
        }
        commercial_retry_contexts.append(retry_context)
        retry_tool_name = str(retry_context.get("tool_name") or "").strip()
        if retry_tool_name:
            retried_tools.add(retry_tool_name)
        retried_tools.update(
            str(name or "").strip()
            for name in retry_context.get("required_tools") or []
            if str(name or "").strip()
        )

    promo_tool = "search_promo_catalog"
    promo_keys = set(matched_signal_keys.get(promo_tool) or [])
    latest_signal_keys = {
        str(signal.get("key") or "").strip()
        for signal in background_signals or []
        if isinstance(signal, dict)
        and str(signal.get("source") or "").strip() == "latest_user_message"
        and str(signal.get("key") or "").strip()
        and signal.get("value") not in (None, "", [])
    }
    latest_promo_objective = "promo_types" in latest_signal_keys or bool(
        {"required_brands", "preferred_brands"}.intersection(latest_signal_keys)
        and "promo_types" in promo_keys
    )
    combined_retry_contexts = [
        retry_context
        for retry_context in commercial_retry_contexts
        if len(retry_context.get("required_tools") or []) > 1
    ]
    latest_combined_retry = (
        combined_retry_contexts[-1] if combined_retry_contexts else {}
    )

    def _tool_executed_after_retry(
        tool_name: str,
        retry_context: Mapping[str, Any],
    ) -> bool:
        retry_round = retry_context.get("_retry_round")
        for result in tool_results or []:
            if (
                not isinstance(result, Mapping)
                or str(result.get("name") or "").strip() != tool_name
            ):
                continue
            result_round = result.get("round")
            if isinstance(retry_round, int):
                if isinstance(result_round, int) and result_round > retry_round:
                    return True
                continue
            return True
        return False

    promo_retry_allowed = promo_tool not in retried_tools or bool(
        latest_combined_retry
        and any(
            name != promo_tool
            and _tool_executed_after_retry(name, latest_combined_retry)
            for name in latest_combined_retry.get("required_tools") or []
        )
    )
    promo_context: Dict[str, Any] = {}
    if (
        promo_tool in tool_names
        and promo_tool in candidate_tools
        and promo_tool not in executed_tools
        and promo_retry_allowed
        and "promo_types" in promo_keys
        and latest_promo_objective
    ):
        promo_context = {
            "status": "reviewed_promo_evidence_required",
            "tool_name": promo_tool,
            "authority": "reviewed_promo_catalog",
            "matched_signal_keys": sorted(promo_keys),
        }

    payment_tool = "answer_order_faq"
    payment_keys = {
        "payment_method",
        "payment_option",
        "reservation_payment_method",
        "balance_payment_method",
    }.intersection(set(matched_signal_keys.get(payment_tool) or []))
    latest_payment_signals = [
        signal
        for signal in background_signals or []
        if isinstance(signal, dict)
        and str(signal.get("source") or "").strip() == "latest_user_message"
        and str(signal.get("key") or "").strip()
        in {
            "payment_method",
            "payment_option",
            "reservation_payment_method",
            "balance_payment_method",
        }
        and signal.get("value") not in (None, "", [])
    ]
    unconfirmed_payment_query_keys = {
        str(signal.get("key") or "").strip()
        for signal in latest_payment_signals
        if (
            str(signal.get("status") or "").strip() == "mentioned_unconfirmed"
            or str(signal.get("relation") or "").strip()
            in {"question_only", "conditional"}
        )
    }
    payment_context: Dict[str, Any] = {}
    expected_installment_scopes = _explicit_customer_installment_plan_scopes(
        current_user_message
    )
    expected_payment_scopes = [
        *expected_installment_scopes,
        *_model_merged_cross_clause_payment_scopes(
            current_user_message,
            background_signals=background_signals,
            tool_results=tool_results,
        ),
    ]
    executed_payment_scopes = [
        dict(result.get("args") or {})
        for result in tool_results or []
        if isinstance(result, Mapping)
        and str(result.get("name") or "") == payment_tool
        and isinstance(result.get("args"), Mapping)
    ]

    def _payment_scope_was_executed(scope: Mapping[str, Any]) -> bool:
        expected_method_tokens = _payment_scope_distinctive_tokens(
            scope.get("requested_payment_method")
        )
        for executed_scope in executed_payment_scopes:
            if not _contains_ordered_local_token_span(
                _payment_scope_distinctive_tokens(
                    executed_scope.get("requested_payment_method")
                ),
                expected_method_tokens,
            ):
                continue
            if any(
                " ".join(str(scope.get(key) or "").casefold().split())
                and " ".join(str(scope.get(key) or "").casefold().split())
                != " ".join(
                    str(executed_scope.get(key) or "").casefold().split()
                )
                for key in ("requested_product_brand", "payment_option")
            ):
                continue
            return True
        return False

    # Explicit terms can describe either an immediate policy question or a
    # confirmed checkout preference saved for later. Only a question/unconfirmed
    # scope is owed an authority answer in this turn. This keeps product-first
    # turns from spending follow-on model rounds on future payment work while
    # retaining strict recovery for compound payment questions.
    payment_policy_answer_due_now = bool(
        not latest_payment_signals
        or unconfirmed_payment_query_keys
    )
    missing_payment_scopes = (
        [
            scope
            for scope in expected_payment_scopes
            if not _payment_scope_was_executed(scope)
        ]
        if payment_policy_answer_due_now
        else []
    )
    prior_payment_scope_retries: List[
        Tuple[Dict[str, Any], Dict[str, Any]]
    ] = []
    for retry_context in commercial_retry_contexts:
        if retry_context.get("tool_name") == payment_tool:
            prior_payment_scope_retries.append(
                (retry_context, retry_context)
            )
            continue
        for objective in retry_context.get("objectives") or []:
            if (
                isinstance(objective, dict)
                and objective.get("tool_name") == payment_tool
            ):
                prior_payment_scope_retries.append(
                    (objective, retry_context)
                )
    latest_retried_payment_scopes = (
        prior_payment_scope_retries[-1][0].get("missing_payment_scopes") or []
        if prior_payment_scope_retries
        else []
    )
    payment_scope_retry_made_progress = any(
        isinstance(scope, Mapping) and _payment_scope_was_executed(scope)
        for scope in latest_retried_payment_scopes
    )
    latest_payment_retry_parent = (
        prior_payment_scope_retries[-1][1]
        if prior_payment_scope_retries
        else {}
    )
    other_combined_tool_made_progress = bool(
        latest_payment_retry_parent.get("required_tools")
        and any(
            name != payment_tool
            and _tool_executed_after_retry(name, latest_payment_retry_parent)
            for name in latest_payment_retry_parent.get("required_tools") or []
        )
    )
    payment_scope_retry_allowed = (
        not prior_payment_scope_retries
        or payment_scope_retry_made_progress
        or other_combined_tool_made_progress
    )
    if (
        payment_tool in tool_names
        and (
            payment_tool in candidate_tools
            or payment_tool in executed_tools
        )
        and payment_scope_retry_allowed
        and missing_payment_scopes
    ):
        payment_context = {
            "status": "checkout_payment_scope_evidence_required",
            "tool_name": payment_tool,
            "authority": "active_checkout_payment_metadata",
            "missing_payment_scopes": missing_payment_scopes,
        }
    elif (
        payment_tool in tool_names
        and payment_tool in candidate_tools
        and payment_tool not in executed_tools
        and (
            payment_tool not in retried_tools
            or other_combined_tool_made_progress
        )
        and unconfirmed_payment_query_keys
    ):
        payment_context = {
            "status": "checkout_payment_evidence_required",
            "tool_name": payment_tool,
            "authority": "active_checkout_payment_metadata",
            "matched_signal_keys": sorted(payment_keys),
            "unconfirmed_query_signal_keys": sorted(unconfirmed_payment_query_keys),
        }
    if promo_context and payment_context:
        return {
            "status": "multiple_commercial_authorities_required",
            "required_tools": [promo_tool, payment_tool],
            "objectives": [promo_context, payment_context],
        }
    return promo_context or payment_context


def _partner_lookup_slot_followup_retry_context(
    *,
    tool_schemas: Sequence[Dict[str, Any]],
    tool_results: Sequence[Dict[str, Any]],
    retry_events: Sequence[Dict[str, Any]],
) -> Dict[str, str]:
    """Return retry context when hidden partner rows should become grouped slot options."""

    if any(event.get("type") == "partner_lookup_slot_followup_tool_retry" for event in retry_events or []):
        return {}
    tool_names = _tool_schema_names(tool_schemas)
    if "find_installation_slots" not in tool_names:
        return {}
    if any(result.get("name") == "find_installation_slots" for result in tool_results or []):
        return {}
    for tool_result in reversed(list(tool_results or [])):
        if tool_result.get("name") not in {"find_installation_partners", "find_service_locations"}:
            continue
        full_result = tool_result.get("full_result") if isinstance(tool_result.get("full_result"), dict) else {}
        cards = [card for card in full_result.get("installation_partner_cards") or [] if isinstance(card, dict)]
        if not _should_suppress_anonymous_partner_cards(str(tool_result.get("name") or ""), full_result, cards):
            continue
        query_basis = full_result.get("query_basis") if isinstance(full_result.get("query_basis"), dict) else {}
        location = str(
            query_basis.get("customer_location_label")
            or query_basis.get("location")
            or query_basis.get("area")
            or _service_customer_location_label(full_result)
            or ""
        ).strip()
        if not location:
            continue
        service_type = str(query_basis.get("service_type") or full_result.get("service_type") or "installation").strip()
        return {
            "tool_name": "find_installation_slots",
            "location": location,
            "service_type": service_type or "installation",
            "lookup_goal": "show_grouped_slots_after_area_partner_lookup",
            "source_observation_ref": str(full_result.get("observation_ref") or ""),
        }
    return {}


def _partner_lookup_slot_followup_retry_prompt(*, user_message: str, context: Dict[str, str]) -> str:
    location = str(context.get("location") or "").strip()
    service_type = str(context.get("service_type") or "installation").strip() or "installation"
    return (
        "Internal runtime tool-use retry: the previous installation partner lookup returned "
        "only hidden/area-level partner options and explicitly recommends slot lookup before "
        f"final response. Call find_installation_slots now using location={location}; "
        f"service_type={service_type}; no exact schedule was provided, so use the tool's "
        "default grouped nearby availability search. Do not ask the customer to choose "
        "anonymous partner options, and do not mention this retry. Latest customer message: "
        f"{str(user_message or '').strip()[:240]}"
    )


def _ready_order_submit_retry_context(
    *,
    background_signals: Sequence[Dict[str, Any]],
    tool_schemas: Sequence[Dict[str, Any]],
    tool_results: Sequence[Dict[str, Any]],
    retry_events: Sequence[Dict[str, Any]],
) -> Dict[str, str]:
    """Return retry context when a payload ref is ready and submission was requested."""

    if any(event.get("type") == "ready_order_submit_tool_retry" for event in retry_events or []):
        return {}
    tool_names = _tool_schema_names(tool_schemas)
    if "submit_order" not in tool_names:
        return {}
    if any(
        result.get("name") == "submit_order" and (result.get("result") or {}).get("status") == "success"
        for result in tool_results or []
    ):
        return {}
    latest_payload: Dict[str, Any] = {}
    for result in reversed(tool_results or []):
        if result.get("name") != "build_order_payload":
            continue
        payload_result = result.get("result") if isinstance(result.get("result"), dict) else {}
        if payload_result.get("can_submit_order") is True and str(payload_result.get("order_payload_ref") or "").strip():
            latest_payload = {
                "order_payload_ref": str(payload_result.get("order_payload_ref") or "").strip(),
                "payload_reason": str((result.get("args") or {}).get("payload_reason") or "").strip(),
            }
            break
    if not latest_payload:
        return {}
    if not _latest_customer_explicit_order_confirmation(background_signals):
        return {}
    return latest_payload


def _latest_customer_explicit_order_confirmation(
    background_signals: Sequence[Dict[str, Any]],
) -> bool:
    """Accept only a current customer-derived submit confirmation signal."""

    for signal in background_signals or []:
        if not isinstance(signal, dict):
            continue
        if str(signal.get("key") or "").strip() != "explicit_order_confirmation":
            continue
        source, status = signal_authority(signal)
        if source != "latest_user_message":
            continue
        if status in {"mentioned_unconfirmed", "invalid", "rejected", "superseded"}:
            continue
        normalized = " ".join(str(signal.get("value") or "").casefold().split())
        if normalized and normalized not in {
            "0",
            "false",
            "no",
            "nope",
            "not yet",
            "later",
        }:
            return True
    return False


def _typed_state_authorizes_order_submission(
    *,
    latest_order_summary_snapshot: Optional[Dict[str, Any]] = None,
    background_signals: Optional[Sequence[Dict[str, Any]]] = None,
) -> bool:
    """Require current-turn typed customer confirmation after a ready summary."""

    snapshot = (
        latest_order_summary_snapshot
        if isinstance(latest_order_summary_snapshot, dict)
        else {}
    )
    if str(snapshot.get("status") or "").strip() != "ready":
        return False
    return _latest_customer_explicit_order_confirmation(background_signals or [])


def _ready_order_submit_retry_prompt(*, user_message: str, context: Dict[str, str]) -> str:
    return (
        "Internal runtime tool-use retry: build_order_payload returned a validated "
        f"order_payload_ref={context.get('order_payload_ref')}, and the structured "
        "confirmation context indicates the customer is proceeding to submission or payment. "
        "Call submit_order now with that order_payload_ref before saying the order is "
        "submitted, created, booked, or ready for payment. Do not mention this retry. "
        "Latest customer message: "
        f"{str(user_message or '').strip()[:240]}"
    )


def _ready_payment_request_retry_context(
    *,
    tool_schemas: Sequence[Dict[str, Any]],
    tool_results: Sequence[Dict[str, Any]],
    retry_events: Sequence[Dict[str, Any]],
) -> Dict[str, str]:
    """Continue a successful submission to its already-selected payment route."""

    if any(
        event.get("type") == "ready_payment_request_tool_retry"
        for event in retry_events or []
    ):
        return {}
    if "prepare_payment_request" not in _tool_schema_names(tool_schemas):
        return {}
    if any(
        item.get("name") == "prepare_payment_request"
        and str((item.get("result") or {}).get("status") or "") == "ok"
        for item in tool_results or []
        if isinstance(item, dict)
    ):
        return {}
    for item in reversed(tool_results or []):
        if not isinstance(item, dict) or item.get("name") != "submit_order":
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        order_id = str(result.get("order_id") or "").strip()
        if (
            str(result.get("status") or "") == "success"
            and result.get("can_request_payment") is True
            and order_id
        ):
            return {
                "order_id": order_id,
                "order_payload_ref": str(result.get("order_payload_ref") or "").strip(),
            }
    return {}


def _ready_payment_request_retry_prompt(
    *,
    user_message: str,
    context: Dict[str, str],
) -> str:
    return (
        "Internal runtime tool-use retry: submit_order succeeded for "
        f"order_id={context.get('order_id')}, and the validated order already "
        "contains the customer's selected payment route. Call "
        "prepare_payment_request now so the final response can show the grounded "
        "payment instructions. Do not ask the customer to confirm proceeding a "
        "second time and do not mention this retry. Latest customer message: "
        f"{str(user_message or '').strip()[:240]}"
    )


def _forced_tool_choice(tool_name: Any) -> Any:
    name = str(tool_name or "").strip()
    if not name:
        return "auto"
    return {"type": "function", "function": {"name": name}}


def _named_catalog_promo_tool_context(
    *,
    current_user_message: str,
    promo_catalog: Optional[PromoCatalogService],
    tool_schemas: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Select the promo provider when the customer names an active catalog title."""

    if promo_catalog is None or "search_promo_catalog" not in _tool_schema_names(tool_schemas):
        return {}
    match = promo_catalog.exact_named_promo_reference(current_user_message)
    if not match:
        return {}
    return {"tool_name": "search_promo_catalog", **match}


def _named_catalog_promo_tool_prompt(*, user_message: str, context: Dict[str, Any]) -> str:
    """Expose a validated catalog entity without deciding the turn's intent."""

    return (
        "Validated entity context: the latest customer message exactly contains the current "
        f"reviewed catalog title {context.get('title')!r}. This proves the entity exists; it "
        "does not prove the customer's intent or require a tool call. Decide from the complete "
        "turn whether to call search_promo_catalog. If current promo facts or a promo surface "
        "are needed, use targeted mode, the latest request as query, "
        "presentation_mode=gallery_if_available, and explicit_redisplay=false. Do not answer "
        f"commercial facts from prior assistant text. Latest customer request: {user_message!r}."
    )


def _should_retry_empty_model_output(
    *,
    assistant_text: str,
    retry_events: Sequence[Dict[str, Any]],
) -> bool:
    if any(
        event.get("type") == "empty_model_output_retry"
        for event in retry_events or []
    ):
        return False
    text = str(assistant_text or "").strip()
    if not text:
        return True
    structured_units = _parse_structured_response_units(text)
    if structured_units is not None:
        return not any(
            _structured_response_unit_has_renderable_content(unit)
            for unit in structured_units
        )
    # Preserve existing specialized recovery for ordinary prose (for example,
    # renderer-duplication cleanup). JSON-like contract failures, including a
    # raw response-unit array without the required envelope, belong to this
    # generic bounded retry.
    json_array = False
    if text.startswith("["):
        try:
            json_array = isinstance(json.loads(text), list)
        except (TypeError, ValueError):
            json_array = bool(re.match(r"^\[\s*\{", text))
    return text.startswith("{") or json_array or bool(
        re.match(r"^```(?:json)?\s*[\[{]", text, flags=re.IGNORECASE)
    )


def _structured_response_unit_has_renderable_content(
    unit: Mapping[str, Any],
) -> bool:
    """Recognize a potentially visible unit before the final render pass."""

    unit_type = str(unit.get("type") or "").strip()
    content = unit.get("content") if isinstance(unit.get("content"), Mapping) else {}
    if unit_type == "text":
        return bool(str(content.get("text") or "").strip())
    if unit_type == "render_surface":
        return bool(str(content.get("surface_ref") or "").strip())
    if unit_type == "image":
        return bool(re.match(r"^https?://", str(content.get("url") or "").strip(), re.IGNORECASE))
    return False


def _empty_model_output_retry_prompt(*, user_message: str) -> str:
    return (
        "Internal runtime empty-output retry: the previous model call returned no renderable "
        "customer response and no tool call. Write a concise customer-facing reply, or call one of "
        "the exposed tools if the customer's question needs grounded business facts. Do not "
        "return an empty response. Latest customer message: "
        f"{str(user_message or '').strip()[:240]}"
    )


def _empty_runtime_fallback_response(user_message: str) -> str:
    """Return a neutral resend request without inferring intent or the next CTA."""

    del user_message
    return (
        "Pasensya po, hindi ko nakuha nang maayos yung reply. "
        "Pwede po paki-send ulit yung question or details?"
    )


def _unsupported_payment_claim_fallback_text(
    tool_results: Sequence[Dict[str, Any]],
) -> str:
    """State exact validated payment facts after both model attempts fail.

    This is the last-resort commercial safety boundary. Normal response prose
    remains model-owned; the fallback is used only after the structured
    composer and its repair both failed the payment claim contract.
    """

    sentences: List[str] = []
    for policy in payment_policies_from_tool_results(tool_results):
        claim = payment_claim(policy)
        if not claim:
            continue
        method = _final_composer_payment_method_label(
            claim.get("requested_method") or claim.get("method") or ""
        ).strip()
        brand = str(claim.get("brand") or "").strip()
        payment_option = str(claim.get("payment_option") or "").strip()
        scope = "".join(
            (
                f" for {brand}" if brand else "",
                f" under {payment_option}" if payment_option else "",
            )
        )
        if claim.get("outcome") == "eligible":
            sentences.append(f"Yes po, puwede ang {method}{scope}.")
        elif claim.get("outcome") == "not_eligible":
            sentences.append(f"Hindi po available ang {method}{scope}.")
        elif claim.get("outcome") == "unsupported":
            sentences.append(
                f"Wala pa po tayong {method} as a payment option."
            )
    promo_sentences = _validated_promo_fallback_sentences(tool_results)
    if sentences or promo_sentences:
        return " ".join([*sentences, *promo_sentences])
    if any(
        isinstance(item, dict)
        and item.get("name") in {"product_search", "get_product_details"}
        for item in tool_results or []
    ):
        return "We have options for the requested tire size and preferences."
    return (
        "Hindi ko pa ma-confirm ang payment option mula sa current order "
        "details."
    )


def _provider_grounded_payment_response_text(
    tool_results: Sequence[Dict[str, Any]],
) -> str:
    """Compose a pure typed payment-policy turn without another model call.

    This narrow path applies only when every result is a payment-scoped
    ``answer_order_faq`` result and each result produced one typed claim. Mixed
    FAQ, product, promo, service, and renderer turns stay with the final
    composer because they still need model-owned connective prose and surface
    ordering.
    """

    results = [item for item in tool_results or [] if isinstance(item, dict)]
    if not results or len(results) != len(tool_results or []):
        return ""
    if any(
        str(item.get("name") or "") != "answer_order_faq"
        or not _order_faq_result_is_payment_scoped(item)
        for item in results
    ):
        return ""
    policies = payment_policies_from_tool_results(results)
    claims = [payment_claim(policy) for policy in policies]
    if len(policies) != len(results) or any(not claim for claim in claims):
        return ""
    response_text = _unsupported_payment_claim_fallback_text(results).strip()
    if not response_text:
        return ""
    if payment_claim_contract_violations(response_text, results):
        return ""
    if ungrounded_payment_assertion_violations(response_text, results):
        return ""
    return response_text


def _should_offer_location_contact_fallback(
    *,
    background_signals: Sequence[Dict[str, Any]],
    lead_qualification: Mapping[str, Any],
    selected_product_context: Optional[Mapping[str, Any]],
    tool_results: Sequence[Dict[str, Any]],
    interaction_packet: Optional[Mapping[str, Any]],
    validated_choice_context: Optional[Mapping[str, Any]],
) -> bool:
    """Return whether location uncertainty should progress to contact capture.

    The semantic extractor owns recognition of wording variations. This guard
    consumes only its closed, current-turn signal and then enforces deterministic
    scope: an established product/size-brand path, no usable location/contact,
    and no competing grounded answer or tracked action. A rejected or completed
    province/city picker is not competing because this signal explicitly says
    the customer cannot provide that input now.
    """

    if interaction_packet or validated_choice_context:
        return False
    tool_names = {
        str(item.get("name") or "").strip()
        for item in tool_results or []
        if isinstance(item, Mapping)
    }
    if tool_names - {"present_serviceable_location_choices"}:
        return False
    if not _current_turn_location_unavailable(background_signals):
        return False
    present = (
        lead_qualification.get("present")
        if isinstance(lead_qualification.get("present"), Mapping)
        else {}
    )
    if present.get("location") or present.get("contact_number"):
        return False
    has_product_progression = bool(
        selected_product_context
        or (present.get("tire_size") and present.get("tire_brand"))
    )
    return has_product_progression


def _current_turn_location_unavailable(
    background_signals: Sequence[Dict[str, Any]],
) -> bool:
    """Return whether semantic extraction found current-turn location inability."""

    return any(
        isinstance(signal, Mapping)
        and str(signal.get("key") or "") == "location_response_status"
        and str(signal.get("value") or "") == "unavailable_now"
        and str(signal.get("source") or "") == "latest_user_message"
        and str(signal.get("relation") or "") in TRANSIENT_SIGNAL_RELATIONS
        for signal in background_signals or []
    )


def _location_contact_fallback_text() -> str:
    """Return reviewed copy for a customer who cannot provide location yet."""

    return (
        "Okay lang po kung hindi pa sure ang installation or delivery location. "
        "Pwede niyo pong iwan ang contact number ninyo para ma-follow up kayo "
        "ng team; iko-confirm pa rin nila ang available location or service area."
    )


def _payment_fallback_response_units(
    response_units: Sequence[Dict[str, Any]],
    fallback_text: str,
) -> List[Dict[str, Any]]:
    """Replace unsafe prose while retaining the accepted renderer plan.

    This helper runs only after the final composer has already produced an
    authoritative surface plan but failed the payment-claim contract. Exact
    renderer-owned surfaces remain; model text, images, and unknown units do
    not survive the commercial safety fallback.
    """

    output: List[Dict[str, Any]] = []
    safe_text = str(fallback_text or "").strip()
    if safe_text:
        output.append(
            {
                "type": "text",
                "content": {"text": safe_text},
            }
        )
    rendered_refs: set[str] = set()
    for unit in response_units or []:
        if not isinstance(unit, dict) or str(unit.get("type") or "") != (
            "render_surface"
        ):
            continue
        content = unit.get("content") if isinstance(unit.get("content"), dict) else {}
        surface_ref = str(content.get("surface_ref") or "").strip()
        if not surface_ref or surface_ref in rendered_refs:
            continue
        output.append(
            {
                "type": "render_surface",
                "content": {"surface_ref": surface_ref},
            }
        )
        rendered_refs.add(surface_ref)
    return output


def _validated_promo_fallback_sentences(
    tool_results: Sequence[Dict[str, Any]],
) -> List[str]:
    """Return exact reviewed offer summaries for a failed compound composer."""

    output: List[str] = []
    context = _promo_fact_audit_context(tool_results)
    for search in context.get("promo_searches") or []:
        if not isinstance(search, Mapping):
            continue
        requested_brands = {
            str(value or "").strip().casefold()
            for value in search.get("requested_brands") or []
            if str(value or "").strip()
        }
        candidates = [
            candidate
            for candidate in search.get("applicable_promos") or []
            if isinstance(candidate, Mapping)
            and (
                not requested_brands
                or requested_brands.intersection(
                    {
                        str(value or "").strip().casefold()
                        for value in candidate.get("brands") or []
                        if str(value or "").strip()
                    }
                )
            )
        ]
        for candidate in candidates[:1]:
            title = str(candidate.get("title") or "").strip()
            summary = str(candidate.get("offer_summary") or "").strip()
            if not summary:
                continue
            sentence = f"For the current {title}, {summary}" if title else summary
            if sentence[-1:] not in ".!?":
                sentence += "."
            if sentence not in output:
                output.append(sentence)
    return output


def _service_advisory_capability_retry_prompt(*, user_message: str) -> str:
    return (
        "Internal runtime capability retry: service language or evidence was detected, "
        "but service tools are not exposed in this turn. If the latest customer message "
        "needs service, installation, branch/location, delivery, pickup, same-day, or "
        "schedule facts, call request_capability with domain=service now. If it does not "
        "need service capability, answer directly without making unsupported service "
        "claims. Latest customer message: "
        f"{str(user_message or '').strip()[:240]}"
    )


def _missing_product_tool_retry_prompt(*, user_message: str, context: Dict[str, Any]) -> str:
    objectives = context.get("product_objectives") if isinstance(context, dict) else []
    objective_lines = []
    for objective in objectives[:3] if isinstance(objectives, list) else []:
        if not isinstance(objective, dict):
            continue
        objective_lines.append(
            _compact_unit(
                {
                    "priority": objective.get("priority"),
                    "objective": objective.get("objective"),
                    "tool": objective.get("tool"),
                    "reason": objective.get("reason") or objective.get("use_rule"),
                }
            )
        )
    objective_text = json.dumps(objective_lines, ensure_ascii=False) if objective_lines else "[]"
    return (
        "Internal runtime tool-use retry: the structured Tool Objectives still contain a "
        "primary product objective, but no product tool has run in this turn. Use the "
        "objectives below to decide whether to call an exposed product tool now. Do not "
        "mention this retry. If the objective is no longer relevant after re-reading the "
        "current context, answer directly without saying you will check or look for options. "
        f"Tool Objectives: {objective_text}. Latest customer message: "
        f"{str(user_message or '').strip()[:240]}"
    )


def _required_commercial_evidence_retry_prompt(*, user_message: str, context: Dict[str, Any]) -> str:
    required_tools = [
        str(name or "").strip()
        for name in context.get("required_tools") or []
        if str(name or "").strip()
    ]
    if len(required_tools) > 1:
        instruction = (
            "Call each required read-only authority in the same response: "
            "search_promo_catalog only for the promotion question, and answer_order_faq only "
            "for the payment question. Do not submit the payment wording as a promo-catalog "
            "query or use one tool as a substitute for the other. Pass any named payment method "
            "as requested_payment_method; active checkout metadata decides support."
        )
        return (
            "Internal runtime commercial-evidence retry: independent structured commercial "
            f"questions still lack their authoritative lookups. {instruction} Answer from both "
            "tool results and do not mention this retry or any internal source names. Latest "
            f"customer message: {str(user_message or '').strip()[:240]}"
        )
    tool_name = str(context.get("tool_name") or "").strip()
    if tool_name == "search_promo_catalog":
        instruction = (
            "Call search_promo_catalog now using the promo type, requested brand, and tire size "
            "already present in the latest message and structured context. Treat those arguments "
            "as a proposed lookup plan; the runtime catalog decides whether the offer is reviewed "
            "and applicable. Use presentation_mode=gallery_if_available and "
            "explicit_redisplay=false so the validated surface can be completed without another "
            "model round. Do not infer promo eligibility from product matches or memory."
        )
    elif context.get("missing_payment_scopes"):
        scopes = json.dumps(
            context.get("missing_payment_scopes") or [],
            ensure_ascii=False,
            sort_keys=True,
        )
        instruction = (
            "Call answer_order_faq once for each missing customer-authored "
            "payment scope below, preserving its requested_payment_method, "
            "requested_product_brand, payment_option, and question. Do not "
            "combine it with a sibling method or term. Missing scopes: "
            f"{scopes}. Active checkout metadata decides support and brand "
            "eligibility."
        )
    else:
        instruction = (
            "Call answer_order_faq now. Pass the payment method or bank named by the customer as "
            "requested_payment_method and pass a requested product brand when one is explicitly "
            "part of the question. These are proposed lookup values; active checkout metadata "
            "decides support and brand eligibility. A stated preference is not proof of support."
        )
    return (
        "Internal runtime commercial-evidence retry: a structured commercial question still lacks "
        f"its authoritative lookup. {instruction} Answer from the tool result and do not mention "
        "this retry or any internal source names. Latest customer message: "
        f"{str(user_message or '').strip()[:240]}"
    )


def _required_policy_evidence_retry_prompt(
    *,
    user_message: str,
    context: Mapping[str, Any],
) -> str:
    """Build one bounded tool retry for an unmet general-policy obligation."""

    return (
        "Internal runtime tool-use retry: the latest customer turn asks a "
        "general delivery-policy question, but no authored policy evidence was "
        "retrieved. Call answer_policy_faq now with service_type=delivery and "
        "the complete latest customer question. Use the result only for "
        "published general delivery facts. Do not assert that the customer's "
        "exact address is serviceable, and do not mention this retry. Latest "
        f"customer message: {str(user_message or '').strip()[:300]}"
    )


def _should_retry_service_card_presentation(
    *,
    assistant_text: str,
    tool_results: Sequence[Dict[str, Any]],
    retry_events: Sequence[Dict[str, Any]],
) -> bool:
    """Retry once when the model duplicates deterministic service card content."""

    if not tool_results or any(event.get("type") == "service_card_presentation_retry" for event in retry_events):
        return False
    latest_cards: List[Dict[str, Any]] = []
    for tool_result in reversed(tool_results):
        full_result = tool_result.get("full_result") or {}
        if tool_result.get("name") not in {
            "find_installation_partners",
            "find_service_locations",
            "find_installation_slots",
        }:
            continue
        latest_cards = [card for card in full_result.get("installation_partner_cards") or [] if isinstance(card, dict)]
        break
    if not latest_cards:
        return False
    text = str(assistant_text or "")
    lowered = text.lower()
    if not _short_service_model_text(text, max_len=620, max_paragraphs=3):
        return True
    if _installation_partner_intro_has_renderer_owned_details(lowered):
        return True
    if _has_unvalidated_service_action_claim(lowered):
        return True
    if _has_no_walkin_policy(lowered):
        return True
    mentioned_names = 0
    for card in latest_cards:
        name = str(card.get("name") or "").strip().lower()
        if name and name in lowered:
            mentioned_names += 1
    return mentioned_names >= 2


def _deferred_presentation_retry_events(
    *,
    round_index: int,
    assistant_text: str,
    tool_results: Sequence[Dict[str, Any]],
    retry_events: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return presentation-cleanup events that should be handled by final composer."""

    events: List[Dict[str, Any]] = []
    if _should_retry_service_card_presentation(
        assistant_text=assistant_text,
        tool_results=tool_results,
        retry_events=retry_events,
    ):
        events.append(
            {
                "round": round_index,
                "type": "service_card_presentation_cleanup_deferred",
                "reason": "draft_may_duplicate_service_renderer_or_policy_content",
            }
        )
    return events


def _latest_named_tool_result(tool_results: Sequence[Dict[str, Any]], name: str) -> Dict[str, Any]:
    for tool_result in reversed(tool_results or []):
        if tool_result.get("name") == name:
            return tool_result
    return {}


def _service_card_presentation_retry_prompt(*, user_message: str) -> str:
    return (
        "Internal runtime service-card presentation retry: deterministic installation partner "
        "rows and service policy notes are already available and will be inserted by the runtime. "
        "Do not list partner names, do not use bullets, do not copy card rows, and do not restate "
        "the no-walk-in policy. Write only a short customer-facing lead-in plus one natural next "
        "step question. If the turn is mixed product/service and a tire sidewall confirmation is "
        "still useful, include that as a short follow-up after the service question. Latest customer "
        f"message: {str(user_message or '').strip()[:240]}"
    )


def _tool_schema_names(tool_schemas: Sequence[Dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for schema in tool_schemas:
        if not isinstance(schema, dict):
            continue
        function = schema.get("function")
        if isinstance(function, dict) and function.get("name"):
            names.add(str(function.get("name")))
    return names


def _recoverable_unexposed_read_tool_domains(
    tool_calls: Sequence[Dict[str, Any]],
    *,
    exposed_tool_names: Sequence[str],
    already_requested_domains: Sequence[str] = (),
) -> Dict[str, List[str]]:
    """Return safe domain expansions implied by unexposed read-tool calls.

    The main model can recognize a compound request that the cheaper signal
    extractor only partially classified. In that case, recompile the turn with
    the missing registered read domain and let the model retry against the
    actual schema. Never execute the unexposed call directly, and never recover
    unknown tools, mutation tools, general tools, or a domain already expanded
    during this turn.
    """

    exposed = {
        str(name or "").strip()
        for name in exposed_tool_names or []
        if str(name or "").strip()
    }
    already_requested = {
        str(domain or "").strip().lower()
        for domain in already_requested_domains or []
        if str(domain or "").strip()
    }
    output: Dict[str, List[str]] = {}
    for call in tool_calls or []:
        if not isinstance(call, dict):
            continue
        name = str(call.get("name") or "").strip()
        if not name or name in exposed:
            continue
        capability = TOOL_CAPABILITIES.get(name)
        if capability is None or capability.action_kind != "read":
            continue
        domain = str(capability.domain or "").strip().lower()
        if domain not in {"product", "service", "order"}:
            continue
        if domain in already_requested:
            continue
        output.setdefault(domain, [])
        if name not in output[domain]:
            output[domain].append(name)
    return output


def _expand_tool_schemas_after_order_progress(
    tool_schemas: Sequence[Dict[str, Any]],
    *,
    source_tool_name: str,
    compact_result: Dict[str, Any],
    round_index: int,
    record: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Expose the next order tool after the prior order tool creates its ref.

    Capability selection happens before the turn starts, but order submit and
    payment are sequential: a validated payload ref or submitted order id can
    appear only after a tool has already run. Keep the normal schema guard, then
    add the next schema only when the runtime has produced the required ref.
    """

    name = str(source_tool_name or "").strip()
    result = compact_result if isinstance(compact_result, dict) else {}
    existing = _tool_schema_names(tool_schemas)
    additions: List[str] = []
    if (
        name == "build_order_payload"
        and result.get("can_submit_order") is True
        and str(result.get("order_payload_ref") or "").strip()
    ):
        additions.append("submit_order")
    if (
        name == "validate_installation_slot"
        and result.get("status") == "ok"
        and result.get("valid") is True
    ):
        additions.append("build_order_payload")
    if (
        name == "submit_order"
        and result.get("can_request_payment") is True
        and str(result.get("order_id") or "").strip()
    ):
        additions.extend(["prepare_payment_request", "get_order_details"])

    additions = [tool_name for tool_name in additions if tool_name not in existing]
    if not additions:
        return list(tool_schemas or [])

    record.setdefault("dynamic_tool_schema_events", []).append(
        {
            "round": round_index,
            "type": "order_progress_tool_schema_expansion",
            "source_tool": name,
            "added_tools": additions,
            "order_payload_ref": result.get("order_payload_ref"),
            "order_id": result.get("order_id"),
        }
    )
    return [*list(tool_schemas or []), *schemas_for_tool_names(additions)]


def _normalize_probe_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _service_policy_note_block(notes: Sequence[Dict[str, Any]], model_text: str) -> str:
    if _has_no_walkin_policy(str(model_text or "").lower()):
        return ""
    lines = []
    for note in notes:
        text = _clean_inline_text(note.get("text") or "")
        if not text:
            continue
        note_id = str(note.get("id") or "").strip()
        if note_id == "no_walkin_setup":
            lines.append(text)
    return "\n".join(lines)


def _short_service_model_text(model_text: str, *, max_len: int, max_paragraphs: int = 2) -> str:
    text = _drop_internal_runtime_leakage(str(model_text or "")).strip()
    if not text or len(text) > max_len:
        return ""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs or len(paragraphs) > max(1, max_paragraphs):
        return ""
    if any(_looks_like_list_or_card(part) for part in paragraphs):
        return ""
    return "\n\n".join(paragraphs)


def _split_trailing_question(text: str) -> Tuple[str, str]:
    cleaned = _clean_inline_text(text)
    if "?" not in cleaned:
        return cleaned, ""
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
    if len(parts) == 1 and parts[-1].endswith("?"):
        return "", parts[-1]
    if len(parts) < 2 or not parts[-1].endswith("?"):
        return cleaned, ""
    return _clean_inline_text(" ".join(parts[:-1])), parts[-1]


def _installation_partner_intro_has_renderer_owned_details(lowered_text: str) -> bool:
    if re.search(r"\b\d+(?:\.\d+)?\s*km\b", lowered_text):
        return True
    if any(
        token in lowered_text
        for token in [
            "exact address",
            "partner contact",
            "branch contact",
            "contact number ng partner",
            "contact number ng branch",
            "map link",
        ]
    ):
        return True
    if ("walk-in" in lowered_text or "walk in" in lowered_text) and not _has_no_walkin_policy(lowered_text):
        return True
    return False


def _has_no_walkin_policy(lowered_text: str) -> bool:
    return any(
        token in lowered_text
        for token in [
            "no walk-in",
            "no walk in",
            "wala po kaming walk-in",
            "wala kaming walk-in",
            "do not accept walk-ins",
            "hindi po pwede ang walk-in",
            "reservation bago pumunta",
        ]
    )


def _has_unvalidated_service_action_claim(lowered_text: str) -> bool:
    return any(
        token in lowered_text
        for token in [
            "booking is confirmed",
            "confirmed booking",
            "slot is confirmed",
            "reserved na",
            "reservation is confirmed",
        ]
    )


def _product_search_intro_fallback(product_result: Optional[Dict[str, Any]] = None) -> str:
    product_result = product_result if isinstance(product_result, dict) else {}
    result_level = str(product_result.get("result_level") or "").strip()
    presentation_strategy = (
        product_result.get("presentation_strategy")
        if isinstance(product_result.get("presentation_strategy"), dict)
        else {}
    )
    relaxation = presentation_strategy.get("relaxation") if isinstance(presentation_strategy, dict) else None
    if isinstance(relaxation, dict) and relaxation.get("applied"):
        return "I did not find options matching every requested filter, so I included the closest useful matches from the available results."
    if result_level in {"partial", "alternate"}:
        return "I did not find an exact match for every requested detail, so I included the closest available alternatives."
    if result_level == "near_exact":
        return "I found near matches, but not every requested detail matched exactly."
    return "I found these options based on the requested tire size and preferences."


def _single_intro_paragraph(model_text: str) -> str:
    """Return the model's short intro, rejecting long or card-like responses."""

    text = _drop_internal_runtime_leakage(str(model_text or "")).strip()
    if not text:
        return ""
    if len(text) > 280:
        return ""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(paragraphs) > 1:
        if len(paragraphs) > 2 or any(_looks_like_list_or_card(part) for part in paragraphs):
            return ""
        text = " ".join(paragraphs)
        if len(text) > 280:
            return ""
    if _looks_like_list_or_card(text):
        return ""
    return _clean_inline_text(text)


def _clean_inline_text(text: str) -> str:
    """Collapse safe short model prose without changing wording."""

    return re.sub(r"\s+", " ", _strip_customer_markup(str(text or ""))).strip()


def _strip_customer_markup(text: str) -> str:
    """Remove channel-breaking markup while preserving model wording."""

    cleaned = str(text or "")
    cleaned = re.sub(r"<\s*br\s*/?\s*>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</\s*(?:p|div|ul|ol)\s*>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<\s*(?:p|div|ul|ol)(?:\s+[^>]*)?>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<\s*li(?:\s+[^>]*)?>\s*(?:[-*]\s*)?", "\n- ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</\s*li\s*>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</?(?:span|strong|em|b|i)[^>]*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = "\n".join(_restore_adjacent_plain_bullets(line) for line in cleaned.splitlines())
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n\s*\n(?=\s*[-*]\s+)", "\n", cleaned)
    return re.sub(r"(?:\n\s*){3,}", "\n\n", cleaned)


def _restore_adjacent_plain_bullets(line: str) -> str:
    """Preserve line breaks when model emits adjacent plain bullets."""

    text = str(line or "")
    stripped = text.lstrip()
    indent = text[: len(text) - len(stripped)]
    if not re.match(r"^[-*]\s+\S", stripped):
        return text
    if len(re.findall(r"[-*]\s+[A-Za-z0-9]", stripped)) < 2:
        return text
    parts = [
        part.strip()
        for part in re.split(r"(?=[-*]\s+[A-Za-z0-9])", stripped)
        if part.strip()
    ]
    if len(parts) < 2:
        return text
    return "\n".join(f"{indent}{part}" for part in parts)


_INTERNAL_RUNTIME_FIELD_PATTERN = re.compile(
    r"\b(?:"
    r"cards_will_be_inserted_by_runtime|card_runtime_insert|presentation_units?|"
    r"response_units?|render_surface|"
    r"runtime_renders_body|tool_calls?|tool_choice|tool_result|tool_results|"
    r"observation_ref|presentation_ref|service_location_ref|installation_partner_ref|"
    r"customer_explanation_hints|coverage_assessment|query_basis|result_level|"
    r"result_pool_summary|requires_validation|external_product_evidence|"
    r"selected_product_cards|installation_partner_card_headers|"
    r"trusted_order_total_candidates?|order_threshold_assessment"
    r")\b",
    re.IGNORECASE,
)
_INTERNAL_RUNTIME_SNAKE_FIELD_PATTERN = re.compile(
    r"\b(?:runtime|tool|presentation|card|cards|service|product|installation|order|coverage|customer|"
    r"selected|trusted|requires|source|status|result|query|fallback|observation|external|"
    r"availability|slot|branch|background|capability)_[a-z0-9_]+\b",
    re.IGNORECASE,
)


def _has_internal_runtime_leakage(text: str) -> bool:
    """Detect model leakage of structural runtime fields, not customer prose."""

    raw = str(text or "")
    lowered = raw.lower()
    if _INTERNAL_RUNTIME_FIELD_PATTERN.search(raw):
        return True
    if _INTERNAL_RUNTIME_SNAKE_FIELD_PATTERN.search(raw):
        return True
    return any(
        phrase in lowered
        for phrase in [
            "cards will be inserted by runtime",
            "runtime inserts the cards",
            "deterministic card body",
            "internal runtime",
            "tool output",
            "tool result",
        ]
    )


def _drop_internal_runtime_leakage(text: str) -> str:
    """Drop only paragraphs/lines that expose runtime fields or markers."""

    raw = str(text or "")
    if not raw or not _has_internal_runtime_leakage(raw):
        return raw
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", raw) if part.strip()]
    kept: List[str] = []
    for paragraph in paragraphs:
        if _has_internal_runtime_leakage(paragraph):
            clean_lines = [
                line.strip()
                for line in paragraph.splitlines()
                if line.strip() and not _has_internal_runtime_leakage(line)
            ]
            if clean_lines:
                cleaned_paragraph = " ".join(clean_lines)
                if _looks_like_renderer_placeholder_lead_in(cleaned_paragraph):
                    _intro, trailing_question = _split_trailing_question(cleaned_paragraph)
                    if trailing_question:
                        kept.append(trailing_question)
                    continue
                kept.append(cleaned_paragraph)
            continue
        kept.append(paragraph)
    return "\n\n".join(kept)


def _looks_like_renderer_placeholder_lead_in(text: str) -> bool:
    """Detect short setup lines whose body was an internal renderer marker."""

    cleaned = _clean_inline_text(text)
    if not cleaned or len(cleaned) > 160:
        return False
    lowered = cleaned.lower()
    if "?" in lowered:
        return False
    return any(
        token in lowered
        for token in [
            "summary",
            "order details",
            "details below",
            "ito po ang details",
            "eto po ang details",
            "ito po ang summary",
            "eto po ang summary",
            "cards below",
        ]
    )


def _looks_like_list_or_card(text: str) -> bool:
    return bool(re.search(r"(^|\n)\s*(?:[-*]|\d+[.)])\s+", text))


def _has_unvalidated_order_action_claim(lowered_text: str) -> bool:
    """Return true when model prose strays into guarded order/payment actions.

    Product-installment availability is a product fact when the customer asks for
    it and `product_search`/details tools ground it. Do not block that wording
    here; block only action-taking language that belongs to order readiness.
    """

    return any(
        token in lowered_text
        for token in [
            "pay the balance",
            "reserve with",
            "place the order",
            "submit the order",
            "order confirmation",
        ]
    )


def _has_unvalidated_fitment_claim(lowered_text: str) -> bool:
    """Return true when the intro asserts vehicle compatibility."""

    return any(
        token in lowered_text
        for token in [
            "compatible with",
            "fits your car",
            "fit your car",
            "fits your vehicle",
            "fit your vehicle",
        ]
    )


def _has_unvalidated_preference_completion_claim(
    lowered_text: str,
    presentation_strategy: Optional[Dict[str, Any]],
) -> bool:
    """Reject broad match claims when presentation data says filters were relaxed."""

    strategy = presentation_strategy if isinstance(presentation_strategy, dict) else {}
    relaxation = strategy.get("relaxation") if isinstance(strategy.get("relaxation"), dict) else {}
    missing = set(relaxation.get("shown_cards_missing_filters") or [])
    if "promo_only" in missing and any(token in lowered_text for token in ["promo options", "naka promo", "with promo"]):
        return True
    if "tire_category" in missing and any(token in lowered_text for token in ["budget options", "budget lang", "budget tires"]):
        return True
    budget_fit = strategy.get("budget_fit") if isinstance(strategy.get("budget_fit"), dict) else {}
    budget_claim = any(
        token in lowered_text
        for token in [
            "fits your budget",
            "fit your budget",
            "within your budget",
            "under your budget",
            "pasok sa budget",
        ]
    )
    if budget_claim and not budget_fit.get("all_presented_fit"):
        return True
    universal_claim = any(token in lowered_text for token in ["all ", "lahat", "every "])
    completion_claim = any(token in lowered_text for token in ["match", "fit", "meet", "pasok"])
    return bool(universal_claim and completion_claim)


def _format_brand_model(brand: Any, model: Any) -> str:
    brand_text = str(brand or "").strip()
    model_text = str(model or "").strip()
    if not brand_text:
        return model_text
    if model_text.upper().startswith(brand_text.upper()):
        return model_text
    return f"{brand_text} {model_text}".strip()


def _compact_assistant_context_for_next_turn(text: str, tool_results: Sequence[Dict[str, Any]]) -> str:
    presented_order_summary = any(
        result.get("name") == "build_order_summary" and (result.get("result") or {}).get("card_runtime_insert")
        for result in tool_results
    )
    if presented_order_summary:
        return "Assistant presented a deterministic order summary. Use Order Readiness and trusted refs for exact order facts; no order, booking, reservation, payment, or schedule action is confirmed yet."
    presented_selected_product = any(
        result.get("name") == "get_product_details" and (result.get("result") or {}).get("card_runtime_insert")
        for result in tool_results
    )
    if presented_selected_product:
        return "Assistant presented deterministic selected-product detail cards. Use Trusted Product Observations and selected card refs for exact product facts."
    presented_cards = any(
        result.get("name") == "product_search" and (result.get("result") or {}).get("cards_will_be_inserted_by_runtime")
        for result in tool_results
    )
    if presented_cards:
        return "Assistant presented product cards. Use Trusted Product Observations and Last Product Presentation for exact product refs and facts."
    presented_buckets = any(
        result.get("name") == "discover_brand_buckets"
        and (result.get("result") or {}).get("cards_will_be_inserted_by_runtime")
        for result in tool_results
    )
    if presented_buckets:
        return "Assistant presented deterministic brand/category menu cards. Use them only to narrow product options before exact tire options."
    presented_installation_slots = any(
        result.get("name") == "find_installation_slots"
        and (result.get("result") or {}).get("cards_will_be_inserted_by_runtime")
        for result in tool_results
    )
    if presented_installation_slots:
        slot_context = _installation_slot_context_for_next_turn(tool_results)
        return (
            "Assistant presented deterministic installation slot options. Use Trusted Service Observations "
            "for exact slot refs; no booking, order, reservation, payment, or schedule action is confirmed. "
            f"{slot_context}"
            "If the customer agrees to proceed after this and no deterministic order summary has been presented, "
            "treat that agreement as permission to show/validate the order summary first, not as submitted-order confirmation. "
            "The customer must choose an exact visible slot before order payload/submission."
        )
    presented_installation_partner_cards = any(
        result.get("name") in {"find_installation_partners", "find_service_locations", "find_installation_slots"}
        and (result.get("result") or {}).get("cards_will_be_inserted_by_runtime")
        for result in tool_results
    )
    if presented_installation_partner_cards:
        return "Assistant presented deterministic installation partner cards. Use Trusted Service Observations for service refs; no booking is confirmed."
    service_lookup = any(
        result.get("name") in {
            "find_installation_partners",
            "find_service_locations",
            "find_installation_slots",
        }
        for result in tool_results
    )
    if service_lookup:
        return "Assistant used read-only service tools. Use Trusted Service Observations for service refs and availability context; no booking is confirmed."
    quote_lookup = any(result.get("name") == "calculate_order_quote" for result in tool_results)
    if quote_lookup:
        return "Assistant used a read-only order quote. Use Order Readiness and trusted product/service refs for exact quote facts; no order, booking, reservation, payment, or schedule action is confirmed yet."
    faq_answer = any(result.get("name") in {"answer_product_faq", "answer_service_faq", "answer_order_faq"} for result in tool_results)
    if faq_answer:
        return "Assistant answered from an FAQ tool result. Use FAQ tools again for policy facts if the customer asks follow-up details."
    cleaned = str(text or "").strip()
    if len(cleaned) <= 700:
        return cleaned
    return cleaned[:697].rstrip() + "..."


def _installation_slot_context_for_next_turn(tool_results: Sequence[Dict[str, Any]]) -> str:
    """Summarize visible slot dates so follow-up turns do not reuse stale requests."""

    for result in reversed(tool_results or []):
        if result.get("name") != "find_installation_slots":
            continue
        payload = result.get("result") if isinstance(result.get("result"), dict) else {}
        semantics = payload.get("schedule_semantics") if isinstance(payload.get("schedule_semantics"), dict) else {}
        surfaces = payload.get("presentation_surfaces") if isinstance(payload.get("presentation_surfaces"), list) else []
        slot_lines: List[str] = []
        for surface in surfaces:
            if not isinstance(surface, dict):
                continue
            for card in surface.get("cards") or []:
                if not isinstance(card, dict):
                    continue
                for line in card.get("slot_summary_lines") or []:
                    text = str(line or "").strip()
                    if text and text not in slot_lines:
                        slot_lines.append(text)
        bits: List[str] = []
        requested = str(semantics.get("requested_date") or "").strip()
        returned = semantics.get("requested_date_returned")
        if requested and returned is False:
            bits.append(f"Requested date {requested} was not returned; visible rows are next-available slots, not the requested date.")
        if slot_lines:
            bits.append("Visible slot options: " + " | ".join(slot_lines[:2]) + ".")
        note = str(semantics.get("composer_grounding_note") or "").strip()
        if note:
            bits.append(note)
        return (" ".join(bits) + " ") if bits else ""
    return ""


def _product_observation_headers_with_delivery_state(
    headers: Sequence[Dict[str, Any]],
    presentation_history: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Distinguish generated product candidates from customer-visible cards."""

    delivered_refs = {
        str(item.get("presentation_ref") or "").strip()
        for item in presentation_history or []
        if isinstance(item, Mapping)
        and str(item.get("delivery_status") or "").strip().casefold()
        == "success"
        and str(item.get("presentation_ref") or "").strip()
    }
    return [
        {
            **dict(header),
            "presentation_delivered": (
                str(header.get("presentation_ref") or "").strip()
                in delivered_refs
            ),
        }
        for header in headers or []
        if isinstance(header, Mapping)
    ]


def _prune_irrelevant_promo_tools_for_location_product_resume(
    profile: Any,
    *,
    validated_choice_context: Mapping[str, Any],
    selected_product_context: Mapping[str, Any],
) -> None:
    """Shape a location-first click for model-led unresolved tire discovery.

    A validated city control establishes fulfillment location, not promo
    interest. When no trusted product exists, broad promo tools compete with
    the product/category tools needed to honor the customer's known tire size.
    The capability profile may otherwise be service-only because the synthetic
    click turn carries a validated location signal rather than repeating the
    earlier tire request. Make both normal product-discovery tools available,
    then remove only unrelated broad-promo schemas. This enables the model's
    choice; it does not force a product tool, rewrite the CTA, or infer a SKU.
    """

    if (
        not isinstance(validated_choice_context, Mapping)
        or validated_choice_context.get("validation_status") != "valid"
        or validated_choice_context.get("choice_type") != "serviceable_city"
        or selected_product_context
    ):
        return

    product_tools = ("product_search", "discover_brand_buckets")
    candidate = list(getattr(profile, "candidate_tools", []) or [])
    exposed = list(getattr(profile, "exposed_tools", []) or [])
    domains = list(getattr(profile, "selected_domains", []) or [])
    for name in product_tools:
        if name not in candidate:
            candidate.append(name)
        if name not in exposed:
            exposed.append(name)
    if "product" not in domains:
        domains.append("product")

    profile.candidate_tools = candidate
    profile.selected_domains = domains
    irrelevant_tools = {"search_promo_catalog", "present_promo_gallery"}
    pruned = [name for name in exposed if name not in irrelevant_tools]
    profile.exposed_tools = pruned
    reason = "validated_location_click:resume_unresolved_product_discovery"
    reasons = list(getattr(profile, "selection_reasons", []) or [])
    if reason not in reasons:
        profile.selection_reasons = [*reasons, reason]


def _guided_location_optional_reoffer_suppressed(
    *,
    choice_presentation_history: Sequence[Dict[str, Any]],
    choice_action_history: Sequence[Dict[str, Any]],
) -> bool:
    """Back off optional province re-engagement after a visible location move.

    Typed delivered presentations and validated actions are the only authority.
    This suppresses the post-product candidate, not the tool schema, so a new
    explicit customer request can still be handled by the main model.
    """

    location_choice_types = {"serviceable_province", "serviceable_city"}
    valid_action_refs = {
        str(action.get("presentation_ref") or "").strip()
        for action in choice_action_history or []
        if isinstance(action, dict)
        and str(action.get("choice_type") or "").strip()
        in location_choice_types
        and str(action.get("validation_status") or "").strip()
        in {"valid", "duplicate"}
    }
    if valid_action_refs:
        return True

    for presentation in reversed(list(choice_presentation_history or [])):
        if not isinstance(presentation, dict):
            continue
        if str(presentation.get("choice_type") or "").strip() != (
            "serviceable_province"
        ):
            continue
        if str(presentation.get("delivery_status") or "").strip() not in {
            "success",
            "evaluated",
        }:
            continue
        if presentation.get("superseded_at"):
            continue
        presentation_ref = str(
            presentation.get("presentation_ref") or ""
        ).strip()
        if presentation_ref and presentation_ref not in valid_action_refs:
            return True
    return False
