"""Exact starter-control context for Runtime V7 composition.

Free-text meaning belongs to the model. This module only recognizes the exact
labels emitted by known guided starter controls; it does not classify customer
phrasing or prescribe a lead-stage CTA.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence


_BUTTON_INTENT_DATA: Dict[str, Dict[str, str]] = {
    "can you help me find the right tire for my car?": {
        "type": "automated_tire_help_button",
        "intent": "Customer wants help identifying suitable tires for their vehicle.",
        "guidance": (
            "Acknowledge the request for tire help, then ask for exactly one useful discovery input: the "
            "sidewall tire size when available, otherwise the vehicle make/model. A reviewed promo gallery "
            "may accompany that discovery step when it is genuinely useful, but it must not replace the "
            "size/vehicle question or become the main answer. Do not use an open-ended 'How can I help?' response."
        ),
    },
    "is anyone available to chat?": {
        "type": "automated_availability_button",
        "intent": "Customer asks whether assistance is available in this chat; this is not by itself a human takeover request.",
        "guidance": (
            "Answer yes briefly without claiming a human handoff. Because this approved starter provides no "
            "usable shopping criteria, apply the model-led low-information entry preference: normally show the "
            "reviewed promo catalog now with a short contextual lead-in and one connected discovery question. "
            "Skip the gallery only when it is unavailable, recently shown, or unhelpful in retained context."
        ),
    },
    "do you have ongoing promotion?": {
        "type": "automated_promo_button",
        "intent": "Customer asks about current promotions; use the reviewed promo catalog before stating facts.",
    },
    "how to avail?": {
        "type": "automated_how_to_avail_button",
        "intent": "Customer asks how to proceed with buying, reservation, installation, or delivery.",
        "guidance": (
            "Answer the short purchase process first from the reviewed order/service policy: identify the tire, "
            "confirm delivery or installation, then collect the order details and any required reservation step. "
            "Do not reinterpret this process question as promo discovery. If a reviewed promo is also useful, "
            "offer or render it only after the process answer and keep the single next question on the first "
            "missing purchase input, usually tire size or vehicle."
        ),
    },
    "do you offer same day installation?": {
        "type": "automated_same_day_installation_button",
        "intent": "Customer asks about same-day installation; ground policy and availability before answering.",
    },
    "get started": {
        "type": "automated_get_started_button",
        "intent": "Customer wants to begin a tire-shopping inquiry.",
        "guidance": (
            "Treat this bare approved entry control as starting a shopping conversation, "
            "not an order-process or 'How to order' request. Compose a compact natural "
            "Gulong.ph welcome in your own words. Continue already-known customer details; "
            "otherwise ask one connected discovery question for tire size or vehicle. A reviewed "
            "promo gallery may accompany that discovery step when useful, but it is optional "
            "support rather than the primary answer or a mandatory surface. Do not ask permission to run a safe "
            "read-only check or show an available surface. You choose the wording, CTA, and "
            "any supported surface; this is not a deterministic insertion or fixed script."
        ),
    },
    "what is gulong guarantee": {
        "type": "automated_gulong_guarantee_button",
        "intent": "Customer asks what the Gulong Guarantee is; use current reviewed warranty or promo evidence.",
    },
}


def build_response_seeds(
    *,
    current_user_message: str,
    max_seeds: int = 2,
) -> List[Dict[str, Any]]:
    """Return context only for exact guided starter labels.

    Free-text interpretation belongs to the model-led composer. This helper
    recognizes only exact, tracked guided-starter labels.
    """
    seeds: List[Dict[str, Any]] = []

    exact_button = build_exact_button_context(current_user_message)
    if exact_button:
        seeds.append(
            _seed(
                seed_type=str(exact_button["type"]),
                guidance=(
                    str(exact_button.get("guidance") or "").strip()
                    or (
                        "Recognized starter intent. Treat it only as the customer's current goal; "
                        "write the answer in your own words and use grounded tools for any business "
                        f"facts. Intent: {exact_button['intent']}"
                    )
                ),
                priority="high",
            )
        )

    return seeds[: max(1, int(max_seeds or 2))]


def build_exact_button_context(current_user_message: str) -> Optional[Dict[str, str]]:
    """Return advisory context only for an approved platform control label."""

    button = _BUTTON_INTENT_DATA.get(_normalize_control_label(current_user_message))
    if not button:
        return None
    context = {
        "type": button["type"],
        "intent": button["intent"],
    }
    if button.get("guidance"):
        context["guidance"] = button["guidance"]
    return context


def _seed(
    *,
    seed_type: str,
    guidance: str,
    priority: str,
    missing_fields: Optional[Sequence[str]] = None,
    present_fields: Optional[Sequence[str]] = None,
    response_units: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "type": seed_type,
        "priority": priority,
        "guidance": guidance,
    }
    if missing_fields:
        row["missing_fields"] = list(missing_fields)
    if present_fields:
        row["present_fields"] = list(present_fields)
    if response_units:
        row["response_units"] = [dict(unit) for unit in response_units if isinstance(unit, dict)]
    return row


_CONTROL_LABEL_CHECKMARKS = ("✅", "✔", "☑")
_CONTROL_LABEL_VARIATION_SELECTORS = "\ufe0e\ufe0f"
_CONTROL_LABEL_PREFIX_RE = re.compile(
    rf"^(?:{'|'.join(re.escape(mark) for mark in _CONTROL_LABEL_CHECKMARKS)})"
    rf"[{_CONTROL_LABEL_VARIATION_SELECTORS}]?\s*"
)


def _normalize_control_label(text: str) -> str:
    """Normalize approved starter-control chrome without interpreting free text.

    ManyChat may prepend one of its known checkmark decorations (with an emoji
    or text variation selector) to an otherwise exact control label. Strip only
    that leading platform chrome, then require the remaining whole label to
    match the approved-control registry. Customer prose stays untouched apart
    from case and whitespace normalization, so it remains model-owned.
    """

    collapsed = re.sub(r"\s+", " ", str(text or "").strip().casefold())
    return _CONTROL_LABEL_PREFIX_RE.sub("", collapsed, count=1)


__all__ = [
    "build_exact_button_context",
    "build_response_seeds",
]
