"""Fulfillment vocabulary normalization for Runtime V7.

This resolver maps business-domain aliases such as "shipping" or courier names
to fulfillment context. It does not approve actions or mutate responses.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


DELIVERY_ALIAS_PATTERNS = [
    r"\bdeliver(?:y|ing)?\b",
    r"\b(?:be|get|have)\s+(?:it|this|these|the\s+(?:tire|tires|order))?\s*delivered\b",
    r"\bdelivered\s+(?:to|at)\b",
    r"\bship(?:ping|ped)?\b",
    r"\bpadala\b",
    r"\bcourier\b",
    r"\bdoor[- ]?to[- ]?door\b",
    r"\blbc\b",
    r"\bj\s*&\s*t\b",
    r"\bjnt\b",
    r"\bj and t\b",
]


def resolve_fulfillment_alias(text: Any) -> Optional[Dict[str, Any]]:
    """Return advisory fulfillment context detected from customer wording."""

    raw = str(text or "").strip()
    if not raw:
        return None
    lowered = raw.lower()
    matched = _matched_patterns(lowered, DELIVERY_ALIAS_PATTERNS)
    if matched:
        return {
            "service_type": "delivery",
            "matched_aliases": matched,
            "source": "fulfillment_alias_resolver",
            "safe_for_action": False,
        }
    return None


def fulfillment_alias_candidates(text: Any) -> List[Dict[str, Any]]:
    """Return model-compatible advisory signal candidates."""

    resolved = resolve_fulfillment_alias(text)
    if not resolved:
        return []
    return [
        {
            "key": "service_type",
            "value": resolved["service_type"],
            "source": "latest_user_message",
            "confidence": "high",
            "status_hint": "fulfillment_alias",
            "evidence": ", ".join(resolved.get("matched_aliases") or [])[:80],
            "origin": "fulfillment_alias_resolver",
            "metadata": {"fulfillment_alias": resolved},
        }
    ]


def enrich_text_for_delivery_faq(text: Any) -> str:
    """Append delivery wording for FAQ routing when only an alias was used."""

    raw = str(text or "")
    resolved = resolve_fulfillment_alias(raw)
    if not resolved or "delivery" in raw.lower():
        return raw
    return f"{raw} delivery"


def _matched_patterns(text: str, patterns: List[str]) -> List[str]:
    matched: List[str] = []
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            matched.append(pattern)
    return matched


__all__ = [
    "enrich_text_for_delivery_faq",
    "fulfillment_alias_candidates",
    "resolve_fulfillment_alias",
]
