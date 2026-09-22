"""Shared canonical entity resolvers for Runtime V7.

These helpers normalize lightweight entity text before it is stored in
Background Signals or used to hydrate tool arguments. They do not validate
commercial facts; tools and trusted observations still own validation.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple


_KNOWN_MAKES = {
    "TOYOTA",
    "HONDA",
    "MITSUBISHI",
    "NISSAN",
    "SUZUKI",
    "FORD",
    "HYUNDAI",
    "KIA",
    "MAZDA",
    "ISUZU",
}

_TRAILING_TRIM_TOKENS = {
    "BASE",
    "DLX",
    "E",
    "EL",
    "EX",
    "G",
    "GL",
    "GLS",
    "GX",
    "J",
    "S",
    "SE",
    "RS",
    "V",
    "VX",
}


def canonical_vehicle_query(value: Optional[str]) -> str:
    """Return canonical vehicle text for model context and fitment lookup."""

    text = _strip_model_year_token(value)
    if not text:
        return ""
    alias_make, alias_model = canonical_vehicle_alias(text)
    if alias_make and alias_model:
        return f"{alias_make} {alias_model}".strip()
    parts = text.split()
    if not parts:
        return ""
    make = _canonical_make(parts[0])
    model = _canonical_model_text(" ".join(parts[1:]))
    if str(make or "").upper() not in _KNOWN_MAKES:
        return text
    return " ".join(part for part in [make, model] if part).strip()


def canonical_vehicle_make_model_pair(
    car_make: Optional[str],
    car_model: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    """Return canonical make/model pair for compatibility endpoint params."""

    make = _canonical_make(car_make)
    model = _canonical_model_text(car_model)
    alias_make, alias_model = canonical_vehicle_alias(" ".join(part for part in [make, model] if part).strip())
    if alias_make and alias_model:
        return alias_make, alias_model
    return make, model


def canonical_vehicle_alias(value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Return known vehicle aliases that carry enough signal to set the make."""

    tokens = {token.upper().strip(".") for token in str(value or "").replace("-", " ").split() if token.strip()}
    if "G4" in tokens and ("MIRAGE" in tokens or "MITSUBISHI" in tokens):
        return "Mitsubishi", "Mirage G4"
    if "WIGO" in tokens or "WGO" in tokens:
        return "Toyota", "Wigo"
    return None, None


def _canonical_make(value: Optional[str]) -> Optional[str]:
    text = _strip_model_year_token(value)
    if not text:
        return None
    upper = text.upper()
    if upper in _KNOWN_MAKES:
        return text.title()
    return text


def _canonical_model_text(value: Optional[str]) -> Optional[str]:
    text = _strip_model_year_token(value)
    if not text:
        return None
    parts = text.split()
    while len(parts) > 1 and parts[-1].upper().strip(".") in _TRAILING_TRIM_TOKENS:
        parts.pop()
    formatted = [_format_model_token(part) for part in parts]
    return " ".join(part for part in formatted if part).strip() or None


def _format_model_token(value: str) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    clean = token.replace("-", "")
    if clean.isalnum() and len(clean) <= 4 and any(char.isdigit() for char in clean):
        return token.upper()
    return token.title()


def _strip_model_year_token(value: Optional[str]) -> Optional[str]:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return None
    cleaned = re.sub(r"\b(?:19|20)\d{2}\b", " ", text)
    cleaned = " ".join(cleaned.split())
    return cleaned or None


__all__ = [
    "canonical_vehicle_alias",
    "canonical_vehicle_make_model_pair",
    "canonical_vehicle_query",
]
