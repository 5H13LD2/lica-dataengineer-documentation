from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from runtime_v7 import api_runtime
from runtime_v7.api_runtime import RuntimeV7APIRequest
from runtime_v7.business_identity import BUSINESS_IDENTITY_EVIDENCE_REF
from runtime_v7.capability_profile import build_capability_profile
from runtime_v7.channel_renderer import render_turn_for_channel
from runtime_v7.location_choices import ServiceableLocationChoicesProvider
from runtime_v7.model_contract import (
    ALL_RUNTIME_V7_TOOL_SCHEMAS,
    RuntimeV7FinalResponseModel,
    build_tool_objectives,
)
from runtime_v7.runtime_harness import (
    RuntimeV7Harness,
    _audit_semantic_answer_goal,
    _audit_promo_fact_answer,
    _apply_validated_choice_signal_boundaries,
    _authorized_service_area_claim_scopes,
    _build_final_composer_messages,
    _build_semantic_scope_retry_messages,
    _build_customer_turn_plan,
    _enforce_renderer_owned_unit_contract,
    _complete_required_supporting_replacement_surfaces,
    _final_composer_attempt_observability,
    _final_composer_claim_contract_violations,
    _final_composer_renderer_contract_violations,
    _final_composer_request_coverage_contract_violations,
    _final_composer_service_action_contract_violations,
    _guided_location_optional_reoffer_suppressed,
    _location_tool_plan_rejection,
    _location_plan_rejection_result_status,
    _requires_provider_owned_empty_promo_result,
    _renderer_decision_layer_repair_contract,
    _safe_semantic_answer_units,
    _semantic_answer_audit_context,
    _safe_promo_fact_units,
    _sanitize_provider_owned_service_claim_prose,
    _sanitize_post_repair_provider_owned_service_copy,
    _semantic_fallback_includes_authored_answers,
    _semantic_scope_repair_base_messages,
)
from runtime_v7.service_observations import ServiceObservationStore


def test_final_composer_attempt_observability_classifies_existing_rounds() -> None:
    expected = {
        "final_composer": "initial",
        "final_composer_format_retry": "format_retry",
        "final_composer_repair": "contract_repair",
        "final_composer_repair_format_retry": "repair_format_retry",
        "final_composer_semantic_scope_repair": "semantic_scope_repair",
    }

    assert {
        round_name: _final_composer_attempt_observability(
            round_name=round_name
        )["attempt_kind"]
        for round_name in expected
    } == expected
    semantic_repair = _final_composer_attempt_observability(
        round_name="final_composer_semantic_scope_repair",
        repair_reason="semantic_scope_violations",
        violations=[
            {"type": "promo_fact_unsupported"},
            {"type": "answer_goal_unsupported"},
            {"type": "promo_fact_unsupported"},
        ],
    )
    assert semantic_repair["repair_reason"] == "semantic_scope_violations"
    assert semantic_repair["violation_types"] == [
        "answer_goal_unsupported",
        "promo_fact_unsupported",
    ]


def test_service_claim_scope_is_limited_to_one_provider_query_area() -> None:
    tool_results = [
        {
            "name": "find_installation_partners",
            "full_result": {
                "status": "ok",
                "observation_ref": "svc_obs_rosario",
                "presentation_ref": "pres_rosario",
                "query_basis": {
                    "location": "Rosario, Cavite",
                    "customer_location_label": "Rosario, Cavite",
                },
                "installation_partners": [
                    {
                        "installation_partner_ref": "ip_bacoor",
                        "municipality_city": "Bacoor, Cavite",
                    }
                ],
            },
        }
    ]

    scopes = _authorized_service_area_claim_scopes(tool_results)

    assert scopes["svc_obs_rosario"] == [
        {
            "scope_ref": "service_query_area:svc_obs_rosario",
            "queried_location": "Rosario, Cavite",
            "outcome": "partner_options_found",
            "scope_boundary": (
                "Only this queried area is authorized. Other mentioned "
                "locations require separate provider lookups."
            ),
        }
    ]
    assert scopes["pres_rosario"] == scopes["svc_obs_rosario"]


def test_service_claim_contract_rejects_missing_or_foreign_area_scope() -> None:
    plan = {
        "authorized_claim_categories": ["service_availability"],
        "authorized_evidence_refs": ["svc_obs_rosario"],
        "progression_context": {
            "authorized_evidence_refs_by_claim_category": {
                "service_availability": ["svc_obs_rosario"],
            },
            "authorized_service_area_claims_by_evidence_ref": {
                "svc_obs_rosario": [
                    {
                        "scope_ref": "service_query_area:svc_obs_rosario",
                        "queried_location": "Rosario, Cavite",
                        "outcome": "partner_options_found",
                    }
                ]
            },
        },
    }
    missing = json.dumps(
        {
            "claim_assertions": [
                {
                    "category": "service_availability",
                    "response_unit_indexes": [0],
                    "evidence_refs": ["svc_obs_rosario"],
                }
            ],
            "response_units": [
                {"type": "text", "content": {"text": "May options po."}}
            ],
        }
    )
    foreign = json.dumps(
        {
            "claim_assertions": [
                {
                    "category": "service_availability",
                    "response_unit_indexes": [0],
                    "evidence_refs": ["svc_obs_rosario"],
                    "service_area_claims": [
                        {
                            "scope_ref": "service_query_area:imus",
                            "outcome": "partner_options_found",
                        }
                    ],
                }
            ],
            "response_units": [
                {"type": "text", "content": {"text": "May options po."}}
            ],
        }
    )
    valid = json.dumps(
        {
            "claim_assertions": [
                {
                    "category": "service_availability",
                    "response_unit_indexes": [0],
                    "evidence_refs": ["svc_obs_rosario"],
                    "service_area_claims": [
                        {
                            "scope_ref": "service_query_area:svc_obs_rosario",
                            "outcome": "partner_options_found",
                        }
                    ],
                }
            ],
            "response_units": [
                {"type": "text", "content": {"text": "May options po."}}
            ],
        }
    )

    assert any(
        row["type"] == "service_claim_missing_query_area_scope"
        for row in _final_composer_claim_contract_violations(missing, plan)
    )
    assert any(
        row["type"] == "unauthorized_service_query_area_scope"
        for row in _final_composer_claim_contract_violations(foreign, plan)
    )
    assert _final_composer_claim_contract_violations(valid, plan) == []


def test_service_claim_contract_rejects_prose_when_summary_surface_owns_fact() -> None:
    plan = {
        "authorized_claim_categories": ["service_availability"],
        "authorized_evidence_refs": ["svc_obs_rosario"],
        "available_surfaces": [
            {
                "surface_ref": "pres_rosario",
                "surface_type": "installation_partner_summary",
                "required": True,
            }
        ],
        "progression_context": {
            "authorized_evidence_refs_by_claim_category": {
                "service_availability": ["svc_obs_rosario"],
            },
            "authorized_service_area_claims_by_evidence_ref": {
                "svc_obs_rosario": [
                    {
                        "scope_ref": "service_query_area:svc_obs_rosario",
                        "queried_location": "Rosario, Cavite",
                        "outcome": "partner_options_found",
                    }
                ]
            },
        },
    }
    response = json.dumps(
        {
            "claim_assertions": [
                {
                    "category": "service_availability",
                    "response_unit_indexes": [0],
                    "evidence_refs": ["svc_obs_rosario"],
                    "service_area_claims": [
                        {
                            "scope_ref": "service_query_area:svc_obs_rosario",
                            "outcome": "partner_options_found",
                        }
                    ],
                }
            ],
            "response_units": [
                {
                    "type": "text",
                    "content": {
                        "text": "May installation partners po sa lahat ng area."
                    },
                },
                {
                    "type": "render_surface",
                    "content": {"surface_ref": "pres_rosario"},
                },
            ],
        }
    )

    violations = _final_composer_claim_contract_violations(response, plan)

    assert any(
        row["type"]
        == "service_availability_prose_duplicates_provider_surface"
        for row in violations
    )


def test_provider_owned_service_sanitizer_removes_shared_claim_unit() -> None:
    plan = {
        "available_surfaces": [
            {
                "surface_ref": "pres_rosario",
                "surface_type": "installation_partner_summary",
                "required": True,
            }
        ]
    }
    payload = {
        "claim_assertions": [
            {
                "category": "service_availability",
                "response_unit_indexes": [0],
            },
            {
                "category": "validated_state",
                "response_unit_indexes": [0],
            },
        ],
        "request_coverage": [
            {
                "obligation_id": "surface:pres_rosario",
                "disposition": "answered",
                "response_unit_indexes": [1],
                "surface_refs": ["pres_rosario"],
            }
        ],
        "response_units": [
            {
                "type": "text",
                "content": {
                    "text": "May partners sa lahat ng nabanggit na area."
                },
            },
            {
                "type": "render_surface",
                "content": {"surface_ref": "pres_rosario"},
            },
        ],
    }

    sanitized_text, units, removed = (
        _sanitize_provider_owned_service_claim_prose(
            json.dumps(payload),
            customer_turn_plan=plan,
        )
    )
    sanitized = json.loads(sanitized_text)

    assert removed == 1
    assert units == [payload["response_units"][1]]
    assert sanitized["claim_assertions"] == []
    assert sanitized["request_coverage"][0]["response_unit_indexes"] == [0]


def test_post_repair_service_sanitizer_clears_sole_provider_copy_violation() -> None:
    plan = {
        "authorized_claim_categories": ["service_availability"],
        "authorized_evidence_refs": ["svc_obs_qc"],
        "available_surfaces": [
            {
                "surface_ref": "pres_qc",
                "surface_type": "installation_partner_summary",
                "required": True,
                "response_role": "direct_answer",
                "decision_layer": "service",
            }
        ],
        "request_obligations": [
            {
                "obligation_id": "surface:pres_qc",
                "required_response_modes": ["surface"],
                "authorized_surface_refs": ["pres_qc"],
            }
        ],
        "progression_context": {
            "authorized_evidence_refs_by_claim_category": {
                "service_availability": ["svc_obs_qc"]
            },
            "authorized_service_area_claims_by_evidence_ref": {
                "svc_obs_qc": [
                    {
                        "scope_ref": "service_query_area:svc_obs_qc",
                        "queried_location": "Quezon City, Metro Manila",
                        "outcome": "partner_options_found",
                    }
                ]
            },
        },
    }
    payload = {
        "claim_assertions": [
            {
                "category": "service_availability",
                "response_unit_indexes": [0],
                "evidence_refs": ["svc_obs_qc"],
                "service_area_claims": [
                    {
                        "scope_ref": "service_query_area:svc_obs_qc",
                        "outcome": "partner_options_found",
                    }
                ],
            }
        ],
        "request_coverage": [
            {
                "obligation_id": "surface:pres_qc",
                "disposition": "answered",
                "response_unit_indexes": [1],
                "surface_refs": ["pres_qc"],
            }
        ],
        "response_units": [
            {
                "type": "text",
                "content": {"text": "May partners po sa Quezon City."},
            },
            {
                "type": "render_surface",
                "content": {"surface_ref": "pres_qc"},
            },
        ],
    }

    text, units, remaining, removed = (
        _sanitize_post_repair_provider_owned_service_copy(
            json.dumps(payload),
            payload["response_units"],
            [
                {
                    "type": (
                        "service_availability_prose_duplicates_provider_surface"
                    )
                }
            ],
            tool_results=[],
            customer_turn_plan=plan,
        )
    )

    assert removed == 1
    assert remaining == []
    assert units == [payload["response_units"][1]]
    assert json.loads(text)["request_coverage"][0][
        "response_unit_indexes"
    ] == [0]


class LocationHTTP:
    def get_json(self, path, params=None):
        rows = {
            "/get_province": [
                {"PROV_CODE": "PH-03-PAM", "PROV_NAME": "PAMPANGA"},
            ],
            "/get_city": [
                {
                    "CITY_CODE": "PH-03-PAM-SFN",
                    "CITY_NAME": "SAN FERNANDO CITY",
                    "PROV_CODE": "PH-03-PAM",
                },
                {
                    "CITY_CODE": "PH-03-PAM-MAB",
                    "CITY_NAME": "MABALACAT",
                    "PROV_CODE": "PH-03-PAM",
                },
            ],
            "/branch_list_loc": [
                {
                    "id": 1,
                    "area": "Pampanga",
                    "address": "San Fernando, Pampanga",
                    "name": "A",
                },
                {
                    "id": 2,
                    "area": "Pampanga",
                    "address": "Mabalacat, Pampanga",
                    "name": "B",
                },
            ],
        }
        return rows[path]


class FailingLocationProvider:
    def province_surface(self, *, turn_id):
        raise RuntimeError("location provider unavailable")


def _city_surface() -> dict:
    return ServiceableLocationChoicesProvider(
        http_client=LocationHTTP()
    ).city_surface_for_province_label(
        province_label="Pampanga",
        turn_id="turn_pampanga",
    )


def _product_tool_result(*, brand: str = "APOLLO") -> dict:
    return {
        "name": "product_search",
        "args": {"brands": [brand]},
        "full_result": {
            "status": "ok",
            "presentation_ref": f"pres_{brand.casefold()}",
            "product_cards": [
                {
                    "card_ref": f"card_{brand.casefold()}",
                    "brand": brand,
                    "sku_model": f"{brand} SAMPLE 175/65R14",
                }
            ],
        },
    }


def _promo_gallery_tool_result() -> dict:
    return {
        "name": "present_promo_gallery",
        "full_result": {
            "status": "ok",
            "presentation_ref": "promo_gallery_current",
            "card_runtime_insert": True,
            "promo_refs": [
                "promo:apollo-3-1-promo",
                "promo:michelin-3-1-promo",
            ],
            "cards": [
                {
                    "card_ref": "promo_apollo",
                    "title": "APOLLO 3+1 PROMO",
                },
                {
                    "card_ref": "promo_michelin",
                    "title": "MICHELIN 3+1 PROMO",
                },
            ],
        },
    }


def test_turn_authorization_requires_city_surface_after_validated_province_choice() -> None:
    surface = _city_surface()
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [],
            "location_choice_surface": surface,
        },
        order_readiness={"collected": {"Product": "APOLLO ALNAC"}},
        draft_assistant_text="Pampanga po.",
        validated_choice_context={
            "validation_status": "valid",
            "choice_type": "serviceable_province",
            "label": "Pampanga",
        },
    )

    assert plan["progression_context"]["slots_authorized"] is False
    assert plan["already_satisfied_fields"] == ["Product"]
    assert len(plan["available_surfaces"]) == 1
    assert plan["available_surfaces"][0]["visible_count"] == 2

    ref = surface["presentation_ref"]
    missing = _final_composer_renderer_contract_violations(
        [{"type": "text", "content": {"text": "Choose a city."}}],
        [],
        customer_turn_plan=plan,
    )
    duplicate = _final_composer_renderer_contract_violations(
        [
            {"type": "render_surface", "content": {"surface_ref": ref}},
            {"type": "render_surface", "content": {"surface_ref": ref}},
        ],
        [],
        customer_turn_plan=plan,
    )

    assert missing == [
        {
            "type": "required_renderer_surface_missing",
            "surface_ref": ref,
            "response_role": "direct_answer",
        }
    ]
    assert duplicate == [
        {
            "type": "renderer_surface_duplicated",
            "surface_ref": ref,
            "count": 2,
        }
    ]


def test_final_response_schema_rejects_empty_customer_turn() -> None:
    with pytest.raises(ValueError):
        RuntimeV7FinalResponseModel(response_units=[])


def test_typed_request_coverage_maps_each_grounded_surface() -> None:
    plan = {
        "available_surfaces": [
            {
                "surface_ref": "promo_1",
                "required": True,
                "response_role": "direct_answer",
            },
            {
                "surface_ref": "location_1",
                "required": True,
                "response_role": "direct_answer",
            },
        ],
        "request_obligations": [
            {
                "obligation_id": "surface:promo_1",
                "objective": "promo",
                "required_response_modes": ["surface"],
                "authorized_surface_refs": ["promo_1"],
            },
            {
                "obligation_id": "surface:location_1",
                "objective": "location",
                "required_response_modes": ["surface"],
                "authorized_surface_refs": ["location_1"],
            },
        ],
    }
    units = [
        {"type": "render_surface", "content": {"surface_ref": "promo_1"}},
        {"type": "render_surface", "content": {"surface_ref": "location_1"}},
    ]
    model_text = json.dumps(
        {
            "request_coverage": [
                {
                    "obligation_id": "surface:promo_1",
                    "disposition": "answered",
                    "surface_refs": ["promo_1"],
                },
                {
                    "obligation_id": "surface:location_1",
                    "disposition": "answered",
                    "surface_refs": ["location_1"],
                },
            ],
            "response_units": units,
        }
    )

    assert not _final_composer_request_coverage_contract_violations(
        model_text,
        units,
        customer_turn_plan=plan,
    )

    missing_location = json.dumps(
        {
            "request_coverage": [
                {
                    "obligation_id": "surface:promo_1",
                    "disposition": "answered",
                    "surface_refs": ["promo_1"],
                }
            ],
            "response_units": units,
        }
    )
    assert _final_composer_request_coverage_contract_violations(
        missing_location,
        units,
        customer_turn_plan=plan,
    ) == [
        {
            "type": "request_coverage_missing",
            "obligation_id": "surface:location_1",
        }
    ]


