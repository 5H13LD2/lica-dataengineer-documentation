"""Run an isolated Drive-to-GCS-to-Firestore promo mechanics vector-search trial.

This script is deliberately separate from the live Runtime V7 request path. It
uses the dedicated promo service account and Google Drive API for source reads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import quote
from xml.etree import ElementTree

import google.auth
from google.auth.transport.requests import AuthorizedSession, Request
from google.auth import impersonated_credentials
from google.cloud import firestore, storage
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from google.cloud.firestore_v1.vector import Vector


DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_FILE_URL = "https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
GOOGLE_DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
VERTEX_EMBEDDING_URL = (
    "https://us-central1-aiplatform.googleapis.com/v1/projects/{project_id}/"
    "locations/us-central1/publishers/google/models/gemini-embedding-001:predict"
)
@dataclass(frozen=True)
class DriveItem:
    """A file or folder returned by the Google Drive API."""

    file_id: str
    name: str
    mime_type: str


@dataclass(frozen=True)
class MechanicsChunk:
    """A bounded mechanics passage prepared for retrieval."""

    chunk_id: str
    ordinal: int
    text: str
    content_hash: str


class DriveApiSource:
    """Read Drive source files through the dedicated promo service account."""

    def __init__(self, *, service_account_email: str) -> None:
        source_credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        drive_credentials = impersonated_credentials.Credentials(
            source_credentials=source_credentials,
            target_principal=service_account_email,
            target_scopes=["https://www.googleapis.com/auth/drive.readonly"],
            lifetime=3600,
        )
        self._session = AuthorizedSession(drive_credentials)

    def list_children(self, folder_id: str) -> list[DriveItem]:
        """List direct children while retaining mime types needed by the builder."""

        response = self._session.get(
            DRIVE_FILES_URL,
            params={
                "q": f"'{folder_id}' in parents and trashed = false",
                "fields": "files(id,name,mimeType)",
                "orderBy": "folder,name",
                "pageSize": 1000,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            },
            timeout=30,
        )
        response.raise_for_status()
        return [
            DriveItem(file_id=item["id"], name=item["name"], mime_type=item.get("mimeType", ""))
            for item in response.json().get("files", [])
        ]

    def download(self, item: DriveItem) -> bytes:
        """Download a binary source file. Google Docs require a separate exporter."""

        response = self._session.get(DRIVE_FILE_URL.format(file_id=item.file_id), timeout=60)
        response.raise_for_status()
        return response.content


def require_named_item(items: Iterable[DriveItem], name: str) -> DriveItem:
    """Return one exact-name Drive item or fail with the visible alternatives."""

    expected = name.casefold()
    for item in items:
        if item.name.casefold() == expected:
            return item
    names = ", ".join(item.name for item in items)
    raise ValueError(f"Missing Drive item {name!r}. Found: {names or '(none)'}")


def extract_docx_paragraphs(payload: bytes) -> list[str]:
    """Extract non-empty Word paragraphs without depending on python-docx."""

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(document_xml)
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace)).strip()
        if text:
            paragraphs.append(repair_mojibake(text))
    return paragraphs


def repair_mojibake(text: str) -> str:
    """Repair common UTF-8 text that was previously decoded as Windows-1252."""

    if not any(marker in text for marker in ("â", "Ã", "â€")):
        return text
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except UnicodeError:
        return text
    return repaired if repaired != text else text


def chunk_paragraphs(paragraphs: Sequence[str], *, max_characters: int = 1100, overlap_characters: int = 180) -> list[MechanicsChunk]:
    """Create deterministic, overlapping chunks while preserving paragraph boundaries."""

    if max_characters <= overlap_characters:
        raise ValueError("max_characters must be greater than overlap_characters")
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n{paragraph}"
        if current and len(candidate) > max_characters:
            chunks.append(current)
            current = f"{current[-overlap_characters:]}\n{paragraph}".strip()
        else:
            current = candidate
    if current:
        chunks.append(current)
    return [
        MechanicsChunk(
            chunk_id=f"chunk-{ordinal:03d}",
            ordinal=ordinal,
            text=text,
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
        for ordinal, text in enumerate(chunks, start=1)
    ]


def make_version_id() -> str:
    """Return an immutable, lexically sortable trial version identifier."""

    return datetime.now(timezone.utc).strftime("trial-%Y%m%dT%H%M%SZ")


class VertexEmbedder:
    """Small Vertex REST client using Application Default Credentials."""

    def __init__(
        self,
        project_id: str,
        *,
        dimensions: int = 768,
        service_account_email: str = "",
    ) -> None:
        self._project_id = project_id
        self._dimensions = dimensions
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        target_principal = str(service_account_email or "").strip()
        if target_principal:
            credentials = impersonated_credentials.Credentials(
                source_credentials=credentials,
                target_principal=target_principal,
                target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
                lifetime=3600,
            )
        credentials.refresh(Request())
        self._session = AuthorizedSession(credentials)

    def embed(self, text: str, *, task_type: str) -> list[float]:
        """Embed one bounded text value with an explicit retrieval task type."""

        response = self._session.post(
            VERTEX_EMBEDDING_URL.format(project_id=self._project_id),
            json={
                "instances": [{"content": text, "task_type": task_type}],
                "parameters": {"autoTruncate": False, "outputDimensionality": self._dimensions},
            },
            timeout=45,
        )
        response.raise_for_status()
        values = response.json()["predictions"][0]["embeddings"]["values"]
        if len(values) != self._dimensions:
            raise RuntimeError(f"Expected {self._dimensions} embedding dimensions, received {len(values)}")
        return [float(value) for value in values]


def upload_bytes(bucket: storage.Bucket, object_name: str, payload: bytes, content_type: str) -> str:
    """Upload one immutable build artifact and return its GCS URI."""

    blob = bucket.blob(object_name)
    blob.upload_from_string(payload, content_type=content_type)
    return f"gs://{bucket.name}/{object_name}"


def run_trial(args: argparse.Namespace) -> dict[str, Any]:
    """Run source discovery, artifact persistence, vector indexing, and retrieval."""

    run_started = time.perf_counter()
    version_id = args.version_id or make_version_id()
    drive_source = DriveApiSource(service_account_email=args.drive_service_account)
    source_items = drive_source.list_children(args.drive_source_folder_id)
    month_folder = require_named_item(source_items, args.month_folder_name)
    month_items = drive_source.list_children(month_folder.file_id)
    images_folder = require_named_item(month_items, args.images_folder_name)
    mechanics_folder = require_named_item(month_items, args.mechanics_folder_name)
    image_items = [item for item in drive_source.list_children(images_folder.file_id) if Path(item.name).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
    mechanics_items = drive_source.list_children(mechanics_folder.file_id)
    mechanics_file = next((item for item in mechanics_items if item.name.lower().endswith(".docx")), None)
    if mechanics_file is None:
        raise ValueError("No .docx mechanics file found in the Mechanics folder")

    mechanics_docx = drive_source.download(mechanics_file)
    paragraphs = extract_docx_paragraphs(mechanics_docx)
    mechanics_text = "\n".join(paragraphs)
    chunks = chunk_paragraphs(paragraphs)

    storage_client = storage.Client(project=args.project_id)
    bucket = storage_client.bucket(args.bucket)
    prefix = f"promo_catalog/trials/{version_id}"
    artifact_uris = {
        "mechanics_docx": upload_bytes(bucket, f"{prefix}/source/{quote(mechanics_file.name)}", mechanics_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "mechanics_text": upload_bytes(bucket, f"{prefix}/parsed/mechanics.txt", mechanics_text.encode("utf-8"), "text/plain; charset=utf-8"),
    }
    uploaded_images: list[dict[str, str]] = []
    for image_item in image_items:
        image_bytes = drive_source.download(image_item)
        suffix = Path(image_item.name).suffix.lower()
        content_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}[suffix]
        uploaded_images.append(
            {
                "source_name": image_item.name,
                "source_file_id": image_item.file_id,
                "gcs_uri": upload_bytes(bucket, f"{prefix}/source/images/{image_item.file_id}{suffix}", image_bytes, content_type),
            }
        )

    manifest = {
        "version_id": version_id,
        "source_drive_folder_id": args.drive_source_folder_id,
        "month_folder": args.month_folder_name,
        "mechanics_file": asdict(mechanics_file),
        "image_count": len(uploaded_images),
        "mechanics_chunks": [asdict(chunk) | {"text": chunk.text} for chunk in chunks],
        "artifacts": artifact_uris,
        "images": uploaded_images,
    }
    artifact_uris["manifest"] = upload_bytes(
        bucket,
        f"{prefix}/catalog/manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        "application/json; charset=utf-8",
    )

    embedder = VertexEmbedder(args.project_id, dimensions=args.embedding_dimensions)
    firestore_client = firestore.Client(project=args.project_id)
    collection = firestore_client.collection(args.collection)
    batch = firestore_client.batch()
    embedded_chunks: list[dict[str, Any]] = []
    for chunk in chunks:
        vector = embedder.embed(chunk.text, task_type="RETRIEVAL_DOCUMENT")
        document_id = f"{version_id}-{chunk.chunk_id}"
        batch.set(
            collection.document(document_id),
            {
                "catalog_version_id": version_id,
                "chunk_id": chunk.chunk_id,
                "ordinal": chunk.ordinal,
                "text": chunk.text,
                "content_hash": chunk.content_hash,
                "embedding": Vector(vector),
                "source_gcs_uri": artifact_uris["mechanics_text"],
                "created_at": firestore.SERVER_TIMESTAMP,
            },
        )
        embedded_chunks.append({"document_id": document_id, "chunk_id": chunk.chunk_id, "dimensions": len(vector)})
    batch.commit()

    query_vector = embedder.embed(args.query, task_type="RETRIEVAL_QUERY")
    vector_query = collection.where(filter=FieldFilter("catalog_version_id", "==", version_id)).find_nearest(
        vector_field="embedding",
        query_vector=Vector(query_vector),
        distance_measure=DistanceMeasure.COSINE,
        limit=args.top_k,
        distance_result_field="vector_distance",
    )
    results = [
        {
            "document_id": document.id,
            "chunk_id": document.get("chunk_id"),
            "distance": document.get("vector_distance"),
            "text": document.get("text"),
        }
        for document in vector_query.stream()
    ]
    return {
        "status": "success",
        "version_id": version_id,
        "collection": args.collection,
        "bucket": args.bucket,
        "artifact_uris": artifact_uris,
        "uploaded_image_count": len(uploaded_images),
        "mechanics_paragraph_count": len(paragraphs),
        "embedded_chunk_count": len(embedded_chunks),
        "embedding_dimensions": args.embedding_dimensions,
        "query": args.query,
        "results": results,
        "latency_ms": int((time.perf_counter() - run_started) * 1000),
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
    parser.add_argument("--collection", default="promo_mechanics_chunks_trial")
    parser.add_argument("--embedding-dimensions", type=int, default=768)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--version-id")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = run_trial(args)
    except Exception as exc:
        result = {"status": "error", "error_type": type(exc).__name__, "error": str(exc)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output.as_posix())
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
