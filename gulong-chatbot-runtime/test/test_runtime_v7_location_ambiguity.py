from runtime_v7.installation_partners import FindInstallationPartnersTool
from runtime_v7.location_resolution import (
    RuntimeV7LocationResolver,
    compact_location_resolution,
    location_display_label,
)
from runtime_v7.model_contract import build_runtime_v7_context, build_tool_objectives
from runtime_v7.state_signal_normalization import _canonical_location_with_metadata


class DuplicateCityCatalogClient:
    def get_json(self, path, *, params=None):
        if path == "/get_province":
            return [
                {"PROV_CODE": "PH-PLW", "PROV_NAME": "PALAWAN", "REGION_CODE": "04B"},
                {"PROV_CODE": "PH-RIZ", "PROV_NAME": "RIZAL", "REGION_CODE": "04A"},
                {"PROV_CODE": "PH-CAV", "PROV_NAME": "CAVITE", "REGION_CODE": "04A"},
            ]
        if path == "/get_city":
            return [
                {"CITY_CODE": "PH-PLW-TAY", "CITY_NAME": "TAYTAY", "PROV_CODE": "PH-PLW"},
                {"CITY_CODE": "PH-RIZ-TAY", "CITY_NAME": "TAYTAY", "PROV_CODE": "PH-RIZ"},
                {"CITY_CODE": "PH-CAV-GTR", "CITY_NAME": "GENERAL TRIAS", "PROV_CODE": "PH-CAV"},
                {"CITY_CODE": "PH-CAV-CAV", "CITY_NAME": "CAVITE CITY", "PROV_CODE": "PH-CAV"},
            ]
        if path in {"/branch_list_loc", "/branch_list", "/all_branch"}:
            return [
                {
                    "id": 1,
                    "name": "TAYTAY RIZAL PARTNER",
                    "area": "Taytay",
                    "city": "Taytay",
                    "province": "Rizal",
                    "address": "Taytay, Rizal",
                    "active": True,
                },
                {
                    "id": 2,
                    "name": "TAYTAY PALAWAN PARTNER",
                    "area": "Taytay",
                    "city": "Taytay",
                    "province": "Palawan",
                    "address": "Taytay, Palawan",
                    "active": True,
                },
            ]
        return []


def _resolver():
    return RuntimeV7LocationResolver(
        http_client=DuplicateCityCatalogClient(),
        api_key="",
    )


def test_unqualified_duplicate_city_is_preserved_as_ambiguous():
    resolution = _resolver().resolve("Taga-Taytay po ako", allow_geocode=False)
    compact = compact_location_resolution(resolution)

    assert resolution["status"] == "ambiguous_city"
    assert resolution["selected_city_candidate"] is None
    assert resolution["province_hint"] is None
    assert resolution["location_precision"] == "ambiguous_city"
    assert resolution["clarification_options"] == [
        "Taytay, Palawan",
        "Taytay, Rizal",
    ]
    assert location_display_label("Taga-Taytay po ako", resolution) == "Taga-taytay Po Ako"
    assert compact["ambiguity_status"] == "ambiguous_city"


def test_explicit_duplicate_city_province_resolves_normally():
    resolution = _resolver().resolve("Taytay, Rizal", allow_geocode=False)

    assert resolution["ambiguity_status"] is None
    assert resolution["city_hint"] == "Taytay"
    assert resolution["province_hint"] == "Rizal"
    assert resolution["selected_city_candidate"]["city_code"] == "PH-RIZ-TAY"
    assert location_display_label("Taytay, Rizal", resolution) == "Taytay, Rizal"


def test_province_name_is_not_coerced_to_same_named_city():
    resolution = _resolver().resolve("Cavite", allow_geocode=False)

    assert resolution["selected_city_candidate"] is None
    assert resolution["city_hint"] is None
    assert resolution["province_hint"] == "Cavite"
    assert resolution["location_precision"] == "province_only"


def test_explicit_city_suffix_resolves_same_named_city():
    resolution = _resolver().resolve("Cavite City", allow_geocode=False)

    assert resolution["city_hint"] == "Cavite City"
    assert resolution["province_hint"] == "Cavite"
    assert resolution["location_precision"] == "city_or_area"


