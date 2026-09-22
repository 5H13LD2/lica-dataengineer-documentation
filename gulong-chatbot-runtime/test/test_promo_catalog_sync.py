from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import promo_catalog_sync
from scripts.promo_catalog_builder import PromoCard
from scripts.promo_vector_trial import DriveItem
from scripts.promo_catalog_sync import (
    CATALOG_PUBLICATION_REVISION,
    REVIEW_TABS,
    SHEETS_API,
    GoogleReviewSheetClient,
    _carry_forward_reviewed_promos,
    _delete_obsolete_version_documents,
    _existing_version_is_complete,
    _require_google_api_success,
    _review_credentials,
    _monthly_review_spreadsheet_id,
    _require_review_spreadsheet_month,
    _review_tab_titles,
    _version_for_source_hash,
    build_button_definitions,
    build_published_display_card,
    discover_source_bundle,
    fit_manychat_card_text,
    parse_review_timestamp,
    parse_review_workbook,
    required_retrieval_evaluations,
    evaluate_catalog_drafts,
    review_sheet_rows,
    validate_reviewed_catalog,
)


class _VersionSnapshot:
    def __init__(self, values: dict) -> None:
        self._values = values

    def to_dict(self) -> dict:
        return dict(self._values)


class _VersionQuery:
    def __init__(self, versions: list[dict]) -> None:
        self.versions = versions

    def where(self, *, filter: object) -> _VersionQuery:
        return self

    def stream(self) -> list[_VersionSnapshot]:
        return [_VersionSnapshot(version) for version in self.versions]


class _VersionDb:
    def __init__(self, versions: list[dict]) -> None:
        self.versions = versions

    def collection(self, name: str) -> _VersionQuery:
        return _VersionQuery(self.versions)


def test_source_hash_reuse_is_scoped_to_publication_revision() -> None:
    old_publisher = {
        "catalog_version_id": "catalog-v2-p1",
        "source_hash": "same-source",
        "catalog_schema_version": 2,
        "catalog_publication_revision": 1,
        "status": "published",
    }
    current_publisher = {
        **old_publisher,
        "catalog_version_id": "catalog-v2-p2",
        "catalog_publication_revision": CATALOG_PUBLICATION_REVISION,
        "status": "pending_review",
    }

    assert _version_for_source_hash(
        _VersionDb([old_publisher]),
        "promo_catalog_versions",
        "same-source",
    ) == {}
    assert _version_for_source_hash(
        _VersionDb([old_publisher, current_publisher]),
        "promo_catalog_versions",
        "same-source",
    )["catalog_version_id"] == "catalog-v2-p2"


def test_monthly_review_workbook_resolution_ignores_legacy_shared_files() -> None:
    db = _VersionDb(
        [
            {
                "month_folder_name": "2026-08",
                "spreadsheet_id": "legacy-shared",
                "created_at": "2026-08-01T00:00:00+08:00",
            },
            {
                "month_folder_name": "2026-08",
                "spreadsheet_id": "august-v1",
                "review_workbook_scope": "monthly",
                "review_workbook_month": "2026-08",
                "created_at": "2026-08-02T00:00:00+08:00",
            },
            {
                "month_folder_name": "2026-08",
                "spreadsheet_id": "august-current",
                "review_workbook_scope": "monthly",
                "review_workbook_month": "2026-08",
                "created_at": "2026-08-03T00:00:00+08:00",
            },
        ]
    )

    assert (
        _monthly_review_spreadsheet_id(db, "promo_catalog_versions", "2026-08")
        == "august-current"
    )


def test_review_workbook_cannot_mix_catalog_months() -> None:
    _require_review_spreadsheet_month(
        [{"month_folder_name": "2026-08"}],
        "2026-08",
    )

    with pytest.raises(ValueError, match="different catalog month: '2026-07'"):
        _require_review_spreadsheet_month(
            [
                {"month_folder_name": "2026-08"},
                {"month_folder_name": "2026-07"},
            ],
            "2026-08",
        )


