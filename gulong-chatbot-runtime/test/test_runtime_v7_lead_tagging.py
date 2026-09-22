import json

import pytest

from runtime_v7.lead_qualification import (
    INTENT_RULE_VERSION,
    build_lead_qualification_snapshot,
)
from runtime_v7.model_contract import PRODUCT_POLICY_PROMPT
from runtime_v7.product_observations import ProductToolHarness
from runtime_v7.runtime_harness import (
    FIRST_TURN_INTRO_MODE_WELCOME_ONLY,
    FINAL_COMPOSER_SYSTEM_PROMPT,
    WELCOME_SPIEL_GUARD_EVENT_TYPE,
    RuntimeV7Harness,
)
from runtime_v7.tagging import (
    enrich_runtime_v7_analytical_qualifications,
    evaluate_runtime_v7_tagging,
    mark_runtime_v7_tags_applied,
)


class FakeBackgroundSignalModelClient:
    def __init__(self, candidates):
        self.candidates = list(candidates)
        self.calls = []

    def extract_background_signals(self, *, system_prompt, user_prompt, metadata=None):
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt, "metadata": dict(metadata or {})})
        return {
            "content": json.dumps({"candidates": self.candidates}),
            "tool_calls": [],
            "usage": {},
            "cache_usage": {},
            "latency_ms": 1,
            "finish_reason": "stop",
        }






class HumanHandoffToolModel:
    def __init__(self):
        self.calls = []

    def complete(self, *, messages, tools, tool_choice="auto", response_format=None):
        self.calls.append(
            {
                "messages": list(messages),
                "tools": list(tools),
                "response_format": response_format,
            }
        )
        if (
            getattr(response_format, "__name__", "")
            == "RuntimeV7HumanHandoffDecisionModel"
        ):
            return {
                "content": json.dumps(
                    {
                        "decision": "request_now",
                        "explicit_human_takeover": True,
                        "explicit_stop_automation": True,
                        "reason": "Customer explicitly requested takeover.",
                    }
                ),
                "tool_calls": [],
                "usage": {},
                "cache_usage": {},
                "latency_ms": 1,
                "finish_reason": "stop",
            }
        if response_format is not None:
            return {
                "content": json.dumps(
                    {
                        "response_units": [
                            {
                                "type": "text",
                                "content": {
                                    "text": (
                                        "Noted po. Hihinto na muna ang automated sales replies after this message. "
                                        "A human teammate still needs to pick up the chat."
                                    )
                                },
                            }
                        ]
                    }
                ),
                "tool_calls": [],
                "usage": {},
                "cache_usage": {},
                "latency_ms": 1,
                "finish_reason": "stop",
            }
        if any(message.get("role") == "tool" for message in messages):
            return {
                "content": "Noted po. Hihinto na muna ang automated sales replies after this message.",
                "tool_calls": [],
                "usage": {},
                "cache_usage": {},
                "latency_ms": 1,
                "finish_reason": "stop",
            }
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_handoff",
                    "name": "request_human_handoff",
                    "args": {
                        "reason_category": "customer_request",
                        "summary": "Customer explicitly asked for a human agent.",
                    },
                }
            ],
            "usage": {},
            "cache_usage": {},
            "latency_ms": 1,
            "finish_reason": "tool_calls",
        }


class HumanAvailabilityMisfireModel(HumanHandoffToolModel):
    def complete(self, *, messages, tools, tool_choice="auto", response_format=None):
        if (
            getattr(response_format, "__name__", "")
            == "RuntimeV7HumanHandoffDecisionModel"
        ):
            return {
                "content": json.dumps(
                    {
                        "decision": "availability_question",
                        "explicit_human_takeover": False,
                        "explicit_stop_automation": False,
                        "reason": "Customer asked only whether human support exists.",
                    }
                ),
                "tool_calls": [],
                "usage": {},
                "cache_usage": {},
                "latency_ms": 1,
                "finish_reason": "stop",
            }
        if response_format is not None:
            return {
                "content": json.dumps(
                    {
                        "response_units": [
                            {
                                "type": "text",
                                "content": {
                                    "text": "Yes po, may human customer service team tayo."
                                },
                            }
                        ]
                    }
                ),
                "tool_calls": [],
                "usage": {},
                "cache_usage": {},
                "latency_ms": 1,
                "finish_reason": "stop",
            }
        return super().complete(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
        )


class BadGenericComposerModel:
    def __init__(self):
        self.calls = []

    def complete(self, *, messages, tools, tool_choice="auto", response_format=None):
        self.calls.append({"messages": list(messages), "tools": list(tools), "tool_choice": tool_choice, "response_format": response_format})
        return {
            "content": json.dumps(
                {
                    "action": "ask_missing_lead_info",
                    "reason": "bad generic wording",
                    "response_units": [
                        {
                            "type": "text",
                            "content": {
                                "text": "Hello! Para saan po 'yan? Pwede ko po kayong tulungan mag-check ng presyo ng gulong."
                            },
                        }
                    ],
                }
            ),
            "tool_calls": [],
            "usage": {},
            "cache_usage": {},
            "latency_ms": 1,
            "finish_reason": "stop",
        }


class BadLocationComposerModel:
    def __init__(self):
        self.calls = []

    def complete(self, *, messages, tools, tool_choice="auto", response_format=None):
        self.calls.append({"messages": list(messages), "tools": list(tools), "tool_choice": tool_choice, "response_format": response_format})
        return {
            "content": json.dumps(
                {
                    "action": "ask_missing_lead_info",
                    "reason": "bad generic location wording",
                    "response_units": [
                        {
                            "type": "text",
                            "content": {
                                "text": "Para saan po ang location? May installation partners po kami across Metro Manila and nearby provinces."
                            },
                        }
                    ],
                }
            ),
            "tool_calls": [],
            "usage": {},
            "cache_usage": {},
            "latency_ms": 1,
            "finish_reason": "stop",
        }


class BadPalaComposerModel:
    def __init__(self):
        self.calls = []

    def complete(self, *, messages, tools, tool_choice="auto", response_format=None):
        self.calls.append({"messages": list(messages), "tools": list(tools), "tool_choice": tool_choice, "response_format": response_format})
        return {
            "content": json.dumps(
                {
                    "action": "ask_missing_lead_info",
                    "reason": "bad generic pala wording",
                    "response_units": [
                        {
                            "type": "text",
                            "content": {
                                "text": "Para saan po pala, anong tire size hinahanap niyo? Pwede rin pong car model or photo ng gulong."
                            },
                        }
                    ],
                }
            ),
            "tool_calls": [],
            "usage": {},
            "cache_usage": {},
            "latency_ms": 1,
            "finish_reason": "stop",
        }


