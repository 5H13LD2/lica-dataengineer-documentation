"""Compact validated tokens for Runtime V7 interactive discovery choices."""

from __future__ import annotations

from typing import Any, Dict


CHOICE_TOKEN_PREFIX = "bc1"
LOCATION_CHOICE_TOKEN_PREFIX = "lc1"
PRODUCT_CHOICE_TOKEN_PREFIX = "ps1"
SCHEDULE_CHOICE_TOKEN_PREFIX = "ss1"
PAYMENT_OPTION_CHOICE_TOKEN_PREFIX = "po1"
PAYMENT_METHOD_CHOICE_TOKEN_PREFIX = "pm1"
SUPPORTED_PRICE_CATEGORIES = {"budget", "economy", "mid_range", "premium"}
SUPPORTED_LOCATION_LEVELS = {"province", "city"}


def build_price_category_token(
    *,
    presentation_ref: str,
    category: str,
    section_width: str,
    aspect_ratio: str,
    rim_size: str,
) -> str:
    """Encode one delivered category choice into the existing router field."""

    category = str(category or "").strip().casefold()
    values = [
        str(presentation_ref or "").strip(),
        category,
        str(section_width or "").strip(),
        str(aspect_ratio or "").strip(),
        str(rim_size or "").strip().upper(),
    ]
    if not all(values) or category not in SUPPORTED_PRICE_CATEGORIES:
        raise ValueError("Price-category token requires a valid presentation, category, and tire size")
    if any("|" in value for value in values):
        raise ValueError("Price-category token values must not contain '|'")
    token = "|".join([CHOICE_TOKEN_PREFIX, *values])
    if len(token) > 255:
        raise ValueError("Price-category token exceeds the ManyChat text-field limit")
    return token


def parse_price_category_token(value: Any) -> Dict[str, str]:
    """Decode a category token, or return empty for another action type."""

    token = str(value or "").strip()
    if not token.startswith(f"{CHOICE_TOKEN_PREFIX}|"):
        return {}
    parts = token.split("|")
    if len(parts) != 6:
        raise ValueError("Malformed price-category token")
    _, presentation_ref, category, section_width, aspect_ratio, rim_size = parts
    if category not in SUPPORTED_PRICE_CATEGORIES or not all(
        [presentation_ref, section_width, aspect_ratio, rim_size]
    ):
        raise ValueError("Price-category token contains invalid values")
    return {
        "presentation_ref": presentation_ref,
        "category": category,
        "section_width": section_width,
        "aspect_ratio": aspect_ratio,
        "rim_size": rim_size,
    }


def build_location_choice_token(
    *,
    presentation_ref: str,
    level: str,
    parent_code: str,
    choice_code: str,
) -> str:
    """Encode one delivered serviceable-location choice for the shared router."""

    values = [
        str(presentation_ref or "").strip(),
        str(level or "").strip().casefold(),
        str(parent_code or "").strip(),
        str(choice_code or "").strip(),
    ]
    if not all(values) or values[1] not in SUPPORTED_LOCATION_LEVELS:
        raise ValueError("Location token requires a presentation, level, parent, and choice")
    if any("|" in value for value in values):
        raise ValueError("Location token values must not contain '|'")
    token = "|".join([LOCATION_CHOICE_TOKEN_PREFIX, *values])
    if len(token) > 255:
        raise ValueError("Location token exceeds the ManyChat text-field limit")
    return token


def parse_location_choice_token(value: Any) -> Dict[str, str]:
    """Decode a location token, or return empty for another action type."""

    token = str(value or "").strip()
    if not token.startswith(f"{LOCATION_CHOICE_TOKEN_PREFIX}|"):
        return {}
    parts = token.split("|")
    if len(parts) != 5:
        raise ValueError("Malformed location-choice token")
    _, presentation_ref, level, parent_code, choice_code = parts
    if level not in SUPPORTED_LOCATION_LEVELS or not all(
        [presentation_ref, parent_code, choice_code]
    ):
        raise ValueError("Location-choice token contains invalid values")
    return {
        "presentation_ref": presentation_ref,
        "level": level,
        "parent_code": parent_code,
        "choice_code": choice_code,
    }


