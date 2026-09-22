"""Run a staging-hosted Runtime V7 release-candidate journey matrix.

The probe exercises the deployed API, live model, trusted product/payment/promo
providers, renderer surfaces, and tracked-choice router. It always uses
return-only delivery and synthetic users. Full UTF-8 artifacts are written
before the compact console summary. Case and journey selectors allow long
live-model validation to be checkpointed without weakening individual gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime_v7.promotion_health_evaluator import (  # noqa: E402
    OPERATIONAL_FUNNEL_CONTRACT_SCHEMA_VERSION,
    OPERATIONAL_FUNNEL_CONTRACT_VERSION,
    SCENARIO_CONTRACT_SCHEMA_VERSION,
    SCENARIO_CONTRACT_VERSION,
    DEFAULT_HEALTH_POLICY,
    MUTATING_TOOLS,
    attach_artifact_integrity,
    canonical_json_digest,
    load_json,
    payment_authority_contract_failures,
    phrase_tolerant_fact_present,
    render_health_markdown,
    score_release_candidate,
    tool_argument_contract_failures,
    tool_argument_chain_contract_failures,
    tool_argument_chain_evidence,
)


DEFAULT_BASE_URL = (
    "https://gulong-chatbot-runtime-staging-107559478147.asia-southeast1.run.app"
)

FEATURE_EXPECTATION_MODES = frozenset(
    {
        "required_when_enabled",
        "not_applicable_when_unavailable",
        "forbidden_when_disabled",
    }
)

DEFAULT_FEATURE_EXPECTATIONS: Mapping[str, str] = {
    "promo_guided_actions": "not_applicable_when_unavailable",
    "product_choices": "required_when_enabled",
    "location_choices": "required_when_enabled",
    "schedule_choices": "required_when_enabled",
    "payment_option_choices": "required_when_enabled",
    "payment_method_choices": "required_when_enabled",
}


CASES: Sequence[Dict[str, Any]] = (
    {
        "id": "promo_toyo_truth",
        "message": (
            "May Buy 3 Get 1 ba ang Toyo for 175/65R14? "
            "Kung wala, ano yung valid promo alternatives?"
        ),
        "required_tools": (
            "search_promo_catalog",
            "present_promo_gallery",
        ),
        "require_scoped_negative_promo_contract": True,
        "promo_token_tracks_current_refs": True,
        "forbidden_token_prefixes": ("lc1|",),
        "expected_promo_requested_brand": "TOYO",
        "expected_promo_unmatched_brand": "TOYO",
    },
    {
        "id": "promo_apollo_valid",
        "message": (
            "May Apollo Buy 3 Get 1 ba for 175/65R14? "
            "Paki-check yung current price for four tires."
        ),
        "required_tools": ("search_promo_catalog", "product_search"),
        "required_product_promo_claim": {
            "brand": "APOLLO",
            "tire_size": "175/65R14",
            "pricing_basis": "buy3get1",
            "quantity": 4,
        },
        "promo_token_tracks_current_refs": True,
        "expected_promo_requested_brand": "APOLLO",
    },
    {
        "id": "promo_vredestein_valid",
        "message": (
            "May Vredestein Buy 3 Get 1 ba for 175/65R14? "
            "Paki-check yung current price for four tires."
        ),
        "required_tools": ("search_promo_catalog", "product_search"),
        "minimum_product_presentations": 1,
        "required_product_promo_claim": {
            "brand": "VREDESTEIN",
            "tire_size": "175/65R14",
            "pricing_basis": "buy3get1",
            "quantity": 4,
        },
        "promo_token_tracks_current_refs": True,
        "expected_promo_requested_brand": "VREDESTEIN",
    },
    {
        "id": "payment_yokohama_home_credit",
        "message": (
            "Pwede ba Home Credit? For Yokohama Pay Later, available ba "
            "ang 3-month 0% at BPI 6-month 0%?"
        ),
        "required_tools": ("answer_order_faq",),
        "required_composer_statuses": (
            "used",
            "repaired",
            "provider_grounded_payment_composition",
        ),
        "minimum_commercial_claims": 3,
        "require_payment_authority_contract": True,
        "expected_payment_claims": (
            ("Home Credit", "unsupported", "", ""),
            (
                "3-mos Installment (0% interest)",
                "eligible",
                "YOKOHAMA",
                "Pay Later",
            ),
            (
                "BPI 6-mos Installment (0% interest)",
                "not_eligible",
                "YOKOHAMA",
                "Pay Later",
            ),
        ),
        "expected_tool_chain_contracts": (
            {
                "id": "home_credit_scope",
                "tool": "answer_order_faq",
                "pre_args": {
                    "requested_payment_method": {
                        "equals": "Home Credit",
                        "kind": "payment_method",
                    }
                },
                "post_args": {
                    "requested_payment_method": {
                        "equals": "Home Credit",
                        "kind": "payment_method",
                    },
                    "requested_product_brand": {"absent": True},
                    "payment_option": {"absent": True},
                },
            },
            {
                "id": "yokohama_three_month_scope",
                "tool": "answer_order_faq",
                "args": {
                    "requested_payment_method": {
                        "contains": "3",
                        "kind": "payment_method",
                    },
                    "requested_product_brand": {
                        "equals": "YOKOHAMA",
                        "kind": "brand",
                    },
                    "payment_option": {
                        "equals": "Pay Later",
                        "kind": "payment_option",
                    },
                },
            },
            {
                "id": "yokohama_bpi_six_month_scope",
                "tool": "answer_order_faq",
                "pre_args": {
                    "requested_payment_method": {
                        # Model wording may omit a term that deterministic
                        # hydration can recover from one unambiguous customer
                        # clause. Provider identity and brand pairing must
                        # already be present; post-hydration remains exact.
                        "contains": "BPI",
                        "kind": "payment_method",
                    },
                },
                "post_args": {
                    "requested_payment_method": {
                        "contains": "BPI 6",
                        "kind": "payment_method",
                    },
                    "requested_product_brand": {
                        "equals": "YOKOHAMA",
                        "kind": "brand",
                    },
                    "payment_option": {
                        "equals": "Pay Later",
                        "kind": "payment_option",
                    },
                },
            },
        ),
    },
    {
        "id": "payment_two_brand_reordered_typo",
        "message": (
            "BPI 6mos 0% ba for Michelin? Tapos YOKOHAMA Pay Later 3mos 0% - availble?"
        ),
        "required_tools": ("answer_order_faq",),
        "required_composer_statuses": (
            "used",
            "repaired",
            "provider_grounded_payment_composition",
        ),
        "minimum_commercial_claims": 2,
        "require_payment_authority_contract": True,
        "expected_payment_claims": (
            (
                "BPI 6-mos Installment (0% interest)",
                "eligible",
                "MICHELIN",
                "Pay Now",
            ),
            (
                "3-mos Installment (0% interest)",
                "eligible",
                "YOKOHAMA",
                "Pay Later",
            ),
        ),
        "expected_tool_chain_contracts": (
            {
                "id": "michelin_bpi_six_month_scope",
                "tool": "answer_order_faq",
                "pre_args": {
                    "requested_payment_method": {
                        # Preserve the model's customer-backed provider/brand
                        # pairing while allowing deterministic hydration to
                        # restore one uniquely identifiable omitted term.
                        "contains": "BPI",
                        "kind": "payment_method",
                    },
                    "requested_product_brand": {
                        "equals": "MICHELIN",
                        "kind": "brand",
                    },
                },
                "post_args": {
                    "requested_payment_method": {
                        "contains": "BPI 6",
                        "kind": "payment_method",
                    },
                    "requested_product_brand": {
                        "equals": "MICHELIN",
                        "kind": "brand",
                    },
                    "payment_option": {"absent": True},
                },
            },
            {
                "id": "yokohama_three_month_reordered_scope",
                "tool": "answer_order_faq",
                "args": {
                    "requested_payment_method": {
                        "contains": "3",
                        "kind": "payment_method",
                    },
                    "requested_product_brand": {
                        "equals": "YOKOHAMA",
                        "kind": "brand",
                    },
                    "payment_option": {
                        "equals": "Pay Later",
                        "kind": "payment_option",
                    },
                },
            },
        ),
    },
    {
        "id": "payment_apollo_unknown_provider",
        "message": (
            "May Atome ba? For Apollo Pay Later naman, available ba ang "
            "3-month 0% at BPI 6-month 0%?"
        ),
        "required_tools": ("answer_order_faq",),
        "required_composer_statuses": (
            "used",
            "repaired",
            "provider_grounded_payment_composition",
        ),
        "minimum_commercial_claims": 3,
        "require_payment_authority_contract": True,
        "expected_payment_claims": (
            ("Atome", "unsupported", "", ""),
            (
                "3-mos Installment (0% interest)",
                "eligible",
                "APOLLO",
                "Pay Later",
            ),
            (
                "BPI 6-mos Installment (0% interest)",
                "eligible",
                "APOLLO",
                "Pay Later",
            ),
        ),
    },
    {
        "id": "availability_exact_brand_size",
        "message": (
            "May exact Yokohama 195/60R15 ba ngayon? "
            "Show only available matching products."
        ),
        "required_tools": ("product_search",),
        "expected_product_brand_size": ("YOKOHAMA", "195/60R15"),
        "product_cards_only_brands": ("YOKOHAMA",),
    },
    {
        "id": "size_zr_normalization",
        "message": "May Yokohama 265/35ZR21 ba? Paki-check exact available options.",
        "required_tools": ("product_search",),
        "expected_product_query": {
            "section_width": "265",
            "aspect_ratio": "35",
            "rim_size": "ZR21",
            "brands": ["YOKOHAMA"],
        },
        "require_exact_base_query_verified": True,
    },
    {
        "id": "brandless_promo_discovery",
        "message": "Ano yung current Buy 3 Get 1 promos natin?",
        "required_tools": ("search_promo_catalog",),
        "promo_token_tracks_current_refs": True,
        "forbidden_token_prefixes": ("lc1|",),
    },
    {
        "id": "business_contact_grounded",
        "message": "Ano hotline number ninyo?",
        "required_tools": ("get_business_contact",),
        "required_composer_statuses": ("used", "repaired"),
        "forbidden_token_prefixes": ("lc1|",),
    },
    {
        "id": "delivery_policy_grounded",
        "message": "Pwede delivery sa BGC?",
        "required_tools_any": ("answer_policy_faq", "answer_order_faq"),
        "required_composer_statuses": (
            "used",
            "repaired",
            "answer_goal_safe_fallback",
        ),
        "required_response_facts": (
            {
                "id": "delivery_area",
                "any_of": ({"all_terms": ("Greater", "Manila", "Area")},),
            },
            {
                "id": "delivery_courier",
                "any_of": ({"all_terms": ("Lalamove",)},),
            },
            {
                "id": "delivery_lead_time",
                "any_of": ({"regex": r"7\s*(?:-|to|hanggang)\s*10\s*(?:days?|araw)"},),
            },
        ),
        "forbidden_token_prefixes": ("lc1|",),
    },
    {
        "id": "delivery_policy_typo_variation",
        "message": "Nagdedeliver po ba kayo sa Makti? Mga ilang araw at anong courier?",
        "required_tools_any": ("answer_policy_faq", "answer_order_faq"),
        "required_composer_statuses": (
            "used",
            "repaired",
            "answer_goal_safe_fallback",
        ),
        "required_response_facts": (
            {
                "id": "delivery_area",
                "any_of": ({"all_terms": ("Greater", "Manila", "Area")},),
            },
            {
                "id": "delivery_courier",
                "any_of": ({"all_terms": ("Lalamove",)},),
            },
            {
                "id": "delivery_lead_time",
                "any_of": ({"regex": r"7\s*(?:-|to|hanggang)\s*10\s*(?:days?|araw)"},),
            },
        ),
        "forbidden_token_prefixes": ("lc1|",),
    },
    {
        "id": "semantic_store_location",
        "message": "location ng store?",
        "required_composer_statuses": ("used", "repaired", "skipped"),
        "required_response_facts": (
            {
                "id": "customer_location_question",
                "any_of": (
                    {
                        "regex": (
                            r"(?:saan(?:g)?|taga\s*saan|ano(?:ng)?|which|what)"
                            r".{0,60}(?:city|area|location|lugar|banda)"
                        )
                    },
                    {
                        "regex": (
                            r"(?:city|area|location|lugar|banda)"
                            r".{0,60}(?:ninyo|nyo|mo|kayo)"
                        )
                    },
                ),
            },
        ),
        "forbidden_response_facts": (
            {
                "id": "unsolicited_head_office_address",
                "any_of": ({"all_terms": ("1166", "Chino", "Roces")},),
            },
        ),
        "forbidden_tools": (
            "present_serviceable_location_choices",
            "find_installation_partners",
            "find_installation_slots",
        ),
        "forbidden_token_prefixes": ("lc1|",),
    },
    {
        "id": "explicit_head_office_address",
        "message": "Ano po ang exact address ng head office ninyo?",
        "required_composer_statuses": ("used", "repaired", "skipped"),
        "required_response_facts": (
            {
                "id": "head_office_address",
                "any_of": ({"all_terms": ("1166", "Chino", "Roces", "Makati")},),
            },
        ),
        "forbidden_tools": (
            "present_serviceable_location_choices",
            "find_installation_partners",
            "find_installation_slots",
        ),
        "forbidden_token_prefixes": ("lc1|",),
    },
    {
        "id": "province_schedule_gate",
        "message": (
            "May installation schedule ba sa Pampanga bukas for Michelin "
            "175/65R14? Hindi pa ako sure sa city."
        ),
        "required_tools": ("find_installation_slots",),
        "required_token_prefix": "lc1|",
        "forbidden_token_prefixes": ("ss1|", "pm1|", "po1|"),
    },
    {
        "id": "nonlinear_product_first",
        "message": (
            "Need 175/65R14, 4 pcs, Pay Later sana via BPI 6 months, "
            "installation in Quezon City tomorrow. Show tire options first."
        ),
        "required_tools": ("product_search",),
        "required_composer_statuses": (
            "used",
            "repaired",
            "payment_claim_safe_surface_fallback",
        ),
        "required_token_prefix": "ps1|",
        "forbidden_token_prefixes": ("sc1|", "pm1|", "po1|"),
    },
)

SMOKE_CASE_IDS = frozenset(
    {
        "business_contact_grounded",
        "delivery_policy_grounded",
        "payment_yokohama_home_credit",
    }
)

CASE_COVERAGE: Mapping[str, Mapping[str, Any]] = {
    "promo_toyo_truth": {
        "domain": "promotion",
        "variation_tags": ["unsupported_brand", "size", "alternatives"],
    },
    "promo_apollo_valid": {
        "domain": "promotion",
        "variation_tags": ["supported_brand", "size", "price"],
    },
    "promo_vredestein_valid": {
        "domain": "promotion",
        "variation_tags": ["supported_brand", "size", "price"],
    },
    "payment_yokohama_home_credit": {
        "domain": "payment",
        "variation_tags": ["compound", "unsupported_method", "brand", "term"],
    },
    "payment_two_brand_reordered_typo": {
        "domain": "payment",
        "variation_tags": ["compound", "reordered", "two_brands", "short_form", "typo"],
    },
    "payment_apollo_unknown_provider": {
        "domain": "payment",
        "variation_tags": ["compound", "unknown_method", "brand", "term"],
    },
    "availability_exact_brand_size": {
        "domain": "product",
        "variation_tags": ["exact_brand", "exact_size", "availability"],
    },
    "size_zr_normalization": {
        "domain": "product",
        "variation_tags": ["canonical_size", "zr", "availability"],
    },
    "brandless_promo_discovery": {
        "domain": "promotion",
        "variation_tags": ["brand_omitted", "discovery"],
    },
    "business_contact_grounded": {
        "domain": "business_contact",
        "variation_tags": ["tagalog", "direct_fact"],
    },
    "delivery_policy_grounded": {
        "domain": "delivery_policy",
        "variation_tags": ["yes_no", "location", "taglish"],
    },
    "delivery_policy_typo_variation": {
        "domain": "delivery_policy",
        "variation_tags": ["typo", "location", "multi_fact"],
    },
    "semantic_store_location": {
        "domain": "location",
        "variation_tags": [
            "short_form",
            "ambiguous_location",
            "customer_area_clarification",
        ],
    },
    "explicit_head_office_address": {
        "domain": "business_identity",
        "variation_tags": ["explicit_address", "head_office", "negative_control"],
    },
    "province_schedule_gate": {
        "domain": "scheduling",
        "variation_tags": ["incomplete_location", "date", "brand", "size"],
    },
    "nonlinear_product_first": {
        "domain": "multi_intent",
        "variation_tags": ["nonlinear", "quantity", "payment", "location", "date"],
    },
}

JOURNEY_CONTRACTS: Mapping[str, Mapping[str, Any]] = {
    "product_location": {
        "case_id": "product_location_schedule_payment_journey",
        "initial_message": (
            "Need 4 pcs 175/65R14, budget but safe. Installation sa "
            "Dasmarinas, Cavite tomorrow. Show tire options first."
        ),
        "steps": (
            "product",
            "location",
            "schedule",
            "payment_option",
            "payment_method",
        ),
    },
    "promo_details": {
        "case_id": "promo_details_informational_journey",
        "initial_message": "Show me the current promos.",
        "steps": ("promo_gallery", "promo_details"),
    },
    "about_brand": {
        "case_id": "about_brand_source_backed_journey",
        "initial_message": "Show me the current promos.",
        "steps": ("promo_gallery", "about_brand"),
    },
}

OPERATIONAL_FUNNEL_CONTRACTS: Mapping[str, Mapping[str, Any]] = {
    "size_brand_typed_location_shortform": {
        "case_id": "size_brand_typed_location_shortform",
        "provenance": "privacy_safe_july_transcript_corpus:july_live_049",
        "initial_message": "185 55 R15 pang mirage po mgkno po? westlake tire po",
        "customer_completion": "qc po",
        "expected_completion_signal": "location",
        "variation_tags": ["size_brand", "typo", "spacing", "typed_location"],
    },
    "size_brand_guided_location_choice": {
        "case_id": "size_brand_guided_location_choice",
        "provenance": "privacy_safe_july_transcript_corpus:safety_ineligible_bfg_promo",
        "initial_message": "265/70R16 BFGoodrich po, hm?",
        "guided_request_message": "Ano pong installation areas ang puwede kong piliin?",
        "expected_completion_signal": "location",
        "variation_tags": ["size_brand", "short_form", "guided_location"],
    },
    "size_brand_contact_fallback": {
        "case_id": "size_brand_contact_fallback",
        "provenance": "privacy_safe_july_transcript_corpus:july_live_046",
        "initial_message": "185/60R15 Apollo buy 3 get 1, hm po?",
        "location_uncertain_message": "Hindi pa ako sure sa city kung saan ipapakabit.",
        "customer_completion": "0917 000 0000",
        "expected_completion_signal": "contact_number",
        "variation_tags": ["size_brand", "location_uncertain", "contact_fallback"],
    },
    "size_brand_location_complete_negative_control": {
        "case_id": "size_brand_location_complete_negative_control",
        "provenance": "privacy_safe_july_transcript_corpus:safety_single_focus_contact",
        "initial_message": "185/65R15 Michelin po, Quezon City.",
        "expected_completion_signal": "location",
        "variation_tags": ["size_brand_location", "negative_control"],
    },
}


def scenario_definition_digest(tier: str) -> str:
    """Digest the approved inputs and exact mechanical contracts for one tier."""

    selected = [case for case in CASES if _case_in_tier(str(case["id"]), tier)]
    journeys = JOURNEY_CONTRACTS if tier in {"promotion", "full"} else {}
    return canonical_json_digest(
        {
            "contract_version": SCENARIO_CONTRACT_VERSION,
            "tier": tier,
            "cases": selected,
            "coverage": {
                str(case["id"]): CASE_COVERAGE.get(str(case["id"])) or {}
                for case in selected
            },
            "journeys": journeys,
        }
    )


def build_scenario_contract(tier: str) -> Dict[str, Any]:
    """Build the immutable required-corpus manifest used by the scorer."""

    cases = [str(case["id"]) for case in CASES if _case_in_tier(str(case["id"]), tier)]
    journeys = [
        str(item["case_id"])
        for item in (
            JOURNEY_CONTRACTS.values() if tier in {"promotion", "full"} else []
        )
    ]
    return {
        "schema_version": SCENARIO_CONTRACT_SCHEMA_VERSION,
        "contract_version": SCENARIO_CONTRACT_VERSION,
        "verification_basis": "versioned_preverified_expected_contracts",
        "definition_digest": scenario_definition_digest(tier),
        "required_case_ids": cases,
        "required_journey_ids": journeys,
    }


def operational_funnel_definition_digest(tier: str) -> str:
    """Digest reviewed, data-derived progression inputs and stage expectations."""

    selected = OPERATIONAL_FUNNEL_CONTRACTS if tier in {"promotion", "full"} else {}
    return canonical_json_digest(
        {
            "contract_version": OPERATIONAL_FUNNEL_CONTRACT_VERSION,
            "tier": tier,
            "scenarios": selected,
        }
    )


def build_operational_funnel_contract(tier: str) -> Dict[str, Any]:
    """Build the immutable manifest for synthetic pre-delivery funnel checks."""

    required_ids = (
        list(OPERATIONAL_FUNNEL_CONTRACTS) if tier in {"promotion", "full"} else []
    )
    return {
        "schema_version": OPERATIONAL_FUNNEL_CONTRACT_SCHEMA_VERSION,
        "contract_version": OPERATIONAL_FUNNEL_CONTRACT_VERSION,
        "verification_basis": "reviewed_privacy_safe_transcript_derived_scenarios",
        "measurement_boundary": "rendered_response_and_planned_qualification_before_delivery",
        "definition_digest": operational_funnel_definition_digest(tier),
        "required_scenario_ids": required_ids,
    }


def resolve_feature_expectations(
    overrides: Mapping[str, Any] | None = None,
) -> Dict[str, str]:
    """Validate explicit environment expectations without inferring activation."""

    values = dict(overrides or {})
    unknown = sorted(set(values) - set(DEFAULT_FEATURE_EXPECTATIONS))
    if unknown:
        raise ValueError(f"unknown feature expectation(s): {', '.join(unknown)}")
    resolved = dict(DEFAULT_FEATURE_EXPECTATIONS)
    for feature, mode_value in values.items():
        mode = str(mode_value or "").strip()
        if mode not in FEATURE_EXPECTATION_MODES:
            raise ValueError(
                f"invalid feature expectation for {feature}: {mode or '<empty>'}"
            )
        resolved[str(feature)] = mode
    return resolved


def feature_surface_decision(
    *,
    feature: str,
    token: str,
    feature_expectations: Mapping[str, str],
    unavailable: bool = False,
    unavailable_reason: str = "",
) -> Dict[str, Any]:
    """Apply one explicit feature expectation to observed rendered evidence."""

    mode = str(feature_expectations.get(feature) or "").strip()
    if mode not in FEATURE_EXPECTATION_MODES:
        return {
            "feature": feature,
            "expectation": mode,
            "status": "failed",
            "token_present": bool(token),
            "activate": False,
            "failure": f"feature_expectation_missing_or_invalid:{feature}",
        }
    if mode == "forbidden_when_disabled":
        if token:
            return {
                "feature": feature,
                "expectation": mode,
                "status": "failed",
                "token_present": True,
                "activate": False,
                "failure": f"forbidden_feature_surface_rendered:{feature}",
            }
        return {
            "feature": feature,
            "expectation": mode,
            "status": "forbidden_and_absent",
            "token_present": False,
            "activate": False,
            "failure": "",
        }
    if token:
        return {
            "feature": feature,
            "expectation": mode,
            "status": "available",
            "token_present": True,
            "activate": True,
            "failure": "",
        }
    if mode == "not_applicable_when_unavailable" and unavailable:
        return {
            "feature": feature,
            "expectation": mode,
            "status": "not_applicable",
            "token_present": False,
            "activate": False,
            "reason": unavailable_reason or "authoritative_surface_unavailable",
            "failure": "",
        }
    failure = (
        f"required_feature_surface_missing:{feature}"
        if mode == "required_when_enabled"
        else f"feature_unavailability_not_proven:{feature}"
    )
    return {
        "feature": feature,
        "expectation": mode,
        "status": "failed",
        "token_present": False,
        "activate": False,
        "failure": failure,
    }


def _public_feature_outcome(decision: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        str(key): value
        for key, value in decision.items()
        if key not in {"activate", "failure"} and value not in (None, "", [], {})
    }


def _promo_surface_unavailable(response: Mapping[str, Any]) -> tuple[bool, str]:
    """Require an explicit provider-owned empty ref list before allowing N/A."""

    for call in (response.get("debug") or {}).get("tool_calls") or []:
        if not isinstance(call, Mapping) or call.get("name") != "search_promo_catalog":
            continue
        scope = call.get("commercial_scope")
        if not isinstance(scope, Mapping) or "allowed_promo_refs" not in scope:
            continue
        refs = scope.get("allowed_promo_refs")
        if isinstance(refs, list) and not refs:
            return True, "no_current_promo_refs"
    return False, ""


def _promo_action_unavailable(
    response: Mapping[str, Any], *, caption_pattern: str
) -> tuple[bool, str]:
    """Prove one action is absent only from a complete rendered promo surface."""

    catalog_unavailable, reason = _promo_surface_unavailable(response)
    if catalog_unavailable:
        return True, reason
    presentation = response.get("promo_presentation") or {}
    card_refs = {
        str(value or "").strip()
        for value in presentation.get("card_refs") or []
        if str(value or "").strip()
    }
    if not card_refs:
        return False, ""
    rendered_card_refs: set[str] = set()
    matching_action = False
    for message in response.get("content_messages") or []:
        if not isinstance(message, Mapping):
            continue
        for element in message.get("elements") or []:
            if not isinstance(element, Mapping):
                continue
            for button in element.get("buttons") or []:
                if not isinstance(button, Mapping):
                    continue
                caption = str(button.get("caption") or "")
                for action in button.get("actions") or []:
                    if not isinstance(action, Mapping):
                        continue
                    value = str(action.get("value") or "").strip()
                    if not value.startswith("pc1|"):
                        continue
                    rendered_card_refs.update(
                        card_ref for card_ref in card_refs if card_ref in value
                    )
                    if re.search(caption_pattern, caption, flags=re.IGNORECASE):
                        matching_action = True
    if matching_action or rendered_card_refs != card_refs:
        return False, ""
    return True, "rendered_current_promo_cards_lack_action"


def _checkout_surface_unavailable(
    response: Mapping[str, Any], *, count_field: str
) -> tuple[bool, str]:
    status = (response.get("debug") or {}).get("checkout_choice_surface_status") or {}
    reason = str(status.get("reason") or "")
    unavailable = reason == "surface_empty" and int(status.get(count_field) or 0) == 0
    return unavailable, reason


def _choice_validation_failures(
    response: Mapping[str, Any], expected_choice_type: str | Sequence[str]
) -> List[str]:
    expected_types = (
        (expected_choice_type,)
        if isinstance(expected_choice_type, str)
        else tuple(expected_choice_type)
    )
    expected_label = "|".join(expected_types)
    validation = response.get("choice_action_validation") or {}
    failures: List[str] = []
    if validation.get("status") != "accepted":
        failures.append(
            f"choice_action_not_accepted:{expected_label}:"
            f"{validation.get('status') or 'missing'}"
        )
    if validation.get("validation_status") != "valid":
        failures.append(
            f"choice_action_not_valid:{expected_label}:"
            f"{validation.get('validation_status') or 'missing'}"
        )
    if validation.get("choice_type") not in expected_types:
        failures.append(
            f"choice_action_wrong_type:{expected_label}:"
            f"{validation.get('choice_type') or 'missing'}"
        )
    return failures


def _intent_observability_failures(
    response: Mapping[str, Any],
    *,
    expected_tags: Sequence[str],
    expected_event_id: str = "",
) -> List[str]:
    """Validate deterministic intent triggers and their routing-independent trace."""

    tagging = response.get("tagging_result") or {}
    observed_tags = {
        str(item.get("tag") or "")
        for key in ("tags_to_add", "tags_skipped_existing")
        for item in tagging.get(key) or []
        if isinstance(item, Mapping)
    }
    failures = [
        f"missing_intent_trigger:{tag}"
        for tag in expected_tags
        if tag not in observed_tags
    ]
    qualifications = [
        item
        for item in tagging.get("analytical_qualifications") or []
        if isinstance(item, Mapping) and item.get("qualification_level") == "moderate"
    ]
    if not qualifications:
        failures.append("missing_moderate_analytical_qualification")
        return failures
    qualification = qualifications[0]
    for key, expected in (
        ("schema_version", 1),
        ("kind", "analytical_qualification"),
        ("countable", True),
        ("decision_mode", "deterministic"),
    ):
        if qualification.get(key) != expected:
            failures.append(f"invalid_analytical_qualification:{key}")
    if not str(qualification.get("rule_version") or "").strip():
        failures.append("invalid_analytical_qualification:rule_version")
    qualification_event_id = str(
        qualification.get("qualification_event_id") or ""
    ).strip()
    if not re.fullmatch(r"aq_v1_[0-9a-f]{24}", qualification_event_id):
        failures.append("invalid_analytical_qualification:qualification_event_id")
    event_identity = qualification.get("event_identity")
    if not isinstance(event_identity, Mapping):
        failures.append("invalid_analytical_qualification:event_identity")
    else:
        if not str(event_identity.get("event_id") or "").strip():
            failures.append("invalid_analytical_qualification:event_identity.event_id")
        if not str(event_identity.get("idempotency_key") or "").strip():
            failures.append(
                "invalid_analytical_qualification:event_identity.idempotency_key"
            )
        if expected_event_id and event_identity.get("event_id") != expected_event_id:
            failures.append("analytical_qualification_event_identity_mismatch")
    return failures


def _after_turn_customer_signal_evidence(
    response: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return redacted canonical signal provenance from the post-turn ledger."""

    snapshots = ((response.get("debug") or {}).get("turn_trace") or {}).get(
        "state_snapshots"
    ) or []
    ledger: Sequence[Any] = ()
    for snapshot in snapshots:
        if not isinstance(snapshot, Mapping):
            continue
        if snapshot.get(
            "state_name"
        ) == "background_signal_ledger_after_turn" and isinstance(
            snapshot.get("state_json"), list
        ):
            ledger = snapshot["state_json"]
            break
    trusted_sources = {
        "latest_user_message",
        "customer_history",
        "validated_choice_action",
    }
    aliases = {
        "preferred_brands": "tire_brand",
        "required_brands": "tire_brand",
    }
    sources_by_key: Dict[str, set[str]] = {}
    for signal in ledger:
        if not isinstance(signal, Mapping):
            continue
        source = str(signal.get("source") or "").strip()
        relation = str(signal.get("relation") or "asserted").strip().casefold()
        if source not in trusted_sources or relation in {
            "question_only",
            "conditional",
            "rejected",
            "historical",
        }:
            continue
        if signal.get("value") in (None, "", [], {}):
            continue
        raw_key = str(signal.get("key") or "").strip()
        key = aliases.get(raw_key, raw_key)
        if key in {"tire_size", "tire_brand", "location", "contact_number"}:
            sources_by_key.setdefault(key, set()).add(source)
    return {
        "ledger_present": bool(ledger),
        "keys": sorted(sources_by_key),
        "sources_by_key": {
            key: sorted(values) for key, values in sorted(sources_by_key.items())
        },
    }