class BadParaSaComposerModel:
    def __init__(self):
        self.calls = []

    def complete(self, *, messages, tools, tool_choice="auto", response_format=None):
        self.calls.append({"messages": list(messages), "tools": list(tools), "tool_choice": tool_choice, "response_format": response_format})
        return {
            "content": json.dumps(
                {
                    "action": "ask_missing_lead_info",
                    "reason": "bad para sa wording",
                    "response_units": [
                        {
                            "type": "text",
                            "content": {
                                "text": "Para sa anong tire size po?"
                            },
                        }
                    ],
                }
            ),
            "tool_calls": [],
            "usage": {},
            "cache_usage": {},
            "latency_ms": 1,
            "finish_reason": "stop",
        }




class MainNoToolModel:
    def __init__(self):
        self.calls = 0

    def complete(self, *, messages, tools, tool_choice="auto"):
        self.calls += 1
        return {
            "content": "Sige po, i-check natin sa main flow.",
            "tool_calls": [],
            "usage": {},
            "cache_usage": {},
            "latency_ms": 1,
            "finish_reason": "stop",
        }


class SemanticLocationToolModel:
    """Exercise the model-owned location-choice capability in the main loop."""

    def __init__(self):
        self.calls = []

    def complete(
        self,
        *,
        messages,
        tools,
        tool_choice="auto",
        response_format=None,
        max_tokens=None,
    ):
        self.calls.append(
            {
                "messages": list(messages),
                "tools": list(tools),
                "tool_choice": tool_choice,
            }
        )
        response_name = getattr(response_format, "__name__", "")
        if response_name == "RuntimeV7FinalResponseModel":
            return {
                "content": json.dumps(
                    {
                        "response_units": [
                            {
                                "type": "text",
                                "content": {
                                    "text": (
                                        "Online store po ang Gulong.PH, with "
                                        "reservation-based installation partners."
                                    )
                                },
                            },
                            {
                                "type": "render_surface",
                                "content": {
                                    "surface_ref": "loc_semantic_test"
                                },
                            },
                            {
                                "type": "text",
                                "content": {
                                    "text": "Pili po kayo ng province below."
                                },
                            },
                        ]
                    }
                ),
                "tool_calls": [],
                "usage": {},
                "cache_usage": {},
                "latency_ms": 1,
                "finish_reason": "stop",
            }
        if messages[-1].get("role") == "tool":
            return {
                "content": (
                    "Online store po ang Gulong.PH, with reservation-based "
                    "installation partners. Pili po kayo ng province below."
                ),
                "tool_calls": [],
                "usage": {},
                "cache_usage": {},
                "latency_ms": 1,
                "finish_reason": "stop",
            }
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_location_choices",
                    "name": "present_serviceable_location_choices",
                    "args": {},
                }
            ],
            "usage": {},
            "cache_usage": {},
            "latency_ms": 1,
            "finish_reason": "tool_calls",
        }










def _serviceable_province_result(_args):
    """Return a minimal provider-backed surface for harness contract tests."""

    return {
        "status": "ok",
        "location_choice_surface": {
            "presentation_ref": "loc_semantic_test",
            "surface_type": "serviceable_province_choices",
            "choice_type": "serviceable_province",
            "level": "province",
            "parent_code": "PH",
            "choices": [
                {
                    "choice_ref": "location:province:PH-40",
                    "code": "PH-40",
                    "label": "Cavite",
                    "partner_count": 1,
                }
            ],
            "source": "branch_api",
        },
        "routing_only": True,
        "read_only": True,
        "can_confirm_serviceability": False,
    }


def _attach_semantic_location_surface(partial_turn):
    """Mirror the API planner for the focused harness-level intro contract."""

    surface = partial_turn["tool_results"][0]["full_result"][
        "location_choice_surface"
    ]
    return {
        "location_choice_surface": surface,
        "location_choice_surface_status": {
            "status": "attached",
            "reason": "model_requested_serviceable_location_choices",
            "routing_only": True,
            "slots_authorized": False,
        },
    }


class MainFitmentModel:
    def __init__(self):
        self.calls = 0

    def complete(self, *, messages, tools, tool_choice="auto"):
        self.calls += 1
        if messages[-1].get("role") == "tool":
            return {
                "content": "May possible tire sizes po for Toyota Wigo. Pa-confirm po yung tire size sa sidewall bago tayo mag-show ng exact options.",
                "tool_calls": [],
                "usage": {},
                "cache_usage": {},
                "latency_ms": 1,
                "finish_reason": "stop",
            }
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_fitment_1",
                    "name": "extract_compatible_fitment",
                    "args": {"vehicle_query": "Toyota Wigo", "top_k": 3},
                }
            ],
            "usage": {},
            "cache_usage": {},
            "latency_ms": 1,
            "finish_reason": "tool_calls",
        }


class MainFitmentComposerModel:
    def __init__(self):
        self.calls = []

    def complete(self, *, messages, tools, tool_choice="auto", response_format=None):
        self.calls.append(
            {
                "messages": list(messages),
                "tools": list(tools),
                "tool_choice": tool_choice,
                "response_format": response_format,
            }
        )
        if response_format is not None:
            return {
                "content": json.dumps(
                    {
                        "response_units": [
                            {
                                "type": "text",
                                "content": {
                                    "text": (
                                        "Possible sizes po for Toyota Wigo include 175/65R14 and 165/65R14. "
                                        "Pa-confirm po yung exact tire size sa sidewall; send niyo na rin preferred brand "
                                        "or location if meron para ma-narrow natin."
                                    )
                                },
                            }
                        ]
                    }
                ),
                "tool_calls": [],
                "usage": {},
                "cache_usage": {},
                "latency_ms": 1,
                "finish_reason": "stop",
            }
        if messages[-1].get("role") == "tool":
            return {
                "content": "May possible tire sizes po for Toyota Wigo. Pa-confirm po yung tire size sa sidewall.",
                "tool_calls": [],
                "usage": {},
                "cache_usage": {},
                "latency_ms": 1,
                "finish_reason": "stop",
            }
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_fitment_1",
                    "name": "extract_compatible_fitment",
                    "args": {"vehicle_query": "Toyota Wigo", "top_k": 3},
                }
            ],
            "usage": {},
            "cache_usage": {},
            "latency_ms": 1,
            "finish_reason": "tool_calls",
        }


class FakeFitmentTools(ProductToolHarness):
    def __init__(self):
        super().__init__()
        self.fitment_calls = []

    def extract_compatible_fitment(self, payload):
        self.fitment_calls.append(dict(payload or {}))
        return {
            "status": "ok",
            "vehicle_query": payload.get("vehicle_query"),
            "candidate_sizes": [
                {"size": "175/65R14", "confidence": "medium"},
                {"size": "165/65R14", "confidence": "medium"},
            ],
            "requires_customer_confirmation": True,
        }


def _candidate(key, value, *, source="latest_user_message", confidence="high", status_hint="mentioned"):
    return {
        "key": key,
        "value": value,
        "source": source,
        "confidence": confidence,
        "status_hint": status_hint,
        "evidence": str(value),
    }


