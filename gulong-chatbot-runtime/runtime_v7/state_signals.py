"""Public orchestrator for Runtime V7 advisory commercial state signals.

`build_commercial_state_context` keeps the public API stable while delegating to
smaller modules:
- `state_signal_model` owns lightweight model extraction.
- `state_signal_fallback` owns structured observation projection and diagnostics.
- `state_signal_normalization` owns canonicalization, validation, signal shaping,
  and missing-info projection.

Active Working Memory remains the primary narrative context. Background signals
are advisory until guarded order/payment/reservation/schedule actions.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from runtime_v7.canonical_values import CanonicalValuesProvider
from runtime_v7.location_resolution import RuntimeV7LocationResolver
from runtime_v7.state_signal_fallback import (
    _build_extraction_diagnostics,
    _previous_signal_candidates,
    _structured_context_candidates,
)
from runtime_v7.state_signal_model import (
    BACKGROUND_SIGNAL_EXTRACTOR_SYSTEM_PROMPT,
    BackgroundSignalExtractionModelClient,
    RuntimeV7BackgroundSignalModelClient,
    _extract_model_candidates,
    _is_valid_candidate_payload,
    _normalize_model_extraction_policy,
    build_background_signal_extraction_prompt,
)
from runtime_v7.llm_gateway import RuntimeV7ProviderCallLimitExceeded
from runtime_v7.state_signal_normalization import (
    _build_missing_info,
    _clean,
    _construct_background_signals,
    _normalize_candidates_with_failures,
    _turns_text,
)
from runtime_v7.state_signal_schema import (
    BackgroundSignal,
    signal_is_advisory_context,
)


class BackgroundSignalExtractionError(RuntimeError):
    """Compatibility error type for legacy signal-extraction callers."""


def build_commercial_state_context(
    *,
    current_user_message: str,
    active_working_memory: str = "",
    recent_turns: Optional[Sequence[Dict[str, str]]] = None,
    previous_background_signals: Optional[Sequence[Dict[str, Any]]] = None,
    latest_product_observation: Optional[Dict[str, Any]] = None,
    latest_service_observation: Optional[Dict[str, Any]] = None,
    external_evidence_refs: Optional[Sequence[Dict[str, Any]]] = None,
    external_evidence_candidates: Optional[Sequence[Dict[str, Any]]] = None,
    model_client: Optional[BackgroundSignalExtractionModelClient] = None,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
    location_resolver: Optional[RuntimeV7LocationResolver] = None,
    model_extraction_policy: str = "auto",
    model_retry_attempts: int = 2,
) -> Dict[str, Any]:
    """Build advisory background signals and order-readiness checks.

    Raw customer-message extraction is model-owned except for one bounded
    prompted-field completion: a short, canonically resolvable location answer
    immediately after an assistant location question. Deterministic code also
    projects structured tool observations and normalizes/canonicalizes model
    candidates. If the model extractor is called and transport/runtime failures
    exhaust `model_retry_attempts`, the extractor degrades to structured context
    plus that bounded completion. It does not use general raw-text heuristics for
    commercial meaning.
    """

    latest_text = _clean(current_user_message)
    memory_text = _clean(active_working_memory)
    recent_text = _turns_text(recent_turns or [])
    latest_observation = latest_product_observation or {}
    latest_service = latest_service_observation or {}
    external_candidates = [dict(candidate) for candidate in (external_evidence_candidates or []) if isinstance(candidate, dict)]
    previous_signal_candidates = _previous_signal_candidates(previous_background_signals or [])
    structured_context_candidates = [
        *previous_signal_candidates,
        *external_candidates,
        *_structured_context_candidates(latest_observation, latest_service),
    ]
    prompted_location_candidates = _prompted_location_completion_candidates(
        latest_text=latest_text,
        recent_turns=recent_turns or [],
        canonical_values_provider=canonical_values_provider,
        location_resolver=location_resolver,
    )
    structured_context_candidates.extend(prompted_location_candidates)
    structured_normalized, structured_failures = _normalize_candidates_with_failures(
        structured_context_candidates,
        canonical_values_provider=canonical_values_provider,
        location_resolver=location_resolver,
    )
    extraction_diagnostics = _build_extraction_diagnostics(
        latest_text=latest_text,
        memory_text=memory_text,
        recent_text=recent_text,
        latest_product_observation=latest_observation,
        deterministic_candidates=structured_context_candidates,
        normalized_candidates=structured_normalized,
        normalization_failures=structured_failures,
    )

    policy = _normalize_model_extraction_policy(model_extraction_policy)
    model_candidates: List[Dict[str, Any]] = []
    model_normalized: List[Dict[str, Any]] = []
    retry_attempts = max(0, int(model_retry_attempts or 0))
    should_call_model = model_client is not None and policy != "never"
    extraction_meta: Dict[str, Any] = {
        "mode": "model_primary" if should_call_model else "model_unavailable_or_disabled",
        "model_used": False,
        "model_available": model_client is not None,
        "model_policy": policy,
        "raw_message_extraction": "disabled",
        "retry_attempts_allowed": retry_attempts,
        "external_evidence_ref_count": len(external_evidence_refs or []),
        "external_evidence_candidate_count": len(external_candidates),
        "previous_background_signal_count": len(previous_background_signals or []),
        "previous_signal_candidate_count": len(previous_signal_candidates),
        "prompted_location_completion_count": len(prompted_location_candidates),
        "diagnostics": extraction_diagnostics,
    }

    if model_client is not None and policy == "never":
        extraction_meta["model_skipped_reason"] = "policy_never"

    if should_call_model:
        prompt = build_background_signal_extraction_prompt(
            current_user_message=latest_text,
            active_working_memory=memory_text,
            recent_turns=recent_turns or [],
            latest_product_observation=latest_observation,
            latest_service_observation=latest_service,
            external_evidence_refs=external_evidence_refs or [],
            previous_background_signals=previous_background_signals or [],
            canonical_values_provider=canonical_values_provider,
            extraction_diagnostics=extraction_diagnostics,
        )
        extraction_meta.update(
            {
                "model_used": True,
                "system_prompt": BACKGROUND_SIGNAL_EXTRACTOR_SYSTEM_PROMPT,
                "user_prompt": prompt,
            }
        )
        (
            response,
            attempt_errors,
            model_candidates,
            model_normalized,
            model_failures,
        ) = _call_signal_model_with_retries(
            model_client,
            system_prompt=BACKGROUND_SIGNAL_EXTRACTOR_SYSTEM_PROMPT,
            user_prompt=prompt,
            retry_attempts=retry_attempts,
            canonical_values_provider=canonical_values_provider,
            location_resolver=location_resolver,
        )
        attempt_usage = _aggregate_model_attempt_usage(
            (response or {}).get("_attempt_usage_records") or [],
            fallback_response=response or {},
        )
        model_attempts = (response or {}).get("_attempt_count")
        extraction_meta["model_attempts"] = int(model_attempts or (len(attempt_errors) + 1))
        extraction_meta["model_metered_attempts"] = attempt_usage["metered_attempts"]
        extraction_meta["model_unmetered_attempts"] = max(
            extraction_meta["model_attempts"]
            - extraction_meta["model_metered_attempts"],
            0,
        )
        if attempt_errors:
            extraction_meta["model_retry_errors"] = attempt_errors
        if (response or {}).get("_degraded_reason"):
            extraction_meta["status"] = "degraded"
            extraction_meta["model_degraded_reason"] = str((response or {}).get("_degraded_reason") or "")
            extraction_meta["model_extraction_failed"] = True
        else:
            extraction_meta["status"] = "ok"
        extraction_meta.update(
            {
                "model_output_content": str((response or {}).get("content") or ""),
                "model_usage": attempt_usage["usage"],
                "model_cache_usage": attempt_usage["cache_usage"],
                "model_request_cache": dict((response or {}).get("request_cache") or {}),
                "model_latency_ms": attempt_usage["latency_ms"],
                "model": str((response or {}).get("model") or ""),
                "model_candidate_count": len(model_candidates),
                "model_normalized_candidate_count": len(model_normalized),
                "model_normalization_failures": model_failures,
            }
        )
        if model_candidates and not model_normalized and model_failures:
            extraction_meta["model_degraded_reason"] = "all_model_candidates_failed_normalization"

    model_candidate_count_before_authority_filter = len(model_candidates)
    model_candidates = [
        candidate
        for candidate in model_candidates
        if signal_is_advisory_context(candidate)
    ]
    extraction_meta["model_candidates_rejected_as_narrative"] = (
        model_candidate_count_before_authority_filter - len(model_candidates)
    )

    structured_candidates_for_merge = list(structured_context_candidates)

    signal_candidates = list(structured_candidates_for_merge)
    if extraction_meta.get("model_used"):
        signal_candidates = [*model_candidates, *structured_candidates_for_merge]
        extraction_meta["candidate_source"] = (
            "model_primary_with_structured_context"
            if model_normalized
            else "model_primary_empty_with_structured_context"
        )
    elif policy == "never":
        extraction_meta["candidate_source"] = "structured_context_only_policy_never"
    else:
        extraction_meta["candidate_source"] = "structured_context_only_no_model"

    signals = _construct_background_signals(
        candidates=signal_candidates,
        latest_product_observation=latest_observation,
        canonical_values_provider=canonical_values_provider,
        location_resolver=location_resolver,
    )
    signal_map = {signal.key: signal for signal in signals}
    missing_info = _build_missing_info(signal_map, latest_product_observation=latest_observation)
    return {
        "background_signals": [signal.to_dict() for signal in signals],
        "missing_info": missing_info,
        "background_signal_extraction": extraction_meta,
    }


def _prompted_location_completion_candidates(
    *,
    latest_text: str,
    recent_turns: Sequence[Dict[str, str]],
    canonical_values_provider: Optional[CanonicalValuesProvider],
    location_resolver: Optional[RuntimeV7LocationResolver],
) -> List[Dict[str, Any]]:
    """Recover one short canonical location only after a direct location ask."""

    assistant_text = next(
        (
            _clean(turn.get("content"))
            for turn in reversed(recent_turns)
            if str(turn.get("role") or "").strip().casefold() == "assistant"
            and _clean(turn.get("content"))
        ),
        "",
    )
    if not _assistant_requested_customer_location(assistant_text):
        return []
    if re.search(
        r"\b(?:hindi|di\s+pa|not\s+sure|unknown|wala|none|near\s+me|"
        r"store|branch|head\s+office|address)\b",
        latest_text,
        flags=re.IGNORECASE,
    ):
        return []
    candidate_text = re.sub(
        r"^(?:sa|taga)\s+|\s+(?:po|opo|lang|please|pls|ako)$",
        "",
        latest_text.strip(),
        flags=re.IGNORECASE,
    ).strip(" .,!")
    candidate_text = re.sub(
        r"\s+(?:po|opo|lang|please|pls)$",
        "",
        candidate_text,
        flags=re.IGNORECASE,
    ).strip(" .,!")
    if not candidate_text or len(candidate_text.split()) > 6 or "?" in latest_text:
        return []
    candidate = {
        "key": "location",
        "value": candidate_text,
        "source": "latest_user_message",
        "confidence": "high",
        "relation": "asserted",
        "confirmation_state": "confirmed",
        "origin": "deterministic",
        "evidence": latest_text[:160],
        "metadata": {"completion_mode": "prompted_canonical_location"},
    }
    normalized, _failures = _normalize_candidates_with_failures(
        [candidate],
        canonical_values_provider=canonical_values_provider,
        location_resolver=location_resolver,
    )
    if not normalized:
        return []
    normalization = (normalized[0].get("metadata") or {}).get("normalization") or {}
    resolution = normalization.get("location_resolution") or {}
    if normalization.get("status") == "location_ambiguous" or resolution.get(
        "ambiguity_status"
    ):
        return []
    return [candidate]


def _assistant_requested_customer_location(text: str) -> bool:
    """Recognize a direct customer city/area request, not a business-location fact."""

    patterns = (
        r"\b(?:saan(?:g)?|ano(?:ng)?|which|what)\b.{0,70}"
        r"\b(?:city|area|location|lugar|banda)\b",
        r"\b(?:city|area|location|lugar|banda)\b.{0,70}"
        r"\b(?:ninyo|nyo|mo|kayo|located)\b",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _call_signal_model_with_retries(
    model_client: BackgroundSignalExtractionModelClient,
    *,
    system_prompt: str,
    user_prompt: str,
    retry_attempts: int,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
    location_resolver: Optional[RuntimeV7LocationResolver] = None,
) -> Tuple[Dict[str, Any], List[str], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Call the extractor, retrying transport/runtime, JSON, and unusable values."""

    errors: List[str] = []
    last_response: Dict[str, Any] = {}
    attempt_usage_records: List[Dict[str, Any]] = []
    total_attempts = max(1, 1 + int(retry_attempts or 0))
    for attempt in range(1, total_attempts + 1):
        try:
            attempt_user_prompt = (
                user_prompt
                if attempt == 1
                else _background_signal_retry_prompt(user_prompt, errors[-1] if errors else "")
            )
            response = model_client.extract_background_signals(
                system_prompt=system_prompt,
                user_prompt=attempt_user_prompt,
                metadata={
                    "component": "runtime_v7_background_signal_extractor",
                    "attempt": attempt,
                    "max_attempts": total_attempts,
                },
            )
            last_response = dict(response or {})
            attempt_usage_records.append(
                _model_attempt_usage_record(response or {}, attempt=attempt)
            )
            if _is_valid_candidate_payload(response):
                candidates = _extract_model_candidates(response)
                normalized, failures = _normalize_candidates_with_failures(
                    candidates,
                    canonical_values_provider=canonical_values_provider,
                    location_resolver=location_resolver,
                )
                if _is_semantically_usable_model_payload(candidates, normalized):
                    return (
                        _with_model_attempt_usage(
                            response or {},
                            attempt_usage_records,
                        ),
                        errors,
                        candidates,
                        normalized,
                        failures,
                    )
                error = (
                    "attempt_"
                    f"{attempt}:UnusableModelCandidates: "
                    f"candidate_count={len(candidates)}; "
                    f"normalized_candidate_count={len(normalized)}; "
                    f"failures={_candidate_failure_preview(failures)}"
                )
                if attempt < total_attempts:
                    errors.append(error)
                    continue
                return (
                    _with_model_attempt_usage(
                        response or {},
                        attempt_usage_records,
                    ),
                    errors,
                    candidates,
                    normalized,
                    failures,
                )
            finish_reason = str((response or {}).get("finish_reason") or "").strip() or "unknown"
            content_preview = str((response or {}).get("content") or "")[:240]
            errors.append(
                f"attempt_{attempt}:InvalidModelOutput: finish_reason={finish_reason}; "
                f"content_preview={content_preview!r}"
            )
        except RuntimeV7ProviderCallLimitExceeded:
            # A tester ceiling is intentionally terminal so the endpoint can
            # report its bounded diagnostic instead of silently degrading.
            raise
        except Exception as exc:
            attempt_usage_records.append(
                {
                    "attempt": attempt,
                    "status": "exception_without_usage",
                    "usage": {},
                    "cache_usage": {},
                    "latency_ms": None,
                }
            )
            errors.append(f"attempt_{attempt}:{exc.__class__.__name__}: {exc}")
    degraded_response = dict(last_response)
    degraded_response.setdefault("content", "")
    degraded_response.setdefault("usage", {})
    degraded_response.setdefault("cache_usage", {})
    degraded_response.setdefault("request_cache", {})
    degraded_response.setdefault("latency_ms", None)
    degraded_response.setdefault("finish_reason", "background_signal_extractor_unavailable")
    degraded_response["_attempt_count"] = total_attempts
    degraded_response["_degraded_reason"] = "model_extraction_failed_after_retries"
    return (
        _with_model_attempt_usage(degraded_response, attempt_usage_records),
        errors,
        [],
        [],
        [],
    )