def test_request_coverage_contract_enforces_pending_scope_boundary() -> None:
    obligation_id = "scope_boundary:faq:order:delivery_process"
    plan = {
        "request_obligations": [
            {
                "obligation_id": obligation_id,
                "objective": "exact_delivery_serviceability",
                "required_response_modes": ["text"],
                "authorized_surface_refs": [],
                "expected_disposition": "pending_validation",
            }
        ]
    }
    units = [
        {
            "type": "text",
            "content": {"text": "Exact location coverage still needs validation."},
        }
    ]
    valid = json.dumps(
        {
            "request_coverage": [
                {
                    "obligation_id": obligation_id,
                    "disposition": "pending_validation",
                    "response_unit_indexes": [0],
                }
            ],
            "response_units": units,
        }
    )

    assert not _final_composer_request_coverage_contract_violations(
        valid,
        units,
        customer_turn_plan=plan,
    )

    overclaimed = valid.replace("pending_validation", "answered")
    assert _final_composer_request_coverage_contract_violations(
        overclaimed,
        units,
        customer_turn_plan=plan,
    ) == [
        {
            "type": "request_coverage_disposition_mismatch",
            "obligation_id": obligation_id,
            "expected_disposition": "pending_validation",
            "disposition": "answered",
        }
    ]


def test_request_coverage_contract_rejects_omitted_required_declaration() -> None:
    obligation_id = "scope_boundary:faq:order:delivery_process"
    plan = {
        "request_obligations": [
            {
                "obligation_id": obligation_id,
                "objective": "exact_delivery_serviceability",
                "required_response_modes": ["text"],
                "authorized_surface_refs": [],
                "expected_disposition": "pending_validation",
            }
        ]
    }
    units = [
        {"type": "text", "content": {"text": "General policy only."}}
    ]
    payload = json.dumps({"response_units": units})

    assert _final_composer_request_coverage_contract_violations(
        payload,
        units,
        customer_turn_plan=plan,
    ) == [
        {
            "type": "request_coverage_missing",
            "obligation_id": obligation_id,
        }
    ]


def test_failed_unknown_surface_repair_preserves_initial_text_and_required_surface() -> None:
    plan = {
        "available_surfaces": [
            {
                "surface_ref": "product_1",
                "decision_layer": "product",
                "required": True,
                "response_role": "direct_answer",
            },
            {
                "surface_ref": "promo_optional",
                "decision_layer": "promo",
                "required": False,
                "response_role": "optional_context",
            },
        ]
    }

    units = _enforce_renderer_owned_unit_contract(
        [
            {
                "type": "render_surface",
                "content": {"surface_ref": "unknown"},
            }
        ],
        [],
        customer_turn_plan=plan,
        fallback_response_units=[
            {
                "type": "text",
                "content": {"text": "Ito po yung exact options at prices."},
            }
        ],
    )

    assert units == [
        {
            "type": "text",
            "content": {"text": "Ito po yung exact options at prices."},
        },
        {"type": "render_surface", "content": {"surface_ref": "product_1"}},
    ]


def test_product_answer_is_required_while_unrequested_broad_promo_is_optional() -> None:
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                _product_tool_result(brand="MICHELIN"),
                _promo_gallery_tool_result(),
            ]
        },
        order_readiness={"collected": {"Quantity": "4 tires"}},
        background_signals=[
            {
                "source": "latest_user_message",
                "key": "tire_size",
                "value": "185/60R15",
            }
        ],
    )
    surfaces = {
        surface["surface_type"]: surface
        for surface in plan["available_surfaces"]
    }

    assert surfaces["product_cards"]["required"] is True
    assert surfaces["product_cards"]["response_role"] == "direct_answer"
    assert surfaces["promo_catalog"]["required"] is False
    assert surfaces["promo_catalog"]["response_role"] == "optional_context"
    product_ref = surfaces["product_cards"]["surface_ref"]
    promo_ref = surfaces["promo_catalog"]["surface_ref"]
    assert plan["request_obligations"] == [
        {
            "obligation_id": f"surface:{product_ref}",
            "objective": "product",
            "required_response_modes": ["surface"],
            "authorized_surface_refs": [product_ref],
        }
    ]
    assert not _final_composer_renderer_contract_violations(
        [{"type": "render_surface", "content": {"surface_ref": product_ref}}],
        [],
        customer_turn_plan=plan,
    )
    violations = _final_composer_renderer_contract_violations(
        [{"type": "render_surface", "content": {"surface_ref": promo_ref}}],
        [],
        customer_turn_plan=plan,
    )
    assert any(
        violation["type"] == "required_renderer_surface_missing"
        and violation["surface_ref"] == product_ref
        for violation in violations
    )


def test_service_no_match_requires_text_not_an_empty_renderer_surface() -> None:
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                {
                    "name": "find_installation_partners",
                    "args": {"location": "Panglao, Bohol"},
                    "full_result": {
                        "status": "no_match",
                        "presentation_ref": "service_no_match_1",
                        "coverage_assessment": {
                            "installation_service_area_status": (
                                "outside_known_installation_service_area"
                            ),
                            "customer_location_label": "Panglao, Bohol",
                        },
                        "customer_explanation_hints": [
                            "Delivery remains available for checking."
                        ],
                    },
                }
            ]
        },
        order_readiness={},
    )

    surface = plan["available_surfaces"][0]
    assert surface["surface_type"] == "service_no_match_context"
    assert surface["required"] is False
    assert plan["request_obligations"] == [
        {
            "obligation_id": "text:service_no_match_1",
            "objective": "service_no_match_context",
            "required_response_modes": ["text"],
            "authorized_surface_refs": [],
        }
    ]


def test_successful_area_only_service_lookup_requires_provider_owned_summary() -> None:
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                {
                    "name": "find_installation_partners",
                    "args": {"location": "Quezon City"},
                    "full_result": {
                        "status": "ok",
                        "observation_ref": "svc_obs_qc_1",
                        "presentation_ref": "pres_qc_1",
                        "partner_detail_level": "area_only",
                        "query_basis": {
                            "location": "Quezon City, Metro Manila",
                            "customer_location_label": (
                                "Quezon City, Metro Manila"
                            ),
                        },
                        "installation_partners": [
                            {
                                "installation_partner_ref": "partner_qc_1",
                                "city": "Quezon City",
                            }
                        ],
                        "installation_partner_cards": [
                            {
                                "name": "",
                                "card_text": "Quezon City area option",
                                "partner_detail_level": "area_only",
                            }
                        ],
                        "coverage_assessment": {
                            "installation_service_area_status": (
                                "has_installation_partner_options"
                            ),
                            "presentable_partner_count": 1,
                            "customer_location_label": (
                                "Quezon City, Metro Manila"
                            ),
                        },
                    },
                }
            ]
        },
        order_readiness={},
        background_signals=[
            {
                "source": "latest_user_message",
                "key": "location",
                "value": "Quezon City, Metro Manila",
            }
        ],
    )

    assert plan["available_surfaces"] == [
        {
            "surface_ref": "pres_qc_1",
            "surface_type": "installation_partner_summary",
            "decision_layer": "location",
            "visible_labels": [],
            "visible_count": 0,
            "selection_state": "",
            "source": "find_installation_partners_summary",
            "source_version": "",
            "required": True,
            "response_role": "direct_answer",
        }
    ]
    assert plan["request_obligations"] == [
        {
            "obligation_id": "surface:pres_qc_1",
            "objective": "location",
            "required_response_modes": ["surface"],
            "authorized_surface_refs": ["pres_qc_1"],
        }
    ]


def test_product_and_location_surfaces_are_both_available_to_model() -> None:
    location_surface = ServiceableLocationChoicesProvider(
        http_client=LocationHTTP()
    ).province_surface(turn_id="turn_product_first")
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [_product_tool_result()],
            "location_choice_surface": location_surface,
        },
        order_readiness={"collected": {"Quantity": "4 tires"}},
        draft_assistant_text="May isang matching Apollo option.",
        validated_choice_context={},
    )

    assert {
        surface["decision_layer"]
        for surface in plan["available_surfaces"]
    } == {"product", "province"}
    assert "product_facts" in plan["authorized_claim_categories"]
    assert "service_availability" not in plan["authorized_claim_categories"]
    assert "schedule_availability" not in plan["authorized_claim_categories"]
    assert (
        plan["progression_context"][
            "service_availability_claims_authorized"
        ]
        is False
    )
    assert (
        plan["progression_context"][
            "schedule_availability_claims_authorized"
        ]
        is False
    )
    assert "not service-availability evidence" in (
        plan["progression_context"]["service_evidence_instruction"]
    )


def test_model_requested_location_and_product_surfaces_remain_available() -> None:
    location_surface = ServiceableLocationChoicesProvider(
        http_client=LocationHTTP()
    ).province_surface(turn_id="turn_semantic_location")
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [_product_tool_result()],
            "location_choice_surface": location_surface,
            "location_choice_surface_status": {
                "status": "attached",
                "reason": "model_requested_serviceable_location_choices",
                "routing_only": True,
                "slots_authorized": False,
            },
        },
        order_readiness={"collected": {}},
        draft_assistant_text="Pili po kayo ng province below.",
        validated_choice_context={},
    )

    assert {
        surface["decision_layer"]
        for surface in plan["available_surfaces"]
    } == {"product", "province"}
    assert "service_availability" not in plan["authorized_claim_categories"]
    assert "schedule_availability" not in plan["authorized_claim_categories"]


def test_semantic_location_tool_is_always_available_to_main_model() -> None:
    profile = build_capability_profile(
        current_user_message="completely novel phrasing",
        default_domains=("product",),
    )
    schema_names = {
        schema["function"]["name"] for schema in ALL_RUNTIME_V7_TOOL_SCHEMAS
    }

    assert "present_serviceable_location_choices" in schema_names
    assert "present_serviceable_location_choices" in profile.exposed_tools
    assert "get_business_contact" in profile.exposed_tools


def test_active_installation_without_area_adds_location_candidate() -> None:
    profile = build_capability_profile(
        current_user_message="Gusto ko magpakabit",
        background_signals=[
            {
                "key": "service_type",
                "value": "installation",
                "status": "mentioned_unconfirmed",
                "source": "latest_user_message",
            }
        ],
        default_domains=(),
    )

    assert "present_serviceable_location_choices" in profile.candidate_tools
    assert (
        "present_serviceable_location_choices:"
        "active_installation_without_usable_service_location"
        in profile.selection_reasons
    )


def test_delivered_product_help_adds_optional_location_candidate() -> None:
    profile = build_capability_profile(
        current_user_message="May iba pa bang practical na option?",
        product_observation_headers=[
            {
                "observation_ref": "obs_product_choices",
                "presentation_ref": "pres_product_choices",
                "card_count": 3,
                "presentation_delivered": True,
            }
        ],
        default_domains=(),
    )

    assert "present_serviceable_location_choices" in profile.candidate_tools
    assert (
        "present_serviceable_location_choices:"
        "delivered_product_help_without_usable_service_location"
        in profile.selection_reasons
    )


@pytest.mark.parametrize(
    "product_header",
    [
        {
            "observation_ref": "obs_not_presented",
            "presentation_ref": "pres_delivery_unknown",
            "card_count": 3,
        },
        {
            "observation_ref": "obs_delivery_failed",
            "presentation_ref": "pres_delivery_failed",
            "card_count": 3,
            "presentation_delivered": False,
        },
    ],
)
def test_hidden_or_undelivered_product_help_does_not_add_location_candidate(
    product_header,
) -> None:
    profile = build_capability_profile(
        current_user_message="May iba pa bang option?",
        product_observation_headers=[product_header],
        default_domains=(),
    )

    assert "present_serviceable_location_choices" not in profile.candidate_tools


def test_prior_location_surface_suppresses_only_optional_reengagement_candidate() -> None:
    profile = build_capability_profile(
        current_user_message="Pakita ulit ng service areas",
        product_observation_headers=[
            {
                "observation_ref": "obs_product_choices",
                "presentation_ref": "pres_product_choices",
                "card_count": 3,
                "presentation_delivered": True,
            }
        ],
        guided_location_optional_reoffer_suppressed=True,
        default_domains=("product",),
    )

    assert "present_serviceable_location_choices" not in profile.candidate_tools
    assert "present_serviceable_location_choices" in profile.exposed_tools
    assert (
        "present_serviceable_location_choices:"
        "deferred:prior_location_surface_or_action"
        in profile.selection_reasons
    )


def test_current_installation_request_can_reopen_location_after_prior_surface() -> None:
    profile = build_capability_profile(
        current_user_message="Installation na, pakita ulit ng areas",
        background_signals=[
            {
                "key": "service_type",
                "value": "installation",
                "source": "latest_user_message",
            }
        ],
        product_observation_headers=[
            {
                "observation_ref": "obs_product_choices",
                "presentation_ref": "pres_product_choices",
                "card_count": 3,
                "presentation_delivered": True,
            }
        ],
        guided_location_optional_reoffer_suppressed=True,
        default_domains=(),
    )

    assert "present_serviceable_location_choices" in profile.candidate_tools


def test_unselected_delivered_province_surface_suppresses_optional_reoffer() -> None:
    assert _guided_location_optional_reoffer_suppressed(
        choice_presentation_history=[
            {
                "presentation_ref": "loc_waiting",
                "choice_type": "serviceable_province",
                "delivery_status": "success",
            }
        ],
        choice_action_history=[],
    )


def test_valid_other_province_action_suppresses_optional_reoffer() -> None:
    assert _guided_location_optional_reoffer_suppressed(
        choice_presentation_history=[],
        choice_action_history=[
            {
                "presentation_ref": "loc_other",
                "choice_type": "serviceable_province",
                "choice_code": "other",
                "validation_status": "valid",
                "recommended_service_path": "delivery",
                "service_path_selected": False,
            }
        ],
    )


@pytest.mark.parametrize(
    "extra_signal",
    [
        {
            "key": "delivery_address",
            "value": "Makati City",
            "status": "confirmed",
            "source": "validated_choice_action",
        },
        {
            "key": "location",
            "value": "Makati City",
            "source": "latest_user_message",
            "resolution": {
                "city_hint": "Makati City",
                "province_hint": "Metro Manila",
                "location_precision": "city",
            },
        },
    ],
)
def test_delivery_or_resolved_location_suppresses_location_candidate(extra_signal) -> None:
    profile = build_capability_profile(
        current_user_message="Installation po",
        background_signals=[
            {
                "key": "service_type",
                "value": "installation",
                "status": "mentioned_unconfirmed",
                "source": "latest_user_message",
            },
            extra_signal,
        ],
        default_domains=(),
    )

    assert "present_serviceable_location_choices" not in profile.candidate_tools


@pytest.mark.parametrize(
    "blocking_signal",
    [
        {
            "key": "service_type",
            "value": "delivery",
            "status": "mentioned_unconfirmed",
            "source": "latest_user_message",
        },
        {
            "key": "delivery_address",
            "value": "Makati City",
            "status": "confirmed",
            "source": "validated_choice_action",
        },
        {
            "key": "location",
            "value": "Makati City",
            "source": "latest_user_message",
            "resolution": {
                "city_hint": "Makati City",
                "province_hint": "Metro Manila",
                "location_precision": "city",
            },
        },
    ],
)
def test_product_reengagement_respects_delivery_and_known_location_guards(
    blocking_signal,
) -> None:
    profile = build_capability_profile(
        current_user_message="Hindi pa ako sure sa options",
        background_signals=[blocking_signal],
        product_observation_headers=[
            {
                "observation_ref": "obs_product_choices",
                "presentation_ref": "pres_product_choices",
                "card_count": 2,
                "presentation_delivered": True,
            }
        ],
        default_domains=(),
    )

    assert "present_serviceable_location_choices" not in profile.candidate_tools


