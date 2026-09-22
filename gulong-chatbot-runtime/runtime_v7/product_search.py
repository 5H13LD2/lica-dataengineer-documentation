"""Runtime V7 product search runner for Gulong tire catalog discovery.

The runner is intentionally deterministic. The model supplies endpoint-shaped
search fields; this module owns API attempts, fallback scans, candidate ranking,
and compact output shaping.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

from runtime.http.sync_http_client import SyncHTTPClient, SyncHTTPClientConfig
from runtime_v7.canonical_values import CanonicalValuesProvider
from runtime_v7.entity_resolution import (
    canonical_vehicle_alias,
    canonical_vehicle_make_model_pair,
    canonical_vehicle_query,
)
from runtime_v7.payment_provider_display import payment_provider_names_from_row


DEFAULT_API_BASE_URL = "https://api.gulong.ph/api"
MANILA_TZ = timezone(timedelta(hours=8))
BUNDLE_PRICING_ENV = "RUNTIME_V7_ENABLE_BUNDLE_PRICING"
CATALOG_CACHE_ENABLED_ENV = "RUNTIME_V7_ENABLE_PRODUCT_LIST_CACHE"
CATALOG_CACHE_TTL_ENV = "RUNTIME_V7_PRODUCT_LIST_CACHE_TTL_SECONDS"
PRODUCT_VISIBILITY_DENYLIST_PATH_ENV = "RUNTIME_V7_PRODUCT_VISIBILITY_DENYLIST_PATH"
PRODUCT_VISIBILITY_DENYLIST_SLUGS_ENV = "RUNTIME_V7_PRODUCT_VISIBILITY_DENYLIST_SLUGS"
PRODUCT_VISIBILITY_DENYLIST_PRODUCT_IDS_ENV = "RUNTIME_V7_PRODUCT_VISIBILITY_DENYLIST_PRODUCT_IDS"
DEFAULT_PRODUCT_VISIBILITY_DENYLIST_PATH = Path(__file__).with_name("product_visibility_denylist.json")
TRUSTED_PRODUCT_IMAGE_HOSTS = {
    "gulong-ph.sgp1.digitaloceanspaces.com",
    "gulongph.sgp1.digitaloceanspaces.com",
    "storage.googleapis.com",
}
CORE_FILTERS = {"rim_size", "brand", "section_width", "aspect_ratio", "model_or_pattern"}
DEFAULT_CANONICAL_BRANDS = (
    "ACCELERA",
    "APOLLO",
    "ARIVO",
    "ATLAS",
    "BFGOODRICH",
    "BLACK ARROW",
    "BRIDGESTONE",
    "CONTINENTAL",
    "COOPER",
    "CST",
    "DEESTONE",
    "DUNLOP",
    "DURATURN",
    "FALKEN",
    "FRONWAY",
    "GENERAL TIRE",
    "GOODYEAR",
    "HANKOOK",
    "KINTO",
    "LAUFENN",
    "LINGLONG",
    "MAXXIS",
    "MICHELIN",
    "NANKANG",
    "NITTO",
    "PETLAS",
    "PIRELLI",
    "TOYO",
    "VREDESTEIN",
    "WESTLAKE",
    "YOKOHAMA",
)
PRICE_CATEGORY_ORDER = ("BUDGET", "ECONOMY", "MID RANGE", "PREMIUM")
PRESENTATION_TARGET_CARD_COUNT = 3
PRESENTATION_MAX_CARD_COUNT = 4
YOKOHAMA_SET_PROMO_5200_SKUS = {
    ("175/65/R14", "E70K"),
    ("175/65/R14", "ES32"),
    ("185/55/R15", "AE01"),
    ("185/55/R15", "ES32"),
    ("185/60/R15", "E70B"),
    ("185/60/R15", "ES32"),
    ("185/65/R15", "AE01"),
    ("185/65/R15", "ES32"),
    ("195/55/R15", "ES32"),
    ("195/55/R15", "V701"),
    ("185/55/R16", "ES32"),
    ("195/60/R16", "ES32"),
    ("205/55/R16", "ES32"),
    ("205/60/R16", "AE51"),
    ("205/65/R16", "E70B"),
    ("215/70/R16", "G058"),
    ("205/45/R17", "V701"),
    ("205/50/R17", "AE51"),
    ("215/45/R17", "V701"),
    ("215/50/R17", "AE51"),
    ("215/55/R17", "E70B"),
    ("215/60/R17", "G058"),
    ("225/60/R17", "G058"),
    ("215/45/R18", "V701"),
    ("225/45/R18", "V701"),
    ("225/50/R18", "V701"),
    ("225/55/R18", "G058"),
    ("235/60/R18", "G058"),
    ("245/40/R18", "V701"),
    ("255/50/R18", "G057"),
}
YOKOHAMA_SET_PROMO_6000_SKUS = {
    ("265/65/R17", "G018"),
    ("265/65/R17", "G062"),
    ("255/60/R18", "G062"),
    ("265/60/R18", "G018"),
    ("265/60/R18", "G062"),
    ("265/65/R18", "G018"),
    ("265/50/R20", "G018"),
    ("265/50/R20", "G057"),
}
PRICE_CATEGORY_DISPLAY = {
    "BUDGET": "Budget",
    "ECONOMY": "Economy",
    "MID RANGE": "Mid Range",
    "PREMIUM": "Premium",
}
BRAND_ALIASES = {
    "ARRIVO": "ARIVO",
    "BFG": "BFGOODRICH",
    "BFGOODRICH": "BFGOODRICH",
    "BFGUDRICH": "BFGOODRICH",
    "BFGUDRUCH": "BFGOODRICH",
    "BFGUDRITCH": "BFGOODRICH",
    "BFGODRICH": "BFGOODRICH",
    "BFGOODRITCH": "BFGOODRICH",
    "BFGRICH": "BFGOODRICH",
    "BRIDGESTON": "BRIDGESTONE",
    "BRIDGSTONE": "BRIDGESTONE",
    "GOODRICH": "BFGOODRICH",
    "MICH": "MICHELIN",
    "MICHELINE": "MICHELIN",
    "MICHELLIN": "MICHELIN",
    "MICHILIN": "MICHELIN",
    "WESLAKE": "WESTLAKE",
    "WESTLAK": "WESTLAKE",
    "YOKO": "YOKOHAMA",
    "YOKOHMA": "YOKOHAMA",
    "YOKOHANA": "YOKOHAMA",
}
KNOWN_BRAND_ORIGIN_HINTS = {
    # Used only to enforce explicit origin filters when catalog origin is blank.
    "ARIVO": "China",
    "ATLAS": "China",
    "DURATURN": "China",
    "LINGLONG": "China",
    "SAILUN": "China",
    "WESTLAKE": "China",
}
KNOWN_BRAND_WARRANTY_HINTS = {
    # Used only when API warranty fields and warranty badge metadata are blank.
    "BFGOODRICH": "6 years",
    "BRIDGESTONE": "5 years",
    "FRONWAY": "5 years from purchase date",
    "MICHELIN": "6 years",
    "NANKANG": "5 years",
    "YOKOHAMA": "5 years",
}
SECONDARY_FILTERS = {
    "budget_max",
    "promo_only",
    "promo_type",
    "ev_compatible",
    "gulong_guarantee_only",
    "tire_category",
    "origin",
    "warranty_years",
    "terrain_type",
    "availability",
    "installment",
    "installment_bank",
    "installment_months",
    "installment_interest",
}
PRODUCT_FITMENT_FILTERS = frozenset(
    {
        "section_width",
        "aspect_ratio",
        "rim_size",
        "ev_compatible",
    }
)


@dataclass
class ProductSearchRequest:
    """Model-facing product search request.

    All fields are optional. `brands` is always a list; even one requested brand
    should arrive as `["YOKOHAMA"]` after normalization.
    """

    section_width: Optional[str] = None
    aspect_ratio: Optional[str] = None
    rim_size: Optional[str] = None
    brands: List[str] = field(default_factory=list)
    brand_match_mode: str = "prefer"
    preferred_brands: List[str] = field(default_factory=list)
    excluded_brands: List[str] = field(default_factory=list)
    model_or_pattern: Optional[str] = None
    budget_max: Optional[float] = None
    budget_scope: str = "per_tire"
    promo_only: Optional[bool] = None
    promo_types: List[str] = field(default_factory=list)
    ev_compatible: Optional[bool] = None
    gulong_guarantee_only: Optional[bool] = None
    gulong_guarantee_tiers: List[int] = field(default_factory=list)
    origins: List[str] = field(default_factory=list)
    excluded_origins: List[str] = field(default_factory=list)
    warranty_years: List[int] = field(default_factory=list)
    tire_categories: List[str] = field(default_factory=list)
    excluded_tire_categories: List[str] = field(default_factory=list)
    terrain_types: List[str] = field(default_factory=list)
    availability: str = "any"
    installment_only: Optional[bool] = None
    installment_banks: List[str] = field(default_factory=list)
    installment_months: List[int] = field(default_factory=list)
    installment_max_interest: Optional[float] = None
    ply_rating: Optional[int] = None
    quantity: int = 4
    sort: str = "best_value"
    top_k: int = 6
    semantic_query: Optional[str] = None
    soft_preferences: List[str] = field(default_factory=list)
    brand_corrections: List[Dict[str, Any]] = field(default_factory=list)
    size_corrections: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, payload: Optional[Dict[str, Any]]) -> "ProductSearchRequest":
        """Build a request from a JSON-like mapping."""

        payload = payload or {}
        size_parts, size_corrections = _split_tire_size_arg(payload.get("tire_size"))
        brands = _split_brand_values(payload.get("required_brands") or payload.get("brands"))
        # Defensive migration only: callers should not use singular `brand`.
        if not brands and payload.get("brand"):
            brands = _split_brand_values([payload.get("brand")])
        preferred_brands = _split_brand_values(
            payload.get("preferred_brands")
            or payload.get("preferred_brand")
            or payload.get("brand_preferences")
            or payload.get("brand_preference")
        )
        quantity = _coerce_int(payload.get("quantity"), default=4, minimum=1, maximum=12)
        top_k = _coerce_int(payload.get("top_k"), default=6, minimum=1, maximum=12)
        budget_max = _coerce_float(payload.get("budget_max"))
        raw_budget_scope = str(payload.get("budget_scope") or "").strip().lower()
        budget_scope = raw_budget_scope or ("total" if budget_max is not None else "per_tire")
        return cls(
            section_width=_clean_optional(payload.get("section_width")) or size_parts.get("section_width"),
            aspect_ratio=_clean_optional(payload.get("aspect_ratio")) or size_parts.get("aspect_ratio"),
            rim_size=_clean_optional(payload.get("rim_size")) or size_parts.get("rim_size"),
            brands=brands,
            brand_match_mode=normalize_brand_match_mode(payload.get("brand_match_mode")),
            preferred_brands=preferred_brands,
            excluded_brands=_split_brand_values(payload.get("excluded_brands") or payload.get("excluded_brand")),
            model_or_pattern=_clean_optional(payload.get("model_or_pattern")),
            budget_max=budget_max,
            budget_scope=budget_scope,
            promo_only=_coerce_optional_bool(payload.get("promo_only")),
            promo_types=normalize_promo_types(payload.get("promo_types") or payload.get("promo_type")),
            ev_compatible=_coerce_optional_bool(payload.get("ev_compatible")),
            gulong_guarantee_only=_coerce_optional_bool(payload.get("gulong_guarantee_only")),
            gulong_guarantee_tiers=_normalize_int_list(payload.get("gulong_guarantee_tiers")),
            origins=normalize_origins(payload.get("origins") or payload.get("country_origins") or payload.get("origin")),
            excluded_origins=normalize_origins(
                payload.get("excluded_origins") or payload.get("excluded_origin") or payload.get("avoid_origins")
            ),
            warranty_years=normalize_warranty_years(payload.get("warranty_years") or payload.get("warranty")),
            tire_categories=normalize_tire_categories(
                payload.get("tire_categories") or payload.get("price_categories") or payload.get("price_category")
            ),
            excluded_tire_categories=normalize_tire_categories(
                payload.get("excluded_tire_categories")
                or payload.get("excluded_price_categories")
                or payload.get("avoid_tire_categories")
            ),
            terrain_types=normalize_terrain_types(payload.get("terrain_types") or payload.get("terrain_type")),
            availability=normalize_availability(payload),
            installment_only=_coerce_optional_bool(payload.get("installment_only")),
            installment_banks=normalize_installment_banks(
                payload.get("installment_banks") or payload.get("installment_bank")
            ),
            installment_months=normalize_warranty_years(
                payload.get("installment_months")
                or payload.get("installment_term_months")
                or payload.get("months_to_pay")
            ),
            installment_max_interest=_coerce_float(
                payload.get("installment_max_interest")
                if payload.get("installment_max_interest") is not None
                else payload.get("installment_interest_percent")
            ),
            ply_rating=_coerce_optional_int(payload.get("ply_rating") or payload.get("ply")),
            quantity=quantity,
            sort=str(payload.get("sort") or "best_value").strip().lower(),
            top_k=top_k,
            semantic_query=_clean_optional(payload.get("semantic_query")),
            soft_preferences=_normalize_string_list(payload.get("soft_preferences")),
            size_corrections=size_corrections,
        )

    def normalized(self, *, canonical_brands: Optional[Iterable[str]] = None) -> "ProductSearchRequest":
        """Return a normalized copy used by the runner."""

        section = normalize_section_width(self.section_width)
        aspect = _normalize_numeric_text(self.aspect_ratio)
        rim = normalize_rim_size(self.rim_size, section_width=section)
        if self.ply_rating is not None and self.ply_rating >= 6:
            if rim and re.fullmatch(r"R\d{2}", str(rim).upper()):
                rim = f"{rim}C"
        section, size_corrections = normalize_metric_section_width_with_corrections(
            section,
            aspect_ratio=aspect,
            rim_size=rim,
        )
        brands, brand_corrections = normalize_brands_with_corrections(
            self.brands,
            canonical_brands=canonical_brands,
        )
        preferred_brands, preferred_brand_corrections = normalize_brands_with_corrections(
            self.preferred_brands,
            canonical_brands=canonical_brands,
        )
        excluded_brands, excluded_brand_corrections = normalize_brands_with_corrections(
            self.excluded_brands,
            canonical_brands=canonical_brands,
        )
        if not brand_corrections and self.brand_corrections:
            brand_corrections = [dict(item) for item in self.brand_corrections]
        all_brand_corrections = [*brand_corrections, *preferred_brand_corrections, *excluded_brand_corrections]
        promo_types = normalize_promo_types(self.promo_types)
        quantity = max(1, int(self.quantity or 4))
        promo_only = self.promo_only
        if promo_only is None and _promo_types_imply_promo_only(promo_types, quantity=quantity):
            promo_only = True
        return ProductSearchRequest(
            section_width=section,
            aspect_ratio=aspect,
            rim_size=rim,
            brands=brands,
            brand_match_mode=normalize_brand_match_mode(self.brand_match_mode),
            preferred_brands=preferred_brands,
            excluded_brands=excluded_brands,
            model_or_pattern=_clean_optional(self.model_or_pattern),
            budget_max=self.budget_max,
            budget_scope=self.budget_scope if self.budget_scope in {"per_tire", "total"} else "per_tire",
            promo_only=promo_only,
            promo_types=promo_types,
            ev_compatible=self.ev_compatible,
            gulong_guarantee_only=self.gulong_guarantee_only,
            gulong_guarantee_tiers=[tier for tier in self.gulong_guarantee_tiers if tier in (1, 2)],
            origins=normalize_origins(self.origins),
            excluded_origins=normalize_origins(self.excluded_origins),
            warranty_years=normalize_warranty_years(self.warranty_years),
            tire_categories=normalize_tire_categories(self.tire_categories),
            excluded_tire_categories=normalize_tire_categories(self.excluded_tire_categories),
            terrain_types=normalize_terrain_types(self.terrain_types),
            availability=self.availability if self.availability in {"any", "in_stock", "pre_order"} else "any",
            installment_only=self.installment_only,
            installment_banks=normalize_installment_banks(self.installment_banks),
            installment_months=normalize_warranty_years(self.installment_months),
            installment_max_interest=self.installment_max_interest,
            ply_rating=self.ply_rating,
            quantity=quantity,
            sort=self.sort or "best_value",
            top_k=max(1, min(12, int(self.top_k or 6))),
            semantic_query=_clean_optional(self.semantic_query),
            soft_preferences=_normalize_string_list(self.soft_preferences),
            brand_corrections=all_brand_corrections,
            size_corrections=[*self.size_corrections, *size_corrections],
        )

    def to_public_dict(self) -> Dict[str, Any]:
        """Return the normalized request fields for result metadata."""

        normalized = self.normalized()
        data = {
            "section_width": normalized.section_width,
            "aspect_ratio": normalized.aspect_ratio,
            "rim_size": normalized.rim_size,
            "brands": normalized.brands,
            "brand_match_mode": normalized.brand_match_mode if normalized.brands else None,
            "preferred_brands": normalized.preferred_brands,
            "excluded_brands": normalized.excluded_brands,
            "model_or_pattern": normalized.model_or_pattern,
            "budget_max": normalized.budget_max,
            "budget_scope": normalized.budget_scope,
            "promo_only": normalized.promo_only,
            "promo_types": normalized.promo_types,
            "ev_compatible": normalized.ev_compatible,
            "gulong_guarantee_only": normalized.gulong_guarantee_only,
            "gulong_guarantee_tiers": normalized.gulong_guarantee_tiers,
            "origins": normalized.origins,
            "excluded_origins": normalized.excluded_origins,
            "warranty_years": normalized.warranty_years,
            "tire_categories": normalized.tire_categories,
            "excluded_tire_categories": normalized.excluded_tire_categories,
            "terrain_types": normalized.terrain_types,
            "availability": normalized.availability,
            "installment_only": normalized.installment_only,
            "installment_banks": normalized.installment_banks,
            "installment_months": normalized.installment_months,
            "installment_max_interest": normalized.installment_max_interest,
            "ply_rating": normalized.ply_rating,
            "quantity": normalized.quantity,
            "sort": normalized.sort,
            "top_k": normalized.top_k,
            "semantic_query": normalized.semantic_query,
            "soft_preferences": normalized.soft_preferences,
        }
        if normalized.brand_corrections:
            data["brand_corrections"] = normalized.brand_corrections
        if normalized.size_corrections:
            data["size_corrections"] = normalized.size_corrections
        return data


@dataclass
class _AttemptSpec:
    label: str
    params: Dict[str, Any]
    source: str = "shop"


def _split_tire_size_arg(value: Any) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    """Split a defensive raw tire_size tool arg into canonical request fields."""

    raw = str(value or "").strip()
    if not raw:
        return {}, []
    text = raw.upper().replace(" ", "")
    metric = re.search(
        r"(?P<section>\d{3})/?(?P<aspect>\d{2})(?P<prefix>ZR|R)?(?P<rim>\d{2})(?P<commercial>C)?",
        text,
    )
    if metric:
        section = normalize_section_width(metric.group("section")) or metric.group("section")
        aspect = metric.group("aspect")
        prefix = metric.group("prefix") or "R"
        commercial = metric.group("commercial") or ""
        rim_token = f"R{metric.group('rim')}C" if commercial else f"{prefix}{metric.group('rim')}"
        rim = normalize_rim_size(rim_token, section_width=section) or rim_token
        parts = {"section_width": section, "aspect_ratio": aspect, "rim_size": rim}
        return parts, [_tire_size_arg_split_metadata(raw, parts)]

    commercial = re.search(r"(?P<section>\d{3})(?:/|R)(?P<rim>\d{2})(?P<commercial>C)?", text)
    if commercial:
        section = normalize_section_width(commercial.group("section")) or commercial.group("section")
        rim_token = f"R{commercial.group('rim')}{commercial.group('commercial') or ''}"
        parts = {
            "section_width": section,
            "rim_size": normalize_rim_size(rim_token, section_width=section) or rim_token,
        }
        return parts, [_tire_size_arg_split_metadata(raw, parts)]

    return {}, [
        {
            "input_tire_size": raw,
            "status": "unparsed_tire_size_arg",
            "reason": "tool arg did not contain a full metric or commercial tire size",
        }
    ]


def _tire_size_arg_split_metadata(raw: str, parts: Dict[str, str]) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "input_tire_size": raw,
        "status": "tire_size_arg_split",
        "method": "defensive_tool_arg_normalization",
        "section_width": parts.get("section_width"),
        "rim_size": parts.get("rim_size"),
    }
    if parts.get("aspect_ratio"):
        metadata["aspect_ratio"] = parts.get("aspect_ratio")
    return metadata


class ProductSearchRunner:
    """Fetch, merge, rank, and compact tire product search results."""

    _catalog_cache: ClassVar[Dict[Tuple[str, bool], Tuple[float, List[Dict[str, Any]]]]] = {}
    _visibility_denylist_cache: ClassVar[Dict[Tuple[str, str, str], Dict[str, Any]]] = {}
    _catalog_cache_client_tokens: ClassVar["weakref.WeakKeyDictionary[Any, str]"] = weakref.WeakKeyDictionary()
    _catalog_cache_token_counter: ClassVar[int] = 0

    def __init__(
        self,
        *,
        http_client: Optional[SyncHTTPClient] = None,
        canonical_values_provider: Optional[CanonicalValuesProvider] = None,
        max_api_calls: int = 12,
        max_pages_per_attempt: int = 1,
        use_catalog_fallback: bool = True,
        enable_bundle_pricing: Optional[bool] = None,
        use_catalog_cache: Optional[bool] = None,
        catalog_cache_ttl_seconds: Optional[int] = None,
        visibility_denylist: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._http = http_client or SyncHTTPClient(
            config=SyncHTTPClientConfig(base_url=DEFAULT_API_BASE_URL)
        )
        self.canonical_values_provider = canonical_values_provider
        self.max_api_calls = max(1, int(max_api_calls))
        self.max_pages_per_attempt = max(1, int(max_pages_per_attempt))
        self.use_catalog_fallback = bool(use_catalog_fallback)
        self.enable_bundle_pricing = (
            _env_bool(BUNDLE_PRICING_ENV, default=True)
            if enable_bundle_pricing is None
            else bool(enable_bundle_pricing)
        )
        self.use_catalog_cache = (
            _env_bool(CATALOG_CACHE_ENABLED_ENV, default=True)
            if use_catalog_cache is None
            else bool(use_catalog_cache)
        )
        self.catalog_cache_ttl_seconds = (
            _env_int(CATALOG_CACHE_TTL_ENV, default=900, minimum=0, maximum=86400)
            if catalog_cache_ttl_seconds is None
            else max(0, int(catalog_cache_ttl_seconds))
        )
        self._visibility_denylist_override = deepcopy(visibility_denylist) if visibility_denylist is not None else None
        self._promo_brands: Optional[set[str]] = None

    def _canonical_brands_for_request(self, request: ProductSearchRequest) -> Optional[Sequence[str]]:
        """Return API-backed brands only when local normalization cannot settle input."""

        provider = self.canonical_values_provider
        if provider is None:
            return None
        raw_values = [*request.brands, *request.preferred_brands, *request.excluded_brands]
        if not _brand_inputs_need_catalog_lookup(raw_values):
            return None
        try:
            return provider.brands()
        except Exception:
            return None

    def run(self, payload: ProductSearchRequest | Dict[str, Any]) -> Dict[str, Any]:
        """Run bounded product search and return compact model-facing results."""

        started = time.perf_counter()
        request = payload if isinstance(payload, ProductSearchRequest) else ProductSearchRequest.from_mapping(payload)
        request = request.normalized(canonical_brands=self._canonical_brands_for_request(request))
        attempts: List[Dict[str, Any]] = []
        products_by_key: Dict[str, Dict[str, Any]] = {}
        api_calls = 0
        stopped_reason = "attempts_exhausted"

        for group in self._build_attempt_groups(request):
            if api_calls >= self.max_api_calls:
                stopped_reason = "api_call_cap_reached"
                break
            remaining_calls = max(0, self.max_api_calls - api_calls)
            specs = group[:remaining_calls]
            for group_products, group_attempts, used_calls in self._fetch_shop_group(specs):
                self._enrich_product_flags(group_products, allow_promo_lookup=requires_promo_truth(request))
                api_calls += used_calls
                attempts.extend(group_attempts)
                self._merge_products(products_by_key, group_products)
            ranked_preview = self._rank_products(request, products_by_key.values())
            if self._has_enough_strong_results(request, ranked_preview):
                stopped_reason = f"enough_results_after_{group[0].label}"
                break
            if api_calls >= self.max_api_calls:
                stopped_reason = "api_call_cap_reached"
                break

        if self._should_use_catalog_fallback(request, products_by_key.values(), attempts, api_calls):
            had_endpoint_attempts = bool(attempts)
            catalog_products, catalog_attempt = self._fetch_catalog_candidates(request)
            self._enrich_product_flags(catalog_products, allow_promo_lookup=requires_promo_truth(request))
            attempts.append(catalog_attempt)
            self._merge_products(products_by_key, catalog_products)
            catalog_ranked_preview = self._rank_products(request, catalog_products)
            if (
                request.model_or_pattern
                and not catalog_ranked_preview
                and not had_endpoint_attempts
                and api_calls < self.max_api_calls
            ):
                broad_specs = self._specs_for(
                    "broad_discovery",
                    section_width=None,
                    aspect_ratio=None,
                    rim_size=None,
                    brands=request.brands,
                )
                remaining_calls = max(0, self.max_api_calls - api_calls)
                for group_products, group_attempts, used_calls in self._fetch_shop_group(broad_specs[:remaining_calls]):
                    group_products = refine_model_products(request, group_products)
                    self._enrich_product_flags(group_products, allow_promo_lookup=requires_promo_truth(request))
                    api_calls += used_calls
                    attempts.extend(group_attempts)
                    self._merge_products(products_by_key, group_products)

        if self._should_fetch_presentation_alternatives(request, products_by_key.values(), api_calls):
            alt_products, alt_attempt = self._fetch_presentation_alternative_candidates(request)
            self._enrich_product_flags(alt_products, allow_promo_lookup=requires_promo_truth(request))
            attempts.append(alt_attempt)
            self._merge_products(products_by_key, alt_products)

        checkout_installment_evidence = self._apply_checkout_installment_authority(
            products_by_key.values(),
            request,
        )
        ranked = self._rank_products(request, products_by_key.values())
        # Promo truth affects which representative card should be shown, not
        # only promo-only filtering. Enrich before card selection so Buy 3 Get 1
        # products can win within otherwise equivalent category/brand pools.
        self._enrich_product_flags(ranked, allow_promo_lookup=True)
        best_products = ranked[: request.top_k]
        exact_size_requested = bool(
            request.section_width
            and request.aspect_ratio
            and request.rim_size
        )
        exact_size_products = _requested_full_size_candidates(request, ranked)
        card_products = select_presentation_products(
            request,
            ranked,
            limit=presentation_card_limit(request),
        )
        card_products = prefer_image_backed_presentation_products(
            request,
            ranked,
            selected=card_products,
            limit=presentation_card_limit(request),
        )
        self._enrich_product_flags(card_products, allow_promo_lookup=True)
        self._enrich_product_flags(best_products, allow_promo_lookup=True)
        product_cards = render_product_cards(request, card_products)
        presented_products = [self._public_product(item) for item in card_products]
        preferred_presentation_status = _preferred_brand_presentation_status(
            request,
            ranked,
            card_products,
        )
        visibility_filter = self._visibility_filter_summary(products_by_key.values())
        result_pool_summary = _pool_summary(ranked)
        match_tiers = _build_match_tiers(ranked)
        status, result_level = _status_from_pool(result_pool_summary)
        exact_base_query_verified = _exact_size_base_query_verified(
            request,
            attempts,
        )
        if exact_size_requested and not exact_size_products:
            # Broader candidates remain internal diagnostic evidence. They
            # cannot become selectable products until the customer explicitly
            # agrees to explore a different tire size.
            status = (
                "exact_unavailable"
                if exact_base_query_verified
                else "unavailable"
            )
            result_level = "none"
            card_products = []
            product_cards = []
            presented_products = []
            preferred_presentation_status = _preferred_brand_presentation_status(
                request,
                ranked,
                card_products,
            )
        recovery_options = _product_search_recovery_options(request, status, result_level, result_pool_summary)
        quantity_promo_context = buy3get1_quantity_context(request)
        promo_evidence = self._promo_claim_evidence(request, ranked)
        presentation = presentation_strategy(request, card_products, ranked)
        if quantity_promo_context:
            presentation["quantity_promo_context"] = quantity_promo_context
        latency_ms = int((time.perf_counter() - started) * 1000)
        observation_ref = _observation_ref(request, attempts, best_products)

        result = {
            "status": status,
            "result_level": result_level,
            "query_basis": {
                "normalized_filters": request.to_public_dict(),
                "partial_match": status == "partial_match",
                "exact_base_query_verified": exact_base_query_verified,
                "exact_size_cards_suppressed": (
                    status in {"exact_unavailable", "unavailable"}
                    and exact_size_requested
                    and not exact_size_products
                ),
                "stopped_reason": stopped_reason,
                "visibility_filter": visibility_filter,
            },
            "best_products": [self._public_product(item) for item in best_products],
            "presented_products": presented_products,
            "product_cards": product_cards,
            "product_card_link_validation": _product_card_link_validation_summary(
                product_cards
            ),
            "presentation_strategy": presentation,
            "facets": self._build_facets(ranked),
            "match_tiers": match_tiers,
            "result_pool_summary": result_pool_summary,
            "attempted_queries": attempts,
            "no_match_reasons": self._no_match_reasons(request, result_pool_summary, attempts),
            "requested_brand_status": self._brand_status(
                request.brands,
                ranked,
                presented=card_products,
                strict_active_filters=True,
            ),
            "preferred_brand_status": self._brand_status(request.preferred_brands, ranked),
            "preferred_brand_presentation_status": preferred_presentation_status,
            "requested_model_pattern_status": self._model_pattern_status(request, ranked),
            "budget_status": self._budget_status(request, ranked),
            "recommended_response_strategy": _response_strategy(status, result_level, result_pool_summary),
            "observation_ref": observation_ref,
            "latency_ms": latency_ms,
            "api_call_count": api_calls,
        }
        if status == "exact_unavailable":
            result["reason"] = (
                "No active product matched the exact requested tire size in "
                "the exact-size base query. Broader-size candidates were kept "
                "as diagnostics and were not rendered."
            )
        elif status == "unavailable" and exact_size_requested:
            result["reason"] = (
                "The exact-size base query did not complete successfully, so "
                "the runtime cannot claim that the requested size is unavailable."
            )
        if promo_evidence:
            result["promo_evidence"] = promo_evidence
        if checkout_installment_evidence:
            result["checkout_installment_evidence"] = checkout_installment_evidence
        if quantity_promo_context:
            result["quantity_promo_context"] = quantity_promo_context
            result["suggested_followup_searches"] = quantity_promo_context.get("suggested_followup_searches") or []
        if visibility_filter.get("filtered_count"):
            result["visibility_filter"] = visibility_filter
        if recovery_options:
            result["recovery_options"] = recovery_options
            result["suggested_tool"] = recovery_options[0].get("tool")
            result["suggested_next_step"] = recovery_options[0].get("customer_next_step")
        return result

    def _promo_claim_evidence(
        self,
        request: ProductSearchRequest,
        ranked: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Return compact Buy-3-Get-1 authority for an explicit promo request."""

        if request.promo_only is not True:
            return {}
        active_brands = sorted(self._promo_brand_set())
        requested = list(request.brands)
        requested_not_eligible = [brand for brand in requested if brand not in active_brands]
        nonqualifying = [
            product
            for product in ranked
            if product.get("match", {}).get("missed_filters")
            and "promo_only" in set(product.get("match", {}).get("missed_filters") or [])
        ]
        return {
            "authority": "gulong_api_promo_brands",
            "promo_type": "buy3get1",
            "verified_brands": active_brands,
            "requested_brands": requested,
            "requested_brands_not_eligible": requested_not_eligible,
            "nonqualifying_exact_or_near_match_count": len(nonqualifying),
            "card_presentation_rule": "Only products that pass promo_only may render as promo cards.",
        }

    def _apply_checkout_installment_authority(
        self,
        products: Iterable[Dict[str, Any]],
        request: ProductSearchRequest,
    ) -> Dict[str, Any]:
        """Reconcile every product card with active checkout installment rows.

        Product `/shop` installments remain a bounded fallback only when the
        checkout metadata provider is unavailable or fails. Once `/payment/list`
        returns successfully, its active rows own current bank/term and brand
        eligibility, including an authoritative empty result.
        """

        if self.canonical_values_provider is None:
            return {}
        try:
            metadata = self.canonical_values_provider.checkout_metadata()
        except Exception:
            return {}
        payment_rows = [
            dict(row)
            for row in metadata.get("payment_types") or []
            if isinstance(row, dict)
            and not _truthy(row.get("is_disabled"))
            and (
                _truthy(row.get("is_installment"))
                or "installment" in _checkout_payment_row_text(row).lower()
            )
        ]
        affected = 0
        for product in products:
            if not isinstance(product, dict):
                continue
            catalog_installments = list(product.get("installments") or [])
            api_installments = _checkout_installments_for_brand(
                payment_rows,
                product.get("brand") or product.get("make"),
            )
            installment_text, minimum_interest = installment_summary(api_installments)
            product["catalog_installments"] = catalog_installments
            product["installments"] = api_installments
            product["installment_text"] = installment_text
            product["installment_min_interest"] = minimum_interest
            product["installment_authority"] = str(
                metadata.get("source") or "gulong_api_checkout_metadata"
            )
            affected += 1
        return {
            "authority": str(metadata.get("source") or "gulong_api_checkout_metadata"),
            "payment_type_ids": [row.get("id") for row in payment_rows],
            "active_installment_count": len(payment_rows),
            "affected_product_count": affected,
            "rule": "Active checkout eligibility replaces catalog installment fields on every product card.",
        }

    def extract_compatible_fitment(self, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract candidate tire sizes for a vehicle query.

        This method intentionally does not produce product cards. `/shop?search=`
        can surface products associated with vehicle text, but that is weaker
        than a customer-confirmed sidewall size, so every result is marked as
        requiring customer confirmation before product recommendations.
        """

        started = time.perf_counter()
        payload = payload or {}
        raw_vehicle_query = _fitment_raw_vehicle_query(payload)
        vehicle_query = _fitment_vehicle_query(payload)
        top_k = _coerce_int(payload.get("top_k"), default=6, minimum=1, maximum=8)
        size_preferences = _fitment_size_preferences(payload, vehicle_query=vehicle_query)
        collection_top_k = max(top_k, min(24, top_k * 4))
        attempts: List[Dict[str, Any]] = []
        source = "shop_search"
        candidates: List[Dict[str, Any]] = []

        fallback_candidates, fallback_attempts = self._fetch_compatible_fitment_fallback(
            payload,
            vehicle_query=vehicle_query,
            top_k=collection_top_k,
        )
        attempts.extend(fallback_attempts)
        if fallback_candidates:
            candidates = fallback_candidates
            source = "car_tire_sizes"

        if not candidates and vehicle_query and _fitment_shop_search_allowed(payload, vehicle_query):
            params = {"sn": "y", "v": 1, "page": 1, "search": vehicle_query}
            attempt_started = time.perf_counter()
            payload_result = self._http.post_json("/shop", params=params, json_data=None)
            latency_ms = int((time.perf_counter() - attempt_started) * 1000)
            products = flatten_shop_payload(
                payload_result,
                source="shop",
                attempt_label="fitment_vehicle_search",
                enable_bundle_pricing=self.enable_bundle_pricing,
            )
            products = [product for product in products if _is_active_product(product)]
            candidates = _fitment_candidates_from_products(products, top_k=collection_top_k)
            attempts.append(
                {
                    "label": "fitment_vehicle_search",
                    "source": "shop",
                    "params": params,
                    "latency_ms": latency_ms,
                    "status": "ok" if isinstance(payload_result, list) else "error",
                    "product_count": len(products),
                    "candidate_size_count": len(candidates),
                    "category_counts": category_counts(payload_result),
                    "error": None if isinstance(payload_result, list) else _safe_error(payload_result),
                }
            )

        candidates, preference_summary = _rank_fitment_candidates_by_preferences(
            candidates,
            size_preferences=size_preferences,
            top_k=top_k,
        )
        any_ok_attempt = any(attempt.get("status") == "ok" for attempt in attempts)
        status = "ok" if candidates else ("no_candidates" if any_ok_attempt else "error")
        presentation_ref = _fitment_presentation_ref(vehicle_query, candidates)
        return {
            "status": status,
            "vehicle_query": vehicle_query,
            "raw_vehicle_query": raw_vehicle_query if raw_vehicle_query != vehicle_query else None,
            "presentation_ref": presentation_ref if candidates else None,
            "card_runtime_insert": bool(candidates),
            "query_basis": {
                "vehicle_query": vehicle_query,
                "raw_vehicle_query": raw_vehicle_query if raw_vehicle_query != vehicle_query else None,
                "size_preferences": size_preferences,
                "soft_preferences": _normalize_string_list(payload.get("soft_preferences")),
            },
            "source": source,
            "candidate_sizes": candidates,
            "size_preference_summary": preference_summary,
            "requires_customer_confirmation": True,
            "note": (
                "Candidate sizes are extracted from search or compatibility metadata. "
                "Ask the customer to confirm the tire sidewall size before product recommendations."
            ),
            "attempted_queries": attempts,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    def discover_brand_buckets(self, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Return deterministic brand buckets by price category.

        This is a discovery aid for narrowing options. It deliberately returns
        brand/category cards, not product SKU cards, so exact product claims still
        come from `product_search`.
        """

        started = time.perf_counter()
        payload = payload or {}
        request = ProductSearchRequest.from_mapping(payload)
        request = request.normalized(canonical_brands=self._canonical_brands_for_request(request))
        top_brands = _coerce_int(payload.get("top_brands_per_bucket"), default=5, minimum=1, maximum=8)
        attempts: List[Dict[str, Any]] = []
        products_by_key: Dict[str, Dict[str, Any]] = {}
        api_calls = 0

        specs = self._brand_bucket_specs(request)
        if specs:
            for group_products, group_attempts, used_calls in self._fetch_shop_group(specs[: self.max_api_calls]):
                self._enrich_product_flags(group_products, allow_promo_lookup=True)
                api_calls += used_calls
                attempts.extend(group_attempts)
                self._merge_products(products_by_key, group_products)

        if not products_by_key and self.use_catalog_fallback:
            catalog_products, catalog_attempt = self._fetch_catalog_candidates(request)
            self._enrich_product_flags(catalog_products, allow_promo_lookup=True)
            attempts.append(catalog_attempt)
            self._merge_products(products_by_key, catalog_products)

        products = [
            product
            for product in products_by_key.values()
            if _is_active_product(product) and _product_allowed_for_brand_bucket(request, product)
            and not self._is_hidden_visibility_product(product)
        ]
        buckets = build_brand_buckets(request, products, top_brands_per_bucket=top_brands)
        bucket_cards = render_brand_bucket_cards(buckets)
        presentation_basis = json.dumps(
            {
                "filters": request.to_public_dict(),
                "choices": [card.get("choice_ref") for card in bucket_cards],
            },
            sort_keys=True,
            ensure_ascii=True,
            default=str,
        )
        presentation_ref = "price_categories_" + hashlib.sha256(
            presentation_basis.encode("utf-8")
        ).hexdigest()[:16]
        for position, card in enumerate(bucket_cards, start=1):
            card["presentation_ref"] = presentation_ref
            card["position"] = position
        legend_text = brand_bucket_legend_text(buckets)
        total_brand_count = sum(len(bucket.get("brands") or []) for bucket in buckets.values())
        suggested_next_tool = (
            "product_search"
            if bucket_cards
            and total_brand_count < 5
            and (request.budget_max is not None or request.promo_only is True or request.tire_categories)
            else None
        )
        status = "ok" if bucket_cards else "no_results"
        return {
            "status": status,
            "query_basis": {
                "normalized_filters": request.to_public_dict(),
                "top_brands_per_bucket": top_brands,
            },
            "presentation_ref": presentation_ref if bucket_cards else None,
            "choice_type": "price_category",
            "buckets": buckets,
            "bucket_cards": bucket_cards,
            "legend_text": legend_text,
            "bucket_summary": _brand_bucket_summary(buckets),
            "total_brand_count": total_brand_count,
            "result_pool_summary": _pool_summary(products),
            "requested_brand_status": self._brand_status(request.brands, products),
            "preferred_brand_status": self._brand_status(request.preferred_brands, products),
            "attempted_queries": attempts,
            "suggested_next_tool": suggested_next_tool,
            "recommended_response_strategy": (
                "Fewer than five brands meet the request; call product_search with the same filters before finalizing."
                if suggested_next_tool == "product_search"
                else
                "Preferred brand was not present in this brand/category menu. Do not state that it is unavailable from this result alone; ask for tire size or use exact product search when enough size/model context is available."
                if request.preferred_brands and self._brand_status(request.preferred_brands, products).get("missing")
                else
                "Ask which bucket, brand, or price tier the customer wants to see as actual product cards."
                if bucket_cards
                else "Ask for a confirmed tire size or broader preference before showing product options."
            ),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "api_call_count": api_calls,
        }

    def _brand_bucket_specs(self, request: ProductSearchRequest) -> List[_AttemptSpec]:
        """Return a minimal `/shop` query for bucket discovery."""

        has_supplied_scope = bool(
            request.section_width
            or request.aspect_ratio
            or request.rim_size
            or request.brands
            or request.preferred_brands
        )
        supplied = (
            self._specs_for(
                "brand_bucket_discovery",
                section_width=request.section_width,
                aspect_ratio=request.aspect_ratio,
                rim_size=request.rim_size,
                brands=request.brands,
            )
            if has_supplied_scope
            else []
        )
        preferred_supplied = (
            self._specs_for(
                "brand_bucket_preferred_brand_discovery",
                section_width=request.section_width,
                aspect_ratio=request.aspect_ratio,
                rim_size=request.rim_size,
                brands=request.preferred_brands,
            )
            if request.preferred_brands and not request.brands
            else []
        )
        if supplied or preferred_supplied:
            return [*preferred_supplied, *supplied]
        if request.rim_size:
            preferred_rim = (
                self._specs_for(
                    "brand_bucket_preferred_brand_rim_only",
                    section_width=None,
                    aspect_ratio=None,
                    rim_size=request.rim_size,
                    brands=request.preferred_brands,
                )
                if request.preferred_brands
                else []
            )
            generic_rim = self._specs_for(
                "brand_bucket_rim_only",
                section_width=None,
                aspect_ratio=None,
                rim_size=request.rim_size,
                brands=request.brands,
            )
            return [*preferred_rim, *generic_rim]
        preferred_sample = (
            self._specs_for(
                "brand_bucket_preferred_brand_catalog_sample",
                section_width=None,
                aspect_ratio=None,
                rim_size=None,
                brands=request.preferred_brands,
            )
            if request.preferred_brands
            else []
        )
        generic_sample = self._specs_for(
            "brand_bucket_catalog_sample",
            section_width=None,
            aspect_ratio=None,
            rim_size=None,
            brands=request.brands,
        )
        return [*preferred_sample, *generic_sample]

    def _fetch_compatible_fitment_fallback(
        self,
        payload: Dict[str, Any],
        *,
        vehicle_query: str,
        top_k: int,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Use the legacy compatible-size endpoint when shop search has no sizes."""

        car_make, car_model = _fitment_vehicle_parts(payload, vehicle_query)
        if not (car_make or car_model):
            return [], []
        raw_year = payload.get("car_year")
        year = _coerce_int(raw_year, default=0, minimum=0, maximum=9999) if raw_year not in (None, "") else 0
        year_options = [0]
        if year:
            year_options.append(year)
        attempts: List[Dict[str, Any]] = []
        for year_option in year_options:
            params = {
                "car_make": car_make or "",
                "car_model": car_model.title() if car_model else "",
            }
            if year_option:
                params["car_year"] = str(year_option)
            started = time.perf_counter()
            try:
                raw = self._http.get_json("/car_tire_sizes", params=params)
            except TypeError:
                raw = self._http.get_json("/car_tire_sizes")
            latency_ms = int((time.perf_counter() - started) * 1000)
            rows = raw.get("products") if isinstance(raw, dict) and "products" in raw else raw
            candidates = _fitment_candidates_from_size_rows(rows, top_k=top_k)
            attempts.append(
                {
                    "label": "fitment_compatible_endpoint",
                    "source": "car_tire_sizes",
                    "params": params,
                    "latency_ms": latency_ms,
                    "status": "ok" if isinstance(rows, list) else "error",
                    "candidate_size_count": len(candidates),
                    "error": None if isinstance(rows, list) else _safe_error(raw),
                }
            )
            if candidates:
                return candidates, attempts
        return [], attempts

    def _build_attempt_groups(self, request: ProductSearchRequest) -> List[List[_AttemptSpec]]:
        """Return ordered endpoint attempts, grouped by recovery level."""

        groups: List[List[_AttemptSpec]] = []
        primary_rim = request.rim_size
        alternate_rims = [rim for rim in rim_query_variants(primary_rim) if rim != primary_rim]

        if (
            request.model_or_pattern
            and not any([request.section_width, request.aspect_ratio, primary_rim, request.brands])
            and not installment_filters_requested(request)
        ):
            return []

        supplied = self._specs_for(
            "supplied_filters",
            section_width=request.section_width,
            aspect_ratio=request.aspect_ratio,
            rim_size=primary_rim,
            brands=request.brands,
        )
        if supplied:
            groups.append(supplied)

        if (
            request.section_width
            and request.aspect_ratio
            and primary_rim
            and request.brands
        ):
            groups.append(
                self._specs_for(
                    "exact_size_base",
                    section_width=request.section_width,
                    aspect_ratio=request.aspect_ratio,
                    rim_size=primary_rim,
                    brands=[],
                )
            )

        if alternate_rims:
            for rim in alternate_rims:
                specs = self._specs_for(
                    "rim_family_variant",
                    section_width=request.section_width,
                    aspect_ratio=request.aspect_ratio,
                    rim_size=rim,
                    brands=request.brands,
                )
                if specs:
                    groups.append(specs)

        if request.section_width and request.aspect_ratio and primary_rim:
            groups.append(
                self._specs_for(
                    "width_rim_no_aspect",
                    section_width=request.section_width,
                    aspect_ratio=None,
                    rim_size=primary_rim,
                    brands=request.brands,
                )
            )

        if primary_rim and request.brands:
            groups.append(
                self._specs_for(
                    "rim_brand",
                    section_width=None,
                    aspect_ratio=None,
                    rim_size=primary_rim,
                    brands=request.brands,
                )
            )

        if request.brands:
            groups.append(
                self._specs_for(
                    "brand_only",
                    section_width=None,
                    aspect_ratio=None,
                    rim_size=None,
                    brands=request.brands,
                )
            )

        if primary_rim:
            groups.append(
                self._specs_for(
                    "rim_only",
                    section_width=None,
                    aspect_ratio=None,
                    rim_size=primary_rim,
                    brands=[],
                )
            )

        if request.section_width and primary_rim:
            groups.append(
                self._specs_for(
                    "width_rim",
                    section_width=request.section_width,
                    aspect_ratio=None,
                    rim_size=primary_rim,
                    brands=[],
                )
            )

        if not groups and request.model_or_pattern and not installment_filters_requested(request):
            return []

        if not groups or request.model_or_pattern:
            groups.append(
                self._specs_for(
                    "broad_discovery",
                    section_width=None,
                    aspect_ratio=None,
                    rim_size=None,
                    brands=request.brands,
                )
            )

        return _dedupe_groups(groups)

    def _specs_for(
        self,
        label: str,
        *,
        section_width: Optional[str],
        aspect_ratio: Optional[str],
        rim_size: Optional[str],
        brands: Sequence[str],
    ) -> List[_AttemptSpec]:
        brand_param_sets = brand_query_values(brands)
        specs: List[_AttemptSpec] = []
        for brand_value in brand_param_sets:
            params: Dict[str, Any] = {"sn": "y", "v": 1}
            if section_width:
                params["section_width"] = section_width
            if aspect_ratio:
                params["aspect_ratio"] = aspect_ratio
            if rim_size:
                params["rim_size"] = rim_size
            if brand_value:
                params["b"] = brand_value
            specs.append(_AttemptSpec(label=label, params=params))
        return specs

    def _fetch_shop_attempt(self, spec: _AttemptSpec) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
        products: List[Dict[str, Any]] = []
        attempts: List[Dict[str, Any]] = []
        previous_keys: set[str] = set()
        calls = 0
        for page in range(1, self.max_pages_per_attempt + 1):
            params = dict(spec.params)
            params["page"] = page
            started = time.perf_counter()
            payload = self._http.post_json("/shop", params=params, json_data=None)
            latency_ms = int((time.perf_counter() - started) * 1000)
            calls += 1
            page_products = flatten_shop_payload(
                payload,
                source="shop",
                attempt_label=spec.label,
                enable_bundle_pricing=self.enable_bundle_pricing,
            )
            page_keys = {product_key(item) for item in page_products if product_key(item)}
            new_keys = page_keys.difference(previous_keys)
            attempts.append(
                {
                    "label": spec.label,
                    "source": spec.source,
                    "params": params,
                    "latency_ms": latency_ms,
                    "status": "ok" if isinstance(payload, list) else "error",
                    "product_count": len(page_products),
                    "new_product_count": len(new_keys),
                    "category_counts": category_counts(payload),
                    "brands_sample": sorted({str(p.get("brand") or "") for p in page_products if p.get("brand")})[:12],
                    "models_sample": [str(p.get("model") or "") for p in page_products[:5] if p.get("model")],
                    "duplicate_page": bool(page > 1 and not new_keys and page_keys),
                    "error": None if isinstance(payload, list) else _safe_error(payload),
                }
            )
            products.extend(page_products)
            if page > 1 and not new_keys:
                break
            previous_keys.update(page_keys)
        return products, attempts, calls

    def _fetch_shop_group(
        self,
        specs: Sequence[_AttemptSpec],
    ) -> List[Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]]:
        if not specs:
            return []
        if len(specs) == 1:
            return [self._fetch_shop_attempt(specs[0])]
        workers = min(len(specs), 4)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            return list(executor.map(self._fetch_shop_attempt, specs))

    def _fetch_catalog_candidates(self, request: ProductSearchRequest) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        started = time.perf_counter()
        products, catalog_meta = self._load_catalog_products()
        latency_ms = int((time.perf_counter() - started) * 1000)
        if request.brands:
            products = [p for p in products if str(p.get("brand") or "").upper() in set(request.brands)]
        if request.rim_size:
            products = [p for p in products if rim_matches(request.rim_size, p.get("rim_size"))]
        if request.section_width:
            products = [p for p in products if str(p.get("section_width") or "") == str(request.section_width)]
        if request.aspect_ratio:
            products = [p for p in products if str(p.get("aspect_ratio") or "") == str(request.aspect_ratio)]
        if request.model_or_pattern:
            products = refine_model_products(request, products)
        return products, {
            "label": "catalog_fallback",
            "source": "product_list",
            "params": {"local_filters": request.to_public_dict()},
            "latency_ms": latency_ms,
            "status": catalog_meta.get("status"),
            "cache_status": catalog_meta.get("cache_status"),
            "cache_ttl_seconds": self.catalog_cache_ttl_seconds if self.use_catalog_cache else 0,
            "product_count": len(products),
            "new_product_count": len(products),
            "category_counts": {},
            "brands_sample": sorted({str(p.get("brand") or "") for p in products if p.get("brand")})[:12],
            "models_sample": [str(p.get("model") or "") for p in products[:5] if p.get("model")],
            "duplicate_page": False,
            "error": catalog_meta.get("error"),
        }

    def _load_catalog_products(self) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        cache_key = self._catalog_cache_key()
        now = time.time()
        if self.use_catalog_cache and self.catalog_cache_ttl_seconds > 0:
            cached = self._catalog_cache.get(cache_key)
            if cached and now - cached[0] <= self.catalog_cache_ttl_seconds:
                return [dict(product) for product in cached[1]], {"status": "ok", "cache_status": "hit"}

        payload = self._http.get_json("/product_list")
        if not isinstance(payload, list):
            return [], {"status": "error", "cache_status": "miss", "error": _safe_error(payload)}

        products = flatten_product_list(
            payload,
            source="product_list",
            attempt_label="catalog_fallback",
            enable_bundle_pricing=self.enable_bundle_pricing,
        )
        if self.use_catalog_cache and self.catalog_cache_ttl_seconds > 0:
            self._catalog_cache[cache_key] = (now, [dict(product) for product in products])
            cache_status = "miss_stored"
        else:
            cache_status = "disabled"
        return products, {"status": "ok", "cache_status": cache_status}

    def _catalog_cache_key(self) -> Tuple[str, bool]:
        config = getattr(self._http, "_config", None)
        base_url = str(getattr(config, "base_url", "") or "")
        if not base_url:
            base_url = (
                f"{self._http.__class__.__module__}.{self._http.__class__.__name__}:"
                f"{self._catalog_cache_client_token(self._http)}"
            )
        return (base_url.rstrip("/"), self.enable_bundle_pricing)

    @classmethod
    def _catalog_cache_client_token(cls, client: Any) -> str:
        try:
            token = cls._catalog_cache_client_tokens.get(client)
            if token:
                return token
            cls._catalog_cache_token_counter += 1
            token = f"client_{cls._catalog_cache_token_counter}"
            cls._catalog_cache_client_tokens[client] = token
            return token
        except TypeError:
            return f"id_{id(client)}"

    @classmethod
    def clear_catalog_cache(cls) -> None:
        cls._catalog_cache.clear()
        cls._visibility_denylist_cache.clear()
        cls._catalog_cache_client_tokens = weakref.WeakKeyDictionary()
        cls._catalog_cache_token_counter = 0

    def warm_catalog_cache(self) -> Dict[str, Any]:
        started = time.perf_counter()
        products, meta = self._load_catalog_products()
        return {
            "status": meta.get("status"),
            "cache_status": meta.get("cache_status"),
            "product_count": len(products),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "cache_ttl_seconds": self.catalog_cache_ttl_seconds if self.use_catalog_cache else 0,
            "error": meta.get("error"),
        }

    def _merge_products(self, target: Dict[str, Dict[str, Any]], products: Iterable[Dict[str, Any]]) -> None:
        for product in products:
            key = product_key(product)
            if not key:
                continue
            existing = target.get(key)
            if existing is None:
                target[key] = product
                continue
            had_shop_source = "shop" in existing.get("sources", [])
            existing_sources = set(existing.get("sources") or [])
            for source in product.get("sources") or []:
                existing_sources.add(source)
            existing["sources"] = sorted(existing_sources)
            # Prefer /shop values for prices and availability.
            if "shop" in product.get("sources", []) and not had_shop_source:
                target[key] = {**existing, **product, "sources": sorted(existing_sources)}

    def _should_use_catalog_fallback(
        self,
        request: ProductSearchRequest,
        products: Iterable[Dict[str, Any]],
        attempts: Sequence[Dict[str, Any]],
        api_calls: int,
    ) -> bool:
        if not self.use_catalog_fallback:
            return False
        if api_calls >= self.max_api_calls and products:
            return False
        ranked = self._rank_products(request, products)
        summary = _pool_summary(ranked)
        if request.model_or_pattern and summary.get("exact", 0) == 0 and summary.get("near_exact", 0) == 0:
            return True
        if has_catalog_refiner_request(request) and summary.get("exact", 0) == 0:
            return True
        if not products and (request.model_or_pattern or request.brands):
            return True
        if not attempts:
            return True
        return False

    def _should_fetch_presentation_alternatives(
        self,
        request: ProductSearchRequest,
        products: Iterable[Dict[str, Any]],
        api_calls: int,
    ) -> bool:
        if api_calls >= self.max_api_calls:
            return False
        if not (request.brands and request.rim_size):
            return False
        if request.brand_match_mode == "strict":
            return False
        ranked = self._rank_products(request, products)
        if not ranked:
            return True
        if _explicit_product_alternatives_allowed(request):
            brands = {
                str(product.get("brand") or "").upper()
                for product in ranked
                if product.get("brand")
            }
            return len(brands) < 2
        requested_brands = set(request.brands)
        if any(
            str(product.get("brand") or "").upper() in requested_brands
            and _matches_requested_full_size(request, product)
            and presentation_preferences_match(request, product)
            for product in ranked
        ):
            return False
        brands = {str(product.get("brand") or "").upper() for product in ranked if product.get("brand")}
        if len(brands) >= 2:
            return False
        return True

    def _fetch_presentation_alternative_candidates(
        self,
        request: ProductSearchRequest,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        started = time.perf_counter()
        products, catalog_meta = self._load_catalog_products()
        latency_ms = int((time.perf_counter() - started) * 1000)
        if request.rim_size:
            products = [p for p in products if rim_matches(request.rim_size, p.get("rim_size"))]
        if request.section_width:
            products = [p for p in products if str(p.get("section_width") or "") == str(request.section_width)]
        if request.aspect_ratio:
            products = [p for p in products if str(p.get("aspect_ratio") or "") == str(request.aspect_ratio)]
        return products[:120], {
            "label": "presentation_catalog_alternatives",
            "source": "product_list",
            "params": {"local_filters": {**request.to_public_dict(), "brands": []}},
            "latency_ms": latency_ms,
            "status": catalog_meta.get("status"),
            "cache_status": catalog_meta.get("cache_status"),
            "cache_ttl_seconds": self.catalog_cache_ttl_seconds if self.use_catalog_cache else 0,
            "product_count": len(products),
            "new_product_count": len(products),
            "category_counts": {},
            "brands_sample": sorted({str(p.get("brand") or "") for p in products if p.get("brand")})[:12],
            "models_sample": [str(p.get("model") or "") for p in products[:5] if p.get("model")],
            "duplicate_page": False,
            "error": catalog_meta.get("error"),
        }

    def _has_enough_strong_results(self, request: ProductSearchRequest, ranked: Sequence[Dict[str, Any]]) -> bool:
        if not ranked:
            return False
        summary = _pool_summary(ranked)
        target = min(request.top_k, 3)
        specific_size = bool(request.section_width and request.aspect_ratio and request.rim_size)
        specific_search = specific_size and bool(
            request.brands
            or request.model_or_pattern
            or request.budget_max is not None
            or request.promo_only is True
            or request.ev_compatible is not None
            or request.gulong_guarantee_only is True
            or bool(request.gulong_guarantee_tiers)
            or bool(request.origins)
            or bool(request.warranty_years)
            or bool(request.tire_categories)
            or bool(request.terrain_types)
            or request.availability in {"in_stock", "pre_order"}
            or request.installment_only is True
            or bool(request.installment_banks)
            or bool(request.installment_months)
            or request.installment_max_interest is not None
        )
        # If the user gave a highly specific request and we already found a
        # true exact hit, fetching broad fallbacks makes the tool slower and can
        # confuse the response strategy.
        if specific_search and summary.get("exact", 0) > 0:
            return True
        if summary.get("exact", 0) >= target:
            return True
        if not request.aspect_ratio and summary.get("near_exact", 0) >= target:
            return True
        return False

    def _rank_products(
        self,
        request: ProductSearchRequest,
        products: Iterable[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        ranked: List[Dict[str, Any]] = []
        visibility_denylist = self._visibility_denylist()
        for product in products:
            if not _is_active_product(product):
                continue
            if _hidden_visibility_reason(product, visibility_denylist):
                continue
            if product_matches_exclusions(request, product):
                continue
            scored = dict(product)
            match = score_product(request, product)
            scored["match"] = match
            scored["item_ref"] = f"prod_{len(ranked) + 1}"
            ranked.append(scored)
        ranked.sort(key=lambda product: self._sort_key(request, product))
        for index, product in enumerate(ranked, start=1):
            product["item_ref"] = f"prod_{index}"
        return ranked

    def _is_hidden_visibility_product(self, product: Dict[str, Any]) -> bool:
        denylist = self._visibility_denylist()
        return _hidden_visibility_reason(product, denylist) is not None

    def _visibility_filter_summary(self, products: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        denylist = self._visibility_denylist()
        slugs = denylist.get("slugs") or set()
        product_ids = denylist.get("product_ids") or set()
        filtered: List[Dict[str, Any]] = []
        for product in products:
            reason = _hidden_visibility_reason(product, denylist)
            if not reason:
                continue
            filtered.append(
                {
                    "slug": product.get("slug"),
                    "product_id": product.get("product_id"),
                    "brand": product.get("brand"),
                    "reason": reason,
                }
            )
        summary = {
            "applied": bool(slugs or product_ids),
            "source": denylist.get("source"),
            "version": denylist.get("version"),
            "slug_count": len(slugs),
            "product_id_count": len(product_ids),
            "filtered_count": len(filtered),
        }
        if filtered:
            summary["filtered_slugs_sample"] = _ordered_unique(item.get("slug") for item in filtered)[:12]
            summary["filtered_brands_sample"] = _ordered_unique(item.get("brand") for item in filtered)[:12]
        if denylist.get("error"):
            summary["error"] = denylist.get("error")
        return summary

    def _visibility_denylist(self) -> Dict[str, Any]:
        if self._visibility_denylist_override is not None:
            return _normalize_visibility_denylist(
                self._visibility_denylist_override,
                source="constructor_override",
            )

        path_text = str(os.getenv(PRODUCT_VISIBILITY_DENYLIST_PATH_ENV) or DEFAULT_PRODUCT_VISIBILITY_DENYLIST_PATH).strip()
        slugs_env = str(os.getenv(PRODUCT_VISIBILITY_DENYLIST_SLUGS_ENV) or "")
        ids_env = str(os.getenv(PRODUCT_VISIBILITY_DENYLIST_PRODUCT_IDS_ENV) or "")
        cache_key = (path_text, slugs_env, ids_env)
        cached = self._visibility_denylist_cache.get(cache_key)
        if cached is not None:
            return cached

        payload: Dict[str, Any] = {}
        source = path_text or "env_only"
        error = ""
        if path_text:
            path = Path(path_text)
            if path.exists():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8-sig"))
                    payload = loaded if isinstance(loaded, dict) else {}
                except Exception as exc:
                    error = f"visibility denylist load failed: {exc}"
            else:
                source = "env_only"

        denylist = _normalize_visibility_denylist(payload, source=source)
        denylist["slugs"].update(_normalize_slug_list(slugs_env.split(",")))
        denylist["product_ids"].update(_normalize_product_id_list(ids_env.split(",")))
        if error:
            denylist["error"] = error
        self._visibility_denylist_cache[cache_key] = denylist
        return denylist

    def _sort_key(self, request: ProductSearchRequest, product: Dict[str, Any]) -> Tuple[Any, ...]:
        match = product.get("match") or {}
        price = _coerce_float(product.get("price")) or 0.0
        pre_order = 1 if product.get("pre_order") else 0
        if request.sort == "price_high_to_low":
            price_sort = -price
        else:
            price_sort = price
        return (
            -int(match.get("match_score") or 0),
            pre_order,
            price_sort,
            str(product.get("brand") or ""),
            str(product.get("model") or ""),
        )

    def _public_product(self, product: Dict[str, Any]) -> Dict[str, Any]:
        keys = [
            "item_ref",
            "product_id",
            "slug",
            "brand",
            "model",
            "pattern",
            "size",
            "section_width",
            "aspect_ratio",
            "rim_size",
            "category",
            "price",
            "price_text",
            "list_price",
            "list_price_text",
            "promo_label",
            "promo_text",
            "product_discount_label",
            "product_discount_text",
            "product_discount_amount",
            "voucher_text",
            "voucher_amount",
            "dot",
            "origin",
            "warranty",
            "warranty_years",
            "terrain_types",
            "installments",
            "installment_text",
            "installment_min_interest",
            "ev_compatible",
            "gulong_guarantee",
            "status_id",
            "buy3get1_eligible",
            "pre_order",
            "total_price",
            "total_price_text",
            "pricing_basis",
            "bundle_pricing",
            "url",
            "sources",
            "match",
        ]
        return {key: product.get(key) for key in keys if product.get(key) not in (None, "", [])}

    def _build_facets(self, ranked: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        brands: Dict[str, int] = {}
        sizes: Dict[str, int] = {}
        categories: Dict[str, int] = {}
        origins: Dict[str, int] = {}
        warranty_years: Dict[str, int] = {}
        terrain_types: Dict[str, int] = {}
        availability: Dict[str, int] = {}
        installment_banks: Dict[str, int] = {}
        installment_months: Dict[str, int] = {}
        price_values: List[float] = []
        for product in ranked:
            _count(brands, product.get("brand"))
            _count(sizes, product.get("size"))
            _count(categories, product.get("category"))
            _count(origins, product.get("origin"))
            if product.get("warranty_years") is not None:
                _count(warranty_years, f"{product.get('warranty_years')} years")
            for terrain_type in product.get("terrain_types") or []:
                _count(terrain_types, terrain_type)
            _count(availability, "pre_order" if product.get("pre_order") else "in_stock")
            for installment in product.get("installments") or []:
                if not isinstance(installment, dict):
                    continue
                _count(installment_banks, installment.get("bank_name"))
                if installment.get("months_to_pay") not in (None, ""):
                    _count(installment_months, f"{installment.get('months_to_pay')} months")
            price = _coerce_float(product.get("price"))
            if price is not None:
                price_values.append(price)
        return {
            "brands": _top_counts(brands),
            "sizes": _top_counts(sizes),
            "categories": _top_counts(categories),
            "origins": _top_counts(origins),
            "warranty_years": _top_counts(warranty_years),
            "terrain_types": _top_counts(terrain_types),
            "availability": _top_counts(availability),
            "installment_banks": _top_counts(installment_banks),
            "installment_months": _top_counts(installment_months),
            "price": {
                "min": min(price_values) if price_values else None,
                "max": max(price_values) if price_values else None,
            },
        }

    def _brand_status(
        self,
        requested_brands: Sequence[str],
        ranked: Sequence[Dict[str, Any]],
        *,
        presented: Optional[Sequence[Dict[str, Any]]] = None,
        strict_active_filters: bool = False,
    ) -> Dict[str, Any]:
        requested = {str(brand or "").upper() for brand in requested_brands or [] if str(brand or "").strip()}
        if not requested:
            return {"requested": [], "matched": [], "missing": []}

        all_matched = {
            str(product.get("brand") or "").upper()
            for product in ranked
            if str(product.get("brand") or "").upper() in requested
        }
        matched = all_matched
        if strict_active_filters:
            matched = {
                str(product.get("brand") or "").upper()
                for product in ranked
                if str(product.get("brand") or "").upper() in requested
                and str((product.get("match") or {}).get("tier") or "") in {"exact", "near_exact"}
            }
        result = {
            "requested": sorted(requested),
            "matched": sorted(matched),
            "missing": sorted(requested.difference(matched)),
        }
        if presented is not None:
            presented_brands = {
                str(product.get("brand") or "").upper()
                for product in presented
                if str(product.get("brand") or "").upper() in requested
            }
            result["presented"] = sorted(presented_brands)
            result["not_presented"] = sorted(matched.difference(presented_brands))
        if strict_active_filters:
            outside_active_filters = sorted(all_matched.difference(matched))
            if outside_active_filters:
                result["available_outside_requested_filters"] = outside_active_filters
                result["outside_requested_filters_reasons"] = [
                    {
                        "brand": brand,
                        "reason": "brand appears only in broader partial results, not in products matching the requested size/filter set",
                    }
                    for brand in outside_active_filters
                ]
        return result

    def _model_pattern_status(self, request: ProductSearchRequest, ranked: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        if not request.model_or_pattern:
            return {"requested": None, "used": False}
        scores = [
            model_match_score_for_product(request.model_or_pattern, product)
            for product in ranked
        ]
        best = max(scores) if scores else 0.0
        threshold = model_match_threshold(request.model_or_pattern)
        suggestions = [
            {"model": product.get("model"), "score": round(model_match_score_for_product(request.model_or_pattern, product), 3)}
            for product in ranked[:5]
            if product.get("model")
        ]
        return {
            "requested": request.model_or_pattern,
            "used": best >= threshold,
            "best_score": round(best, 3),
            "match_count": sum(1 for score in scores if score >= threshold),
            "suggestions": suggestions[:3],
        }

    def _budget_status(self, request: ProductSearchRequest, ranked: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        if request.budget_max is None:
            return {"requested": None}
        within = 0
        near = 0
        over = 0
        for product in ranked:
            price_basis = budget_price_basis(request, product)
            if price_basis is None:
                continue
            if price_basis <= request.budget_max:
                within += 1
            elif price_basis <= request.budget_max * 1.15:
                near += 1
            else:
                over += 1
        return {
            "requested": request.budget_max,
            "scope": request.budget_scope,
            "within_count": within,
            "near_count": near,
            "over_count": over,
        }

    def _promo_brand_set(self) -> set[str]:
        """Return brands eligible for Buy 3 Get 1 promo according to API truth."""

        if self._promo_brands is not None:
            return self._promo_brands
        payload = self._http.get_json("/promo_brands")
        brands: set[str] = set()
        if isinstance(payload, list):
            brands = {
                str(item.get("brand") or "").strip().upper()
                for item in payload
                if isinstance(item, dict) and item.get("brand")
            }
        self._promo_brands = {brand for brand in brands if brand}
        return self._promo_brands

    def _enrich_product_flags(self, products: List[Dict[str, Any]], *, allow_promo_lookup: bool) -> None:
        """Attach promo and total-price fields that require external lookup."""

        needs_promo_lookup = allow_promo_lookup and bool(products)
        promo_brands = self._promo_brand_set() if needs_promo_lookup else set()
        for product in products:
            brand = str(product.get("brand") or "").strip().upper()
            buy3get1 = brand in promo_brands
            product["buy3get1_eligible"] = buy3get1
            price = _coerce_float(product.get("price"))
            if buy3get1 and price:
                total = round(price * 3, 2)
                product["promo_label"] = "Buy 3 Get 1 FREE"
                product["promo_text"] = f"PHP {total:,.2f} {_tire_total_suffix(4)}"
                product["bundle_pricing"] = {
                    "enabled": False,
                    "base_unit_price": price,
                    "tiers": [],
                    "source": "disabled_for_buy3get1",
                }
            qty = 4
            total_price = effective_total_price(product, qty)
            if total_price is not None:
                product["total_price"] = total_price
                product["total_price_text"] = f"PHP {total_price:,.2f} {_tire_total_suffix(qty)}"
                product["pricing_basis"] = pricing_basis(product, qty)

    def _no_match_reasons(
        self,
        request: ProductSearchRequest,
        summary: Dict[str, int],
        attempts: Sequence[Dict[str, Any]],
    ) -> List[str]:
        if summary.get("total", 0) > 0:
            reasons = []
            if summary.get("exact", 0) == 0:
                reasons.append("no product satisfied every requested filter")
            if request.brands and summary.get("same_rim_requested_brand", 0) == 0:
                reasons.append("no requested-brand product found for the strongest size/rim filter")
            return reasons
        reasons = ["no products returned after bounded search attempts"]
        if any((attempt.get("product_count") or 0) == 0 for attempt in attempts):
            reasons.append("one or more exact attempts returned zero products")
        return reasons


def flatten_shop_payload(
    payload: Any,
    *,
    source: str,
    attempt_label: str,
    enable_bundle_pricing: bool = True,
) -> List[Dict[str, Any]]:
    """Flatten `/shop` category payload into normalized products."""

    if not isinstance(payload, list):
        return []
    products: List[Dict[str, Any]] = []
    for category in payload:
        if not isinstance(category, dict):
            continue
        category_name = str(category.get("name") or category.get("tire_type") or "").strip()
        for raw in category.get("products", []) or []:
            if not isinstance(raw, dict):
                continue
            products.append(
                normalize_product(
                    raw,
                    category_name=category_name,
                    source=source,
                    attempt_label=attempt_label,
                    enable_bundle_pricing=enable_bundle_pricing,
                )
            )
    return products


def flatten_product_list(
    payload: Any,
    *,
    source: str,
    attempt_label: str,
    enable_bundle_pricing: bool = True,
) -> List[Dict[str, Any]]:
    """Normalize `/product_list` items into the same product shape."""

    if not isinstance(payload, list):
        return []
    return [
        normalize_product(
            raw,
            category_name=str(raw.get("tire_type") or ""),
            source=source,
            attempt_label=attempt_label,
            enable_bundle_pricing=enable_bundle_pricing,
        )
        for raw in payload
        if isinstance(raw, dict)
    ]


def _normalize_visibility_denylist(payload: Dict[str, Any], *, source: str) -> Dict[str, Any]:
    """Normalize hidden product config into constant-time lookup sets."""

    slug_values = (
        payload.get("hidden_product_slugs")
        or payload.get("product_slugs")
        or payload.get("slugs")
        or []
    )
    id_values = (
        payload.get("hidden_product_ids")
        or payload.get("product_ids")
        or payload.get("ids")
        or []
    )
    return {
        "slugs": set(_normalize_slug_list(slug_values)),
        "product_ids": set(_normalize_product_id_list(id_values)),
        "source": str(payload.get("source") or source or "").strip() or "unknown",
        "version": str(payload.get("version") or payload.get("generated_at") or "").strip() or None,
    }


def _normalize_slug_list(values: Any) -> List[str]:
    if isinstance(values, str):
        raw_values = re.split(r"[\s,]+", values)
    elif isinstance(values, list):
        raw_values = values
    else:
        raw_values = []
    return _ordered_unique(str(value or "").strip().lower() for value in raw_values if str(value or "").strip())


def _normalize_product_id_list(values: Any) -> List[int]:
    if isinstance(values, str):
        raw_values = re.split(r"[\s,]+", values)
    elif isinstance(values, list):
        raw_values = values
    else:
        raw_values = []
    output: List[int] = []
    for value in raw_values:
        try:
            if value not in (None, ""):
                output.append(int(value))
        except (TypeError, ValueError):
            continue
    return _ordered_unique(output)


def _hidden_visibility_reason(product: Dict[str, Any], denylist: Dict[str, Any]) -> Optional[str]:
    slug = str(product.get("slug") or "").strip().lower()
    if slug and slug in (denylist.get("slugs") or set()):
        return "hidden_product_slug"
    product_ids = denylist.get("product_ids") or set()
    for key in ("product_id", "id", "catalog_product_id"):
        value = product.get(key)
        try:
            if value not in (None, "") and int(value) in product_ids:
                return "hidden_product_id"
        except (TypeError, ValueError):
            continue
    return None


def normalize_product(
    raw: Dict[str, Any],
    *,
    category_name: str,
    source: str,
    attempt_label: str,
    enable_bundle_pricing: bool = True,
) -> Dict[str, Any]:
    """Return compact product data used by the runner and model output."""

    brand = str(raw.get("make") or raw.get("brand") or "").strip().upper()
    model = str(raw.get("model") or raw.get("display_name") or "").strip()
    section = normalize_section_width(raw.get("section_width"))
    aspect = _normalize_numeric_text(raw.get("aspect_ratio"))
    rim = _clean_optional(raw.get("rim_size"))
    rim = str(rim or "").strip().upper() or None
    price = _price_from_product(raw)
    list_price = _coerce_float(raw.get("srp"))
    category = category_name or str(raw.get("tire_type") or "").strip()
    slug = _clean_optional(raw.get("slug"))
    pattern = _clean_optional(raw.get("pattern") or raw.get("tread_pattern"))
    url, product_link_status = _validated_product_url(slug, pattern=pattern)
    promo_label, promo_text = _promo_fields(raw, price)
    discount_label, discount_text, discount_amount = _product_discount_fields(raw)
    sale_discount_amount = _sale_price_discount_amount(raw)
    origin = _clean_optional(raw.get("origin_country") or raw.get("origin"))
    warranty = _manufacturer_warranty_text(raw, brand)
    dot = _dot_value(raw)
    installments = normalize_installments(raw.get("installments"))
    installment_text, installment_min_interest = installment_summary(installments)
    image_url = normalize_product_image_url(
        raw.get("default_image")
        or raw.get("image_do")
        or raw.get("image_url")
        or raw.get("product_image_url")
        or raw.get("image")
    )
    product = {
        "product_id": raw.get("id"),
        "slug": slug,
        "brand": brand,
        "model": model,
        "pattern": pattern,
        "size": format_size(section, aspect, rim) or _size_from_model(model),
        "section_width": section,
        "aspect_ratio": aspect,
        "rim_size": rim,
        "category": category,
        "price": price,
        "price_text": f"PHP {price:,.2f} per tire" if price else None,
        "list_price": list_price if list_price and price and list_price > price else None,
        "list_price_text": f"PHP {list_price:,.2f} per tire" if list_price and price and list_price > price else None,
        "promo_label": promo_label,
        "promo_text": promo_text,
        "product_discount_label": discount_label,
        "product_discount_text": discount_text,
        "product_discount_amount": discount_amount,
        "sale_tag": _truthy(raw.get("sale_tag")),
        "sale_price_discount_amount": sale_discount_amount,
        "sale_price_discount_text": (
            f"PHP {sale_discount_amount:,.2f} off/tire already reflected in unit price"
            if sale_discount_amount
            else None
        ),
        "voucher_text": _voucher_text(raw),
        "voucher_amount": _voucher_amount(raw),
        "dot": dot,
        "bundle_pricing": build_bundle_pricing(raw, price, enabled=enable_bundle_pricing),
        "origin": origin,
        "warranty": warranty,
        "warranty_years": infer_warranty_years(warranty),
        "terrain_types": infer_terrain_types(raw, brand=brand, model=model, category=category),
        "installments": installments,
        "installment_text": installment_text,
        "installment_min_interest": installment_min_interest,
        "ev_compatible": _truthy(raw.get("ev_tire")),
        "gulong_guarantee": raw.get("is_gulong_guarantee"),
        "promo_tag": _truthy(raw.get("promo_tag")),
        "pre_order": _truthy(raw.get("pre_order")),
        "activity": raw.get("activity"),
        "status_id": raw.get("status_id"),
        "stock": raw.get("stock"),
        "url": url,
        "product_link_status": product_link_status,
        "image_url": image_url,
        "sources": [source],
        "attempt_labels": [attempt_label],
        "description": _clean_optional(raw.get("description")),
        "features": _clean_optional(raw.get("features")),
        "raw_key": product_key(raw),
    }
    attach_search_fields(product)
    return product


def _validated_product_url(
    slug: Any,
    *,
    pattern: Any = None,
) -> Tuple[Optional[str], str]:
    """Suppress any catalog URL whose slug contradicts structured identity.

    A stale link must not discard otherwise useful product, pricing, or image
    evidence.  This validator therefore fails soft at the action boundary for
    every catalog card rather than special-casing a brand, model, or SKU.
    """

    slug_text = str(slug or "").strip()
    if not slug_text:
        return None, "missing_slug"
    pattern_tokens = [
        token
        for token in _normalize_match_text(pattern).split()
        if len(token) > 1 or token.isdigit()
    ]
    if pattern_tokens:
        slug_tokens = set(_normalize_match_text(slug_text).split())
        coded_tokens = [
            token for token in pattern_tokens if any(character.isdigit() for character in token)
        ]
        lexical_tokens = [token for token in pattern_tokens if len(token) >= 4]
        coded_mismatch = any(token not in slug_tokens for token in coded_tokens)
        no_identity_overlap = bool(lexical_tokens) and not any(
            token in slug_tokens for token in lexical_tokens
        )
        no_short_pattern_overlap = (
            not coded_tokens
            and not lexical_tokens
            and not any(token in slug_tokens for token in pattern_tokens)
        )
        if coded_mismatch or no_identity_overlap or no_short_pattern_overlap:
            return None, "suppressed_pattern_slug_mismatch"
    return f"https://gulong.ph/product/{slug_text}", "matched"


def normalize_product_image_url(value: Any) -> Optional[str]:
    """Return a stable public Gulong catalog image URL, or ``None``."""

    if isinstance(value, dict):
        value = value.get("url") or value.get("src")
    url = str(value or "").strip()
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = str(parsed.hostname or "").strip().casefold()
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or host not in TRUSTED_PRODUCT_IMAGE_HOSTS
        or parsed.username
        or parsed.password
    ):
        return None
    return url


def score_product(request: ProductSearchRequest, product: Dict[str, Any]) -> Dict[str, Any]:
    """Score a product and return explainable match evidence."""

    passed: List[str] = []
    missed: List[str] = []
    soft: List[str] = []
    score = 0

    if request.rim_size:
        if rim_matches(request.rim_size, product.get("rim_size")):
            passed.append("rim_size")
            score += 30
            if str(product.get("rim_size") or "").upper() != request.rim_size:
                soft.append("rim_family_variant")
        else:
            missed.append("rim_size")
            score -= 10

    if request.brands:
        if str(product.get("brand") or "").upper() in set(request.brands):
            passed.append("brand")
            score += 25
        else:
            missed.append("brand")
            score -= 8

    if request.preferred_brands and str(product.get("brand") or "").upper() in set(request.preferred_brands):
        soft.append("preferred_brand")
        score += 7

    if request.model_or_pattern:
        model_score = model_match_score_for_product(request.model_or_pattern, product)
        if model_score >= model_match_threshold(request.model_or_pattern):
            passed.append("model_or_pattern")
            score += int(20 * model_score)
        else:
            missed.append("model_or_pattern")
            score -= 6
    else:
        model_score = 0.0

    if request.section_width:
        if str(product.get("section_width") or "") == str(request.section_width):
            passed.append("section_width")
            score += 12
        else:
            missed.append("section_width")
            score -= 4

    if request.aspect_ratio:
        if str(product.get("aspect_ratio") or "") == str(request.aspect_ratio):
            passed.append("aspect_ratio")
            score += 10
        else:
            missed.append("aspect_ratio")
            score -= 4
    elif is_commercial_no_aspect_request(request):
        commercial_profile = commercial_no_aspect_profile_label(product)
        if commercial_profile == "commercial_70_plus_profile":
            soft.append(commercial_profile)
            score += 7
        elif commercial_profile == "commercial_implicit_profile":
            soft.append(commercial_profile)
            score += 4
        else:
            soft.append("commercial_lower_profile")

    if request.tire_categories:
        if category_matches(request.tire_categories, product.get("category")):
            passed.append("tire_category")
            score += 8
        else:
            missed.append("tire_category")
            score -= 3

    if request.origins:
        if origin_matches(request.origins, _product_origin_for_filter(product)):
            passed.append("origin")
            score += 6
        else:
            missed.append("origin")
            score -= 3

    if request.warranty_years:
        product_warranty_years = infer_warranty_years(product.get("warranty"))
        if product_warranty_years in set(request.warranty_years):
            passed.append("warranty_years")
            score += 6
        else:
            missed.append("warranty_years")
            score -= 3

    if request.terrain_types:
        product_terrain_types = set(normalize_terrain_types(product.get("terrain_types")))
        if product_terrain_types.intersection(request.terrain_types):
            passed.append("terrain_type")
            score += 10
        else:
            missed.append("terrain_type")
            score -= 4

    if request.availability == "in_stock":
        if not product.get("pre_order"):
            passed.append("availability")
            score += 7
        else:
            missed.append("availability")
            score -= 7
    elif request.availability == "pre_order":
        if product.get("pre_order"):
            passed.append("availability")
            score += 7
        else:
            missed.append("availability")
            score -= 3

    installment_requested = installment_filters_requested(request)
    if installment_requested:
        product_installments = product.get("installments") or []
        if product_installments:
            passed.append("installment")
            score += 6
        else:
            missed.append("installment")
            score -= 5

        if request.installment_banks:
            if installment_bank_matches(request.installment_banks, product_installments):
                passed.append("installment_bank")
                score += 4
            else:
                missed.append("installment_bank")
                score -= 3

        if request.installment_months:
            if installment_months_match(request.installment_months, product_installments):
                passed.append("installment_months")
                score += 4
            else:
                missed.append("installment_months")
                score -= 3

        if request.installment_max_interest is not None:
            if installment_interest_match(request.installment_max_interest, product_installments):
                passed.append("installment_interest")
                score += 4
            else:
                missed.append("installment_interest")
                score -= 3

    if request.budget_max is not None:
        price_basis = budget_price_basis(request, product)
        if price_basis is not None and price_basis <= request.budget_max:
            passed.append("budget_max")
            score += 10
        elif price_basis is not None and price_basis <= request.budget_max * 1.15:
            missed.append("budget_max")
            soft.append("near_budget")
            score += 4
        else:
            missed.append("budget_max")
            score -= 4

    if request.promo_only is True:
        if product_matches_promo_request(request, product):
            passed.append("promo_only")
            score += 6
        else:
            missed.append("promo_only")
            score -= 3

    if request.ev_compatible is not None:
        ev_match = bool(product.get("ev_compatible")) is bool(request.ev_compatible)
        if ev_match:
            passed.append("ev_compatible")
            score += 6
        else:
            missed.append("ev_compatible")
            score -= 3

    requested_guarantee_tiers = set(request.gulong_guarantee_tiers or [])
    if request.gulong_guarantee_only is True or requested_guarantee_tiers:
        tier = gulong_guarantee_tier(product)
        if requested_guarantee_tiers:
            guarantee_match = tier in requested_guarantee_tiers
        else:
            guarantee_match = tier in {1, 2}
        if guarantee_match:
            passed.append("gulong_guarantee")
            score += 6
        else:
            missed.append("gulong_guarantee")
            score -= 3

    semantic_score = semantic_match_score(request, product)
    if semantic_score > 0:
        score += semantic_score
        soft.append("semantic_preference")

    if product.get("pre_order"):
        soft.append("pre_order")
        score -= 5

    tier = classify_match_tier(request, passed, missed)
    why = why_shown(product, passed, missed, tier)
    return {
        "match_score": max(0, min(100, score)),
        "tier": tier,
        "passed_filters": passed,
        "missed_filters": missed,
        "soft_matches": soft,
        "model_score": round(model_score, 3),
        "why_shown": why,
    }


def classify_match_tier(request: ProductSearchRequest, passed: Sequence[str], missed: Sequence[str]) -> str:
    passed_set = set(passed)
    requested_filters = set()
    if request.rim_size:
        requested_filters.add("rim_size")
    if request.brands:
        requested_filters.add("brand")
    if request.model_or_pattern:
        requested_filters.add("model_or_pattern")
    if request.section_width:
        requested_filters.add("section_width")
    if request.aspect_ratio:
        requested_filters.add("aspect_ratio")
    if request.budget_max is not None:
        requested_filters.add("budget_max")
    if request.promo_only is True:
        requested_filters.add("promo_only")
    if request.ev_compatible is not None:
        requested_filters.add("ev_compatible")
    if request.gulong_guarantee_only is True or request.gulong_guarantee_tiers:
        requested_filters.add("gulong_guarantee")
    if request.tire_categories:
        requested_filters.add("tire_category")
    if request.origins:
        requested_filters.add("origin")
    if request.warranty_years:
        requested_filters.add("warranty_years")
    if request.terrain_types:
        requested_filters.add("terrain_type")
    if request.availability in {"in_stock", "pre_order"}:
        requested_filters.add("availability")
    if installment_filters_requested(request):
        requested_filters.add("installment")
    if request.installment_banks:
        requested_filters.add("installment_bank")
    if request.installment_months:
        requested_filters.add("installment_months")
    if request.installment_max_interest is not None:
        requested_filters.add("installment_interest")

    if requested_filters and requested_filters.issubset(passed_set):
        return "exact"
    core_requested = requested_filters.intersection(CORE_FILTERS)
    if core_requested and core_requested.issubset(passed_set):
        return "near_exact"
    if {"rim_size", "brand"}.issubset(passed_set):
        return "same_rim_requested_brand"
    if "rim_size" in passed_set:
        return "same_rim"
    if "brand" in passed_set:
        return "requested_brand_other_size"
    if "model_or_pattern" in passed_set:
        return "model_pattern_match"
    return "alternate"


def why_shown(product: Dict[str, Any], passed: Sequence[str], missed: Sequence[str], tier: str) -> str:
    brand = str(product.get("brand") or "").strip()
    size = str(product.get("size") or "").strip()
    model = str(product.get("model") or "").strip()
    parts = []
    if passed:
        parts.append("matches " + ", ".join(passed[:4]))
    if missed:
        parts.append("misses " + ", ".join(missed[:3]))
    basis = "; ".join(parts) if parts else "included as a fallback option"
    title = " ".join(part for part in [brand, size, model] if part)
    return f"{title}: {basis} ({tier}).".strip()


def normalize_rim_size(rim_size: Optional[Any], *, section_width: Optional[Any] = None) -> Optional[str]:
    """Normalize common passenger rim values while preserving ZR and C suffixes."""

    if rim_size is None:
        return None
    rim = str(rim_size).strip().upper().replace(" ", "")
    if not rim:
        return None
    if rim.startswith("ZR"):
        return rim
    if rim.startswith("R"):
        return rim
    if re.fullmatch(r"\d{2}C", rim):
        return f"R{rim}"
    if re.fullmatch(r"\d{2}(?:\.\d)?", rim):
        if _section_uses_bare_numeric_rim(section_width, rim):
            return rim
        return f"R{rim}"
    return rim


def rim_query_variants(norm_rim: Optional[str]) -> List[Optional[str]]:
    """Return query variants for R/ZR rim family recovery."""

    if not norm_rim:
        return [None]
    rim = str(norm_rim).strip().upper()
    if rim.startswith("ZR"):
        return [rim]
    if re.fullmatch(r"R\d{2}", rim):
        return [rim, f"Z{rim}"]
    if re.fullmatch(r"\d{2}(?:\.\d)?", rim):
        return [rim, f"R{rim}"]
    return [rim]


def brand_query_values(brands: Sequence[str]) -> List[Optional[str]]:
    normalized = _normalize_brands(brands)
    if not normalized:
        return [None]
    if len(normalized) == 1:
        return [normalized[0]]
    return ["--".join(normalized), *normalized]


def flatten_query_params(params: Dict[str, Any]) -> Tuple[Tuple[str, Any], ...]:
    return tuple(sorted((key, value) for key, value in params.items() if value not in (None, "")))


def product_key(product: Dict[str, Any]) -> str:
    raw = product.get("slug") or product.get("raw_key") or product.get("id") or product.get("product_id")
    return str(raw or "").strip().lower()


def category_counts(payload: Any) -> Dict[str, int]:
    if not isinstance(payload, list):
        return {}
    counts: Dict[str, int] = {}
    for category in payload:
        if not isinstance(category, dict):
            continue
        name = str(category.get("name") or category.get("slug") or "unknown").strip() or "unknown"
        counts[name] = len(category.get("products") or [])
    return counts


def format_size(section: Optional[str], aspect: Optional[str], rim: Optional[str]) -> Optional[str]:
    if section and aspect and rim:
        return f"{section}/{aspect}{rim}"
    if section and rim:
        return f"{section}/{rim}"
    if rim:
        return rim
    return None


def _fitment_vehicle_query(payload: Dict[str, Any]) -> str:
    """Return the compact vehicle search text supplied to `/shop?search=`."""

    canonical = _clean_optional(payload.get("car_make_model"))
    if canonical:
        return _canonical_fitment_vehicle_query(canonical)
    structured_parts = [
        _clean_optional(payload.get("car_make")),
        _clean_optional(payload.get("car_model")),
    ]
    if all(structured_parts):
        return _canonical_fitment_vehicle_query(" ".join(part for part in structured_parts if part).strip())
    explicit = _clean_optional(payload.get("vehicle_query"))
    if explicit:
        return _canonical_fitment_vehicle_query(explicit)
    parts = [
        _clean_optional(payload.get("car_make")),
        _clean_optional(payload.get("car_model")),
    ]
    return _canonical_fitment_vehicle_query(" ".join(part for part in parts if part).strip())


def _fitment_raw_vehicle_query(payload: Dict[str, Any]) -> str:
    explicit = _clean_optional(payload.get("raw_vehicle_query") or payload.get("vehicle_query"))
    if explicit:
        return explicit
    parts = [
        _clean_optional(payload.get("car_make_model")),
        _clean_optional(payload.get("car_make")),
        _clean_optional(payload.get("car_model")),
        _clean_optional(payload.get("car_year")),
    ]
    return " ".join(part for part in parts if part).strip()


def _fitment_vehicle_parts(payload: Dict[str, Any], vehicle_query: str) -> Tuple[Optional[str], Optional[str]]:
    """Return best-effort make/model fields for the compatibility fallback."""

    car_make = _clean_optional(payload.get("car_make"))
    car_model = _clean_optional(payload.get("car_model"))
    car_make_model = _clean_optional(payload.get("car_make_model"))
    if car_make_model and not (car_make and car_model):
        parts = _canonical_fitment_vehicle_query(car_make_model).split()
        if len(parts) >= 2:
            car_make = car_make or parts[0]
            car_model = car_model or " ".join(parts[1:])
        elif parts:
            car_model = car_model or parts[0]
    if car_make and not car_model and " " in car_make:
        parts = car_make.split()
        car_make = parts[0]
        car_model = " ".join(parts[1:])
    if not car_make and not car_model and vehicle_query:
        parts = vehicle_query.split()
        if len(parts) >= 2:
            car_make = parts[0]
            car_model = " ".join(parts[1:])
        else:
            car_model = vehicle_query
    return _canonical_fitment_make_model_pair(car_make, car_model)


_FITMENT_TRAILING_TRIM_TOKENS = {
    "BASE",
    "DLX",
    "E",
    "EL",
    "EX",
    "G",
    "GL",
    "GLS",
    "GX",
    "J",
    "S",
    "SE",
    "RS",
    "V",
    "VX",
}


def _canonical_fitment_vehicle_query(value: Optional[str]) -> str:
    return canonical_vehicle_query(value)


def _canonical_fitment_make_text(value: Optional[str]) -> Optional[str]:
    return _strip_model_year_token(value)


def _canonical_fitment_model_text(value: Optional[str]) -> Optional[str]:
    text = _strip_model_year_token(value)
    if not text:
        return None
    parts = text.split()
    while len(parts) > 1 and parts[-1].upper().strip(".") in _FITMENT_TRAILING_TRIM_TOKENS:
        parts.pop()
    return " ".join(parts).strip() or None


def _canonical_fitment_make_model_pair(car_make: Optional[str], car_model: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    return canonical_vehicle_make_model_pair(car_make, car_model)


def _canonical_fitment_vehicle_alias(value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Return known make/model aliases for compatibility endpoint lookup."""

    return canonical_vehicle_alias(value)


def _canonical_fitment_model_alias(car_make: Optional[str], car_model: Optional[str]) -> Optional[str]:
    """Map common customer model shorthand to the compatibility endpoint names."""

    model = _clean_optional(car_model)
    if not model:
        return None
    make_key = str(_clean_optional(car_make) or "").upper()
    model_tokens = {token.upper().strip(".") for token in model.split() if token.strip()}
    if make_key == "MITSUBISHI" and "G4" in model_tokens and "MIRAGE" not in model_tokens:
        return "Mirage G4"
    return model


def _strip_model_year_token(value: Optional[str]) -> Optional[str]:
    """Remove standalone model-year tokens from make/model text."""

    text = _clean_optional(value)
    if not text:
        return None
    cleaned = re.sub(r"\b(?:19|20)\d{2}\b", " ", text)
    cleaned = _clean_optional(cleaned)
    return cleaned or None


def _fitment_presentation_ref(vehicle_query: str, candidates: Sequence[Dict[str, Any]]) -> str:
    sizes = [
        str(candidate.get("size") or "").strip()
        for candidate in candidates or []
        if isinstance(candidate, dict) and str(candidate.get("size") or "").strip()
    ]
    material = json.dumps({"vehicle_query": vehicle_query, "sizes": sizes[:8]}, sort_keys=True, ensure_ascii=True)
    digest = hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]
    return f"pres_fitment_{digest}"


def _fitment_shop_search_allowed(payload: Dict[str, Any], vehicle_query: str) -> bool:
    """Return true only when weak shop search is safe as a fitment fallback.

    `/shop?search=` can return generic tire catalog rows for vehicle names such
    as "Honda City" or "Innova". Prefer the compatibility endpoint whenever
    make/model text is available; use shop search only when the query also has
    concrete size clues that can rank/filter the candidates.
    """

    if not str(vehicle_query or "").strip():
        return False
    if _fitment_size_preferences(payload, vehicle_query=vehicle_query):
        return True
    return False


def _fitment_size_preferences(payload: Dict[str, Any], *, vehicle_query: str = "") -> Dict[str, Any]:
    """Return non-blocking fitment size clues from tool args."""

    clue = _clean_optional(payload.get("tire_size_clue") or payload.get("tire_size"))
    clue_parts: Dict[str, str] = {}
    if clue:
        clue_parts, _corrections = _split_tire_size_arg(clue)
    clue_text = " ".join(
        str(part or "")
        for part in [
            clue,
            payload.get("rim_size"),
            payload.get("section_width"),
            payload.get("aspect_ratio"),
            vehicle_query,
            " ".join(_normalize_string_list(payload.get("soft_preferences"))),
        ]
        if str(part or "").strip()
    )
    section = normalize_section_width(payload.get("section_width") or clue_parts.get("section_width"))
    aspect = _normalize_numeric_text(payload.get("aspect_ratio") or clue_parts.get("aspect_ratio"))
    rim = normalize_rim_size(
        payload.get("rim_size") or clue_parts.get("rim_size") or _rim_size_from_clue_text(clue_text),
        section_width=section,
    )
    return {
        key: value
        for key, value in {
            "section_width": section,
            "aspect_ratio": aspect,
            "rim_size": rim,
            "tire_size_clue": clue,
        }.items()
        if value not in (None, "")
    }


def _rim_size_from_clue_text(text: str) -> Optional[str]:
    raw = str(text or "").upper()
    if not raw:
        return None
    match = re.search(r"\b(?:RIM\s*)?(?:ZR|R)?(?P<rim>\d{2})(?:\s*(?:RIM|INCH|INCHES))?\b", raw)
    if not match:
        return None
    return f"R{match.group('rim')}"


def _rank_fitment_candidates_by_preferences(
    candidates: Sequence[Dict[str, Any]],
    *,
    size_preferences: Dict[str, Any],
    top_k: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Rank fitment candidates by size clues and enforce explicit rim constraints."""

    rows = [deepcopy(candidate) for candidate in candidates or [] if isinstance(candidate, dict)]
    wanted = {key: str(value).strip().upper() for key, value in (size_preferences or {}).items() if key != "tire_size_clue" and value}
    if not rows or not wanted:
        return rows[: max(1, int(top_k or 6))], {
            "requested": bool(wanted),
            "matching_candidate_count": 0,
            "ranking_applied": False,
        }

    ranked: List[Tuple[int, int, int, str, Dict[str, Any]]] = []
    for index, candidate in enumerate(rows):
        parts = _fitment_candidate_size_parts(candidate.get("size"))
        matched: List[str] = []
        missed: List[str] = []
        score = 0
        for key, weight in (("rim_size", 5), ("section_width", 3), ("aspect_ratio", 2)):
            wanted_value = wanted.get(key)
            if not wanted_value:
                continue
            actual = str(parts.get(key) or "").strip().upper()
            if actual and actual == wanted_value:
                matched.append(key)
                score += weight
            elif actual:
                missed.append(key)
        annotated = deepcopy(candidate)
        annotated["size_preference_match"] = {
            "matched": matched,
            "missed": missed,
            "score": score,
            "preferences": wanted,
        }
        if matched:
            annotated["soft_matches"] = _ordered_unique([*(annotated.get("soft_matches") or []), *matched])
        ranked.append((score, int(annotated.get("count") or 0), -index, str(annotated.get("size") or ""), annotated))

    ranked.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))
    matching_count = sum(1 for score, *_rest in ranked if score > 0)
    hard_filter_applied = False
    filtered_ranked = ranked
    if wanted.get("rim_size"):
        rim_matches = [
            item
            for item in ranked
            if "rim_size" in (((item[-1].get("size_preference_match") or {}).get("matched")) or [])
        ]
        if rim_matches:
            filtered_ranked = rim_matches
            hard_filter_applied = len(rim_matches) != len(ranked)
    return [row[-1] for row in filtered_ranked[: max(1, int(top_k or 6))]], {
        "requested": True,
        "ranking_applied": True,
        "hard_filter_applied": hard_filter_applied,
        "preferences": wanted,
        "matching_candidate_count": matching_count,
        "note": (
            "Explicit rim-size clues are enforced when at least one candidate matches; "
            "other partial tire-size clues remain ranking preferences until the customer confirms the sidewall."
        ),
    }


def _fitment_candidate_size_parts(size: Any) -> Dict[str, str]:
    parts, _corrections = _split_tire_size_arg(size)
    return {
        key: value
        for key, value in {
            "section_width": normalize_section_width(parts.get("section_width")),
            "aspect_ratio": _normalize_numeric_text(parts.get("aspect_ratio")),
            "rim_size": normalize_rim_size(parts.get("rim_size"), section_width=parts.get("section_width")),
        }.items()
        if value
    }


def _fitment_candidates_from_products(products: Sequence[Dict[str, Any]], *, top_k: int) -> List[Dict[str, Any]]:
    """Group `/shop` search results into candidate tire-size summaries."""

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for product in products:
        size = _fitment_size_from_product(product)
        if not size:
            continue
        groups.setdefault(size, []).append(product)
    candidates: List[Dict[str, Any]] = []
    for size, rows in groups.items():
        candidates.append(
            {
                "size": size,
                "count": len(rows),
                "confidence": _fitment_confidence(len(rows), source="shop_search"),
                "sample_products": [_fitment_sample_product(product) for product in rows[:3]],
            }
        )
    candidates.sort(key=lambda item: (-int(item.get("count") or 0), str(item.get("size") or "")))
    return candidates[: max(1, int(top_k or 6))]


def _fitment_candidates_from_size_rows(rows: Any, *, top_k: int) -> List[Dict[str, Any]]:
    """Normalize legacy compatible-size endpoint rows into candidate summaries."""

    if not isinstance(rows, list):
        return []
    grouped: Dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        size = _fitment_size_from_product(row)
        if not size:
            continue
        grouped[size] = grouped.get(size, 0) + 1
    candidates = [
        {
            "size": size,
            "count": count,
            "confidence": _fitment_confidence(count, source="car_tire_sizes"),
            "sample_products": [],
        }
        for size, count in grouped.items()
    ]
    candidates.sort(key=lambda item: (-int(item.get("count") or 0), str(item.get("size") or "")))
    return candidates[: max(1, int(top_k or 6))]


def _fitment_size_from_product(product: Dict[str, Any]) -> Optional[str]:
    """Extract a full tire size from a normalized product or endpoint row."""

    section = normalize_section_width(product.get("section_width"))
    aspect = _normalize_numeric_text(product.get("aspect_ratio"))
    rim = normalize_rim_size(product.get("rim_size"), section_width=section)
    size = format_size(section, aspect, rim)
    if size and _is_full_tire_size(size):
        return size
    raw_size = _clean_optional(product.get("size"))
    if raw_size:
        parsed = _size_from_model(raw_size)
        if parsed and _is_full_tire_size(parsed):
            return parsed
        compact = raw_size.upper().replace(" ", "").replace("/R", "R")
        if _is_full_tire_size(compact):
            return compact
    model_size = _size_from_model(str(product.get("model") or ""))
    if model_size and _is_full_tire_size(model_size):
        return model_size
    return None


def _is_full_tire_size(value: Optional[str]) -> bool:
    return bool(re.search(r"\b\d{3}/\d{2}Z?R\d{2}[A-Z]?\b", str(value or "").upper()))


def _fitment_confidence(count: int, *, source: str) -> str:
    if source == "car_tire_sizes" and count >= 1:
        return "medium"
    if count >= 5:
        return "high"
    if count >= 2:
        return "medium"
    return "low"


def _fitment_sample_product(product: Dict[str, Any]) -> Dict[str, Any]:
    keys = ["product_id", "slug", "brand", "model", "size", "category", "rim_size"]
    return {key: product.get(key) for key in keys if product.get(key) not in (None, "", [])}


def rim_matches(requested: Optional[str], actual: Optional[Any]) -> bool:
    requested_norm = normalize_rim_size(requested)
    actual_norm = normalize_rim_size(actual)
    if not requested_norm or not actual_norm:
        return False
    if requested_norm == actual_norm:
        return True
    if requested_norm.endswith("C") or actual_norm.endswith("C"):
        return False
    return _rim_number(requested_norm) == _rim_number(actual_norm)


def is_commercial_no_aspect_request(request: ProductSearchRequest) -> bool:
    return bool(request.section_width and request.rim_size and not request.aspect_ratio and str(request.rim_size).upper().endswith("C"))


def commercial_no_aspect_profile_label(product: Dict[str, Any]) -> str:
    """Label profile fit for a commercial width/rim request without aspect."""

    aspect = _normalize_numeric_text(product.get("aspect_ratio"))
    if aspect is None:
        return "commercial_implicit_profile"
    try:
        if float(aspect) >= 70:
            return "commercial_70_plus_profile"
    except Exception:
        pass
    return "commercial_lower_profile"


def model_match_score(query: Optional[str], text: str) -> float:
    query_norm = _normalize_match_text(query)
    text_norm = _normalize_match_text(text)
    text_tokens = set(text_norm.split())
    return model_match_score_normalized(query_norm, text_norm, text_tokens)


def model_match_score_for_product(query: Optional[str], product: Dict[str, Any]) -> float:
    query_norm = _normalize_match_text(query)
    text_norm = str(product.get("_search_norm") or "")
    if not text_norm:
        attach_search_fields(product)
        text_norm = str(product.get("_search_norm") or "")
    tokens = product.get("_search_tokens") or ()
    return model_match_score_normalized(query_norm, text_norm, set(tokens))


def model_match_score_normalized(query_norm: str, text_norm: str, text_tokens: set[str]) -> float:
    if not query_norm or not text_norm:
        return 0.0
    if query_norm in text_norm:
        return 1.0
    query_tokens = set(query_norm.split())
    if query_tokens and query_tokens.issubset(text_tokens):
        return 0.92
    overlap = len(query_tokens.intersection(text_tokens)) / max(1, len(query_tokens))
    ratio = difflib.SequenceMatcher(None, query_norm, text_norm).ratio()
    partial = max(
        (difflib.SequenceMatcher(None, query_norm, token).ratio() for token in text_tokens),
        default=0.0,
    )
    token_coverage = fuzzy_token_coverage(query_tokens, text_tokens)
    phrase_ratio = best_phrase_ratio(query_norm.split(), text_norm.split())
    return max(overlap * 0.85, ratio, partial * 0.72, token_coverage * 0.95, phrase_ratio)


def model_match_threshold(query: Optional[str]) -> float:
    norm = _normalize_match_text(query)
    return 0.42 if len(norm) <= 4 else 0.58


def prefilter_model_candidates(query: Optional[str], products: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    query_norm = _normalize_match_text(query)
    query_tokens = [token for token in query_norm.split() if token]
    if not query_norm or not query_tokens:
        return list(products)

    token_to_indices: Dict[str, List[int]] = {}
    vocabulary: set[str] = set()
    direct_matches: set[int] = set()
    for index, product in enumerate(products):
        attach_search_fields(product)
        text_norm = str(product.get("_search_norm") or "")
        tokens = set(product.get("_search_tokens") or ())
        if query_norm in text_norm or set(query_tokens).intersection(tokens):
            direct_matches.add(index)
        for token in tokens:
            vocabulary.add(token)
            token_to_indices.setdefault(token, []).append(index)

    candidate_indices = set(direct_matches)
    for query_token in query_tokens:
        close_tokens = difflib.get_close_matches(
            query_token,
            vocabulary,
            n=60,
            cutoff=fuzzy_token_floor(query_token),
        )
        # Customer input is often truncated: "pilot spor" should keep "SPORT".
        if len(query_token) >= 3:
            close_tokens.extend(token for token in vocabulary if token.startswith(query_token))
        for token in close_tokens:
            candidate_indices.update(token_to_indices.get(token) or [])

    if not candidate_indices:
        return list(products)
    return [products[index] for index in sorted(candidate_indices)]


def refine_model_products(request: ProductSearchRequest, products: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not request.model_or_pattern or not products:
        return list(products)
    candidates = prefilter_model_candidates(request.model_or_pattern, products)
    threshold = model_match_threshold(request.model_or_pattern)
    scored = [
        (model_match_score_for_product(request.model_or_pattern, product), product)
        for product in candidates
    ]
    scored = [(score, product) for score, product in scored if score >= threshold]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [product for _, product in scored[:80]]


def select_presentation_products(
    request: ProductSearchRequest,
    ranked: Sequence[Dict[str, Any]],
    *,
    limit: int = 4,
) -> List[Dict[str, Any]]:
    candidates = presentation_eligible_candidates(request, ranked)
    if not candidates:
        return []
    is_general_size_ladder = _is_general_size_price_ladder_request(request)
    card_limit = max(1, min(PRESENTATION_MAX_CARD_COUNT, int(limit or PRESENTATION_MAX_CARD_COUNT)))
    if is_general_size_ladder and _candidate_category_count(candidates) > card_limit:
        card_limit = PRESENTATION_MAX_CARD_COUNT
    if request.budget_max is not None:
        selected = _select_budget_cards(request, candidates, card_limit)
        return _ensure_preferred_brand_cards(request, selected, candidates, card_limit)
    if request.brands and request.rim_size:
        selected = _select_size_brand_cards(request, candidates, card_limit)
        return _ensure_preferred_brand_cards(request, selected, candidates, card_limit)
    if request.rim_size and not request.brands:
        selected = _select_size_only_cards(request, candidates, card_limit)
        if is_general_size_ladder:
            return selected
        return _ensure_preferred_brand_cards(request, selected, candidates, card_limit)
    selected = _select_diverse_cards(request, candidates, card_limit)
    return _ensure_preferred_brand_cards(request, selected, candidates, card_limit)


def presentation_card_limit(request: ProductSearchRequest) -> int:
    """Return the product-card limit separately from the raw result top-k.

    Product cards are customer-facing recommendations, so the runner aims for
    about three options by default. An explicit `top_k=1` is a narrowed
    selection plan and must remain one card in the presentation; expanding it
    would reintroduce unrelated alternatives after a customer has chosen.
    """

    requested = int(request.top_k or 0)
    if requested == 1:
        return 1
    if requested in {4, 5} or requested > 6:
        return PRESENTATION_MAX_CARD_COUNT
    return PRESENTATION_TARGET_CARD_COUNT


def prefer_image_backed_presentation_products(
    request: ProductSearchRequest,
    ranked: Sequence[Dict[str, Any]],
    *,
    selected: Sequence[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    """Replace incomplete multi-card sets with ranked image-backed candidates.

    The already fetched, query-filtered ranked pool remains authoritative. No
    extra provider call is made, and exact single-product progression remains
    untouched. A required-brand exact-size result also remains intact: the
    channel renderer can list every source-backed option in text while limiting
    its visual gallery and tracked buttons to trusted-image cards. If no
    image-backed candidate exists, the original products are retained so the
    renderer can still provide a truthful text-only result.
    """

    chosen = [dict(product) for product in selected if isinstance(product, dict)]
    if len(chosen) <= 1 or all(product.get("image_url") for product in chosen):
        return chosen
    if (
        request.brands
        and request.section_width
        and request.aspect_ratio
        and request.rim_size
    ):
        return chosen
    image_backed = [
        product
        for product in ranked
        if isinstance(product, dict) and product.get("image_url")
    ]
    if not image_backed:
        return chosen
    replacements = select_presentation_products(
        request,
        image_backed,
        limit=limit,
    )
    return replacements or chosen


def _is_general_size_price_ladder_request(request: ProductSearchRequest) -> bool:
    """Return True for broad size/rim discovery where tier spread matters most.

    Soft preferred brands may come from remembered state. They should choose the
    representative inside each price tier, not disable the four-tier ladder.
    """

    return bool(
        request.section_width
        and request.aspect_ratio
        and request.rim_size
        and not request.brands
        and not request.excluded_brands
        and not request.model_or_pattern
        and request.budget_max is None
        and request.promo_only is not True
        and not request.promo_types
        and request.ev_compatible is None
        and request.gulong_guarantee_only is not True
        and not request.gulong_guarantee_tiers
        and not request.origins
        and not request.excluded_origins
        and not request.warranty_years
        and not request.tire_categories
        and not request.excluded_tire_categories
        and not request.terrain_types
        and request.availability == "any"
        and not installment_filters_requested(request)
        and request.ply_rating is None
    )


def _candidate_category_count(candidates: Sequence[Dict[str, Any]]) -> int:
    return len({_category_key(product) for product in candidates if _category_key(product)})


def presentation_eligible_candidates(
    request: ProductSearchRequest,
    ranked: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return cards under the fitment-first product presentation contract.

    Full tire size, explicit EV compatibility, and customer exclusions are
    hard constraints. Other shopping attributes are preferences that may be
    relaxed only when the provider records the miss and the deterministic
    renderer discloses it. A requested brand becomes hard only when the
    customer explicitly selected ``brand_match_mode=strict``.
    """

    requested_size = _requested_full_size_candidates(request, ranked)
    if requested_size:
        fitment_candidates = [
            product
            for product in requested_size
            if _presentation_fitment_filters_match(request, product)
        ]
        if not fitment_candidates:
            return []
        strict_brand_scope = bool(
            request.brands and request.brand_match_mode == "strict"
        )
        scoped_requested_size = fitment_candidates
        if strict_brand_scope:
            requested_brands = set(request.brands)
            scoped_requested_size = [
                product
                for product in fitment_candidates
                if str(product.get("brand") or "").upper() in requested_brands
            ]
            if not scoped_requested_size:
                # Explicit "brand only" wording is a customer prohibition.
                return []
        strict_requested_size = [
            product
            for product in scoped_requested_size
            if presentation_preferences_match(request, product)
        ]
        if strict_requested_size:
            return strict_requested_size
        return _best_disclosed_fitment_candidates(
            request,
            scoped_requested_size,
        )
    eligible = [product for product in ranked if presentation_preferences_match(request, product)]
    if eligible or not has_presentation_constraints(request):
        return eligible if eligible else list(ranked)
    return _relaxed_presentation_candidates(request, ranked)


def _best_disclosed_fitment_candidates(
    request: ProductSearchRequest,
    candidates: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return exact-fitment near matches with every relaxed preference typed."""

    eligible: List[Tuple[int, Dict[str, Any]]] = []
    for product in candidates:
        misses = set(_presentation_filter_misses(request, product))
        if misses and not misses.intersection(PRODUCT_FITMENT_FILTERS):
            eligible.append((len(misses), product))
    if not eligible:
        return []
    minimum_misses = min(count for count, _product in eligible)
    return [
        product
        for count, product in eligible
        if count == minimum_misses
    ]


def _presentation_fitment_filters_match(
    request: ProductSearchRequest,
    product: Dict[str, Any],
) -> bool:
    """Enforce vehicle-fitment constraints before any preference relaxation."""

    if not _matches_requested_full_size(request, product):
        return False
    if (
        request.ev_compatible is not None
        and bool(product.get("ev_compatible")) is not bool(request.ev_compatible)
    ):
        return False
    return True


def _requested_full_size_candidates(
    request: ProductSearchRequest,
    ranked: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return candidates that preserve the customer's requested full size.

    Promo/category/refiner filters can be relaxed for presentation, but a
    customer-facing tire-card surface must not silently substitute a different
    section width or aspect ratio when the customer gave a full tire size.
    """

    if not (request.section_width and request.aspect_ratio and request.rim_size):
        return []
    return [
        product
        for product in ranked
        if _matches_requested_full_size(request, product)
    ]


def _matches_requested_full_size(request: ProductSearchRequest, product: Dict[str, Any]) -> bool:
    if str(product.get("section_width") or "") != str(request.section_width):
        return False
    if str(product.get("aspect_ratio") or "") != str(request.aspect_ratio):
        return False
    return bool(rim_matches(request.rim_size, product.get("rim_size")))


def presentation_preferences_match(request: ProductSearchRequest, product: Dict[str, Any]) -> bool:
    """Return whether a product satisfies every positive presentation request.

    This is the strict first-pass ranking check. The fitment-first fallback may
    subsequently relax non-fitment misses, but it never changes the catalog
    facts evaluated here.
    """

    if (
        request.section_width
        and str(product.get("section_width") or "")
        != str(request.section_width)
    ):
        return False
    if (
        request.aspect_ratio
        and str(product.get("aspect_ratio") or "")
        != str(request.aspect_ratio)
    ):
        return False
    if request.rim_size and not rim_matches(
        request.rim_size,
        product.get("rim_size"),
    ):
        return False
    if (
        request.brands
        and str(product.get("brand") or "").upper()
        not in set(request.brands)
        and (
            request.brand_match_mode == "strict"
            or not _explicit_product_alternatives_allowed(request)
        )
    ):
        return False
    if request.promo_only is True and not product_matches_promo_request(request, product):
        return False
    if request.ev_compatible is not None and bool(product.get("ev_compatible")) is not bool(request.ev_compatible):
        return False
    if request.gulong_guarantee_only is True and gulong_guarantee_tier(product) == 0:
        return False
    if request.gulong_guarantee_tiers and gulong_guarantee_tier(product) not in set(request.gulong_guarantee_tiers):
        return False
    if request.availability == "in_stock" and product.get("pre_order"):
        return False
    if request.availability == "pre_order" and not product.get("pre_order"):
        return False
    if request.terrain_types and not set(normalize_terrain_types(product.get("terrain_types"))).intersection(request.terrain_types):
        return False
    if request.tire_categories and not category_matches(request.tire_categories, product.get("category")):
        return False
    if installment_filters_requested(request):
        installments = product.get("installments") or []
        if request.installment_only is True and not installments:
            return False
        if request.installment_banks and not installment_bank_matches(request.installment_banks, installments):
            return False
        if request.installment_months and not installment_months_match(request.installment_months, installments):
            return False
        if request.installment_max_interest is not None and not installment_interest_match(request.installment_max_interest, installments):
            return False
    return True


def _relaxed_presentation_candidates(
    request: ProductSearchRequest,
    ranked: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return best near-match candidates when strict presentation filters empty out.

    Search ranking still records which requested filters were missed. This layer
    only prevents the customer-facing card renderer from returning no cards when
    preference/refiner filters over-constrain an otherwise useful product pool.
    """

    candidates = list(ranked or [])
    if not candidates:
        return []

    core_candidates = _best_core_tier_candidates(candidates)
    scoped = core_candidates or candidates
    misses_by_key = {
        product_key(product): _presentation_filter_misses(request, product)
        for product in scoped
        if product_key(product)
    }
    if not misses_by_key:
        return scoped
    min_misses = min(len(misses) for misses in misses_by_key.values())
    relaxed = [
        product
        for product in scoped
        if product_key(product) and len(misses_by_key.get(product_key(product), [])) == min_misses
    ]
    return relaxed or scoped


def _best_core_tier_candidates(products: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    tier_priority = {
        "exact": 0,
        "near_exact": 1,
        "partial": 2,
        "same_rim_requested_brand": 3,
        "same_rim": 4,
        "requested_brand_other_size": 5,
        "model_pattern_match": 6,
        "alternate": 7,
    }
    scored = [
        (tier_priority.get(str((product.get("match") or {}).get("tier") or ""), 99), product)
        for product in products
    ]
    if not scored:
        return []
    best_priority = min(priority for priority, _product in scored)
    return [product for priority, product in scored if priority == best_priority]


def _presentation_filter_misses(request: ProductSearchRequest, product: Dict[str, Any]) -> List[str]:
    match = product.get("match") if isinstance(product.get("match"), dict) else {}
    misses: List[str] = [
        str(item)
        for item in match.get("missed_filters") or []
        if str(item)
    ]
    if request.promo_only is True and not product_matches_promo_request(request, product):
        misses.append("promo_only")
    if request.ev_compatible is not None and bool(product.get("ev_compatible")) is not bool(request.ev_compatible):
        misses.append("ev_compatible")
    if request.gulong_guarantee_only is True and gulong_guarantee_tier(product) == 0:
        misses.append("gulong_guarantee")
    if request.gulong_guarantee_tiers and gulong_guarantee_tier(product) not in set(request.gulong_guarantee_tiers):
        misses.append("gulong_guarantee")
    if request.availability == "in_stock" and product.get("pre_order"):
        misses.append("availability")
    if request.availability == "pre_order" and not product.get("pre_order"):
        misses.append("availability")
    if request.terrain_types and not set(normalize_terrain_types(product.get("terrain_types"))).intersection(request.terrain_types):
        misses.append("terrain_type")
    if request.tire_categories and not category_matches(request.tire_categories, product.get("category")):
        misses.append("tire_category")
    if installment_filters_requested(request):
        installments = product.get("installments") or []
        if request.installment_only is True and not installments:
            misses.append("installment")
        if request.installment_banks and not installment_bank_matches(request.installment_banks, installments):
            misses.append("installment_bank")
        if request.installment_months and not installment_months_match(request.installment_months, installments):
            misses.append("installment_months")
        if request.installment_max_interest is not None and not installment_interest_match(request.installment_max_interest, installments):
            misses.append("installment_interest")
    return _ordered_unique(misses)


def has_presentation_constraints(request: ProductSearchRequest) -> bool:
    """Return whether the request contains a constraint worth disclosing."""

    return bool(
        request.brands
        or request.model_or_pattern
        or request.budget_max is not None
        or request.promo_only is True
        or request.ev_compatible is not None
        or request.gulong_guarantee_only is True
        or request.gulong_guarantee_tiers
        or request.origins
        or request.warranty_years
        or request.availability in {"in_stock", "pre_order"}
        or request.terrain_types
        or request.tire_categories
        or installment_filters_requested(request)
    )


def render_product_cards(request: ProductSearchRequest, products: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Render trusted normalized products into deterministic customer cards.

    Product normalization owns catalog identity, URL validity, and display
    units before this boundary. This renderer preserves those exact facts,
    omits rejected links instead of inventing replacements, and returns stable
    card refs and presentation fields for downstream channel rendering.
    """

    cards: List[Dict[str, Any]] = []
    for index, product in enumerate(products, start=1):
        quantity = max(1, int(request.quantity or 4))
        total_price = effective_total_price(product, quantity)
        unit_price = _coerce_float(product.get("price"))
        promo_savings = product_promo_savings(product, quantity=quantity)
        pricing_facts = product_card_pricing_facts(
            product,
            quantity=quantity,
            unit_price=unit_price,
            total_price=total_price,
        )
        category = _category_display(product.get("category"))
        sku_model = product_model_label(product)
        price_category_line = f"[{category.upper()}]"
        deal_price_line = _deal_price_line(
            product,
            quantity=quantity,
            unit_price=unit_price,
            total_price=total_price,
        )
        promo_line = promo_savings
        dot = str(product.get("dot") or "")
        origin = str(product.get("origin") or "").strip()
        warranty = str(product.get("warranty") or "").strip()
        tpp = tire_protection_plan_text(product)
        installment_text = str(product.get("installment_text") or "").strip()
        url = str(product.get("url") or "")
        missing_requested_filters = _presentation_filter_misses(request, product)
        mismatch_labels = _customer_filter_mismatch_labels(
            request,
            missing_requested_filters,
        )
        card_lines = [
            price_category_line,
            f"🛞 {sku_model}",
            f"💰 {deal_price_line or _money_text(unit_price, suffix='per tire') or '-'}",
        ]
        if mismatch_labels:
            card_lines.append("Does not match: " + ", ".join(mismatch_labels))
        if promo_line:
            card_lines.append(f"🎁 {promo_line}")
        if installment_text:
            card_lines.append(f"💳 {installment_text}")
        if origin:
            card_lines.append(f"Origin: {origin}")
        if dot:
            card_lines.append(f"🗓️ DOT: {dot}")
        if warranty or tpp:
            card_lines.append(f"Warranty: {' + '.join(part for part in [warranty, tpp] if part)}")
        if url:
            card_lines.append(f"🔗 {url}")
        card_text = "\n".join(card_lines)
        cards.append(
            {
                "card_ref": f"card_{index}",
                "item_ref": product.get("item_ref"),
                "product_id": product.get("product_id"),
                "slug": product.get("slug"),
                "brand": product.get("brand"),
                "category": category,
                "tire_size": product.get("size"),
                "pattern": product.get("pattern"),
                "sku_model": sku_model,
                "price_category_line": price_category_line,
                "deal_price_line": deal_price_line,
                "promo_savings_line": promo_line,
                "pricing_facts": pricing_facts,
                "installment_text": installment_text or None,
                "quantity": quantity,
                "pricing_basis": pricing_basis(product, quantity),
                "dot": dot or None,
                "origin": origin or None,
                "warranty": warranty or None,
                "tire_protection_plan": tpp or None,
                "url": url,
                "product_link_status": product.get("product_link_status"),
                "image_url": product.get("image_url"),
                "why_shown": card_reason(request, product),
                "missing_requested_filters": missing_requested_filters,
                "preference_mismatch_labels": mismatch_labels,
                "presentation_scope": product.get("presentation_scope"),
                "card_text": card_text,
            }
        )
    return cards


def _customer_filter_mismatch_labels(
    request: ProductSearchRequest,
    misses: Sequence[str],
) -> List[str]:
    """Translate typed ranking misses into compact customer-facing labels."""

    requested_brands = "/".join(request.brands)
    labels = {
        "brand": f"requested brand ({requested_brands})" if requested_brands else "requested brand",
        "model_or_pattern": "requested model/pattern",
        "budget_max": "requested budget",
        "promo_only": "requested promo",
        "promo_type": "requested promo type",
        "gulong_guarantee": "requested Tire Protection Plan",
        "tire_category": "requested price category",
        "origin": "requested origin",
        "warranty_years": "requested warranty term",
        "terrain_type": "requested terrain type",
        "availability": "requested stock status",
        "installment": "requested installment availability",
        "installment_bank": "requested installment bank",
        "installment_months": "requested installment term",
        "installment_interest": "requested installment rate",
    }
    return _ordered_unique(
        labels.get(str(miss), str(miss).replace("_", " "))
        for miss in misses
    )


def _product_card_link_validation_summary(
    cards: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    status_counts: Dict[str, int] = {}
    suppressed_card_refs: List[str] = []
    for card in cards or []:
        status = str(card.get("product_link_status") or "unknown").strip()
        status_counts[status] = status_counts.get(status, 0) + 1
        if status.startswith("suppressed_"):
            suppressed_card_refs.append(str(card.get("card_ref") or ""))
    return {
        "status_counts": status_counts,
        "suppressed_card_refs": [value for value in suppressed_card_refs if value],
    }


def product_card_pricing_facts(
    product: Dict[str, Any],
    *,
    quantity: int,
    unit_price: Optional[float],
    total_price: Optional[float],
) -> Dict[str, Any]:
    """Return structured card pricing facts for follow-up grounding."""

    qty = max(1, int(quantity or 1))
    base_unit = _base_card_unit_price(product)
    display_unit = _coerce_float(base_unit if base_unit is not None else unit_price)
    payable_total = _coerce_float(total_price)
    bundle = product.get("bundle_pricing") if isinstance(product.get("bundle_pricing"), dict) else {}
    api_quantity_promo = str(bundle.get("source") or "") == "api_product_promo"
    facts: Dict[str, Any] = {
        "quantity": qty,
        "pricing_basis": pricing_basis(product, qty),
    }
    if display_unit is not None:
        facts["unit_price"] = round(display_unit, 2)
        facts["unit_price_text"] = _money_text(display_unit, suffix="/tire")
    if payable_total is not None:
        facts["payable_total"] = round(payable_total, 2)
        facts["payable_total_text"] = _money_text(payable_total, suffix=_tire_total_suffix(qty))
        facts["payable_total_already_includes_savings"] = True
    if display_unit is not None and payable_total is not None and qty > 1:
        pre_discount_total = round(display_unit * qty, 2)
        facts["pre_discount_total"] = pre_discount_total
        facts["pre_discount_total_text"] = _money_text(pre_discount_total)
        if not api_quantity_promo:
            total_savings = max(0.0, round(pre_discount_total - payable_total, 2))
            facts["total_savings"] = total_savings
            facts["total_savings_text"] = _money_text(total_savings)
    tier = bundle_tier_for_quantity(product, qty)
    if tier and api_quantity_promo:
        facts["pricing_source"] = "api_product_promo"
        before_promo = _coerce_float(tier.get("total_before_quantity_promo"))
        tier_unit = _coerce_float(tier.get("unit_price_before_quantity_promo"))
        promo_amount = _coerce_float(tier.get("quantity_promo_discount_amount"))
        if before_promo is not None:
            facts["total_before_quantity_promo"] = round(before_promo, 2)
            facts["total_before_quantity_promo_text"] = _money_text(before_promo)
        if tier_unit is not None:
            facts["quantity_tier_unit_price"] = round(tier_unit, 2)
            facts["quantity_tier_unit_price_text"] = _money_text(tier_unit, suffix="/tire")
        if promo_amount is not None:
            facts["quantity_promo_discount_amount"] = round(promo_amount, 2)
            facts["quantity_promo_discount_text"] = _money_text(promo_amount)
        if bundle.get("product_promo_ref") is not None:
            facts["product_promo_ref"] = bundle["product_promo_ref"]
    sale_discount = _coerce_float(product.get("sale_price_discount_amount"))
    if sale_discount and sale_discount > 0:
        facts["unit_price_already_includes_sale_discount"] = True
        facts["sale_discount_per_tire"] = round(sale_discount, 2)
        facts["sale_discount_per_tire_text"] = _money_text(sale_discount, suffix="/tire")
    included_promos = _included_pricing_promos(product, qty, total_savings=facts.get("total_savings"))
    if included_promos:
        facts["included_promos"] = included_promos
    return {key: value for key, value in facts.items() if value not in (None, "", [], {})}


def _included_pricing_promos(
    product: Dict[str, Any],
    quantity: int,
    *,
    total_savings: Optional[float],
) -> List[str]:
    promos: List[str] = []
    discount_text = _clean_optional(product.get("product_discount_text"))
    bundle = product.get("bundle_pricing") if isinstance(product.get("bundle_pricing"), dict) else {}
    tier = bundle_tier_for_quantity(product, quantity)
    api_quantity_promo = bool(tier and str(bundle.get("source") or "") == "api_product_promo")
    if discount_text:
        promos.append(discount_text)
        if not api_quantity_promo:
            bundle_savings = _product_discount_bundle_savings(
                product,
                quantity,
                total_savings=float(total_savings or 0.0),
            )
            if bundle_savings:
                promos.append(f"Bundle: Save PHP {bundle_savings:,.2f}")
    if api_quantity_promo:
        quantity_promo_amount = _coerce_float(tier.get("quantity_promo_discount_amount"))
        if quantity_promo_amount:
            promos.append(f"Quantity promo: PHP {quantity_promo_amount:,.2f} off")
    sale_discount_text = _clean_optional(product.get("sale_price_discount_text"))
    if sale_discount_text and not discount_text:
        promos.append(sale_discount_text)
    promo_label = _clean_optional(product.get("promo_label"))
    if promo_label:
        promos.append(promo_label)
    elif not discount_text and total_savings and total_savings > 0:
        if pricing_basis(product, quantity) == "bundle_tier":
            promos.append(f"Bundle: Save PHP {float(total_savings):,.2f}")
        elif pricing_basis(product, quantity) == "buy3get1":
            promos.append("Buy 3 Get 1 FREE")
    voucher_text = _clean_optional(product.get("voucher_text"))
    voucher_amount = _coerce_float(product.get("voucher_amount"))
    if voucher_text:
        promos.append(voucher_text)
    elif voucher_amount:
        promos.append(f"Voucher: PHP {voucher_amount:,.2f} off")
    return _ordered_unique(promos)


def build_brand_buckets(
    request: ProductSearchRequest,
    products: Sequence[Dict[str, Any]],
    *,
    top_brands_per_bucket: int = 5,
) -> Dict[str, Dict[str, Any]]:
    """Group grounded products into brand buckets for option narrowing."""

    buckets: Dict[str, Dict[str, Any]] = {}
    for category_key in PRICE_CATEGORY_ORDER:
        bucket_products = [
            product
            for product in products
            if _normalize_category_key(product.get("category")) == category_key
        ]
        brand_meta = _brand_bucket_meta(request, bucket_products, limit=top_brands_per_bucket)
        marker_keys = _ordered_unique(key for item in brand_meta for key in item.get("marker_keys") or [])
        prices = [
            value
            for product in bucket_products
            if (value := _coerce_float(product.get("price"))) is not None
        ]
        buckets[_category_slug(category_key)] = {
            "label": PRICE_CATEGORY_DISPLAY.get(category_key, category_key.title()),
            "emoji": _brand_bucket_emoji(category_key),
            "sales_pitch": _brand_bucket_sales_pitch(category_key),
            "brands": [item["brand"] for item in brand_meta],
            "promo_brands": [item["brand"] for item in brand_meta if item.get("promo_marker_keys")],
            "tire_protection_plan_brands": [item["brand"] for item in brand_meta if "tpp" in set(item.get("marker_keys") or [])],
            "marker_legend_keys": marker_keys,
            "brand_meta": brand_meta,
            "product_count": len(bucket_products),
            "brand_count": len(brand_meta),
            "min_price": min(prices) if prices else None,
            "max_price": max(prices) if prices else None,
            "min_price_text": _money_text(min(prices)) if prices else None,
            "max_price_text": _money_text(max(prices)) if prices else None,
        }
    return buckets


def render_brand_bucket_cards(buckets: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return deterministic brand-bucket cards for customer display."""

    cards: List[Dict[str, Any]] = []
    for index, bucket_key in enumerate(["budget", "economy", "mid_range", "premium"], start=1):
        bucket = buckets.get(bucket_key) or {}
        brand_meta = [item for item in bucket.get("brand_meta") or [] if isinstance(item, dict)]
        if not brand_meta:
            continue
        label = str(bucket.get("label") or bucket_key).strip()
        emoji = str(bucket.get("emoji") or "").strip()
        header = f"{emoji} [{label.upper()}]".strip()
        lines = [header]
        sales_pitch = str(bucket.get("sales_pitch") or "").strip()
        if sales_pitch:
            lines.append(sales_pitch)
        for item in brand_meta:
            markers = [str(marker) for marker in item.get("markers") or [] if str(marker).strip()]
            suffix = f" ({' | '.join(markers)})" if markers else ""
            lines.append(f"- {item.get('brand')}{suffix}")
        cards.append(
            {
                "bucket_ref": f"bucket_{index}",
                "choice_ref": f"price_category:{bucket_key}",
                "bucket": bucket_key,
                "label": label,
                "brands": [item.get("brand") for item in brand_meta],
                "promo_brands": [item.get("brand") for item in brand_meta if item.get("promo_marker_keys")],
                "marker_legend_keys": bucket.get("marker_legend_keys") or [],
                "markers_by_brand": {
                    str(item.get("brand") or ""): item.get("markers") or []
                    for item in brand_meta
                    if item.get("markers")
                },
                "product_count": int(bucket.get("product_count") or 0),
                "brand_count": int(bucket.get("brand_count") or len(brand_meta)),
                "min_price": bucket.get("min_price"),
                "max_price": bucket.get("max_price"),
                "min_price_text": bucket.get("min_price_text"),
                "max_price_text": bucket.get("max_price_text"),
                "card_text": "\n".join(lines),
            }
        )
    return cards


def brand_bucket_legend_text(buckets: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """Return a compact legend for deterministic bucket markers."""

    keys = set(
        key
        for bucket in buckets.values()
        for key in bucket.get("marker_legend_keys") or []
    )
    parts: List[str] = []
    if "buy3get1" in keys:
        parts.append("3+1 = Buy 3 Get 1 FREE")
    if "product_discount" in keys:
        parts.append("PHP off/tire = product discount per tire")
    if "tpp" in keys:
        parts.append("TPP = Tire Protection Plan")
    return f"Legend: {'; '.join(parts)}." if parts else None


def presentation_strategy(
    request: ProductSearchRequest,
    cards: Sequence[Dict[str, Any]],
    ranked: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    if request.budget_max is not None:
        mode = "budget_satisfied" if any(
            budget_price_basis(request, product) is not None and budget_price_basis(request, product) <= request.budget_max
            for product in ranked
        ) else "nearest_budget"
    elif request.brands and request.rim_size:
        mode = "size_brand_with_alternatives"
    elif request.rim_size:
        mode = "size_category_mix"
    else:
        mode = "diverse_ranked"
    strategy = {
        "mode": mode,
        "card_count": len(cards),
        "brands": _ordered_unique(card.get("brand") for card in cards),
        "categories": _ordered_unique(card.get("category") for card in cards),
    }
    scopes = _ordered_unique(card.get("presentation_scope") for card in cards)
    if scopes:
        strategy["presentation_scopes"] = scopes
        if "same_rim_alternative" in scopes:
            strategy["alternative_scope"] = "same_rim_alternatives"
        elif "same_full_size_alternative" in scopes:
            strategy["alternative_scope"] = "same_full_size_alternatives"
    if request.budget_max is not None:
        fit_flags = [
            budget_price_basis(request, card) is not None and budget_price_basis(request, card) <= request.budget_max
            for card in cards
        ]
        strategy["budget_fit"] = {
            "scope": request.budget_scope,
            "max": request.budget_max,
            "all_presented_fit": bool(fit_flags) and all(fit_flags),
            "some_presented_fit": any(fit_flags),
        }
    relaxation = _presentation_relaxation_summary(request, cards)
    if relaxation:
        strategy["relaxation"] = relaxation
    return strategy


def _presentation_relaxation_summary(
    request: ProductSearchRequest,
    cards: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not cards or not has_presentation_constraints(request):
        return None
    missing = _ordered_unique(
        miss
        for card in cards
        for miss in _presentation_filter_misses(request, card)
    )
    if not missing:
        return None
    return {
        "applied": True,
        "reason": "no products matched all requested presentation filters",
        "shown_cards_missing_filters": missing,
    }


def product_model_label(product: Dict[str, Any]) -> str:
    brand = str(product.get("brand") or "").strip()
    size = str(product.get("size") or "").strip()
    model = str(product.get("model") or "").strip()
    model_norm = _normalize_match_text(model)
    parts: List[str] = []
    if brand and _normalize_match_text(brand) not in model_norm:
        parts.append(brand)
    if size and _normalize_size_text(size) not in _normalize_size_text(model):
        parts.append(size)
    if model:
        parts.append(model)
    return " ".join(parts) or str(product.get("slug") or product.get("product_id") or "Product")


def product_promo_savings(product: Dict[str, Any], *, quantity: int) -> Optional[str]:
    qty = max(1, int(quantity or 4))
    if qty == 1:
        return None
    total = effective_total_price(product, qty)
    unit = _base_card_unit_price(product)
    if total is None or unit is None:
        return _clean_optional(product.get("promo_label") or product.get("promo_text"))
    bundle = product.get("bundle_pricing") if isinstance(product.get("bundle_pricing"), dict) else {}
    tier = bundle_tier_for_quantity(product, qty)
    if tier and str(bundle.get("source") or "") == "api_product_promo":
        parts = []
        discount_text = _clean_optional(product.get("product_discount_text"))
        if discount_text:
            parts.append(discount_text)
        quantity_promo_amount = _coerce_float(tier.get("quantity_promo_discount_amount"))
        if quantity_promo_amount:
            parts.append(f"Quantity promo: PHP {quantity_promo_amount:,.2f} off")
        return " | ".join(parts) if parts else None
    base_total = round(unit * qty, 2)
    savings = max(0.0, round(base_total - total, 2))
    parts: List[str] = []
    discount_text = _clean_optional(product.get("product_discount_text"))
    if discount_text:
        parts.append(discount_text)
        bundle_savings = _product_discount_bundle_savings(product, qty, total_savings=savings)
        if bundle_savings:
            parts.append(f"🎁 Bundle: Save PHP {bundle_savings:,.2f}")
    sale_discount_text = _clean_optional(product.get("sale_price_discount_text"))
    if sale_discount_text and not discount_text:
        parts.append(sale_discount_text)
    if product.get("promo_label"):
        promo_label = str(product.get("promo_label") or "").strip()
        if has_buy3get1(product) and qty != 4 and "buy 3 get 1" in promo_label.lower():
            pass
        else:
            parts.append(promo_label)
    elif not discount_text and pricing_basis(product, qty) == "bundle_tier" and savings > 0:
        parts.append(f"Bundle: Save PHP {savings:,.2f}")
    elif pricing_basis(product, qty) == "buy3get1":
        parts.append("Buy 3 Get 1 FREE")
    if savings > 0 and not discount_text:
        if not any(part.startswith("Bundle: Save PHP") for part in parts):
            parts.append(f"Save PHP {savings:,.2f}")
    voucher_text = _clean_optional(product.get("voucher_text"))
    voucher_amount = _coerce_float(product.get("voucher_amount"))
    if voucher_text:
        parts.append(voucher_text)
    elif voucher_amount:
        parts.append(f"Voucher: PHP {voucher_amount:,.2f} off")
    if discount_text and savings > 0:
        promo_line = " | ".join(parts)
        return f"{promo_line}\n💸 Save PHP {savings:,.2f}!" if promo_line else f"💸 Save PHP {savings:,.2f}!"
    if not parts and product.get("promo_text"):
        promo_text = _clean_display_promo_text(product.get("promo_text"))
        if promo_text:
            parts.append(promo_text)
    return " | ".join(parts) if parts else None


def _product_discount_bundle_savings(
    product: Dict[str, Any],
    quantity: int,
    *,
    total_savings: float,
) -> Optional[float]:
    """Return the bundle-only savings portion for product-discount cards."""

    product_discount_savings = product_discount_savings_for_quantity(product, quantity)
    if product_discount_savings is None:
        return None
    bundle_savings = round(float(total_savings or 0.0) - product_discount_savings, 2)
    return bundle_savings if bundle_savings > 0 else None


def _base_card_unit_price(product: Dict[str, Any]) -> Optional[float]:
    """Return the one-tire customer price before quantity bundle effects."""

    if (_coerce_float(product.get("product_discount_amount")) or 0.0) > 0:
        list_price = _coerce_float(product.get("list_price"))
        if list_price is not None:
            return round(list_price, 2)
    one_tire_total = effective_total_price(product, 1)
    if one_tire_total is not None:
        return round(one_tire_total, 2)
    return _coerce_float(product.get("price"))


def _deal_price_line(
    product: Dict[str, Any],
    *,
    quantity: int,
    unit_price: Optional[float],
    total_price: Optional[float],
) -> str:
    """Return the customer-facing price line for a product card."""

    qty = max(1, int(quantity or 1))
    base_unit = _base_card_unit_price(product)
    if qty == 1:
        return _money_text(base_unit or unit_price, suffix="/tire") or ""
    bundle = product.get("bundle_pricing") if isinstance(product.get("bundle_pricing"), dict) else {}
    tier = bundle_tier_for_quantity(product, qty)
    if tier and str(bundle.get("source") or "") == "api_product_promo":
        quantity_unit = _coerce_float(tier.get("unit_price_before_quantity_promo"))
        promo_amount = _coerce_float(tier.get("quantity_promo_discount_amount"))
        if quantity_unit is not None and promo_amount is not None:
            return " | ".join(
                [
                    f"{_money_text(quantity_unit, suffix='/tire')} x {qty}",
                    f"{_money_text(total_price)} after {_money_text(promo_amount)} promo",
                ]
            )
    return " | ".join(
        part
        for part in [
            _money_text(base_unit or unit_price, suffix="/tire"),
            _money_text(total_price, suffix=_tire_total_suffix(qty)),
        ]
        if part
    )


def _tire_total_suffix(quantity: int) -> str:
    qty = max(1, int(quantity or 1))
    unit = "tire" if qty == 1 else "tires"
    if qty == 4:
        return f"if for {qty} {unit}"
    return f"for {qty} {unit}"


def _clean_display_promo_text(value: Optional[Any]) -> Optional[str]:
    text = _clean_optional(value)
    if not text:
        return None
    # Some upstream rows put the numeric sale price in promo_text. That is a
    # price fact, not a promotion label, and should not render as a gift line.
    if re.fullmatch(r"(?:php\s*)?[\d,]+(?:\.\d+)?", text, flags=re.IGNORECASE):
        return None
    if not re.search(r"[A-Za-z%+]", text):
        return None
    return text


def buy3get1_quantity_context(request: ProductSearchRequest) -> Optional[Dict[str, Any]]:
    """Explain when a Buy 3 Get 1 request conflicts with a smaller quantity.

    This is model-facing tool guidance. It keeps the deterministic card renderer
    honest and gives the tool loop a concrete way to split a mixed request into
    a current-quantity search and a four-tire promo search.
    """

    promo_types = set(normalize_promo_types(request.promo_types))
    if "buy3get1" not in promo_types:
        return None
    quantity = max(1, int(request.quantity or 4))
    if quantity == 4:
        return None
    regular_args = _product_search_args_from_request(request)
    regular_args["quantity"] = quantity
    regular_args.pop("promo_only", None)
    regular_args.pop("promo_types", None)
    promo_args = _product_search_args_from_request(request)
    promo_args["quantity"] = 4
    promo_args["promo_only"] = True
    promo_args["promo_types"] = ["buy3get1"]
    return {
        "status": "quantity_promo_conflict",
        "current_quantity": quantity,
        "promo_type": "buy3get1",
        "promo_requires_quantity": 4,
        "customer_explanation": (
            "Buy 3 Get 1 FREE is a four-tire promo path. Do not present it as "
            f"applying to {quantity} tire(s)."
        ),
        "recommended_response_strategy": (
            "Compare regular options for the current quantity with separate "
            "quantity=4 Buy 3 Get 1 FREE options before finalizing."
        ),
        "suggested_followup_searches": [
            {
                "label": "current_quantity_regular_options",
                "tool": "product_search",
                "args": _strip_empty_values(regular_args),
            },
            {
                "label": "four_tire_buy3get1_options",
                "tool": "product_search",
                "args": _strip_empty_values(promo_args),
            },
        ],
    }


def _product_search_args_from_request(request: ProductSearchRequest) -> Dict[str, Any]:
    args: Dict[str, Any] = {
        "section_width": request.section_width,
        "aspect_ratio": request.aspect_ratio,
        "rim_size": request.rim_size,
        "required_brands": list(request.brands or []),
        "brand_match_mode": request.brand_match_mode if request.brands else None,
        "preferred_brands": list(request.preferred_brands or []),
        "excluded_brands": list(request.excluded_brands or []),
        "model_or_pattern": request.model_or_pattern,
        "budget_max": request.budget_max,
        "budget_scope": request.budget_scope,
        "promo_only": request.promo_only,
        "promo_types": list(request.promo_types or []),
        "ev_compatible": request.ev_compatible,
        "gulong_guarantee_only": request.gulong_guarantee_only,
        "gulong_guarantee_tiers": list(request.gulong_guarantee_tiers or []),
        "origins": list(request.origins or []),
        "excluded_origins": list(request.excluded_origins or []),
        "warranty_years": list(request.warranty_years or []),
        "tire_categories": list(request.tire_categories or []),
        "excluded_tire_categories": list(request.excluded_tire_categories or []),
        "terrain_types": list(request.terrain_types or []),
        "availability": request.availability,
        "installment_only": request.installment_only,
        "installment_banks": list(request.installment_banks or []),
        "installment_months": list(request.installment_months or []),
        "installment_max_interest": request.installment_max_interest,
        "ply_rating": request.ply_rating,
        "quantity": request.quantity,
        "sort": request.sort,
        "top_k": request.top_k,
        "semantic_query": request.semantic_query,
        "soft_preferences": list(request.soft_preferences or []),
    }
    return args


def _strip_empty_values(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, "", [], {})
    }


def card_reason(request: ProductSearchRequest, product: Dict[str, Any]) -> str:
    scope = str(product.get("presentation_scope") or "").strip()
    if scope == "requested_brand_model_rim_anchor":
        return "matches requested brand/model/rim"
    if scope == "same_full_size_alternative":
        return "same tire size alternative"
    if scope == "same_rim_alternative":
        return "same rim alternative"
    match = product.get("match") or {}
    passed = set(match.get("passed_filters") or [])
    missed = set(match.get("missed_filters") or [])
    core_misses = missed.intersection({"section_width", "aspect_ratio", "rim_size"})
    if product_matches_preferred_brand(request, product):
        return "preferred brand option"
    if request.budget_max is not None:
        price_basis = budget_price_basis(request, product)
        if price_basis is not None and price_basis <= request.budget_max:
            return "within requested budget"
        return "nearest option to requested budget"
    if request.brands and str(product.get("brand") or "").upper() not in set(request.brands):
        return "alternative brand option"
    if request.brands and core_misses:
        return "requested brand alternative with a different tire size"
    if "tire_category" in passed:
        return "matches requested price category"
    if request.rim_size and core_misses:
        return "same rim alternative"
    if request.rim_size:
        return "matches requested size/rim"
    return "ranked product option"


def _select_budget_cards(
    request: ProductSearchRequest,
    candidates: Sequence[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    within = [
        product
        for product in candidates
        if budget_price_basis(request, product) is not None and budget_price_basis(request, product) <= request.budget_max
    ]
    if within:
        selected = _select_diverse_cards(request, within, limit)
        target = min(limit, PRESENTATION_TARGET_CARD_COUNT)
        if len(selected) >= target:
            return selected
        used_keys = {product_key(product) for product in selected if product_key(product)}
        alternatives = _budget_alternative_candidates(request, candidates, used_keys)
        return _fill_diverse_cards(request, selected, used_keys, alternatives, target, preserve_order=True)
    priced = [
        product
        for product in candidates
        if budget_price_basis(request, product) is not None
    ]
    priced.sort(
        key=lambda product: (
            abs((budget_price_basis(request, product) or 0) - (request.budget_max or 0)),
            _presentation_sort_key(request, product),
        )
    )
    return _select_diverse_cards(request, priced or candidates, limit, preserve_order=True)


def _budget_alternative_candidates(
    request: ProductSearchRequest,
    candidates: Sequence[Dict[str, Any]],
    used_keys: set[str],
) -> List[Dict[str, Any]]:
    budget = float(request.budget_max or 0)
    priced: List[Dict[str, Any]] = []
    unpriced: List[Dict[str, Any]] = []
    for product in candidates:
        key = product_key(product)
        if not key or key in used_keys:
            continue
        price_basis = budget_price_basis(request, product)
        if price_basis is None:
            unpriced.append(product)
        else:
            priced.append(product)

    def sort_key(product: Dict[str, Any]) -> Tuple[Any, ...]:
        price_basis = budget_price_basis(request, product) or 0
        match = product.get("match") or {}
        return (
            0 if price_basis >= budget else 1,
            abs(price_basis - budget),
            -int(match.get("match_score") or 0),
            _coerce_float(product.get("price")) or 0,
            str(product.get("brand") or ""),
        )

    priced.sort(key=sort_key)
    return priced + unpriced


def _select_size_only_cards(request: ProductSearchRequest, candidates: Sequence[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    used_keys: set[str] = set()
    category_order = tuple(reversed(PRICE_CATEGORY_ORDER)) if _is_general_size_price_ladder_request(request) else PRICE_CATEGORY_ORDER
    for category in category_order:
        category_candidates = [
            item
            for item in candidates
            if _category_key(item) == category and product_key(item) not in used_keys
        ]
        product = _best_presentation_product(request, category_candidates)
        if product:
            _append_card(selected, used_keys, product, limit)
        if len(selected) >= limit:
            return selected
    return _fill_diverse_cards(request, selected, used_keys, candidates, limit)


def _select_size_brand_cards(
    request: ProductSearchRequest,
    candidates: Sequence[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    if request.model_or_pattern:
        selected = _select_brand_model_rim_cards(request, candidates, limit)
        if selected:
            return selected
    requested = set(request.brands)
    selected: List[Dict[str, Any]] = []
    used_keys: set[str] = set()
    requested_candidates = [item for item in candidates if str(item.get("brand") or "").upper() in requested]
    requested_anchor_candidates = _requested_brand_anchor_candidates(request, requested_candidates)
    has_alternative_brand_candidates = any(
        str(item.get("brand") or "").upper() not in requested
        for item in candidates
    )
    requested_target = min(
        PRESENTATION_TARGET_CARD_COUNT if has_alternative_brand_candidates else limit,
        limit,
    )
    for product in _sort_presentation_candidates(request, requested_anchor_candidates):
        _append_card(selected, used_keys, product, limit)
        if len(selected) >= requested_target:
            break
    if not selected:
        anchor = _best_presentation_product(request, requested_candidates) or _best_presentation_product(request, candidates)
        _append_card(selected, used_keys, anchor, limit)
    anchor = selected[0] if selected else None
    anchor_category = (
        _normalize_category_key(request.tire_categories[0])
        if request.tire_categories
        else (_category_key(anchor) if anchor else None)
    )
    for category in _category_priority(anchor_category):
        category_candidates = [
            product
            for product in candidates
            if _category_key(product) == category and str(product.get("brand") or "").upper() not in requested
        ]
        product = _best_presentation_product(request, category_candidates)
        if product:
            _append_card(selected, used_keys, product, limit)
        if len(selected) >= limit:
            return selected
    return _fill_diverse_cards(request, selected, used_keys, candidates, limit)


def _requested_brand_anchor_candidates(
    request: ProductSearchRequest,
    requested_candidates: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Prefer requested-brand cards that still match the requested size scope."""

    if not (request.section_width or request.aspect_ratio):
        return list(requested_candidates)
    strong = [
        product
        for product in requested_candidates
        if str((product.get("match") or {}).get("tier") or "") in {"exact", "near_exact"}
    ]
    return strong or list(requested_candidates)


def _select_brand_model_rim_cards(
    request: ProductSearchRequest,
    candidates: Sequence[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    """Keep brand/model/rim presentations anchored to the exact product size."""

    requested = set(request.brands)
    requested_candidates = [
        item
        for item in candidates
        if str(item.get("brand") or "").upper() in requested
    ]
    exact_requested = [
        item
        for item in requested_candidates
        if str((item.get("match") or {}).get("tier") or "") == "exact"
    ]
    anchor = _best_presentation_product(request, exact_requested) or _best_presentation_product(request, requested_candidates)
    if not anchor:
        return []

    card_limit = max(1, min(PRESENTATION_MAX_CARD_COUNT, int(limit or PRESENTATION_TARGET_CARD_COUNT)))
    target = min(card_limit, PRESENTATION_TARGET_CARD_COUNT)
    selected: List[Dict[str, Any]] = []
    used_keys: set[str] = set()
    _append_card(selected, used_keys, _with_presentation_scope(anchor, "requested_brand_model_rim_anchor"), card_limit)

    anchor_size = _product_full_size_key(anchor)
    if not anchor_size:
        return selected

    same_full_size = [
        product
        for product in candidates
        if product_key(product) not in used_keys and _product_full_size_key(product) == anchor_size
    ]
    for product in _sort_presentation_candidates(request, same_full_size):
        _append_card(selected, used_keys, _with_presentation_scope(product, "same_full_size_alternative"), target)
        if len(selected) >= target:
            return selected

    if not _explicit_product_alternatives_allowed(request):
        return selected

    same_rim = [
        product
        for product in candidates
        if product_key(product) not in used_keys
        and request.rim_size
        and rim_matches(request.rim_size, product.get("rim_size"))
    ]
    for product in _sort_presentation_candidates(request, same_rim):
        _append_card(selected, used_keys, _with_presentation_scope(product, "same_rim_alternative"), target)
        if len(selected) >= target:
            return selected
    return selected


def _product_full_size_key(product: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    section = str(product.get("section_width") or "").strip()
    aspect = str(product.get("aspect_ratio") or "").strip()
    rim = normalize_rim_size(product.get("rim_size"), section_width=section)
    if not (section and aspect and rim):
        return None
    return (section, aspect, str(rim).upper())


def _with_presentation_scope(product: Dict[str, Any], scope: str) -> Dict[str, Any]:
    scoped = dict(product)
    scoped["presentation_scope"] = scope
    return scoped


def _explicit_product_alternatives_allowed(request: ProductSearchRequest) -> bool:
    text = " ".join(str(item or "") for item in request.soft_preferences or []).lower()
    if not text:
        return False
    return any(token in text for token in ("alternative", "alternatives", "other option", "other brand", "compare"))


def _select_diverse_cards(
    request: ProductSearchRequest,
    candidates: Sequence[Dict[str, Any]],
    limit: int,
    *,
    preserve_order: bool = False,
) -> List[Dict[str, Any]]:
    return _fill_diverse_cards(request, [], set(), candidates, limit, preserve_order=preserve_order)


def _fill_diverse_cards(
    request: ProductSearchRequest,
    selected: List[Dict[str, Any]],
    used_keys: set[str],
    candidates: Sequence[Dict[str, Any]],
    limit: int,
    *,
    preserve_order: bool = False,
) -> List[Dict[str, Any]]:
    used_brands = {str(product.get("brand") or "").upper() for product in selected}
    used_categories = {_category_key(product) for product in selected}
    sorted_candidates = list(candidates) if preserve_order else _sort_presentation_candidates(request, candidates)
    for product in sorted_candidates:
        if str(product.get("brand") or "").upper() in used_brands:
            continue
        if _category_key(product) in used_categories:
            continue
        if _append_card(selected, used_keys, product, limit):
            used_brands.add(str(product.get("brand") or "").upper())
            used_categories.add(_category_key(product))
        if len(selected) >= limit:
            return selected
    for product in sorted_candidates:
        if str(product.get("brand") or "").upper() in used_brands:
            continue
        if _append_card(selected, used_keys, product, limit):
            used_brands.add(str(product.get("brand") or "").upper())
        if len(selected) >= limit:
            return selected
    for product in sorted_candidates:
        _append_card(selected, used_keys, product, limit)
        if len(selected) >= limit:
            return selected
    return selected


def _best_presentation_product(
    request: ProductSearchRequest,
    candidates: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    sorted_candidates = _sort_presentation_candidates(request, candidates)
    return sorted_candidates[0] if sorted_candidates else None


def _sort_presentation_candidates(
    request: ProductSearchRequest,
    candidates: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return sorted(candidates, key=lambda product: _presentation_sort_key(request, product))


def _presentation_sort_key(request: ProductSearchRequest, product: Dict[str, Any]) -> Tuple[Any, ...]:
    total = effective_total_price(product, max(1, int(request.quantity or 4)))
    unit_price = _coerce_float(product.get("price"))
    return (
        -_presentation_match_score(request, product),
        1 if product.get("pre_order") else 0,
        _premium_brand_preference_rank(request, product),
        0 if product_matches_preferred_brand(request, product) else 1,
        0 if has_priority_promo(product) else 1,
        total if total is not None else float("inf"),
        unit_price if unit_price is not None else float("inf"),
        str(product.get("brand") or ""),
        str(product.get("model") or ""),
    )


def _presentation_match_score(request: ProductSearchRequest, product: Dict[str, Any]) -> int:
    """Return match score without double-counting soft brand preferences."""

    match = product.get("match") or {}
    score = int(match.get("match_score") or 0)
    if product_matches_preferred_brand(request, product):
        score -= 7
    return score


def _premium_brand_preference_rank(request: ProductSearchRequest, product: Dict[str, Any]) -> int:
    """Prefer Michelin for broad Premium presentations unless brand-constrained."""

    if not _premium_michelin_preference_applies(request, product):
        return 0
    brand = str(product.get("brand") or "").strip().upper()
    if brand == "MICHELIN":
        return 0
    if brand == "YOKOHAMA":
        return 1
    return 2


def _premium_michelin_preference_applies(request: ProductSearchRequest, product: Dict[str, Any]) -> bool:
    if _category_key(product) != "PREMIUM":
        return False
    if request.brands or request.model_or_pattern:
        return False
    if request.budget_max is not None or request.promo_only is True or request.promo_types:
        return False
    if _is_general_size_price_ladder_request(request):
        return True
    if request.tire_categories and "PREMIUM" in set(request.tire_categories):
        return True
    soft_text = " ".join(str(item or "") for item in request.soft_preferences or []).lower()
    return "premium" in soft_text


def _ensure_preferred_brand_cards(
    request: ProductSearchRequest,
    selected: Sequence[Dict[str, Any]],
    candidates: Sequence[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    preferred = set(request.preferred_brands)
    if not preferred or limit <= 0:
        return list(selected)

    preferred_candidates = [
        product
        for product in candidates
        if product_matches_preferred_brand(request, product)
    ]
    if not preferred_candidates:
        return list(selected)

    target = min(2, limit, len({product_key(product) for product in preferred_candidates if product_key(product)}))
    result = list(selected)
    used_keys = {product_key(product) for product in result if product_key(product)}

    current_count = sum(1 for product in result if product_matches_preferred_brand(request, product))
    for product in _sort_presentation_candidates(request, preferred_candidates):
        if current_count >= target:
            break
        key = product_key(product)
        if not key or key in used_keys:
            continue
        result.append(product)
        used_keys.add(key)
        current_count += 1

    while len(result) > limit:
        removable = [
            (index, product)
            for index, product in enumerate(result)
            if not product_matches_preferred_brand(request, product)
        ]
        if not removable:
            result.pop()
            continue
        remove_index, _ = max(removable, key=lambda item: _presentation_sort_key(request, item[1]))
        result.pop(remove_index)

    preferred_cards = [product for product in result if product_matches_preferred_brand(request, product)]
    other_cards = [product for product in result if not product_matches_preferred_brand(request, product)]
    return preferred_cards + other_cards


def _append_card(selected: List[Dict[str, Any]], used_keys: set[str], product: Dict[str, Any], limit: int) -> bool:
    key = product_key(product)
    if not key or key in used_keys or len(selected) >= limit:
        return False
    selected.append(product)
    used_keys.add(key)
    return True


def _category_priority(anchor_category: Optional[str]) -> List[str]:
    if anchor_category not in PRICE_CATEGORY_ORDER:
        return list(PRICE_CATEGORY_ORDER)
    index = PRICE_CATEGORY_ORDER.index(anchor_category)
    ordered = [anchor_category]
    for offset in range(1, len(PRICE_CATEGORY_ORDER)):
        lower = index - offset
        upper = index + offset
        if lower >= 0:
            ordered.append(PRICE_CATEGORY_ORDER[lower])
        if upper < len(PRICE_CATEGORY_ORDER):
            ordered.append(PRICE_CATEGORY_ORDER[upper])
    return ordered


def _category_key(product: Dict[str, Any]) -> Optional[str]:
    return _normalize_category_key(product.get("category")) or _clean_optional(product.get("category"))


def _category_display(value: Any) -> str:
    key = _normalize_category_key(value)
    if key:
        return PRICE_CATEGORY_DISPLAY.get(key, key.title())
    text = str(value or "").strip()
    return text if text else "Other Options"


def _ordered_unique(values: Iterable[Any]) -> List[str]:
    out: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def fuzzy_token_coverage(query_tokens: Iterable[str], text_tokens: Iterable[str]) -> float:
    query_list = [token for token in query_tokens if token]
    text_list = [token for token in text_tokens if token]
    if not query_list or not text_list:
        return 0.0
    scores: List[float] = []
    for query_token in query_list:
        best = max((token_similarity(query_token, text_token) for text_token in text_list), default=0.0)
        if best < fuzzy_token_floor(query_token):
            best = 0.0
        scores.append(best)
    return sum(scores) / max(1, len(scores))


def best_phrase_ratio(query_tokens: Sequence[str], text_tokens: Sequence[str]) -> float:
    if not query_tokens or not text_tokens:
        return 0.0
    query = " ".join(query_tokens)
    window_sizes = {len(query_tokens)}
    if len(query_tokens) > 1:
        window_sizes.add(len(query_tokens) + 1)
        window_sizes.add(max(1, len(query_tokens) - 1))
    best = 0.0
    for window_size in sorted(window_sizes):
        if window_size > len(text_tokens):
            continue
        for start in range(0, len(text_tokens) - window_size + 1):
            phrase = " ".join(text_tokens[start : start + window_size])
            best = max(best, difflib.SequenceMatcher(None, query, phrase).ratio())
    return best if best >= 0.72 else 0.0


def token_similarity(query_token: str, text_token: str) -> float:
    if query_token == text_token:
        return 1.0
    if len(query_token) >= 2 and text_token.startswith(query_token):
        return 0.9
    if len(text_token) >= 2 and query_token.startswith(text_token):
        return 0.86
    return difflib.SequenceMatcher(None, query_token, text_token).ratio()


def fuzzy_token_floor(query_token: str) -> float:
    length = len(query_token)
    if length <= 2:
        return 0.92
    if length <= 4:
        return 0.84
    return 0.74


def semantic_match_score(request: ProductSearchRequest, product: Dict[str, Any]) -> int:
    text = " ".join(
        str(value or "")
        for value in [
            product.get("model"),
            product.get("pattern"),
            product.get("description"),
            product.get("features"),
            product.get("category"),
            product.get("origin"),
            product.get("warranty"),
            " ".join(product.get("terrain_types") or []),
        ]
    )
    query = " ".join([request.semantic_query or "", *request.soft_preferences])
    query_tokens = set(_normalize_match_text(query).split())
    if not query_tokens:
        return 0
    text_tokens = set(_normalize_match_text(text).split())
    overlap = len(query_tokens.intersection(text_tokens))
    return min(5, overlap)


def budget_price_basis(request: ProductSearchRequest, product: Dict[str, Any]) -> Optional[float]:
    if request.budget_scope == "total":
        return effective_total_price(product, max(1, int(request.quantity or 4)))
    total = effective_total_price(product, max(1, int(request.quantity or 4)))
    if total is not None:
        return total / max(1, int(request.quantity or 4))
    return _coerce_float(product.get("price"))


def product_discount_savings_for_quantity(product: Dict[str, Any], quantity: int) -> Optional[float]:
    qty = max(1, int(quantity or 4))
    discount_amount = _coerce_float(product.get("product_discount_amount"))
    if discount_amount:
        return round(discount_amount * qty, 2)
    tier = bundle_tier_for_quantity(product, qty)
    if tier:
        before_discount = _coerce_float(tier.get("pre_discount_total_price"))
        after_discount = _coerce_float(tier.get("total_price"))
        if before_discount is not None and after_discount is not None and before_discount > after_discount:
            return round(before_discount - after_discount, 2)
    return None


def effective_total_price(product: Dict[str, Any], quantity: int) -> Optional[float]:
    price = _coerce_float(product.get("price"))
    if price is None:
        return None
    qty = max(1, int(quantity or 4))
    if qty == 4 and has_buy3get1(product):
        return round(price * 3, 2)
    tier = bundle_tier_for_quantity(product, qty)
    if tier:
        total = _coerce_float(tier.get("total_price"))
        if total is not None:
            return round(total, 2)
    return round(price * qty, 2)


def pricing_basis(product: Dict[str, Any], quantity: int) -> str:
    qty = max(1, int(quantity or 4))
    if qty == 4 and has_buy3get1(product):
        return "buy3get1"
    if bundle_tier_for_quantity(product, qty):
        return "bundle_tier"
    return "unit_price"


def bundle_tier_for_quantity(product: Dict[str, Any], quantity: int) -> Optional[Dict[str, Any]]:
    bundle = product.get("bundle_pricing") if isinstance(product.get("bundle_pricing"), dict) else {}
    tiers = bundle.get("tiers") if isinstance(bundle, dict) else None
    if not isinstance(tiers, list):
        return None
    qty = max(1, int(quantity or 4))
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        try:
            tier_qty = int(tier.get("quantity") or 0)
        except Exception:
            tier_qty = 0
        if tier_qty == qty:
            return tier
    return None


def has_promo(product: Dict[str, Any]) -> bool:
    text = " ".join(str(product.get(key) or "") for key in ["promo_label", "promo_text"]).lower()
    return bool(text.strip())


def has_buy3get1(product: Dict[str, Any]) -> bool:
    return bool(product.get("buy3get1_eligible"))


def has_product_discount(product: Dict[str, Any]) -> bool:
    return bool(
        (_coerce_float(product.get("product_discount_amount")) or 0) > 0
        or (_coerce_float(product.get("sale_price_discount_amount")) or 0) > 0
    )


def has_active_promo(product: Dict[str, Any]) -> bool:
    return bool(has_buy3get1(product) or has_product_discount(product) or product.get("promo_label") == "Clearance Sale")


def has_priority_promo(product: Dict[str, Any]) -> bool:
    """Return whether a product should be promoted in representative cards.

    Bundle-tier pricing is intentionally not counted here; it is a standing
    pricing rule and would make almost every product look like a promo.
    """

    voucher_amount = _coerce_float(product.get("voucher_amount"))
    voucher_text = _clean_optional(product.get("voucher_text"))
    return bool(has_active_promo(product) or voucher_amount or voucher_text)


def product_matches_preferred_brand(request: ProductSearchRequest, product: Dict[str, Any]) -> bool:
    return bool(request.preferred_brands and str(product.get("brand") or "").upper() in set(request.preferred_brands))


def _preferred_brand_presentation_status(
    request: ProductSearchRequest,
    ranked: Sequence[Dict[str, Any]],
    presented: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Explain soft preferred-brand carryover without overriding hard filters."""

    requested = _ordered_unique(request.preferred_brands)
    if not requested:
        return {"requested": [], "matched": [], "presented": [], "not_presented": []}

    matched_products = [
        product
        for product in ranked
        if str(product.get("brand") or "").upper() in set(requested)
    ]
    matched = _ordered_unique(product.get("brand") for product in matched_products)
    presented_brands = _ordered_unique(
        product.get("brand")
        for product in presented
        if str(product.get("brand") or "").upper() in set(requested)
    )
    not_presented = [brand for brand in matched if brand not in set(presented_brands)]
    reasons: List[Dict[str, Any]] = []
    presented_keys = {product_key(product) for product in presented if product_key(product)}
    for brand in not_presented:
        brand_products = [
            product
            for product in matched_products
            if str(product.get("brand") or "").upper() == str(brand).upper()
            and product_key(product) not in presented_keys
        ]
        best = _best_presentation_product(request, brand_products)
        if not best:
            continue
        missed_filters = _presentation_filter_misses(request, best)
        reasons.append(
            _compact_status_unit(
                {
                    "brand": brand,
                    "reason": (
                        "matched remembered preferred brand but was not shown because it misses active presentation filters"
                        if missed_filters
                        else "matched remembered preferred brand but lower-ranked options better fit the latest request"
                    ),
                    "missed_filters": missed_filters,
                    "best_available_category": _category_display(best.get("category")),
                    "best_available_size": best.get("size"),
                }
            )
        )
    return {
        "requested": requested,
        "matched": matched,
        "presented": presented_brands,
        "not_presented": not_presented,
        "not_presented_reasons": reasons,
    }


def _compact_status_unit(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def product_matches_promo_request(request: ProductSearchRequest, product: Dict[str, Any]) -> bool:
    promo_types = set(normalize_promo_types(request.promo_types))
    if not promo_types or "any" in promo_types:
        return has_active_promo(product)
    if "buy3get1" in promo_types and has_buy3get1(product):
        return True
    if "product_discount" in promo_types and has_product_discount(product):
        return True
    if "clearance" in promo_types and product.get("promo_label") == "Clearance Sale":
        return True
    return False


def gulong_guarantee_tier(product: Dict[str, Any]) -> int:
    try:
        tier = int(product.get("gulong_guarantee") or 0)
    except Exception:
        return 0
    return tier if tier in (1, 2) else 0


def _dedupe_groups(groups: Sequence[Sequence[_AttemptSpec]]) -> List[List[_AttemptSpec]]:
    seen: set[Tuple[Tuple[str, Any], ...]] = set()
    clean: List[List[_AttemptSpec]] = []
    for group in groups:
        specs: List[_AttemptSpec] = []
        for spec in group:
            key = flatten_query_params(spec.params)
            if key in seen:
                continue
            seen.add(key)
            specs.append(spec)
        if specs:
            clean.append(specs)
    return clean


def _split_brand_values(value: Any) -> List[str]:
    values = _normalize_string_list(value)
    split_values: List[str] = []
    for item in values:
        split_values.extend(part for part in re.split(r"--|,|/|\bor\b|\band\b", item, flags=re.I) if part.strip())
    out: List[str] = []
    for item in split_values:
        brand = str(item or "").strip()
        if brand and brand not in out:
            out.append(brand)
    return out


def _normalize_brands(value: Any, *, canonical_brands: Optional[Iterable[str]] = None) -> List[str]:
    brands, _ = normalize_brands_with_corrections(value, canonical_brands=canonical_brands)
    return brands


def _brand_inputs_need_catalog_lookup(values: Sequence[Any]) -> bool:
    default_lookup = _canonical_brand_lookup()
    for value in _flatten_brand_values(values):
        canonical, correction = normalize_brand_value(value)
        if not canonical:
            continue
        key = _brand_match_key(canonical)
        if correction or key in default_lookup:
            continue
        return True
    return False


def _flatten_brand_values(values: Sequence[Any]) -> List[str]:
    output: List[str] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            output.extend(_flatten_brand_values(list(value)))
        else:
            text = str(value or "").strip()
            if text:
                output.append(text)
    return output


def normalize_brands_with_corrections(
    value: Any,
    *,
    canonical_brands: Optional[Iterable[str]] = None,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Normalize requested brand text to canonical catalog brand names.

    The model may output likely brand text from the customer message, including
    typo forms. This normalizer owns the canonical API value so typo brands do
    not become guaranteed zero-result `/shop` calls.
    """

    split_values = _split_brand_values(value)
    out: List[str] = []
    corrections: List[Dict[str, Any]] = []
    for item in split_values:
        raw = str(item or "").strip()
        brand, correction = normalize_brand_value(raw, canonical_brands=canonical_brands)
        if brand and brand not in out:
            out.append(brand)
        if correction:
            corrections.append(correction)
    return out, corrections


def normalize_brand_value(
    value: Any,
    *,
    canonical_brands: Optional[Iterable[str]] = None,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    raw = str(value or "").strip()
    if not raw:
        return None, None

    raw_display = _normalize_brand_display(raw)
    key = _brand_match_key(raw)
    if not key:
        return None, None

    canonical_by_key = _canonical_brand_lookup(canonical_brands)
    alias = BRAND_ALIASES.get(key)
    if alias:
        correction = None
        if alias != raw_display:
            correction = {
                "input": raw,
                "canonical": alias,
                "method": "alias",
                "score": 1.0,
            }
        return alias, correction

    exact = canonical_by_key.get(key)
    if exact:
        correction = None
        if exact != raw_display:
            correction = {
                "input": raw,
                "canonical": exact,
                "method": "canonical_key",
                "score": 1.0,
            }
        return exact, correction

    fuzzy = _fuzzy_canonical_brand(key, canonical_by_key)
    if fuzzy:
        canonical, score = fuzzy
        return canonical, {
            "input": raw,
            "canonical": canonical,
            "method": "fuzzy",
            "score": round(score, 3),
        }

    return raw_display, None


def _canonical_brand_lookup(canonical_brands: Optional[Iterable[str]] = None) -> Dict[str, str]:
    brands = list(DEFAULT_CANONICAL_BRANDS)
    if canonical_brands:
        for brand in canonical_brands:
            normalized = _normalize_brand_display(brand)
            if normalized and normalized not in brands:
                brands.append(normalized)
    return {
        _brand_match_key(brand): _normalize_brand_display(brand)
        for brand in brands
        if _brand_match_key(brand)
    }


def _fuzzy_canonical_brand(key: str, canonical_by_key: Dict[str, str]) -> Optional[Tuple[str, float]]:
    if len(key) <= 2:
        return None

    scored = sorted(
        (
            (difflib.SequenceMatcher(None, key, candidate_key).ratio(), candidate_key)
            for candidate_key in canonical_by_key
        ),
        reverse=True,
    )
    if not scored:
        return None
    best_score, best_key = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    threshold = _brand_fuzzy_threshold(key)
    clear_winner = best_score >= 0.9 or best_score - second_score >= 0.06
    if best_score >= threshold and clear_winner:
        return canonical_by_key[best_key], best_score
    return None


def _brand_fuzzy_threshold(key: str) -> float:
    if len(key) <= 4:
        return 0.9
    if len(key) <= 7:
        return 0.86
    return 0.82


def _normalize_brand_display(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().upper())


def _brand_match_key(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def normalize_origins(value: Any) -> List[str]:
    """Normalize country-origin filters while tolerating catalog spelling drift."""

    values = _normalize_string_list(value)
    out: List[str] = []
    for item in values:
        for part in re.split(r",|/|\bor\b|\band\b", item, flags=re.I):
            origin = _normalize_origin_key(part)
            if origin and origin not in out:
                out.append(origin)
    return out


def normalize_tire_categories(value: Any) -> List[str]:
    """Normalize price/tire category facets such as Budget and Mid Range."""

    values = _normalize_string_list(value)
    out: List[str] = []
    for item in values:
        for part in re.split(r",|/|\bor\b|\band\b", item, flags=re.I):
            category = _normalize_category_key(part)
            if category and category not in out:
                out.append(category)
    return out


def normalize_warranty_years(value: Any) -> List[int]:
    values = _normalize_string_list(value)
    out: List[int] = []
    for item in values:
        for match in re.findall(r"\d+", str(item)):
            try:
                parsed = int(match)
            except Exception:
                continue
            if parsed > 0 and parsed not in out:
                out.append(parsed)
    return out


def normalize_terrain_types(value: Any) -> List[str]:
    values = _normalize_string_list(value)
    out: List[str] = []
    for item in values:
        for terrain_type in _terrain_types_from_text(str(item)):
            if terrain_type not in out:
                out.append(terrain_type)
    return out


def normalize_promo_types(value: Any) -> List[str]:
    values = _normalize_string_list(value)
    aliases = {
        "ANY": "any",
        "PROMO": "any",
        "PROMOS": "any",
        "DISCOUNT": "product_discount",
        "DISCOUNTS": "product_discount",
        "PRODUCT DISCOUNT": "product_discount",
        "VOUCHER": "product_discount",
        "VOUCHERS": "product_discount",
        "BUY 3 GET 1": "buy3get1",
        "BUY3GET1": "buy3get1",
        "B3G1": "buy3get1",
        "3+1": "buy3get1",
        "BUY 3 GET 1 FREE": "buy3get1",
        "CLEARANCE": "clearance",
        "CLEARANCE SALE": "clearance",
    }
    out: List[str] = []
    for item in values:
        for part in re.split(r",|/|\bor\b|\band\b", item, flags=re.I):
            key = re.sub(r"[^A-Z0-9+]+", " ", str(part or "").upper()).strip()
            normalized = aliases.get(key)
            if not normalized and key in {"BUY 3", "GET 1"}:
                normalized = "buy3get1"
            if normalized and normalized not in out:
                out.append(normalized)
    return out


def _promo_types_imply_promo_only(promo_types: Sequence[str], *, quantity: int) -> bool:
    """Treat named promo-type filters as hard filters when the quantity can support them."""

    requested = {str(item or "").strip().lower() for item in promo_types if str(item or "").strip()}
    requested.discard("any")
    if not requested:
        return False
    if requested == {"buy3get1"} and quantity != 4:
        return False
    return True


def normalize_installment_banks(value: Any) -> List[str]:
    values = _normalize_string_list(value)
    out: List[str] = []
    aliases = {
        "BPI": "BPI",
        "BDO": "BDO",
        "METROBANK": "Metrobank",
        "METRO BANK": "Metrobank",
        "EASTWEST": "EastWest",
        "EAST WEST": "EastWest",
        "HSBC": "HSBC",
        "CHINABANK": "China Bank",
        "CHINA BANK": "China Bank",
    }
    for item in values:
        for part in re.split(r",|/|\bor\b|\band\b", item, flags=re.I):
            key = re.sub(r"[^A-Z0-9]+", " ", str(part or "").upper()).strip()
            bank = aliases.get(key)
            if bank and bank not in out:
                out.append(bank)
    return out


def normalize_availability(payload: Dict[str, Any]) -> str:
    value = payload.get("availability")
    if value is None:
        pre_order_only = _coerce_optional_bool(payload.get("pre_order_only"))
        in_stock_only = _coerce_optional_bool(payload.get("in_stock_only"))
        if pre_order_only is True:
            return "pre_order"
        if in_stock_only is True or pre_order_only is False:
            return "in_stock"
        return "any"
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"preorder", "pre_order", "pre_order_only"}:
        return "pre_order"
    if text in {"stock", "in_stock", "available", "available_now", "on_hand"}:
        return "in_stock"
    return "any"


def normalize_brand_match_mode(value: Any) -> str:
    """Return the canonical requested-brand presentation policy.

    A named brand normally expresses a ranking preference, not permission to
    hide every exact-fitment alternative. ``strict`` is reserved for an
    explicit customer prohibition such as "Michelin only" or "no other
    brands".
    """

    text = re.sub(r"[^a-z]+", "_", str(value or "").strip().casefold()).strip("_")
    return "strict" if text in {"strict", "only", "required", "no_alternatives"} else "prefer"


def normalize_installments(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        bank = normalize_installment_banks(item.get("bank_name") or item.get("bank"))
        months = _coerce_int(item.get("months_to_pay") or item.get("months"), default=0, minimum=0, maximum=120)
        interest = _coerce_float(item.get("percent_interest") if item.get("percent_interest") is not None else item.get("interest"))
        if not bank or months <= 0:
            continue
        row = {
            "bank_name": bank[0],
            "months_to_pay": months,
            "percent_interest": float(interest or 0.0),
        }
        out.append(row)
    return out


def _checkout_payment_row_text(row: Dict[str, Any]) -> str:
    """Return API checkout fields used to identify bank and installment term."""

    return " ".join(
        str(row.get(key) or "")
        for key in ("name", "label", "value", "description", "icons")
    )


def _checkout_installments_for_brand(
    payment_rows: Sequence[Dict[str, Any]],
    brand_value: Any,
) -> List[Dict[str, Any]]:
    """Project active checkout eligibility into product-search filter rows."""

    normalized_brand = _normalize_brands(brand_value)
    brand = normalized_brand[0] if normalized_brand else ""
    rows: List[Dict[str, Any]] = []
    for payment in payment_rows:
        allowed_brands = {
            _normalize_brands(value)[0]
            for value in str(payment.get("available_brands") or "").split(",")
            if _normalize_brands(value)
        }
        if allowed_brands and brand not in allowed_brands:
            continue
        text = _checkout_payment_row_text(payment)
        banks = payment_provider_names_from_row(payment)
        months_match = re.search(r"\b(\d+)[\s-]*(?:mos?|months?|month)\b", text, flags=re.IGNORECASE)
        months = int(months_match.group(1)) if months_match else 0
        if not months:
            continue
        for bank in banks or ["Credit Card"]:
            rows.append(
                {
                    "bank_name": bank,
                    "months_to_pay": months,
                    "percent_interest": 0.0 if "0%" in text else None,
                    "payment_type_id": payment.get("id"),
                    "source": "gulong_api_checkout_metadata",
                }
            )
    return rows


def installment_summary(installments: Sequence[Dict[str, Any]]) -> Tuple[Optional[str], Optional[float]]:
    parts: List[str] = []
    interest_rates: List[float] = []
    seen: set[Tuple[str, str, float]] = set()
    for inst in installments:
        if not isinstance(inst, dict):
            continue
        bank = str(inst.get("bank_name") or "").strip()
        months = inst.get("months_to_pay")
        interest = _coerce_float(inst.get("percent_interest")) or 0.0
        if not bank or not months:
            continue
        fact_key = (
            re.sub(r"[^A-Z0-9]+", "", bank.upper()),
            str(months).strip(),
            interest,
        )
        if fact_key in seen:
            continue
        seen.add(fact_key)
        interest_text = "0% interest" if interest == 0 else f"{interest:g}% interest"
        parts.append(f"{bank} {months}mo {interest_text}")
        interest_rates.append(interest)
    return (" | ".join(parts) if parts else None, min(interest_rates) if interest_rates else None)


def _normalize_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Iterable):
        return [str(item).strip() for item in value if str(item or "").strip()]
    return [str(value).strip()]


def _normalize_int_list(value: Any) -> List[int]:
    values = _normalize_string_list(value)
    out: List[int] = []
    for item in values:
        try:
            parsed = int(item)
        except Exception:
            continue
        if parsed not in out:
            out.append(parsed)
    return out


def _normalize_origin_key(value: Any) -> Optional[str]:
    text = _clean_optional(value)
    if text is None:
        return None
    key = re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()
    aliases = {
        "UNITED STATES": "USA",
        "UNITED STATES OF AMERICA": "USA",
        "U S": "USA",
        "US": "USA",
        "USA": "USA",
        "SOUTH KOREA": "SOUTH KOREA",
        "KOREA": "SOUTH KOREA",
        "NETHERLAND": "NETHERLANDS",
        "THE NETHERLANDS": "NETHERLANDS",
        "UK": "UK",
        "UNITED KINGDOM": "UK",
    }
    return aliases.get(key, key)


def _normalize_category_key(value: Any) -> Optional[str]:
    text = _clean_optional(value)
    if text is None:
        return None
    key = re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()
    aliases = {
        "MID": "MID RANGE",
        "MIDRANGE": "MID RANGE",
        "MID RANGE": "MID RANGE",
        "MID TIER": "MID RANGE",
        "MIDDLE": "MID RANGE",
        "ENTRY": "BUDGET",
        "ENTRY LEVEL": "BUDGET",
        "CHEAP": "BUDGET",
        "AFFORDABLE": "BUDGET",
        "VALUE": "ECONOMY",
        "ECON": "ECONOMY",
        "PREMIUM": "PREMIUM",
        "BUDGET": "BUDGET",
        "ECONOMY": "ECONOMY",
    }
    category = aliases.get(key)
    return category if category in PRICE_CATEGORY_ORDER else None


def infer_warranty_years(value: Any) -> Optional[int]:
    text = _clean_optional(value)
    if text is None:
        return None
    match = re.search(r"(\d+)\s*(?:YEAR|YEARS|YR|YRS)?", text.upper())
    if not match:
        return None
    try:
        parsed = int(match.group(1))
    except Exception:
        return None
    return parsed if parsed > 0 else None


def infer_terrain_types(
    raw: Dict[str, Any],
    *,
    brand: Optional[str] = None,
    model: Optional[str] = None,
    category: Optional[str] = None,
) -> List[str]:
    fields = [
        brand,
        model,
        category,
        raw.get("pattern"),
        raw.get("tread_pattern"),
        raw.get("description"),
        raw.get("features"),
        raw.get("product_type"),
        raw.get("tire_category"),
        raw.get("terrain"),
    ]
    return _terrain_types_from_text(" ".join(str(field or "") for field in fields))


def _terrain_types_from_text(value: str) -> List[str]:
    text = str(value or "").upper().replace("_", " ")
    padded = f" {text} "
    checks = [
        (
            "ALL_TERRAIN",
            [
                r"\bALL[\s-]?TERRAIN\b",
                r"\bA\s*/\s*T\b",
                r"\bA-T\b",
                r"\bA\s*T\s*(?:2|3|4|5)\b",
                r"\bAT(?:2|3|4|5)\b",
            ],
        ),
        (
            "MUD_TERRAIN",
            [
                r"\bMUD[\s-]?TERRAIN\b",
                r"\bM\s*/\s*T\b",
                r"\bM-T\b",
                r"\bM\s*T\s*(?:2|3|4|5|6|7|8|9)?\b",
                r"\bMT(?:2|3|4|5|6|7|8|9)\b",
            ],
        ),
        (
            "HIGHWAY_TERRAIN",
            [
                r"\bHIGHWAY[\s-]?TERRAIN\b",
                r"\bH\s*/\s*T\b",
                r"\bH-T\b",
                r"\bH\s*T\s*(?:2|3|4|5|6|7|8|9)?\b",
                r"\bHT(?:2|3|4|5|6|7|8|9)\b",
            ],
        ),
        (
            "RUGGED_TERRAIN",
            [
                r"\bRUGGED[\s-]?TERRAIN\b",
                r"\bROUGH[\s-]?TERRAIN\b",
                r"\bTRAIL[\s-]?TERRAIN\b",
                r"\bR\s*/\s*T\b",
                r"\bR-T\b",
                r"\bR\s*T\s*(?:2|3|4|5|6|7|8|9)?\b",
                r"\bRT(?:2|3|4|5|6|7|8|9)\b",
            ],
        ),
    ]
    out: List[str] = []
    for terrain_type, patterns in checks:
        if any(re.search(pattern, padded) for pattern in patterns):
            out.append(terrain_type)
    return out


def category_matches(requested_categories: Sequence[str], product_category: Any) -> bool:
    requested = set(normalize_tire_categories(requested_categories))
    actual = _normalize_category_key(product_category)
    return bool(actual and actual in requested)


def origin_matches(requested_origins: Sequence[str], product_origin: Any) -> bool:
    requested = set(normalize_origins(requested_origins))
    actual = set(normalize_origins(product_origin))
    return bool(requested.intersection(actual))


def _product_origin_for_filter(product: Dict[str, Any]) -> Any:
    origin = product.get("origin")
    if origin not in (None, "", [], {}):
        return origin
    brand = str(product.get("brand") or "").strip().upper()
    return KNOWN_BRAND_ORIGIN_HINTS.get(brand)


def _product_allowed_for_brand_bucket(request: ProductSearchRequest, product: Dict[str, Any]) -> bool:
    """Return whether product can contribute to a brand bucket card."""

    if product_matches_exclusions(request, product):
        return False
    if request.brands and str(product.get("brand") or "").upper() not in set(request.brands):
        return False
    if request.origins and not origin_matches(request.origins, _product_origin_for_filter(product)):
        return False
    if request.warranty_years and infer_warranty_years(product.get("warranty")) not in set(request.warranty_years):
        return False
    if request.tire_categories and not category_matches(request.tire_categories, product.get("category")):
        return False
    if request.promo_only is True and not product_matches_promo_request(request, product):
        return False
    if request.budget_max is not None:
        price_basis = budget_price_basis(request, product)
        if price_basis is None or price_basis > request.budget_max:
            return False
    if request.ev_compatible is not None and bool(product.get("ev_compatible")) is not bool(request.ev_compatible):
        return False
    if request.gulong_guarantee_only is True and gulong_guarantee_tier(product) == 0:
        return False
    if request.gulong_guarantee_tiers and gulong_guarantee_tier(product) not in set(request.gulong_guarantee_tiers):
        return False
    if request.availability == "in_stock" and product.get("pre_order"):
        return False
    if request.availability == "pre_order" and not product.get("pre_order"):
        return False
    if request.terrain_types and not set(normalize_terrain_types(product.get("terrain_types"))).intersection(request.terrain_types):
        return False
    if installment_filters_requested(request):
        installments = product.get("installments") or []
        if request.installment_only is True and not installments:
            return False
        if request.installment_banks and not installment_bank_matches(request.installment_banks, installments):
            return False
        if request.installment_months and not installment_months_match(request.installment_months, installments):
            return False
        if request.installment_max_interest is not None and not installment_interest_match(request.installment_max_interest, installments):
            return False
    return True


def _brand_bucket_meta(
    request: ProductSearchRequest,
    products: Sequence[Dict[str, Any]],
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    """Build compact brand metadata from grounded products."""

    by_brand: Dict[str, List[Dict[str, Any]]] = {}
    for product in products:
        brand = str(product.get("brand") or "").strip().upper()
        if brand:
            by_brand.setdefault(brand, []).append(product)

    rows: List[Dict[str, Any]] = []
    for brand, items in by_brand.items():
        prices = [_coerce_float(item.get("price")) for item in items if _coerce_float(item.get("price")) is not None]
        min_price = min(prices) if prices else None
        markers = _brand_bucket_marker_payload(items)
        rows.append(
            {
                "brand": brand,
                "product_count": len(items),
                "from_price": min_price,
                "from_price_text": _money_text(min_price),
                "promo": bool(markers["promo_marker_keys"]),
                "promo_marker_keys": markers["promo_marker_keys"],
                "markers": markers["markers"],
                "marker_keys": markers["marker_keys"],
                "tire_protection_plan": markers["tire_protection_plan"],
                "preferred": brand in set(request.preferred_brands),
            }
        )
    rows.sort(
        key=lambda item: (
            0 if item.get("preferred") else 1,
            0 if item.get("promo") else 1,
            0 if item.get("tire_protection_plan") else 1,
            -int(item.get("product_count") or 0),
            _coerce_float(item.get("from_price")) or 9999999,
            str(item.get("brand") or ""),
        )
    )
    return rows[: max(1, int(limit or 5))]


def _brand_bucket_summary(buckets: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Return compact summary for model/tool metadata."""

    return {
        key: {
            "label": bucket.get("label"),
            "brand_count": len(bucket.get("brands") or []),
            "brands": bucket.get("brands") or [],
            "promo_brands": bucket.get("promo_brands") or [],
            "tire_protection_plan_brands": bucket.get("tire_protection_plan_brands") or [],
            "marker_legend_keys": bucket.get("marker_legend_keys") or [],
        }
        for key, bucket in buckets.items()
    }


def _category_slug(category_key: str) -> str:
    return str(category_key or "").strip().lower().replace(" ", "_")


def _brand_bucket_emoji(category_key: str) -> str:
    return {
        "BUDGET": "💸",
        "ECONOMY": "⚖️",
        "MID RANGE": "🛞",
        "PREMIUM": "⭐",
    }.get(category_key, "•")


def _brand_bucket_sales_pitch(category_key: str) -> str:
    return {
        "BUDGET": "Value-focused brands for keeping costs low while still covering daily driving needs.",
        "ECONOMY": "Practical step-up brands for everyday comfort and dependable value.",
        "MID RANGE": "Balanced brands for durability, comfort, and stronger promo availability.",
        "PREMIUM": "Higher-end brands for comfort, performance, and longer ownership confidence.",
    }.get(category_key, "Available brand options.")


def _brand_bucket_marker_payload(products: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Build display markers for promo and Tire Protection Plan signals."""

    marker_keys: List[str] = []
    promo_marker_keys: List[str] = []
    markers: List[str] = []
    if any(has_buy3get1(product) for product in products):
        marker_keys.append("buy3get1")
        promo_marker_keys.append("buy3get1")
        markers.append("3+1")
    discount_amount = max((_coerce_float(product.get("product_discount_amount")) or 0.0) for product in products) if products else 0.0
    if discount_amount > 0:
        marker_keys.append("product_discount")
        promo_marker_keys.append("product_discount")
        markers.append(f"{_money_text(discount_amount)} off/tire")
    tpp_tier = max([gulong_guarantee_tier(product) for product in products] or [0])
    tpp_marker = _tpp_marker_from_tier(tpp_tier)
    if tpp_marker:
        marker_keys.append("tpp")
        markers.append(tpp_marker)
    return {
        "markers": markers,
        "marker_keys": _ordered_unique(marker_keys),
        "promo_marker_keys": _ordered_unique(promo_marker_keys),
        "tire_protection_plan": _tpp_text_from_tier(tpp_tier),
    }


def tire_protection_plan_text(product: Dict[str, Any]) -> Optional[str]:
    """Return Tire Protection Plan wording for a normalized product."""

    return _tpp_text_from_tier(gulong_guarantee_tier(product))


def _tpp_marker_from_tier(tier: int) -> Optional[str]:
    if tier == 1:
        return "TPP 1Y"
    if tier == 2:
        return "TPP 6 MOS"
    return None


def _tpp_text_from_tier(tier: int) -> Optional[str]:
    if tier == 1:
        return "Tire Protection Plan (1 Year)"
    if tier == 2:
        return "Tire Protection Plan (6 Months)"
    return None


def product_matches_exclusions(request: ProductSearchRequest, product: Dict[str, Any]) -> bool:
    """Return true when a product violates model-extracted exclusion filters."""

    brand = str(product.get("brand") or "").upper()
    if request.excluded_brands and brand in set(request.excluded_brands):
        return True
    if request.excluded_tire_categories and category_matches(request.excluded_tire_categories, product.get("category")):
        return True
    if request.excluded_origins and origin_matches(request.excluded_origins, _product_origin_for_filter(product)):
        return True
    return False


def has_catalog_refiner_request(request: ProductSearchRequest) -> bool:
    return bool(
        request.origins
        or request.excluded_origins
        or request.warranty_years
        or request.tire_categories
        or request.excluded_tire_categories
        or request.terrain_types
        or request.availability in {"in_stock", "pre_order"}
    )


def installment_filters_requested(request: ProductSearchRequest) -> bool:
    return bool(
        request.installment_only is True
        or request.installment_banks
        or request.installment_months
        or request.installment_max_interest is not None
    )


def requires_promo_truth(request: ProductSearchRequest) -> bool:
    """Return whether promo-brand lookup can affect filtering or ranking."""

    return bool(request.promo_only is True or request.budget_max is not None)


def installment_bank_matches(requested_banks: Sequence[str], installments: Sequence[Dict[str, Any]]) -> bool:
    requested = set(normalize_installment_banks(requested_banks))
    actual = {
        bank
        for inst in installments
        for bank in normalize_installment_banks(inst.get("bank_name"))
    }
    return bool(requested.intersection(actual))


def installment_months_match(requested_months: Sequence[int], installments: Sequence[Dict[str, Any]]) -> bool:
    requested = set(normalize_warranty_years(requested_months))
    actual = set()
    for inst in installments:
        try:
            actual.add(int(inst.get("months_to_pay") or 0))
        except Exception:
            continue
    return bool(requested.intersection(actual))


def installment_interest_match(max_interest: float, installments: Sequence[Dict[str, Any]]) -> bool:
    for inst in installments:
        interest = _coerce_float(inst.get("percent_interest"))
        if interest is not None and interest <= max_interest:
            return True
    return False


def normalize_section_width(value: Optional[Any]) -> Optional[str]:
    """Normalize endpoint section-width values without assuming passenger sizes."""

    text = _clean_optional(value)
    if text is None:
        return None
    text = text.upper().replace(" ", "")
    if re.fullmatch(r"\d{3}\.0", text):
        return text[:-2]
    if re.fullmatch(r"\d+\.\d", text):
        return f"{float(text):.2f}"
    return text


def normalize_metric_section_width_with_corrections(
    section_width: Optional[Any],
    *,
    aspect_ratio: Optional[Any],
    rim_size: Optional[Any],
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Correct likely one-digit passenger metric section-width typos."""

    section = normalize_section_width(section_width)
    aspect = _normalize_numeric_text(aspect_ratio)
    rim = normalize_rim_size(rim_size, section_width=section)
    if not section or not aspect or not rim:
        return section, []
    if not re.fullmatch(r"\d{3}", str(section)):
        return section, []
    try:
        value = int(str(section))
    except Exception:
        return section, []
    if not (100 <= value <= 405) or value % 5 == 0:
        return section, []
    lower = (value // 5) * 5
    upper = lower + 5
    nearest = upper if (upper - value) <= (value - lower) else lower
    distance = abs(nearest - value)
    if distance > 1:
        return section, [
            {
                "input": f"{section}/{aspect}{rim}",
                "input_section_width": section,
                "status": "nonstandard_metric_section_width_flagged",
                "reason": "metric passenger tire section widths usually use 5 mm increments",
            }
        ]
    canonical_section = str(nearest)
    return canonical_section, [
        {
            "input": f"{section}/{aspect}{rim}",
            "canonical": f"{canonical_section}/{aspect}{rim}",
            "input_section_width": section,
            "canonical_section_width": canonical_section,
            "status": "section_width_rounded_to_nearest_5mm",
            "reason": "one-off customer typo against common metric tire section-width increments",
        }
    ]


def _section_uses_bare_numeric_rim(section_width: Optional[Any], rim: str) -> bool:
    section = normalize_section_width(section_width)
    if section is None:
        return False
    if re.fullmatch(r"\d+\.\d{2}", section):
        return True
    return section == "10" and rim == "10"


def _normalize_numeric_text(value: Optional[Any]) -> Optional[str]:
    text = _clean_optional(value)
    if text is None:
        return None
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        return None
    return text


def _clean_optional(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a"}:
        return None
    return text


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"(\d[\d,]*\.?\d*)", str(value))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _coerce_optional_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    match = re.search(r"\d+", str(value))
    if not match:
        return None
    try:
        return int(match.group(0))
    except Exception:
        return None


def _coerce_optional_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (1, "1"):
        return True
    text = str(value or "").strip().lower()
    return text in {"true", "yes", "y"}


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _env_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(minimum, min(maximum, parsed))


def _price_from_product(raw: Dict[str, Any]) -> Optional[float]:
    if raw.get("sale_tag") or _active_product_discount_amount(raw):
        price = _coerce_float(raw.get("promo"))
        if price:
            return price
    for key in ["srp", "price", "mp_price", "product_price"]:
        price = _coerce_float(raw.get(key))
        if price:
            return price
    return None


def _promo_fields(raw: Dict[str, Any], price: Optional[float]) -> Tuple[Optional[str], Optional[str]]:
    if raw.get("clearance_sale"):
        return "Clearance Sale", None
    promo_text = _clean_optional(raw.get("promo"))
    return None, promo_text


def _product_discount_fields(raw: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[float]]:
    discount = raw.get("product_discount")
    if not isinstance(discount, dict):
        return None, None, None
    amount = _active_product_discount_amount(raw)
    if not amount:
        return None, None, None
    name = _clean_optional(discount.get("name")) or "Product Discount"
    text = f"{name}: PHP {amount:,.2f} off/tire"
    return name, text, amount


def _active_product_discount_amount(raw: Dict[str, Any]) -> Optional[float]:
    discount = raw.get("product_discount")
    if not isinstance(discount, dict):
        return None
    amount = _coerce_float(discount.get("total_discount") or discount.get("amount"))
    if not amount:
        return None
    status = discount.get("status_id")
    if str(status).strip().lower() in {"0", "false", "inactive", "disabled"}:
        return None
    return amount


def _sale_price_discount_amount(raw: Dict[str, Any]) -> Optional[float]:
    if not raw.get("sale_tag"):
        return None
    list_price = _coerce_float(raw.get("srp"))
    sale_price = _coerce_float(raw.get("promo"))
    if list_price is None or sale_price is None or list_price <= sale_price:
        return None
    return round(list_price - sale_price, 2)


def _dot_value(raw: Dict[str, Any]) -> Optional[str]:
    for key in ["DOT_SKU", "dot_sku", "DOT", "dot", "dot_year", "date_of_tire"]:
        value = _clean_optional(raw.get(key))
        if value:
            return value
    return None


def _manufacturer_warranty_text(raw: Dict[str, Any], brand: str) -> Optional[str]:
    """Return manufacturer warranty wording from explicit fields or badge data."""

    for key in ["warranty", "manufacturer_warranty", "warranty_text"]:
        value = _clean_optional(raw.get(key))
        if value:
            # Some catalog rows store a year count in a free-text warranty
            # field (for example, ``"5"``). Normalize only a wholly numeric
            # value so authored terms such as ``"5 years from purchase date"``
            # remain unchanged.
            if re.fullmatch(r"\d+(?:\.\d+)?", value):
                years = _coerce_float(value)
                if years and years > 0:
                    return _warranty_years_text(years)
                continue
            return value
    for key in ["warranty_year", "warranty_years"]:
        years = _coerce_float(raw.get(key))
        if years and years > 0:
            return _warranty_years_text(years)
    for key in ["default_product_banner", "product_banner", "banner_url", "warranty_badge"]:
        years = _warranty_years_from_badge(raw.get(key))
        if years:
            return _warranty_years_text(years)
    return KNOWN_BRAND_WARRANTY_HINTS.get(str(brand or "").strip().upper())


def _warranty_years_from_badge(value: Any) -> Optional[float]:
    text = unquote(str(value or ""))
    if not text or "warranty" not in text.lower():
        return None
    match = re.search(r"\b([1-9][0-9]?)\s*(?:years?|yrs?)\b", text, flags=re.IGNORECASE)
    if match:
        return _coerce_float(match.group(1))
    match = re.search(r"(?:\]|/|\s)([1-9][0-9]?)(?:\.\w+$|\s|$)", text)
    return _coerce_float(match.group(1)) if match else None


def _warranty_years_text(years: float) -> str:
    amount = int(years) if float(years).is_integer() else years
    unit = "year" if amount == 1 else "years"
    return f"{amount} {unit}"


def _voucher_text(raw: Dict[str, Any]) -> Optional[str]:
    for key in ["voucher_text", "voucher", "coupon_text", "coupon", "discount_text"]:
        value = _clean_optional(raw.get(key))
        if value:
            return value
    amount = _voucher_amount(raw)
    if amount:
        return f"Voucher: PHP {amount:,.2f} off"
    return None


def _voucher_amount(raw: Dict[str, Any]) -> Optional[float]:
    for key in ["voucher_amount", "coupon_amount", "discount_amount", "voucher_discount", "discount"]:
        amount = _coerce_float(raw.get(key))
        if amount:
            return amount
    return None


def _money_text(value: Optional[float], *, suffix: str = "") -> Optional[str]:
    amount = _coerce_float(value)
    if amount is None:
        return None
    tail = suffix if suffix.startswith("/") else f" {suffix}" if suffix else ""
    return f"PHP {amount:,.2f}{tail}"


def _normalize_size_text(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def build_bundle_pricing(raw: Dict[str, Any], price: Optional[float], *, enabled: bool = True) -> Dict[str, Any]:
    """Return normalized bundle tiers used for budget checks."""

    if not enabled:
        return {
            "enabled": False,
            "base_unit_price": price,
            "tiers": [],
            "source": "disabled_by_config",
        }
    raw_bundle = raw.get("bundle_pricing")
    if isinstance(raw_bundle, dict) and isinstance(raw_bundle.get("tiers"), list):
        return {**raw_bundle, "source": raw_bundle.get("source") or "api"}
    if price is None or price <= 0:
        return {"enabled": False, "base_unit_price": price, "tiers": [], "source": "no_price"}
    product_discount_amount = _active_product_discount_amount(raw)
    brand = str(raw.get("make") or raw.get("brand") or "").strip().upper()
    quantity_promo = _active_quantity_promo(raw)
    if not quantity_promo and brand == "YOKOHAMA" and product_discount_amount:
        fallback_amount = _yokohama_selected_set_discount_amount(raw)
        if fallback_amount:
            quantity_promo = {
                "discount_amount": fallback_amount,
                "required_quantity": 4,
                "source": "reviewed_yokohama_set_promo_fallback",
            }
    list_price = _coerce_float(raw.get("srp"))
    base_price = list_price if product_discount_amount and list_price else price
    tiers = []
    for quantity, discount_rate in {1: 0.0, 2: 0.01, 3: 0.02, 4: 0.03}.items():
        pre_discount_unit_price = round(base_price * (1 - discount_rate), 2)
        unit_price = pre_discount_unit_price
        if product_discount_amount:
            unit_price = max(0.0, round(pre_discount_unit_price - product_discount_amount, 2))
        total_before_quantity_promo = round(unit_price * quantity, 2)
        quantity_promo_amount = 0.0
        if quantity_promo and quantity >= int(quantity_promo["required_quantity"]):
            quantity_promo_amount = min(
                total_before_quantity_promo,
                float(quantity_promo["discount_amount"]),
            )
        total_price = max(0.0, round(total_before_quantity_promo - quantity_promo_amount, 2))
        tier = {
            "quantity": quantity,
            "discount_rate": discount_rate,
            "unit_price": round(total_price / quantity, 2),
            "total_price": total_price,
            "unit_price_text": f"PHP {round(total_price / quantity, 2):,.2f}",
            "total_price_text": f"PHP {total_price:,.2f}",
        }
        if product_discount_amount:
            pre_discount_total_price = round(pre_discount_unit_price * quantity, 2)
            tier.update(
                {
                    "pre_discount_unit_price": pre_discount_unit_price,
                    "pre_discount_total_price": pre_discount_total_price,
                    "pre_discount_unit_price_text": f"PHP {pre_discount_unit_price:,.2f}",
                    "pre_discount_total_price_text": f"PHP {pre_discount_total_price:,.2f}",
                    "product_discount_amount": product_discount_amount,
                }
            )
        if quantity_promo_amount:
            tier.update(
                {
                    "unit_price_before_quantity_promo": unit_price,
                    "total_before_quantity_promo": total_before_quantity_promo,
                    "quantity_promo_discount_amount": quantity_promo_amount,
                    # Retained for existing customer-facing bundle savings rendering.
                    "set_discount_amount": quantity_promo_amount,
                }
            )
        tiers.append(tier)
    if quantity_promo:
        source = str(quantity_promo["source"])
    else:
        source = "local_policy_product_discount_after_bundle" if product_discount_amount else "local_policy"
    payload = {"enabled": True, "base_unit_price": base_price, "tiers": tiers, "source": source}
    if product_discount_amount:
        payload["product_discount_amount"] = product_discount_amount
    if quantity_promo:
        payload.update(
            {
                "quantity_promo_discount_amount": quantity_promo["discount_amount"],
                "quantity_promo_required_quantity": quantity_promo["required_quantity"],
                "set_discount_amount": quantity_promo["discount_amount"],
                "set_discount_text": (
                    f"PHP {quantity_promo['discount_amount']:,.2f} off "
                    f"for {quantity_promo['required_quantity']} tires"
                ),
            }
        )
        if quantity_promo.get("product_promo_ref") is not None:
            payload["product_promo_ref"] = quantity_promo["product_promo_ref"]
    return payload


def _active_quantity_promo(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return an active API quantity-promo contract with its evidence ref."""

    promo = raw.get("product_promo")
    if not isinstance(promo, dict):
        return None
    status = str(promo.get("status_id") if promo.get("status_id") is not None else "1").strip().lower()
    if status in {"0", "false", "inactive", "disabled"}:
        return None
    discount_amount = _coerce_float(promo.get("discount_amount"))
    required_quantity = _coerce_float(promo.get("required_quantity"))
    if not discount_amount or not required_quantity:
        return None
    required_quantity_int = int(required_quantity)
    if required_quantity_int <= 0 or required_quantity_int != required_quantity:
        return None
    return {
        "discount_amount": round(discount_amount, 2),
        "required_quantity": required_quantity_int,
        "product_promo_ref": promo.get("id"),
        "source": "api_product_promo",
    }


def _yokohama_selected_set_discount_amount(raw: Dict[str, Any]) -> float:
    banner_amount = _yokohama_banner_set_discount_amount(raw)
    if banner_amount:
        return banner_amount

    size = format_size(
        normalize_section_width(raw.get("section_width")),
        _normalize_numeric_text(raw.get("aspect_ratio")),
        normalize_rim_size(raw.get("rim_size")),
    )
    model_norm = _normalize_match_text(raw.get("model") or raw.get("display_name") or raw.get("pattern") or "")
    for size_key, pattern_key in YOKOHAMA_SET_PROMO_6000_SKUS:
        if _normalize_size_text(size) == _normalize_size_text(size_key) and pattern_key in model_norm:
            return 2000.0
    for size_key, pattern_key in YOKOHAMA_SET_PROMO_5200_SKUS:
        if _normalize_size_text(size) == _normalize_size_text(size_key) and pattern_key in model_norm:
            return 1200.0
    return 0.0


def _yokohama_banner_set_discount_amount(raw: Dict[str, Any]) -> float:
    banner = raw.get("banner")
    if not isinstance(banner, dict):
        return 0.0
    text = " ".join(
        str(value or "")
        for value in [
            banner.get("label"),
            banner.get("sub_label"),
            banner.get("description"),
        ]
    )
    text = text.replace("₱", "PHP")
    if not text.strip():
        return 0.0
    match = re.search(
        r"additional\s*(?:php|p)?\s*([\d,]+(?:\.\d+)?)\s*discount\s*for\s*4[-\s]?tires",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return 0.0
    amount = _coerce_float(match.group(1))
    return float(amount or 0.0)


def _is_active_product(product: Dict[str, Any]) -> bool:
    activity = product.get("activity")
    if activity is not None and activity not in (1, "1", True):
        return False
    status_id = product.get("status_id")
    if status_id not in (0, "0"):
        return False
    return True


def _model_text(product: Dict[str, Any]) -> str:
    return " ".join(
        str(product.get(key) or "")
        for key in [
            "brand",
            "model",
            "pattern",
            "size",
            "slug",
            "description",
            "features",
        ]
    )


def attach_search_fields(product: Dict[str, Any]) -> None:
    if product.get("_search_norm") and product.get("_search_tokens"):
        return
    text = _model_text(product)
    norm = _normalize_match_text(text)
    product["_search_norm"] = norm
    product["_search_tokens"] = tuple(norm.split())


def _normalize_match_text(value: Optional[str]) -> str:
    text = str(value or "").upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _size_from_model(model: str) -> Optional[str]:
    match = re.search(r"(\d{3})[/ ](\d{2})[/ ](Z?R\d{2}[A-Z]?)", model.upper())
    if match:
        return f"{match.group(1)}/{match.group(2)}{match.group(3)}"
    match = re.search(r"(\d{3})[/ ](R\d{2}C?)", model.upper())
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    return None


def _rim_number(value: str) -> Optional[str]:
    match = re.search(r"(\d{2})", str(value or ""))
    return match.group(1) if match else None


def _safe_error(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        return str(payload.get("content") or payload.get("error") or payload.get("status") or payload)[:300]
    return None


def _count(target: Dict[str, int], value: Any) -> None:
    text = str(value or "").strip()
    if text:
        target[text] = target.get(text, 0) + 1


def _top_counts(values: Dict[str, int], *, limit: int = 12) -> List[Dict[str, Any]]:
    return [
        {"value": value, "count": count}
        for value, count in sorted(values.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _pool_summary(ranked: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    summary: Dict[str, int] = {
        "total": len(ranked),
        "exact": 0,
        "near_exact": 0,
        "partial": 0,
        "alternate": 0,
        "same_rim_requested_brand": 0,
        "same_rim": 0,
        "requested_brand_other_size": 0,
        "model_pattern_match": 0,
    }
    for product in ranked:
        tier = str((product.get("match") or {}).get("tier") or "alternate")
        if tier in summary:
            summary[tier] += 1
        if tier in {"same_rim_requested_brand", "same_rim", "requested_brand_other_size", "model_pattern_match"}:
            summary["partial"] += 1
    return summary


def _build_match_tiers(ranked: Sequence[Dict[str, Any]], *, limit_per_tier: int = 12) -> Dict[str, List[str]]:
    tiers: Dict[str, List[str]] = {
        "exact_requested_filters": [],
        "core_match_secondary_miss": [],
        "same_rim_requested_brand": [],
        "same_rim_other_brand": [],
        "requested_brand_other_size": [],
        "model_pattern_matches": [],
        "alternates": [],
    }
    for product in ranked:
        ref = str(product.get("item_ref") or "")
        if not ref:
            continue
        tier = str((product.get("match") or {}).get("tier") or "")
        if tier == "exact":
            key = "exact_requested_filters"
        elif tier == "near_exact":
            key = "core_match_secondary_miss"
        elif tier == "same_rim_requested_brand":
            key = "same_rim_requested_brand"
        elif tier == "same_rim":
            key = "same_rim_other_brand"
        elif tier == "requested_brand_other_size":
            key = "requested_brand_other_size"
        elif tier == "model_pattern_match":
            key = "model_pattern_matches"
        else:
            key = "alternates"
        if len(tiers[key]) < limit_per_tier:
            tiers[key].append(ref)
    return tiers


def _status_from_pool(summary: Dict[str, int]) -> Tuple[str, str]:
    if summary.get("exact", 0) > 0:
        return "ok", "exact"
    if summary.get("near_exact", 0) > 0:
        return "partial_match", "near_exact"
    if summary.get("partial", 0) > 0:
        return "partial_match", "partial"
    if summary.get("alternate", 0) > 0:
        return "partial_match", "alternate"
    return "no_match", "none"


def _response_strategy(status: str, result_level: str, summary: Dict[str, int]) -> str:
    if status == "ok":
        return "present_best_matches"
    if status == "exact_unavailable":
        return "state_exact_size_miss_and_request_consent_before_nearby_sizes"
    if result_level == "near_exact":
        return "present_near_matches_with_secondary_miss"
    if result_level == "partial":
        return "present_partial_matches_and_ask_clarifying_question"
    if result_level == "alternate":
        return "explain_no_exact_match_and_offer_alternatives"
    return "ask_for_more_search_details"


def _product_search_recovery_options(
    request: ProductSearchRequest,
    status: str,
    result_level: str,
    summary: Dict[str, int],
) -> List[Dict[str, Any]]:
    """Return model-visible recovery choices for weak or empty exact searches."""

    options: List[Dict[str, Any]] = []
    has_size_context = bool(request.section_width or request.aspect_ratio or request.rim_size)
    if status == "exact_unavailable":
        if request.brands or request.preferred_brands or request.model_or_pattern:
            return [
                {
                    "tool": "discover_brand_buckets",
                    "reason": (
                        "The requested brand or model had no exact full-size "
                        "match. Keep the exact size and broaden only the brand "
                        "or price-category dimension."
                    ),
                    "customer_next_step": (
                        "Explain that the requested brand/model was not found "
                        "for the exact size and offer current same-size brand "
                        "or price-category choices."
                    ),
                }
            ]
        return [
            {
                "tool": "product_search",
                "reason": (
                    "The exact full-size base query returned no active product. "
                    "Broader-size candidates are not customer-selectable without consent."
                ),
                "customer_next_step": (
                    "Say the exact size was not found, suggest checking the "
                    "sidewall or fitment, and ask whether the customer wants "
                    "nearby-size options explored."
                ),
            }
        ]
    if status == "unavailable" and has_size_context:
        return [
            {
                "tool": "product_search",
                "reason": (
                    "The exact-size base query could not be verified. Do not "
                    "claim the requested product or size is unavailable."
                ),
                "customer_next_step": (
                    "Explain that current availability could not be verified "
                    "and offer to retry the exact search."
                ),
            }
        ]
    brand_filtered = bool(request.brands or request.preferred_brands or request.model_or_pattern)
    exact_brand_or_model_miss = brand_filtered and summary.get("exact", 0) == 0 and summary.get("near_exact", 0) == 0
    if has_size_context and exact_brand_or_model_miss:
        options.append(
            {
                "tool": "discover_brand_buckets",
                "reason": "Exact brand/model search did not return exact products, but size context is available.",
                "customer_next_step": "Offer broader same-size brand/category choices or same-size alternatives.",
            }
        )
    elif status == "partial_match" and result_level in {"partial", "alternate"} and has_size_context:
        options.append(
            {
                "tool": "product_search",
                "reason": "Only partial or alternate matches were found.",
                "customer_next_step": "Explain which requested detail did not exactly match, then offer grounded same-size alternatives.",
            }
        )
    return options


def _exact_size_base_query_verified(
    request: ProductSearchRequest,
    attempts: Sequence[Dict[str, Any]],
) -> bool:
    """Return whether an exact full-size `/shop` query completed successfully."""

    if not (
        request.section_width
        and request.aspect_ratio
        and request.rim_size
    ):
        return False
    for attempt in attempts or []:
        if not isinstance(attempt, dict):
            continue
        if str(attempt.get("status") or "") != "ok":
            continue
        params = (
            attempt.get("params")
            if isinstance(attempt.get("params"), dict)
            else {}
        )
        if (
            str(params.get("section_width") or "")
            == str(request.section_width)
            and str(params.get("aspect_ratio") or "")
            == str(request.aspect_ratio)
            and rim_matches(request.rim_size, params.get("rim_size"))
        ):
            return True
    return False


def _observation_ref(
    request: ProductSearchRequest,
    attempts: Sequence[Dict[str, Any]],
    best_products: Sequence[Dict[str, Any]],
) -> str:
    digest = hashlib.sha1(
        json.dumps(
            {
                "request": request.to_public_dict(),
                "attempts": [
                    {
                        "label": attempt.get("label"),
                        "params": attempt.get("params"),
                        "product_count": attempt.get("product_count"),
                    }
                    for attempt in attempts
                ],
                "best": [product.get("slug") or product.get("product_id") for product in best_products],
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"obs_product_search_{digest}"