def test_source_discovery_accepts_a_folder_that_is_already_the_month_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    images_folder = DriveItem("images", "Promo Images", "application/vnd.google-apps.folder")
    mechanics_folder = DriveItem("mechanics", "Promo Mechanics", "application/vnd.google-apps.folder")
    mechanics = DriveItem(
        "docx",
        "AUGUST 2026 PROMO MECHANICS.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    poster = DriveItem("poster", "The Gulong Double Warranty.png", "image/png")

    class _Drive:
        def __init__(self, service_account_email: str) -> None:
            assert service_account_email == "promo@example.com"

        def list_children(self, folder_id: str) -> list[DriveItem]:
            return {
                "month-root": [images_folder, mechanics_folder],
                "images": [poster],
                "mechanics": [mechanics],
            }[folder_id]

        def download(self, item: DriveItem) -> bytes:
            return b"mechanics" if item.file_id == "docx" else b"poster"

    monkeypatch.setattr(promo_catalog_sync, "DriveApiSource", _Drive)
    monkeypatch.setattr(
        promo_catalog_sync,
        "extract_docx_paragraphs",
        lambda payload: ["THE GULONG DOUBLE WARRANTY"],
    )
    bundle = discover_source_bundle(
        SimpleNamespace(
            drive_service_account="promo@example.com",
            drive_source_folder_id="month-root",
            month_folder_name="2026-08",
            images_folder_name="Promo Images",
            mechanics_folder_name="Promo Mechanics",
        )
    )

    assert bundle.month_name == "2026-08"
    assert bundle.mechanics_item == mechanics
    assert [image.item for image in bundle.images] == [poster]


class _Document:
    def __init__(self, document_id: str) -> None:
        self.id = document_id
        self.reference = document_id


class _Collection:
    def __init__(self, document_ids: list[str]) -> None:
        self.document_ids = document_ids

    def where(self, *, filter: object) -> _Collection:
        return self

    def stream(self) -> list[_Document]:
        return [_Document(document_id) for document_id in self.document_ids]


class _DeleteBatch:
    def __init__(self, deleted: list[str]) -> None:
        self.deleted = deleted
        self.pending: list[str] = []

    def delete(self, reference: str) -> None:
        self.pending.append(reference)

    def commit(self) -> None:
        self.deleted.extend(self.pending)


class _DeleteDb:
    def __init__(self, document_ids: list[str]) -> None:
        self.document_ids = document_ids
        self.deleted: list[str] = []

    def collection(self, name: str) -> _Collection:
        return _Collection(self.document_ids)

    def batch(self) -> _DeleteBatch:
        return _DeleteBatch(self.deleted)


def test_obsolete_draft_documents_are_deleted_before_activation() -> None:
    db = _DeleteDb(["catalog-v2-reviewed", "catalog-v2-ai-typo"])

    deleted = _delete_obsolete_version_documents(
        db,
        collection="promo_catalog_cards",
        version_id="catalog-v2",
        keep_document_ids={"catalog-v2-reviewed"},
    )

    assert deleted == 1
    assert db.deleted == ["catalog-v2-ai-typo"]


def test_cloud_run_job_executes_catalog_sync_as_module() -> None:
    config = (
        Path(__file__).resolve().parents[1] / "cloudbuild.promo-catalog-infra.yaml"
    ).read_text(encoding="utf-8")

    assert "--args=-m,scripts.promo_catalog_sync,sync" in config
    assert "--args=scripts/promo_catalog_sync.py,sync" not in config
    assert "--remove-secrets=PROMO_REVIEW_GOOGLE_OAUTH_JSON" in config
    assert '_REVIEW_SPREADSHEET_ID: ""' in config
    assert "_IMAGE_TAG: staging-latest" in config
    assert "gulong-chatbot-runtime:${_IMAGE_TAG}" in config
    assert "1MPFt1ievuiHYAKW3EguTOvAPidT7oiJRwGCYlbE0luk" not in config


class _Response:
    def __init__(self, payload: dict | None = None, *, ok: bool = True, text: str = "") -> None:
        self.ok = ok
        self.status_code = 200 if ok else 400
        self.text = text
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class _ReviewSession:
    def __init__(self, *, existing: bool = False) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.existing = existing
        self.sheet_titles = ["Sheet1"] if existing else []

    def post(self, url: str, *, json: dict, timeout: int) -> _Response:
        self.calls.append(("POST", url, json))
        if url == SHEETS_API:
            return _Response(
                {
                    "spreadsheetId": "sheet-1",
                    "sheets": [
                        {"properties": {"sheetId": index, "title": tab}}
                        for index, tab in enumerate(REVIEW_TABS)
                    ],
                }
            )
        if url.endswith(":batchUpdate"):
            for request in json.get("requests") or []:
                renamed = request.get("updateSheetProperties") or {}
                renamed_properties = renamed.get("properties") or {}
                if renamed_properties.get("title"):
                    sheet_id = int(renamed_properties["sheetId"])
                    self.sheet_titles[sheet_id] = renamed_properties["title"]
                title = ((request.get("addSheet") or {}).get("properties") or {}).get("title")
                if title:
                    self.sheet_titles.append(title)
        return _Response()

    def get(self, url: str, *, params: dict, timeout: int) -> _Response:
        self.calls.append(("GET", url, params))
        if url.startswith(SHEETS_API):
            return _Response(
                {
                    "spreadsheetId": "sheet-1",
                    "sheets": [
                        {"properties": {"sheetId": index, "title": title}}
                        for index, title in enumerate(self.sheet_titles)
                    ],
                }
            )
        return _Response(
            {
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "parents": ["folder-1"] if self.existing else [],
                "capabilities": {"canEdit": True},
            }
        )

    def patch(self, url: str, *, params: dict, json: dict, timeout: int) -> _Response:
        self.calls.append(("PATCH", url, {"params": params, "json": json}))
        return _Response()


def test_review_sheet_uses_supported_locale_and_manila_timezone() -> None:
    client = object.__new__(GoogleReviewSheetClient)
    session = _ReviewSession()
    client._session = session

    result = client.create_review_sheet(
        title="Review",
        review_folder_id="folder-1",
        tab_rows={tab: [["header"]] for tab in REVIEW_TABS},
    )

    properties = session.calls[0][2]["properties"]
    assert properties == {"title": "Review", "locale": "en_US", "timeZone": "Asia/Manila"}
    assert result["review_spreadsheet_url"].endswith("/sheet-1/edit")


def test_owner_created_bootstrap_sheet_gets_required_tabs_and_is_cleared() -> None:
    client = object.__new__(GoogleReviewSheetClient)
    session = _ReviewSession(existing=True)
    client._session = session

    result = client.create_review_sheet(
        title="Ignored for existing workbook",
        review_folder_id="folder-1",
        spreadsheet_id="sheet-1",
        tab_rows={tab: [["header"]] for tab in REVIEW_TABS},
    )

    assert set(session.sheet_titles) == set(REVIEW_TABS)
    assert any(url.endswith("/values:batchClear") for _, url, _ in session.calls)
    assert not any(method == "POST" and url == SHEETS_API for method, url, _ in session.calls)
    assert result["spreadsheet_id"] == "sheet-1"


def test_shared_review_sheet_archives_completed_version_tabs_before_reuse() -> None:
    client = object.__new__(GoogleReviewSheetClient)
    session = _ReviewSession(existing=True)
    session.sheet_titles = [tab for tab in REVIEW_TABS if tab != "Eligibility"]
    client._session = session

    client.create_review_sheet(
        title="Ignored for existing workbook",
        review_folder_id="folder-1",
        spreadsheet_id="sheet-1",
        archive_prefix="v1-3574297cf6ef",
        tab_rows={tab: [["header"]] for tab in REVIEW_TABS},
    )

    assert set(REVIEW_TABS).issubset(session.sheet_titles)
    assert {
        f"v1-3574297cf6ef {tab}" for tab in REVIEW_TABS if tab != "Eligibility"
    }.issubset(session.sheet_titles)
    assert any(url.endswith("/values:batchClear") for _, url, _ in session.calls)


def test_review_refresh_creates_visible_tabs_before_hiding_the_archive() -> None:
    client = object.__new__(GoogleReviewSheetClient)
    session = _ReviewSession(existing=True)
    session.sheet_titles = list(REVIEW_TABS)
    client._session = session

    client.create_review_sheet(
        title="Ignored for existing workbook",
        review_folder_id="folder-1",
        spreadsheet_id="sheet-1",
        archive_prefix="v1-previous",
        tab_rows={tab: [["header"]] for tab in REVIEW_TABS},
    )

    batch_payloads = [
        payload
        for _, url, payload in session.calls
        if url.endswith(":batchUpdate")
    ]
    add_tabs_batch = next(
        index
        for index, payload in enumerate(batch_payloads)
        if any("addSheet" in request for request in payload.get("requests") or [])
    )
    hide_archive_batch = next(
        index
        for index, payload in enumerate(batch_payloads)
        if any(
            (request.get("updateSheetProperties") or {}).get("properties", {}).get("hidden") is True
            and (request.get("updateSheetProperties") or {}).get("fields") == "hidden"
            for request in payload.get("requests") or []
        )
    )

    assert add_tabs_batch < hide_archive_batch


def test_month_review_tabs_put_an_explicit_approval_tab_in_front() -> None:
    client = object.__new__(GoogleReviewSheetClient)
    session = _ReviewSession(existing=True)
    session.sheet_titles = list(REVIEW_TABS)
    client._session = session

    client.create_review_sheet(
        title="Ignored for existing workbook",
        review_folder_id="folder-1",
        spreadsheet_id="sheet-1",
        archive_prefix="ARCHIVE JUL 2026 v2-example",
        month_name="2026-08",
        archive_month_name="2026-07",
        tab_rows={tab: [["header"]] for tab in REVIEW_TABS},
    )

    august_titles = _review_tab_titles("2026-08")
    assert august_titles["Version"] == "AUG 2026 APPROVAL - START HERE"
    assert set(august_titles.values()).issubset(session.sheet_titles)
    assert {
        f"ARCHIVE JUL 2026 v2-example {tab}" for tab in REVIEW_TABS
    }.issubset(session.sheet_titles)
    property_updates = [
        request["updateSheetProperties"]
        for _, url, payload in session.calls
        if url.endswith(":batchUpdate")
        for request in payload.get("requests") or []
        if "updateSheetProperties" in request
    ]
    assert any(
        update["properties"].get("index") == 0
        and "tabColorStyle" in update["properties"]
        for update in property_updates
    )


def test_unchanged_source_keeps_published_review_values_and_new_eligibility() -> None:
    extracted = _promo()
    extracted = PromoCard(
        **{
            **extracted.__dict__,
            "promo_id": "michelin-typo-id",
            "title": "MICHELN 3+1 PROMO",
            "valid_from": "",
            "valid_until": "",
            "eligibility": {**extracted.eligibility, "confidence": "medium"},
        }
    )
    carried = _carry_forward_reviewed_promos(
        [extracted],
        prior_cards=[
            {
                "promo_id": "michelin-3plus1",
                "title": "Michelin 3+1 Promo",
                "brands": ["Michelin"],
                "promo_type": "buy_3_get_1",
                "offer_summary": "Reviewed offer.",
                "valid_from": "2026-07-15",
                "valid_until": "2026-07-31",
                "source_evidence": ["MICHELIN 3+1 mechanics source"],
                "display_order": 1,
                "display_cards": [{"source_image_name": "michelin.jpg"}],
            }
        ],
        mechanics_by_promo={
            "michelin-3plus1": [
                {"ordinal": 1, "chunk_id": "m1", "text": "Reviewed mechanics."}
            ]
        },
    )

    assert carried[0].promo_id == "michelin-3plus1"
    assert carried[0].title == "Michelin 3+1 Promo"
    assert carried[0].valid_from == "2026-07-15"
    assert carried[0].valid_until == "2026-07-31"
    assert carried[0].mechanics == ["Reviewed mechanics."]
    assert carried[0].eligibility["confidence"] == "medium"


def test_authorized_user_review_credentials_require_refresh_fields() -> None:
    with pytest.raises(ValueError, match="refresh_token"):
        _review_credentials(
            "promo@example.iam.gserviceaccount.com",
            '{"client_id":"client","client_secret":"secret"}',
        )

    credentials = _review_credentials(
        "promo@example.iam.gserviceaccount.com",
        '{"client_id":"client","client_secret":"secret","refresh_token":"refresh",'
        '"token_uri":"https://oauth2.googleapis.com/token"}',
    )
    assert credentials.refresh_token == "refresh"


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ({}, False),
        ({"status": "pending_review"}, False),
        ({"status": "pending_review", "spreadsheet_id": "sheet-1"}, True),
        ({"status": "published"}, True),
        ({"status": "superseded"}, True),
    ],
)
def test_existing_version_is_complete_only_after_review_artifact(
    version: dict, expected: bool
) -> None:
    assert _existing_version_is_complete(version) is expected


