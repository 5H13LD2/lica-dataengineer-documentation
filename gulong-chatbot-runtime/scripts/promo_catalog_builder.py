"""Build a review-gated, AI-extracted promo catalog from the shared Drive folder.

The builder is intentionally separate from the Runtime V7 request path. It creates
immutable Firestore/GCS trial artifacts and never changes an active catalog pointer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import google.auth
from google.auth.transport.requests import AuthorizedSession, Request
from google.cloud import firestore, storage
from google.cloud.firestore_v1.vector import Vector

try:
    from scripts.promo_vector_trial import (
        DriveApiSource,
        DriveItem,
        VertexEmbedder,
        chunk_paragraphs,
        extract_docx_paragraphs,
        make_version_id,
        require_named_item,
        upload_bytes,
    )
except ModuleNotFoundError:  # Direct ``python scripts/promo_catalog_builder.py`` execution.
    from promo_vector_trial import (
        DriveApiSource,
        DriveItem,
        VertexEmbedder,
        chunk_paragraphs,
        extract_docx_paragraphs,
        make_version_id,
        require_named_item,
        upload_bytes,
    )


VERTEX_GENERATE_URL = (
    "https://us-central1-aiplatform.googleapis.com/v1/projects/{project_id}/"
    "locations/us-central1/publishers/google/models/{model}:generateContent"
)
PROMO_TYPES = {
    "buy_3_get_1",
    "cashback",
    "fixed_discount",
    "percent_discount",
    "event",
    "warranty",
    "other",
}
ELIGIBILITY_SCOPES = {
    "all_brand_products",
    "selected_patterns",
    "selected_sizes",
    "selected_products",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class PromoCard:
    """Validated AI extraction for one customer-visible promo."""

    promo_id: str
    title: str
    brands: list[str]
    promo_type: str
    offer_summary: str
    mechanics: list[str]
    valid_from: str
    valid_until: str
    source_evidence: list[str]
    image_source_names: list[str]
    eligibility: dict[str, Any] = field(default_factory=dict)


class GeminiCatalogExtractor:
    """Extract bounded catalog JSON from the mechanics source using Vertex Gemini."""

    def __init__(self, project_id: str, model: str) -> None:
        self._project_id = project_id
        self._model = model
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        credentials.refresh(Request())
        self._session = AuthorizedSession(credentials)

    def extract(self, source_text: str, image_names: list[str]) -> list[PromoCard]:
        """Return source-grounded promo records. The caller validates every record."""

        source_paragraphs = [line for line in source_text.splitlines() if line.strip()]
        numbered_source = "\n".join(f"[{index}] {paragraph}" for index, paragraph in enumerate(source_paragraphs, start=1))
        prompt = f"""Extract the active promotions from the source text below.
Return JSON only, using this shape:
{{"promos":[{{"title":"", "brands":[""], "promo_type":"buy_3_get_1|cashback|fixed_discount|percent_discount|event|warranty|other", "offer_summary":"", "mechanics":[""], "valid_from":"YYYY-MM-DD or empty", "valid_until":"YYYY-MM-DD or empty", "source_evidence_indices":[1], "image_source_names":["exact filename"], "eligibility":{{"scope":"all_brand_products|selected_patterns|selected_sizes|selected_products", "included_brands":[""], "excluded_brands":[], "included_patterns":[], "excluded_patterns":[], "included_sizes":["195/60R15"], "excluded_sizes":[], "qualifying_quantity":0, "free_quantity":0, "confidence":"high|medium|low", "source_evidence_indices":[1]}}}}]}}

Rules:
- Create one record per customer-visible promo, not one record per paragraph.
- Never invent a brand, amount, date, eligibility rule, or image assignment.
- source_evidence_indices must contain the numbered source paragraphs supporting the offer.
- Derive eligibility from the mechanics. Never infer an included size, pattern,
  product, brand, or quantity unless source evidence states it.
- Use all_brand_products only when the source applies the promo to the brand
  generally. Use the narrowest selected_* scope supported by the source.
- Normalize tire sizes as WIDTH/ASPECTRIM, for example 195/60R15. Keep arrays
  empty when the source does not enumerate them.