def test_lead_qualification_complete_means_moderate_intent():
    snapshot = build_lead_qualification_snapshot(
        [
            {"key": "tire_size", "value": "175/65R14"},
            {"key": "preferred_brands", "value": "YOKOHAMA"},
            {"key": "location", "value": "Taguig"},
        ]
    )

    assert snapshot.lead_stage == "complete"
    assert snapshot.moderate_intent is True
    assert snapshot.present["tire_brand"] == "YOKOHAMA"
    assert snapshot.missing == []
    assert snapshot.optional_missing == ["contact_number"]
    payload = snapshot.to_dict()
    assert payload["decision_mode"] == "deterministic"
    assert payload["rule_version"] == INTENT_RULE_VERSION
    assert INTENT_RULE_VERSION == "gulong_intent_v2_20260811"


def test_lead_qualification_incomplete_asks_only_needed_fields():
    snapshot = build_lead_qualification_snapshot(
        [
            {"key": "tire_size", "value": "175/65R14"},
            {"key": "preferred_brands", "value": "YOKOHAMA"},
        ]
    )

    assert snapshot.lead_stage == "incomplete"
    assert snapshot.moderate_intent is False
    assert snapshot.missing == ["location"]


@pytest.mark.parametrize(
    ("signals", "expected_moderate"),
    [
        (
            [
                {"key": "tire_size", "value": "175/65R14"},
                {"key": "preferred_brands", "value": "YOKOHAMA"},
            ],
            False,
        ),
        (
            [
                {"key": "tire_size", "value": "175/65R14"},
                {"key": "product", "value": "YOKOHAMA A-Drive"},
            ],
            False,
        ),
        (
            [
                {"key": "tire_size", "value": "175/65R14"},
                {"key": "preferred_brands", "value": "YOKOHAMA"},
                {"key": "product", "value": "YOKOHAMA A-Drive"},
            ],
            False,
        ),
        (
            [
                {"key": "tire_size", "value": "175/65R14"},
                {"key": "preferred_brands", "value": "YOKOHAMA"},
                {"key": "location", "value": "Taguig"},
            ],
            True,
        ),
        (
            [
                {"key": "tire_size", "value": "175/65R14"},
                {"key": "preferred_brands", "value": "YOKOHAMA"},
                {"key": "contact_number", "value": "09171234567"},
            ],
            True,
        ),
    ],
)
def test_lead_qualification_keeps_product_out_of_moderate_support_rule(
    signals, expected_moderate
):
    snapshot = build_lead_qualification_snapshot(signals)

    assert snapshot.moderate_intent is expected_moderate


def test_lead_qualification_rejects_malformed_contact_support():
    snapshot = build_lead_qualification_snapshot(
        [
            {"key": "tire_size", "value": "175/65R14"},
            {"key": "preferred_brands", "value": "YOKOHAMA"},
            {"key": "contact_number", "value": "not-provided"},
        ]
    )

    assert snapshot.moderate_intent is False
    assert "contact_number" not in snapshot.present


def test_lead_qualification_does_not_count_service_phrase_as_location():
    snapshot = build_lead_qualification_snapshot(
        [
            {"key": "tire_size", "value": "225/55R19"},
            {"key": "preferred_brands", "value": "MICHELIN"},
            {"key": "location", "value": "Free Installation", "source": "service_observation_store"},
        ]
    )

    assert snapshot.lead_stage == "incomplete"
    assert snapshot.moderate_intent is False
    assert "location" not in snapshot.present
    assert snapshot.missing == ["location"]


def test_lead_qualification_does_not_count_question_as_customer_location():
    snapshot = build_lead_qualification_snapshot(
        [
            {"key": "tire_size", "value": "205/55R16"},
            {"key": "preferred_brands", "value": "YOKOHAMA"},
            {
                "key": "location",
                "value": "Saan Kayo Located",
                "relation": "question_only",
                "source": "latest_user_message",
            },
        ]
    )

    assert snapshot.lead_stage == "incomplete"
    assert snapshot.moderate_intent is False
    assert "location" not in snapshot.present
    assert snapshot.missing == ["location"]




def test_runtime_routes_location_button_text_through_semantic_tool_loop(
    monkeypatch,
):
    monkeypatch.setenv("RUNTIME_V7_TURN_PLAN_ENABLED", "1")
    model = SemanticLocationToolModel()
    harness = RuntimeV7Harness(
        model_client=model,
        tools=ProductToolHarness(),
        background_signal_model_client=FakeBackgroundSignalModelClient([]),
    )
    harness.location_plan_executor = _serviceable_province_result
    harness.turn_surface_planner = _attach_semantic_location_surface

    record = harness.run_turn("Where are you located?")

    assert record["llm_calls"][0]["tool_calls"][0]["name"] == (
        "present_serviceable_location_choices"
    )
    assert record["tool_results"][0]["full_result"]["routing_only"] is True
    assert any(
        tool["function"]["name"] == "present_serviceable_location_choices"
        for tool in model.calls[0]["tools"]
    )
    assert record["welcome_spiel_inserted"] is False
    assert record["first_turn_opening_model_composed"] is True
    assert record["first_turn_intro_mode"] == (
        FIRST_TURN_INTRO_MODE_WELCOME_ONLY
    )
    assert record["runtime_final_response"].startswith("Online store po ang Gulong.PH")
    assert "Para ma-check namin yung best tires" not in record[
        "runtime_final_response"
    ]
    assert "Pili po kayo ng province below" in record["runtime_final_response"]
    assert not any(event.get("type") == WELCOME_SPIEL_GUARD_EVENT_TYPE for event in record["response_guard_events"])


def test_runtime_routes_exact_tire_help_starter_to_model_owned_composition():
    model = MainNoToolModel()
    harness = RuntimeV7Harness(
        model_client=model,
        tools=ProductToolHarness(),
        background_signal_model_client=FakeBackgroundSignalModelClient([]),
    )

    record = harness.run_turn("Can you help me find the right tire for my car?")

    assert model.calls == 1
    assert len(record["llm_calls"]) == 1
    assert record["tool_results"] == []
    assert record["welcome_spiel_inserted"] is False
    assert record["first_turn_opening_model_composed"] is True
    assert record["first_turn_intro_mode"] == FIRST_TURN_INTRO_MODE_WELCOME_ONLY
    assert record["runtime_final_response"] == "Sige po, i-check natin sa main flow."


def test_bare_greeting_seed_asks_one_open_question_without_full_intake():
    harness = RuntimeV7Harness(
        model_client=MainNoToolModel(),
        tools=ProductToolHarness(),
        background_signal_model_client=FakeBackgroundSignalModelClient([]),
    )

    record = harness.run_turn("Good morning po!")

    assert record["response_seeds"] == []
    assert "Good morning po!" in record["context_input"]


def test_human_availability_seed_does_not_dump_lead_intake_or_claim_handoff():
    harness = RuntimeV7Harness(
        model_client=MainNoToolModel(),
        tools=ProductToolHarness(),
        background_signal_model_client=FakeBackgroundSignalModelClient([]),
    )

    record = harness.run_turn("Hi, is there anyone available to assist?")

    assert record["response_seeds"] == []
    assert "is there anyone available to assist" in record["context_input"]


