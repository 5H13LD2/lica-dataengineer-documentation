"""Published promo catalog retrieval and constrained gallery presentation.

The runtime reads only the active, review-approved catalog. Card definitions are
treated as immutable publication artifacts: the model can select promo refs but
cannot construct or modify titles, media URLs, buttons, or mechanics.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Sequence
from zoneinfo import ZoneInfo

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from google.cloud.firestore_v1.vector import Vector

from runtime_v7.brand_knowledge import BrandKnowledgeService
from scripts.promo_vector_trial import VertexEmbedder
from runtime_v7.llm_gateway import RuntimeV7ProviderCallGuard


ACTIVE_CONFIG_COLLECTION = "promo_catalog_config"
ACTIVE_CONFIG_DOCUMENT = "active"
CARDS_COLLECTION = "promo_catalog_cards"
MECHANICS_COLLECTION = "promo_catalog_mechanics"
BRAND_PROFILES_COLLECTION = "promo_brand_profiles"
PROMO_INFORMATION_ACTIONS = frozenset({"promo_details", "about_brand"})
PROMO_SELECTION_ACTIONS = frozenset({"check_price", "choose_brand"})
SUPPORTED_ACTIONS = set(PROMO_INFORMATION_ACTIONS | PROMO_SELECTION_ACTIONS)


def product_card_matches_promo_types(
    card: Dict[str, Any],
    *,
    requested_promo_types: set[str],
) -> bool:
    """Match structured product pricing to canonical requested promo types.

    This shared predicate reconciles live product pricing with reviewed promo
    retrieval without any brand-specific allowlist.
    """

    pricing = (
        card.get("pricing_facts")
        if isinstance(card.get("pricing_facts"), dict)
        else {}
    )
    pricing_basis = str(pricing.get("pricing_basis") or "").casefold()
    promo_text = " ".join(
        [
            pricing_basis,
            *[
                str(value or "").casefold()
                for value in pricing.get("included_promos") or []
                if str(value or "").strip()
            ],
            str(card.get("promo_savings_line") or "").casefold(),
        ]
    )
    if not requested_promo_types:
        return bool(promo_text.strip())
    compact_text = re.sub(r"[^a-z0-9]+", "", promo_text)
    for value in requested_promo_types:
        normalized = re.sub(r"[^a-z0-9]+", "", value.casefold())
        if normalized in {"buy3get1", "3plus1", "3get1"}:
            if pricing_basis == "buy3get1":
                return True
            if re.search(r"(?:buy\s*3\s*get\s*1|3\s*\+\s*1)", promo_text):
                return True
            continue
        if normalized and normalized in compact_text:
            return True
    return False
PROMO_CLICK_TOKEN_PREFIX = "pc1"
PROMO_CLICK_TOKEN_MAX_LENGTH = 255
KNOWN_TIRE_BRANDS = {
    "apollo",
    "bridgestone",
    "continental",
    "dunlop",
    "goodyear",
    "michelin",
    "nankang",
    "sailun",
    "toyo",
    "westlake",
    "yokohama",
}
PROMO_QUERY_MARKERS = (
    "promo",
    "promos",
    "promotion",
    "discount",
    "sale",
    "3+1",
    "buy 3 get 1",
    "get 1 free",
    "free tire",
    "trip to japan",
    "passion experience",
    "warranty",
)
def promo_catalog_enabled_for_user(
    user_id: str,
    *,
    enabled_value: Optional[str] = None,
    allowlist_value: Optional[str] = None,
) -> bool:
    """Return whether promo tools and click actions are enabled for a user."""

    raw_enabled = (
        os.getenv("RUNTIME_V7_PROMO_CATALOG_ENABLED", "0")
        if enabled_value is None
        else enabled_value
    )
    if str(raw_enabled).strip().lower() not in {"1", "true", "yes", "on"}:
        return False

    raw_allowlist = (
        os.getenv("RUNTIME_V7_PROMO_CATALOG_USER_ALLOWLIST", "")
        if allowlist_value is None
        else allowlist_value
    )
    allowed_users = {
        value.strip()
        for value in re.split(r"[,;\s]+", str(raw_allowlist or ""))
        if value.strip()
    }
    return not allowed_users or str(user_id or "").strip() in allowed_users


class PromoEmbeddingGateway(Protocol):
    """Minimal embedding interface used by targeted catalog search."""

    def embed(self, text: str, *, task_type: str) -> List[float]:
        ...


@dataclass(frozen=True)
class PromoSearchContext:
    """Current-turn allowlist created by a catalog search."""

    catalog_version_id: str
    promo_refs: tuple[str, ...]
    query: str
    mode: str
    tire_size: str = ""


def build_promo_click_token(
    *,
    catalog_version_id: str,
    promo_id: str,
    card_id: str,
    action: str,
    selected_brand: str = "",
) -> str:
    """Encode one catalog-bound click in a single ManyChat text field."""

    values = [
        str(catalog_version_id or "").strip(),
        str(promo_id or "").strip(),
        str(card_id or "").strip(),
        str(action or "").strip().lower(),
        str(selected_brand or "").strip(),
    ]
    if not all(values[:4]):
        raise ValueError("Promo click token requires version, promo, card, and action values")
    if values[3] not in SUPPORTED_ACTIONS:
        raise ValueError(f"Unsupported promo click action: {values[3]}")
    if any("|" in value for value in values):
        raise ValueError("Promo click token values must not contain '|'")
    token = "|".join([PROMO_CLICK_TOKEN_PREFIX, *values])
    if len(token) > PROMO_CLICK_TOKEN_MAX_LENGTH:
        raise ValueError(f"Promo click token exceeds {PROMO_CLICK_TOKEN_MAX_LENGTH} characters")
    return token


def parse_promo_click_token(value: Any) -> Dict[str, str]:
    """Decode a promo click token, or return empty for a normal promo ID."""

    token = str(value or "").strip()
    if not token.startswith(f"{PROMO_CLICK_TOKEN_PREFIX}|"):
        return {}
    parts = token.split("|")
    if len(parts) != 6:
        raise ValueError("Malformed promo click token")
    _, catalog_version_id, promo_id, card_id, action, selected_brand = parts
    if not catalog_version_id or not promo_id or not card_id or not action:
        raise ValueError("Promo click token is missing required values")
    action = action.strip().lower()
    if action not in SUPPORTED_ACTIONS:
        raise ValueError("Promo click token contains an unsupported action")
    return {
        "catalog_version_id": catalog_version_id,
        "promo_id": promo_id,
        "card_id": card_id,
        "action": action,
        "selected_brand": selected_brand,
    }


class PromoCatalogRepository:
    """Read the active published catalog from Firestore."""

    def __init__(
        self,
        *,
        project_id: Optional[str] = None,
        firestore_client: Any = None,
        embedder: Optional[PromoEmbeddingGateway] = None,
        cards_collection: str = CARDS_COLLECTION,
        mechanics_collection: str = MECHANICS_COLLECTION,
        brand_profiles_collection: str = BRAND_PROFILES_COLLECTION,
        config_collection: str = ACTIVE_CONFIG_COLLECTION,
        embedding_service_account: Optional[str] = None,
        provider_call_guard: Optional[RuntimeV7ProviderCallGuard] = None,
    ) -> None:
        self._project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "gulong-chatbot-459723")
        self._firestore = firestore_client or firestore.Client(project=self._project_id)
        self._embedder = embedder
        self._embedding_service_account = (
            str(embedding_service_account).strip()
            if embedding_service_account is not None
            else os.getenv("PROMO_CATALOG_EMBEDDING_SERVICE_ACCOUNT", "").strip()
        )
        self._cards_collection = cards_collection
        self._mechanics_collection = mechanics_collection
        self._brand_profiles_collection = brand_profiles_collection
        self._config_collection = config_collection
        self._provider_call_guard = provider_call_guard

    def active_config(self) -> Dict[str, Any]:
        """Return the active pointer or an empty mapping when none is published."""

        snapshot = self._firestore.collection(self._config_collection).document(ACTIVE_CONFIG_DOCUMENT).get()
        if not getattr(snapshot, "exists", False):
            return {}
        payload = dict(snapshot.to_dict() or {})
        version_id = str(payload.get("catalog_version_id") or payload.get("active_catalog_version_id") or "").strip()
        if version_id:
            payload["catalog_version_id"] = version_id
        return payload

    def list_cards(self, catalog_version_id: str) -> List[Dict[str, Any]]:
        """Return reviewed promo records in their publication order."""

        query = self._firestore.collection(self._cards_collection).where(
            filter=FieldFilter("catalog_version_id", "==", catalog_version_id)
        )
        cards = [_snapshot_payload(snapshot) for snapshot in query.stream()]
        cards = [card for card in cards if _published_record(card)]
        return sorted(cards, key=lambda card: (int(card.get("display_order") or 9999), str(card.get("promo_id") or "")))

    def vector_candidates(
        self,
        *,
        catalog_version_id: str,
        query_text: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Search parent promo records, filtering only by catalog version."""

        embedder = self._embedder or VertexEmbedder(
            self._project_id,
            dimensions=768,
            service_account_email=self._embedding_service_account,
        )
        self._reserve_provider_call()
        vector = embedder.embed(query_text, task_type="RETRIEVAL_QUERY")
        query = self._firestore.collection(self._cards_collection).where(
            filter=FieldFilter("catalog_version_id", "==", catalog_version_id)
        ).find_nearest(
            vector_field="embedding",
            query_vector=Vector(vector),
            distance_measure=DistanceMeasure.COSINE,
            limit=max(1, int(limit)),
            distance_result_field="vector_distance",
        )
        return [
            payload
            for payload in (_snapshot_payload(snapshot) for snapshot in query.stream())
            if _published_record(payload)
        ]

    def _reserve_provider_call(self) -> None:
        """Account for direct Vertex embedding I/O outside the LiteLLM gateway."""

        if self._provider_call_guard is not None:
            self._provider_call_guard.reserve()

    def mechanics_for_promos(
        self,
        *,
        catalog_version_id: str,
        promo_ids: Iterable[str],
        max_chunks_per_promo: int = 5,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Load reviewed child mechanics and group them by parent promo."""

        wanted = {str(value or "").strip() for value in promo_ids if str(value or "").strip()}
        if not wanted:
            return {}
        query = self._firestore.collection(self._mechanics_collection).where(
            filter=FieldFilter("catalog_version_id", "==", catalog_version_id)
        )
        grouped: Dict[str, List[Dict[str, Any]]] = {promo_id: [] for promo_id in wanted}
        for snapshot in query.stream():
            payload = _snapshot_payload(snapshot)
            promo_id = str(payload.get("promo_id") or "").strip()
            if promo_id not in wanted or not _published_record(payload):
                continue
            grouped[promo_id].append(payload)
        for promo_id, rows in grouped.items():
            rows.sort(key=lambda row: (int(row.get("ordinal") or 9999), str(row.get("chunk_id") or "")))
            grouped[promo_id] = _select_compact_mechanic_rows(
                rows,
                max_chunks=max_chunks_per_promo,
            )
        return grouped

    def brand_profile(self, *, catalog_version_id: str, brand: str) -> Dict[str, Any]:
        """Return one reviewed brand profile from the active catalog version."""

        brand_key = _slug(brand)
        direct_id = f"{catalog_version_id}-{brand_key}"
        snapshot = self._firestore.collection(self._brand_profiles_collection).document(direct_id).get()
        if getattr(snapshot, "exists", False):
            payload = _snapshot_payload(snapshot)
            return payload if _published_record(payload) else {}
        query = self._firestore.collection(self._brand_profiles_collection).where(
            filter=FieldFilter("catalog_version_id", "==", catalog_version_id)
        )
        for row in query.stream():
            payload = _snapshot_payload(row)
            if str(payload.get("brand") or "").strip().casefold() == str(brand or "").strip().casefold():
                return payload if _published_record(payload) else {}
        return {}


class PromoCatalogService:
    """Runtime tool boundary for search, presentation, and click validation."""

    def __init__(
        self,
        repository: PromoCatalogRepository,
        *,
        product_lookup: Optional[Callable[[str, Sequence[str]], Sequence[Dict[str, Any]]]] = None,
        brand_knowledge: Optional[BrandKnowledgeService] = None,
    ) -> None:
        self.repository = repository
        self.product_lookup = product_lookup
        self.brand_knowledge = brand_knowledge
        self.latest_search: Optional[PromoSearchContext] = None

    def active_version_id(self) -> str:
        return str(self.repository.active_config().get("catalog_version_id") or "").strip()

    def exact_named_promo_reference(self, user_message: str) -> Dict[str, str]:
        """Resolve an exact current catalog title without hard-coded campaign names."""

        if not normalize_promo_query(user_message):
            return {}
        version_id = self.active_version_id()
        if not version_id:
            return {}
        for card in self.repository.list_cards(version_id):
            if not promo_is_current(card):
                continue
            title = str(card.get("title") or "").strip()
            if exact_promo_title_mentioned(user_message, title):
                return {
                    "catalog_version_id": version_id,
                    "promo_id": str(card.get("promo_id") or "").strip(),
                    "promo_ref": promo_ref(card),
                    "title": title,
                }
        return {}

    def search_promo_catalog(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Return compact, source-backed candidates from the active catalog."""

        started = time.perf_counter()
        query_text = str(payload.get("query") or "").strip()
        mode = str(payload.get("mode") or "targeted").strip().lower()
        if mode not in {"general", "targeted"}:
            return {"status": "error", "reason": "mode must be general or targeted", "read_only": True}
        alternative_scope = str(
            payload.get("alternative_scope") or "none"
        ).strip().lower()
        if alternative_scope not in {"none", "same_mechanic", "any_current"}:
            return {
                "status": "error",
                "reason": (
                    "alternative_scope must be none, same_mechanic, or any_current"
                ),
                "read_only": True,
            }
        top_k = max(1, min(int(payload.get("top_k") or (8 if mode == "general" else 5)), 8))
        tire_size = normalize_tire_size(payload.get("tire_size"))
        active = self.repository.active_config()
        version_id = str(active.get("catalog_version_id") or "").strip()
        if not version_id:
            return {"status": "unavailable", "reason": "no_active_catalog", "read_only": True}

        published_cards = self.repository.list_cards(version_id)
        all_cards = [card for card in published_cards if promo_is_current(card)]
        customer_brand_scope_supplied = (
            "_customer_query_text" in payload
            or "_customer_requested_brands" in payload
        )
        proposed_brands = requested_brand_names(query_text, all_cards)
        if customer_brand_scope_supplied:
            customer_query_text = str(
                payload.get("_customer_query_text") or ""
            ).strip()
            customer_brands = requested_brand_names(
                customer_query_text,
                all_cards,
            )
            normalized_customer_query = normalize_promo_query(
                customer_query_text
            )
            catalog_labels = {
                brand.casefold(): brand
                for card in all_cards
                for brand in (
                    str(value or "").strip()
                    for value in card.get("brands") or []
                )
                if brand
            }
            for brand in payload.get("_customer_requested_brands") or []:
                normalized = str(brand or "").strip().casefold()
                if normalized and re.search(
                    rf"\b{re.escape(normalized)}\b",
                    normalized_customer_query,
                ):
                    customer_brands.append(
                        catalog_labels.get(normalized, str(brand).strip())
                    )
            customer_brands = list(
                {
                    brand.casefold(): brand
                    for brand in reversed(customer_brands)
                }.values()
            )
            customer_brand_keys = {
                brand.casefold() for brand in customer_brands
            }
            rejected_plan_brands = [
                brand
                for brand in proposed_brands
                if brand.casefold() not in customer_brand_keys
            ]
            query_text = remove_promo_brand_terms(
                query_text,
                rejected_plan_brands,
            )
            for brand in customer_brands:
                if brand.casefold() not in {
                    value.casefold()
                    for value in requested_brand_names(query_text, all_cards)
                }:
                    query_text = " ".join(
                        value for value in (query_text, brand) if value
                    )
        else:
            customer_brands = proposed_brands
            rejected_plan_brands = []
        if mode == "general":
            ranked = all_cards[:top_k]
        else:
            if not query_text:
                return {"status": "error", "reason": "query is required for targeted mode", "read_only": True}
            pool_limit = min(max(top_k * 3, 8), 24)
            literal = self.repository.vector_candidates(
                catalog_version_id=version_id,
                query_text=query_text,
                limit=pool_limit,
            )
            normalized_query = normalize_promo_query(query_text)
            normalized = []
            if normalized_query and normalized_query != query_text.casefold():
                normalized = self.repository.vector_candidates(
                    catalog_version_id=version_id,
                    query_text=normalized_query,
                    limit=pool_limit,
                )
            current_refs = {promo_ref(card) for card in all_cards}
            current_candidates = [
                card
                for card in [*literal, *normalized]
                if promo_ref(card) in current_refs
            ]
            ranked = rerank_promo_candidates(
                query_text,
                current_candidates,
            )[:top_k]

        mechanics = self.repository.mechanics_for_promos(
            catalog_version_id=version_id,
            promo_ids=[card.get("promo_id") for card in ranked],
        )
        inventory_products: Sequence[Dict[str, Any]] = []
        if tire_size and self.product_lookup:
            brands = sorted({str(brand) for card in ranked for brand in card.get("brands") or [] if str(brand)})
            try:
                inventory_products = list(self.product_lookup(tire_size, brands) or [])
            except Exception:
                inventory_products = []
        requested_brands = (
            customer_brands
            if customer_brand_scope_supplied
            else requested_brand_names(query_text, all_cards)
        )
        alternative_query = remove_promo_brand_terms(
            query_text,
            requested_brands,
        )
        candidates = []
        allowed_refs: List[str] = []
        alternative_refs: List[str] = []
        for card in ranked:
            candidate = compact_promo_candidate(card, mechanics.get(str(card.get("promo_id") or ""), []))
            applicability = evaluate_promo_applicability(
                card,
                tire_size=tire_size,
                products=inventory_products,
                inventory_checked=bool(tire_size and self.product_lookup),
            )
            candidate["applicability"] = applicability
            candidate["query_constraint_match"] = (
                promo_candidate_matches_explicit_constraints(
                    query_text,
                    candidate,
                )
            )
            candidate["alternative_constraint_match"] = bool(
                alternative_scope == "any_current"
                or (
                    alternative_scope == "same_mechanic"
                    and promo_candidate_matches_explicit_constraints(
                        alternative_query,
                        candidate,
                    )
                )
            )
            candidate_brand_keys = {
                str(value or "").strip().casefold()
                for value in candidate.get("brands") or []
                if str(value or "").strip()
            }
            requested_brand_match = bool(
                not requested_brands
                or candidate_brand_keys.intersection(
                    brand.casefold() for brand in requested_brands
                )
            )
            candidate["requested_brand_match"] = requested_brand_match
            candidates.append(candidate)
            if (
                applicability["status"] in {
                    "eligible",
                    "not_size_qualified",
                }
                and candidate["query_constraint_match"]
                and requested_brand_match
                and candidate.get("promo_ref")
            ):
                allowed_refs.append(str(candidate["promo_ref"]))
            elif (
                alternative_scope != "none"
                and candidate["alternative_constraint_match"]
                and applicability["status"] in {
                    "eligible",
                    "not_size_qualified",
                }
                and candidate.get("promo_ref")
            ):
                alternative_refs.append(str(candidate["promo_ref"]))
        promo_refs = tuple(dict.fromkeys([*allowed_refs, *alternative_refs]))
        self.latest_search = PromoSearchContext(
            catalog_version_id=version_id,
            promo_refs=promo_refs,
            query=query_text,
            mode=mode,
            tire_size=tire_size,
        )
        exact_brand_matches = sorted(
            {
                brand
                for candidate in candidates
                if candidate.get("query_constraint_match") is True
                for brand in candidate.get("brands") or []
                if brand.casefold() in {item.casefold() for item in requested_brands}
            }
        )
        exact_brand_match_keys = {
            brand.casefold() for brand in exact_brand_matches
        }
        unmatched_requested_brands = [
            brand
            for brand in requested_brands
            if brand.casefold() not in exact_brand_match_keys
        ]
        evidence_ref = promo_search_evidence_ref(
            catalog_version_id=version_id,
            mode=mode,
            query=query_text,
            tire_size=tire_size,
            requested_brands=requested_brands,
            alternative_scope=alternative_scope,
        )
        return {
            "status": "ok",
            "catalog_version_id": version_id,
            "evidence_ref": evidence_ref,
            "mode": mode,
            "query": query_text,
            "candidate_count": len(candidates),
            "published_candidate_count": len(published_cards),
            "current_candidate_count": len(all_cards),
            "expired_candidate_count": len(published_cards) - len(all_cards),
            "candidates": candidates,
            "allowed_promo_refs": list(promo_refs),
            "primary_promo_refs": list(dict.fromkeys(allowed_refs)),
            "alternative_promo_refs": list(dict.fromkeys(alternative_refs)),
            "alternative_scope": alternative_scope,
            "tire_size": tire_size or None,
            "eligible_candidate_count": len(dict.fromkeys(allowed_refs)),
            "alternative_candidate_count": len(dict.fromkeys(alternative_refs)),
            "gallery_eligible_candidate_count": len(promo_refs),
            "requested_brands": requested_brands,
            "rejected_plan_brands": rejected_plan_brands,
            "matched_requested_brands": exact_brand_matches,
            "unmatched_requested_brands": unmatched_requested_brands,
            "exact_requested_brand_match": bool(exact_brand_matches) if requested_brands else None,
            "negative_match_guidance": (
                "No active promo matches one or more requested brands. State that clearly for each unmatched brand, then offer only alternative_promo_refs as the customer-requested fallback."
                if unmatched_requested_brands and alternative_refs
                else
                "No active promo matches one or more requested brands. State only that scoped result; unrelated candidates are not authorized as alternatives."
                if unmatched_requested_brands
                else ""
            ),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "read_only": True,
        }

    def present_promo_gallery(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Emit only stored card refs authorized by the current search.

        A mixed model proposal can contain usable refs plus candidates that the
        reviewed search did not authorize. Keeping the allowed intersection is
        safe and useful; an entirely unauthorized proposal still fails closed.
        """

        if self.latest_search is None:
            return {"status": "error", "reason": "search_promo_catalog must run before presentation", "read_only": True}
        requested = [str(value or "").strip() for value in payload.get("promo_refs") or [] if str(value or "").strip()]
        if not requested:
            return {"status": "error", "reason": "promo_refs is required", "read_only": True}
        allowed = set(self.latest_search.promo_refs)
        invalid = [ref for ref in requested if ref not in allowed]
        requested = list(
            dict.fromkeys(ref for ref in requested if ref in allowed)
        )
        if not requested:
            return {
                "status": "error",
                "reason": "promo_refs_not_returned_by_current_search",
                "invalid_promo_refs": invalid,
                "allowed_promo_refs": list(self.latest_search.promo_refs),
                "read_only": True,
            }
        active_version = self.active_version_id()
        if active_version != self.latest_search.catalog_version_id:
            return {"status": "stale", "reason": "active_catalog_changed", "read_only": True}
        records = {promo_ref(card): card for card in self.repository.list_cards(active_version)}
        cards: List[Dict[str, Any]] = []
        selected_promos: List[str] = []
        selected_card_refs: List[str] = []
        selected_promo_types: List[str] = []
        selected_promo_titles: List[str] = []
        max_promos = 3 if self.latest_search.mode == "targeted" else 8
        for ref in requested[:max_promos]:
            record = records.get(ref)
            if not record or not promo_is_current(record):
                continue
            visual_cards = [dict(card) for card in record.get("display_cards") or [] if isinstance(card, dict)]
            cards_before = len(cards)
            for card in visual_cards:
                if not _valid_public_image_url(card.get("image_url")):
                    continue
                cards.append(deepcopy(card))
                selected_card_refs.append(str(card.get("card_id") or card.get("card_ref") or ""))
                if len(cards) >= 8:
                    break
            if len(cards) > cards_before:
                selected_promos.append(str(record.get("promo_id") or ""))
                promo_type = str(record.get("promo_type") or "").strip()
                title = str(record.get("title") or "").strip()
                if promo_type:
                    selected_promo_types.append(promo_type)
                if title:
                    selected_promo_titles.append(title)
            if len(cards) >= 8:
                break
        if not cards:
            return {"status": "no_visual_cards", "reason": "selected_promos_have_no_valid_published_images", "read_only": True}
        fingerprint = selection_fingerprint(active_version, selected_promos, selected_card_refs)
        return {
            "status": "ok",
            "catalog_version_id": active_version,
            "presentation_ref": f"promo_gallery_{fingerprint[:16]}",
            "promo_refs": [f"promo:{promo_id}" for promo_id in selected_promos],
            "promo_ids": selected_promos,
            "promo_types": list(dict.fromkeys(selected_promo_types)),
            "promo_titles": list(dict.fromkeys(selected_promo_titles)),
            "card_refs": [value for value in selected_card_refs if value],
            "cards": cards,
            "selection_fingerprint": fingerprint,
            "trigger_mode": str(payload.get("trigger_mode") or self.latest_search.mode),
            "explicit_redisplay": payload.get("explicit_redisplay") is True,
            "rejected_promo_refs": invalid,
            "selection_normalized": bool(invalid),
            "card_runtime_insert": True,
            "read_only": True,
        }

    def validate_action(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a tracked card click against the currently active catalog."""

        active_version = self.active_version_id()
        supplied_version = str(payload.get("catalog_version_id") or "").strip()
        promo_id = str(payload.get("promo_id") or "").strip()
        card_id = str(payload.get("card_id") or "").strip()
        action = str(payload.get("action") or "").strip().lower()
        selected_brand = str(payload.get("selected_brand") or "").strip()
        if action not in SUPPORTED_ACTIONS:
            return {"status": "invalid", "reason": "unsupported_action", "active_catalog_version_id": active_version}
        if not active_version or supplied_version != active_version:
            return {"status": "stale", "reason": "catalog_version_is_not_active", "active_catalog_version_id": active_version}
        record = next(
            (card for card in self.repository.list_cards(active_version) if str(card.get("promo_id") or "") == promo_id),
            None,
        )
        if not record or not promo_is_current(record):
            return {"status": "stale", "reason": "promo_is_missing_or_expired", "active_catalog_version_id": active_version}
        visual = next(
            (card for card in record.get("display_cards") or [] if str(card.get("card_id") or card.get("card_ref") or "") == card_id),
            None,
        )
        if not visual:
            return {"status": "invalid", "reason": "card_not_found", "active_catalog_version_id": active_version}
        card_buttons = [button for button in visual.get("buttons") or [] if isinstance(button, dict)]
        allowed_actions = {str(button.get("action") or "").strip().lower() for button in card_buttons}
        if action not in allowed_actions:
            return {"status": "invalid", "reason": "action_not_allowed_for_card", "allowed_actions": sorted(allowed_actions)}
        brands = [str(value).strip() for value in record.get("brands") or [] if str(value).strip()]
        if selected_brand and selected_brand.casefold() not in {brand.casefold() for brand in brands}:
            return {"status": "invalid", "reason": "selected_brand_not_allowed", "allowed_brands": brands}
        exact_button = next(
            (
                button
                for button in card_buttons
                if str(button.get("action") or "").strip().lower() == action
                and str(button.get("selected_brand") or "").strip().casefold() == selected_brand.casefold()
            ),
            None,
        )
        if exact_button is None:
            return {
                "status": "invalid",
                "reason": "action_brand_pair_not_allowed_for_card",
                "allowed_brands": brands,
            }
        brand_profile = {}
        if action == "about_brand" and selected_brand:
            if self.brand_knowledge is not None:
                brand_profile = self.brand_knowledge.profile_for_brand(
                    selected_brand
                )
            else:
                brand_profile = self.repository.brand_profile(
                    catalog_version_id=active_version,
                    brand=selected_brand,
                )
            if not brand_profile:
                return {"status": "invalid", "reason": "reviewed_brand_profile_missing"}
        mechanics = self.repository.mechanics_for_promos(
            catalog_version_id=active_version,
            promo_ids=[promo_id],
        ).get(promo_id, [])
        return {
            "status": "valid",
            "catalog_version_id": active_version,
            "promo": compact_promo_candidate(record, mechanics),
            "card_id": card_id,
            "action": action,
            "selected_brand": selected_brand,
            "brand_profile": _compact_brand_profile(brand_profile),
            "read_only": True,
        }


def compact_promo_candidate(card: Dict[str, Any], mechanics: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Return only model-safe, reviewed facts and source references."""

    mechanic_rows = []
    for row in mechanics:
        text = str(row.get("text") or row.get("mechanic") or "").strip()
        if text:
            mechanic_rows.append(
                {
                    "text": text,
                    "evidence_refs": list(row.get("evidence_refs") or row.get("source_evidence") or []),
                }
            )
    return {
        "promo_ref": promo_ref(card),
        "promo_id": str(card.get("promo_id") or ""),
        "title": str(card.get("title") or ""),
        "brands": [str(value) for value in card.get("brands") or []],
        "offer_summary": str(card.get("offer_summary") or ""),
        "valid_from": _date_text(card.get("valid_from")),
        "valid_until": _date_text(card.get("valid_until")),
        "relevant_mechanics": mechanic_rows,
        "evidence_refs": list(card.get("evidence_refs") or card.get("source_evidence") or []),
        "retrieval_score": round(float(card.get("retrieval_score") or 0.0), 6),
        "has_visual_cards": any(
            _valid_public_image_url(item.get("image_url"))
            for item in card.get("display_cards") or []
            if isinstance(item, dict)
        ),
    }


def _select_compact_mechanic_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    max_chunks: int,
) -> List[Dict[str, Any]]:
    """Keep core mechanics plus a bounded exact operational URL mechanic."""

    limit = max(1, int(max_chunks or 1))
    core_limit = min(4, limit)
    selected = list(rows[:core_limit])
    if len(selected) >= limit:
        return selected

    selected_urls = {
        url
        for row in selected
        for url in re.findall(
            r"https?://[^\s,|]+",
            str(row.get("text") or row.get("mechanic") or ""),
        )
    }
    for row in rows[core_limit:]:
        urls = re.findall(
            r"https?://[^\s,|]+",
            str(row.get("text") or row.get("mechanic") or ""),
        )
        if not urls or all(url in selected_urls for url in urls):
            continue
        selected.append(row)
        selected_urls.update(urls)
        if len(selected) >= limit:
            break
    return selected


def rerank_promo_candidates(query: str, candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Union duplicate vector hits and add deterministic exact-match bonuses."""

    by_ref: Dict[str, Dict[str, Any]] = {}
    for candidate in candidates:
        ref = promo_ref(candidate)
        if not ref:
            continue
        current = by_ref.get(ref)
        distance = _float(candidate.get("vector_distance"), default=1.0)
        if current is None or distance < _float(current.get("vector_distance"), default=1.0):
            by_ref[ref] = dict(candidate)

    normalized_query = normalize_promo_query(query)
    query_amounts = set(extract_amounts(normalized_query))
    query_has_3plus1 = "3+1" in normalized_query or "buy 3 get 1" in normalized_query
    query_tokens = {token for token in re.findall(r"[a-z0-9]+", normalized_query) if len(token) > 2}
    ranked: List[Dict[str, Any]] = []
    for candidate in by_ref.values():
        haystack = normalize_promo_query(
            " ".join(
                [
                    str(candidate.get("title") or ""),
                    " ".join(str(value) for value in candidate.get("brands") or []),
                    str(candidate.get("promo_type") or ""),
                    str(candidate.get("offer_summary") or ""),
                    " ".join(str(value) for value in candidate.get("retrieval_aliases") or []),
                    " ".join(str(value) for value in candidate.get("mechanics") or []),
                ]
            )
        )
        candidate_amounts = set(extract_amounts(haystack))
        distance = _float(candidate.get("vector_distance"), default=1.0)
        score = 1.0 - distance
        if query_amounts:
            if query_amounts.intersection(candidate_amounts):
                score += 1.25
            elif candidate_amounts:
                score -= 0.45
        candidate_has_3plus1 = "3+1" in haystack or "buy 3 get 1" in haystack or "buy_3_get_1" in haystack
        if query_has_3plus1 and candidate_has_3plus1:
            score += 0.75
        literal_overlap = query_tokens.intersection(set(re.findall(r"[a-z0-9]+", haystack)))
        score += min(len(literal_overlap), 4) * 0.08
        candidate["retrieval_score"] = score
        ranked.append(candidate)
    return sorted(
        ranked,
        key=lambda item: (
            -_float(item.get("retrieval_score")),
            int(item.get("display_order") or 9999),
            str(item.get("promo_id") or ""),
        ),
    )


def promo_candidate_matches_explicit_constraints(
    query: str,
    candidate: Dict[str, Any],
) -> bool:
    """Validate explicit offer mechanics after model-led promo routing."""

    normalized_query = normalize_promo_query(query)
    mechanics = " ".join(
        str(row.get("text") or "")
        for row in candidate.get("relevant_mechanics") or []
        if isinstance(row, dict)
    )
    candidate_text = normalize_promo_query(
        " ".join(
            [
                str(candidate.get("title") or ""),
                str(candidate.get("offer_summary") or ""),
                mechanics,
            ]
        )
    )
    query_has_3plus1 = (
        "3+1" in normalized_query
        or "buy 3 get 1" in normalized_query
    )
    candidate_has_3plus1 = (
        "3+1" in candidate_text
        or "buy 3 get 1" in candidate_text
        or "buy_3_get_1" in candidate_text
    )
    if query_has_3plus1 and not candidate_has_3plus1:
        return False

    query_amounts = set(explicit_offer_amounts(query))
    if query_amounts:
        candidate_amounts = set(extract_amounts(candidate_text))
        if not query_amounts.intersection(candidate_amounts):
            return False
    return True


def explicit_offer_amounts(value: str) -> List[str]:
    """Return amounts that the customer explicitly framed as offer values."""

    text = str(value or "").casefold().replace("\u20b1", " php ")
    values: List[str] = []
    patterns = (
        r"\bphp\.?\s*([1-9][0-9,]*(?:\.\d+)?)",
        r"\b([1-9][0-9]*(?:\.\d+)?)\s*k\b",
        r"\b([1-9][0-9,]{2,}(?:\.\d+)?)\s*(?:off|discount|save|savings)\b",
    )
    for index, pattern in enumerate(patterns):
        for match in re.finditer(pattern, text):
            raw = match.group(1).replace(",", "")
            if index == 1:
                raw = str(int(float(raw) * 1000))
            elif raw.endswith(".0"):
                raw = raw[:-2]
            values.append(raw)
    return list(dict.fromkeys(values))


def normalize_promo_query(value: str) -> str:
    """Normalize currency and common mechanic aliases without dropping intent."""

    text = str(value or "").casefold().replace("\u20b1", " php ")
    text = re.sub(r"\b(?:php|php\.)\s*([0-9][0-9,]*(?:\.\d+)?)", lambda match: f" php {match.group(1).replace(',', '')} ", text)
    text = re.sub(r"\b([0-9]+)\s*[+]\s*([0-9]+)\b", r"\1+\2 buy \1 get \2", text)
    text = re.sub(r"\bbuy\s+three\s+get\s+one\b", "buy 3 get 1 3+1", text)
    text = re.sub(r"\b([0-9]+)k\b", lambda match: str(int(match.group(1)) * 1000), text)
    return " ".join(text.split())


def exact_promo_title_mentioned(message: str, title: str) -> bool:
    """Match one catalog title as an entity, allowing a leading ``The`` to be omitted."""

    normalized_message = normalize_promo_query(message)
    normalized_title = normalize_promo_query(title)
    if not normalized_message or len(normalized_title.split()) < 2:
        return False
    title_forms = [normalized_title]
    if normalized_title.startswith("the "):
        title_forms.append(normalized_title[4:].strip())
    return any(
        form
        and len(form.split()) >= 2
        and re.search(
            rf"(?<![a-z0-9]){re.escape(form)}(?![a-z0-9])",
            normalized_message,
        )
        for form in title_forms
    )


def extract_amounts(value: str) -> List[str]:
    """Return normalized monetary amounts from customer or catalog text."""

    text = normalize_promo_query(value)
    amounts = re.findall(r"(?:php\s*)?\b([1-9][0-9]{2,})\b", text)
    return list(dict.fromkeys(amount.replace(",", "") for amount in amounts))


def requested_brand_names(query: str, cards: Sequence[Dict[str, Any]]) -> List[str]:
    """Detect explicit brands for negative-match reporting, never pre-filtering."""

    catalog_brands = {
        str(brand).strip()
        for card in cards
        for brand in card.get("brands") or []
        if str(brand).strip()
    }
    labels = {brand.casefold(): brand for brand in catalog_brands}
    for brand in KNOWN_TIRE_BRANDS:
        labels.setdefault(brand, brand.title())
    normalized = normalize_promo_query(query)
    return [label for key, label in sorted(labels.items()) if re.search(rf"\b{re.escape(key)}\b", normalized)]


def remove_promo_brand_terms(query: str, brands: Sequence[str]) -> str:
    """Remove model-only brand terms while preserving the proposed promo intent."""

    cleaned = str(query or "")
    for brand in sorted(
        {str(value or "").strip() for value in brands if str(value or "").strip()},
        key=len,
        reverse=True,
    ):
        words = [re.escape(value) for value in re.findall(r"[A-Za-z0-9]+", brand)]
        if not words:
            continue
        flexible_name = r"[\s\W]+".join(words)
        cleaned = re.sub(
            rf"(?<![A-Za-z0-9]){flexible_name}(?![A-Za-z0-9])",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
    return " ".join(cleaned.split())


def is_targeted_promo_query(user_message: str) -> bool:
    """Identify promo-oriented evaluation queries outside customer routing."""

    normalized = normalize_promo_query(user_message)
    return any(marker in normalized for marker in PROMO_QUERY_MARKERS)


def promo_ref(card: Dict[str, Any]) -> str:
    promo_id = str(card.get("promo_id") or "").strip()
    return f"promo:{promo_id}" if promo_id else ""


def normalize_tire_size(value: Any) -> str:
    """Return one canonical passenger-tire size or an empty string."""

    compact = re.sub(r"[^0-9A-Z]", "", str(value or "").upper())
    match = re.fullmatch(r"(\d{3})(\d{2})(ZR|R)?(\d{2})", compact)
    if not match:
        return ""
    return f"{match.group(1)}/{match.group(2)}{match.group(3) or 'R'}{match.group(4)}"


def evaluate_promo_applicability(
    card: Dict[str, Any],
    *,
    tire_size: str,
    products: Sequence[Dict[str, Any]],
    inventory_checked: bool,
) -> Dict[str, Any]:
    """Combine reviewed eligibility with exact-size visible inventory."""

    canonical_size = normalize_tire_size(tire_size)
    if not canonical_size:
        return {"status": "not_size_qualified", "reason": "tire_size_not_supplied"}
    rule = card.get("eligibility") if isinstance(card.get("eligibility"), dict) else {}
    if not rule:
        return {"status": "ineligible", "reason": "reviewed_eligibility_missing", "tire_size": canonical_size}
    included_sizes = {normalize_tire_size(value) for value in rule.get("included_sizes") or []}
    excluded_sizes = {normalize_tire_size(value) for value in rule.get("excluded_sizes") or []}
    included_sizes.discard("")
    excluded_sizes.discard("")
    if canonical_size in excluded_sizes:
        return {"status": "ineligible", "reason": "size_explicitly_excluded", "tire_size": canonical_size}
    scope = str(rule.get("scope") or "").strip().casefold()
    if scope == "selected_sizes" and canonical_size not in included_sizes:
        return {"status": "ineligible", "reason": "size_not_in_reviewed_rule", "tire_size": canonical_size}
    if not inventory_checked:
        return {"status": "ineligible", "reason": "exact_size_inventory_not_checked", "tire_size": canonical_size}

    included_brands = {
        str(value).strip().casefold()
        for value in (rule.get("included_brands") or card.get("brands") or [])
        if str(value).strip()
    }
    excluded_brands = {str(value).strip().casefold() for value in rule.get("excluded_brands") or [] if str(value).strip()}
    included_patterns = {normalize_promo_query(value) for value in rule.get("included_patterns") or [] if str(value).strip()}
    excluded_patterns = {normalize_promo_query(value) for value in rule.get("excluded_patterns") or [] if str(value).strip()}
    matches: List[Dict[str, str]] = []
    for product in products or []:
        product_size = normalize_tire_size(
            product.get("tire_size")
            or product.get("size")
            or product.get("size_text")
        )
        brand = str(product.get("brand") or "").strip()
        brand_key = brand.casefold()
        pattern = normalize_promo_query(
            " ".join(
                str(product.get(key) or "")
                for key in ("sku_model", "model", "pattern", "name", "title")
            )
        )
        if product_size != canonical_size or brand_key in excluded_brands:
            continue
        if included_brands and brand_key not in included_brands:
            continue
        if any(value and value in pattern for value in excluded_patterns):
            continue
        if scope in {"selected_patterns", "selected_products"} and not any(
            value and value in pattern for value in included_patterns
        ):
            continue
        matches.append({"brand": brand, "product_ref": str(product.get("item_ref") or product.get("product_id") or "")})
    if not matches:
        return {"status": "ineligible", "reason": "no_visible_eligible_exact_size_product", "tire_size": canonical_size}
    return {
        "status": "eligible",
        "reason": "reviewed_rule_and_inventory_match",
        "tire_size": canonical_size,
        "eligible_product_count": len(matches),
        "eligible_brands": sorted({item["brand"] for item in matches if item["brand"]}),
    }


def promo_is_current(card: Dict[str, Any], *, today: Optional[date] = None) -> bool:
    """Apply reviewed validity dates at read time."""

    current = today or datetime.now(ZoneInfo("Asia/Manila")).date()
    valid_from = _parse_date(card.get("valid_from"))
    valid_until = _parse_date(card.get("valid_until"))
    if valid_from and current < valid_from:
        return False
    if valid_until and current > valid_until:
        return False
    return True


def selection_fingerprint(version_id: str, promo_ids: Sequence[str], card_refs: Sequence[str]) -> str:
    payload = json.dumps(
        {"version": version_id, "promos": list(promo_ids), "cards": list(card_refs)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def promo_search_evidence_ref(
    *,
    catalog_version_id: str,
    mode: str,
    query: str,
    tire_size: str,
    requested_brands: Sequence[str],
    alternative_scope: str = "none",
) -> str:
    """Return a stable ref for one reviewed promo-search result scope.

    The ref authorizes positive or negative facts about the exact validated
    search result. It does not authorize any individual offer that is absent
    from ``allowed_promo_refs``.
    """

    scope = json.dumps(
        {
            "mode": str(mode or "").strip().casefold(),
            "query": normalize_promo_query(query),
            "tire_size": normalize_tire_size(tire_size) or "",
            "requested_brands": sorted(
                {
                    str(brand or "").strip().casefold()
                    for brand in requested_brands or []
                    if str(brand or "").strip()
                }
            ),
            "alternative_scope": str(
                alternative_scope or "none"
            ).strip().casefold(),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:20]
    return f"promo_search:{catalog_version_id}:{digest}"


def _snapshot_payload(snapshot: Any) -> Dict[str, Any]:
    payload = dict(snapshot.to_dict() or {})
    payload.setdefault("document_id", str(getattr(snapshot, "id", "") or ""))
    return payload


def _published_record(payload: Dict[str, Any]) -> bool:
    status = str(payload.get("status") or "published").strip().lower()
    return status in {"published", "active", "approved"} and payload.get("enabled", True) is not False


def _valid_public_image_url(value: Any) -> bool:
    url = str(value or "").strip()
    return url.startswith("https://storage.googleapis.com/") and "?" not in url


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _date_text(value: Any) -> str:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else ""


def _float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").casefold()).strip("-")


def _compact_brand_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    if not profile:
        return {}
    if profile.get("profile_ref") or profile.get("about_brand"):
        return {
            "profile_ref": str(profile.get("profile_ref") or ""),
            "brand": str(profile.get("brand") or ""),
            "about_brand": str(profile.get("about_brand") or ""),
            "origin_country": str(profile.get("origin_country") or ""),
            "market_segment": str(profile.get("market_segment") or ""),
            "manufacturer_warranty": dict(
                profile.get("manufacturer_warranty") or {}
            ),
            "gulong_guarantee": dict(
                profile.get("gulong_guarantee") or {}
            ),
            "warranty_policy": dict(
                profile.get("warranty_policy") or {}
            ),
            "source_updated_at": str(
                profile.get("source_updated_at") or ""
            ),
            "source_urls": list(profile.get("source_urls") or []),
            "evidence_refs": list(profile.get("evidence_refs") or []),
        }
    return {
        "brand": str(profile.get("brand") or ""),
        "summary": str(profile.get("summary") or ""),
        "positioning": list(profile.get("positioning") or []),
        "evidence_refs": list(profile.get("evidence_refs") or profile.get("source_evidence") or []),
    }
