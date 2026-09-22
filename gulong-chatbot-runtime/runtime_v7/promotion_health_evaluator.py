"""Deterministically score Runtime V7 release-candidate artifacts.

The evaluator executes a versioned set of pre-verified scenario contracts. It
does not require a reviewer or use an LLM as release authority, and it does not
grade wording against one reference sentence. Mutable commercial facts remain
owned by provider evidence captured in each tester response.
"""

from __future__ import annotations

import json
import hashlib
import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from runtime_v7.order_canonicalization import (
    local_canonical_payment_method,
    local_canonical_payment_option,
)


SCHEMA_VERSION = "runtime_v7_promotion_health_v2"
SCENARIO_CONTRACT_SCHEMA_VERSION = "runtime_v7_preverified_scenarios_v1"
SCENARIO_CONTRACT_VERSION = "2026-09-16.2"
OPERATIONAL_FUNNEL_CONTRACT_SCHEMA_VERSION = (
    "runtime_v7_operational_funnel_scenarios_v1"
)
OPERATIONAL_FUNNEL_CONTRACT_VERSION = "2026-09-16.1"

REQUIRED_SCENARIOS_BY_TIER: Mapping[str, Mapping[str, Sequence[str]]] = {
    "smoke": {
        "cases": (
            "business_contact_grounded",
            "delivery_policy_grounded",
            "payment_yokohama_home_credit",
        ),
        "journeys": (),
    },
    "promotion": {
        "cases": (
            "promo_toyo_truth",
            "promo_apollo_valid",
            "promo_vredestein_valid",
            "payment_yokohama_home_credit",
            "payment_two_brand_reordered_typo",
            "payment_apollo_unknown_provider",
            "availability_exact_brand_size",
            "size_zr_normalization",
            "brandless_promo_discovery",
            "business_contact_grounded",
            "delivery_policy_grounded",
            "delivery_policy_typo_variation",
            "semantic_store_location",
            "explicit_head_office_address",
            "province_schedule_gate",
            "nonlinear_product_first",
        ),
        "journeys": (
            "product_location_schedule_payment_journey",
            "promo_details_informational_journey",
            "about_brand_source_backed_journey",
        ),
    },
}
REQUIRED_SCENARIOS_BY_TIER["full"] = REQUIRED_SCENARIOS_BY_TIER["promotion"]

REQUIRED_OPERATIONAL_FUNNEL_SCENARIOS_BY_TIER: Mapping[str, Sequence[str]] = {
    "smoke": (),
    "promotion": (
        "size_brand_typed_location_shortform",
        "size_brand_guided_location_choice",
        "size_brand_contact_fallback",
        "size_brand_location_complete_negative_control",
    ),
}
REQUIRED_OPERATIONAL_FUNNEL_SCENARIOS_BY_TIER["full"] = (
    REQUIRED_OPERATIONAL_FUNNEL_SCENARIOS_BY_TIER["promotion"]
)

ALLOWED_OPERATIONAL_FUNNEL_ACTIONS: Mapping[str, Sequence[Sequence[str]]] = {
    "size_brand_typed_location_shortform": (("chat", "chat"),),
    "size_brand_guided_location_choice": (
        ("chat", "click_product", "click_location"),
        ("chat", "click_product", "click_location", "click_location"),
        ("chat", "click_product", "chat", "click_location"),
        ("chat", "click_product", "chat", "click_location", "click_location"),
        ("chat", "click_location"),
        ("chat", "click_location", "click_location"),
        ("chat", "chat", "click_location"),
        ("chat", "chat", "click_location", "click_location"),
    ),
    "size_brand_contact_fallback": (
        ("chat", "chat", "chat"),
        ("chat", "click_product", "chat", "chat"),
    ),
    "size_brand_location_complete_negative_control": (("chat",),),
}

REQUIRED_OPERATIONAL_FUNNEL_STAGES: Mapping[str, Sequence[str]] = {
    "size_brand_typed_location_shortform": (
        "eligible_near_miss",
        "location_request_rendered",
        "typed_response_accepted",
        "canonical_location_captured",
        "official_mh_planned",
        "final_response_rendered",
    ),
    "size_brand_guided_location_choice": (
        "eligible_near_miss",
        "location_request_rendered",
        "guided_response_accepted",
        "canonical_location_captured",
        "official_mh_planned",
        "final_response_rendered",
    ),
    "size_brand_contact_fallback": (
        "eligible_near_miss",
        "location_request_rendered",
        "contact_fallback_offered",
        "uncertain_location_not_captured",
        "mh_not_planned_before_contact",
        "typed_response_accepted",
        "canonical_contact_captured",
        "official_mh_planned",
        "final_response_rendered",
    ),
    "size_brand_location_complete_negative_control": (
        "excluded_from_near_miss",
        "location_not_reasked",
        "official_mh_planned",
        "final_response_rendered",
    ),
}

# Filled from the exact versioned data-derived definitions in the release
# matrix. Updating these digests requires a deliberate contract review.
APPROVED_OPERATIONAL_FUNNEL_DEFINITION_DIGESTS: Mapping[str, str] = {
    "smoke": "dd3c5c9614d2f71dc0b47903997304d3ed9d840399617a023f9f2cfb1fa8875b",
    "promotion": "7a07688aeed853c3ef9e4b279a98b1a83b224eacc45850e448e2522a041e8810",
    "full": "d69732769140be9a6126f4ec3ec8950da58e4a4e3e82727befb6a247199043dd",
}

ALLOWED_JOURNEY_ACTIONS: Mapping[str, Sequence[Sequence[str]]] = {
    "product_location_schedule_payment_journey": (
        (
            "chat",
            "click_product",
            "click_schedule",
            "click_payment_option",
            "click_payment_method",
        ),
        (
            "chat",
            "click_product",
            "chat_schedule",
            "click_schedule",
            "click_payment_option",
            "click_payment_method",
        ),
        (
            "chat",
            "click_product",
            "click_location",
            "click_schedule",
            "click_payment_option",
            "click_payment_method",
        ),
        (
            "chat",
            "click_product",
            "click_location",
            "click_location",
            "click_schedule",
            "click_payment_option",
            "click_payment_method",
        ),
    ),
    "promo_details_informational_journey": (
        ("chat",),
        ("chat", "click_promo_details"),
    ),
    "about_brand_source_backed_journey": (
        ("chat",),
        ("chat", "click_about_brand"),
    ),
}

# Updated only when the versioned scenario inputs/contracts are intentionally
# changed and re-verified. The matrix computes the digest from its definitions.
APPROVED_SCENARIO_DEFINITION_DIGESTS: Mapping[str, str] = {
    "smoke": "c5fbb12db35e126547596a64cb90a9176581143b9886e384c5945b5ac84a80b2",
    "promotion": "b5839290ecf5abeb2c3bd02810a5eb595d21edc715025f4d4c9087de9f9ca81f",
    "full": "5d12424c2ccfce0a6d39f57b14e78ab13b8392336708548314b8f2c37dd2c5b5",
}

# Baseline-only compatibility. These exact previous-contract identities retain
# the same scenario/action cohort and health policy; the current candidate is
# still validated exclusively against the current approved digest above.
APPROVED_BASELINE_CONTRACT_BRIDGES: Mapping[
    tuple[str, str], frozenset[tuple[str, str]]
] = {
    (
        "2026-09-16.2",
        "c5fbb12db35e126547596a64cb90a9176581143b9886e384c5945b5ac84a80b2",
    ): frozenset(
        {
            (
                "2026-09-13.1",
                "2807dca165f92d117fa83323d204fe28bb2cb6e0c35314d343b6b4d1a6c95d47",
            ),
            (
                "2026-09-11.4",
                "dc1d4fae3852e180e368e9fe6d775989e5589434498252eae443b4afb5adce1f",
            )
        }
    ),
    (
        "2026-09-16.2",
        "b5839290ecf5abeb2c3bd02810a5eb595d21edc715025f4d4c9087de9f9ca81f",
    ): frozenset(
        {
            (
                "2026-09-13.1",
                "59455de47429e53e92726b035f456c37e29f0d957dfdffadf225793750cc90ef",
            ),
            (
                "2026-09-11.4",
                "5b803facd63ed902e01a3f81172137dff20e23c63974cde7d0bf342dc8d39ddf",
            )
        }
    ),
    (
        "2026-09-16.2",
        "5d12424c2ccfce0a6d39f57b14e78ab13b8392336708548314b8f2c37dd2c5b5",
    ): frozenset(
        {
            (
                "2026-09-13.1",
                "5d277c269a3359f1acc0d33eac7d1debc4621f5944bece05a4534aac9d8460b0",
            ),
            (
                "2026-09-11.4",
                "cc7cc0f71ab99b596d1881782d6bf05c97c9e0b33780231c13c33e62b509cac7",
            )
        }
    ),
}

CS_DIMENSIONS: Sequence[str] = (
    "understands_customer",
    "natural_language",
    "directness",
    "grounding",
    "progression",
    "presentation",
    "consistency",
)

MUTATING_TOOLS = frozenset(
    {
        "submit_order",
        "prepare_payment_request",
        "process_payment_proof",
        "verify_payment_proof",
    }
)

TOOL_ERROR_STATUSES = frozenset(
    {"error", "failed", "exception", "timeout", "unavailable"}
)

DEFAULT_HEALTH_POLICY: Mapping[str, float] = {
    "latency_p95_concern_ms": 45_000,
    "latency_p95_fail_ms": 95_000,
    "total_token_regression_concern_percent": 10.0,
    "total_token_regression_fail_percent": 25.0,
    # This remains the approved cap for the frozen core matrix. The
    # operational-funnel add-on has its own independently enforced budget.
    "max_total_tokens": 2_000_000,
    "max_operational_funnel_tokens": 1_200_000,
    "max_model_calls": 250,
}


