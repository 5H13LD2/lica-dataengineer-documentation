from io import BytesIO
from unittest.mock import Mock
from zipfile import ZipFile

import scripts.promo_vector_trial as promo_vector_trial
from scripts.promo_vector_trial import (
    DriveItem,
    VertexEmbedder,
    chunk_paragraphs,
    extract_docx_paragraphs,
    repair_mojibake,
    require_named_item,
)


def test_require_named_item_is_case_insensitive():
    items = [
        DriveItem(file_id="folder-one", name="Promo Source", mime_type="application/vnd.google-apps.folder"),
        DriveItem(file_id="folder-two", name="Promo Catalog Reviews", mime_type="application/vnd.google-apps.folder"),
    ]

    assert require_named_item(items, "promo source").file_id == "folder-one"


def test_extract_docx_paragraphs_and_chunking_preserve_source_text():
    document = BytesIO()
    with ZipFile(document, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>MICHELIN PROMO</w:t></w:r></w:p>
                <w:p><w:r><w:t>Buy three tires and get one free.</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """,
        )

    paragraphs = extract_docx_paragraphs(document.getvalue())
    chunks = chunk_paragraphs(paragraphs, max_characters=80, overlap_characters=20)

    assert paragraphs == ["MICHELIN PROMO", "Buy three tires and get one free."]
    assert len(chunks) == 1
    assert "get one free" in chunks[0].text
    assert len(chunks[0].content_hash) == 64


def test_vertex_embedder_impersonates_configured_service_account(monkeypatch):
    source_credentials = Mock()
    target_credentials = Mock()
    impersonate = Mock(return_value=target_credentials)
    session = Mock()

    monkeypatch.setattr(promo_vector_trial.google.auth, "default", Mock(return_value=(source_credentials, "project")))
    monkeypatch.setattr(promo_vector_trial.impersonated_credentials, "Credentials", impersonate)
    monkeypatch.setattr(promo_vector_trial, "AuthorizedSession", Mock(return_value=session))

    embedder = VertexEmbedder(
        "gulong-chatbot-459723",
        service_account_email="promo-catalog-bot@gulong-chatbot-459723.iam.gserviceaccount.com",
    )

    impersonate.assert_called_once_with(
        source_credentials=source_credentials,
        target_principal="promo-catalog-bot@gulong-chatbot-459723.iam.gserviceaccount.com",
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        lifetime=3600,
    )
    target_credentials.refresh.assert_called_once()
    assert embedder._session is session


def test_repair_mojibake_preserves_valid_text():
    assert repair_mojibake("Get â‚±6,000 off. It wonâ€™t apply to one tire.") == "Get ₱6,000 off. It won’t apply to one tire."
    assert repair_mojibake("Get ₱6,000 off.") == "Get ₱6,000 off."
