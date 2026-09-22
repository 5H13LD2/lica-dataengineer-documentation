"""Focused contracts for approved Runtime V7 starter-control labels."""

from __future__ import annotations

import json

import pytest

from runtime_v7.model_contract import RUNTIME_V7_SYSTEM_PROMPT, build_runtime_v7_context
from runtime_v7.product_observations import ProductToolHarness
from runtime_v7.runtime_harness import (
    FINAL_COMPOSER_SYSTEM_PROMPT,
    RuntimeV7Harness,
    _build_final_composer_messages,
    _first_turn_intro_context_for_model,
)
from runtime_v7.triage_seeds import (
    build_exact_button_context,
    build_response_seeds,
)


@pytest.mark.parametrize(
    "label",
    [
        "Get Started",
        "GET STARTED",
        "  get\t started  ",
        "\u2705 Get Started",
        "\u2705\ufe0f  GET STARTED",
        "\u2714\ufe0f Get Started",
        "\u2611\ufe0e Get Started",
    ],
)
def test_approved_get_started_control_variants_receive_the_typed_entry_seed(label: str) -> None:
    context = build_exact_button_context(label)
    seeds = build_response_seeds(current_user_message=label)

    assert context is not None
    assert context["type"] == "automated_get_started_button"
    assert [seed["type"] for seed in seeds] == ["automated_get_started_button"]


@pytest.mark.parametrize(
    "message",
    [
        "How do I get started with ordering?",
        "Get Started - paano umorder?",
        "I want to get started with my order",
        "Get Started 205/55R16 po",
        "\u2705 Get Started, Michelin preferred ko",
        "Get Started sa Dasmarinas, may promo ba?",
    ],
)
def test_get_started_customer_prose_or_compound_messages_stay_model_owned(message: str) -> None:
    assert build_exact_button_context(message) is None
    assert build_response_seeds(current_user_message=message) == []


def test_bare_get_started_context_keeps_order_faq_and_composition_choices_separate() -> None:
    seeds = build_response_seeds(current_user_message="\u2705 Get Started")

    context = build_runtime_v7_context(
        current_user_message="\u2705 Get Started",
        response_seeds=seeds,
    )

    assert "## Bare Get Started Entry Action" in context
    assert "not a how-to-order or order-process request" in context
    assert "ask one connected discovery question for tire size or vehicle" in context
    assert "optional support rather than the primary answer" in context
    assert "normally show the reviewed promo catalog" not in context
    assert "Do not ask permission to check or show" in context
    assert "Choose the wording, CTA, and any supported surface yourself" in context


def test_low_information_first_turn_keeps_progression_model_led_without_permission_step() -> None:
    intro = _first_turn_intro_context_for_model("welcome_only")
    instruction = intro["model_instruction"]

    assert "ask one connected discovery question" in instruction
    assert "may accompany a generic availability" in instruction
    assert "must not replace that answer or discovery step" in instruction
    assert "compact welcome plus one discovery question" in instruction
    assert "If no useful surface is supplied" in instruction
    assert "do not mention or promise current promo cards" in instruction
    assert "Do not ask permission" in instruction
    assert "If the customer provided meaningful details or asked a specific question" in instruction
    assert "it is not mandatory" in RUNTIME_V7_SYSTEM_PROMPT
    assert "only \"How can I help?\"" in RUNTIME_V7_SYSTEM_PROMPT
    assert "multi-field intake list" in FINAL_COMPOSER_SYSTEM_PROMPT
    assert "This is not permission to" in FINAL_COMPOSER_SYSTEM_PROMPT
    assert "mention, promise, or invite" in FINAL_COMPOSER_SYSTEM_PROMPT


def test_availability_starter_can_use_promo_entry_guidance() -> None:
    seeds = build_response_seeds(
        current_user_message="Is anyone available to chat?"
    )

    assert [seed["type"] for seed in seeds] == ["automated_availability_button"]
    assert "normally show the reviewed promo catalog" in seeds[0]["guidance"]
    assert "one connected discovery question" in seeds[0]["guidance"]


def test_tire_help_starter_leads_with_discovery_and_keeps_promo_optional() -> None:
    seeds = build_response_seeds(
        current_user_message="Can you help me find the right tire for my car?"
    )

    assert [seed["type"] for seed in seeds] == ["automated_tire_help_button"]
    guidance = seeds[0]["guidance"]
    assert "exactly one useful discovery input" in guidance
    assert "sidewall tire size" in guidance
    assert "otherwise the vehicle make/model" in guidance
    assert "may accompany" in guidance
    assert "must not replace" in guidance


def test_how_to_avail_starter_answers_purchase_process_before_optional_promo() -> None:
    seeds = build_response_seeds(current_user_message="How to avail?")

    assert [seed["type"] for seed in seeds] == ["automated_how_to_avail_button"]
    guidance = seeds[0]["guidance"]
    assert "purchase process first" in guidance
    assert "Do not reinterpret this process question as promo discovery" in guidance
    assert "only after the process answer" in guidance


def test_final_composer_receives_the_normal_typed_entry_seed() -> None:
    seeds = build_response_seeds(current_user_message="Get Started")

    messages = _build_final_composer_messages(
        current_user_message="Get Started",
        request_time="2026-08-11T09:00:00+08:00",
        active_working_memory="",
        background_signals=[],
        lead_qualification={},
        order_readiness={},
        capability_profile={},
        tool_results=[],
        draft_assistant_text="Welcome po.",
        response_seeds=seeds,
    )
    payload = json.loads(messages[-1]["content"])

    assert payload["response_seed_context"] == [
        {
            "type": "automated_get_started_button",
            "priority": "high",
            "guidance": seeds[0]["guidance"],
        }
    ]


class _WelcomeOnlyModel:
    """Deterministic no-tool model stub for the model-owned entry path."""

    def __init__(self) -> None:
        self.calls = []

    def complete(
        self,
        *,
        messages,
        tools,
        tool_choice="auto",
        response_format=None,
        max_tokens=None,
        temperature=None,
    ):
        self.calls.append(
            {
                "messages": list(messages),
                "tools": list(tools),
                "tool_choice": tool_choice,
                "response_format": response_format,
            }
        )
        return {
            "content": "Welcome po. Ano pong tire size or vehicle ninyo?",
            "tool_calls": [],
            "usage": {},
            "cache_usage": {},
            "latency_ms": 1,
            "finish_reason": "stop",
        }


def test_bare_get_started_reaches_the_model_composed_welcome_path_without_order_faq() -> None:
    model = _WelcomeOnlyModel()
    record = RuntimeV7Harness(
        model_client=model,
        tools=ProductToolHarness(),
    ).run_turn("\u2705 Get Started")

    main_context = model.calls[0]["messages"][-1]["content"]
    assert "## Bare Get Started Entry Action" in main_context
    assert "not a how-to-order or order-process request" in main_context
    assert "ask one connected discovery question for tire size or vehicle" in main_context
    assert "promo is optional support rather than the primary answer" in main_context
    assert "normal default is to call search_promo_catalog" not in main_context
    assert record["runtime_final_response"] == "Welcome po. Ano pong tire size or vehicle ninyo?"
    assert not any(result["name"] == "answer_order_faq" for result in record["tool_results"])