- Set eligibility confidence to low when the source is ambiguous or contradictory.
- Use an empty image_source_names array if no image can be matched confidently.
- Keep mechanics as factual, customer-facing statements only.

Available image filenames:
{json.dumps(image_names, ensure_ascii=False)}

Source text:
{numbered_source}
"""
        response = self._session.post(
            VERTEX_GENERATE_URL.format(project_id=self._project_id, model=self._model),
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            },
            timeout=120,
        )
        response.raise_for_status()
        candidates = response.json().get("candidates", [])
        if not candidates:
            raise ValueError("Gemini returned no catalog extraction candidate")
        parts = candidates[0].get("content", {}).get("parts", [])
        raw_json = "".join(str(part.get("text", "")) for part in parts).strip()
        return parse_catalog_response(
            raw_json,
            source_text=source_text,
            source_paragraphs=source_paragraphs,
            allowed_image_names=image_names,
        )


def slugify(value: str) -> str:
    """Produce a stable Firestore-safe identifier from an extracted title."""

    compact = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return compact[:80] or "promo"


def parse_catalog_response(
    raw_json: str,
    *,
    source_text: str,
    allowed_image_names: Iterable[str],
    source_paragraphs: list[str] | None = None,
) -> list[PromoCard]:
    """Validate Gemini output before it can become a Firestore catalog record."""

    payload = json.loads(raw_json)
    entries = payload.get("promos")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Gemini extraction must contain at least one promo")
    allowed_images = {name for name in allowed_image_names}
    cards: list[PromoCard] = []
    seen_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Gemini extraction contains a non-object promo")
        title = str(entry.get("title", "")).strip()
        brands = [str(value).strip() for value in entry.get("brands", []) if str(value).strip()]
        mechanics = [str(value).strip() for value in entry.get("mechanics", []) if str(value).strip()]
        evidence_indices = entry.get("source_evidence_indices", [])
        if source_paragraphs is not None and isinstance(evidence_indices, list):
            try:
                evidence = [source_paragraphs[int(value) - 1] for value in evidence_indices]
            except (IndexError, TypeError, ValueError):
                raise ValueError(f"Promo {title or '<untitled>'!r} has an invalid source evidence index") from None
        else:
            evidence = [str(value).strip() for value in entry.get("source_evidence", []) if str(value).strip()]
        image_names = [str(value).strip() for value in entry.get("image_source_names", []) if str(value).strip()]
        promo_type = str(entry.get("promo_type", "other")).strip().casefold()
        if promo_type not in PROMO_TYPES:
            promo_type = "other"
        brand_required = promo_type != "warranty"
        if not title or not mechanics or not evidence or (brand_required and not brands):
            raise ValueError(
                f"Promo {title or '<untitled>'!r} is missing title, mechanics, evidence, or a required brand"
            )
        if any(item not in source_text for item in evidence):
            raise ValueError(f"Promo {title!r} includes evidence that is not present in the source document")
        if any(item not in allowed_images for item in image_names):
            raise ValueError(f"Promo {title!r} references an unknown image filename")
        eligibility = _parse_eligibility(
            entry.get("eligibility"),
            title=title,
            promo_brands=brands,
            source_text=source_text,
            source_paragraphs=source_paragraphs,
            fallback_evidence=evidence,
        )
        base_id = slugify(title)
        promo_id = base_id
        suffix = 2
        while promo_id in seen_ids:
            promo_id = f"{base_id}-{suffix}"
            suffix += 1
        seen_ids.add(promo_id)
        cards.append(
            PromoCard(
                promo_id=promo_id,
                title=title,
                brands=brands,
                promo_type=promo_type,
                offer_summary=str(entry.get("offer_summary", "")).strip(),
                mechanics=mechanics,
                valid_from=str(entry.get("valid_from", "")).strip(),
                valid_until=str(entry.get("valid_until", "")).strip(),
                source_evidence=evidence,
                image_source_names=image_names,
                eligibility=eligibility,
            )
        )
    return preserve_source_urls(
        cards,
        source_paragraphs
        or [line for line in source_text.splitlines() if line.strip()],
    )


def preserve_source_urls(
    cards: list[PromoCard],
    source_paragraphs: list[str],
) -> list[PromoCard]:
    """Attach exact operational URLs to the promo section that contains them."""

    promo_id_by_header = {slugify(card.title): card.promo_id for card in cards}
    additions: dict[str, list[str]] = {card.promo_id: [] for card in cards}
    current_promo_id = ""
    cards_by_id = {card.promo_id: card for card in cards}
    for paragraph in source_paragraphs:
        text = str(paragraph or "").strip()
        if not text:
            continue
        if text.casefold() == "source and review notes":
            current_promo_id = ""
            continue
        header_promo_id = promo_id_by_header.get(slugify(text))
        if header_promo_id:
            current_promo_id = header_promo_id
        if not current_promo_id:
            continue
        for raw_url in re.findall(r'https?://[^\s<>"\']+', text):
            url = raw_url.rstrip(".,;:!?)]}")
            card = cards_by_id[current_promo_id]
            if any(url in mechanic for mechanic in card.mechanics):
                continue
            if any(url in mechanic for mechanic in additions[current_promo_id]):
                continue
            label = "Promo submission form" if "docs.google.com/forms/" in url else "Promo source link"
            additions[current_promo_id].append(f"{label}: {url}")
    return [
        replace(card, mechanics=[*card.mechanics, *additions[card.promo_id]])
        for card in cards
    ]


def _parse_eligibility(
    raw: Any,
    *,
    title: str,
    promo_brands: list[str],
    source_text: str,
    source_paragraphs: list[str] | None,
    fallback_evidence: list[str],
) -> dict[str, Any]:
    """Validate one AI-derived eligibility rule before review-sheet creation."""

    payload = raw if isinstance(raw, dict) else {}
    scope = str(payload.get("scope") or "all_brand_products").strip().casefold()
    if scope not in ELIGIBILITY_SCOPES:
        raise ValueError(f"Promo {title!r} has an invalid eligibility scope")
    confidence = str(payload.get("confidence") or "low").strip().casefold()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    evidence_indices = payload.get("source_evidence_indices") or []
    evidence: list[str] = []
    if source_paragraphs is not None and isinstance(evidence_indices, list):
        try:
            evidence = [source_paragraphs[int(value) - 1] for value in evidence_indices]
        except (IndexError, TypeError, ValueError):
            raise ValueError(f"Promo {title!r} has an invalid eligibility evidence index") from None
    if not evidence and not payload:
        evidence = list(fallback_evidence)
    if not evidence or any(item not in source_text for item in evidence):
        raise ValueError(f"Promo {title!r} is missing grounded eligibility evidence")

    def values(name: str) -> list[str]:
        return [str(value).strip() for value in payload.get(name) or [] if str(value).strip()]

    return {
        "scope": scope,
        "included_brands": values("included_brands") or list(promo_brands),
        "excluded_brands": values("excluded_brands"),
        "included_patterns": values("included_patterns"),
        "excluded_patterns": values("excluded_patterns"),
        "included_sizes": [_normalize_eligibility_size(value) for value in values("included_sizes")],
        "excluded_sizes": [_normalize_eligibility_size(value) for value in values("excluded_sizes")],
        "qualifying_quantity": _nonnegative_int(payload.get("qualifying_quantity")),
        "free_quantity": _nonnegative_int(payload.get("free_quantity")),
        "confidence": confidence,
        "source_evidence": evidence,
    }


def _normalize_eligibility_size(value: str) -> str:
    compact = re.sub(r"[^0-9A-Z]", "", str(value or "").upper())
    match = re.fullmatch(r"(\d{3})(\d{2})(ZR|R)(\d{2})", compact)
    if not match:
        raise ValueError(f"Invalid eligibility tire size: {value!r}")
    return f"{match.group(1)}/{match.group(2)}{match.group(3)}{match.group(4)}"


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def build_parent_text(card: PromoCard) -> str:
    """Make each promo's identity explicit to the embedding model."""

    aliases = build_retrieval_aliases(card)
    return "\n".join(
        [
            f"Promo title: {card.title}",
            f"Brands: {', '.join(card.brands)}",
            f"Promo type: {card.promo_type}",
            f"Offer: {card.offer_summary}",
            f"Valid from: {card.valid_from or 'not stated'}",
            f"Valid until: {card.valid_until or 'not stated'}",
            f"Eligibility: {json.dumps(card.eligibility, ensure_ascii=False, sort_keys=True)}",
            f"Retrieval aliases: {', '.join(aliases)}",
            "Mechanics:",
            *card.mechanics,
        ]
    )


