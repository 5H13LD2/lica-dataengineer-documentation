from scripts.manychat_promo_fields import RequiredField, inspect_required_fields


def test_manychat_fields_reuse_matching_names_and_types() -> None:
    inspection = inspect_required_fields(
        [
            {"id": "14765453", "name": "promo_catalog_version", "type": "text"},
            {"id": "200", "name": "promo_gallery_show_count", "type": "number"},
        ],
        required_fields=[
            RequiredField("promo_catalog_version", "text", ""),
            RequiredField("promo_gallery_show_count", "number", ""),
        ],
    )

    assert not inspection["missing"]
    assert not inspection["conflicts"]
    assert inspection["found"][0]["reuses_known_flow_field_id"] is True


def test_manychat_fields_report_type_conflict_instead_of_reusing_it() -> None:
    inspection = inspect_required_fields(
        [{"id": "14765454", "name": "promo_gallery_last_shown_at", "type": "text"}],
        required_fields=[RequiredField("promo_gallery_last_shown_at", "datetime", "")],
    )

    assert not inspection["found"]
    assert inspection["conflicts"][0]["actual_type"] == "text"
