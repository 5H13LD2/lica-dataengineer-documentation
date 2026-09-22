"""Runtime V7 customer location resolution helpers.

This module keeps location normalization and geocoding separate from service
tool dispatch. It is intentionally small: expand common customer shorthand,
build better geocode queries, and return coordinates when a configured geocoder
can resolve the location.
"""

from __future__ import annotations

import math
import os
import re
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests


DEFAULT_GEOCODE_TTL_SECONDS = 300
DEFAULT_GEOCODE_RETRY_ATTEMPTS = 2
DEFAULT_GEOCODE_RETRY_BACKOFF_SECONDS = 0.15
DEFAULT_GULONG_API_BASE_URL = "https://api.gulong.ph/api"
DEFAULT_LOCATION_GAZETTEER_TTL_SECONDS = 300
METRO_MANILA_PROVINCE_NAME = "Metro Manila"
GOOGLE_GEOCODE_RETRY_STATUSES = {"REQUEST_DENIED", "UNKNOWN_ERROR", "OVER_QUERY_LIMIT", "RESOURCE_EXHAUSTED"}
LANDMARK_HINTS = {
    "sm north edsa": {
        "label": "SM City North EDSA",
        "query": "SM City North EDSA, Quezon City",
        "city": "Quezon City",
        "province": "Metro Manila",
        "precision": "point",
    },
    "sm north": {
        "label": "SM City North EDSA",
        "query": "SM City North EDSA, Quezon City",
        "city": "Quezon City",
        "province": "Metro Manila",
        "precision": "point",
    },
    "trinoma": {
        "label": "TriNoma",
        "query": "TriNoma, Quezon City",
        "city": "Quezon City",
        "province": "Metro Manila",
        "precision": "point",
    },
    "sm fairview": {
        "label": "SM City Fairview",
        "query": "SM City Fairview, Quezon City",
        "city": "Quezon City",
        "province": "Metro Manila",
        "precision": "point",
    },
    "university of the philippines diliman": {
        "label": "University of the Philippines Diliman",
        "query": "University of the Philippines Diliman, Quezon City",
        "city": "Quezon City",
        "province": "Metro Manila",
        "precision": "point",
    },
    "up diliman": {
        "label": "University of the Philippines Diliman",
        "query": "University of the Philippines Diliman, Quezon City",
        "city": "Quezon City",
        "province": "Metro Manila",
        "precision": "point",
    },
    "mall of asia": {
        "label": "SM Mall of Asia",
        "query": "SM Mall of Asia, Pasay",
        "city": "Pasay",
        "province": "Metro Manila",
        "precision": "point",
    },
    "sm megamall": {
        "label": "SM Megamall",
        "query": "SM Megamall, Mandaluyong",
        "city": "Mandaluyong",
        "province": "Metro Manila",
        "precision": "point",
    },
    "slex": {
        "label": "SLEX",
        "query": "South Luzon Expressway, Muntinlupa",
        "city": "Muntinlupa",
        "province": "Metro Manila",
        "precision": "route",
    },
}
METRO_MANILA_HINTS = {
    "cubao": "Quezon City",
    "gilmore": "Quezon City",
    "katipunan": "Quezon City",
    "san juan": "San Juan City",
    "greenhills": "San Juan City",
    "sm north": "Quezon City",
    "sm north edsa": "Quezon City",
    "university of the philippines diliman": "Quezon City",
    "up diliman": "Quezon City",
    "mall of asia": "Pasay",
    "moa": "Pasay",
    "sm megamall": "Mandaluyong",
    "megamall": "Mandaluyong",
    "trinoma": "Quezon City",
    "sm fairview": "Quezon City",
    "ortigas": "Pasig",
    "slex": "Muntinlupa",
    "makati": "Makati",
    "bgc": "Taguig",
    "bonifacio global city": "Taguig",
    "alabang": "Muntinlupa",
}
LOCATION_TEXT_ALIASES = {
    "gen tri": "general trias",
    "gentri": "general trias",
    "sjdm": "san jose del monte city",
    "pque": "paranaque city",
    "mla": "manila",
    "sta rosa": "santa rosa",
    "sta. rosa": "santa rosa",
    "bukdinon": "bukidnon",
    "upd": "university of the philippines diliman",
    "u.p.d.": "university of the philippines diliman",
    "up diliman": "university of the philippines diliman",
    "moa": "mall of asia",
    "megamall": "sm megamall",
}
PREFERRED_CITY_PROVINCE_HINTS = {
    "santa rosa": ("Santa Rosa City", "Laguna"),
}