def test_runtime_routes_location_alias_without_question_mark_through_model(
    monkeypatch,
):
    monkeypatch.setenv("RUNTIME_V7_TURN_PLAN_ENABLED", "1")
    model = SemanticLocationToolModel()
    harness = RuntimeV7Harness(
        model_client=model,
        tools=ProductToolHarness(),
        background_signal_model_client=FakeBackgroundSignalModelClient([]),
    )
    harness.location_plan_executor = _serviceable_province_result
    harness.turn_surface_planner = _attach_semantic_location_surface

    record = harness.run_turn("Where are you located")

    assert record["llm_calls"][0]["tool_calls"][0]["name"] == (
        "present_serviceable_location_choices"
    )
    assert record["welcome_spiel_inserted"] is False
    assert record["first_turn_opening_model_composed"] is True
    assert record["first_turn_intro_mode"] == (
        FIRST_TURN_INTRO_MODE_WELCOME_ONLY
    )
    assert record["runtime_final_response"].startswith("Online store po ang Gulong.PH")












def test_runtime_does_not_phrase_rewrite_model_price_clarification():
    bad_model = BadGenericComposerModel()
    harness = RuntimeV7Harness(
        model_client=bad_model,
        tools=ProductToolHarness(),
        background_signal_model_client=FakeBackgroundSignalModelClient([]),
    )

    record = harness.run_turn("how much")

    assert bad_model.calls
    assert "mag-check ng presyo" in record["runtime_final_response"]
    assert "Para saan" in record["runtime_final_response"]
    assert not any(event["type"] == "generic_clarification_phrase_removed" for event in record["response_guard_events"])


def test_runtime_does_not_phrase_rewrite_model_pala_prefix():
    bad_model = BadPalaComposerModel()
    harness = RuntimeV7Harness(
        model_client=bad_model,
        tools=ProductToolHarness(),
        background_signal_model_client=FakeBackgroundSignalModelClient([]),
        recent_turns=[
            {"role": "user", "content": "For sedan"},
            {"role": "assistant", "content": "What's your complete tire size po?"},
        ],
    )

    record = harness.run_turn("how much")

    assert bad_model.calls
    assert "anong tire size" in record["runtime_final_response"]
    assert "Para saan" in record["runtime_final_response"]
    assert not any(event["type"] == "generic_clarification_phrase_removed" for event in record["response_guard_events"])


def test_runtime_does_not_phrase_rewrite_model_tire_size_prefix():
    bad_model = BadParaSaComposerModel()
    harness = RuntimeV7Harness(
        model_client=bad_model,
        tools=ProductToolHarness(),
        background_signal_model_client=FakeBackgroundSignalModelClient([]),
        recent_turns=[
            {"role": "user", "content": "For sedan"},
            {"role": "assistant", "content": "What's your complete tire size po?"},
        ],
    )

    record = harness.run_turn("how much")

    assert bad_model.calls
    assert record["runtime_final_response"] == "Para sa anong tire size po?"
    assert not any(event["type"] == "generic_clarification_phrase_removed" for event in record["response_guard_events"])


def test_runtime_does_not_phrase_rewrite_model_location_clarification():
    bad_model = BadLocationComposerModel()
    harness = RuntimeV7Harness(
        model_client=bad_model,
        tools=ProductToolHarness(),
        background_signal_model_client=FakeBackgroundSignalModelClient([]),
    )

    record = harness.run_turn("location po?")

    assert bad_model.calls
    assert "installation partners" in record["runtime_final_response"]
    assert "Para saan" in record["runtime_final_response"]
    assert not any(event["type"] == "generic_clarification_phrase_removed" for event in record["response_guard_events"])


def test_vehicle_model_in_incomplete_lead_reaches_fitment_tool_loop():
    main_model = MainFitmentModel()
    tools = FakeFitmentTools()
    harness = RuntimeV7Harness(
        model_client=main_model,
        tools=tools,
        background_signal_model_client=FakeBackgroundSignalModelClient(
            [_candidate("car_make_model", "Toyota Wigo", status_hint="mentioned")]
        ),
    )

    record = harness.run_turn("can you help me find the right tire for my car? Toyota wigo")

    assert record["response_seeds"] == []
    assert record["llm_calls"][0]["round"] == 1
    assert record["tool_results"][0]["name"] == "extract_compatible_fitment"
    assert tools.fitment_calls[0]["vehicle_query"] == "Toyota Wigo"
    assert "Pa-confirm" in record["runtime_final_response"]
    assert "year" not in record["runtime_final_response"].lower()


def test_vehicle_model_with_full_tire_size_uses_main_composer_without_fitment_first():
    main_model = MainNoToolModel()
    harness = RuntimeV7Harness(
        model_client=main_model,
        tools=ProductToolHarness(),
        background_signal_model_client=FakeBackgroundSignalModelClient(
            [
                _candidate("tire_size", "215/50R18"),
                _candidate("car_make_model", "Mazda CX3"),
                _candidate("quantity", "4"),
            ]
        ),
    )

    record = harness.run_turn("Boss magkano para sa Mazda CX3 215 50 18 isang set na 3 plus 1")

    assert record["response_seeds"] == []
    assert main_model.calls >= 1


def test_actionable_bse_signals_reach_main_composer():
    main_model = MainNoToolModel()
    harness = RuntimeV7Harness(
        model_client=main_model,
        tools=ProductToolHarness(),
        background_signal_model_client=FakeBackgroundSignalModelClient(
            [
                _candidate("rim_size", "R15"),
                _candidate("preferred_brands", "MICHELIN"),
                _candidate("budget", "PHP 20,000 total"),
            ]
        ),
    )

    harness.run_turn("hi magkano rim 15 michelin below 20k")

    assert main_model.calls >= 1


def test_fitment_prompts_avoid_year_and_perfect_fit_claims():
    composer_prompt = " ".join(FINAL_COMPOSER_SYSTEM_PROMPT.split())
    assert "do not ask for\n  vehicle year/model year" in PRODUCT_POLICY_PROMPT
    assert "Avoid wording like \"perfect fit\"" in PRODUCT_POLICY_PROMPT
    assert "never ask for vehicle year/model year" in composer_prompt
    assert "Rewrite draft wording such as \"perfect fit\"" in composer_prompt
    assert "Keep coherent lead-in sentences together before the render_surface" in composer_prompt
    assert "Avoid stiff wording like \"prioritize\"" in composer_prompt
    assert "cheapest/value, promo, category, or brand" in composer_prompt
    assert "rewrite the lead-in and CTA into natural Gulong Taglish" in composer_prompt
    assert "Here are some options" in composer_prompt
    assert "discard draft greetings instead of preserving them" in composer_prompt
    assert "Use first_turn_intro_context when present" in FINAL_COMPOSER_SYSTEM_PROMPT
    assert "you own the complete first customer-facing text" in FINAL_COMPOSER_SYSTEM_PROMPT
    assert "Runtime uses fixed welcome copy only" in FINAL_COMPOSER_SYSTEM_PROMPT
    assert "Do not ask the customer to choose by \"card number\"" in FINAL_COMPOSER_SYSTEM_PROMPT
    assert "Never ask the customer to reply with a card number" in PRODUCT_POLICY_PROMPT
    assert "Buy 3 Get 1 FREE is a four-tire path" in PRODUCT_POLICY_PROMPT
    assert "answer from the latest fitment candidates" in PRODUCT_POLICY_PROMPT
    assert "may nakita po ako/kami/tayo" in composer_prompt
    assert 'use "pcs" or "tires"' in composer_prompt
    assert 'do not translate it to "piraso"' in composer_prompt


