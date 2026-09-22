"""Runtime V7 delivery, payment, and installment policy source.

This module keeps policy facts that affect customer copy and order math in one
place so FAQ answers, quote totals, and payment-request routing do not drift.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


STANDARD_DELIVERY_FEE = 500.0
COD_RESERVATION_FEE = 500.0
DELIVERY_LEAD_TIME = "7-10 days"
FREE_DELIVERY_BRANDS = set()
FREE_DELIVERY_CATEGORIES = {"premium"}

METRO_MANILA_LOCATION_TERMS = {
    "metro manila",
    "ncr",
    "caloocan",
    "las pinas",
    "makati",
    "malabon",
    "mandaluyong",
    "manila",
    "marikina",
    "muntinlupa",
    "navotas",
    "paranaque",
    "pasay",
    "pasig",
    "pateros",
    "quezon city",
    "san juan",
    "taguig",
    "valenzuela",
}
OUTSIDE_METRO_PROVINCE_TERMS = {
    "batangas",
    "bulacan",
    "cavite",
    "laguna",
    "pampanga",
    "quezon",
    "rizal",
}


def delivery_fee_for_product(product: Dict[str, Any]) -> Optional[float]:
    """Return the delivery fee for a trusted product row."""

    brand = _key(product.get("brand") or product.get("make"))
    category = _category_key(product.get("category") or product.get("tire_type") or product.get("page_source"))
    if brand in FREE_DELIVERY_BRANDS or category in FREE_DELIVERY_CATEGORIES:
        return 0.0
    if not category:
        return None
    return STANDARD_DELIVERY_FEE


def order_policy_answer_for_title(title: str) -> str:
    """Return the V7-owned policy answer for order FAQ titles when available."""

    normalized = _normalize_title(title)
    # Payment and installment availability are API-backed checkout metadata.
    # `faq_tools` owns their runtime answer so this static policy module cannot
    # drift from the live website checkout options.
    if normalized in {
        _normalize_title("How do I Pay?"),
        _normalize_title("Do you offer installment payments?"),
        _normalize_title("What is the delivery and payment process?"),
    }:
        return ""
    if normalized == _normalize_title("How much is the delivery fee?"):
        return shipping_fee_spiel()
    if normalized == _normalize_title("How long does delivery take?"):
        return delivery_process_spiel()
    if normalized == _normalize_title("Can I request a formal quotation?"):
        return (
            "Yes po. We can first check the current tire choices and prices here in chat. "
            "For a formal company, corporate, or fleet quotation, our customer-service "
            "team needs to prepare and confirm the document. Please share the tire size "
            "and quantity needed; company and contact details can be collected when the "
            "request is progressed. Product availability, final totals, taxes, and order "
            "status still need validation before they are treated as confirmed."
        )
    if normalized == _normalize_title("Do you issue an official receipt?"):
        return (
            "Yes po. Gulong.ph issues an official receipt for completed purchases. "
            "It is sent to the customer's email after installation or order completion."
        )
    return ""


def shipping_fee_spiel() -> str:
    """Return the customer-facing shipping fee policy."""

    return "\n".join(
        [
            "Shipping Fee 🚚",
            "- FREE: Premium Brands",
            "- ₱500: Budget, Economy, and Mid-Range Brands",
        ]
    )


def delivery_process_spiel() -> str:
    """Return the customer-facing delivery process policy."""

    return "\n".join(
        [
            "Delivery 📦",
            "- Greater Manila Area: Lalamove",
            "- Outside Metro Manila: Lazada",
            f"- Estimated delivery time: {DELIVERY_LEAD_TIME}",
        ]
    )


def delivery_payment_policy_for_location(location_text: Any) -> Dict[str, Any]:
    """Return compact delivery payment policy for a location string."""

    location = _normalize_text(location_text)
    if not location:
        area_type = "unknown"
    elif is_metro_manila_location(location):
        area_type = "metro_manila"
    else:
        area_type = "outside_metro_manila"

    if area_type == "metro_manila":
        return {
            "area_type": area_type,
            "full_payment_required": True,
            "cod_available": False,
            "primary_methods": ["Online Banking", "GCash"],
        }
    if area_type == "outside_metro_manila":
        return {
            "area_type": area_type,
            "full_payment_required": False,
            "cod_available": True,
            "reservation_fee": COD_RESERVATION_FEE,
            "primary_methods": ["COD", "Online Banking", "GCash"],
        }
    return {
        "area_type": area_type,
        "full_payment_required": False,
        "cod_available": None,
        "primary_methods": ["Online Banking", "GCash"],
    }


def is_metro_manila_location(location_text: Any) -> bool:
    """Return whether a customer-facing location appears to be Metro Manila."""

    text = _normalize_text(location_text)
    if any(term in text for term in OUTSIDE_METRO_PROVINCE_TERMS):
        return False
    return any(term in text for term in METRO_MANILA_LOCATION_TERMS)


def payment_request_requires_full_payment(data: Dict[str, Any], payment_method: Any) -> bool:
    """Return whether a delivery payment request must use full payment."""

    if not _is_delivery_order_data(data):
        return False
    method_text = " ".join(
        str(value or "")
        for value in [
            payment_method,
            data.get("payment_option_value"),
            data.get("sub_payment_type"),
            _details_text(data.get("payment_type_details")),
        ]
    )
    if _is_card_or_installment_method(method_text):
        return True
    area = delivery_payment_policy_for_location(
        " ".join(
            str(value or "")
            for value in [
                data.get("address_1"),
                data.get("city_1"),
                data.get("province_1"),
            ]
        )
    )
    if area.get("full_payment_required") and _is_online_or_e_wallet_method(method_text):
        return True
    return False


def payment_instruction_route(payment_method: str, *, instruction_mode: str = "") -> str:
    """Return the primary payment instruction route for a payment method."""

    mode = _normalize_text(instruction_mode)
    if mode in {"link", "payment_link", "2c2p", "card", "installment"}:
        return "payment_link"
    if mode in {"details", "manual", "account", "accounts", "bank_details", "qr"}:
        return "qr_code"
    method = _normalize_text(payment_method)
    if not method:
        return "qr_code"
    if _is_card_or_installment_method(method):
        return "payment_link"
    return "qr_code"


def _is_delivery_order_data(data: Dict[str, Any]) -> bool:
    details = data.get("transaction_type_details") if isinstance(data.get("transaction_type_details"), dict) else {}
    text = _normalize_text(
        " ".join(
            str(value or "")
            for value in [
                data.get("transaction_type"),
                details.get("name"),
                details.get("description"),
            ]
        )
    )
    return "delivery" in text or text.strip() == "11"


def _is_card_or_installment_method(value: Any) -> bool:
    text = _normalize_text(value)
    return any(token in text for token in ["credit", "debit", "card", "installment", "2c2p", "cc"])


def _is_online_or_e_wallet_method(value: Any) -> bool:
    text = _normalize_text(value)
    return any(token in text for token in ["gcash", "g cash", "maya", "bank", "online", "transfer", "qr"])


def _details_text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return " ".join(str(value.get(key) or "") for key in ("name", "label", "value", "description"))


def _category_key(value: Any) -> str:
    text = _normalize_text(value).replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return {
        "mid range": "midrange",
        "midrange": "midrange",
        "premium": "premium",
        "budget": "budget",
        "economy": "economy",
    }.get(text, text.replace(" ", ""))


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _normalize_title(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())