def test_google_api_error_keeps_response_body() -> None:
    with pytest.raises(RuntimeError, match="Unsupported locale: en_PH"):
        _require_google_api_success(
            _Response(ok=False, text='{"error":{"message":"Unsupported locale: en_PH"}}'),
            "create review spreadsheet",
        )


def test_manychat_review_default_preserves_original_and_fits_limit() -> None:
    original = (
        "Get a chance to win 1 ticket to the Michelin Passion Experience event in "
        "Oita, Japan, including round-trip airfares, hotel, event access, and more."
    )

    shortened = fit_manychat_card_text(original)

    assert len(shortened) <= 80
    assert shortened.endswith("...")
    assert original.startswith(shortened[:-3])


@pytest.mark.parametrize(
    "value",
    ["2026-07-20T08:58:11+08:00", "7/20/2026 8:58:11"],
)
def test_review_timestamp_is_normalized_to_manila(value: str) -> None:
    parsed = parse_review_timestamp(value)

    assert parsed.isoformat() == "2026-07-20T08:58:11+08:00"


def test_review_timestamp_rejects_unparseable_value() -> None:
    with pytest.raises(ValueError, match="reviewed_at"):
        parse_review_timestamp("yesterday morning")


def _promo() -> PromoCard:
    return PromoCard(
        promo_id="michelin-3plus1",
        title="Michelin 3+1 Promo",
        brands=["Michelin"],
        promo_type="buy_3_get_1",
        offer_summary="Buy 3, get 1 free.",
        mechanics=["Buy three eligible Michelin tires and get one eligible tire free."],
        valid_from="2026-07-01",
        valid_until="2026-07-31",
        source_evidence=["MICHELIN 3+1 mechanics source"],
        image_source_names=["michelin.jpg"],
        eligibility={
            "scope": "all_brand_products",
            "included_brands": ["Michelin"],
            "excluded_brands": [],
            "included_patterns": [],
            "excluded_patterns": [],
            "included_sizes": [],
            "excluded_sizes": [],
            "qualifying_quantity": 3,
            "free_quantity": 1,
            "confidence": "high",
            "source_evidence": ["MICHELIN 3+1 mechanics source"],
        },
    )


