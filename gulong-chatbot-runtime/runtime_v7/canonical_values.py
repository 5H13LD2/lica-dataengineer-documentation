"""Runtime V7 canonical value provider for Gulong API-backed metadata.

The provider owns the endpoint paths used by Runtime V7 and loads each metadata
family lazily. Callers should use local deterministic aliases for cheap
detection, then use this provider whenever a collected value needs
catalog-backed canonicalization.
"""

from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence

from runtime.http.sync_http_client import SyncHTTPClient, SyncHTTPClientConfig


DEFAULT_API_BASE_URL = "https://api.gulong.ph/api"

DEFAULT_BRAND_EXAMPLES = [
    "YOKOHAMA",
    "MICHELIN",
    "BRIDGESTONE",
    "GOODYEAR",
    "APOLLO",
    "DURATURN",
    "ATLAS",
]
DEFAULT_TIRE_CATEGORY_EXAMPLES = ["Budget", "Economy", "Mid Range", "Premium"]
DEFAULT_LOCATION_EXAMPLES = ["Quezon City", "Cubao", "Makati", "Carmona", "Bulacan"]
DEFAULT_PAYMENT_METHOD_EXAMPLES = [
    "gcash",
    "credit card",
    "credit card installment",
    "installment",
    "cash",
]
DEFAULT_BRANCH_ADDON_EXAMPLES = ["Wheel Alignment", "Wheel Balancing", "Nitrogen"]


class CanonicalValuesProvider(Protocol):
    """Lazy source of API-backed canonical values used by V7 normalizers."""

    def brands(self) -> Sequence[str]:
        """Return canonical tire brand names."""

        ...

    def tire_categories(self) -> Sequence[str]:
        """Return canonical tire category names."""

        ...

    def payment_methods(self) -> Sequence[str]:
        """Return canonical payment method labels."""

        ...

    def transaction_types(self) -> Sequence[str]:
        """Return canonical checkout transaction types."""

        ...

    def checkout_metadata(self) -> Dict[str, Any]:
        """Return checkout metadata for payment/order normalization."""

        ...

    def locations(self) -> Sequence[str]:
        """Return canonical province/city/location labels."""

        ...

    def branch_names(self) -> Sequence[str]:
        """Return canonical installation partner or branch names."""

        ...

    def branch_addon_names(self) -> Sequence[str]:
        """Return canonical branch add-on service names."""

        ...

    def product_by_id(self, product_id: Any) -> Dict[str, Any]:
        """Return the raw product catalog row for order payload construction."""

        ...

    def branch_by_id(self, branch_id: Any) -> Dict[str, Any]:
        """Return the raw installation branch row for order payload construction."""

        ...

    def prompt_examples(self) -> Dict[str, Sequence[str]]:
        """Return compact canonical examples for model prompts."""

        ...


@dataclass
class _CacheEntry:
    """TTL cache entry for a list of canonical strings."""

    values: List[str]
    expires_at: float


@dataclass
class _MetadataCacheEntry:
    """TTL cache entry for metadata dictionaries."""

    value: Dict[str, Any]
    expires_at: float


@dataclass
class _RowsCacheEntry:
    """TTL cache entry for raw API rows used at submit-payload boundaries."""

    rows: List[Dict[str, Any]]
    expires_at: float