def test_final_composer_gets_lead_qualification_after_fitment_tool():
    main_model = MainFitmentComposerModel()
    tools = FakeFitmentTools()
    harness = RuntimeV7Harness(
        model_client=main_model,
        tools=tools,
        background_signal_model_client=FakeBackgroundSignalModelClient(
            [_candidate("car_make_model", "Toyota Wigo", status_hint="mentioned")]
        ),
    )

    record = harness.run_turn("can you help me find the right tire for my car? Toyota wigo")

    final_call = next(call for call in main_model.calls if call["response_format"] is not None)
    final_payload = json.loads(final_call["messages"][-1]["content"])
    assert final_payload["lead_qualification"]["lead_stage"] == "incomplete"
    assert final_payload["lead_qualification"]["missing"] == ["tire_size", "tire_brand", "location"]
    assert "Pa-confirm" in record["runtime_final_response"]
    assert "preferred brand" in record["runtime_final_response"]
    assert "location" in record["runtime_final_response"]
    assert "year" not in record["runtime_final_response"].lower()


def test_budget_signal_reaches_main_composer():
    main_model = MainNoToolModel()
    harness = RuntimeV7Harness(
        model_client=main_model,
        tools=ProductToolHarness(),
        background_signal_model_client=FakeBackgroundSignalModelClient(
            [
                _candidate("tire_size", "175/65R14"),
                _candidate("budget", "PHP 15,000 total"),
            ]
        ),
    )

    record = harness.run_turn("hm 175 65 14 budget 15k")

    assert main_model.calls >= 1
    assert record["llm_calls"][0]["round"] == 1


def test_runtime_v7_tagging_emits_moderate_and_high_intent_from_grounded_gates():
    result = evaluate_runtime_v7_tagging(
        current_user_message="sige bukas na lang sa Taguig",
        assistant_response="May quoted options na po.",
        background_signals=[
            {"key": "tire_size", "value": "175/65R14"},
            {"key": "preferred_brands", "value": "YOKOHAMA"},
            {"key": "location", "value": "Taguig"},
            {"key": "chosen_schedule_slot", "value": "tomorrow"},
        ],
        lead_qualification={
            "lead_stage": "complete",
            "moderate_intent": True,
            "present": {"tire_size": "175/65R14", "tire_brand": "YOKOHAMA", "location": "Taguig"},
        },
        tool_results=[
            {
                "name": "product_search",
                "result": {"product_card_headers": [{"brand": "YOKOHAMA", "sku_model": "YOKOHAMA 175/65R14"}]},
                "full_result": {"product_cards": [{"brand": "YOKOHAMA", "sku_model": "YOKOHAMA 175/65R14"}]},
            }
        ],
        turn_count=3,
    )

    tags = {action["tag"] for action in result["tags_to_add"]}
    assert "Moderate Intent" in tags
    assert "High Intent" in tags


def test_analytical_qualification_copies_lineage_from_lead_snapshot():
    snapshot = build_lead_qualification_snapshot(
        [
            {"key": "tire_size", "value": "225/55R18"},
            {"key": "tire_brand", "value": "Hankook"},
            {"key": "location", "value": "Makati"},
        ]
    )
    result = evaluate_runtime_v7_tagging(
        current_user_message="225/55R18 Hankook, Makati po.",
        lead_qualification=snapshot.to_dict(),
        tool_results=[],
    )

    qualification = result["analytical_qualifications"][0]
    assert qualification["decision_mode"] == snapshot.to_dict()["decision_mode"]
    assert qualification["rule_version"] == snapshot.to_dict()["rule_version"]


def test_moderate_qualification_is_countable_with_trace_identity_and_applied_tag():
    result = evaluate_runtime_v7_tagging(
        current_user_message="225/55R18 Hankook, Makati po.",
        assistant_response="Noted po.",
        background_signals=[
            {
                "key": "tire_size",
                "value": "225/55R18",
                "source": "latest_user_message",
                "metadata": {"evidence_ref": "msg:size"},
            },
            {"key": "tire_brand", "value": "Hankook", "source": "latest_user_message"},
            {"key": "location", "value": "Makati", "source": "validated_choice_action"},
        ],
        lead_qualification={
            "lead_stage": "complete",
            "moderate_intent": True,
            "present": {
                "tire_size": "225/55R18",
                "tire_brand": "Hankook",
                "location": "Makati",
            },
        },
        tool_results=[],
        interaction_context={
            "presentation_ref": "pres_products_1",
            "card_ref": "card_hankook_1",
            "surface_type": "product_choices",
            "choice_type": "product_selection",
            "choice_ref": "card_hankook_1",
        },
    )
    marked = mark_runtime_v7_tags_applied(
        result,
        applied_tags=["Moderate Intent"],
        apply_status="success",
    )
    enriched = enrich_runtime_v7_analytical_qualifications(
        marked,
        event_id="evt-qualification-1",
        channel_event_id="evt-qualification-1",
        message_id="msg-qualification-1",
        idempotency_key="idem-qualification-1",
        request_id="req-qualification-1",
        user_id="user-qualification-1",
        channel_user_id="channel-user-qualification-1",
        session_id="session-qualification-1",
        trace_id="trace-qualification-1",
        turn_id="turn-qualification-1",
        channel="manychat",
        occurred_at="2026-08-11T10:00:00+08:00",
        service_environment="staging",
        runtime_host="runtime-staging",
        release_version="test-release",
        git_sha="abc123",
    )

    qualification = enriched["analytical_qualifications"][0]
    assert qualification["countable"] is True
    assert qualification["qualification_level"] == "moderate"
    assert qualification["decision_mode"] == "deterministic"
    assert qualification["rule_version"] == INTENT_RULE_VERSION
    assert qualification["qualification_event_id"].startswith("aq_v1_")
    assert qualification["event_identity"] == {
        "event_id": "evt-qualification-1",
        "channel_event_id": "evt-qualification-1",
        "message_id": "msg-qualification-1",
        "idempotency_key": "idem-qualification-1",
        "request_id": "req-qualification-1",
    }
    assert qualification["environment"]["service_environment"] == "staging"
    assert qualification["context"]["session_id"] == "session-qualification-1"
    assert qualification["occurred_at"] == "2026-08-11T10:00:00+08:00"
    assert {signal["key"] for signal in qualification["source_signals"]} >= {
        "moderate_intent",
        "tire_size",
        "tire_brand",
        "location",
    }
    assert qualification["evidence_refs"] == ["msg:size", "pres_products_1", "card_hankook_1", "card_hankook_1"][:3]
    assert qualification["interaction_context"] == {
        "surface_type": "product_choices",
        "presentation_ref": "pres_products_1",
        "card_ref": "card_hankook_1",
        "choice_type": "product_selection",
        "choice_ref": "card_hankook_1",
    }
    assert qualification["tag_application_outcome"]["moderate_tag_outcome"] == "applied"