def _approved_workbook() -> tuple[dict, dict]:
    promo = _promo()
    rows = review_sheet_rows(
        version_id="catalog-v1",
        source_hash="source-hash",
        source_file_name="mechanics.docx",
        promos=[promo],
        cards=[
            {
                "card_id": "michelin-3plus1-card-1",
                "promo_id": promo.promo_id,
                "display_order": 1,
                "source_image_name": "michelin.jpg",
                "title": promo.title,
                "subtitle": promo.offer_summary,
                "enabled": True,
                "button_policy": "single_brand",
                "evidence": promo.source_evidence[0],
            }
        ],
        mechanics=[
            {
                "mechanic_id": "michelin-3plus1-mechanic-1",
                "promo_id": promo.promo_id,
                "ordinal": 1,
                "text": promo.mechanics[0],
                "enabled": True,
                "evidence": promo.source_evidence[0],
            }
        ],
        brand_profiles={
            "Michelin": {
                "summary": "Michelin has one reviewed current 3+1 offer.",
                "positioning": ["Buy 3, get 1 free."],
                "source_evidence": promo.source_evidence,
            }
        },
    )
    for row in rows["Version"]:
        if row[0] == "review_status":
            row[2] = "APPROVED"
        elif row[0] == "reviewed_by":
            row[2] = "marketing@example.com"
        elif row[0] == "reviewed_at":
            row[2] = "2026-07-20T10:00:00+08:00"
    for row in rows["Evaluation"][1:]:
        row[5] = "PASS"
    for row in rows["Eligibility"][1:]:
        row[21] = "PASS"
    version = {
        "catalog_version_id": "catalog-v1",
        "source_hash": "source-hash",
        "image_manifest": {"michelin.jpg": {"sha256": "abc", "suffix": ".jpg"}},
    }
    return rows, version