class RuntimeV7LocationGazetteer:
    """Cached Gulong city/province catalog used for location hints."""

    def __init__(
        self,
        *,
        http_client: Optional[Any] = None,
        base_url: Optional[str] = None,
        cache_ttl_seconds: int = DEFAULT_LOCATION_GAZETTEER_TTL_SECONDS,
    ) -> None:
        self._http = http_client
        self._base_url = str(base_url or os.getenv("GULONG_API_BASE_URL") or DEFAULT_GULONG_API_BASE_URL).rstrip("/")
        self._cache_ttl_seconds = max(0, int(cache_ttl_seconds or DEFAULT_LOCATION_GAZETTEER_TTL_SECONDS))
        self._catalog_cache: Optional[Tuple[float, Dict[str, Any]]] = None

    def resolve(
        self,
        normalized_location: str,
        *,
        preferred_city_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return catalog-backed city/province candidates for a customer area."""

        text = normalize_location_text(normalized_location)
        if not text:
            return {
                "status": "empty",
                "city_candidates": [],
                "selected_city_candidate": None,
                "province_matches": [],
                "province_hint": None,
            }

        catalog = self._load_catalog()
        if catalog.get("status") != "ok":
            return {
                "status": catalog.get("status") or "unavailable",
                "city_candidates": [],
                "selected_city_candidate": None,
                "province_matches": [],
                "province_hint": None,
            }

        province_matches = _match_provinces(text, catalog.get("provinces") or [])
        province_matches = _remove_city_shadowed_province_matches(
            province_matches,
            text=text,
            preferred_city_hint=preferred_city_hint,
        )
        candidates = _match_city_candidates(text, catalog.get("cities") or [], province_matches=province_matches)
        explicit_nonmetro_province = any(
            not _is_metro_manila_name(match.get("province_name")) for match in province_matches
        )

        if preferred_city_hint and not explicit_nonmetro_province:
            hinted = _candidate_for_city_hint(preferred_city_hint, catalog.get("cities") or [])
            if hinted:
                hinted = deepcopy(hinted)
                hinted["score"] = max(float(hinted.get("score") or 0), 120.0)
                hinted["match_type"] = "landmark_city_hint"
                candidates.insert(0, hinted)

        candidates = _dedupe_candidates(candidates)
        ambiguous_candidates = _ambiguous_city_candidates(
            candidates,
            province_matches=province_matches,
        )
        selected = (
            None
            if ambiguous_candidates
            else _select_city_candidate(candidates, province_matches=province_matches)
        )
        province_hint = (
            selected.get("province_name")
            if selected
            else _select_province_hint(province_matches)
        )
        return {
            "status": "ok",
            "city_candidates": candidates[:5],
            "selected_city_candidate": selected,
            "ambiguous_city_candidates": ambiguous_candidates,
            "province_matches": province_matches[:5],
            "province_hint": province_hint,
        }

    def _load_catalog(self) -> Dict[str, Any]:
        now = time.time()
        if self._catalog_cache and self._catalog_cache[0] >= now:
            return deepcopy(self._catalog_cache[1])

        province_rows = _rows_from_payload(self._get_json("/get_province"))
        city_rows = _rows_from_payload(self._get_json("/get_city"))
        provinces_by_code: Dict[str, Dict[str, Any]] = {}
        for row in province_rows:
            code = _clean_text(row.get("PROV_CODE") or row.get("prov_code") or row.get("province_code"))
            name = _format_location_name(row.get("PROV_NAME") or row.get("prov_name") or row.get("province_name"))
            if not code or not name:
                continue
            provinces_by_code[code] = {
                "prov_code": code,
                "province_name": name,
                "region_code": _clean_text(row.get("REGION_CODE") or row.get("region_code")),
            }

        cities: List[Dict[str, Any]] = []
        for row in city_rows:
            prov_code = _clean_text(row.get("PROV_CODE") or row.get("prov_code") or row.get("province_code"))
            province = provinces_by_code.get(prov_code, {})
            name = _format_location_name(row.get("CITY_NAME") or row.get("city_name") or row.get("name"))
            if not name:
                continue
            cities.append(
                {
                    "city_code": _clean_text(row.get("CITY_CODE") or row.get("city_code")),
                    "city_name": name,
                    "prov_code": prov_code,
                    "province_name": province.get("province_name") or "",
                    "region_code": province.get("region_code") or "",
                }
            )

        provinces = list(provinces_by_code.values())
        status = "ok" if provinces and cities else "unavailable"
        result = {"status": status, "provinces": provinces, "cities": cities}
        self._catalog_cache = (now + self._cache_ttl_seconds, deepcopy(result))
        return result

    def _get_json(self, path: str) -> Any:
        if self._http is not None:
            try:
                return self._http.get_json(path, params=None)
            except TypeError:
                return self._http.get_json(path)
            except Exception:
                return {"status": "Error", "content": "location catalog request failed"}
        try:
            response = requests.get(f"{self._base_url}/{path.lstrip('/')}", timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception:
            return {"status": "Error", "content": "location catalog request failed"}


class RuntimeV7LocationResolver:
    """Normalize customer location text and geocode it when possible."""

    def __init__(
        self,
        *,
        geocoder: Optional[Any] = None,
        api_key: Optional[str] = None,
        gazetteer: Optional[RuntimeV7LocationGazetteer] = None,
        http_client: Optional[Any] = None,
        base_url: Optional[str] = None,
        cache_ttl_seconds: int = DEFAULT_GEOCODE_TTL_SECONDS,
        geocode_retry_attempts: Optional[int] = None,
        geocode_retry_backoff_s: Optional[float] = None,
    ) -> None:
        self._geocoder = geocoder
        self._api_key = api_key if api_key is not None else os.getenv("GMAPS_API_KEY")
        self._geocode_retry_attempts = max(
            0,
            _coerce_int(
                geocode_retry_attempts
                if geocode_retry_attempts is not None
                else os.getenv("RUNTIME_V7_GEOCODE_RETRY_ATTEMPTS"),
                default=DEFAULT_GEOCODE_RETRY_ATTEMPTS,
            ),
        )
        self._geocode_retry_backoff_s = max(
            0.0,
            _coerce_float(
                geocode_retry_backoff_s
                if geocode_retry_backoff_s is not None
                else os.getenv("RUNTIME_V7_GEOCODE_RETRY_BACKOFF_S"),
                default=DEFAULT_GEOCODE_RETRY_BACKOFF_SECONDS,
            ),
        )
        self._gazetteer = gazetteer or RuntimeV7LocationGazetteer(
            http_client=http_client,
            base_url=base_url,
            cache_ttl_seconds=cache_ttl_seconds,
        )
        self._cache_ttl_seconds = max(0, int(cache_ttl_seconds or DEFAULT_GEOCODE_TTL_SECONDS))
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    def resolve(self, location_text: str, *, allow_geocode: bool = True) -> Dict[str, Any]:
        """Return normalized location text, hints, geocode queries, and coords."""

        raw = _clean_text(location_text)
        normalized = normalize_location_text(raw)
        if not normalized:
            return {
                "status": "empty",
                "raw": raw,
                "normalized": "",
                "geocode_queries": [],
                "coordinates": None,
                "city_hint": None,
                "province_hint": None,
                "landmark_hint": None,
                "location_precision": None,
                "requires_point_geocode": False,
                "gazetteer_status": "empty",
                "geocode_attempts": 0,
                "geocode_last_status": None,
                "geocode_last_error": None,
                "provider": "none",
            }
        cache_key = f"{normalized}|geocode={1 if allow_geocode else 0}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        landmark_hint = infer_landmark_hint(normalized)
        static_city_hint = landmark_hint.get("city") if landmark_hint else infer_city_hint(normalized)
        gazetteer_resolution = self._gazetteer.resolve(normalized, preferred_city_hint=static_city_hint)
        selected_candidate = gazetteer_resolution.get("selected_city_candidate")
        ambiguous_candidates = gazetteer_resolution.get("ambiguous_city_candidates") or []
        clarification_options = _city_candidate_labels(ambiguous_candidates)
        city_hint = (
            selected_candidate.get("city_name")
            if isinstance(selected_candidate, dict) and selected_candidate.get("city_name")
            else static_city_hint
        )
        province_hint = gazetteer_resolution.get("province_hint")
        if not province_hint and landmark_hint.get("province"):
            province_hint = landmark_hint.get("province")
        if city_hint and not province_hint and _looks_like_metro_manila(normalized, city_hint=city_hint):
            province_hint = METRO_MANILA_PROVINCE_NAME
        geocode_queries = [] if ambiguous_candidates else build_geocode_queries(
            normalized,
            city_hint=city_hint,
            province_hint=province_hint,
            landmark_query=landmark_hint.get("query"),
        )
        coordinates = None
        provider = "none"
        status = "not_geocoded"
        geocode_attempts = 0
        geocode_last_status = None
        geocode_last_error = None
        if ambiguous_candidates:
            status = "ambiguous_city"
        elif allow_geocode:
            for query in geocode_queries:
                provider, coordinates, geocode_meta = self._geocode(query)
                geocode_attempts += int(geocode_meta.get("attempts") or 0)
                geocode_last_status = geocode_meta.get("status") or geocode_last_status
                geocode_last_error = geocode_meta.get("error") or geocode_last_error
                if coordinates:
                    status = "geocoded"
                    break
                if provider == "none":
                    status = "not_configured"

        result = {
            "status": status,
            "raw": raw,
            "normalized": normalized,
            "geocode_queries": geocode_queries,
            "coordinates": coordinates,
            "city_hint": city_hint,
            "province_hint": province_hint,
            "landmark_hint": landmark_hint.get("label") or None,
            "location_precision": (
                "ambiguous_city"
                if ambiguous_candidates
                else landmark_hint.get("precision")
                or (
                    "city_or_area"
                    if city_hint
                    else ("province_only" if province_hint else None)
                )
            ),
            "requires_point_geocode": landmark_hint.get("precision") == "point",
            "gazetteer_status": gazetteer_resolution.get("status"),
            "city_candidates": gazetteer_resolution.get("city_candidates") or [],
            "selected_city_candidate": selected_candidate,
            "ambiguity_status": "ambiguous_city" if ambiguous_candidates else None,
            "ambiguity_reason": (
                "place name matches multiple city or municipality records"
                if ambiguous_candidates
                else None
            ),
            "clarification_options": clarification_options,
            "province_matches": gazetteer_resolution.get("province_matches") or [],
            "geocode_attempts": geocode_attempts,
            "geocode_last_status": geocode_last_status,
            "geocode_last_error": geocode_last_error,
            "provider": provider,
        }
        self._cache[cache_key] = (time.time() + self._cache_ttl_seconds, deepcopy(result))
        return result

    def _geocode(self, query: str) -> Tuple[str, Optional[Dict[str, float]], Dict[str, Any]]:
        if self._geocoder is not None:
            try:
                payload = self._geocoder.geocode(query)
            except Exception:
                return "custom", None, {"attempts": 1, "status": "custom_error", "error": "custom_geocoder_error"}
            coordinates = coordinates_from_payload(payload)
            return "custom", coordinates, {"attempts": 1, "status": "OK" if coordinates else "ZERO_RESULTS"}
        if not self._api_key:
            return "none", None, {"attempts": 0, "status": "not_configured"}
        params = {
            "address": query,
            "key": self._api_key,
            "region": "ph",
            "components": "country:PH",
        }
        total_attempts = 1 + self._geocode_retry_attempts
        last_status = ""
        last_error = ""
        last_attempt = 0
        for attempt in range(1, total_attempts + 1):
            last_attempt = attempt
            try:
                response = requests.get(
                    "https://maps.googleapis.com/maps/api/geocode/json",
                    params=params,
                    timeout=5,
                )
                if response.status_code != 200:
                    last_status = f"http_{response.status_code}"
                    last_error = _clean_text(getattr(response, "text", ""))
                    if not _should_retry_geocode_status(last_status, attempt=attempt, total_attempts=total_attempts):
                        break
                    self._sleep_before_geocode_retry(attempt)
                    continue
                payload = response.json()
            except requests.Timeout:
                last_status = "timeout"
                last_error = "Request timed out"
                if not _should_retry_geocode_status(last_status, attempt=attempt, total_attempts=total_attempts):
                    break
                self._sleep_before_geocode_retry(attempt)
                continue
            except Exception as exc:
                last_status = "request_error"
                last_error = f"{exc.__class__.__name__}: {exc}"
                if not _should_retry_geocode_status(last_status, attempt=attempt, total_attempts=total_attempts):
                    break
                self._sleep_before_geocode_retry(attempt)
                continue

            coordinates = coordinates_from_payload(payload)
            last_status = _clean_text(payload.get("status")) or ("OK" if coordinates else "unknown")
            last_error = _clean_text(payload.get("error_message"))
            if coordinates:
                return "google_maps", coordinates, {"attempts": attempt, "status": last_status, "error": last_error}
            if not _should_retry_geocode_status(last_status, attempt=attempt, total_attempts=total_attempts):
                break
            self._sleep_before_geocode_retry(attempt)
        return "google_maps", None, {"attempts": last_attempt, "status": last_status, "error": last_error}

    def _sleep_before_geocode_retry(self, attempt: int) -> None:
        if self._geocode_retry_backoff_s <= 0:
            return
        time.sleep(self._geocode_retry_backoff_s * attempt)

    def _get_cached(self, key: str) -> Optional[Dict[str, Any]]:
        entry = self._cache.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if expires_at < time.time():
            self._cache.pop(key, None)
            return None
        return deepcopy(value)


def normalize_location_text(value: Any) -> str:
    """Normalize common customer shorthand without pretending to know exact intent."""

    text = _clean_text(value).lower()
    if not text:
        return ""
    text = re.sub(r"\bq\s*\.?\s*c\.?\b", "quezon city", text)
    text = re.sub(r"\bncr\b", "metro manila", text)
    text = re.sub(r"\bmetro\s+mla\b", "metro manila", text)
    text = re.sub(r"\bsj\b", "san juan", text)
    for alias, canonical in sorted(LOCATION_TEXT_ALIASES.items(), key=lambda item: -len(item[0])):
        text = _replace_location_alias(text, alias=alias, canonical=canonical)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _replace_location_alias(text: str, *, alias: str, canonical: str) -> str:
    """Replace an alias unless the current phrase already includes its canonical prefix."""

    alias_text = str(alias or "").strip()
    canonical_text = str(canonical or "").strip()
    if not alias_text or not canonical_text:
        return text
    leading_canonical = ""
    if canonical_text != alias_text and canonical_text.endswith(alias_text):
        leading_canonical = canonical_text[: -len(alias_text)].strip()
    pattern = re.compile(rf"\b{re.escape(alias_text)}\b")

    def replace(match: re.Match[str]) -> str:
        if leading_canonical:
            prefix = text[: match.start()].rstrip()
            if prefix.endswith(leading_canonical):
                return match.group(0)
        return canonical_text

    return pattern.sub(replace, text)


def infer_city_hint(normalized_location: str) -> Optional[str]:
    """Infer a city/municipality hint from known customer shorthand or landmarks."""

    text = normalize_location_text(normalized_location)
    if not text:
        return None
    landmark_hint = infer_landmark_hint(text)
    if landmark_hint.get("city"):
        return landmark_hint["city"]
    if "quezon city" in text:
        return "Quezon City"
    preferred = PREFERRED_CITY_PROVINCE_HINTS.get(text)
    if preferred:
        return preferred[0]
    for phrase, city in sorted(METRO_MANILA_HINTS.items(), key=lambda item: -len(item[0])):
        if phrase in text:
            return city
    return None


def infer_landmark_hint(normalized_location: str) -> Dict[str, str]:
    """Return a point/route landmark hint from normalized customer text."""

    text = normalize_location_text(normalized_location)
    if not text:
        return {}
    for phrase, hint in sorted(LANDMARK_HINTS.items(), key=lambda item: -len(item[0])):
        if phrase in text:
            payload = dict(hint)
            payload["phrase"] = phrase
            return payload
    return {}


def build_geocode_queries(
    normalized_location: str,
    *,
    city_hint: Optional[str],
    province_hint: Optional[str] = None,
    landmark_query: Optional[str] = None,
) -> List[str]:
    """Build bounded geocode queries, most specific first."""

    text = _clean_text(normalized_location)
    if not text:
        return []
    queries: List[str] = []
    text_lower = text.lower()
    city_lower = str(city_hint or "").lower()
    province_lower = str(province_hint or "").lower()
    province_tail = province_hint
    if not province_tail and _looks_like_metro_manila(text, city_hint=city_hint):
        province_tail = METRO_MANILA_PROVINCE_NAME
    if landmark_query:
        query = _clean_text(landmark_query)
        query_lower = query.lower()
        if province_tail and province_tail.lower() not in query_lower:
            query = f"{query}, {province_tail}"
        if "philippines" not in query.lower():
            query = f"{query}, Philippines"
        queries.append(query)
    if city_hint and city_lower not in text_lower:
        if province_tail:
            queries.append(f"{text}, {city_hint}, {province_tail}, Philippines")
        else:
            queries.append(f"{text}, {city_hint}, Philippines")
    elif province_hint and province_lower not in text_lower:
        queries.append(f"{text}, {province_hint}, Philippines")
    if "philippines" not in text.lower():
        if "metro manila" not in text.lower() and _looks_like_metro_manila(text, city_hint=city_hint):
            queries.append(f"{text}, Metro Manila, Philippines")
        queries.append(f"{text}, Philippines")
    else:
        queries.append(text)
    return _unique(queries)


def coordinates_from_payload(payload: Any) -> Optional[Dict[str, float]]:
    """Extract coordinates from common geocoder payload shapes."""

    if not payload:
        return None
    if isinstance(payload, tuple) and len(payload) == 2:
        return _coords(payload[0], payload[1])
    if not isinstance(payload, dict):
        return None
    direct = _coords(payload.get("lat") or payload.get("latitude"), payload.get("lng") or payload.get("longitude"))
    if direct:
        return direct
    coordinates = payload.get("coordinates")
    if isinstance(coordinates, dict):
        direct = _coords(
            coordinates.get("lat") or coordinates.get("latitude"),
            coordinates.get("lng") or coordinates.get("longitude"),
        )
        if direct:
            return direct
    try:
        location = payload["results"][0]["geometry"]["location"]
        return _coords(location.get("lat"), location.get("lng"))
    except Exception:
        return None


def coordinates_from_branch(row: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Extract branch coordinates from Gulong branch catalog rows."""

    return _coords(
        row.get("lat") or row.get("latitude"),
        row.get("lng") or row.get("longitude"),
    )


def distance_km(a: Dict[str, float], b: Dict[str, float]) -> Optional[float]:
    """Return haversine distance in kilometers for two coordinate dicts."""

    try:
        lat1 = math.radians(float(a["lat"]))
        lon1 = math.radians(float(a["lng"]))
        lat2 = math.radians(float(b["lat"]))
        lon2 = math.radians(float(b["lng"]))
    except Exception:
        return None
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return round(6371.0 * 2 * math.atan2(math.sqrt(hav), math.sqrt(1 - hav)), 2)


def compact_location_resolution(resolution: Dict[str, Any]) -> Dict[str, Any]:
    """Return prompt/tool-output safe location resolution metadata."""

    return {
        "status": resolution.get("status"),
        "normalized": resolution.get("normalized"),
        "city_hint": resolution.get("city_hint"),
        "province_hint": resolution.get("province_hint"),
        "landmark_hint": resolution.get("landmark_hint"),
        "location_precision": resolution.get("location_precision"),
        "requires_point_geocode": resolution.get("requires_point_geocode"),
        "provider": resolution.get("provider"),
        "coordinates_available": bool(resolution.get("coordinates")),
        "geocode_query_count": len(resolution.get("geocode_queries") or []),
        "geocode_attempts": resolution.get("geocode_attempts"),
        "geocode_last_status": resolution.get("geocode_last_status"),
        "gazetteer_status": resolution.get("gazetteer_status"),
        "city_candidate_count": len(resolution.get("city_candidates") or []),
        "candidate_match": (
            resolution.get("selected_city_candidate", {}).get("match_type")
            if isinstance(resolution.get("selected_city_candidate"), dict)
            else None
        ),
        "ambiguity_status": resolution.get("ambiguity_status"),
        "ambiguity_reason": resolution.get("ambiguity_reason"),
        "clarification_options": list(resolution.get("clarification_options") or [])[:5],
    }


def location_display_label(location_text: Any, resolution: Dict[str, Any]) -> str:
    """Return a compact customer-facing label from resolved location metadata."""

    resolution = resolution or {}
    landmark = _clean_text(resolution.get("landmark_hint"))
    city = _clean_text(resolution.get("city_hint"))
    province = _clean_text(resolution.get("province_hint"))
    normalized = _clean_text(resolution.get("normalized"))
    if landmark and city and province and _normalize_lookup_text(province) not in _normalize_lookup_text(landmark):
        return f"{landmark}, {city}, {province}"
    if landmark and city:
        return f"{landmark}, {city}"
    if landmark:
        return landmark
    area = _area_label_from_normalized(normalized, city=city, province=province)
    if area and city and province:
        return f"{area}, {city}, {province}"
    if area and city:
        return f"{area}, {city}"
    if area:
        return area
    if city and province and _normalize_lookup_text(city) != _normalize_lookup_text(province):
        return f"{city}, {province}"
    if city:
        return city
    if province:
        return province
    return _display_location_from_normalized(normalized) or _clean_text(location_text)


def _area_label_from_normalized(value: str, *, city: str, province: str) -> str:
    key = _normalize_lookup_text(value)
    city_key = _normalize_lookup_text(city)
    province_key = _normalize_lookup_text(province)
    aliases = {
        "cubao": "Cubao",
        "gilmore": "Gilmore",
        "gilmore quezon city": "Gilmore",
        "katipunan": "Katipunan",
        "greenhills": "Greenhills",
        "ortigas": "Ortigas",
        "bgc": "BGC",
        "bonifacio global city": "BGC",
        "alabang": "Alabang",
    }
    area = aliases.get(key)
    if not area:
        return ""
    area_key = _normalize_lookup_text(area)
    if area_key and area_key not in {city_key, province_key}:
        return area
    return ""


def _display_location_from_normalized(value: str) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    aliases = {
        "bukidnon": "Bukidnon",
        "paranaque city": "Paranaque City",
        "manila": "Manila",
        "santa rosa": "Santa Rosa",
        "san jose del monte city": "San Jose del Monte City",
        "panglao": "Panglao",
        "isabela": "Isabela",
        "quezon city": "Quezon City",
        "san juan": "San Juan",
        "san juan city": "San Juan City",
    }
    return aliases.get(_normalize_lookup_text(text)) or _format_location_name(text)


def _looks_like_metro_manila(text: str, *, city_hint: Optional[str]) -> bool:
    if city_hint:
        if city_hint in {
            "Makati",
            "Mandaluyong",
            "Manila",
            "Muntinlupa",
            "Paranaque City",
            "Pasay",
            "Pasig",
            "Pateros",
            "Quezon City",
            "San Juan City",
            "Taguig",
        }:
            return True
    return any(phrase in text.lower() for phrase in METRO_MANILA_HINTS)


def _match_provinces(text: str, provinces: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    text_key = _normalize_lookup_text(text)
    matches: List[Dict[str, Any]] = []
    for province in provinces:
        province_name = _clean_text(province.get("province_name"))
        province_key = _normalize_lookup_text(province_name)
        if not province_key:
            continue
        aliases = [province_key]
        if _is_metro_manila_name(province_name):
            aliases.append("ncr")
        best_score = 0.0
        match_type = ""
        for alias in aliases:
            if alias == text_key:
                best_score = max(best_score, 100.0)
                match_type = "exact_province"
            elif _contains_lookup_phrase(text_key, alias):
                best_score = max(best_score, 82.0)
                match_type = "province_in_text"
        if best_score:
            item = deepcopy(province)
            item["score"] = best_score
            item["match_type"] = match_type
            matches.append(item)
    matches.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("province_name") or "")))
    return matches


