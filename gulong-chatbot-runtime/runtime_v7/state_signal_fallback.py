"""Structured context projection and extraction diagnostics for Runtime V7.

Raw-message commercial fact extraction is model-owned. This module must not
derive slot/state candidates from customer prose; deterministic logic here is
limited to tool-grounded observation projection and non-candidate diagnostics.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from runtime_v7.state_signal_normalization import (
    _candidate,
)
from runtime_v7.state_signal_schema import signal_has_durable_authority


NON_CARRY_FORWARD_SIGNAL_KEYS = {
    "explicit_order_confirmation",
    "latest_product_presentation",
    "latest_service_presentation",
}


def _previous_signal_candidates(previous_background_signals: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert prior normalized signals into low-priority carry-forward candidates."""

    candidates: List[Dict[str, Any]] = []
    for signal in previous_background_signals or []:
        if not isinstance(signal, dict):
            continue
        if not signal_has_durable_authority(signal):
            continue
        key = str(signal.get("key") or "").strip()
        value = signal.get("value")
        if not key or key in NON_CARRY_FORWARD_SIGNAL_KEYS or value in (None, "", []):
            continue
        candidate = _candidate(
            key,
            value,
            source="signal_ledger",
            confidence=str(signal.get("confidence") or "medium"),
            status_hint=str(signal.get("status") or "remembered_context"),
            evidence="previous_background_signal",
        )
        candidate["relation"] = str(signal.get("relation") or "asserted")
        if isinstance(signal.get("metadata"), dict):
            candidate["metadata"] = dict(signal.get("metadata") or {})
        if isinstance(signal.get("resolution"), dict):
            candidate["resolution"] = dict(signal.get("resolution") or {})
        candidates.append(candidate)
    return candidates


def _structured_context_candidates(
    latest_product_observation: Dict[str, Any],
    latest_service_observation: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """Project tool-grounded context into signals without extracting from prose."""

    candidates: List[Dict[str, Any]] = []
    candidates.extend(_product_observation_candidates(latest_product_observation))
    candidates.extend(_service_observation_candidates(latest_service_observation or {}))
    return candidates


def _product_observation_candidates(latest_product_observation: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Project the latest product observation ref into signal candidates."""

    if not latest_product_observation:
        return []
    obs = latest_product_observation.get("observation_ref")
    pres = latest_product_observation.get("presentation_ref")
    refs = " / ".join(str(ref) for ref in [obs, pres] if ref)
    if not refs:
        return []
    return [
        _candidate(
            "latest_product_presentation",
            refs,
            source="product_observation_store",
            confidence="high",
            status_hint="tool_grounded",
        )
    ]


def _service_observation_candidates(latest_service_observation: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Project safe latest service-observation headers into signal candidates."""

    if not latest_service_observation:
        return []
    obs = latest_service_observation.get("observation_ref")
    pres = latest_service_observation.get("presentation_ref")
    refs = " / ".join(str(ref) for ref in [obs, pres] if ref)
    candidates: List[Dict[str, Any]] = []
    if refs:
        candidates.append(
            _candidate(
                "latest_service_presentation",
                refs,
                source="service_observation_store",
                confidence="high",
                status_hint="tool_grounded",
            )
        )

    query_basis = (
        latest_service_observation.get("query_basis")
        if isinstance(latest_service_observation.get("query_basis"), dict)
        else {}
    )
    location = (
        query_basis.get("customer_location_label")
        or query_basis.get("location")
        or query_basis.get("area")
    )
    if location:
        candidates.append(
            _candidate(
                "location",
                location,
                source="service_observation_store",
                confidence="medium",
                status_hint="tool_grounded",
                evidence="latest service observation location",
            )
        )
    service_type = query_basis.get("service_type")
    if service_type:
        candidates.append(
            _candidate(
                "service_type",
                service_type,
                source="service_observation_store",
                confidence="medium",
                status_hint="tool_grounded",
                evidence="latest service observation service_type",
            )
        )
    return candidates


def _build_extraction_diagnostics(
    *,
    latest_text: str,
    memory_text: str,
    recent_text: str,
    latest_product_observation: Dict[str, Any],
    deterministic_candidates: Sequence[Dict[str, Any]],
    normalized_candidates: Sequence[Dict[str, Any]],
    normalization_failures: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Summarize extraction setup without deriving facts from prose."""

    normalized_keys = sorted({str(candidate.get("key") or "") for candidate in normalized_candidates if candidate.get("key")})

    return {
        "raw_message_extraction": "disabled",
        "structured_candidate_count": len(deterministic_candidates),
        "structured_normalized_candidate_count": len(normalized_candidates),
        "structured_normalized_keys": normalized_keys,
        "structured_normalization_failures": list(normalization_failures),
        "trigger_reasons": [],
        "model_recommended": True,
        "latest_message_features": {
            "raw_message_feature_detection": "disabled",
            "latest_message_present": bool(latest_text),
            "active_working_memory_present": bool(memory_text),
            "recent_turns_present": bool(recent_text),
            "latest_product_observation_present": bool(latest_product_observation),
        },
        "latest_message_preview": latest_text[:240],
    }