def test_review_sheet_values_are_authoritative_and_corrections_are_audited() -> None:
    workbook, version = _approved_workbook()
    workbook["Promos"][1][3] = "Reviewed Michelin 3+1"

    reviewed = parse_review_workbook(workbook)
    validate_reviewed_catalog(version, reviewed)

    assert reviewed["promos"][0]["title"] == "Reviewed Michelin 3+1"
    correction = reviewed["promos"][0]["corrections"][0]
    assert correction["original_value"] == "Michelin 3+1 Promo"
    assert correction["reviewed_value"] == "Reviewed Michelin 3+1"
    assert correction["source_evidence"]


def test_publication_validation_fails_closed_on_evaluation_gap() -> None:
    workbook, version = _approved_workbook()
    workbook["Evaluation"][1][5] = "PENDING"

    with pytest.raises(ValueError, match="evaluation is incomplete"):
        validate_reviewed_catalog(version, parse_review_workbook(workbook))


def test_publication_validation_allows_source_backed_brandless_warranty() -> None:
    workbook, version = _approved_workbook()
    promo_row = workbook["Promos"][1]
    promo_row[4] = ""
    promo_row[5] = ""
    promo_row[6] = "warranty"
    promo_row[7] = "warranty"
    workbook["Cards"][1][9] = "multi_brand"
    eligibility_row = workbook["Eligibility"][1]
    eligibility_row[4] = ""
    eligibility_row[5] = ""

    validate_reviewed_catalog(version, parse_review_workbook(workbook))