def test_unresolved_location_noun_does_not_expose_concrete_service_lookup() -> None:
    profile = build_capability_profile(
        current_user_message="novel business location wording",
        background_signals=[
            {
                "key": "location",
                "value": "generic place noun",
                "relation": "question_only",
                "resolution": {
                    "city_hint": None,
                    "province_hint": None,
                    "landmark_hint": None,
                    "location_precision": None,
                },
            }
        ],
        default_domains=(),
    )

    assert profile.selected_domains == []
    assert "find_installation_partners" not in profile.exposed_tools
    assert "present_serviceable_location_choices" in profile.exposed_tools


def test_location_surface_provider_failure_records_non_authorizing_status(
    monkeypatch,
) -> None:
    monkeypatch.setenv("RUNTIME_V7_TURN_PLAN_ENABLED", "0")
    turn = {
        "turn_id": "turn_location_provider_failure",
        "lead_qualification": {"present": {}},
        "order_readiness_before_turn": {"collected": {}},
    }
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="Where are your service locations?",
        flow_context={
            "choice_action_runtime_context": {
                "validation_status": "valid",
                "choice_type": "serviceable_province",
                "choice_code": "PH-40",
                "label": "Cavite",
            }
        },
    )

    api_runtime._attach_location_choice_surface(
        turn,
        request=request,
        provider=FailingLocationProvider(),
    )

    assert "location_choice_surface" not in turn
    assert turn["location_choice_surface_status"] == {
        "status": "not_attached",
        "reason": "provider_unavailable",
        "slots_authorized": False,
    }


def test_resolved_customer_city_exposes_service_lookup() -> None:
    profile = build_capability_profile(
        current_user_message="novel concrete place wording",
        background_signals=[
            {
                "key": "location",
                "value": "Makati",
                "source": "latest_user_message",
                "relation": "question_only",
                "resolution": {
                    "city_hint": "Makati City",
                    "province_hint": "Metro Manila",
                    "location_precision": "city",
                },
            }
        ],
        default_domains=(),
    )

    assert "service" in profile.selected_domains
    assert "find_installation_partners" in profile.exposed_tools


def test_semantic_province_plan_rejects_normalized_concrete_location() -> None:
    rejection = _location_tool_plan_rejection(
        name="present_serviceable_location_choices",
        execution_args={},
        validated_choice_context={},
        background_signals=[
            {
                "key": "location",
                "value": "Makati",
                "source": "latest_user_message",
                "resolution": {
                    "province_hint": "Metro Manila",
                    "city_hint": "Makati City",
                    "location_precision": "city",
                },
            }
        ],
        order_readiness={"collected": {}},
    )

    assert rejection["required_decision_layer"] == "service_lookup"
    assert rejection["source"] == "normalized_latest_customer_location"
    assert rejection["location_precision"] == "city"


def test_semantic_province_plan_rejects_validated_delivery_path() -> None:
    rejection = _location_tool_plan_rejection(
        name="present_serviceable_location_choices",
        execution_args={},
        validated_choice_context={},
        background_signals=[],
        order_readiness={
            "collected": {
                "Fulfillment": "delivery",
                "Delivery address": "BGC, Taguig",
            }
        },
    )

    assert rejection["required_decision_layer"] == "delivery_address"
    assert rejection["source"] == "validated_order_readiness"


def test_semantic_province_plan_rejects_durable_delivery_signal() -> None:
    rejection = _location_tool_plan_rejection(
        name="present_serviceable_location_choices",
        execution_args={},
        validated_choice_context={},
        background_signals=[
            {
                "key": "service_type",
                "value": "delivery",
                "status": "confirmed",
                "source": "signal_ledger",
            }
        ],
        order_readiness={"collected": {}},
    )

    assert rejection["required_decision_layer"] == "delivery_address"
    assert rejection["source"] == "durable_signal_ledger"


def test_rejected_province_slot_plan_attaches_city_surface_over_product(
    monkeypatch,
) -> None:
    monkeypatch.setenv("RUNTIME_V7_TURN_PLAN_ENABLED", "1")
    provider = ServiceableLocationChoicesProvider(
        http_client=LocationHTTP()
    )
    turn = {
        "turn_id": "turn_province_slot_rejected",
        "tool_results": [
            _product_tool_result(brand="MICHELIN"),
            {
                "name": "find_installation_slots",
                "full_result": {
                    "status": "error",
                    "error_type": "tool_plan_not_authorized",
                    "required_decision_layer": "city",
                    "reason": "Choose a serviceable city first.",
                },
            },
        ],
        "background_signals_before_turn": [
            {
                "key": "location",
                "value": "Pampanga",
                "source": "latest_user_message",
                "resolution": {
                    "province_hint": "Pampanga",
                    "city_hint": None,
                    "location_precision": "province_only",
                },
            }
        ],
    }
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text=(
            "May schedule ba sa Pampanga? Hindi pa ako sure sa city."
        ),
    )

    api_runtime._attach_location_choice_surface(
        turn,
        request=request,
        provider=provider,
    )

    assert turn["location_choice_surface"]["level"] == "city"
    assert [
        choice["label"]
        for choice in turn["location_choice_surface"]["choices"]
    ] == ["Mabalacat", "San Fernando City"]
    assert turn["location_choice_surface_status"] == {
        "status": "attached",
        "reason": "province_only_free_text",
        "location_precision": "province_only",
        "slots_authorized": False,
    }


def test_slot_evidence_authorizes_service_and_schedule_claim_categories() -> None:
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                {
                    "name": "find_installation_slots",
                    "full_result": {
                        "status": "ok",
                        "observation_ref": "obs_slots_1",
                        "presentation_ref": "pres_slots_1",
                        "slot_groups": [
                            {
                                "date": "2026-08-03",
                                "slots": [{"time": "08:00"}],
                            }
                        ],
                    },
                }
            ],
        },
        order_readiness={
            "collected": {
                "Product": "APOLLO ALNAC",
                "Installation area": "Dasmarinas City, Cavite",
            }
        },
        draft_assistant_text="May current schedule choices.",
        validated_choice_context={},
    )

    assert "service_availability" in plan["authorized_claim_categories"]
    assert "schedule_availability" in plan["authorized_claim_categories"]
    assert (
        plan["progression_context"][
            "service_availability_claims_authorized"
        ]
        is True
    )
    assert (
        plan["progression_context"][
            "schedule_availability_claims_authorized"
        ]
        is True
    )
    assert plan["progression_context"][
        "authorized_evidence_refs_by_claim_category"
    ]["schedule_availability"] == [
        "obs_slots_1",
        "pres_slots_1",
    ]
    assert "service_evidence_instruction" not in plan["progression_context"]


def test_ranked_city_preview_refs_authorize_preview_claims() -> None:
    surface = _city_surface()
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                {
                    "name": "find_installation_slots",
                    "full_result": {
                        "status": "ok",
                        "recommendation_mode": "serviceable_city",
                        "preview_observation_refs": [
                            "preview_mabalacat",
                            "preview_san_fernando",
                        ],
                        "location_choice_surface": surface,
                    },
                }
            ],
            "location_choice_surface": surface,
            "location_choice_surface_status": {
                "status": "attached",
                "reason": "customer_unsure_city_ranked_preview",
                "slots_authorized": False,
            },
        },
        order_readiness={
            "collected": {"Installation area": "Pampanga"}
        },
        draft_assistant_text="Pili po tayo ng serviceable city.",
        validated_choice_context={},
    )

    refs_by_category = plan["progression_context"][
        "authorized_evidence_refs_by_claim_category"
    ]
    assert refs_by_category["service_availability"] == [
        "preview_mabalacat",
        "preview_san_fernando",
        surface["presentation_ref"],
        surface["source_version"],
    ]
    assert refs_by_category["schedule_availability"] == [
        "preview_mabalacat",
        "preview_san_fernando",
        surface["presentation_ref"],
        surface["source_version"],
    ]
    assert _final_composer_claim_contract_violations(
        (
            '{"claim_assertions":[{"category":"service_availability",'
            '"response_unit_indexes":[0],"evidence_refs":'
            '["preview_mabalacat"]},{"category":'
            '"schedule_availability","response_unit_indexes":[0],'
            '"evidence_refs":["preview_mabalacat"]}],'
            '"response_units":[{"type":"text","content":{"text":'
            '"May preview availability sa Mabalacat."}},'
            '{"type":"render_surface","content":{"surface_ref":"'
            + surface["presentation_ref"]
            + '"}}]}'
        ),
        plan,
    ) == []


def test_ranked_city_schedule_request_remains_pending_until_city_selection() -> None:
    surface = _city_surface()
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                {
                    "name": "find_installation_slots",
                    "full_result": {
                        "status": "ok",
                        "recommendation_mode": "serviceable_city",
                        "preview_observation_refs": ["preview_mabalacat"],
                        "location_choice_surface": surface,
                    },
                }
            ],
            "location_choice_surface": surface,
            "location_choice_surface_status": {
                "status": "attached",
                "reason": "customer_unsure_city_ranked_preview",
                "slots_authorized": False,
            },
        },
        order_readiness={"collected": {"Installation area": "Pampanga"}},
        background_signals=[
            {
                "key": "preferred_schedule",
                "value": "bukas",
                "source": "latest_user_message",
            }
        ],
        validated_choice_context={},
    )

    schedule_obligation = next(
        item
        for item in plan["request_obligations"]
        if item["objective"] == "schedule_availability"
    )
    assert schedule_obligation["expected_disposition"] == "pending_validation"


def test_product_search_promo_evidence_authorizes_product_promo_claim() -> None:
    result = _product_tool_result(brand="MICHELIN")
    result["full_result"]["promo_evidence"] = {
        "verified_brands": ["MICHELIN"],
        "source": "promo_brands",
    }
    plan = _build_customer_turn_plan(
        record={"tool_results": [result]},
        order_readiness={},
        draft_assistant_text="May current Buy 3 Get 1 promo.",
        validated_choice_context={},
    )

    refs_by_category = plan["progression_context"][
        "authorized_evidence_refs_by_claim_category"
    ]
    assert refs_by_category["promo_facts"] == ["pres_michelin"]
    assert "promo_facts" in plan["authorized_claim_categories"]


def test_promo_search_registers_allowed_promo_refs_as_claim_evidence() -> None:
    search_ref = "promo_search:catalog-v1:scope"
    promo_ref = "promo:catalog-v1:offer-1"
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                {
                    "name": "search_promo_catalog",
                    "full_result": {
                        "status": "ok",
                        "evidence_ref": search_ref,
                        "allowed_promo_refs": [promo_ref],
                        "candidates": [{"promo_ref": promo_ref}],
                    },
                }
            ]
        },
        order_readiness={},
        draft_assistant_text="May verified promo.",
        validated_choice_context={},
    )

    assert plan["authorized_evidence_refs"] == [
        BUSINESS_IDENTITY_EVIDENCE_REF,
        search_ref,
        promo_ref,
    ]
    assert plan["progression_context"][
        "authorized_evidence_refs_by_claim_category"
    ]["promo_facts"] == [search_ref, promo_ref]
    assert _final_composer_claim_contract_violations(
        json.dumps(
            {
                "claim_assertions": [
                    {
                        "category": "promo_facts",
                        "response_unit_indexes": [0],
                        "evidence_refs": [promo_ref],
                    }
                ],
                "response_units": [
                    {
                        "type": "text",
                        "content": {"text": "May verified promo."},
                    }
                ],
            }
        ),
        plan,
    ) == []
    assert plan["progression_context"]["promo_response_contract"][
        "version"
    ] == "promo_response_contract_v1"

    composer_messages = _build_final_composer_messages(
        current_user_message="May promo po?",
        request_time="2026-08-04T12:00:00+08:00",
        active_working_memory="",
        background_signals=[],
        lead_qualification={},
        order_readiness={},
        capability_profile={},
        tool_results=[
            {
                "name": "search_promo_catalog",
                "full_result": {
                    "status": "ok",
                    "mode": "targeted",
                    "evidence_ref": search_ref,
                    "allowed_promo_refs": [promo_ref],
                    "candidates": [{"promo_ref": promo_ref}],
                },
                "result": {
                    "status": "ok",
                    "mode": "targeted",
                    "evidence_ref": search_ref,
                    "allowed_promo_refs": [promo_ref],
                    "candidates": [{"promo_ref": promo_ref}],
                    "composition_guidance": "duplicate guidance",
                },
            }
        ],
        draft_assistant_text="May verified promo.",
        customer_turn_plan=plan,
    )
    composer_payload = json.loads(composer_messages[-1]["content"])

    assert composer_payload["promo_response_contract"]["version"] == (
        "promo_response_contract_v1"
    )
    assert "promo_response_contract" not in composer_payload[
        "customer_turn_plan"
    ]["progression_context"]
    search_payload = composer_payload["tool_results"][0]["result"]
    assert "candidates" not in search_payload
    assert "composition_guidance" not in search_payload
    assert search_payload["promo_response_contract_is_top_level"] is True


def test_payment_request_authorizes_payment_and_order_claims() -> None:
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                {
                    "name": "prepare_payment_request",
                    "full_result": {
                        "status": "ok",
                        "order_payload_ref": "order_payload_1",
                        "payment_request_ref": "payment_request_1",
                        "presentation_ref": "payment_surface_1",
                    },
                }
            ]
        },
        order_readiness={},
        draft_assistant_text="Ready na ang payment request.",
        validated_choice_context={},
    )

    assert {"order_facts", "payment_facts"}.issubset(
        plan["authorized_claim_categories"]
    )
    refs_by_category = plan["progression_context"][
        "authorized_evidence_refs_by_claim_category"
    ]
    assert refs_by_category["order_facts"] == [
        "payment_surface_1",
        "order_payload_1",
        "payment_request_1",
    ]
    assert refs_by_category["payment_facts"] == refs_by_category[
        "order_facts"
    ]


def test_empty_promo_search_authorizes_only_its_scoped_negative_result() -> None:
    evidence_ref = "promo_search:catalog-v1:empty_scope"
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                {
                    "name": "search_promo_catalog",
                    "full_result": {
                        "status": "ok",
                        "catalog_version_id": "catalog-v1",
                        "evidence_ref": evidence_ref,
                        "mode": "targeted",
                        "query": "May Toyo 3+1 promo ba?",
                        "requested_brands": ["Toyo"],
                        "matched_requested_brands": [],
                        "unmatched_requested_brands": ["Toyo"],
                        "allowed_promo_refs": [],
                    },
                }
            ],
        },
        order_readiness={},
        draft_assistant_text="Walang matching reviewed promo.",
        validated_choice_context={},
    )

    refs_by_category = plan["progression_context"][
        "authorized_evidence_refs_by_claim_category"
    ]
    assert evidence_ref in plan["authorized_evidence_refs"]
    assert refs_by_category["promo_facts"] == [evidence_ref]
    assert _final_composer_claim_contract_violations(
        (
            '{"claim_assertions":[{"category":"promo_facts",'
            '"response_unit_indexes":[0],"evidence_refs":'
            f'["{evidence_ref}"]}}],"response_units":['
            '{"type":"text","content":{"text":'
            '"Walang matching reviewed promo."}}]}'
        ),
        plan,
    ) == []


def test_rejected_slot_plan_does_not_authorize_availability_claims() -> None:
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                {
                    "name": "find_installation_slots",
                    "full_result": {
                        "status": "error",
                        "error_type": "tool_plan_not_authorized",
                        "reason": "Choose a serviceable city first.",
                    },
                }
            ],
        },
        order_readiness={
            "collected": {
                "Installation area": "Pampanga",
            }
        },
        draft_assistant_text="Choose a serviceable city first.",
        validated_choice_context={},
    )

    assert "service_availability" not in plan["authorized_claim_categories"]
    assert "schedule_availability" not in plan["authorized_claim_categories"]


def test_typed_claim_contract_rejects_unsupported_service_claim() -> None:
    violations = _final_composer_claim_contract_violations(
        (
            '{"claim_assertions":[{"category":"service_availability",'
            '"response_unit_indexes":[0],"evidence_refs":[]}],'
            '"response_units":[{"type":"text","content":{"text":'
            '"Puwede ito for installation sa Quezon City."}}]}'
        ),
        {
            "authorized_claim_categories": [
                "product_facts",
                "renderer_owned_facts",
                "validated_state",
            ],
            "authorized_evidence_refs": ["prod_obs_1"],
        },
    )

    assert {item["type"] for item in violations} == {
        "unauthorized_claim_category",
        "availability_claim_missing_current_evidence",
    }


