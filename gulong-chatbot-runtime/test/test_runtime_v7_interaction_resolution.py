import json

import pytest

from runtime_v7.interaction_resolution import (
    compile_interaction_packet,
    default_interaction_decision,
    validate_interaction_decision,
)


def _choice(
    event_id,
    choice_ref,
    choice_type,
    occurred_at,
    **overrides,
):
    return {
        "event_id": event_id,
        "idempotency_key": f"idem-{event_id}",
        "presentation_ref": "pres-1",
        "choice_ref": choice_ref,
        "choice_type": choice_type,
        "label": overrides.pop("label", choice_ref),
        "click_timestamp": occurred_at,
        "received_at": overrides.pop("received_at", occurred_at),
        "validation_status": overrides.pop("validation_status", "valid"),
        "delivery_status": overrides.pop(
            "delivery_status",
            "superseded_before_composition",
        ),
        **overrides,
    }


def _packet(*events, current_event_id=""):
    return compile_interaction_packet(
        choice_history=list(events),
        promo_history=[],
        current_event_id=current_event_id or events[-1]["event_id"],
    )


def test_identical_event_id_is_collapsed_but_new_repeat_is_preserved():
    first = _choice(
        "evt-1",
        "price_category:premium",
        "price_category",
        "2026-07-28T10:00:00+08:00",
    )
    retry = {**first, "received_at": "2026-07-28T10:00:00.100+08:00"}
    collapsed = _packet(first, retry)
    assert collapsed["runtime_relation"] == "single_valid_event"
    assert collapsed["event_count"] == 1

    repeat = _choice(
        "evt-2",
        "price_category:premium",
        "price_category",
        "2026-07-28T10:00:00.200+08:00",
    )
    preserved = _packet(first, repeat)
    assert preserved["runtime_relation"] == "same_choice_repeat"
    assert [event["event_id"] for event in preserved["events"]] == [
        "evt-1",
        "evt-2",
    ]


@pytest.mark.parametrize(
    ("choice_type", "first_ref", "second_ref", "allowed"),
    [
        (
            "price_category",
            "price_category:premium",
            "price_category:budget",
            {"accept_latest", "compare", "clarify"},
        ),
        (
            "product_selection",
            "card-a",
            "card-b",
            {"accept_latest", "compare", "clarify"},
        ),
        (
            "schedule_selection",
            "slot-0830",
            "slot-0930",
            {"accept_latest", "clarify"},
        ),
        (
            "payment_option_selection",
            "pay-now",
            "pay-later",
            {"accept_latest", "clarify"},
        ),
    ],
)
def test_same_layer_distinct_choices_defer_state_to_model(
    choice_type,
    first_ref,
    second_ref,
    allowed,
):
    packet = _packet(
        _choice(
            "evt-1",
            first_ref,
            choice_type,
            "2026-07-28T10:00:00+08:00",
        ),
        _choice(
            "evt-2",
            second_ref,
            choice_type,
            "2026-07-28T10:00:00.200+08:00",
        ),
    )
    assert packet["runtime_relation"] == "same_layer_distinct"
    assert packet["state_commit_deferred"] is True
    assert set(packet["allowed_model_interpretations"]) == allowed


def test_province_then_child_city_is_objective_hierarchy():
    packet = _packet(
        _choice(
            "evt-province",
            "location:cavite",
            "serviceable_province",
            "2026-07-28T10:00:00+08:00",
        ),
        _choice(
            "evt-city",
            "location:dasmarinas",
            "serviceable_city",
            "2026-07-28T10:00:00.300+08:00",
            province_code="cavite",
        ),
    )
    assert packet["runtime_relation"] == "hierarchical_sequence"
    assert packet["allowed_model_interpretations"] == [
        "hierarchical_advance"
    ]


def test_competing_provinces_are_not_mistaken_for_hierarchy():
    packet = _packet(
        _choice(
            "evt-cavite",
            "location:cavite",
            "serviceable_province",
            "2026-07-28T10:00:00+08:00",
        ),
        _choice(
            "evt-laguna",
            "location:laguna",
            "serviceable_province",
            "2026-07-28T10:00:00.300+08:00",
        ),
    )
    assert packet["runtime_relation"] == "same_layer_distinct"
    assert packet["allowed_model_interpretations"] == [
        "accept_latest",
        "clarify",
    ]


def test_promo_information_actions_allow_comparison_without_selection():
    promos = [
        {
            "event_id": "evt-michelin",
            "idempotency_key": "idem-michelin",
            "catalog_version_id": "catalog-1",
            "promo_ref": "promo-michelin",
            "action": "promo_details",
            "selected_brand": "Michelin",
            "validation_status": "valid",
            "delivery_status": "superseded_before_composition",
            "click_timestamp": "2026-07-28T10:00:00+08:00",
        },
        {
            "event_id": "evt-apollo",
            "idempotency_key": "idem-apollo",
            "catalog_version_id": "catalog-1",
            "promo_ref": "promo-apollo",
            "action": "promo_details",
            "selected_brand": "Apollo",
            "validation_status": "valid",
            "delivery_status": "pending",
            "click_timestamp": "2026-07-28T10:00:00.200+08:00",
        },
    ]
    packet = compile_interaction_packet(
        choice_history=[],
        promo_history=promos,
        current_event_id="evt-apollo",
    )
    assert packet["runtime_relation"] == "same_layer_distinct"
    assert all(
        event["decision_layer"] == "promo_information"
        for event in packet["events"]
    )
    assert "compare" in packet["allowed_model_interpretations"]