def test_publication_validation_rejects_brandless_commercial_promo() -> None:
    workbook, version = _approved_workbook()
    workbook["Promos"][1][4] = ""
    workbook["Promos"][1][5] = ""

    with pytest.raises(ValueError, match="is missing brands"):
        validate_reviewed_catalog(version, parse_review_workbook(workbook))


def test_retrieval_evaluations_follow_current_catalog_content() -> None:
    promos = [
        {
            "promo_id": "bfgoodrich-1000-off",
            "title": "BFGoodrich PHP 1,000 Off",
            "brands": ["BFGoodrich"],
            "promo_type": "fixed_discount",
            "enabled": True,
        },
        {
            "promo_id": "michelin-cashback",
            "title": "Michelin PHP 1,000 Cashback",
            "brands": ["Michelin"],
            "promo_type": "cashback",
            "enabled": True,
        },
        {
            "promo_id": "michelin-3plus1",
            "title": "Michelin 3+1",
            "brands": ["Michelin"],
            "promo_type": "buy_3_get_1",
            "enabled": True,
        },
        {
            "promo_id": "apollo-3plus1",
            "title": "Apollo 3+1",
            "brands": ["Apollo"],
            "promo_type": "buy_3_get_1",
            "enabled": True,
        },
    ]

    cases = required_retrieval_evaluations(promos)
    case_ids = {case.evaluation_id for case in cases}

    assert case_ids == {
        "promo_bfgoodrich-1000-off",
        "promo_michelin-cashback",
        "promo_michelin-3plus1",
        "promo_apollo-3plus1",
        "brand_michelin",
        "generic_3plus1",
        "unavailable_brand_3plus1",
        "expired_promos",
        "unrelated",
    }
    assert "michelin_japan" not in case_ids
    assert "yokohama_6000" not in case_ids
    negative = next(
        case for case in cases if case.evaluation_id == "unavailable_brand_3plus1"
    )
    assert negative.negative_brand == "Bridgestone"
    assert set(negative.target_promo_ids) == {
        "michelin-3plus1",
        "apollo-3plus1",
    }