def test_ambiguous_location_signal_retains_options_without_service_ready_status():
    value, metadata = _canonical_location_with_metadata(
        "Taytay",
        location_resolver=_resolver(),
    )

    assert value == "Taytay"
    assert metadata["status"] == "location_ambiguous"
    assert metadata["location_resolution"]["clarification_options"] == [
        "Taytay, Palawan",
        "Taytay, Rizal",
    ]


def test_partner_tool_requires_duplicate_city_clarification():
    client = DuplicateCityCatalogClient()
    tool = FindInstallationPartnersTool(
        http_client=client,
        location_resolver=RuntimeV7LocationResolver(http_client=client, api_key=""),
    )

    result = tool.run(
        {
            "location": "Taytay",
            "service_type": "installation",
        }
    )

    assert result["status"] == "needs_location"
    assert result["installation_partners"] == []
    assert result["coverage_assessment"]["clarification_recommended"] is True
    assert result["coverage_assessment"]["location_resolution"]["clarification_options"] == [
        "Taytay, Palawan",
        "Taytay, Rizal",
    ]


def test_model_context_asks_one_specific_location_clarification():
    context = build_runtime_v7_context(
        current_user_message="Taga-Taytay po ako. Pwede installation Saturday?",
        background_signals=[
            {
                "key": "location",
                "value": "Taytay",
                "status": "mentioned_unconfirmed",
                "source": "latest_user_message",
                "resolution": {
                    "status": "ambiguous_location",
                    "display_label": "Taytay",
                    "location_precision": "ambiguous_city",
                    "clarification_options": [
                        "Taytay, Palawan",
                        "Taytay, Rizal",
                    ],
                },
            },
            {
                "key": "service_type",
                "value": "installation",
                "status": "mentioned_unconfirmed",
                "source": "latest_user_message",
            },
            {
                "key": "chosen_schedule_slot",
                "value": "Saturday",
                "status": "mentioned_unconfirmed",
                "source": "latest_user_message",
            },
        ],
        capability_profile={
            "selected_domains": ["service"],
            "exposed_tools": ["find_installation_slots", "request_capability"],
        },
    )

    assert "location clarification needed" in context
    assert "Taytay, Palawan, or Taytay, Rizal" in context
    assert "slot lookup ready" not in context
    assert "continue any independent product, price, promo" in context


def test_compound_product_preference_remains_primary_during_location_clarification():
    signals = [
        {
            "key": "tire_size",
            "value": "195/60R15",
            "source": "latest_user_message",
        },
        {
            "key": "tire_category_preference",
            "value": "Budget",
            "source": "latest_user_message",
        },
        {
            "key": "location",
            "value": "Taytay",
            "source": "latest_user_message",
            "resolution": {
                "status": "ambiguous_location",
                "clarification_options": [
                    "Taytay, Palawan",
                    "Taytay, Rizal",
                ],
            },
        },
        {
            "key": "service_type",
            "value": "installation",
            "source": "latest_user_message",
        },
        {
            "key": "chosen_schedule_slot",
            "value": "Saturday",
            "source": "latest_user_message",
        },
    ]
    objectives = build_tool_objectives(
        background_signals=signals,
        capability_profile={
            "candidate_tools": [
                "product_search",
                "find_installation_slots",
            ],
            "exposed_tools": [
                "product_search",
                "find_installation_slots",
                "request_capability",
            ],
            "matched_signal_keys": {
                "product_search": [
                    "tire_size",
                    "tire_category_preference",
                ],
                "find_installation_slots": [
                    "location",
                    "service_type",
                    "chosen_schedule_slot",
                ],
            },
            "available_context_refs": {},
        },
    )

    product = next(row for row in objectives if row["objective"] == "product_discovery")
    service = next(row for row in objectives if row["objective"] == "service_slot_availability")
    assert product["priority"] == "primary"
    assert "blocked fulfillment detail does not block" in product["use_rule"]
    assert service["priority"] == "conditional"
