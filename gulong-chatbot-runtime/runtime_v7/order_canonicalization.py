"""Shared Runtime V7 canonicalization for order-facing business values.

Background Signals may propose candidate order facts, but submit readiness and
payload construction must resolve those facts through the same deterministic
catalog-backed helpers. This module is the shared boundary for checkout
metadata, payment choices, transaction types, and chatbot source constants.
"""

from __future__ import annotations

import re
from copy import deepcopy
from difflib import get_close_matches
from typing import Any, Dict, List, Optional, Sequence

from runtime_v7.canonical_values import CanonicalValuesProvider


CHATBOT_CUSTOMER_TYPE_ID = 11
DEFAULT_CHATBOT_CUSTOMER_SOURCE_LABEL = "CHAT"


def checkout_metadata(provider: Optional[CanonicalValuesProvider]) -> Dict[str, Any]:
    """Return canonical checkout metadata with stable Runtime V7 fallbacks."""

    if provider is None:
        return default_checkout_metadata()
    try:
        metadata = provider.checkout_metadata()
    except Exception:
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    defaults = default_checkout_metadata()
    return {
        "transaction_types": metadata.get("transaction_types") or defaults["transaction_types"],
        "payment_options": metadata.get("payment_options") or defaults["payment_options"],
        "payment_types": metadata.get("payment_types") or [],
        "source": metadata.get("source") or "runtime_v7_checkout_metadata",
        "generated_at_epoch_s": metadata.get("generated_at_epoch_s"),
        "ttl_seconds": metadata.get("ttl_seconds"),
    }


def default_checkout_metadata() -> Dict[str, Any]:
    """Return local checkout metadata used when the API catalog is unavailable."""

    return {
        "transaction_types": [
            {"id": 10, "trans_type": "Install"},
            {"id": 11, "trans_type": "Delivery"},
            {"id": 12, "trans_type": "Pick-up"},
            {"id": 13, "trans_type": "Home Installation Service"},
        ],
        "payment_options": [
            {"id": 1, "name": "Pay Later", "description": "Pay a reservation fee to secure your slot."},
            {"id": 2, "name": "Pay Now", "description": "Pay in full now and receive a PHP 100 discount."},
        ],
        "payment_types": [],
        "source": "runtime_v7_default_checkout_metadata",
    }


def normalize_payment_option(value: Any) -> str:
    """Normalize customer-facing payment timing into Runtime V7 labels."""

    lowered = str(value or "").strip().lower()
    if not lowered:
        return ""
    if "now" in lowered or "full" in lowered:
        return "Pay Now"
    if lowered in {"cod", "c.o.d."} or "cash on delivery" in lowered or "pay on delivery" in lowered:
        return "Pay Later / Pay After Service"
    if "after" in lowered or "later" in lowered or "reservation" in lowered:
        return "Pay Later / Pay After Service"
    return ""


def normalize_payload_payment_option(value: Any) -> str:
    """Return only payment options accepted by the order-payload boundary."""

    normalized = normalize_payment_option(value)
    if normalized in {"Pay Now", "Pay Later / Pay After Service"}:
        return normalized
    return ""


def payment_option_label(payment_option: Any) -> str:
    """Return the checkout-metadata label for a Runtime V7 payment option."""

    normalized = normalize_payload_payment_option(payment_option)
    if normalized == "Pay Later / Pay After Service":
        return "Pay Later"
    return normalized


def canonical_customer_source(payload: Dict[str, Any]) -> str:
    """Return the dashboard source label for chatbot-created orders."""

    source = (
        payload.get("customer_source")
        or payload.get("sales_agent")
        or payload.get("agent_assigned")
        or DEFAULT_CHATBOT_CUSTOMER_SOURCE_LABEL
    )
    return str(source or DEFAULT_CHATBOT_CUSTOMER_SOURCE_LABEL).strip().upper()