def test_retrieval_evaluation_applies_explicit_offer_constraints() -> None:
    class _Embedder:
        def embed(self, text: str, *, task_type: str) -> list[float]:
            return [1.0, 0.0]

    common = {
        "enabled": True,
        "valid_from": "2026-08-01",
        "valid_until": "2026-08-31",
        "mechanics": [],
        "retrieval_aliases": [],
    }
    promos = [
        {
            **common,
            "promo_id": "michelin-3plus1",
            "title": "Michelin 3+1",
            "brands": ["Michelin"],
            "promo_type": "buy_3_get_1",
            "offer_summary": "Buy 3 get 1 free.",
            "display_order": 1,
            "embedding_values": [0.0, 1.0],
        },
        {
            **common,
            "promo_id": "apollo-3plus1",
            "title": "Apollo 3+1",
            "brands": ["Apollo"],
            "promo_type": "buy_3_get_1",
            "offer_summary": "Buy 3 get 1 free.",
            "display_order": 2,
            "embedding_values": [0.0, 1.0],
        },
        {
            **common,
            "promo_id": "michelin-cashback",
            "title": "Michelin PHP 1,000 Cashback",
            "brands": ["Michelin"],
            "promo_type": "cashback",
            "offer_summary": "PHP 1,000 cashback per eligible tire.",
            "display_order": 3,
            "embedding_values": [1.0, 0.0],
        },
    ]

    results = evaluate_catalog_drafts(
        promos=promos,
        embedder=_Embedder(),
        today=date(2026, 8, 1),
    )

    negative = results["unavailable_brand_3plus1"]
    assert negative["ai_status"] == "AI_PASS"
    assert "michelin-cashback" not in negative["observed"]


def test_single_two_and_multi_brand_button_policies() -> None:
    single = build_button_definitions(
        version_id="catalog-v1",
        promo_id="promo-1",
        card_id="card-1",
        brands=["Michelin"],
        flow_namespaces={
            "staging": "content-staging-promo-router",
            "live": "content-live-promo-router",
        },
    )
    two = build_button_definitions(
        version_id="catalog-v1",
        promo_id="promo-2",
        card_id="card-2",
        brands=["Michelin", "Yokohama"],
        flow_namespaces={
            "staging": "content-staging-promo-router",
            "live": "content-live-promo-router",
        },
    )
    many = build_button_definitions(
        version_id="catalog-v1",
        promo_id="promo-3",
        card_id="card-3",
        brands=["Michelin", "Yokohama", "Apollo"],
        flow_namespaces={
            "staging": "content-staging-promo-router",
            "live": "content-live-promo-router",
        },
    )

    assert [button["caption"] for button in single] == ["Check Price", "Promo Details", "About Brand"]
    assert [button["caption"] for button in two] == ["Michelin", "Yokohama", "Promo Details"]
    assert [button["caption"] for button in many] == ["Choose Brand", "Promo Details"]
    assert all(button["type"] == "flow" and "action_url" not in button for button in [*single, *two, *many])
    assert all(
        button["targets"]
        == {"staging": "content-staging-promo-router", "live": "content-live-promo-router"}
        for button in [*single, *two, *many]
    )
    assert all(len(button["actions"]) == 1 for button in [*single, *two, *many])
    assert all(button["actions"][0]["field_name"] == "promo_selected_id" for button in [*single, *two, *many])
    assert all(button["actions"][0]["value"].startswith("pc1|") for button in [*single, *two, *many])


def test_double_warranty_uses_find_tires_for_generic_discovery() -> None:
    buttons = build_button_definitions(
        version_id="catalog-v1",
        promo_id="the-gulong-double-warranty",
        card_id="double-warranty-card",
        brands=[],
        flow_namespaces={
            "staging": "content-staging-promo-router",
            "live": "content-live-promo-router",
        },
    )

    assert [button["caption"] for button in buttons] == [
        "Find Tires",
        "Promo Details",
    ]
    assert buttons[0]["action"] == "choose_brand"
    assert buttons[0]["selected_brand"] == ""


def test_published_card_keeps_gcs_provenance_and_durable_https_url() -> None:
    card = build_published_display_card(
        version_id="catalog-v1",
        promo={"promo_id": "promo-1", "brands": ["Michelin"]},
        card={
            "card_id": "card-1",
            "display_order": 1,
            "title": "Promo",
            "subtitle": "Mechanics summary",
            "source_image_name": "promo.jpg",
        },
        media={
            "source_gcs_uri": "gs://private/source.jpg",
            "public_gcs_uri": "gs://public/catalog/v1/source.jpg",
            "image_url": "https://storage.googleapis.com/public/catalog/v1/source.jpg",
        },
        flow_namespaces={
            "staging": "content-staging-promo-router",
            "live": "content-live-promo-router",
        },
    )

    assert card["source_gcs_uri"].startswith("gs://")
    assert card["public_gcs_uri"].startswith("gs://")
    assert card["image_url"].startswith("https://storage.googleapis.com/")
    assert "?" not in card["image_url"]
