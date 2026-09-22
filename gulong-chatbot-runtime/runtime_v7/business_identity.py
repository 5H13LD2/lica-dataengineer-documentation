"""Reviewed, low-volatility Gulong.ph operating identity for model context.

These facts describe how the business operates. The partner-network statement
is an approved lower-bound brand claim, not an exact current count. Current
coverage, stock, schedules, prices, promos, and order state remain owned by
their runtime providers and tools.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict


BUSINESS_IDENTITY_POLICY_VERSION = "2026-08-06"
BUSINESS_IDENTITY_EVIDENCE_REF = (
    f"business_identity:{BUSINESS_IDENTITY_POLICY_VERSION}"
)
GULONG_HEAD_OFFICE_ADDRESS = (
    "1166 Chino Roces Avenue corner Estrella, Makati City"
)

GULONG_BUSINESS_IDENTITY_FACTS = (
    "Gulong.ph is an online-first tire shop.",
    "Gulong.ph works with a network of over 100 trusted installation partners.",
    (
        f"Gulong.ph's head office is at {GULONG_HEAD_OFFICE_ADDRESS}, and it is "
        "also an installation site."
    ),
    (
        "For ordinary tire purchases and installation, tires come from the warehouse "
        "and are sent to the booked installation site after reservation or appointment."
    ),
)

GULONG_BUSINESS_IDENTITY_PROMPT = """Reviewed Gulong.ph operating identity:
- Gulong.ph is an online-first tire shop.
- Gulong.ph works with a network of over 100 trusted installation partners.
- Its head office is at 1166 Chino Roces Avenue corner Estrella, Makati City,
  and the head office is also an installation site.
- For ordinary tire purchases and installation, tires come from the warehouse
  and are sent to the booked installation site after reservation or appointment.

Use these facts as natural brand and operating context only when relevant. Do
not recite them as a fixed spiel or force them into unrelated turns. On a first
turn, normally use a natural variation of "Welcome to Gulong.ph" as part of the
personalized direct answer unless the situation calls for apology, urgency, or
de-escalation; later in a conversation, continue without reintroducing the
brand. For an explicit question about Gulong.PH's own/head-office address,
answer the location/process question naturally and only use the facts that help
that specific customer. A bare or ambiguous store/branch-location request that
could mean a convenient customer option is not enough to assume the head office;
ask for the customer's city/area first without volunteering the Makati address.
If the customer asks about a physical shop or walk-in,
explain the applicable reservation or appointment process without reciting
every operating fact. The head-office installation capability is permission to
answer accurately when it directly matters; it is not a required talking point
or a promotional claim. Never describe the head office as unavailable for
installation.

Do not increase or make the approved more-than-100 partner claim more specific.
Exact current totals, coverage areas, partner names and addresses,
serviceability, slots, stock, prices, promos, payment terms, and order state are
not part of this identity. State those only from the applicable current runtime
tool or trusted state. Say "over 100 trusted installation partners" in English
or "mahigit 100 trusted installation partners" in Filipino/Taglish. Do not use
a plus-sign count, add "nationwide," or name regions without current coverage
authority. If a nearby installation option is the natural next step, use an
already known city/area or ask for that one location detail; do not pivot to
tire size in the same CTA unless the customer is asking for product/fitment
help. Let the service tools establish the actual available path.