def test_moderate_qualification_keeps_stable_identity_across_retry():
    result = evaluate_runtime_v7_tagging(
        current_user_message="205/55R16 Michelin sa Quezon City",
        background_signals=[],
        lead_qualification={"moderate_intent": True, "lead_stage": "complete"},
        tool_results=[],
    )
    first = enrich_runtime_v7_analytical_qualifications(
        result,
        event_id="evt-retry-1",
        idempotency_key="idem-retry-1",
        request_id="req-original",
        user_id="user-retry-1",
        session_id="session-retry-1",
        turn_id="turn-retry-1",
        channel="manychat",
        occurred_at="2026-08-11T10:05:00+08:00",
    )
    retry = enrich_runtime_v7_analytical_qualifications(
        result,
        event_id="evt-retry-1",
        idempotency_key="idem-retry-1",
        request_id="req-retry",
        user_id="user-retry-1",
        session_id="session-retry-1",
        turn_id="turn-retry-1",
        channel="manychat",
        occurred_at="2026-08-11T10:05:00+08:00",
    )

    first_record = first["analytical_qualifications"][0]
    retry_record = retry["analytical_qualifications"][0]
    assert first_record["qualification_event_id"] == retry_record["qualification_event_id"]
    assert retry_record["event_identity"]["request_id"] == "req-retry"
    assert retry_record["event_identity"]["idempotency_key"] == "idem-retry-1"


def test_moderate_qualification_records_tag_delivery_failure():
    result = evaluate_runtime_v7_tagging(
        current_user_message="195/65R15 Goodyear sa Pasig",
        background_signals=[],
        lead_qualification={"moderate_intent": True, "lead_stage": "complete"},
        tool_results=[],
    )
    marked = mark_runtime_v7_tags_applied(
        result,
        failed_tags=[{"tag": "Moderate Intent", "error": "manychat timeout"}],
        apply_status="failed",
    )

    outcome = marked["analytical_qualifications"][0]["tag_application_outcome"]
    assert outcome["moderate_tag_outcome"] == "failed"
    assert outcome["apply_status"] == "failed"
    assert outcome["tags_failed"] == ["Moderate Intent"]


def test_non_moderate_turn_has_no_analytical_qualification():
    result = evaluate_runtime_v7_tagging(
        current_user_message="May gulong ba kayo?",
        background_signals=[],
        lead_qualification={"moderate_intent": False, "lead_stage": "incomplete"},
        tool_results=[],
    )

    assert "analytical_qualifications" not in result


def test_runtime_v7_tagging_does_not_treat_visible_options_as_selected_product():
    result = evaluate_runtime_v7_tagging(
        current_user_message="Tingnan ko muna.",
        assistant_response="Sige po, take your time.",
        background_signals=[
            {"key": "tire_size", "value": "215/55R17"},
            {
                "key": "latest_product_presentation",
                "value": "pres_options_only",
            },
        ],
        lead_qualification={"lead_stage": "incomplete"},
        tool_results=[],
        turn_count=2,
    )

    assert result["synthetic_signals"]["selected_product_ref"] is False
    assert result["synthetic_signals"]["has_tire_brand"] is False


def test_runtime_v7_tagging_retains_trusted_selected_product_context():
    result = evaluate_runtime_v7_tagging(
        current_user_message="Sige po.",
        assistant_response="Noted po.",
        background_signals=[{"key": "tire_size", "value": "225/45R18"}],
        lead_qualification={"lead_stage": "incomplete"},
        tool_results=[],
        selected_product_context={
            "product_card_ref": "card_selected",
            "product_id": "12345",
        },
        turn_count=3,
    )

    assert result["synthetic_signals"]["selected_product_ref"] is True
    assert result["synthetic_signals"]["has_tire_brand"] is True


def test_runtime_v7_tagging_does_not_count_service_phrase_location_or_failed_slot_lookup():
    result = evaluate_runtime_v7_tagging(
        current_user_message="Saan po ako makakatanggap ng libreng pag-installation?",
        assistant_response="Pa-send po city/barangay para ma-check natin.",
        background_signals=[
            {"key": "tire_size", "value": "225/55R19"},
            {"key": "preferred_brands", "value": "MICHELIN"},
            {"key": "location", "value": "Free Installation", "source": "service_observation_store"},
        ],
        lead_qualification={
            "lead_stage": "incomplete",
            "moderate_intent": False,
            "present": {"tire_size": "225/55R19", "tire_brand": "MICHELIN", "location": "Free Installation"},
            "missing": ["location"],
        },
        tool_results=[
            {
                "name": "product_search",
                "result": {"product_card_headers": [{"brand": "MICHELIN", "sku_model": "MICHELIN 225/55R19"}]},
                "full_result": {"product_cards": [{"brand": "MICHELIN", "sku_model": "MICHELIN 225/55R19"}]},
            },
            {
                "name": "find_installation_slots",
                "result": {"status": "no_service_location", "availability": {"slot_count": 0}},
                "full_result": {
                    "status": "no_service_location",
                    "query_basis": {"location": "Free Installation", "location_input_status": "generic_non_location"},
                    "availability": {"slot_count": 0},
                    "slot_groups": [],
                },
            },
        ],
        turn_count=3,
    )

    tags = {action["tag"] for action in result["tags_to_add"]}
    assert "Moderate Intent" not in tags
    assert "High Intent" not in tags
    assert result["synthetic_signals"]["has_location"] is False
    assert result["synthetic_signals"]["has_location_or_partner"] is False
    assert result["synthetic_signals"]["has_schedule_or_payment"] is False


def test_runtime_v7_tagging_emits_irate_chatbot_error_and_order_booked():
    result = evaluate_runtime_v7_tagging(
        current_user_message="ang tagal, bad service ito",
        assistant_response="Pasensya po.",
        background_signals=[],
        lead_qualification={},
        tool_results=[
            {"name": "create_order", "result": {"status": "success"}, "full_result": {"status": "success", "order_id": "ORD-1"}},
            {"name": "product_search", "result": {"status": "error"}, "full_result": {"status": "error", "error_type": "timeout"}},
        ],
        retry_events=[{"type": "empty_final_response_fallback"}],
        turn_count=1,
    )

    tags = {action["tag"] for action in result["tags_to_add"]}
    assert "Irate" in tags
    assert "Chatbot Error" in tags
    assert "Order Booked" in tags