def _planned_mh_signal_keys(response: Mapping[str, Any]) -> set[str]:
    tagging = response.get("tagging_result") or {}
    keys: set[str] = set()
    for qualification in tagging.get("analytical_qualifications") or []:
        if not isinstance(qualification, Mapping):
            continue
        if (
            qualification.get("qualification_level") != "moderate"
            or qualification.get("countable") is not True
        ):
            continue
        keys.update(
            str(item.get("key") or "")
            for item in qualification.get("source_signals") or []
            if isinstance(item, Mapping) and item.get("present") is True
        )
    return keys


def _visible_location_request(response: Mapping[str, Any]) -> bool:
    """Recognize an explicit customer location request on rendered surfaces."""

    if find_choice_token(response, prefixes=("lc1|",)):
        return True
    text = " ".join(_rendered_text_surfaces(response).casefold().split())
    location = r"(?:located|location|area|city|province|barangay|lugar|serviceable\s+areas?)"
    question = r"(?:saan|saang|anong|ano|which|what|where)"
    request = r"(?:paki(?:send|bigay|select)|send|share|provide|ibigay|select|choose)"
    customer = r"(?:ninyo|niyo|nyo|mo|your)"
    purpose = r"(?:install(?:ation)?|ipa-?install|delivery|serviceable)"
    return bool(
        # A wh-question has to be about a location concept, rather than a
        # statement that happens to contain the word "location".
        re.search(rf"\b{question}\b.{{0,70}}\b{location}\b", text)
        # Imperative guided alternatives explicitly cue the customer to give
        # their own location even when no question mark is present.
        or re.search(rf"\b{request}\b.{{0,55}}\b{location}\b", text)
        # Natural alternatives such as "saan ... prefer niyo" can place the
        # customer cue after the serviceable/install context.
        or (
            bool(
                re.search(
                    rf"\b{question}\b.{{0,140}}\b{location}\b.{{0,70}}"
                    rf"\b(?:{customer}|prefer)\b",
                    text,
                )
            )
            and bool(re.search(rf"\b{purpose}\b", text))
        )
    )