def effective_health_policy(profile: Mapping[str, Any]) -> Dict[str, float]:
    """Return the sealed budget policy, defaulting the new add-on cap for old artifacts."""

    effective = dict(DEFAULT_HEALTH_POLICY)
    configured = profile.get("health_policy") or {}
    if not isinstance(configured, Mapping):
        return effective
    for key in DEFAULT_HEALTH_POLICY:
        value = configured.get(key)
        if (
            key in {"max_total_tokens", "max_operational_funnel_tokens"}
            and type(value) in (int, float)
            and 0 < value <= DEFAULT_HEALTH_POLICY[key]
        ):
            effective[key] = configured[key]
    return effective


def health_policy_failures(profile: Mapping[str, Any]) -> List[str]:
    """Reject malformed or expanded caps while accepting legacy sealed artifacts."""

    configured = profile.get("health_policy")
    if not isinstance(configured, Mapping):
        return ["scenario_contract_health_policy_mismatch"]
    for key, default in DEFAULT_HEALTH_POLICY.items():
        if key == "max_operational_funnel_tokens" and key not in configured:
            # Artifacts sealed before the add-on cap inherit its safe default.
            continue
        value = configured.get(key)
        if key in {"max_total_tokens", "max_operational_funnel_tokens"}:
            if type(value) not in (int, float) or not 0 < value <= default:
                return ["scenario_contract_health_policy_mismatch"]
        elif value != default:
            return ["scenario_contract_health_policy_mismatch"]
    return []


# Compare cost only where both revisions executed the same scenario action and
# exposed valid usage. This remains outside the artifact scenario contract so
# historical baselines can be rescored without treating newly restored journey
# steps as if the older revision had executed them for zero tokens.
MIN_BASELINE_ACTION_COVERAGE_PERCENT = 80.0


def canonical_json_digest(value: Any) -> str:
    """Return a stable SHA-256 digest for JSON-compatible evidence."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def artifact_evidence_digest(artifact: Mapping[str, Any]) -> str:
    """Digest run evidence while excluding derived score and integrity fields."""

    evidence = {
        key: value
        for key, value in artifact.items()
        if key not in {"promotion_health", "artifact_integrity"}
    }
    return canonical_json_digest(evidence)


def attach_artifact_integrity(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """Attach a self-checking content digest before deterministic scoring."""

    artifact["artifact_integrity"] = {
        "algorithm": "sha256",
        "scope": "artifact_without_promotion_health_or_artifact_integrity",
        "evidence_digest": artifact_evidence_digest(artifact),
    }
    return artifact


def canonical_text(value: Any) -> str:
    """Normalize a stable identifier or label without erasing its meaning."""

    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = normalized.replace("–", "-").replace("—", "-")
    return " ".join(normalized.split())


def canonical_tire_size(value: Any) -> str:
    """Return a comparison form for common R/ZR tire-size spellings."""

    value_text = canonical_text(value).upper().replace(" ", "")
    value_text = value_text.replace("-", "/")
    return re.sub(r"[^0-9A-Z/]", "", value_text)


def canonical_equivalent(actual: Any, expected: Any, *, kind: str = "text") -> bool:
    """Compare canonical values while keeping the asserted kind explicit."""

    if kind == "tire_size":
        return canonical_tire_size(actual) == canonical_tire_size(expected)
    if kind == "payment_method":
        actual_local = local_canonical_payment_method(actual)
        expected_local = local_canonical_payment_method(expected)
        if actual_local and expected_local:
            return canonical_text(actual_local) == canonical_text(expected_local)
        return _payment_method_key(actual) == _payment_method_key(expected)
    if kind == "payment_option":
        return canonical_text(
            local_canonical_payment_option(actual) or actual
        ) == canonical_text(local_canonical_payment_option(expected) or expected)
    if kind in {"brand", "location", "faq_id"}:
        return canonical_text(actual) == canonical_text(expected)
    return canonical_text(actual) == canonical_text(expected)


def _payment_method_key(value: Any) -> str:
    """Normalize common bank/term spellings while retaining scope identity."""

    tokens = re.findall(r"[a-z0-9]+", canonical_text(value))
    ignored = {
        "month",
        "months",
        "mos",
        "mo",
        "installment",
        "interest",
        "term",
    }
    return " ".join(token for token in tokens if token not in ignored)


def phrase_tolerant_fact_present(text: str, fact: Mapping[str, Any]) -> bool:
    """Check a fact concept using alternatives, not a reference response."""

    normalized = canonical_text(text)
    alternatives = fact.get("any_of") or []
    if not alternatives and fact.get("all_terms"):
        alternatives = [{"all_terms": fact.get("all_terms")}]
    for alternative in alternatives:
        if isinstance(alternative, str):
            if canonical_text(alternative) in normalized:
                return True
            continue
        if not isinstance(alternative, Mapping):
            continue
        terms = [canonical_text(term) for term in alternative.get("all_terms") or []]
        if terms and all(term in normalized for term in terms):
            return True
        pattern = str(alternative.get("regex") or "")
        if pattern and re.search(pattern, text, flags=re.IGNORECASE):
            return True
    return False


def tool_argument_contract_failures(
    contracts: Sequence[Mapping[str, Any]],
    response: Mapping[str, Any],
) -> List[str]:
    """Validate exact/canonical tool arguments from tester-only trace evidence."""

    calls = _tool_calls_with_args(response)
    failures: List[str] = []
    for contract in contracts:
        tool_name = str(contract.get("tool") or "")
        minimum = int(contract.get("minimum_matches") or 1)
        matches = 0
        for call in calls:
            if str(call.get("name") or "") != tool_name:
                continue
            args = call.get("args") if isinstance(call.get("args"), Mapping) else {}
            if _arguments_match(args, contract.get("args") or {}):
                matches += 1
        if matches < minimum:
            contract_id = str(contract.get("id") or tool_name or "unknown")
            failures.append(f"tool_arg_contract:{contract_id}:{matches}<{minimum}")
    return failures


def tool_argument_chain_evidence(
    contracts: Sequence[Mapping[str, Any]],
    response: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Trace required scopes from model proposal through execution and dedupe.

    Model-call spans are the pre-hydration source, debug tool calls represent
    actual provider executions, and bounded dedupe events identify calls that
    were reused instead.  Contracts may define different ``pre_args`` and
    ``post_args`` when hydration is expected to remove or canonicalize fields.
    """

    model_calls = _model_tool_calls_with_args(response)
    executed_calls = _executed_tool_calls_with_args(response)
    dedupe_events = _tool_dedupe_events(response)
    evidence: List[Dict[str, Any]] = []
    for contract in contracts:
        contract_id = str(contract.get("id") or contract.get("tool") or "unknown")
        tool_name = str(contract.get("tool") or "")
        minimum = int(contract.get("minimum_matches") or 1)
        default_args = contract.get("args") or {}
        pre_args = contract.get("pre_args") or default_args
        post_args = contract.get("post_args") or default_args
        pre_matches = [
            call
            for call in model_calls
            if str(call.get("name") or "") == tool_name
            and _arguments_match(call.get("args") or {}, pre_args)
        ]
        pre_identities = {
            identity
            for identity in (_tool_call_identity(call) for call in pre_matches)
            if identity is not None
        }
        executed_matches = [
            call
            for call in executed_calls
            if _tool_call_identity(call) in pre_identities
            and str(call.get("name") or "") == tool_name
            and _arguments_match(call.get("args") or {}, post_args)
        ]
        matching_reuse = [
            event
            for event in dedupe_events
            if _tool_call_identity(event) in pre_identities
            and str(event.get("name") or "") == tool_name
        ]
        changed_reuse = [
            event
            for event in matching_reuse
            if not _arguments_match(event.get("args") or {}, post_args)
        ]
        equivalent_reuse = len(matching_reuse) - len(changed_reuse)
        allow_equivalent_reuse = bool(contract.get("allow_equivalent_reuse", True))
        missing_identities = sum(
            _tool_call_identity(call) is None for call in pre_matches
        )
        passed = (
            len(pre_matches) >= minimum
            and len(executed_matches) >= minimum
            and not changed_reuse
            and not missing_identities
            and (allow_equivalent_reuse or not equivalent_reuse)
        )
        evidence.append(
            {
                "contract_id": contract_id,
                "tool": tool_name,
                "required_matches": minimum,
                "pre_hydration_matches": len(pre_matches),
                "provider_execution_matches": len(executed_matches),
                "equivalent_dedup_reuse": equivalent_reuse,
                "equivalent_dedup_reuse_allowed": allow_equivalent_reuse,
                "scope_changed_before_dedup": len(changed_reuse),
                "missing_call_identity": missing_identities,
                "passed": passed,
            }
        )
    return evidence


def tool_argument_chain_contract_failures(
    contracts: Sequence[Mapping[str, Any]],
    response: Mapping[str, Any],
) -> List[str]:
    """Return deterministic failures for incomplete or corrupted tool chains."""

    failures: List[str] = []
    for row in tool_argument_chain_evidence(contracts, response):
        contract_id = row["contract_id"]
        minimum = row["required_matches"]
        if row["pre_hydration_matches"] < minimum:
            failures.append(
                "tool_chain_pre_hydration:"
                f"{contract_id}:{row['pre_hydration_matches']}<{minimum}"
            )
        if row["missing_call_identity"]:
            failures.append(
                f"tool_chain_call_identity:{contract_id}:"
                f"{row['missing_call_identity']} missing"
            )
        if row["provider_execution_matches"] < minimum:
            failures.append(
                "tool_chain_provider_execution:"
                f"{contract_id}:{row['provider_execution_matches']}<{minimum}"
            )
        if row["scope_changed_before_dedup"]:
            failures.append(
                f"tool_chain_dedup_scope_changed:{contract_id}:"
                f"{row['scope_changed_before_dedup']}"
            )
        if (
            not row["equivalent_dedup_reuse_allowed"]
            and row["equivalent_dedup_reuse"]
            and not row["scope_changed_before_dedup"]
        ):
            failures.append(
                f"tool_chain_dedup_reuse_not_allowed:{contract_id}:"
                f"{row['equivalent_dedup_reuse']}"
            )
    return failures