def test_typed_claim_contract_skips_when_authorization_contract_is_absent() -> None:
    model_text = (
        '{"claim_assertions":[{"category":"product_facts",'
        '"response_unit_indexes":[0],"evidence_refs":["obs_products_1"]}],'
        '"response_units":[{"type":"text","content":{"text":'
        '"May matching product options."}}]}'
    )

    assert _final_composer_claim_contract_violations(model_text, {}) == []


def test_typed_claim_contract_keeps_explicit_empty_allowlist_fail_closed() -> None:
    model_text = (
        '{"claim_assertions":[{"category":"product_facts",'
        '"response_unit_indexes":[0],"evidence_refs":["obs_products_1"]}],'
        '"response_units":[{"type":"text","content":{"text":'
        '"May matching product options."}}]}'
    )
    violations = _final_composer_claim_contract_violations(
        model_text,
        {
            "authorized_claim_categories": [],
            "authorized_evidence_refs": [],
        },
    )

    assert {item["type"] for item in violations} == {
        "unauthorized_claim_category",
        "unknown_claim_evidence_ref",
    }


def test_typed_claim_contract_accepts_grounded_service_claim() -> None:
    violations = _final_composer_claim_contract_violations(
        (
            '{"claim_assertions":[{"category":"service_availability",'
            '"response_unit_indexes":[0],'
            '"evidence_refs":["obs_slots_1"]}],'
            '"response_units":[{"type":"text","content":{"text":'
            '"May current installation slots sa Dasmarinas."}}]}'
        ),
        {
            "authorized_claim_categories": [
                "service_availability",
                "schedule_availability",
            ],
            "authorized_evidence_refs": [
                "obs_slots_1",
                "pres_slots_1",
            ],
            "progression_context": {
                "authorized_evidence_refs_by_claim_category": {
                    "service_availability": [
                        "obs_slots_1",
                        "pres_slots_1",
                    ],
                    "schedule_availability": [
                        "obs_slots_1",
                        "pres_slots_1",
                    ],
                }
            },
        },
    )

    assert violations == []


def test_policy_faq_authorizes_general_facts_without_address_serviceability() -> None:
    evidence_ref = "faq:order:order_how_long_does_delivery_take"
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                {
                    "name": "answer_policy_faq",
                    "full_result": {
                        "status": "ok",
                        "domain": "order",
                        "faq_id": "order_how_long_does_delivery_take",
                        "evidence_ref": evidence_ref,
                        "answer": "Greater Manila Area: Lalamove",
                    },
                }
            ]
        },
        order_readiness={},
        draft_assistant_text="Delivery is generally offered.",
        validated_choice_context={},
    )

    assert "faq_facts" in plan["authorized_claim_categories"]
    assert "service_availability" not in plan["authorized_claim_categories"]
    assert plan["progression_context"][
        "authorized_evidence_refs_by_claim_category"
    ]["faq_facts"] == [evidence_ref]
    assert plan["progression_context"]["required_faq_fact_answers"] == [
        {
            "faq_id": "order_how_long_does_delivery_take",
            "domain": "order",
            "policy_type": "",
            "applicability": "",
            "evidence_ref": evidence_ref,
            "authored_answer": "Greater Manila Area: Lalamove",
            "answer_required": True,
            "scope_boundary": (
                "Use only the facts in this FAQ result. A general policy does "
                "not authorize a narrower current service, schedule, product, "
                "or order fact."
            ),
        }
    ]
    assert _final_composer_claim_contract_violations(
        (
            '{"claim_assertions":[{"category":"faq_facts",'
            '"response_unit_indexes":[0],"evidence_refs":'
            f'["{evidence_ref}"]'
            '}],"response_units":[{"type":"text","content":'
            '{"text":"Delivery is offered through the published paths."}}]}'
        ),
        plan,
    ) == []
    serviceability_violations = _final_composer_claim_contract_violations(
        (
            '{"claim_assertions":[{"category":"service_availability",'
            '"response_unit_indexes":[0],"evidence_refs":'
            f'["{evidence_ref}"]'
            '}],"response_units":[{"type":"text","content":'
            '{"text":"The exact address is serviceable."}}]}'
        ),
        plan,
    )
    assert {item["type"] for item in serviceability_violations} == {
        "unauthorized_claim_category",
        "availability_claim_missing_current_evidence",
    }


def test_policy_faq_no_match_does_not_authorize_facts() -> None:
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                {
                    "name": "answer_policy_faq",
                    "full_result": {
                        "status": "no_match",
                        "domain": "policy",
                        "answer": "",
                    },
                }
            ]
        },
        order_readiness={},
        draft_assistant_text="",
        validated_choice_context={},
    )

    assert "faq_facts" not in plan["authorized_claim_categories"]
    assert "faq_facts" not in plan["progression_context"][
        "authorized_evidence_refs_by_claim_category"
    ]
    assert plan["progression_context"]["required_faq_fact_answers"] == []


def test_policy_faq_claim_category_is_part_of_response_format() -> None:
    payload = RuntimeV7FinalResponseModel.model_validate(
        {
            "claim_assertions": [
                {
                    "category": "faq_facts",
                    "response_unit_indexes": [0],
                    "evidence_refs": ["faq:order:delivery"],
                }
            ],
            "response_units": [
                {
                    "type": "text",
                    "content": {"text": "Delivery is generally offered."},
                }
            ],
        }
    )

    assert payload.claim_assertions[0].category == "faq_facts"


def test_general_policy_audit_rejects_semantic_scope_overclaim() -> None:
    class AuditModel:
        def complete(
            self,
            *,
            messages,
            tools,
            tool_choice="none",
            response_format=None,
            max_tokens=None,
            temperature=None,
        ):
            assert response_format.__name__ == (
                "RuntimeV7SemanticAnswerAuditModel"
            )
            assert max_tokens == 1600
            assert "customer-named city, district, barangay" in messages[
                0
            ]["content"]
            assert "factual process claim" in messages[0]["content"]
            assert "epistemic scope boundary" in messages[0]["content"]
            assert "required customer input" in messages[0]["content"]
            assert "provide input Y" in messages[0]["content"]
            assert "serves another goal" in messages[0]["content"]
            return {
                "content": json.dumps(
                    {
                        "decision": "unsupported",
                        "unsupported_claims": [
                            "The response confirms the customer's exact area."
                        ],
                        "missing_answers": [],
                        "reason": "General delivery policy is not coverage.",
                    }
                ),
                "usage": {},
                "cache_usage": {},
                "latency_ms": 1,
                "finish_reason": "stop",
            }

    evidence_ref = "faq:order:order_how_long_does_delivery_take"
    tool_results = [
        {
            "name": "answer_policy_faq",
            "full_result": {
                "status": "ok",
                "faq_id": "order_how_long_does_delivery_take",
                "policy_type": "delivery_process",
                "applicability": "policy_general",
                "evidence_ref": evidence_ref,
                "answer": "Greater Manila Area: Lalamove",
                "composition_hint": (
                    "Do not confirm exact street-address serviceability."
                ),
            },
        }
    ]
    record = {"llm_calls": []}
    violation = _audit_semantic_answer_goal(
        model_client=AuditModel(),
        current_user_message="Can you deliver to my area?",
        model_text=(
            '{"claim_assertions":[{"category":"faq_facts",'
            '"evidence_refs":["faq:order:order_how_long_does_delivery_take"]}]}'
        ),
        parsed_units=[
            {
                "type": "text",
                "content": {"text": "Yes, we deliver to your exact area."},
            }
        ],
        tool_results=tool_results,
        customer_turn_plan={
            "progression_context": {
                "required_faq_fact_answers": [
                    {"evidence_ref": evidence_ref, "answer_required": True}
                ],
                "service_availability_claims_authorized": False,
            }
        },
        record=record,
        round_name="policy_audit_test",
    )

    assert violation is not None
    assert violation["type"] == "answer_goal_unsupported"
    assert record["llm_calls"][0]["component"] == (
        "semantic_answer_goal_audit"
    )
    fallback = _safe_semantic_answer_units(tool_results)
    fallback_text = fallback[0]["content"]["text"]
    assert "Greater Manila Area: Lalamove" in fallback_text
    assert "exact details" in fallback_text
    assert "exact area" not in fallback_text


def test_policy_audit_typed_scope_overrides_inconsistent_supported_decision() -> None:
    class AuditModel:
        def complete(
            self,
            *,
            messages,
            tools,
            tool_choice="none",
            response_format=None,
            max_tokens=None,
            temperature=None,
        ):
            return {
                "content": json.dumps(
                    {
                        "decision": "supported",
                        "customer_request_scope": "case_specific",
                        "case_specific_handling": (
                            "mentioned_without_resolution"
                        ),
                        "validation_process_handling": "none",
                        "repair_contract": {
                            "required_meanings": [
                                "The exact case remains pending."
                            ]
                        },
                    }
                ),
                "usage": {},
            }

    violation = _audit_semantic_answer_goal(
        model_client=AuditModel(),
        current_user_message="Can you deliver to this exact district?",
        model_text='{"response_units":[]}',
        parsed_units=[
            {
                "type": "text",
                "content": {"text": "The district was noted. GMA uses delivery."},
            }
        ],
        tool_results=[
            {
                "name": "answer_policy_faq",
                "full_result": {
                    "status": "ok",
                    "applicability": "policy_general",
                    "evidence_ref": "faq:delivery",
                    "answer": "GMA uses delivery.",
                },
            }
        ],
        customer_turn_plan={
            "progression_context": {
                "service_availability_claims_authorized": False,
                "schedule_availability_claims_authorized": False,
            }
        },
        record={"llm_calls": []},
        round_name="typed_policy_audit_test",
    )

    assert violation is not None
    assert violation["type"] == "answer_goal_incomplete"
    assert violation["repair_contract"]["required_meanings"] == [
        "The exact case remains pending."
    ]


def test_semantic_answer_audit_blocks_unrelated_non_policy_answer_goal() -> None:
    class AuditModel:
        def complete(
            self,
            *,
            messages,
            tools,
            tool_choice="none",
            response_format=None,
            max_tokens=None,
            temperature=None,
        ):
            return {
                "content": json.dumps(
                    {
                        "decision": "supported",
                        "answer_goal_alignment": "misaligned",
                        "customer_request_scope": "not_applicable",
                        "case_specific_handling": "not_applicable",
                        "validation_process_handling": "none",
                        "reason": "Warranty does not answer a manufacturing-date question.",
                        "repair_contract": {
                            "required_meanings": ["Ask one concise clarification."],
                            "forbidden_meanings": ["Warranty is the requested answer."],
                        },
                    }
                ),
                "usage": {},
            }

    tool_results = [
        {
            "name": "answer_product_faq",
            "full_result": {
                "status": "ok",
                "faq_id": "product_warranty",
                "applicability": "product_general",
                "evidence_ref": "faq:product:warranty",
                "question": "Do your tires have a warranty?",
                "answer": "Manufacturer warranty is included.",
            },
        }
    ]
    record = {"llm_calls": []}

    violation = _audit_semantic_answer_goal(
        model_client=AuditModel(),
        current_user_message="Ano ang manufacturing date o DOT ng tire?",
        model_text='{"response_units":[]}',
        parsed_units=[
            {
                "type": "text",
                "content": {"text": "May manufacturer warranty po."},
            }
        ],
        tool_results=tool_results,
        customer_turn_plan={"progression_context": {}},
        record=record,
        round_name="faq_alignment_test",
    )

    assert violation is not None
    assert violation["type"] == "answer_goal_unsupported"
    assert violation["answer_goal_alignment"] == "misaligned"
    fallback = _safe_semantic_answer_units(
        tool_results,
        include_authored_answers=False,
    )
    assert "warranty" not in fallback[0]["content"]["text"].casefold()
    assert "paki-clarify" in fallback[0]["content"]["text"]


def test_semantic_fallback_keeps_initially_relevant_authored_answer() -> None:
    assert _semantic_fallback_includes_authored_answers(
        initial_violations=[
            {
                "type": "answer_goal_unsupported",
                "answer_goal_alignment": "partial",
            }
        ],
        remaining_violations=[
            {
                "type": "answer_goal_unsupported",
                "answer_goal_alignment": "misaligned",
            }
        ],
    )


def test_semantic_fallback_omits_initially_unrelated_authored_answer() -> None:
    assert not _semantic_fallback_includes_authored_answers(
        initial_violations=[
            {
                "type": "answer_goal_unsupported",
                "answer_goal_alignment": "misaligned",
            }
        ],
        remaining_violations=[
            {
                "type": "answer_goal_unsupported",
                "answer_goal_alignment": "partial",
            }
        ],
    )


def test_semantic_answer_audit_accepts_provider_backed_case_specific_fact() -> None:
    class AuditModel:
        def complete(
            self,
            *,
            messages,
            tools,
            tool_choice="none",
            response_format=None,
            max_tokens=None,
            temperature=None,
        ):
            return {
                "content": json.dumps(
                    {
                        "decision": "supported",
                        "answer_goal_alignment": "aligned",
                        "customer_request_scope": "case_specific",
                        "case_specific_handling": "implied_or_confirmed",
                        "validation_process_handling": "none",
                        "unsupported_claims": [],
                        "missing_answers": [],
                        "reason": "Checkout authority directly resolves this brand and method.",
                    }
                ),
                "usage": {},
            }

    record = {"llm_calls": []}
    violation = _audit_semantic_answer_goal(
        model_client=AuditModel(),
        current_user_message="Pwede ang 3-month 0% for Yokohama?",
        model_text='{"response_units":[]}',
        parsed_units=[
            {
                "type": "text",
                "content": {
                    "text": "Available po ang 3-month 0% for Yokohama."
                },
            }
        ],
        tool_results=[
            {
                "name": "answer_order_faq",
                "full_result": {
                    "status": "ok",
                    "faq_id": "order_how_do_i_pay",
                    "evidence_ref": "faq:order:order_how_do_i_pay",
                    "question": "How do I pay?",
                    "answer": "Yokohama is eligible for 3-month 0% installment.",
                },
            }
        ],
        customer_turn_plan={"progression_context": {}},
        record=record,
        round_name="payment_answer_goal_test",
    )

    assert violation is None
    assert record["semantic_answer_goal_audits"][0]["decision"] == "supported"


def test_semantic_answer_goal_context_includes_business_contact_answers() -> None:
    contexts = _semantic_answer_audit_context(
        [
            {
                "name": "get_business_contact",
                "full_result": {
                    "status": "ok",
                    "evidence_ref": "business_contact:abc",
                    "question": "May website po kayo?",
                    "answer": "You may contact us at 0956-701-9222.",
                },
            }
        ]
    )

    assert contexts == [
        {
            "tool": "get_business_contact",
            "faq_id": "",
            "policy_type": "",
            "applicability": "",
            "answer_goal": "May website po kayo?",
            "evidence_ref": "business_contact:abc",
            "authored_answer": "You may contact us at 0956-701-9222.",
            "composition_boundary": (
                "This authored answer authorizes only its visible facts and does "
                "not prove a narrower current product, service, schedule, payment, "
                "or order fact."
            ),
        }
    ]


def test_delivery_policy_context_uses_complete_general_answer_goal() -> None:
    contexts = _semantic_answer_audit_context(
        [
            {
                "name": "answer_policy_faq",
                "full_result": {
                    "status": "ok",
                    "faq_id": "order_how_long_does_delivery_take",
                    "policy_type": "delivery_process",
                    "applicability": "policy_general",
                    "question": "How long does delivery take?",
                    "answer": "Greater Manila Area: Lalamove; 7-10 days.",
                    "evidence_ref": "faq:order:delivery",
                },
            }
        ]
    )

    assert contexts[0]["answer_goal"] == (
        "Explain whether delivery is offered generally, the published delivery "
        "paths, and expected delivery time without confirming an exact-location "
        "serviceability result."
    )