def _model_attempt_usage_record(
    response: Dict[str, Any],
    *,
    attempt: int,
) -> Dict[str, Any]:
    """Retain content-free usage metadata for one extractor response."""

    return {
        "attempt": int(attempt),
        "status": "returned",
        "usage": dict(response.get("usage") or {}),
        "cache_usage": dict(response.get("cache_usage") or {}),
        "latency_ms": response.get("latency_ms"),
    }


def _with_model_attempt_usage(
    response: Dict[str, Any],
    records: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Attach bounded per-attempt usage without retaining discarded content."""

    payload = dict(response or {})
    payload["_attempt_count"] = len(records)
    payload["_attempt_usage_records"] = [dict(record) for record in records]
    return payload


def _aggregate_model_attempt_usage(
    records: Sequence[Dict[str, Any]],
    *,
    fallback_response: Dict[str, Any],
) -> Dict[str, Any]:
    """Sum extractor usage across returned attempts and expose missing attempts."""

    normalized = [dict(record) for record in records if isinstance(record, dict)]
    if not normalized:
        normalized = [
            {
                "status": "returned",
                "usage": dict(fallback_response.get("usage") or {}),
                "cache_usage": dict(fallback_response.get("cache_usage") or {}),
                "latency_ms": fallback_response.get("latency_ms"),
            }
        ]
    usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    cache_usage = {
        "cache_read_input_tokens": 0,
        "reasoning_tokens": 0,
    }
    latency_ms = 0
    latency_present = False
    metered_attempts = 0
    for record in normalized:
        attempt_usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
        attempt_cache = (
            record.get("cache_usage")
            if isinstance(record.get("cache_usage"), dict)
            else {}
        )
        for key in usage:
            usage[key] += _usage_int(attempt_usage.get(key))
        prompt_details = (
            attempt_usage.get("prompt_tokens_details")
            if isinstance(attempt_usage.get("prompt_tokens_details"), dict)
            else {}
        )
        completion_details = (
            attempt_usage.get("completion_tokens_details")
            if isinstance(attempt_usage.get("completion_tokens_details"), dict)
            else {}
        )
        cached = (
            attempt_cache.get("cache_read_input_tokens")
            or attempt_usage.get("cache_read_input_tokens")
            or prompt_details.get("cached_tokens")
        )
        reasoning = (
            attempt_cache.get("reasoning_tokens")
            or attempt_usage.get("reasoning_tokens")
            or completion_details.get("reasoning_tokens")
        )
        cache_usage["cache_read_input_tokens"] += _usage_int(cached)
        cache_usage["reasoning_tokens"] += _usage_int(reasoning)
        if _usage_int(attempt_usage.get("total_tokens")) > 0:
            metered_attempts += 1
        attempt_latency = record.get("latency_ms")
        if attempt_latency is not None:
            latency_ms += _usage_int(attempt_latency)
            latency_present = True
    return {
        "usage": usage,
        "cache_usage": cache_usage,
        "latency_ms": latency_ms if latency_present else None,
        "metered_attempts": metered_attempts,
    }


def _usage_int(value: Any) -> int:
    """Return a non-negative integer for provider usage aggregation."""

    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _background_signal_retry_prompt(user_prompt: str, last_error: str) -> str:
    """Return a stricter retry prompt after invalid extractor output."""

    return "\n".join(
        [
            str(user_prompt or "").strip(),
            "",
            "Retry correction:",
            "Your previous output was invalid or unusable for the BackgroundSignalExtractionResponseModel.",
            f"Last validation issue: {str(last_error or '')[:300]}",
            'Return only valid JSON in this exact shape: {"candidates":[{"key":"...","value":"...","source":"latest_user_message","confidence":"high","relation":"asserted","status_hint":"","evidence":"..."}]}',
            "Do not include metadata, markdown, comments, trailing prose, or nested objects.",
            'If there is no safe concrete candidate, return {"candidates":[]}.',
        ]
    )


def _is_semantically_usable_model_payload(candidates: Sequence[Dict[str, Any]], normalized: Sequence[Dict[str, Any]]) -> bool:
    """Accept empty extraction, but reject candidates that all fail normalization."""

    if not candidates:
        return True
    return bool(normalized)


def _candidate_failure_preview(failures: Sequence[Dict[str, Any]]) -> str:
    """Return a compact retry diagnostic for unusable candidate payloads."""

    if not failures:
        return "[]"
    preview = []
    for failure in failures[:3]:
        preview.append(
            {
                "key": failure.get("key"),
                "value": failure.get("value"),
                "reason": failure.get("reason"),
            }
        )
    return str(preview)


__all__ = [
    "BackgroundSignal",
    "BackgroundSignalExtractionError",
    "BackgroundSignalExtractionModelClient",
    "RuntimeV7BackgroundSignalModelClient",
    "build_background_signal_extraction_prompt",
    "build_commercial_state_context",
]