def payment_authority_contract_failures(response: Mapping[str, Any]) -> List[str]:
    """Require each typed payment fact to agree with its provider-owned scope."""

    debug = response.get("debug") or {}
    claims = [
        claim
        for claim in debug.get("commercial_payment_claims") or []
        if isinstance(claim, Mapping)
    ]
    failures: List[str] = []
    claimable_scope_identities: set[tuple[str, str, str, str]] = set()
    for index, call in enumerate(debug.get("tool_calls") or [], start=1):
        if not isinstance(call, Mapping) or call.get("name") != "answer_order_faq":
            continue
        scope = (
            call.get("payment_scope")
            if isinstance(call.get("payment_scope"), Mapping)
            else {}
        )
        authority = (
            call.get("authority") if isinstance(call.get("authority"), Mapping) else {}
        )
        method = scope.get("requested_method")
        brand = scope.get("brand")
        option = scope.get("payment_option")
        requested_status = canonical_text(scope.get("requested_status"))
        brand_status = canonical_text(scope.get("brand_eligibility"))
        expected_outcome = ""
        if requested_status == "unsupported":
            expected_outcome = "unsupported"
            brand = ""
            option = ""
        elif brand_status == "not_eligible":
            expected_outcome = "not_eligible"
        elif brand_status in {"eligible", "not_brand_restricted"}:
            expected_outcome = "eligible"
        if not expected_outcome:
            continue
        claimable_scope_identities.add(
            (
                canonical_text(method),
                expected_outcome,
                canonical_text(brand),
                canonical_text(option),
            )
        )
        if not authority.get("source") or not (
            authority.get("evidence_ref") or authority.get("faq_id")
        ):
            failures.append(f"payment_authority_evidence_missing:{index}")
        if not any(
            canonical_equivalent(claim.get("method"), method, kind="payment_method")
            and canonical_text(claim.get("outcome")) == expected_outcome
            and (
                not brand
                or canonical_equivalent(claim.get("brand"), brand, kind="brand")
            )
            and (
                not option
                or canonical_text(option) in canonical_text(claim.get("payment_option"))
                or canonical_text(claim.get("payment_option")) in canonical_text(option)
            )
            for claim in claims
        ):
            failures.append(
                "payment_claim_not_backed_by_authority:"
                f"{index}:{method}|{expected_outcome}|{brand}|{option}"
            )
    claimable_scope_count = len(claimable_scope_identities)
    if claimable_scope_count and len(claims) < claimable_scope_count:
        failures.append(
            f"payment_claim_scope_count:{len(claims)}<{claimable_scope_count}"
        )
    return failures