def test_runtime_v7_tagging_does_not_mark_rejected_tool_plan_as_error():
    result = evaluate_runtime_v7_tagging(
        current_user_message=(
            "May schedule ba sa Pampanga? Hindi pa ako sure sa city."
        ),
        assistant_response=(
            "Pili po tayo ng serviceable city para ma-check ang schedule."
        ),
        background_signals=[],
        lead_qualification={},
        tool_results=[
            {
                "name": "find_installation_slots",
                "result": {
                    "status": "error",
                    "error_type": "tool_plan_not_authorized",
                    "required_decision_layer": "city",
                },
                "full_result": {
                    "status": "error",
                    "error_type": "tool_plan_not_authorized",
                    "required_decision_layer": "city",
                },
            }
        ],
        turn_count=1,
    )

    tags = {action["tag"] for action in result["tags_to_add"]}
    assert "Chatbot Error" not in tags


def test_runtime_v7_tagging_emits_payment_confirmation_from_match_tool():
    result = evaluate_runtime_v7_tagging(
        current_user_message="sent ko na payment proof",
        assistant_response="Received po, ipa-verify natin.",
        background_signals=[{"key": "payment_proof_evidence", "value": "img_payment_1"}],
        lead_qualification={},
        tool_results=[
            {
                "name": "match_payment_proof",
                "result": {"status": "matched_unverified", "payment_proof_received": True},
                "full_result": {
                    "status": "matched_unverified",
                    "payment_proof_received": True,
                    "evidence_ref": "img_payment_1",
                },
            }
        ],
        turn_count=4,
    )

    tags = {action["tag"] for action in result["tags_to_add"]}
    assert "Payment Confirmation" in tags
    assert "Order Booked" not in tags


def test_runtime_v7_tagging_emits_website_inquiry_from_customer_text():
    result = evaluate_runtime_v7_tagging(
        current_user_message=(
            "Nakita ko sa website niyo ito "
            "https://gulong.ph/product/apollo-175-65-r14-amazer, available pa ba?"
        ),
        assistant_response="Check ko po.",
        background_signals=[],
        lead_qualification={},
        tool_results=[],
        turn_count=1,
    )

    tags = {action["tag"] for action in result["tags_to_add"]}
    assert "Website Inquiry" in tags
    assert "customer_sent_gulong_url" in result["synthetic_signals"]["website_evidence"]
    assert "customer_referenced_website_or_site" in result["synthetic_signals"]["website_evidence"]


def test_runtime_v7_tagging_ignores_assistant_product_links_for_website_inquiry():
    result = evaluate_runtime_v7_tagging(
        current_user_message="hm 175 65 14",
        assistant_response="https://gulong.ph/product/apollo-175-65-r14-amazer",
        background_signals=[],
        lead_qualification={},
        tool_results=[
            {
                "name": "product_search",
                "result": {"product_card_headers": [{"brand": "APOLLO"}]},
                "full_result": {"product_cards": [{"url": "https://gulong.ph/product/apollo-175-65-r14-amazer"}]},
            }
        ],
        turn_count=1,
    )

    tags = {action["tag"] for action in result["tags_to_add"]}
    assert "Website Inquiry" not in tags
    assert result["synthetic_signals"]["website_evidence"] == []


def test_runtime_v7_tagging_emits_website_inquiry_from_product_page_image_evidence():
    result = evaluate_runtime_v7_tagging(
        current_user_message="available pa ba ito?",
        assistant_response="Check ko po.",
        background_signals=[
            {
                "key": "external_product_evidence",
                "value": "img_123: product_title=MICHELIN PRIMACY 4 205/55R16",
                "source": "external_evidence",
                "metadata": {
                    "image_type": "website_product_card",
                    "evidence_ref": "img_123",
                    "source_origin": "gulong_ph",
                    "gulong_surface": "product_card",
                },
            }
        ],
        lead_qualification={},
        tool_results=[],
        turn_count=1,
    )

    tags = {action["tag"] for action in result["tags_to_add"]}
    assert "Website Inquiry" in tags
    assert result["synthetic_signals"]["website_evidence"] == ["gulong_product_card_image"]


def test_runtime_v7_tagging_ignores_marketing_asset_even_when_ocr_includes_gulong_url():
    result = evaluate_runtime_v7_tagging(
        current_user_message="price list po neto",
        assistant_response="Check ko po.",
        background_signals=[
            {
                "key": "website_inquiry_evidence",
                "value": "img_marketing_1:marketing_asset",
                "source": "external_evidence",
                "metadata": {
                    "image_type": "website_product_card",
                    "evidence_ref": "img_marketing_1",
                    "source_origin": "gulong_ph",
                    "gulong_surface": "marketing_asset",
                },
            },
            {
                "key": "external_product_evidence",
                "value": "https://gulong.ph/promo/tire-price-list",
                "source": "external_evidence",
                "metadata": {
                    "image_type": "website_product_card",
                    "evidence_ref": "img_marketing_1",
                    "source_origin": "gulong_ph",
                    "gulong_surface": "marketing_asset",
                },
            },
        ],
        lead_qualification={"lead_stage": "complete"},
        tool_results=[],
        turn_count=1,
    )

    assert result["synthetic_signals"]["website_evidence"] == []
    assert {action["tag"] for action in result["tags_to_add"]} == {"Moderate Intent"}


def test_runtime_v7_tagging_does_not_route_unclassified_image_ocr_gulong_url():
    result = evaluate_runtime_v7_tagging(
        current_user_message="Paki-check po itong image.",
        assistant_response="Check ko po.",
        background_signals=[
            {
                "key": "external_product_evidence",
                "value": (
                    "img_marketing_unclassified: product_url="
                    "https://gulong.ph/promo/michelin-cashback"
                ),
                "source": "external_evidence",
                "metadata": {
                    "image_type": "website_product_card",
                    "evidence_ref": "img_marketing_unclassified",
                    "source_origin": "gulong_ph",
                    "gulong_surface": "",
                },
            }
        ],
        lead_qualification={"lead_stage": "complete"},
        tool_results=[],
        turn_count=1,
    )

    assert result["synthetic_signals"]["website_evidence"] == []
    assert {action["tag"] for action in result["tags_to_add"]} == {"Moderate Intent"}


def test_runtime_v7_tagging_emits_website_inquiry_from_gulong_order_email_image():
    result = evaluate_runtime_v7_tagging(
        current_user_message="Ito po yung order email ko.",
        assistant_response="Check ko po.",
        background_signals=[
            {
                "key": "website_inquiry_evidence",
                "value": "img_order_1:order_email",
                "source": "external_evidence",
                "metadata": {
                    "image_type": "order_confirmation",
                    "evidence_ref": "img_order_1",
                    "source_origin": "gulong_ph",
                    "gulong_surface": "order_email",
                },
            }
        ],
        lead_qualification={},
        tool_results=[],
        turn_count=1,
    )

    assert {action["tag"] for action in result["tags_to_add"]} == {
        "Website Inquiry"
    }
    assert result["synthetic_signals"]["website_evidence"] == [
        "gulong_order_email_image"
    ]