def test_promo_audit_typed_scope_overrides_unverified_alternative() -> None:
    class AuditModel:
        def complete(
            self,
            *,
            messages,
            tools,
            tool_choice="none",
            response_format=None,
            max_tokens=None,
            temperature=None,
        ):
            return {
                "content": json.dumps(
                    {
                        "decision": "supported",
                        "customer_requested_promo_fact": True,
                        "requested_promo_result_handling": (
                            "answered_within_scope"
                        ),
                        "customer_requested_alternatives": True,
                        "alternative_promo_handling": "unverified_positive",
                        "category_surface_handling": "used_as_promo_evidence",
                        "repair_contract": {
                            "forbidden_meanings": [
                                "Other brands have promos."
                            ]
                        },
                    }
                ),
                "usage": {},
            }

    violation = _audit_promo_fact_answer(
        model_client=AuditModel(),
        current_user_message="If unavailable, what promo alternatives exist?",
        model_text='{"response_units":[]}',
        parsed_units=[
            {
                "type": "text",
                "content": {"text": "Other categories have promos."},
            }
        ],
        tool_results=[
            {
                "name": "search_promo_catalog",
                "full_result": {
                    "status": "ok",
                    "evidence_ref": "promo_search:test",
                    "requested_brands": ["Example Brand"],
                    "unmatched_requested_brands": ["Example Brand"],
                    "allowed_promo_refs": [],
                    "candidates": [],
                },
            }
        ],
        record={"llm_calls": []},
        round_name="typed_promo_audit_test",
    )

    assert violation is not None
    assert violation["type"] == "promo_fact_unsupported"
    assert violation["repair_contract"]["forbidden_meanings"] == [
        "Other brands have promos."
    ]


def test_promo_audit_accepts_scoped_no_verified_alternative_answer() -> None:
    class AuditModel:
        def complete(
            self,
            *,
            messages,
            tools,
            tool_choice="none",
            response_format=None,
            max_tokens=None,
            temperature=None,
        ):
            assert "complete truthful answer" in messages[0]["content"]
            packet = json.loads(messages[-1]["content"])
            search = packet["promo_evidence"]["promo_searches"][0]
            assert search["reviewed_search_scope_outcome"] == (
                "no_verified_applicable_promo_returned"
            )
            return {
                "content": json.dumps(
                    {
                        "decision": "supported",
                        "customer_requested_promo_fact": True,
                        "requested_promo_result_handling": (
                            "answered_within_scope"
                        ),
                        "customer_requested_alternatives": True,
                        "alternative_promo_handling": (
                            "explicitly_none_verified"
                        ),
                        "category_surface_handling": "not_present",
                        "unsupported_claims": [],
                        "missing_answers": [],
                        "reason": (
                            "The exact reviewed scope returned no alternative."
                        ),
                    }
                ),
                "usage": {},
                "cache_usage": {},
                "latency_ms": 1,
                "finish_reason": "stop",
            }

    evidence_ref = "promo_search:catalog-v1:scope"
    record = {"llm_calls": []}
    violation = _audit_promo_fact_answer(
        model_client=AuditModel(),
        current_user_message="If none match, what promo alternatives are valid?",
        model_text=json.dumps(
            {
                "claim_assertions": [
                    {
                        "category": "promo_facts",
                        "evidence_refs": [evidence_ref],
                    }
                ]
            }
        ),
        parsed_units=[
            {
                "type": "text",
                "content": {
                    "text": "No verified promo alternative was returned."
                },
            }
        ],
        tool_results=[
            {
                "name": "search_promo_catalog",
                "full_result": {
                    "status": "ok",
                    "evidence_ref": evidence_ref,
                    "requested_brands": ["Requested brand"],
                    "unmatched_requested_brands": ["Requested brand"],
                    "allowed_promo_refs": [],
                    "candidates": [],
                },
            }
        ],
        record=record,
        round_name="promo_audit_test",
    )

    assert violation is None
    assert record["llm_calls"][0]["component"] == "promo_fact_scope_audit"


def test_promo_audit_does_not_invent_category_surface_for_valid_gallery() -> None:
    class AuditModel:
        def complete(
            self,
            *,
            messages,
            tools,
            tool_choice="none",
            response_format=None,
            max_tokens=None,
            temperature=None,
        ):
            del messages, tools, tool_choice, response_format, max_tokens, temperature
            return {
                "content": json.dumps(
                    {
                        "decision": "supported",
                        "customer_requested_promo_fact": True,
                        "requested_promo_result_handling": "answered_within_scope",
                        "customer_requested_alternatives": False,
                        "alternative_promo_handling": "not_requested",
                        # Simulates the contradictory auxiliary label observed
                        # live even though no category surface was in context.
                        "category_surface_handling": "used_as_promo_evidence",
                        "unsupported_claims": [],
                        "missing_answers": [],
                        "reason": "The response is grounded in the promo gallery.",
                    }
                ),
                "usage": {},
            }

    promo_ref = "promo:catalog-v1:offer-1"
    record = {"llm_calls": []}
    violation = _audit_promo_fact_answer(
        model_client=AuditModel(),
        current_user_message="Ano ang current promos ninyo?",
        model_text='{"response_units":[]}',
        parsed_units=[
            {
                "type": "text",
                "content": {"text": "Ito po ang current promo options."},
            }
        ],
        tool_results=[
            {
                "name": "search_promo_catalog",
                "full_result": {
                    "status": "ok",
                    "evidence_ref": "promo_search:catalog-v1:scope",
                    "allowed_promo_refs": [promo_ref],
                    "candidates": [{"promo_ref": promo_ref}],
                },
            },
            {
                "name": "present_promo_gallery",
                "full_result": {
                    "status": "ok",
                    "presentation_ref": "promo_gallery_1",
                    "promo_refs": [promo_ref],
                },
            },
        ],
        record=record,
        round_name="valid_gallery_promo_audit_test",
    )

    assert violation is None
    assert record["promo_fact_scope_audits"][0]["decision"] == "supported"
    assert (
        record["promo_fact_scope_audits"][0]["category_surface_handling"]
        == "not_present"
    )


def test_promo_audit_rejects_catalog_no_match_as_product_promo_denial() -> None:
    class AuditModel:
        def complete(
            self,
            *,
            messages,
            tools,
            tool_choice="none",
            response_format=None,
            max_tokens=None,
            temperature=None,
        ):
            del tools, tool_choice, response_format, max_tokens, temperature
            assert "separate providers" in messages[0]["content"]
            assert "never require customer-visible catalog" in messages[0][
                "content"
            ]
            assert "no tire_size and no verified_product_promos" in messages[
                0
            ]["content"]
            packet = json.loads(messages[-1]["content"])
            boundary = packet["promo_evidence"]["promo_searches"][0][
                "search_scope_boundary"
            ]
            assert "cannot deny product-level" in boundary
            return {
                "content": json.dumps(
                    {
                        "decision": "supported",
                        "customer_requested_promo_fact": True,
                        "requested_promo_result_handling": (
                            "answered_within_scope"
                        ),
                        "customer_requested_alternatives": False,
                        "alternative_promo_handling": "not_requested",
                        "category_surface_handling": "not_present",
                        "negative_promo_scope_handling": (
                            "overgeneralized_across_providers"
                        ),
                        "unsupported_claims": [
                            "No active quantity promo exists."
                        ],
                        "missing_answers": [],
                        "repair_contract": {
                            "required_meanings": [
                                "Exact product promo price needs a tire size."
                            ],
                            "forbidden_meanings": [
                                "No product-level quantity promo exists."
                            ],
                        },
                        "reason": (
                            "The catalog no-match cannot deny product promos."
                        ),
                    }
                ),
                "usage": {},
            }

    violation = _audit_promo_fact_answer(
        model_client=AuditModel(),
        current_user_message="If ever, how much po yung bundle promo?",
        model_text='{"response_units":[]}',
        parsed_units=[
            {
                "type": "text",
                "content": {
                    "text": "Wala tayong active bundle promo ngayon."
                },
            }
        ],
        tool_results=[
            {
                "name": "search_promo_catalog",
                "full_result": {
                    "status": "ok",
                    "evidence_ref": "promo_search:catalog-v1:bundle",
                    "allowed_promo_refs": [],
                    "candidates": [],
                },
            }
        ],
        record={"llm_calls": []},
        round_name="cross_provider_negative_promo_audit_test",
    )

    assert violation is not None
    assert violation["type"] == "promo_fact_unsupported"
    assert violation["repair_contract"]["forbidden_meanings"] == [
        "No product-level quantity promo exists."
    ]


def test_promo_audit_accepts_grounded_proactive_promo_without_repair() -> None:
    class AuditModel:
        def complete(
            self,
            *,
            messages,
            tools,
            tool_choice="none",
            response_format=None,
            max_tokens=None,
            temperature=None,
        ):
            del messages, tools, tool_choice, response_format, max_tokens, temperature
            return {
                "content": json.dumps(
                    {
                        "decision": "incomplete",
                        "customer_requested_promo_fact": False,
                        "requested_promo_result_handling": "not_requested",
                        "customer_requested_alternatives": False,
                        "alternative_promo_handling": "not_requested",
                        "category_surface_handling": "non_promo_continuation",
                        "unsupported_claims": [],
                        "missing_answers": [],
                        "reason": "The proactive promo is fully grounded.",
                    }
                ),
                "usage": {},
            }

    promo_ref = "promo:catalog-v1:offer-1"
    record = {"llm_calls": []}
    violation = _audit_promo_fact_answer(
        model_client=AuditModel(),
        current_user_message="Greenfield Mandaluyong po location ko.",
        model_text='{"response_units":[]}',
        parsed_units=[
            {
                "type": "text",
                "content": {"text": "May verified Michelin promo."},
            }
        ],
        tool_results=[
            {
                "name": "search_promo_catalog",
                "full_result": {
                    "status": "ok",
                    "evidence_ref": "promo_search:catalog-v1:scope",
                    "allowed_promo_refs": [promo_ref],
                    "candidates": [{"promo_ref": promo_ref}],
                },
            }
        ],
        record=record,
        round_name="proactive_promo_audit_test",
    )

    assert violation is None
    assert record["promo_fact_scope_audits"][0]["decision"] == "supported"


def test_promo_audit_keeps_missing_requested_promo_as_incomplete() -> None:
    class AuditModel:
        def complete(
            self,
            *,
            messages,
            tools,
            tool_choice="none",
            response_format=None,
            max_tokens=None,
            temperature=None,
        ):
            del messages, tools, tool_choice, response_format, max_tokens, temperature
            return {
                "content": json.dumps(
                    {
                        "decision": "supported",
                        "customer_requested_promo_fact": True,
                        "requested_promo_result_handling": "not_requested",
                        "customer_requested_alternatives": False,
                        "alternative_promo_handling": "not_requested",
                        "category_surface_handling": "not_present",
                        "unsupported_claims": [],
                        "missing_answers": ["Requested promo result"],
                    }
                ),
                "usage": {},
            }

    violation = _audit_promo_fact_answer(
        model_client=AuditModel(),
        current_user_message="May promo ba?",
        model_text='{"response_units":[]}',
        parsed_units=[],
        tool_results=[
            {
                "name": "search_promo_catalog",
                "full_result": {
                    "status": "ok",
                    "evidence_ref": "promo_search:catalog-v1:scope",
                    "allowed_promo_refs": [],
                    "candidates": [],
                },
            }
        ],
        record={"llm_calls": []},
        round_name="requested_promo_audit_test",
    )

    assert violation is not None
    assert violation["type"] == "promo_fact_incomplete"


def test_safe_promo_fallback_keeps_scoped_facts_and_non_promo_surface() -> None:
    tool_results = [
            {
                "name": "search_promo_catalog",
                "full_result": {
                    "status": "ok",
                    "evidence_ref": "promo_search:catalog-v1:scope",
                    "tire_size": "175/65R14",
                    "requested_brands": ["Example Brand"],
                    "unmatched_requested_brands": ["Example Brand"],
                    "allowed_promo_refs": [],
                    "candidates": [],
                },
            },
            {
                "name": "discover_brand_buckets",
                "full_result": {
                    "status": "ok",
                    "presentation_ref": "price_categories:test",
                    "bucket_cards": [
                        {"bucket": "budget", "label": "Budget"},
                        {"bucket": "premium", "label": "Premium"},
                    ],
                },
            },
        ]
    units = _safe_promo_fact_units(tool_results)

    assert units == [
        {
            "type": "text",
            "content": {
                "text": (
                    "Sa current reviewed promos, wala pong verified promo na "
                    "tugma para sa Example Brand, size 175/65R14. Wala rin "
                    "pong verified promo alternative na bumalik para sa exact "
                    "search na ito."
                )
            },
        },
        {
            "type": "text",
            "content": {
                "text": (
                    "Puwede pa rin po kayong tumingin ng regular tire options "
                    "ayon sa price category. Hindi po promo alternatives ang "
                    "mga category na ito."
                )
            },
        },
        {
            "type": "render_surface",
            "content": {"surface_ref": "price_categories:test"},
        },
    ]
    assert _requires_provider_owned_empty_promo_result(tool_results) is True


def test_semantic_scope_repair_removes_generated_draft_anchors() -> None:
    messages = [
        {"role": "system", "content": "Compose from trusted facts."},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "draft_assistant_text": "Unsupported generated claim.",
                    "customer_turn_plan": {
                        "draft_conversational_content": (
                            "Same unsupported generated claim."
                        ),
                        "authorized_claim_categories": ["faq_facts"],
                    },
                    "tool_results": [
                        {
                            "name": "answer_policy_faq",
                            "status": "ok",
                        }
                    ],
                }
            ),
        },
    ]

    repaired = _semantic_scope_repair_base_messages(messages)
    payload = json.loads(repaired[-1]["content"])

    assert "draft_assistant_text" not in payload
    assert "draft_conversational_content" not in payload[
        "customer_turn_plan"
    ]
    assert payload["customer_turn_plan"][
        "authorized_claim_categories"
    ] == ["faq_facts"]
    assert payload["tool_results"][0]["status"] == "ok"
    assert "draft_assistant_text" in json.loads(messages[-1]["content"])


def test_answer_only_composer_omits_stale_progression_and_uses_payment_prompt() -> None:
    evidence_ref = "faq:order:installment"
    messages = _build_final_composer_messages(
        current_user_message="Paano po nagwo-work installment?",
        request_time="2026-08-03 21:00:00",
        active_working_memory="May prior product quote at kulang ang location.",
        recent_turns=[
            {"role": "assistant", "content": "May product options na po."}
        ],
        background_signals=[{"key": "location", "value": "QC"}],
        lead_qualification={"missing": ["location"]},
        order_readiness={"status": "not_ready"},
        capability_profile={"selected_domains": ["product", "order"]},
        tool_results=[
            {
                "name": "answer_order_faq",
                "full_result": {
                    "status": "ok",
                    "faq_id": "order_do_you_offer_installment_payments",
                    "evidence_ref": evidence_ref,
                    "question": "Do you offer installment payments?",
                    "answer": "May 3-month at BPI 6-month 0% installment.",
                },
                "result": {
                    "status": "ok",
                    "evidence_ref": evidence_ref,
                    "answer": "May 3-month at BPI 6-month 0% installment.",
                },
            }
        ],
        draft_assistant_text=(
            "May installment options. Anong city ninyo para ma-check ang "
            "installation?"
        ),
        customer_turn_plan={
            "turn_goal": "compose_grounded_customer_turn",
            "authorized_evidence_refs": [evidence_ref],
            "authorized_claim_categories": ["faq_facts", "payment_facts"],
            "draft_conversational_content": (
                "Anong city ninyo para ma-check ang installation?"
            ),
            "progression_context": {
                "authorized_evidence_refs_by_claim_category": {
                    "faq_facts": [evidence_ref],
                    "payment_facts": [evidence_ref],
                },
                "required_faq_fact_answers": [
                    {
                        "evidence_ref": evidence_ref,
                        "authored_answer": (
                            "May 3-month at BPI 6-month 0% installment."
                        ),
                    }
                ],
                "service_evidence_instruction": "Ask for location next.",
            },
        },
    )

    assert "payment inquiry" in messages[0]["content"]
    payload = json.loads(messages[-1]["content"])
    assert "draft_assistant_text" not in payload
    assert "decision_contract" not in payload
    assert "lead_qualification" not in payload
    assert "background_signals" not in payload
    assert "order_progression_context" not in payload
    assert "Anong city" not in messages[-1]["content"]
    assert payload["customer_turn_plan"]["authorized_evidence_refs"] == [
        evidence_ref
    ]
    assert payload["customer_turn_plan"]["progression_context"][
        "required_faq_fact_answers"
    ][0]["evidence_ref"] == evidence_ref


