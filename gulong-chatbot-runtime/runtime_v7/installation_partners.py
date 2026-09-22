"""Runtime V7 read-only installation partner lookup tool.

This module owns the V7 implementation of `find_installation_partners`. It is
not imported from Runtime V6. It reads the Gulong branch catalog, normalizes
branch rows into compact partner records, and ranks those records for a customer
area or explicit partner name. It never books, reserves, schedules, or confirms
fulfillment.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
import unicodedata
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from runtime.http.sync_http_client import SyncHTTPClient, SyncHTTPClientConfig
from runtime_v7.location_resolution import (
    RuntimeV7LocationResolver,
    compact_location_resolution,
    coordinates_from_branch,
    distance_km,
    location_display_label,
    normalize_location_text,
)
from runtime_v7.location_quality import is_rejected_service_location


DEFAULT_API_BASE_URL = "https://api.gulong.ph/api"
DEFAULT_CATALOG_TTL_SECONDS = 300
METRO_MANILA_PROVINCE_NAME = "Metro Manila"
METRO_MANILA_POINT_PREFERRED_RADIUS_KM = 5.0
METRO_MANILA_POINT_SOFT_RADIUS_KM = 8.0
SERVICE_AREA_POINT_PREFERRED_RADIUS_KM = 15.0
SERVICE_AREA_POINT_SOFT_RADIUS_KM = 20.0
SOURCE_BRANCH_CATALOG = "runtime_v7_gulong_branch_catalog"
PARTNER_DETAIL_AREA_ONLY = "area_only"
PARTNER_DETAIL_AVAILABILITY_SUMMARY = "availability_summary"
PARTNER_DETAIL_NAME_ONLY = "name_only"
PARTNER_DETAIL_FULL_ADDRESS = "full_address"
PARTNER_DETAIL_LEVELS = {
    PARTNER_DETAIL_AREA_ONLY,
    PARTNER_DETAIL_AVAILABILITY_SUMMARY,
    PARTNER_DETAIL_NAME_ONLY,
    PARTNER_DETAIL_FULL_ADDRESS,
}
ORDER_THRESHOLD_CUSTOMER_EXPLANATION_HINTS = [
    "Delivery is the practical option for the current validated order details.",
    "Ask if delivery is okay or ask for the delivery area/address as the next step.",
    "Avoid explaining this as a partner or slot availability issue.",
]
NO_WALK_IN_POLICY_NOTE = (
    "🚫 Paalala po: hindi po walk-in setup ang installation partners. "
    "Fresh stocks po galing warehouse ang tires at dinadala sa installation partner "
    "after reservation/booking, kaya kailangan muna ma-book bago pumunta para "
    "secured ang tires at schedule."
)
DELIVERY_FALLBACK_GUIDANCE = (
    "No installation partner cards are available from this lookup. Offer delivery "
    "as an alternative, wording the coverage status from coverage_assessment."
)
PUBLIC_CITY_LABEL_ALIASES = {
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
    "las pinas city": "Las Pinas",
    "makati": "Makati",
    "muntinlupa": "Muntinlupa",
    "paranaque": "Paranaque City",
    "paranaque city": "Paranaque City",
    "pasay": "Pasay",
    "pasig": "Pasig",
    "quezon city": "Quezon City",
    "san pedro": "San Pedro",
    "san pedro city": "San Pedro",
    "san juan city": "San Juan City",
    "silang": "Silang",
    "sta rosa": "Sta. Rosa",
    "santa rosa": "Sta. Rosa",
    "tagaytay": "Tagaytay",
    "taguig": "Taguig",
    "trece martires": "Trece Martires",
}


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


class FindInstallationPartnersTool:
    """Read-only tool implementation for finding installation partners."""

    def __init__(
        self,
        *,
        http_client: Optional[Any] = None,
        base_url: Optional[str] = None,
        catalog_ttl_seconds: int = DEFAULT_CATALOG_TTL_SECONDS,
        location_resolver: Optional[RuntimeV7LocationResolver] = None,
        geocoder: Optional[Any] = None,
        geocode_api_key: Optional[str] = None,
    ) -> None:
        resolved_base_url = str(base_url or os.getenv("GULONG_API_BASE_URL") or DEFAULT_API_BASE_URL).rstrip("/")
        self._http = http_client or SyncHTTPClient(config=SyncHTTPClientConfig(base_url=resolved_base_url))
        self._catalog_ttl_seconds = max(0, int(catalog_ttl_seconds or DEFAULT_CATALOG_TTL_SECONDS))
        self._catalog_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._location_resolver = location_resolver or RuntimeV7LocationResolver(
            geocoder=geocoder,
            api_key=geocode_api_key,
            http_client=self._http,
            base_url=resolved_base_url,
        )

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Find read-only installation partners for a customer area or branch query."""

        payload = payload or {}
        location_text = _clean_text(
            payload.get("location") or payload.get("area") or payload.get("address") or payload.get("query")
        )
        partner_name = _clean_text(
            payload.get("installation_partner_name") or payload.get("partner_name") or payload.get("branch_name")
        )
        raw_service_type = _clean_text(payload.get("service_type"))
        service_type = normalize_service_type(raw_service_type)
        partner_detail_level = normalize_partner_detail_level(payload.get("partner_detail_level"))
        top_k = _coerce_int(payload.get("top_k"), default=3, minimum=1, maximum=6)
        radius_km = _coerce_float(payload.get("radius_km"), default=65.0, minimum=1.0, maximum=250.0)
        requested_addons = _list_of_text(payload.get("requested_addons") or payload.get("branch_addons"))
        trusted_order_total = _coerce_optional_float(payload.get("trusted_order_total"))
        trusted_order_total_candidates = _list_of_dicts(payload.get("trusted_order_total_candidates"), limit=4)
        raw_model_query = _clean_text(payload.get("model_query") or payload.get("model_or_pattern"))
        raw_tire_brand = _clean_text(payload.get("tire_brand") or payload.get("brand"))
        advisory_model_query, advisory_tire_brand = _service_catalog_model_brand_filters(
            model_query=raw_model_query,
            tire_brand=raw_tire_brand,
        )
        # Branch catalogs do not yet provide a trusted SKU/brand compatibility
        # boundary. Use tire size as the hard filter and keep brand/model as
        # advisory context so selected-product details do not hide serviceable
        # partners.
        size_filters = {
            "section_width": _clean_text(payload.get("section_width")),
            "aspect_ratio": _clean_text(payload.get("aspect_ratio")),
            "rim_size": _clean_text(payload.get("rim_size")),
            "model_query": "",
            "tire_brand": "",
        }
        query_basis = {
            "location": location_text or None,
            "installation_partner_name": partner_name or None,
            "service_type": service_type,
            "customer_requested_walk_in": _walk_in_requested(raw_service_type),
            "service_type_was_defaulted": not bool(raw_service_type),
            "requested_addons": requested_addons,
            "section_width": size_filters["section_width"] or None,
            "aspect_ratio": size_filters["aspect_ratio"] or None,
            "rim_size": size_filters["rim_size"] or None,
            "model_query": size_filters["model_query"] or None,
            "tire_brand": size_filters["tire_brand"] or None,
            "advisory_model_query": advisory_model_query or None,
            "advisory_tire_brand": advisory_tire_brand or None,
            "raw_model_query": raw_model_query or None,
            "trusted_order_total": trusted_order_total,
            "trusted_order_total_source": _clean_text(payload.get("trusted_order_total_source")) or None,
            "trusted_order_total_candidates": trusted_order_total_candidates,
            "partner_detail_level": partner_detail_level,
            "top_k": top_k,
            "radius_km": radius_km,
        }

        if service_type == "delivery" and raw_service_type:
            return self._build_result(
                status="delivery_requested",
                query_basis=query_basis,
                partners=[],
                note=(
                    "The customer is asking for delivery, not installation partner discovery. "
                    "Continue the delivery path and do not render installation partner cards."
                ),
            )

        if not location_text and not partner_name:
            return self._build_result(
                status="needs_location",
                query_basis=query_basis,
                partners=[],
                note="Ask for the customer's area before showing installation partners.",
            )

        if location_text and not partner_name and _is_generic_non_location_text(location_text):
            query_basis["location_input_status"] = "generic_non_location"
            return self._build_result(
                status="needs_location",
                query_basis=query_basis,
                partners=[],
                note=(
                    "The provided location text is a generic business-location phrase, not a customer area. "
                    "Do not claim partner availability from this lookup. When guided service-area choices are available, "
                    "call present_serviceable_location_choices now; otherwise ask for the customer's city/area."
                ),
            )

        catalog_result = self._load_partner_catalog(size_filters=size_filters)
        if catalog_result["status"] != "ok":
            return self._build_result(
                status="tool_error",
                query_basis=query_basis,
                partners=[],
                note="Installation partner catalog is unavailable; ask the customer for location details or retry later.",
                error_type=catalog_result.get("error_type") or "branch_catalog_unavailable",
            )
        partner_catalog_filter = deepcopy(catalog_result.get("partner_catalog_filter") or {})
        if partner_catalog_filter:
            query_basis["partner_catalog_filter"] = partner_catalog_filter

        location_resolution = self._location_resolver.resolve(location_text) if location_text else {}
        query_basis["location_resolution"] = compact_location_resolution(location_resolution)
        query_basis["customer_location_label"] = _customer_location_label(location_text, location_resolution)
        if location_resolution.get("ambiguity_status"):
            return self._build_result(
                status="needs_location",
                query_basis=query_basis,
                partners=[],
                service_area_status="needs_location",
                location_resolution=location_resolution,
                note=(
                    "The customer place name matches multiple city or municipality records. "
                    "Ask which province/location they mean before claiming installation coverage "
                    "or schedule availability."
                ),
            )
        matches = _rank_installation_partners(
            catalog_result["partners"],
            location_text=location_text,
            partner_name=partner_name,
            service_type=service_type,
            requested_addons=requested_addons,
            location_resolution=location_resolution,
            radius_km=radius_km,
        )
        if not matches and _should_fallback_to_text_location_match(
            location_resolution,
            partner_name=partner_name,
            catalog_partners=catalog_result["partners"],
        ):
            fallback_resolution = _text_match_location_resolution(location_resolution)
            fallback_matches = _rank_installation_partners(
                catalog_result["partners"],
                location_text=location_text,
                partner_name=partner_name,
                service_type=service_type,
                requested_addons=requested_addons,
                location_resolution=fallback_resolution,
                radius_km=radius_km,
            )
            if fallback_matches:
                matches = fallback_matches
                location_resolution = fallback_resolution
                query_basis["location_resolution"] = compact_location_resolution(location_resolution)
        matches, order_threshold_assessment = _apply_order_threshold(
            matches,
            trusted_order_total=trusted_order_total,
        )
        partners = [_compact_installation_partner(partner) for partner in matches[:top_k]]
        status = "ok" if partners else "below_order_threshold" if order_threshold_assessment.get("delivery_fallback_relevant") else "no_match"
        service_area_status = _service_area_status(
            status=status,
            location_resolution=location_resolution,
            catalog_partners=catalog_result["partners"],
        )
        return self._build_result(
            status=status,
            query_basis=query_basis,
            partners=partners,
            service_area_status=service_area_status,
            location_resolution=location_resolution,
            order_threshold_assessment=order_threshold_assessment,
            note=_result_note(status),
        )

    def find_nearest(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Compatibility alias for callers that phrase this as nearest lookup."""

        return self.run(payload)

    @property
    def location_resolver(self) -> RuntimeV7LocationResolver:
        """Return the shared location resolver used before partner ranking."""

        return self._location_resolver

    def _build_result(
        self,
        *,
        status: str,
        query_basis: Dict[str, Any],
        partners: Sequence[Dict[str, Any]],
        note: str,
        error_type: str = "",
        service_area_status: str = "",
        location_resolution: Optional[Dict[str, Any]] = None,
        order_threshold_assessment: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        resolution = location_resolution or {}
        threshold_assessment = order_threshold_assessment or {}
        match_source = "geocode" if resolution.get("coordinates") else "text_match"
        service_area = service_area_status or _default_service_area_status(status, partners)
        compact_resolution = compact_location_resolution(resolution) if resolution else {}
        detail_level = normalize_partner_detail_level(query_basis.get("partner_detail_level"))
        customer_location_label = _customer_location_label(query_basis.get("location"), resolution)
        clarification = _coverage_clarification_advice(
            status=status,
            partners=partners,
            compact_resolution=compact_resolution,
            service_area_status=service_area,
        )
        coverage_assessment = {
            "presentable_partner_count": len(partners),
            "clarify_location": status == "needs_location",
            "location_precision": compact_resolution.get("location_precision"),
            "presentation_confidence": clarification["presentation_confidence"],
            "clarification_recommended": clarification["clarification_recommended"],
            "clarification_reason": clarification["clarification_reason"],
            "delivery_fallback_relevant": True if status in {"no_match", "below_order_threshold"} else False,
            "installation_service_area_status": service_area,
            "customer_location_label": customer_location_label,
            "source": SOURCE_BRANCH_CATALOG,
            "match_source": match_source,
            "location_resolution": compact_resolution,
        }
        if threshold_assessment:
            coverage_assessment["order_threshold_assessment"] = deepcopy(threshold_assessment)
        customer_explanation_hints = _customer_explanation_hints(
            status=status,
            coverage_assessment=coverage_assessment,
        )
        if customer_explanation_hints:
            coverage_assessment["customer_explanation_hints"] = list(customer_explanation_hints)
        if query_basis.get("partner_catalog_filter"):
            coverage_assessment["partner_catalog_filter"] = deepcopy(query_basis["partner_catalog_filter"])
        result = {
            "status": status,
            "query_basis": deepcopy(query_basis),
            "installation_partners": deepcopy(list(partners)),
            "service_locations": deepcopy(list(partners)),
            "presentation_ref": _presentation_ref(query_basis, partners) if partners else None,
            "partner_detail_level": detail_level,
            "detail_disclosure": _detail_disclosure(
                detail_level=detail_level,
                partners=partners,
                customer_location_label=customer_location_label,
            ),
            "installation_partner_cards": render_installation_partner_cards(
                partners,
                detail_level=detail_level,
                customer_location_label=customer_location_label,
            ),
            "cta_text": "",
            "service_policy_notes": _service_policy_notes(status),
            "coverage_assessment": coverage_assessment,
            "read_only": True,
            "can_confirm_booking": False,
            "source": SOURCE_BRANCH_CATALOG,
            "generated_at": _utc_now_iso(),
            "ttl_seconds": 900,
            "note": note,
        }
        if customer_explanation_hints:
            result["customer_explanation_hints"] = list(customer_explanation_hints)
        if error_type:
            result["error_type"] = error_type
        return result

    def _load_partner_catalog(self, *, size_filters: Dict[str, str]) -> Dict[str, Any]:
        cache_key = _catalog_cache_key(size_filters)
        cached = self._catalog_cache.get(cache_key)
        now = time.time()
        if cached and cached[0] >= now:
            return deepcopy(cached[1])

        fetched = self._fetch_partner_rows(size_filters=size_filters)
        rows = fetched.get("rows") or []
        partners = [
            normalized
            for row in rows
            for normalized in [_normalize_partner(row, source=SOURCE_BRANCH_CATALOG)]
            if normalized
        ]
        if not partners:
            result = {
                "status": "tool_error",
                "partners": [],
                "error_type": "branch_catalog_empty",
                "source": SOURCE_BRANCH_CATALOG,
                "partner_catalog_filter": fetched.get("partner_catalog_filter"),
            }
        else:
            result = {
                "status": "ok",
                "partners": partners,
                "source": SOURCE_BRANCH_CATALOG,
                "catalog_source_path": fetched.get("source_path"),
                "partner_catalog_filter": fetched.get("partner_catalog_filter"),
            }

        self._catalog_cache[cache_key] = (now + self._catalog_ttl_seconds, deepcopy(result))
        return result

    def _fetch_partner_rows(self, *, size_filters: Dict[str, str]) -> Dict[str, Any]:
        has_api_filters = bool(
            size_filters.get("section_width")
            or size_filters.get("rim_size")
            or size_filters.get("model_query")
        )
        has_catalog_filters = any(_clean_text(value) for value in size_filters.values())
        if has_api_filters:
            filtered_params = {
                "sw": size_filters.get("section_width") or "",
                "ar": size_filters.get("aspect_ratio") or "",
                "rs": size_filters.get("rim_size") or "",
                "pt": size_filters.get("model_query") or "",
            }
            filtered_payload = self._http.get_json("/branch_list_loc", params=filtered_params)
            filtered_rows = _rows_from_payload(filtered_payload)
            if filtered_rows:
                locally_filtered_rows = _filter_partner_rows_by_catalog_fields(filtered_rows, size_filters=size_filters)
                status = "applied"
                if locally_filtered_rows:
                    filtered_rows = locally_filtered_rows
                elif _clean_text(size_filters.get("tire_brand")) or _rows_have_filter_metadata(filtered_rows):
                    status = "relaxed_filtered_endpoint_local_miss"
                return {
                    "rows": filtered_rows,
                    "source_path": "/branch_list_loc",
                    "partner_catalog_filter": _partner_catalog_filter_meta(
                        status=status,
                        size_filters=size_filters,
                        source_path="/branch_list_loc",
                    ),
                }
            for path in ("/branch_list", "/all_branch"):
                payload = self._http.get_json(path, params=None)
                rows = _rows_from_payload(payload)
                if rows:
                    local_filtered_rows = _filter_partner_rows_by_catalog_fields(rows, size_filters=size_filters)
                    if local_filtered_rows:
                        return {
                            "rows": local_filtered_rows,
                            "source_path": path,
                            "partner_catalog_filter": _partner_catalog_filter_meta(
                                status="local_filtered_after_api_empty",
                                size_filters=size_filters,
                                source_path=path,
                                filtered_source_path="/branch_list_loc",
                            ),
                        }
                    return {
                        "rows": rows,
                        "source_path": path,
                        "partner_catalog_filter": _partner_catalog_filter_meta(
                            status="relaxed_no_filtered_rows",
                            size_filters=size_filters,
                            source_path=path,
                            filtered_source_path="/branch_list_loc",
                        ),
                    }
            return {
                "rows": [],
                "source_path": "",
                "partner_catalog_filter": _partner_catalog_filter_meta(
                    status="no_rows",
                    size_filters=size_filters,
                    source_path="",
                    filtered_source_path="/branch_list_loc",
                ),
            }

        for path in ("/all_branch", "/branch_list"):
            payload = self._http.get_json(path, params=None)
            rows = _rows_from_payload(payload)
            if rows:
                if has_catalog_filters:
                    local_filtered_rows = _filter_partner_rows_by_catalog_fields(rows, size_filters=size_filters)
                    if local_filtered_rows:
                        return {
                            "rows": local_filtered_rows,
                            "source_path": path,
                            "partner_catalog_filter": _partner_catalog_filter_meta(
                                status="local_filtered",
                                size_filters=size_filters,
                                source_path=path,
                            ),
                        }
                    return {
                        "rows": rows,
                        "source_path": path,
                        "partner_catalog_filter": _partner_catalog_filter_meta(
                            status="relaxed_no_filtered_rows",
                            size_filters=size_filters,
                            source_path=path,
                        ),
                    }
                return {
                    "rows": rows,
                    "source_path": path,
                    "partner_catalog_filter": _partner_catalog_filter_meta(
                        status="not_requested",
                        size_filters=size_filters,
                        source_path=path,
                    ),
                }
        return {
            "rows": [],
            "source_path": "",
            "partner_catalog_filter": _partner_catalog_filter_meta(
                status="not_requested",
                size_filters=size_filters,
                source_path="",
            ),
        }


def normalize_service_type(value: Any) -> str:
    """Normalize customer service wording into the service type enum."""

    text = _clean_text(value).lower()
    if not text:
        return "installation"
    if "walk" in text:
        return "installation"
    if "deliver" in text:
        return "delivery"
    if "home" in text:
        return "home_service"
    if "pick" in text:
        return "pickup"
    if (
        "install" in text
        or "branch" in text
        or "partner" in text
        or "appointment" in text
        or "schedule" in text
        or "reschedule" in text
    ):
        return "installation"
    return text


def _walk_in_requested(value: Any) -> bool:
    return "walk" in _clean_text(value).lower()


def _service_catalog_model_brand_filters(*, model_query: str, tire_brand: str) -> Tuple[str, str]:
    """Normalize product filters before using them against branch catalogs.

    Service catalogs are usually size/location oriented. A single-token product
    query from the model is often a brand carrier such as "Apollo", not a SKU
    pattern. Treat that as a soft brand filter and avoid over-constraining the
    partner lookup with `pt=<brand>`.
    """

    model = _clean_text(model_query)
    brand = _clean_text(tire_brand)
    if model and not brand and _looks_like_brand_carrier(model):
        return "", model.upper()
    return model, brand


def _looks_like_brand_carrier(value: str) -> bool:
    text = _clean_text(value)
    return bool(text and re.fullmatch(r"[A-Za-z][A-Za-z0-9&.+-]{1,24}", text))


def normalize_partner_detail_level(value: Any, *, default: str = PARTNER_DETAIL_AREA_ONLY) -> str:
    """Normalize how much partner identity can be shown to the customer."""

    fallback = default if default in PARTNER_DETAIL_LEVELS else PARTNER_DETAIL_AREA_ONLY
    text = _clean_text(value).lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    aliases = {
        "area": PARTNER_DETAIL_AREA_ONLY,
        "area_only": PARTNER_DETAIL_AREA_ONLY,
        "availability": PARTNER_DETAIL_AVAILABILITY_SUMMARY,
        "availability_summary": PARTNER_DETAIL_AVAILABILITY_SUMMARY,
        "summary": PARTNER_DETAIL_AVAILABILITY_SUMMARY,
        "name": PARTNER_DETAIL_NAME_ONLY,
        "name_only": PARTNER_DETAIL_NAME_ONLY,
        "branch_name": PARTNER_DETAIL_NAME_ONLY,
        "full": PARTNER_DETAIL_FULL_ADDRESS,
        "full_address": PARTNER_DETAIL_FULL_ADDRESS,
        "address": PARTNER_DETAIL_FULL_ADDRESS,
        "exact": PARTNER_DETAIL_FULL_ADDRESS,
        "exact_address": PARTNER_DETAIL_FULL_ADDRESS,
    }
    return aliases.get(normalized, fallback)


def _result_note(status: str) -> str:
    if status == "no_match":
        return DELIVERY_FALLBACK_GUIDANCE
    if status == "below_order_threshold":
        return (
            "Nearby installation partners were found, but installation is not "
            "available for the current validated order details. Offer delivery "
            "as the practical alternative unless the validated order details change."
        )
    return (
        "Installation partners are read-only discovery context; do not treat them "
        "as confirmed bookings, slots, reservations, or fulfillment actions."
    )


def _detail_disclosure(
    *,
    detail_level: str,
    partners: Sequence[Dict[str, Any]],
    customer_location_label: str,
) -> Dict[str, Any]:
    normalized = normalize_partner_detail_level(detail_level)
    names_revealed = normalized in {PARTNER_DETAIL_NAME_ONLY, PARTNER_DETAIL_FULL_ADDRESS}
    addresses_revealed = normalized == PARTNER_DETAIL_FULL_ADDRESS
    return {
        "partner_detail_level": normalized,
        "customer_location_label": customer_location_label or "",
        "partner_names_revealed": names_revealed,
        "exact_addresses_revealed": addresses_revealed,
        "full_partner_records_available_internally": bool(partners),
        "policy": (
            "Default customer-facing partner discovery is area-only. Exact partner names "
            "or addresses should be shown only in order-summary/proceed context, or when "
            "the customer explicitly asks for branch details and the no-walk-in reservation "
            "policy is included."
        ),
    }


def _service_policy_notes(status: str) -> List[Dict[str, str]]:
    if status != "ok":
        return []
    notes = [
        {
            "id": "no_walkin_setup",
            "source": "runtime_gulong_spiel_bank",
            "text": NO_WALK_IN_POLICY_NOTE,
        }
    ]
    return notes


def _customer_location_label(location_text: Any, resolution: Dict[str, Any]) -> str:
    return location_display_label(location_text, resolution)


def _service_area_status(
    *,
    status: str,
    location_resolution: Dict[str, Any],
    catalog_partners: Sequence[Dict[str, Any]],
) -> str:
    if status != "no_match":
        return _default_service_area_status(status, [])
    resolution = location_resolution or {}
    if (
        resolution.get("requires_point_geocode")
        and not resolution.get("coordinates")
        and _resolution_hint_matches_catalog(resolution, catalog_partners)
    ):
        return "needs_precise_landmark_resolution"
    if resolution.get("city_hint") or resolution.get("province_hint"):
        if not _resolution_hint_matches_catalog(resolution, catalog_partners):
            return "outside_known_installation_service_area"
    return "no_installation_partner_match_for_area"


def _default_service_area_status(status: str, partners: Sequence[Dict[str, Any]]) -> str:
    if status == "needs_location":
        return "needs_location"
    if status == "tool_error":
        return "unknown"
    if status == "below_order_threshold":
        return "below_order_threshold_delivery_recommended"
    if partners or status == "ok":
        return "has_installation_partner_options"
    if status == "no_match":
        return "no_installation_partner_match_for_area"
    return status or "unknown"


def _coverage_clarification_advice(
    *,
    status: str,
    partners: Sequence[Dict[str, Any]],
    compact_resolution: Dict[str, Any],
    service_area_status: str,
) -> Dict[str, Any]:
    """Return neutral presentation diagnostics for the model."""

    precision = str(compact_resolution.get("location_precision") or "").strip()
    if compact_resolution.get("ambiguity_status"):
        return {
            "presentation_confidence": "low",
            "clarification_recommended": True,
            "clarification_reason": "place name matches multiple city or municipality records",
        }
    if status == "needs_location":
        return {
            "presentation_confidence": "low",
            "clarification_recommended": True,
            "clarification_reason": "customer area is missing",
        }
    if service_area_status == "needs_precise_landmark_resolution":
        return {
            "presentation_confidence": "low",
            "clarification_recommended": True,
            "clarification_reason": "landmark needs a more precise resolvable point",
        }
    if precision in {"route", "province", "unknown"}:
        return {
            "presentation_confidence": "low",
            "clarification_recommended": True,
            "clarification_reason": "location is broad; ask for city, exit, barangay, or landmark",
        }
    if precision == "point":
        return {
            "presentation_confidence": "high" if partners else "medium",
            "clarification_recommended": False,
            "clarification_reason": "",
        }
    if precision == "city_or_area":
        return {
            "presentation_confidence": "medium" if partners else "low",
            "clarification_recommended": False if partners else True,
            "clarification_reason": "" if partners else "no nearby partner matched the city or area",
        }
    return {
        "presentation_confidence": "medium" if partners else "low",
        "clarification_recommended": False if partners else status in {"no_match", "needs_location"},
        "clarification_reason": "" if partners else "no partner matched the current lookup",
    }


def _customer_explanation_hints(
    *,
    status: str,
    coverage_assessment: Dict[str, Any],
) -> List[str]:
    """Return model-facing interpretation hints for exceptional service results."""

    location_resolution = coverage_assessment.get("location_resolution")
    location_resolution = location_resolution if isinstance(location_resolution, dict) else {}
    if location_resolution.get("ambiguity_status"):
        options = [
            str(item).strip()
            for item in location_resolution.get("clarification_options") or []
            if str(item).strip()
        ]
        return [
            "The customer's place name has multiple valid city or municipality matches.",
            (
                "Ask which location they mean: " + ", or ".join(options[:3]) + "."
                if options
                else "Ask for the province before checking installation availability."
            ),
            "Do not claim partner or schedule availability until the location is disambiguated.",
        ]
    threshold = coverage_assessment.get("order_threshold_assessment")
    if (
        status == "below_order_threshold"
        and isinstance(threshold, dict)
        and threshold.get("delivery_fallback_relevant") is True
    ):
        return list(ORDER_THRESHOLD_CUSTOMER_EXPLANATION_HINTS)
    return []


def _location_clarification_cta(location_label: Any) -> str:
    label = _clean_text(location_label)
    if label:
        return (
            f"Saan po banda sa {label}? Pwede pong exit, landmark, barangay, "
            "or city para mas malapit yung ma-check natin."
        )
    return "Anong exit, landmark, barangay, or city po para mas malapit yung ma-check natin?"


def _resolution_hint_matches_catalog(
    resolution: Dict[str, Any],
    catalog_partners: Sequence[Dict[str, Any]],
) -> bool:
    city_key = _normalize_lookup_text(resolution.get("city_hint"))
    province_key = _normalize_lookup_text(resolution.get("province_hint"))
    if not city_key and not province_key:
        return False
    for partner in catalog_partners:
        searchable = _normalize_lookup_text(_partner_searchable_text(partner))
        if city_key and _contains_lookup_phrase(searchable, city_key):
            return True
        if province_key and _contains_lookup_phrase(searchable, province_key):
            return True
    return False


def compact_installation_partner(partner: Dict[str, Any]) -> Dict[str, Any]:
    """Return the public compact partner shape."""

    return _compact_installation_partner(partner)


def render_installation_partner_cards(
    partners: Sequence[Dict[str, Any]],
    *,
    detail_level: str = PARTNER_DETAIL_AREA_ONLY,
    customer_location_label: str = "",
) -> List[Dict[str, Any]]:
    """Return deterministic customer-facing installation partner cards.

    Full branch records remain available internally for order validation, but
    public discovery defaults to area-only disclosure to reduce walk-in leakage.
    """

    normalized_detail = normalize_partner_detail_level(detail_level)
    cards: List[Dict[str, Any]] = []
    for partner in partners:
        if not isinstance(partner, dict):
            continue
        name = _clean_text(partner.get("name"))
        place = _municipality_city_label(partner)
        address = _clean_text(partner.get("address"))
        if not name and normalized_detail in {PARTNER_DETAIL_NAME_ONLY, PARTNER_DETAIL_FULL_ADDRESS}:
            continue
        card_index = len(cards) + 1
        public_place = place or _clean_text(customer_location_label)
        base_card = {
            "card_ref": f"partner_card_{card_index}",
            "installation_partner_ref": partner.get("installation_partner_ref"),
            "service_location_ref": partner.get("service_location_ref"),
            "branch_id": partner.get("branch_id"),
            "partner_detail_level": normalized_detail,
            "municipality_city": public_place,
        }
        if normalized_detail in {PARTNER_DETAIL_AREA_ONLY, PARTNER_DETAIL_AVAILABILITY_SUMMARY}:
            label = (
                f"Installation partner option {card_index}"
                if len(partners) > 1
                else "Installation partner option"
            )
            area_text = f"{public_place} area" if public_place else "your area"
            base_card.update(
                {
                    "display_name": label,
                    "card_text": f"🛞 {label} - 📍 {area_text}",
                }
            )
            cards.append(base_card)
            continue
        if normalized_detail == PARTNER_DETAIL_FULL_ADDRESS:
            location_line = address or public_place
            card_text = "\n".join(
                part
                for part in [
                    f"🛞 {name}",
                    f"📍 {location_line}" if location_line else "",
                ]
                if part
            )
            base_card.update({"name": name, "address": address, "card_text": card_text})
            cards.append(base_card)
            continue
        card_text = f"🛞 {name} - 📍 {public_place}" if public_place else f"🛞 {name}"
        base_card.update({"name": name, "card_text": card_text})
        cards.append(base_card)
    return cards


def _apply_order_threshold(
    partners: Sequence[Dict[str, Any]],
    *,
    trusted_order_total: Optional[float],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if trusted_order_total is None:
        return [deepcopy(partner) for partner in partners], {}

    eligible: List[Dict[str, Any]] = []
    below_threshold_count = 0
    threshold_values: List[float] = []
    for partner in partners:
        assessed = deepcopy(partner)
        threshold = _coerce_optional_float(assessed.get("order_value_threshold"))
        if threshold is None:
            assessed["order_threshold_status"] = "not_provided"
            eligible.append(assessed)
            continue
        threshold_values.append(threshold)
        if trusted_order_total >= threshold:
            assessed["order_threshold_status"] = "meets_threshold"
            eligible.append(assessed)
            continue
        below_threshold_count += 1
        assessed["order_threshold_status"] = "below_threshold"
        assessed["order_threshold_gap"] = round(threshold - trusted_order_total, 2)

    assessment = {
        "requested": True,
        "trusted_order_total": round(float(trusted_order_total), 2),
        "source": "trusted_order_total_tool_arg",
        "partner_count_before_threshold": len(partners),
        "eligible_partner_count": len(eligible),
        "below_threshold_partner_count": below_threshold_count,
        "minimum_threshold_seen": min(threshold_values) if threshold_values else None,
        "delivery_fallback_relevant": bool(partners) and not eligible and below_threshold_count > 0,
        "note": (
            "Order threshold was applied only because a trusted_order_total was provided. "
            "Partners without threshold metadata are not blocked by this filter."
        ),
    }
    return eligible, assessment


def _rank_installation_partners(
    partners: Sequence[Dict[str, Any]],
    *,
    location_text: str,
    partner_name: str,
    service_type: str,
    requested_addons: Sequence[str],
    location_resolution: Optional[Dict[str, Any]] = None,
    radius_km: float = 65.0,
) -> List[Dict[str, Any]]:
    resolution = location_resolution or {}
    resolved_coordinates = resolution.get("coordinates") if isinstance(resolution.get("coordinates"), dict) else None
    requires_point_geocode = bool(resolution.get("requires_point_geocode"))
    point_radius_policy = _point_radius_policy(resolution)
    normalized_text = normalize_location_text(location_text)
    city_hint = str(resolution.get("city_hint") or "").strip()
    province_hint = str(resolution.get("province_hint") or "").strip()
    location_terms = set(_meaningful_location_tokens(normalized_text or location_text))
    city_terms = set(_meaningful_location_tokens(city_hint))
    primary_location_terms = location_terms.difference(city_terms) or location_terms
    direct_location_match_exists = bool(primary_location_terms) and any(
        primary_location_terms.issubset(set(_meaningful_location_tokens(_partner_searchable_text(partner))))
        for partner in partners
    )
    partner_terms = set(_tokens(partner_name))
    requested_addon_terms = set(_tokens(" ".join(requested_addons)))
    scored: List[Tuple[float, int, Dict[str, Any]]] = []
    normalized_location = _normalize_lookup_text(normalized_text or location_text)
    normalized_partner = _normalize_lookup_text(partner_name)

    for index, partner in enumerate(partners):
        supported = [str(item).strip().lower() for item in partner.get("service_types") or []]
        if service_type and supported and service_type not in supported:
            continue
        searchable = _partner_searchable_text(partner)
        searchable_terms = set(_meaningful_location_tokens(searchable))
        score = 2 if not service_type or service_type in supported or not supported else 0

        if normalized_partner:
            name_text = _normalize_lookup_text(partner.get("name"))
            name_terms = set(_tokens(partner.get("name")))
            partner_overlap = len(partner_terms.intersection(name_terms))
            if normalized_partner in name_text:
                score += 20
            elif partner_overlap:
                score += 8 + partner_overlap
            else:
                continue

        if resolved_coordinates:
            if not isinstance(partner.get("coordinates"), dict):
                if not normalized_partner:
                    continue
            else:
                branch_distance = distance_km(resolved_coordinates, partner["coordinates"])
                if branch_distance is not None:
                    max_radius = radius_km
                    preferred_radius = None
                    if point_radius_policy:
                        preferred_radius, soft_radius = point_radius_policy
                        max_radius = min(radius_km, soft_radius)
                    if branch_distance > max_radius and not normalized_partner:
                        continue
                    relationship = _location_relationship(
                        partner,
                        city_hint=city_hint,
                        province_hint=province_hint,
                        distance_km=branch_distance,
                        preferred_radius_km=preferred_radius,
                    )
                    partner["distance_km"] = branch_distance
                    partner["location_match_source"] = "geocode"
                    partner["location_relationship"] = relationship["relationship"]
                    partner["location_note"] = relationship["note"]
                    if preferred_radius is not None:
                        partner["preferred_radius_km"] = preferred_radius
                        partner["within_preferred_radius"] = branch_distance <= preferred_radius
                    # Keep distance as the dominant signal when geocoding succeeds.
                    score += max(0.0, 100.0 - branch_distance)
                    if relationship["relationship"].startswith("same_city"):
                        score += 1.5

        if normalized_location and not resolved_coordinates:
            if requires_point_geocode and not direct_location_match_exists and not normalized_partner:
                continue
            exact_fields = [
                _normalize_lookup_text(partner.get("area")),
                _normalize_lookup_text(partner.get("city")),
                _normalize_lookup_text(partner.get("province")),
            ]
            location_overlap = len(location_terms.intersection(searchable_terms))
            city_overlap = len(city_terms.intersection(searchable_terms))
            primary_overlap = len(primary_location_terms.intersection(searchable_terms))
            if normalized_location in exact_fields:
                score += 18
            elif any(field and (field in normalized_location or normalized_location in field) for field in exact_fields):
                score += 12
            elif direct_location_match_exists and primary_location_terms and primary_overlap < len(primary_location_terms):
                if not normalized_partner:
                    continue
            elif location_overlap and (len(location_terms) == 1 or location_overlap >= len(location_terms)):
                score += 4 + location_overlap
            elif city_overlap and (len(city_terms) == 1 or city_overlap >= len(city_terms)):
                score += 3 + city_overlap
            elif not normalized_partner:
                continue
            partner["location_match_source"] = "text_match"

        if requested_addon_terms:
            addon_text = _normalize_lookup_text(" ".join(partner.get("branch_addons") or []))
            addon_overlap = len(requested_addon_terms.intersection(set(_tokens(addon_text))))
            if addon_text:
                score += addon_overlap

        scored.append((score, -index, deepcopy(partner)))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [partner for _score, _index, partner in scored]


def _should_fallback_to_text_location_match(
    resolution: Dict[str, Any],
    *,
    partner_name: str,
    catalog_partners: Sequence[Dict[str, Any]] = (),
) -> bool:
    """Use city/area text matching when geocoding is too sparse for branch rows."""

    if partner_name:
        return False
    if not isinstance(resolution, dict) or not resolution.get("coordinates"):
        return _should_fallback_landmark_to_city_hint(resolution, catalog_partners=catalog_partners)
    if bool(resolution.get("requires_point_geocode")):
        return False
    return str(resolution.get("location_precision") or "").strip() in {"city_or_area", "province_or_region"}


def _text_match_location_resolution(resolution: Dict[str, Any]) -> Dict[str, Any]:
    fallback = deepcopy(resolution or {})
    had_coordinates = bool(fallback.get("coordinates"))
    fallback.pop("coordinates", None)
    if bool(fallback.get("requires_point_geocode")) and not had_coordinates:
        fallback["status"] = "landmark_city_hint_text_match_fallback"
        fallback["requires_point_geocode"] = False
        fallback["location_precision"] = "city_or_area"
        fallback["landmark_city_text_match_fallback"] = True
    else:
        fallback["status"] = "geocoded_text_match_fallback"
    fallback["geocode_text_match_fallback"] = True
    return fallback


def _should_fallback_landmark_to_city_hint(
    resolution: Dict[str, Any],
    *,
    catalog_partners: Sequence[Dict[str, Any]],
) -> bool:
    if not isinstance(resolution, dict):
        return False
    if not bool(resolution.get("requires_point_geocode")):
        return False
    if str(resolution.get("location_precision") or "").strip() != "point":
        return False
    if not str(resolution.get("landmark_hint") or "").strip():
        return False
    return _resolution_city_hint_matches_catalog(resolution, catalog_partners)


def _resolution_city_hint_matches_catalog(
    resolution: Dict[str, Any],
    catalog_partners: Sequence[Dict[str, Any]],
) -> bool:
    city_key = _normalize_lookup_text(resolution.get("city_hint"))
    if not city_key:
        return False
    for partner in catalog_partners or []:
        searchable = _normalize_lookup_text(_partner_searchable_text(partner))
        if _contains_lookup_phrase(searchable, city_key):
            return True
    return False


def _partner_searchable_text(partner: Dict[str, Any]) -> str:
    return " ".join(
        str(partner.get(key) or "")
        for key in ["name", "area", "city", "province", "address", "notes"]
    )


def _point_radius_policy(resolution: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    if resolution.get("location_precision") != "point":
        return None
    if _is_metro_manila_resolution(resolution):
        return METRO_MANILA_POINT_PREFERRED_RADIUS_KM, METRO_MANILA_POINT_SOFT_RADIUS_KM
    return SERVICE_AREA_POINT_PREFERRED_RADIUS_KM, SERVICE_AREA_POINT_SOFT_RADIUS_KM


def _location_relationship(
    partner: Dict[str, Any],
    *,
    city_hint: str,
    province_hint: str,
    distance_km: float,
    preferred_radius_km: Optional[float],
) -> Dict[str, str]:
    same_city = _same_city_partner(partner, city_hint=city_hint)
    place = _partner_place_label(partner)
    outside_preferred = preferred_radius_km is not None and distance_km > preferred_radius_km
    if same_city and outside_preferred:
        return {
            "relationship": "same_city_outside_preferred_radius",
            "note": f"same city as {city_hint}, but outside the preferred {preferred_radius_km:g} km radius",
        }
    if same_city:
        return {
            "relationship": "same_city_nearby",
            "note": f"same city as {city_hint}" if city_hint else "nearby",
        }
    if outside_preferred:
        return {
            "relationship": "cross_city_outside_preferred_radius",
            "note": (
                f"nearby but in {place}, outside the preferred {preferred_radius_km:g} km radius"
                if place
                else f"nearby but outside the preferred {preferred_radius_km:g} km radius"
            ),
        }
    if place:
        return {
            "relationship": "cross_city_nearby" if city_hint or province_hint else "nearby",
            "note": f"nearby but in {place}" if city_hint or province_hint else f"near {place}",
        }
    return {"relationship": "nearby", "note": "nearby"}


def _same_city_partner(partner: Dict[str, Any], *, city_hint: str) -> bool:
    city_key = _normalize_lookup_text(city_hint)
    if not city_key:
        return False
    fields = [
        _normalize_lookup_text(partner.get("city")),
        _normalize_lookup_text(partner.get("area")),
        _normalize_lookup_text(partner.get("address")),
    ]
    return any(field and _contains_lookup_phrase(field, city_key) for field in fields)


def _partner_place_label(partner: Dict[str, Any]) -> str:
    return (
        _clean_text(partner.get("city"))
        or _clean_text(partner.get("area"))
        or _clean_text(partner.get("province"))
        or _clean_text(partner.get("address"))
    )


def _municipality_city_label(partner: Dict[str, Any]) -> str:
    city = _clean_text(partner.get("city"))
    area = _clean_text(partner.get("area"))
    province = _clean_text(partner.get("province"))
    address = _clean_text(partner.get("address"))
    province_hint = province or (area if _is_known_province_name(area) else "")
    place = _known_public_city_label(city) or _known_public_city_label(area)
    if not place and area and not _is_known_province_name(area) and not _looks_like_street_address(area):
        place = area
    if not place:
        place = _city_label_from_address(address, province_hint=province_hint)
    if not place and _looks_like_street_address(area):
        place = _city_label_from_address(f"{area}, {province_hint}", province_hint=province_hint)
    if not place:
        return province_hint or area
    if not province_hint and _is_metro_manila_place(place):
        province_hint = METRO_MANILA_PROVINCE_NAME
    if not province_hint:
        return place
    place_key = _normalize_lookup_text(place)
    province_key = _normalize_lookup_text(province_hint)
    if place_key and province_key and place_key != province_key:
        return f"{place}, {province_hint}"
    return place


def _city_label_from_address(address: str, *, province_hint: str = "") -> str:
    text = _clean_text(address)
    province = _clean_text(province_hint)
    if not text or not province:
        return ""
    province_match = re.search(re.escape(province), text, flags=re.IGNORECASE)
    if not province_match:
        return ""
    before_province = text[: province_match.start()]
    before_province = re.sub(r"\b\d{4}\b", " ", before_province)
    parts = [_clean_text(part) for part in before_province.split(",") if _clean_text(part)]
    if not parts:
        return ""
    candidate = re.sub(r"\b(?:city|municipality|philippines)\b", " ", parts[-1], flags=re.IGNORECASE)
    candidate = _clean_text(candidate)
    known_city = _known_public_city_label(candidate) or _known_public_city_label(before_province)
    if known_city:
        return known_city
    return _canonical_public_city_label(candidate)


def _looks_like_street_address(value: str) -> bool:
    text = _clean_text(value)
    if not text:
        return False
    lowered = text.lower()
    return bool(
        re.search(r"\b(?:blk|block|b\d+|l\d+|lot|street|st\.?|road|rd\.?|brgy|barangay|subd|village)\b", lowered)
        or re.search(r"\b\d{1,5}\b", lowered)
    )


def _canonical_public_city_label(value: str) -> str:
    key = _normalize_lookup_text(value)
    aliases = {
        "sta rosa": "Sta. Rosa",
        "santa rosa": "Sta. Rosa",
        "sta maria": "Sta. Maria",
        "santa maria": "Sta. Maria",
        "binan": "Biñan",
    }
    return aliases.get(key, _clean_text(value))


def _known_public_city_label(value: str) -> str:
    key = _normalize_lookup_text(value)
    for alias, label in sorted(PUBLIC_CITY_LABEL_ALIASES.items(), key=lambda item: -len(item[0])):
        if _contains_lookup_phrase(key, alias):
            return label
    return ""


def _is_known_province_name(value: str) -> bool:
    key = _normalize_lookup_text(value)
    return key in {
        "batangas",
        "bohol",
        "bukidnon",
        "bulacan",
        "cavite",
        "cebu",
        "isabela",
        "laguna",
        "negros occidental",
        "nueva ecija",
        "pampanga",
        "quezon",
        "rizal",
        "zamboanga del norte",
    }


def _is_metro_manila_place(value: str) -> bool:
    key = _normalize_lookup_text(value)
    return key in {
        "caloocan city",
        "las pinas",
        "las pinas city",
        "makati",
        "makati city",
        "malabon",
        "mandaluyong",
        "manila",
        "marikina",
        "muntinlupa",
        "navotas",
        "paranaque",
        "paranaque city",
        "pasay",
        "pasig",
        "quezon city",
        "san juan city",
        "taguig",
        "valenzuela",
    }


def _is_metro_manila_resolution(resolution: Dict[str, Any]) -> bool:
    province_key = _normalize_lookup_text(resolution.get("province_hint"))
    city_key = _normalize_lookup_text(resolution.get("city_hint"))
    metro_cities = {
        "caloocan city",
        "las pinas",
        "makati",
        "malabon",
        "mandaluyong",
        "manila",
        "marikina",
        "muntinlupa",
        "navotas",
        "paranaque city",
        "pasay",
        "pasig",
        "quezon city",
        "san juan city",
        "taguig",
        "valenzuela",
    }
    return province_key in {"metro manila", "ncr"} or city_key in metro_cities


def _contains_lookup_phrase(text_key: str, phrase_key: str) -> bool:
    if not text_key or not phrase_key:
        return False
    return f" {phrase_key} " in f" {text_key} "


def _normalize_partner(row: Dict[str, Any], *, source: str) -> Dict[str, Any]:
    if not isinstance(row, dict) or not _is_active_branch(row):
        return {}

    branch_id = _clean_text(row.get("id") or row.get("branch_id") or row.get("code") or row.get("branch_code"))
    name = _clean_text(row.get("name") or row.get("branch_name") or row.get("display_name"))
    area = _clean_text(row.get("area") or row.get("branch_area") or row.get("city") or row.get("province"))
    city = _clean_text(row.get("city") or row.get("municipality") or row.get("town"))
    province = _clean_text(row.get("province") or row.get("province_name"))
    address = _clean_text(row.get("address") or row.get("complete_address") or row.get("full_address"))
    coordinates = coordinates_from_branch(row)
    if not name and not area and not address:
        return {}

    ref_seed = "|".join([branch_id, name, area, address])
    ref_suffix = branch_id or hashlib.sha1(ref_seed.encode("utf-8")).hexdigest()[:10]
    installation_partner_ref = _clean_text(row.get("installation_partner_ref")) or f"ip_{ref_suffix}"
    service_location_ref = _clean_text(row.get("service_location_ref")) or f"svc_loc_{ref_suffix}"
    service_types = _normalize_service_types(row)
    branch_addons = _extract_branch_addons(row)
    branch_addon_details = _extract_branch_addon_details(row)
    same_day_possible = _coerce_optional_bool(
        row.get("same_day_possible")
        if "same_day_possible" in row
        else row.get("same_day")
        if "same_day" in row
        else row.get("is_same_day")
    )
    lead_day = _coerce_optional_int(row.get("lead_day") or row.get("lead_days"))
    order_value_threshold = _coerce_optional_float(
        row.get("order_value_threshold")
        or row.get("order_threshold")
        or row.get("minimum_order_amount")
        or row.get("min_order_amount")
    )

    partner: Dict[str, Any] = {
        "installation_partner_ref": installation_partner_ref,
        "service_location_ref": service_location_ref,
        "branch_id": branch_id or None,
        "name": name or area or address,
        "area": area or city or province,
        "city": city,
        "province": province,
        "address": address,
        "service_types": service_types,
        "same_day_possible": same_day_possible,
        "lead_day": lead_day,
        "order_value_threshold": order_value_threshold,
        "branch_addons": branch_addons,
        "branch_addon_details": branch_addon_details,
        "coordinates": coordinates,
        "notes": _clean_text(row.get("notes") or row.get("note")),
        "source": source,
    }
    return {key: value for key, value in partner.items() if value not in (None, "", [])}


def _compact_installation_partner(partner: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        "installation_partner_ref",
        "service_location_ref",
        "branch_id",
        "name",
        "area",
        "city",
        "province",
        "address",
        "service_types",
        "same_day_possible",
        "lead_day",
        "order_value_threshold",
        "order_threshold_status",
        "order_threshold_gap",
        "branch_addons",
        "branch_addon_details",
        "distance_km",
        "location_match_source",
        "location_relationship",
        "location_note",
        "preferred_radius_km",
        "within_preferred_radius",
        "notes",
        "source",
    ]
    return {key: deepcopy(partner.get(key)) for key in keys if partner.get(key) not in (None, "", [])}


def _presentation_ref(query_basis: Dict[str, Any], partners: Sequence[Dict[str, Any]]) -> str:
    digest = hashlib.sha1(
        repr(
            {
                "query_basis": query_basis,
                "partners": [
                    {
                        "ref": partner.get("installation_partner_ref") or partner.get("service_location_ref"),
                        "name": partner.get("name"),
                        "place": _municipality_city_label(partner),
                    }
                    for partner in partners
                    if isinstance(partner, dict)
                ],
            }
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"pres_installation_partners_{digest}"


def _rows_from_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    if str(payload.get("status") or "").lower() == "error":
        return []
    for key in ("data", "branches", "branch", "items", "results", "locations"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _filter_partner_rows_by_catalog_fields(
    rows: Sequence[Dict[str, Any]],
    *,
    size_filters: Dict[str, str],
) -> List[Dict[str, Any]]:
    if not _rows_have_filter_metadata(rows):
        return []
    section_width = _clean_text(size_filters.get("section_width")).upper()
    aspect_ratio = _clean_text(size_filters.get("aspect_ratio")).upper()
    rim_size = _clean_text(size_filters.get("rim_size")).upper()
    model_query = _normalize_lookup_text(size_filters.get("model_query"))
    tire_brand = _normalize_lookup_text(size_filters.get("tire_brand"))
    return [
        row
        for row in rows
        if _csv_has(row.get("section_width") or row.get("sw"), section_width)
        and _csv_has(row.get("aspect_ratio") or row.get("ar"), aspect_ratio)
        and _csv_has(row.get("rim_size") or row.get("rs"), rim_size)
        and _pattern_matches(row, model_query)
        and _brand_matches(row, tire_brand)
    ]


def _rows_have_filter_metadata(rows: Sequence[Dict[str, Any]]) -> bool:
    filter_keys = {
        "section_width",
        "sw",
        "aspect_ratio",
        "ar",
        "rim_size",
        "rs",
    }
    return any(any(key in row for key in filter_keys) for row in rows if isinstance(row, dict))


def _csv_has(value: Any, target: str) -> bool:
    if not target:
        return True
    raw = _clean_text(value).upper()
    if not raw:
        return True
    tokens = [token.strip().upper() for token in re.split(r"[,/|]", raw) if token.strip()]
    return target in tokens


def _pattern_matches(row: Dict[str, Any], model_query: str) -> bool:
    if not model_query:
        return True
    pattern_text = _normalize_lookup_text(
        row.get("pattern") or row.get("pt") or row.get("product_pattern") or row.get("model") or ""
    )
    if not pattern_text:
        return True
    return model_query in pattern_text or pattern_text in model_query


def _brand_matches(row: Dict[str, Any], tire_brand: str) -> bool:
    if not tire_brand:
        return True
    raw_brand = (
        row.get("brand")
        or row.get("tire_brand")
        or row.get("product_brand")
        or row.get("make")
        or row.get("brands")
        or row.get("brands_for_order_today")
        or ""
    )
    raw_values = raw_brand if isinstance(raw_brand, Sequence) and not isinstance(raw_brand, str) else [raw_brand]
    brand_terms: List[str] = []
    for raw_value in raw_values:
        brand_text = _normalize_lookup_text(raw_value)
        brand_terms.extend(
            _normalize_lookup_text(part)
            for part in re.split(r"[,/|]", brand_text)
            if _normalize_lookup_text(part)
        )
    if not brand_terms:
        return True
    return any(tire_brand in term or term in tire_brand for term in brand_terms)


def _normalize_service_types(row: Dict[str, Any]) -> List[str]:
    raw = row.get("service_types") or row.get("services") or []
    values: List[str] = []
    if isinstance(raw, str):
        values.extend(part.strip() for part in re.split(r"[,/|]", raw) if part.strip())
    elif isinstance(raw, Sequence):
        values.extend(str(part).strip() for part in raw if str(part or "").strip())
    normalized = [normalize_service_type(value) for value in values if normalize_service_type(value)]
    if not normalized:
        normalized = ["installation", "pickup"]
    return _unique(normalized)


def _extract_branch_addons(row: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    raw = row.get("branch_add_ons") or row.get("branch_addons") or row.get("addons") or []
    if isinstance(raw, str):
        values.extend(part.strip() for part in re.split(r"[,/|]", raw) if part.strip())
    elif isinstance(raw, Sequence):
        for item in raw:
            if isinstance(item, dict):
                for key in ("service", "name", "addon_name", "title"):
                    value = _clean_text(item.get(key))
                    if value:
                        values.append(value)
                        break
            else:
                value = _clean_text(item)
                if value:
                    values.append(value)
    return _unique(values)


def _extract_branch_addon_details(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    details: List[Dict[str, Any]] = []
    raw = row.get("branch_add_ons") or row.get("branch_addons") or row.get("addons") or []
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        return []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = ""
        for key in ("service", "name", "addon_name", "title"):
            name = _clean_text(item.get(key))
            if name:
                break
        if not name:
            continue
        price = item.get("promo_price") if _truthy(item.get("promo_tag")) and item.get("promo_price") not in (None, "") else item.get("price")
        detail = {
            "service": name,
            "price": _coerce_optional_float(price),
            "promo_applied": _truthy(item.get("promo_tag")) if item.get("promo_tag") not in (None, "") else False,
            "source": SOURCE_BRANCH_CATALOG,
        }
        if item.get("id") not in (None, ""):
            detail["id"] = item.get("id")
        details.append({key: value for key, value in detail.items() if value not in (None, "", [])})
    return details


def _is_active_branch(row: Dict[str, Any]) -> bool:
    for key in ("active", "is_active", "enabled", "is_enabled"):
        if key in row:
            return _truthy(row.get(key))
    status = _clean_text(row.get("status") or row.get("branch_status")).lower()
    if status:
        return status not in {"inactive", "disabled", "closed", "0", "false"}
    return True


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = _clean_text(value).lower()
    if text in {"", "0", "false", "no", "n", "inactive", "disabled", "closed"}:
        return False
    return True


def _coerce_optional_bool(value: Any) -> Optional[bool]:
    if value in (None, ""):
        return None
    return _truthy(value)


def _coerce_optional_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _coerce_optional_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _coerce_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _tokens(text: str) -> List[str]:
    folded = unicodedata.normalize("NFKD", _clean_text(text)).encode("ascii", "ignore").decode("ascii")
    return [token for token in re.findall(r"[a-z0-9]+", folded.lower()) if len(token) >= 3]


def _meaningful_location_tokens(text: str) -> List[str]:
    generic = {"city", "metro", "manila", "philippines", "province"}
    return [token for token in _tokens(text) if token not in generic]


def _is_generic_non_location_text(value: Any) -> bool:
    if is_rejected_service_location(value):
        return True
    tokens = set(_tokens(_clean_text(value)))
    if not tokens:
        return False
    generic = {
        "area",
        "areas",
        "available",
        "banda",
        "branch",
        "branches",
        "coverage",
        "covered",
        "installation",
        "location",
        "locations",
        "located",
        "near",
        "nearby",
        "office",
        "partner",
        "partners",
        "service",
        "services",
        "shop",
        "site",
        "sites",
        "store",
        "where",
        "kayo",
        "saan",
        "san",
    }
    return tokens.issubset(generic)


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_lookup_text(value: Any) -> str:
    return " ".join(_tokens(_clean_text(value)))


def _list_of_text(value: Any) -> List[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [_clean_text(value)] if _clean_text(value) else []
    if isinstance(value, Sequence):
        return [_clean_text(item) for item in value if _clean_text(item)]
    return [_clean_text(value)] if _clean_text(value) else []


def _list_of_dicts(value: Any, *, limit: int) -> List[Dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    rows: List[Dict[str, Any]] = []
    for item in value[: max(1, int(limit or 1))]:
        if not isinstance(item, dict):
            continue
        row = {
            key: deepcopy(val)
            for key, val in item.items()
            if key != "product" and val not in (None, "", [], {})
        }
        if row:
            rows.append(row)
    return rows


def _partner_catalog_filter_meta(
    *,
    status: str,
    size_filters: Dict[str, str],
    source_path: str,
    filtered_source_path: str = "",
) -> Dict[str, Any]:
    filters = {
        "section_width": _clean_text(size_filters.get("section_width")) or None,
        "aspect_ratio": _clean_text(size_filters.get("aspect_ratio")) or None,
        "rim_size": _clean_text(size_filters.get("rim_size")) or None,
        "model_query": _clean_text(size_filters.get("model_query")) or None,
        "tire_brand": _clean_text(size_filters.get("tire_brand")) or None,
    }
    requested = any(value for value in filters.values())
    return {
        "requested": requested,
        "status": status,
        "source_path": source_path or None,
        "filtered_source_path": filtered_source_path or None,
        "verified_by_filtered_partner_catalog": status == "applied",
        "compatibility_status": _partner_catalog_compatibility_status(status, requested),
        "filters": filters,
        "note": _partner_catalog_filter_note(status),
    }


def _partner_catalog_compatibility_status(status: str, requested: bool) -> str:
    if not requested:
        return "not_requested"
    if status == "applied":
        return "verified_by_filtered_catalog"
    if status in {"local_filtered", "local_filtered_after_api_empty"}:
        return "locally_filtered_from_catalog_metadata"
    if status in {"relaxed_no_filtered_rows", "relaxed_filtered_endpoint_local_miss"}:
        return "unverified_relaxed"
    return status or "unknown"


def _partner_catalog_filter_note(status: str) -> str:
    if status == "applied":
        return "Partner pool came from the size-aware branch catalog endpoint. Brand/model context is advisory, not a hard partner filter."
    if status == "relaxed_filtered_endpoint_local_miss":
        return "Size-aware branch catalog returned rows, but local size metadata did not verify the requested filters; partner compatibility is not verified."
    if status == "relaxed_no_filtered_rows":
        return "Filtered/local compatibility checks had no matching rows, so the lookup fell back to the broader branch catalog; partner compatibility is not verified."
    if status == "local_filtered":
        return "Partner pool was locally filtered using broad branch catalog tire-size metadata."
    if status == "local_filtered_after_api_empty":
        return "Size-aware branch catalog returned no rows, so the lookup applied local tire-size fields from the broader branch catalog."
    if status == "no_rows":
        return "No partner rows were available from either filtered or broad branch catalogs."
    return "No tire size/model/brand partner filter was requested."


def _unique(values: Sequence[str]) -> List[str]:
    output: List[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            output.append(text)
    return output


def _catalog_cache_key(size_filters: Dict[str, str]) -> str:
    return "|".join(
        [
            _clean_text(size_filters.get("section_width")),
            _clean_text(size_filters.get("aspect_ratio")),
            _clean_text(size_filters.get("rim_size")),
            _clean_text(size_filters.get("model_query")),
            _clean_text(size_filters.get("tire_brand")),
        ]
    )