def _should_retry_geocode_status(status: str, *, attempt: int, total_attempts: int) -> bool:
    if attempt >= total_attempts:
        return False
    cleaned = _clean_text(status).upper()
    if cleaned in GOOGLE_GEOCODE_RETRY_STATUSES:
        return True
    if cleaned in {"TIMEOUT", "REQUEST_ERROR"}:
        return True
    if cleaned.startswith("HTTP_"):
        try:
            code = int(cleaned.split("_", 1)[1])
        except Exception:
            return False
        return code == 429 or code >= 500
    return False


def _remove_city_shadowed_province_matches(
    province_matches: Sequence[Dict[str, Any]],
    *,
    text: str,
    preferred_city_hint: Optional[str],
) -> List[Dict[str, Any]]:
    if not preferred_city_hint:
        return list(province_matches)
    text_key = _normalize_lookup_text(text)
    hint_key = _normalize_lookup_text(preferred_city_hint)
    if not _contains_lookup_phrase(text_key, hint_key):
        return list(province_matches)
    filtered: List[Dict[str, Any]] = []
    for match in province_matches:
        province_key = _normalize_lookup_text(match.get("province_name"))
        explicit_province_phrase = _contains_lookup_phrase(
            text_key,
            f"{province_key} province",
        ) or _contains_lookup_phrase(text_key, f"province {province_key}")
        if (
            province_key
            and _contains_lookup_phrase(hint_key, province_key)
            and not explicit_province_phrase
        ):
            continue
        filtered.append(deepcopy(match))
    return filtered


