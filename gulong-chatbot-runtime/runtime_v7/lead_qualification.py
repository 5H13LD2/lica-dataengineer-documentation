"""Runtime V7 lead-qualification snapshot.

The lead stage is intentionally small: incomplete or complete. Complete means
the conversation satisfies the current Moderate Intent rule:
tire size plus at least two of tire brand, location, and contact number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from runtime_v7.location_quality import usable_lead_location
from runtime_v7.state_signal_schema import TRANSIENT_SIGNAL_RELATIONS


LEAD_FIELDS = ("tire_size", "tire_brand", "location", "contact_number")
MODERATE_SUPPORT_FIELDS = ("tire_brand", "location", "contact_number")
BRAND_SIGNAL_KEYS = ("tire_brand", "required_brands", "preferred_brands")
INTENT_RULE_VERSION = "gulong_intent_v2_20260811"


@dataclass(frozen=True)
class LeadQualificationSnapshot:
    """Computed lead qualification state for routing and tagging."""

    lead_stage: str
    moderate_intent: bool
    present: Dict[str, str] = field(default_factory=dict)
    missing: List[str] = field(default_factory=list)
    optional_missing: List[str] = field(default_factory=list)
    rule: str = "tire_size + at least 2 of tire_brand/location/contact_number"
    support_count: int = 0
    priority: List[str] = field(default_factory=lambda: list(LEAD_FIELDS))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize qualification state and its deterministic lineage metadata."""

        return {
            "lead_stage": self.lead_stage,
            "status": self.lead_stage,
            "moderate_intent": bool(self.moderate_intent),
            "present": dict(self.present),
            "missing": list(self.missing),
            "optional_missing": list(self.optional_missing),
            "priority": list(self.priority),
            "rule": self.rule,
            "support_count": int(self.support_count),
            "decision_mode": "deterministic",
            "rule_version": INTENT_RULE_VERSION,
        }


def build_lead_qualification_snapshot(
    signals: Sequence[Any],
    *,
    profile_fields: Optional[Mapping[str, Any]] = None,
) -> LeadQualificationSnapshot:
    """Return the current incomplete/complete lead stage from normalized facts."""

    values = _values_by_key(signals)
    if profile_fields:
        _merge_profile_fields(values, profile_fields)

    present: Dict[str, str] = {}
    if values.get("tire_size"):
        present["tire_size"] = values["tire_size"]
    brand_value = _first_present_value(values, BRAND_SIGNAL_KEYS)
    if brand_value:
        present["tire_brand"] = brand_value
    location = usable_lead_location(values.get("location"))
    if location:
        present["location"] = location
    if _usable_contact_number(values.get("contact_number")):
        present["contact_number"] = values["contact_number"]

    support_count = sum(1 for field_name in MODERATE_SUPPORT_FIELDS if present.get(field_name))
    moderate_intent = bool(present.get("tire_size") and support_count >= 2)
    if moderate_intent:
        missing: List[str] = []
        optional_missing = [field_name for field_name in LEAD_FIELDS if not present.get(field_name)]
    else:
        missing = _missing_fields_needed_for_moderate(present)
        optional_missing = []

    return LeadQualificationSnapshot(
        lead_stage="complete" if moderate_intent else "incomplete",
        moderate_intent=moderate_intent,
        present=present,
        missing=missing,
        optional_missing=optional_missing,
        support_count=support_count,
    )


def _values_by_key(signals: Sequence[Any]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for signal in signals or []:
        if isinstance(signal, Mapping):
            key = str(signal.get("key") or "").strip()
            value = signal.get("value")
            relation = str(signal.get("relation") or "asserted").strip().lower()
        else:
            key = str(getattr(signal, "key", "") or "").strip()
            value = getattr(signal, "value", None)
            relation = str(
                getattr(signal, "relation", "asserted") or "asserted"
            ).strip().lower()
        if relation in {*TRANSIENT_SIGNAL_RELATIONS, "rejected"}:
            continue
        if not key or value in (None, "", [], {}):
            continue
        if key == "location" and not usable_lead_location(value):
            continue
        values.setdefault(key, str(value).strip())
    return values


def _merge_profile_fields(values: Dict[str, str], profile_fields: Mapping[str, Any]) -> None:
    aliases = {
        "phone": "contact_number",
        "mobile": "contact_number",
        "mobile_number": "contact_number",
        "contact": "contact_number",
        "brand": "tire_brand",
        "tire_brand": "tire_brand",
        "tire_size": "tire_size",
        "location": "location",
    }
    for raw_key, raw_value in profile_fields.items():
        key = aliases.get(str(raw_key or "").strip())
        if not key or key in values or raw_value in (None, "", [], {}):
            continue
        candidate = str(raw_value).strip()
        if key == "location":
            candidate = usable_lead_location(candidate)
        if candidate:
            values[key] = candidate


def _first_present_value(values: Mapping[str, str], keys: Sequence[str]) -> str:
    for key in keys:
        value = str(values.get(key) or "").strip()
        if value:
            return value
    return ""


def _usable_contact_number(value: Any) -> bool:
    """Accept only plausible Philippine mobile contacts as Moderate support."""

    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("63") and len(digits) == 12:
        digits = "0" + digits[2:]
    elif digits.startswith("9") and len(digits) == 10:
        digits = "0" + digits
    return len(digits) == 11 and digits.startswith("09")


def _missing_fields_needed_for_moderate(present: Mapping[str, str]) -> List[str]:
    missing: List[str] = []
    if not present.get("tire_size"):
        missing.append("tire_size")
    support_present = [field_name for field_name in MODERATE_SUPPORT_FIELDS if present.get(field_name)]
    support_needed = max(0, 2 - len(support_present))
    if support_needed:
        for field_name in MODERATE_SUPPORT_FIELDS:
            if field_name not in support_present:
                missing.append(field_name)
            if len([field for field in missing if field in MODERATE_SUPPORT_FIELDS]) >= support_needed:
                break
    return missing


__all__ = [
    "BRAND_SIGNAL_KEYS",
    "INTENT_RULE_VERSION",
    "LEAD_FIELDS",
    "MODERATE_SUPPORT_FIELDS",
    "LeadQualificationSnapshot",
    "build_lead_qualification_snapshot",
]
