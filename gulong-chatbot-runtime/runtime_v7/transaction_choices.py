"""Renderer-ready schedule and checkout choice projections for Runtime V7.

These helpers do not fetch data or mutate order state. They turn trusted slot,
quote, and checkout metadata into bounded choices that the shared interaction
ledger can validate after delivery.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from runtime_v7.order_canonicalization import (
    normalize_payment_option,
    payment_method_stage,
    resolve_payment_option,
    resolve_transaction_for_service_path,
    truthy,
)


def signal_authority(signal: Mapping[str, Any]) -> Tuple[str, str]:
    """Resolve original source/status retained by the signal ledger."""

    source = str(signal.get("source") or "").strip()
    status = str(signal.get("status") or "").strip()
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
    if source == "signal_ledger":
        source = str(ledger.get("authority_source") or source).strip()
        status = str(ledger.get("authority_status") or status).strip()
    return source, status


def build_schedule_choice_surface(result: Dict[str, Any]) -> Dict[str, Any]:
    """Project trusted slot groups into one card per available day."""

    if not isinstance(result, dict):
        return {}
    presentation_ref = str(result.get("presentation_ref") or "").strip()
    observation_ref = str(result.get("observation_ref") or "").strip()
    if not presentation_ref:
        return {}

    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for group in result.get("slot_groups") or []:
        if not isinstance(group, dict):
            continue
        partner = {
            key: deepcopy(group.get(key))
            for key in (
                "installation_partner_ref",
                "service_location_ref",
                "branch_id",
                "name",
                "address",
                "area",
                "city",
                "province",
                "municipality_city",
            )
            if group.get(key) not in (None, "")
        }
        group_slots = list(group.get("slots") or [])
        fallback_slot = group.get("fallback_next_open_slot")
        if isinstance(fallback_slot, dict) and fallback_slot:
            group_slots.append(fallback_slot)
        for slot in group_slots:
            if not isinstance(slot, dict):
                continue
            date = str(slot.get("date") or "").strip()
            slot_ref = str(slot.get("slot_ref") or "").strip()
            time_text = str(slot.get("time_text") or slot.get("time") or "").strip()
            if not date or not slot_ref or not time_text:
                continue
            by_date.setdefault(date, []).append(
                {
                    "slot_ref": slot_ref,
                    "date": date,
                    "time_text": time_text,
                    "start": slot.get("start"),
                    "partner": partner,
                }
            )

    days: List[Dict[str, Any]] = []
    all_choices: List[Dict[str, Any]] = []
    for day_position, date in enumerate(sorted(by_date)[:10], start=1):
        candidates = _dedupe_slots(by_date[date])
        classified = [(item, _slot_hour(item)) for item in candidates]
        morning = [item for item, hour in classified if hour is not None and hour < 12]
        afternoon = [item for item, hour in classified if hour is not None and hour >= 12]
        exact = _distributed_slots(morning, limit=2)
        choices: List[Dict[str, Any]] = []
        for choice_position, item in enumerate(exact, start=1):
            choice = {
                "choice_ref": f"d{day_position}t{choice_position}",
                "choice_type": "schedule_selection",
                "selection_kind": "exact_slot",
                "label": item["time_text"],
                "date": date,
                "time_text": item["time_text"],
                "slot_ref": item["slot_ref"],
                "installation_partner_ref": item["partner"].get(
                    "installation_partner_ref"
                ),
                "service_location_ref": item["partner"].get(
                    "service_location_ref"
                ),
                "position": choice_position,
            }
            choices.append(choice)
            all_choices.append(deepcopy(choice))

        earliest_afternoon = afternoon[0] if afternoon else {}
        afternoon_choice = {
            "choice_ref": f"d{day_position}aft",
            "choice_type": "schedule_selection",
            "selection_kind": "afternoon_preference",
            "label": "Anytime in the afternoon",
            "date": date,
            "time_window": "afternoon",
            "time_text": (
                str(earliest_afternoon.get("time_text") or "").strip()
                or "12:00 PM"
            ),
            "slot_ref": str(
                earliest_afternoon.get("slot_ref") or ""
            ).strip(),
            "installation_partner_ref": (
                earliest_afternoon.get("partner") or {}
            ).get("installation_partner_ref"),
            "service_location_ref": (
                earliest_afternoon.get("partner") or {}
            ).get("service_location_ref"),
            "slot_refs": [item["slot_ref"] for item in afternoon],
            "availability_status": (
                "current_afternoon_slots_present"
                if afternoon
                else "preference_only_no_current_afternoon_slot"
            ),
            "position": len(choices) + 1,
        }
        choices.append(afternoon_choice)
        all_choices.append(deepcopy(afternoon_choice))
        days.append(
            {
                "date": date,
                "title": _day_title(date),
                "subtitle": _day_subtitle(result),
                "choices": choices,
            }
        )

    if not days:
        return {}
    return {
        "presentation_ref": presentation_ref,
        "observation_ref": observation_ref,
        "surface_type": "schedule_choices",
        "choice_type": "schedule_selection",
        "days": days,
        "choices": all_choices,
        "service_policy_notes": [
            deepcopy(note)
            for note in result.get("service_policy_notes") or []
            if isinstance(note, dict)
        ],
        "source": "validated_installation_slot_observation",
        "renderer_variant": "manychat_schedule_day_cards_v1",
    }


def build_payment_option_surface(
    *,
    quote: Dict[str, Any],
    metadata: Dict[str, Any],
    turn_id: str,
) -> Dict[str, Any]:
    """Build Pay Now versus Pay Later choices from quote and metadata."""

    preview = (
        (quote.get("quote_breakdown") or {}).get("payment_options_preview")
        if isinstance(quote.get("quote_breakdown"), dict)
        else {}
    )
    if not isinstance(preview, dict) or not preview:
        return {}
    choices: List[Dict[str, Any]] = []
    for row in metadata.get("payment_options") or []:
        if not isinstance(row, dict):
            continue
        normalized = normalize_payment_option(row.get("name") or row.get("label"))
        if normalized == "Pay Now":
            facts = preview.get("pay_now") or {}
            subtitle = " | ".join(
                part
                for part in [
                    "Pay in full now",
                    (
                        f"Save {facts.get('discount_text')}"
                        if facts.get("discount_text")
                        else ""
                    ),
                    (
                        f"Due now {facts.get('amount_due_now_text')}"
                        if facts.get("amount_due_now_text")
                        else ""
                    ),
                ]
                if part
            )
            label = "Pay Now"
        elif normalized == "Pay Later / Pay After Service":
            facts = preview.get("pay_later") or {}
            subtitle = " | ".join(
                part
                for part in [
                    (
                        f"Reservation {facts.get('reservation_fee_text')}"
                        if facts.get("reservation_fee_text")
                        else "Reservation required"
                    ),
                    (
                        f"Balance {facts.get('balance_due_text')}"
                        if facts.get("balance_due_text")
                        else ""
                    ),
                ]
                if part
            )
            label = "Pay Later"
        else:
            continue
        option_id = str(row.get("id") or "").strip()
        if not option_id:
            continue
        choices.append(
            {
                "choice_ref": f"option_{option_id}",
                "choice_type": "payment_option_selection",
                "option_id": option_id,
                "label": label,
                "value": normalized,
                "subtitle": subtitle,
                "position": len(choices) + 1,
            }
        )
    if not choices:
        return {}
    presentation_ref = _presentation_ref(
        "payment_options",
        turn_id,
        quote.get("quote_ref"),
        choices,
    )
    return {
        "presentation_ref": presentation_ref,
        "surface_type": "payment_option_choices",
        "choice_type": "payment_option_selection",
        "choices": choices,
        "source": str(metadata.get("source") or "gulong_api_checkout_metadata"),
        "quote_ref": str(quote.get("quote_ref") or ""),
        "renderer_variant": "manychat_payment_option_cards_v1",
    }


def build_payment_method_surface(
    *,
    metadata: Dict[str, Any],
    payment_option: str,
    product_brand: str,
    service_path: str,
    turn_id: str,
    payment_stage: str = "",
) -> Dict[str, Any]:
    """Build only payment methods compatible with current checkout evidence."""

    option = resolve_payment_option(payment_option, metadata)
    option_id = str(option.get("id") or "").strip()
    if not option_id:
        return {}
    transaction = resolve_transaction_for_service_path(service_path, metadata)
    transaction_id = str(transaction.get("id") or "").strip()
    brand = str(product_brand or "").strip().upper()
    stage_filter = str(payment_stage or "").strip()
    choices: List[Dict[str, Any]] = []
    for row in metadata.get("payment_types") or []:
        if not isinstance(row, dict) or truthy(row.get("is_disabled")):
            continue
        if str(row.get("main_payment_type_id") or "").strip() != option_id:
            continue
        excluded = str(row.get("exclude_transaction_type_id") or "").strip()
        if excluded and transaction_id and excluded == transaction_id:
            continue
        allowed_brands = {
            value.strip().upper()
            for value in str(row.get("available_brands") or "").split(",")
            if value.strip()
        }
        if allowed_brands and (not brand or brand not in allowed_brands):
            continue
        row_id = str(row.get("id") or "").strip()
        # The API's generic label can collapse specific choices such as
        # "BPI 6-mos Installment" into only "Installment".
        label = str(row.get("name") or row.get("label") or "").strip()
        if not row_id or not label:
            continue
        row_payment_stage = payment_method_stage(
            payment_option=payment_option,
            is_installment=truthy(row.get("is_installment")),
        )
        if stage_filter and stage_filter != row_payment_stage:
            continue
        choices.append(
            {
                "choice_ref": f"method_{row_id}",
                "choice_type": "payment_method_selection",
                "payment_type_id": row_id,
                "payment_option_id": option_id,
                "label": label,
                "value": str(row.get("value") or row.get("name") or label),
                "description": _payment_method_choice_description(
                    payment_option=payment_option,
                    payment_stage=row_payment_stage,
                ),
                "payment_stage": row_payment_stage,
                "is_installment": truthy(row.get("is_installment")),
                "installment_months": _installment_months(row),
                "available_brands": str(row.get("available_brands") or ""),
                "exclude_transaction_type_id": excluded,
                "position": len(choices) + 1,
            }
        )
    if not choices:
        return {}
    presentation_ref = _presentation_ref(
        "payment_methods",
        turn_id,
        option_id,
        service_path,
        brand,
        choices,
    )
    return {
        "presentation_ref": presentation_ref,
        "surface_type": "payment_method_choices",
        "choice_type": "payment_method_selection",
        "payment_option": payment_option,
        "payment_option_id": option_id,
        "service_path": service_path,
        "product_brand": brand,
        "choices": choices[:20],
        "source": str(metadata.get("source") or "gulong_api_checkout_metadata"),
        "renderer_variant": "manychat_payment_method_cards_v1",
    }


def _installment_months(row: Dict[str, Any]) -> str:
    """Return a structured term from an API payment row when it declares one."""

    for key in (
        "installment_months",
        "term_months",
        "months",
        "installment_term",
    ):
        value = str(row.get(key) or "").strip()
        match = re.search(r"\b(\d{1,3})\b", value)
        if match:
            return match.group(1)
    text = " ".join(
        str(row.get(key) or "")
        for key in ("name", "label", "value")
    )
    match = re.search(
        r"\b(\d{1,3})\s*(?:-|–)?\s*(?:mos?|months?)\b",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else ""


def _payment_method_choice_description(
    *,
    payment_option: str,
    payment_stage: str = "",
) -> str:
    """Explain the selected checkout layer without repeating stale API copy."""

    if normalize_payment_option(payment_option) == "Pay Now":
        return "Use for Pay Now. The order total already includes the available discount."
    if payment_stage == "balance_payment":
        return "Use for the balance after service. A reservation fee is still required."
    return "Use to pay the reservation fee for Pay Later."


def _dedupe_slots(slots: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in sorted(
        slots,
        key=lambda value: (
            str(value.get("start") or ""),
            str(value.get("time_text") or ""),
            str(value.get("slot_ref") or ""),
        ),
    ):
        key = (str(item.get("date") or ""), _time_key(item.get("time_text")))
        if key in seen:
            continue
        seen.add(key)
        output.append(deepcopy(item))
    return output


def _distributed_slots(
    slots: Sequence[Dict[str, Any]],
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    ordered = list(slots)
    if len(ordered) <= limit:
        return [deepcopy(item) for item in ordered]
    if limit <= 1:
        return [deepcopy(ordered[0])]
    indexes = [
        round(index * (len(ordered) - 1) / (limit - 1))
        for index in range(limit)
    ]
    return [deepcopy(ordered[index]) for index in dict.fromkeys(indexes)]


def _slot_hour(item: Dict[str, Any]) -> int | None:
    text = str(item.get("time_text") or item.get("start") or "").strip()
    for pattern in ("%I:%M %p", "%I %p", "%H:%M"):
        try:
            return datetime.strptime(text.upper(), pattern).hour
        except ValueError:
            continue
    start = str(item.get("start") or "")
    try:
        return datetime.fromisoformat(start.replace("Z", "+00:00")).hour
    except ValueError:
        return None


def _time_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    for pattern in ("%I:%M %p", "%I %p", "%H:%M"):
        try:
            return datetime.strptime(text, pattern).strftime("%H:%M")
        except ValueError:
            continue
    return text


def _day_title(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
        return f"{parsed.strftime('%a, %b')} {parsed.day}"
    except ValueError:
        return value


def _day_subtitle(result: Dict[str, Any]) -> str:
    disclosure = (
        result.get("detail_disclosure")
        if isinstance(result.get("detail_disclosure"), dict)
        else {}
    )
    label = str(
        disclosure.get("customer_location_label")
        or (result.get("query_basis") or {}).get("customer_location_label")
        or ""
    ).strip()
    return f"{label} area" if label else "Current installation schedule"


def _presentation_ref(prefix: str, *parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=True, sort_keys=True, default=str)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"pres_{prefix}_{digest}"