def build_retrieval_aliases(card: PromoCard) -> list[str]:
    """Add deterministic amount and mechanic phrasing for semantic retrieval."""

    aliases = [card.title, *card.brands, card.promo_type]
    source = f"{card.title} {card.offer_summary} {' '.join(card.mechanics)}"
    for match in re.finditer(r"(?:PHP|₱)\s*([0-9][0-9,]*(?:\.[0-9]+)?)", source, flags=re.IGNORECASE):
        amount = match.group(1).replace(",", "")
        aliases.extend([f"PHP {amount}", f"{amount} pesos"])
        if amount.isdigit() and int(amount) % 1000 == 0:
            aliases.append(f"{int(amount) // 1000}K")
    if card.promo_type == "buy_3_get_1":
        aliases.extend(["3+1", "buy 3 get 1", "buy three get one", "three plus one"])
    return list(dict.fromkeys(alias for alias in aliases if alias))


def _discover_source(drive: DriveApiSource, args: argparse.Namespace) -> tuple[DriveItem, list[DriveItem], list[DriveItem]]:
    source_items = drive.list_children(args.drive_source_folder_id)
    month = require_named_item(source_items, args.month_folder_name)
    month_items = drive.list_children(month.file_id)
    images_folder = require_named_item(month_items, args.images_folder_name)
    mechanics_folder = require_named_item(month_items, args.mechanics_folder_name)
    images = [item for item in drive.list_children(images_folder.file_id) if Path(item.name).suffix.casefold() in IMAGE_SUFFIXES]
    mechanics = drive.list_children(mechanics_folder.file_id)
    docx = next((item for item in mechanics if item.name.casefold().endswith(".docx")), None)
    if docx is None:
        raise ValueError("No .docx mechanics file found in the mechanics folder")
    return docx, images, mechanics


