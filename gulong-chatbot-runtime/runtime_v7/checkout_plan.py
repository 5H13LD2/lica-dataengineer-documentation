"""Checkout compatibility planning for Runtime V7.

The model decides what to ask or explain. This module decides whether a
candidate checkout path is internally coherent once the runtime has trusted
product, service, payment, and policy facts.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence

from runtime_v7.delivery_payment_policy import (
    delivery_payment_policy_for_location,
)
from runtime_v7.order_canonicalization import resolve_transaction_for_service_path, truthy
from runtime_v7.product_search import normalize_installment_banks, normalize_installments


def resolve_checkout_plan(
    *,
    stage: str = "payload",
    selected_product: Optional[Dict[str, Any]] = None,
    quantity: Optional[int] = None,
    service_path: str = "",
    location: str = "",
    delivery_address: str = "",
    service_location: Optional[Dict[str, Any]] = None,
    schedule: str = "",
    has_validated_slot: bool = False,
    quote_breakdown: Optional[Dict[str, Any]] = None,
    payment_selection: Optional[Dict[str, Any]] = None,
    checkout_metadata: Optional[Dict[str, Any]] = None,
    service_compatibility: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a prescriptive but non-conversational checkout feasibility plan."""

    product = dict(selected_product or {})
    service_location = dict(service_location or {})
    quote = dict(quote_breakdown or {})
    payment = dict(payment_selection or {})
    metadata = dict(checkout_metadata or {})
    service_compatibility = dict(service_compatibility or {})
    blockers: List[Dict[str, Any]] = []
    advisories: List[Dict[str, Any]] = []
    prescriptions: List[str] = []

    if not product:
        blockers.append(_blocker("selected_product", "", "Selected product must come from a trusted product ref."))

    payment_invalid = payment.get("invalid_fields") if isinstance(payment.get("invalid_fields"), list) else []
    for item in payment_invalid:
        if isinstance(item, dict):
            blockers.append(
                _blocker(
                    str(item.get("field") or "payment_method"),
                    item.get("value"),
                    str(item.get("reason") or "Payment selection is not compatible with checkout metadata."),
                )
            )

    product_payment = _product_payment_compatibility(
        product,
        quantity=quantity,
        payment_selection=payment,
        checkout_metadata=metadata,
        service_path=service_path,
    )
    blockers.extend(product_payment["blockers"])
    advisories.extend(product_payment["advisories"])

    fulfillment_payment = _fulfillment_payment_compatibility(
        service_path=service_path,
        location=location,
        delivery_address=delivery_address,
        payment_selection=payment,
    )
    blockers.extend(fulfillment_payment["blockers"])
    advisories.extend(fulfillment_payment["advisories"])

    service_result = _service_compatibility(
        stage=stage,
        service_path=service_path,
        service_location=service_location,
        schedule=schedule,
        has_validated_slot=has_validated_slot,
        quote_breakdown=quote,
        service_compatibility=service_compatibility,
    )
    blockers.extend(service_result["blockers"])
    advisories.extend(service_result["advisories"])

    if blockers:
        prescriptions.append("Do not submit the order or claim the path is ready until blockers are resolved.")
    if not blockers and product and service_path:
        prescriptions.append("Checkout path is internally coherent for summary/payload preparation.")
    if advisories:
        prescriptions.append("Mention advisory constraints only when relevant to the customer's next decision.")

    return {
        "status": "blocked" if blockers else "ready" if product and service_path else "incomplete",
        "can_build_payload": bool(product and service_path and not blockers),
        "blockers": _unique_issue_list(blockers),
        "advisories": _unique_issue_list(advisories),
        "prescriptions": prescriptions,
        "compatibility": {
            "product_payment": product_payment["status"],
            "fulfillment_payment": fulfillment_payment["status"],
            "service": service_result["status"],
        },
        "normalized": {
            "service_path": service_path or "",
            "stage": stage,
            "payment_option": payment.get("payment_option") or "",
            "payment_method": payment.get("payment_method_for_submit") or payment.get("payment_method") or "",
            "product_id": product.get("product_id") or product.get("id") or "",
            "service_location_ref": service_location.get("service_location_ref") or "",
        },
    }