def _rendered_text_surfaces(response: Mapping[str, Any]) -> str:
    """Collect only structured customer-visible text, never composer/debug prose."""

    surfaces = [customer_text(response)]
    for message in response.get("content_messages") or []:
        if (
            isinstance(message, Mapping)
            and str(message.get("type") or "").casefold() == "text"
        ):
            surfaces.append(str(message.get("text") or ""))
    return "\n".join(item for item in surfaces if item)


def _visible_contact_request(response: Mapping[str, Any]) -> bool:
    """Recognize a customer-contact request without confusing business hotlines."""

    text = " ".join(customer_text(response).casefold().split())
    if any(term in text for term in ("hotline", "customer service number")):
        return False
    contact = r"(?:contact|mobile|phone|cellphone|cp)\s*(?:no\.?|number)?"
    request = r"(?:paki(?:send|bigay)|send|share|provide|ibigay|ano|anong|what)"
    owner = r"(?:ninyo|nyo|mo|your|customer)"
    return bool(
        re.search(rf"\b{request}\b.{{0,45}}\b{contact}\b", text)
        or re.search(rf"\b{contact}\b.{{0,35}}\b{owner}\b", text)
    )


def _visible_response_rendered(response: Mapping[str, Any]) -> bool:
    return bool(
        customer_text(response).strip()
        or [
            item
            for item in response.get("content_messages") or []
            if isinstance(item, Mapping)
        ]
    )


def _funnel_stage(passed: bool, **evidence: Any) -> Dict[str, Any]:
    return {"applicable": True, "passed": bool(passed), "evidence": evidence}


def _record_stage_failure(
    failures: List[str], stages: Mapping[str, Mapping[str, Any]], stage_name: str
) -> None:
    if not bool((stages.get(stage_name) or {}).get("passed")):
        failures.append(f"operational_stage_failed:{stage_name}")


