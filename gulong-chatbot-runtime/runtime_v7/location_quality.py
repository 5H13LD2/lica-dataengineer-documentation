"""Location quality guards shared by Runtime V7 service and lead paths."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


_SERVICE_LOCATION_ONLY_TOKENS = {
    "appoint",
    "appointment",
    "availability",
    "available",
    "balance",
    "balancing",
    "branch",
    "branches",
    "check",
    "delivery",
    "deliver",
    "free",
    "install",
    "installation",
    "kabit",
    "location",
    "mount",
    "mounting",
    "nearby",
    "nearest",
    "partner",
    "partners",
    "pito",
    "schedule",
    "service",
    "services",
    "slot",
    "slots",
    "valve",
    "valves",
    "weight",
    "weights",
    "wheel",
}

_REJECTED_EXACT_SERVICE_LOCATIONS = {
    "availability",
    "delivery",
    "free delivery",
    "free install",
    "free installation",
    "free installation partner",
    "free mounting",
    "free mounting balancing",
    "install",
    "installation",
    "installation availability",
    "installation partner",
    "mounting",
    "mounting balancing",
    "partner",
    "service",
    "service availability",
    "valves",
    "wheel balancing",
}


def is_rejected_service_location(value: Any) -> bool:
    """Return True when a supposed location is only a service/business phrase."""

    text = _normalize_location_quality_text(value)
    if not text:
        return False
    if text in _REJECTED_EXACT_SERVICE_LOCATIONS:
        return True
    tokens = set(text.split())
    if not tokens:
        return False
    return tokens.issubset(_SERVICE_LOCATION_ONLY_TOKENS) and any(
        token in tokens
        for token in {
            "availability",
            "delivery",
            "install",
            "installation",
            "mounting",
            "partner",
            "service",
            "valves",
            "wheel",
        }
    )


def usable_lead_location(value: Any) -> str:
    """Return a lead-safe location value, or empty string when it should not count."""

    cleaned = re.sub(r"\s+", " ", str(value or "").strip())
    if not cleaned or is_rejected_service_location(cleaned):
        return ""
    return cleaned


def _normalize_location_quality_text(value: Any) -> str:
    folded = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", folded.lower())).strip()


__all__ = ["is_rejected_service_location", "usable_lead_location"]