def test_runtime_v7_tagging_does_not_route_other_merchant_order_image():
    result = evaluate_runtime_v7_tagging(
        current_user_message="Ito po yung order email ko.",
        assistant_response="Check ko po.",
        background_signals=[
            {
                "key": "website_inquiry_evidence",
                "value": "img_order_2:order_email",
                "source": "external_evidence",
                "metadata": {
                    "image_type": "order_confirmation",
                    "evidence_ref": "img_order_2",
                    "source_origin": "other_merchant",
                    "gulong_surface": "order_email",
                },
            }
        ],
        lead_qualification={},
        tool_results=[],
        turn_count=1,
    )

    assert "Website Inquiry" not in {
        action["tag"] for action in result["tags_to_add"]
    }


def test_runtime_v7_tagging_does_not_treat_gulong_email_address_as_url():
    result = evaluate_runtime_v7_tagging(
        current_user_message="Send ko po sa hello@gulong.ph yung proof.",
        assistant_response="Sige po.",
        background_signals=[],
        lead_qualification={},
        tool_results=[],
        turn_count=1,
    )

    assert result["synthetic_signals"]["website_evidence"] == []
    assert "Website Inquiry" not in {
        action["tag"] for action in result["tags_to_add"]
    }


def test_website_inquiry_suppresses_competing_moderate_and_high_intent_tags():
    result = evaluate_runtime_v7_tagging(
        current_user_message="Nag-checkout ako sa https://gulong.ph/checkout",
        assistant_response="Check ko po.",
        background_signals=[
            {
                "key": "chosen_schedule_slot",
                "value": "2026-08-03 09:00",
                "source": "latest_user_message",
            }
        ],
        lead_qualification={
            "lead_stage": "complete",
            "moderate_intent": True,
            "present": {
                "tire_size": "225/55R18",
                "tire_brand": "HANKOOK",
                "location": "Makati City",
                "contact_number": "09000000000",
            },
        },
        tool_results=[
            {
                "name": "resolve_product_reference",
                "full_result": {
                    "selected_product_cards": [{"item_ref": "prod_1"}]
                },
            }
        ],
        turn_count=5,
    )

    tags = {action["tag"] for action in result["tags_to_add"]}
    assert tags == {"Website Inquiry"}
    assert result["synthetic_signals"]["moderate_intent"] is True
    qualification = result["analytical_qualifications"][0]
    assert qualification["countable"] is True
    assert qualification["tag_application_outcome"]["routing_policy"] == "website_inquiry_exclusive"
    assert (
        qualification["tag_application_outcome"]["moderate_tag_outcome"]
        == "suppressed_by_website_inquiry"
    )


def test_website_inquiry_keeps_independent_operational_tags():
    result = evaluate_runtime_v7_tagging(
        current_user_message=(
            "Nag-checkout ako sa https://gulong.ph/checkout pero nag-error."
        ),
        assistant_response="Check ko po.",
        background_signals=[],
        lead_qualification={
            "lead_stage": "complete",
            "moderate_intent": True,
            "present": {
                "tire_size": "225/55R18",
                "tire_brand": "HANKOOK",
                "location": "Makati City",
            },
        },
        tool_results=[
            {
                "name": "create_order",
                "result": {"status": "success"},
                "full_result": {"status": "success", "order_id": "ORD-1"},
            }
        ],
        retry_events=[{"type": "empty_final_response_fallback"}],
        turn_count=5,
    )

    tags = {action["tag"] for action in result["tags_to_add"]}
    assert tags == {"Website Inquiry", "Chatbot Error", "Order Booked"}
    assert "Moderate Intent" not in tags
    assert "High Intent" not in tags


def test_existing_website_inquiry_tag_keeps_routing_priority_on_later_turns():
    result = evaluate_runtime_v7_tagging(
        current_user_message="225/55R18, Makati po.",
        assistant_response="Check ko po.",
        background_signals=[],
        lead_qualification={
            "lead_stage": "complete",
            "moderate_intent": True,
            "present": {
                "tire_size": "225/55R18",
                "tire_brand": "HANKOOK",
                "location": "Makati City",
            },
        },
        tool_results=[],
        turn_count=2,
        existing_tags=["Website Inquiry"],
    )

    assert result["tags_to_add"] == []
    assert {
        action["tag"] for action in result["tags_skipped_existing"]
    } == {"Website Inquiry"}
    assert "existing_website_inquiry_tag" in result["synthetic_signals"][
        "website_evidence"
    ]


def test_typed_human_handoff_records_state_and_requests_stop_chatbot_tag(
    monkeypatch,
):
    monkeypatch.setenv("RUNTIME_V7_TURN_PLAN_ENABLED", "1")
    harness = RuntimeV7Harness(
        model_client=HumanHandoffToolModel(),
        tools=ProductToolHarness(),
        default_domains=(),
    )

    turn = harness.run_turn(
        "Please stop the bot and let me talk to a human agent.",
    )

    handoff = next(
        result
        for result in turn["tool_results"]
        if result["name"] == "request_human_handoff"
    )
    assert handoff["full_result"]["status"] == "requested"
    assert handoff["full_result"]["human_assignment_confirmed"] is False
    assert turn["human_handoff_state_after_turn"]["status"] == "requested"
    assert "request_human_handoff" in turn["customer_turn_plan"][
        "authorized_side_effects"
    ]
    assert {
        action["tag"] for action in turn["tagging"]["tags_to_add"]
    } == {"Stop Chatbot"}
    assert "already connected" not in turn["runtime_final_response"].casefold()
    assert "welcome to gulong" not in turn["runtime_final_response"].casefold()
    assert "human teammate still needs to pick up" in turn[
        "runtime_final_response"
    ].casefold()


def test_human_availability_text_alone_does_not_trigger_stop_tag():
    result = evaluate_runtime_v7_tagging(
        current_user_message="Do you have human customer service agents?",
        assistant_response="Yes, our team can help during service hours.",
        background_signals=[],
        lead_qualification={},
        tool_results=[],
        retry_events=[],
        turn_count=1,
    )

    assert "Stop Chatbot" not in {
        action["tag"] for action in result["tags_to_add"]
    }


def test_semantic_handoff_gate_rejects_model_tool_misfire_for_availability():
    harness = RuntimeV7Harness(
        model_client=HumanAvailabilityMisfireModel(),
        tools=ProductToolHarness(),
        default_domains=(),
    )

    turn = harness.run_turn("May human customer service agents ba kayo?")

    handoff = next(
        result
        for result in turn["tool_results"]
        if result["name"] == "request_human_handoff"
    )
    assert handoff["full_result"]["status"] == "not_requested"
    assert turn["human_handoff_decision"]["decision"] == (
        "availability_question"
    )
    assert turn["human_handoff_state_after_turn"] == {}
    assert "Stop Chatbot" not in {
        action["tag"] for action in turn["tagging"]["tags_to_add"]
    }
    assert "pause" not in turn["runtime_final_response"].casefold()
    assert "human customer service" in turn[
        "runtime_final_response"
    ].casefold()