def test_timestamp_order_wins_over_arrival_order_and_is_stable_on_ties():
    later_arrival_first = _choice(
        "evt-later",
        "slot-0930",
        "schedule_selection",
        "2026-07-28T10:00:01+08:00",
        received_at="2026-07-28T10:00:01.100+08:00",
    )
    earlier_arrival_second = _choice(
        "evt-earlier",
        "slot-0830",
        "schedule_selection",
        "2026-07-28T10:00:00+08:00",
        received_at="2026-07-28T10:00:01.200+08:00",
    )
    packet = _packet(later_arrival_first, earlier_arrival_second)
    assert [event["event_id"] for event in packet["events"]] == [
        "evt-earlier",
        "evt-later",
    ]

    missing = _choice(
        "evt-missing",
        "slot-0700",
        "schedule_selection",
        "",
        received_at="",
    )
    packet = _packet(later_arrival_first, missing)
    assert packet["events"][0]["event_id"] == "evt-missing"

    same_zone_later = _choice(
        "evt-local",
        "slot-1000",
        "schedule_selection",
        "2026-07-28T10:00:00+08:00",
    )
    utc_later = _choice(
        "evt-utc",
        "slot-1001",
        "schedule_selection",
        "2026-07-28T02:01:00Z",
    )
    packet = _packet(utc_later, same_zone_later)
    assert [event["event_id"] for event in packet["events"]] == [
        "evt-local",
        "evt-utc",
    ]


def test_stale_current_event_is_visible_but_only_clarification_is_legal():
    packet = _packet(
        _choice(
            "evt-stale",
            "slot-old",
            "schedule_selection",
            "2026-07-28T10:00:00+08:00",
            validation_status="stale",
            delivery_status="pending",
        ),
    )
    assert packet["runtime_relation"] == "stale_or_invalid_present"
    assert packet["allowed_model_interpretations"] == ["clarify"]


def test_decision_validation_rejects_unknown_non_latest_and_bad_flags():
    packet = _packet(
        _choice(
            "evt-1",
            "price_category:premium",
            "price_category",
            "2026-07-28T10:00:00+08:00",
        ),
        _choice(
            "evt-2",
            "price_category:budget",
            "price_category",
            "2026-07-28T10:00:00.200+08:00",
        ),
    )
    non_latest = validate_interaction_decision(
        packet,
        {
            "interpretation": "accept_latest",
            "effective_event_ids": ["evt-1"],
            "needs_clarification": False,
        },
    )
    assert non_latest["status"] == "invalid"
    assert "effective_event_must_be_latest" in non_latest[
        "validation_reasons"
    ]

    unknown = validate_interaction_decision(
        packet,
        {
            "interpretation": "accept_latest",
            "effective_event_ids": ["evt-unknown"],
            "needs_clarification": False,
        },
    )
    assert unknown["status"] == "invalid"
    assert "unknown_effective_event_id" in unknown["validation_reasons"]

    bad_clarify = validate_interaction_decision(
        packet,
        {
            "interpretation": "clarify",
            "effective_event_ids": [],
            "needs_clarification": False,
        },
    )
    assert bad_clarify["status"] == "invalid"
    assert "clarification_flag_required" in bad_clarify[
        "validation_reasons"
    ]


def test_safe_default_accepts_single_and_latest_ordered_same_layer_choice():
    single = _packet(
        _choice(
            "evt-1",
            "pay-now",
            "payment_option_selection",
            "2026-07-28T10:00:00+08:00",
        )
    )
    accepted = default_interaction_decision(single)
    assert validate_interaction_decision(single, accepted)["status"] == "valid"
    assert accepted["effective_event_ids"] == ["evt-1"]

    ambiguous = _packet(
        _choice(
            "evt-1",
            "pay-now",
            "payment_option_selection",
            "2026-07-28T10:00:00+08:00",
        ),
        _choice(
            "evt-2",
            "pay-later",
            "payment_option_selection",
            "2026-07-28T10:00:00.100+08:00",
        ),
    )
    clarified = default_interaction_decision(ambiguous)
    assert clarified["interpretation"] == "accept_latest"
    assert clarified["effective_event_ids"] == ["evt-2"]
    assert validate_interaction_decision(
        ambiguous,
        clarified,
    )["status"] == "valid"


def test_packet_is_bounded_to_five_events_and_2500_characters():
    events = [
        _choice(
            f"evt-{index}",
            f"card-{index}",
            "product_selection",
            f"2026-07-28T10:00:0{index}+08:00",
            label="X" * 900,
        )
        for index in range(8)
    ]
    packet = _packet(*events)
    assert packet["event_count"] <= 5
    assert len(json.dumps(packet, ensure_ascii=False)) <= 2500
