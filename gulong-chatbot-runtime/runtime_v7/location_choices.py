"""Source-backed serviceable location choices for Runtime V7.

The live branch catalog is the authority for whether a location is shown. The
PSGC-style province and city catalogs provide stable labels and codes. Branch
addresses are used only to assign an active provincial branch to a city within
its already-authoritative province; ambiguous rows are omitted rather than
guessed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence, Tuple

from runtime.http.sync_http_client import SyncHTTPClient, SyncHTTPClientConfig


DEFAULT_API_BASE_URL = "https://api.gulong.ph/api"
DEFAULT_CACHE_TTL_SECONDS = 300
METRO_MANILA_CODE = "PH-00"
OTHER_CHOICE_CODE = "other"
ROOT_PARENT_CODE = "root"
SOURCE_NAME = "gulong_api_serviceable_location_catalog"
# Current catalog and customer-facing spellings can differ after a municipality
# rename. Keep these as data normalization aliases, not serviceability rules.
CANONICAL_CITY_ALIASES = {
    "baliuag": {"baliwag"},
}


class ServiceableLocationChoicesProvider:
    """Build a two-level location hierarchy from current active branch data."""

    def __init__(
        self,
        *,
        http_client: Optional[Any] = None,
        base_url: Optional[str] = None,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        resolved_base = str(
            base_url or os.getenv("GULONG_API_BASE_URL") or DEFAULT_API_BASE_URL
        ).rstrip("/")
        self._http = http_client or SyncHTTPClient(
            config=SyncHTTPClientConfig(base_url=resolved_base)
        )
        self._cache_ttl_seconds = max(0, int(cache_ttl_seconds))
        self._cache: Optional[Tuple[float, Dict[str, Any]]] = None

    def province_surface(self, *, turn_id: str) -> Dict[str, Any]:
        """Return serviceable province choices plus a typed-location fallback."""

        catalog = self._load_catalog()
        if catalog.get("status") != "ok":
            return {}
        choices = [deepcopy(item) for item in catalog.get("provinces") or []]
        choices.append(
            {
                "choice_ref": "location:province:other",
                "code": OTHER_CHOICE_CODE,
                "label": "Others",
                "partner_count": 0,
                "serviceability_status": "typed_location_required",
            }
        )
        return self._surface(
            level="province",
            parent_code=ROOT_PARENT_CODE,
            parent_label="",
            choices=choices,
            source_version=str(catalog.get("source_version") or ""),
            turn_id=turn_id,
            diagnostics=catalog.get("diagnostics") or {},
        )

    def city_surface(self, *, province_code: str, turn_id: str) -> Dict[str, Any]:
        """Return only cities backed by an active branch in one province."""

        catalog = self._load_catalog()
        province = next(
            (
                item
                for item in catalog.get("provinces") or []
                if str(item.get("code") or "") == str(province_code or "")
            ),
            None,
        )
        if not province:
            return {}
        choices = [
            deepcopy(item)
            for item in (catalog.get("cities_by_province") or {}).get(province_code, [])
        ]
        if not choices:
            return {}
        return self._surface(
            level="city",
            parent_code=province_code,
            parent_label=str(province.get("label") or ""),
            choices=choices,
            source_version=str(catalog.get("source_version") or ""),
            turn_id=turn_id,
            diagnostics=catalog.get("diagnostics") or {},
        )

    def city_surface_for_province_label(
        self,
        *,
        province_label: str,
        turn_id: str,
    ) -> Dict[str, Any]:
        """Resolve an exact serviceable province label to its city surface."""

        label_key = _normalize(province_label)
        if not label_key:
            return {}
        catalog = self._load_catalog()
        province = next(
            (
                item
                for item in catalog.get("provinces") or []
                if _normalize(item.get("label")) == label_key
            ),
            None,
        )
        if not province:
            return {}
        return self.city_surface(
            province_code=str(province.get("code") or ""),
            turn_id=turn_id,
        )

    def _surface(
        self,
        *,
        level: str,
        parent_code: str,
        parent_label: str,
        choices: Sequence[Dict[str, Any]],
        source_version: str,
        turn_id: str,
        diagnostics: Dict[str, Any],
    ) -> Dict[str, Any]:
        identity = "|".join([source_version, str(turn_id or ""), level, parent_code])
        presentation_ref = "loc_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        return {
            "presentation_ref": presentation_ref,
            "surface_type": f"serviceable_{level}_choices",
            "choice_type": f"serviceable_{level}",
            "level": level,
            "parent_code": parent_code,
            "parent_label": parent_label,
            "choices": [dict(item) for item in choices],
            "source": SOURCE_NAME,
            "source_paths": ["/branch_list_loc", "/get_province", "/get_city"],
            "source_version": source_version,
            "freshness_ttl_seconds": self._cache_ttl_seconds,
            "diagnostics": dict(diagnostics),
            "renderer_variant": "manychat_serviceable_location_cards_v1",
        }

    def _load_catalog(self) -> Dict[str, Any]:
        now = time.time()
        if self._cache and self._cache[0] >= now:
            return deepcopy(self._cache[1])
        branches = _rows(self._http.get_json("/branch_list_loc", params=None))
        provinces = _rows(self._http.get_json("/get_province", params=None))
        cities = _rows(self._http.get_json("/get_city", params=None))
        result = _build_catalog(branches=branches, provinces=provinces, cities=cities)
        self._cache = (now + self._cache_ttl_seconds, deepcopy(result))
        return result


def _build_catalog(
    *,
    branches: Sequence[Dict[str, Any]],
    provinces: Sequence[Dict[str, Any]],
    cities: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    province_by_code: Dict[str, Dict[str, str]] = {}
    province_by_name: Dict[str, Dict[str, str]] = {}
    for row in provinces:
        code = _clean(row.get("PROV_CODE"))
        label = _display(row.get("PROV_NAME"))
        if not code or not label:
            continue
        item = {"code": code, "label": label}
        province_by_code[code] = item
        province_by_name[_normalize(label)] = item

    cities_by_province_code: Dict[str, List[Dict[str, str]]] = {}
    city_by_area: Dict[str, Dict[str, str]] = {}
    for row in cities:
        code = _clean(row.get("CITY_CODE"))
        label = _display(row.get("CITY_NAME"))
        province_code = _clean(row.get("PROV_CODE"))
        province = province_by_code.get(province_code)
        if not code or not label or not province:
            continue
        item = {
            "code": code,
            "label": label,
            "province_code": province_code,
            "province_label": province["label"],
        }
        cities_by_province_code.setdefault(province_code, []).append(item)
        if province_code == METRO_MANILA_CODE:
            city_by_area[_location_key(label)] = item

    counts: Dict[Tuple[str, str], int] = {}
    unresolved: List[str] = []
    for branch in branches:
        area_key = _location_key(branch.get("area"))
        metro_city = city_by_area.get(area_key)
        if metro_city:
            key = (metro_city["province_code"], metro_city["code"])
            counts[key] = counts.get(key, 0) + 1
            continue
        province = province_by_name.get(_normalize(branch.get("area")))
        if not province:
            unresolved.append(_clean(branch.get("id")) or _clean(branch.get("name")))
            continue
        city = _resolve_branch_city(
            branch,
            province=province,
            candidates=cities_by_province_code.get(province["code"], []),
        )
        if not city:
            unresolved.append(_clean(branch.get("id")) or _clean(branch.get("name")))
            continue
        key = (province["code"], city["code"])
        counts[key] = counts.get(key, 0) + 1

    serviceable_cities: Dict[str, List[Dict[str, Any]]] = {}
    province_counts: Dict[str, int] = {}
    city_lookup = {
        (item["province_code"], item["code"]): item
        for values in cities_by_province_code.values()
        for item in values
    }
    for key, count in counts.items():
        city = city_lookup[key]
        province_code = key[0]
        serviceable_cities.setdefault(province_code, []).append(
            {
                "choice_ref": f"location:city:{city['code']}",
                "code": city["code"],
                "label": _friendly_label(city["label"]),
                "province_code": province_code,
                "province_label": _friendly_label(city["province_label"]),
                "partner_count": count,
                "serviceability_status": "serviceable",
            }
        )
        province_counts[province_code] = province_counts.get(province_code, 0) + count
    for values in serviceable_cities.values():
        values.sort(key=lambda item: (-int(item["partner_count"]), str(item["label"])))

    serviceable_provinces: List[Dict[str, Any]] = []
    for province_code, count in province_counts.items():
        province = province_by_code[province_code]
        serviceable_provinces.append(
            {
                "choice_ref": f"location:province:{province_code}",
                "code": province_code,
                "label": _friendly_label(province["label"]),
                "partner_count": count,
                "serviceability_status": "serviceable",
            }
        )
    serviceable_provinces.sort(
        key=lambda item: (
            0 if item["code"] == METRO_MANILA_CODE else 1,
            -int(item["partner_count"]),
            str(item["label"]),
        )
    )
    source_rows = [
        {
            "id": _clean(row.get("id")),
            "area": _clean(row.get("area")),
            "address": _clean(row.get("address")),
            "lat": _clean(row.get("lat")),
            "lng": _clean(row.get("lng")),
        }
        for row in branches
    ]
    source_version = hashlib.sha256(
        json.dumps(source_rows, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "status": "ok" if serviceable_provinces else "empty",
        "provinces": serviceable_provinces,
        "cities_by_province": serviceable_cities,
        "source_version": source_version,
        "diagnostics": {
            "branch_count": len(branches),
            "mapped_branch_count": sum(counts.values()),
            "unresolved_branch_count": len(unresolved),
            "unresolved_branch_refs": unresolved[:20],
        },
    }


def _resolve_branch_city(
    branch: Dict[str, Any],
    *,
    province: Dict[str, str],
    candidates: Sequence[Dict[str, str]],
) -> Optional[Dict[str, str]]:
    address = _normalize(branch.get("address"))
    name = _normalize(branch.get("name"))
    province_key = _location_key(province.get("label"))
    scored: List[Tuple[int, int, Dict[str, str]]] = []
    for candidate in candidates:
        label_key = _location_key(candidate.get("label"))
        aliases = _city_aliases(candidate.get("label"))
        best_score = -1
        best_position = -1
        for alias in aliases:
            if not alias:
                continue
            position = _phrase_position(name, alias)
            if position >= 0:
                if label_key == province_key and not _explicit_city_phrase(name, alias):
                    position = -1
            if position >= 0:
                best_score = max(best_score, 200 + len(alias))
                best_position = max(best_position, position)
            position = _phrase_position(address, alias)
            if position < 0:
                continue
            if label_key == province_key and not _explicit_city_phrase(address, alias):
                continue
            if _looks_like_road_name(address, alias, position):
                continue
            score = 100 + len(alias)
            if position > best_position or score > best_score:
                best_score = score
                best_position = position
        if best_score >= 0:
            scored.append((best_score, best_position, candidate))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if len(scored) > 1 and scored[0][:2] == scored[1][:2]:
        return None
    return scored[0][2]


def _city_aliases(value: Any) -> List[str]:
    text = _normalize(value)
    base = re.sub(r"\bcity\b", " ", text)
    base = " ".join(base.split())
    aliases = {text, base}
    parenthetical = re.findall(r"\(([^)]+)\)", _clean(value))
    aliases.update(_normalize(item) for item in parenthetical)
    aliases.add(re.sub(r"\bsanta\b", "sta", base))
    aliases.add(re.sub(r"\bsanto\b", "sto", base))
    aliases.update(CANONICAL_CITY_ALIASES.get(base, set()))
    return sorted((item for item in aliases if item), key=len, reverse=True)


def _phrase_position(text: str, phrase: str) -> int:
    match = re.search(rf"(?:^|\s){re.escape(phrase)}(?:\s|$)", text)
    return match.start() if match else -1


def _explicit_city_phrase(text: str, alias: str) -> bool:
    return bool(
        re.search(
            rf"(?:\bcity\s+of\s+{re.escape(alias)}\b|\b{re.escape(alias)}\s+city\b)",
            text,
        )
    )


def _looks_like_road_name(text: str, alias: str, position: int) -> bool:
    tail = text[position + len(alias) + 1 :].lstrip()
    return bool(re.match(r"(?:highway|road|rd|street|st|avenue|ave)\b", tail))


def _rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "result", "content", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _clean(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _location_key(value: Any) -> str:
    text = re.sub(r"\bcity\b", " ", _normalize(value))
    return " ".join(text.split())


def _display(value: Any) -> str:
    return _clean(value).title()


def _friendly_label(value: Any) -> str:
    label = _display(value)
    replacements = {
        "Metro Manila": "Metro Manila",
        "Las Pinas City": "Las Piñas",
        "Paranaque City": "Parañaque",
    }
    return replacements.get(label, label)