def _operational_funnel_result(
    *,
    contract: Mapping[str, Any],
    user_id: str,
    failures: Sequence[str],
    stages: Mapping[str, Mapping[str, Any]],
    steps: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    return {
        "case_id": contract["case_id"],
        "expected_contract": dict(contract),
        "domain": "size_brand_operational_funnel",
        "variation_tags": list(contract.get("variation_tags") or []),
        "user_id": user_id,
        "passed": not failures,
        "mechanical_passed": not failures,
        "failures": list(dict.fromkeys(failures)),
        "funnel_stages": dict(stages),
        "steps": list(steps),
        "summary": [compact_response(step["response"]) for step in steps],
    }


def run_operational_funnel_scenario(
    scenario_id: str,
    *,
    base_url: str,
    timeout_s: float,
    run_id: str,
    expected_release: str,
    expected_git_sha: str = "",
    expected_environment: str = "",
) -> Dict[str, Any]:
    """Exercise one reviewed size+brand completion path before delivery."""

    contract = OPERATIONAL_FUNNEL_CONTRACTS[scenario_id]
    user_id = f"rc-funnel-{scenario_id}-{uuid.uuid4().hex[:8]}"
    steps: List[Dict[str, Any]] = []
    failures: List[str] = []
    stages: Dict[str, Dict[str, Any]] = {}

    first_event = f"{run_id}_{scenario_id}_1"
    first = chat(
        base_url,
        user_id=user_id,
        message=str(contract["initial_message"]),
        event_id=first_event,
        reset=True,
        timeout_s=timeout_s,
    )
    steps.append(
        {"action": "chat", "message": contract["initial_message"], "response": first}
    )
    first_contract = {
        "required_tools": ("product_search",),
        "allow_location_progression_guard": True,
    }
    if scenario_id == "size_brand_location_complete_negative_control":
        first_contract["allow_service_claim_surface_sanitized"] = True
    failures.extend(
        evaluate(
            first_contract,
            first,
            expected_release=expected_release,
            expected_git_sha=expected_git_sha,
            expected_environment=expected_environment,
        )
    )
    first_signals = _after_turn_customer_signal_evidence(first)
    first_keys = set(first_signals["keys"])

    if scenario_id == "size_brand_location_complete_negative_control":
        stages["excluded_from_near_miss"] = _funnel_stage(
            {"tire_size", "tire_brand", "location"} <= first_keys,
            signal_evidence=first_signals,
            exclusion_reason="location_already_customer_supplied",
        )
        stages["location_not_reasked"] = _funnel_stage(
            not _visible_location_request(first),
            rendered_location_request=_visible_location_request(first),
        )
        mh_failures = _intent_observability_failures(
            first, expected_tags=("Moderate Intent",), expected_event_id=first_event
        )
        mh_keys = _planned_mh_signal_keys(first)
        stages["official_mh_planned"] = _funnel_stage(
            not mh_failures and {"tire_size", "tire_brand", "location"} <= mh_keys,
            qualification_failures=mh_failures,
            source_signal_keys=sorted(mh_keys),
            boundary="planned_before_persistence",
        )
        stages["final_response_rendered"] = _funnel_stage(
            _visible_response_rendered(first),
            boundary="final_response_before_delivery",
            delivery_required=False,
        )
        failures.extend(mh_failures)
        for name in stages:
            _record_stage_failure(failures, stages, name)
        return _operational_funnel_result(
            contract=contract,
            user_id=user_id,
            failures=failures,
            stages=stages,
            steps=steps,
        )

    stages["eligible_near_miss"] = _funnel_stage(
        {"tire_size", "tire_brand"} <= first_keys
        and not ({"location", "contact_number"} & first_keys)
        and not _planned_mh_signal_keys(first),
        signal_evidence=first_signals,
        required_present=["tire_size", "tire_brand"],
        required_absent=["location", "contact_number"],
    )

    current = first
    if scenario_id in {
        "size_brand_guided_location_choice",
        "size_brand_contact_fallback",
    }:
        product_token = find_choice_token(current, prefixes=("ps1|",))
        if product_token and not _visible_location_request(current):
            current = click(
                base_url,
                user_id=user_id,
                token=product_token,
                event_id=f"{run_id}_{scenario_id}_product",
                timeout_s=timeout_s,
            )
            steps.append(
                {"action": "click_product", "token": product_token, "response": current}
            )
            failures.extend(
                evaluate(
                    {},
                    current,
                    expected_release=expected_release,
                    expected_git_sha=expected_git_sha,
                    expected_environment=expected_environment,
                )
            )
            failures.extend(_choice_validation_failures(current, "product_selection"))

    if scenario_id == "size_brand_guided_location_choice" and not find_choice_token(
        current, prefixes=("lc1|",)
    ):
        guided_event = f"{run_id}_{scenario_id}_guided_request"
        current = chat(
            base_url,
            user_id=user_id,
            message=str(contract["guided_request_message"]),
            event_id=guided_event,
            reset=False,
            timeout_s=timeout_s,
        )
        steps.append(
            {
                "action": "chat",
                "message": contract["guided_request_message"],
                "response": current,
            }
        )
        failures.extend(
            evaluate(
                {},
                current,
                expected_release=expected_release,
                expected_git_sha=expected_git_sha,
                expected_environment=expected_environment,
            )
        )

    stages["location_request_rendered"] = _funnel_stage(
        _visible_location_request(current),
        rendered_location_request=_visible_location_request(current),
        has_guided_location_action=bool(find_choice_token(current, prefixes=("lc1|",))),
        boundary="final_response_before_delivery",
    )

    final = current
    final_event = first_event
    completion_key = str(contract.get("expected_completion_signal") or "")
    if scenario_id == "size_brand_typed_location_shortform":
        final_event = f"{run_id}_{scenario_id}_typed_location"
        final = chat(
            base_url,
            user_id=user_id,
            message=str(contract["customer_completion"]),
            event_id=final_event,
            reset=False,
            timeout_s=timeout_s,
        )
        steps.append(
            {
                "action": "chat",
                "message": contract["customer_completion"],
                "response": final,
            }
        )
        failures.extend(
            evaluate(
                {"required_composer_statuses": ("used", "repaired", "skipped")},
                final,
                expected_release=expected_release,
                expected_git_sha=expected_git_sha,
                expected_environment=expected_environment,
            )
        )
        final_signals = _after_turn_customer_signal_evidence(final)
        stages["typed_response_accepted"] = _funnel_stage(
            completion_key in set(final_signals["keys"]),
            signal_evidence=final_signals,
            input_mode="typed_short_form",
        )
    elif scenario_id == "size_brand_guided_location_choice":
        city_accepted = False
        for index in range(2):
            token = find_choice_token(final, prefixes=("lc1|",))
            if not token:
                break
            final_event = f"{run_id}_{scenario_id}_location_{index + 1}"
            final = click(
                base_url,
                user_id=user_id,
                token=token,
                event_id=final_event,
                timeout_s=timeout_s,
            )
            steps.append(
                {"action": "click_location", "token": token, "response": final}
            )
            failures.extend(
                evaluate(
                    {},
                    final,
                    expected_release=expected_release,
                    expected_git_sha=expected_git_sha,
                    expected_environment=expected_environment,
                )
            )
            validation_failures = _choice_validation_failures(
                final, ("serviceable_province", "serviceable_city")
            )
            failures.extend(validation_failures)
            if (
                not validation_failures
                and (final.get("choice_action_validation") or {}).get("choice_type")
                == "serviceable_city"
            ):
                city_accepted = True
                break
        final_signals = _after_turn_customer_signal_evidence(final)
        stages["guided_response_accepted"] = _funnel_stage(
            city_accepted,
            accepted_choice_type=(final.get("choice_action_validation") or {}).get(
                "choice_type"
            ),
            required_choice_type="serviceable_city",
        )
    else:
        uncertain_event = f"{run_id}_{scenario_id}_uncertain"
        uncertain = chat(
            base_url,
            user_id=user_id,
            message=str(contract["location_uncertain_message"]),
            event_id=uncertain_event,
            reset=False,
            timeout_s=timeout_s,
        )
        steps.append(
            {
                "action": "chat",
                "message": contract["location_uncertain_message"],
                "response": uncertain,
            }
        )
        failures.extend(
            evaluate(
                {"required_composer_statuses": ("used", "repaired", "skipped")},
                uncertain,
                expected_release=expected_release,
                expected_git_sha=expected_git_sha,
                expected_environment=expected_environment,
            )
        )
        stages["contact_fallback_offered"] = _funnel_stage(
            _visible_contact_request(uncertain),
            rendered_contact_request=_visible_contact_request(uncertain),
            boundary="final_response_before_delivery",
        )
        uncertain_signals = _after_turn_customer_signal_evidence(uncertain)
        stages["uncertain_location_not_captured"] = _funnel_stage(
            "location" not in set(uncertain_signals["keys"]),
            signal_evidence=uncertain_signals,
            customer_stance="location_uncertain",
        )
        uncertain_mh_keys = _planned_mh_signal_keys(uncertain)
        stages["mh_not_planned_before_contact"] = _funnel_stage(
            not uncertain_mh_keys,
            source_signal_keys=sorted(uncertain_mh_keys),
        )
        final_event = f"{run_id}_{scenario_id}_typed_contact"
        final = chat(
            base_url,
            user_id=user_id,
            message=str(contract["customer_completion"]),
            event_id=final_event,
            reset=False,
            timeout_s=timeout_s,
        )
        steps.append(
            {
                "action": "chat",
                "message": contract["customer_completion"],
                "response": final,
            }
        )
        failures.extend(
            evaluate(
                {"required_composer_statuses": ("used", "repaired", "skipped")},
                final,
                expected_release=expected_release,
                expected_git_sha=expected_git_sha,
                expected_environment=expected_environment,
            )
        )
        final_signals = _after_turn_customer_signal_evidence(final)
        stages["typed_response_accepted"] = _funnel_stage(
            completion_key in set(final_signals["keys"]),
            signal_evidence=final_signals,
            input_mode="typed_contact",
        )

    final_keys = set(final_signals["keys"])
    canonical_stage = (
        "canonical_contact_captured"
        if completion_key == "contact_number"
        else f"canonical_{completion_key}_captured"
    )
    stages[canonical_stage] = _funnel_stage(
        completion_key in final_keys,
        signal_evidence=final_signals,
        trusted_sources=["latest_user_message", "validated_choice_action"],
    )
    mh_failures = _intent_observability_failures(
        final, expected_tags=("Moderate Intent",), expected_event_id=final_event
    )
    mh_keys = _planned_mh_signal_keys(final)
    stages["official_mh_planned"] = _funnel_stage(
        not mh_failures and {"tire_size", "tire_brand", completion_key} <= mh_keys,
        qualification_failures=mh_failures,
        source_signal_keys=sorted(mh_keys),
        boundary="planned_before_persistence",
    )
    stages["final_response_rendered"] = _funnel_stage(
        _visible_response_rendered(final),
        boundary="final_response_before_delivery",
        delivery_required=False,
    )
    failures.extend(mh_failures)
    for name in stages:
        _record_stage_failure(failures, stages, name)
    return _operational_funnel_result(
        contract=contract,
        user_id=user_id,
        failures=failures,
        stages=stages,
        steps=steps,
    )


def _journey_result(
    *,
    case_id: str,
    variation_tags: Sequence[str],
    user_id: str,
    failures: Sequence[str],
    steps: Sequence[Mapping[str, Any]],
    feature_outcomes: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    """Build one consistent journey row, including explicit feature outcomes."""

    return {
        "case_id": case_id,
        "expected_contract": next(
            (
                dict(contract)
                for contract in JOURNEY_CONTRACTS.values()
                if contract.get("case_id") == case_id
            ),
            {},
        ),
        "domain": "multi_turn_progression",
        "variation_tags": list(variation_tags),
        "user_id": user_id,
        "passed": not failures,
        "mechanical_passed": not failures,
        "failures": list(failures),
        "feature_outcomes": [dict(item) for item in feature_outcomes],
        "steps": list(steps),
        "summary": [compact_response(step["response"]) for step in steps],
    }


def _case_in_tier(case_id: str, tier: str) -> bool:
    """Select the bounded smoke set or the complete promotion matrix."""

    return tier != "smoke" or case_id in SMOKE_CASE_IDS


def main() -> None:
    """Run selected tester-only scenarios and persist complete gate artifacts."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--expected-release", default="")
    parser.add_argument("--expected-git-sha", default="")
    parser.add_argument("--expected-environment", default="")
    parser.add_argument(
        "--tier",
        choices=("smoke", "promotion", "full"),
        default="promotion",
        help="Cost-bounded scenario tier. Promotion is the default release gate.",
    )
    parser.add_argument("--baseline-summary", default="")
    parser.add_argument(
        "--max-core-model-tokens",
        type=int,
        default=int(DEFAULT_HEALTH_POLICY["max_total_tokens"]),
        help="Hard cap for the frozen core matrix; cannot exceed the approved 2M limit.",
    )
    parser.add_argument(
        "--max-operational-funnel-tokens",
        type=int,
        default=int(DEFAULT_HEALTH_POLICY["max_operational_funnel_tokens"]),
        help="Separate cap for the additive size+brand operational-funnel scenarios.",
    )
    parser.add_argument(
        "--feature-expectations",
        default="",
        help=(
            "Optional path to a JSON object overriding the explicit feature "
            "expectation profile recorded in the artifact."
        ),
    )
    parser.add_argument(
        "--require-baseline",
        action="store_true",
        help="Block promotion unless the supplied baseline is cohort-compatible.",
    )
    parser.add_argument("--out-dir", default="tmp/runtime_v7_release_candidate_matrix")
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="Run only the named single-turn case; repeat for multiple cases.",
    )
    parser.add_argument("--skip-cases", action="store_true")
    parser.add_argument("--skip-journeys", action="store_true")
    parser.add_argument("--skip-operational-funnel", action="store_true")
    parser.add_argument(
        "--journey",
        action="append",
        choices=("product_location", "promo_details", "about_brand"),
        default=[],
        help="Run only the named journey; repeat for multiple journeys.",
    )
    parser.add_argument(
        "--operational-funnel-scenario",
        action="append",
        choices=tuple(OPERATIONAL_FUNNEL_CONTRACTS),
        default=[],
        help=(
            "Run only the named data-derived size+brand progression scenario; "
            "repeat for multiple scenarios."
        ),
    )
    args = parser.parse_args()

    missing_identity = [
        flag
        for flag, value in (
            ("--expected-release", args.expected_release),
            ("--expected-git-sha", args.expected_git_sha),
            ("--expected-environment", args.expected_environment),
        )
        if not str(value or "").strip()
    ]
    if missing_identity:
        parser.error(
            "exact deployed target identity is required: " + ", ".join(missing_identity)
        )
    if not 0 < args.max_core_model_tokens <= DEFAULT_HEALTH_POLICY["max_total_tokens"]:
        parser.error("--max-core-model-tokens must be between 1 and 2000000")
    if not 0 < args.max_operational_funnel_tokens <= DEFAULT_HEALTH_POLICY[
        "max_operational_funnel_tokens"
    ]:
        parser.error("--max-operational-funnel-tokens must be between 1 and 1200000")

    try:
        feature_overrides = (
            load_json(Path(args.feature_expectations))
            if args.feature_expectations
            else {}
        )
        feature_expectations = resolve_feature_expectations(feature_overrides)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    run_id = datetime.now(ZoneInfo("Asia/Manila")).strftime("%Y%m%d_%H%M%S_%f")
    out_dir = Path(args.out_dir) / f"runtime_v7_release_candidate_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    requested_cases = {str(value) for value in args.case}
    selected_cases = [
        case
        for case in CASES
        if (
            str(case["id"]) in requested_cases
            if requested_cases
            else _case_in_tier(str(case["id"]), args.tier)
        )
    ]
    unknown_cases = sorted(requested_cases - {str(case["id"]) for case in CASES})
    if unknown_cases:
        parser.error(f"unknown --case value(s): {', '.join(unknown_cases)}")

    rows: List[Dict[str, Any]] = []
    if not args.skip_cases:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {
                pool.submit(
                    run_case,
                    case,
                    base_url=args.base_url,
                    timeout_s=args.timeout_s,
                    run_id=run_id,
                    expected_release=args.expected_release,
                    expected_git_sha=args.expected_git_sha,
                    expected_environment=args.expected_environment,
                ): case
                for case in selected_cases
            }
            for future in as_completed(futures):
                case = futures[future]
                try:
                    rows.append(future.result())
                except Exception as exc:
                    rows.append(
                        _runner_exception_row(
                            str(case["id"]),
                            exc,
                            coverage=CASE_COVERAGE.get(str(case["id"])) or {},
                        )
                    )
    rows.sort(key=lambda row: str(row["case_id"]))

    journey_runners = {
        "product_location": run_product_location_journey,
        "promo_details": run_promo_details_journey,
        "about_brand": run_about_brand_journey,
    }
    selected_journeys = list(args.journey) or (
        list(journey_runners) if args.tier in {"promotion", "full"} else []
    )
    journeys = []
    if not args.skip_journeys:
        for name in selected_journeys:
            try:
                journeys.append(
                    journey_runners[name](
                        base_url=args.base_url,
                        timeout_s=args.timeout_s,
                        run_id=run_id,
                        expected_release=args.expected_release,
                        expected_git_sha=args.expected_git_sha,
                        expected_environment=args.expected_environment,
                        feature_expectations=feature_expectations,
                    )
                )
            except Exception as exc:
                journeys.append(
                    _runner_exception_row(
                        f"{name}_journey",
                        exc,
                        coverage={"domain": "multi_turn_progression"},
                    )
                )

    selected_operational_ids = list(args.operational_funnel_scenario) or (
        list(OPERATIONAL_FUNNEL_CONTRACTS) if args.tier in {"promotion", "full"} else []
    )
    operational_funnel_scenarios: List[Dict[str, Any]] = []
    if not args.skip_operational_funnel:
        for scenario_id in selected_operational_ids:
            try:
                operational_funnel_scenarios.append(
                    run_operational_funnel_scenario(
                        scenario_id,
                        base_url=args.base_url,
                        timeout_s=args.timeout_s,
                        run_id=run_id,
                        expected_release=args.expected_release,
                        expected_git_sha=args.expected_git_sha,
                        expected_environment=args.expected_environment,
                    )
                )
            except Exception as exc:
                operational_funnel_scenarios.append(
                    _runner_exception_row(
                        scenario_id,
                        exc,
                        coverage={"domain": "size_brand_operational_funnel"},
                    )
                )

    artifact = {
        "schema_version": "runtime_v7_release_candidate_artifact_v1",
        "run_id": run_id,
        "base_url": args.base_url,
        "evaluation_profile": {
            "schema_version": "runtime_v7_release_candidate_matrix_v4",
            "tier": args.tier,
            "tester_route": True,
            "base_url": args.base_url.rstrip("/"),
            "expected_release": args.expected_release,
            "expected_git_sha": args.expected_git_sha,
            "expected_environment": args.expected_environment,
            "workers": max(1, args.workers),
            "timeout_s": args.timeout_s,
            "require_compatible_baseline": bool(args.require_baseline),
            "health_policy": {
                **dict(DEFAULT_HEALTH_POLICY),
                "max_total_tokens": args.max_core_model_tokens,
                "max_operational_funnel_tokens": args.max_operational_funnel_tokens,
            },
            "selected_case_ids": [str(case["id"]) for case in selected_cases],
            "selected_journey_ids": [
                str(JOURNEY_CONTRACTS[name]["case_id"]) for name in selected_journeys
            ],
            "selected_journey_runners": selected_journeys,
            "selected_operational_funnel_ids": selected_operational_ids,
            "feature_expectations": feature_expectations,
        },
        "evaluation_boundary": {
            "automated": (
                "transport, release, return-only delivery, trusted tool "
                "results, evidence claims, renderer surfaces, state, and "
                "choice-token progression plus deterministic CS rubric proxies"
            ),
            "scenario_authority": "versioned pre-verified expected contracts",
        },
        "scenario_contract": build_scenario_contract(args.tier),
        "operational_funnel_contract": build_operational_funnel_contract(args.tier),
        "single_turn_cases": rows,
        "journeys": journeys,
        "operational_funnel_scenarios": operational_funnel_scenarios,
        "passed": sum(row["passed"] for row in rows)
        + sum(row["passed"] for row in journeys)
        + sum(row["passed"] for row in operational_funnel_scenarios),
        "failed": sum(not row["passed"] for row in rows)
        + sum(not row["passed"] for row in journeys)
        + sum(not row["passed"] for row in operational_funnel_scenarios),
    }
    baseline = load_json(Path(args.baseline_summary)) if args.baseline_summary else None
    attach_artifact_integrity(artifact)
    artifact["promotion_health"] = score_release_candidate(
        artifact,
        baseline=baseline,
    )
    json_path = out_dir / "summary.json"
    json_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path = out_dir / "summary.md"
    md_path.write_text(
        render_health_markdown(artifact["promotion_health"])
        + "\n"
        + render_markdown(artifact),
        encoding="utf-8",
    )
    integrity_path = out_dir / "integrity.json"
    integrity_path.write_text(
        json.dumps(artifact["artifact_integrity"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest_path = out_dir / "run_manifest.json"
    files = {}
    for path in (json_path, md_path, integrity_path):
        files[path.name] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "runtime_v7_evaluator_bundle_v1",
                "run_id": run_id,
                "created_at": datetime.now(ZoneInfo("Asia/Manila")).isoformat(),
                "environment": args.expected_environment,
                "release_version": args.expected_release,
                "git_sha": args.expected_git_sha,
                "promotion_status": artifact["promotion_health"]["promotion_status"],
                "evidence_digest": artifact["artifact_integrity"]["evidence_digest"],
                "files": files,
                "external_storage_key": (
                    f"runtime-v7-evaluator/{args.expected_environment}/"
                    f"{datetime.now(ZoneInfo('Asia/Manila')).date().isoformat()}/{run_id}/"
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "summary_json": str(json_path.resolve()),
                "summary_markdown": str(md_path.resolve()),
                "integrity": str(integrity_path.resolve()),
                "run_manifest": str(manifest_path.resolve()),
                "passed": artifact["passed"],
                "failed": artifact["failed"],
                "promotion_status": artifact["promotion_health"]["promotion_status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if artifact["failed"]:
        raise SystemExit(1)
    if artifact["promotion_health"]["promotion_status"] == "blocked":
        raise SystemExit(1)


def _runner_exception_row(
    case_id: str,
    exc: Exception,
    *,
    coverage: Mapping[str, Any],
) -> Dict[str, Any]:
    """Preserve unexpected runner failures as visible release-gate evidence."""

    error = f"{type(exc).__name__}: {exc}"
    return {
        "case_id": case_id,
        **dict(coverage),
        "passed": False,
        "mechanical_passed": False,
        "failures": [f"runner_exception:{error}"],
        "response": {
            "status": "error",
            "_probe_http_status": 0,
            "_probe_error": error,
        },
        "summary": {"runner_exception": error},
    }


def run_case(
    case: Mapping[str, Any],
    *,
    base_url: str,
    timeout_s: float,
    run_id: str,
    expected_release: str,
    expected_git_sha: str = "",
    expected_environment: str = "",
) -> Dict[str, Any]:
    """Run one isolated synthetic turn and retain its machine and review evidence."""

    case_id = str(case["id"])
    user_id = f"rc-{case_id}-{uuid.uuid4().hex[:10]}"
    response = chat(
        base_url,
        user_id=user_id,
        message=str(case["message"]),
        event_id=f"{run_id}_{case_id}_1",
        reset=True,
        timeout_s=timeout_s,
    )
    failures = evaluate(
        case,
        response,
        expected_release=expected_release,
        expected_git_sha=expected_git_sha,
        expected_environment=expected_environment,
    )
    return {
        "case_id": case_id,
        "expected_contract": {
            key: value for key, value in case.items() if key not in {"id", "message"}
        },
        **dict(CASE_COVERAGE.get(case_id) or {}),
        "user_id": user_id,
        "message": case["message"],
        "passed": not failures,
        "mechanical_passed": not failures,
        "failures": failures,
        "tool_chain_evidence": tool_argument_chain_evidence(
            case.get("expected_tool_chain_contracts") or [],
            response,
        ),
        "response": response,
        "summary": compact_response(response),
    }


def run_product_location_journey(
    *,
    base_url: str,
    timeout_s: float,
    run_id: str,
    expected_release: str,
    expected_git_sha: str = "",
    expected_environment: str = "",
    feature_expectations: Mapping[str, str] = DEFAULT_FEATURE_EXPECTATIONS,
) -> Dict[str, Any]:
    """Exercise product, location, schedule, and safe payment-choice progression."""

    user_id = f"rc-product-location-{uuid.uuid4().hex[:10]}"
    steps: List[Dict[str, Any]] = []
    feature_outcomes: List[Dict[str, Any]] = []
    first = chat(
        base_url,
        user_id=user_id,
        message=str(JOURNEY_CONTRACTS["product_location"]["initial_message"]),
        event_id=f"{run_id}_journey_product_1",
        reset=True,
        timeout_s=timeout_s,
    )
    steps.append(
        {
            "action": "chat",
            "message": JOURNEY_CONTRACTS["product_location"]["initial_message"],
            "response": first,
        }
    )
    failures = evaluate(
        {
            "required_tools": ("product_search",),
            "forbidden_token_prefixes": ("sc1|", "pm1|", "po1|"),
        },
        first,
        expected_release=expected_release,
        expected_git_sha=expected_git_sha,
        expected_environment=expected_environment,
    )
    current = first
    product_token = find_choice_token(current, prefixes=("ps1|",))
    product_decision = feature_surface_decision(
        feature="product_choices",
        token=product_token,
        feature_expectations=feature_expectations,
    )
    feature_outcomes.append(_public_feature_outcome(product_decision))
    if product_decision.get("failure"):
        failures.append(str(product_decision["failure"]))
    if product_decision.get("activate"):
        current = click(
            base_url,
            user_id=user_id,
            token=product_token,
            event_id=f"{run_id}_journey_product_click",
            timeout_s=timeout_s,
        )
        steps.append(
            {
                "action": "click_product",
                "token": product_token,
                "response": current,
            }
        )
        failures.extend(
            evaluate(
                {},
                current,
                expected_release=expected_release,
                expected_git_sha=expected_git_sha,
                expected_environment=expected_environment,
            )
        )
        failures.extend(_choice_validation_failures(current, "product_selection"))
        if find_choice_token(current, prefixes=("po1|", "pm1|")):
            failures.append("product_click_advanced_to_payment")
    else:
        return _journey_result(
            case_id="product_location_schedule_payment_journey",
            variation_tags=(
                "product",
                "location",
                "schedule",
                "payment_option",
                "payment_method",
                "tracked_actions",
            ),
            user_id=user_id,
            failures=failures,
            steps=steps,
            feature_outcomes=feature_outcomes,
        )

    first_location_token = find_choice_token(current, prefixes=("lc1|",))
    resolved_schedule_token = find_choice_token(current, prefixes=("ss1|",))
    known_installation_area = _known_installation_area(current)
    typed_schedule_continuation = bool(
        not first_location_token
        and not resolved_schedule_token
        and known_installation_area
        and _visible_schedule_request(current)
    )
    if not first_location_token and (resolved_schedule_token or typed_schedule_continuation):
        location_decision = {
            "feature": "location_choices",
            "expectation": str(feature_expectations.get("location_choices") or ""),
            "status": "not_required_location_already_resolved",
            "token_present": False,
            "activate": False,
            "reason": (
                "validated_schedule_surface_proves_location_resolution"
                if resolved_schedule_token
                else "order_snapshot_and_schedule_request_prove_location_resolution"
            ),
            "failure": "",
        }
    else:
        location_decision = feature_surface_decision(
            feature="location_choices",
            token=first_location_token,
            feature_expectations=feature_expectations,
        )
    feature_outcomes.append(_public_feature_outcome(location_decision))
    if location_decision.get("failure"):
        failures.append(str(location_decision["failure"]))
    if typed_schedule_continuation:
        schedule_message = "Bukas po."
        current = chat(
            base_url,
            user_id=user_id,
            message=schedule_message,
            event_id=f"{run_id}_journey_schedule_request",
            reset=False,
            timeout_s=timeout_s,
        )
        steps.append(
            {
                "action": "chat_schedule",
                "message": schedule_message,
                "response": current,
            }
        )
        failures.extend(
            evaluate(
                {"required_composer_statuses": ("used", "repaired", "skipped")},
                current,
                expected_release=expected_release,
                expected_git_sha=expected_git_sha,
                expected_environment=expected_environment,
            )
        )
        resolved_schedule_token = find_choice_token(current, prefixes=("ss1|",))
    if not location_decision.get("activate") and not resolved_schedule_token:
        return _journey_result(
            case_id="product_location_schedule_payment_journey",
            variation_tags=(
                "product",
                "location",
                "schedule",
                "payment_option",
                "payment_method",
                "tracked_actions",
            ),
            user_id=user_id,
            failures=failures,
            steps=steps,
            feature_outcomes=feature_outcomes,
        )
    if location_decision.get("activate"):
        for index in range(2):
            location_token = find_choice_token(current, prefixes=("lc1|",))
            if not location_token:
                break
            current = click(
                base_url,
                user_id=user_id,
                token=location_token,
                event_id=f"{run_id}_journey_location_{index + 1}",
                timeout_s=timeout_s,
            )
            steps.append(
                {
                    "action": "click_location",
                    "token": location_token,
                    "response": current,
                }
            )
            failures.extend(
                evaluate(
                    {},
                    current,
                    expected_release=expected_release,
                    expected_git_sha=expected_git_sha,
                    expected_environment=expected_environment,
                )
            )
            failures.extend(
                _choice_validation_failures(
                    current,
                    ("serviceable_province", "serviceable_city"),
                )
            )

    schedule_token = find_choice_token(current, prefixes=("ss1|",))
    schedule_decision = feature_surface_decision(
        feature="schedule_choices",
        token=schedule_token,
        feature_expectations=feature_expectations,
    )
    feature_outcomes.append(_public_feature_outcome(schedule_decision))
    if schedule_decision.get("failure"):
        failures.append(str(schedule_decision["failure"]))
    if schedule_decision.get("activate"):
        final = click(
            base_url,
            user_id=user_id,
            token=schedule_token,
            event_id=f"{run_id}_journey_schedule_1",
            timeout_s=timeout_s,
        )
        steps.append(
            {
                "action": "click_schedule",
                "token": schedule_token,
                "response": final,
            }
        )
        failures.extend(
            evaluate(
                {},
                final,
                expected_release=expected_release,
                expected_git_sha=expected_git_sha,
                expected_environment=expected_environment,
            )
        )
        failures.extend(_choice_validation_failures(final, "schedule_selection"))
        if find_choice_token(final, prefixes=("lc1|",)):
            failures.append("schedule_click_reasked_satisfied_location")
        current = final
    else:
        return _journey_result(
            case_id="product_location_schedule_payment_journey",
            variation_tags=(
                "product",
                "location",
                "schedule",
                "payment_option",
                "payment_method",
                "tracked_actions",
            ),
            user_id=user_id,
            failures=failures,
            steps=steps,
            feature_outcomes=feature_outcomes,
        )

    payment_option_token = find_choice_token(
        current,
        prefixes=("po1|",),
        caption_pattern=r"pay now",
    ) or find_choice_token(current, prefixes=("po1|",))
    payment_option_unavailable, payment_option_reason = _checkout_surface_unavailable(
        current, count_field="payment_option_count"
    )
    payment_option_decision = feature_surface_decision(
        feature="payment_option_choices",
        token=payment_option_token,
        feature_expectations=feature_expectations,
        unavailable=payment_option_unavailable,
        unavailable_reason=payment_option_reason,
    )
    feature_outcomes.append(_public_feature_outcome(payment_option_decision))
    if payment_option_decision.get("failure"):
        failures.append(str(payment_option_decision["failure"]))
    if not payment_option_decision.get("activate"):
        return _journey_result(
            case_id="product_location_schedule_payment_journey",
            variation_tags=(
                "product",
                "location",
                "schedule",
                "payment_option",
                "payment_method",
                "tracked_actions",
            ),
            user_id=user_id,
            failures=failures,
            steps=steps,
            feature_outcomes=feature_outcomes,
        )

    current = click(
        base_url,
        user_id=user_id,
        token=payment_option_token,
        event_id=f"{run_id}_journey_payment_option_1",
        timeout_s=timeout_s,
    )
    steps.append(
        {
            "action": "click_payment_option",
            "token": payment_option_token,
            "response": current,
        }
    )
    failures.extend(
        evaluate(
            {},
            current,
            expected_release=expected_release,
            expected_git_sha=expected_git_sha,
            expected_environment=expected_environment,
        )
    )
    failures.extend(_choice_validation_failures(current, "payment_option_selection"))

    payment_method_token = find_choice_token(current, prefixes=("pm1|",))
    payment_method_unavailable, payment_method_reason = _checkout_surface_unavailable(
        current, count_field="payment_method_count"
    )
    payment_method_decision = feature_surface_decision(
        feature="payment_method_choices",
        token=payment_method_token,
        feature_expectations=feature_expectations,
        unavailable=payment_method_unavailable,
        unavailable_reason=payment_method_reason,
    )
    feature_outcomes.append(_public_feature_outcome(payment_method_decision))
    if payment_method_decision.get("failure"):
        failures.append(str(payment_method_decision["failure"]))
    if payment_method_decision.get("activate"):
        current = click(
            base_url,
            user_id=user_id,
            token=payment_method_token,
            event_id=f"{run_id}_journey_payment_method_1",
            timeout_s=timeout_s,
        )
        steps.append(
            {
                "action": "click_payment_method",
                "token": payment_method_token,
                "response": current,
            }
        )
        failures.extend(
            evaluate(
                {},
                current,
                expected_release=expected_release,
                expected_git_sha=expected_git_sha,
                expected_environment=expected_environment,
            )
        )
        failures.extend(
            _choice_validation_failures(current, "payment_method_selection")
        )
        if find_choice_token(current, prefixes=("po1|",)):
            failures.append("payment_method_click_reasked_payment_option")
        collected = (
            (current.get("debug") or {})
            .get("order_readiness_before_turn", {})
            .get("collected", {})
        )
        if not collected.get("Payment option"):
            failures.append("payment_option_missing_after_method_click")
        if not any(
            collected.get(key)
            for key in (
                "Payment method",
                "Reservation payment method",
                "Balance payment method",
            )
        ):
            failures.append("payment_method_missing_after_method_click")
        failures.extend(
            _intent_observability_failures(
                current,
                expected_tags=("Moderate Intent", "High Intent"),
                expected_event_id=f"{run_id}_journey_payment_method_1",
            )
        )

    return _journey_result(
        case_id="product_location_schedule_payment_journey",
        variation_tags=(
            "product",
            "location",
            "schedule",
            "payment_option",
            "payment_method",
            "tracked_actions",
        ),
        user_id=user_id,
        failures=failures,
        steps=steps,
        feature_outcomes=feature_outcomes,
    )


def run_promo_details_journey(
    *,
    base_url: str,
    timeout_s: float,
    run_id: str,
    expected_release: str,
    expected_git_sha: str = "",
    expected_environment: str = "",
    feature_expectations: Mapping[str, str] = DEFAULT_FEATURE_EXPECTATIONS,
) -> Dict[str, Any]:
    """Exercise a tracked promo action without authorizing customer delivery."""

    user_id = f"rc-promo-details-{uuid.uuid4().hex[:10]}"
    first = chat(
        base_url,
        user_id=user_id,
        message=str(JOURNEY_CONTRACTS["promo_details"]["initial_message"]),
        event_id=f"{run_id}_promo_details_1",
        reset=True,
        timeout_s=timeout_s,
    )
    failures = evaluate(
        {"required_tools": ("search_promo_catalog",)},
        first,
        expected_release=expected_release,
        expected_git_sha=expected_git_sha,
        expected_environment=expected_environment,
    )
    token = find_choice_token(
        first,
        prefixes=("pc1|",),
        caption_pattern=r"promo details",
    )
    steps: List[Dict[str, Any]] = [
        {
            "action": "chat",
            "message": JOURNEY_CONTRACTS["promo_details"]["initial_message"],
            "response": first,
        }
    ]
    feature_outcomes: List[Dict[str, Any]] = []
    promo_unavailable, promo_unavailable_reason = _promo_surface_unavailable(first)
    decision = feature_surface_decision(
        feature="promo_guided_actions",
        token=token,
        feature_expectations=feature_expectations,
        unavailable=promo_unavailable,
        unavailable_reason=promo_unavailable_reason,
    )
    feature_outcomes.append(_public_feature_outcome(decision))
    if decision.get("failure"):
        failures.append(str(decision["failure"]))
    if decision.get("activate"):
        second = click(
            base_url,
            user_id=user_id,
            token=token,
            event_id=f"{run_id}_promo_details_click",
            timeout_s=timeout_s,
        )
        steps.append(
            {"action": "click_promo_details", "token": token, "response": second}
        )
        failures.extend(
            evaluate(
                {},
                second,
                expected_release=expected_release,
                expected_git_sha=expected_git_sha,
                expected_environment=expected_environment,
            )
        )
        readiness = (
            second.get("debug", {})
            .get("order_readiness_before_turn", {})
            .get("collected", {})
        )
        if readiness.get("Product"):
            failures.append("informational_promo_click_selected_product")
        if find_choice_token(second, prefixes=("lc1|", "sc1|", "po1|", "pm1|")):
            failures.append("informational_promo_click_advanced_transaction_layer")

    return _journey_result(
        case_id="promo_details_informational_journey",
        variation_tags=("promotion", "informational_click", "negative_control"),
        user_id=user_id,
        failures=failures,
        steps=steps,
        feature_outcomes=feature_outcomes,
    )


def run_about_brand_journey(
    *,
    base_url: str,
    timeout_s: float,
    run_id: str,
    expected_release: str,
    expected_git_sha: str = "",
    expected_environment: str = "",
    feature_expectations: Mapping[str, str] = DEFAULT_FEATURE_EXPECTATIONS,
) -> Dict[str, Any]:
    """Verify a tracked About Brand click reaches published source evidence."""

    user_id = f"rc-about-brand-{uuid.uuid4().hex[:10]}"
    first = chat(
        base_url,
        user_id=user_id,
        message=str(JOURNEY_CONTRACTS["about_brand"]["initial_message"]),
        event_id=f"{run_id}_about_brand_1",
        reset=True,
        timeout_s=timeout_s,
    )
    failures = evaluate(
        {"required_tools": ("search_promo_catalog",)},
        first,
        expected_release=expected_release,
        expected_git_sha=expected_git_sha,
        expected_environment=expected_environment,
    )
    token = find_choice_token(
        first,
        prefixes=("pc1|",),
        caption_pattern=r"about brand",
    )
    steps: List[Dict[str, Any]] = [
        {
            "action": "chat",
            "message": JOURNEY_CONTRACTS["about_brand"]["initial_message"],
            "response": first,
        }
    ]
    feature_outcomes: List[Dict[str, Any]] = []
    promo_unavailable, promo_unavailable_reason = _promo_action_unavailable(
        first,
        caption_pattern=r"about brand",
    )
    decision = feature_surface_decision(
        feature="promo_guided_actions",
        token=token,
        feature_expectations=feature_expectations,
        unavailable=promo_unavailable,
        unavailable_reason=promo_unavailable_reason,
    )
    feature_outcomes.append(_public_feature_outcome(decision))
    if decision.get("failure"):
        failures.append(str(decision["failure"]))
    if decision.get("activate"):
        second = click(
            base_url,
            user_id=user_id,
            token=token,
            event_id=f"{run_id}_about_brand_click",
            timeout_s=timeout_s,
        )
        steps.append(
            {"action": "click_about_brand", "token": token, "response": second}
        )
        failures.extend(
            evaluate(
                {},
                second,
                expected_release=expected_release,
                expected_git_sha=expected_git_sha,
                expected_environment=expected_environment,
            )
        )
        validation = second.get("promo_action_validation") or {}
        profile = validation.get("brand_profile") or {}
        if validation.get("status") != "valid":
            failures.append("about_brand_action_not_valid")
        if not profile.get("profile_ref") or not profile.get("about_brand"):
            failures.append("published_brand_profile_missing")
        composer_status = str(
            (second.get("debug") or {}).get("final_composer_status") or ""
        )
        reviewed_profile_rendered = _reviewed_profile_renderer_accepted(
            second,
            profile,
        )
        if composer_status not in {"used", "repaired"} and not (
            reviewed_profile_rendered
        ):
            failures.append("about_brand_composer_not_accepted")
        if find_choice_token(
            second,
            prefixes=("lc1|", "ss1|", "po1|", "pm1|"),
        ):
            failures.append("about_brand_advanced_transaction_layer")

    return _journey_result(
        case_id="about_brand_source_backed_journey",
        variation_tags=("promotion", "about_brand", "source_grounding"),
        user_id=user_id,
        failures=failures,
        steps=steps,
        feature_outcomes=feature_outcomes,
    )


def chat(
    base_url: str,
    *,
    user_id: str,
    message: str,
    event_id: str,
    reset: bool,
    timeout_s: float,
) -> Dict[str, Any]:
    """Call the return-only tester chat route with analytics disabled."""

    payload = {
        "user_id": user_id,
        "channel_user_id": user_id,
        "channel": "manychat",
        "user_text": message,
        "message_id": event_id,
        "idempotency_key": event_id,
        "channel_event_id": event_id,
        "flow_context": {"probe": "runtime_v7_release_candidate_matrix"},
        "delivery_mode": "return_only",
        "return_logs": 1,
        "save_analytics": 0,
        "reset": int(reset),
    }
    response = post_json(
        f"{base_url.rstrip('/')}/gulong/v7/chat/tester", payload, timeout_s
    )
    response["_probe_model_usage_expectation"] = "required"
    return response


def click(
    base_url: str,
    *,
    user_id: str,
    token: str,
    event_id: str,
    timeout_s: float,
) -> Dict[str, Any]:
    """Resolve one tracked tester action without delivery or analytics writes."""

    payload = {
        "user_id": user_id,
        "channel_user_id": user_id,
        "promo_id": token,
        "click_timestamp": datetime.now(ZoneInfo("Asia/Manila")).isoformat(),
        "event_id": event_id,
        "idempotency_key": event_id,
        "channel": "manychat",
        "save_analytics": 0,
        "return_logs": 1,
        "delivery_mode": "return_only",
    }
    response = post_json(
        f"{base_url.rstrip('/')}/gulong/v7/choice-action/tester",
        payload,
        timeout_s,
    )
    response["_probe_model_usage_expectation"] = "required"
    return response


def post_json(url: str, payload: Mapping[str, Any], timeout_s: float) -> Dict[str, Any]:
    """Post JSON and preserve HTTP or transport failures as structured evidence."""

    started = time.perf_counter()
    transport_errors: List[str] = []
    output: Dict[str, Any] = {}
    max_attempts = 3
    attempt_count = 0
    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        remaining_s = timeout_s - (time.perf_counter() - started)
        if remaining_s <= 0:
            break
        attempt_count = attempt
        try:
            with urllib.request.urlopen(request, timeout=remaining_s) as response:
                raw = response.read().decode("utf-8", errors="replace")
                output = json.loads(raw) if raw.strip() else {}
                output["_probe_http_status"] = response.status
            break
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                output = json.loads(raw)
            except Exception:
                output = {"status": "error", "raw_body": raw}
            output["_probe_http_status"] = exc.code
            break
        except Exception as exc:
            transport_errors.append(f"{type(exc).__name__}: {exc}")
            output = {
                "status": "error",
                "_probe_http_status": 0,
                "_probe_error": transport_errors[-1],
            }
            if attempt >= max_attempts:
                break
            remaining_s = timeout_s - (time.perf_counter() - started)
            if remaining_s <= 0:
                break
            time.sleep(min(0.5 * attempt, remaining_s))
    output["_probe_attempt_count"] = max(1, attempt_count)
    if transport_errors:
        output["_probe_transport_errors"] = transport_errors
    output["_probe_elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    return output


def _payment_claim_window(
    visible_text: str, method: str
) -> str:
    """Return the sentence-sized visible span that names one payment method."""

    normalized_method = " ".join(str(method or "").casefold().split())
    if normalized_method in {"home credit", "atome"}:
        pattern = re.escape(normalized_method)
    elif "bpi" in normalized_method and "6" in normalized_method:
        pattern = r"\bbpi\b.{0,18}\b6[-\s]*(?:mos?|months?)\b"
    elif re.search(r"\b3[-\s]*(?:mos?|months?)\b", normalized_method):
        pattern = r"\b3[-\s]*(?:mos?|months?)\b"
    else:
        pattern = re.escape(normalized_method)
    match = re.search(pattern, visible_text, flags=re.IGNORECASE)
    if not match:
        return ""
    return visible_text[max(0, match.start() - 100) : match.end() + 160]


def _provider_grounded_payment_composition_failures(
    case: Mapping[str, Any], response: Mapping[str, Any]
) -> List[str]:
    """Require provider-backed typed claims to be rendered in final payment prose."""

    if not case.get("require_payment_authority_contract"):
        return ["provider_grounded_payment_composition_not_payment_only"]
    expected_claims = list(case.get("expected_payment_claims") or [])
    if not expected_claims:
        return ["provider_grounded_payment_composition_expected_claims_missing"]
    authority_failures = payment_authority_contract_failures(response)
    if authority_failures:
        return ["provider_grounded_payment_composition_authority_unverified"]

    visible_text = customer_text(response).casefold()
    outcome_terms = {
        "eligible": ("available", "eligible", "puwede", "pwede", "yes", "oo"),
        "not_eligible": (
            "hindi available",
            "not available",
            "not eligible",
            "unavailable",
            "hindi puwede",
            "hindi pwede",
        ),
        "unsupported": (
            "wala",
            "walang",
            "hindi available",
            "not available",
            "unsupported",
        ),
    }
    failures: List[str] = []
    for method, outcome, brand, payment_option in expected_claims:
        window = _payment_claim_window(visible_text, str(method))
        identity = f"{method}|{outcome}|{brand}|{payment_option}"
        if not window:
            failures.append(f"provider_grounded_payment_visible_method_missing:{identity}")
            continue
        outcome_window = " ".join(
            re.sub(r"\b(?:po|naman)\b", " ", window).split()
        )
        if not any(
            term in outcome_window for term in outcome_terms.get(str(outcome), ())
        ):
            failures.append(f"provider_grounded_payment_visible_outcome_missing:{identity}")
        if brand and str(brand).casefold() not in window:
            failures.append(f"provider_grounded_payment_visible_brand_missing:{identity}")
        if payment_option:
            option_terms = str(payment_option).casefold().split()
            if not all(term in window for term in option_terms):
                failures.append(f"provider_grounded_payment_visible_option_missing:{identity}")
    return failures


def evaluate(
    case: Mapping[str, Any],
    response: Mapping[str, Any],
    *,
    expected_release: str = "",
    expected_git_sha: str = "",
    expected_environment: str = "",
) -> List[str]:
    """Return deterministic contract failures without judging conversational prose."""

    failures: List[str] = []
    if int(response.get("_probe_http_status") or 0) != 200:
        failures.append(f"http_status:{response.get('_probe_http_status')}")
    if response.get("status") != "success":
        failures.append(f"runtime_status:{response.get('status')}")
    if expected_release and response.get("release_version") != expected_release:
        failures.append(f"wrong_release:{response.get('release_version')}")
    if expected_git_sha and response.get("git_sha") != expected_git_sha:
        failures.append(f"wrong_git_sha:{response.get('git_sha')}")
    if (
        expected_environment
        and response.get("service_environment") != expected_environment
    ):
        failures.append(f"wrong_environment:{response.get('service_environment')}")
    delivery = response.get("delivery_result") or {}
    if delivery.get("status") != "skipped" or delivery.get("reason") != "return_only":
        failures.append(f"unsafe_delivery:{delivery}")
    tagging = response.get("tagging_result") or {}
    explicit_return_only_skip = (
        tagging.get("tag_apply_skipped") is True
        and tagging.get("tag_apply_skip_reason") == "return_only"
    )
    empty_tag_plan = (
        tagging.get("apply_status") == "no_tags"
        and not (tagging.get("tags_to_add") or [])
        and not (tagging.get("tags_applied") or [])
        and not (tagging.get("tags_failed") or [])
    )
    if (tagging.get("tags_applied") or []) or not (
        explicit_return_only_skip or empty_tag_plan
    ):
        failures.append(f"unsafe_tagging:{tagging}")

    tool_rows = [
        item
        for item in (response.get("debug") or {}).get("tool_calls") or []
        if isinstance(item, Mapping)
    ]
    tools = {str(item.get("name") or "") for item in tool_rows}
    for tool in sorted(tools.intersection(MUTATING_TOOLS)):
        failures.append(f"mutating_tool_called:{tool}")
    for tool in case.get("required_tools") or []:
        if tool not in tools:
            failures.append(f"missing_tool:{tool}")
    required_any = set(case.get("required_tools_any") or [])
    if required_any and not tools.intersection(required_any):
        failures.append(f"missing_any_tool:{sorted(required_any)}")
    for tool in case.get("forbidden_tools") or []:
        if tool in tools:
            failures.append(f"forbidden_tool:{tool}")
    for tool in case.get("forbidden_successful_tools") or []:
        if any(
            str(item.get("name") or "") == tool
            and str(item.get("status") or "").casefold()
            not in {"error", "blocked", "rejected", "suppressed"}
            for item in tool_rows
        ):
            failures.append(f"forbidden_successful_tool:{tool}")

    tokens = choice_tokens(response)
    prefix = str(case.get("required_token_prefix") or "")
    if prefix and not any(token.startswith(prefix) for token in tokens):
        failures.append(f"missing_token_prefix:{prefix}")
    for forbidden_prefix in case.get("forbidden_token_prefixes") or []:
        if any(token.startswith(forbidden_prefix) for token in tokens):
            failures.append(f"forbidden_token_prefix:{forbidden_prefix}")

    visible_text = customer_text(response).casefold()
    for required_text in case.get("required_response_substrings") or []:
        if str(required_text or "").casefold() not in visible_text:
            failures.append(f"missing_response_fact:{required_text}")
    for fact in case.get("required_response_facts") or []:
        if not phrase_tolerant_fact_present(visible_text, fact):
            failures.append(f"missing_response_fact:{fact.get('id') or 'unnamed'}")
    for fact in case.get("forbidden_response_facts") or []:
        if phrase_tolerant_fact_present(visible_text, fact):
            failures.append(f"forbidden_response_fact:{fact.get('id') or 'unnamed'}")

    failures.extend(
        tool_argument_contract_failures(
            case.get("expected_tool_arg_contracts") or [],
            response,
        )
    )
    failures.extend(
        tool_argument_chain_contract_failures(
            case.get("expected_tool_chain_contracts") or [],
            response,
        )
    )
    if case.get("require_payment_authority_contract"):
        failures.extend(payment_authority_contract_failures(response))

    if case.get("promo_token_tracks_current_refs"):
        promo_scopes = [
            item.get("commercial_scope") or {}
            for item in tool_rows
            if item.get("name") == "search_promo_catalog"
        ]
        allowed_refs = [
            str(ref)
            for scope in promo_scopes
            for ref in scope.get("allowed_promo_refs") or []
            if str(ref or "").strip()
        ]
        has_promo_token = any(token.startswith("pc1|") for token in tokens)
        if allowed_refs and not has_promo_token:
            failures.append("current_promo_refs_missing_gallery_token")
        if not allowed_refs and has_promo_token:
            failures.append("gallery_token_without_current_promo_ref")

    required_composer_statuses = set(case.get("required_composer_statuses") or [])
    composer_status = str(
        (response.get("debug") or {}).get("final_composer_status") or ""
    )
    location_progression_guard = bool(
        case.get("allow_location_progression_guard")
        and _location_progression_guard_contract_valid(response)
    )
    service_claim_surface_sanitized = bool(
        case.get("allow_service_claim_surface_sanitized")
        and _service_claim_surface_sanitized_contract_valid(response)
    )
    response_guard_events = (response.get("debug") or {}).get(
        "response_guard_events"
    ) or []
    promo_safe_fallback = bool(
        composer_status == "promo_fact_safe_fallback"
        and any(
            isinstance(event, Mapping)
            and str(event.get("type") or "") == "promo_fact_safe_fallback_used"
            for event in response_guard_events
        )
    )
    promo_scoped_result = bool(
        composer_status == "promo_fact_scoped_result"
        and any(
            isinstance(event, Mapping)
            and str(event.get("type") or "") == "promo_fact_scoped_result_rendered"
            for event in response_guard_events
        )
    )
    deterministic_promo_result = bool(promo_safe_fallback or promo_scoped_result)
    answer_goal_safe_fallback = bool(
        composer_status == "answer_goal_safe_fallback"
        and any(
            isinstance(event, Mapping)
            and str(event.get("type") or "") == "answer_goal_safe_fallback_used"
            for event in response_guard_events
        )
        and any(
            isinstance(audit, Mapping)
            and str(audit.get("decision") or "") != "supported"
            for audit in (
                (response.get("debug") or {}).get("semantic_answer_goal_audits") or []
            )
        )
    )
    if composer_status == "answer_goal_safe_fallback" and not answer_goal_safe_fallback:
        failures.append("answer_goal_safe_fallback_not_guarded")
    payment_claim_safe_surface_fallback = bool(
        composer_status == "payment_claim_safe_surface_fallback"
        and not ((response.get("debug") or {}).get("commercial_payment_claims") or [])
        and any(
            isinstance(event, Mapping)
            and str(event.get("type") or "")
            == "payment_claim_safe_surface_fallback_used"
            and int(event.get("preserved_surface_count") or 0) > 0
            for event in response_guard_events
        )
    )
    if (
        composer_status == "payment_claim_safe_surface_fallback"
        and not payment_claim_safe_surface_fallback
    ):
        failures.append("payment_claim_safe_surface_fallback_not_guarded")
    if composer_status == "provider_grounded_payment_composition":
        failures.extend(
            _provider_grounded_payment_composition_failures(case, response)
        )
    if (
        required_composer_statuses
        and composer_status not in required_composer_statuses
        and not (composer_status == "skipped" and location_progression_guard)
        and not service_claim_surface_sanitized
    ):
        failures.append(f"composer_status:{composer_status or 'missing'}")

    claims = (response.get("debug") or {}).get("commercial_payment_claims") or []
    minimum_claims = int(case.get("minimum_commercial_claims") or 0)
    if len(claims) < minimum_claims:
        failures.append(f"commercial_claims:{len(claims)}<{minimum_claims}")
    for expected in case.get("expected_payment_claims") or []:
        method, outcome, brand, payment_option = expected
        if not any(
            str(claim.get("method") or "").casefold() == str(method).casefold()
            and str(claim.get("outcome") or "").casefold() == str(outcome).casefold()
            and str(claim.get("brand") or "").casefold() == str(brand).casefold()
            and (
                not payment_option
                or str(claim.get("payment_option") or "")
                .casefold()
                .startswith(str(payment_option).casefold())
            )
            for claim in claims
            if isinstance(claim, Mapping)
        ):
            failures.append(
                f"missing_commercial_claim:{method}|{outcome}|{brand}|{payment_option}"
            )

    expected_unmatched = str(
        case.get("expected_promo_unmatched_brand") or ""
    ).casefold()
    if expected_unmatched and not any(
        expected_unmatched
        in {
            str(value or "").casefold()
            for value in (item.get("commercial_scope") or {}).get(
                "unmatched_requested_brands"
            )
            or []
        }
        for item in tool_rows
        if item.get("name") == "search_promo_catalog"
    ):
        failures.append(f"promo_unmatched_brand_missing:{expected_unmatched}")
    expected_requested = str(
        case.get("expected_promo_requested_brand") or ""
    ).casefold()
    if expected_requested and not any(
        expected_requested
        in {
            str(value or "").casefold()
            for value in (item.get("commercial_scope") or {}).get("requested_brands")
            or []
        }
        for item in tool_rows
        if item.get("name") == "search_promo_catalog"
    ):
        failures.append(f"promo_requested_brand_missing:{expected_requested}")

    product_cards = [
        card
        for presentation in response.get("product_presentations") or []
        if isinstance(presentation, Mapping)
        for card in presentation.get("cards") or []
        if isinstance(card, Mapping)
    ]
    expected_promo_brand = str(
        case.get("expected_product_promo_brand") or ""
    ).casefold()
    if expected_promo_brand and not any(
        str(card.get("brand") or "").casefold() == expected_promo_brand
        and _card_has_buy3get1(card)
        for card in product_cards
    ):
        failures.append(f"validated_product_promo_missing:{expected_promo_brand}")
    forbidden_promo_brand = str(
        case.get("forbidden_product_promo_brand") or ""
    ).casefold()
    if forbidden_promo_brand and any(
        str(card.get("brand") or "").casefold() == forbidden_promo_brand
        and _card_has_buy3get1(card)
        for card in product_cards
    ):
        failures.append(f"unsupported_product_promo_present:{forbidden_promo_brand}")
    expected_brand_size = case.get("expected_product_brand_size") or ()
    if expected_brand_size:
        expected_brand, expected_size = expected_brand_size
        if not any(
            str(card.get("brand") or "").casefold() == str(expected_brand).casefold()
            and _compact_size(card.get("tire_size")) == _compact_size(expected_size)
            for card in product_cards
        ):
            failures.append(
                f"matching_product_card_missing:{expected_brand}|{expected_size}"
            )
    allowed_card_brands = {
        str(value or "").casefold()
        for value in case.get("product_cards_only_brands") or []
        if str(value or "").strip()
    }
    unexpected_card_brands = sorted(
        {
            str(card.get("brand") or "").strip()
            for card in product_cards
            if str(card.get("brand") or "").strip()
            and str(card.get("brand") or "").casefold() not in allowed_card_brands
        }
    )
    if allowed_card_brands and unexpected_card_brands:
        failures.append(
            "unexpected_product_card_brands:" + ",".join(unexpected_card_brands)
        )
    required_product_promo_claim = case.get("required_product_promo_claim") or {}
    if required_product_promo_claim:
        failures.extend(
            _product_promo_claim_contract_failures(
                required_product_promo_claim,
                response,
            )
        )

    query_basis_rows = [
        value.get("query_basis")
        for value in _walk_mappings(
            (response.get("debug") or {}).get("turn_trace") or {}
        )
        if isinstance(value.get("query_basis"), Mapping)
    ]
    expected_query = case.get("expected_product_query") or {}
    if expected_query and not any(
        all(
            (basis.get("normalized_filters") or {}).get(key) == expected
            for key, expected in expected_query.items()
        )
        for basis in query_basis_rows
    ):
        failures.append(
            "normalized_product_query_missing:"
            + json.dumps(expected_query, ensure_ascii=False, sort_keys=True)
        )
    if case.get("require_exact_base_query_verified") and not any(
        basis.get("exact_base_query_verified") is True for basis in query_basis_rows
    ):
        failures.append("exact_base_query_not_verified")

    minimum_products = int(case.get("minimum_product_presentations") or 0)
    product_count = sum(
        len(presentation.get("cards") or [])
        for presentation in response.get("product_presentations") or []
        if isinstance(presentation, Mapping)
    )
    if product_count < minimum_products:
        failures.append(f"product_presentations:{product_count}<{minimum_products}")
    if case.get("require_supported_promo_audit"):
        promo_audits = (response.get("debug") or {}).get(
            "promo_fact_scope_audits"
        ) or []
        latest_audit_supported = bool(
            promo_audits
            and str((promo_audits[-1] or {}).get("decision") or "") == "supported"
        )
        if not latest_audit_supported and not deterministic_promo_result:
            failures.append("promo_fact_audit_not_supported")
    if case.get("require_scoped_negative_promo_contract"):
        failures.extend(_scoped_negative_promo_contract_failures(case, response))
    payment_guard = (response.get("debug") or {}).get(
        "payment_policy_truth_guard"
    ) or {}
    if payment_guard.get("status") == "rewritten":
        failures.append("payment_guard_rewrite")
    promo_guard = (response.get("debug") or {}).get("promo_provider_truth_guard") or {}
    if expected_promo_brand and promo_guard.get("status") == "rewritten":
        failures.append("promo_guard_rewrite")
    allowed_composer_statuses = required_composer_statuses or {
        "used",
        "repaired",
    }
    if location_progression_guard:
        allowed_composer_statuses.add("skipped")
    if service_claim_surface_sanitized:
        allowed_composer_statuses.add("service_claim_surface_sanitized")
    if case.get("require_supported_promo_audit") and deterministic_promo_result:
        allowed_composer_statuses.update(
            {"promo_fact_safe_fallback", "promo_fact_scoped_result"}
        )
    if composer_status not in allowed_composer_statuses:
        failures.append("composer_status:" + composer_status)
    return failures


def _location_progression_guard_contract_valid(
    response: Mapping[str, Any],
) -> bool:
    """Accept deterministic CTA ownership only with exact positive evidence."""

    guard = (response.get("debug") or {}).get("location_progression_guard") or {}
    if not (
        str(guard.get("status") or "") == "rewritten"
        and str(guard.get("reason") or "")
        == "single_exact_size_brand_result_requires_location_question"
        and int(guard.get("product_card_count") or 0) == 1
        and _visible_location_request(response)
    ):
        return False
    product_presentations = [
        presentation
        for presentation in response.get("product_presentations") or []
        if isinstance(presentation, Mapping)
    ]
    if sum(
        len(presentation.get("cards") or [])
        for presentation in product_presentations
    ) != 1:
        return False
    product_refs = {
        str(presentation.get("presentation_ref") or "").strip()
        for presentation in product_presentations
        if str(presentation.get("presentation_ref") or "").strip()
    }
    preserved_refs = {
        str(value or "").strip()
        for value in guard.get("preserved_surface_refs") or []
        if str(value or "").strip()
    }
    return bool(product_refs and product_refs.intersection(preserved_refs))


def _service_claim_surface_sanitized_contract_valid(
    response: Mapping[str, Any],
) -> bool:
    """Accept service sanitization only with exact provider and guard evidence."""

    debug = response.get("debug") or {}
    if str(debug.get("final_composer_status") or "") != (
        "service_claim_surface_sanitized"
    ):
        return False
    guard_valid = any(
        isinstance(event, Mapping)
        and str(event.get("type") or "")
        == "provider_owned_service_claim_prose_sanitized"
        and str(event.get("reason") or "")
        == "availability_fact_owned_by_exact_query_area_surface"
        and int(event.get("removed_response_unit_count") or 0) > 0
        and not (event.get("remaining_violations") or [])
        for event in debug.get("response_guard_events") or []
    )
    provider_rows = [
        row
        for row in debug.get("tool_calls") or []
        if isinstance(row, Mapping)
        and str(row.get("name") or "") == "find_installation_partners"
        and str(row.get("status") or "") == "ok"
        and str((row.get("args") or {}).get("location") or "").strip()
        and str((row.get("authority") or {}).get("source") or "").strip()
        and str((row.get("authority") or {}).get("presentation_ref") or "").strip()
    ]
    return bool(guard_valid and provider_rows and _visible_response_rendered(response))


def _known_installation_area(response: Mapping[str, Any]) -> str:
    """Read the canonical selected installation area from an order snapshot."""

    snapshots = (((response.get("debug") or {}).get("turn_trace") or {}).get(
        "state_snapshots"
    ) or [])
    for snapshot in reversed(snapshots):
        if not isinstance(snapshot, Mapping):
            continue
        if str(snapshot.get("state_name") or "") != (
            "latest_order_summary_snapshot_after_turn"
        ):
            continue
        fields = (snapshot.get("state_json") or {}).get("fields") or {}
        value = str(fields.get("Installation Area") or "").strip()
        if value and value != "-":
            return value
    return ""


def _visible_schedule_request(response: Mapping[str, Any]) -> bool:
    """Recognize reviewed meaning-level requests for an installation date."""

    text = customer_text(response)
    patterns = (
        r"\b(?:kailan|anong\s+(?:date|araw)|what\s+(?:date|day)|when)\b.{0,90}"
        r"\b(?:install|installation|magpa[-\s]?install|schedule)\b",
        r"\b(?:install|installation|magpa[-\s]?install|schedule)\b.{0,90}"
        r"\b(?:kailan|anong\s+(?:date|araw)|what\s+(?:date|day)|when)\b",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _card_has_buy3get1(card: Mapping[str, Any]) -> bool:
    pricing = (
        card.get("pricing_facts")
        if isinstance(card.get("pricing_facts"), Mapping)
        else {}
    )
    if str(pricing.get("pricing_basis") or "").casefold() == "buy3get1":
        return True
    promo_text = " ".join(
        [
            *[str(value or "") for value in pricing.get("included_promos") or []],
            str(card.get("promo_savings_line") or ""),
        ]
    )
    return bool(
        re.search(
            r"(?:buy\s*3\s*get\s*1|3\s*\+\s*1)",
            promo_text,
            flags=re.IGNORECASE,
        )
    )


def _product_promo_claim_contract_failures(
    expected: Mapping[str, Any], response: Mapping[str, Any]
) -> List[str]:
    """Validate visible promo meaning against one provider-backed product card."""

    expected_brand = str(expected.get("brand") or "").casefold()
    expected_size = _compact_size(expected.get("tire_size"))
    expected_basis = str(expected.get("pricing_basis") or "").casefold()
    expected_quantity = int(expected.get("quantity") or 0)
    matches: List[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for presentation in response.get("product_presentations") or []:
        if not isinstance(presentation, Mapping):
            continue
        for card in presentation.get("cards") or []:
            if not isinstance(card, Mapping):
                continue
            pricing = card.get("pricing_facts") or {}
            if not isinstance(pricing, Mapping):
                continue
            if (
                expected_brand
                and str(card.get("brand") or "").casefold() != expected_brand
            ):
                continue
            if expected_size and _compact_size(card.get("tire_size")) != expected_size:
                continue
            if (
                expected_basis
                and str(pricing.get("pricing_basis") or "").casefold() != expected_basis
            ):
                continue
            if (
                expected_quantity
                and int(pricing.get("quantity") or 0) != expected_quantity
            ):
                continue
            matches.append((presentation, card))
    if not matches:
        return ["product_promo_claim_evidence_missing"]

    presentation, card = matches[0]
    failures: List[str] = []
    if not all(
        str(value or "").strip()
        for value in (
            presentation.get("presentation_ref"),
            presentation.get("observation_ref"),
            card.get("card_ref"),
            card.get("product_id") or card.get("slug"),
        )
    ):
        failures.append("product_promo_claim_identity_missing")
    visible = customer_text(response)
    normalized_visible = " ".join(visible.casefold().split())
    if expected_brand and expected_brand not in normalized_visible:
        failures.append("product_promo_visible_brand_missing")
    if expected_size and expected_size not in _compact_size(visible):
        failures.append("product_promo_visible_size_missing")
    if expected_basis == "buy3get1" and not re.search(
        r"(?:buy\s*3\s*get\s*1|3\s*\+\s*1)",
        visible,
        flags=re.IGNORECASE,
    ):
        failures.append("product_promo_visible_mechanic_missing")
    pricing = card.get("pricing_facts") or {}
    payable_total = pricing.get("payable_total")
    if payable_total in (None, ""):
        failures.append("product_promo_payable_total_missing")
    else:
        expected_amount = _normalized_money_amount(payable_total)
        visible_amounts = {
            _normalized_money_amount(value)
            for value in re.findall(
                r"(?:PHP|₱)\s*([0-9][0-9,]*(?:\.\d{1,2})?)",
                visible,
                flags=re.IGNORECASE,
            )
        }
        if not expected_amount or expected_amount not in visible_amounts:
            failures.append("product_promo_visible_total_mismatch")
    return failures


def _normalized_money_amount(value: Any) -> str:
    """Normalize a provider or visible money amount without fixing its price."""

    try:
        return f"{float(str(value).replace(',', '').strip()):.2f}"
    except (TypeError, ValueError):
        return ""


def _scoped_negative_promo_contract_failures(
    case: Mapping[str, Any], response: Mapping[str, Any]
) -> List[str]:
    """Require deterministic scope provenance for a negative promo answer."""

    guard = (response.get("debug") or {}).get("promo_provider_truth_guard") or {}
    failures: List[str] = []
    if str(guard.get("status") or "") not in {"validated", "rewritten"}:
        failures.append("scoped_negative_promo_guard_missing")
    expected_brand = str(case.get("expected_promo_unmatched_brand") or "").casefold()
    guarded_brands = {
        str(value or "").casefold()
        for value in guard.get("unmatched_requested_brands") or []
    }
    if expected_brand and expected_brand not in guarded_brands:
        failures.append("scoped_negative_promo_brand_missing")
    visible = " ".join(customer_text(response).casefold().split())
    visible_tokens = set(re.findall(r"[a-z0-9]+", visible))
    typed_partial_disclosure = bool(
        str(guard.get("status") or "") == "validated"
        and str(guard.get("reason") or "")
        == "unmatched_promo_brand_scoped_by_product_disclosure"
        and guard.get("partial_product_surface_suppressed") is False
    )
    bounded_scope = bool(
        {"promo", "promos"} & visible_tokens
        and (
            "verified" in visible_tokens
            or "reviewed" in visible_tokens
            or (
                "current" in visible_tokens
                and ("catalog" in visible_tokens or "list" in visible_tokens)
            )
            or typed_partial_disclosure
        )
    )
    if not (
        bounded_scope
        and expected_brand in visible
        and any(cue in visible for cue in ("wala", "walang", "hindi available", "no "))
    ):
        failures.append("scoped_negative_promo_visible_scope_missing")
    return failures


def _compact_size(value: Any) -> str:
    """Normalize a renderer tire-size serialization for exact comparison."""

    return re.sub(r"[^0-9a-z]+", "", str(value or "").casefold()).replace(
        "zr",
        "r",
    )


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    """Yield nested mappings for structured trace inspection."""

    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_mappings(child)


def customer_text(response: Mapping[str, Any]) -> str:
    """Return ordered customer-visible bubbles without the exact fallback welcome."""

    bubbles = response.get("response") or {}
    if isinstance(bubbles, Mapping):
        values = [
            str(value or "")
            for key, value in sorted(
                bubbles.items(),
                key=lambda item: _bubble_order(str(item[0])),
            )
            if not _is_standalone_runtime_welcome(value)
        ]
        return "\n".join(values)
    return ""


def _is_standalone_runtime_welcome(value: Any) -> bool:
    """Match only the exact fixed runtime welcome, never merged answer prose."""

    normalized = " ".join(
        " ".join(str(value or "").casefold().split())
        .replace(
            "😊",
            "",
        )
        .split()
    )
    return normalized.strip() == (
        "hi po! welcome to gulong.ph we'll help you find brand-new, legit "
        "tires that fit your car, budget, and area."
    )


def _reviewed_profile_renderer_accepted(
    response: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> bool:
    """Recognize an exact zero-call reviewed About Brand response."""

    composer_status = str(
        (response.get("debug") or {}).get("final_composer_status") or ""
    )
    about_brand = str(profile.get("about_brand") or "").strip()
    return bool(
        not composer_status
        and not ((response.get("debug") or {}).get("tool_calls") or [])
        and about_brand
        and about_brand in customer_text(response)
    )


def choice_tokens(response: Mapping[str, Any]) -> List[str]:
    """Return all tracked action values exposed by rendered response buttons."""

    output: List[str] = []
    for message in response.get("content_messages") or []:
        if not isinstance(message, Mapping):
            continue
        for element in message.get("elements") or []:
            if not isinstance(element, Mapping):
                continue
            for button in element.get("buttons") or []:
                if not isinstance(button, Mapping):
                    continue
                for action in button.get("actions") or []:
                    if not isinstance(action, Mapping):
                        continue
                    value = str(action.get("value") or "").strip()
                    if value:
                        output.append(value)
    return output


def find_choice_token(
    response: Mapping[str, Any],
    *,
    prefixes: Iterable[str],
    caption_pattern: str = "",
) -> str:
    """Return the first rendered tracked token matching type and caption filters."""

    accepted = tuple(prefixes)
    for message in response.get("content_messages") or []:
        if not isinstance(message, Mapping):
            continue
        for element in message.get("elements") or []:
            if not isinstance(element, Mapping):
                continue
            for button in element.get("buttons") or []:
                if not isinstance(button, Mapping):
                    continue
                caption = str(button.get("caption") or "")
                if caption_pattern and not re.search(
                    caption_pattern,
                    caption,
                    flags=re.IGNORECASE,
                ):
                    continue
                for action in button.get("actions") or []:
                    if not isinstance(action, Mapping):
                        continue
                    value = str(action.get("value") or "").strip()
                    if value.startswith(accepted):
                        return value
    return ""


def compact_response(response: Mapping[str, Any]) -> Dict[str, Any]:
    """Project one deployed response into bounded release-evaluation evidence."""

    debug = response.get("debug") or {}
    tagging = response.get("tagging_result") or {}
    return {
        "request_id": response.get("request_id"),
        "release_version": response.get("release_version"),
        "elapsed_ms": response.get("_probe_elapsed_ms"),
        "bubbles": list((response.get("response") or {}).values()),
        "content_messages": response.get("content_messages") or [],
        "tools": debug.get("tool_calls") or [],
        "tokens": choice_tokens(response),
        "commercial_payment_claims": debug.get("commercial_payment_claims") or [],
        "final_composer_status": debug.get("final_composer_status"),
        "payment_guard": debug.get("payment_policy_truth_guard") or {},
        "promo_guard": debug.get("promo_provider_truth_guard") or {},
        "choice_action_validation": response.get("choice_action_validation") or {},
        "promo_action_validation": response.get("promo_action_validation") or {},
        "delivery_result": response.get("delivery_result") or {},
        "llm_usage_summary": debug.get("llm_usage_summary") or {},
        "intent_tags": [
            str(item.get("tag") or "")
            for key in ("tags_to_add", "tags_skipped_existing")
            for item in tagging.get(key) or []
            if isinstance(item, Mapping) and str(item.get("tag") or "").strip()
        ],
        "analytical_qualifications": tagging.get("analytical_qualifications") or [],
    }


def render_markdown(artifact: Mapping[str, Any]) -> str:
    """Render complete customer inputs, surfaces, and machine evidence."""

    lines = [
        "# Runtime V7 Release Candidate Matrix",
        "",
        f"- Run: `{artifact['run_id']}`",
        f"- Mechanical passed: **{artifact['passed']}**",
        f"- Mechanical failed: **{artifact['failed']}**",
        "- Evaluation authority: **versioned pre-verified scenario contracts**",
        "",
        "The seven CS dimensions are deterministic structural proxies over "
        "pre-verified expected contracts. Complete rendered evidence remains "
        "available here for optional external audit.",
        "",
        "## Single-turn cases",
        "",
    ]
    for row in artifact["single_turn_cases"]:
        status = "PASS" if row["passed"] else "FAIL"
        lines.extend(
            [
                f"### {status} - {row['case_id']}",
                "",
                f"- Failures: `{row['failures']}`",
                f"- Customer: {json.dumps(row.get('message') or '', ensure_ascii=False)}",
                f"- Expected contract: `{json.dumps(row.get('expected_contract') or {}, ensure_ascii=False, sort_keys=True)}`",
                f"- Request: `{row['summary'].get('request_id')}`",
                f"- Latency: `{row['summary'].get('elapsed_ms')} ms`",
                f"- Tools: `{[item.get('name') for item in row['summary'].get('tools') or []]}`",
                f"- Tool-chain evidence: `{row.get('tool_chain_evidence') or []}`",
                "",
                *[
                    f"> {line}"
                    for bubble in row["summary"].get("bubbles") or []
                    for line in str(bubble).splitlines()
                ],
                "",
            ]
        )
        for content in row["summary"].get("content_messages") or []:
            lines.append(
                f"```json\n{json.dumps(content, ensure_ascii=False, indent=2)}\n```"
            )
        lines.append("")
    lines.extend(["## Journeys", ""])
    for row in artifact["journeys"]:
        status = "PASS" if row["passed"] else "FAIL"
        lines.extend(
            [
                f"### {status} - {row['case_id']}",
                "",
                f"- Failures: `{row['failures']}`",
                f"- Expected contract: `{json.dumps(row.get('expected_contract') or {}, ensure_ascii=False, sort_keys=True)}`",
                "",
            ]
        )
        steps = row.get("steps") or []
        for index, summary in enumerate(row["summary"], start=1):
            step = steps[index - 1] if index <= len(steps) else {}
            customer_input = step.get("message") or step.get("token") or ""
            lines.append(
                f"- Step {index} `{step.get('action') or 'unknown'}` input "
                f"{json.dumps(customer_input, ensure_ascii=False)}; request "
                f"`{summary.get('request_id')}`, "
                f"`{summary.get('elapsed_ms')} ms`, tools "
                f"`{[item.get('name') for item in summary.get('tools') or []]}`"
            )
            for bubble in summary.get("bubbles") or []:
                lines.extend(f"  > {line}" for line in str(bubble).splitlines())
            for content in summary.get("content_messages") or []:
                lines.append(
                    f"```json\n{json.dumps(content, ensure_ascii=False, indent=2)}\n```"
                )
        lines.append("")
    lines.extend(["## Size+brand operational funnel", ""])
    for row in artifact.get("operational_funnel_scenarios") or []:
        status = "PASS" if row["passed"] else "FAIL"
        lines.extend(
            [
                f"### {status} - {row['case_id']}",
                "",
                f"- Failures: `{row['failures']}`",
                f"- Provenance: `{(row.get('expected_contract') or {}).get('provenance')}`",
                f"- Funnel stages: `{json.dumps(row.get('funnel_stages') or {}, ensure_ascii=False, sort_keys=True)}`",
                "",
            ]
        )
        steps = row.get("steps") or []
        for index, summary in enumerate(row.get("summary") or [], start=1):
            step = steps[index - 1] if index <= len(steps) else {}
            customer_input = step.get("message") or step.get("token") or ""
            lines.append(
                f"- Step {index} `{step.get('action') or 'unknown'}` input "
                f"{json.dumps(customer_input, ensure_ascii=False)}; request "
                f"`{summary.get('request_id')}`, `{summary.get('elapsed_ms')} ms`"
            )
            for bubble in summary.get("bubbles") or []:
                lines.extend(f"  > {line}" for line in str(bubble).splitlines())
            for content in summary.get("content_messages") or []:
                lines.append(
                    f"```json\n{json.dumps(content, ensure_ascii=False, indent=2)}\n```"
                )
        lines.append("")
    return "\n".join(lines)


def _bubble_order(key: str) -> int:
    match = re.search(r"(\d+)$", key)
    return int(match.group(1)) if match else 999


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    main()
