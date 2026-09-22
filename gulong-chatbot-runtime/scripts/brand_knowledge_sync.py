"""Publish Gulong.ph brand background and warranty knowledge to Firestore.

The command fetches the public brand directory and each active brand page,
validates the source shape, creates narrative and warranty embeddings, and
atomically activates one immutable version. Any fetch, parse, schema, or
embedding failure leaves the previous active version unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Dict, List, Sequence
from zoneinfo import ZoneInfo

import requests
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector

from runtime_v7.brand_knowledge import (
    ACTIVE_CONFIG_COLLECTION,
    ACTIVE_CONFIG_DOCUMENT,
    CHUNKS_COLLECTION,
    PROFILES_COLLECTION,
)
from scripts.promo_vector_trial import VertexEmbedder


MANILA = ZoneInfo("Asia/Manila")
DEFAULT_BRANDS_URL = "https://gulong.ph/brands"
BRAND_SCHEMA_VERSION = "brand-knowledge-v1"
_POLICY_HEADINGS = {
    "warranty coverage": "coverage",
    "warranty period": "period",
    "conditions for warranty claims": "conditions",
    "claim process": "claim_process",
    "limitations": "limitations",
}


class _WarrantySectionParser(HTMLParser):
    """Extract block text only from the public warranty-policy section."""

    _BLOCK_TAGS = {
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "section",
        "ul",
        "ol",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.capturing = False
        self.section_depth = 0
        self.parts: List[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: Sequence[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        if (
            not self.capturing
            and tag == "section"
            and attributes.get("id") == "warranty_policy"
        ):
            self.capturing = True
            self.section_depth = 1
            self.parts.append("\n")
            return
        if not self.capturing:
            return
        if tag == "section":
            self.section_depth += 1
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self.capturing:
            return
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "section":
            self.section_depth -= 1
            if self.section_depth <= 0:
                self.capturing = False

    def handle_data(self, data: str) -> None:
        if self.capturing and str(data or "").strip():
            self.parts.append(data)

    def lines(self) -> List[str]:
        values = [
            re.sub(r"\s+", " ", value).strip()
            for value in "".join(self.parts).splitlines()
        ]
        return list(dict.fromkeys(value for value in values if value))


def extract_brand_directory(html: str) -> List[Dict[str, Any]]:
    """Extract the website's server-rendered brand records."""

    match = re.search(
        r'\\"brands\\":(\[.*?\]),\\"brandsToday\\":',
        str(html or ""),
        re.DOTALL,
    )
    if not match:
        raise ValueError("brand_directory_payload_missing")
    try:
        decoded = json.loads('"' + match.group(1) + '"')
        rows = json.loads(decoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("brand_directory_payload_invalid") from exc
    if not isinstance(rows, list) or not rows:
        raise ValueError("brand_directory_empty")
    output: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or int(row.get("active") or 0) != 1:
            continue
        brand = str(row.get("brand") or "").strip()
        slug = _slug(row.get("slug") or brand)
        about = str(row.get("about_brand") or "").strip()
        if not brand or not slug or not about or slug in seen:
            raise ValueError("active_brand_profile_invalid")
        output.append(dict(row))
        seen.add(slug)
    if not output:
        raise ValueError("active_brand_profiles_empty")
    return output


def extract_warranty_policy(html: str) -> Dict[str, List[str]]:
    """Extract structured public warranty-policy sections from one page."""

    parser = _WarrantySectionParser()
    parser.feed(str(html or ""))
    lines = parser.lines()
    if not lines:
        return {}
    output: Dict[str, List[str]] = {}
    active_key = ""
    for line in lines:
        normalized = re.sub(r"[^a-z0-9]+", " ", line.casefold()).strip()
        heading = next(
            (
                key
                for label, key in _POLICY_HEADINGS.items()
                if normalized == label
            ),
            "",
        )
        if heading:
            active_key = heading
            output.setdefault(active_key, [])
            continue
        if active_key:
            output.setdefault(active_key, []).append(line)
    return {
        key: list(dict.fromkeys(values))
        for key, values in output.items()
        if values
    }


def build_profiles(
    directory_rows: Sequence[Dict[str, Any]],
    detail_pages: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Validate and combine directory metadata with detail warranty policy."""

    profiles: List[Dict[str, Any]] = []
    for row in directory_rows:
        brand = str(row.get("brand") or "").strip()
        slug = _slug(row.get("slug") or brand)
        source_url = f"https://gulong.ph/brand/{slug}"
        if slug not in detail_pages:
            raise ValueError(f"brand_detail_missing:{slug}")
        policy = extract_warranty_policy(detail_pages[slug])
        guarantee_years = _duration_years(
            " ".join(policy.get("period") or [])
        )
        warranty_years = _positive_int(row.get("warranty_year"))
        manufacturer_warranty: Dict[str, Any] = {}
        if warranty_years:
            manufacturer_warranty = {
                "duration_years": warranty_years,
                "display": str(row.get("warranty") or "").strip()
                or f"{warranty_years} years",
                "scope": "brand_product_warranty",
                "authorized_fields": [
                    "duration_years",
                    "display",
                ],
                "unpublished_fields": [
                    "coverage",
                    "start_date",
                    "claim_conditions",
                ],
            }
        gulong_guarantee: Dict[str, Any] = {}
        if guarantee_years and policy.get("coverage"):
            gulong_guarantee = {
                "duration_years": guarantee_years,
                "scope": "gulong_unconditional_damage_warranty",
                "coverage": policy["coverage"][:2],
                "period_text": (policy.get("period") or [""])[0],
                "conditions": (policy.get("conditions") or [])[:5],
            }
        profiles.append(
            {
                "brand": brand,
                "brand_slug": slug,
                "about_brand": str(row.get("about_brand") or "").strip(),
                "origin_country": str(row.get("origin_country") or "").strip(),
                "market_segment": str(row.get("name") or "").strip(),
                "manufacturer_warranty": manufacturer_warranty,
                "gulong_guarantee": gulong_guarantee,
                "warranty_policy": policy,
                "source_updated_at": str(row.get("updated_at") or "").strip(),
                "source_urls": [DEFAULT_BRANDS_URL, source_url],
                "source_brand_id": row.get("id"),
            }
        )
    return profiles


def sync_brand_knowledge(args: argparse.Namespace) -> Dict[str, Any]:
    """Fetch, validate, embed, and atomically activate one publication."""

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Gulong-Runtime-V7-Brand-Knowledge/1.0 "
                "(source-backed customer support)"
            )
        }
    )
    directory_html = _fetch_text(
        session,
        args.brands_url,
        timeout=args.timeout_seconds,
    )
    directory = extract_brand_directory(directory_html)
    details: Dict[str, str] = {}
    for row in directory:
        slug = _slug(row.get("slug") or row.get("brand"))
        details[slug] = _fetch_text(
            session,
            f"{args.brand_base_url.rstrip('/')}/{slug}",
            timeout=args.timeout_seconds,
        )
    profiles = build_profiles(directory, details)
    canonical = json.dumps(
        profiles,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    source_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    version_id = (
        args.version_id
        or "brand-"
        + datetime.now(MANILA).strftime("%Y%m%d")
        + "-"
        + source_hash[:12]
    )

    db = firestore.Client(project=args.project_id)
    config_ref = (
        db.collection(args.config_collection)
        .document(ACTIVE_CONFIG_DOCUMENT)
    )
    previous_config = config_ref.get().to_dict() or {}
    if (
        str(previous_config.get("source_hash") or "") == source_hash
        and str(
            previous_config.get("brand_knowledge_version_id") or ""
        ).strip()
    ):
        return {
            "status": "unchanged",
            "brand_knowledge_version_id": previous_config.get(
                "brand_knowledge_version_id"
            ),
            "source_hash": source_hash,
            "brand_count": len(profiles),
        }

    embedder = VertexEmbedder(
        args.project_id,
        dimensions=args.embedding_dimensions,
        service_account_email=args.embedding_service_account or None,
    )
    materialized: List[Dict[str, Any]] = []
    chunks: List[Dict[str, Any]] = []
    for profile in profiles:
        refs = [
            f"brand_source:{source_hash[:16]}:{profile['brand_slug']}",
            *profile["source_urls"],
        ]
        materialized.append(
            {
                **profile,
                "version_id": version_id,
                "source_hash": source_hash,
                "evidence_refs": refs,
            }
        )
        narrative = _narrative_embedding_text(profile)
        chunks.append(
            {
                "chunk_id": f"{profile['brand_slug']}-background",
                "brand": profile["brand"],
                "brand_slug": profile["brand_slug"],
                "chunk_type": "brand_background",
                "text": narrative,
                "embedding": embedder.embed(
                    narrative,
                    task_type="RETRIEVAL_DOCUMENT",
                ),
                "evidence_refs": refs,
            }
        )
        warranty = _warranty_embedding_text(profile)
        if warranty:
            chunks.append(
                {
                    "chunk_id": f"{profile['brand_slug']}-warranty",
                    "brand": profile["brand"],
                    "brand_slug": profile["brand_slug"],
                    "chunk_type": "brand_warranty",
                    "text": warranty,
                    "embedding": embedder.embed(
                        warranty,
                        task_type="RETRIEVAL_DOCUMENT",
                    ),
                    "evidence_refs": refs,
                }
            )

    batch = db.batch()
    for profile in materialized:
        batch.set(
            db.collection(args.profiles_collection).document(
                f"{version_id}-{profile['brand_slug']}"
            ),
            {
                **profile,
                "status": "published",
                "enabled": True,
                "published_at": firestore.SERVER_TIMESTAMP,
            },
        )
    for chunk in chunks:
        batch.set(
            db.collection(args.chunks_collection).document(
                f"{version_id}-{chunk['chunk_id']}"
            ),
            {
                **chunk,
                "version_id": version_id,
                "source_hash": source_hash,
                "status": "published",
                "enabled": True,
                "embedding": Vector(chunk["embedding"]),
                "published_at": firestore.SERVER_TIMESTAMP,
            },
        )
    batch.set(
        db.collection(args.versions_collection).document(version_id),
        {
            "brand_knowledge_version_id": version_id,
            "schema_version": BRAND_SCHEMA_VERSION,
            "source_hash": source_hash,
            "source_urls": [
                args.brands_url,
                args.brand_base_url,
            ],
            "brand_count": len(materialized),
            "chunk_count": len(chunks),
            "embedding_dimensions": args.embedding_dimensions,
            "status": "published",
            "previous_version_id": str(
                previous_config.get("brand_knowledge_version_id") or ""
            ),
            "published_at": firestore.SERVER_TIMESTAMP,
        },
    )
    batch.set(
        config_ref,
        {
            "brand_knowledge_version_id": version_id,
            "schema_version": BRAND_SCHEMA_VERSION,
            "source_hash": source_hash,
            "brand_count": len(materialized),
            "chunk_count": len(chunks),
            "source_urls": [
                args.brands_url,
                args.brand_base_url,
            ],
            "activated_at": firestore.SERVER_TIMESTAMP,
        },
    )
    batch.commit()
    return {
        "status": "published",
        "brand_knowledge_version_id": version_id,
        "source_hash": source_hash,
        "brand_count": len(materialized),
        "chunk_count": len(chunks),
        "previous_version_id": str(
            previous_config.get("brand_knowledge_version_id") or ""
        ),
    }


def _fetch_text(
    session: requests.Session,
    url: str,
    *,
    timeout: float,
) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    text = str(response.text or "")
    if not text.strip():
        raise ValueError(f"empty_source:{url}")
    return text


def _narrative_embedding_text(profile: Dict[str, Any]) -> str:
    return " | ".join(
        value
        for value in (
            f"Brand: {profile.get('brand')}",
            f"Background: {profile.get('about_brand')}",
            f"Origin: {profile.get('origin_country')}",
            f"Market segment: {profile.get('market_segment')}",
        )
        if str(value or "").strip()
    )


def _warranty_embedding_text(profile: Dict[str, Any]) -> str:
    parts: List[str] = [f"Brand: {profile.get('brand')}"]
    manufacturer = profile.get("manufacturer_warranty") or {}
    if manufacturer:
        parts.append(
            "Product warranty: "
            + str(manufacturer.get("display") or "")
        )
    guarantee = profile.get("gulong_guarantee") or {}
    if guarantee:
        parts.append(
            "Gulong.ph unconditional damage warranty: "
            + str(guarantee.get("duration_years") or "")
            + " year"
        )
    for key, rows in (profile.get("warranty_policy") or {}).items():
        if rows:
            parts.append(
                key.replace("_", " ").title()
                + ": "
                + " ".join(str(row) for row in rows)
            )
    return " | ".join(part for part in parts if part.strip())


def _duration_years(text: str) -> int:
    match = re.search(
        r"(?:\((\d+)\)|\b(\d+)\b)\s*year",
        str(text or "").casefold(),
    )
    if not match:
        return 0
    return _positive_int(match.group(1) or match.group(2))


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _slug(value: Any) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "-",
        str(value or "").casefold(),
    ).strip("-")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-id",
        default="gulong-chatbot-459723",
    )
    parser.add_argument("--brands-url", default=DEFAULT_BRANDS_URL)
    parser.add_argument(
        "--brand-base-url",
        default="https://gulong.ph/brand",
    )
    parser.add_argument(
        "--profiles-collection",
        default=PROFILES_COLLECTION,
    )
    parser.add_argument(
        "--chunks-collection",
        default=CHUNKS_COLLECTION,
    )
    parser.add_argument(
        "--config-collection",
        default=ACTIVE_CONFIG_COLLECTION,
    )
    parser.add_argument(
        "--versions-collection",
        default="brand_knowledge_versions",
    )
    parser.add_argument(
        "--embedding-dimensions",
        type=int,
        default=768,
    )
    parser.add_argument(
        "--embedding-service-account",
        default="",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--version-id", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = sync_brand_knowledge(args)
    except Exception as exc:
        result = {
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") in {"published", "unchanged"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
