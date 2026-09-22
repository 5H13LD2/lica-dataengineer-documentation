import json

import pytest

from scripts.promo_catalog_builder import build_parent_text, build_retrieval_aliases, parse_catalog_response


SOURCE = "MICHELIN 3+1 PROMO\nBuy three Michelin tires and get one free.\nValid until July 31, 2026."


def test_parse_catalog_response_requires_source_evidence_and_known_images():
    raw = json.dumps(
        {
            "promos": [
                {
                    "title": "Michelin 3+1 Promo",
                    "brands": ["Michelin"],
                    "promo_type": "buy_3_get_1",
                    "offer_summary": "Buy three tires and get one free.",
                    "mechanics": ["Buy three Michelin tires and get one free."],
                    "valid_from": "",
                    "valid_until": "2026-07-31",
                    "source_evidence": ["Buy three Michelin tires and get one free."],
                    "image_source_names": ["michelin-3-plus-1.jpg"],
                }
            ]
        }
    )

    cards = parse_catalog_response(raw, source_text=SOURCE, allowed_image_names=["michelin-3-plus-1.jpg"])

    assert cards[0].promo_id == "michelin-3-1-promo"
    assert "Promo type: buy_3_get_1" in build_parent_text(cards[0])
    assert "buy three get one" in build_retrieval_aliases(cards[0])


def test_parse_catalog_response_rejects_unsupported_evidence():
    raw = json.dumps(
        {
            "promos": [
                {
                    "title": "Michelin 3+1 Promo",
                    "brands": ["Michelin"],
                    "promo_type": "buy_3_get_1",
                    "offer_summary": "Buy three tires and get one free.",
                    "mechanics": ["Buy three Michelin tires and get one free."],
                    "source_evidence": ["Invented promotion terms."],
                    "image_source_names": [],
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="not present"):
        parse_catalog_response(raw, source_text=SOURCE, allowed_image_names=[])


def test_parse_catalog_response_maps_model_evidence_indexes_to_source_text():
    raw = json.dumps(
        {
            "promos": [
                {
                    "title": "Michelin 3+1 Promo",
                    "brands": ["Michelin"],
                    "promo_type": "buy_3_get_1",
                    "offer_summary": "Buy three tires and get one free.",
                    "mechanics": ["Buy three Michelin tires and get one free."],
                    "source_evidence_indices": [2, 3],
                    "image_source_names": [],
                }
            ]
        }
    )

    cards = parse_catalog_response(
        raw,
        source_text=SOURCE,
        source_paragraphs=SOURCE.splitlines(),
        allowed_image_names=[],
    )

    assert cards[0].source_evidence == ["Buy three Michelin tires and get one free.", "Valid until July 31, 2026."]


def test_parse_catalog_response_allows_brandless_warranty_content():
    source = "THE GULONG DOUBLE WARRANTY\nManufacturer warranty plus Gulong tire protection warranty."
    raw = json.dumps(
        {
            "promos": [
                {
                    "title": "The Gulong Double Warranty",
                    "brands": [],
                    "promo_type": "warranty",
                    "offer_summary": "Two layers of warranty coverage.",
                    "mechanics": ["Manufacturer warranty plus Gulong tire protection warranty."],
                    "source_evidence_indices": [2],
                    "image_source_names": [],
                    "eligibility": {
                        "scope": "all_brand_products",
                        "included_brands": [],
                        "confidence": "high",
                        "source_evidence_indices": [2],
                    },
                }
            ]
        }
    )

    cards = parse_catalog_response(
        raw,
        source_text=source,
        source_paragraphs=source.splitlines(),
        allowed_image_names=[],
    )

    assert cards[0].promo_type == "warranty"
    assert cards[0].brands == []
    assert cards[0].eligibility["included_brands"] == []


def test_parse_catalog_response_preserves_cashback_as_distinct_from_discount():
    source = "MICHELIN CASHBACK\nReceive PHP 1,000 cashback after an approved claim."
    raw = json.dumps(
        {
            "promos": [
                {
                    "title": "Michelin Cashback",
                    "brands": ["Michelin"],
                    "promo_type": "cashback",
                    "offer_summary": "Receive PHP 1,000 cashback.",
                    "mechanics": [
                        "Receive PHP 1,000 cashback after an approved claim."
                    ],
                    "source_evidence_indices": [2],
                    "image_source_names": [],
                }
            ]
        }
    )

    cards = parse_catalog_response(
        raw,
        source_text=source,
        source_paragraphs=source.splitlines(),
        allowed_image_names=[],
    )

    assert cards[0].promo_type == "cashback"
    assert "Promo type: cashback" in build_parent_text(cards[0])


def test_parse_catalog_response_preserves_exact_operational_urls() -> None:
    form_url = "https://docs.google.com/forms/d/e/example/viewform?usp=header"
    source = "\n".join(
        [
            "MICHELIN CASHBACK",
            "Receive PHP 1,000 cashback after an approved claim.",
            f"Complete the Google Form: {form_url}, then submit the requirements.",
            "Source and Review Notes",
            f"Confirmed form: {form_url}.",
        ]
    )
    raw = json.dumps(
        {
            "promos": [
                {
                    "title": "Michelin Cashback",
                    "brands": ["Michelin"],
                    "promo_type": "cashback",
                    "offer_summary": "Receive PHP 1,000 cashback.",
                    "mechanics": ["Complete the Google Form, then submit the requirements."],
                    "source_evidence_indices": [2, 3],
                    "image_source_names": [],
                }
            ]
        }
    )

    cards = parse_catalog_response(
        raw,
        source_text=source,
        source_paragraphs=source.splitlines(),
        allowed_image_names=[],
    )

    assert cards[0].mechanics[-1] == f"Promo submission form: {form_url}"
    assert sum(form_url in mechanic for mechanic in cards[0].mechanics) == 1