All identity facts are optional context, not a required checklist. When the
partner-network count helps, connect it naturally to the online operating model,
the convenience of arranged installation, or the reason for asking the
customer's area. Do not drop it into the reply as a detached credential or
recite all operating facts just because one is relevant. If the customer is
explicitly asking for Gulong.PH's own address, answer that business question
first. For a bare store/branch-location request with no customer area, ask one
city/area question instead of supplying the head-office address or assuming an
installation-area choice. A purely corporate-address question can end after
the answer, but an open tire-shopping or installation inquiry should normally
move one easy step forward."""


def authorized_business_identity_context() -> Dict[str, Any]:
    """Return compact model-visible authority for business-presence answers."""

    return {
        "policy_version": BUSINESS_IDENTITY_POLICY_VERSION,
        "evidence_ref": BUSINESS_IDENTITY_EVIDENCE_REF,
        "authorized_business_facts": list(GULONG_BUSINESS_IDENTITY_FACTS),
        "head_office_address_authorized": True,
        "head_office_installation_site_authorized": True,
        "can_confirm_serviceability": False,
        "prohibited_inferences": [
            "an exact current partner total beyond the approved more-than-100 brand claim or geographic coverage",
            "walk-in retail or pickup without the applicable reservation process",
            "partner availability, schedule, stock, booking, or reservation",
        ],
    }


def classify_business_location_request(message: str) -> str:
    """Classify only the stable business-location boundary.

    This combines semantic cue groups instead of matching one customer
    sentence. Product delivery, installation, partner, schedule, and
    concrete-area routing remain owned by their existing runtime paths.
    """

    text = _normalized_location_text(message)
    tokens = set(text.split())
    if not tokens:
        return ""

    fulfillment_cues = {
        "deliver",
        "delivery",
        "install",
        "installation",
        "installer",
        "partner",
        "schedule",
        "service",
        "slot",
    }
    mixed_domain_cues = {
        "available",
        "availability",
        "bili",
        "buy",
        "credit",
        "discount",
        "installment",
        "order",
        "pay",
        "payment",
        "presyo",
        "price",
        "promo",
        "promotion",
        "purchase",
        "size",
        "stock",
        "tire",
        "tires",
        "tyre",
        "tyres",
        "warranty",
    }
    explicit_office_entity = bool(
        re.search(
            r"\b(?:head|main|corporate|registered)\s+(?:office|opisina)\b",
            text,
        )
    ) or bool(tokens & {"headquarters", "hq"})
    if tokens & (fulfillment_cues | mixed_domain_cues):
        return ""

    address_cues = {
        "address",
        "addr",
        "banda",
        "directions",
        "loc",
        "located",
        "location",
        "map",
        "nasaan",
        "saan",
        "where",
    }
    store_cues = {"branch", "outlet", "shop", "store", "tindahan"}
    office_cues = {"office", "opisina"}
    own_business_cues = {
        "gulong",
        "inyo",
        "kayo",
        "ninyo",
        "nyo",
        "your",
    }
    has_location_question = bool(tokens & address_cues)
    if (explicit_office_entity and has_location_question) or (
        bool(tokens & office_cues)
        and bool(tokens & {"address", "location", "saan", "where"})
    ):
        return "explicit_business_address"
    if bool(tokens & store_cues) and has_location_question:
        return "ambiguous_store_location"
    if has_location_question and bool(tokens & own_business_cues):
        return "explicit_business_address"
    return ""


def guard_business_location_response(
    *,
    customer_message: str,
    response_text: str,
    customer_location_known: bool = False,
    isolated_goal: bool = True,
) -> Dict[str, Any]:
    """Apply canonical last-resort behavior for business-location ambiguity."""

    classification = classify_business_location_request(customer_message)
    response = str(response_text or "").strip()
    if not isolated_goal:
        return {"classification": classification, "changed": False, "response": response}
    if classification == "explicit_business_address":
        if _contains_head_office_address(response):
            return {"classification": classification, "changed": False, "response": response}
        return {
            "classification": classification,
            "changed": True,
            "reason": "explicit_business_address_missing_canonical_fact",
            "evidence_ref": BUSINESS_IDENTITY_EVIDENCE_REF,
            "response": (
                "Ang head office po namin ay nasa "
                f"{GULONG_HEAD_OFFICE_ADDRESS}."
            ),
        }
    if classification == "ambiguous_store_location":
        has_head_office = _contains_head_office_address(response)
        if not has_head_office and (
            customer_location_known or _asks_for_customer_area(response)
        ):
            return {"classification": classification, "changed": False, "response": response}
        return {
            "classification": classification,
            "changed": True,
            "reason": "ambiguous_store_location_requires_customer_area",
            "evidence_ref": BUSINESS_IDENTITY_EVIDENCE_REF,
            "response": (
                "Aling store o branch detail po ang gusto ninyong i-check para sa area ninyo?"
                if customer_location_known
                else "Saang city o area po kayo naghahanap?"
            ),
        }
    return {"classification": classification, "changed": False, "response": response}


def _normalized_location_text(value: str) -> str:
    folded = unicodedata.normalize("NFKD", str(value or "").casefold())
    ascii_text = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text).split())


def _contains_head_office_address(value: str) -> bool:
    text = _normalized_location_text(value)
    return all(
        part in text
        for part in (
            "1166",
            "chino roces avenue",
            "corner estrella",
            "makati city",
        )
    )


def _asks_for_customer_area(value: str) -> bool:
    text = _normalized_location_text(value)
    tokens = set(text.split())
    location_detail = bool(
        tokens
        & {
            "area",
            "barangay",
            "city",
            "location",
            "lugar",
            "municipality",
            "province",
            "saan",
            "where",
        }
    )
    if not location_detail:
        return False
    return "?" in str(value or "") or bool(
        tokens
        & {
            "bigay",
            "pakibigay",
            "pakisend",
            "provide",
            "send",
            "share",
            "tell",
        }
    )
