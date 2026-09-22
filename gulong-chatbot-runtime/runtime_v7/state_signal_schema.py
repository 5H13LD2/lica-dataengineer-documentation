"""Schema and constants for Runtime V7 advisory commercial signals.

This module contains data shapes only. It deliberately avoids model calls,
regex extraction, and canonical-value lookups so other signal modules can share
one stable contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


TRANSIENT_SIGNAL_RELATIONS = {
    "conditional",
    "question_only",
    "historical",
}

DURABLE_SIGNAL_RELATIONS = {
    "asserted",
    "selected",
    "corrected",
}

# Narrative sources are useful to the model as context, but never establish a
# customer or commercial fact on their own.
NON_AUTHORITATIVE_NARRATIVE_SOURCES = {
    "active_working_memory",
    "assistant_message",
    "assistant_transcript",
    "conversation_context",
    "recent_turns",
}

# Evidence extracted from an image, screenshot, or other external artifact is
# deliberately *lookup-only*.  It can help the model choose a question or a
# read-only validation tool in this turn, but it must not become remembered
# customer state or unlock an order action.  In particular, OCR text and a
# screenshot's commercial claims are not order authority.
LOOKUP_ONLY_SIGNAL_SOURCES = {
    "external_evidence",
}

# These are closed runtime provenance values, rather than model-provided
# status prose.  `validated_choice_action` is written only by the delivered
# guided-choice allowlist path before it reaches the signal ledger.
DURABLE_SIGNAL_AUTHORITY_SOURCES = {
    "latest_user_message",
    "customer_history",
    "validated_choice_action",
}


def signal_authority_source(signal: Dict[str, Any]) -> str:
    """Return the original provenance behind a signal or ledger carry-forward."""

    source = str(signal.get("source") or "").strip().casefold()
    if source != "signal_ledger":
        return source
    metadata = signal.get("metadata") if isinstance(signal.get("metadata"), dict) else {}
    ledger = metadata.get("ledger") if isinstance(metadata.get("ledger"), dict) else {}
    # A carry-forward record without its original provenance is legacy
    # narrative context, not authority.  New ledger rows always retain this
    # field; failing closed avoids reviving an untraceable historic value.
    return str(ledger.get("authority_source") or "").strip().casefold()


def signal_is_lookup_only_evidence(signal: Dict[str, Any]) -> bool:
    """Return whether a signal may inform lookup but never durable state."""

    return signal_authority_source(signal) in LOOKUP_ONLY_SIGNAL_SOURCES


def signal_is_advisory_context(signal: Dict[str, Any]) -> bool:
    """Return whether a signal may remain in this turn's model context.

    This is intentionally broader than durable authority: external evidence is
    valuable context for a model-led reply or a validation lookup even though
    it is not permitted to persist or influence readiness.
    """

    source = signal_authority_source(signal)
    return bool(source) and source not in NON_AUTHORITATIVE_NARRATIVE_SOURCES


def signal_has_durable_authority(signal: Dict[str, Any]) -> bool:
    """Return whether typed state may persist or influence readiness/actions."""

    source = signal_authority_source(signal)
    return source in DURABLE_SIGNAL_AUTHORITY_SOURCES

LEAD_QUALIFICATION_FIELDS = [
    "tire_size",
    "tire_brand",
    "location",
    "contact_number",
]

ORDER_READINESS_FIELDS = [
    "quantity",
    "chosen_schedule_slot",
    "delivery_address",
    "selected_installation_partner",
    "reservation_payment_method",
    "balance_payment_method",
    "payment_option",
    "bank",
    "installment_months",
    "first_name",
    "last_name",
    "email_address",
]

ORDER_READINESS_OPTIONAL_FIELDS = [
    "branch_addons",
    "invoice_to_company",
]

KNOWN_BRANDS = [
    "YOKOHAMA",
    "MICHELIN",
    "BFGOODRICH",
    "VREDESTEIN",
    "BRIDGESTONE",
    "GOODYEAR",
    "PIRELLI",
    "CONTINENTAL",
    "DUNLOP",
    "HANKOOK",
    "KUMHO",
    "MAXXIS",
    "APOLLO",
    "ARIVO",
    "SAILUN",
    "DURATURN",
    "ATLAS",
    "WESTLAKE",
]

KNOWN_LOCATIONS = [
    "Cubao",
    "Carmona",
    "Bulacan",
    "Makati",
    "Alabang",
    "Cavite",
    "Laguna",
    "Quezon City",
    "Manila",
    "Pasig",
    "Taguig",
]

SIGNAL_ORDER = [
    "tire_size",
    "rim_size",
    "preferred_brands",
    "required_brands",
    "brand_match_mode",
    "excluded_brands",
    "car_make_model",
    "location",
    "acceptable_service_locations",
    "location_response_status",
    "contact_number",
    "quantity",
    "promo_types",
    "promo_discovery_scope",
    "promo_alternative_scope",
    "budget",
    "tire_category_preference",
    "excluded_tire_categories",
    "origins",
    "excluded_origins",
    "latest_product_presentation",
    "external_product_evidence",
    "website_inquiry_evidence",
    "latest_service_presentation",
    "order_id",
    "specific_sku_model",
    "terrain_types",
    "service_type",
    "chosen_schedule_slot",
    "delivery_address",
    "selected_installation_partner",
    "branch_addons",
    "reservation_payment_method",
    "balance_payment_method",
    "payment_option",
    "payment_method",
    "bank",
    "installment_months",
    "payment_proof_evidence",
    "first_name",
    "last_name",
    "email_address",
    "invoice_to_company",
    "order_summary_review_confirmation",
    "explicit_order_confirmation",
]

MULTI_VALUE_KEYS = {
    "tire_size",
    "preferred_brands",
    "required_brands",
    "excluded_brands",
    "branch_addons",
    "excluded_tire_categories",
    "origins",
    "excluded_origins",
    "promo_types",
    "terrain_types",
}


@dataclass(frozen=True)
class BackgroundSignal:
    """Prompt-facing signal with provenance and validation metadata."""

    key: str
    label: str
    value: Optional[str]
    status: str
    confidence: str
    source: str
    relevance: str
    ask_timing: str
    relation: str = "asserted"
    safe_for_action: bool = False
    resolution: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return the JSON-serializable context-packet representation."""

        payload = {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "status": self.status,
            "confidence": self.confidence,
            "source": self.source,
            "relevance": self.relevance,
            "ask_timing": self.ask_timing,
            "relation": self.relation,
            "safe_for_action": self.safe_for_action,
            "requires_validation": not bool(self.safe_for_action),
        }
        if self.resolution:
            payload["resolution"] = self.resolution
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


