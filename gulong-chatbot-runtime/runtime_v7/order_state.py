"""Order readiness compiler for Runtime V7.

This module keeps order progress as derived state. It reads normalized
Background Signals plus trusted product/service observations and returns a
compact factual summary for the model. Order submission is a separate boundary:
it posts only a previously validated Runtime V7 `{data, newCartItems}` payload
and never rebuilds order facts from raw customer text at submit time.
"""

from __future__ import annotations

import re
import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from runtime_v7.canonical_values import CanonicalValuesProvider
from runtime_v7.checkout_plan import resolve_checkout_plan
from runtime_v7.delivery_payment_policy import (
    delivery_fee_for_product as policy_delivery_fee_for_product,
    payment_instruction_route as policy_payment_instruction_route,
    payment_request_requires_full_payment,
)
from runtime_v7.order_canonicalization import (
    CHATBOT_CUSTOMER_TYPE_ID,
    canonical_customer_source,
    checkout_metadata as shared_checkout_metadata,
    normalize_payment_option as shared_normalize_payment_option,
    normalize_payload_payment_option as shared_normalize_payload_payment_option,
    payment_option_label as shared_payment_option_label,
    resolve_payment_option,
    resolve_payment_selection,
    resolve_payment_type,
    resolve_transaction_for_service_path,
)
from runtime_v7.product_observations import ProductObservation, ProductObservationStore
from runtime_v7.product_search import (
    effective_total_price,
    pricing_basis,
    product_discount_savings_for_quantity,
)
from runtime_v7.service_observations import ServiceObservation, ServiceObservationStore
from runtime_v7.state_signal_schema import (
    TRANSIENT_SIGNAL_RELATIONS,
    signal_authority_source,
    signal_has_durable_authority,
)


MANILA_TZ = ZoneInfo("Asia/Manila")
PAYMENT_OPTIONS_CONFIG_PATH = Path(__file__).resolve().parents[1] / "runtime" / "bu" / "gulong" / "config" / "payment_options.json"


@dataclass(frozen=True)
class OrderReadiness:
    """Prompt-facing order readiness state."""

    status: str
    customer_order_intent: str
    can_prepare_order_summary: bool
    high_intent_signals: List[str] = field(default_factory=list)
    collected: Dict[str, str] = field(default_factory=dict)
    missing: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    validation: List[str] = field(default_factory=list)
    schedule_status: str = ""
    submission_blockers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable readiness payload."""

        return {
            "status": self.status,
            "customer_order_intent": self.customer_order_intent,
            "can_prepare_order_summary": self.can_prepare_order_summary,
            "high_intent_signals": list(self.high_intent_signals),
            "collected": dict(self.collected),
            "missing": list(self.missing),
            "assumptions": list(self.assumptions),
            "validation": list(self.validation),
            "schedule_status": self.schedule_status,
            "submission_blockers": list(self.submission_blockers),
        }


def calculate_order_quote(
    *,
    payload: Optional[Dict[str, Any]] = None,
    current_user_message: str = "",
    active_working_memory: str = "",
    background_signals: Optional[Sequence[Dict[str, Any]]] = None,
    product_observation_store: Optional[ProductObservationStore] = None,
    service_observation_store: Optional[ServiceObservationStore] = None,
    order_readiness: Optional[Dict[str, Any] | OrderReadiness] = None,
    previous_order_summary_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compile a read-only quote from trusted product state and policy math.

    The quote is safe for explanation and order-summary preparation only. It
    does not submit an order, reserve stock, book a slot, or create payment
    instructions.
    """

    payload = dict(payload or {})
    signals = _signals_by_key(background_signals or [])
    readiness_payload = (
        order_readiness.to_dict()
        if isinstance(order_readiness, OrderReadiness)
        else dict(order_readiness or {})
    )
    if not readiness_payload:
        readiness_payload = build_order_readiness(
            current_user_message=current_user_message,
            active_working_memory=active_working_memory,
            background_signals=background_signals,
            product_observation_store=product_observation_store,
            service_observation_store=service_observation_store,
            previous_order_summary_snapshot=previous_order_summary_snapshot,
        ).to_dict()

    latest_product = product_observation_store.latest() if product_observation_store else None
    latest_service = service_observation_store.latest() if service_observation_store else None
    latest_service_presentation = service_observation_store.latest_presentation() if service_observation_store else None
    selected_product, product_reason = _selected_product_from_summary_payload(payload, product_observation_store)
    if not selected_product:
        selected_product, product_reason = _selected_product(latest_product, signals)
    quantity, quantity_is_default = _quantity_for_summary(
        payload,
        signals,
        default_allowed=bool(selected_product or latest_product),
        selected_product=selected_product,
        previous_order_summary_snapshot=previous_order_summary_snapshot,
    )
    service_path, service_reason = _fulfillment_path_for_summary(
        payload,
        signals,
        latest_service,
        latest_service_presentation,
    )
    reservation_payment = _payload_or_signal(payload, signals, "reservation_payment_method")
    balance_payment = _payload_or_signal(payload, signals, "balance_payment_method")
    payment_method = _payload_or_signal(payload, signals, "payment_method")
    payment_selection = resolve_payment_selection(
        payment_option=_payload_or_signal(payload, signals, "payment_option"),
        payment_method=payment_method,
        reservation_payment_method=reservation_payment,
        balance_payment_method=balance_payment,
        bank=_payload_or_signal(payload, signals, "bank"),
        installment_months=_payload_or_signal(payload, signals, "installment_months"),
        metadata=_checkout_metadata(None),
    )
    payment_option = str(payment_selection.get("payment_option") or "")
    payment_conflicts = list(payment_selection.get("invalid_fields") or [])
    quote_payment_option = "" if payment_conflicts else payment_option

    quote = _quote_for_product(
        selected_product,
        quantity=quantity,
        quantity_is_default=quantity_is_default,
        service_path=service_path,
        service_reason=service_reason,
        payment_option=quote_payment_option,
        latest_service=latest_service,
        signals=signals,
        product_reason=product_reason,
    )
    candidate_quotes: List[Dict[str, Any]] = []
    if not selected_product and latest_product is not None:
        candidate_quotes = _quote_candidates_from_observation(
            latest_product,
            quantity=quantity or 4,
            service_path=service_path,
            service_reason=service_reason,
            payment_option=payment_option,
        )

    missing = list(quote.get("missing_fields") or [])
    if not selected_product:
        missing.append("Selected product/SKU")
    invalid_fields = _unique_invalid_fields(payment_conflicts)
    status = "ok" if selected_product and not missing else "incomplete" if selected_product or candidate_quotes else "not_started"
    if invalid_fields:
        status = "needs_payment_clarification"
    if candidate_quotes and not selected_product:
        status = "needs_product_selection"

    return {
        "status": status,
        "quote_ref": _quote_ref(quote or {"candidate_quotes": candidate_quotes}),
        "order_readiness_status": readiness_payload.get("status"),
        "customer_order_intent": readiness_payload.get("customer_order_intent"),
        "selected_product": _quote_product_summary(selected_product) if selected_product else {},
        "candidate_quotes": candidate_quotes,
        "quantity": quantity or None,
        "quantity_defaulted": bool(quantity_is_default and quantity),
        "service_path": service_path,
        "service_reason": service_reason,
        "payment_option": quote_payment_option,
        "quote_summary": _quote_summary(quote),
        "quote_breakdown": quote,
        "missing_fields": _unique(missing),
        "invalid_fields": invalid_fields,
        "assumptions": _unique(
            [
                *([quote.get("quantity_assumption")] if quote.get("quantity_assumption") else []),
                *(quote.get("assumptions") or []),
            ]
        ),
        "validation": _unique([item for item in quote.get("validation") or [] if item]),
        "customer_explanation_hints": _quote_customer_explanation_hints(
            quote=quote,
            selected_product=bool(selected_product),
            candidate_quotes=bool(candidate_quotes),
            invalid_fields=invalid_fields,
        ),
        "read_only": True,
        "can_submit_order": False,
        "note": "Read-only quote. It does not create an order, booking, reservation, payment, or schedule confirmation.",
    }