def _match_city_candidates(
    text: str,
    cities: Sequence[Dict[str, Any]],
    *,
    province_matches: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    text_key = _normalize_lookup_text(text)
    province_keys = {_normalize_lookup_text(item.get("province_name")) for item in province_matches}
    candidates: List[Dict[str, Any]] = []
    for city in cities:
        city_name = _clean_text(city.get("city_name"))
        province_name = _clean_text(city.get("province_name"))
        province_key = _normalize_lookup_text(province_name)
        best_score = 0.0
        match_type = ""
        for alias, alias_type in _city_aliases(city_name):
            alias_key = _normalize_lookup_text(alias)
            if not alias_key:
                continue
            score = 0.0
            current_type = ""
            if alias_key == text_key:
                score = 100.0
                current_type = "exact_city"
            elif _contains_lookup_phrase(_text_without_province_phrases(text_key, province_keys), alias_key):
                score = 80.0
                current_type = "city_in_text"
            if not score:
                continue
            if alias_type == "without_city" and province_key and alias_key == province_key:
                score -= 35.0
                current_type = "province_city_name_overlap"
            if province_key and province_key in province_keys:
                score += 35.0
                current_type = f"{current_type}_with_province"
            elif _is_metro_manila_name(province_name) and not province_matches:
                score += 15.0
            if score > best_score:
                best_score = score
                match_type = current_type
        if best_score:
            item = deepcopy(city)
            item["score"] = best_score
            item["match_type"] = match_type
            candidates.append(item)
    candidates.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("city_name") or "")))
    return candidates


