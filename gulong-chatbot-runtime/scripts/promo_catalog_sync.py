"""Build, review, publish, and roll back the production promo catalog.

The hourly Cloud Run Job runs ``sync``. It creates an immutable pending build
only when the current Manila-month Drive source hash changes, generates a Google
Sheet for human review, and publishes any pending sheet marked APPROVED after
all validation checks pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote
from zoneinfo import ZoneInfo

import google.auth
from google.auth import impersonated_credentials
from google.auth.transport.requests import AuthorizedSession
from google.cloud import firestore, storage
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.vector import Vector
from google.oauth2.credentials import Credentials as AuthorizedUserCredentials

from runtime_v7.promo_catalog import (
    build_promo_click_token,
    is_targeted_promo_query,
    promo_candidate_matches_explicit_constraints,
    rerank_promo_candidates,
)
from scripts.promo_catalog_builder import (
    GeminiCatalogExtractor,
    PromoCard,
    build_parent_text,
    build_retrieval_aliases,
)
from scripts.promo_vector_trial import (
    DriveApiSource,
    DriveItem,
    VertexEmbedder,
    extract_docx_paragraphs,
    require_named_item,
    upload_bytes,
)


MANILA = ZoneInfo("Asia/Manila")
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE_FILES_API = "https://www.googleapis.com/drive/v3/files"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
PUBLIC_CACHE_CONTROL = "public,max-age=31536000,immutable"
CATALOG_SCHEMA_VERSION = 2
# Increment when publication-only behavior changes while the reviewed Drive
# source and catalog schema remain stable. This creates a new immutable review
# candidate without pretending Marketing changed the source evidence.
CATALOG_PUBLICATION_REVISION = 2
REVIEW_TABS = ("Version", "Promos", "Cards", "Mechanics", "Eligibility", "Brand Profiles", "Evaluation")
REVIEW_TAB_LABELS = {
    "Version": "APPROVAL - START HERE",
    "Promos": "Promos",
    "Cards": "Cards",
    "Mechanics": "Mechanics",
    "Eligibility": "Eligibility",
    "Brand Profiles": "Brand Profiles",
    "Evaluation": "Evaluation",
}
REVIEW_SCOPES = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
)
EVALUATION_NEGATIVE_BRANDS = (
    "Bridgestone",
    "Continental",
    "Dunlop",
    "Goodyear",
    "Toyo",
    "Yokohama",
)


@dataclass(frozen=True)
class RetrievalEvaluation:
    """One source-derived retrieval gate for a pending catalog version."""

    evaluation_id: str
    query: str
    expected: str
    rule: str
    target_promo_ids: tuple[str, ...] = ()
    negative_brand: str = ""


@dataclass(frozen=True)
class SourceImage:
    item: DriveItem
    payload: bytes
    sha256: str
    content_type: str


@dataclass(frozen=True)
class SourceBundle:
    month_name: str
    mechanics_item: DriveItem
    mechanics_payload: bytes
    mechanics_text: str
    images: tuple[SourceImage, ...]
    source_hash: str


class GoogleReviewSheetClient:
    """Small Sheets/Drive REST client using the promo service account."""

    def __init__(self, service_account_email: str, authorized_user_json: str = "") -> None:
        credentials = _review_credentials(service_account_email, authorized_user_json)
        self._session = AuthorizedSession(credentials)

    def create_review_sheet(
        self,
        *,
        title: str,
        review_folder_id: str,
        tab_rows: Dict[str, Sequence[Sequence[Any]]],
        spreadsheet_id: str = "",
        archive_prefix: str = "",
        month_name: str = "",
        archive_month_name: str = "",
    ) -> Dict[str, str]:
        """Create or refresh one review workbook scoped to one catalog month."""

        tab_titles = _review_tab_titles(month_name)
        spreadsheet_id = str(spreadsheet_id or "").strip()
        if spreadsheet_id:
            payload = self._prepare_existing_review_sheet(
                spreadsheet_id=spreadsheet_id,
                review_folder_id=review_folder_id,
                archive_prefix=archive_prefix,
                tab_titles=tab_titles,
                archive_tab_titles=_review_tab_titles(archive_month_name),
            )
        else:
            response = self._session.post(
                SHEETS_API,
                json={
                    "properties": {"title": title, "locale": "en_US", "timeZone": "Asia/Manila"},
                    "sheets": [
                        {"properties": {"title": tab_titles[tab]}}
                        for tab in REVIEW_TABS
                    ],
                },
                timeout=60,
            )
            _require_google_api_success(response, "create review spreadsheet")
            payload = response.json()
            spreadsheet_id = str(payload["spreadsheetId"])
        values = [
            {
                "range": f"'{tab_titles[tab]}'!A1",
                "majorDimension": "ROWS",
                "values": [list(row) for row in tab_rows[tab]],
            }
            for tab in REVIEW_TABS
        ]
        write = self._session.post(
            f"{SHEETS_API}/{spreadsheet_id}/values:batchUpdate",
            json={"valueInputOption": "RAW", "data": values},
            timeout=60,
        )
        _require_google_api_success(write, "populate review spreadsheet")
        format_requests: List[Dict[str, Any]] = []
        sheet_ids_by_title = {
            str((sheet.get("properties") or {}).get("title") or ""): (sheet.get("properties") or {}).get("sheetId")
            for sheet in payload.get("sheets") or []
        }
        for logical_tab in reversed(REVIEW_TABS):
            sheet_id = sheet_ids_by_title.get(tab_titles[logical_tab])
            if sheet_id is None:
                continue
            properties: Dict[str, Any] = {
                "sheetId": sheet_id,
                "index": 0,
                "hidden": False,
            }
            fields = "index,hidden"
            if logical_tab == "Version":
                properties["tabColorStyle"] = {
                    "rgbColor": {"red": 0.95, "green": 0.62, "blue": 0.12}
                }
                fields += ",tabColorStyle"
            format_requests.append(
                {
                    "updateSheetProperties": {
                        "properties": properties,
                        "fields": fields,
                    }
                }
            )
        for sheet in payload.get("sheets") or []:
            properties = sheet.get("properties") or {}
            if str(properties.get("title") or "") not in set(tab_titles.values()):
                continue
            sheet_id = properties.get("sheetId")
            if sheet_id is None:
                continue
            format_requests.extend(
                [
                    {
                        "updateSheetProperties": {
                            "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                            "fields": "gridProperties.frozenRowCount",
                        }
                    },
                    {
                        "repeatCell": {
                            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": {"red": 0.20, "green": 0.31, "blue": 0.25},
                                    "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                                    "wrapStrategy": "WRAP",
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat,wrapStrategy)",
                        }
                    },
                    {
                        "autoResizeDimensions": {
                            "dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 24}
                        }
                    },
                ]
            )
        formatted = self._session.post(
            f"{SHEETS_API}/{spreadsheet_id}:batchUpdate",
            json={"requests": format_requests},
            timeout=60,
        )
        _require_google_api_success(formatted, "format review spreadsheet")
        if not str(spreadsheet_id or "").strip():
            raise RuntimeError("Review spreadsheet creation returned no spreadsheet ID")
        if not self._is_in_review_folder(spreadsheet_id, review_folder_id):
            move = self._session.patch(
                f"{DRIVE_FILES_API}/{spreadsheet_id}",
                params={"addParents": review_folder_id, "removeParents": "root", "fields": "id,parents", "supportsAllDrives": "true"},
                json={},
                timeout=30,
            )
            _require_google_api_success(move, "move review spreadsheet")
        return {
            "spreadsheet_id": spreadsheet_id,
            "review_spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
        }

    def _prepare_existing_review_sheet(
        self,
        *,
        spreadsheet_id: str,
        review_folder_id: str,
        archive_prefix: str = "",
        tab_titles: Optional[Dict[str, str]] = None,
        archive_tab_titles: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Prepare one month's workbook and preserve its prior version tabs."""

        if not self._is_in_review_folder(spreadsheet_id, review_folder_id, require_edit=True):
            raise ValueError("Bootstrap review spreadsheet must be inside the configured review folder")
        payload = self._read_spreadsheet_metadata(spreadsheet_id)
        sheet_properties = [dict(sheet.get("properties") or {}) for sheet in payload.get("sheets") or []]
        existing_titles = {str(properties.get("title") or "") for properties in sheet_properties}
        tab_titles = dict(tab_titles or _review_tab_titles(""))
        archive_tab_titles = dict(archive_tab_titles or _review_tab_titles(""))
        prepare_requests: List[Dict[str, Any]] = [
            {
                "updateSpreadsheetProperties": {
                    "properties": {"locale": "en_US", "timeZone": "Asia/Manila"},
                    "fields": "locale,timeZone",
                }
            }
        ]
        archive_hide_sheet_ids: List[int] = []
        archive_prefix = _safe_sheet_archive_prefix(archive_prefix)
        if archive_prefix:
            archived_titles = {f"{archive_prefix} {tab}" for tab in REVIEW_TABS}
            archive_already_exists = bool(existing_titles & archived_titles)
            if not archive_already_exists:
                for properties in sheet_properties:
                    current_title = str(properties.get("title") or "")
                    logical_tab = next(
                        (
                            tab
                            for tab in REVIEW_TABS
                            if current_title in {tab, archive_tab_titles[tab]}
                        ),
                        "",
                    )
                    if not logical_tab:
                        continue
                    archived_title = f"{archive_prefix} {logical_tab}"
                    prepare_requests.append(
                        {
                            "updateSheetProperties": {
                                "properties": {
                                    "sheetId": properties["sheetId"],
                                    "title": archived_title,
                                },
                                "fields": "title",
                            }
                        }
                    )
                    archive_hide_sheet_ids.append(int(properties["sheetId"]))
                    existing_titles.discard(current_title)
                    existing_titles.add(archived_title)
        approval_title = tab_titles["Version"]
        if approval_title not in existing_titles:
            default_sheet = next(
                (properties for properties in sheet_properties if properties.get("title") == "Sheet1"),
                None,
            )
            if default_sheet is not None:
                prepare_requests.append(
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": default_sheet["sheetId"],
                                "title": approval_title,
                                "hidden": False,
                            },
                            "fields": "title,hidden",
                        }
                    }
                )
                existing_titles.discard("Sheet1")
                existing_titles.add(approval_title)
        missing_tabs = [tab for tab in REVIEW_TABS if tab_titles[tab] not in existing_titles]
        prepare_requests.extend(
            {"addSheet": {"properties": {"title": tab_titles[tab]}}}
            for tab in missing_tabs
        )
        prepared = self._session.post(
            f"{SHEETS_API}/{spreadsheet_id}:batchUpdate",
            json={"requests": prepare_requests},
            timeout=60,
        )
        _require_google_api_success(prepared, "prepare bootstrap review spreadsheet")
        if archive_hide_sheet_ids:
            hidden = self._session.post(
                f"{SHEETS_API}/{spreadsheet_id}:batchUpdate",
                json={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {"sheetId": sheet_id, "hidden": True},
                                "fields": "hidden",
                            }
                        }
                        for sheet_id in archive_hide_sheet_ids
                    ]
                },
                timeout=60,
            )
            _require_google_api_success(hidden, "hide archived review spreadsheet tabs")
        payload = self._read_spreadsheet_metadata(spreadsheet_id)
        cleared = self._session.post(
            f"{SHEETS_API}/{spreadsheet_id}/values:batchClear",
            json={"ranges": [f"'{tab_titles[tab]}'!A:Z" for tab in REVIEW_TABS]},
            timeout=60,
        )
        _require_google_api_success(cleared, "clear bootstrap review spreadsheet")
        return payload

    def _read_spreadsheet_metadata(self, spreadsheet_id: str) -> Dict[str, Any]:
        response = self._session.get(
            f"{SHEETS_API}/{spreadsheet_id}",
            params={"fields": "spreadsheetId,properties,sheets.properties"},
            timeout=60,
        )
        _require_google_api_success(response, "read review spreadsheet metadata")
        return dict(response.json())

    def _is_in_review_folder(
        self,
        spreadsheet_id: str,
        review_folder_id: str,
        *,
        require_edit: bool = False,
    ) -> bool:
        response = self._session.get(
            f"{DRIVE_FILES_API}/{spreadsheet_id}",
            params={
                "fields": "id,mimeType,parents,capabilities(canEdit)",
                "supportsAllDrives": "true",
            },
            timeout=30,
        )
        _require_google_api_success(response, "read review spreadsheet Drive metadata")
        metadata = response.json()
        if metadata.get("mimeType") != "application/vnd.google-apps.spreadsheet":
            raise ValueError("Configured review file is not a Google Sheet")
        if require_edit and not bool((metadata.get("capabilities") or {}).get("canEdit")):
            raise ValueError("Promo catalog credential cannot edit the bootstrap review spreadsheet")
        return review_folder_id in set(metadata.get("parents") or [])

    def read_review_sheet(self, spreadsheet_id: str, month_name: str = "") -> Dict[str, List[List[str]]]:
        """Return all review tabs as string rows."""

        tab_titles = _review_tab_titles(month_name)
        response = self._session.get(
            f"{SHEETS_API}/{spreadsheet_id}/values:batchGet",
            params=[("ranges", f"'{tab_titles[tab]}'!A:Z") for tab in REVIEW_TABS],
            timeout=60,
        )
        _require_google_api_success(response, "read review spreadsheet")
        output: Dict[str, List[List[str]]] = {}
        for tab, value_range in zip(REVIEW_TABS, response.json().get("valueRanges") or []):
            output[tab] = [[str(value) for value in row] for row in value_range.get("values") or []]
        return output