def score_release_candidate(
    artifact: Mapping[str, Any],
    *,
    baseline: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute an automated promotion status from pre-verified scenarios."""

    rows = list(_all_rows(artifact))
    responses = list(_all_responses(rows))
    total = len(rows)
    passed = sum(bool(row.get("passed")) for row in rows)
    mechanical_score = round(100.0 * passed / total, 2) if total else 0.0

    technical = _technical_health(responses)
    telemetry_contract_failures = _telemetry_contract_failures(rows)
    cs_proxy = _structural_cs_proxy(rows)
    scenario_contract = _scenario_contract_status(artifact)
    operational_funnel = _operational_funnel_status(artifact)
    integrity = _artifact_integrity_status(artifact)
    target_identity = _target_identity_status(artifact, responses)
    baseline_comparison = _compare_baseline(artifact, baseline)
    policy = effective_health_policy(artifact.get("evaluation_profile") or {})
    operational_technical = operational_funnel.get("technical") or {}
    core_total_tokens = _int_or_zero(technical["tokens"].get("total_tokens"))
    core_model_calls = _int_or_zero(technical.get("model_call_count"))
    operational_total_tokens = _int_or_zero(
        (operational_technical.get("tokens") or {}).get("total_tokens")
    )
    operational_model_calls = _int_or_zero(
        operational_technical.get("model_call_count")
    )
    combined_total_tokens = core_total_tokens + operational_total_tokens
    combined_model_calls = core_model_calls + operational_model_calls
    blockers: List[str] = []
    warnings: List[str] = []
    if total == 0:
        blockers.append("no_scenarios_evaluated")
    if passed != total:
        blockers.append(f"mechanical_failures:{total - passed}")
    if technical["http_error_count"]:
        blockers.append(f"http_errors:{technical['http_error_count']}")
    if technical["runtime_error_count"]:
        blockers.append(f"runtime_errors:{technical['runtime_error_count']}")
    if technical["tool_error_count"]:
        blockers.append(f"tool_errors:{technical['tool_error_count']}")
    if technical["mutating_tool_count"]:
        blockers.append(f"mutating_tools:{technical['mutating_tool_count']}")
    if technical["missing_latency_count"]:
        blockers.append(f"missing_latency:{technical['missing_latency_count']}")
    if technical["missing_usage_count"]:
        blockers.append(f"missing_model_usage:{technical['missing_usage_count']}")
    if technical["invalid_usage_count"]:
        blockers.append(f"invalid_model_usage:{technical['invalid_usage_count']}")
    if technical["missing_phase_timing_count"]:
        blockers.append(
            f"missing_runtime_phase_timing:{technical['missing_phase_timing_count']}"
        )
    if technical["invalid_phase_timing_count"]:
        blockers.append(
            f"invalid_runtime_phase_timing:{technical['invalid_phase_timing_count']}"
        )
    if technical["missing_tool_latency_count"]:
        blockers.append(
            f"missing_tool_latency:{technical['missing_tool_latency_count']}"
        )
    blockers.extend(telemetry_contract_failures)
    if scenario_contract["status"] != "pass":
        blockers.extend(scenario_contract["failures"])
    if operational_funnel["status"] == "fail":
        blockers.extend(operational_funnel["failures"])
    warnings.extend(operational_funnel.get("concerns") or [])
    if integrity["status"] != "pass":
        blockers.extend(integrity["failures"])
    if target_identity["status"] != "pass":
        blockers.extend(target_identity["failures"])
    if cs_proxy["status"] != "pass":
        warnings.append(
            f"cs_structural_proxy_concerns:{len(cs_proxy.get('concerns') or [])}"
        )
    p95_latency = technical["latency_ms"]["p95"]
    if p95_latency is not None:
        if p95_latency > policy["latency_p95_fail_ms"]:
            blockers.append(f"p95_latency_ms:{p95_latency}")
        elif p95_latency > policy["latency_p95_concern_ms"]:
            warnings.append(f"p95_latency_ms:{p95_latency}")
    token_regression = (baseline_comparison.get("deltas") or {}).get(
        "total_tokens_percent"
    )
    if token_regression is not None:
        if token_regression > policy["total_token_regression_fail_percent"]:
            blockers.append(f"total_token_regression_percent:{token_regression}")
        elif token_regression > policy["total_token_regression_concern_percent"]:
            warnings.append(f"total_token_regression_percent:{token_regression}")
    if core_total_tokens > policy["max_total_tokens"]:
        blockers.append(
            f"total_token_budget:{core_total_tokens}"
            f">{int(policy['max_total_tokens'])}"
        )
    if operational_total_tokens > policy["max_operational_funnel_tokens"]:
        blockers.append(
            "operational_funnel_token_budget:"
            f"{operational_total_tokens}"
            f">{int(policy['max_operational_funnel_tokens'])}"
        )
    if core_model_calls > policy["max_model_calls"]:
        blockers.append(
            f"model_call_budget:{core_model_calls}>{int(policy['max_model_calls'])}"
        )
    if (artifact.get("evaluation_profile") or {}).get("require_compatible_baseline"):
        if baseline_comparison.get("status") != "compatible":
            blockers.append(
                f"baseline:{baseline_comparison.get('status') or 'missing'}"
            )

    if blockers:
        grade = "red"
        promotion_status = "blocked"
    elif str((artifact.get("evaluation_profile") or {}).get("tier")) == "smoke":
        grade = "green"
        promotion_status = "diagnostic_pass"
    elif warnings:
        grade = "yellow"
        promotion_status = "automated_gate_concern"
    else:
        grade = "green"
        promotion_status = "ready_for_promotion"

    report = {
        "schema_version": SCHEMA_VERSION,
        "run_id": artifact.get("run_id"),
        "evaluation_profile": artifact.get("evaluation_profile") or {},
        "grade": grade,
        "promotion_status": promotion_status,
        "blockers": blockers,
        "warnings": warnings,
        "health_policy": policy,
        "mechanical": {
            "status": "pass" if total and passed == total else "fail",
            "score_percent": mechanical_score,
            "passed": passed,
            "failed": total - passed,
            "total": total,
            "failure_evidence": [
                {
                    "case_id": row.get("case_id"),
                    "failures": list(row.get("failures") or []),
                }
                for row in rows
                if row.get("failures")
            ],
            "by_domain": _domain_breakdown(rows),
        },
        "technical": technical,
        "metered_usage": {
            "scope": "core_plus_operational_funnel",
            "core": {
                "model_call_count": core_model_calls,
                "total_tokens": core_total_tokens,
                "max_total_tokens": int(policy["max_total_tokens"]),
            },
            "operational_funnel": {
                "model_call_count": operational_model_calls,
                "total_tokens": operational_total_tokens,
                "max_total_tokens": int(policy["max_operational_funnel_tokens"]),
            },
            "total_tokens": combined_total_tokens,
            "model_call_count": combined_model_calls,
        },
        "cs_structural_proxy": cs_proxy,
        "preverified_scenario_contract": scenario_contract,
        "operational_funnel": operational_funnel,
        "artifact_integrity": integrity,
        "target_identity": target_identity,
        "baseline_comparison": baseline_comparison,
        "evidence_limits": [
            "Tester route uses return-only delivery and disables analytics, but synthetic session state and traces persist in isolated test collections.",
            "The automated CS rubric validates pre-verified hard-fact and structural contracts; it does not claim fresh human judgment of every generated phrase.",
            "Token usage is measured from runtime telemetry; monetary cost is unavailable unless separately priced by model/component.",
            "Provider-relative commercial evidence prevents stale pack literals, but does not replace canonical-source QA.",
            "Operational-funnel status is a synthetic pre-delivery capability score; actual ManyChat delivery, production abandonment, and 7/14-day linked booking conversion remain observational metrics.",
        ],
    }
    return report


def render_health_markdown(report: Mapping[str, Any]) -> str:
    """Render the compact promotion-health section used by operators."""

    mechanical = report.get("mechanical") or {}
    technical = report.get("technical") or {}
    proxy = report.get("cs_structural_proxy") or {}
    scenario_contract = report.get("preverified_scenario_contract") or {}
    operational_funnel = report.get("operational_funnel") or {}
    metered_usage = report.get("metered_usage") or {}
    core_usage = metered_usage.get("core") or {}
    operational_usage = metered_usage.get("operational_funnel") or {}
    integrity = report.get("artifact_integrity") or {}
    target_identity = report.get("target_identity") or {}
    baseline = report.get("baseline_comparison") or {}
    lines = [
        "# Runtime V7 Promotion Health",
        "",
        f"- Grade: **{str(report.get('grade') or '').upper()}**",
        f"- Promotion status: **{report.get('promotion_status')}**",
        f"- Mechanical: **{mechanical.get('passed')}/{mechanical.get('total')}** ({mechanical.get('score_percent')}%)",
        f"- Structural CS proxy: **{proxy.get('status')}** ({proxy.get('score_percent')}%)",
        f"- Pre-verified scenario contract: **{scenario_contract.get('status')}**",
        f"- Size+brand to M/H operational funnel: **{operational_funnel.get('status')}** ({operational_funnel.get('score_percent')}%)",
        f"- Artifact integrity: **{integrity.get('status')}**",
        f"- Target identity: **{target_identity.get('status')}**",
        f"- HTTP/runtime/tool errors: **{technical.get('http_error_count')}/{technical.get('runtime_error_count')}/{technical.get('tool_error_count')}**",
        f"- Core matrix usage: **{core_usage.get('total_tokens')} / {core_usage.get('max_total_tokens')} tokens; {core_usage.get('model_call_count')} model calls**",
        f"- Operational-funnel usage: **{operational_usage.get('total_tokens')} / {operational_usage.get('max_total_tokens')} tokens; {operational_usage.get('model_call_count')} model calls**",
        f"- Metered usage (core + operational): **{metered_usage.get('total_tokens')} tokens / {metered_usage.get('model_call_count')} model calls**",
        f"- Latency p50/p95: **{technical.get('latency_ms', {}).get('p50')}/{technical.get('latency_ms', {}).get('p95')} ms**",
        f"- Handler p50/p95: **{technical.get('runtime_phase_latency_ms', {}).get('handler_total', {}).get('p50')}/{technical.get('runtime_phase_latency_ms', {}).get('handler_total', {}).get('p95')} ms**",
        f"- Client/transport overhead p50/p95: **{technical.get('client_transport_overhead_ms', {}).get('p50')}/{technical.get('client_transport_overhead_ms', {}).get('p95')} ms**",
        f"- Runtime phase/tool-latency telemetry gaps: **{technical.get('missing_phase_timing_count')}/{technical.get('invalid_phase_timing_count')}/{technical.get('missing_tool_latency_count')}**",
        f"- Prompt/cache/completion tokens: **{technical.get('tokens', {}).get('prompt_tokens')}/{technical.get('tokens', {}).get('cache_read_input_tokens')}/{technical.get('tokens', {}).get('completion_tokens')}**",
        f"- Estimated cost: **{technical.get('estimated_cost', {}).get('status')}**",
        f"- Baseline: **{baseline.get('status')}**",
        f"- Baseline deltas: `{json.dumps(baseline.get('deltas') or {}, sort_keys=True)}`",
        f"- Baseline context differences: `{baseline.get('context_differences') or []}`",
        "",
    ]
    blockers = list(report.get("blockers") or [])
    lines.append("## Blockers")
    lines.append("")
    lines.extend(f"- `{item}`" for item in blockers)
    if not blockers:
        lines.append("- None")
    warnings = list(report.get("warnings") or [])
    lines.extend(["", "## Concerns", ""])
    lines.extend(f"- `{item}`" for item in warnings)
    if not warnings:
        lines.append("- None")
    lines.extend(["", "## Domain coverage", ""])
    for domain, item in (mechanical.get("by_domain") or {}).items():
        lines.append(
            f"- `{domain}`: {item.get('passed')}/{item.get('total')} "
            f"({item.get('score_percent')}%)"
        )
    lines.extend(["", "## Size+brand near-miss operational funnel", ""])
    for stage, item in (operational_funnel.get("by_stage") or {}).items():
        lines.append(
            f"- `{stage}`: {item.get('passed')}/{item.get('total')} "
            f"({item.get('score_percent')}%)"
        )
    observational = operational_funnel.get("downstream_observational_metrics") or {}
    for metric, item in observational.items():
        lines.append(f"- `{metric}`: {item.get('status')}")
    lines.extend(["", "## Evidence limits", ""])
    lines.extend(f"- {item}" for item in report.get("evidence_limits") or [])
    failures = mechanical.get("failure_evidence") or []
    if failures:
        lines.extend(["", "## Mechanical failure evidence", ""])
        for item in failures:
            lines.append(f"- `{item.get('case_id')}`: `{item.get('failures')}`")
    return "\n".join(lines) + "\n"


def load_json(path: Path) -> Dict[str, Any]:
    """Read one UTF-8 JSON artifact."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _arguments_match(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    for key, specification in expected.items():
        actual_value = actual.get(key)
        if isinstance(specification, Mapping):
            if specification.get("absent") is True:
                if actual_value not in (None, "", [], {}):
                    return False
                continue
            expected_value = specification.get("equals")
            kind = str(specification.get("kind") or "text")
            if expected_value is not None and not canonical_equivalent(
                actual_value, expected_value, kind=kind
            ):
                return False
            contains = specification.get("contains")
            if contains is not None:
                if isinstance(actual_value, (list, tuple, set)):
                    if not any(
                        canonical_equivalent(item, contains, kind=kind)
                        for item in actual_value
                    ):
                        return False
                elif canonical_text(contains) not in canonical_text(actual_value):
                    return False
            if specification.get("present") is True and actual_value in (
                None,
                "",
                [],
                {},
            ):
                return False
        elif actual_value != specification:
            return False
    return True


def _tool_call_identity(call: Mapping[str, Any]) -> Optional[tuple[str, str]]:
    call_id = str(call.get("tool_call_id") or call.get("id") or "").strip()
    if not call_id:
        return None
    return str(call.get("round") or ""), call_id


def _model_tool_calls_with_args(response: Mapping[str, Any]) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    turn_trace = (response.get("debug") or {}).get("turn_trace") or {}
    for span in turn_trace.get("component_spans") or []:
        if not isinstance(span, Mapping) or span.get("component_type") != "model_call":
            continue
        for call in span.get("tool_calls") or []:
            if not isinstance(call, Mapping):
                continue
            function = (
                call.get("function")
                if isinstance(call.get("function"), Mapping)
                else {}
            )
            args = call.get("args")
            if not isinstance(args, Mapping):
                args = (
                    function.get("arguments")
                    if isinstance(function.get("arguments"), Mapping)
                    else {}
                )
            calls.append(
                {
                    "round": span.get("round"),
                    "tool_call_id": call.get("id") or call.get("tool_call_id"),
                    "name": call.get("name") or function.get("name"),
                    "args": dict(args or {}),
                }
            )
    return calls


def _executed_tool_calls_with_args(response: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [
        dict(item)
        for item in (response.get("debug") or {}).get("tool_calls") or []
        if isinstance(item, Mapping)
    ]


def _tool_dedupe_events(response: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [
        dict(item)
        for item in (response.get("debug") or {}).get("tool_dedupe_events") or []
        if isinstance(item, Mapping)
    ]


def _tool_calls_with_args(response: Mapping[str, Any]) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    for item in (response.get("debug") or {}).get("tool_calls") or []:
        if isinstance(item, Mapping):
            calls.append(dict(item))
    turn_trace = (response.get("debug") or {}).get("turn_trace") or {}
    for span in turn_trace.get("component_spans") or []:
        if not isinstance(span, Mapping) or span.get("component_type") != "tool_call":
            continue
        calls.append(
            {
                "name": span.get("component_name"),
                "status": span.get("status"),
                "args": dict(span.get("input") or {}),
            }
        )
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for call in calls:
        key = (
            str(call.get("name") or ""),
            json.dumps(call.get("args") or {}, ensure_ascii=False, sort_keys=True),
            str(call.get("round") or ""),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(call)
    return deduped


def _all_rows(artifact: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    yield from [
        row
        for row in artifact.get("single_turn_cases") or []
        if isinstance(row, Mapping)
    ]
    yield from [
        row for row in artifact.get("journeys") or [] if isinstance(row, Mapping)
    ]


def _operational_funnel_rows(
    artifact: Mapping[str, Any],
) -> Iterable[Mapping[str, Any]]:
    """Yield synthetic pre-delivery progression rows kept outside the baseline corpus."""

    yield from [
        row
        for row in artifact.get("operational_funnel_scenarios") or []
        if isinstance(row, Mapping)
    ]


def _domain_breakdown(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    buckets: Dict[str, Dict[str, int]] = {}
    for row in rows:
        domain = str(row.get("domain") or "unclassified")
        bucket = buckets.setdefault(domain, {"passed": 0, "failed": 0, "total": 0})
        bucket["total"] += 1
        bucket["passed" if row.get("passed") else "failed"] += 1
    for bucket in buckets.values():
        bucket["score_percent"] = round(100.0 * bucket["passed"] / bucket["total"], 2)
    return dict(sorted(buckets.items()))


def _all_responses(rows: Iterable[Mapping[str, Any]]) -> Iterable[Mapping[str, Any]]:
    for row in rows:
        response = row.get("response")
        if isinstance(response, Mapping):
            yield response
        for step in row.get("steps") or []:
            if isinstance(step, Mapping) and isinstance(step.get("response"), Mapping):
                yield step["response"]


def _technical_health(responses: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    latencies: List[int] = []
    http_errors = 0
    runtime_errors = 0
    tool_errors = 0
    tool_calls = 0
    mutating_tools = 0
    model_calls = 0
    missing_latency = 0
    missing_usage = 0
    invalid_usage = 0
    missing_phase_timings = 0
    invalid_phase_timings = 0
    missing_tool_latency = 0
    phase_samples: Dict[str, List[int]] = {}
    tool_latency_samples: List[int] = []
    tool_latency_by_name: Dict[str, List[int]] = {}
    client_transport_overhead: List[int] = []
    token_totals = {
        "prompt_tokens": 0,
        "cache_read_input_tokens": 0,
        "uncached_prompt_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }
    for response in responses:
        elapsed_value = response.get("_probe_elapsed_ms")
        if isinstance(elapsed_value, (int, float)) and elapsed_value > 0:
            latencies.append(int(elapsed_value))
        else:
            missing_latency += 1
        if _int_or_zero(response.get("_probe_http_status")) != 200:
            http_errors += 1
        if str(response.get("status") or "") != "success":
            runtime_errors += 1
        debug = response.get("debug") or {}
        runtime_phases = debug.get("runtime_phase_timings_ms")
        if not isinstance(runtime_phases, Mapping) or not runtime_phases:
            missing_phase_timings += 1
            runtime_phases = {}
        else:
            for phase_name, duration in runtime_phases.items():
                if (
                    not isinstance(phase_name, str)
                    or type(duration) not in (int, float)
                    or duration < 0
                ):
                    invalid_phase_timings += 1
                    continue
                phase_samples.setdefault(phase_name, []).append(int(duration))
            handler_total = runtime_phases.get("handler_total")
            if type(handler_total) not in (int, float) or handler_total < 0:
                invalid_phase_timings += 1
            elif isinstance(elapsed_value, (int, float)) and elapsed_value > 0:
                client_transport_overhead.append(
                    max(int(elapsed_value - handler_total), 0)
                )
        spans = (debug.get("turn_trace") or {}).get("component_spans") or []
        response_model_calls = sum(
            max(1, _int_or_zero(span.get("provider_call_count")))
            for span in spans
            if isinstance(span, Mapping)
            and (
                span.get("component_type") == "model_call"
                or (
                    span.get("component_type") == "state_extraction"
                    and span.get("model_used") is True
                )
            )
        )
        for call in debug.get("tool_calls") or []:
            if not isinstance(call, Mapping):
                continue
            tool_calls += 1
            name = str(call.get("name") or "")
            if name in MUTATING_TOOLS:
                mutating_tools += 1
            if canonical_text(call.get("status")) in TOOL_ERROR_STATUSES:
                tool_errors += 1
            tool_latency = call.get("latency_ms")
            if type(tool_latency) in (int, float) and tool_latency >= 0:
                duration = int(tool_latency)
                tool_latency_samples.append(duration)
                tool_latency_by_name.setdefault(name or "unknown", []).append(duration)
            else:
                missing_tool_latency += 1
        usage = debug.get("llm_usage_summary")
        usage_expectation = str(response.get("_probe_model_usage_expectation") or "")
        usage_required = usage_expectation == "required" or (
            usage_expectation == "required_if_model_called" and response_model_calls > 0
        )
        usage_was_mapping = isinstance(usage, Mapping)
        if not usage_was_mapping:
            usage = {}
        reported_model_calls = _int_or_zero(usage.get("llm_call_count"))
        model_calls += reported_model_calls or response_model_calls
        required_usage_fields = tuple(token_totals)
        if usage_required:
            if not usage_was_mapping:
                missing_usage += 1
                continue
            missing_fields = [key for key in required_usage_fields if key not in usage]
            if missing_fields:
                missing_usage += 1
            elif any(
                type(usage.get(key)) is not int or usage.get(key) < 0
                for key in required_usage_fields
            ):
                invalid_usage += 1
            elif usage.get("total_tokens", 0) < (
                usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
            ):
                invalid_usage += 1
            elif usage.get("uncached_prompt_tokens") != max(
                usage.get("prompt_tokens", 0) - usage.get("cache_read_input_tokens", 0),
                0,
            ):
                invalid_usage += 1
            elif _int_or_zero(usage.get("missing_usage_call_count")) > 0:
                missing_usage += 1
            elif _int_or_zero(usage.get("unmetered_retry_count")) > 0:
                missing_usage += 1
            elif (
                "llm_call_count" in usage
                and reported_model_calls < response_model_calls
            ):
                invalid_usage += 1
        for key in token_totals:
            token_totals[key] += _int_or_zero(usage.get(key))
    return {
        "status": "pass"
        if not (
            http_errors
            or runtime_errors
            or tool_errors
            or mutating_tools
            or missing_phase_timings
            or invalid_phase_timings
            or missing_tool_latency
        )
        else "fail",
        "response_count": len(responses),
        "http_error_count": http_errors,
        "runtime_error_count": runtime_errors,
        "tool_call_count": tool_calls,
        "tool_error_count": tool_errors,
        "tool_error_rate": round(tool_errors / tool_calls, 4) if tool_calls else 0.0,
        "mutating_tool_count": mutating_tools,
        "model_call_count": model_calls,
        "missing_latency_count": missing_latency,
        "missing_usage_count": missing_usage,
        "invalid_usage_count": invalid_usage,
        "missing_phase_timing_count": missing_phase_timings,
        "invalid_phase_timing_count": invalid_phase_timings,
        "missing_tool_latency_count": missing_tool_latency,
        "telemetry_completeness_percent": round(
            100.0
            * (
                max(
                    3 * len(responses)
                    - missing_latency
                    - missing_usage
                    - invalid_usage
                    - missing_phase_timings
                    - invalid_phase_timings,
                    0,
                )
            )
            / (3 * len(responses)),
            2,
        )
        if responses
        else 0.0,
        "latency_ms": {
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "max": max(latencies) if latencies else None,
        },
        "runtime_phase_latency_ms": {
            name: _latency_summary(values)
            for name, values in sorted(phase_samples.items())
        },
        "client_transport_overhead_ms": _latency_summary(client_transport_overhead),
        "tool_latency_ms": {
            "all_calls": _latency_summary(tool_latency_samples),
            "by_tool": {
                name: _latency_summary(values)
                for name, values in sorted(tool_latency_by_name.items())
            },
        },
        "tokens": token_totals,
        "estimated_cost": {
            "status": "not_available",
            "reason": "deployed tester telemetry does not expose priced per-model call records",
        },
    }


def _structural_cs_proxy(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Apply deterministic proxies mapped to the established seven-part rubric."""

    checks: List[Dict[str, Any]] = []
    for row in rows:
        case_id = str(row.get("case_id") or "")
        response_rows = list(_all_responses([row]))
        visible = [_visible_text(response) for response in response_rows]
        has_visible = bool(visible and all(visible))
        no_mojibake = all(
            marker not in text for text in visible for marker in ("\ufffd", "â€", "ðŸ")
        )
        bounded_questions = all(text.count("?") <= 1 for text in visible)
        bounded_bubbles = all(
            len((response.get("response") or {})) <= 6 for response in response_rows
        )
        no_duplicates = all(
            len(turn_bubbles) == len(set(turn_bubbles))
            for turn_bubbles in (
                [
                    canonical_text(value)
                    for value in (response.get("response") or {}).values()
                    if str(value or "").strip()
                ]
                for response in response_rows
            )
        )
        mechanical = not bool(row.get("failures"))
        mapped = {
            "understands_customer": has_visible and mechanical,
            "natural_language": has_visible and no_mojibake,
            "directness": has_visible and bounded_questions and bounded_bubbles,
            "grounding": mechanical,
            "progression": has_visible and mechanical,
            "presentation": has_visible and no_duplicates and bounded_bubbles,
            "consistency": mechanical and no_duplicates,
        }
        checks.extend(
            {
                "case_id": case_id,
                "dimension": dimension,
                "check": "preverified_structural_contract",
                "passed": passed,
            }
            for dimension, passed in mapped.items()
        )
    passed = sum(bool(item["passed"]) for item in checks)
    score = round(100.0 * passed / len(checks), 2) if checks else 0.0
    return {
        "status": "pass" if checks and passed == len(checks) else "concern",
        "score_percent": score,
        "passed_checks": passed,
        "total_checks": len(checks),
        "concerns": [item for item in checks if not item["passed"]],
        "by_dimension": {
            dimension: {
                "passed": sum(
                    bool(item["passed"])
                    for item in checks
                    if item.get("dimension") == dimension
                ),
                "total": sum(
                    1 for item in checks if item.get("dimension") == dimension
                ),
            }
            for dimension in CS_DIMENSIONS
        },
        "interpretation_limit": (
            "These are deterministic proxies over pre-verified scenarios, not "
            "fresh subjective review of every generated sentence."
        ),
    }


def _scenario_contract_status(artifact: Mapping[str, Any]) -> Dict[str, Any]:
    """Fail closed unless the exact pre-verified tier corpus was executed."""

    profile = artifact.get("evaluation_profile") or {}
    contract = artifact.get("scenario_contract") or {}
    tier = str(profile.get("tier") or "")
    required = REQUIRED_SCENARIOS_BY_TIER.get(tier)
    failures: List[str] = []
    if artifact.get("schema_version") != "runtime_v7_release_candidate_artifact_v1":
        failures.append("release_candidate_artifact_schema_mismatch")
    if not required:
        failures.append(f"scenario_contract_unknown_tier:{tier or 'missing'}")
        required = {"cases": (), "journeys": ()}
    failures.extend(health_policy_failures(profile))
    if contract.get("schema_version") != SCENARIO_CONTRACT_SCHEMA_VERSION:
        failures.append("scenario_contract_schema_mismatch")
    if contract.get("contract_version") != SCENARIO_CONTRACT_VERSION:
        failures.append("scenario_contract_version_mismatch")
    approved_digest = APPROVED_SCENARIO_DEFINITION_DIGESTS.get(tier)
    if not approved_digest or contract.get("definition_digest") != approved_digest:
        failures.append("scenario_contract_definition_digest_mismatch")
    observed_case_list = [
        str(row.get("case_id") or "")
        for row in artifact.get("single_turn_cases") or []
        if isinstance(row, Mapping)
    ]
    observed_journey_list = [
        str(row.get("case_id") or "")
        for row in artifact.get("journeys") or []
        if isinstance(row, Mapping)
    ]
    observed_cases = sorted(observed_case_list)
    observed_journeys = sorted(observed_journey_list)
    raw_cases = artifact.get("single_turn_cases")
    raw_journeys = artifact.get("journeys")
    if not isinstance(raw_cases, list) or len(raw_cases) != len(observed_case_list):
        failures.append("scenario_contract_malformed_case_rows")
    if not isinstance(raw_journeys, list) or len(raw_journeys) != len(
        observed_journey_list
    ):
        failures.append("scenario_contract_malformed_journey_rows")
    required_cases = sorted(str(value) for value in required["cases"])
    required_journeys = sorted(str(value) for value in required["journeys"])
    if observed_cases != required_cases:
        failures.append("scenario_contract_case_set_incomplete")
    if observed_journeys != required_journeys:
        failures.append("scenario_contract_journey_set_incomplete")
    if sorted(contract.get("required_case_ids") or []) != required_cases:
        failures.append("scenario_contract_required_case_manifest_mismatch")
    if sorted(contract.get("required_journey_ids") or []) != required_journeys:
        failures.append("scenario_contract_required_journey_manifest_mismatch")
    if len(observed_case_list) != len(set(observed_case_list)):
        failures.append("scenario_contract_duplicate_case_id")
    if len(observed_journey_list) != len(set(observed_journey_list)):
        failures.append("scenario_contract_duplicate_journey_id")
    if sorted(profile.get("selected_case_ids") or []) != observed_cases:
        failures.append("scenario_contract_profile_case_set_mismatch")
    if sorted(profile.get("selected_journey_ids") or []) != observed_journeys:
        failures.append("scenario_contract_profile_journey_set_mismatch")
    for row in _all_rows(artifact):
        case_id = str(row.get("case_id") or "missing")
        row_failures = list(row.get("failures") or [])
        if not isinstance(row.get("passed"), bool):
            failures.append(f"scenario_row_passed_not_boolean:{case_id}")
        elif row["passed"] != (not row_failures):
            failures.append(f"scenario_row_result_inconsistent:{case_id}")
        if case_id in observed_case_list and not isinstance(
            row.get("response"), Mapping
        ):
            failures.append(f"scenario_response_missing:{case_id}")
        if case_id in observed_journey_list:
            raw_steps = row.get("steps")
            valid_steps = [
                step for step in raw_steps or [] if isinstance(step, Mapping)
            ]
            if not isinstance(raw_steps, list) or len(raw_steps) != len(valid_steps):
                failures.append(f"scenario_journey_steps_malformed:{case_id}")
            actions = tuple(str(step.get("action") or "") for step in valid_steps)
            if actions not in ALLOWED_JOURNEY_ACTIONS.get(case_id, ()):
                failures.append(f"scenario_journey_actions_invalid:{case_id}")
            if any(
                not isinstance(step.get("response"), Mapping) for step in valid_steps
            ):
                failures.append(f"scenario_journey_response_missing:{case_id}")
    return {
        "status": "pass" if not failures else "fail",
        "contract_version": contract.get("contract_version"),
        "definition_digest": contract.get("definition_digest"),
        "tier": tier,
        "required_case_count": len(required_cases),
        "required_journey_count": len(required_journeys),
        "failures": failures,
    }


def _operational_funnel_status(artifact: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate the data-derived size+brand progression contract and its stages."""

    profile = artifact.get("evaluation_profile") or {}
    contract = artifact.get("operational_funnel_contract") or {}
    tier = str(profile.get("tier") or "")
    required_ids = tuple(REQUIRED_OPERATIONAL_FUNNEL_SCENARIOS_BY_TIER.get(tier, ()))
    rows = list(_operational_funnel_rows(artifact))
    responses = list(_all_responses(rows))
    raw_rows = artifact.get("operational_funnel_scenarios")
    failures: List[str] = []
    concerns: List[str] = []
    stage_counts: Dict[str, Dict[str, int]] = {}

    if tier not in REQUIRED_OPERATIONAL_FUNNEL_SCENARIOS_BY_TIER:
        failures.append(f"operational_funnel_unknown_tier:{tier or 'missing'}")
    if not required_ids:
        if rows:
            failures.append("operational_funnel_unexpected_rows")
        return {
            "status": "fail" if failures else "not_applicable",
            "score_percent": None,
            "contract_version": contract.get("contract_version"),
            "definition_digest": contract.get("definition_digest"),
            "tier": tier,
            "required_scenario_count": 0,
            "scenario_count": len(rows),
            "synthetic_scenario_dropoff_count": 0,
            "by_stage": {},
            "technical": _technical_health(responses) if responses else {},
            "failures": failures,
            "concerns": concerns,
            "downstream_observational_metrics": {
                "production_abandonment": {
                    "status": "not_measured_in_synthetic_evaluator"
                },
                "linked_booking_conversion_7d": {
                    "status": "not_measured_in_synthetic_evaluator"
                },
                "linked_booking_conversion_14d": {
                    "status": "not_measured_in_synthetic_evaluator"
                },
            },
        }

    if contract.get("schema_version") != OPERATIONAL_FUNNEL_CONTRACT_SCHEMA_VERSION:
        failures.append("operational_funnel_contract_schema_mismatch")
    if contract.get("contract_version") != OPERATIONAL_FUNNEL_CONTRACT_VERSION:
        failures.append("operational_funnel_contract_version_mismatch")
    approved_digest = APPROVED_OPERATIONAL_FUNNEL_DEFINITION_DIGESTS.get(tier)
    if not approved_digest or contract.get("definition_digest") != approved_digest:
        failures.append("operational_funnel_definition_digest_mismatch")

    observed_ids = [str(row.get("case_id") or "") for row in rows]
    if not isinstance(raw_rows, list) or len(raw_rows) != len(rows):
        failures.append("operational_funnel_malformed_rows")
    if sorted(observed_ids) != sorted(required_ids):
        failures.append("operational_funnel_scenario_set_incomplete")
    if len(observed_ids) != len(set(observed_ids)):
        failures.append("operational_funnel_duplicate_scenario_id")
    if sorted(contract.get("required_scenario_ids") or []) != sorted(required_ids):
        failures.append("operational_funnel_required_manifest_mismatch")
    if sorted(profile.get("selected_operational_funnel_ids") or []) != sorted(
        observed_ids
    ):
        failures.append("operational_funnel_profile_scenario_set_mismatch")

    for row in rows:
        case_id = str(row.get("case_id") or "missing")
        row_failures = list(row.get("failures") or [])
        if not isinstance(row.get("passed"), bool):
            failures.append(f"operational_funnel_row_passed_not_boolean:{case_id}")
        elif row["passed"] != (not row_failures):
            failures.append(f"operational_funnel_row_result_inconsistent:{case_id}")
        if row.get("passed") is not True:
            failures.append(f"operational_funnel_scenario_failed:{case_id}")
        raw_steps = row.get("steps")
        valid_steps = [step for step in raw_steps or [] if isinstance(step, Mapping)]
        if not isinstance(raw_steps, list) or len(raw_steps) != len(valid_steps):
            failures.append(f"operational_funnel_steps_malformed:{case_id}")
        actions = tuple(str(step.get("action") or "") for step in valid_steps)
        if actions not in ALLOWED_OPERATIONAL_FUNNEL_ACTIONS.get(case_id, ()):
            failures.append(f"operational_funnel_actions_invalid:{case_id}")
        if any(not isinstance(step.get("response"), Mapping) for step in valid_steps):
            failures.append(f"operational_funnel_response_missing:{case_id}")

        raw_stages = row.get("funnel_stages")
        stages = raw_stages if isinstance(raw_stages, Mapping) else {}
        if not isinstance(raw_stages, Mapping):
            failures.append(f"operational_funnel_stages_missing:{case_id}")
        required_stages = REQUIRED_OPERATIONAL_FUNNEL_STAGES.get(case_id)
        if required_stages is None:
            failures.append(f"operational_funnel_unknown_scenario:{case_id}")
            required_stages = ()
        for stage_name in required_stages:
            stage = stages.get(stage_name)
            if not isinstance(stage, Mapping):
                failures.append(
                    f"operational_funnel_required_stage_missing:{case_id}:{stage_name}"
                )
                continue
            if stage.get("applicable") is not True:
                failures.append(
                    f"operational_funnel_required_stage_not_applicable:{case_id}:{stage_name}"
                )
            if not isinstance(stage.get("passed"), bool):
                failures.append(
                    f"operational_funnel_stage_passed_not_boolean:{case_id}:{stage_name}"
                )
            elif stage.get("passed") is not True:
                failures.append(
                    f"operational_funnel_stage_failed:{case_id}:{stage_name}"
                )
            evidence = stage.get("evidence")
            if not isinstance(evidence, Mapping) or not evidence:
                failures.append(
                    f"operational_funnel_stage_evidence_missing:{case_id}:{stage_name}"
                )
        for stage_name, stage in stages.items():
            if not isinstance(stage, Mapping) or stage.get("applicable") is not True:
                continue
            bucket = stage_counts.setdefault(
                str(stage_name), {"passed": 0, "failed": 0, "total": 0}
            )
            bucket["total"] += 1
            bucket["passed" if stage.get("passed") is True else "failed"] += 1

    technical = _technical_health(responses)
    technical_count_fields = {
        "http_error_count": "http_errors",
        "runtime_error_count": "runtime_errors",
        "tool_error_count": "tool_errors",
        "mutating_tool_count": "mutating_tools",
        "missing_latency_count": "missing_latency",
        "missing_usage_count": "missing_model_usage",
        "invalid_usage_count": "invalid_model_usage",
        "missing_phase_timing_count": "missing_runtime_phase_timing",
        "invalid_phase_timing_count": "invalid_runtime_phase_timing",
        "missing_tool_latency_count": "missing_tool_latency",
    }
    for field, code in technical_count_fields.items():
        count = _int_or_zero(technical.get(field))
        if count:
            failures.append(f"operational_funnel_{code}:{count}")
    failures.extend(
        f"operational_funnel_{failure}"
        for failure in _telemetry_contract_failures(rows)
    )
    identity = _target_identity_status(artifact, responses)
    failures.extend(f"operational_funnel_{failure}" for failure in identity["failures"])
    p95_latency = (technical.get("latency_ms") or {}).get("p95")
    if (
        p95_latency is not None
        and p95_latency > DEFAULT_HEALTH_POLICY["latency_p95_fail_ms"]
    ):
        failures.append(f"operational_funnel_p95_latency_ms:{p95_latency}")
    elif (
        p95_latency is not None
        and p95_latency > DEFAULT_HEALTH_POLICY["latency_p95_concern_ms"]
    ):
        concerns.append(f"operational_funnel_p95_latency_ms:{p95_latency}")

    for bucket in stage_counts.values():
        bucket["score_percent"] = round(100.0 * bucket["passed"] / bucket["total"], 2)
    passed_stage_count = sum(item["passed"] for item in stage_counts.values())
    total_stage_count = sum(item["total"] for item in stage_counts.values())
    score = (
        round(100.0 * passed_stage_count / total_stage_count, 2)
        if total_stage_count
        else 0.0
    )
    return {
        "status": "pass" if not failures else "fail",
        "score_percent": score,
        "contract_version": contract.get("contract_version"),
        "definition_digest": contract.get("definition_digest"),
        "tier": tier,
        "required_scenario_count": len(required_ids),
        "scenario_count": len(rows),
        "synthetic_scenario_dropoff_count": sum(
            1 for row in rows if not bool(row.get("passed"))
        ),
        "by_stage": dict(sorted(stage_counts.items())),
        "technical": technical,
        "target_identity": identity,
        "failures": failures,
        "concerns": concerns,
        "scenario_evidence": [
            {
                "case_id": row.get("case_id"),
                "passed": row.get("passed"),
                "failures": list(row.get("failures") or []),
                "funnel_stages": dict(row.get("funnel_stages") or {}),
            }
            for row in rows
        ],
        "downstream_observational_metrics": {
            "production_abandonment": {"status": "not_measured_in_synthetic_evaluator"},
            "linked_booking_conversion_7d": {
                "status": "not_measured_in_synthetic_evaluator"
            },
            "linked_booking_conversion_14d": {
                "status": "not_measured_in_synthetic_evaluator"
            },
        },
    }


def _artifact_integrity_status(artifact: Mapping[str, Any]) -> Dict[str, Any]:
    """Detect accidental or post-run changes to stored evaluation evidence."""

    integrity = artifact.get("artifact_integrity") or {}
    expected = str(integrity.get("evidence_digest") or "")
    actual = artifact_evidence_digest(artifact)
    failures: List[str] = []
    if integrity.get("algorithm") != "sha256":
        failures.append("artifact_integrity_algorithm_missing")
    if integrity.get("scope") != (
        "artifact_without_promotion_health_or_artifact_integrity"
    ):
        failures.append("artifact_integrity_scope_mismatch")
    if not expected:
        failures.append("artifact_integrity_digest_missing")
    elif expected != actual:
        failures.append("artifact_integrity_digest_mismatch")
    return {
        "status": "pass" if not failures else "fail",
        "algorithm": integrity.get("algorithm"),
        "evidence_digest": expected,
        "computed_digest": actual,
        "failures": failures,
    }


def _target_identity_status(
    artifact: Mapping[str, Any], responses: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    """Require every deployed response to identify the exact intended target."""

    profile = artifact.get("evaluation_profile") or {}
    expectations = {
        "release_version": str(profile.get("expected_release") or "").strip(),
        "git_sha": str(profile.get("expected_git_sha") or "").strip(),
        "service_environment": str(profile.get("expected_environment") or "").strip(),
    }
    failures: List[str] = []
    for key, expected in expectations.items():
        if not expected:
            failures.append(f"target_identity_expectation_missing:{key}")
            continue
        mismatches = sum(
            1 for response in responses if str(response.get(key) or "") != expected
        )
        if mismatches:
            failures.append(f"target_identity_mismatch:{key}:{mismatches}")
    return {
        "status": "pass" if not failures else "fail",
        "expected": expectations,
        "response_count": len(responses),
        "failures": failures,
    }


def _telemetry_contract_failures(
    rows: Sequence[Mapping[str, Any]],
) -> List[str]:
    """Require telemetry policy from scenario position, not artifact opt-out."""

    failures: List[str] = []
    positioned: List[tuple[str, str, Mapping[str, Any]]] = []
    for row in rows:
        case_id = str(row.get("case_id") or "missing")
        response = row.get("response")
        if isinstance(response, Mapping):
            positioned.append((case_id, "chat", response))
        for step in row.get("steps") or []:
            if isinstance(step, Mapping) and isinstance(step.get("response"), Mapping):
                positioned.append(
                    (case_id, str(step.get("action") or "missing"), step["response"])
                )
    for case_id, action, response in positioned:
        if response.get("_probe_model_usage_expectation") != "required":
            failures.append(f"telemetry_policy_missing:{case_id}:{action}")
            continue
        usage = (response.get("debug") or {}).get("llm_usage_summary")
        spans = ((response.get("debug") or {}).get("turn_trace") or {}).get(
            "component_spans"
        ) or []
        has_model_call = any(
            isinstance(span, Mapping) and span.get("component_type") == "model_call"
            for span in spans
        )
        total_tokens = (
            _int_or_zero(usage.get("total_tokens")) if isinstance(usage, Mapping) else 0
        )
        if total_tokens > 0 and not has_model_call:
            failures.append(f"model_usage_without_call_evidence:{case_id}:{action}")
        if has_model_call and total_tokens <= 0:
            failures.append(f"model_call_without_usage:{case_id}:{action}")
        if action == "chat" and isinstance(usage, Mapping):
            if total_tokens <= 0:
                failures.append(f"chat_token_usage_not_positive:{case_id}")
            if not has_model_call:
                failures.append(f"chat_model_call_evidence_missing:{case_id}")
    return failures


def _compare_baseline(
    artifact: Mapping[str, Any], baseline: Optional[Mapping[str, Any]]
) -> Dict[str, Any]:
    if not baseline:
        return {"status": "not_provided", "deltas": {}}
    baseline_integrity = _artifact_integrity_status(baseline)
    if baseline_integrity["status"] != "pass":
        return {
            "status": "inconclusive",
            "reason": "baseline_integrity_failed",
            "mismatched_fields": ["artifact_integrity"],
            "deltas": {},
        }
    current_profile = artifact.get("evaluation_profile") or {}
    baseline_profile = baseline.get("evaluation_profile") or {}
    current_contract = artifact.get("scenario_contract") or {}
    baseline_contract = baseline.get("scenario_contract") or {}
    contract_bridge = _approved_baseline_contract_bridge(
        current_contract,
        baseline_contract,
    )
    current_ids = [str(row.get("case_id") or "") for row in _all_rows(artifact)]
    baseline_ids = [str(row.get("case_id") or "") for row in _all_rows(baseline)]
    mismatch = []
    for key in (
        "schema_version",
        "tier",
        "workers",
        "timeout_s",
        "feature_expectations",
        "health_policy",
    ):
        if current_profile.get(key) != baseline_profile.get(key):
            mismatch.append(key)
    if sorted(current_ids) != sorted(baseline_ids):
        mismatch.append("selected_case_ids")
    for key in (
        "schema_version",
        "contract_version",
        "definition_digest",
        "required_case_ids",
        "required_journey_ids",
    ):
        if current_contract.get(key) != baseline_contract.get(key):
            if contract_bridge and key in {"contract_version", "definition_digest"}:
                continue
            mismatch.append(f"scenario_contract.{key}")
    if mismatch:
        return {
            "status": "inconclusive",
            "reason": "baseline_profile_mismatch",
            "mismatched_fields": mismatch,
            "deltas": {},
        }
    current_rows = list(_all_rows(artifact))
    baseline_rows = list(_all_rows(baseline))
    current_score = _mechanical_score(current_rows)
    baseline_score = _mechanical_score(baseline_rows)
    current_technical = _technical_health(list(_all_responses(current_rows)))
    baseline_technical = _technical_health(list(_all_responses(baseline_rows)))
    current_tokens = current_technical["tokens"]
    baseline_tokens = baseline_technical["tokens"]
    aggregate_total_token_delta = (
        current_tokens["total_tokens"] - baseline_tokens["total_tokens"]
    )
    aggregate_total_token_percent = (
        round(
            100.0 * aggregate_total_token_delta / baseline_tokens["total_tokens"],
            2,
        )
        if baseline_tokens["total_tokens"]
        else None
    )
    context_differences = [
        key
        for key in ("base_url", "expected_environment")
        if current_profile.get(key) != baseline_profile.get(key)
    ]
    current_entries = _response_entries(current_rows)
    baseline_entries = _response_entries(baseline_rows)
    current_by_key = {entry["key"]: entry for entry in current_entries}
    baseline_by_key = {entry["key"]: entry for entry in baseline_entries}
    matched_current: List[Mapping[str, Any]] = []
    matched_baseline: List[Mapping[str, Any]] = []
    excluded_keys: List[str] = []
    per_case_responses: Dict[str, Dict[str, List[Mapping[str, Any]]]] = {}
    for key in sorted(set(current_by_key) & set(baseline_by_key)):
        current_entry = current_by_key[key]
        baseline_entry = baseline_by_key[key]
        current_response = current_entry["response"]
        baseline_response = baseline_entry["response"]
        if not (
            _response_usage_is_comparable(current_response)
            and _response_usage_is_comparable(baseline_response)
        ):
            excluded_keys.append(key)
            continue
        matched_current.append(current_response)
        matched_baseline.append(baseline_response)
        case_bucket = per_case_responses.setdefault(
            current_entry["case_id"], {"current": [], "baseline": []}
        )
        case_bucket["current"].append(current_response)
        case_bucket["baseline"].append(baseline_response)

    baseline_response_count = len(baseline_entries)
    matched_action_count = len(matched_current)
    coverage_percent = (
        round(100.0 * matched_action_count / baseline_response_count, 2)
        if baseline_response_count
        else 0.0
    )
    matched_current_health = _technical_health(matched_current)
    matched_baseline_health = _technical_health(matched_baseline)
    matched_current_tokens = matched_current_health["tokens"]
    matched_baseline_tokens = matched_baseline_health["tokens"]
    total_token_delta = (
        matched_current_tokens["total_tokens"] - matched_baseline_tokens["total_tokens"]
    )
    total_token_percent = (
        round(
            100.0 * total_token_delta / matched_baseline_tokens["total_tokens"],
            2,
        )
        if matched_baseline_tokens["total_tokens"]
        else None
    )
    comparison_status = "compatible"
    comparison_reason = None
    if not baseline_response_count or not matched_action_count:
        comparison_status = "inconclusive"
        comparison_reason = "baseline_action_usage_unavailable"
    elif coverage_percent < MIN_BASELINE_ACTION_COVERAGE_PERCENT:
        comparison_status = "inconclusive"
        comparison_reason = "baseline_action_coverage_below_minimum"

    per_case = {}
    for case_id, response_sets in sorted(per_case_responses.items()):
        current_case_health = _technical_health(response_sets["current"])
        baseline_case_health = _technical_health(response_sets["baseline"])
        per_case[case_id] = {
            "matched_action_count": len(response_sets["current"]),
            "total_tokens": (
                current_case_health["tokens"]["total_tokens"]
                - baseline_case_health["tokens"]["total_tokens"]
            ),
            "p95_latency_ms": _subtract_optional(
                current_case_health["latency_ms"]["p95"],
                baseline_case_health["latency_ms"]["p95"],
            ),
        }
    return {
        "status": comparison_status,
        **({"reason": comparison_reason} if comparison_reason else {}),
        **(
            {"contract_compatibility_bridge": contract_bridge}
            if contract_bridge
            else {}
        ),
        "context_differences": context_differences,
        "comparison_scope": {
            "grain": "case_action_occurrence",
            "minimum_baseline_coverage_percent": (MIN_BASELINE_ACTION_COVERAGE_PERCENT),
            "baseline_action_count": baseline_response_count,
            "candidate_action_count": len(current_entries),
            "matched_action_count": matched_action_count,
            "matched_baseline_coverage_percent": coverage_percent,
            "candidate_only_actions": sorted(
                set(current_by_key) - set(baseline_by_key)
            ),
            "baseline_only_actions": sorted(set(baseline_by_key) - set(current_by_key)),
            "usage_excluded_actions": excluded_keys,
        },
        "deltas": {
            "mechanical_score_percent": round(current_score - baseline_score, 2),
            "p95_latency_ms": _subtract_optional(
                matched_current_health["latency_ms"]["p95"],
                matched_baseline_health["latency_ms"]["p95"],
            ),
            "prompt_tokens": matched_current_tokens["prompt_tokens"]
            - matched_baseline_tokens["prompt_tokens"],
            "uncached_prompt_tokens": matched_current_tokens["uncached_prompt_tokens"]
            - matched_baseline_tokens["uncached_prompt_tokens"],
            "completion_tokens": matched_current_tokens["completion_tokens"]
            - matched_baseline_tokens["completion_tokens"],
            "total_tokens": total_token_delta,
            "total_tokens_percent": total_token_percent,
            "per_case": per_case,
        },
        "aggregate_observed_deltas": {
            "interpretation": (
                "Includes unmatched actions and missing-usage failures; report for "
                "workload cost visibility, not per-action efficiency gating."
            ),
            "candidate_response_count": current_technical["response_count"],
            "baseline_response_count": baseline_technical["response_count"],
            "total_tokens": aggregate_total_token_delta,
            "total_tokens_percent": aggregate_total_token_percent,
        },
    }


def _approved_baseline_contract_bridge(
    current_contract: Mapping[str, Any],
    baseline_contract: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return an explicit exact-digest bridge for cost comparison only."""

    current_identity = (
        str(current_contract.get("contract_version") or ""),
        str(current_contract.get("definition_digest") or ""),
    )
    baseline_identity = (
        str(baseline_contract.get("contract_version") or ""),
        str(baseline_contract.get("definition_digest") or ""),
    )
    if baseline_identity not in APPROVED_BASELINE_CONTRACT_BRIDGES.get(
        current_identity,
        frozenset(),
    ):
        return {}
    return {
        "status": "applied",
        "scope": "cost_and_latency_comparison_only",
        "from_contract_version": baseline_identity[0],
        "from_definition_digest": baseline_identity[1],
        "to_contract_version": current_identity[0],
        "to_definition_digest": current_identity[1],
    }


def _response_entries(
    rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Index responses at stable scenario/action/occurrence grain."""

    entries: List[Dict[str, Any]] = []
    for row in rows:
        case_id = str(row.get("case_id") or "")
        occurrences: Dict[str, int] = {}
        response_items: List[tuple[str, Mapping[str, Any]]] = []
        response = row.get("response")
        if isinstance(response, Mapping):
            response_items.append(("chat", response))
        for step in row.get("steps") or []:
            if not isinstance(step, Mapping) or not isinstance(
                step.get("response"), Mapping
            ):
                continue
            response_items.append(
                (str(step.get("action") or "unknown"), step["response"])
            )
        for action, item_response in response_items:
            occurrence = occurrences.get(action, 0) + 1
            occurrences[action] = occurrence
            entries.append(
                {
                    "key": f"{case_id}|{action}|{occurrence}",
                    "case_id": case_id,
                    "action": action,
                    "occurrence": occurrence,
                    "response": item_response,
                }
            )
    return entries


def _response_usage_is_comparable(response: Mapping[str, Any]) -> bool:
    health = _technical_health([response])
    return not (health["missing_usage_count"] or health["invalid_usage_count"])


def _mechanical_score(rows: Sequence[Mapping[str, Any]]) -> float:
    if not rows:
        return 0.0
    return round(100.0 * sum(bool(row.get("passed")) for row in rows) / len(rows), 2)


def _subtract_optional(actual: Any, baseline: Any) -> Optional[int]:
    if actual is None or baseline is None:
        return None
    return _int_or_zero(actual) - _int_or_zero(baseline)


def _visible_text(response: Mapping[str, Any]) -> str:
    response_map = response.get("response") or {}
    return "\n".join(
        str(value).strip()
        for _, value in sorted(response_map.items())
        if str(value or "").strip()
    )


def _percentile(values: Sequence[int], percentile: int) -> Optional[int]:
    if not values:
        return None
    ordered = sorted(values)
    index = max(
        0, min(len(ordered) - 1, math.ceil(percentile / 100 * len(ordered)) - 1)
    )
    return int(ordered[index])


def _latency_summary(values: Sequence[int]) -> Dict[str, Optional[int]]:
    return {
        "count": len(values),
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "max": max(values) if values else None,
    }


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