def _product_payment_compatibility(
    product: Dict[str, Any],
    *,
    quantity: Optional[int],
    payment_selection: Dict[str, Any],
    checkout_metadata: Dict[str, Any],
    service_path: str,
) -> Dict[str, Any]:
    blockers: List[Dict[str, Any]] = []
    advisories: List[Dict[str, Any]] = []
    method_text = _payment_text(payment_selection)
    if "installment" not in method_text:
        return {"status": "not_applicable", "blockers": blockers, "advisories": advisories}

    bank = _canonical_bank(payment_selection.get("bank") or method_text)
    months = _installment_months(payment_selection)
    payment_type = payment_selection.get("payment_type_row")
    payment_type = dict(payment_type) if isinstance(payment_type, dict) else {}
    if payment_type:
        if truthy(payment_type.get("is_disabled")):
            blockers.append(_blocker("payment_method", payment_type.get("name"), "Selected payment method is not active."))
        allowed_brands = _payment_row_brands(payment_type)
        brand = _normalize_brand(product.get("brand") or product.get("make"))
        if allowed_brands and brand not in allowed_brands:
            blockers.append(
                _blocker(
                    "selected_product",
                    product.get("brand"),
                    "Selected payment method is not available for this tire brand.",
                )
            )
        transaction = resolve_transaction_for_service_path(service_path, checkout_metadata)
        excluded_transaction_id = str(payment_type.get("exclude_transaction_type_id") or "").strip()
        if excluded_transaction_id and str(transaction.get("id") or "").strip() == excluded_transaction_id:
            blockers.append(
                _blocker(
                    "service_path",
                    service_path,
                    "Selected payment method is not available for this fulfillment path.",
                )
            )
        return {
            "status": "blocked" if blockers else "verified_by_checkout_metadata",
            "blockers": blockers,
            "advisories": advisories,
        }

    product_installments = normalize_installments(product.get("installments") or [])
    if product_installments:
        if bank and not _installment_bank_supported(bank, product_installments):
            blockers.append(
                _blocker("payment_method", bank, "Selected product does not list this installment bank.")
            )
        if months and not any(int(item.get("months_to_pay") or 0) == months for item in product_installments):
            blockers.append(
                _blocker("payment_method", months, "Selected product does not list this installment term.")
            )
        return {"status": "blocked" if blockers else "verified_by_product_installments", "blockers": blockers, "advisories": advisories}

    if not months:
        advisories.append(
            _advisory(
                "payment_method",
                payment_selection.get("payment_method_for_submit") or payment_selection.get("payment_method"),
                "Installment term is not specified; confirm 3 months or an eligible 6-month BPI option before payment request.",
            )
        )

    return {"status": "blocked" if blockers else "policy_compatible", "blockers": blockers, "advisories": advisories}


def _payment_row_brands(payment_type: Dict[str, Any]) -> set[str]:
    """Return API-declared eligible brands for a payment row."""

    raw = str(payment_type.get("available_brands") or "")
    return {
        _normalize_brand(value)
        for value in raw.split(",")
        if _normalize_brand(value)
    }


def _fulfillment_payment_compatibility(
    *,
    service_path: str,
    location: str,
    delivery_address: str,
    payment_selection: Dict[str, Any],
) -> Dict[str, Any]:
    blockers: List[Dict[str, Any]] = []
    advisories: List[Dict[str, Any]] = []
    if service_path != "delivery":
        return {"status": "not_applicable", "blockers": blockers, "advisories": advisories}

    policy = delivery_payment_policy_for_location(delivery_address or location)
    method_text = _payment_text(payment_selection)
    option = str(payment_selection.get("payment_option") or "")
    if policy.get("area_type") == "metro_manila" and ("cash on delivery" in method_text or "cod" in method_text):
        blockers.append(_blocker("payment_method", method_text, "COD is not available for Metro Manila delivery."))
    if policy.get("full_payment_required") and option == "Pay Later / Pay After Service":
        advisories.append(
            _advisory(
                "payment_option",
                option,
                "Metro Manila delivery requires full payment; payment request should collect the full amount.",
            )
        )
    return {"status": "blocked" if blockers else "policy_compatible", "blockers": blockers, "advisories": advisories}