def test_payment_faq_with_selected_product_keeps_active_sales_continuation() -> None:
    evidence_ref = "faq:order:installment"
    selected = {
        "product_observation_ref": "obs_product_selected",
        "product_presentation_ref": "pres_product_selected",
        "product_summary": {
            "brand": "YOKOHAMA",
            "sku_model": "GEOLANDAR CV G058",
            "tire_size": "215/60R17",
        },
    }
    messages = _build_final_composer_messages(
        current_user_message="Ano pong installment available?",
        request_time="2026-08-10 10:00:00",
        active_working_memory=(
            "Customer selected a tire and is continuing the order inquiry."
        ),
        recent_turns=[],
        background_signals=[
            {
                "key": "location",
                "value": "Bacoor, Cavite",
                "source": "latest_user_message",
            }
        ],
        lead_qualification={},
        order_readiness={
            "status": "ready_for_summary",
            "customer_order_intent": "possible",
            "collected": {
                "Product": "YOKOHAMA GEOLANDAR CV G058",
                "Fulfillment": "delivery",
                "Delivery area": "Bacoor, Cavite",
            },
            "high_intent_signals": ["product selected"],
        },
        capability_profile={"selected_domains": ["order"]},
        tool_results=[
            {
                "name": "answer_order_faq",
                "full_result": {
                    "status": "ok",
                    "faq_id": "order_do_you_offer_installment_payments",
                    "evidence_ref": evidence_ref,
                    "answer": "May 3-month 0% installment under Pay Now.",
                },
                "result": {
                    "status": "ok",
                    "evidence_ref": evidence_ref,
                    "answer": "May 3-month 0% installment under Pay Now.",
                },
            }
        ],
        draft_assistant_text="May installment po.",
        selected_product_context=selected,
        customer_turn_plan={
            "known_customer_context": {
                "location": {
                    "value": "Bacoor, Cavite",
                    "requires_validation": False,
                }
            },
            "authorized_evidence_refs": [evidence_ref],
            "authorized_claim_categories": ["faq_facts", "payment_facts"],
        },
    )

    payload = json.loads(messages[-1]["content"])
    assert payload["validated_selected_product"][
        "product_observation_ref"
    ] == "obs_product_selected"
    assert payload["order_readiness"]["collected"][
        "Delivery area"
    ] == "Bacoor, Cavite"
    assert payload["customer_turn_plan"]["known_customer_context"][
        "location"
    ]["value"] == "Bacoor, Cavite"
    normalized_prompt = " ".join(messages[0]["content"].split()).casefold()
    assert "para sa tanong ninyo tungkol sa" in normalized_prompt
    assert "start with the useful subject and answer directly" in normalized_prompt


def test_answer_only_non_payment_order_faq_keeps_general_composer_prompt() -> None:
    evidence_ref = "faq:order:formal_quotation"
    messages = _build_final_composer_messages(
        current_user_message="Can I request a formal company quotation?",
        request_time="2026-08-03 21:00:00",
        active_working_memory="Prior product context.",
        recent_turns=[],
        background_signals=[],
        lead_qualification={"missing": ["quantity"]},
        order_readiness={},
        capability_profile={"selected_domains": ["order"]},
        tool_results=[
            {
                "name": "answer_order_faq",
                "args": {
                    "faq_id": "order_can_i_request_a_formal_quotation"
                },
                "full_result": {
                    "status": "ok",
                    "faq_id": "order_can_i_request_a_formal_quotation",
                    "evidence_ref": evidence_ref,
                    "answer": "CS can prepare and confirm the document.",
                },
                "result": {
                    "status": "ok",
                    "faq_id": "order_can_i_request_a_formal_quotation",
                    "evidence_ref": evidence_ref,
                    "answer": "CS can prepare and confirm the document.",
                },
            }
        ],
        draft_assistant_text="Please share the tire size and quantity.",
        customer_turn_plan={
            "authorized_evidence_refs": [evidence_ref],
            "authorized_claim_categories": ["faq_facts"],
        },
    )

    assert "payment inquiry" not in messages[0]["content"]
    assert "final response composer" in messages[0]["content"].lower()
    payload = json.loads(messages[-1]["content"])
    assert "draft_assistant_text" not in payload
    assert payload["tool_results"][0]["result"]["faq_id"] == (
        "order_can_i_request_a_formal_quotation"
    )


def test_mixed_tool_composer_keeps_progression_context() -> None:
    messages = _build_final_composer_messages(
        current_user_message="May installment at magkano yung options?",
        request_time="2026-08-03 21:00:00",
        active_working_memory="",
        recent_turns=[],
        background_signals=[],
        lead_qualification={"missing": ["location"]},
        order_readiness={},
        capability_profile={"selected_domains": ["product", "order"]},
        tool_results=[
            {
                "name": "answer_order_faq",
                "result": {"status": "ok", "answer": "May installment."},
            },
            {
                "name": "product_search",
                "result": {
                    "status": "ok",
                    "presentation_ref": "product_surface_1",
                },
            },
        ],
        draft_assistant_text="May installment at product choices po.",
        customer_turn_plan={
            "authorized_evidence_refs": ["product_surface_1"],
            "authorized_claim_categories": [
                "faq_facts",
                "product_facts",
            ],
        },
    )

    payload = json.loads(messages[-1]["content"])
    assert payload["draft_assistant_text"] == (
        "May installment at product choices po."
    )
    assert "decision_contract" not in payload
    assert "surface_authorization" in payload
    assert "lead_qualification" in payload


def test_semantic_scope_retry_keeps_authority_but_omits_customer_anchors() -> None:
    messages = [
        {"role": "system", "content": "Compose a schema response."},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "current_customer_message": "Can you deliver to Exact Place?",
                    "recent_turns": [
                        {
                            "role": "user",
                            "content": "Can you deliver to Exact Place?",
                        }
                    ],
                    "active_working_memory": "Customer location is Exact Place.",
                    "background_signals": [
                        {"key": "location", "value": "Exact Place"}
                    ],
                    "customer_turn_plan": {
                        "authorized_evidence_refs": ["faq:delivery"],
                        "authorized_claim_categories": ["faq_facts"],
                    },
                    "customer_voice_contract": {"language": "Taglish"},
                    "tool_results": [
                        {
                            "name": "answer_policy_faq",
                            "args": {"question": "Exact Place?"},
                        }
                    ],
                    "draft_assistant_text": "Yes, Exact Place is covered.",
                }
            ),
        },
    ]
    retry = _build_semantic_scope_retry_messages(
        final_messages=messages,
        semantic_scope_violations=[
            {
                "type": "answer_goal_unsupported",
                "repair_contract": {
                    "required_meanings": ["Exact case remains pending."],
                    "forbidden_meanings": ["Exact case is covered."],
                },
            }
        ],
        policy_evidence=[
            {
                "evidence_ref": "faq:delivery",
                "applicability": "policy_general",
                "authored_answer": "General delivery is available.",
                "composition_boundary": (
                    "Do not confirm a narrower serviceability result."
                ),
            }
        ],
        promo_evidence={},
    )
    payload = json.loads(retry[-1]["content"])

    assert "Exact Place" not in retry[-1]["content"]
    assert "current_customer_message" not in payload
    assert "recent_turns" not in payload
    assert "tool_results" not in payload
    assert payload["general_policy_evidence"][0]["evidence_ref"] == (
        "faq:delivery"
    )
    assert payload["customer_turn_plan"]["authorized_evidence_refs"] == [
        "faq:delivery"
    ]
    assert payload["customer_voice_contract"] == {"language": "Taglish"}
    assert payload["semantic_scope_constraints"]["answer_goal_scope"] == {
        "allowed_answer_scope": (
            "authored FAQ facts that directly answer the customer request"
        ),
        "unrelated_faq_answers": "omit",
        "customer_origin_details": "omit unless separately authorized",
        "exact_case_status": "not confirmed and still pending",
        "broad_policy_alone_is_insufficient": True,
        "direct_case_answer": "do_not_answer_yes_or_no",
    }
    assert "explicit exact-case status" in payload["instruction"]
    assert payload["model_semantic_repair_contracts"] == [
        {
            "required_meanings": ["Exact case remains pending."],
            "forbidden_meanings": ["Exact case is covered."],
        }
    ]


def test_semantic_scope_retry_marks_empty_promo_surface_as_non_promo() -> None:
    messages = [
        {"role": "system", "content": "Compose a schema response."},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "customer_turn_plan": {
                        "authorized_evidence_refs": ["promo_search:test"]
                    },
                    "presentation_surfaces": [
                        {
                            "surface_ref": "price_categories:test",
                            "type": "price_category_choices",
                        }
                    ],
                }
            ),
        },
    ]

    retry = _build_semantic_scope_retry_messages(
        final_messages=messages,
        semantic_scope_violations=[
            {
                "type": "promo_fact_unsupported",
                "repair_contract": {
                    "required_meanings": ["No verified alternative."],
                    "renderer_surface_roles": ["Non-promo continuation."],
                },
            }
        ],
        policy_evidence=[],
        promo_evidence={
            "promo_searches": [
                {
                    "provider_available": True,
                    "tire_size": "175/65R14",
                    "requested_brands": ["Example Brand"],
                    "unmatched_requested_brands": ["Example Brand"],
                    "applicable_promo_refs": [],
                }
            ],
            "category_choice_surfaces": [
                {"surface_ref": "price_categories:test"}
            ],
        },
    )
    payload = json.loads(retry[-1]["content"])

    assert "promo_evidence" not in payload
    assert payload["promo_response_contract"]["promo_searches"][0][
        "requested_brands"
    ] == ["Example Brand"]

    assert payload["semantic_scope_constraints"][
        "empty_promo_search_scope"
    ] == {
        "required_scoped_negative_results": [
            {
                "tire_size": "175/65R14",
                "requested_brands": ["Example Brand"],
                "unmatched_requested_brands": ["Example Brand"],
                "applicable_promo_count": 0,
            }
        ],
        "required_negative_answer": "state every scoped negative result",
        "verified_alternative_promo_count": 0,
        "alternative_promo_availability": "none_verified",
        "promo_alternative_result": (
            "no verified applicable alternative was returned by this search"
        ),
        "required_alternative_answer": (
            "state that no verified applicable alternative was returned"
        ),
        "category_surface_role": "non-promo shopping continuation",
        "required_category_surface_meaning": (
            "choose a price category to continue ordinary product shopping"
        ),
        "allowed_promo_claim_scope": (
            "only the requested-brand negative results listed above"
        ),
        "other_brand_promo_claims": (
            "forbidden_without_verified_promo_refs"
        ),
        "forbidden_category_implication": (
            "promo, discount, bundle, free item, or eligibility"
        ),
        "required_customer_answer_meanings": [
            {
                "meaning": "requested search scope has no matching promo",
                "scopes": [
                    {
                        "tire_size": "175/65R14",
                        "requested_brands": ["Example Brand"],
                        "unmatched_requested_brands": ["Example Brand"],
                        "applicable_promo_count": 0,
                    }
                ],
            },
            {
                "meaning": "no verified promo alternative was returned",
                "verified_alternative_promo_count": 0,
            },
            {
                "meaning": (
                    "price categories are ordinary product shopping choices, "
                    "not promo alternatives"
                )
            },
        ],
    }


def test_typed_brand_claim_contract_rejects_unpublished_manufacturer_scope() -> None:
    profile_ref = "brand_profile:brand-v1:apollo"
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                {
                    "name": "get_brand_knowledge",
                    "full_result": {
                        "status": "ok",
                        "profiles": [
                            {
                                "profile_ref": profile_ref,
                                "brand": "APOLLO",
                                "manufacturer_warranty": {
                                    "duration_years": 5,
                                    "display": "5 years",
                                    "authorized_fields": [
                                        "duration_years",
                                        "display",
                                    ],
                                    "unpublished_fields": ["coverage"],
                                },
                                "gulong_guarantee": {
                                    "duration_years": 1,
                                    "coverage": ["All tire damage."],
                                    "conditions": [
                                        "Bought from Gulong.ph.",
                                        "Installed by an authorized partner.",
                                    ],
                                },
                                "evidence_refs": [profile_ref],
                            }
                        ],
                    },
                }
            ],
        },
        order_readiness={},
        draft_assistant_text="Apollo warranty details.",
        validated_choice_context={},
    )

    violations = _final_composer_claim_contract_violations(
        (
            '{"claim_assertions":[{"category":"brand_facts",'
            '"response_unit_indexes":[0],'
            f'"evidence_refs":["{profile_ref}"],'
            '"fact_fields":["manufacturer_warranty.coverage"]}],'
            '"response_units":[{"type":"text","content":{"text":'
            '"Factory defects are covered."}}]}'
        ),
        plan,
    )

    assert {item["type"] for item in violations} == {
        "unauthorized_brand_fact_fields",
    }


def test_typed_brand_claim_contract_requires_full_gulong_conditions() -> None:
    profile_ref = "brand_profile:brand-v1:apollo"
    turn_plan = {
        "authorized_claim_categories": ["brand_facts"],
        "authorized_evidence_refs": [profile_ref],
        "progression_context": {
            "authorized_evidence_refs_by_claim_category": {
                "brand_facts": [profile_ref],
            },
            "authorized_brand_fact_fields_by_evidence_ref": {
                profile_ref: [
                    "gulong_guarantee.duration_years",
                    "gulong_guarantee.coverage",
                    "gulong_guarantee.conditions",
                ]
            },
        },
    }

    violations = _final_composer_claim_contract_violations(
        (
            '{"claim_assertions":[{"category":"brand_facts",'
            '"response_unit_indexes":[0],'
            f'"evidence_refs":["{profile_ref}"],'
            '"fact_fields":["gulong_guarantee.coverage"]}],'
            '"response_units":[{"type":"text","content":{"text":'
            '"All damage is covered."}}]}'
        ),
        turn_plan,
    )

    assert {item["type"] for item in violations} == {
        "gulong_coverage_missing_published_conditions",
    }


def test_final_response_schema_accepts_generic_tire_advisory_claims() -> None:
    payload = RuntimeV7FinalResponseModel(
        claim_assertions=[
            {
                "category": "general_tire_advisory",
                "response_unit_indexes": [0],
                "evidence_refs": [],
            }
        ],
        response_units=[
            {
                "type": "text",
                "content": {
                    "text": (
                        "Touring tires generally prioritize everyday comfort."
                    )
                },
            }
        ],
    )

    assert payload.claim_assertions[0].category == "general_tire_advisory"


def test_validated_promo_details_seed_authorizes_reviewed_promo_facts() -> None:
    source_ref = (
        "gs://promo-catalog/catalog-v1/parsed/mechanics.txt"
    )
    plan = _build_customer_turn_plan(
        record={
            "response_seeds": [
                {
                    "type": "promo_action",
                    "evidence": {
                        "status": "valid",
                        "action": "promo_details",
                        "catalog_version_id": "catalog-v1",
                        "promo": {
                            "promo_ref": "promo:apollo-3plus1",
                            "evidence_refs": [source_ref],
                            "relevant_mechanics": [
                                {
                                    "text": "Same size and model.",
                                    "evidence_refs": [source_ref],
                                }
                            ],
                        },
                    },
                }
            ],
            "tool_results": [],
        },
        order_readiness={},
        draft_assistant_text="Reviewed Apollo promo details.",
        validated_choice_context={},
    )

    assert "promo_facts" in plan["authorized_claim_categories"]
    assert plan["progression_context"][
        "authorized_evidence_refs_by_claim_category"
    ]["promo_facts"] == [
        "promo:apollo-3plus1",
        "catalog-v1",
        source_ref,
    ]
    assert source_ref in plan["authorized_evidence_refs"]
    assert _final_composer_claim_contract_violations(
        (
            '{"claim_assertions":[{"category":"promo_facts",'
            '"response_unit_indexes":[0],"evidence_refs":['
            f'"{source_ref}"'
            ']}],"response_units":[{"type":"text","content":'
            '{"text":"Apollo promo details."}}]}'
        ),
        plan,
    ) == []