def resolve_transaction_for_service_path(service_path: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve a Runtime V7 fulfillment path to checkout transaction metadata."""

    labels_by_path = {
        "installation": ["Install", "Installation"],
        "delivery": ["Delivery", "Deliver"],
        "pickup": ["Pick-up", "Pickup", "Pick Up"],
        "home_service": ["Home Installation Service", "Home Service", "Home Install"],
    }
    rows = [row for row in metadata.get("transaction_types") or [] if isinstance(row, dict)]
    for label in labels_by_path.get(str(service_path or "").strip(), []):
        match = match_checkout_row(rows, label, keys=("trans_type", "name", "description"))
        if match:
            return match
    return {}


def resolve_payment_option(payment_option: Any, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve Pay Now / Pay Later to checkout payment-option metadata."""

    label = payment_option_label(payment_option)
    rows = [row for row in metadata.get("payment_options") or [] if isinstance(row, dict)]
    return match_checkout_row(rows, label, keys=("name", "label", "description"))


def resolve_payment_type(
    payment_method: Any,
    metadata: Dict[str, Any],
    *,
    payment_option_id: Any = None,
) -> Dict[str, Any]:
    """Resolve a payment method within the selected payment-option scope."""

    rows = [
        row
        for row in metadata.get("payment_types") or []
        if isinstance(row, dict) and not truthy(row.get("is_disabled"))
    ]
    if payment_option_id not in (None, ""):
        scoped = [
            row
            for row in rows
            if str(row.get("main_payment_type_id") or "").strip() == str(payment_option_id).strip()
        ]
        if scoped:
            rows = scoped
    local_value = local_canonical_payment_method(payment_method)
    best_match = best_payment_type_match(
        raw_value=str(payment_method or ""),
        local_value=local_value,
        payment_types=rows,
    )
    if best_match:
        return best_match

    # The strict scorer already accepts exact aliases, exact catalog values,
    # and bounded close label matches. If it rejects the candidate, do not use
    # generic substring overlap to discard distinguishing words from a named
    # financial product (for example a loan/credit suffix).
    return {}


def resolve_payment_selection(
    *,
    payment_option: Any = "",
    payment_method: Any = "",
    reservation_payment_method: Any = "",
    balance_payment_method: Any = "",
    bank: Any = "",
    installment_months: Any = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve cross-field payment intent into one coherent checkout selection.

    Background Signals and tool args can carry payment facts in different
    fields. For example, a model may place "BPI" in reservation_payment_method
    while also setting Pay Now + installment. This resolver interprets those
    structured fields together before the order boundary validates or submits.
    """

    metadata = metadata or default_checkout_metadata()
    raw_option = clean(payment_option)
    raw_method = clean(payment_method)
    raw_reservation = clean(reservation_payment_method)
    raw_balance = clean(balance_payment_method)
    raw_bank = clean(bank)
    raw_months = clean(installment_months)
    bank_value = _payment_bank_from_values(raw_bank, raw_method, raw_reservation, raw_balance)
    months_value = _payment_months_from_values(raw_months, raw_method, raw_reservation, raw_balance)

    option = normalize_payload_payment_option(raw_option)
    explicit_option = bool(option)
    if not option:
        option = _infer_payment_option_from_fields(
            payment_method=raw_method,
            reservation_payment_method=raw_reservation,
            balance_payment_method=raw_balance,
        )
        if not option and (bank_value or months_value) and months_value:
            option = "Pay Now"

    conflicts: List[Dict[str, str]] = []
    ignored_fields: List[str] = []
    if option == "Pay Now":
        if _field_has_true_pay_later_terms(raw_method):
            conflicts.append(
                {
                    "field": "payment_option/payment_method",
                    "value": f"{option} + {raw_method}",
                    "reason": (
                        "Payment option is Pay Now, but payment method implies COD, "
                        "reservation, or Pay Later."
                    ),
                }
            )
        for field_name, value in (
            ("reservation_payment_method", raw_reservation),
            ("balance_payment_method", raw_balance),
        ):
            if _field_has_true_pay_later_terms(value):
                conflicts.append(
                    {
                        "field": "payment_option/payment_method",
                        "value": f"{option} + {value}",
                        "reason": (
                            "Payment option is Pay Now, but a structured payment method "
                            "field implies COD, reservation, or Pay Later."
                        ),
                    }
                )
            elif value:
                ignored_fields.append(field_name)
        reservation_out = ""
        balance_out = ""
    elif option == "Pay Later / Pay After Service":
        pay_now_route_fields = [
            value
            for value in (raw_method, raw_reservation, raw_balance)
            if _payment_text_implies_pay_now(value) and not _field_has_true_pay_later_terms(value)
        ]
        reservation_out = raw_reservation
        balance_out = raw_balance
    else:
        reservation_out = raw_reservation
        balance_out = raw_balance

    method_candidates = _payment_method_candidates(
        payment_option=option,
        payment_method=raw_method,
        reservation_payment_method=raw_reservation,
        balance_payment_method=raw_balance,
        bank=bank_value,
        installment_months=months_value,
    )
    payment_option_row = resolve_payment_option(option, metadata) if option else {}
    option_id = payment_option_row.get("id") if payment_option_row else None
    payment_type_row = _resolve_first_payment_type(
        method_candidates,
        metadata=metadata,
        payment_option_id=option_id,
    )
    if (
        option == "Pay Later / Pay After Service"
        and (pay_now_route_fields or months_value)
        and not payment_type_row
    ):
        conflict_value = " + ".join(
            [
                option,
                *pay_now_route_fields,
                f"{months_value} months" if months_value else "",
            ]
        )
        conflict_value = re.sub(
            r"\s+\+\s*$",
            "",
            conflict_value,
        ).strip()
        conflicts.append(
            {
                "field": "payment_option/payment_method",
                "value": conflict_value,
                "reason": (
                    "Payment option is Pay Later, but the proposed card or "
                    "installment route is not authorized for Pay Later by "
                    "checkout metadata."
                ),
            }
        )
    normalized_method = _normalized_payment_method_from_candidates(
        method_candidates,
        payment_type_row=payment_type_row,
    )
    if (
        option == "Pay Later / Pay After Service"
        and payment_type_row
        and raw_method
        and not raw_reservation
        and not raw_balance
        and not _field_has_true_pay_later_terms(raw_method)
    ):
        stage = payment_method_stage(
            payment_option=option,
            is_installment=truthy(payment_type_row.get("is_installment")),
        )
        if stage == "reservation_fee":
            reservation_out = normalized_method or raw_method
        elif stage == "balance_payment":
            balance_out = normalized_method or raw_method

    unsupported = []
    has_payment_type_catalog = any(isinstance(row, dict) for row in metadata.get("payment_types") or [])
    authoritative_catalog_expected = str(
        metadata.get("source") or ""
    ).strip() not in {"", "runtime_v7_default_checkout_metadata"}
    if (
        method_candidates
        and not payment_type_row
        and not conflicts
        and (has_payment_type_catalog or authoritative_catalog_expected)
    ):
        requested = method_candidates[0]
        unsupported.append(
            {
                "field": "payment_method",
                "value": requested,
                "reason": (
                    "Payment method did not match checkout payment metadata."
                    if has_payment_type_catalog
                    else (
                        "Current checkout payment metadata is unavailable, so "
                        "this payment method cannot be validated."
                    )
                ),
            }
        )

    if option == "Pay Later / Pay After Service" and _field_has_true_pay_later_terms(raw_method):
        if _payment_text_means_cod(raw_method):
            if not balance_out:
                balance_out = normalized_method or raw_method
        elif not reservation_out:
            reservation_out = normalized_method or raw_method
    if option == "Pay Now":
        reservation_out = ""
        balance_out = ""

    status = "ready"
    if conflicts:
        status = "conflict"
    elif unsupported:
        status = "unsupported"
    elif not option:
        status = "missing_payment_option"

    return {
        "status": status,
        "payment_option": option,
        "payment_method": normalized_method,
        "payment_method_for_submit": normalized_method or reservation_out or balance_out,
        "reservation_payment_method": reservation_out,
        "balance_payment_method": balance_out,
        "bank": bank_value,
        "installment_months": months_value,
        "payment_option_row": payment_option_row,
        "payment_type_row": payment_type_row,
        "ignored_conflicting_fields": ignored_fields,
        "invalid_fields": conflicts or unsupported,
        "allowed_options": _allowed_payment_method_labels(metadata),
        "explicit_payment_option": explicit_option,
    }


def payment_method_stage(
    *,
    payment_option: Any,
    is_installment: bool,
) -> str:
    """Classify one validated API payment row into its checkout layer."""

    if normalize_payment_option(payment_option) == "Pay Now":
        return "full_payment"
    if is_installment:
        return "balance_payment"
    return "reservation_fee"


def canonical_payment_option_with_metadata(
    text: Any,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> tuple[Optional[str], Dict[str, Any]]:
    """Canonicalize Pay Now vs Pay Later/Pay After Service with metadata."""

    raw_value = clean(text)
    local_value = local_canonical_payment_option(raw_value)
    if canonical_values_provider is None:
        value = local_value or raw_value
        return (
            value or None,
            {
                "raw_value": raw_value,
                "status": "local_normalized_unvalidated",
                "source": "local_alias",
                "normalized_value": value,
            } if value else {},
        )

    try:
        metadata = checkout_metadata(canonical_values_provider)
    except Exception as exc:
        value = local_value or raw_value
        return (
            value or None,
            {
                "raw_value": raw_value,
                "status": "checkout_metadata_error",
                "source": "local_alias",
                "normalized_value": value,
                "error": f"{exc.__class__.__name__}: {exc}",
            } if value else {},
        )

    option = resolve_payment_option(local_value or raw_value, metadata)
    if option:
        value = str(option.get("name") or local_value or raw_value).strip()
        return value, {
            "raw_value": raw_value,
            "status": "checkout_metadata_canonicalized",
            "source": "checkout_metadata",
            "normalized_value": value,
            "payment_option": compact_checkout_row(option),
        }
    if not local_value:
        return None, {
            "raw_value": raw_value,
            "status": "checkout_metadata_no_match",
            "source": "checkout_metadata",
            "needs": "payment_option must be Pay Now or Pay Later; treat card, GCash, COD, or installment as payment_method",
        }
    return local_value, {
        "raw_value": raw_value,
        "status": "checkout_metadata_no_match",
        "source": "local_alias",
        "normalized_value": local_value,
    }


def canonical_payment_method_with_metadata(
    text: Any,
    *,
    key: str,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> tuple[Optional[str], Dict[str, Any]]:
    """Canonicalize payment method candidates with checkout metadata."""

    raw_value = clean(text)
    local_value = local_canonical_payment_method(raw_value)
    fallback_value = local_value or raw_value.lower()
    base_metadata = {
        "raw_value": raw_value,
        "local_normalized_value": local_value,
    }
    if canonical_values_provider is None:
        if not fallback_value:
            return None, {}
        return fallback_value, {
            **base_metadata,
            "status": "local_normalized_unvalidated",
            "source": "local_alias",
            "normalized_value": fallback_value,
        }

    try:
        metadata = checkout_metadata(canonical_values_provider)
    except Exception as exc:
        if not fallback_value:
            return None, {}
        return fallback_value, {
            **base_metadata,
            "status": "checkout_metadata_error",
            "source": "local_alias",
            "normalized_value": fallback_value,
            "error": f"{exc.__class__.__name__}: {exc}",
        }

    payment_types = [row for row in metadata.get("payment_types") or [] if isinstance(row, dict)]
    payment_options = [row for row in metadata.get("payment_options") or [] if isinstance(row, dict)]
    if (
        key in {"balance_payment_method", "payment_method"}
        and local_value in {"credit card installment", "installment"}
        and not has_explicit_installment_terms(raw_value)
    ):
        candidates = candidate_checkout_payment_types(
            raw_value=raw_value,
            local_value=local_value,
            payment_types=payment_types,
            limit=3,
        )
        return fallback_value, {
            **base_metadata,
            "status": "checkout_metadata_deferred_product_installment_selection",
            "source": "checkout_metadata",
            "normalized_value": fallback_value,
            "requires_product_installment_option": True,
            "candidate_payment_types": [compact_checkout_row(row) for row in candidates],
        }

    payment_type = match_checkout_payment_type(
        raw_value=raw_value,
        local_value=local_value,
        key=key,
        payment_types=payment_types,
    )
    if payment_type:
        normalized_value = compact_payment_value_from_row(payment_type, fallback_value)
        payment_option = payment_option_for_type(payment_type, payment_options)
        return normalized_value, {
            **base_metadata,
            "status": "checkout_metadata_canonicalized",
            "source": "checkout_metadata",
            "normalized_value": normalized_value,
            "payment_type": compact_checkout_row(payment_type),
            "payment_option": compact_checkout_row(payment_option) if payment_option else None,
        }

    if not fallback_value:
        return None, {
            **base_metadata,
            "status": "checkout_metadata_no_match",
            "source": "checkout_metadata",
            "normalized_value": None,
        }
    return fallback_value, {
        **base_metadata,
        "status": "checkout_metadata_no_match",
        "source": "local_alias",
        "normalized_value": fallback_value,
    }


def local_canonical_payment_option(text: Any) -> Optional[str]:
    """Return a local payment timing label without claiming catalog validity."""

    lowered = str(text or "").strip().lower()
    if not lowered:
        return None
    if "now" in lowered or "full" in lowered:
        return "Pay Now"
    if lowered in {"cod", "c.o.d."} or "cash on delivery" in lowered or "pay on delivery" in lowered:
        return "Pay Later"
    if "later" in lowered or "after service" in lowered or "reservation" in lowered:
        return "Pay Later"
    return None


def local_canonical_payment_method(text: Any) -> Optional[str]:
    """Return a local payment method label without claiming catalog validity."""

    lowered = str(text or "").lower()
    normalized = re.sub(r"[^a-z0-9]+", "", lowered)
    has_card = "credit card" in lowered or re.search(r"\bcard\b", lowered) is not None
    has_installment = "installment" in lowered or "installments" in lowered
    if normalized in {"cod", "cashondelivery"} or "cash on delivery" in lowered or "pay on delivery" in lowered:
        return "cash on delivery"
    if has_card and has_installment:
        return "credit card installment"
    if _matches_wallet_alias(lowered, aliases=("gcash",)):
        return "gcash"
    if has_card:
        return "credit card"
    if has_installment:
        return "installment"
    if re.search(r"\bcash\b", lowered):
        return "cash"
    if _matches_wallet_alias(lowered, aliases=("maya", "paymaya")):
        return "maya"
    if "bank transfer" in lowered:
        return "bank transfer"
    return None


def _matches_wallet_alias(text: str, *, aliases: Sequence[str]) -> bool:
    """Match a wallet name without absorbing a distinct financial product."""

    tokens = re.findall(r"[a-z0-9]+", str(text or "").lower())
    while tokens and tokens[0] in {"via", "using", "use"}:
        tokens.pop(0)
    if not tokens or tokens[0] not in set(aliases):
        return False
    # These modifiers preserve the wallet/payment-rail meaning. Other words
    # such as credit, loan, card, or installment denote a different product
    # and must go through provider-backed validation under their full name.
    return set(tokens[1:]).issubset(
        {"wallet", "e", "payment", "payments", "pay", "qr", "qrcode"}
    )


def _infer_payment_option_from_fields(
    *,
    payment_method: str,
    reservation_payment_method: str,
    balance_payment_method: str,
) -> str:
    if reservation_payment_method or balance_payment_method:
        values = [payment_method, reservation_payment_method, balance_payment_method]
        if any(_payment_text_implies_pay_now(value) for value in values) and not any(
            _field_has_true_pay_later_terms(value) for value in values
        ):
            return "Pay Now"
        return "Pay Later / Pay After Service"
    if _payment_text_implies_pay_later(payment_method):
        return "Pay Later / Pay After Service"
    if _payment_text_implies_pay_now(payment_method):
        return "Pay Now"
    return ""


def _payment_text_implies_pay_now(value: Any) -> bool:
    text = clean(value).lower()
    if not text:
        return False
    normalized = alnum_lower(text)
    return (
        any(token in text for token in ("pay now", "full payment", "2c2p", "credit card", "debit card", "installment"))
        or normalized in {"cc", "card", "creditcard", "debitcard"}
    )


def _payment_text_implies_pay_later(value: Any) -> bool:
    return _field_has_true_pay_later_terms(value)


def _field_has_true_pay_later_terms(value: Any) -> bool:
    text = clean(value).lower()
    if not text:
        return False
    normalized = alnum_lower(text)
    return (
        normalized in {"cod", "cashondelivery", "payondelivery"}
        or "cash on delivery" in text
        or "pay on delivery" in text
        or "pay later" in text
        or "pay after service" in text
        or "reservation" in text
        or "down payment" in text
        or re.search(r"\bdp\b", text) is not None
    )


def _payment_text_means_cod(value: Any) -> bool:
    text = clean(value).lower()
    if not text:
        return False
    normalized = alnum_lower(text)
    return (
        normalized in {"cod", "cashondelivery", "payondelivery"}
        or "cash on delivery" in text
        or "pay on delivery" in text
    )


def _payment_method_candidates(
    *,
    payment_option: str,
    payment_method: str,
    reservation_payment_method: str,
    balance_payment_method: str,
    bank: str,
    installment_months: str,
) -> List[str]:
    values = [payment_method]
    if payment_option == "Pay Now":
        values.extend(
            value
            for value in (reservation_payment_method, balance_payment_method)
            if value and not _field_has_true_pay_later_terms(value)
        )
    else:
        values.extend([reservation_payment_method, balance_payment_method])

    has_installment = any(_payment_text_mentions_installment(value) for value in values) or bool(installment_months)
    has_card = any(_payment_text_mentions_card(value) for value in values)
    composed_parts: List[str] = []
    if bank:
        composed_parts.append(bank)
    if installment_months:
        composed_parts.append(f"{installment_months} months")
    if has_installment:
        composed_parts.append("credit card installment" if has_card or bank else "installment")
    elif has_card:
        composed_parts.append("credit card")
    composed = " ".join(composed_parts).strip()

    candidates = [composed] if composed else []
    candidates.extend(value for value in values if value)
    output: List[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = alnum_lower(candidate)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(candidate)
    return output


def _resolve_first_payment_type(
    candidates: Sequence[str],
    *,
    metadata: Dict[str, Any],
    payment_option_id: Any,
) -> Dict[str, Any]:
    for candidate in candidates:
        row = resolve_payment_type(candidate, metadata, payment_option_id=payment_option_id)
        if row:
            return row
    return {}


def _normalized_payment_method_from_candidates(
    candidates: Sequence[str],
    *,
    payment_type_row: Dict[str, Any],
) -> str:
    fallback = ""
    for candidate in candidates:
        local = local_canonical_payment_method(candidate)
        if local:
            fallback = local
            break
    if not fallback and candidates:
        fallback = clean(candidates[0])
    if payment_type_row:
        return compact_payment_value_from_row(payment_type_row, fallback)
    return fallback


def _payment_bank_from_values(*values: Any) -> str:
    banks = [
        ("bpi", "BPI"),
        ("bdo", "BDO"),
        ("metrobank", "Metrobank"),
        ("eastwest", "EastWest"),
        ("east west", "EastWest"),
        ("hsbc", "HSBC"),
        ("china bank", "China Bank"),
        ("chinabank", "China Bank"),
    ]
    text = " ".join(clean(value).lower() for value in values if clean(value))
    for needle, label in banks:
        if needle in text:
            return label
    return ""


def _payment_months_from_values(*values: Any) -> str:
    for value in values:
        text = clean(value).lower()
        match = re.search(
            r"\b(\d{1,2})\s*[-]?\s*(?:mos?|months?|month|buwan)\b",
            text,
        )
        if match:
            return match.group(1)
        if re.fullmatch(r"\d{1,2}", text):
            return text
    return ""


def payment_plan_hints_from_text(*values: Any) -> Dict[str, str]:
    """Extract bank and installment-term hints from customer-backed text.

    Model tool arguments are proposed query plans and can be less specific than
    the customer's actual question.  These hints let the runtime restore
    explicit bank/term constraints before matching the authoritative checkout
    catalog without teaching the resolver any brand-specific business rules.
    """

    return {
        "bank": _payment_bank_from_values(*values),
        "installment_months": _payment_months_from_values(*values),
    }


def _payment_text_mentions_installment(value: Any) -> bool:
    text = clean(value).lower()
    return "installment" in text or "0%" in text or _payment_months_from_values(text) != ""


def _payment_text_mentions_card(value: Any) -> bool:
    text = clean(value).lower()
    normalized = alnum_lower(text)
    return any(token in text for token in ("credit card", "debit card")) or normalized in {
        "cc",
        "card",
        "creditcard",
        "debitcard",
    }


def _allowed_payment_method_labels(metadata: Dict[str, Any]) -> List[str]:
    labels: List[str] = []
    for row in metadata.get("payment_types") or []:
        if not isinstance(row, dict):
            continue
        label = clean(row.get("name") or row.get("label") or row.get("value"))
        if label:
            labels.append(label)
    return labels[:8]


def match_checkout_payment_type(
    *,
    raw_value: str,
    local_value: Optional[str],
    key: str,
    payment_types: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Match a candidate payment method against checkout metadata."""

    if not payment_types:
        return None

    candidates = list(payment_types)
    if key == "reservation_payment_method":
        pay_later_rows = [
            row for row in candidates if int_or_none(row.get("main_payment_type_id")) == 1
        ]
        scoped = best_payment_type_match(
            raw_value=raw_value,
            local_value=local_value,
            payment_types=pay_later_rows,
        )
        if scoped:
            return scoped

    return best_payment_type_match(
        raw_value=raw_value,
        local_value=local_value,
        payment_types=candidates,
    )


def best_payment_type_match(
    *,
    raw_value: str,
    local_value: Optional[str],
    payment_types: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Select the best payment-type match by deterministic score."""

    best_row: Optional[Dict[str, Any]] = None
    best_score = 0
    for row in payment_types:
        score = payment_type_match_score(row, raw_value=raw_value, local_value=local_value)
        if score > best_score:
            best_score = score
            best_row = row
    return deepcopy(best_row) if best_row and best_score >= 75 else None


def candidate_checkout_payment_types(
    *,
    raw_value: str,
    local_value: Optional[str],
    payment_types: Sequence[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    """Return compact candidate payment types for deferred choices."""

    scored = [
        (
            payment_type_match_score(row, raw_value=raw_value, local_value=local_value),
            row,
        )
        for row in payment_types
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [deepcopy(row) for score, row in scored if score >= 75][: max(0, int(limit))]


def payment_type_match_score(
    row: Dict[str, Any],
    *,
    raw_value: str,
    local_value: Optional[str],
) -> int:
    """Score how well a payment-type metadata row matches a customer value."""

    text = checkout_row_match_text(row)
    raw = clean(raw_value).lower()
    local = clean(local_value).lower()
    is_installment = truthy(row.get("is_installment")) or "installment" in text or "0%" in text
    requested_months = _payment_months_from_values(raw)
    requested_bank = _payment_bank_from_values(raw)

    # The live checkout catalog can contain multiple installment rows in the
    # same payment-option scope. A generic "installment" score must not let a
    # three-month row win when the customer supplied BPI and six months.
    if is_installment and (requested_months or requested_bank):
        if requested_months and not re.search(
            rf"\b{re.escape(requested_months)}[\s-]*(?:mos?|months?|month)\b", text
        ):
            return 0
        if requested_bank and requested_bank.lower().replace(" ", "") not in re.sub(r"[^a-z0-9]+", "", text):
            return 0

    if local == "gcash":
        return 100 if "gcash" in text else 0
    if local == "credit card installment":
        if is_installment:
            return 100 if any(token in text for token in ["card", "credit", "debit", "cc"]) else 94
        return 0
    if local == "installment":
        return 95 if is_installment else 0
    if local == "credit card":
        if is_installment:
            return 0
        return 94 if any(token in text for token in ["credit", "debit", "card", "cc"]) else 0
    if local == "cash on delivery":
        if re.search(r"\bcod\b", text) or "cash on delivery" in text or "pay on delivery" in text:
            return 100
        return 0
    if local == "cash":
        return 90 if re.search(r"(?<!g)\bcash\b", text) else 0
    if local == "maya":
        return 90 if "maya" in text or "paymaya" in text else 0
    if local == "bank transfer":
        return 90 if "bank" in text or "transfer" in text else 0

    normalized_raw = alnum_lower(raw)
    if normalized_raw:
        row_keys = [
            alnum_lower(row.get("name")),
            alnum_lower(row.get("label")),
            alnum_lower(row.get("value")),
        ]
        if normalized_raw in row_keys:
            return 92
        if len(normalized_raw) >= 4 and any(normalized_raw in row_key for row_key in row_keys):
            return 86
        matches = get_close_matches(normalized_raw, [key for key in row_keys if key], n=1, cutoff=0.84)
        if matches:
            return 82
    return 0


def match_checkout_row(rows: Sequence[Dict[str, Any]], value: Any, *, keys: Sequence[str]) -> Dict[str, Any]:
    """Match a generic checkout metadata row by label-like fields."""

    needle = normalize_checkout_text(value)
    if not needle:
        return {}
    best: Dict[str, Any] = {}
    best_score = 0
    for row in rows:
        haystacks = [normalize_checkout_text(row.get(key)) for key in keys]
        haystacks = [item for item in haystacks if item]
        if not haystacks:
            continue
        if needle in haystacks:
            return deepcopy(row)
        for haystack in haystacks:
            score = checkout_match_score(needle, haystack)
            if score > best_score:
                best_score = score
                best = row
    return deepcopy(best) if best_score >= 85 else {}


def normalize_checkout_text(value: Any) -> str:
    """Normalize checkout metadata labels for deterministic matching."""

    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    aliases = {
        "pay after service": "pay later",
        "pay later pay after service": "pay later",
        "cash on delivery": "cash",
        "credit card debit card": "credit card",
        "cc": "credit card",
        "card": "credit card",
        "maya only": "maya",
        "gcash qr": "gcash",
        "g cash": "gcash",
    }
    text = re.sub(r"\s+", " ", text).strip()
    return aliases.get(text, text)


def checkout_match_score(needle: str, haystack: str) -> int:
    """Return a term-overlap score for normalized checkout strings."""

    if not needle or not haystack:
        return 0
    if needle == haystack:
        return 100
    if needle in haystack or haystack in needle:
        return 92
    needle_terms = set(needle.split())
    haystack_terms = set(haystack.split())
    if not needle_terms or not haystack_terms:
        return 0
    overlap = len(needle_terms.intersection(haystack_terms))
    return int(100 * overlap / max(len(needle_terms), len(haystack_terms)))


def payment_option_for_type(
    payment_type: Dict[str, Any],
    payment_options: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return the payment option associated with a payment-type row."""

    option_id = int_or_none(payment_type.get("main_payment_type_id"))
    if option_id is None:
        return None
    for option in payment_options:
        if int_or_none(option.get("id")) == option_id:
            return deepcopy(option)
    return None


def compact_checkout_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a compact checkout metadata row safe for model-facing context."""

    if not row:
        return None
    return {
        key: row.get(key)
        for key in (
            "id",
            "main_payment_type_id",
            "name",
            "label",
            "value",
            "description",
            "is_installment",
            "direct_payment",
        )
        if row.get(key) not in (None, "")
    }


def compact_payment_value_from_row(row: Dict[str, Any], fallback_value: str) -> str:
    """Return a compact payment value from a checkout payment-type row."""

    fallback = clean(fallback_value).lower()
    if fallback in {
        "gcash",
        "credit card",
        "credit card installment",
        "installment",
        "cash on delivery",
        "cash",
        "maya",
        "bank transfer",
    }:
        return fallback

    text = checkout_row_match_text(row)
    if truthy(row.get("is_installment")) or "installment" in text:
        return "credit card installment" if any(token in text for token in ["card", "credit", "debit", "cc"]) else "installment"
    if "gcash" in text:
        return "gcash"
    if "maya" in text or "paymaya" in text:
        return "maya"
    if "bank" in text:
        return "bank transfer"
    if "cod" in text or "cash on delivery" in text or "pay on delivery" in text:
        return "cash on delivery"
    if any(token in text for token in ["credit", "debit", "card", "cc"]):
        return "credit card"
    if re.search(r"(?<!g)\bcash\b", text):
        return "cash"
    return clean(row.get("label") or row.get("name") or row.get("value")).lower()


def checkout_row_match_text(row: Dict[str, Any]) -> str:
    """Build lowercase searchable text from a checkout metadata row."""

    return " ".join(
        clean(row.get(field)).lower()
        for field in ("name", "label", "value", "description", "icons", "payment_type", "type")
        if clean(row.get(field))
    )


def has_explicit_installment_terms(text: str) -> bool:
    """Return whether a value names enough installment terms for action use."""

    lowered = (text or "").lower()
    if re.search(r"\b\d{1,2}\s*(?:mos?|months?|month|buwan)\b", lowered):
        return True
    if re.search(r"\b\d{1,2}\s*%\b", lowered):
        return True
    banks = ["bpi", "bdo", "metrobank", "eastwest", "hsbc", "china bank", "chinabank"]
    return any(bank in lowered for bank in banks)


def clean(value: Any) -> str:
    """Collapse whitespace and coerce optional values to clean text."""

    return re.sub(r"\s+", " ", str(value or "")).strip()


def alnum_lower(value: Any) -> str:
    """Build a lowercase alphanumeric key for fuzzy matching."""

    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def int_or_none(value: Any) -> Optional[int]:
    """Coerce a value to int when possible without raising."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def truthy(value: Any) -> bool:
    """Normalize common truthy payload values to a boolean."""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}