def build_product_choice_token(
    *,
    presentation_ref: str,
    card_ref: str,
) -> str:
    """Encode one delivered product-card choice for the shared router."""

    values = [
        str(presentation_ref or "").strip(),
        str(card_ref or "").strip(),
    ]
    if not all(values):
        raise ValueError("Product-choice token requires a presentation and card reference")
    if any("|" in value for value in values):
        raise ValueError("Product-choice token values must not contain '|'")
    token = "|".join([PRODUCT_CHOICE_TOKEN_PREFIX, *values])
    if len(token) > 255:
        raise ValueError("Product-choice token exceeds the ManyChat text-field limit")
    return token


def parse_product_choice_token(value: Any) -> Dict[str, str]:
    """Decode a product-card token, or return empty for another action type."""

    token = str(value or "").strip()
    if not token.startswith(f"{PRODUCT_CHOICE_TOKEN_PREFIX}|"):
        return {}
    parts = token.split("|")
    if len(parts) != 3:
        raise ValueError("Malformed product-choice token")
    _, presentation_ref, card_ref = parts
    if not presentation_ref or not card_ref:
        raise ValueError("Product-choice token contains invalid values")
    return {
        "presentation_ref": presentation_ref,
        "card_ref": card_ref,
    }


def build_schedule_choice_token(
    *,
    presentation_ref: str,
    choice_ref: str,
) -> str:
    """Encode one delivered exact-slot or flexible schedule choice."""

    return _build_reference_choice_token(
        prefix=SCHEDULE_CHOICE_TOKEN_PREFIX,
        presentation_ref=presentation_ref,
        choice_ref=choice_ref,
        label="Schedule-choice",
    )


def parse_schedule_choice_token(value: Any) -> Dict[str, str]:
    """Decode a schedule-choice token, or return empty for another action."""

    return _parse_reference_choice_token(
        value,
        prefix=SCHEDULE_CHOICE_TOKEN_PREFIX,
        label="schedule-choice",
    )


def build_payment_option_choice_token(
    *,
    presentation_ref: str,
    choice_ref: str,
) -> str:
    """Encode one delivered Pay Now or Pay Later choice."""

    return _build_reference_choice_token(
        prefix=PAYMENT_OPTION_CHOICE_TOKEN_PREFIX,
        presentation_ref=presentation_ref,
        choice_ref=choice_ref,
        label="Payment-option choice",
    )


def parse_payment_option_choice_token(value: Any) -> Dict[str, str]:
    """Decode a payment-option token, or return empty for another action."""

    return _parse_reference_choice_token(
        value,
        prefix=PAYMENT_OPTION_CHOICE_TOKEN_PREFIX,
        label="payment-option choice",
    )


def build_payment_method_choice_token(
    *,
    presentation_ref: str,
    choice_ref: str,
) -> str:
    """Encode one delivered checkout-compatible payment method."""

    return _build_reference_choice_token(
        prefix=PAYMENT_METHOD_CHOICE_TOKEN_PREFIX,
        presentation_ref=presentation_ref,
        choice_ref=choice_ref,
        label="Payment-method choice",
    )


def parse_payment_method_choice_token(value: Any) -> Dict[str, str]:
    """Decode a payment-method token, or return empty for another action."""

    return _parse_reference_choice_token(
        value,
        prefix=PAYMENT_METHOD_CHOICE_TOKEN_PREFIX,
        label="payment-method choice",
    )


def _build_reference_choice_token(
    *,
    prefix: str,
    presentation_ref: str,
    choice_ref: str,
    label: str,
) -> str:
    values = [
        str(presentation_ref or "").strip(),
        str(choice_ref or "").strip(),
    ]
    if not all(values):
        raise ValueError(f"{label} token requires a presentation and choice reference")
    if any("|" in item for item in values):
        raise ValueError(f"{label} token values must not contain '|'")
    token = "|".join([prefix, *values])
    if len(token) > 255:
        raise ValueError(f"{label} token exceeds the ManyChat text-field limit")
    return token


def _parse_reference_choice_token(
    value: Any,
    *,
    prefix: str,
    label: str,
) -> Dict[str, str]:
    token = str(value or "").strip()
    if not token.startswith(f"{prefix}|"):
        return {}
    parts = token.split("|")
    if len(parts) != 3:
        raise ValueError(f"Malformed {label} token")
    _, presentation_ref, choice_ref = parts
    if not presentation_ref or not choice_ref:
        raise ValueError(f"{label.capitalize()} token contains invalid values")
    return {
        "presentation_ref": presentation_ref,
        "choice_ref": choice_ref,
    }