def test_validated_about_brand_seed_authorizes_published_brand_fields() -> None:
    profile_ref = "brand_profile:brand-v1:apollo"
    source_ref = "https://gulong.ph/brands/apollo"
    plan = _build_customer_turn_plan(
        record={
            "response_seeds": [
                {
                    "type": "promo_action",
                    "evidence": {
                        "status": "valid",
                        "action": "about_brand",
                        "catalog_version_id": "catalog-v1",
                        "selected_brand": "Apollo",
                        "brand_profile": {
                            "profile_ref": profile_ref,
                            "brand": "APOLLO",
                            "about_brand": "Apollo is an Indian tire brand.",
                            "origin_country": "India",
                            "manufacturer_warranty": {
                                "duration_years": 5,
                                "display": "5 years",
                                "authorized_fields": [
                                    "duration_years",
                                    "display",
                                ],
                            },
                            "evidence_refs": [source_ref],
                        },
                    },
                }
            ],
            "tool_results": [],
        },
        order_readiness={},
        draft_assistant_text="Apollo brand background.",
        validated_choice_context={},
    )

    fields_by_ref = plan["progression_context"][
        "authorized_brand_fact_fields_by_evidence_ref"
    ]
    expected_fields = [
        "brand",
        "about_brand",
        "origin_country",
        "manufacturer_warranty.display",
        "manufacturer_warranty.duration_years",
    ]
    assert fields_by_ref[profile_ref] == expected_fields
    assert fields_by_ref[source_ref] == expected_fields
    assert _final_composer_claim_contract_violations(
        (
            '{"claim_assertions":[{"category":"brand_facts",'
            '"response_unit_indexes":[0],'
            f'"evidence_refs":["{profile_ref}"],'
            '"fact_fields":["about_brand","origin_country"]}],'
            '"response_units":[{"type":"text","content":{"text":'
            '"Apollo is an Indian tire brand."}}]}'
        ),
        plan,
    ) == []


def test_unmatched_requested_promo_exposes_grounded_surfaces_without_priority() -> None:
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                _product_tool_result(brand="TOYO"),
                {
                    "name": "search_promo_catalog",
                    "full_result": {
                        "status": "ok",
                        "requested_brands": ["Toyo"],
                        "unmatched_requested_brands": ["Toyo"],
                    },
                },
                _promo_gallery_tool_result(),
            ],
        },
        order_readiness={"collected": {"Quantity": "4 tires"}},
        draft_assistant_text=(
            "Walang current reviewed 3+1 para sa Toyo; "
            "may ibang valid options."
        ),
        validated_choice_context={},
    )

    assert {
        surface["decision_layer"]
        for surface in plan["available_surfaces"]
    } == {"promo_catalog", "product"}


def test_api_verified_promo_brand_exposes_product_and_promo_surfaces() -> None:
    product_result = _product_tool_result(brand="VREDESTEIN")
    product_result["full_result"]["promo_evidence"] = {
        "authority": "gulong_api_promo_brands",
        "verified_brands": ["APOLLO", "MICHELIN", "VREDESTEIN"],
    }
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                product_result,
                {
                    "name": "search_promo_catalog",
                    "full_result": {
                        "status": "ok",
                        "requested_brands": ["Vredestein"],
                        "unmatched_requested_brands": ["Vredestein"],
                    },
                },
                _promo_gallery_tool_result(),
            ],
        },
        order_readiness={"collected": {"Quantity": "4 tires"}},
        draft_assistant_text="May matching Vredestein 3+1 option.",
        validated_choice_context={},
    )

    assert {
        surface["decision_layer"]
        for surface in plan["available_surfaces"]
    } == {"product", "promo_catalog"}


def test_brandless_promo_without_size_exposes_grounded_surfaces() -> None:
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                _product_tool_result(brand="MICHELIN"),
                {
                    "name": "search_promo_catalog",
                    "full_result": {
                        "status": "ok",
                        "tire_size": None,
                        "requested_brands": [],
                        "unmatched_requested_brands": [],
                    },
                },
                _promo_gallery_tool_result(),
            ],
        },
        order_readiness={"collected": {"Quantity": "4 tires"}},
        draft_assistant_text="Ito ang current Buy 3 Get 1 promos.",
        validated_choice_context={},
    )

    assert {
        surface["decision_layer"]
        for surface in plan["available_surfaces"]
    } == {"promo_catalog", "product"}


def test_reviewed_promo_and_price_categories_are_available_without_priority() -> None:
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                {
                    "name": "search_promo_catalog",
                    "full_result": {
                        "status": "ok",
                        "tire_size": "195/65R15",
                        "requested_brands": [],
                        "unmatched_requested_brands": [],
                    },
                },
                _promo_gallery_tool_result(),
                {
                    "name": "discover_brand_buckets",
                    "full_result": {
                        "status": "ok",
                        "presentation_ref": "price_categories_1",
                        "bucket_cards": [
                            {"bucket": "economy", "label": "Economy"},
                            {"bucket": "premium", "label": "Premium"},
                        ],
                    },
                },
            ],
        },
        order_readiness={"collected": {"Quantity": "4 tires"}},
        draft_assistant_text="May active promos para sa size ninyo.",
        validated_choice_context={},
    )

    assert {
        surface["decision_layer"]
        for surface in plan["available_surfaces"]
    } == {"promo_catalog", "price_category"}


def test_installation_slot_tool_requires_explicit_discovery_mode() -> None:
    schema = next(
        tool["function"]
        for tool in ALL_RUNTIME_V7_TOOL_SCHEMAS
        if tool["function"]["name"] == "find_installation_slots"
    )

    parameters = schema["parameters"]
    discovery_mode = parameters["properties"]["discovery_mode"]

    assert parameters["required"] == ["discovery_mode"]
    assert discovery_mode["type"] == "string"
    assert set(discovery_mode["enum"]) == {
        "exact_city_slots",
        "recommend_serviceable_cities",
    }
    assert discovery_mode.get("description")


def test_turn_authorization_fallback_preserves_model_text_and_drops_unknown_surface() -> None:
    surface = _city_surface()
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [],
            "location_choice_surface": surface,
        },
        order_readiness={"collected": {}},
        draft_assistant_text="",
        validated_choice_context={
            "validation_status": "valid",
            "choice_type": "serviceable_province",
            "label": "Pampanga",
        },
    )

    units = _enforce_renderer_owned_unit_contract(
        [
            {"type": "text", "content": {"text": "Pili po ng city."}},
            {
                "type": "render_surface",
                "content": {"surface_ref": "unknown"},
            },
        ],
        [],
        customer_turn_plan=plan,
    )

    assert units == [
        {"type": "text", "content": {"text": "Pili po ng city."}},
        {
            "type": "render_surface",
            "content": {"surface_ref": surface["presentation_ref"]},
        },
    ]


def test_turn_authorization_fallback_does_not_invent_order_summary_or_cta() -> None:
    plan = {
        "available_surfaces": [
            {
                "surface_ref": "order_summary_1",
                "surface_type": "order_summary",
                "decision_layer": "order_summary",
                "missing_fields": [
                    "Contact number",
                    "Customer name",
                    "Email",
                    "Payment option",
                ],
            }
        ],
    }

    units = _enforce_renderer_owned_unit_contract(
        [{"type": "text", "content": {"text": "Choose an option."}}],
        [],
        customer_turn_plan=plan,
    )

    assert units == [
        {"type": "text", "content": {"text": "Choose an option."}}
    ]


def test_service_action_contract_rejects_unsubmitted_schedule_confirmation() -> None:
    violations = _final_composer_service_action_contract_violations(
        [
            {
                "type": "text",
                "content": {
                    "text": (
                        "Okay, we've confirmed your installation schedule "
                        "for July 28 at 8:30 AM."
                    )
                },
            }
        ],
        validated_installation_context={
            "validation_status": "slot_validated",
            "selected_slot": {
                "date": "2026-07-28",
                "time_text": "8:30 AM",
            },
        },
        customer_turn_plan={"authorized_side_effects": []},
    )

    assert violations == [
        {
            "type": "unauthorized_schedule_mutation_claim",
            "unit_index": 0,
            "instruction": (
                "The selected schedule, appointment, or installation is "
                "validated only for order review. Describe the customer's "
                "preferred slot as selected or available, and do not imply "
                "that the booking is complete."
            ),
        }
    ]


def test_service_action_contract_rejects_confirmed_installation_without_submission() -> None:
    """Cover the customer-visible phrasing found by live human/CS review."""

    violations = _final_composer_service_action_contract_violations(
        [
            {
                "type": "text",
                "content": {
                    "text": (
                        "Okay po, na-confirm na natin ang installation niyo "
                        "sa Dasmarinas sa August 3, 8:00 AM."
                    )
                },
            }
        ],
        validated_installation_context={
            "validation_status": "slot_validated",
            "selected_slot": {
                "date": "2026-08-03",
                "time_text": "8:00 AM",
            },
        },
        customer_turn_plan={"authorized_side_effects": []},
    )

    assert [item["type"] for item in violations] == [
        "unauthorized_schedule_mutation_claim"
    ]


def test_service_action_contract_checks_full_sentence_not_character_window() -> None:
    violations = _final_composer_service_action_contract_violations(
        [
            {
                "type": "text",
                "content": {
                    "text": (
                        "Okay po, na-confirm na natin yung FRONWAY "
                        "175/65/R14 ECOGREEN ONE 82V na apat na gulong "
                        "for installation sa partner sa August 3, 8:00 AM."
                    )
                },
            }
        ],
        validated_installation_context={
            "validation_status": "slot_validated",
            "selected_slot": {
                "date": "2026-08-03",
                "time_text": "8:00 AM",
            },
        },
        customer_turn_plan={"authorized_side_effects": []},
    )

    assert [item["type"] for item in violations] == [
        "unauthorized_schedule_mutation_claim"
    ]


def test_service_action_contract_allows_read_only_schedule_wording() -> None:
    units = [
        {
            "type": "text",
            "content": {
                "text": (
                    "Selected na yung July 28, 8:30 AM for order review. "
                    "Hindi pa ito booked or reserved."
                )
            },
        }
    ]

    assert (
        _final_composer_service_action_contract_violations(
            units,
            validated_installation_context={
                "validation_status": "slot_validated",
                "selected_slot": {
                    "date": "2026-07-28",
                    "time_text": "8:30 AM",
                },
            },
            customer_turn_plan={"authorized_side_effects": []},
        )
        == []
    )


def test_service_action_contract_allows_authorized_submitted_order() -> None:
    units = [
        {
            "type": "text",
            "content": {
                "text": "Confirmed na yung installation schedule ninyo."
            },
        }
    ]

    assert (
        _final_composer_service_action_contract_violations(
            units,
            validated_installation_context={
                "validation_status": "slot_validated",
                "selected_slot": {
                    "date": "2026-07-28",
                    "time_text": "8:30 AM",
                },
            },
            customer_turn_plan={"authorized_side_effects": ["submit_order"]},
        )
        == []
    )


def test_structural_validator_does_not_phrase_match_model_cta() -> None:
    plan = {
        "available_surfaces": [],
        "already_satisfied_fields": [
            "Preferred installation schedule",
        ],
    }

    violations = _final_composer_renderer_contract_violations(
        [
            {
                "type": "text",
                "content": {
                    "text": (
                        "Noted po. Ano ang preferred installation schedule "
                        "ninyo?"
                    )
                },
            }
        ],
        [],
        customer_turn_plan=plan,
    )

    assert violations == []


def test_turn_plan_does_not_treat_unvalidated_schedule_preference_as_satisfied(
) -> None:
    surface = _city_surface()
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [],
            "location_choice_surface": surface,
        },
        order_readiness={
            "collected": {
                "Installation area": "Pampanga",
                "Preferred installation schedule": "earliest",
            },
            "schedule_status": "unvalidated",
        },
        draft_assistant_text=(
            "Choose a city so we can check the earliest schedule."
        ),
        validated_choice_context={},
    )

    assert "Installation area" in plan["already_satisfied_fields"]
    assert (
        "Preferred installation schedule"
        not in plan["already_satisfied_fields"]
    )
    assert _final_composer_renderer_contract_violations(
        [
            {
                "type": "text",
                "content": {
                    "text": (
                        "Pili po ng city para ma-check natin ang earliest "
                        "installation schedule."
                    )
                },
            },
            {
                "type": "render_surface",
                "content": {
                    "surface_ref": surface["presentation_ref"],
                },
            },
        ],
        [],
        customer_turn_plan=plan,
    ) == []


def test_turn_plan_keeps_accepted_flexible_schedule_as_satisfied() -> None:
    plan = _build_customer_turn_plan(
        record={"tool_results": []},
        order_readiness={
            "collected": {
                "Preferred installation schedule": (
                    "Anytime in the afternoon"
                ),
            },
            "schedule_status": "flexible_preference",
        },
        draft_assistant_text="Noted po.",
        validated_choice_context={},
    )

    assert plan["already_satisfied_fields"] == [
        "Preferred installation schedule"
    ]


def test_renderer_preserves_composer_order_for_location_surface(monkeypatch) -> None:
    monkeypatch.setenv(
        "PRICE_CATEGORY_LIVE_ROUTER_FLOW_NAMESPACE",
        "content_router",
    )
    surface = _city_surface()
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [],
            "location_choice_surface": surface,
        },
        order_readiness={"collected": {}},
        draft_assistant_text="",
        validated_choice_context={
            "validation_status": "valid",
            "choice_type": "serviceable_province",
            "label": "Pampanga",
        },
    )
    rendered = render_turn_for_channel(
        {
            "assistant_text": (
                '{"response_units":['
                '{"type":"text","content":{"text":"Pampanga po. Pili tayo ng city."}},'
                '{"type":"render_surface","content":{"surface_ref":"'
                + surface["presentation_ref"]
                + '"}},'
                '{"type":"text","content":{"text":"Aling city ang convenient sa inyo?"}}'
                "]}"
            ),
            "runtime_final_response": "",
            "tool_results": [],
            "location_choice_surface": surface,
            "customer_turn_plan": plan,
        }
    )

    assert [message["type"] for message in rendered.content_messages] == [
        "text",
        "cards",
        "text",
    ]
    assert rendered.content_messages[0]["text"].startswith("Pampanga")
    assert rendered.content_messages[-1]["text"].startswith("Aling city")


def test_province_only_tool_plan_is_rejected_before_service_execution() -> None:
    rejection = _location_tool_plan_rejection(
        name="find_installation_slots",
        validated_choice_context={
            "validation_status": "valid",
            "choice_type": "serviceable_province",
        },
        background_signals=[],
    )
    free_text_rejection = _location_tool_plan_rejection(
        name="find_installation_partners",
        validated_choice_context={},
        background_signals=[
            {
                "key": "location",
                "value": "Pampanga",
                "source": "latest_user_message",
                "resolution": {
                    "province_hint": "Pampanga",
                    "city_hint": None,
                    "location_precision": "province_or_region",
                },
            }
        ],
    )
    exact_city = _location_tool_plan_rejection(
        name="find_installation_slots",
        validated_choice_context={},
        background_signals=[
            {
                "key": "location",
                "value": "San Fernando, Pampanga",
                "source": "latest_user_message",
                "resolution": {
                    "province_hint": "Pampanga",
                    "city_hint": "San Fernando",
                    "location_precision": "city_or_area",
                },
            }
        ],
    )

    assert rejection["location_precision"] == "province_only"
    assert free_text_rejection["source"] == (
        "normalized_latest_customer_location"
    )
    assert exact_city == {}
    persisted_province = _location_tool_plan_rejection(
        name="find_installation_slots",
        validated_choice_context={},
        background_signals=[
            {
                "key": "location",
                "value": "Pampanga",
                "source": "signal_ledger",
                "resolution": {
                    "province_hint": "Pampanga",
                    "city_hint": None,
                    "location_precision": "province_or_region",
                },
            }
        ],
    )
    assert persisted_province["source"] == "validated_location_state"


def test_contact_followup_location_redirect_is_not_a_tool_error() -> None:
    expected_redirect = {
        "required_decision_layer": "contact_followup",
        "source": "semantic_current_turn_location_response_status",
    }
    ordinary_rejection = {
        "required_decision_layer": "city",
        "source": "validated_location_state",
    }
    partner_coverage_redirect = {
        "required_decision_layer": "service_partner_coverage",
        "source": "typed_service_slot_prerequisites",
    }

    assert _location_plan_rejection_result_status(expected_redirect) == (
        "not_applicable"
    )
    assert _location_plan_rejection_result_status(partner_coverage_redirect) == (
        "not_applicable"
    )
    assert _location_plan_rejection_result_status(ordinary_rejection) == "error"


def test_turn_plan_authorizes_validated_installation_selection_evidence() -> None:
    plan = _build_customer_turn_plan(
        record={"tool_results": [], "response_seeds": []},
        order_readiness={"collected": {}},
        validated_installation_context={
            "validation_status": "slot_validated",
            "service_location": {"name": "YABIJA TIRE CENTER"},
            "selected_slot": {
                "date": "2026-09-20",
                "time_text": "8:00 AM",
            },
        },
    )

    assert "validated_installation_selection" in plan[
        "authorized_evidence_refs"
    ]
    refs_by_category = plan["progression_context"][
        "authorized_evidence_refs_by_claim_category"
    ]
    assert refs_by_category["validated_state"] == [
        "validated_installation_selection"
    ]
    assert refs_by_category["order_facts"] == [
        "validated_installation_selection"
    ]


