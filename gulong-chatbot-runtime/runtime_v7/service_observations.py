"""Runtime V7 read-only service observation storage.

This module stores compact, trusted service tool outputs for follow-up turns.
It does not fetch branch catalogs, rank partners, or execute service tools.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class ServiceObservation:
    """Compact read-only service tool result saved for follow-up turns."""

    observation_ref: str
    created_at: str
    result_type: str
    presentation_ref: str = ""
    query_basis: Dict[str, Any] = field(default_factory=dict)
    service_locations: List[Dict[str, Any]] = field(default_factory=list)
    installation_partner_cards: List[Dict[str, Any]] = field(default_factory=list)
    slot_groups: List[Dict[str, Any]] = field(default_factory=list)
    addon_groups: List[Dict[str, Any]] = field(default_factory=list)
    availability: Dict[str, Any] = field(default_factory=dict)

    def to_public_header(self) -> Dict[str, Any]:
        """Return a compact prompt-facing service observation header."""

        return {
            "observation_ref": self.observation_ref,
            "created_at": self.created_at,
            "result_type": self.result_type,
            "presentation_ref": self.presentation_ref,
            "query_basis": deepcopy(self.query_basis),
            "location_count": len(self.service_locations),
            "card_count": len(self.installation_partner_cards),
            "service_location_refs": [
                location.get("service_location_ref")
                for location in self.service_locations[:4]
                if location.get("service_location_ref")
            ],
            "installation_partner_refs": [
                location.get("installation_partner_ref")
                for location in self.service_locations[:4]
                if location.get("installation_partner_ref")
            ],
            "slot_refs": [
                slot.get("slot_ref")
                for group in self.slot_groups[:4]
                for slot in group.get("slots", [])[:2]
                if isinstance(slot, dict) and slot.get("slot_ref")
            ],
            "addon_group_count": len(self.addon_groups),
            "availability_status": self.availability.get("availability_status"),
        }


class ServiceObservationStore:
    """In-memory store for Runtime V7 read-only service observations."""

    def __init__(self) -> None:
        self._observations: Dict[str, ServiceObservation] = {}
        self._latest_ref: Optional[str] = None
        self._location_index: Dict[str, Dict[str, Any]] = {}

    def save_location_result(self, result: Dict[str, Any], *, created_at: Optional[str] = None) -> ServiceObservation:
        """Save an installation-partner lookup result."""

        observation = self._save(result, result_type="installation_partners", created_at=created_at)
        for location in observation.service_locations:
            for key in ("service_location_ref", "installation_partner_ref"):
                ref = str(location.get(key) or "").strip()
                if ref:
                    self._location_index[ref] = deepcopy(location)
        return observation

    def save_availability_result(self, result: Dict[str, Any], *, created_at: Optional[str] = None) -> ServiceObservation:
        """Save a read-only service-availability result."""

        observation = self._save(result, result_type="service_availability", created_at=created_at)
        for location in observation.service_locations:
            for key in ("service_location_ref", "installation_partner_ref"):
                ref = str(location.get(key) or "").strip()
                if ref:
                    self._location_index[ref] = deepcopy(location)
        return observation

    def save_installation_slots_result(
        self,
        result: Dict[str, Any],
        *,
        created_at: Optional[str] = None,
    ) -> ServiceObservation:
        """Save a read-only installation-slot lookup result."""

        return self._save(result, result_type="installation_slots", created_at=created_at)

    def get_location(self, service_location_ref: Optional[Any]) -> Optional[Dict[str, Any]]:
        """Return a previously observed service location or partner by ref."""

        ref = str(service_location_ref or "").strip()
        if not ref:
            return None
        return deepcopy(self._location_index.get(ref) or {})

    def get_observation(self, observation_ref: Optional[Any]) -> Optional[ServiceObservation]:
        """Return a previously saved service observation by ref."""

        ref = str(observation_ref or "").strip()
        if not ref:
            return None
        observation = self._observations.get(ref)
        return deepcopy(observation) if observation else None

    def latest(self) -> Optional[ServiceObservation]:
        """Return the latest service observation."""

        return self._observations.get(self._latest_ref or "")

    def latest_presentation(self) -> Optional[ServiceObservation]:
        """Return the latest service observation with visible presentation cards."""

        for observation in reversed(list(self._observations.values())):
            if observation.installation_partner_cards:
                return observation
        return None

    def latest_installation_slots_observation(
        self,
        *,
        location_label: str = "",
        max_age_seconds: int = 600,
    ) -> Optional[ServiceObservation]:
        """Return a fresh slot observation compatible with the current area."""

        for observation in reversed(list(self._observations.values())):
            if observation.result_type != "installation_slots":
                continue
            if not observation.presentation_ref or not observation.slot_groups:
                continue
            if not _observation_is_fresh(
                observation,
                max_age_seconds=max_age_seconds,
            ):
                continue
            observed_location = str(
                observation.query_basis.get("customer_location_label") or ""
            )
            if (
                location_label
                and observed_location
                and _normalized_location(location_label)
                != _normalized_location(observed_location)
            ):
                continue
            return observation
        return None

    def latest_validated_slot_context(self) -> Dict[str, Any]:
        """Return trusted partner and schedule details for the latest validated slot."""

        observation = self.latest_validated_slot_observation()
        if observation is None:
            return {}
        location = next(
            (
                deepcopy(item)
                for item in observation.service_locations
                if isinstance(item, dict) and item
            ),
            {},
        )
        slot = next(
            (
                deepcopy(item)
                for group in observation.slot_groups
                if isinstance(group, dict)
                for item in group.get("slots") or []
                if isinstance(item, dict) and item
            ),
            {},
        )
        if not location or not slot:
            return {}
        return {
            "observation_ref": observation.observation_ref,
            "presentation_ref": observation.presentation_ref,
            "service_location": location,
            "selected_slot": slot,
            "validation_status": "slot_validated",
        }

    def latest_validated_slot_observation(self) -> Optional[ServiceObservation]:
        """Return the newest validated slot even after later read-only lookups."""

        for observation in reversed(list(self._observations.values())):
            if (
                str(observation.availability.get("availability_status") or "")
                == "slot_validated"
            ):
                return observation
        return None

    def headers(self, *, limit: int = 3) -> List[Dict[str, Any]]:
        """Return compact prompt-facing service observation headers."""

        observations = list(self._observations.values())[-max(1, int(limit or 3)) :]
        return [observation.to_public_header() for observation in observations]

    def clear_location_dependent(self) -> None:
        """Discard partner, slot, and validation evidence after location changes."""

        self._observations.clear()
        self._location_index.clear()
        self._latest_ref = None

    def retain_compatible_location(self, location_label: str) -> None:
        """Keep only service evidence compatible with a newly selected city."""

        expected = _normalized_location(location_label)
        if not expected:
            self.clear_location_dependent()
            return
        kept: Dict[str, ServiceObservation] = {}
        for ref, observation in self._observations.items():
            query = observation.query_basis or {}
            observed = _normalized_location(
                query.get("customer_location_label")
                or query.get("location")
                or ""
            )
            if observed and (
                expected in observed
                or observed in expected
            ):
                kept[ref] = observation
        self._observations = kept
        self._latest_ref = (
            next(reversed(kept))
            if kept
            else None
        )
        self._location_index = {
            ref: deepcopy(location)
            for observation in kept.values()
            for location in observation.service_locations
            if isinstance(location, dict)
            for ref in (
                str(location.get("service_location_ref") or "").strip(),
                str(
                    location.get("installation_partner_ref") or ""
                ).strip(),
            )
            if ref
        }

    def _save(self, result: Dict[str, Any], *, result_type: str, created_at: Optional[str]) -> ServiceObservation:
        observation_ref = str(result.get("observation_ref") or "").strip()
        if not observation_ref:
            observation_ref = f"svc_obs_{result_type}_{len(self._observations) + 1}"
        service_locations = result.get("service_locations") or result.get("installation_partners") or []
        presentation_ref = str(result.get("presentation_ref") or "").strip()
        observation = ServiceObservation(
            observation_ref=observation_ref,
            created_at=created_at or _utc_now_iso(),
            result_type=result_type,
            presentation_ref=presentation_ref,
            query_basis=deepcopy(result.get("query_basis") or {}),
            service_locations=deepcopy(service_locations),
            installation_partner_cards=deepcopy(result.get("installation_partner_cards") or []),
            slot_groups=deepcopy(result.get("slot_groups") or []),
            addon_groups=deepcopy(result.get("addon_groups") or []),
            availability=deepcopy(result.get("availability") or {}),
        )
        self._observations[observation_ref] = observation
        self._latest_ref = observation_ref
        return observation


def _observation_is_fresh(
    observation: ServiceObservation,
    *,
    max_age_seconds: int,
) -> bool:
    """Return whether a reusable service observation is within its TTL."""

    if max_age_seconds <= 0:
        return False
    try:
        created_at = datetime.fromisoformat(
            str(observation.created_at or "").replace("Z", "+00:00")
        )
    except ValueError:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(tz=timezone.utc) - created_at).total_seconds()
    return 0 <= age_seconds <= max_age_seconds


def _normalized_location(value: Any) -> str:
    """Normalize punctuation and spacing for exact area compatibility checks."""

    text = "".join(
        character.casefold() if character.isalnum() else " "
        for character in str(value or "")
    )
    return " ".join(text.split())