def _text_without_province_phrases(text_key: str, province_keys: Sequence[str]) -> str:
    stripped = f" {text_key} "
    for province_key in province_keys:
        province_key = _normalize_lookup_text(province_key)
        if not province_key:
            continue
        stripped = re.sub(rf"\s{re.escape(province_key)}\s", " ", stripped)
    return " ".join(stripped.split())


def _candidate_for_city_hint(city_hint: str, cities: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    hint_key = _normalize_lookup_text(city_hint)
    preferred_province = _preferred_province_for_city_hint(city_hint)
    for city in cities:
        if _normalize_lookup_text(city.get("city_name")) != hint_key:
            continue
        if preferred_province and _normalize_lookup_text(city.get("province_name")) != preferred_province:
            continue
        item = deepcopy(city)
        item["score"] = 120.0
        item["match_type"] = "landmark_city_hint"
        return item
    for city in cities:
        if _normalize_lookup_text(city.get("city_name")) == hint_key:
            item = deepcopy(city)
            item["score"] = 120.0
            item["match_type"] = "landmark_city_hint"
            return item
    if city_hint:
        province_name = METRO_MANILA_PROVINCE_NAME if _looks_like_metro_manila(city_hint, city_hint=city_hint) else ""
        return {
            "city_code": "",
            "city_name": _format_location_name(city_hint),
            "prov_code": "",
            "province_name": province_name,
            "region_code": "NCR" if province_name else "",
            "score": 110.0,
            "match_type": "landmark_city_hint",
        }
    return None


def _select_city_candidate(
    candidates: Sequence[Dict[str, Any]],
    *,
    province_matches: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None
    top = candidates[0]
    explicit_province = bool(province_matches)
    if explicit_province and str(top.get("match_type") or "").startswith(
        "province_city_name_overlap"
    ):
        return None
    exact_province_keys = {
        _normalize_lookup_text(item.get("province_name"))
        for item in province_matches
        if item.get("match_type") == "exact_province"
    }
    top_province_key = _normalize_lookup_text(top.get("province_name"))
    if exact_province_keys and top_province_key not in exact_province_keys:
        return None
    return deepcopy(top)


def _ambiguous_city_candidates(
    candidates: Sequence[Dict[str, Any]],
    *,
    province_matches: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return equally plausible duplicate place names that need a province.

    The national city catalog legitimately contains municipalities with the
    same name in different provinces.  Catalog order must never decide an
    exact service or schedule location when the customer did not provide a
    province.  Explicit province text or an established preferred-city alias
    still resolves normally.
    """

    if province_matches or len(candidates) < 2:
        return []
    top = candidates[0]
    top_score = float(top.get("score") or 0)
    top_city_key = _base_city_key(top.get("city_name"))
    if not top_city_key:
        return []
    plausible = [
        deepcopy(candidate)
        for candidate in candidates
        if _base_city_key(candidate.get("city_name")) == top_city_key
        and top_score - float(candidate.get("score") or 0) <= 10.0
    ]
    province_keys = {
        _normalize_lookup_text(candidate.get("province_name"))
        for candidate in plausible
        if _normalize_lookup_text(candidate.get("province_name"))
    }
    return plausible[:5] if len(province_keys) > 1 else []


def _base_city_key(value: Any) -> str:
    key = _normalize_lookup_text(value)
    key = re.sub(r"^city of\s+", "", key).strip()
    key = re.sub(r"\s+city$", "", key).strip()
    return key


def _city_candidate_labels(candidates: Sequence[Dict[str, Any]]) -> List[str]:
    labels: List[str] = []
    for candidate in candidates:
        city = _clean_text(candidate.get("city_name"))
        province = _clean_text(candidate.get("province_name"))
        label = ", ".join(part for part in (city, province) if part)
        if label and label not in labels:
            labels.append(label)
    return labels[:5]


def _select_province_hint(province_matches: Sequence[Dict[str, Any]]) -> Optional[str]:
    if not province_matches:
        return None
    return _clean_text(province_matches[0].get("province_name")) or None


def _dedupe_candidates(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    best_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for candidate in candidates:
        key = (
            _normalize_lookup_text(candidate.get("city_name")),
            _normalize_lookup_text(candidate.get("province_name")),
        )
        if not key[0]:
            continue
        current = best_by_key.get(key)
        if not current or float(candidate.get("score") or 0) > float(current.get("score") or 0):
            best_by_key[key] = deepcopy(candidate)
    output = list(best_by_key.values())
    output.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("city_name") or "")))
    return output


def _city_aliases(city_name: str) -> List[Tuple[str, str]]:
    name = _clean_text(city_name)
    aliases: List[Tuple[str, str]] = []
    if name:
        aliases.append((name, "full"))
    without_city = re.sub(r"\s+city$", "", name, flags=re.IGNORECASE).strip()
    if without_city and without_city.lower() != name.lower():
        aliases.append((without_city, "without_city"))
    city_of = re.sub(r"^city\s+of\s+", "", name, flags=re.IGNORECASE).strip()
    if city_of and city_of.lower() != name.lower():
        aliases.append((city_of, "without_city"))
    return aliases


def _rows_from_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    if str(payload.get("status") or "").lower() == "error":
        return []
    for key in ("data", "items", "results", "cities", "provinces"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _contains_lookup_phrase(text_key: str, phrase_key: str) -> bool:
    if not text_key or not phrase_key:
        return False
    return f" {phrase_key} " in f" {text_key} "


def _normalize_lookup_text(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", _clean_text(value).lower()))


def _is_metro_manila_name(value: Any) -> bool:
    return _normalize_lookup_text(value) in {"metro manila", "ncr"}


def _format_location_name(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if text.upper() == "NCR":
        return "NCR"
    preserved = {"NCR", "BGC"}
    return " ".join(part if part.upper() in preserved else part.capitalize() for part in text.split())


def _preferred_province_for_city_hint(city_hint: str) -> str:
    hint_key = _normalize_lookup_text(city_hint)
    for city, province in PREFERRED_CITY_PROVINCE_HINTS.values():
        if _normalize_lookup_text(city) == hint_key:
            return _normalize_lookup_text(province)
    return ""


def _coords(lat: Any, lng: Any) -> Optional[Dict[str, float]]:
    if lat in (None, "") or lng in (None, ""):
        return None
    try:
        return {"lat": float(lat), "lng": float(lng)}
    except Exception:
        return None


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _coerce_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


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