def test_required_supporting_surface_is_completed_without_model_repair() -> None:
    plan = {
        "available_surfaces": [
            {
                "surface_ref": "pres_products_1",
                "required": True,
                "response_role": "direct_answer",
                "decision_layer": "product",
            },
            {
                "surface_ref": "promo_gallery_1",
                "required": True,
                "response_role": "supporting_replacement",
                "decision_layer": "promo",
                "supporting_context": True,
            },
        ],
        "request_obligations": [
            {
                "obligation_id": "surface:pres_products_1",
                "required_response_modes": ["surface"],
                "authorized_surface_refs": ["pres_products_1"],
            }
        ],
    }
    payload = {
        "request_coverage": [
            {
                "obligation_id": "surface:pres_products_1",
                "disposition": "answered",
                "response_unit_indexes": [0],
                "surface_refs": ["pres_products_1"],
            }
        ],
        "response_units": [
            {
                "type": "render_surface",
                "content": {"surface_ref": "pres_products_1"},
            }
        ],
    }

    text, units, completed = _complete_required_supporting_replacement_surfaces(
        json.dumps(payload),
        payload["response_units"],
        customer_turn_plan=plan,
    )

    assert completed == ["promo_gallery_1"]
    assert json.loads(text)["response_units"] == units
    assert [unit["content"]["surface_ref"] for unit in units] == [
        "pres_products_1",
        "promo_gallery_1",
    ]
    assert _final_composer_renderer_contract_violations(
        units,
        [],
        customer_turn_plan=plan,
    ) == []


def test_validated_city_choice_outranks_stale_province_for_service_lookup() -> None:
    rejection = _location_tool_plan_rejection(
        name="find_installation_slots",
        execution_args={"location": "Las Piñas, Metro Manila"},
        validated_choice_context={
            "validation_status": "valid",
            "choice_type": "serviceable_city",
            "label": "Las Piñas",
            "province_label": "Metro Manila",
        },
        background_signals=[
            {
                "key": "location",
                "value": "Metro Manila",
                "source": "signal_ledger",
                "resolution": {
                    "province_hint": "Metro Manila",
                    "city_hint": None,
                    "location_precision": "province_only",
                },
            }
        ],
    )

    assert rejection == {}


def test_validated_city_boundary_restores_choice_authority_after_extraction() -> None:
    state_context = {
        "background_signals": [
            {
                "key": "tire_size",
                "value": "205/55R16",
                "source": "signal_ledger",
                "relation": "asserted",
            },
            {
                "key": "location",
                "value": "Metro Manila",
                "source": "latest_user_message",
                "status": "mentioned_by_latest_user_message",
                "relation": "asserted",
                "safe_for_action": False,
            },
            {
                "key": "service_type",
                "value": "installation",
                "source": "latest_user_message",
                "status": "mentioned_by_latest_user_message",
                "relation": "asserted",
                "safe_for_action": False,
            },
        ],
        "missing_info": {"order_readiness": {"status": "not_ready"}},
    }

    _apply_validated_choice_signal_boundaries(
        state_context,
        validated_choice_context={
            "validation_status": "valid",
            "choice_type": "serviceable_city",
            "label": "Las Piñas",
            "province_label": "Metro Manila",
            "choice_ref": "city_las_pinas",
            "presentation_ref": "locations_metro_manila",
        },
    )

    signal_map = {
        signal["key"]: signal for signal in state_context["background_signals"]
    }
    assert signal_map["location"]["value"] == "Las Piñas, Metro Manila"
    assert signal_map["location"]["source"] == "validated_choice_action"
    assert signal_map["location"]["safe_for_action"] is True
    assert signal_map["service_type"]["source"] == "validated_choice_action"
    assert state_context["missing_info"]["lead_qualification"]["present"][
        "location"
    ] == "Las Piñas, Metro Manila"


def test_validated_city_signals_are_current_for_service_tool_objective() -> None:
    objectives = build_tool_objectives(
        background_signals=[
            {
                "key": "location",
                "value": "Las Piñas, Metro Manila",
                "source": "validated_choice_action",
                "status": "tool_grounded",
                "safe_for_action": True,
                "resolution": {
                    "city_hint": "Las Piñas",
                    "province_hint": "Metro Manila",
                    "location_precision": "city_or_area",
                },
            },
            {
                "key": "service_type",
                "value": "installation",
                "source": "validated_choice_action",
                "status": "tool_grounded",
                "safe_for_action": True,
            },
        ],
        capability_profile={
            "candidate_tools": ["find_installation_slots"],
            "exposed_tools": ["find_installation_slots"],
            "available_context_refs": {"product_presentation": ["products_1"]},
        },
    )

    assert any(
        objective.get("tool") == "find_installation_slots"
        for objective in objectives
    )


def test_multi_surface_repair_keeps_first_customer_decision_layer() -> None:
    contract = _renderer_decision_layer_repair_contract(
        [
            {
                "type": "render_surface",
                "content": {"surface_ref": "products_1"},
            },
            {
                "type": "render_surface",
                "content": {"surface_ref": "cities_1"},
            },
        ],
        {
            "available_surfaces": [
                {
                    "surface_ref": "products_1",
                    "decision_layer": "product",
                    "supporting_context": False,
                },
                {
                    "surface_ref": "cities_1",
                    "decision_layer": "city",
                    "supporting_context": False,
                },
            ]
        },
    )

    assert contract == {
        "active_decision_layer": "product",
        "deferred_decision_layers": ["city"],
        "cta_rule": "ask_only_for_the_active_decision_layer",
    }


def test_incomplete_order_summary_supports_checkout_choice_as_one_step() -> None:
    plan = _build_customer_turn_plan(
        record={
            "tool_results": [
                {
                    "name": "build_order_summary",
                    "full_result": {
                        "status": "incomplete",
                        "card_runtime_insert": True,
                        "order_summary_ref": "order_summary_1",
                        "order_summary_block": "Order Details So Far",
                        "missing_fields": [
                            "Contact number",
                            "Payment option (Pay Now or Pay Later)",
                        ],
                    },
                }
            ],
            "checkout_choice_surface": {
                "presentation_ref": "payment_options_1",
                "surface_type": "payment_option_choices",
                "choice_type": "payment_option_selection",
                "choices": [
                    {"label": "Pay Now"},
                    {"label": "Pay Later"},
                ],
            },
        },
        order_readiness={"collected": {}},
        draft_assistant_text="Review po natin, then pili ng payment option.",
        validated_choice_context={},
    )

    surfaces = {
        surface["surface_ref"]: surface
        for surface in plan["available_surfaces"]
    }
    assert surfaces["order_summary_1"]["supporting_context"] is True
    assert surfaces["payment_options_1"].get("supporting_context") is not True
    assert not any(
        violation["type"] == "multiple_customer_decision_layers"
        for violation in _final_composer_renderer_contract_violations(
            [
                {
                    "type": "render_surface",
                    "content": {"surface_ref": "order_summary_1"},
                },
                {
                    "type": "render_surface",
                    "content": {"surface_ref": "payment_options_1"},
                },
            ],
            [],
            customer_turn_plan=plan,
        )
    )


def test_ambiguous_city_tool_plan_is_rejected_before_service_execution() -> None:
    signal = {
        "key": "location",
        "value": "Taytay",
        "source": "latest_user_message",
        "resolution": {
            "status": "ambiguous_location",
            "display_label": "Taytay",
            "location_precision": "ambiguous_city",
            "clarification_options": ["Taytay, Palawan", "Taytay, Rizal"],
        },
    }

    rejection = _location_tool_plan_rejection(
        name="find_installation_slots",
        execution_args={"location": "Taytay, Palawan"},
        validated_choice_context={},
        background_signals=[signal],
    )

    assert rejection["location_precision"] == "ambiguous_city"
    assert rejection["clarification_options"] == [
        "Taytay, Palawan",
        "Taytay, Rizal",
    ]
    assert rejection["source"] == "normalized_latest_customer_location"


def test_turn_authorization_separates_known_location_from_action_authority() -> None:
    plan = _build_customer_turn_plan(
        record={"tool_results": []},
        order_readiness={"collected": {}},
        background_signals=[
            {
                "key": "location",
                "value": "Santa Rosa City, Laguna",
                "status": "recognized_context",
                "source": "service_observation_store",
                "relation": "asserted",
                "requires_validation": True,
                "safe_for_action": False,
            },
            {
                "key": "tire_size",
                "value": "225/55R18",
                "status": "confirmed_by_latest_user_message",
                "source": "latest_user_message",
                "relation": "asserted",
                "requires_validation": False,
                "safe_for_action": True,
            },
        ],
    )

    known = plan["known_customer_context"]
    assert known["location"]["value"] == "Santa Rosa City, Laguna"
    assert known["location"]["requires_validation"] is True
    assert known["location"]["safe_for_action"] is False
    assert known["tire_size"]["value"] == "225/55R18"
    assert "location" not in plan["already_satisfied_fields"]
    assert "service_availability" not in plan[
        "authorized_claim_categories"
    ]


def test_province_slot_rejection_exposes_model_led_city_recommendation_retry(
    monkeypatch,
) -> None:
    monkeypatch.setenv("RUNTIME_V7_TURN_PLAN_ENABLED", "1")
    harness = object.__new__(RuntimeV7Harness)
    harness.current_validated_choice_context = {
        "validation_status": "valid",
        "choice_type": "serviceable_province",
        "label": "Pampanga",
    }

    result, compact, _, reused = harness._execute_tool_call_with_turn_cache(
        {
            "id": "call_slots",
            "name": "find_installation_slots",
        },
        {
            "location": "Pampanga",
        },
        round_index=1,
        record={},
        tool_result_cache={},
        allowed_tool_names=["find_installation_slots"],
        current_user_message=(
            "Pampanga po pero hindi ako sure sa city."
        ),
        active_working_memory="",
        background_signals=[],
        order_readiness={},
    )

    assert reused is False
    assert result["error_type"] == "tool_plan_not_authorized"
    alternative = compact["authorized_alternative_plan"]
    assert alternative["tool_name"] == "find_installation_slots"
    assert alternative["discovery_mode"] == "recommend_serviceable_cities"
    assert "city" in alternative["result_semantics"].casefold()
    assert "does not select" in alternative["result_semantics"].casefold()


def test_city_recommendation_preview_trusts_model_plan_without_prose_regex() -> None:
    broad_schedule_request = _location_tool_plan_rejection(
        name="find_installation_slots",
        execution_args={
            "location": "Pampanga",
            "discovery_mode": "recommend_serviceable_cities",
        },
        validated_choice_context={},
        background_signals=[],
        current_user_message=(
            "May installation schedule ba sa Pampanga bukas?"
        ),
    )
    unsure_request = _location_tool_plan_rejection(
        name="find_installation_slots",
        execution_args={
            "location": "Pampanga",
            "discovery_mode": "recommend_serviceable_cities",
        },
        validated_choice_context={},
        background_signals=[],
        current_user_message=(
            "Pampanga po pero hindi ako sure sa city."
        ),
    )

    assert broad_schedule_request == {}
    assert unsure_request == {}


def test_location_change_discards_partner_and_schedule_observations() -> None:
    store = ServiceObservationStore()
    store.save_installation_slots_result(
        {
            "observation_ref": "service_slots_old",
            "presentation_ref": "slots_old",
            "service_locations": [
                {"service_location_ref": "branch_old"}
            ],
            "slot_groups": [
                {"slots": [{"slot_ref": "slot_old"}]}
            ],
            "availability": {"availability_status": "slots_found"},
        }
    )

    store.clear_location_dependent()

    assert store.latest() is None
    assert store.get_location("branch_old") == {}
    assert store.headers() == []


def test_city_change_keeps_only_compatible_new_service_evidence() -> None:
    store = ServiceObservationStore()
    for ref, location in (
        ("old_slots", "Quezon City, Metro Manila"),
        ("new_slots", "San Fernando City, Pampanga"),
    ):
        store.save_installation_slots_result(
            {
                "observation_ref": ref,
                "query_basis": {
                    "location": location,
                    "customer_location_label": location,
                },
                "slot_groups": [
                    {"slots": [{"slot_ref": ref + "_slot"}]}
                ],
                "availability": {
                    "availability_status": "slots_found"
                },
            }
        )

    store.retain_compatible_location(
        "San Fernando City, Pampanga"
    )

    assert store.get_observation("old_slots") is None
    assert store.get_observation("new_slots") is not None
    assert store.latest().observation_ref == "new_slots"


def test_unsure_city_ranking_uses_isolated_previews_without_selection(
    monkeypatch,
) -> None:
    class FakePreviewTools:
        def __init__(self, **kwargs):
            self.store = kwargs["store"]

        def find_installation_slots(self, args):
            city = str(args.get("location") or "")
            if city.startswith("Mabalacat"):
                start = "2026-07-30T08:00:00+08:00"
                time_text = "8:00 AM"
            else:
                start = "2026-07-29T09:30:00+08:00"
                time_text = "9:30 AM"
            return {
                "observation_ref": "preview_" + city.split(",")[0],
                "slot_groups": [
                    {
                        "slots": [
                            {
                                "start": start,
                                "date": start[:10],
                                "weekday": "Wednesday",
                                "time_text": time_text,
                            }
                        ]
                    }
                ],
            }

    monkeypatch.setattr(
        api_runtime,
        "RuntimeV7ServiceTools",
        FakePreviewTools,
    )
    provider = ServiceableLocationChoicesProvider(
        http_client=LocationHTTP()
    )
    original_store = ServiceObservationStore()
    harness = SimpleNamespace(
        service_tools=SimpleNamespace(
            store=original_store,
            canonical_values_provider=None,
            installation_partner_tool=object(),
            installation_slot_lookup=object(),
        )
    )
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="Hindi ako sure sa city.",
        flow_context={
            "choice_action_runtime_context": {
                "validation_status": "valid",
                "choice_type": "serviceable_province",
                "label": "Pampanga",
            }
        },
    )

    result = api_runtime._recommend_serviceable_cities(
        {
            "discovery_mode": "recommend_serviceable_cities",
            "location": "Pampanga",
        },
        request=request,
        harness=harness,
        provider=provider,
    )

    surface = result["location_choice_surface"]
    assert [choice["label"] for choice in surface["choices"]] == [
        "San Fernando City",
        "Mabalacat",
    ]
    assert surface["preview_is_selection"] is False
    assert all(
        choice.get("earliest_slot_preview")
        for choice in surface["choices"]
    )
    assert original_store.latest() is None


def test_location_change_clears_only_draft_booking_artifacts() -> None:
    harness = SimpleNamespace(
        latest_order_summary_snapshot={"summary": "old"},
        order_payload_store={"payload_old": {"status": "ready"}},
        latest_order_payload_ref="payload_old",
        payment_request_store={"payment_old": {"status": "ready"}},
        latest_payment_request_ref="payment_old",
        choice_action_history=[
            {"choice_type": "product_selection"},
            {"choice_type": "schedule_selection"},
            {"choice_type": "payment_option_selection"},
        ],
    )

    api_runtime._clear_location_dependent_order_state(harness)

    assert harness.latest_order_summary_snapshot == {}
    assert harness.order_payload_store == {}
    assert harness.latest_order_payload_ref == ""
    assert harness.payment_request_store == {}
    assert harness.latest_payment_request_ref == ""
    assert [row["choice_type"] for row in harness.choice_action_history] == [
        "product_selection",
        "payment_option_selection",
    ]


def test_payment_policy_plans_do_not_classify_raw_non_payment_request() -> None:
    plans = api_runtime._semantic_customer_payment_query_plans(
        {},
        request=RuntimeV7APIRequest(
            user_id="trial",
            user_text="Pwede makahingi ng formal quotation for our fleet?",
        ),
    )

    assert plans == []


def test_payment_policy_lookup_keeps_typed_unknown_provider_for_validation() -> None:
    plans = api_runtime._semantic_customer_payment_query_plans(
        {
            "payment_query_decision": {
                "decision": "payment_request",
                "payment_queries": [
                    {
                        "scope_kind": "named_method",
                        "requested_payment_method": "Maya Credit",
                    }
                ],
            }
        },
        request=RuntimeV7APIRequest(
            user_id="trial",
            user_text="May Maya Credit po ba kayo?",
        ),
    )

    assert plans == [
        {
            "question": "Maya Credit",
            "requested_payment_method": "Maya Credit",
        }
    ]