def discover_source_bundle(args: argparse.Namespace) -> SourceBundle:
    """Download and hash the current Manila-month mechanics and poster files."""

    drive = DriveApiSource(service_account_email=args.drive_service_account)
    source_children = drive.list_children(args.drive_source_folder_id)
    month_name = args.month_folder_name or datetime.now(MANILA).strftime("%Y-%m")
    child_names = {item.name.casefold() for item in source_children}
    direct_month_source = {
        args.images_folder_name.casefold(),
        args.mechanics_folder_name.casefold(),
    }.issubset(child_names)
    if direct_month_source:
        month_children = source_children
    else:
        month_folder = require_named_item(source_children, month_name)
        month_children = drive.list_children(month_folder.file_id)
    images_folder = require_named_item(month_children, args.images_folder_name)
    mechanics_folder = require_named_item(month_children, args.mechanics_folder_name)
    mechanics_items = drive.list_children(mechanics_folder.file_id)
    mechanics_item = next((item for item in mechanics_items if item.name.casefold().endswith(".docx")), None)
    if mechanics_item is None:
        raise ValueError("No .docx mechanics file found in the current month folder")
    mechanics_payload = drive.download(mechanics_item)
    mechanics_text = "\n".join(extract_docx_paragraphs(mechanics_payload))
    image_items = sorted(
        [item for item in drive.list_children(images_folder.file_id) if Path(item.name).suffix.casefold() in IMAGE_SUFFIXES],
        key=lambda item: (item.name.casefold(), item.file_id),
    )
    images = []
    for item in image_items:
        payload = drive.download(item)
        suffix = Path(item.name).suffix.casefold()
        images.append(
            SourceImage(
                item=item,
                payload=payload,
                sha256=hashlib.sha256(payload).hexdigest(),
                content_type={".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}[suffix],
            )
        )
    digest = hashlib.sha256()
    digest.update(month_name.encode("utf-8"))
    digest.update(mechanics_item.file_id.encode("utf-8"))
    digest.update(mechanics_payload)
    for image in images:
        digest.update(image.item.file_id.encode("utf-8"))
        digest.update(image.item.name.encode("utf-8"))
        digest.update(image.payload)
    return SourceBundle(
        month_name=month_name,
        mechanics_item=mechanics_item,
        mechanics_payload=mechanics_payload,
        mechanics_text=mechanics_text,
        images=tuple(images),
        source_hash=digest.hexdigest(),
    )


def build_pending_version(args: argparse.Namespace, bundle: SourceBundle) -> Dict[str, Any]:
    """Create immutable private artifacts, pending Firestore rows, and review Sheet."""

    started = time.perf_counter()
    db = firestore.Client(project=args.project_id)
    existing = _version_for_source_hash(
        db,
        args.versions_collection,
        bundle.source_hash,
        schema_version=CATALOG_SCHEMA_VERSION,
        publication_revision=CATALOG_PUBLICATION_REVISION,
    )
    if _existing_version_is_complete(existing):
        return {
            "status": "unchanged",
            "version_id": existing.get("catalog_version_id"),
            "source_hash": bundle.source_hash,
            "version_status": existing.get("status"),
            "review_spreadsheet_url": existing.get("review_spreadsheet_url"),
        }

    version_id = (
        args.version_id
        or str(existing.get("catalog_version_id") or "").strip()
        or (
            f"catalog-{bundle.month_name.replace('-', '')}-{bundle.source_hash[:12]}"
            f"-v{CATALOG_SCHEMA_VERSION}-p{CATALOG_PUBLICATION_REVISION}"
        )
    )
    review_spreadsheet_id = str(args.review_spreadsheet_id or "").strip()
    if not review_spreadsheet_id:
        review_spreadsheet_id = _monthly_review_spreadsheet_id(
            db,
            args.versions_collection,
            bundle.month_name,
        )
    archived_review_version: Dict[str, Any] = {}
    if review_spreadsheet_id:
        spreadsheet_versions = _versions_for_spreadsheet_id(
            db,
            args.versions_collection,
            review_spreadsheet_id,
        )
        _require_review_spreadsheet_month(spreadsheet_versions, bundle.month_name)
        reusable_versions = [
            item
            for item in spreadsheet_versions
            if str(item.get("catalog_version_id") or "") != version_id
            and not item.get("review_sheet_archived_at")
        ]
        blocked_versions = [
            item
            for item in reusable_versions
            if str(item.get("status") or "") not in {"published", "superseded", "rolled_back"}
        ]
        if blocked_versions:
            raise ValueError(
                "Review spreadsheet has an unfinished catalog version: "
                f"{blocked_versions[0].get('catalog_version_id')!r}"
            )
        if len(reusable_versions) > 1:
            raise ValueError("Review spreadsheet has multiple unarchived catalog versions")
        if reusable_versions:
            archived_review_version = reusable_versions[0]
    extractor = GeminiCatalogExtractor(args.project_id, args.extractor_model)
    promo_cards = extractor.extract(bundle.mechanics_text, [image.item.name for image in bundle.images])
    promo_cards, carried_forward_version_id, carried_forward_count = _carry_forward_published_review(
        db=db,
        versions_collection=args.versions_collection,
        cards_collection=args.cards_collection,
        mechanics_collection=args.mechanics_collection,
        source_hash=bundle.source_hash,
        extracted_promos=promo_cards,
        target_version_id=version_id,
    )
    bucket = storage.Client(project=args.project_id).bucket(args.private_bucket)
    prefix = f"promo_catalog/builds/{version_id}"
    mechanics_text_uri = upload_bytes(
        bucket,
        f"{prefix}/parsed/mechanics.txt",
        bundle.mechanics_text.encode("utf-8"),
        "text/plain; charset=utf-8",
    )
    mechanics_docx_uri = upload_bytes(
        bucket,
        f"{prefix}/source/{quote(bundle.mechanics_item.name)}",
        bundle.mechanics_payload,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    image_manifest: Dict[str, Dict[str, Any]] = {}
    for image in bundle.images:
        suffix = Path(image.item.name).suffix.casefold()
        gcs_uri = upload_bytes(
            bucket,
            f"{prefix}/source/images/{image.sha256}{suffix}",
            image.payload,
            image.content_type,
        )
        image_manifest[image.item.name] = {
            "source_file_id": image.item.file_id,
            "source_name": image.item.name,
            "source_gcs_uri": gcs_uri,
            "sha256": image.sha256,
            "content_type": image.content_type,
            "suffix": suffix,
        }

    embedder = VertexEmbedder(args.project_id, dimensions=768)
    batch = db.batch()
    cards_collection = db.collection(args.cards_collection)
    mechanics_collection = db.collection(args.mechanics_collection)
    profiles_collection = db.collection(args.brand_profiles_collection)
    mechanic_rows: List[Dict[str, Any]] = []
    card_rows: List[Dict[str, Any]] = []
    embedded_promos: List[Dict[str, Any]] = []
    for display_order, promo in enumerate(promo_cards, start=1):
        parent_text = build_parent_text(promo)
        card_id = f"{version_id}-{promo.promo_id}"
        display_cards = []
        for image_order, image_name in enumerate(promo.image_source_names, start=1):
            visual_id = f"{promo.promo_id}-card-{image_order}"
            display_cards.append(
                {
                    "card_id": visual_id,
                    "display_order": image_order,
                    "source_image_name": image_name,
                    "title": promo.title,
                    "subtitle": promo.offer_summary,
                    "enabled": True,
                }
            )
            card_rows.append(
                {
                    "card_id": visual_id,
                    "promo_id": promo.promo_id,
                    "display_order": image_order,
                    "source_image_name": image_name,
                    "title": promo.title,
                    "subtitle": promo.offer_summary,
                    "enabled": True,
                    "button_policy": button_policy_name(promo.brands),
                    "evidence": " | ".join(promo.source_evidence),
                }
            )
        parent_vector = embedder.embed(parent_text, task_type="RETRIEVAL_DOCUMENT")
        embedded_promos.append(
            {
                **asdict(promo),
                "display_order": display_order,
                "retrieval_aliases": build_retrieval_aliases(promo),
                "embedding_values": parent_vector,
            }
        )
        batch.set(
            cards_collection.document(card_id),
            {
                "catalog_version_id": version_id,
                "promo_id": promo.promo_id,
                "status": "pending_review",
                "enabled": True,
                "display_order": display_order,
                "title": promo.title,
                "brands": promo.brands,
                "promo_type": promo.promo_type,
                "offer_summary": promo.offer_summary,
                "valid_from": promo.valid_from,
                "valid_until": promo.valid_until,
                "source_evidence": promo.source_evidence,
                "eligibility": promo.eligibility,
                "evidence_refs": [mechanics_text_uri],
                "retrieval_aliases": build_retrieval_aliases(promo),
                "display_cards": display_cards,
                "embedding": Vector(parent_vector),
                "source_gcs_uri": mechanics_text_uri,
                "created_at": firestore.SERVER_TIMESTAMP,
            },
        )
        for ordinal, mechanic in enumerate(promo.mechanics, start=1):
            mechanic_id = f"{promo.promo_id}-mechanic-{ordinal}"
            mechanic_text = _mechanic_embedding_text(promo, mechanic)
            row = {
                "mechanic_id": mechanic_id,
                "promo_id": promo.promo_id,
                "ordinal": ordinal,
                "text": mechanic,
                "evidence": " | ".join(promo.source_evidence),
                "enabled": True,
            }
            mechanic_rows.append(row)
            batch.set(
                mechanics_collection.document(f"{version_id}-{mechanic_id}"),
                {
                    "catalog_version_id": version_id,
                    "promo_id": promo.promo_id,
                    "card_id": card_id,
                    "chunk_id": mechanic_id,
                    "ordinal": ordinal,
                    "text": mechanic,
                    "status": "pending_review",
                    "enabled": True,
                    "source_evidence": promo.source_evidence,
                    "evidence_refs": [mechanics_text_uri],
                    "embedding": Vector(embedder.embed(mechanic_text, task_type="RETRIEVAL_DOCUMENT")),
                    "created_at": firestore.SERVER_TIMESTAMP,
                },
            )

    brand_profiles = build_brand_profile_drafts(promo_cards)
    for brand, profile in brand_profiles.items():
        batch.set(
            profiles_collection.document(f"{version_id}-{_slug(brand)}"),
            {
                "catalog_version_id": version_id,
                "brand": brand,
                "summary": profile["summary"],
                "positioning": profile["positioning"],
                "source_evidence": profile["source_evidence"],
                "evidence_refs": [mechanics_text_uri],
                "status": "pending_review",
                "enabled": True,
                "created_at": firestore.SERVER_TIMESTAMP,
            },
        )

    version_ref = db.collection(args.versions_collection).document(version_id)
    batch.set(
        version_ref,
        {
            "catalog_version_id": version_id,
            "status": "pending_review",
            "source_hash": bundle.source_hash,
            "source_drive_folder_id": args.drive_source_folder_id,
            "month_folder_name": bundle.month_name,
            "source_file_id": bundle.mechanics_item.file_id,
            "source_file_name": bundle.mechanics_item.name,
            "private_bucket": args.private_bucket,
            "mechanics_docx_gcs_uri": mechanics_docx_uri,
            "mechanics_text_gcs_uri": mechanics_text_uri,
            "image_manifest": image_manifest,
            "card_count": len(promo_cards),
            "visual_card_count": len(card_rows),
            "mechanics_count": len(mechanic_rows),
            "embedding_dimensions": 768,
            "catalog_schema_version": CATALOG_SCHEMA_VERSION,
            "catalog_publication_revision": CATALOG_PUBLICATION_REVISION,
            "carried_forward_from_catalog_version_id": carried_forward_version_id,
            "carried_forward_promo_count": carried_forward_count,
            "created_at": firestore.SERVER_TIMESTAMP,
        },
    )
    batch.commit()
    _delete_obsolete_version_documents(
        db,
        collection=args.cards_collection,
        version_id=version_id,
        keep_document_ids={f"{version_id}-{promo.promo_id}" for promo in promo_cards},
    )
    _delete_obsolete_version_documents(
        db,
        collection=args.mechanics_collection,
        version_id=version_id,
        keep_document_ids={f"{version_id}-{row['mechanic_id']}" for row in mechanic_rows},
    )
    _delete_obsolete_version_documents(
        db,
        collection=args.brand_profiles_collection,
        version_id=version_id,
        keep_document_ids={f"{version_id}-{_slug(brand)}" for brand in brand_profiles},
    )

    evaluation_results = evaluate_catalog_drafts(
        promos=embedded_promos,
        embedder=embedder,
        today=datetime.now(MANILA).date(),
    )

    tab_rows = review_sheet_rows(
        version_id=version_id,
        source_hash=bundle.source_hash,
        source_file_name=bundle.mechanics_item.name,
        month_name=bundle.month_name,
        promos=promo_cards,
        cards=card_rows,
        mechanics=mechanic_rows,
        brand_profiles=brand_profiles,
        evaluation_results=evaluation_results,
    )
    review = GoogleReviewSheetClient(
        args.drive_service_account,
        args.review_authorized_user_json,
    ).create_review_sheet(
        title=f"Promo Catalog Review - {bundle.month_name}",
        review_folder_id=args.review_folder_id,
        tab_rows=tab_rows,
        spreadsheet_id=review_spreadsheet_id,
        archive_prefix=_review_archive_prefix(archived_review_version),
        month_name=bundle.month_name,
        archive_month_name=str(archived_review_version.get("month_folder_name") or ""),
    )
    if archived_review_version:
        archived_version_id = str(archived_review_version.get("catalog_version_id") or "").strip()
        db.collection(args.versions_collection).document(archived_version_id).update(
            {
                "review_sheet_archive_prefix": _review_archive_prefix(archived_review_version),
                "review_sheet_archived_at": firestore.SERVER_TIMESTAMP,
            }
        )
    version_ref.update(
        {
            **review,
            "review_status": "PENDING",
            "review_workbook_scope": "monthly",
            "review_workbook_month": bundle.month_name,
            "review_sheet_created_at": firestore.SERVER_TIMESTAMP,
        }
    )
    manifest = {
        "catalog_version_id": version_id,
        "source_hash": bundle.source_hash,
        "source_file": asdict(bundle.mechanics_item),
        "mechanics_docx_gcs_uri": mechanics_docx_uri,
        "mechanics_text_gcs_uri": mechanics_text_uri,
        "images": image_manifest,
        "promos": [asdict(card) for card in promo_cards],
        "review": review,
    }
    manifest_uri = upload_bytes(
        bucket,
        f"{prefix}/catalog/manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        "application/json; charset=utf-8",
    )
    version_ref.update({"manifest_gcs_uri": manifest_uri})
    return {
        "status": "built",
        "version_id": version_id,
        "version_status": "pending_review",
        "source_hash": bundle.source_hash,
        **review,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


def publish_approved_versions(args: argparse.Namespace) -> List[Dict[str, Any]]:
    """Publish every pending version whose review workbook is approved."""

    db = firestore.Client(project=args.project_id)
    query = db.collection(args.versions_collection).where(filter=FieldFilter("status", "==", "pending_review"))
    results = []
    client = GoogleReviewSheetClient(
        args.drive_service_account,
        args.review_authorized_user_json,
    )
    for snapshot in query.stream():
        version = dict(snapshot.to_dict() or {})
        spreadsheet_id = str(version.get("spreadsheet_id") or "").strip()
        if not spreadsheet_id:
            continue
        rows = client.read_review_sheet(
            spreadsheet_id,
            month_name=str(version.get("month_folder_name") or ""),
        )
        metadata = _key_value_tab(rows.get("Version") or [])
        if str(metadata.get("review_status") or "").strip().upper() != "APPROVED":
            continue
        try:
            results.append(publish_reviewed_version(args, version, rows))
        except Exception as exc:
            snapshot.reference.update(
                {
                    "publication_validation_status": "failed",
                    "publication_error_type": type(exc).__name__,
                    "publication_error": str(exc)[:2000],
                    "publication_checked_at": firestore.SERVER_TIMESTAMP,
                }
            )
            results.append(
                {
                    "status": "validation_failed",
                    "version_id": version.get("catalog_version_id"),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
    return results


def publish_reviewed_version(
    args: argparse.Namespace,
    version: Dict[str, Any],
    workbook: Dict[str, List[List[str]]],
) -> Dict[str, Any]:
    """Validate reviewed rows, publish media/docs, then activate the pointer."""

    started = time.perf_counter()
    version_id = str(version.get("catalog_version_id") or "").strip()
    if not version_id:
        raise ValueError("Version document is missing catalog_version_id")
    reviewed = parse_review_workbook(workbook)
    validate_reviewed_catalog(version, reviewed)
    flow_namespaces = {
        "staging": str(args.staging_router_flow_namespace or "").strip(),
        "live": str(args.live_router_flow_namespace or "").strip(),
    }
    if not all(flow_namespaces.values()):
        raise ValueError(
            "PROMO_STAGING_ROUTER_FLOW_NAMESPACE and PROMO_LIVE_ROUTER_FLOW_NAMESPACE "
            "are required before publication"
        )
    public_bucket = storage.Client(project=args.project_id).bucket(args.public_bucket)
    _require_public_bucket(public_bucket)
    private_bucket = storage.Client(project=args.project_id).bucket(args.private_bucket)
    image_manifest = version.get("image_manifest") if isinstance(version.get("image_manifest"), dict) else {}
    public_images: Dict[str, Dict[str, str]] = {}
    for source_name in sorted({card["source_image_name"] for card in reviewed["cards"] if card["enabled"]}):
        image = image_manifest.get(source_name) if isinstance(image_manifest.get(source_name), dict) else {}
        if not image:
            raise ValueError(f"Reviewed card references unknown image {source_name!r}")
        source_uri = str(image.get("source_gcs_uri") or "")
        source_blob = private_bucket.blob(_gcs_object_name(source_uri, args.private_bucket))
        object_name = f"catalog/{version_id}/cards/{image['sha256']}{image['suffix']}"
        target_blob = public_bucket.blob(object_name)
        if not target_blob.exists():
            public_bucket.copy_blob(source_blob, public_bucket, object_name)
        target_blob.cache_control = PUBLIC_CACHE_CONTROL
        target_blob.content_type = str(image.get("content_type") or "application/octet-stream")
        target_blob.patch()
        public_images[source_name] = {
            "source_gcs_uri": source_uri,
            "public_gcs_uri": f"gs://{args.public_bucket}/{object_name}",
            "image_url": f"https://storage.googleapis.com/{args.public_bucket}/{quote(object_name, safe='/')}",
        }

    db = firestore.Client(project=args.project_id)
    embedder = VertexEmbedder(args.project_id, dimensions=768)
    corrections: List[Dict[str, Any]] = []
    promo_by_id = {promo["promo_id"]: promo for promo in reviewed["promos"]}
    cards_by_promo: Dict[str, List[Dict[str, Any]]] = {}
    for card in reviewed["cards"]:
        if not card["enabled"]:
            continue
        promo = promo_by_id[card["promo_id"]]
        media = public_images[card["source_image_name"]]
        display_card = build_published_display_card(
            version_id=version_id,
            promo=promo,
            card=card,
            media=media,
            flow_namespaces=flow_namespaces,
        )
        cards_by_promo.setdefault(card["promo_id"], []).append(display_card)
        corrections.extend(card.get("corrections") or [])
    for promo in reviewed["promos"]:
        corrections.extend(promo.get("corrections") or [])
    for eligibility in reviewed["eligibility"]:
        corrections.extend(eligibility.get("corrections") or [])
    for mechanic in reviewed["mechanics"]:
        corrections.extend(mechanic.get("corrections") or [])
    for profile in reviewed["brand_profiles"]:
        corrections.extend(profile.get("corrections") or [])

    writes = db.batch()
    mechanics_by_promo: Dict[str, List[str]] = {}
    for mechanic in reviewed["mechanics"]:
        mechanics_by_promo.setdefault(mechanic["promo_id"], []).append(mechanic["text"])
    eligibility_by_promo = {row["promo_id"]: row for row in reviewed["eligibility"]}
    for promo in reviewed["promos"]:
        promo_id = promo["promo_id"]
        materialized_promo = {
            **promo,
            "mechanics": mechanics_by_promo.get(promo_id, []),
            "eligibility": eligibility_by_promo[promo_id],
        }
        parent = _promo_from_review_row(materialized_promo)
        promo_fields = parent.pop("promo_card_fields")
        promo_card = PromoCard(**promo_fields)
        parent["evidence_refs"] = [version.get("mechanics_text_gcs_uri")]
        writes.set(
            db.collection(args.cards_collection).document(f"{version_id}-{promo_id}"),
            {
                **parent,
                "catalog_version_id": version_id,
                "status": "published",
                "display_cards": sorted(cards_by_promo.get(promo_id, []), key=lambda card: int(card["display_order"])),
                "retrieval_aliases": build_retrieval_aliases(promo_card),
                "embedding": Vector(embedder.embed(build_parent_text(promo_card), task_type="RETRIEVAL_DOCUMENT")),
                "published_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
    for mechanic in reviewed["mechanics"]:
        promo = {
            **promo_by_id[mechanic["promo_id"]],
            "mechanics": mechanics_by_promo.get(mechanic["promo_id"], []),
            "eligibility": eligibility_by_promo[mechanic["promo_id"]],
        }
        mechanic_promo = PromoCard(**_promo_from_review_row(promo)["promo_card_fields"])
        writes.set(
            db.collection(args.mechanics_collection).document(f"{version_id}-{mechanic['mechanic_id']}"),
            {
                "catalog_version_id": version_id,
                "promo_id": mechanic["promo_id"],
                "chunk_id": mechanic["mechanic_id"],
                "ordinal": mechanic["ordinal"],
                "text": mechanic["text"],
                "enabled": mechanic["enabled"],
                "status": "published",
                "source_evidence": mechanic["evidence"],
                "evidence_refs": [version.get("mechanics_text_gcs_uri")],
                "embedding": Vector(
                    embedder.embed(
                        _mechanic_embedding_text(mechanic_promo, mechanic["text"]),
                        task_type="RETRIEVAL_DOCUMENT",
                    )
                ),
                "published_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
    for profile in reviewed["brand_profiles"]:
        writes.set(
            db.collection(args.brand_profiles_collection).document(f"{version_id}-{_slug(profile['brand'])}"),
            {
                "catalog_version_id": version_id,
                "brand": profile["brand"],
                "summary": profile["summary"],
                "positioning": profile["positioning"],
                "source_evidence": profile["evidence"],
                "evidence_refs": [version.get("mechanics_text_gcs_uri")],
                "status": "published",
                "enabled": True,
                "published_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
    writes.commit()
    _delete_obsolete_version_documents(
        db,
        collection=args.cards_collection,
        version_id=version_id,
        keep_document_ids={f"{version_id}-{promo['promo_id']}" for promo in reviewed["promos"]},
    )
    _delete_obsolete_version_documents(
        db,
        collection=args.mechanics_collection,
        version_id=version_id,
        keep_document_ids={f"{version_id}-{row['mechanic_id']}" for row in reviewed["mechanics"]},
    )
    _delete_obsolete_version_documents(
        db,
        collection=args.brand_profiles_collection,
        version_id=version_id,
        keep_document_ids={f"{version_id}-{_slug(row['brand'])}" for row in reviewed["brand_profiles"]},
    )

    config_ref = db.collection(args.config_collection).document("active")
    previous_config = config_ref.get().to_dict() or {}
    previous_version = str(previous_config.get("catalog_version_id") or "").strip()
    transaction = db.transaction()

    @firestore.transactional
    def activate(txn: Any) -> None:
        target_ref = db.collection(args.versions_collection).document(version_id)
        target = target_ref.get(transaction=txn)
        if not target.exists or str((target.to_dict() or {}).get("status")) != "pending_review":
            raise ValueError("Catalog version is no longer pending review")
        txn.update(
            target_ref,
            {
                "status": "published",
                "review_status": "APPROVED",
                "reviewed_by": str(reviewed["metadata"]["reviewed_by"]).strip(),
                "reviewed_at": parse_review_timestamp(reviewed["metadata"]["reviewed_at"]),
                "previous_catalog_version_id": previous_version,
                "corrections": corrections,
                "public_bucket": args.public_bucket,
                "publication_validation_status": "passed",
                "published_at": firestore.SERVER_TIMESTAMP,
            },
        )
        if previous_version and previous_version != version_id:
            txn.update(
                db.collection(args.versions_collection).document(previous_version),
                {"status": "superseded", "superseded_at": firestore.SERVER_TIMESTAMP},
            )
        txn.set(
            config_ref,
            {
                "catalog_version_id": version_id,
                "previous_catalog_version_id": previous_version,
                "activated_at": firestore.SERVER_TIMESTAMP,
                "source_hash": version.get("source_hash"),
                "review_spreadsheet_id": version.get("spreadsheet_id"),
            },
        )

    activate(transaction)
    return {
        "status": "published",
        "version_id": version_id,
        "previous_version_id": previous_version,
        "promo_count": len(reviewed["promos"]),
        "visual_card_count": sum(len(cards) for cards in cards_by_promo.values()),
        "correction_count": len(corrections),
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


def rollback_active_catalog(args: argparse.Namespace, target_version_id: str = "") -> Dict[str, Any]:
    """Restore the previous or explicitly requested published catalog pointer."""

    db = firestore.Client(project=args.project_id)
    config_ref = db.collection(args.config_collection).document("active")
    config = config_ref.get().to_dict() or {}
    current = str(config.get("catalog_version_id") or "").strip()
    target = str(target_version_id or config.get("previous_catalog_version_id") or "").strip()
    if not target:
        raise ValueError("No previous catalog version is recorded")
    target_ref = db.collection(args.versions_collection).document(target)
    target_doc = target_ref.get()
    if not target_doc.exists or str((target_doc.to_dict() or {}).get("status")) not in {"published", "superseded"}:
        raise ValueError(f"Rollback target {target!r} is not a retained published version")
    batch = db.batch()
    batch.set(
        config_ref,
        {
            "catalog_version_id": target,
            "previous_catalog_version_id": current,
            "activated_at": firestore.SERVER_TIMESTAMP,
            "rollback_from_catalog_version_id": current,
        },
    )
    batch.update(target_ref, {"status": "published", "rollback_activated_at": firestore.SERVER_TIMESTAMP})
    if current:
        batch.update(
            db.collection(args.versions_collection).document(current),
            {"status": "superseded", "rollback_superseded_at": firestore.SERVER_TIMESTAMP},
        )
    batch.commit()
    return {"status": "rolled_back", "catalog_version_id": target, "previous_catalog_version_id": current}


def run_sync(args: argparse.Namespace) -> Dict[str, Any]:
    """Build only on source change, then publish independently approved sheets."""

    build_result: Dict[str, Any]
    try:
        bundle = discover_source_bundle(args)
        build_result = build_pending_version(args, bundle)
    except ValueError as exc:
        if "Missing Drive item" in str(exc) and not args.month_folder_name:
            build_result = {"status": "no_current_month_source", "reason": str(exc), "active_catalog_unchanged": True}
        else:
            raise
    publication_results = publish_approved_versions(args)
    return {"status": "success", "build": build_result, "publication": publication_results}


def review_sheet_rows(
    *,
    version_id: str,
    source_hash: str,
    source_file_name: str,
    month_name: str = "",
    promos: Sequence[PromoCard],
    cards: Sequence[Dict[str, Any]],
    mechanics: Sequence[Dict[str, Any]],
    brand_profiles: Dict[str, Dict[str, Any]],
    evaluation_results: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, List[List[Any]]]:
    """Build review rows with immutable originals beside authoritative values."""

    version_rows = [
        ["key", "original_value", "reviewed_value", "notes"],
        ["catalog_month", month_name, month_name, "Monthly review boundary"],
        ["catalog_version_id", version_id, version_id, "Immutable"],
        ["source_hash", source_hash, source_hash, "Immutable"],
        ["source_file_name", source_file_name, source_file_name, "Source evidence"],
        ["catalog_schema_version", CATALOG_SCHEMA_VERSION, CATALOG_SCHEMA_VERSION, "Immutable"],
        [
            "catalog_publication_revision",
            CATALOG_PUBLICATION_REVISION,
            CATALOG_PUBLICATION_REVISION,
            "Immutable publication-format revision",
        ],
        ["review_status", "PENDING", "PENDING", "Set reviewed_value to APPROVED after all tabs pass review"],
        ["reviewed_by", "", "", "Required for approval"],
        ["reviewed_at", "", "", "Required ISO date/time for approval"],
    ]
    promo_rows: List[List[Any]] = [[
        "promo_id", "display_order", "original_title", "reviewed_title", "original_brands", "reviewed_brands",
        "original_promo_type", "reviewed_promo_type", "original_offer_summary", "reviewed_offer_summary",
        "original_valid_from", "reviewed_valid_from", "original_valid_until", "reviewed_valid_until",
        "enabled", "source_evidence",
    ]]
    for order, promo in enumerate(promos, start=1):
        promo_rows.append([
            promo.promo_id, order, promo.title, promo.title, ", ".join(promo.brands), ", ".join(promo.brands),
            promo.promo_type, promo.promo_type, promo.offer_summary, promo.offer_summary,
            promo.valid_from, promo.valid_from, promo.valid_until, promo.valid_until,
            "TRUE", " | ".join(promo.source_evidence),
        ])
    card_rows: List[List[Any]] = [[
        "card_id", "promo_id", "display_order", "source_image_name", "original_title", "reviewed_title",
        "original_subtitle", "reviewed_subtitle", "enabled", "button_policy", "source_evidence",
    ]]
    for card in cards:
        card_rows.append([
            card["card_id"], card["promo_id"], card["display_order"], card["source_image_name"],
            card["title"], fit_manychat_card_text(card["title"]),
            card["subtitle"], fit_manychat_card_text(card["subtitle"]), "TRUE",
            card["button_policy"], card["evidence"],
        ])
    mechanic_sheet_rows: List[List[Any]] = [[
        "mechanic_id", "promo_id", "ordinal", "original_text", "reviewed_text", "enabled", "source_evidence",
    ]]
    for mechanic in mechanics:
        mechanic_sheet_rows.append([
            mechanic["mechanic_id"], mechanic["promo_id"], mechanic["ordinal"], mechanic["text"], mechanic["text"],
            "TRUE", mechanic["evidence"],
        ])
    eligibility_rows: List[List[Any]] = [[
        "eligibility_id", "promo_id", "original_scope", "reviewed_scope",
        "original_included_brands", "reviewed_included_brands",
        "original_excluded_brands", "reviewed_excluded_brands",
        "original_included_patterns", "reviewed_included_patterns",
        "original_excluded_patterns", "reviewed_excluded_patterns",
        "original_included_sizes", "reviewed_included_sizes",
        "original_excluded_sizes", "reviewed_excluded_sizes",
        "original_qualifying_quantity", "reviewed_qualifying_quantity",
        "original_free_quantity", "reviewed_free_quantity",
        "ai_confidence", "review_status", "review_notes", "source_evidence",
    ]]
    for promo in promos:
        eligibility = dict(
            promo.eligibility
            or {
                "scope": "all_brand_products",
                "included_brands": list(promo.brands),
                "confidence": "low",
                "source_evidence": list(promo.source_evidence),
            }
        )
        eligibility_rows.append([
            f"{promo.promo_id}-eligibility", promo.promo_id,
            eligibility.get("scope", ""), eligibility.get("scope", ""),
            ", ".join(eligibility.get("included_brands") or []),
            ", ".join(eligibility.get("included_brands") or []),
            ", ".join(eligibility.get("excluded_brands") or []),
            ", ".join(eligibility.get("excluded_brands") or []),
            ", ".join(eligibility.get("included_patterns") or []),
            ", ".join(eligibility.get("included_patterns") or []),
            ", ".join(eligibility.get("excluded_patterns") or []),
            ", ".join(eligibility.get("excluded_patterns") or []),
            ", ".join(eligibility.get("included_sizes") or []),
            ", ".join(eligibility.get("included_sizes") or []),
            ", ".join(eligibility.get("excluded_sizes") or []),
            ", ".join(eligibility.get("excluded_sizes") or []),
            eligibility.get("qualifying_quantity", 0), eligibility.get("qualifying_quantity", 0),
            eligibility.get("free_quantity", 0), eligibility.get("free_quantity", 0),
            eligibility.get("confidence", "low"),
            "NEEDS_REVIEW" if eligibility.get("confidence") == "low" else "PENDING",
            "Confirm the AI-derived rule against source evidence, then set review_status to PASS.",
            " | ".join(eligibility.get("source_evidence") or []),
        ])
    profile_rows: List[List[Any]] = [[
        "brand", "original_summary", "reviewed_summary", "original_positioning", "reviewed_positioning",
        "enabled", "source_evidence",
    ]]
    for brand, profile in sorted(brand_profiles.items()):
        positioning = " | ".join(profile["positioning"])
        profile_rows.append([
            brand, profile["summary"], profile["summary"], positioning, positioning, "TRUE",
            " | ".join(profile["source_evidence"]),
        ])
    evaluation_rows: List[List[Any]] = [[
        "evaluation_id", "query", "expected", "ai_status", "observed", "review_status", "review_notes"
    ]]
    for case in required_retrieval_evaluations(promos):
        evaluation = (evaluation_results or {}).get(case.evaluation_id) or {}
        evaluation_rows.append(
            [
                case.evaluation_id,
                case.query,
                case.expected,
                evaluation.get("ai_status") or "PENDING",
                evaluation.get("observed") or "",
                "PENDING",
                "Review the AI result and set review_status to PASS only when the observed ranking is acceptable.",
            ]
        )
    return {
        "Version": version_rows,
        "Promos": promo_rows,
        "Cards": card_rows,
        "Mechanics": mechanic_sheet_rows,
        "Eligibility": eligibility_rows,
        "Brand Profiles": profile_rows,
        "Evaluation": evaluation_rows,
    }


def parse_review_workbook(workbook: Dict[str, List[List[str]]]) -> Dict[str, Any]:
    """Parse authoritative reviewed values while preserving correction evidence."""

    metadata = _key_value_tab(workbook.get("Version") or [])
    promos = []
    for row in _dict_rows(workbook.get("Promos") or []):
        promo_id = _required(row, "promo_id")
        promos.append(
            {
                "promo_id": promo_id,
                "display_order": _int(row.get("display_order"), 9999),
                "title": _required(row, "reviewed_title"),
                "brands": _csv(row.get("reviewed_brands")),
                "promo_type": _required(row, "reviewed_promo_type"),
                "offer_summary": _required(row, "reviewed_offer_summary"),
                "valid_from": str(row.get("reviewed_valid_from") or "").strip(),
                "valid_until": str(row.get("reviewed_valid_until") or "").strip(),
                "enabled": _bool(row.get("enabled")),
                "evidence": _pipe(row.get("source_evidence")),
                "corrections": _row_corrections("Promos", promo_id, row),
            }
        )
    cards = []
    for row in _dict_rows(workbook.get("Cards") or []):
        card_id = _required(row, "card_id")
        cards.append(
            {
                "card_id": card_id,
                "promo_id": _required(row, "promo_id"),
                "display_order": _int(row.get("display_order"), 9999),
                "source_image_name": _required(row, "source_image_name"),
                "title": _required(row, "reviewed_title"),
                "subtitle": _required(row, "reviewed_subtitle"),
                "enabled": _bool(row.get("enabled")),
                "button_policy": _required(row, "button_policy"),
                "evidence": _pipe(row.get("source_evidence")),
                "corrections": _row_corrections("Cards", card_id, row),
            }
        )
    mechanics = []
    for row in _dict_rows(workbook.get("Mechanics") or []):
        mechanic_id = _required(row, "mechanic_id")
        mechanics.append(
            {
                "mechanic_id": mechanic_id,
                "promo_id": _required(row, "promo_id"),
                "ordinal": _int(row.get("ordinal"), 9999),
                "text": _required(row, "reviewed_text"),
                "enabled": _bool(row.get("enabled")),
                "evidence": _pipe(row.get("source_evidence")),
                "corrections": _row_corrections("Mechanics", mechanic_id, row),
            }
        )
    eligibility = []
    for row in _dict_rows(workbook.get("Eligibility") or []):
        eligibility_id = _required(row, "eligibility_id")
        eligibility.append(
            {
                "eligibility_id": eligibility_id,
                "promo_id": _required(row, "promo_id"),
                "scope": _required(row, "reviewed_scope").casefold(),
                "included_brands": _csv(row.get("reviewed_included_brands")),
                "excluded_brands": _csv(row.get("reviewed_excluded_brands")),
                "included_patterns": _csv(row.get("reviewed_included_patterns")),
                "excluded_patterns": _csv(row.get("reviewed_excluded_patterns")),
                "included_sizes": _csv(row.get("reviewed_included_sizes")),
                "excluded_sizes": _csv(row.get("reviewed_excluded_sizes")),
                "qualifying_quantity": _int(row.get("reviewed_qualifying_quantity"), 0),
                "free_quantity": _int(row.get("reviewed_free_quantity"), 0),
                "confidence": str(row.get("ai_confidence") or "low").strip().casefold(),
                "review_status": str(row.get("review_status") or "").strip().upper(),
                "review_notes": str(row.get("review_notes") or "").strip(),
                "evidence": _pipe(row.get("source_evidence")),
                "corrections": _row_corrections("Eligibility", eligibility_id, row),
            }
        )
    profiles = []
    for row in _dict_rows(workbook.get("Brand Profiles") or []):
        brand = _required(row, "brand")
        if not _bool(row.get("enabled")):
            continue
        profiles.append(
            {
                "brand": brand,
                "summary": _required(row, "reviewed_summary"),
                "positioning": _pipe(row.get("reviewed_positioning")),
                "evidence": _pipe(row.get("source_evidence")),
                "corrections": _row_corrections("Brand Profiles", brand, row),
            }
        )
    evaluations = _dict_rows(workbook.get("Evaluation") or [])
    return {
        "metadata": metadata,
        "promos": [row for row in promos if row["enabled"]],
        "cards": cards,
        "mechanics": [row for row in mechanics if row["enabled"]],
        "eligibility": eligibility,
        "brand_profiles": profiles,
        "evaluations": evaluations,
    }


def validate_reviewed_catalog(version: Dict[str, Any], reviewed: Dict[str, Any]) -> None:
    """Fail closed on any review, evidence, identity, media, or eval gap."""

    metadata = reviewed["metadata"]
    if str(metadata.get("review_status") or "").strip().upper() != "APPROVED":
        raise ValueError("Version review_status must be APPROVED")
    if not str(metadata.get("reviewed_by") or "").strip() or not str(metadata.get("reviewed_at") or "").strip():
        raise ValueError("reviewed_by and reviewed_at are required")
    parse_review_timestamp(metadata["reviewed_at"])
    if str(metadata.get("catalog_version_id") or "") != str(version.get("catalog_version_id") or ""):
        raise ValueError("Review Sheet catalog_version_id does not match Firestore")
    if str(metadata.get("source_hash") or "") != str(version.get("source_hash") or ""):
        raise ValueError("Review Sheet source_hash does not match immutable source")
    promos = reviewed["promos"]
    if not promos:
        raise ValueError("At least one reviewed promo is required")
    promo_ids = [promo["promo_id"] for promo in promos]
    if len(promo_ids) != len(set(promo_ids)) or any(not re.fullmatch(r"[a-z0-9-]{1,100}", promo_id) for promo_id in promo_ids):
        raise ValueError("Promo IDs must be unique lowercase slug values")
    for promo in promos:
        if not promo["evidence"]:
            raise ValueError(f"Promo {promo['promo_id']} is missing source evidence")
        if not promo["brands"] and promo["promo_type"] != "warranty":
            raise ValueError(f"Promo {promo['promo_id']} is missing brands")
        if promo["valid_from"]:
            date.fromisoformat(promo["valid_from"])
        if promo["valid_until"]:
            date.fromisoformat(promo["valid_until"])
        if promo["valid_from"] and promo["valid_until"] and promo["valid_from"] > promo["valid_until"]:
            raise ValueError(f"Promo {promo['promo_id']} has reversed validity dates")
    eligibility_by_promo = {row["promo_id"]: row for row in reviewed["eligibility"]}
    allowed_scopes = {"all_brand_products", "selected_patterns", "selected_sizes", "selected_products"}
    for promo in promos:
        rule = eligibility_by_promo.get(promo["promo_id"])
        if not rule:
            raise ValueError(f"Promo {promo['promo_id']} is missing an eligibility rule")
        if rule["review_status"] != "PASS" or rule["scope"] not in allowed_scopes or not rule["evidence"]:
            raise ValueError(f"Promo {promo['promo_id']} eligibility is not reviewed and source-backed")
        if rule["scope"] == "selected_patterns" and not rule["included_patterns"]:
            raise ValueError(f"Promo {promo['promo_id']} selected_patterns eligibility has no included patterns")
        if rule["scope"] == "selected_sizes" and not rule["included_sizes"]:
            raise ValueError(f"Promo {promo['promo_id']} selected_sizes eligibility has no included sizes")
        for size in [*rule["included_sizes"], *rule["excluded_sizes"]]:
            if not re.fullmatch(r"\d{3}/\d{2}(?:ZR|R)\d{2}", size.upper()):
                raise ValueError(f"Promo {promo['promo_id']} has invalid eligibility tire size {size!r}")
    image_manifest = version.get("image_manifest") if isinstance(version.get("image_manifest"), dict) else {}
    seen_cards = set()
    for card in reviewed["cards"]:
        if not card["enabled"]:
            continue
        if card["card_id"] in seen_cards or card["promo_id"] not in promo_ids:
            raise ValueError(f"Card {card['card_id']} has a duplicate ID or unknown promo")
        seen_cards.add(card["card_id"])
        if card["source_image_name"] not in image_manifest or not card["evidence"]:
            raise ValueError(f"Card {card['card_id']} has an invalid image assignment or missing evidence")
        if len(card["title"]) > 80 or len(card["subtitle"]) > 80:
            raise ValueError(f"Card {card['card_id']} exceeds ManyChat title/subtitle limits")
        expected_policy = button_policy_name(next(promo["brands"] for promo in promos if promo["promo_id"] == card["promo_id"]))
        if card["button_policy"] != expected_policy:
            raise ValueError(f"Card {card['card_id']} has button policy {card['button_policy']!r}; expected {expected_policy!r}")
    for mechanic in reviewed["mechanics"]:
        if mechanic["promo_id"] not in promo_ids or not mechanic["evidence"]:
            raise ValueError(f"Mechanic {mechanic['mechanic_id']} has an unknown promo or missing evidence")
    profile_brands = {profile["brand"].casefold() for profile in reviewed["brand_profiles"] if profile["summary"] and profile["evidence"]}
    required_brands = {brand.casefold() for promo in promos for brand in promo["brands"]}
    if not required_brands.issubset(profile_brands):
        raise ValueError(f"Reviewed brand profiles are missing: {sorted(required_brands - profile_brands)}")
    eval_by_id = {str(row.get("evaluation_id") or ""): row for row in reviewed["evaluations"]}
    required_evaluations = required_retrieval_evaluations(promos)
    missing = [case.evaluation_id for case in required_evaluations if case.evaluation_id not in eval_by_id]
    failed = [
        case.evaluation_id
        for case in required_evaluations
        if str((eval_by_id.get(case.evaluation_id) or {}).get("review_status") or "").strip().upper() != "PASS"
    ]
    if missing or failed:
        raise ValueError(f"Retrieval evaluation is incomplete. missing={missing}; not_passed={failed}")


def build_published_display_card(
    *,
    version_id: str,
    promo: Dict[str, Any],
    card: Dict[str, Any],
    media: Dict[str, str],
    flow_namespaces: Dict[str, str],
) -> Dict[str, Any]:
    """Build the immutable delivery card once, during publication."""

    buttons = build_button_definitions(
        version_id=version_id,
        promo_id=promo["promo_id"],
        card_id=card["card_id"],
        brands=promo["brands"],
        flow_namespaces=flow_namespaces,
    )
    return {
        "card_id": card["card_id"],
        "card_ref": f"card:{card['card_id']}",
        "display_order": card["display_order"],
        "title": card["title"],
        "subtitle": card["subtitle"],
        "source_image_name": card["source_image_name"],
        "source_gcs_uri": media["source_gcs_uri"],
        "public_gcs_uri": media["public_gcs_uri"],
        "image_url": media["image_url"],
        "buttons": buttons,
    }


def build_button_definitions(
    *,
    version_id: str,
    promo_id: str,
    card_id: str,
    brands: Sequence[str],
    flow_namespaces: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Apply the reviewed button policy and tracked field actions."""

    clean_brands = [str(brand).strip() for brand in brands if str(brand).strip()]
    clean_targets = {
        environment: str(flow_namespaces.get(environment) or "").strip()
        for environment in ("staging", "live")
    }
    if not all(clean_targets.values()):
        raise ValueError("Both staging and live promo router flow namespaces are required")
    if len(clean_brands) == 1:
        specifications = [
            ("Check Price", "check_price", clean_brands[0]),
            ("Promo Details", "promo_details", ""),
            ("About Brand", "about_brand", clean_brands[0]),
        ]
    elif len(clean_brands) == 2:
        specifications = [
            (clean_brands[0][:20], "choose_brand", clean_brands[0]),
            (clean_brands[1][:20], "choose_brand", clean_brands[1]),
            ("Promo Details", "promo_details", ""),
        ]
    else:
        discovery_caption = (
            "Find Tires"
            if promo_id == "the-gulong-double-warranty"
            else "Choose Brand"
        )
        specifications = [(discovery_caption, "choose_brand", ""), ("Promo Details", "promo_details", "")]
    return [
        {
            "type": "flow",
            "caption": caption,
            "targets": clean_targets,
            "action": action,
            "selected_brand": selected_brand,
            "actions": _button_field_actions(
                version_id=version_id,
                promo_id=promo_id,
                card_id=card_id,
                action=action,
                selected_brand=selected_brand,
            ),
        }
        for caption, action, selected_brand in specifications
    ]


def _button_field_actions(
    *,
    version_id: str,
    promo_id: str,
    card_id: str,
    action: str,
    selected_brand: str,
) -> List[Dict[str, Any]]:
    token = build_promo_click_token(
        catalog_version_id=version_id,
        promo_id=promo_id,
        card_id=card_id,
        action=action,
        selected_brand=selected_brand,
    )
    return [{"action": "set_field_value", "field_name": "promo_selected_id", "value": token}]


def build_brand_profile_drafts(promos: Sequence[PromoCard]) -> Dict[str, Dict[str, Any]]:
    """Create evidence-bound review drafts without unsupported brand lore."""

    output: Dict[str, Dict[str, Any]] = {}
    brands = sorted({brand for promo in promos for brand in promo.brands})
    for brand in brands:
        related = [promo for promo in promos if brand in promo.brands]
        titles = [promo.title for promo in related]
        output[brand] = {
            "summary": f"{brand} has current reviewed offers in this catalog: {', '.join(titles)}.",
            "positioning": [promo.offer_summary for promo in related if promo.offer_summary],
            "source_evidence": list(dict.fromkeys(item for promo in related for item in promo.source_evidence)),
        }
    return output


def required_retrieval_evaluations(
    promos: Sequence[Any],
) -> List[RetrievalEvaluation]:
    """Build review gates from the promos that can actually be published.

    Monthly catalogs change independently of runtime releases. Deriving the
    positive cases from promo IDs, brands, and types prevents an expired
    campaign from becoming a permanent publication requirement while keeping
    stable expired/unrelated negative controls.
    """

    enabled_promos = [promo for promo in promos if _promo_field(promo, "enabled", True)]
    cases: List[RetrievalEvaluation] = []
    for promo in enabled_promos:
        promo_id = str(_promo_field(promo, "promo_id", "") or "").strip()
        title = str(_promo_field(promo, "title", "") or promo_id).strip()
        if not promo_id:
            continue
        cases.append(
            RetrievalEvaluation(
                evaluation_id=f"promo_{promo_id}",
                query=f"Ano po mechanics ng {title}?",
                expected=f"{title} ranks first",
                rule="promo_first",
                target_promo_ids=(promo_id,),
            )
        )

    promo_ids_by_brand: Dict[str, List[str]] = {}
    brand_labels: Dict[str, str] = {}
    for promo in enabled_promos:
        promo_id = str(_promo_field(promo, "promo_id", "") or "").strip()
        for brand in _promo_field(promo, "brands", []) or []:
            label = str(brand or "").strip()
            if not promo_id or not label:
                continue
            key = label.casefold()
            brand_labels.setdefault(key, label)
            promo_ids_by_brand.setdefault(key, []).append(promo_id)
    for brand_key, promo_ids in sorted(promo_ids_by_brand.items()):
        unique_ids = tuple(dict.fromkeys(promo_ids))
        if len(unique_ids) < 2:
            continue
        label = brand_labels[brand_key]
        cases.append(
            RetrievalEvaluation(
                evaluation_id=f"brand_{_slug(label)}",
                query=f"Ano po mga promo niyo sa {label}?",
                expected=f"All {label} promos lead the results",
                rule="targets_lead",
                target_promo_ids=unique_ids,
            )
        )

    buy_three_ids = tuple(
        str(_promo_field(promo, "promo_id", "") or "").strip()
        for promo in enabled_promos
        if str(_promo_field(promo, "promo_type", "") or "").strip() == "buy_3_get_1"
    )
    buy_three_ids = tuple(promo_id for promo_id in buy_three_ids if promo_id)
    if buy_three_ids:
        cases.append(
            RetrievalEvaluation(
                evaluation_id="generic_3plus1",
                query="Ano yung available na 3+1 promo?",
                expected="All current 3+1 promos lead the results",
                rule="targets_lead",
                target_promo_ids=buy_three_ids,
            )
        )
        catalog_brands = set(promo_ids_by_brand)
        negative_brand = next(
            (
                brand
                for brand in EVALUATION_NEGATIVE_BRANDS
                if brand.casefold() not in catalog_brands
            ),
            "Unlisted Brand",
        )
        cases.append(
            RetrievalEvaluation(
                evaluation_id="unavailable_brand_3plus1",
                query=f"May {negative_brand} 3+1 promo ba?",
                expected=(
                    f"No exact {negative_brand} match; current 3+1 alternatives lead"
                ),
                rule="negative_brand_targets_lead",
                target_promo_ids=buy_three_ids,
                negative_brand=negative_brand,
            )
        )

    cases.extend(
        [
            RetrievalEvaluation(
                evaluation_id="expired_promos",
                query="Ano mga expired promo?",
                expected="Expired promos are not presented as active",
                rule="no_expired",
            ),
            RetrievalEvaluation(
                evaluation_id="unrelated",
                query="Saan nearest installation partner sa Makati?",
                expected="No definitive promo claim is made",
                rule="unrelated",
            ),
        ]
    )
    return cases


def _promo_field(promo: Any, name: str, default: Any = None) -> Any:
    """Read one promo field from either a dataclass draft or reviewed row."""

    if isinstance(promo, dict):
        return promo.get(name, default)
    return getattr(promo, name, default)


def evaluate_catalog_drafts(
    *,
    promos: Sequence[Dict[str, Any]],
    embedder: Any,
    today: date,
) -> Dict[str, Dict[str, str]]:
    """Run the mandatory retrieval matrix against freshly built draft vectors."""

    def search(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Rank drafts and retain only candidates satisfying explicit offer terms."""

        query_vector = embedder.embed(query, task_type="RETRIEVAL_QUERY")
        candidates = []
        for promo in promos:
            document_vector = promo.get("embedding_values") or []
            candidate = {key: value for key, value in promo.items() if key != "embedding_values"}
            candidate["vector_distance"] = _cosine_distance(query_vector, document_vector)
            candidates.append(candidate)
        ranked = rerank_promo_candidates(query, candidates)
        # Match the runtime's deterministic allowed-ref boundary. An explicit
        # 3+1 or offer-amount query may still retrieve semantically related
        # offers, but those candidates cannot satisfy the publication gate.
        constrained = [
            candidate
            for candidate in ranked
            if promo_candidate_matches_explicit_constraints(query, candidate)
        ]
        return constrained[:top_k]

    results: Dict[str, Dict[str, str]] = {}
    for case in required_retrieval_evaluations(promos):
        ranked = search(case.query)
        ids = [str(row.get("promo_id") or "") for row in ranked]
        leading_ids = set(ids[: len(case.target_promo_ids)])
        target_ids = set(case.target_promo_ids)
        if case.rule == "promo_first":
            passed = bool(ids) and ids[0] in target_ids
        elif case.rule == "targets_lead":
            passed = bool(target_ids) and leading_ids == target_ids
        elif case.rule == "negative_brand_targets_lead":
            negative_brand = case.negative_brand.casefold()
            exact = any(
                negative_brand
                in {str(brand).casefold() for brand in row.get("brands") or []}
                for row in ranked
            )
            passed = not exact and bool(target_ids) and leading_ids == target_ids
        elif case.rule == "no_expired":
            passed = not any(_promo_expired(row, today=today) for row in promos if row.get("enabled", True))
        elif case.rule == "unrelated":
            passed = not is_targeted_promo_query(case.query)
        else:
            passed = False
        results[case.evaluation_id] = {
            "ai_status": "AI_PASS" if passed else "AI_FAIL",
            "observed": "ranked_promo_ids=" + ", ".join(ids[:5]),
        }
    return results


def _cosine_distance(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 1.0
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if not left_norm or not right_norm:
        return 1.0
    return 1.0 - (dot / (left_norm * right_norm))


def _promo_expired(promo: Dict[str, Any], *, today: date) -> bool:
    text = str(promo.get("valid_until") or "").strip()
    if not text:
        return False
    try:
        return date.fromisoformat(text) < today
    except ValueError:
        return True


def button_policy_name(brands: Sequence[str]) -> str:
    count = len([brand for brand in brands if str(brand).strip()])
    if count == 1:
        return "single_brand"
    if count == 2:
        return "two_brand"
    return "multi_brand"


def _delete_obsolete_version_documents(
    db: Any,
    *,
    collection: str,
    version_id: str,
    keep_document_ids: set[str],
) -> int:
    """Delete stale drafts so they cannot consume vector-search result slots."""

    query = db.collection(collection).where(
        filter=FieldFilter("catalog_version_id", "==", version_id)
    )
    obsolete_refs = [
        snapshot.reference
        for snapshot in query.stream()
        if str(snapshot.id) not in keep_document_ids
    ]
    for offset in range(0, len(obsolete_refs), 400):
        batch = db.batch()
        for reference in obsolete_refs[offset : offset + 400]:
            batch.delete(reference)
        batch.commit()
    return len(obsolete_refs)


def _promo_from_review_row(row: Dict[str, Any]) -> Dict[str, Any]:
    published_eligibility = {
        key: value
        for key, value in dict(row.get("eligibility") or {}).items()
        if key not in {"corrections", "review_notes", "review_status", "eligibility_id"}
    }
    fields = {
        "promo_id": row["promo_id"],
        "title": row["title"],
        "brands": row["brands"],
        "promo_type": row["promo_type"],
        "offer_summary": row["offer_summary"],
        "mechanics": list(row.get("mechanics") or []),
        "valid_from": row["valid_from"],
        "valid_until": row["valid_until"],
        "source_evidence": row["evidence"],
        "image_source_names": [],
        "eligibility": published_eligibility,
    }
    return {
        "promo_id": row["promo_id"],
        "title": row["title"],
        "brands": row["brands"],
        "promo_type": row["promo_type"],
        "offer_summary": row["offer_summary"],
        "valid_from": row["valid_from"],
        "valid_until": row["valid_until"],
        "enabled": row["enabled"],
        "display_order": row["display_order"],
        "source_evidence": row["evidence"],
        "evidence_refs": [],
        "eligibility": published_eligibility,
        "promo_card_fields": fields,
    }


def _mechanic_embedding_text(promo: PromoCard, mechanic: str) -> str:
    return "\n".join(
        [
            f"Promo title: {promo.title}",
            f"Brands: {', '.join(promo.brands)}",
            f"Promo type: {promo.promo_type}",
            f"Mechanic: {mechanic}",
        ]
    )


def _version_for_source_hash(
    db: Any,
    collection: str,
    source_hash: str,
    *,
    schema_version: int = CATALOG_SCHEMA_VERSION,
    publication_revision: int = CATALOG_PUBLICATION_REVISION,
) -> Dict[str, Any]:
    """Return a reusable immutable build for the same source and publisher format."""

    query = db.collection(collection).where(filter=FieldFilter("source_hash", "==", source_hash))
    for snapshot in query.stream():
        payload = dict(snapshot.to_dict() or {})
        if (
            int(payload.get("catalog_schema_version") or 1) == int(schema_version)
            and int(payload.get("catalog_publication_revision") or 1)
            == int(publication_revision)
            and str(payload.get("status") or "") in {"pending_review", "published", "superseded"}
        ):
            return payload
    return {}


def _carry_forward_published_review(
    *,
    db: Any,
    versions_collection: str,
    cards_collection: str,
    mechanics_collection: str,
    source_hash: str,
    extracted_promos: Sequence[PromoCard],
    target_version_id: str,
) -> tuple[List[PromoCard], str, int]:
    """Retain prior human-reviewed catalog values when the source is unchanged."""

    version_query = db.collection(versions_collection).where(
        filter=FieldFilter("source_hash", "==", source_hash)
    )
    prior_versions = []
    for snapshot in version_query.stream():
        payload = dict(snapshot.to_dict() or {})
        version_id = str(payload.get("catalog_version_id") or snapshot.id).strip()
        if version_id == target_version_id:
            continue
        if str(payload.get("status") or "") not in {"published", "superseded"}:
            continue
        payload["catalog_version_id"] = version_id
        prior_versions.append(payload)
    if not prior_versions:
        return list(extracted_promos), "", 0
    prior_versions.sort(
        key=lambda item: (
            str(item.get("status") or "") == "published",
            int(item.get("catalog_schema_version") or 1),
        ),
        reverse=True,
    )
    prior_version_id = str(prior_versions[0]["catalog_version_id"])
    prior_cards = []
    cards_query = db.collection(cards_collection).where(
        filter=FieldFilter("catalog_version_id", "==", prior_version_id)
    )
    for snapshot in cards_query.stream():
        payload = dict(snapshot.to_dict() or {})
        if str(payload.get("status") or "") != "published":
            continue
        prior_cards.append(payload)
    mechanics_by_promo: Dict[str, List[Dict[str, Any]]] = {}
    mechanics_query = db.collection(mechanics_collection).where(
        filter=FieldFilter("catalog_version_id", "==", prior_version_id)
    )
    for snapshot in mechanics_query.stream():
        payload = dict(snapshot.to_dict() or {})
        if str(payload.get("status") or "") != "published" or payload.get("enabled", True) is False:
            continue
        mechanics_by_promo.setdefault(str(payload.get("promo_id") or ""), []).append(payload)
    carried = _carry_forward_reviewed_promos(
        extracted_promos,
        prior_cards=prior_cards,
        mechanics_by_promo=mechanics_by_promo,
    )
    count = sum(1 for card in carried if card.promo_id in {str(row.get("promo_id") or "") for row in prior_cards})
    return carried, prior_version_id, count


def _carry_forward_reviewed_promos(
    extracted_promos: Sequence[PromoCard],
    *,
    prior_cards: Sequence[Dict[str, Any]],
    mechanics_by_promo: Dict[str, List[Dict[str, Any]]],
) -> List[PromoCard]:
    """Match immutable poster assignments and layer new eligibility onto reviewed promos."""

    prior_by_images: Dict[frozenset[str], Dict[str, Any]] = {}
    for prior in prior_cards:
        image_names = frozenset(
            str(card.get("source_image_name") or "").strip()
            for card in prior.get("display_cards") or []
            if str(card.get("source_image_name") or "").strip()
        )
        if image_names:
            prior_by_images[image_names] = prior
    output: List[tuple[int, int, PromoCard]] = []
    for index, extracted in enumerate(extracted_promos):
        image_names = frozenset(extracted.image_source_names)
        prior = prior_by_images.get(image_names)
        if not prior:
            output.append((10000 + index, index, extracted))
            continue
        prior_promo_id = str(prior.get("promo_id") or "").strip()
        mechanics = sorted(
            mechanics_by_promo.get(prior_promo_id) or [],
            key=lambda row: (int(row.get("ordinal") or 9999), str(row.get("chunk_id") or "")),
        )
        output.append(
            (
                int(prior.get("display_order") or 9999),
                index,
                PromoCard(
                    promo_id=prior_promo_id,
                    title=str(prior.get("title") or extracted.title).strip(),
                    brands=[str(value).strip() for value in prior.get("brands") or [] if str(value).strip()],
                    promo_type=str(prior.get("promo_type") or extracted.promo_type).strip(),
                    offer_summary=str(prior.get("offer_summary") or extracted.offer_summary).strip(),
                    mechanics=[
                        str(row.get("text") or "").strip()
                        for row in mechanics
                        if str(row.get("text") or "").strip()
                    ]
                    or list(extracted.mechanics),
                    valid_from=str(prior.get("valid_from") or "").strip(),
                    valid_until=str(prior.get("valid_until") or "").strip(),
                    source_evidence=[
                        str(value).strip()
                        for value in prior.get("source_evidence") or []
                        if str(value).strip()
                    ]
                    or list(extracted.source_evidence),
                    image_source_names=list(extracted.image_source_names),
                    eligibility=dict(extracted.eligibility),
                ),
            )
        )
    return [card for _, _, card in sorted(output, key=lambda item: (item[0], item[1]))]


def _versions_for_spreadsheet_id(db: Any, collection: str, spreadsheet_id: str) -> List[Dict[str, Any]]:
    query = db.collection(collection).where(filter=FieldFilter("spreadsheet_id", "==", spreadsheet_id))
    return [dict(snapshot.to_dict() or {}) for snapshot in query.stream()]


def _monthly_review_spreadsheet_id(db: Any, collection: str, month_name: str) -> str:
    """Return the newest explicitly month-scoped review workbook, if one exists."""

    query = db.collection(collection).where(
        filter=FieldFilter("month_folder_name", "==", month_name)
    )
    candidates = []
    for snapshot in query.stream():
        version = dict(snapshot.to_dict() or {})
        if str(version.get("review_workbook_scope") or "").strip() != "monthly":
            continue
        if str(version.get("review_workbook_month") or "").strip() != month_name:
            continue
        if not str(version.get("spreadsheet_id") or "").strip():
            continue
        candidates.append(version)
    if not candidates:
        return ""
    newest = max(
        candidates,
        key=lambda item: str(
            item.get("review_sheet_created_at")
            or item.get("created_at")
            or ""
        ),
    )
    return str(newest.get("spreadsheet_id") or "").strip()


def _require_review_spreadsheet_month(
    spreadsheet_versions: Sequence[Dict[str, Any]],
    month_name: str,
) -> None:
    """Reject a review workbook that already contains another catalog month."""

    foreign_months = sorted(
        {
            str(item.get("month_folder_name") or "").strip()
            for item in spreadsheet_versions
            if str(item.get("month_folder_name") or "").strip()
            and str(item.get("month_folder_name") or "").strip() != month_name
        }
    )
    if foreign_months:
        raise ValueError(
            "Review spreadsheet is already scoped to a different catalog month: "
            f"{foreign_months[0]!r}"
        )


def _review_archive_prefix(version: Dict[str, Any]) -> str:
    version_id = str(version.get("catalog_version_id") or "").strip()
    if not version_id:
        return ""
    schema_version = int(version.get("catalog_schema_version") or 1)
    month_label = _month_review_label(str(version.get("month_folder_name") or ""))
    return _safe_sheet_archive_prefix(
        f"ARCHIVE {month_label} v{schema_version}-{version_id[-12:]}"
    )


def _review_tab_titles(month_name: str) -> Dict[str, str]:
    """Map stable logical tab names to month-first reviewer-facing titles."""

    month_name = str(month_name or "").strip()
    if not month_name:
        return {tab: tab for tab in REVIEW_TABS}
    prefix = _month_review_label(month_name)
    return {
        tab: _safe_sheet_archive_prefix(f"{prefix} {REVIEW_TAB_LABELS[tab]}")
        for tab in REVIEW_TABS
    }


def _month_review_label(month_name: str) -> str:
    """Return a short, unambiguous month label for review tabs."""

    value = str(month_name or "").strip()
    match = re.fullmatch(r"(\d{4})-(\d{2})", value)
    if not match:
        return value or "UNKNOWN MONTH"
    year, month = (int(part) for part in match.groups())
    return date(year, month, 1).strftime("%b %Y").upper()


def _safe_sheet_archive_prefix(value: str) -> str:
    compact = re.sub(r"[\\/\?\*\[\]:]+", "-", str(value or "").strip())
    return compact[:72].strip()


def _review_credentials(service_account_email: str, authorized_user_json: str) -> Any:
    """Build review credentials for Shared Drive, user OAuth, or bootstrap Sheet access."""

    authorized_user_json = str(authorized_user_json or "").strip()
    if authorized_user_json:
        try:
            info = json.loads(authorized_user_json)
        except json.JSONDecodeError as exc:
            raise ValueError("PROMO_REVIEW_GOOGLE_OAUTH_JSON is not valid JSON") from exc
        missing = [
            key
            for key in ("client_id", "client_secret", "refresh_token")
            if not str(info.get(key) or "").strip()
        ]
        if missing:
            raise ValueError(
                "PROMO_REVIEW_GOOGLE_OAUTH_JSON is missing required fields: "
                + ", ".join(missing)
            )
        return AuthorizedUserCredentials.from_authorized_user_info(
            info,
            scopes=list(REVIEW_SCOPES),
        )

    source_credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    return impersonated_credentials.Credentials(
        source_credentials=source_credentials,
        target_principal=service_account_email,
        target_scopes=list(REVIEW_SCOPES),
        lifetime=3600,
    )


def _existing_version_is_complete(version: Dict[str, Any]) -> bool:
    """Return whether an existing immutable build can safely be skipped."""

    status = str(version.get("status") or "").strip()
    if status in {"published", "superseded"}:
        return True
    return status == "pending_review" and bool(str(version.get("spreadsheet_id") or "").strip())


def _require_google_api_success(response: Any, operation: str) -> None:
    """Raise an actionable error that retains the Google API response body."""

    if bool(getattr(response, "ok", False)):
        return
    status_code = getattr(response, "status_code", "unknown")
    detail = str(getattr(response, "text", "") or "").strip()
    if len(detail) > 2000:
        detail = f"{detail[:2000]}..."
    raise RuntimeError(f"Google API {operation} failed ({status_code}): {detail or 'empty response'}")


def _require_public_bucket(bucket: Any) -> None:
    if not bucket.exists():
        raise ValueError(f"Public media bucket {bucket.name!r} does not exist")
    policy = bucket.get_iam_policy(requested_policy_version=3)
    bindings = getattr(policy, "bindings", {})
    if isinstance(bindings, dict):
        public = "allUsers" in set(bindings.get("roles/storage.objectViewer") or [])
    else:
        public = any(
            binding.get("role") == "roles/storage.objectViewer" and "allUsers" in set(binding.get("members") or [])
            for binding in bindings or []
        )
    if not public:
        raise ValueError("Public media bucket does not grant roles/storage.objectViewer to allUsers")


def _gcs_object_name(uri: str, bucket_name: str) -> str:
    prefix = f"gs://{bucket_name}/"
    if not uri.startswith(prefix):
        raise ValueError(f"Expected an object in gs://{bucket_name}")
    return uri[len(prefix) :]


def _key_value_tab(rows: Sequence[Sequence[str]]) -> Dict[str, str]:
    output = {}
    for row in list(rows)[1:]:
        if not row:
            continue
        key = str(row[0] or "").strip()
        original = str(row[1] if len(row) > 1 else "").strip()
        reviewed = str(row[2] if len(row) > 2 else "").strip()
        if key:
            output[key] = reviewed if reviewed != "" else original
    return output


def _dict_rows(rows: Sequence[Sequence[str]]) -> List[Dict[str, str]]:
    if not rows:
        return []
    headers = [str(value or "").strip() for value in rows[0]]
    output = []
    for values in rows[1:]:
        if not any(str(value or "").strip() for value in values):
            continue
        output.append({header: str(values[index] if index < len(values) else "").strip() for index, header in enumerate(headers) if header})
    return output


def _row_corrections(tab: str, row_id: str, row: Dict[str, str]) -> List[Dict[str, str]]:
    corrections = []
    for key, original in row.items():
        if not key.startswith("original_"):
            continue
        suffix = key[len("original_") :]
        reviewed_key = f"reviewed_{suffix}"
        if reviewed_key in row and str(row[reviewed_key]) != str(original):
            corrections.append(
                {
                    "tab": tab,
                    "row_id": row_id,
                    "field": suffix,
                    "original_value": str(original),
                    "reviewed_value": str(row[reviewed_key]),
                    "source_evidence": str(row.get("source_evidence") or ""),
                }
            )
    return corrections


def _required(row: Dict[str, str], key: str) -> str:
    value = str(row.get(key) or "").strip()
    if not value:
        raise ValueError(f"Review row is missing required field {key!r}")
    return value


def _bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "enabled"}


def _int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _csv(value: Any) -> List[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _pipe(value: Any) -> List[str]:
    return [item.strip() for item in str(value or "").split("|") if item.strip()]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").casefold()).strip("-")


def fit_manychat_card_text(value: Any, limit: int = 80) -> str:
    """Shorten a review default at a word boundary without changing its source value."""

    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    available = max(1, limit - 3)
    shortened = text[:available].rstrip()
    if " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]
    shortened = shortened.rstrip(" ,.;:-") or text[:available]
    return f"{shortened}..."


def parse_review_timestamp(value: Any) -> datetime:
    """Return a timezone-aware review timestamp from ISO or Sheets display text."""

    text = str(value or "").strip()
    if not text:
        raise ValueError("reviewed_at is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
        for format_string in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p"):
            try:
                parsed = datetime.strptime(text, format_string)
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValueError("reviewed_at must be an ISO or Google Sheets date/time")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MANILA)
    return parsed.astimezone(MANILA)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI contract for monthly catalog sync, review, and rollback actions."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["sync", "build", "publish", "rollback"], nargs="?", default="sync")
    parser.add_argument("--project-id", default=os.getenv("GOOGLE_CLOUD_PROJECT", "gulong-chatbot-459723"))
    parser.add_argument("--drive-source-folder-id", default="18s3IRvGJ52Zbcnqibyiz9I7VlMKDi-GD")
    parser.add_argument("--review-folder-id", default="1gyeRwn3_Yd9Tsky4quSVqfjCwN9wxOhO")
    parser.add_argument("--drive-service-account", default="promo-catalog-bot@gulong-chatbot-459723.iam.gserviceaccount.com")
    parser.add_argument(
        "--review-authorized-user-json",
        default=os.getenv("PROMO_REVIEW_GOOGLE_OAUTH_JSON", ""),
        help="Authorized-user OAuth JSON used to create owner-backed review workbooks.",
    )
    parser.add_argument(
        "--review-spreadsheet-id",
        default=os.getenv("PROMO_REVIEW_SPREADSHEET_ID", ""),
        help=(
            "Optional existing workbook for the requested month. Same-month versions may reuse it; "
            "a workbook cannot be reused across catalog months."
        ),
    )
    parser.add_argument("--month-folder-name", default=os.getenv("PROMO_MONTH_FOLDER_NAME", ""))
    parser.add_argument("--images-folder-name", default="Promo Images")
    parser.add_argument("--mechanics-folder-name", default="Promo Mechanics")
    parser.add_argument("--private-bucket", default="lica-gulong-chatbot-embeddings")
    parser.add_argument("--public-bucket", default="gulong-chatbot-459723-promo-media")
    parser.add_argument("--extractor-model", default="gemini-2.5-flash")
    parser.add_argument("--versions-collection", default="promo_catalog_versions")
    parser.add_argument("--cards-collection", default="promo_catalog_cards")
    parser.add_argument("--mechanics-collection", default="promo_catalog_mechanics")
    parser.add_argument("--brand-profiles-collection", default="promo_brand_profiles")
    parser.add_argument("--config-collection", default="promo_catalog_config")
    parser.add_argument(
        "--staging-router-flow-namespace",
        default=os.getenv("PROMO_STAGING_ROUTER_FLOW_NAMESPACE", ""),
    )
    parser.add_argument(
        "--live-router-flow-namespace",
        default=os.getenv("PROMO_LIVE_ROUTER_FLOW_NAMESPACE", ""),
    )
    parser.add_argument("--version-id")
    parser.add_argument("--target-version-id", default="")
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.action == "sync":
            result = run_sync(args)
        elif args.action == "build":
            result = build_pending_version(args, discover_source_bundle(args))
        elif args.action == "publish":
            result = {"status": "success", "publication": publish_approved_versions(args)}
        else:
            result = rollback_active_catalog(args, args.target_version_id)
    except Exception as exc:
        result = {"status": "error", "error_type": type(exc).__name__, "error": str(exc)}
    text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0 if result.get("status") in {"success", "built", "unchanged", "published", "rolled_back"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
