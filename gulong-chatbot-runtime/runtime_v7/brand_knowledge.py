"""Published Gulong brand knowledge retrieval for Runtime V7.

The runtime reads only an atomically activated Firestore version produced from
Gulong.ph brand pages. Narrative background may be found semantically, while
exact warranty claims come from structured fields on the published profile.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Protocol

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from google.cloud.firestore_v1.vector import Vector

from scripts.promo_vector_trial import VertexEmbedder
from runtime_v7.llm_gateway import RuntimeV7ProviderCallGuard, RuntimeV7ProviderCallLimitExceeded


ACTIVE_CONFIG_COLLECTION = "brand_knowledge_config"
ACTIVE_CONFIG_DOCUMENT = "active"
PROFILES_COLLECTION = "brand_knowledge_profiles"
CHUNKS_COLLECTION = "brand_knowledge_chunks"
logger = logging.getLogger(__name__)


class BrandEmbeddingGateway(Protocol):
    """Minimal embedding interface used by semantic brand retrieval."""

    def embed(self, text: str, *, task_type: str) -> List[float]:
        ...


def brand_knowledge_enabled(*, value: Optional[str] = None) -> bool:
    """Return whether source-backed brand retrieval is enabled."""

    raw = (
        os.getenv("RUNTIME_V7_BRAND_KNOWLEDGE_ENABLED", "0")
        if value is None
        else value
    )
    return str(raw or "").strip().casefold() in {"1", "true", "yes", "on"}


class BrandKnowledgeRepository:
    """Read one active immutable brand-knowledge publication."""

    def __init__(
        self,
        *,
        project_id: Optional[str] = None,
        firestore_client: Any = None,
        embedder: Optional[BrandEmbeddingGateway] = None,
        profiles_collection: str = PROFILES_COLLECTION,
        chunks_collection: str = CHUNKS_COLLECTION,
        config_collection: str = ACTIVE_CONFIG_COLLECTION,
        embedding_service_account: Optional[str] = None,
        provider_call_guard: Optional[RuntimeV7ProviderCallGuard] = None,
    ) -> None:
        self._project_id = project_id or os.getenv(
            "GOOGLE_CLOUD_PROJECT",
            "gulong-chatbot-459723",
        )
        self._firestore = firestore_client or firestore.Client(
            project=self._project_id
        )
        self._embedder = embedder
        self._profiles_collection = profiles_collection
        self._chunks_collection = chunks_collection
        self._config_collection = config_collection
        self._embedding_service_account = (
            str(embedding_service_account).strip()
            if embedding_service_account is not None
            else os.getenv(
                "BRAND_KNOWLEDGE_EMBEDDING_SERVICE_ACCOUNT",
                os.getenv("PROMO_CATALOG_EMBEDDING_SERVICE_ACCOUNT", ""),
            ).strip()
        )
        self._provider_call_guard = provider_call_guard

    def active_config(self) -> Dict[str, Any]:
        """Return the active pointer, or an empty mapping."""

        snapshot = (
            self._firestore.collection(self._config_collection)
            .document(ACTIVE_CONFIG_DOCUMENT)
            .get()
        )
        if not getattr(snapshot, "exists", False):
            return {}
        payload = dict(snapshot.to_dict() or {})
        version_id = str(
            payload.get("brand_knowledge_version_id")
            or payload.get("active_version_id")
            or ""
        ).strip()
        if version_id:
            payload["brand_knowledge_version_id"] = version_id
        return payload

    def profile(
        self,
        *,
        version_id: str,
        brand: str,
    ) -> Dict[str, Any]:
        """Return one published profile by exact normalized brand name."""

        slug = _slug(brand)
        if not version_id or not slug:
            return {}
        snapshot = (
            self._firestore.collection(self._profiles_collection)
            .document(f"{version_id}-{slug}")
            .get()
        )
        if getattr(snapshot, "exists", False):
            payload = _snapshot_payload(snapshot)
            return payload if _published_record(payload) else {}
        query = self._firestore.collection(self._profiles_collection).where(
            filter=FieldFilter("version_id", "==", version_id)
        )
        for row in query.stream():
            payload = _snapshot_payload(row)
            if _slug(payload.get("brand")) == slug:
                return payload if _published_record(payload) else {}
        return {}

    def semantic_profiles(
        self,
        *,
        version_id: str,
        query_text: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Return published profiles selected by narrative chunk similarity."""

        if not version_id or not str(query_text or "").strip():
            return []
        try:
            embedder = self._embedder or VertexEmbedder(
                self._project_id,
                dimensions=768,
                service_account_email=self._embedding_service_account,
            )
            self._reserve_provider_call()
            vector = embedder.embed(
                str(query_text).strip(),
                task_type="RETRIEVAL_QUERY",
            )
            query = (
                self._firestore.collection(self._chunks_collection)
                .where(filter=FieldFilter("version_id", "==", version_id))
                .find_nearest(
                    vector_field="embedding",
                    query_vector=Vector(vector),
                    distance_measure=DistanceMeasure.COSINE,
                    limit=max(1, min(int(limit or 4) * 2, 12)),
                    distance_result_field="vector_distance",
                )
            )
            profiles: List[Dict[str, Any]] = []
            seen: set[str] = set()
            for snapshot in query.stream():
                chunk = _snapshot_payload(snapshot)
                if not _published_record(chunk):
                    continue
                slug = _slug(
                    chunk.get("brand_slug") or chunk.get("brand")
                )
                if not slug or slug in seen:
                    continue
                profile = self.profile(
                    version_id=version_id,
                    brand=slug,
                )
                if not profile:
                    continue
                profile["vector_distance"] = chunk.get("vector_distance")
                profile["matched_chunk_type"] = chunk.get("chunk_type")
                profile["retrieval_method"] = "vector"
                profiles.append(profile)
                seen.add(slug)
                if len(profiles) >= max(1, min(int(limit or 4), 4)):
                    break
            return profiles
        except RuntimeV7ProviderCallLimitExceeded:
            # The tester ceiling must reach the endpoint diagnostic instead of
            # silently falling back to lexical retrieval.
            raise
        except Exception as exc:
            # Index creation and short provider interruptions must not make a
            # read-only brand question fail. The active corpus is only a few
            # dozen profiles, so a bounded lexical scan is a safe fallback.
            logger.warning(
                "Brand semantic retrieval failed; using lexical fallback: %s",
                type(exc).__name__,
            )
            return self._lexical_profiles(
                version_id=version_id,
                query_text=query_text,
                limit=limit,
            )

    def _reserve_provider_call(self) -> None:
        """Account for direct Vertex embedding I/O outside the LiteLLM gateway."""

        if self._provider_call_guard is not None:
            self._provider_call_guard.reserve()

    def _lexical_profiles(
        self,
        *,
        version_id: str,
        query_text: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        tokens = {
            value
            for value in re.findall(
                r"[a-z0-9]+",
                str(query_text or "").casefold(),
            )
            if len(value) > 2
        }
        query = self._firestore.collection(
            self._profiles_collection
        ).where(filter=FieldFilter("version_id", "==", version_id))
        ranked: List[tuple[int, str, Dict[str, Any]]] = []
        for snapshot in query.stream():
            profile = _snapshot_payload(snapshot)
            if not _published_record(profile):
                continue
            text = " ".join(
                str(profile.get(key) or "")
                for key in (
                    "brand",
                    "about_brand",
                    "origin_country",
                    "market_segment",
                )
            ).casefold()
            score = sum(1 for token in tokens if token in text)
            if score <= 0:
                continue
            profile["retrieval_method"] = "lexical_fallback"
            ranked.append(
                (
                    score,
                    str(profile.get("brand") or ""),
                    profile,
                )
            )
        ranked.sort(key=lambda row: (-row[0], row[1]))
        return [
            profile
            for _, _, profile in ranked[
                : max(1, min(int(limit or 4), 4))
            ]
        ]


class BrandKnowledgeService:
    """Validate model brand-query plans and return source-backed facts."""

    def __init__(self, repository: BrandKnowledgeRepository) -> None:
        self.repository = repository

    def active_version_id(self) -> str:
        return str(
            self.repository.active_config().get(
                "brand_knowledge_version_id"
            )
            or ""
        ).strip()

    def profile_for_brand(self, brand: str) -> Dict[str, Any]:
        """Return one compact exact profile from the active publication."""

        version_id = self.active_version_id()
        profile = self.repository.profile(
            version_id=version_id,
            brand=brand,
        )
        return compact_brand_profile(profile) if profile else {}

    def get_brand_knowledge(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a bounded exact-or-semantic brand knowledge query."""

        version_id = self.active_version_id()
        if not version_id:
            return {
                "status": "unavailable",
                "reason": "no_active_brand_knowledge",
                "read_only": True,
            }
        query = str(payload.get("query") or "").strip()
        proposed = [
            str(value).strip()
            for value in payload.get("brands") or []
            if str(value).strip()
        ][:4]
        customer_query = str(
            payload.get("_customer_query_text") or ""
        ).strip()
        trusted_brands = {
            _slug(value)
            for value in payload.get("_trusted_brands") or []
            if _slug(value)
        }
        normalized_customer = " ".join(
            re.findall(r"[a-z0-9]+", customer_query.casefold())
        )
        requested: List[str] = []
        rejected: List[str] = []
        for brand in proposed:
            slug = _slug(brand)
            normalized_brand = slug.replace("-", " ")
            customer_named = bool(
                normalized_brand
                and re.search(
                    rf"(?:^|\s){re.escape(normalized_brand)}(?:\s|$)",
                    normalized_customer,
                )
            )
            if customer_named or slug in trusted_brands:
                requested.append(brand)
            else:
                rejected.append(brand)
        profiles: List[Dict[str, Any]] = []
        seen: set[str] = set()
        missing: List[str] = []
        for brand in requested:
            profile = self.repository.profile(
                version_id=version_id,
                brand=brand,
            )
            if not profile:
                missing.append(brand)
                continue
            slug = _slug(profile.get("brand"))
            if slug not in seen:
                profiles.append(profile)
                seen.add(slug)
        if query and not requested:
            for profile in self.repository.semantic_profiles(
                version_id=version_id,
                query_text=query,
                limit=4,
            ):
                slug = _slug(profile.get("brand"))
                if slug and slug not in seen:
                    profiles.append(profile)
                    seen.add(slug)
                if len(profiles) >= 4:
                    break
        compact = [compact_brand_profile(profile) for profile in profiles]
        return {
            "status": "ok" if compact else "not_found",
            "brand_knowledge_version_id": version_id,
            "profiles": compact,
            "missing_brands": missing,
            "rejected_proposed_brands": rejected,
            "query": query,
            "read_only": True,
        }


def compact_brand_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Return bounded model-safe narrative and structured warranty evidence."""

    if not profile:
        return {}
    version_id = str(profile.get("version_id") or "").strip()
    brand = str(profile.get("brand") or "").strip()
    source_urls = [
        str(value).strip()
        for value in profile.get("source_urls") or []
        if str(value).strip()
    ]
    evidence_refs = [
        str(value).strip()
        for value in profile.get("evidence_refs") or []
        if str(value).strip()
    ]
    profile_ref = (
        f"brand_profile:{version_id}:{_slug(brand)}"
        if version_id and brand
        else ""
    )
    if profile_ref and profile_ref not in evidence_refs:
        evidence_refs.append(profile_ref)
    warranty_policy = _compact_warranty_policy(
        profile.get("warranty_policy") or {}
    )
    gulong_guarantee = dict(
        profile.get("gulong_guarantee") or {}
    )
    if (
        not gulong_guarantee.get("conditions")
        and warranty_policy.get("conditions")
    ):
        gulong_guarantee["conditions"] = list(
            warranty_policy.get("conditions") or []
        )
    return {
        "profile_ref": profile_ref,
        "brand": brand,
        "about_brand": str(profile.get("about_brand") or "").strip(),
        "origin_country": str(
            profile.get("origin_country") or ""
        ).strip(),
        "market_segment": str(
            profile.get("market_segment") or ""
        ).strip(),
        "manufacturer_warranty": dict(
            profile.get("manufacturer_warranty") or {}
        ),
        "gulong_guarantee": gulong_guarantee,
        "warranty_policy": warranty_policy,
        "source_updated_at": str(
            profile.get("source_updated_at") or ""
        ).strip(),
        "source_urls": source_urls,
        "evidence_refs": evidence_refs,
        "matched_chunk_type": str(
            profile.get("matched_chunk_type") or ""
        ).strip(),
        "retrieval_method": str(
            profile.get("retrieval_method") or "exact"
        ).strip(),
    }


def _snapshot_payload(snapshot: Any) -> Dict[str, Any]:
    payload = dict(snapshot.to_dict() or {})
    if getattr(snapshot, "id", None):
        payload.setdefault("document_id", snapshot.id)
    return payload


def _compact_warranty_policy(value: Any) -> Dict[str, Any]:
    """Keep exact policy evidence useful without flooding the model context."""

    policy = dict(value or {}) if isinstance(value, dict) else {}
    limits = {
        "coverage": 2,
        "period": 2,
        "conditions": 5,
        "claim_process": 4,
        "limitations": 5,
    }
    output: Dict[str, Any] = {}
    for key, max_items in limits.items():
        raw = policy.get(key)
        rows = raw if isinstance(raw, list) else [raw] if raw else []
        bounded = [
            str(item).strip()[:500]
            for item in rows
            if str(item or "").strip()
        ][:max_items]
        if bounded:
            output[key] = bounded
    return output


def _published_record(payload: Dict[str, Any]) -> bool:
    return (
        str(payload.get("status") or "").strip().casefold() == "published"
        and payload.get("enabled", True) is not False
    )


def _slug(value: Any) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "-",
        str(value or "").casefold(),
    ).strip("-")