def run_builder(args: argparse.Namespace) -> dict[str, Any]:
    """Build a pending-review catalog version from Drive without publishing it."""

    started = time.perf_counter()
    version_id = args.version_id or make_version_id().replace("trial-", "catalog-")
    drive = DriveApiSource(service_account_email=args.drive_service_account)
    mechanics_file, image_items, _ = _discover_source(drive, args)
    mechanics_docx = drive.download(mechanics_file)
    source_text = "\n".join(extract_docx_paragraphs(mechanics_docx))
    extractor = GeminiCatalogExtractor(args.project_id, args.extractor_model)
    cards = extractor.extract(source_text, [item.name for item in image_items])

    storage_client = storage.Client(project=args.project_id)
    bucket = storage_client.bucket(args.bucket)
    prefix = f"promo_catalog/builds/{version_id}"
    image_uris: dict[str, str] = {}
    for image in image_items:
        suffix = Path(image.name).suffix.casefold()
        content_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}[suffix]
        image_uris[image.name] = upload_bytes(bucket, f"{prefix}/source/images/{image.file_id}{suffix}", drive.download(image), content_type)
    artifact_uris = {
        "mechanics_docx": upload_bytes(bucket, f"{prefix}/source/{quote(mechanics_file.name)}", mechanics_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "mechanics_text": upload_bytes(bucket, f"{prefix}/parsed/mechanics.txt", source_text.encode("utf-8"), "text/plain; charset=utf-8"),
    }

    firestore_client = firestore.Client(project=args.project_id)
    embedder = VertexEmbedder(args.project_id, dimensions=args.embedding_dimensions)
    cards_collection = firestore_client.collection(args.cards_collection)
    chunks_collection = firestore_client.collection(args.chunks_collection)
    version_document = firestore_client.collection(args.versions_collection).document(version_id)
    batch = firestore_client.batch()
    chunk_count = 0
    for card in cards:
        parent_text = build_parent_text(card)
        card_id = f"{version_id}-{card.promo_id}"
        batch.set(
            cards_collection.document(card_id),
            {
                "catalog_version_id": version_id,
                "promo_id": card.promo_id,
                "title": card.title,
                "brands": card.brands,
                "promo_type": card.promo_type,
                "offer_summary": card.offer_summary,
                "valid_from": card.valid_from,
                "valid_until": card.valid_until,
                "source_evidence": card.source_evidence,
                "image_uris": [image_uris[name] for name in card.image_source_names],
                "embedding": Vector(embedder.embed(parent_text, task_type="RETRIEVAL_DOCUMENT")),
                "source_gcs_uri": artifact_uris["mechanics_text"],
                "created_at": firestore.SERVER_TIMESTAMP,
            },
        )
        mechanics_chunks = chunk_paragraphs(parent_text.splitlines(), max_characters=args.chunk_characters, overlap_characters=args.chunk_overlap)
        for chunk in mechanics_chunks:
            chunk_count += 1
            chunk_id = f"{card_id}-{chunk.chunk_id}"
            batch.set(
                chunks_collection.document(chunk_id),
                {
                    "catalog_version_id": version_id,
                    "promo_id": card.promo_id,
                    "card_id": card_id,
                    "chunk_id": chunk.chunk_id,
                    "text": chunk.text,
                    "content_hash": chunk.content_hash,
                    "embedding": Vector(embedder.embed(chunk.text, task_type="RETRIEVAL_DOCUMENT")),
                    "source_gcs_uri": artifact_uris["mechanics_text"],
                    "created_at": firestore.SERVER_TIMESTAMP,
                },
            )
    batch.set(
        version_document,
        {
            "catalog_version_id": version_id,
            "status": "pending_review",
            "source_drive_folder_id": args.drive_source_folder_id,
            "month_folder_name": args.month_folder_name,
            "source_file_id": mechanics_file.file_id,
            "source_content_hash": hashlib.sha256(mechanics_docx).hexdigest(),
            "cards_collection": args.cards_collection,
            "chunks_collection": args.chunks_collection,
            "card_count": len(cards),
            "chunk_count": chunk_count,
            "embedding_dimensions": args.embedding_dimensions,
            "created_at": firestore.SERVER_TIMESTAMP,
        },
    )
    batch.commit()
    manifest = {
        "version_id": version_id,
        "status": "pending_review",
        "source_file": asdict(mechanics_file),
        "artifacts": artifact_uris,
        "images": image_uris,
        "cards": [asdict(card) for card in cards],
        "card_count": len(cards),
        "chunk_count": chunk_count,
    }
    artifact_uris["manifest"] = upload_bytes(bucket, f"{prefix}/catalog/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"), "application/json; charset=utf-8")
    return {
        "status": "success",
        "version_id": version_id,
        "version_status": "pending_review",
        "card_count": len(cards),
        "chunk_count": chunk_count,
        "artifact_uris": artifact_uris,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default="gulong-chatbot-459723")
    parser.add_argument("--bucket", default="lica-gulong-chatbot-embeddings")
    parser.add_argument("--drive-source-folder-id", default="18s3IRvGJ52Zbcnqibyiz9I7VlMKDi-GD")
    parser.add_argument("--drive-service-account", default="promo-catalog-bot@gulong-chatbot-459723.iam.gserviceaccount.com")
    parser.add_argument("--month-folder-name", default="2026-07")
    parser.add_argument("--images-folder-name", default="Promo Images")
    parser.add_argument("--mechanics-folder-name", default="Promo Mechanics")
    parser.add_argument("--extractor-model", default="gemini-2.5-flash")
    parser.add_argument("--cards-collection", default="promo_catalog_cards_trial")
    parser.add_argument("--chunks-collection", default="promo_catalog_mechanics_trial")
    parser.add_argument("--versions-collection", default="promo_catalog_versions_trial")
    parser.add_argument("--embedding-dimensions", type=int, default=768)
    parser.add_argument("--chunk-characters", type=int, default=900)
    parser.add_argument("--chunk-overlap", type=int, default=120)
    parser.add_argument("--version-id")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = run_builder(args)
    except Exception as exc:
        result = {"status": "error", "error_type": type(exc).__name__, "error": str(exc)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output.as_posix())
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
