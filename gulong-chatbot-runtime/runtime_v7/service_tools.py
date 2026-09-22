"""Runtime V7 read-only service toolset.

This module wires service tool implementations to the shared service
observation store. Individual tool logic lives in dedicated modules such as
`installation_partners`; this toolset only dispatches and records outputs.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from runtime_v7.canonical_values import CanonicalValuesProvider
from runtime_v7.installation_partners import (
    FindInstallationPartnersTool,
    NO_WALK_IN_POLICY_NOTE,
    PARTNER_DETAIL_AREA_ONLY,
    PARTNER_DETAIL_AVAILABILITY_SUMMARY,
    PARTNER_DETAIL_FULL_ADDRESS,
    PARTNER_DETAIL_NAME_ONLY,
    compact_installation_partner,
    normalize_partner_detail_level,
    normalize_service_type,
)
from runtime_v7.installation_slots import (
    DEFAULT_SLOT_LIMIT,
    InstallationSlotLookup,
    compact_slot,
    preferred_date_options,
    slot_is_same_day,
)
from runtime_v7.location_resolution import RuntimeV7LocationResolver
from runtime_v7.service_observations import ServiceObservationStore


class RuntimeV7ServiceTools:
    """Read-only Runtime V7 service tools used by the harness."""

    def __init__(
        self,
        *,
        store: Optional[ServiceObservationStore] = None,
        canonical_values_provider: Optional[CanonicalValuesProvider] = None,
        installation_partner_tool: Optional[FindInstallationPartnersTool] = None,
        installation_slot_lookup: Optional[InstallationSlotLookup] = None,
        http_client: Optional[Any] = None,
        base_url: Optional[str] = None,
        catalog_ttl_seconds: int = 300,
        location_resolver: Optional[RuntimeV7LocationResolver] = None,
        geocoder: Optional[Any] = None,
        geocode_api_key: Optional[str] = None,
    ) -> None:
        self.store = store or ServiceObservationStore()
        self.canonical_values_provider = canonical_values_provider
        self.installation_partner_tool = installation_partner_tool or FindInstallationPartnersTool(
            http_client=http_client,
            base_url=base_url,
            catalog_ttl_seconds=catalog_ttl_seconds,
            location_resolver=location_resolver,
            geocoder=geocoder,
            geocode_api_key=geocode_api_key,
        )
        self.installation_slot_lookup = installation_slot_lookup or InstallationSlotLookup(
            http_client=http_client,
            base_url=base_url,
        )

    def set_canonical_values_provider(self, provider: CanonicalValuesProvider) -> None:
        """Attach a shared canonical provider for future service metadata use."""

        self.canonical_values_provider = provider

    @property
    def location_resolver(self) -> RuntimeV7LocationResolver:
        """Return the service toolset's shared location resolver."""

        return self.installation_partner_tool.location_resolver

    def find_installation_partners(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute `find_installation_partners` and store its read-only refs."""

        result = self.installation_partner_tool.run(payload or {})
        result = deepcopy(result)
        result["observation_ref"] = result.get("observation_ref") or self._next_ref("installation_partners")
        observation = self.store.save_location_result(result)
        result["observation_ref"] = observation.observation_ref
        return result

    def find_service_locations(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Compatibility alias for callers still using the old V7 tool name."""

        result = self.find_installation_partners(payload)
        result["alias_of"] = "find_installation_partners"
        return result

    def get_branch_addons(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Return read-only addon details/prices for a grounded service partner."""

        payload = payload or {}
        partner_refs = _service_partner_refs(payload)
        locations: List[Dict[str, Any]] = []
        for ref in partner_refs:
            location = self.store.get_location(ref) or {}
            if location:
                locations.append(location)
        lookup: Dict[str, Any] = {}
        if not locations:
            lookup = self.find_installation_partners(
                {
                    "location": payload.get("location") or payload.get("area"),
                    "installation_partner_name": payload.get("installation_partner_name") or payload.get("partner_name"),
                    "service_type": "installation",
                    "requested_addons": payload.get("requested_addons") or payload.get("branch_addons"),
                    "top_k": 3,
                }
            )
            locations = [
                compact_installation_partner(partner)
                for partner in lookup.get("installation_partners") or []
                if isinstance(partner, dict)
            ]
        requested_addons = _list_of_text(payload.get("requested_addons") or payload.get("branch_addons"))
        addon_groups = []
        addon_count = 0
        matched_addon_count = 0
        for location in locations[:3]:
            addons = _addon_details_for_location(location)
            addon_count += len(addons)
            filtered_addons = _filter_addon_details(addons, requested_addons)
            matched_addon_count += len(filtered_addons)
            addon_groups.append(
                {
                    "installation_partner_ref": location.get("installation_partner_ref"),
                    "service_location_ref": location.get("service_location_ref"),
                    "branch_id": location.get("branch_id"),
                    "name": location.get("name"),
                    "address": location.get("address"),
                    "municipality_city": _public_location_label(location),
                    "addons": filtered_addons,
                    "pricing_available": any(addon.get("price") is not None for addon in filtered_addons),
                }
            )
        status = (
            "ok"
            if matched_addon_count
            else "no_matching_addons"
            if requested_addons and addon_count
            else "no_addons"
            if locations
            else "no_service_location"
        )
        result = {
            "status": status,
            "observation_ref": self._next_ref("branch_addons"),
            "query_basis": {
                "service_location_ref": payload.get("service_location_ref") or None,
                "installation_partner_ref": payload.get("installation_partner_ref") or None,
                "installation_partner_name": _clean_text(payload.get("installation_partner_name") or payload.get("partner_name")) or None,
                "location": _clean_text(payload.get("location") or payload.get("area")) or None,
                "requested_addons": requested_addons,
            },
            "addon_groups": addon_groups,
            "lookup_observation_ref": lookup.get("observation_ref"),
            "read_only": True,
            "can_confirm_booking": False,
            "source": "runtime_v7_gulong_branch_catalog",
            "generated_at": _utc_now_iso(),
            "ttl_seconds": 900,
            "note": "Read-only branch addon details from the branch catalog. Addon availability/prices still need final order validation before booking or payment.",
        }
        saved = self.store.save_availability_result(result)
        result["observation_ref"] = saved.observation_ref
        return result

    def find_installation_slots(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Find read-only installation slot options for nearby partners."""

        payload = payload or {}
        service_type = normalize_service_type(payload.get("service_type"))
        preferred_date = _clean_text(payload.get("preferred_date"))
        preferred_date_start = _clean_text(payload.get("preferred_date_start"))
        preferred_date_end = _clean_text(payload.get("preferred_date_end"))
        preferred_time_window = _clean_text(payload.get("preferred_time_window"))
        request_time = _clean_text(payload.get("request_time"))
        source_schedule_phrase = _clean_text(payload.get("source_schedule_phrase") or payload.get("schedule_phrase"))
        preferred_schedule_candidates = payload.get("preferred_schedule_candidates")
        partner_detail_level = normalize_partner_detail_level(
            payload.get("partner_detail_level"),
            default=PARTNER_DETAIL_AVAILABILITY_SUMMARY,
        )
        slots_per_partner = _coerce_int(payload.get("slots_per_partner") or payload.get("slot_limit"), default=DEFAULT_SLOT_LIMIT, minimum=1, maximum=4)
        slot_collection_limit = max(slots_per_partner, 4)
        max_days = _coerce_int(payload.get("max_days"), default=14, minimum=0, maximum=14)
        top_k = _coerce_int(payload.get("top_k"), default=3, minimum=1, maximum=6)
        partner_search_top_k = _coerce_int(
            payload.get("partner_search_top_k"),
            default=max(6, top_k),
            minimum=top_k,
            maximum=6,
        )
        if service_type == "delivery":
            result = {
                "status": "not_applicable_for_delivery",
                "observation_ref": self._next_ref("installation_slots"),
                "query_basis": {
                    "service_location_ref": payload.get("service_location_ref") or None,
                    "installation_partner_ref": payload.get("installation_partner_ref") or None,
                    "location": _clean_text(payload.get("location") or payload.get("area")) or None,
                    "service_type": service_type,
                    "preferred_date": preferred_date or None,
                    "preferred_date_start": preferred_date_start or None,
                    "preferred_date_end": preferred_date_end or None,
                    "preferred_time_window": preferred_time_window or None,
                    "source_schedule_phrase": source_schedule_phrase or None,
                    "preferred_schedule_candidates": _compact_schedule_candidate_inputs(preferred_schedule_candidates),
                    "request_time": request_time or None,
                    "section_width": _clean_text(payload.get("section_width")) or None,
                    "aspect_ratio": _clean_text(payload.get("aspect_ratio")) or None,
                    "rim_size": _clean_text(payload.get("rim_size")) or None,
                    "model_query": _clean_text(payload.get("model_query") or payload.get("model_or_pattern")) or None,
                    "tire_brand": _clean_text(payload.get("tire_brand") or payload.get("brand")) or None,
                    "partner_detail_level": partner_detail_level,
                },
                "partner_detail_level": partner_detail_level,
                "detail_disclosure": {},
                "coverage_assessment": {
                    "customer_location_label": _clean_text(payload.get("location") or payload.get("area")) or None,
                    "installation_service_area_status": "not_applicable_for_delivery",
                    "delivery_fallback_relevant": False,
                    "presentable_partner_count": 0,
                    "presentation_confidence": "not_applicable",
                },
                "customer_explanation_hints": [
                    "This was a delivery request, not an installation slot lookup.",
                    "Do not say no installation partner matched.",
                    "Do not say delivery is unavailable.",
                    "Use order policy or quote tools for delivery fee/process.",
                    "If the conversation needs installation, run a separate installation lookup with service_type=installation.",
                ],
                "lookup_observation_ref": None,
                "presentation_ref": None,
                "installation_partner_cards": [],
                "service_policy_notes": [],
                "service_locations": [],
                "installation_partners": [],
                "slot_groups": [],
                "availability": {
                    "availability_status": "not_applicable_for_delivery",
                    "same_day_requested": _same_day_requested(preferred_date, preferred_time_window, request_time=request_time),
                    "same_day_available": False,
                    "slot_count": 0,
                    "partner_count_checked": 0,
                    "can_confirm_booking": False,
                    "requires_follow_up": True,
                },
                "read_only": True,
                "can_confirm_booking": False,
                "source": "runtime_v7_installation_slot_lookup",
                "generated_at": _utc_now_iso(),
                "ttl_seconds": 300,
                "note": (
                    "find_installation_slots is not applicable to delivery requests. "
                    "Use delivery/order policy or quote tools for delivery, or run an installation lookup "
                    "with service_type=installation if the customer wants installation."
                ),
            }
            observation = self.store.save_installation_slots_result(result)
            result["observation_ref"] = observation.observation_ref
            return result
        partner_refs = _service_partner_refs(payload)
        locations: List[Dict[str, Any]] = []
        for ref in partner_refs:
            location = self.store.get_location(ref) or {}
            if location:
                locations.append(location)
        source = "runtime_v7_installation_slot_lookup"
        lookup: Dict[str, Any] = {}

        if not locations:
            lookup = self.find_installation_partners(
                _partner_lookup_payload(
                    payload,
                    service_type=service_type,
                    top_k=partner_search_top_k,
                    partner_detail_level=partner_detail_level,
                )
            )
            source = str(lookup.get("source") or source).strip()
            partners = lookup.get("installation_partners") or []
            locations = [compact_installation_partner(partner) for partner in partners if isinstance(partner, dict)]

        if not locations:
            result = {
                "status": "no_service_location",
                "observation_ref": self._next_ref("installation_slots"),
                "query_basis": _with_lookup_query_metadata(
                    {
                        "service_location_ref": payload.get("service_location_ref") or None,
                        "installation_partner_ref": payload.get("installation_partner_ref") or None,
                        "location": _clean_text(payload.get("location") or payload.get("area")) or None,
                        "service_type": service_type,
                        "preferred_date": preferred_date or None,
                        "preferred_date_start": preferred_date_start or None,
                        "preferred_date_end": preferred_date_end or None,
                        "preferred_time_window": preferred_time_window or None,
                        "source_schedule_phrase": source_schedule_phrase or None,
                        "preferred_schedule_candidates": _compact_schedule_candidate_inputs(preferred_schedule_candidates),
                        "request_time": request_time or None,
                        "section_width": _clean_text(payload.get("section_width")) or None,
                        "aspect_ratio": _clean_text(payload.get("aspect_ratio")) or None,
                        "rim_size": _clean_text(payload.get("rim_size")) or None,
                        "model_query": _clean_text(payload.get("model_query") or payload.get("model_or_pattern")) or None,
                        "tire_brand": _clean_text(payload.get("tire_brand") or payload.get("brand")) or None,
                        "trusted_order_total": _coerce_optional_float(payload.get("trusted_order_total")),
                        "trusted_order_total_source": _clean_text(payload.get("trusted_order_total_source")) or None,
                        "partner_detail_level": partner_detail_level,
                    },
                    lookup,
                ),
                "partner_detail_level": lookup.get("partner_detail_level") or partner_detail_level,
                "detail_disclosure": deepcopy(lookup.get("detail_disclosure") or {}),
                "coverage_assessment": deepcopy(lookup.get("coverage_assessment") or {}),
                "customer_explanation_hints": deepcopy(lookup.get("customer_explanation_hints") or []),
                "lookup_observation_ref": lookup.get("observation_ref"),
                "presentation_ref": lookup.get("presentation_ref"),
                "installation_partner_cards": deepcopy(lookup.get("installation_partner_cards") or []),
                "service_policy_notes": deepcopy(lookup.get("service_policy_notes") or []),
                "service_locations": [],
                "installation_partners": [],
                "slot_groups": [],
                "availability": {
                    "availability_status": "no_installation_partner_match",
                    "same_day_requested": _same_day_requested(preferred_date, preferred_time_window, request_time=request_time),
                    "same_day_available": False,
                    "slot_count": 0,
                    "partner_count_checked": 0,
                    "can_confirm_booking": False,
                    "requires_follow_up": True,
                },
                "read_only": True,
                "can_confirm_booking": False,
                "source": source,
                "generated_at": _utc_now_iso(),
                "ttl_seconds": 300,
                "note": _availability_no_location_note(lookup),
            }
            observation = self.store.save_installation_slots_result(result)
            result["observation_ref"] = observation.observation_ref
            return result

        slot_option_candidates = _slot_search_option_candidates(
            preferred_date=preferred_date,
            preferred_date_start=preferred_date_start,
            preferred_date_end=preferred_date_end,
            preferred_time_window=preferred_time_window,
            request_time=request_time,
            source_schedule_phrase=source_schedule_phrase,
            preferred_schedule_candidates=preferred_schedule_candidates,
        )
        primary_slot_options = slot_option_candidates[0] if slot_option_candidates else _empty_slot_options()
        schedule_constrained = any(_schedule_constrained(options) for options in slot_option_candidates)
        slot_groups: List[Dict[str, Any]] = []
        all_slots: List[Dict[str, Any]] = []
        fallback_next_slots: List[Dict[str, Any]] = []
        group_locations: List[Dict[str, Any]] = []
        for location in locations[:partner_search_top_k]:
            branch_slots: Dict[str, Any] = {}
            compact_slots: List[Dict[str, Any]] = []
            selected_slot_options = primary_slot_options
            schedule_candidate_attempts: List[Dict[str, Any]] = []
            for slot_options in slot_option_candidates:
                candidate_branch_slots = self.installation_slot_lookup.branch_slots(
                    location,
                    request_time=request_time or None,
                    limit=slot_collection_limit,
                    max_days=max_days,
                    prefer_weekend=bool(slot_options.get("prefer_weekend")),
                    preferred_weekday=slot_options.get("preferred_weekday"),
                    preferred_date=slot_options.get("preferred_date"),
                    preferred_date_start=slot_options.get("preferred_date_start"),
                    preferred_date_end=slot_options.get("preferred_date_end"),
                )
                if not branch_slots:
                    branch_slots = candidate_branch_slots
                candidate_compact_slots = [
                    compact_slot(slot, request_time=request_time or None)
                    for slot in candidate_branch_slots.get("slots") or []
                    if isinstance(slot, dict)
                ]
                schedule_candidate_attempts.append(
                    {
                        "candidate_index": slot_options.get("candidate_index"),
                        "candidate_source": slot_options.get("candidate_source"),
                        "candidate_label": slot_options.get("candidate_label"),
                        "candidate_confidence": slot_options.get("candidate_confidence"),
                        "status": candidate_branch_slots.get("status"),
                        "slot_count": len(candidate_compact_slots),
                    }
                )
                if candidate_compact_slots:
                    branch_slots = candidate_branch_slots
                    compact_slots = candidate_compact_slots
                    selected_slot_options = slot_options
                    break
            all_slots.extend(compact_slots)
            next_open_lookup: Dict[str, Any] = {}
            next_open_slot: Optional[Dict[str, Any]] = None
            if not compact_slots and (
                primary_slot_options.get("preferred_date")
                or primary_slot_options.get("preferred_weekday")
                or primary_slot_options.get("prefer_weekend")
                or primary_slot_options.get("preferred_date_start")
            ):
                next_open_lookup = self.installation_slot_lookup.branch_availability(
                    location,
                    request_time=request_time or None,
                    horizon_days=max_days,
                    not_before_date=_fallback_not_before_date(primary_slot_options),
                )
                raw_next_slot = next_open_lookup.get("next_open_slot")
                if isinstance(raw_next_slot, dict):
                    next_open_slot = compact_slot(raw_next_slot, request_time=request_time or None)
                    fallback_next_slots.append(next_open_slot)
            slot_groups.append(
                {
                    "installation_partner_ref": location.get("installation_partner_ref"),
                    "service_location_ref": location.get("service_location_ref"),
                    "branch_id": location.get("branch_id"),
                    "name": location.get("name"),
                    "address": location.get("address")
                    or location.get("full_address"),
                    "area": location.get("area"),
                    "city": location.get("city"),
                    "province": location.get("province"),
                    "municipality_city": _public_location_label(location),
                    "status": branch_slots.get("status"),
                    "gating_reason": branch_slots.get("gating_reason"),
                    "earliest_allowed": branch_slots.get("earliest_allowed"),
                    "lead_days_applied": branch_slots.get("lead_days_applied"),
                    "selected_schedule_candidate": _compact_slot_options(selected_slot_options),
                    "schedule_candidate_attempts": schedule_candidate_attempts,
                    "slots": compact_slots,
                    "fallback_next_open_slot": next_open_slot,
                    "fallback_next_open_status": next_open_lookup.get("status") if next_open_lookup else None,
                }
            )
            group_locations.append(location)

        visible_groups, visible_locations = _visible_slot_groups_and_locations(
            slot_groups,
            group_locations,
            top_k=top_k,
            schedule_constrained=schedule_constrained,
        )
        visible_slots = [
            slot
            for group in visible_groups
            for slot in group.get("slots") or []
            if isinstance(slot, dict)
        ]
        visible_fallback_slots = [
            group.get("fallback_next_open_slot")
            for group in visible_groups
            if isinstance(group.get("fallback_next_open_slot"), dict)
        ]

        earliest = _earliest_slot(visible_slots + visible_fallback_slots)
        same_day_requested = any(bool(options.get("same_day_requested")) for options in slot_option_candidates)
        same_day_available = any(
            slot_is_same_day(slot, request_time=request_time or None)
            for slot in visible_slots
        ) if same_day_requested else None
        requested_exact_dates = _requested_exact_dates(slot_option_candidates)
        requested_exact_date_returned = _slots_include_any_date(visible_slots, requested_exact_dates)
        visible_slots_are_next_available = bool(
            visible_slots
            and requested_exact_dates
            and not requested_exact_date_returned
        ) or bool(
            visible_slots
            and same_day_requested
            and same_day_available is False
            and not requested_exact_date_returned
        )
        status = "ok" if visible_slots or visible_fallback_slots else "no_slots"
        availability_status = (
            "next_slots_found"
            if visible_slots_are_next_available
            else "slots_found"
            if visible_slots
            else "next_slots_found"
            if visible_fallback_slots
            else "no_slots_found"
        )
        cards = _render_installation_slot_cards(
            visible_groups,
            detail_level=partner_detail_level,
            customer_location_label=_customer_location_label_from_lookup_or_groups(lookup, visible_groups),
        )
        policy_notes = deepcopy(lookup.get("service_policy_notes") or [])
        if cards and not policy_notes:
            policy_notes = [{"id": "no_walkin_setup", "source": "runtime_gulong_spiel_bank", "text": NO_WALK_IN_POLICY_NOTE}]
        result = {
            "status": status,
            "observation_ref": self._next_ref("installation_slots"),
            "query_basis": _with_lookup_query_metadata(
                {
                    "service_location_ref": payload.get("service_location_ref") or None,
                    "installation_partner_ref": payload.get("installation_partner_ref") or None,
                    "location": _clean_text(payload.get("location") or payload.get("area")) or _public_location_label(locations[0]),
                    "service_type": service_type,
                    "preferred_date": preferred_date or None,
                    "preferred_date_start": preferred_date_start or None,
                    "preferred_date_end": preferred_date_end or None,
                    "preferred_time_window": preferred_time_window or None,
                    "source_schedule_phrase": source_schedule_phrase or None,
                    "preferred_schedule_candidates": _compact_schedule_candidate_inputs(preferred_schedule_candidates),
                    "request_time": request_time or None,
                    "section_width": _clean_text(payload.get("section_width")) or None,
                    "aspect_ratio": _clean_text(payload.get("aspect_ratio")) or None,
                    "rim_size": _clean_text(payload.get("rim_size")) or None,
                    "model_query": _clean_text(payload.get("model_query") or payload.get("model_or_pattern")) or None,
                    "tire_brand": _clean_text(payload.get("tire_brand") or payload.get("brand")) or None,
                    "trusted_order_total": _coerce_optional_float(payload.get("trusted_order_total")),
                    "trusted_order_total_source": _clean_text(payload.get("trusted_order_total_source")) or None,
                    "partner_detail_level": partner_detail_level,
                    "slot_search": {key: value for key, value in primary_slot_options.items() if value not in (None, "", False)},
                    "slot_search_candidates": [
                        _compact_slot_options(options)
                        for options in slot_option_candidates
                        if _compact_slot_options(options)
                    ],
                },
                lookup,
            ),
            "service_locations": visible_locations,
            "installation_partners": visible_locations,
            "partner_detail_level": partner_detail_level,
            "detail_disclosure": _slot_detail_disclosure(
                detail_level=partner_detail_level,
                groups=visible_groups,
                customer_location_label=_customer_location_label_from_lookup_or_groups(lookup, visible_groups),
            ),
            "checked_service_location_count": len(locations[:partner_search_top_k]),
            "slot_groups": visible_groups,
            "availability": {
                "availability_status": availability_status,
                "same_day_requested": same_day_requested,
                "same_day_available": same_day_available,
                "requested_exact_dates": requested_exact_dates,
                "requested_exact_date_returned": requested_exact_date_returned if requested_exact_dates else None,
                "slot_count": len(visible_slots),
                "matching_partner_count": len([group for group in visible_groups if group.get("slots")]),
                "fallback_next_slot_count": len(visible_fallback_slots),
                "partner_count_checked": len(locations[:partner_search_top_k]),
                "earliest_available_slot": earliest,
                "can_confirm_booking": False,
                "requires_follow_up": True,
                "follow_up_needed": "customer must choose a slot and complete product/order readiness before booking confirmation",
            },
            "read_only": True,
            "can_confirm_booking": False,
            "source": source,
            "generated_at": _utc_now_iso(),
            "ttl_seconds": 300,
            "note": "Read-only slot lookup. Candidate slots are grounded by branch slot endpoints but do not confirm booking, reservation, payment, or fulfillment.",
        }
        if lookup:
            result["lookup_observation_ref"] = lookup.get("observation_ref")
            result["coverage_assessment"] = deepcopy(lookup.get("coverage_assessment") or {})
        else:
            result["coverage_assessment"] = {}
        result["presentation_ref"] = _slot_presentation_ref(result["query_basis"], visible_groups) if cards else lookup.get("presentation_ref")
        result["installation_partner_cards"] = cards
        result["service_policy_notes"] = policy_notes
        if lookup.get("customer_explanation_hints"):
            result["customer_explanation_hints"] = deepcopy(lookup.get("customer_explanation_hints") or [])
        observation = self.store.save_installation_slots_result(result)
        result["observation_ref"] = observation.observation_ref
        return result

    def validate_installation_slot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a model-chosen slot against previously grounded slot observations."""

        payload = payload or {}
        observation_ref = _clean_text(payload.get("observation_ref") or payload.get("service_observation_ref"))
        observation = self.store.get_observation(observation_ref) if observation_ref else self.store.latest()
        slot_ref = _clean_text(payload.get("slot_ref"))
        selected_slot_ordinal = _coerce_int(payload.get("slot_ordinal"), default=0, minimum=0, maximum=20)
        partner_ref = _clean_text(payload.get("installation_partner_ref") or payload.get("service_location_ref"))
        preferred_datetime = _clean_text(payload.get("datetime") or payload.get("schedule"))
        preferred_date = _clean_text(payload.get("date") or payload.get("preferred_date"))
        preferred_time = _clean_text(payload.get("time") or payload.get("preferred_time"))

        if observation is None:
            result = {
                "status": "no_observation",
                "valid": False,
                "reason": "no_prior_installation_slot_observation",
                "observation_ref": None,
                "read_only": True,
                "can_confirm_booking": False,
                "note": "Call find_installation_slots before validating a customer-selected slot.",
            }
            saved = self.store.save_availability_result(result)
            result["observation_ref"] = saved.observation_ref
            return result

        candidates = _slot_candidates_from_observation(observation.slot_groups)
        match = _match_slot_candidate(
            candidates,
            slot_ref=slot_ref,
            slot_ordinal=selected_slot_ordinal,
            partner_ref=partner_ref,
            preferred_datetime=preferred_datetime,
            preferred_date=preferred_date,
            preferred_time=preferred_time,
        )
        needs_reference = not any([slot_ref, selected_slot_ordinal, preferred_datetime, preferred_date and preferred_time])
        status = "ok" if match else "needs_slot_reference" if needs_reference else "not_found"
        result = {
            "status": status,
            "valid": bool(match),
            "reason": "matched_grounded_slot" if match else "missing_slot_reference" if needs_reference else "slot_not_in_observation",
            "source_observation_ref": observation.observation_ref,
            "observation_ref": self._next_ref("installation_slot_validation"),
            "selected_slot": deepcopy(match.get("slot")) if match else None,
            "selected_installation_partner": deepcopy(match.get("partner")) if match else None,
            "service_locations": [deepcopy(match.get("partner"))] if match else [],
            "slot_groups": [
                {
                    "partner": deepcopy(match.get("partner")),
                    "slots": [deepcopy(match.get("slot"))],
                    "validation_status": "selected_by_customer",
                }
            ]
            if match
            else [],
            "availability": {
                "availability_status": "slot_validated" if match else status,
                "can_confirm_booking": False,
                "requires_follow_up": not bool(match),
                "slot_count": 1 if match else 0,
            },
            "available_slot_refs": [candidate.get("slot", {}).get("slot_ref") for candidate in candidates[:8] if candidate.get("slot", {}).get("slot_ref")],
            "read_only": True,
            "can_confirm_booking": False,
            "note": "Read-only slot validation against stored Runtime V7 slot observations. This does not book, reserve, or confirm fulfillment.",
        }
        saved = self.store.save_availability_result(result)
        result["observation_ref"] = saved.observation_ref
        return result

    def _next_ref(self, suffix: str) -> str:
        return f"svc_obs_{suffix}_{len(self.store.headers(limit=99)) + 1}"


def _with_lookup_query_metadata(query_basis: Dict[str, Any], lookup: Dict[str, Any]) -> Dict[str, Any]:
    """Carry normalized lookup context into availability results when available."""

    merged = deepcopy(query_basis)
    lookup_query = lookup.get("query_basis") if isinstance(lookup, dict) else {}
    if not isinstance(lookup_query, dict):
        return merged
    if not merged.get("location") and lookup_query.get("location"):
        merged["location"] = lookup_query.get("location")
    for key in ("model_query", "tire_brand"):
        if key in lookup_query:
            merged[key] = deepcopy(lookup_query.get(key))
    for key in (
        "customer_location_label",
        "location_resolution",
        "location_input_status",
        "service_type_was_defaulted",
        "partner_catalog_filter",
        "advisory_model_query",
        "advisory_tire_brand",
    ):
        value = lookup_query.get(key)
        if value not in (None, "", {}):
            merged[key] = deepcopy(value)
    return merged


def _customer_location_label_from_lookup_or_groups(
    lookup: Dict[str, Any],
    groups: Sequence[Dict[str, Any]],
) -> str:
    query = lookup.get("query_basis") if isinstance(lookup, dict) else {}
    if isinstance(query, dict):
        label = _clean_text(query.get("customer_location_label"))
        if label:
            return label
    coverage = lookup.get("coverage_assessment") if isinstance(lookup, dict) else {}
    if isinstance(coverage, dict):
        label = _clean_text(coverage.get("customer_location_label"))
        if label:
            return label
    for group in groups or []:
        if isinstance(group, dict):
            label = _clean_text(group.get("municipality_city"))
            if label:
                return label
    return ""


def _slot_detail_disclosure(
    *,
    detail_level: str,
    groups: Sequence[Dict[str, Any]],
    customer_location_label: str,
) -> Dict[str, Any]:
    normalized = normalize_partner_detail_level(detail_level, default=PARTNER_DETAIL_AVAILABILITY_SUMMARY)
    names_revealed = normalized in {PARTNER_DETAIL_NAME_ONLY, PARTNER_DETAIL_FULL_ADDRESS}
    addresses_revealed = normalized == PARTNER_DETAIL_FULL_ADDRESS
    partner_refs = [
        _clean_text(group.get("installation_partner_ref") or group.get("service_location_ref"))
        for group in groups or []
        if isinstance(group, dict)
    ]
    return {
        "partner_detail_level": normalized,
        "customer_location_label": customer_location_label or "",
        "partner_names_revealed": names_revealed,
        "exact_addresses_revealed": addresses_revealed,
        "partner_count_considered": len(_unique([ref for ref in partner_refs if ref])),
        "policy": (
            "Slot discovery should normally show area-level availability first. "
            "Exact installation partner details stay internal until order-summary/proceed context "
            "or explicit branch-detail request with the reservation/no-walk-in policy."
        ),
    }


def _partner_lookup_payload(
    payload: Dict[str, Any],
    *,
    service_type: str,
    top_k: int,
    partner_detail_level: str = PARTNER_DETAIL_AREA_ONLY,
) -> Dict[str, Any]:
    return {
        "location": payload.get("location") or payload.get("area"),
        "service_type": service_type,
        "installation_partner_name": payload.get("installation_partner_name") or payload.get("partner_name"),
        "requested_addons": payload.get("requested_addons") or payload.get("branch_addons"),
        "section_width": payload.get("section_width"),
        "aspect_ratio": payload.get("aspect_ratio"),
        "rim_size": payload.get("rim_size"),
        "model_query": payload.get("model_query") or payload.get("model_or_pattern"),
        "tire_brand": payload.get("tire_brand") or payload.get("brand"),
        "trusted_order_total": payload.get("trusted_order_total"),
        "partner_detail_level": partner_detail_level,
        "radius_km": payload.get("radius_km") or 20,
        "top_k": top_k,
    }


def _service_partner_refs(payload: Dict[str, Any]) -> List[str]:
    refs: List[str] = []
    for key in ("installation_partner_ref", "service_location_ref"):
        value = payload.get(key)
        if isinstance(value, list):
            refs.extend(str(item).strip() for item in value if str(item or "").strip())
        elif str(value or "").strip():
            refs.append(str(value).strip())
    return _unique(refs)


def _schedule_constrained(slot_options: Dict[str, Any]) -> bool:
    return any(
        slot_options.get(key)
        for key in (
            "preferred_date",
            "preferred_date_start",
            "preferred_date_end",
            "preferred_weekday",
            "prefer_weekend",
        )
    )


def _fallback_not_before_date(slot_options: Dict[str, Any]) -> Optional[str]:
    for key in ("preferred_date", "preferred_date_start"):
        value = slot_options.get(key)
        if str(value or "").strip():
            return str(value).strip()
    return None


def _requested_exact_dates(slot_options: Sequence[Dict[str, Any]]) -> List[str]:
    dates: List[str] = []
    for option in slot_options or []:
        if not isinstance(option, dict):
            continue
        value = _valid_date_text(option.get("preferred_date"))
        if value and value not in dates:
            dates.append(value)
    return dates


def _slots_include_any_date(slots: Sequence[Dict[str, Any]], requested_dates: Sequence[str]) -> bool:
    requested = {str(date or "").strip() for date in requested_dates or [] if str(date or "").strip()}
    if not requested:
        return False
    for slot in slots or []:
        if not isinstance(slot, dict):
            continue
        if str(slot.get("date") or "").strip() in requested:
            return True
    return False


def _visible_slot_groups_and_locations(
    slot_groups: Sequence[Dict[str, Any]],
    locations: Sequence[Dict[str, Any]],
    *,
    top_k: int,
    schedule_constrained: bool,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    pairs = [
        (index, group, locations[index])
        for index, group in enumerate(slot_groups)
        if index < len(locations) and isinstance(group, dict) and isinstance(locations[index], dict)
    ]
    matching = [(index, group, location) for index, group, location in pairs if group.get("slots")]
    matching.sort(key=lambda pair: (_schedule_candidate_sort_index(pair[1]), pair[0]))
    if matching:
        selected = matching[:top_k]
    else:
        fallback = [
            (index, group, location)
            for index, group, location in pairs
            if isinstance(group.get("fallback_next_open_slot"), dict)
        ]
        selected = fallback[:top_k] if fallback else ([] if schedule_constrained else pairs[:top_k])
    return [deepcopy(group) for _, group, _ in selected], [deepcopy(location) for _, _, location in selected]


def _render_installation_slot_cards(
    slot_groups: Sequence[Dict[str, Any]],
    *,
    detail_level: str = PARTNER_DETAIL_AVAILABILITY_SUMMARY,
    customer_location_label: str = "",
) -> List[Dict[str, Any]]:
    """Return deterministic public partner rows with compact schedule hints."""

    normalized_detail = normalize_partner_detail_level(detail_level, default=PARTNER_DETAIL_AVAILABILITY_SUMMARY)
    if normalized_detail in {PARTNER_DETAIL_AREA_ONLY, PARTNER_DETAIL_AVAILABILITY_SUMMARY}:
        return _render_area_only_slot_cards(slot_groups, customer_location_label=customer_location_label)
    cards: List[Dict[str, Any]] = []
    for group in slot_groups or []:
        if not isinstance(group, dict):
            continue
        name = _clean_text(group.get("name"))
        place = _clean_text(group.get("municipality_city"))
        address = _clean_text(group.get("address"))
        if not name:
            continue
        slot_lines = _slot_summary_lines(group)
        if not slot_lines:
            continue
        card_index = len(cards) + 1
        if normalized_detail == PARTNER_DETAIL_FULL_ADDRESS:
            location_line = address or place
            header = "\n".join(
                part
                for part in [
                    f"🛞 {name}",
                    f"📍 {location_line}" if location_line else "",
                ]
                if part
            )
        else:
            header = f"🛞 {name} - 📍 {place}" if place else f"🛞 {name}"
        card_text = "\n".join([header, *[f"   🕒 {line}" for line in slot_lines]])
        card = {
            "card_ref": f"partner_card_{card_index}",
            "installation_partner_ref": group.get("installation_partner_ref"),
            "service_location_ref": group.get("service_location_ref"),
            "branch_id": group.get("branch_id"),
            "partner_detail_level": normalized_detail,
            "name": name,
            "municipality_city": place,
            "slot_summary_lines": slot_lines,
            "slot_refs": [
                slot.get("slot_ref")
                for slot in group.get("slots") or []
                if isinstance(slot, dict) and slot.get("slot_ref")
            ],
            "card_text": card_text,
        }
        if normalized_detail == PARTNER_DETAIL_FULL_ADDRESS and address:
            card["address"] = address
        cards.append(card)
    return cards


def _render_area_only_slot_cards(
    slot_groups: Sequence[Dict[str, Any]],
    *,
    customer_location_label: str = "",
) -> List[Dict[str, Any]]:
    slots: List[Dict[str, Any]] = []
    fallback_slots: List[Dict[str, Any]] = []
    candidate_partner_refs: List[str] = []
    candidate_location_refs: List[str] = []
    candidate_branch_ids: List[str] = []
    places: List[str] = []
    for group in slot_groups or []:
        if not isinstance(group, dict):
            continue
        partner_ref = _clean_text(group.get("installation_partner_ref"))
        location_ref = _clean_text(group.get("service_location_ref"))
        branch_id = _clean_text(group.get("branch_id"))
        place = _clean_text(group.get("municipality_city"))
        if partner_ref:
            candidate_partner_refs.append(partner_ref)
        if location_ref:
            candidate_location_refs.append(location_ref)
        if branch_id:
            candidate_branch_ids.append(branch_id)
        if place:
            places.append(place)
        for slot in group.get("slots") or []:
            if isinstance(slot, dict):
                slots.append(slot)
        fallback = group.get("fallback_next_open_slot")
        if isinstance(fallback, dict):
            fallback_slots.append(fallback)

    slot_lines = _group_slot_lines(slots)[:3]
    if not slot_lines and fallback_slots:
        fallback_labels = [_slot_full_label(slot) for slot in fallback_slots if _slot_full_label(slot)]
        unique_labels = _unique(fallback_labels)
        if unique_labels:
            slot_lines = [f"Next available: {_join_time_labels(unique_labels[:3])}"]
    if not slot_lines:
        return []

    area_label = _clean_text(customer_location_label) or (places[0] if places else "")
    area_text = f"{area_label} area" if area_label else "your area"
    return [
        {
            "card_ref": "partner_card_1",
            "partner_detail_level": PARTNER_DETAIL_AVAILABILITY_SUMMARY,
            "display_name": "Installation slot options",
            "municipality_city": area_label,
            "candidate_installation_partner_refs": _unique(candidate_partner_refs),
            "candidate_service_location_refs": _unique(candidate_location_refs),
            "candidate_branch_ids": _unique(candidate_branch_ids),
            "partner_count": len(_unique(candidate_partner_refs or candidate_location_refs or candidate_branch_ids)),
            "slot_summary_lines": slot_lines,
            "slot_refs": [
                slot.get("slot_ref")
                for slot in slots
                if isinstance(slot, dict) and slot.get("slot_ref")
            ],
            "card_text": "\n".join(
                [f"🛞 Installation slots near {area_text}", *[f"   🕒 {line}" for line in slot_lines]]
            ),
        }
    ]


def _slot_summary_lines(group: Dict[str, Any]) -> List[str]:
    slots = [slot for slot in group.get("slots") or [] if isinstance(slot, dict)]
    if slots:
        return _group_slot_lines(slots)[:3]
    fallback = group.get("fallback_next_open_slot")
    if isinstance(fallback, dict):
        label = _slot_full_label(fallback)
        return [f"Next available: {label}"] if label else []
    return []


def _group_slot_lines(slots: Sequence[Dict[str, Any]]) -> List[str]:
    records = [_slot_record(slot) for slot in slots]
    records = [record for record in records if record]
    if not records:
        return []

    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        by_date.setdefault(record["date"], []).append(record)

    lines: List[str] = []
    for date, date_records in sorted(by_date.items()):
        date_records.sort(key=lambda item: item["minutes"])
        time_labels: List[str] = []
        seen_times: set[str] = set()
        for record in date_records:
            time_text = record["time_text"]
            if time_text in seen_times:
                continue
            seen_times.add(time_text)
            time_labels.append(time_text)
        if time_labels:
            lines.append(f"{_slot_date_label(date_records[0])}: {_join_time_labels(time_labels)}")

    return _compact_repeating_slot_lines(lines)


def _join_time_labels(labels: Sequence[str]) -> str:
    clean = [label for label in labels if label]
    if len(clean) <= 1:
        return clean[0] if clean else ""
    if len(clean) == 2:
        return f"{clean[0]} or {clean[1]}"
    return f"{', '.join(clean[:-1])}, or {clean[-1]}"


def _compact_repeating_slot_lines(lines: Sequence[str]) -> List[str]:
    grouped: Dict[str, List[str]] = {}
    passthrough: List[str] = []
    for line in lines:
        if ": " not in line:
            passthrough.append(line)
            continue
        date_label, time_label = line.split(": ", 1)
        grouped.setdefault(time_label, []).append(date_label)
    compacted: List[str] = []
    for time_label, date_labels in grouped.items():
        if len(date_labels) >= 2:
            compacted.append(f"{_join_date_labels(date_labels)}: {time_label}")
        else:
            compacted.append(f"{date_labels[0]}: {time_label}")
    return compacted + passthrough


def _join_date_labels(labels: Sequence[str]) -> str:
    clean = [label for label in labels if label]
    if len(clean) <= 1:
        return clean[0] if clean else ""
    if len(clean) == 2:
        return f"{clean[0]} / {clean[1]}"
    return f"{clean[0]} - {clean[-1]}"


def _slot_record(slot: Dict[str, Any]) -> Dict[str, Any]:
    date = _clean_text(slot.get("date"))
    time_text = _clean_text(slot.get("time_text"))
    if not date or not time_text:
        return {}
    return {
        "date": date,
        "weekday": _clean_text(slot.get("weekday")),
        "time_text": time_text,
        "minutes": _time_text_minutes(time_text),
    }


def _slot_date_label(record: Dict[str, Any]) -> str:
    date = _clean_text(record.get("date"))
    weekday = _clean_text(record.get("weekday"))
    try:
        from datetime import datetime

        parsed = datetime.strptime(date[:10], "%Y-%m-%d")
        date_label = parsed.strftime("%b %d").replace(" 0", " ")
    except Exception:
        date_label = date
    return f"{date_label} ({weekday})" if weekday else date_label


def _slot_full_label(slot: Dict[str, Any]) -> str:
    record = _slot_record(slot)
    if not record:
        return ""
    return f"{_slot_date_label(record)} at {record['time_text']}"


def _time_text_minutes(value: str) -> int:
    text = _clean_text(value).upper().replace(".", "")
    match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)", text)
    if not match:
        return 24 * 60
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    suffix = match.group(3)
    if suffix == "PM" and hour != 12:
        hour += 12
    if suffix == "AM" and hour == 12:
        hour = 0
    return hour * 60 + minute


def _slot_presentation_ref(query_basis: Dict[str, Any], slot_groups: Sequence[Dict[str, Any]]) -> str:
    seed = {
        "query_basis": query_basis,
        "groups": [
            {
                "branch_id": group.get("branch_id"),
                "slots": [
                    slot.get("slot_ref")
                    for slot in group.get("slots") or []
                    if isinstance(slot, dict) and slot.get("slot_ref")
                ],
            }
            for group in slot_groups or []
            if isinstance(group, dict)
        ],
    }
    raw = json.dumps(seed, ensure_ascii=True, sort_keys=True, default=str)
    return f"pres_installation_slots_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]}"


def _slot_search_option_candidates(
    *,
    preferred_date: str,
    preferred_date_start: str,
    preferred_date_end: str,
    preferred_time_window: str,
    request_time: str,
    source_schedule_phrase: str,
    preferred_schedule_candidates: Any,
) -> List[Dict[str, Any]]:
    """Build ordered deterministic slot-search options from model candidates and raw schedule context."""

    options: List[Dict[str, Any]] = []
    for index, candidate in enumerate(_normalize_schedule_candidate_inputs(preferred_schedule_candidates)):
        candidate_options = _slot_search_options(
            preferred_date=candidate.get("date") or "",
            preferred_date_start=candidate.get("date_start") or "",
            preferred_date_end=candidate.get("date_end") or "",
            preferred_time_window=candidate.get("time_window") or preferred_time_window,
            request_time=request_time,
        )
        if not _schedule_constrained(candidate_options) and not candidate_options.get("same_day_requested"):
            continue
        candidate_options.update(
            {
                "candidate_index": index,
                "candidate_source": "model_preferred_schedule_candidate",
                "candidate_label": candidate.get("label") or candidate.get("date") or candidate.get("date_start"),
                "candidate_confidence": candidate.get("confidence"),
                "candidate_reason": candidate.get("reason"),
                "source_schedule_phrase": candidate.get("source_phrase") or source_schedule_phrase or None,
            }
        )
        options.append(candidate_options)

    fallback_options = _slot_search_options(
        preferred_date=preferred_date or source_schedule_phrase,
        preferred_date_start=preferred_date_start,
        preferred_date_end=preferred_date_end,
        preferred_time_window=preferred_time_window,
        request_time=request_time,
    )
    fallback_options.update(
        {
            "candidate_index": None,
            "candidate_source": "tool_arg_or_background_signal",
            "candidate_label": preferred_date or preferred_time_window or source_schedule_phrase or None,
            "candidate_confidence": None,
            "candidate_reason": None,
            "source_schedule_phrase": source_schedule_phrase or None,
        }
    )
    if not options or _slot_option_key(fallback_options) not in {_slot_option_key(option) for option in options}:
        options.append(fallback_options)
    return options or [_empty_slot_options()]


def _slot_search_options(
    *,
    preferred_date: str,
    preferred_date_start: str,
    preferred_date_end: str,
    preferred_time_window: str,
    request_time: str,
) -> Dict[str, Any]:
    preferred = preferred_date or preferred_time_window
    options = preferred_date_options(
        preferred,
        request_time=request_time or None,
        preferred_date_start=preferred_date_start or None,
        preferred_date_end=preferred_date_end or None,
    )
    if not options.get("same_day_requested") and _same_day_requested(preferred_date, preferred_time_window, request_time=request_time):
        options["same_day_requested"] = True
        if not options.get("preferred_date"):
            options["preferred_date"] = preferred_date_options("today", request_time=request_time or None).get("preferred_date")
    return options


def _empty_slot_options() -> Dict[str, Any]:
    options = preferred_date_options("")
    options.update(
        {
            "candidate_index": None,
            "candidate_source": "none",
            "candidate_label": None,
            "candidate_confidence": None,
            "candidate_reason": None,
            "source_schedule_phrase": None,
        }
    )
    return options


def _normalize_schedule_candidate_inputs(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list):
        return []
    output: List[Dict[str, str]] = []
    for item in value[:4]:
        if not isinstance(item, dict):
            continue
        date = _valid_date_text(item.get("date") or item.get("preferred_date"))
        date_start = _valid_date_text(item.get("date_start") or item.get("preferred_date_start"))
        date_end = _valid_date_text(item.get("date_end") or item.get("preferred_date_end"))
        time_window = _clean_text(item.get("time_window") or item.get("preferred_time_window"))
        if date:
            date_start = ""
            date_end = ""
        elif date_start and not date_end:
            date_end = date_start
        elif date_end and not date_start:
            date_start = date_end
        if not (date or date_start or time_window):
            continue
        output.append(
            {
                "date": date,
                "date_start": date_start,
                "date_end": date_end,
                "time_window": time_window,
                "confidence": _schedule_candidate_confidence(item.get("confidence")),
                "reason": _clean_text(item.get("reason"))[:180],
                "label": _clean_text(item.get("label") or item.get("source_phrase"))[:80],
                "source_phrase": _clean_text(item.get("source_phrase"))[:80],
            }
        )
    return output


def _compact_schedule_candidate_inputs(value: Any) -> List[Dict[str, str]]:
    return [
        {key: item[key] for key in ("date", "date_start", "date_end", "time_window", "confidence", "reason", "label", "source_phrase") if item.get(key)}
        for item in _normalize_schedule_candidate_inputs(value)
    ]


def _compact_slot_options(options: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in {
            "candidate_index": options.get("candidate_index"),
            "candidate_source": options.get("candidate_source"),
            "candidate_label": options.get("candidate_label"),
            "candidate_confidence": options.get("candidate_confidence"),
            "candidate_reason": options.get("candidate_reason"),
            "source_schedule_phrase": options.get("source_schedule_phrase"),
            "preferred_date": options.get("preferred_date"),
            "preferred_date_start": options.get("preferred_date_start"),
            "preferred_date_end": options.get("preferred_date_end"),
            "preferred_weekday": options.get("preferred_weekday"),
            "prefer_weekend": options.get("prefer_weekend"),
            "same_day_requested": options.get("same_day_requested"),
            "date_search_mode": options.get("date_search_mode"),
        }.items()
        if value not in (None, "", False)
    }


def _slot_option_key(options: Dict[str, Any]) -> tuple[Any, ...]:
    return (
        options.get("preferred_date"),
        options.get("preferred_date_start"),
        options.get("preferred_date_end"),
        options.get("preferred_weekday"),
        bool(options.get("prefer_weekend")),
    )


def _schedule_candidate_sort_index(group: Dict[str, Any]) -> int:
    selected = group.get("selected_schedule_candidate")
    if not isinstance(selected, dict):
        return 999
    index = selected.get("candidate_index")
    if index is None:
        return 998
    try:
        return int(index)
    except Exception:
        return 999


def _valid_date_text(value: Any) -> str:
    text = _clean_text(value)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return ""
    return text


def _schedule_candidate_confidence(value: Any) -> str:
    text = _clean_text(value).lower()
    return text if text in {"high", "medium", "low"} else ""


def _same_day_requested(preferred_date: str, preferred_time_window: str, *, request_time: str) -> bool:
    text = f"{preferred_date} {preferred_time_window}".strip().lower()
    return any(token in text for token in ["today", "same day", "same-day", "ngayon", "asap", "now"])


def _earliest_slot(slots: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not slots:
        return None
    return deepcopy(sorted(slots, key=lambda item: str(item.get("start") or ""))[0])


def _public_location_label(location: Dict[str, Any]) -> str:
    parts = []
    area = _clean_text(location.get("area"))
    province = _clean_text(location.get("province")) or (area if _is_known_province_name(area) else "")
    city = _clean_text(location.get("city")) or (area if area and not _is_known_province_name(area) else "")
    if not city:
        city = _city_label_from_address(_clean_text(location.get("address")), province_hint=province)
    if city:
        parts.append(city)
    if province and province.lower() != city.lower():
        parts.append(province)
    return ", ".join(parts)


def _city_label_from_address(address: str, *, province_hint: str) -> str:
    if not address or not province_hint:
        return ""
    known = _known_public_city_label(address)
    if known:
        return known
    province_match = re.search(re.escape(province_hint), address, flags=re.IGNORECASE)
    if not province_match:
        return ""
    before_province = re.sub(r"\b\d{4}\b", " ", address[: province_match.start()])
    parts = [_clean_text(part) for part in before_province.split(",") if _clean_text(part)]
    if not parts:
        return ""
    candidate = re.sub(r"\b(?:city|municipality|philippines)\b", " ", parts[-1], flags=re.IGNORECASE)
    return _known_public_city_label(candidate) or _clean_text(candidate)


def _known_public_city_label(value: str) -> str:
    key = _normalize_location_lookup_text(value)
    aliases = {
        "bacoor": "Bacoor",
        "batangas city": "Batangas City",
        "binan": "Binan",
        "cabuyao": "Cabuyao",
        "caloocan": "Caloocan City",
        "caloocan city": "Caloocan City",
        "carmona": "Carmona",
        "dasmarinas": "Dasmarinas",
        "dasmarinas city": "Dasmarinas",
        "general trias": "General Trias",
        "imus": "Imus",
        "kawit": "Kawit",
        "las pinas": "Las Pinas",
        "makati": "Makati",
        "muntinlupa": "Muntinlupa",
        "paranaque": "Paranaque City",
        "paranaque city": "Paranaque City",
        "pasay": "Pasay",
        "pasig": "Pasig",
        "quezon city": "Quezon City",
        "san juan city": "San Juan City",
        "silang": "Silang",
        "sta rosa": "Sta. Rosa",
        "santa rosa": "Sta. Rosa",
        "tagaytay": "Tagaytay",
        "taguig": "Taguig",
        "trece martires": "Trece Martires",
    }
    for alias, label in sorted(aliases.items(), key=lambda item: -len(item[0])):
        if f" {alias} " in f" {key} ":
            return label
    return ""


def _normalize_location_lookup_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _clean_text(value)).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _is_known_province_name(value: str) -> bool:
    return _clean_text(value).lower() in {
        "batangas",
        "bohol",
        "bukidnon",
        "bulacan",
        "cavite",
        "cebu",
        "isabela",
        "laguna",
        "metro manila",
        "negros occidental",
        "nueva ecija",
        "pampanga",
        "quezon",
        "rizal",
        "zamboanga del norte",
    }


def _slot_candidates_from_observation(slot_groups: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for group in slot_groups or []:
        if not isinstance(group, dict):
            continue
        partner = {
            "installation_partner_ref": group.get("installation_partner_ref"),
            "service_location_ref": group.get("service_location_ref"),
            "branch_id": group.get("branch_id"),
            "name": group.get("name"),
            "address": group.get("address") or group.get("full_address"),
            "area": group.get("area"),
            "city": group.get("city"),
            "province": group.get("province"),
            "municipality_city": group.get("municipality_city"),
        }
        for slot in group.get("slots") or []:
            if isinstance(slot, dict):
                candidates.append({"partner": partner, "slot": deepcopy(slot)})
    return candidates


def _addon_details_for_location(location: Dict[str, Any]) -> List[Dict[str, Any]]:
    details = location.get("branch_addon_details")
    if isinstance(details, list) and details:
        return [deepcopy(item) for item in details if isinstance(item, dict)]
    addons = location.get("branch_addons")
    values = _list_of_text(addons)
    return [{"service": value, "price": None, "source": location.get("source")} for value in values]


def _filter_addon_details(addons: Sequence[Dict[str, Any]], requested_addons: Sequence[str]) -> List[Dict[str, Any]]:
    if not requested_addons:
        return [deepcopy(addon) for addon in addons if isinstance(addon, dict)]
    requested_terms = set(_tokens(" ".join(requested_addons)))
    if not requested_terms:
        return [deepcopy(addon) for addon in addons if isinstance(addon, dict)]
    matches: List[Dict[str, Any]] = []
    for addon in addons:
        if not isinstance(addon, dict):
            continue
        addon_terms = set(_tokens(addon.get("service") or addon.get("name")))
        if requested_terms.intersection(addon_terms):
            matches.append(deepcopy(addon))
    return matches


def _match_slot_candidate(
    candidates: Sequence[Dict[str, Any]],
    *,
    slot_ref: str,
    slot_ordinal: int,
    partner_ref: str,
    preferred_datetime: str,
    preferred_date: str,
    preferred_time: str,
) -> Dict[str, Any]:
    if not candidates:
        return {}
    scoped = [
        candidate
        for candidate in candidates
        if not partner_ref or _candidate_matches_partner(candidate, partner_ref)
    ]
    if not scoped:
        return {}
    if slot_ref:
        for candidate in scoped:
            if _clean_text(candidate.get("slot", {}).get("slot_ref")) == slot_ref:
                return deepcopy(candidate)
        return {}
    if slot_ordinal:
        index = slot_ordinal - 1
        return deepcopy(scoped[index]) if 0 <= index < len(scoped) else {}
    datetime_key = _normalize_slot_datetime_text(preferred_datetime)
    date_key = _clean_text(preferred_date)
    time_key = _normalize_time_text(preferred_time)
    for candidate in scoped:
        slot = candidate.get("slot") or {}
        if datetime_key and _normalize_slot_datetime_text(slot.get("start")) == datetime_key:
            return deepcopy(candidate)
        if date_key and time_key and date_key == _clean_text(slot.get("date")):
            if time_key in {_normalize_time_text(slot.get("time_text")), _normalize_time_text(slot.get("start"))}:
                return deepcopy(candidate)
    natural_match = _match_natural_slot_selection(scoped, preferred_datetime)
    if natural_match:
        return natural_match
    return {}


def _match_natural_slot_selection(
    candidates: Sequence[Dict[str, Any]],
    selection_text: Any,
) -> Dict[str, Any]:
    """Resolve one natural date/time choice against already visible slot rows."""

    text = _clean_text(selection_text).lower()
    time_key = _normalize_time_text(text)
    if not text or not time_key:
        return {}
    matches: List[Dict[str, Any]] = []
    for candidate in candidates:
        slot = candidate.get("slot") if isinstance(candidate.get("slot"), dict) else {}
        if time_key not in {
            _normalize_time_text(slot.get("time_text")),
            _normalize_time_text(slot.get("start")),
        }:
            continue
        date_text = _clean_text(slot.get("date"))
        if _selection_mentions_a_date(text) and not _selection_matches_slot_date(
            text,
            date_text,
        ):
            continue
        matches.append(candidate)
    return deepcopy(matches[0]) if len(matches) == 1 else {}


def _selection_mentions_a_date(text: str) -> bool:
    return bool(
        re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
        or re.search(
            r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
            r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
            r"nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}\b",
            text,
        )
    )


def _selection_matches_slot_date(text: str, date_text: str) -> bool:
    try:
        slot_date = datetime.strptime(date_text, "%Y-%m-%d")
    except (TypeError, ValueError):
        return False
    labels = {
        date_text.lower(),
        slot_date.strftime("%b %d").lower().replace(" 0", " "),
        slot_date.strftime("%B %d").lower().replace(" 0", " "),
    }
    return any(label in text for label in labels)


def _candidate_matches_partner(candidate: Dict[str, Any], partner_ref: str) -> bool:
    partner = candidate.get("partner") if isinstance(candidate.get("partner"), dict) else {}
    ref = _clean_text(partner_ref)
    return ref in {
        _clean_text(partner.get("installation_partner_ref")),
        _clean_text(partner.get("service_location_ref")),
        _clean_text(partner.get("branch_id")),
    }


def _normalize_slot_datetime_text(value: Any) -> str:
    text = _clean_text(value)
    match = re.search(r"(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})(?::\d{2})?", text)
    if not match:
        return ""
    return f"{match.group(1)} {int(match.group(2)):02d}:{match.group(3)}"


def _normalize_time_text(value: Any) -> str:
    text = _clean_text(value).lower()
    if not text:
        return ""
    match = re.search(r"(\d{1,2}):(\d{2})", text)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"
    match = re.search(r"\b(\d{1,2})\s*(am|pm)\b", text)
    if match:
        hour = int(match.group(1))
        meridiem = match.group(2)
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:00"
    return text


def _unique(values: List[str]) -> List[str]:
    output: List[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            output.append(value)
    return output


def _availability_no_location_note(lookup: Dict[str, Any]) -> str:
    if not isinstance(lookup, dict) or str(lookup.get("status") or "") != "no_match":
        return "Ask for the customer area or installation partner before checking availability."
    return (
        "No installation partner was found for the provided area. Use coverage_assessment "
        "to explain the delivery fallback; do not ask for the same location again."
    )


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def _clean_text(value: Any) -> str:
    import re

    return re.sub(r"\s+", " ", str(value or "").strip())


def _list_of_text(value: Any) -> List[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [_clean_text(value)] if _clean_text(value) else []
    if isinstance(value, Sequence):
        return [_clean_text(item) for item in value if _clean_text(item)]
    return [_clean_text(value)] if _clean_text(value) else []


def _tokens(text: Any) -> List[str]:
    return [token for token in re.findall(r"[a-z0-9]+", _clean_text(text).lower()) if len(token) >= 3]


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _coerce_optional_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None