class RuntimeV7CanonicalValuesProvider:
    """Fetch and cache canonical metadata from Gulong API endpoints."""

    def __init__(
        self,
        *,
        http_client: Optional[SyncHTTPClient] = None,
        base_url: str = DEFAULT_API_BASE_URL,
        ttl_seconds: int = 900,
    ) -> None:
        """Create a lazy API-backed provider with a soft TTL cache."""

        self._http = http_client or SyncHTTPClient(
            config=SyncHTTPClientConfig(base_url=str(base_url or DEFAULT_API_BASE_URL).rstrip("/"))
        )
        self._ttl_seconds = max(0, int(ttl_seconds))
        self._cache: Dict[str, _CacheEntry] = {}
        self._metadata_cache: Dict[str, _MetadataCacheEntry] = {}
        self._rows_cache: Dict[str, _RowsCacheEntry] = {}

    def brands(self) -> Sequence[str]:
        """Return canonical tire brand names, loading them lazily if needed."""

        return self._get_or_load("brands", self._load_brands)

    def tire_categories(self) -> Sequence[str]:
        """Return canonical tire category names, loading them lazily if needed."""

        return self._get_or_load("tire_categories", self._load_tire_categories)

    def payment_methods(self) -> Sequence[str]:
        """Return payment method labels, loading them lazily if needed."""

        return self._get_or_load("payment_methods", self._load_payment_methods)

    def transaction_types(self) -> Sequence[str]:
        """Return checkout transaction types, loading them lazily if needed."""

        return self._get_or_load("transaction_types", self._load_transaction_types)

    def checkout_metadata(self) -> Dict[str, Any]:
        """Return checkout metadata used for payment/order-field normalization."""

        return self._get_metadata_or_load("checkout_metadata", self._load_checkout_metadata)

    def locations(self) -> Sequence[str]:
        """Return province and city labels, loading them lazily if needed."""

        return self._get_or_load("locations", self._load_locations)

    def branch_names(self) -> Sequence[str]:
        """Return installation partner names, loading them lazily if needed."""

        return self._get_or_load("branch_names", self._load_branch_names)

    def branch_addon_names(self) -> Sequence[str]:
        """Return branch add-on names, loading them lazily if needed."""

        return self._get_or_load("branch_addon_names", self._load_branch_addon_names)

    def product_by_id(self, product_id: Any) -> Dict[str, Any]:
        """Return a raw product row by product id without exposing raw catalogs to prompts."""

        product_id_text = str(product_id or "").strip()
        if not product_id_text:
            return {}
        for row in self._get_rows_or_load("product_rows", lambda: self._fetch_list("/product_list")):
            row_id = str(row.get("product_id") or row.get("id") or "").strip()
            if row_id and row_id == product_id_text:
                return deepcopy(row)
        return {}

    def branch_by_id(self, branch_id: Any) -> Dict[str, Any]:
        """Return a raw branch row by branch id for order payload submission."""

        branch_id_text = str(branch_id or "").strip()
        if not branch_id_text:
            return {}
        for row in self._get_rows_or_load("branch_rows", lambda: self._fetch_list("/all_branch")):
            row_id = str(row.get("id") or row.get("branch_id") or "").strip()
            if row_id and row_id == branch_id_text:
                return deepcopy(row)
        return {}

    def prompt_examples(self) -> Dict[str, Sequence[str]]:
        """Return compact examples without triggering network loads."""

        return {
            "brands": self._cached_or_default("brands", DEFAULT_BRAND_EXAMPLES),
            "locations": self._cached_or_default("locations", DEFAULT_LOCATION_EXAMPLES),
            "tire_categories": self._cached_or_default(
                "tire_categories", DEFAULT_TIRE_CATEGORY_EXAMPLES
            ),
            "payment_methods": self._cached_or_default(
                "payment_methods", DEFAULT_PAYMENT_METHOD_EXAMPLES
            ),
            "transaction_types": self._cached_or_default("transaction_types", ["Install", "Pick-up"]),
            "branch_addons": self._cached_or_default(
                "branch_addon_names", DEFAULT_BRANCH_ADDON_EXAMPLES
            ),
        }

    def _get_or_load(self, key: str, loader: Callable[[], List[str]]) -> List[str]:
        """Return cached canonical strings or load and cache them."""

        now = time.time()
        cached = self._cache.get(key)
        if cached and cached.expires_at >= now:
            return list(cached.values)
        try:
            values = _unique([value for value in loader() if value])
        except Exception:
            values = []
        self._cache[key] = _CacheEntry(values=values, expires_at=now + self._ttl_seconds)
        return list(values)

    def _get_metadata_or_load(
        self,
        key: str,
        loader: Callable[[], Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Return cached metadata or load and cache a defensive copy."""

        now = time.time()
        cached = self._metadata_cache.get(key)
        if cached and cached.expires_at >= now:
            return deepcopy(cached.value)
        try:
            value = loader()
        except Exception:
            value = {}
        self._metadata_cache[key] = _MetadataCacheEntry(
            value=deepcopy(value),
            expires_at=now + self._ttl_seconds,
        )
        return deepcopy(value)

    def _get_rows_or_load(
        self,
        key: str,
        loader: Callable[[], List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """Return cached raw rows for payload canonicalization boundaries."""

        now = time.time()
        cached = self._rows_cache.get(key)
        if cached and cached.expires_at >= now:
            return deepcopy(cached.rows)
        try:
            rows = [row for row in loader() if isinstance(row, dict)]
        except Exception:
            rows = []
        self._rows_cache[key] = _RowsCacheEntry(
            rows=deepcopy(rows),
            expires_at=now + self._ttl_seconds,
        )
        return deepcopy(rows)

    def _cached_or_default(self, key: str, default: Sequence[str]) -> Sequence[str]:
        """Return cached prompt examples without triggering a network call."""

        cached = self._cache.get(key)
        if cached and cached.expires_at >= time.time() and cached.values:
            return list(cached.values[:20])
        return list(default)

    def _fetch_list(self, path: str) -> List[Dict[str, Any]]:
        """Fetch a list-like API payload and normalize it to dict rows."""

        payload = self._http.get_json(path)
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            return [row for row in payload.get("data") or [] if isinstance(row, dict)]
        return []

    def _load_brands(self) -> List[str]:
        """Load tire brands from the Gulong product dropdown endpoint."""

        rows = self._fetch_list("/product_list_dropdown_brand")
        return [str(row.get("brand") or "").strip().upper() for row in rows if row.get("brand")]

    def _load_tire_categories(self) -> List[str]:
        """Load tire category names from the Gulong category endpoint."""

        rows = self._fetch_list("/tire_brand")
        return [_title_text(row.get("name")) for row in rows if row.get("name")]

    def _load_payment_methods(self) -> List[str]:
        """Load payment method labels from the Gulong payment endpoint."""

        rows = self._fetch_list("/payment/list")
        values: List[str] = []
        for row in rows:
            for key in ("name", "label", "value"):
                value = str(row.get(key) or "").strip()
                if value:
                    values.append(value)
            if row.get("is_installment"):
                values.append("credit card installment")
        values.extend(DEFAULT_PAYMENT_METHOD_EXAMPLES)
        return values

    def _load_checkout_metadata(self) -> Dict[str, Any]:
        """Load checkout metadata needed for payment normalization."""

        return {
            "transaction_types": self._fetch_list("/transaction_list"),
            "payment_options": [
                {
                    "id": 1,
                    "name": "Pay Later",
                    "description": "Pay a reservation fee to secure your slot.",
                },
                {
                    "id": 2,
                    "name": "Pay Now",
                    "description": "Pay in full now and receive a PHP 100 discount.",
                },
            ],
            "payment_types": self._fetch_list("/payment/list"),
            "source": "gulong_api_checkout_metadata",
            "generated_at_epoch_s": int(time.time()),
            "ttl_seconds": self._ttl_seconds,
        }

    def _load_transaction_types(self) -> List[str]:
        """Load checkout transaction type labels from the API."""

        rows = self._fetch_list("/transaction_list")
        return [str(row.get("trans_type") or row.get("name") or "").strip() for row in rows]

    def _load_locations(self) -> List[str]:
        """Load province and city names from the Runtime V7-owned endpoints."""

        provinces = self._fetch_list("/get_province")
        cities = self._fetch_list("/get_city")
        province_by_code = {
            str(row.get("PROV_CODE") or "").strip(): _title_text(row.get("PROV_NAME"))
            for row in provinces
            if row.get("PROV_CODE") and row.get("PROV_NAME")
        }
        values: List[str] = []
        for province in province_by_code.values():
            if province:
                values.append(province)
        for row in cities:
            city = _title_text(row.get("CITY_NAME"))
            province = province_by_code.get(str(row.get("PROV_CODE") or "").strip())
            if city:
                values.append(city)
                if province:
                    values.append(f"{city}, {province}")
        values.extend(DEFAULT_LOCATION_EXAMPLES)
        return values

    def _load_branch_names(self) -> List[str]:
        """Load active installation partner names from the API."""

        rows = self._fetch_list("/all_branch")
        values = []
        for row in rows:
            if "active" in row and not row.get("active"):
                continue
            name = str(row.get("name") or row.get("branch_name") or "").strip()
            if name:
                values.append(name)
        return values

    def _load_branch_addon_names(self) -> List[str]:
        """Load branch add-on service names from branch metadata."""

        rows = self._fetch_list("/branch_list_loc")
        values: List[str] = []
        for row in rows:
            for addon in row.get("branch_add_ons") or []:
                if not isinstance(addon, dict):
                    continue
                for key in ("service", "name", "addon_name"):
                    value = str(addon.get(key) or "").strip()
                    if value:
                        values.append(value)
        values.extend(DEFAULT_BRANCH_ADDON_EXAMPLES)
        return values


def _title_text(value: Any) -> str:
    """Normalize whitespace and title-case a display string."""

    text = " ".join(str(value or "").strip().split())
    return text.title() if text else ""


def _unique(values: Sequence[str]) -> List[str]:
    """Return ordered unique non-empty strings using case-insensitive keys."""

    output: List[str] = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if text and key not in seen:
            output.append(text)
            seen.add(key)
    return output
