"""Evidence contract for customer-visible commercial claims.

The model owns conversational wording. This module only checks whether each
validated payment-policy result is represented in the same response segment as
its method, brand, and outcome. It never decides customer intent or eligibility.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Sequence

from runtime_v7.order_canonicalization import normalize_payment_option


def payment_policies_from_tool_results(
    tool_results: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return deduplicated checkout-backed payment claims."""

    policies: List[Dict[str, Any]] = []
    for item in tool_results or []:
        if not isinstance(item, dict) or item.get("name") != "answer_order_faq":
            continue
        for result_key in ("full_result", "result"):
            result = (
                item.get(result_key)
                if isinstance(item.get(result_key), dict)
                else {}
            )
            policy = (
                result.get("payment_policy")
                if isinstance(result.get("payment_policy"), dict)
                else {}
            )
            if policy:
                policies.append(dict(policy))
                break
    return dedupe_payment_policies(policies)


def dedupe_payment_policies(
    policies: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Collapse equivalent lookups to one authoritative payment-row claim."""

    scoped_payment_types = {
        payment_type
        for policy in policies
        if (payment_type := payment_policy_identity(policy)[0])
        and payment_policy_identity(policy)[1]
        and payment_claim(policy)
    }
    output: List[Dict[str, Any]] = []
    index_by_identity: Dict[tuple[str, str], int] = {}
    for policy in policies:
        identity = payment_policy_identity(policy)
        if identity[0] in scoped_payment_types and not identity[1]:
            # A model may first query the general row before Runtime validates
            # the customer's explicit brand scope. Drop it only when the
            # scoped result carries an authoritative claim; a conflicting or
            # otherwise unclaimable scoped proposal cannot erase a valid
            # unsupported-method fact.
            continue
        if not any(identity):
            output.append(dict(policy))
            continue
        index = index_by_identity.get(identity)
        if index is None:
            index_by_identity[identity] = len(output)
            output.append(dict(policy))
            continue
        existing = output[index]
        candidate_priority = (
            bool(payment_claim(policy)),
            _policy_specificity(policy),
        )
        existing_priority = (
            bool(payment_claim(existing)),
            _policy_specificity(existing),
        )
        if candidate_priority > existing_priority:
            output[index] = dict(policy)
    return output


def payment_policy_identity(policy: Dict[str, Any]) -> tuple[str, str]:
    """Return payment-row and brand identity for idempotent composition."""

    payment_type = str(
        policy.get("requested_payment_type_id")
        or policy.get("requested_payment_method")
        or (
            f"category:{policy.get('requested_payment_category')}:"
            f"{policy.get('payment_option') or ''}"
            if policy.get("requested_payment_category")
            else ""
        )
        or ""
    ).strip().casefold()
    brand = str(
        policy.get("requested_product_brand") or ""
    ).strip().casefold()
    return payment_type, brand


def payment_claim_contract_violations(
    model_text: str,
    tool_results: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return missing or contradicted validated payment claims."""

    response_text = _structured_response_text(model_text)
    policies = payment_policies_from_tool_results(tool_results)
    claims = [
        claim
        for policy in policies
        if (claim := payment_claim(policy))
    ]
    scoped_brands = {
        str(claim.get("brand") or "").strip().casefold()
        for claim in claims
        if str(claim.get("brand") or "").strip()
    }
    shared_brand = next(iter(scoped_brands)) if len(scoped_brands) == 1 else ""
    scoped_payment_options = {
        normalize_payment_option(claim.get("payment_option"))
        for claim in claims
        if normalize_payment_option(claim.get("payment_option"))
    }
    violations: List[Dict[str, Any]] = []
    for claim in claims:
        if _response_has_claim(
            response_text,
            claim,
            shared_brand=shared_brand,
        ):
            continue
        violations.append(
            {
                "type": "commercial_payment_claim_missing_or_contradicted",
                "claim": claim,
                "instruction": (
                    "State this validated fact once in natural customer-facing "
                    "Filipino/Taglish. Do not expose internal policy, resolver, "
                    "allowlist, or checkout-metadata wording."
                ),
            }
        )
    if len(scoped_payment_options) == 1:
        shared_payment_option = next(iter(scoped_payment_options))
        if not _response_has_payment_option_scope(
            response_text,
            shared_payment_option,
        ):
            violations.append(
                {
                    "type": "commercial_payment_scope_missing",
                    "payment_option": shared_payment_option,
                    "instruction": (
                        "Keep this validated Pay Now or Pay Later qualifier "
                        "visible once in the natural customer-facing answer. "
                        "It scopes the related methods and must not be omitted "
                        "or repeated as one policy row per method."
                    ),
                }
            )
    restrictive_claims = [
        claim
        for claim in claims
        if claim.get("outcome") in {"unsupported", "not_eligible"}
    ]
    for claim in claims:
        if claim.get("outcome") != "eligible":
            continue
        positive_method_tokens = set(
            _meaningful_method_tokens(claim.get("method"))
        )
        for segment in _response_segments(response_text):
            if not _segment_has_claim(
                segment,
                _claim_with_shared_brand_scope(
                    claim,
                    shared_brand=shared_brand,
                    response_text=response_text,
                ),
            ):
                continue
            for restrictive in restrictive_claims:
                forbidden = [
                    token
                    for token in _meaningful_method_tokens(
                        restrictive.get("method")
                    )
                    if token not in positive_method_tokens
                ]
                leaked = [
                    token
                    for token in forbidden
                    if re.search(rf"\b{re.escape(token)}\b", segment)
                ]
                if not leaked:
                    continue
                violations.append(
                    {
                        "type": "commercial_payment_claim_cross_association",
                        "claim": claim,
                        "conflicting_claim": restrictive,
                        "leaked_method_anchors": leaked,
                        "instruction": (
                            "Do not associate the validated positive payment "
                            "claim with a bank or provider that belongs to a "
                            "separate restrictive claim. Use only the exact "
                            "validated positive method, term, brand, and "
                            "payment-option scope."
                        ),
                    }
                )
                break
    return violations


def ungrounded_payment_assertion_violations(
    model_text: str,
    tool_results: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Reject affirmative payment promises that have no authoritative result.

    This is a commercial-claim safety check, not an intent classifier.  It is
    deliberately limited to customer-visible affirmative wording and does not
    decide which tool or conversational step should run.
    """

    response_text = _structured_response_text(model_text)
    if not _contains_affirmative_payment_assertion(response_text):
        return []
    if payment_policies_from_tool_results(tool_results):
        return []
    if _has_structured_payment_evidence(tool_results):
        return []
    return [
        {
            "type": "commercial_payment_claim_without_evidence",
            "instruction": (
                "Do not promise a payment method, reservation route, term, or "
                "installment arrangement until an authoritative payment or "
                "checkout result grounds it. You may acknowledge the customer's "
                "preference and offer to verify it."
            ),
        }
    ]


def _contains_affirmative_payment_assertion(value: str) -> bool:
    normalized = " ".join(str(value or "").casefold().split())
    patterns = (
        r"\b(?:can|may)\s+(?:reserve|pay)\b",
        r"\b(?:reserve|pay)\s+(?:with|via|using)\b",
        r"\bpay\s+the\s+(?:remaining\s+)?balance\b",
        r"\b(?:pwede|maaari)\b.{0,64}\b(?:gcash|installment|payment|bayad|reserve)\b",
        r"\b\d+\s*(?:months?|mos?)\s+(?:0%\s*)?installment\b",
        r"\b0%\s*(?:interest|installment)\b",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)


def _has_structured_payment_evidence(
    tool_results: Sequence[Dict[str, Any]],
) -> bool:
    evidence_keys = {
        "installment_options",
        "installment_terms",
        "payment_methods",
        "payment_options",
        "payment_options_preview",
        "payment_policy",
        "reservation_payment_methods",
        "balance_payment_methods",
    }

    def contains_evidence(value: Any) -> bool:
        """Recursively detect non-error structured payment authority."""

        if isinstance(value, dict):
            if str(value.get("status") or "").strip().casefold() == "error":
                return False
            if any(key in value and value.get(key) for key in evidence_keys):
                return True
            return any(contains_evidence(item) for item in value.values())
        if isinstance(value, list):
            return any(contains_evidence(item) for item in value)
        return False

    for item in tool_results or []:
        if not isinstance(item, dict):
            continue
        result = item.get("full_result") or item.get("result") or {}
        if contains_evidence(result):
            return True
    return False


def _response_has_payment_option_scope(
    response_text: str,
    payment_option: str,
) -> bool:
    """Return whether a shared checkout timing scope is visible in prose."""

    normalized_option = normalize_payment_option(payment_option)
    normalized_response = " ".join(
        re.sub(r"[^a-z0-9]+", " ", str(response_text or "").casefold()).split()
    )
    if normalized_option == "Pay Later / Pay After Service":
        return bool(
            re.search(
                r"\bpay\s+(?:later|after\s+service)\b",
                normalized_response,
            )
        )
    if normalized_option == "Pay Now":
        return bool(re.search(r"\bpay\s+now\b", normalized_response))
    return True


def _claim_with_shared_brand_scope(
    claim: Dict[str, Any],
    *,
    shared_brand: str,
    response_text: str,
) -> Dict[str, Any]:
    """Relax only a globally established single-brand discourse scope."""

    claim_brand = str(claim.get("brand") or "").strip().casefold()
    if not claim_brand or claim_brand != shared_brand:
        return claim
    normalized_response = " ".join(
        re.sub(r"[^a-z0-9]+", " ", response_text.casefold()).split()
    )
    if not re.search(
        rf"\b{re.escape(claim_brand)}\b",
        normalized_response,
    ):
        return claim
    scoped = dict(claim)
    scoped["brand"] = ""
    return scoped


def payment_claim(policy: Dict[str, Any]) -> Dict[str, Any]:
    """Build a compact factual claim from one validated payment row."""

    status = str(policy.get("requested_payment_status") or "").strip()
    requested_method = str(
        policy.get("requested_payment_name")
        or policy.get("requested_payment_method")
        or ""
    ).strip()
    if status == "unsupported" and normalize_payment_option(requested_method):
        # Pay Now / Pay Later are timing choices, not payment methods. A
        # malformed model lookup must not create a false unsupported-method
        # claim in a compound answer.
        return {}
    eligibility = str(
        policy.get("requested_brand_eligibility") or ""
    ).strip()
    if status == "unsupported":
        outcome = "unsupported"
    elif eligibility == "not_eligible":
        outcome = "not_eligible"
    elif eligibility in {"eligible", "not_brand_restricted"}:
        outcome = "eligible"
    else:
        return {}
    return {
        "outcome": outcome,
        "method": requested_method,
        "requested_method": str(
            policy.get("requested_payment_method") or ""
        ).strip(),
        "brand": (
            ""
            if outcome == "unsupported"
            else str(policy.get("requested_product_brand") or "").strip()
        ),
        "payment_option": (
            ""
            if outcome == "unsupported"
            else str(policy.get("payment_option") or "").strip()
        ),
        "source": str(policy.get("source") or "").strip(),
        "source_updated_at": policy.get(
            "requested_payment_type_updated_at"
        ),
    }


def _policy_specificity(policy: Dict[str, Any]) -> tuple[int, int]:
    method = str(
        policy.get("requested_payment_name")
        or policy.get("requested_payment_method")
        or ""
    ).strip()
    return (
        len(re.findall(r"[a-z0-9]+", method.casefold())),
        len(method),
    )


def _structured_response_text(model_text: str) -> str:
    raw = str(model_text or "").strip()
    if not raw.startswith("{"):
        return raw
    try:
        payload = json.loads(raw)
    except Exception:
        return raw
    texts = []
    for unit in payload.get("response_units") or []:
        if not isinstance(unit, dict) or unit.get("type") != "text":
            continue
        content = (
            unit.get("content")
            if isinstance(unit.get("content"), dict)
            else {}
        )
        text = str(content.get("text") or "").strip()
        if text:
            texts.append(text)
    return "\n".join(texts)


def _response_has_claim(
    response_text: str,
    claim: Dict[str, Any],
    *,
    shared_brand: str = "",
) -> bool:
    if any(
        _segment_has_claim(segment, claim)
        for segment in _response_segments(response_text)
    ):
        return True
    claim_brand = str(claim.get("brand") or "").strip().casefold()
    if not claim_brand or claim_brand != shared_brand:
        return False
    normalized_response = " ".join(
        re.sub(r"[^a-z0-9]+", " ", response_text.casefold()).split()
    )
    if not re.search(
        rf"\b{re.escape(claim_brand)}\b",
        normalized_response,
    ):
        return False
    shared_scope_claim = dict(claim)
    shared_scope_claim["brand"] = ""
    return any(
        _segment_has_claim(segment, shared_scope_claim)
        for segment in _response_segments(response_text)
    )


def _response_segments(response_text: str) -> List[str]:
    return [
        " ".join(re.sub(r"[^a-z0-9]+", " ", segment).split())
        for segment in re.split(
            r"(?:[.!?;\n]+|\bbut\b|\bhowever\b|\bpero\b|\bsubalit\b)",
            str(response_text or "").casefold(),
        )
        if segment.strip()
    ]


def _segment_has_claim(segment: str, claim: Dict[str, Any]) -> bool:
    anchors = [
        token
        for token in re.findall(
            r"[a-z0-9]+",
            " ".join(
                [
                    str(claim.get("method") or ""),
                    str(claim.get("brand") or ""),
                ]
            ).casefold(),
        )
        if token not in {
            "payment",
            "method",
            "credit",
            "card",
            "interest",
            "zero",
            "0",
            "months",
            "month",
            "mos",
            "installment",
        }
    ]
    anchors = list(dict.fromkeys(anchors))
    requested_method_matches = _segment_has_requested_method(
        segment,
        claim.get("requested_method"),
    )
    if not anchors and not requested_method_matches:
        return False
    outcome = str(claim.get("outcome") or "")
    positive = (
        r"\beligible\b",
        r"\bavailable\b",
        r"\bsupported\b",
        r"\bpuwede\b",
        r"\bpwede\b",
    )
    negative = (
        r"\bnot(?:\s+currently)?\s+(?:eligible|available|supported)\b",
        r"\bnot(?:\s+\w+){0,3}\s+(?:included|applicable|offered)\b",
        r"\bnot\s+an?\s+option\b",
        r"\bunsupported\b",
        r"\bunavailable\b",
        (
            r"\b(?:hindi|di)(?:\s+\w+){0,3}\s+"
            r"(?:eligible|available|supported|kasama|applicable|offered|"
            r"puwede|pwede)\b"
        ),
        r"\b(?:doesn\s+t|does\s+not)\s+apply\b",
        r"\bwal(?:a|ang)\b",
    )
    patterns = positive if outcome == "eligible" else negative
    return (
        (
            requested_method_matches
            or all(
                re.search(rf"\b{re.escape(anchor)}\b", segment)
                for anchor in anchors
            )
        )
        and any(re.search(pattern, segment) for pattern in patterns)
        and (
            outcome != "eligible"
            or not any(
                re.search(pattern, segment) for pattern in negative
            )
        )
    )


def _segment_has_requested_method(segment: str, value: Any) -> bool:
    """Accept the customer's natural label for one validated payment row.

    Checkout metadata can name a combined implementation row such as
    ``Straight Credit Card / Debit Card`` even when the customer asked simply
    about a credit card.  The commercial authority remains that exact row, but
    the response contract should not force its internal display label into
    otherwise natural customer-facing prose.
    """

    requested = " ".join(
        re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split()
    )
    if not requested or normalize_payment_option(requested):
        return False
    if requested in {"credit card", "straight credit card"}:
        return bool(re.search(r"\bcredit\s+card\b", segment))
    if requested in {"debit card", "straight debit card"}:
        return bool(re.search(r"\bdebit\s+card\b", segment))
    requested_pattern = re.escape(requested).replace(r"\ ", r"\s+")
    return bool(re.search(rf"\b{requested_pattern}\b", segment))


def _meaningful_method_tokens(value: Any) -> List[str]:
    """Return provider/bank anchors that cannot leak across payment claims."""

    return [
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if token.isalpha()
        and token
        not in {
            "payment",
            "method",
            "credit",
            "card",
            "interest",
            "zero",
            "months",
            "month",
            "mos",
            "installment",
            "option",
        }
    ]