def _service_compatibility(
    *,
    stage: str,
    service_path: str,
    service_location: Dict[str, Any],
    schedule: str,
    has_validated_slot: bool,
    quote_breakdown: Dict[str, Any],
    service_compatibility: Dict[str, Any],
) -> Dict[str, Any]:
    blockers: List[Dict[str, Any]] = []
    advisories: List[Dict[str, Any]] = []
    if service_path not in {"installation", "pickup"}:
        return {"status": "not_applicable", "blockers": blockers, "advisories": advisories}

    summary_mode = stage == "summary"
    if not service_location:
        issue = _advisory if summary_mode else _blocker
        (advisories if summary_mode else blockers).append(
            issue("selected_installation_partner", "", "Installation requires a selected service location before payload submission.")
        )
    else:
        service_types = _service_types(service_location)
    if service_location and service_path == "installation" and service_types and "installation" not in service_types:
        blockers.append(
            _blocker("selected_installation_partner", service_location.get("name"), "Selected service location does not support installation.")
        )

    threshold = _coerce_float(service_location.get("order_value_threshold"))
    threshold_total = _coerce_float(
        quote_breakdown.get("installation_threshold_total")
        or quote_breakdown.get("product_subtotal")
        or quote_breakdown.get("online_total_before_payment_discount")
        or quote_breakdown.get("order_total")
    )
    if str(service_location.get("order_threshold_status") or "") == "below_threshold":
        blockers.append(
            _blocker(
                "trusted_order_total",
                threshold_total,
                "Selected installation partner is below the required order value threshold.",
            )
        )
    elif threshold is not None and threshold_total is not None and threshold_total < threshold:
        blockers.append(
            _blocker(
                "trusted_order_total",
                threshold_total,
                f"Selected installation partner requires at least PHP {threshold:,.2f} order value.",
            )
        )

    if schedule and not has_validated_slot:
        issue = _advisory if summary_mode else _blocker
        (advisories if summary_mode else blockers).append(
            issue("schedule", schedule, "Installation schedule must be validated before payload submission.")
        )

    compatibility_status = str(service_compatibility.get("compatibility_status") or "").strip()
    if compatibility_status in {"unverified_relaxed", "unknown"}:
        advisories.append(
            _advisory(
                "service_compatibility",
                compatibility_status,
                "Partner compatibility is not verified by size/model-aware catalog data.",
            )
        )

    return {"status": "blocked" if blockers else "verified_or_not_required", "blockers": blockers, "advisories": advisories}


def _payment_text(payment_selection: Dict[str, Any]) -> str:
    values = [
        payment_selection.get("payment_method_for_submit"),
        payment_selection.get("payment_method"),
        payment_selection.get("reservation_payment_method"),
        payment_selection.get("balance_payment_method"),
        payment_selection.get("bank"),
        (payment_selection.get("payment_type_row") or {}).get("name")
        if isinstance(payment_selection.get("payment_type_row"), dict)
        else "",
        (payment_selection.get("payment_type_row") or {}).get("value")
        if isinstance(payment_selection.get("payment_type_row"), dict)
        else "",
    ]
    return " ".join(str(value or "").strip().lower() for value in values if str(value or "").strip())


def _installment_months(payment_selection: Dict[str, Any]) -> Optional[int]:
    raw = str(payment_selection.get("installment_months") or "").strip()
    if raw.isdigit():
        return int(raw)
    text = _payment_text(payment_selection)
    match = re.search(r"\b(\d{1,2})\s*(?:mos?|months?|month|buwan)\b", text)
    return int(match.group(1)) if match else None


def _installment_bank_supported(bank: str, installments: Sequence[Dict[str, Any]]) -> bool:
    requested = set(normalize_installment_banks([bank]))
    if not requested:
        return True
    available = {
        item
        for installment in installments
        for item in normalize_installment_banks(installment.get("bank_name") or installment.get("bank"))
    }
    return bool(requested.intersection(available))


def _canonical_bank(value: Any) -> str:
    banks = normalize_installment_banks([value])
    return banks[0] if banks else ""


def _normalize_brand(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _service_types(location: Dict[str, Any]) -> List[str]:
    values = location.get("service_types") or []
    if isinstance(values, str):
        values = re.split(r"[,/|]", values)
    if not isinstance(values, Sequence):
        return []
    return [str(value or "").strip().lower() for value in values if str(value or "").strip()]


def _blocker(field: str, value: Any, reason: str) -> Dict[str, Any]:
    return {"severity": "blocker", "field": field, "value": "" if value is None else value, "reason": reason}


def _advisory(field: str, value: Any, reason: str) -> Dict[str, Any]:
    return {"severity": "advisory", "field": field, "value": "" if value is None else value, "reason": reason}


def _unique_issue_list(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (
            str(item.get("severity") or ""),
            str(item.get("field") or ""),
            str(item.get("reason") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(deepcopy(item))
    return output


def _coerce_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