def build_order_summary(
    *,
    payload: Optional[Dict[str, Any]] = None,
    current_user_message: str = "",
    active_working_memory: str = "",
    background_signals: Optional[Sequence[Dict[str, Any]]] = None,
    product_observation_store: Optional[ProductObservationStore] = None,
    service_observation_store: Optional[ServiceObservationStore] = None,
    order_readiness: Optional[Dict[str, Any] | OrderReadiness] = None,
    previous_order_summary_snapshot: Optional[Dict[str, Any]] = None,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Dict[str, Any]:
    """Build a deterministic, read-only order summary from trusted state.

    The summary is presentation-only. It does not submit an order, reserve stock,
    book a schedule, or create payment instructions.
    """

    payload = dict(payload or {})
    signals = _signals_by_key(background_signals or [])
    readiness_payload = (
        order_readiness.to_dict()
        if isinstance(order_readiness, OrderReadiness)
        else dict(order_readiness or {})
    )
    if not readiness_payload:
        readiness_payload = build_order_readiness(
            current_user_message=current_user_message,
            active_working_memory=active_working_memory,
            background_signals=background_signals,
            product_observation_store=product_observation_store,
            service_observation_store=service_observation_store,
            previous_order_summary_snapshot=previous_order_summary_snapshot,
        ).to_dict()

    latest_product = product_observation_store.latest() if product_observation_store else None
    latest_service = service_observation_store.latest() if service_observation_store else None
    latest_service_presentation = service_observation_store.latest_presentation() if service_observation_store else None

    selected_product, product_reason = _selected_product_from_summary_payload(payload, product_observation_store)
    if not selected_product:
        selected_product, product_reason = _selected_product(latest_product, signals)
    quantity, quantity_is_default = _quantity_for_summary(
        payload,
        signals,
        default_allowed=bool(selected_product),
        selected_product=selected_product,
        previous_order_summary_snapshot=previous_order_summary_snapshot,
    )
    trusted_total = _trusted_total(selected_product, quantity=quantity) if selected_product else None

    service_path, service_reason = _fulfillment_path_for_summary(
        payload,
        signals,
        latest_service,
        latest_service_presentation,
    )
    service_location = _service_location_from_payload(payload, service_observation_store)
    location = _customer_location_for_order(
        payload=payload,
        signals=signals,
        order_readiness=readiness_payload,
        service_path=service_path,
    )
    delivery_address = _payload_or_signal(payload, signals, "delivery_address")
    contact_number = _payload_or_signal(payload, signals, "contact_number")
    customer_name = _customer_name(payload, signals)
    first_name, last_name = _customer_name_parts(payload, signals, customer_name)
    email = _payload_or_signal(payload, signals, "email_address")
    selected_partner = (
        _payload_or_signal(payload, signals, "installation_partner_name")
        or _payload_or_signal(payload, signals, "selected_installation_partner")
        or str((service_location or {}).get("name") or "").strip()
    )
    schedule = (
        _payload_or_signal(payload, signals, "schedule")
        or _payload_or_signal(payload, signals, "preferred_schedule")
        or _payload_or_signal(payload, signals, "chosen_schedule_slot")
    )
    validated_slot_context = _latest_validated_slot_context(
        service_observation_store,
        service_location_ref=payload.get("service_location_ref") or payload.get("installation_partner_ref"),
    )
    if service_path in {"installation", "pickup"} and validated_slot_context:
        if not service_location:
            service_location = deepcopy(validated_slot_context.get("service_location") or {})
        if not selected_partner:
            selected_partner = str((validated_slot_context.get("service_location") or {}).get("name") or "").strip()
        schedule = _summary_schedule_from_validated_slot(schedule, validated_slot_context)
    has_validated_order_slot = bool(service_path in {"installation", "pickup"} and validated_slot_context and schedule)
    schedule_status = str(readiness_payload.get("schedule_status") or "").strip()
    flexible_schedule_preference = bool(
        service_path in {"installation", "pickup"}
        and schedule
        and not has_validated_order_slot
        and schedule_status == "flexible_preference"
    )
    summary_schedule = schedule
    if flexible_schedule_preference:
        collected = (
            readiness_payload.get("collected")
            if isinstance(readiness_payload.get("collected"), dict)
            else {}
        )
        summary_schedule = str(
            collected.get("Preferred installation schedule")
            or schedule
        ).strip()
    unvalidated_order_slot = bool(
        service_path in {"installation", "pickup"}
        and schedule
        and not has_validated_order_slot
        and not flexible_schedule_preference
    )
    reservation_payment = _payload_or_signal(payload, signals, "reservation_payment_method")
    balance_payment = _payload_or_signal(payload, signals, "balance_payment_method")
    payment_method = _payload_or_signal(payload, signals, "payment_method")
    checkout_metadata = _checkout_metadata(canonical_values_provider)
    payment_selection = resolve_payment_selection(
        payment_option=_payload_or_signal(payload, signals, "payment_option"),
        payment_method=payment_method,
        reservation_payment_method=reservation_payment,
        balance_payment_method=balance_payment,
        bank=_payload_or_signal(payload, signals, "bank"),
        installment_months=_payload_or_signal(payload, signals, "installment_months"),
        metadata=checkout_metadata,
    )
    payment_option = str(payment_selection.get("payment_option") or "")
    payment_method = str(payment_selection.get("payment_method") or payment_method or "").strip()
    reservation_payment = str(payment_selection.get("reservation_payment_method") or "").strip()
    balance_payment = str(payment_selection.get("balance_payment_method") or "").strip()
    payment_conflicts = list(payment_selection.get("invalid_fields") or [])
    if payment_conflicts:
        return _payment_clarification_result(
            conflicts=payment_conflicts,
            selected_product=selected_product,
            quantity=quantity,
            service_path=service_path,
            delivery_address=delivery_address,
            location=location,
            order_readiness=readiness_payload,
        )
    invoice = _payload_or_signal(payload, signals, "invoice_to_company")
    quote_payload = _payload_with_payment_selection(payload, payment_selection)
    quote_result = calculate_order_quote(
        payload=quote_payload,
        current_user_message=current_user_message,
        active_working_memory=active_working_memory,
        background_signals=background_signals or [],
        product_observation_store=product_observation_store,
        service_observation_store=service_observation_store,
        order_readiness=readiness_payload,
        previous_order_summary_snapshot=previous_order_summary_snapshot,
    )
    quote_breakdown = quote_result.get("quote_breakdown") if isinstance(quote_result.get("quote_breakdown"), dict) else {}
    quote_summary = quote_result.get("quote_summary") if isinstance(quote_result.get("quote_summary"), dict) else {}
    checkout_plan = resolve_checkout_plan(
        stage="summary",
        selected_product=selected_product,
        quantity=quantity,
        service_path=service_path,
        location=location,
        delivery_address=delivery_address,
        service_location=service_location,
        schedule=summary_schedule,
        has_validated_slot=bool(validated_slot_context and schedule),
        quote_breakdown=quote_breakdown,
        payment_selection=payment_selection,
        checkout_metadata=checkout_metadata,
        service_compatibility=_service_compatibility_context(latest_service),
    )

    missing: List[str] = []
    assumptions: List[str] = []
    validation: List[str] = []
    invalid: List[Dict[str, str]] = []
    if selected_product:
        validation.append(product_reason)
    else:
        missing.append("Selected product/SKU")
    if selected_product and quantity_is_default:
        assumptions.append("Quantity defaults to 4 tires unless the customer says otherwise.")
    if selected_product and trusted_total is None:
        missing.append("Trusted customer-facing price/total")
    if trusted_total is not None:
        validation.append("Total is derived from trusted product observation pricing and quantity.")
    if quote_breakdown.get("validation"):
        validation.extend(str(item) for item in quote_breakdown.get("validation") or [] if item)
    if quote_result.get("missing_fields"):
        for item in quote_result.get("missing_fields") or []:
            if item != "Selected product/SKU":
                missing.append(str(item))

    require_order_detail = _summary_should_require_order_detail(
        readiness_payload,
        summary_scope=payload.get("summary_scope"),
    )

    if not service_path:
        missing.append("Fulfillment path or delivery/installation area")
    elif service_path == "delivery":
        if not (delivery_address or location):
            missing.append("Delivery area/address")
        elif not delivery_address and require_order_detail:
            missing.append("Complete delivery address")
        elif not delivery_address:
            assumptions.append("Delivery address is still partial; exact address can be collected later.")
    elif service_path == "installation":
        if not (location or selected_partner):
            missing.append("Installation area/location")
        if not schedule and require_order_detail:
            missing.append("Selected installation schedule")
        elif unvalidated_order_slot:
            missing.append("Validated installation schedule")
            validation.append("Selected installation schedule must be validated before it can be used for order payload submission.")
        elif flexible_schedule_preference:
            validation.append(
                "The flexible installation window is valid for order-summary review; "
                "the exact partner and slot remain required before payload submission."
            )

    if require_order_detail:
        if not contact_number:
            missing.append("Contact number")
        if not first_name:
            missing.append("First name")
        if not last_name:
            missing.append("Last name")
        if not email:
            missing.append("Email address")
        if not payment_option:
            missing.append("Payment option (Pay Now or Pay Later)")
        elif payment_option == "Pay Later / Pay After Service" and not reservation_payment:
            missing.append("Reservation payment method")
    if checkout_plan.get("blockers"):
        missing.append("Checkout compatibility clarification")
        invalid.extend(_checkout_plan_invalid_fields(checkout_plan))
    for item in checkout_plan.get("advisories") or []:
        if isinstance(item, dict) and item.get("reason"):
            validation.append(str(item.get("reason")))

    submission_blockers = _unique(
        [
            str(item)
            for item in readiness_payload.get("submission_blockers") or []
            if str(item).strip()
        ]
    )
    if flexible_schedule_preference and not submission_blockers:
        submission_blockers.append(
            "Exact installation partner and schedule must be validated before order submission."
        )
    summary_partner = selected_partner
    if flexible_schedule_preference and not summary_partner:
        summary_partner = "To be confirmed for the selected schedule window"

    fields = _order_summary_fields(
        customer_name=customer_name,
        contact_number=contact_number,
        email=email,
        product=_product_label(selected_product) if selected_product else "",
        tire_size=_product_size(selected_product) if selected_product else _payload_or_signal(payload, signals, "tire_size"),
        quantity=f"{quantity} tires" if quantity else "",
        product_total=quote_breakdown.get("product_subtotal_text") or (_money_text(trusted_total) if trusted_total is not None else ""),
        delivery_fee=quote_breakdown.get("delivery_fee_text") or "",
        home_service_fee=quote_breakdown.get("home_service_fee_text") or "",
        pay_now_discount=quote_breakdown.get("pay_now_discount_text") or "",
        trusted_total=quote_breakdown.get("order_total_text") or (_money_text(trusted_total) if trusted_total is not None else ""),
        amount_due_now=quote_breakdown.get("amount_due_now_text") or "",
        balance_due=quote_breakdown.get("balance_due_text") or "",
        addon_note=_branch_addon_note(quote_breakdown.get("branch_addon_context")),
        service_path=service_path,
        service_reason=service_reason,
        location=location,
        delivery_address=delivery_address,
        selected_partner=summary_partner,
        schedule="" if unvalidated_order_slot else summary_schedule,
        payment_option=payment_option,
        reservation_payment=reservation_payment,
        balance_payment=(
            balance_payment
            if reservation_payment
            else balance_payment or payment_method
        ),
        payment_bank=str(payment_selection.get("bank") or "").strip(),
        installment_months=str(payment_selection.get("installment_months") or "").strip(),
        invoice=invoice,
    )
    summary_block = _render_order_summary_block(fields, missing=_unique(missing))
    has_summary_context = any(value not in {"", "-"} for value in fields.values())
    summary_ref = _order_summary_ref(summary_block)
    status = "ready" if not missing and selected_product else "incomplete" if has_summary_context else "not_started"
    source_refs = _order_product_source_refs(payload=payload, latest_product=latest_product)
    snapshot = _order_summary_snapshot(
        summary_ref=summary_ref,
        status=status,
        fields=fields,
        missing_fields=_unique(missing),
        submission_blockers=submission_blockers,
        schedule_status=schedule_status,
        quote_summary=quote_summary,
        quantity=quantity,
        quantity_defaulted=quantity_is_default,
        quantity_source=_resolved_quantity_source(
            payload=payload,
            signals=signals,
            selected_product=selected_product,
            quantity=quantity,
            quantity_is_default=quantity_is_default,
            previous_order_summary_snapshot=previous_order_summary_snapshot,
        ),
        payment_selection=_summary_payment_selection(payment_selection),
        source_refs=source_refs,
    )
    summary_update = _summary_update_from_snapshot(
        previous_order_summary_snapshot,
        snapshot,
        presentation_intent=payload.get("presentation_intent"),
    )
    card_runtime_insert = bool(status in {"ready", "incomplete"} and summary_block.strip() and has_summary_context)
    if summary_update.get("display_action") == "quiet_update":
        card_runtime_insert = False
    can_build_order_payload = bool(
        status == "ready"
        and not submission_blockers
        and not summary_update.get("confirmation_recommended")
    )
    order_faq_suggestions = _order_faq_suggestions(
        service_path=service_path,
        payment_option=payment_option,
        missing=_unique(missing),
    )

    return {
        "status": status,
        "order_readiness_status": readiness_payload.get("status"),
        "customer_order_intent": readiness_payload.get("customer_order_intent"),
        "can_prepare_order_summary": status in {"ready", "incomplete"},
        "order_summary_ref": summary_ref,
        "card_runtime_insert": card_runtime_insert,
        "runtime_renders_body": card_runtime_insert,
        "summary_preview": {key: value for key, value in fields.items() if value not in ("", "-")},
        "quote_summary": quote_summary,
        "source_refs": source_refs,
        "summary_update": summary_update,
        "order_summary_snapshot": snapshot,
        "can_build_order_payload": can_build_order_payload,
        "recommended_next_tool": "build_order_payload" if can_build_order_payload else "",
        "payment_method": payment_selection.get("payment_method_for_submit") or payment_method,
        "payment_bank": payment_selection.get("bank") or "",
        "installment_months": payment_selection.get("installment_months") or "",
        "missing_fields": _unique(missing),
        "submission_blockers": submission_blockers,
        "schedule_status": schedule_status,
        "invalid_fields": _unique_invalid_fields(invalid),
        "checkout_plan": checkout_plan,
        "assumptions": _unique(assumptions),
        "validation": _unique([item for item in validation if item]),
        "customer_explanation_hints": _order_summary_hints(
            status=status,
            missing=_unique(missing),
            service_path=service_path,
            payment_option=payment_option,
            submission_blockers=submission_blockers,
            summary_update=summary_update,
        ),
        "order_faq_suggestions": order_faq_suggestions,
        "supporting_policy_context": _supporting_order_policy_context(
            order_faq_suggestions,
            service_path=service_path,
            canonical_values_provider=canonical_values_provider,
        ),
        "order_summary_block": summary_block if card_runtime_insert else "",
        "read_only": True,
        "can_submit_order": False,
        "note": "Read-only order summary. This does not create an order, booking, reservation, payment, or schedule confirmation.",
    }


def build_order_payload(
    *,
    payload: Optional[Dict[str, Any]] = None,
    current_user_message: str = "",
    active_working_memory: str = "",
    background_signals: Optional[Sequence[Dict[str, Any]]] = None,
    product_observation_store: Optional[ProductObservationStore] = None,
    service_observation_store: Optional[ServiceObservationStore] = None,
    order_readiness: Optional[Dict[str, Any] | OrderReadiness] = None,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Dict[str, Any]:
    """Validate order data and build a read-only Gulong API submit payload.

    This is a boundary tool for the future submit/payment step. It intentionally
    performs no side effects and does not call the order API. A successful
    result returns the same outer payload shape the Gulong `/order` endpoint
    expects (`data` plus `newCartItems`), built from Runtime V7-normalized and
    validated refs.
    """

    payload = dict(payload or {})
    signals = _signals_by_key(background_signals or [])
    readiness_payload = (
        order_readiness.to_dict()
        if isinstance(order_readiness, OrderReadiness)
        else dict(order_readiness or {})
    )
    if not readiness_payload:
        readiness_payload = build_order_readiness(
            current_user_message=current_user_message,
            active_working_memory=active_working_memory,
            background_signals=background_signals,
            product_observation_store=product_observation_store,
            service_observation_store=service_observation_store,
        ).to_dict()

    latest_product = product_observation_store.latest() if product_observation_store else None
    latest_service = service_observation_store.latest() if service_observation_store else None
    latest_service_presentation = service_observation_store.latest_presentation() if service_observation_store else None
    service_location = _service_location_from_payload(payload, service_observation_store)

    selected_product, product_reason = _selected_product_from_summary_payload(payload, product_observation_store)
    if not selected_product:
        selected_product, product_reason = _selected_product(latest_product, signals)

    quantity, quantity_is_default = _quantity_for_summary(
        payload,
        signals,
        default_allowed=bool(selected_product),
        selected_product=selected_product,
    )
    service_path, service_reason = _fulfillment_path_for_summary(
        payload,
        signals,
        latest_service,
        latest_service_presentation,
    )
    if service_path in {"installation", "pickup"} and not service_location:
        service_location = _latest_validated_slot_service_location(service_observation_store)
    location = _customer_location_for_order(
        payload=payload,
        signals=signals,
        order_readiness=readiness_payload,
        service_path=service_path,
    )
    delivery_address = _payload_or_signal(payload, signals, "delivery_address")
    selected_partner = (
        _payload_or_signal(payload, signals, "installation_partner_name")
        or _payload_or_signal(payload, signals, "selected_installation_partner")
        or str((service_location or {}).get("name") or "").strip()
    )
    schedule = (
        _payload_or_signal(payload, signals, "schedule")
        or _payload_or_signal(payload, signals, "preferred_schedule")
        or _payload_or_signal(payload, signals, "chosen_schedule_slot")
    )
    validated_slot_context = _latest_validated_slot_context(
        service_observation_store,
        service_location_ref=payload.get("service_location_ref") or payload.get("installation_partner_ref"),
    )
    if service_path in {"installation", "pickup"} and validated_slot_context:
        if not service_location:
            service_location = deepcopy(validated_slot_context.get("service_location") or {})
        if not selected_partner:
            selected_partner = str((validated_slot_context.get("service_location") or {}).get("name") or "").strip()
    contact_number = _payload_or_signal(payload, signals, "contact_number")
    customer_name = _customer_name(payload, signals)
    first_name, last_name = _customer_name_parts(payload, signals, customer_name)
    email = _payload_or_signal(payload, signals, "email_address")
    invoice = _payload_or_signal(payload, signals, "invoice_to_company")
    reservation_payment = _payload_or_signal(payload, signals, "reservation_payment_method")
    balance_payment = _payload_or_signal(payload, signals, "balance_payment_method")
    payment_method = _payload_or_signal(payload, signals, "payment_method")
    payment_option_raw = _payload_or_signal(payload, signals, "payment_option")
    checkout_metadata = _checkout_metadata(canonical_values_provider)
    payment_selection = resolve_payment_selection(
        payment_option=payment_option_raw,
        payment_method=payment_method,
        reservation_payment_method=reservation_payment,
        balance_payment_method=balance_payment,
        bank=_payload_or_signal(payload, signals, "bank"),
        installment_months=_payload_or_signal(payload, signals, "installment_months"),
        metadata=checkout_metadata,
    )
    payment_option = str(payment_selection.get("payment_option") or "").strip()
    payment_method = str(payment_selection.get("payment_method") or "").strip()
    reservation_payment = str(payment_selection.get("reservation_payment_method") or "").strip()
    balance_payment = str(payment_selection.get("balance_payment_method") or "").strip()
    payment_conflicts = list(payment_selection.get("invalid_fields") or [])
    payment_method_defaulted = False
    if payment_option == "Pay Now" and not payment_method:
        payment_method = _default_pay_now_payment_method(checkout_metadata)
        payment_method_defaulted = bool(payment_method)
        payment_selection = resolve_payment_selection(
            payment_option=payment_option,
            payment_method=payment_method,
            reservation_payment_method=reservation_payment,
            balance_payment_method=balance_payment,
            bank=_payload_or_signal(payload, signals, "bank"),
            installment_months=_payload_or_signal(payload, signals, "installment_months"),
            metadata=checkout_metadata,
        )
        payment_method = str(payment_selection.get("payment_method") or payment_method or "").strip()
        reservation_payment = str(payment_selection.get("reservation_payment_method") or "").strip()
        balance_payment = str(payment_selection.get("balance_payment_method") or "").strip()
        payment_conflicts = list(payment_selection.get("invalid_fields") or [])

    quote_payload = _payload_with_payment_selection(payload, payment_selection)
    quote_result = calculate_order_quote(
        payload=quote_payload,
        current_user_message=current_user_message,
        active_working_memory=active_working_memory,
        background_signals=background_signals or [],
        product_observation_store=product_observation_store,
        service_observation_store=service_observation_store,
        order_readiness=readiness_payload,
    )
    quote_breakdown = quote_result.get("quote_breakdown") if isinstance(quote_result.get("quote_breakdown"), dict) else {}

    missing: List[str] = []
    invalid: List[Dict[str, str]] = []
    validation: List[str] = []
    assumptions: List[str] = []
    if selected_product:
        validation.append(product_reason)
    else:
        missing.append("Selected product/SKU")
    if not quantity:
        missing.append("Quantity")
    elif quantity_is_default:
        missing.append("Quantity confirmation")
        assumptions.append("Quantity defaults to 4 tires in read-only summaries but must be confirmed before submission.")

    trusted_total = quote_breakdown.get("order_total")
    if selected_product and trusted_total is None:
        missing.append("Trusted order total")
    for item in quote_result.get("missing_fields") or []:
        text = str(item or "").strip()
        if text and text not in {"Selected product/SKU"}:
            missing.append(text)
    if quote_breakdown.get("validation"):
        validation.extend(str(item) for item in quote_breakdown.get("validation") or [] if item)

    if not service_path:
        missing.append("Fulfillment path")
    elif service_path == "delivery":
        if not delivery_address:
            missing.append("Complete delivery address")
    elif service_path == "installation":
        if not (location or selected_partner):
            missing.append("Installation area/location")
        if not selected_partner:
            missing.append("Selected installation partner")
        if not schedule:
            missing.append("Selected installation schedule")
    elif service_path == "pickup":
        if not selected_partner:
            missing.append("Selected pickup branch")
    elif service_path == "home_service":
        if not (delivery_address or location):
            missing.append("Home service address")
        if not schedule:
            missing.append("Selected home service schedule")

    if not contact_number:
        missing.append("Contact number")
    elif not _looks_like_contact_number(contact_number):
        invalid.append(
            {
                "field": "contact_number",
                "value": contact_number,
                "reason": "Contact number should include a usable mobile/phone number.",
            }
        )
    if not first_name:
        missing.append("First name")
    if not last_name:
        missing.append("Last name")
    if not email:
        missing.append("Email address")
    elif not _looks_like_email(email):
        invalid.append(
            {
                "field": "email_address",
                "value": email,
                "reason": "Email address should be usable for checkout.",
            }
        )

    if not payment_option:
        if payment_option_raw:
            invalid.append(
                {
                    "field": "payment_option",
                    "value": str(payment_option_raw),
                    "reason": "Payment option should be Pay Now or Pay Later/Pay After Service.",
                }
            )
        else:
            missing.append("Payment option (Pay Now or Pay Later)")
    elif payment_option == "Pay Now":
        if not payment_method:
            missing.append("Payment method")
        elif payment_method_defaulted:
            assumptions.append("Payment method defaulted to the QR-code route because the customer asked to proceed without choosing a specific payment method.")
    elif payment_option == "Pay Later / Pay After Service":
        if not (reservation_payment or payment_method):
            missing.append("Reservation payment method")
    if payment_conflicts:
        invalid.extend(payment_conflicts)
    if _payment_selection_is_installment_route(payment_selection):
        if not str(payment_selection.get("bank") or "").strip():
            missing.append("Installment bank")
        if not str(payment_selection.get("installment_months") or "").strip():
            missing.append("Installment term")

    transaction = _api_transaction_for_service_path(service_path, checkout_metadata)
    if service_path and not transaction:
        invalid.append(
            {
                "field": "service_type",
                "value": service_path,
                "reason": "Fulfillment path did not match checkout transaction metadata.",
            }
        )
    api_payment_option = payment_selection.get("payment_option_row") or _api_payment_option(payment_option, checkout_metadata)
    if payment_option and not api_payment_option:
        invalid.append(
            {
                "field": "payment_option",
                "value": payment_option,
                "reason": "Payment option did not match checkout metadata.",
            }
        )
    payment_method_for_submit = str(payment_selection.get("payment_method_for_submit") or payment_method or reservation_payment or balance_payment).strip()
    api_payment_type = payment_selection.get("payment_type_row") or _api_payment_type(
        payment_method_for_submit,
        checkout_metadata,
        payment_option_id=api_payment_option.get("id") if api_payment_option else None,
    )
    if payment_method_for_submit and not api_payment_type:
        invalid.append(
            {
                "field": "payment_method",
                "value": payment_method_for_submit,
                "reason": "Payment method did not match checkout payment metadata.",
            }
        )
    selected_branch = _api_selected_branch(service_location, canonical_values_provider=canonical_values_provider)
    if service_path in {"installation", "pickup"} and selected_partner and not selected_branch:
        invalid.append(
            {
                "field": "selected_installation_partner",
                "value": selected_partner,
                "reason": "Installation partner must come from a grounded service observation with a branch id.",
            }
        )
    schedule_parts: Dict[str, str] = {}
    if service_path in {"installation", "pickup", "home_service"} and schedule:
        schedule_parts = _api_schedule_parts(schedule)
        if not schedule_parts and service_path in {"installation", "pickup"}:
            schedule_parts = _schedule_parts_from_text_against_validated_slot(schedule, validated_slot_context)
        if schedule_parts and service_path in {"installation", "pickup"} and validated_slot_context:
            validated_parts = validated_slot_context.get("schedule_parts") or {}
            if validated_parts and not _schedule_parts_equal(schedule_parts, validated_parts):
                invalid.append(
                    {
                        "field": "schedule",
                        "value": str(schedule),
                        "reason": "Schedule conflicts with the latest validated installation slot.",
                    }
                )
            elif validated_parts:
                schedule = _validated_slot_schedule_display(validated_slot_context)
        if not schedule_parts:
            invalid.append(
                {
                    "field": "schedule",
                    "value": schedule,
                    "reason": "Schedule must be a validated date/time before order payload submission.",
                }
            )
        elif service_path in {"installation", "pickup"} and not _has_validated_slot_context(
            service_observation_store,
            service_location_ref=payload.get("service_location_ref") or payload.get("installation_partner_ref"),
            schedule_parts=schedule_parts,
        ):
            invalid.append(
                {
                    "field": "schedule",
                    "value": str(schedule),
                    "reason": "Installation schedule must come from validate_installation_slot before order payload submission.",
                }
            )
    elif service_path in {"installation", "pickup"} and validated_slot_context:
        schedule_parts = deepcopy(validated_slot_context.get("schedule_parts") or {})
        schedule = _validated_slot_schedule_display(validated_slot_context)
    has_validated_schedule_context = bool(
        service_path in {"installation", "pickup"}
        and schedule_parts
        and _has_validated_slot_context(
            service_observation_store,
            service_location_ref=payload.get("service_location_ref") or payload.get("installation_partner_ref"),
            schedule_parts=schedule_parts,
        )
    )

    checkout_plan = resolve_checkout_plan(
        stage="payload",
        selected_product=selected_product,
        quantity=quantity,
        service_path=service_path,
        location=location,
        delivery_address=delivery_address,
        service_location=service_location,
        schedule=schedule,
        has_validated_slot=has_validated_schedule_context,
        quote_breakdown=quote_breakdown,
        payment_selection=payment_selection,
        checkout_metadata=checkout_metadata,
        service_compatibility=_service_compatibility_context(latest_service),
    )
    if checkout_plan.get("blockers"):
        invalid.extend(_checkout_plan_invalid_fields(checkout_plan))
    for item in checkout_plan.get("advisories") or []:
        if isinstance(item, dict) and item.get("reason"):
            validation.append(str(item.get("reason")))

    missing = _unique(missing)
    invalid = _unique_invalid_fields(invalid)
    validation = _unique([item for item in validation if item])
    assumptions = _unique(assumptions)

    source_refs = _order_payload_source_refs(
        payload=payload,
        latest_product=latest_product,
        latest_service=latest_service,
        service_location=service_location,
        quote_ref=str(quote_result.get("quote_ref") or ""),
    )
    order_payload: Dict[str, Any] = {}
    normalized_payload = _runtime_v7_normalized_order_payload(
        selected_product=selected_product,
        quantity=quantity or 0,
        service_path=service_path,
        service_reason=service_reason,
        location=location,
        delivery_address=delivery_address,
        selected_partner=selected_partner,
        service_location=service_location,
        schedule=schedule,
        contact_number=contact_number,
        customer_name=customer_name,
        first_name=first_name,
        last_name=last_name,
        email=email,
        invoice=invoice,
        payment_option=payment_option,
        payment_method=payment_method,
        reservation_payment=reservation_payment,
        balance_payment=balance_payment,
        payment_selection=payment_selection,
        quote_breakdown=quote_breakdown,
        source_refs=source_refs,
    ) if selected_product else {}
    if selected_product and not missing and not invalid:
        order_payload = _runtime_v7_order_api_payload(
            selected_product=selected_product,
            quantity=quantity,
            service_path=service_path,
            service_reason=service_reason,
            location=location,
            delivery_address=delivery_address,
            selected_branch=selected_branch,
            schedule_parts=schedule_parts,
            schedule=schedule,
            contact_number=contact_number,
            customer_name=customer_name,
            first_name=first_name,
            last_name=last_name,
            email=email,
            invoice=invoice,
            transaction=transaction,
            payment_option_row=api_payment_option,
            payment_type_row=api_payment_type,
            payment_method=payment_method_for_submit,
            quote_breakdown=quote_breakdown,
            source_refs=source_refs,
            payload=payload,
            canonical_values_provider=canonical_values_provider,
        )

    payload_ref = _order_payload_ref(order_payload) if order_payload else ""
    status = "ready" if order_payload else "needs_clarification" if selected_product or missing or invalid else "not_started"
    return {
        "status": status,
        "order_payload_ref": payload_ref,
        "order_readiness_status": readiness_payload.get("status"),
        "customer_order_intent": readiness_payload.get("customer_order_intent"),
        "selected_product": _quote_product_summary(selected_product) if selected_product else {},
        "quantity": quantity or None,
        "quantity_defaulted": bool(quantity_is_default and quantity),
        "service_path": service_path,
        "payment_option": payment_option,
        "payment_method": payment_method_for_submit,
        "payment_bank": payment_selection.get("bank") or "",
        "installment_months": payment_selection.get("installment_months") or "",
        "quote_summary": quote_result.get("quote_summary") or {},
        "missing_fields": missing,
        "invalid_fields": invalid,
        "checkout_plan": checkout_plan,
        "assumptions": assumptions,
        "validation": validation,
        "source_refs": source_refs,
        "customer_explanation_hints": _order_payload_hints(
            status=status,
            missing=missing,
            invalid=invalid,
            service_path=service_path,
        ),
        "order_payload": order_payload,
        "normalized_order_payload": normalized_payload,
        "read_only": True,
        "can_submit_order": bool(order_payload),
        "note": "Read-only validation payload. This does not create an order, booking, reservation, payment, or schedule confirmation.",
    }


def submit_order(
    *,
    payload: Optional[Dict[str, Any]] = None,
    order_payload_store: Optional[Mapping[str, Dict[str, Any]]] = None,
    http_client: Any = None,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Dict[str, Any]:
    """Submit a previously validated Runtime V7 order payload to `/order`.

    The caller must pass an `order_payload_ref` stored from build_order_payload
    or a direct API-shaped `order_payload`. This function does not rebuild from
    form fields; it posts the validated `{data, newCartItems}` payload as-is.
    """

    payload = dict(payload or {})
    order_payload_ref = str(payload.get("order_payload_ref") or "").strip()
    stored_payloads = order_payload_store or {}
    order_payload = payload.get("order_payload")
    if not isinstance(order_payload, dict) or not order_payload:
        order_payload = deepcopy(stored_payloads.get(order_payload_ref) or {})
    if not order_payload_ref and isinstance(order_payload, dict) and order_payload:
        order_payload_ref = _order_payload_ref(order_payload)
    order_payload = hydrate_order_api_payload_for_submit(
        order_payload,
        canonical_values_provider=canonical_values_provider,
    )

    invalid = _validate_order_api_payload(order_payload)
    if invalid:
        return {
            "status": "needs_order_payload",
            "order_payload_ref": order_payload_ref,
            "invalid_fields": invalid,
            "missing_fields": [item["field"] for item in invalid if item.get("reason") == "missing_required"],
            "can_request_payment": False,
            "order_submitted": False,
            "read_only": False,
            "note": "Submit requires a validated API-shaped order payload from build_order_payload.",
        }
    if http_client is None or not hasattr(http_client, "post_json"):
        return {
            "status": "error",
            "order_payload_ref": order_payload_ref,
            "error_type": "missing_http_client",
            "message": "Order submit HTTP client is not configured.",
            "can_request_payment": False,
            "order_submitted": False,
            "order_payload": order_payload,
            "read_only": False,
        }

    try:
        api_response = http_client.post_json("/order", json_data=order_payload)
    except Exception as exc:
        return {
            "status": "error",
            "order_payload_ref": order_payload_ref,
            "error_type": exc.__class__.__name__,
            "message": str(exc) or "submit_order_failed",
            "can_request_payment": False,
            "order_submitted": False,
            "order_payload": order_payload,
            "read_only": False,
        }

    api_response = api_response if isinstance(api_response, dict) else {"response": api_response}
    order_id = _order_id_from_submit_response(api_response)
    success = _looks_like_submit_success(api_response)
    amount_mismatch = _submitted_order_amount_mismatch(order_payload, api_response)
    return {
        "status": "success" if success else "error",
        "order_payload_ref": order_payload_ref,
        "order_id": order_id,
        "api_response": api_response,
        "submitted_at": datetime.now(tz=MANILA_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "can_request_payment": bool(success and order_id),
        "order_submitted": bool(success),
        "amount_mismatch": amount_mismatch,
        "order_payload": order_payload,
        "read_only": False,
        "message": "" if success else str(api_response.get("message") or api_response.get("content") or "submit_order_failed"),
        "note": "Order submit tool posts a previously validated Runtime V7 payload directly to /order.",
    }


def hydrate_order_api_payload_for_submit(
    order_payload: Any,
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Dict[str, Any]:
    """Hydrate stored V7 payload refs with full catalog rows before `/order`.

    Older payload refs may have been created from compact product/service
    observations. The submit boundary keeps the validated customer/order fields
    but refreshes cart and branch objects from the API-backed catalog provider
    when available, matching the shape accepted by the Gulong order endpoint.
    """

    if not isinstance(order_payload, dict) or not order_payload:
        return {}
    hydrated = deepcopy(order_payload)
    data = hydrated.get("data") if isinstance(hydrated.get("data"), dict) else {}
    items = hydrated.get("newCartItems") if isinstance(hydrated.get("newCartItems"), list) else []
    if items and isinstance(items[0], dict):
        original = items[0]
        product_id = original.get("product_id") or original.get("id")
        quantity = _coerce_int(original.get("selected_quantity") or original.get("quantity"), default=1, minimum=1, maximum=99)
        catalog_product = _provider_product_by_id(canonical_values_provider, product_id)
        if catalog_product:
            hydrated["newCartItems"][0] = _api_cart_item(
                catalog_product,
                quantity=quantity,
                now=datetime.now(tz=MANILA_TZ),
                canonical_values_provider=canonical_values_provider,
            )
    if data:
        selected = data.get("selectedBranch") if isinstance(data.get("selectedBranch"), dict) else {}
        branch_id = data.get("branch") or selected.get("id") or selected.get("branch_id")
        catalog_branch = _provider_branch_by_id(canonical_values_provider, branch_id)
        if catalog_branch:
            data["selectedBranch"] = catalog_branch
            data["branch"] = catalog_branch.get("id") or branch_id
            data["area"] = catalog_branch.get("area") or data.get("area")
    return hydrated


def get_order_details(
    *,
    payload: Optional[Dict[str, Any]] = None,
    http_client: Any = None,
) -> Dict[str, Any]:
    """Fetch read-only order status/details from the Gulong `/order_details` endpoint."""

    payload = dict(payload or {})
    order_id = _order_id_for_details(payload)
    if not order_id:
        return {
            "status": "needs_order_id",
            "missing_fields": ["order_id"],
            "read_only": True,
            "note": "Order details lookup requires a submitted order id/order number.",
        }
    if http_client is None or not hasattr(http_client, "post_json"):
        return {
            "status": "error",
            "order_id": order_id,
            "error_type": "missing_http_client",
            "message": "Order details HTTP client is not configured.",
            "read_only": True,
        }

    try:
        api_response = http_client.post_json("/order_details", json_data={"order_id": order_id})
    except Exception as exc:
        return {
            "status": "error",
            "order_id": order_id,
            "error_type": exc.__class__.__name__,
            "message": str(exc) or "order_details_lookup_failed",
            "read_only": True,
        }

    record = _order_details_record(api_response)
    if not record:
        return {
            "status": "not_found",
            "order_id": order_id,
            "message": _order_details_error_message(api_response),
            "read_only": True,
        }
    summary = _compact_order_details(record, requested_order_id=order_id)
    return {
        "status": "ok",
        "order_id": summary.get("order_id") or order_id,
        "order_status": summary.get("order_status"),
        "payment_status": summary.get("payment_status"),
        "unpaid_order_status": summary.get("unpaid_order_status"),
        "transaction": summary.get("transaction") or {},
        "fulfillment": summary.get("fulfillment") or {},
        "payment": summary.get("payment") or {},
        "totals": summary.get("totals") or {},
        "items": summary.get("items") or [],
        "order_details": summary,
        "source": "/order_details",
        "read_only": True,
    }


def prepare_payment_request(
    *,
    payload: Optional[Dict[str, Any]] = None,
    order_payload_store: Optional[Mapping[str, Dict[str, Any]]] = None,
    payment_request_store: Optional[Mapping[str, Dict[str, Any]]] = None,
    http_client: Any = None,
) -> Dict[str, Any]:
    """Build exact payment instructions for a submitted Runtime V7 order."""

    payload = dict(payload or {})
    order_payload_ref = str(payload.get("order_payload_ref") or "").strip()
    stored_payloads = order_payload_store or {}
    order_payload = payload.get("order_payload")
    if (not isinstance(order_payload, dict) or not order_payload) and order_payload_ref:
        order_payload = deepcopy(stored_payloads.get(order_payload_ref) or {})
    if not isinstance(order_payload, dict) or not order_payload:
        order_payload = {}
    if not order_payload_ref and order_payload:
        order_payload_ref = _order_payload_ref(order_payload)

    order_id = _payment_order_id(payload, payment_request_store)
    if not order_id:
        return {
            "status": "needs_order_id",
            "missing_fields": ["order_id"],
            "order_payload_ref": order_payload_ref,
            "read_only": False,
            "note": "Payment request needs a submitted order id from submit_order or existing order context.",
        }
    invalid = _validate_order_api_payload(order_payload)
    if invalid:
        return {
            "status": "needs_order_payload",
            "order_id": order_id,
            "order_payload_ref": order_payload_ref,
            "invalid_fields": invalid,
            "missing_fields": [item["field"] for item in invalid if item.get("reason") == "missing_required"],
            "read_only": False,
            "note": "Payment request needs the validated order payload used for submit_order.",
        }

    data = order_payload.get("data") if isinstance(order_payload.get("data"), dict) else {}
    payment_selection = _payment_request_selection(payload, data)
    if payment_selection.get("status") in {"conflict", "unsupported"}:
        invalid_fields = list(payment_selection.get("invalid_fields") or [])
        return {
            "status": "needs_payment_clarification",
            "order_id": order_id,
            "order_payload_ref": order_payload_ref,
            "payment_option": payment_selection.get("payment_option"),
            "payment_method": payment_selection.get("payment_method")
            or payment_selection.get("payment_method_for_submit"),
            "invalid_fields": invalid_fields,
            "missing_fields": [item.get("field") for item in invalid_fields if isinstance(item, dict) and item.get("field")],
            "read_only": False,
            "note": "Payment request needs a coherent payment option and payment method before rendering exact instructions.",
        }
    payment_option = str(payment_selection.get("payment_option") or _payment_request_option(payload, data)).strip()
    payment_method = str(
        payment_selection.get("payment_method_for_submit")
        or payment_selection.get("payment_method")
        or _payment_request_method(payload, data)
    ).strip()
    stage, expected_amount = _payment_stage_and_amount(
        payload,
        data,
        payment_option=payment_option,
        payment_method=payment_method,
    )
    order_details_context = _payment_order_details_context(order_id, http_client)
    persisted_total = _payment_expected_amount_from_order_details(
        order_details_context,
        payment_stage=stage,
    )
    payload_expected_amount = expected_amount
    amount_mismatch = _payment_request_amount_mismatch(
        payload_expected_amount,
        persisted_total,
        source="/order_details",
    )
    if persisted_total is not None:
        expected_amount = persisted_total
        data = deepcopy(data)
        data["total"] = persisted_total
    if expected_amount is None:
        return {
            "status": "needs_expected_amount",
            "order_id": order_id,
            "order_payload_ref": order_payload_ref,
            "payment_option": payment_option,
            "payment_method": payment_method,
            "missing_fields": ["expected_payment_amount"],
            "read_only": False,
            "note": "Payment request needs a trusted amount from the submitted order payload.",
        }

    payment_options = _load_payment_options()
    qr_image = _payment_qr_image(payment_options)
    manual_details = _payment_manual_details(payment_options)
    instruction_mode = _normalize_text(payload.get("payment_instruction_mode") or payload.get("instruction_mode"))
    route = _payment_instruction_route(payment_method, instruction_mode=instruction_mode)
    payment_link: Dict[str, Any] = {}
    link_error = ""
    if route == "payment_link":
        payment_link, link_error = _create_2c2p_payment_link(
            order_id=order_id,
            order_payload=order_payload,
            expected_amount=expected_amount,
            http_client=http_client,
        )

    if route == "payment_link" and payment_link:
        instruction_type = "payment_link_with_manual_fallback" if manual_details else "payment_link"
        primary_method = "2c2p_payment_link"
    elif route == "payment_link" and link_error:
        instruction_type = "payment_link_error_with_manual_fallback" if manual_details or qr_image else "payment_link_error"
        primary_method = "manual_fallback"
    else:
        instruction_type = "qr_code_with_account_details" if manual_details else "qr_code"
        primary_method = "qr_code"

    amount_breakdown = _payment_amount_breakdown(data, expected_amount)
    request_payload = {
        "order_id": order_id,
        "order_payload_ref": order_payload_ref,
        "payment_stage": stage,
        "expected_amount": expected_amount,
        "amount_breakdown": amount_breakdown,
        "payment_option": payment_option,
        "payment_method": payment_method,
        "payment_bank": payment_selection.get("bank") or "",
        "installment_months": payment_selection.get("installment_months") or "",
        "order_details_context": order_details_context,
        "instruction_type": instruction_type,
        "primary_method": primary_method,
        "payment_link": payment_link,
        "qr_image": qr_image,
        "manual_details": manual_details,
    }
    payment_request_ref = _payment_request_ref(request_payload)
    surface_ref = f"pres_payment_request_{payment_request_ref.removeprefix('payment_request_')}"
    return {
        "status": "ok" if "error" not in instruction_type else "payment_link_error",
        "payment_request_ref": payment_request_ref,
        "presentation_ref": surface_ref,
        "order_id": order_id,
        "order_payload_ref": order_payload_ref,
        "payment_stage": stage,
        "expected_amount": expected_amount,
        "expected_amount_text": _money_text(expected_amount),
        "amount_breakdown": amount_breakdown,
        "amount_source": "order_details" if persisted_total is not None else "order_payload",
        "amount_mismatch": amount_mismatch,
        "order_details_context": order_details_context,
        "payment_option": payment_option,
        "payment_method": payment_method,
        "payment_bank": payment_selection.get("bank") or "",
        "installment_months": payment_selection.get("installment_months") or "",
        "payment_instruction_type": instruction_type,
        "primary_method": primary_method,
        "payment_link": payment_link,
        "qr_image": qr_image,
        "manual_details": manual_details,
        "link_error": link_error,
        "payment_instruction_block": _payment_instruction_block(
            order_id=order_id,
            payment_stage=stage,
            expected_amount=expected_amount,
            amount_breakdown=amount_breakdown,
            amount_mismatch=amount_mismatch,
            instruction_type=instruction_type,
            primary_method=primary_method,
            payment_link=payment_link,
            qr_image=qr_image,
            manual_details=manual_details,
            link_error=link_error,
        ),
        "runtime_renders_body": True,
        "can_accept_payment_proof": True,
        "read_only": False,
        "note": "Payment instruction output is exact runtime-owned payment data. The model should not rewrite links, QR URLs, account numbers, or amounts.",
    }


def match_payment_proof(
    *,
    payload: Optional[Dict[str, Any]] = None,
    external_evidence_refs: Optional[Sequence[Dict[str, Any]]] = None,
    payment_request_store: Optional[Mapping[str, Dict[str, Any]]] = None,
    order_payload_store: Optional[Mapping[str, Dict[str, Any]]] = None,
    http_client: Any = None,
) -> Dict[str, Any]:
    """Match a payment-proof image evidence ref to the current payment request."""

    payload = dict(payload or {})
    evidence = _payment_evidence_from_refs(payload, external_evidence_refs or [])
    if not evidence:
        return {
            "status": "needs_payment_proof",
            "missing_fields": ["payment_proof_evidence_ref"],
            "read_only": True,
            "note": "No payment_proof image evidence is available to match.",
        }
    analysis = evidence.get("analysis") if isinstance(evidence.get("analysis"), dict) else {}
    payment_request = _payment_request_from_store(payload, payment_request_store)
    order_payload = _payment_match_order_payload(payload, payment_request, order_payload_store)
    order_id = (
        str(payload.get("order_id") or "").strip()
        or str(analysis.get("order_id") or analysis.get("invoice_no") or "").strip()
        or str(payment_request.get("order_id") or "").strip()
    )
    extracted_amount = _coerce_money(analysis.get("amount"))
    expected_amount = _coerce_float(payload.get("expected_amount")) or _coerce_float(payment_request.get("expected_amount"))
    amount_match = _amount_matches(extracted_amount, expected_amount)
    method = str(analysis.get("payment_method") or "").strip()
    reference_no = str(analysis.get("reference_no") or "").strip()
    paid_at = str(analysis.get("paid_at") or "").strip()
    status = "matched_unverified"
    clarifications: List[str] = []
    mismatches: List[Dict[str, str]] = []
    if extracted_amount is None:
        clarifications.append("payment amount")
    elif expected_amount is not None and not amount_match:
        status = "not_matched"
        mismatches.append(
            {
                "field": "amount",
                "value": _money_text(extracted_amount),
                "expected": _money_text(expected_amount),
                "reason": "screenshot amount does not match expected payment amount",
            }
        )
    if not reference_no:
        clarifications.append("payment reference number")
    if not order_id and not payment_request:
        clarifications.append("order id")
    backend_payment_status = ""
    if order_id and http_client is not None and hasattr(http_client, "post_json"):
        details = get_order_details(payload={"order_id": order_id}, http_client=http_client)
        backend_payment_status = str(details.get("payment_status") or "").strip()
        if backend_payment_status.lower() in {"paid", "settled", "completed"}:
            status = "verified_paid"
    if status != "not_matched" and clarifications:
        status = "needs_verification"

    return {
        "status": status,
        "payment_proof_received": True,
        "evidence_ref": evidence.get("evidence_ref"),
        "order_id": order_id,
        "payment_request_ref": payment_request.get("payment_request_ref"),
        "payment_stage": payment_request.get("payment_stage"),
        "expected_amount": expected_amount,
        "expected_amount_text": _money_text(expected_amount) if expected_amount is not None else "",
        "extracted_amount": extracted_amount,
        "extracted_amount_text": _money_text(extracted_amount) if extracted_amount is not None else "",
        "amount_match": amount_match,
        "payment_method": method,
        "reference_no": reference_no,
        "paid_at": paid_at,
        "merchant": analysis.get("merchant"),
        "backend_payment_status": backend_payment_status,
        "missing_fields": clarifications,
        "mismatches": mismatches,
        "customer_explanation_hints": _payment_proof_hints(status, clarifications, mismatches),
        "order_payload_ref": payment_request.get("order_payload_ref") or payload.get("order_payload_ref"),
        "order_payload_available": bool(order_payload),
        "read_only": True,
        "note": "Screenshot proof is matched but remains unverified unless backend payment status confirms paid.",
    }


def build_order_readiness(
    *,
    current_user_message: str = "",
    active_working_memory: str = "",
    background_signals: Optional[Sequence[Dict[str, Any]]] = None,
    product_observation_store: Optional[ProductObservationStore] = None,
    service_observation_store: Optional[ServiceObservationStore] = None,
    selected_product_context: Optional[Dict[str, Any]] = None,
    choice_action_history: Optional[Sequence[Dict[str, Any]]] = None,
    previous_order_summary_snapshot: Optional[Dict[str, Any]] = None,
    canonical_values_provider: Optional[
        CanonicalValuesProvider
    ] = None,
) -> OrderReadiness:
    """Build deterministic order readiness from normalized state and observations."""

    signals = _signals_by_key(background_signals or [])
    latest_product = product_observation_store.latest() if product_observation_store else None
    latest_service = service_observation_store.latest() if service_observation_store else None
    latest_service_presentation = service_observation_store.latest_presentation() if service_observation_store else None

    selected_product, product_reason = _selected_product_from_summary_payload(
        selected_product_context or {},
        product_observation_store,
    )
    if not selected_product:
        selected_product, product_reason = _selected_product(
            latest_product,
            signals,
        )
    quantity, quantity_is_default = _quantity_with_summary_continuity(
        signals,
        default_allowed=bool(selected_product),
        selected_product=selected_product,
        previous_order_summary_snapshot=previous_order_summary_snapshot,
    )
    trusted_total = _trusted_total(selected_product, quantity=quantity) if selected_product else None
    product_label = _product_label(selected_product) if selected_product else ""

    service_path, service_path_reason = _fulfillment_path(signals)
    location = _signal_value(signals, "location")
    delivery_address = _signal_value(signals, "delivery_address")
    contact_number = _signal_value(signals, "contact_number")
    first_name = _signal_value(signals, "first_name")
    last_name = _signal_value(signals, "last_name")
    email = _signal_value(signals, "email_address")
    selected_partner = _signal_value(signals, "selected_installation_partner")
    selected_slot = _signal_value(signals, "chosen_schedule_slot")
    validated_slot_context = _latest_validated_slot_context(service_observation_store)
    has_validated_selected_slot = bool(service_path in {"installation", "pickup"} and validated_slot_context)
    flexible_schedule_choice = _matching_flexible_schedule_choice(
        choice_action_history or [],
        selected_slot=selected_slot,
    )
    schedule_status = ""
    submission_blockers: List[str] = []
    if has_validated_selected_slot and not selected_partner:
        selected_partner = str(
            (validated_slot_context.get("service_location") or {}).get("name")
            or ""
        ).strip()
    reservation_payment = _signal_value(signals, "reservation_payment_method")
    balance_payment = _signal_value(signals, "balance_payment_method")
    payment_method = _signal_value(signals, "payment_method")
    validated_checkout_choice = any(
        _signal_has_validated_checkout_choice_ref(
            signals.get(key) or {}
        )
        for key in (
            "payment_option",
            "payment_method",
            "reservation_payment_method",
            "balance_payment_method",
            "installment_months",
        )
    )
    payment_selection = resolve_payment_selection(
        payment_option=_signal_value(signals, "payment_option"),
        payment_method=payment_method,
        reservation_payment_method=reservation_payment,
        balance_payment_method=balance_payment,
        bank=_signal_value(signals, "bank"),
        installment_months=_signal_value(signals, "installment_months"),
        metadata=_checkout_metadata(
            canonical_values_provider
            if validated_checkout_choice
            else None
        ),
    )
    payment_option = str(payment_selection.get("payment_option") or "").strip()
    payment_method = str(payment_selection.get("payment_method") or payment_method or "").strip()
    reservation_payment = str(payment_selection.get("reservation_payment_method") or "").strip()
    balance_payment = str(payment_selection.get("balance_payment_method") or "").strip()
    payment_bank = str(payment_selection.get("bank") or "").strip()
    installment_months = str(payment_selection.get("installment_months") or "").strip()

    intent = _customer_order_intent(
        signals=signals,
        selected_product=bool(selected_product),
    )
    high_intent_signals = _high_intent_signals(
        signals=signals,
        selected_product=bool(selected_product),
        service_path=service_path,
        selected_slot=selected_slot,
    )
    if _is_not_started_order_state(
        signals=signals,
        intent=intent,
        selected_product=bool(selected_product),
        high_intent_signals=high_intent_signals,
    ):
        return OrderReadiness(
            status="not_started",
            customer_order_intent="none",
            can_prepare_order_summary=False,
        )

    collected: Dict[str, str] = {}
    assumptions: List[str] = []
    validation: List[str] = []
    missing: List[str] = []

    if selected_product:
        collected["Product"] = product_label or "selected product from latest trusted product observation"
        validation.append(product_reason)
    elif latest_product and len(latest_product.product_cards) > 1:
        collected["Product options"] = (
            f"{len(latest_product.product_cards)} current product candidates"
        )
        missing.append("Selected product/SKU")
    else:
        missing.append("Selected product/SKU")

    if selected_product:
        collected["Quantity"] = f"{quantity} tires" + (" (assumed default)" if quantity_is_default else "")
        if quantity_is_default:
            assumptions.append("Quantity defaults to 4 tires unless the customer says otherwise.")
    elif _signal_value(signals, "quantity"):
        collected["Quantity"] = f"{quantity} tires"

    if trusted_total is not None:
        collected["Trusted total"] = _money_text(trusted_total)
        validation.append("Total is derived from trusted product observation pricing and quantity.")
    elif selected_product:
        missing.append("Trusted customer-facing price/total")

    if service_path:
        collected["Fulfillment"] = service_path_reason or service_path
    else:
        missing.append("Fulfillment path or delivery/installation area")

    if service_path == "delivery":
        if delivery_address:
            collected["Delivery address"] = delivery_address
        elif location:
            collected["Delivery area"] = location
            if intent in {"active", "high"}:
                missing.append("Complete delivery address")
            else:
                assumptions.append("Delivery address is still partial; exact address can be collected later.")
        else:
            missing.append("Delivery area/address")

    if service_path == "installation":
        if location:
            collected["Installation area"] = location
        else:
            missing.append("Installation area/location")
        if selected_partner:
            collected["Installation partner"] = selected_partner
        elif latest_service_presentation and latest_service_presentation.installation_partner_cards:
            collected["Installation partner status"] = "partner options shown, not yet chosen"
        if selected_slot and has_validated_selected_slot:
            schedule_status = "exact_validated"
            collected["Installation schedule"] = selected_slot
        elif selected_slot and flexible_schedule_choice:
            schedule_status = "flexible_preference"
            collected["Preferred installation schedule"] = (
                _flexible_schedule_choice_display(flexible_schedule_choice)
                or selected_slot
            )
            submission_blockers.append(
                "Exact installation partner and schedule must be validated before order submission."
            )
            validation.append(
                "The validated flexible schedule choice is sufficient for order-summary review, "
                "but it does not book or authorize an exact installation slot."
            )
        elif selected_slot:
            schedule_status = "unvalidated"
            collected["Preferred installation schedule"] = selected_slot
            if intent in {"active", "high"}:
                missing.append("Validated installation schedule")
            validation.append("Preferred installation schedule is not a booking or submit-ready schedule until validate_installation_slot grounds it.")
        elif intent in {"active", "high"}:
            schedule_status = "missing"
            missing.append("Selected installation schedule")

    if contact_number:
        collected["Contact number"] = contact_number
    elif intent in {"active", "high"}:
        missing.append("Contact number")

    if first_name:
        collected["First name"] = first_name
    elif intent in {"active", "high"}:
        missing.append("First name")
    if last_name:
        collected["Last name"] = last_name
    elif intent in {"active", "high"}:
        missing.append("Last name")
    if email:
        collected["Email address"] = email
    elif intent in {"active", "high"}:
        missing.append("Email address")

    if payment_option:
        collected["Payment option"] = payment_option
    elif intent in {"active", "high"}:
        missing.append("Payment option (Pay Now or Pay Later)")
    if reservation_payment:
        collected["Reservation payment method"] = reservation_payment
    if balance_payment:
        collected["Balance payment method"] = balance_payment
    elif payment_method and not reservation_payment:
        collected["Payment method"] = payment_method
    if (
        intent in {"active", "high"}
        and payment_option == "Pay Later / Pay After Service"
        and not reservation_payment
        and not (
            payment_method
            and payment_selection.get("payment_type_row")
        )
    ):
        missing.append("Reservation payment method")
    if payment_bank:
        collected["Payment bank"] = payment_bank
    if installment_months:
        collected["Installment term"] = f"{installment_months} months"
    if _payment_selection_is_installment_route(payment_selection):
        if not payment_bank:
            missing.append("Installment bank")
        if not installment_months:
            missing.append("Installment term")

    missing = _unique(missing)
    validation = _unique([item for item in validation if item])
    assumptions = _unique(assumptions)
    if latest_service:
        validation.append(
            "Latest service observation is read-only context and is not a booking confirmation."
        )

    status = _readiness_status(
        selected_product=bool(selected_product),
        missing=missing,
        intent=intent,
        has_any_order_context=bool(collected or high_intent_signals),
    )
    return OrderReadiness(
        status=status,
        customer_order_intent=intent,
        can_prepare_order_summary=status == "ready_for_summary",
        high_intent_signals=high_intent_signals,
        collected=collected,
        missing=missing,
        assumptions=assumptions,
        validation=validation,
        schedule_status=schedule_status,
        submission_blockers=_unique(submission_blockers),
    )


def format_order_readiness(readiness: Optional[Dict[str, Any] | OrderReadiness]) -> str:
    """Render order readiness as a compact context block."""

    if readiness is None:
        return "(none)"
    payload = readiness.to_dict() if isinstance(readiness, OrderReadiness) else dict(readiness)
    status = str(payload.get("status") or "not_started")
    intent = str(payload.get("customer_order_intent") or "none")
    lines = [
        f"Status: {status}",
        f"Customer order intent: {intent}",
        f"Can prepare order summary: {'yes' if payload.get('can_prepare_order_summary') else 'no'}",
    ]
    high_intent = [str(item) for item in payload.get("high_intent_signals") or [] if str(item).strip()]
    if high_intent:
        lines.append("High intent signals: " + ", ".join(high_intent[:5]))
    collected = payload.get("collected") if isinstance(payload.get("collected"), dict) else {}
    if collected:
        lines.append("")
        lines.append("Collected:")
        for key, value in collected.items():
            if value not in (None, ""):
                lines.append(f"- {key}: {value}")
    missing = [str(item) for item in payload.get("missing") or [] if str(item).strip()]
    if missing:
        lines.append("")
        lines.append("Missing:")
        for item in missing[:8]:
            lines.append(f"- {item}")
    assumptions = [str(item) for item in payload.get("assumptions") or [] if str(item).strip()]
    if assumptions:
        lines.append("")
        lines.append("Assumptions:")
        for item in assumptions[:4]:
            lines.append(f"- {item}")
    validation = [str(item) for item in payload.get("validation") or [] if str(item).strip()]
    if validation:
        lines.append("")
        lines.append("Validation:")
        for item in validation[:5]:
            lines.append(f"- {item}")
    submission_blockers = [
        str(item)
        for item in payload.get("submission_blockers") or []
        if str(item).strip()
    ]
    if submission_blockers:
        lines.append("")
        lines.append("Submission blockers:")
        for item in submission_blockers[:4]:
            lines.append(f"- {item}")
    return "\n".join(lines)


def _signals_by_key(signals: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    by_key: Dict[str, Dict[str, Any]] = {}
    for signal in signals:
        if not isinstance(signal, dict):
            continue
        key = str(signal.get("key") or "").strip()
        value = signal.get("value")
        if not key or value in (None, "", []):
            continue
        by_key[key] = dict(signal)
    return by_key


def _signal_has_validated_checkout_choice_ref(
    signal: Dict[str, Any],
) -> bool:
    """Recognize delivered or typed checkout authority after validation."""

    if not isinstance(signal, dict) or not signal_has_durable_authority(signal):
        return False
    metadata = (
        signal.get("metadata")
        if isinstance(signal.get("metadata"), dict)
        else {}
    )
    choice_ref = str(metadata.get("choice_ref") or "").strip()
    presentation_ref = str(
        metadata.get("presentation_ref") or ""
    ).strip()
    normalization = (
        metadata.get("normalization")
        if isinstance(metadata.get("normalization"), dict)
        else {}
    )
    ledger = (
        metadata.get("ledger")
        if isinstance(metadata.get("ledger"), dict)
        else {}
    )
    source = str(signal.get("source") or "").strip()
    status = str(signal.get("status") or "").strip()
    if source == "signal_ledger":
        source = str(ledger.get("authority_source") or source).strip()
        status = str(ledger.get("authority_status") or status).strip()
    # The guided-choice handler writes this provenance only after the customer
    # clicked a delivered allowlisted surface.  Refs by themselves are not
    # authority because a model or external artifact can reproduce their
    # shape.
    if source == "validated_choice_action":
        return bool(
            status == "tool_grounded"
            and choice_ref.startswith(("option_", "method_"))
            and presentation_ref.startswith(
                ("pres_payment_options_", "pres_payment_methods_")
            )
        )
    return bool(
        source == "latest_user_message"
        and status
        not in {
            "mentioned_unconfirmed",
            "invalid",
            "rejected",
            "superseded",
        }
        and str(normalization.get("status") or "").strip()
        == "checkout_metadata_canonicalized"
        and isinstance(normalization.get("payment_type"), dict)
        and normalization["payment_type"].get("id") not in (None, "")
    )


def _selected_product_from_summary_payload(
    payload: Dict[str, Any],
    store: Optional[ProductObservationStore],
) -> Tuple[Dict[str, Any], str]:
    if store is None:
        return {}, ""
    observation = store.get(
        observation_ref=payload.get("product_observation_ref") or payload.get("observation_ref"),
        presentation_ref=payload.get("product_presentation_ref") or payload.get("presentation_ref"),
    )
    if observation is None:
        observation = store.latest()
    if observation is None:
        return {}, ""
    criteria = {
        "card_ref": payload.get("product_card_ref") or payload.get("card_ref"),
        "item_ref": payload.get("product_item_ref") or payload.get("item_ref"),
        "product_id": payload.get("product_id"),
        "slug": payload.get("slug"),
    }
    criteria = {key: str(value).strip() for key, value in criteria.items() if value not in (None, "")}
    if not criteria:
        return {}, ""
    for row in _product_rows(observation):
        product = row.get("product") if isinstance(row, dict) else {}
        if not isinstance(product, dict):
            continue
        card = _card_for_product(observation, product)
        merged = {**card, **product}
        if _matches_summary_ref(merged, criteria):
            return deepcopy({**product, **card}), (
                "Product matched from model-provided trusted product reference "
                f"{observation.observation_ref}."
            )
    return {}, ""


def _card_for_product(observation: ProductObservation, product: Dict[str, Any]) -> Dict[str, Any]:
    item_ref = str(product.get("item_ref") or "").strip()
    product_id = str(product.get("product_id") or product.get("id") or "").strip()
    slug = str(product.get("slug") or "").strip()
    for card in observation.product_cards:
        if not isinstance(card, dict):
            continue
        if item_ref and str(card.get("item_ref") or "").strip() == item_ref:
            return card
        if product_id and str(card.get("product_id") or "").strip() == product_id:
            return card
        if slug and str(card.get("slug") or "").strip() == slug:
            return card
    return {}


def _matches_summary_ref(values: Dict[str, Any], criteria: Dict[str, str]) -> bool:
    for key, expected in criteria.items():
        actual_value = values.get(key)
        if key == "product_id" and actual_value in (None, ""):
            actual_value = values.get("id")
        actual = str(actual_value or "").strip()
        if not actual or actual != expected:
            return False
    return True


def _signal_value(signals: Dict[str, Dict[str, Any]], key: str) -> str:
    signal = signals.get(key) or {}
    if not signal_has_durable_authority(signal):
        return ""
    relation = str(signal.get("relation") or "asserted").strip().casefold()
    if relation in {*TRANSIENT_SIGNAL_RELATIONS, "rejected"}:
        return ""
    if key in {
        "payment_option",
        "payment_method",
        "reservation_payment_method",
        "balance_payment_method",
        "bank",
        "installment_months",
    }:
        status = str(signal.get("status") or "").strip().casefold()
        source = str(signal.get("source") or "").strip().casefold()
        metadata = (
            signal.get("metadata")
            if isinstance(signal.get("metadata"), dict)
            else {}
        )
        ledger = (
            metadata.get("ledger")
            if isinstance(metadata.get("ledger"), dict)
            else {}
        )
        authority_status = str(
            ledger.get("authority_status") or ""
        ).strip().casefold()
        authority_source = str(
            ledger.get("authority_source") or ""
        ).strip().casefold()
        if status == "mentioned_unconfirmed":
            return ""
        if source in {
            "active_working_memory",
            "assistant_transcript",
            "assistant_message",
        }:
            return ""
        if source == "signal_ledger":
            if authority_status == "mentioned_unconfirmed":
                return ""
            if authority_source in {
                "active_working_memory",
                "assistant_transcript",
                "assistant_message",
            }:
                return ""
    value = signal.get("value")
    return _clean_order_state_value(value)


def _payload_or_signal(payload: Dict[str, Any], signals: Dict[str, Dict[str, Any]], key: str) -> str:
    value = payload.get(key)
    if value not in (None, "", []):
        return _clean_order_state_value(value)
    return _signal_value(signals, key)


def _customer_location_for_order(
    *,
    payload: Dict[str, Any],
    signals: Dict[str, Dict[str, Any]],
    order_readiness: Dict[str, Any],
    service_path: str,
) -> str:
    """Keep customer area separate from a selected partner's address."""

    if service_path not in {"installation", "pickup", "home_service"}:
        return _payload_or_signal(payload, signals, "location")
    collected = (
        order_readiness.get("collected")
        if isinstance(order_readiness.get("collected"), dict)
        else {}
    )
    for key in (
        "Installation area",
        "Pickup area",
        "Home service area",
        "Location",
    ):
        value = _clean_order_state_value(collected.get(key))
        if value:
            return value
    signal_location = _signal_value(signals, "location")
    if signal_location:
        return signal_location
    return _payload_or_signal(payload, signals, "location")


def _clean_order_state_value(value: Any) -> str:
    """Drop placeholder/refusal tokens before order readiness or payload use."""

    text = str(value or "").strip()
    if not text:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    compact = re.sub(r"[^a-z0-9]+", "", text.lower())
    placeholder_values = {
        "notprovided",
        "notprovidedchat",
        "notprovidedinthechat",
        "notprovidedinchat",
        "toprovide",
        "tobeprovided",
        "tbd",
        "unknown",
        "na",
        "none",
        "null",
        "missing",
    }
    if compact in placeholder_values:
        return ""
    if normalized.startswith("not provided"):
        return ""
    if normalized in {"to be confirmed", "to confirm", "for confirmation", "not available"}:
        return ""
    if text.startswith("[") and text.endswith("]"):
        return ""
    return text


def _payload_with_payment_selection(payload: Dict[str, Any], selection: Dict[str, Any]) -> Dict[str, Any]:
    """Return a payload copy with cross-field payment values aligned."""

    output = dict(payload or {})
    for key in (
        "payment_option",
        "payment_method",
        "payment_method_for_submit",
        "reservation_payment_method",
        "balance_payment_method",
        "bank",
        "installment_months",
    ):
        value = str(selection.get(key) or "").strip()
        if value:
            output[key] = value
        else:
            output.pop(key, None)
    return output


def _payment_option_for_summary(
    *,
    payload: Dict[str, Any],
    signals: Dict[str, Dict[str, Any]],
    reservation_payment: str,
    balance_payment: str,
    payment_method: str,
) -> str:
    explicit = _payload_or_signal(payload, signals, "payment_option")
    normalized = _normalize_payment_option(explicit)
    if normalized:
        return normalized
    if reservation_payment or balance_payment:
        return "Pay Later / Pay After Service"
    if "pay now" in str(payment_method or "").strip().lower():
        return "Pay Now"
    if _payment_method_implies_pay_later(payment_method):
        return "Pay Later / Pay After Service"
    return ""


def _payment_field_conflicts(
    *,
    payment_option: str,
    payment_method: str,
    reservation_payment: str,
    balance_payment: str,
) -> List[Dict[str, str]]:
    """Return conflicts between already-structured payment fields."""

    conflicts: List[Dict[str, str]] = []
    normalized_option = _normalize_payload_payment_option(payment_option)
    method = str(payment_method or "").strip()
    if normalized_option == "Pay Later / Pay After Service":
        if method and _payment_method_implies_pay_now(method) and not (reservation_payment or balance_payment):
            conflicts.append(
                {
                    "field": "payment_option/payment_method",
                    "value": f"{normalized_option} + {method}",
                    "reason": (
                        "Payment method looks like a Pay Now card/installment route, "
                        "but payment option is Pay Later. Clarify or set Pay Now before rendering the summary."
                    ),
                }
            )
    elif normalized_option == "Pay Now":
        if reservation_payment or balance_payment or _payment_method_implies_pay_later(method):
            conflicting_method = reservation_payment or balance_payment or method
            conflicts.append(
                {
                    "field": "payment_option/payment_method",
                    "value": f"{normalized_option} + {conflicting_method}",
                    "reason": (
                        "Payment option is Pay Now, but reservation/COD/balance fields imply Pay Later. "
                        "Clarify the payment path before rendering the summary."
                    ),
                }
            )
    return conflicts


def _payment_method_implies_pay_now(payment_method: str) -> bool:
    text = str(payment_method or "").strip().lower()
    if not text:
        return False
    normalized = re.sub(r"[^a-z0-9]+", "", text)
    return any(
        token in text
        for token in ["credit card", "debit card", "installment", "2c2p"]
    ) or normalized in {"cc", "card", "creditcard", "debitcard"}


def _payment_clarification_result(
    *,
    conflicts: Sequence[Dict[str, str]],
    selected_product: Optional[Dict[str, Any]],
    quantity: Optional[int],
    service_path: str,
    delivery_address: str,
    location: str,
    order_readiness: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "status": "needs_payment_clarification",
        "order_readiness_status": order_readiness.get("status"),
        "customer_order_intent": order_readiness.get("customer_order_intent"),
        "selected_product": _quote_product_summary(selected_product) if selected_product else {},
        "quantity": quantity or None,
        "service_path": service_path,
        "delivery_address": delivery_address,
        "location": location,
        "missing_fields": ["Payment option/method clarification"],
        "invalid_fields": list(conflicts),
        "customer_explanation_hints": [
            "Payment fields conflict. Ask whether the customer wants Pay Now card/installment or Pay Later/COD/reservation before showing the order summary."
        ],
        "card_runtime_insert": False,
        "runtime_renders_body": False,
        "read_only": True,
        "can_submit_order": False,
        "note": "Read-only clarification result. The order summary is not rendered until payment timing and method are aligned.",
    }


def _payment_method_implies_pay_later(payment_method: str) -> bool:
    text = re.sub(r"[^a-z0-9]+", "", str(payment_method or "").strip().lower())
    if text in {"cod", "cashondelivery", "payondelivery"}:
        return True
    lowered = str(payment_method or "").strip().lower()
    return "cash on delivery" in lowered or "pay on delivery" in lowered


def _normalize_payment_option(value: str) -> str:
    return shared_normalize_payment_option(value)


def _normalize_payload_payment_option(value: str) -> str:
    """Return only payment options accepted by the V7 payload boundary."""

    return shared_normalize_payload_payment_option(value)


def _customer_name(payload: Dict[str, Any], signals: Dict[str, Dict[str, Any]]) -> str:
    direct = str(payload.get("customer_name") or "").strip()
    if direct:
        return direct
    first = _payload_or_signal(payload, signals, "first_name")
    last = _payload_or_signal(payload, signals, "last_name")
    return " ".join(part for part in [first, last] if part).strip()


def _customer_name_parts(
    payload: Dict[str, Any],
    signals: Dict[str, Dict[str, Any]],
    customer_name: str,
) -> Tuple[str, str]:
    first = _payload_or_signal(payload, signals, "first_name")
    last = _payload_or_signal(payload, signals, "last_name")
    parts = [part for part in str(customer_name or "").strip().split() if part]
    if first and last:
        return first, last
    if not parts:
        return first, last
    if len(parts) == 1:
        return first or parts[0], last
    if not first:
        first = parts[0]
    if not last:
        normalized_first = re.sub(r"[^a-z0-9]+", "", str(first or "").lower())
        normalized_head = re.sub(r"[^a-z0-9]+", "", str(parts[0] or "").lower())
        last_parts = parts[1:] if normalized_first == normalized_head else parts[1:]
        last = " ".join(last_parts)
    return first, last


def _quantity_for_summary(
    payload: Dict[str, Any],
    signals: Dict[str, Dict[str, Any]],
    *,
    default_allowed: bool,
    selected_product: Optional[Dict[str, Any]] = None,
    previous_order_summary_snapshot: Optional[Dict[str, Any]] = None,
) -> Tuple[int, bool]:
    selected_quantity = _selected_product_quantity(selected_product or {})
    previous_quantity = _retained_snapshot_quantity(previous_order_summary_snapshot)
    signal_quantity, _ = _quantity(signals, default_allowed=False)
    signal_source = signal_authority_source(signals.get("quantity") or {})
    raw = payload.get("quantity")
    if raw not in (None, "", []):
        try:
            quantity = int(re.search(r"\d+", str(raw)).group(0)) if re.search(r"\d+", str(raw)) else 0
            if quantity > 0:
                if (
                    selected_quantity > 0
                    and selected_quantity != quantity
                    and not (
                        signal_quantity == quantity
                        and signal_source
                        in {
                            "latest_user_message",
                            "customer_history",
                            "validated_choice_action",
                        }
                    )
                ):
                    return selected_quantity, False
                if (
                    signal_quantity > 0
                    and signal_quantity != quantity
                    and signal_source
                    in {
                        "latest_user_message",
                        "customer_history",
                        "validated_choice_action",
                    }
                ):
                    return max(1, min(signal_quantity, 12)), False
                if (
                    previous_quantity > 0
                    and previous_quantity != quantity
                    and not (
                        signal_quantity == quantity
                        and signal_source
                        in {
                            "latest_user_message",
                            "customer_history",
                            "validated_choice_action",
                        }
                    )
                ):
                    return previous_quantity, False
                return max(1, min(quantity, 12)), False
        except Exception:
            pass
    if selected_quantity > 0:
        if (
            signal_quantity > 0
            and signal_quantity != selected_quantity
            and signal_source
            in {
                "latest_user_message",
                "customer_history",
                "validated_choice_action",
            }
        ):
            return max(1, min(signal_quantity, 12)), False
        return max(1, min(selected_quantity, 12)), False
    if signal_quantity > 0:
        return max(1, min(signal_quantity, 12)), False
    if previous_quantity > 0:
        return previous_quantity, False
    return _quantity(signals, default_allowed=default_allowed)


def _quantity_with_summary_continuity(
    signals: Dict[str, Dict[str, Any]],
    *,
    default_allowed: bool,
    selected_product: Optional[Dict[str, Any]] = None,
    previous_order_summary_snapshot: Optional[Dict[str, Any]] = None,
) -> Tuple[int, bool]:
    """Prefer current typed facts, then a prior explicit order quantity, over a default."""

    signal_quantity, _ = _quantity(signals, default_allowed=False)
    if signal_quantity > 0:
        return signal_quantity, False
    selected_quantity = _selected_product_quantity(selected_product or {})
    if selected_quantity > 0:
        return max(1, min(selected_quantity, 12)), False
    previous_quantity = _retained_snapshot_quantity(previous_order_summary_snapshot)
    if previous_quantity > 0:
        return previous_quantity, False
    return _quantity(signals, default_allowed=default_allowed)


def _retained_snapshot_quantity(snapshot: Optional[Dict[str, Any]]) -> int:
    """Return a non-default quantity already rendered in a trusted order summary."""

    if not isinstance(snapshot, dict) or snapshot.get("quantity_defaulted") is not False:
        return 0
    if str(snapshot.get("quantity_source") or "").strip() not in {
        "typed_customer_signal",
        "validated_choice_action",
        "selected_product_binding",
        "order_tool_payload",
        "prior_order_summary",
    }:
        return 0
    raw = snapshot.get("quantity")
    try:
        quantity = int(re.search(r"\d+", str(raw)).group(0)) if re.search(r"\d+", str(raw)) else 0
    except Exception:
        quantity = 0
    return max(1, min(quantity, 12)) if quantity > 0 else 0


def _resolved_quantity_source(
    *,
    payload: Dict[str, Any],
    signals: Dict[str, Dict[str, Any]],
    selected_product: Dict[str, Any],
    quantity: int,
    quantity_is_default: bool,
    previous_order_summary_snapshot: Optional[Dict[str, Any]],
) -> str:
    """Describe why the deterministic order summary used its quantity."""

    if quantity_is_default or quantity <= 0:
        return "assumed_default" if quantity_is_default else ""
    signal_quantity, _ = _quantity(signals, default_allowed=False)
    if signal_quantity == quantity:
        authority = signal_authority_source(signals.get("quantity") or {})
        if authority == "validated_choice_action":
            return "validated_choice_action"
        if authority in {"latest_user_message", "customer_history"}:
            return "typed_customer_signal"
    if _selected_product_quantity(selected_product or {}) == quantity:
        return "selected_product_binding"
    if _retained_snapshot_quantity(previous_order_summary_snapshot) == quantity:
        return "prior_order_summary"
    raw = payload.get("quantity")
    try:
        payload_quantity = int(re.search(r"\d+", str(raw)).group(0)) if re.search(r"\d+", str(raw)) else 0
    except Exception:
        payload_quantity = 0
    if payload_quantity == quantity:
        # Tool arguments become stable only after the deterministic summary is
        # rendered; this prevents a later model turn from silently replacing
        # a visible order quantity with the four-tire default.
        return "order_tool_payload"
    return ""


def _selected_product_quantity(product: Dict[str, Any]) -> int:
    for key in ("selected_quantity",):
        raw = product.get(key)
        try:
            quantity = int(re.search(r"\d+", str(raw)).group(0)) if re.search(r"\d+", str(raw)) else 0
        except Exception:
            quantity = 0
        if quantity > 0:
            return quantity
    if not _selected_product_card_quantity_is_binding(product):
        return 0
    raw = product.get("quantity")
    try:
        quantity = int(re.search(r"\d+", str(raw)).group(0)) if re.search(r"\d+", str(raw)) else 0
    except Exception:
        quantity = 0
    return quantity if quantity > 0 else 0


def _selected_product_card_quantity_is_binding(product: Dict[str, Any]) -> bool:
    pricing_basis = str(product.get("pricing_basis") or "").strip().lower()
    if pricing_basis == "buy3get1":
        return True
    promo_line = str(product.get("promo_savings_line") or product.get("promo_line") or "").strip().lower()
    if "buy 3 get 1" in promo_line:
        return True
    scope = str(product.get("presentation_scope") or "").strip().lower()
    return "buy3get1" in scope or "four_tire" in scope


def _fulfillment_path_for_summary(
    payload: Dict[str, Any],
    signals: Dict[str, Dict[str, Any]],
    latest_service: Optional[ServiceObservation],
    latest_service_presentation: Optional[ServiceObservation],
) -> Tuple[str, str]:
    service_type = str(payload.get("service_type") or "").strip().lower()
    if "delivery" in service_type or payload.get("delivery_address"):
        return "delivery", "delivery"
    if any(token in service_type for token in ["install", "installation", "kabit"]):
        return "installation", "installation"
    if any(token in service_type for token in ["pickup", "pick up"]):
        return "pickup", "pickup"
    if any(token in service_type for token in ["home_service", "home service"]):
        return "home_service", "home service"
    # Product/service observations ground read-only facts, not a customer's
    # fulfillment choice. Keep the parameters for the summary call contract,
    # but derive the path only from durable typed state.
    del latest_service, latest_service_presentation
    return _fulfillment_path(signals)


def _service_location_from_payload(
    payload: Dict[str, Any],
    store: Optional[ServiceObservationStore],
) -> Dict[str, Any]:
    if store is None:
        return {}
    for key in ["service_location_ref", "installation_partner_ref"]:
        location = store.get_location(payload.get(key))
        if location:
            return location
    return {}


def _has_validated_slot_context(
    store: Optional[ServiceObservationStore],
    *,
    service_location_ref: Any,
    schedule_parts: Dict[str, str],
) -> bool:
    """Return true only when a prior slot-validation observation matches payload.

    Slot lookup results are read-only availability. A submit-ready installation
    payload needs a customer-selected slot validated through
    validate_installation_slot, not just a model-picked date/time from a list.
    """

    if store is None or not schedule_parts:
        return False
    observation = store.latest_validated_slot_observation()
    if observation is None:
        return False
    requested_ref = str(service_location_ref or "").strip()
    if requested_ref:
        refs = {
            str(location.get("service_location_ref") or "").strip()
            for location in observation.service_locations or []
            if isinstance(location, dict)
        }
        refs.update(
            str(location.get("installation_partner_ref") or "").strip()
            for location in observation.service_locations or []
            if isinstance(location, dict)
        )
        if requested_ref not in refs:
            return False
    expected_date = str(schedule_parts.get("delivery_date") or "").strip()
    expected_time = str(schedule_parts.get("delivery_time") or "").strip()
    for group in observation.slot_groups or []:
        if not isinstance(group, dict):
            continue
        for slot in group.get("slots") or []:
            if not isinstance(slot, dict):
                continue
            slot_date = str(slot.get("date") or slot.get("delivery_date") or "").strip()
            slot_time = str(slot.get("time") or slot.get("time_text") or slot.get("delivery_time") or "").strip()
            normalized_time = _normalize_time_for_api(slot_time) or slot_time
            if slot_date == expected_date and normalized_time == expected_time:
                return True
    return False


def _latest_validated_slot_service_location(store: Optional[ServiceObservationStore]) -> Dict[str, Any]:
    """Return the partner selected by the latest slot-validation observation."""

    if store is None:
        return {}
    observation = store.latest_validated_slot_observation()
    if observation is None:
        return {}
    for location in observation.service_locations or []:
        if isinstance(location, dict) and location:
            return deepcopy(location)
    return {}


def _latest_validated_slot_context(
    store: Optional[ServiceObservationStore],
    *,
    service_location_ref: Any = "",
) -> Dict[str, Any]:
    """Return canonical order context from the latest validated service slot."""

    if store is None:
        return {}
    observation = store.latest_validated_slot_observation()
    if observation is None:
        return {}
    location = _latest_validated_slot_service_location(store)
    requested_ref = str(service_location_ref or "").strip()
    if requested_ref:
        refs = {
            str(location.get("service_location_ref") or "").strip(),
            str(location.get("installation_partner_ref") or "").strip(),
            str(location.get("branch_id") or "").strip(),
        }
        if requested_ref not in refs:
            return {}
    slot = _latest_validated_slot(observation)
    schedule_parts = _schedule_parts_from_validated_slot(slot)
    if not slot or not schedule_parts:
        return {}
    return {
        "service_location": location,
        "slot": slot,
        "schedule_parts": schedule_parts,
    }


def _matching_flexible_schedule_choice(
    choice_action_history: Sequence[Dict[str, Any]],
    *,
    selected_slot: Any,
) -> Dict[str, Any]:
    """Return the latest delivered flexible-window choice matching current state.

    A flexible schedule is summary evidence only when it came from a validated
    delivered control. Matching its structured date against the normalized
    schedule signal prevents an older location/date choice from silently
    carrying into a newer order path.
    """

    selected_text = str(selected_slot or "").strip().casefold()
    if not selected_text:
        return {}
    for action in reversed(choice_action_history or []):
        if not isinstance(action, dict):
            continue
        if str(action.get("choice_type") or "") != "schedule_selection":
            continue
        if str(action.get("validation_status") or "") != "valid":
            return {}
        if str(action.get("selection_kind") or "") != "afternoon_preference":
            return {}
        date = str(action.get("date") or "").strip()
        if date and date.casefold() not in selected_text:
            return {}
        return deepcopy(action)
    return {}


def _flexible_schedule_choice_display(action: Dict[str, Any]) -> str:
    """Render a customer-readable flexible schedule without claiming a booking."""

    date = str(action.get("date") or "").strip()
    try:
        parsed = datetime.strptime(date, "%Y-%m-%d")
        date_label = f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"
    except ValueError:
        date_label = date
    if (
        action.get("afternoon_resolution_status")
        == "default_noon_preference_unvalidated"
    ):
        window = str(action.get("time_text") or "12:00 PM").strip()
    else:
        window = str(
            action.get("label") or "Anytime in the afternoon"
        ).strip()
    return " - ".join(
        part
        for part in (
            date_label,
            f"{window} (flexible preference)",
        )
        if part
    )


def _latest_validated_slot(observation: ServiceObservation) -> Dict[str, Any]:
    for group in observation.slot_groups or []:
        if not isinstance(group, dict):
            continue
        for slot in group.get("slots") or []:
            if isinstance(slot, dict) and slot:
                return deepcopy(slot)
    return {}


def _schedule_parts_from_validated_slot(slot: Dict[str, Any]) -> Dict[str, str]:
    if not isinstance(slot, dict) or not slot:
        return {}
    from_start = _api_schedule_parts(slot.get("start"))
    if from_start:
        return from_start
    date = str(slot.get("date") or slot.get("delivery_date") or "").strip()
    time_text = str(slot.get("delivery_time") or slot.get("time") or slot.get("time_text") or "").strip()
    normalized_time = _normalize_time_for_api(time_text)
    if date and normalized_time:
        return {"delivery_date": date, "delivery_time": normalized_time}
    return {}


def _validated_slot_schedule_display(context: Dict[str, Any]) -> str:
    parts = context.get("schedule_parts") if isinstance(context.get("schedule_parts"), dict) else {}
    slot = context.get("slot") if isinstance(context.get("slot"), dict) else {}
    date = str(parts.get("delivery_date") or slot.get("date") or "").strip()
    time_text = str(slot.get("time_text") or "").strip()
    if not time_text:
        time_text = str(parts.get("delivery_time") or "").strip()
    return f"{date} {time_text}".strip()


def _summary_schedule_from_validated_slot(schedule: str, context: Dict[str, Any]) -> str:
    """Use canonical validated-slot display when current schedule is absent or equivalent."""

    display = _validated_slot_schedule_display(context)
    if not display:
        return schedule
    if not schedule:
        return display
    schedule_parts = _api_schedule_parts(schedule) or _schedule_parts_from_text_against_validated_slot(schedule, context)
    if schedule_parts and _schedule_parts_equal(schedule_parts, context.get("schedule_parts") or {}):
        return display
    return schedule


def _schedule_parts_from_text_against_validated_slot(schedule: Any, context: Dict[str, Any]) -> Dict[str, str]:
    """Parse common customer-facing date/time text only against a validated slot.

    This keeps free-form date handling grounded: month/day text such as
    "June 3 4pm" is interpreted using the year from the validated slot and
    still has to match the selected slot before it can become submit-ready.
    """

    if not isinstance(context, dict) or not context.get("schedule_parts"):
        return {}
    text = str(schedule or "").strip().lower()
    if not text:
        return {}
    validated_date = str((context.get("schedule_parts") or {}).get("delivery_date") or "").strip()
    if not validated_date:
        return {}
    year = validated_date[:4]
    month_match = re.search(
        r"\b(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+"
        r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\b",
        text,
    )
    time_match = re.search(r"\b(?P<time>\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", text)
    if not month_match or not time_match:
        return {}
    month = _month_number(month_match.group("month"))
    if not month:
        return {}
    delivery_date = f"{year}-{month:02d}-{int(month_match.group('day')):02d}"
    delivery_time = _normalize_time_for_api(time_match.group("time"))
    if not delivery_time:
        return {}
    return {"delivery_date": delivery_date, "delivery_time": delivery_time}


def _month_number(month_text: str) -> int:
    token = str(month_text or "").strip().lower()[:3]
    months = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    return months.get(token, 0)


def _schedule_parts_equal(left: Dict[str, str], right: Dict[str, str]) -> bool:
    return (
        str(left.get("delivery_date") or "").strip() == str(right.get("delivery_date") or "").strip()
        and str(left.get("delivery_time") or "").strip() == str(right.get("delivery_time") or "").strip()
    )




def _summary_should_require_order_detail(
    readiness: Dict[str, Any],
    *,
    summary_scope: Any = None,
) -> bool:
    """Choose preview versus checkout completeness from typed model/state intent."""

    scope = str(summary_scope or "").strip().casefold()
    if scope == "checkout":
        return True
    if scope == "preview":
        return False
    intent = str(readiness.get("customer_order_intent") or "").strip().lower()
    return intent in {"active", "high"}


def _order_summary_fields(
    *,
    customer_name: str,
    contact_number: str,
    email: str,
    product: str,
    tire_size: str,
    quantity: str,
    product_total: str,
    delivery_fee: str,
    home_service_fee: str,
    pay_now_discount: str,
    trusted_total: str,
    amount_due_now: str,
    balance_due: str,
    addon_note: str,
    service_path: str,
    service_reason: str,
    location: str,
    delivery_address: str,
    selected_partner: str,
    schedule: str,
    payment_option: str,
    reservation_payment: str,
    balance_payment: str,
    payment_bank: str,
    installment_months: str,
    invoice: str,
) -> Dict[str, str]:
    fields: Dict[str, str] = {
        "Name": customer_name or "-",
        "Contact No": contact_number or "-",
        "Email": email or "-",
        "Product": product or "-",
        "Tire Size": tire_size or "-",
        "Qty": quantity or "-",
        "Product Total": product_total or "-",
    }
    if service_path == "delivery":
        fields["Delivery Fee"] = delivery_fee or "-"
    if service_path == "home_service":
        fields["Home Service Fee"] = home_service_fee or "-"
    if pay_now_discount:
        fields["Pay Now Discount"] = pay_now_discount
    fields.update({
        "Total": trusted_total or "-",
    })
    if amount_due_now:
        fields["Amount Due Now"] = amount_due_now
    if balance_due:
        fields["Balance After Payment"] = balance_due
    if addon_note:
        fields["Add-ons"] = addon_note
    fields["Service"] = _service_label(service_path, service_reason) or "-"
    if service_path == "delivery":
        fields["Delivery Address"] = delivery_address or location or "-"
    elif service_path == "pickup":
        fields["Pickup Branch"] = selected_partner or location or "-"
    elif service_path == "home_service":
        fields["Service Address"] = delivery_address or location or "-"
    else:
        fields["Installation Area"] = location or "-"
        fields["Installation Partner"] = selected_partner or "-"
    if service_path == "delivery":
        if schedule:
            fields["Preferred Delivery Date/Time"] = schedule
    else:
        fields["Schedule"] = schedule or "-"
    fields["Payment Option"] = _payment_option_display(payment_option) or "-"
    if reservation_payment:
        fields["Reservation Payment Method"] = _payment_method_display(reservation_payment)
    if payment_option == "Pay Now":
        fields["Payment Method"] = _payment_method_display_with_terms(
            balance_payment,
            bank=payment_bank,
            installment_months=installment_months,
        ) or "-"
    else:
        fields["Mode of Payment (for balance)"] = _payment_method_display_with_terms(
            balance_payment,
            bank=payment_bank,
            installment_months=installment_months,
        ) or "-"
    fields["Invoice to Company?"] = invoice or "-"
    return fields


def _payment_method_display(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", "", text.lower())
    if normalized in {"cod", "cashondelivery", "payondelivery"}:
        return "Cash on Delivery"
    lowered = text.lower()
    if "cash on delivery" in lowered or "pay on delivery" in lowered:
        return "Cash on Delivery"
    if lowered == "gcash":
        return "GCash"
    if lowered == "maya":
        return "Maya"
    if lowered == "credit card":
        return "Credit card"
    if lowered == "credit card installment":
        return "Credit card installment"
    if lowered == "bank transfer":
        return "Bank transfer"
    if lowered == "cash":
        return "Cash"
    return text


def _payment_option_display(value: str) -> str:
    """Keep internal payment aliases out of customer-visible summaries."""

    text = str(value or "").strip()
    if text == "Pay Later / Pay After Service":
        return "Pay Later"
    return text


def _payment_method_display_with_terms(value: str, *, bank: str = "", installment_months: str = "") -> str:
    display = _payment_method_display(value)
    if not display:
        return ""
    if not _payment_text_mentions_installment_route(display):
        return display
    details: List[str] = []
    bank_text = str(bank or "").strip()
    months_text = str(installment_months or "").strip()
    if bank_text:
        details.append(bank_text)
    if months_text:
        details.append(f"{months_text} months")
    if details:
        return f"{display} ({' '.join(details)})"
    return display


def _payment_text_mentions_installment_route(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return "installment" in text or "0%" in text


def _service_label(service_path: str, service_reason: str) -> str:
    if service_path == "delivery":
        return "Delivery"
    if service_path == "installation":
        return "Installation"
    if service_path == "pickup":
        return "Pickup"
    if service_path == "home_service":
        return "Home service"
    return service_reason


def _render_order_summary_block(fields: Dict[str, str], *, missing: Sequence[str]) -> str:
    missing = _unique([str(item or "").strip() for item in missing if str(item or "").strip()])
    heading = "Order Details So Far" if missing else "🧾 Order Summary"
    groups: List[List[str]] = [[heading]]
    group_specs = [
        ("Customer", ["Name", "Contact No", "Email"]),
        ("Tire details", ["Product", "Tire Size", "Qty"]),
        (
            "Amount",
            [
                "Product Total",
                "Delivery Fee",
                "Home Service Fee",
                "Pay Now Discount",
                "Total",
                "Amount Due Now",
                "Balance After Payment",
                "Add-ons",
            ],
        ),
        (
            "Service",
            [
                "Service",
                "Delivery Address",
                "Pickup Branch",
                "Service Address",
                "Installation Area",
                "Installation Partner",
                "Preferred Delivery Date/Time",
                "Schedule",
            ],
        ),
        (
            "Payment",
            [
                "Payment Option",
                "Reservation Payment Method",
                "Payment Method",
                "Mode of Payment (for balance)",
                "Invoice to Company?",
            ],
        ),
    ]
    used: set[str] = set()
    for title, keys in group_specs:
        group_lines = [title]
        for key in keys:
            if key not in fields:
                continue
            used.add(key)
            if missing and not _order_form_value_present(fields.get(key)):
                continue
            group_lines.append(f"{key}: {_order_form_display_value(key, fields.get(key))}")
        if len(group_lines) > 1:
            groups.append(group_lines)
    remaining = [
        f"{key}: {_order_form_display_value(key, value)}"
        for key, value in fields.items()
        if key not in used
        and (not missing or _order_form_value_present(value))
    ]
    if remaining:
        groups.append(["Other details", *remaining])
    return "\n\n".join("\n".join(group).strip() for group in groups if group).strip()


def _order_form_value_present(value: Any) -> bool:
    return str(value or "").strip() not in {"", "-"}


def _order_form_display_value(key: str, value: Any) -> str:
    text = str(value or "").strip()
    if text and text != "-":
        return text
    return _ORDER_FORM_PLACEHOLDERS.get(key, "[to fill in]")


_ORDER_FORM_PLACEHOLDERS = {
    "Name": "[name]",
    "Contact No": "[mobile number]",
    "Email": "[needed before submit]",
    "Product": "[selected tire]",
    "Tire Size": "[tire size]",
    "Qty": "[quantity]",
    "Product Total": "[to confirm]",
    "Delivery Fee": "[to confirm]",
    "Home Service Fee": "[to confirm]",
    "Pay Now Discount": "[to confirm]",
    "Total": "[to confirm]",
    "Amount Due Now": "[to confirm]",
    "Balance After Payment": "[to confirm]",
    "Add-ons": "[optional]",
    "Service": "[delivery / installation / pickup]",
    "Delivery Address": "[complete delivery address]",
    "Preferred Delivery Date/Time": "[preferred delivery date/time]",
    "Pickup Branch": "[pickup branch]",
    "Service Address": "[complete service address]",
    "Installation Area": "[area/city]",
    "Installation Partner": "[installation partner]",
    "Schedule": "[preferred date/time]",
    "Payment Option": "[Pay Now / Pay Later]",
    "Reservation Payment Method": "[payment method]",
    "Payment Method": "[GCash / card / bank transfer]",
    "Mode of Payment (for balance)": "[GCash / cash / card]",
    "Invoice to Company?": "[YES/NO]",
}


def _order_summary_ref(summary_block: str) -> str:
    digest = hashlib.sha1(str(summary_block or "").encode("utf-8")).hexdigest()[:10]
    return f"order_summary_{digest}"


def _order_summary_hints(
    *,
    status: str,
    missing: Sequence[str],
    service_path: str = "",
    payment_option: str = "",
    submission_blockers: Sequence[str] = (),
    summary_update: Optional[Dict[str, Any]] = None,
) -> List[str]:
    hints: List[str] = []
    if status == "ready":
        hints.extend(
            [
                "Use the order summary as the order-review body.",
                "Ask the customer to confirm whether the details are correct before moving to the next order action.",
            ]
        )
    if missing:
        hints.extend(
            [
                "Use the order summary as the collected-info body.",
                "Ask only for the missing detail that best moves the order forward.",
            ]
        )
    if service_path == "delivery":
        hints.append("Call answer_order_faq for delivery fee and delivery lead-time before the final delivery-summary response.")
    if not payment_option and not _missing_selected_product(missing):
        hints.append("Call answer_order_faq for payment options before asking Pay Now vs Pay Later.")
    if submission_blockers:
        hints.extend(
            [
                "The order summary may be reviewed now, but do not claim the order is submit-ready.",
                "Keep the customer's flexible schedule preference. Resolve an exact partner and slot from trusted service availability before building or submitting the order payload.",
            ]
        )
    update = summary_update if isinstance(summary_update, dict) else {}
    if update.get("display_action") == "quiet_update":
        hints.append("Acknowledge the simple order-info update briefly; do not re-show the whole form unless the customer asks.")
        if status == "ready":
            hints.append("If the customer has already confirmed the reviewed order details, call build_order_payload next before any submit or payment step.")
    if update.get("critical_change_count"):
        hints.append(
            "A critical order detail differs from the previous summary. Present the current "
            "trusted detail neutrally and ask the customer to confirm it. Do not describe an "
            "internal correction or update unless the customer explicitly changed that detail."
        )
    return hints or ["Use the inserted summary as factual order context only."]


def _order_faq_suggestions(*, service_path: str, payment_option: str, missing: Sequence[str] = ()) -> List[Dict[str, str]]:
    suggestions: List[Dict[str, str]] = []
    if service_path == "delivery":
        suggestions.extend(
            [
                {
                    "faq_id": "order_how_much_is_the_delivery_fee",
                    "question": "How much is the delivery fee?",
                    "reason": "delivery order summary",
                },
                {
                    "faq_id": "order_how_long_does_delivery_take",
                    "question": "How long does delivery take?",
                    "reason": "delivery order summary",
                },
            ]
        )
    if not payment_option and not _missing_selected_product(missing):
        suggestions.append(
            {
                "faq_id": "order_how_do_i_pay",
                "question": "How do I Pay?",
                "reason": "payment option clarification",
            }
        )
    return suggestions


def _missing_selected_product(missing: Sequence[str]) -> bool:
    return any(str(item or "").strip().lower() == "selected product/sku" for item in missing or [])


def _supporting_order_policy_context(
    suggestions: Sequence[Dict[str, str]],
    *,
    service_path: str = "",
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> List[Dict[str, str]]:
    """Attach compact FAQ-grounded policy facts relevant to this summary."""

    if not suggestions:
        return []
    context: List[Dict[str, str]] = []
    for suggestion in suggestions[:3]:
        faq_id = str(suggestion.get("faq_id") or "").strip()
        question = str(suggestion.get("question") or "").strip()
        if not faq_id or not question:
            continue
        result_faq_id = faq_id
        result_question = question
        try:
            from runtime_v7.faq_tools import answer_order_faq
        except Exception:
            continue
        try:
            result = answer_order_faq(
                {"faq_id": faq_id, "question": question, "service_type": service_path},
                canonical_values_provider=canonical_values_provider,
            )
        except Exception:
            continue
        answer = str(result.get("answer") or "").strip()
        if result.get("status") != "ok" or not answer:
            continue
        result_faq_id = str(result.get("faq_id") or faq_id)
        result_question = str(result.get("question") or question)
        context.append(
            {
                "source_type": "faq",
                "faq_id": result_faq_id,
                "question": result_question,
                "answer": _compact_policy_answer(answer),
                "reason": str(suggestion.get("reason") or ""),
            }
        )
    return context


def _compact_policy_answer(answer: str, *, max_len: int = 700) -> str:
    text = re.sub(r"\s+", " ", str(answer or "").strip())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


_PAY_NOW_DISCOUNT = 100.0


def _quote_for_product(
    product: Dict[str, Any],
    *,
    quantity: int,
    quantity_is_default: bool,
    service_path: str,
    service_reason: str,
    payment_option: str,
    latest_service: Optional[ServiceObservation],
    signals: Dict[str, Dict[str, Any]],
    product_reason: str,
) -> Dict[str, Any]:
    """Return read-only quote math for one trusted product."""

    if not product:
        return {
            "status": "missing_product",
            "missing_fields": ["Selected product/SKU"],
            "validation": [],
        }
    quantity = max(1, min(int(quantity or 4), 12))
    product_subtotal = _trusted_total(product, quantity=quantity)
    unit_price = _coerce_float(product.get("price"))
    missing: List[str] = []
    validation: List[str] = []
    assumptions: List[str] = []
    if product_reason:
        validation.append(product_reason)
    if quantity_is_default:
        assumptions.append("Quantity defaults to 4 tires unless the customer says otherwise.")
    if product_subtotal is None:
        missing.append("Trusted customer-facing price/total")
    card_effective_total = effective_total_price(product, quantity)
    checkout_pricing_adjustment: Optional[float] = None
    if (
        card_effective_total is not None
        and product_subtotal is not None
        and abs(round(product_subtotal - card_effective_total, 2)) >= 0.01
    ):
        checkout_pricing_adjustment = round(product_subtotal - card_effective_total, 2)
        validation.append(
            "Order checkout total uses backend sale pricing for submit consistency; product-card quantity total may differ."
        )

    delivery_fee: Optional[float] = None
    home_service_fee: Optional[float] = None
    fulfillment_fee: Optional[float] = 0.0
    home_service_available: Optional[bool] = None
    if service_path == "delivery":
        delivery_fee = _delivery_fee_for_product(product)
        fulfillment_fee = delivery_fee
        if delivery_fee is None:
            missing.append("Delivery fee")
    elif service_path == "home_service":
        home_service_fee, home_service_available = _home_service_fee_for_product(product, quantity=quantity, signals=signals)
        fulfillment_fee = home_service_fee
        if home_service_fee is None:
            missing.append("Home service fee")
        if home_service_available is False:
            validation.append("Home service is unavailable for this rim size based on current policy.")
    elif service_path in {"installation", "pickup", ""}:
        fulfillment_fee = 0.0
    else:
        fulfillment_fee = 0.0

    gross_total: Optional[float] = None
    if product_subtotal is not None and fulfillment_fee is not None:
        gross_total = round(product_subtotal + fulfillment_fee, 2)

    normalized_payment = _normalize_payment_option(payment_option)
    pay_now_discount = _PAY_NOW_DISCOUNT if normalized_payment == "Pay Now" and gross_total is not None else 0.0
    order_total = round(gross_total - pay_now_discount, 2) if gross_total is not None else None
    reservation_fee: Optional[float] = None
    amount_due_now: Optional[float] = None
    balance_due: Optional[float] = None
    if gross_total is not None and normalized_payment == "Pay Later / Pay After Service":
        reservation_fee = _reservation_fee_for_total(gross_total)
        amount_due_now = reservation_fee
        balance_due = round(gross_total - reservation_fee, 2)
    elif gross_total is not None and normalized_payment == "Pay Now":
        amount_due_now = order_total
        balance_due = 0.0

    payment_preview = _payment_options_preview(gross_total)
    savings = product_discount_savings_for_quantity(product, quantity)
    if savings is None and unit_price is not None and product_subtotal is not None:
        undiscounted = round(unit_price * quantity, 2)
        if undiscounted > product_subtotal:
            savings = round(undiscounted - product_subtotal, 2)

    basis = _checkout_pricing_basis(product, quantity)
    branch_addon_context = _branch_addon_context(latest_service)
    quote = {
        "status": "ok" if not missing else "incomplete",
        "product": _quote_product_summary(product),
        "quantity": quantity,
        "quantity_defaulted": quantity_is_default,
        "quantity_assumption": "Quantity defaults to 4 tires unless the customer says otherwise." if quantity_is_default else "",
        "unit_price": unit_price,
        "unit_price_text": _money_text(unit_price) if unit_price is not None else "",
        "product_subtotal": product_subtotal,
        "product_subtotal_text": _money_text(product_subtotal) if product_subtotal is not None else "",
        "product_card_effective_total": card_effective_total,
        "product_card_effective_total_text": _money_text(card_effective_total) if card_effective_total is not None else "",
        "checkout_pricing_adjustment": checkout_pricing_adjustment,
        "checkout_pricing_adjustment_text": _money_text(checkout_pricing_adjustment) if checkout_pricing_adjustment is not None else "",
        "product_pricing_basis": basis,
        "product_discount_savings": savings,
        "product_discount_savings_text": _money_text(savings) if savings is not None else "",
        "service_path": service_path,
        "service_reason": service_reason,
        "delivery_fee": delivery_fee,
        "delivery_fee_text": _money_text(delivery_fee) if delivery_fee is not None and service_path == "delivery" else "",
        "home_service_fee": home_service_fee,
        "home_service_fee_text": _money_text(home_service_fee) if home_service_fee is not None and service_path == "home_service" else "",
        "home_service_available": home_service_available,
        "online_total_before_payment_discount": gross_total,
        "online_total_before_payment_discount_text": _money_text(gross_total) if gross_total is not None else "",
        "payment_option": normalized_payment,
        "pay_now_discount": pay_now_discount,
        "pay_now_discount_text": f"-{_money_text(pay_now_discount)}" if pay_now_discount else "",
        "order_total": order_total,
        "order_total_text": _money_text(order_total) if order_total is not None else "",
        "reservation_fee": reservation_fee,
        "reservation_fee_text": _money_text(reservation_fee) if reservation_fee is not None else "",
        "amount_due_now": amount_due_now,
        "amount_due_now_text": _money_text(amount_due_now) if amount_due_now is not None else "",
        "balance_due": balance_due,
        "balance_due_text": _money_text(balance_due) if balance_due is not None else "",
        "payment_options_preview": payment_preview if not normalized_payment else {},
        "installation_threshold_total": product_subtotal,
        "installation_threshold_total_text": _money_text(product_subtotal) if product_subtotal is not None else "",
        "branch_addon_context": branch_addon_context,
        "missing_fields": _unique(missing),
        "assumptions": _unique(assumptions),
        "validation": _unique(validation),
        "read_only": True,
    }
    return quote


def _quote_candidates_from_observation(
    observation: ProductObservation,
    *,
    quantity: int,
    service_path: str,
    service_reason: str,
    payment_option: str,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for row in _product_rows(observation)[:4]:
        product = row.get("product") if isinstance(row, dict) else {}
        if not isinstance(product, dict):
            continue
        quote = _quote_for_product(
            product,
            quantity=quantity,
            quantity_is_default=False,
            service_path=service_path,
            service_reason=service_reason,
            payment_option=payment_option,
            latest_service=None,
            signals={},
            product_reason=f"Candidate from trusted product observation {observation.observation_ref}.",
        )
        candidates.append(
            {
                "product": _quote_product_summary(product),
                "quantity": quote.get("quantity"),
                "product_subtotal": quote.get("product_subtotal"),
                "product_subtotal_text": quote.get("product_subtotal_text"),
                "order_total": quote.get("order_total"),
                "order_total_text": quote.get("order_total_text"),
                "payment_options_preview": quote.get("payment_options_preview") or {},
                "pricing_basis": quote.get("product_pricing_basis"),
            }
        )
    return candidates


def _quote_product_summary(product: Dict[str, Any]) -> Dict[str, Any]:
    if not product:
        return {}
    return {
        "label": _product_label(product),
        "tire_size": _product_size(product),
        "brand": str(product.get("brand") or "").strip(),
        "category": str(product.get("category") or "").strip(),
        "item_ref": product.get("item_ref"),
        "product_id": product.get("product_id") or product.get("id"),
        "slug": product.get("slug"),
    }


def _quote_summary(quote: Dict[str, Any]) -> Dict[str, Any]:
    if not quote:
        return {}
    summary = {
        "product": (quote.get("product") or {}).get("label"),
        "quantity": quote.get("quantity"),
        "product_subtotal": quote.get("product_subtotal_text"),
        "delivery_fee": quote.get("delivery_fee_text"),
        "home_service_fee": quote.get("home_service_fee_text"),
        "pay_now_discount": quote.get("pay_now_discount_text"),
        "order_total": quote.get("order_total_text"),
        "amount_due_now": quote.get("amount_due_now_text"),
        "balance_due": quote.get("balance_due_text"),
        "payment_option": quote.get("payment_option"),
        "pricing_basis": quote.get("product_pricing_basis"),
    }
    if (quote.get("branch_addon_context") or {}).get("excluded_from_online_total"):
        summary["branch_addons_excluded_from_online_total"] = True
    preview = quote.get("payment_options_preview")
    if isinstance(preview, dict) and preview:
        summary["payment_options_preview"] = preview
    return {key: value for key, value in summary.items() if value not in (None, "", {}, [])}


def _quote_customer_explanation_hints(
    *,
    quote: Dict[str, Any],
    selected_product: bool,
    candidate_quotes: bool,
    invalid_fields: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[str]:
    hints: List[str] = []
    if invalid_fields:
        hints.append("Payment details conflict; clarify Pay Now/Pay Later and the payment method before quoting a final payable amount.")
    if not selected_product and candidate_quotes:
        hints.append("Multiple current product candidates have quote candidates; present or restore their choices and ask which SKU to use before a final order summary.")
    elif not selected_product:
        hints.append("Ask the customer to choose a product/SKU before quoting order totals.")
    if quote.get("payment_options_preview"):
        hints.append("Explain Pay Now vs Pay Later using the preview amounts if the customer is deciding payment option.")
    if quote.get("delivery_fee") is not None:
        hints.append("Delivery fee is included in the read-only quote breakdown.")
    if quote.get("branch_addon_context"):
        hints.append("Branch add-ons are paid at the installation partner and are not included in the online order total.")
    if quote.get("home_service_available") is False:
        hints.append("Home service is not available for the current rim size; offer delivery or installation partner service instead.")
    return hints or ["Use quote numbers as read-only customer-facing pricing context only."]


def _quote_ref(payload: Dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, default=str)
    digest = hashlib.sha1(body.encode("utf-8")).hexdigest()[:10]
    return f"order_quote_{digest}"


def _order_payload_ref(payload: Dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, default=str)
    digest = hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]
    return f"order_payload_{digest}"


def _runtime_v7_normalized_order_payload(
    *,
    selected_product: Dict[str, Any],
    quantity: int,
    service_path: str,
    service_reason: str,
    location: str,
    delivery_address: str,
    selected_partner: str,
    service_location: Dict[str, Any],
    schedule: str,
    contact_number: str,
    customer_name: str,
    first_name: str,
    last_name: str,
    email: str,
    invoice: str,
    payment_option: str,
    payment_method: str,
    reservation_payment: str,
    balance_payment: str,
    payment_selection: Dict[str, Any],
    quote_breakdown: Dict[str, Any],
    source_refs: Dict[str, Any],
) -> Dict[str, Any]:
    """Build V7's normalized view of the order for diagnostics and validation."""

    payment_selection = payment_selection if isinstance(payment_selection, dict) else {}
    payment_method_for_submit = (
        str(payment_selection.get("payment_method_for_submit") or "").strip()
        or payment_method
        or reservation_payment
        or balance_payment
    )
    fulfillment = {
        "service_path": service_path,
        "service_reason": service_reason,
        "location": location,
        "delivery_address": delivery_address,
        "installation_partner": selected_partner,
        "installation_partner_ref": (
            service_location.get("installation_partner_ref")
            or service_location.get("service_location_ref")
            or service_location.get("location_ref")
        ),
        "installation_partner_id": service_location.get("id") or service_location.get("branch_id"),
        "schedule": schedule,
    }
    return _drop_empty_dict_values(
        {
            "payload_version": "runtime_v7_order_payload_v1",
            "customer": _drop_empty_dict_values(
                {
                    "name": customer_name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "contact_number": contact_number,
                    "email_address": email,
                }
            ),
            "product": _drop_empty_dict_values(
                {
                    "label": _product_label(selected_product),
                    "brand": str(selected_product.get("brand") or "").strip(),
                    "model": str(
                        selected_product.get("pattern")
                        or selected_product.get("model")
                        or selected_product.get("sku_model")
                        or ""
                    ).strip(),
                    "tire_size": _product_size(selected_product),
                    "quantity": quantity,
                    "unit_price": _coerce_float(selected_product.get("price")),
                    "unit_price_text": (
                        _money_text(_coerce_float(selected_product.get("price")))
                        if _coerce_float(selected_product.get("price")) is not None
                        else ""
                    ),
                    "pricing_basis": quote_breakdown.get("product_pricing_basis"),
                    "product_id": selected_product.get("product_id") or selected_product.get("id"),
                    "slug": selected_product.get("slug"),
                    "item_ref": selected_product.get("item_ref"),
                }
            ),
            "fulfillment": _drop_empty_dict_values(fulfillment),
            "payment": _drop_empty_dict_values(
                {
                    "payment_option": payment_option,
                    "payment_method": payment_method_for_submit,
                    "payment_method_for_submit": payment_method_for_submit,
                    "reservation_payment_method": reservation_payment,
                    "balance_payment_method": balance_payment,
                    "bank": payment_selection.get("bank"),
                    "installment_months": payment_selection.get("installment_months"),
                    "invoice_to_company": invoice,
                }
            ),
            "totals": _drop_empty_dict_values(
                {
                    "product_subtotal": quote_breakdown.get("product_subtotal"),
                    "product_subtotal_text": quote_breakdown.get("product_subtotal_text"),
                    "delivery_fee": quote_breakdown.get("delivery_fee"),
                    "delivery_fee_text": quote_breakdown.get("delivery_fee_text"),
                    "home_service_fee": quote_breakdown.get("home_service_fee"),
                    "home_service_fee_text": quote_breakdown.get("home_service_fee_text"),
                    "pay_now_discount": quote_breakdown.get("pay_now_discount"),
                    "pay_now_discount_text": quote_breakdown.get("pay_now_discount_text"),
                    "order_total": quote_breakdown.get("order_total"),
                    "order_total_text": quote_breakdown.get("order_total_text"),
                    "amount_due_now": quote_breakdown.get("amount_due_now"),
                    "amount_due_now_text": quote_breakdown.get("amount_due_now_text"),
                    "balance_due": quote_breakdown.get("balance_due"),
                    "balance_due_text": quote_breakdown.get("balance_due_text"),
                }
            ),
            "source_refs": _drop_empty_dict_values(source_refs),
        }
    )


def _runtime_v7_order_api_payload(
    *,
    selected_product: Dict[str, Any],
    quantity: int,
    service_path: str,
    service_reason: str,
    location: str,
    delivery_address: str,
    selected_branch: Dict[str, Any],
    schedule_parts: Dict[str, str],
    schedule: str,
    contact_number: str,
    customer_name: str,
    first_name: str,
    last_name: str,
    email: str,
    invoice: str,
    transaction: Dict[str, Any],
    payment_option_row: Dict[str, Any],
    payment_type_row: Dict[str, Any],
    payment_method: str,
    quote_breakdown: Dict[str, Any],
    source_refs: Dict[str, Any],
    payload: Dict[str, Any],
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Dict[str, Any]:
    """Build the API-submit payload shape used by Gulong `/order`."""

    now = datetime.now(tz=MANILA_TZ)
    cart_item = _api_cart_item(
        selected_product,
        quantity=quantity,
        now=now,
        canonical_values_provider=canonical_values_provider,
    )
    branch_fields = _api_branch_fields(
        service_path=service_path,
        selected_branch=selected_branch,
        schedule_parts=schedule_parts,
    )
    address_fields = _api_address_fields(
        service_path=service_path,
        delivery_address=delivery_address,
        location=location,
    )
    data_block = {
        **_api_amount_fields(quote_breakdown, selected_product=selected_product, quantity=quantity),
        **branch_fields,
        **address_fields,
        "transaction_type": transaction.get("id"),
        "transaction_type_details": {
            "name": transaction.get("trans_type") or transaction.get("name"),
            "description": transaction.get("description")
            or transaction.get("trans_type")
            or transaction.get("name")
            or service_reason,
        },
        "expiration": (now + timedelta(hours=2)).isoformat(),
        "source_order": CHATBOT_CUSTOMER_TYPE_ID,
        "customer_source": _api_customer_source(payload),
        "step": branch_fields.get("step", "appointment"),
        "many_chat_id": (
            payload.get("many_chat_id")
            or payload.get("channel_user_id")
            or payload.get("user_id")
            or payload.get("id")
        ),
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "contact_no": str(contact_number),
        "car_make": payload.get("car_make"),
        "car_model": payload.get("car_model"),
        "payment_option": payment_option_row.get("id"),
        "payment_type": payment_type_row.get("id"),
        "payment_option_details": payment_option_row,
        "payment_option_value": payment_type_row.get("value") or payment_type_row.get("name"),
        "sub_payment_type": payment_type_row.get("value") or payment_type_row.get("name"),
        "payment_type_details": payment_type_row,
        "direct_payment": payment_type_row.get("direct_payment"),
        "deliver_tires_today": 0,
    }
    return {"data": data_block, "newCartItems": [cart_item]}


def _api_customer_source(payload: Dict[str, Any]) -> str:
    """Return the dashboard sales-agent/source label for chatbot-created orders."""

    return canonical_customer_source(payload)


def _validate_order_api_payload(order_payload: Any) -> List[Dict[str, str]]:
    invalid: List[Dict[str, str]] = []
    if not isinstance(order_payload, dict) or not order_payload:
        return [
            {
                "field": "order_payload",
                "value": "",
                "reason": "missing_required",
            }
        ]
    data = order_payload.get("data") if isinstance(order_payload.get("data"), dict) else {}
    items = order_payload.get("newCartItems") if isinstance(order_payload.get("newCartItems"), list) else []
    if not data:
        invalid.append({"field": "data", "value": "", "reason": "missing_required"})
    if not items:
        invalid.append({"field": "newCartItems", "value": "", "reason": "missing_required"})
    required_data = [
        "transaction_type",
        "payment_option",
        "payment_type",
        "first_name",
        "last_name",
        "email",
        "contact_no",
        "total",
    ]
    for field_name in required_data:
        if data.get(field_name) in (None, "", []):
            invalid.append({"field": field_name, "value": "", "reason": "missing_required"})
    if data.get("email") and not _looks_like_email(str(data.get("email"))):
        invalid.append({"field": "email", "value": str(data.get("email")), "reason": "invalid_format"})
    if data.get("contact_no") and not _looks_like_contact_number(str(data.get("contact_no"))):
        invalid.append({"field": "contact_no", "value": str(data.get("contact_no")), "reason": "invalid_format"})
    item = items[0] if items and isinstance(items[0], dict) else {}
    for field_name in ["model", "quantity", "selected_quantity"]:
        if item.get(field_name) in (None, "", []):
            invalid.append({"field": f"newCartItems[0].{field_name}", "value": "", "reason": "missing_required"})
    transaction_label = " ".join(
        str(value or "")
        for value in [
            data.get("transaction_type"),
            (data.get("transaction_type_details") or {}).get("name") if isinstance(data.get("transaction_type_details"), dict) else "",
            (data.get("transaction_type_details") or {}).get("description") if isinstance(data.get("transaction_type_details"), dict) else "",
        ]
    ).lower()
    if "install" in transaction_label and "home" not in transaction_label:
        for field_name in ["selectedBranch", "branch", "delivery_date", "delivery_time"]:
            if data.get(field_name) in (None, "", [], {}):
                invalid.append({"field": field_name, "value": "", "reason": "missing_required"})
    if "delivery" in transaction_label:
        if data.get("address_1") in (None, "", []):
            invalid.append({"field": "address_1", "value": "", "reason": "missing_required"})
    return _unique_invalid_fields(invalid)


def _checkout_metadata(provider: Optional[CanonicalValuesProvider]) -> Dict[str, Any]:
    """Return checkout metadata without making payload validation depend on raw text."""

    return shared_checkout_metadata(provider)


def _api_transaction_for_service_path(service_path: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    return resolve_transaction_for_service_path(service_path, metadata)


def _api_payment_option(payment_option: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    return resolve_payment_option(payment_option, metadata)


def _api_payment_option_label(payment_option: str) -> str:
    return shared_payment_option_label(payment_option)


def _api_payment_type(
    payment_method: str,
    metadata: Dict[str, Any],
    *,
    payment_option_id: Any,
) -> Dict[str, Any]:
    return resolve_payment_type(payment_method, metadata, payment_option_id=payment_option_id)


def _default_pay_now_payment_method(metadata: Dict[str, Any]) -> str:
    """Return the safest local method for the default QR-code Pay Now route."""

    rows = [row for row in (metadata.get("payment_types") or []) if isinstance(row, dict)]
    for row in rows:
        option_id = str(row.get("main_payment_type_id") or "").strip()
        label = " ".join(str(row.get(key) or "") for key in ("name", "label", "value")).lower()
        if option_id == "2" and "gcash" in label:
            return str(row.get("name") or row.get("label") or row.get("value") or "GCash").strip()
    for row in rows:
        label = " ".join(str(row.get(key) or "") for key in ("name", "label", "value")).lower()
        if "gcash" in label:
            return str(row.get("name") or row.get("label") or row.get("value") or "GCash").strip()
    return "GCash"


def _api_selected_branch(
    service_location: Dict[str, Any],
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Dict[str, Any]:
    if not isinstance(service_location, dict) or not service_location:
        return {}
    branch_id = service_location.get("id") or service_location.get("branch_id")
    if branch_id in (None, ""):
        return {}
    catalog_branch = _provider_branch_by_id(canonical_values_provider, branch_id)
    if catalog_branch:
        return catalog_branch
    branch = deepcopy(service_location)
    branch["id"] = branch_id
    if branch.get("active") in (None, ""):
        branch["active"] = True
    return branch


def _api_branch_fields(
    *,
    service_path: str,
    selected_branch: Dict[str, Any],
    schedule_parts: Dict[str, str],
) -> Dict[str, Any]:
    if service_path in {"installation", "pickup"} and selected_branch:
        fields: Dict[str, Any] = {
            "selectedBranch": selected_branch,
            "branch": selected_branch.get("id") or selected_branch.get("branch_id"),
            "area": selected_branch.get("area") or selected_branch.get("city") or selected_branch.get("province"),
        }
        if schedule_parts:
            fields["delivery_date"] = schedule_parts.get("delivery_date")
            fields["delivery_time"] = schedule_parts.get("delivery_time")
        return _drop_empty_dict_values(fields)
    return {"selectedBranch": None, "branch": None, "area": None}


def _api_address_fields(*, service_path: str, delivery_address: str, location: str) -> Dict[str, Any]:
    if service_path not in {"delivery", "home_service"}:
        return {}
    return _heuristic_address_fields(delivery_address or location)


def _heuristic_address_fields(address: str) -> Dict[str, Any]:
    parts = [part.strip() for part in re.split(r"[,\n]", str(address or "")) if part.strip()]
    address_1 = parts[0] if parts else str(address or "").strip()
    city = None
    province = None
    if len(parts) >= 3:
        city = parts[-2]
        province = parts[-1]
    elif len(parts) == 2:
        city = parts[-1]
    elif parts:
        city = parts[-1]
    return {
        "address_1": address_1,
        "city_1": city.upper() if city else None,
        "province_1": province.upper() if province else None,
        "barangay": None,
        "zip_code": None,
    }


def _api_amount_fields(
    quote_breakdown: Dict[str, Any],
    *,
    selected_product: Dict[str, Any],
    quantity: int,
) -> Dict[str, Any]:
    discount = _coerce_float(quote_breakdown.get("product_discount_savings")) or 0.0
    buy3get1_discount = discount if _truthy(selected_product.get("buy3get1_eligible")) else 0.0
    return {
        "buy3get1_discount": buy3get1_discount,
        "paynamics_discount": _coerce_float(quote_breakdown.get("pay_now_discount")) or 0.0,
        "total": _coerce_float(quote_breakdown.get("order_total")),
        "totalDelivery": _coerce_float(quote_breakdown.get("delivery_fee")) or 0.0,
        "total_dp": quote_breakdown.get("reservation_fee"),
        "delivery_fee": _coerce_float(quote_breakdown.get("delivery_fee")) or 0.0,
        "service_fee": _coerce_float(quote_breakdown.get("home_service_fee")) or 0.0,
    }


def _api_cart_item(
    selected_product: Dict[str, Any],
    *,
    quantity: int,
    now: datetime,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Dict[str, Any]:
    product_id = selected_product.get("product_id") or selected_product.get("id")
    catalog_product = _provider_product_by_id(canonical_values_provider, product_id)
    if catalog_product:
        item = deepcopy(catalog_product)
        item["id"] = item.get("product_id") or item.get("id") or product_id
        item["product_id"] = item.get("product_id") or item.get("id") or product_id
        item["quantity"] = quantity
        item["selected_quantity"] = quantity
        item["buy_it_now"] = None
        item["spare_tire"] = None
        item["spare_product_id"] = None
        item["buy3get1"] = 1 if item.get("promo_tag") else 0
        item["total_sold"] = item.get("total_sold")
        item["default_image"] = item.get("image_do") or item.get("image")
        item["default_product_banner"] = item.get("product_banner")
        item["product_price"] = item.get("b2b_price") or item.get("product_price")
        item["lp_date"] = now.strftime("%Y-%m-%d %H:%M:%S")
        item["date_added_to_cart"] = now.isoformat()
        item.pop("bundle_pricing", None)
        return item
    unit_price = _coerce_float(selected_product.get("price"))
    list_price = _coerce_float(selected_product.get("list_price")) or unit_price
    return {
        "id": product_id,
        "product_id": product_id,
        "slug": selected_product.get("slug"),
        "model": _product_model_for_submit(selected_product),
        "make": str(selected_product.get("brand") or "").strip().upper(),
        "section_width": selected_product.get("section_width"),
        "aspect_ratio": selected_product.get("aspect_ratio"),
        "rim_size": selected_product.get("rim_size"),
        "srp": list_price,
        "promo": unit_price,
        "sale_tag": bool(selected_product.get("product_discount_amount")),
        "promo_tag": bool(selected_product.get("buy3get1_eligible")),
        "quantity": quantity,
        "selected_quantity": quantity,
        "buy_it_now": None,
        "spare_tire": None,
        "spare_product_id": None,
        "buy3get1": 1 if selected_product.get("buy3get1_eligible") else 0,
        "total_sold": selected_product.get("total_sold"),
        "default_image": selected_product.get("image") or selected_product.get("image_do"),
        "default_product_banner": selected_product.get("product_banner"),
        "product_price": unit_price,
        "tire_type": str(selected_product.get("category") or "").strip().upper(),
        "page_source": str(selected_product.get("category") or "").strip().upper(),
        "lp_date": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date_added_to_cart": now.isoformat(),
    }


def _provider_product_by_id(
    provider: Optional[CanonicalValuesProvider],
    product_id: Any,
) -> Dict[str, Any]:
    if provider is None or product_id in (None, ""):
        return {}
    loader = getattr(provider, "product_by_id", None)
    if not callable(loader):
        return {}
    try:
        row = loader(product_id)
    except Exception:
        return {}
    return deepcopy(row) if isinstance(row, dict) else {}


def _provider_branch_by_id(
    provider: Optional[CanonicalValuesProvider],
    branch_id: Any,
) -> Dict[str, Any]:
    if provider is None or branch_id in (None, ""):
        return {}
    loader = getattr(provider, "branch_by_id", None)
    if not callable(loader):
        return {}
    try:
        row = loader(branch_id)
    except Exception:
        return {}
    return deepcopy(row) if isinstance(row, dict) else {}


def _product_model_for_submit(product: Dict[str, Any]) -> str:
    return str(
        product.get("model")
        or product.get("sku_model")
        or " ".join(
            part
            for part in [
                product.get("brand"),
                _product_size(product),
                product.get("pattern"),
            ]
            if part
        )
    ).strip()


def _api_schedule_parts(schedule: Any) -> Dict[str, str]:
    if isinstance(schedule, dict):
        date = str(schedule.get("date") or "").strip()
        time_text = str(schedule.get("time") or schedule.get("time_text") or "").strip()
        if date and time_text:
            normalized_time = _normalize_time_for_api(time_text)
            if normalized_time:
                return {"delivery_date": date, "delivery_time": normalized_time}
    text = str(schedule or "").strip()
    if not text:
        return {}
    normalized = text.replace("T", " ")
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        parsed = None
    if parsed is None:
        match = re.search(
            r"\b(?P<date>\d{4}-\d{2}-\d{2})\b.*?\b(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?)\b",
            text,
        )
        if not match:
            return {}
        normalized_time = _normalize_time_for_api(match.group("time"))
        return {"delivery_date": match.group("date"), "delivery_time": normalized_time} if normalized_time else {}
    if parsed.tzinfo:
        parsed = parsed.astimezone(MANILA_TZ)
    return {"delivery_date": parsed.date().isoformat(), "delivery_time": parsed.time().strftime("%H:%M:%S")}


def _normalize_time_for_api(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
        try:
            parsed = datetime.strptime(text.upper(), fmt)
            return parsed.time().strftime("%H:%M:%S")
        except Exception:
            continue
    compact = re.sub(r"\s+", "", text.upper())
    for fmt in ("%I%p",):
        try:
            parsed = datetime.strptime(compact, fmt)
            return parsed.time().strftime("%H:%M:%S")
        except Exception:
            continue
    return ""


def _order_id_from_submit_response(api_response: Dict[str, Any]) -> str:
    data = api_response.get("data") if isinstance(api_response.get("data"), dict) else {}
    for source in [api_response, data]:
        for key in ["order_no", "invoice_no", "order_id", "id"]:
            value = source.get(key) if isinstance(source, dict) else None
            if value not in (None, ""):
                return str(value)
    return ""


def _looks_like_submit_success(api_response: Dict[str, Any]) -> bool:
    status = str(api_response.get("status") or api_response.get("result") or "").strip().lower()
    if status in {"success", "ok", "submitted"}:
        return True
    if api_response.get("error") or status == "error":
        return False
    return bool(_order_id_from_submit_response(api_response))


def _order_id_for_details(payload: Dict[str, Any]) -> str:
    for key in ("order_id", "order_no", "order_number", "id"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _payment_order_id(
    payload: Dict[str, Any],
    payment_request_store: Optional[Mapping[str, Dict[str, Any]]],
) -> str:
    for key in ("order_id", "order_no", "order_number", "invoice_no", "id"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value).strip()
    latest = _latest_payment_request(payment_request_store)
    return str(latest.get("order_id") or "").strip()


def _payment_request_selection(payload: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve payment request method from tool args plus submitted payload."""

    payment_option = _payment_request_option(payload, data)
    explicit_method = _payment_request_explicit_method(payload)
    order_method = _payment_request_order_method(data)
    bank = str(payload.get("bank") or "").strip()
    installment_months = str(payload.get("installment_months") or "").strip()
    if explicit_method and _is_bank_only_payment_text(explicit_method) and _payment_method_text_has_card_or_installment(order_method):
        method = order_method
        if not bank:
            bank = explicit_method
    else:
        method = explicit_method or order_method
    metadata = _payment_request_metadata(data)
    selection = resolve_payment_selection(
        payment_option=payment_option,
        payment_method=method,
        bank=bank,
        installment_months=installment_months,
        metadata=metadata,
    )
    if selection.get("status") in {"unsupported", "conflict"} and explicit_method and order_method and method != order_method:
        fallback = resolve_payment_selection(
            payment_option=payment_option,
            payment_method=order_method,
            bank=bank,
            installment_months=installment_months,
            metadata=metadata,
        )
        if fallback.get("status") == "ready":
            return fallback
    return selection


def _payment_request_option(payload: Dict[str, Any], data: Dict[str, Any]) -> str:
    explicit = shared_normalize_payment_option(payload.get("payment_option"))
    if explicit:
        return explicit
    details = data.get("payment_option_details") if isinstance(data.get("payment_option_details"), dict) else {}
    name = str(details.get("name") or "").strip()
    if name:
        return shared_normalize_payment_option(name)
    raw = data.get("payment_option")
    if str(raw or "").strip() == "1":
        return "Pay Later / Pay After Service"
    if str(raw or "").strip() == "2":
        return "Pay Now"
    return shared_normalize_payment_option(raw)


def _payment_request_explicit_method(payload: Dict[str, Any]) -> str:
    for key in ("payment_method", "payment_type", "reservation_payment_method", "balance_payment_method"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _payment_request_order_method(data: Dict[str, Any]) -> str:
    """Return one authoritative payment-row label from the submitted payload."""

    details = data.get("payment_type_details") if isinstance(data.get("payment_type_details"), dict) else {}
    for value in (
        details.get("name"),
        details.get("label"),
        details.get("value"),
        data.get("payment_option_value"),
        data.get("sub_payment_type"),
    ):
        if str(value or "").strip():
            return str(value).strip()
    return ""


def _payment_request_method(payload: Dict[str, Any], data: Dict[str, Any]) -> str:
    return _payment_request_explicit_method(payload) or _payment_request_order_method(data)


def _payment_request_metadata(data: Dict[str, Any]) -> Dict[str, Any]:
    metadata = shared_checkout_metadata(None)
    option_row = data.get("payment_option_details") if isinstance(data.get("payment_option_details"), dict) else {}
    type_row = data.get("payment_type_details") if isinstance(data.get("payment_type_details"), dict) else {}
    if option_row:
        metadata["payment_options"] = [option_row]
    if type_row:
        metadata["payment_types"] = [type_row]
    return metadata


def _is_bank_only_payment_text(value: Any) -> bool:
    text = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "", text)
    return normalized in {"bpi", "bdo", "metrobank", "eastwest", "hsbc", "chinabank"}


def _payment_method_text_has_card_or_installment(value: Any) -> bool:
    text = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "", text)
    return any(token in text for token in ("credit", "debit", "card", "installment", "2c2p")) or "cc" in normalized


def _payment_selection_is_installment_route(selection: Dict[str, Any]) -> bool:
    if not isinstance(selection, dict):
        return False
    values = [
        selection.get("payment_method"),
        selection.get("payment_method_for_submit"),
        selection.get("reservation_payment_method"),
        selection.get("balance_payment_method"),
    ]
    return any(_payment_text_mentions_installment_route(value) for value in values) or bool(
        selection.get("installment_months")
    )


def _payment_stage_and_amount(
    payload: Dict[str, Any],
    data: Dict[str, Any],
    *,
    payment_option: str,
    payment_method: str,
) -> Tuple[str, Optional[float]]:
    requested_stage = _normalize_text(payload.get("payment_stage") or payload.get("stage"))
    total = _coerce_float(data.get("total"))
    reservation_fee = _coerce_float(data.get("total_dp"))
    if payment_request_requires_full_payment(data, payment_method):
        return "full_payment", total
    if requested_stage in {"balance", "balance_payment", "remaining_balance"}:
        if total is not None and reservation_fee is not None:
            return "balance_payment", round(total - reservation_fee, 2)
        return "balance_payment", None
    normalized_option = shared_normalize_payment_option(payment_option)
    if normalized_option == "Pay Later / Pay After Service":
        return "reservation_fee", reservation_fee
    return "full_payment", total


def _payment_order_details_context(order_id: str, http_client: Any) -> Dict[str, Any]:
    if not order_id or http_client is None or not hasattr(http_client, "post_json"):
        return {}
    result = get_order_details(payload={"order_id": order_id}, http_client=http_client)
    if not isinstance(result, dict) or result.get("status") != "ok":
        return {}
    returned_order_id = str(result.get("order_id") or "").strip()
    if returned_order_id and returned_order_id != str(order_id or "").strip():
        return {}
    return {
        "order_id": returned_order_id or order_id,
        "order_status": result.get("order_status"),
        "payment_status": result.get("payment_status"),
        "totals": deepcopy(result.get("totals") or {}),
        "payment": deepcopy(result.get("payment") or {}),
        "fulfillment": deepcopy(result.get("fulfillment") or {}),
    }


def _payment_expected_amount_from_order_details(
    order_details_context: Dict[str, Any],
    *,
    payment_stage: str,
) -> Optional[float]:
    if not order_details_context:
        return None
    totals = order_details_context.get("totals") if isinstance(order_details_context.get("totals"), dict) else {}
    if payment_stage == "full_payment":
        return _coerce_float(totals.get("overall_total") or totals.get("total"))
    if payment_stage == "balance_payment":
        overall = _coerce_float(totals.get("overall_total") or totals.get("total"))
        reservation = _coerce_float(totals.get("reservation_fee") or totals.get("total_dp"))
        if overall is not None and reservation is not None:
            return round(overall - reservation, 2)
    return None


def _submitted_order_amount_mismatch(order_payload: Dict[str, Any], api_response: Dict[str, Any]) -> Dict[str, Any]:
    data = order_payload.get("data") if isinstance(order_payload.get("data"), dict) else {}
    payload_total = _coerce_float(data.get("total"))
    api_total = _submit_response_total(api_response)
    return _amount_mismatch_context(
        expected_total=payload_total,
        observed_total=api_total,
        expected_source="validated_order_payload",
        observed_source="/order response",
    )


def _payment_request_amount_mismatch(
    payload_expected_amount: Optional[float],
    persisted_total: Optional[float],
    *,
    source: str,
) -> Dict[str, Any]:
    return _amount_mismatch_context(
        expected_total=payload_expected_amount,
        observed_total=persisted_total,
        expected_source="validated_order_payload",
        observed_source=source,
    )


def _submit_response_total(api_response: Dict[str, Any]) -> Optional[float]:
    if not isinstance(api_response, dict):
        return None
    candidates = [
        api_response.get("t"),
        api_response.get("total"),
        api_response.get("overall_total"),
    ]
    data = api_response.get("data")
    if isinstance(data, dict):
        candidates.extend([data.get("t"), data.get("total"), data.get("overall_total")])
    for value in candidates:
        total = _coerce_money(value)
        if total is not None:
            return total
    return None


def _amount_mismatch_context(
    *,
    expected_total: Optional[float],
    observed_total: Optional[float],
    expected_source: str,
    observed_source: str,
) -> Dict[str, Any]:
    if expected_total is None or observed_total is None:
        return {}
    difference = round(float(observed_total) - float(expected_total), 2)
    if abs(difference) <= 0.01:
        return {}
    return {
        "status": "mismatch",
        "expected_total": round(float(expected_total), 2),
        "expected_total_text": _money_text(float(expected_total)),
        "expected_source": expected_source,
        "observed_total": round(float(observed_total), 2),
        "observed_total_text": _money_text(float(observed_total)),
        "observed_source": observed_source,
        "difference": difference,
        "difference_text": _signed_money_text(difference),
        "customer_note": (
            "Final submitted order total differs from the earlier Runtime V7 payload total. "
            "Use the backend order total as the payment amount and make the difference visible."
        ),
    }


def _signed_money_text(value: float) -> str:
    prefix = "+" if float(value) > 0 else "-"
    return f"{prefix}{_money_text(abs(float(value)))}"


def _payment_instruction_route(payment_method: str, *, instruction_mode: str = "") -> str:
    return policy_payment_instruction_route(payment_method, instruction_mode=instruction_mode)


def _create_2c2p_payment_link(
    *,
    order_id: str,
    order_payload: Dict[str, Any],
    expected_amount: float,
    http_client: Any,
) -> Tuple[Dict[str, Any], str]:
    if http_client is None or not hasattr(http_client, "post_json"):
        return {}, "payment_link_http_client_not_configured"
    data = order_payload.get("data") if isinstance(order_payload.get("data"), dict) else {}
    params = {
        "invoiceNo": order_id,
        "email": data.get("email"),
        "name": f"{data.get('first_name', '')} {data.get('last_name', '')}".strip(),
        "mobileNo": data.get("contact_no"),
        "description": (data.get("transaction_type_details") or {}).get("description")
        if isinstance(data.get("transaction_type_details"), dict)
        else data.get("transaction_type"),
        "amount": expected_amount,
        "paymentChannel": data.get("payment_option_value"),
    }
    try:
        response = http_client.post_json("/2c2p/payload", json_data=params)
    except Exception as exc:
        return {}, f"{exc.__class__.__name__}: {exc}"
    response = response if isinstance(response, dict) else {"response": response}
    if str(response.get("status") or "").strip().lower() == "error":
        return {}, str(response.get("content") or response.get("message") or "2c2p_error")
    body = response.get("response") if isinstance(response.get("response"), dict) else response
    url = _extract_payment_link(body)
    if not url:
        return {}, "2c2p_payment_link_missing"
    return {
        "url": url,
        "provider": "2c2p",
        "source": "/2c2p/payload",
    }, ""


def _extract_payment_link(payment_result: Any) -> str:
    if not isinstance(payment_result, dict):
        return ""
    for key in ("payment_url", "webPaymentUrl", "paymentLink", "url"):
        value = str(payment_result.get(key) or "").strip()
        if value:
            return value
    return ""


def _load_payment_options() -> Dict[str, Any]:
    try:
        with PAYMENT_OPTIONS_CONFIG_PATH.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _payment_qr_image(payment_options: Dict[str, Any]) -> Dict[str, str]:
    url = str(payment_options.get("qr_image_url") or "").strip()
    if not url:
        return {}
    return {
        "image_ref": "img_payment_qr_gulong",
        "url": url,
        "alt": "Gulong.PH payment QR code",
    }


def _payment_manual_details(payment_options: Dict[str, Any]) -> List[Dict[str, str]]:
    details: List[Dict[str, str]] = []
    for method, info in payment_options.items():
        if method == "qr_image_url" or not isinstance(info, dict):
            continue
        row = {
            "method": str(method),
            "account_name": str(info.get("account_name") or "").strip(),
            "account_number": str(info.get("account_number") or "").strip(),
        }
        if row["account_name"] or row["account_number"]:
            details.append(row)
    return details


def _payment_request_ref(payload: Dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, default=str)
    digest = hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]
    return f"payment_request_{digest}"


def _payment_instruction_block(
    *,
    order_id: str,
    payment_stage: str,
    expected_amount: float,
    amount_breakdown: Dict[str, Any],
    amount_mismatch: Dict[str, Any],
    instruction_type: str,
    primary_method: str,
    payment_link: Dict[str, Any],
    qr_image: Dict[str, Any],
    manual_details: Sequence[Dict[str, str]],
    link_error: str,
) -> str:
    lines = [
        f"💳 Payment Request for Order {order_id}",
    ]
    subtotal = _coerce_float(amount_breakdown.get("subtotal_before_pay_now_discount"))
    pay_now_discount = _coerce_float(amount_breakdown.get("pay_now_discount"))
    if pay_now_discount and subtotal is not None:
        lines.append("")
        lines.append(f"Product/Order Total: {_money_text(subtotal)}")
        lines.append(f"Pay Now Discount: -{_money_text(pay_now_discount)}")
    lines.append(f"Amount Due: {_money_text(expected_amount)} ({_payment_stage_label(payment_stage)})")
    if amount_mismatch:
        observed = str(amount_mismatch.get("observed_total_text") or "").strip()
        expected = str(amount_mismatch.get("expected_total_text") or "").strip()
        difference = str(amount_mismatch.get("difference_text") or "").strip()
        if observed and expected and difference:
            lines.extend(
                [
                    "",
                    (
                        "Note: Final backend order total is "
                        f"{observed}. Earlier summary/payload was {expected} "
                        f"({difference} difference). Please verify before paying."
                    ),
                ]
            )
    if primary_method == "2c2p_payment_link" and payment_link.get("url"):
        lines.extend(["", "🔗 Primary Payment Link:", str(payment_link.get("url"))])
    elif qr_image.get("url"):
        lines.extend(["", "📷 Primary Payment QR:", str(qr_image.get("url"))])
    if link_error:
        lines.append(f"Payment link status: {link_error}")
    if manual_details:
        lines.extend(["", "🏦 Alternative Account Details:"])
        for row in manual_details:
            lines.append("")
            lines.append(str(row.get("method") or "").strip())
            if row.get("account_name"):
                lines.append(f"Account Name: {row['account_name']}")
            if row.get("account_number"):
                lines.append(f"Account Number: {row['account_number']}")
    return "\n".join(line for line in lines if str(line or "").strip())


def _payment_amount_breakdown(data: Dict[str, Any], expected_amount: float) -> Dict[str, Any]:
    pay_now_discount = _coerce_float(data.get("paynamics_discount")) or 0.0
    total = _coerce_float(data.get("total"))
    breakdown: Dict[str, Any] = {
        "amount_due": expected_amount,
        "amount_due_text": _money_text(expected_amount),
    }
    if pay_now_discount:
        subtotal = round((total if total is not None else expected_amount) + pay_now_discount, 2)
        breakdown.update(
            {
                "subtotal_before_pay_now_discount": subtotal,
                "subtotal_before_pay_now_discount_text": _money_text(subtotal),
                "pay_now_discount": pay_now_discount,
                "pay_now_discount_text": f"-{_money_text(pay_now_discount)}",
            }
        )
    return breakdown


def _payment_stage_label(payment_stage: str) -> str:
    return {
        "reservation_fee": "reservation fee",
        "balance_payment": "balance payment",
        "full_payment": "full payment",
    }.get(str(payment_stage or "").strip(), str(payment_stage or "").strip() or "payment")


def _latest_payment_request(payment_request_store: Optional[Mapping[str, Dict[str, Any]]]) -> Dict[str, Any]:
    if not payment_request_store:
        return {}
    refs = [ref for ref in payment_request_store if str(ref or "").strip()]
    if not refs:
        return {}
    return dict(payment_request_store.get(refs[-1]) or {})


def _payment_request_from_store(
    payload: Dict[str, Any],
    payment_request_store: Optional[Mapping[str, Dict[str, Any]]],
) -> Dict[str, Any]:
    ref = str(payload.get("payment_request_ref") or "").strip()
    if ref and payment_request_store and isinstance(payment_request_store.get(ref), dict):
        return dict(payment_request_store.get(ref) or {})
    latest = _latest_payment_request(payment_request_store)
    return latest if latest else {}


def _payment_match_order_payload(
    payload: Dict[str, Any],
    payment_request: Dict[str, Any],
    order_payload_store: Optional[Mapping[str, Dict[str, Any]]],
) -> Dict[str, Any]:
    direct = payload.get("order_payload")
    if isinstance(direct, dict) and direct:
        return direct
    ref = str(payload.get("order_payload_ref") or payment_request.get("order_payload_ref") or "").strip()
    if ref and order_payload_store and isinstance(order_payload_store.get(ref), dict):
        return dict(order_payload_store.get(ref) or {})
    return {}


def _payment_evidence_from_refs(
    payload: Dict[str, Any],
    refs: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    direct = payload.get("payment_evidence") or payload.get("evidence")
    if isinstance(direct, dict) and direct:
        return direct
    requested_ref = str(payload.get("evidence_ref") or payload.get("payment_proof_evidence_ref") or "").strip()
    candidates = [ref for ref in refs or [] if isinstance(ref, dict)]
    if requested_ref:
        for ref in candidates:
            if str(ref.get("evidence_ref") or "").strip() == requested_ref:
                return ref
    for ref in reversed(candidates):
        if str(ref.get("image_type") or "").strip().lower() == "payment_proof":
            return ref
    return {}


def _coerce_money(value: Any) -> Optional[float]:
    text = str(value or "").strip()
    text = re.sub(r"(?i)\b(?:php|peso|pesos|p)\b", "", text).strip()
    text = text.replace("₱", "").replace(",", "")
    return _coerce_float(text)


def _amount_matches(extracted: Optional[float], expected: Optional[float]) -> bool:
    if extracted is None or expected is None:
        return False
    return abs(float(extracted) - float(expected)) <= 1.0


def _payment_proof_hints(
    status: str,
    missing: Sequence[str],
    mismatches: Sequence[Dict[str, str]],
) -> List[str]:
    if status == "matched_unverified":
        return ["Acknowledge that payment proof was received and will be verified by the team."]
    if status == "verified_paid":
        return ["Backend order details indicate the payment is already marked paid."]
    if mismatches:
        return ["Explain that the screenshot amount does not match the expected payment amount and ask for clarification."]
    if missing:
        return ["Acknowledge receipt but ask for the missing proof detail or say the team will verify it."]
    return ["Acknowledge the payment proof without claiming the order is paid yet."]


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _order_details_record(api_response: Any) -> Dict[str, Any]:
    if not isinstance(api_response, dict):
        return {}
    data = api_response.get("data")
    if isinstance(data, dict) and (data.get("id") or data.get("Status") or data.get("item_orders")):
        return deepcopy(data)
    if api_response.get("id") or api_response.get("Status") or api_response.get("item_orders"):
        return deepcopy(api_response)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return deepcopy(data[0])
    return {}


def _order_details_error_message(api_response: Any) -> str:
    if not isinstance(api_response, dict):
        return "Order details endpoint returned no order record."
    for key in ("message", "error", "content", "reason"):
        value = api_response.get(key)
        if value not in (None, ""):
            return str(value)
    return "Order details endpoint returned no order record."


def _compact_order_details(record: Dict[str, Any], *, requested_order_id: str) -> Dict[str, Any]:
    transaction_id = record.get("trans_type_id") or record.get("transaction_type")
    payment_type_id = record.get("payment_type_id") or record.get("payment_type")
    appointment_date = (
        record.get("pickup_date")
        or record.get("delivery_date")
        or record.get("request_schedule")
        or record.get("app_date")
    )
    return _drop_empty_dict_values(
        {
            "order_id": str(record.get("id") or record.get("order_no") or requested_order_id),
            "order_date": record.get("date_created") or record.get("created_at"),
            "appointment_date": appointment_date,
            "order_status": record.get("Status") or record.get("status"),
            "payment_status": record.get("payment_status"),
            "unpaid_order_status": record.get("unpaid_order_status"),
            "contacted": record.get("contacted"),
            "customer": _drop_empty_dict_values(
                {
                    "name": record.get("customer_name"),
                    "contact_number": record.get("phone_number") or record.get("contact_no"),
                    "many_chat_id": record.get("many_chat_id"),
                    "customer_type_id": record.get("customer_type_id"),
                    "customer_source": record.get("customer_source"),
                }
            ),
            "transaction": _drop_empty_dict_values(
                {
                    "type_id": transaction_id,
                    "label": _order_details_transaction_label(transaction_id, record),
                }
            ),
            "fulfillment": _drop_empty_dict_values(
                {
                    "branch_id": record.get("branch_id"),
                    "branch_name": record.get("branch_name"),
                    "branch_location": record.get("branch_location"),
                    "delivery_address": record.get("address") or record.get("address_1"),
                    "city": record.get("city"),
                    "province": record.get("province"),
                    "appointment_date": appointment_date,
                }
            ),
            "payment": _drop_empty_dict_values(
                {
                    "payment_option": record.get("payment_option"),
                    "payment_type_id": payment_type_id,
                    "payment_name": record.get("payment_name"),
                    "payment_value": record.get("payment_value"),
                    "payment_status": record.get("payment_status"),
                    "qr_code_available": bool(record.get("qr_code_url") or record.get("show_qr_code")),
                }
            ),
            "totals": _drop_empty_dict_values(
                {
                    "total_quantity": record.get("total_qty"),
                    "overall_total": record.get("overall_total"),
                    "delivery_fee": record.get("delivery_fee"),
                    "service_fee": record.get("service_fee"),
                    "total_discount": record.get("total_discount"),
                    "voucher_value": record.get("voucher_value"),
                }
            ),
            "items": _compact_order_detail_items(record.get("item_orders") or []),
            "add_ons": _compact_order_detail_addons(record.get("add_ons") or []),
        }
    )


def _order_details_transaction_label(transaction_id: Any, record: Dict[str, Any]) -> str:
    explicit = record.get("transaction") or record.get("trans_name") or record.get("transaction_name")
    if explicit:
        return str(explicit)
    labels = {
        "1": "Install",
        "2": "Pick-up",
        "3": "Delivery",
        "4": "Home Service",
    }
    return labels.get(str(transaction_id or "").strip(), "")


def _compact_order_detail_items(items: Sequence[Any]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for item in items[:6]:
        if not isinstance(item, dict):
            continue
        output.append(
            _drop_empty_dict_values(
                {
                    "item_id": item.get("id"),
                    "product_id": item.get("product_id"),
                    "sku": item.get("sku") or item.get("model"),
                    "slug": item.get("slug"),
                    "quantity": item.get("quantity"),
                    "price": item.get("price"),
                    "srp": item.get("srp"),
                    "discount": item.get("discount"),
                    "discounted_price": item.get("discounted_price"),
                    "total_discount": item.get("total_discount"),
                    "dot": item.get("DOT_DESC"),
                    "status_id": item.get("status_id"),
                }
            )
        )
    return output


def _compact_order_detail_addons(addons: Sequence[Any]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for addon in addons[:6]:
        if not isinstance(addon, dict):
            continue
        output.append(
            _drop_empty_dict_values(
                {
                    "id": addon.get("id"),
                    "name": addon.get("name") or addon.get("service") or addon.get("addon_name"),
                    "price": addon.get("price") or addon.get("amount"),
                    "quantity": addon.get("quantity"),
                }
            )
        )
    return output


def _order_payload_source_refs(
    *,
    payload: Dict[str, Any],
    latest_product: Optional[ProductObservation],
    latest_service: Optional[ServiceObservation],
    service_location: Dict[str, Any],
    quote_ref: str,
) -> Dict[str, Any]:
    return {
        "product_observation_ref": (
            payload.get("product_observation_ref")
            or payload.get("observation_ref")
            or getattr(latest_product, "observation_ref", "")
        ),
        "product_presentation_ref": (
            payload.get("product_presentation_ref")
            or payload.get("presentation_ref")
            or getattr(latest_product, "presentation_ref", "")
        ),
        "product_card_ref": payload.get("product_card_ref") or payload.get("card_ref"),
        "product_item_ref": payload.get("product_item_ref") or payload.get("item_ref"),
        "service_observation_ref": getattr(latest_service, "observation_ref", ""),
        "service_presentation_ref": getattr(latest_service, "presentation_ref", ""),
        "service_location_ref": (
            payload.get("service_location_ref")
            or payload.get("installation_partner_ref")
            or service_location.get("service_location_ref")
            or service_location.get("installation_partner_ref")
        ),
        "quote_ref": quote_ref,
    }


def _order_payload_hints(
    *,
    status: str,
    missing: Sequence[str],
    invalid: Sequence[Dict[str, str]],
    service_path: str,
) -> List[str]:
    if status == "ready":
        return [
            "Payload validation passed. The next submit/payment action may use order_payload_ref when those tools exist.",
            "Do not tell the customer the order is submitted, reserved, booked, or paid yet.",
        ]
    hints: List[str] = []
    if invalid:
        hints.append("Ask the customer to correct the invalid order detail before submission.")
    if missing:
        hints.append("Ask only for the missing detail that best moves order submission forward.")
    if "Quantity confirmation" in set(missing):
        hints.append("A default quantity is not enough for submission; ask the customer to confirm quantity.")
    if service_path == "installation" and any("installation" in str(item).lower() for item in missing):
        hints.append("Installation orders need a selected partner and schedule before submission.")
    if service_path == "delivery" and any("delivery" in str(item).lower() for item in missing):
        hints.append("Delivery orders need a complete delivery address before submission.")
    return hints or ["Order payload is not ready; continue collecting the smallest missing order detail."]


def _service_compatibility_context(latest_service: Optional[ServiceObservation]) -> Dict[str, Any]:
    """Return compact service compatibility metadata for checkout planning."""

    if latest_service is None:
        return {}
    query_basis = latest_service.query_basis if isinstance(latest_service.query_basis, dict) else {}
    partner_filter = query_basis.get("partner_catalog_filter")
    if isinstance(partner_filter, dict):
        return {
            "compatibility_status": partner_filter.get("compatibility_status"),
            "verified_by_filtered_partner_catalog": partner_filter.get("verified_by_filtered_partner_catalog"),
            "status": partner_filter.get("status"),
        }
    coverage = latest_service.availability if isinstance(latest_service.availability, dict) else {}
    return {
        "compatibility_status": coverage.get("compatibility_status"),
        "status": coverage.get("status"),
    }


def _checkout_plan_invalid_fields(plan: Dict[str, Any]) -> List[Dict[str, str]]:
    """Convert checkout-plan blockers into the order tool invalid field shape."""

    output: List[Dict[str, str]] = []
    for item in plan.get("blockers") or []:
        if not isinstance(item, dict):
            continue
        output.append(
            {
                "field": str(item.get("field") or "checkout_plan"),
                "value": str(item.get("value") or ""),
                "reason": str(item.get("reason") or "Checkout compatibility blocker."),
            }
        )
    return output


def _looks_like_contact_number(value: str) -> bool:
    digits = re.sub(r"\D+", "", str(value or ""))
    return 10 <= len(digits) <= 15


def _looks_like_email(value: str) -> bool:
    text = str(value or "").strip()
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", text))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text not in {"", "0", "false", "no", "none", "null"}


def _unique_invalid_fields(items: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    output: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        field_name = str(item.get("field") or "").strip()
        value = str(item.get("value") or "").strip()
        reason = str(item.get("reason") or "").strip()
        key = (field_name.lower(), value.lower())
        if not field_name or key in seen:
            continue
        seen.add(key)
        output.append({"field": field_name, "value": value, "reason": reason})
    return output


def _drop_empty_dict_values(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, "", [], {})
    }


def _delivery_fee_for_product(product: Dict[str, Any]) -> Optional[float]:
    return policy_delivery_fee_for_product(product)


def _home_service_fee_for_product(
    product: Dict[str, Any],
    *,
    quantity: int,
    signals: Dict[str, Dict[str, Any]],
) -> Tuple[Optional[float], Optional[bool]]:
    rim = _rim_number(product, signals)
    if rim is None:
        return None, None
    qty = max(1, int(quantity or 4))
    if 14 <= rim <= 17:
        per_tire = 500.0 if qty >= 4 else 700.0
        return round(per_tire * qty, 2), True
    if 18 <= rim <= 20:
        return round(1000.0 * qty, 2), True
    if rim >= 21:
        return None, False
    return None, None


def _rim_number(product: Dict[str, Any], signals: Dict[str, Dict[str, Any]]) -> Optional[int]:
    values = [
        product.get("rim_size"),
        product.get("size"),
        _signal_value(signals, "rim_size"),
        _signal_value(signals, "tire_size"),
    ]
    for value in values:
        match = re.search(r"R?\s*(\d{2})\b", str(value or ""), flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _reservation_fee_for_total(total: float) -> float:
    value = float(total or 0)
    if value >= 80000:
        return round(value * 0.10, 2)
    if value >= 40000:
        return 1000.0
    return 500.0


def _payment_options_preview(gross_total: Optional[float]) -> Dict[str, Any]:
    if gross_total is None:
        return {}
    pay_now_total = round(gross_total - _PAY_NOW_DISCOUNT, 2)
    reservation = _reservation_fee_for_total(gross_total)
    return {
        "pay_now": {
            "discount": _PAY_NOW_DISCOUNT,
            "discount_text": _money_text(_PAY_NOW_DISCOUNT),
            "order_total": pay_now_total,
            "order_total_text": _money_text(pay_now_total),
            "amount_due_now": pay_now_total,
            "amount_due_now_text": _money_text(pay_now_total),
            "balance_due": 0.0,
            "balance_due_text": _money_text(0),
        },
        "pay_later": {
            "reservation_fee": reservation,
            "reservation_fee_text": _money_text(reservation),
            "order_total": gross_total,
            "order_total_text": _money_text(gross_total),
            "amount_due_now": reservation,
            "amount_due_now_text": _money_text(reservation),
            "balance_due": round(gross_total - reservation, 2),
            "balance_due_text": _money_text(round(gross_total - reservation, 2)),
        },
    }


def _branch_addon_context(latest_service: Optional[ServiceObservation]) -> Dict[str, Any]:
    groups = getattr(latest_service, "addon_groups", []) if latest_service else []
    if not isinstance(groups, list) or not groups:
        return {}
    items: List[Dict[str, Any]] = []
    for group in groups[:3]:
        if not isinstance(group, dict):
            continue
        for addon in group.get("addons") or []:
            if not isinstance(addon, dict):
                continue
            service = str(addon.get("service") or addon.get("name") or "").strip()
            price = _coerce_float(addon.get("promo_price") if addon.get("promo_tag") else addon.get("price"))
            if service:
                items.append(
                    {
                        "service": service,
                        "price": price,
                        "price_text": _money_text(price) if price is not None else "",
                        "installation_partner_ref": group.get("installation_partner_ref"),
                    }
                )
    if not items:
        return {}
    return {
        "items": items[:6],
        "paid_at_ip": True,
        "excluded_from_online_total": True,
    }


def _branch_addon_note(context: Any) -> str:
    if not isinstance(context, dict) or not context.get("items"):
        return ""
    names = _unique(str(item.get("service") or "").strip() for item in context.get("items") or [] if isinstance(item, dict))
    prefix = ", ".join(names[:3])
    if len(names) > 3:
        prefix += ", etc."
    if prefix:
        return f"{prefix} - paid at installation partner, not included in online total"
    return "Paid at installation partner, not included in online total"


_CRITICAL_ORDER_FIELDS = {
    "Product",
    "Tire Size",
    "Qty",
    "Product Total",
    "Delivery Fee",
    "Home Service Fee",
    "Pay Now Discount",
    "Total",
    "Amount Due Now",
    "Balance After Payment",
    "Service",
    "Delivery Address",
    "Pickup Branch",
    "Service Address",
    "Installation Area",
    "Installation Partner",
    "Schedule",
    "Payment Option",
    "Reservation Payment Method",
    "Payment Method",
    "Mode of Payment (for balance)",
    "Add-ons",
}


def _order_summary_snapshot(
    *,
    summary_ref: str,
    status: str,
    fields: Dict[str, str],
    missing_fields: Sequence[str],
    submission_blockers: Sequence[str] = (),
    schedule_status: str = "",
    quote_summary: Dict[str, Any],
    quantity: int = 0,
    quantity_defaulted: bool = False,
    quantity_source: str = "",
    payment_selection: Optional[Dict[str, Any]] = None,
    source_refs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "order_summary_ref": summary_ref,
        "status": status,
        "fields": deepcopy(fields),
        "missing_fields": list(missing_fields),
        "submission_blockers": list(submission_blockers),
        "schedule_status": str(schedule_status or ""),
        "quote_summary": deepcopy(quote_summary),
        "quantity": int(quantity or 0),
        "quantity_defaulted": bool(quantity_defaulted),
        "quantity_source": str(quantity_source or ""),
        "payment_selection": _summary_payment_selection(payment_selection or {}),
        "source_refs": _drop_empty_dict_values(dict(source_refs or {})),
    }


def _summary_payment_selection(selection: Dict[str, Any]) -> Dict[str, Any]:
    """Persist the resolved payment route from a summary for later payload tools."""

    if not isinstance(selection, dict):
        return {}
    return _drop_empty_dict_values(
        {
            "payment_option": selection.get("payment_option"),
            "payment_method": selection.get("payment_method"),
            "payment_method_for_submit": selection.get("payment_method_for_submit"),
            "reservation_payment_method": selection.get("reservation_payment_method"),
            "balance_payment_method": selection.get("balance_payment_method"),
            "bank": selection.get("bank"),
            "installment_months": selection.get("installment_months"),
            "payment_option_row": deepcopy(selection.get("payment_option_row") or {}),
            "payment_type_row": deepcopy(selection.get("payment_type_row") or {}),
        }
    )


def _order_product_source_refs(
    *,
    payload: Dict[str, Any],
    latest_product: Optional[ProductObservation],
) -> Dict[str, Any]:
    return _drop_empty_dict_values(
        {
            "product_observation_ref": (
                payload.get("product_observation_ref")
                or payload.get("observation_ref")
                or getattr(latest_product, "observation_ref", "")
            ),
            "product_presentation_ref": (
                payload.get("product_presentation_ref")
                or payload.get("presentation_ref")
                or getattr(latest_product, "presentation_ref", "")
            ),
            "product_card_ref": payload.get("product_card_ref") or payload.get("card_ref"),
            "product_item_ref": payload.get("product_item_ref") or payload.get("item_ref"),
            "product_id": payload.get("product_id"),
            "slug": payload.get("slug"),
        }
    )


def _summary_update_from_snapshot(
    previous_snapshot: Optional[Dict[str, Any]],
    current_snapshot: Dict[str, Any],
    *,
    presentation_intent: Any = None,
) -> Dict[str, Any]:
    if not isinstance(previous_snapshot, dict) or not previous_snapshot:
        return {
            "display_action": "show_form",
            "reason": "first_order_summary",
            "changed_fields": [],
            "change_count": 0,
            "critical_change_count": 0,
            "noncritical_change_count": 0,
            "confirmation_recommended": current_snapshot.get("status") == "ready",
        }
    previous_fields = previous_snapshot.get("fields") if isinstance(previous_snapshot.get("fields"), dict) else {}
    current_fields = current_snapshot.get("fields") if isinstance(current_snapshot.get("fields"), dict) else {}
    field_names = sorted(set(previous_fields) | set(current_fields))
    changes: List[Dict[str, Any]] = []
    for name in field_names:
        old_value = _snapshot_field_value(previous_fields.get(name))
        new_value = _snapshot_field_value(current_fields.get(name))
        if old_value == new_value:
            continue
        changes.append(
            {
                "field": name,
                "old": old_value,
                "new": new_value,
                "critical": name in _CRITICAL_ORDER_FIELDS,
            }
        )
    critical_count = sum(1 for change in changes if change.get("critical"))
    missing_changed = set(previous_snapshot.get("missing_fields") or []) != set(current_snapshot.get("missing_fields") or [])
    explicit_review = (
        str(presentation_intent or "").strip().casefold() == "show"
    )
    became_ready = previous_snapshot.get("status") != "ready" and current_snapshot.get("status") == "ready"
    if explicit_review or critical_count or became_ready or len(changes) > 1 or missing_changed:
        action = "show_form"
        reason = (
            "customer_requested_review"
            if explicit_review
            else "critical_order_change"
            if critical_count
            else "became_ready"
            if became_ready
            else "multiple_or_missing_changes"
        )
    else:
        action = "quiet_update"
        reason = "noncritical_order_info_update" if changes else "no_material_change"
    return {
        "display_action": action,
        "reason": reason,
        "changed_fields": changes[:8],
        "change_count": len(changes),
        "critical_change_count": critical_count,
        "noncritical_change_count": len(changes) - critical_count,
        "missing_changed": missing_changed,
        "confirmation_recommended": action == "show_form" and (critical_count > 0 or current_snapshot.get("status") == "ready"),
    }


def _snapshot_field_value(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text == "-" else text




def _selected_product(
    latest_product: Optional[ProductObservation],
    signals: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Any], str]:
    if latest_product is None:
        return {}, ""
    requested_product = _product_selection_signal_value(signals)
    requested_normalized = _normalize_product_identity_text(requested_product)
    if not requested_normalized:
        return {}, ""
    matches: List[Dict[str, Any]] = []
    visible_cards = [
        card
        for card in latest_product.product_cards
        if isinstance(card, dict)
    ]
    cards_by_item = {
        str(card.get("item_ref") or "").strip(): card
        for card in visible_cards
        if str(card.get("item_ref") or "").strip()
    }
    for row in _product_rows(latest_product):
        product = row.get("product") if isinstance(row, dict) else {}
        if not isinstance(product, dict):
            continue
        card = cards_by_item.get(str(product.get("item_ref") or "").strip()) or {}
        combined = deepcopy({**product, **card})
        aliases = {
            _normalize_product_identity_text(combined.get(key))
            for key in (
                "sku_model",
                "model",
                "pattern",
                "name",
                "title",
                "slug",
            )
        }
        aliases.add(_normalize_product_identity_text(_product_label(combined)))
        aliases.discard("")
        requested_tokens = set(requested_normalized.split())
        if any(
            requested_normalized == alias
            or requested_normalized in alias
            or alias in requested_normalized
            or requested_tokens.issubset(set(alias.split()))
            for alias in aliases
        ):
            matches.append(combined)
    if len(matches) == 1:
        return matches[0], (
            "Customer-backed product identity matched one product in trusted "
            f"observation {latest_product.observation_ref}."
        )
    return {}, ""


def _normalize_product_identity_text(value: Any) -> str:
    """Normalize a customer-backed product identity for trusted-row matching."""

    return " ".join(
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if token
    )


def _product_selection_signal_value(
    signals: Dict[str, Dict[str, Any]],
) -> str:
    """Return a customer-backed product identity that is safe to resolve.

    A customer's exact free-text SKU/model may be resolved against the trusted
    visible observation. Candidate, question-only, and explicitly unvalidated
    model interpretations cannot become a selection merely because one row
    happens to match.
    """

    signal = signals.get("specific_sku_model") or {}
    status = str(signal.get("status") or "").strip().casefold()
    if any(
        marker in status
        for marker in (
            "needs_validation",
            "unvalidated",
            "question",
            "candidate",
            "invalid",
            "rejected",
            "superseded",
            "mentioned_unconfirmed",
        )
    ):
        return ""
    return _signal_value(signals, "specific_sku_model")


def _product_for_visible_card(observation: ProductObservation, card: Dict[str, Any]) -> Dict[str, Any]:
    criteria = {
        "item_ref": str(card.get("item_ref") or "").strip(),
        "product_id": str(card.get("product_id") or "").strip(),
        "slug": str(card.get("slug") or "").strip(),
    }
    for row in _product_rows(observation):
        product = row.get("product") if isinstance(row, dict) else {}
        if not isinstance(product, dict):
            continue
        product_id = str(product.get("product_id") or product.get("id") or "").strip()
        if criteria["item_ref"] and str(product.get("item_ref") or "").strip() == criteria["item_ref"]:
            return product
        if criteria["product_id"] and product_id == criteria["product_id"]:
            return product
        if criteria["slug"] and str(product.get("slug") or "").strip() == criteria["slug"]:
            return product
    return {}


def _product_rows(observation: ProductObservation) -> List[Dict[str, Any]]:
    cards_by_item = {
        str(card.get("item_ref") or "").strip(): card
        for card in observation.product_cards
        if isinstance(card, dict) and str(card.get("item_ref") or "").strip()
    }
    products = [product for product in [*observation.presented_products, *observation.best_products] if isinstance(product, dict)]
    seen: set[str] = set()
    rows: List[Dict[str, Any]] = []
    for product in products:
        item_ref = str(product.get("item_ref") or "").strip()
        product_id = str(product.get("product_id") or product.get("id") or "").strip()
        dedupe = item_ref or product_id or str(len(rows))
        if dedupe in seen:
            continue
        seen.add(dedupe)
        card = cards_by_item.get(item_ref) or {}
        merged = {**card, **product}
        rows.append(
            {
                "product": product,
                "match_text": " ".join(
                    str(merged.get(key) or "")
                    for key in [
                        "brand",
                        "model",
                        "pattern",
                        "sku_model",
                        "size",
                        "section_width",
                        "aspect_ratio",
                        "rim_size",
                        "slug",
                    ]
                ),
            }
        )
    if not rows:
        for card in observation.product_cards:
            if isinstance(card, dict):
                rows.append({"product": card, "match_text": " ".join(str(value or "") for value in card.values())})
    return rows


def _match_score(needle: str, haystack: str) -> int:
    needle_tokens = set(_tokens(needle))
    haystack_tokens = set(_tokens(haystack))
    if not needle_tokens or not haystack_tokens:
        return 0
    return len(needle_tokens.intersection(haystack_tokens))


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def _quantity(signals: Dict[str, Dict[str, Any]], *, default_allowed: bool) -> Tuple[int, bool]:
    raw = _signal_value(signals, "quantity")
    try:
        quantity = int(re.search(r"\d+", raw).group(0)) if raw and re.search(r"\d+", raw) else 0
    except Exception:
        quantity = 0
    if quantity > 0:
        return max(1, min(quantity, 12)), False
    return (4, True) if default_allowed else (0, False)


def _trusted_total(product: Dict[str, Any], *, quantity: int) -> Optional[float]:
    if not product or quantity <= 0:
        return None
    # Product normalization owns quantity pricing. Reusing the same resolved
    # tier keeps cards, summaries, and order payloads on one evidence path.
    total = effective_total_price(product, quantity)
    if total is not None:
        return round(float(total), 2)
    price = _coerce_float(product.get("price"))
    if price is None:
        return None
    return round(price * quantity, 2)


def _checkout_pricing_basis(product: Dict[str, Any], quantity: int) -> str:
    if not product:
        return ""
    if pricing_basis(product, quantity) == "buy3get1":
        return "buy3get1"
    bundle = product.get("bundle_pricing") if isinstance(product.get("bundle_pricing"), dict) else {}
    if pricing_basis(product, quantity) == "bundle_tier":
        return str(bundle.get("source") or "bundle_tier")
    return pricing_basis(product, quantity)


def _product_label(product: Dict[str, Any]) -> str:
    brand = str(product.get("brand") or "").strip()
    model = str(product.get("pattern") or product.get("model") or product.get("sku_model") or "").strip()
    if brand and model.upper().startswith(brand.upper()):
        brand = ""
    parts = [
        brand,
        model,
        _product_size(product),
    ]
    return " ".join(part for part in parts if part).strip()


def _product_size(product: Dict[str, Any]) -> str:
    section = str(product.get("section_width") or "").strip()
    aspect = str(product.get("aspect_ratio") or "").strip()
    rim = str(product.get("rim_size") or "").strip()
    if section and aspect and rim:
        rim = rim.upper() if rim.upper().startswith("R") else f"R{rim}"
        return f"{section}/{aspect}{rim}"
    return str(product.get("size") or "").strip()


def _fulfillment_path(
    signals: Dict[str, Dict[str, Any]],
) -> Tuple[str, str]:
    service_type = _signal_value(signals, "service_type").lower()
    delivery_address = _signal_value(signals, "delivery_address")
    selected_partner = _signal_value(signals, "selected_installation_partner")
    selected_slot = _signal_value(signals, "chosen_schedule_slot")
    if "delivery" in service_type or delivery_address:
        return "delivery", "delivery"
    if any(token in service_type for token in ["install", "installation", "kabit"]):
        return "installation", "installation"
    if selected_partner or selected_slot:
        return "installation", "installation"
    return "", ""


def _customer_order_intent(
    *,
    signals: Dict[str, Dict[str, Any]],
    selected_product: bool,
) -> str:
    """Return telemetry derived only from typed state, never raw prose or AWM."""

    if _signal_value(signals, "order_summary_review_confirmation") and selected_product:
        return "active"
    if _signal_value(signals, "explicit_order_confirmation") and selected_product:
        return "active"
    if selected_product:
        return "possible"
    return "none"


def _high_intent_signals(
    *,
    signals: Dict[str, Dict[str, Any]],
    selected_product: bool,
    service_path: str,
    selected_slot: str,
) -> List[str]:
    """Describe objective progress without interpreting customer wording."""

    items: List[str] = []
    if selected_product:
        items.append("product selected")
    if service_path:
        items.append(f"{service_path} context")
    if selected_slot:
        items.append("schedule mentioned")
    if _signal_value(signals, "contact_number"):
        items.append("contact provided")
    if (
        selected_product
        and (
            _signal_value(signals, "order_summary_review_confirmation")
            or _signal_value(signals, "explicit_order_confirmation")
        )
    ):
        items.append("structured order confirmation")
    return _unique(items)


def _is_not_started_order_state(
    *,
    signals: Dict[str, Dict[str, Any]],
    intent: str,
    selected_product: bool,
    high_intent_signals: Sequence[str],
) -> bool:
    if selected_product or intent in {"active", "high"} or high_intent_signals:
        return False
    order_context_keys = {
        "quantity",
        "chosen_schedule_slot",
        "delivery_address",
        "selected_installation_partner",
        "reservation_payment_method",
        "balance_payment_method",
        "order_summary_review_confirmation",
        "explicit_order_confirmation",
    }
    if any(_signal_value(signals, key) for key in order_context_keys):
        return False
    return True


def _readiness_status(
    *,
    selected_product: bool,
    missing: Sequence[str],
    intent: str,
    has_any_order_context: bool,
) -> str:
    if selected_product and _only_order_detail_missing(missing):
        return "ready_for_summary"
    if selected_product or intent in {"active", "high"} or has_any_order_context:
        return "incomplete"
    return "not_started"


def _only_order_detail_missing(missing: Sequence[str]) -> bool:
    """Return true when missing fields can be shown in an incomplete summary."""

    summary_allowed_missing = {
        "contact number",
        "first name",
        "last name",
        "email address",
        "payment option (pay now or pay later)",
        "reservation payment method",
        "balance payment method",
        "invoice preference",
        "complete delivery address",
        "installation partner",
        "installment bank",
        "installment term",
    }
    for item in missing:
        text = str(item or "").strip().lower()
        if text and text not in summary_allowed_missing:
            return False
    return True


def _money_text(value: float) -> str:
    return f"PHP {float(value):,.2f}"


def _coerce_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace(",", ""))
    except Exception:
        return None


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(float(str(value).replace(",", "")))
    except Exception:
        number = default
    return max(minimum, min(number, maximum))


def _unique(items: Sequence[str]) -> List[str]:
    output: List[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        key = text.lower()
        if text and key not in seen:
            output.append(text)
            seen.add(key)
    return output
