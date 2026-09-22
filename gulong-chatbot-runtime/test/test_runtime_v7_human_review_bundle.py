from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "runtime_v7_human_review_bundle.py"
SPEC = importlib.util.spec_from_file_location("runtime_v7_human_review_bundle", SCRIPT)
assert SPEC and SPEC.loader
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)


def _turn(*, user_message: str = "hm po 205/55R16 😊") -> dict:
    return {
        "turn_id": "turn_1",
        "user_message": user_message,
        "runtime_final_response": json.dumps(
            {
                "response_units": [
                    {"type": "text", "content": {"text": "Sige po, ito ang current options 😊"}}
                ]
            },
            ensure_ascii=False,
        ),
        "tool_results": [],
        "llm_usage_summary": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        "context_cache_summary": {"cache_read_input_tokens": 40, "uncached_prompt_tokens": 80},
        "customer_turn_plan": {"current_decision_layer": "product_selection", "next_decision_layer": "location"},
        "final_composer": {"status": "used"},
    }


def test_pack_is_varied_and_contains_no_scripted_response_gate() -> None:
    pack = json.loads(
        (Path(__file__).resolve().parents[1] / "test_packs" / "runtime_v7_human_response_eval_pack.json").read_text(encoding="utf-8")
    )
    assert bundle.validate_pack(pack) == []
    scenarios = pack["scenarios"]
    assert len(scenarios) >= 13
    for field in ("brand", "tire_size", "vehicle", "location"):
        values = [str(row["variation_dimensions"][field]) for row in scenarios if row.get("variation_dimensions", {}).get(field)]
        counts = Counter(values)
        # A larger transition pack may intentionally reuse a value to isolate
        # the changed state while still keeping broad customer-input variety.
        assert len(counts) / len(values) >= 0.85
        assert max(counts.values()) <= 2


def test_harness_artifact_reconstructs_utf8_rendering_as_structural_only() -> None:
    payload = {
        "scenario_id": "utf8_case",
        "runtime_payload": {"turns": [_turn()]},
        "scenario": {"id": "utf8_case", "hard_fact_checks": ["Facts use trusted evidence."]},
    }
    unit = bundle.build_review_unit(payload)
    assert unit["evidence_strength"] == "structural_only"
    assert unit["turns"][0]["visible"]["content_messages"] == [
        {"type": "text", "text": "Sige po, ito ang current options 😊"}
    ]
    assert unit["review"]["dimensions"]["natural_language"]["rating"] is None
    assert unit["mechanical_summary"]["status"] == "clear"


def test_api_debug_payload_preserves_rendered_order_and_return_only_label() -> None:
    payload = {
        "debug_payload": {
            "request": {"request_id": "req-1", "delivery_mode": "return_only"},
            "turn_record": _turn(user_message="pwede sa Cainta?"),
            "rendered": {
                "content_messages": [
                    {"type": "text", "text": "Cainta po, noted."},
                    {"type": "image", "url": "https://cdn.example.test/promo.png", "alt": "Warranty promo"},
                    {"type": "text", "text": "Aling schedule ang okay sa inyo?"},
                ],
                "response": {"version": "2", "content": "ignored internal body"},
                "text": "Cainta po, noted.",
            },
            "delivery_result": {"status": "skipped", "reason": "return_only", "delivery_mode": "return_only"},
        }
    }
    unit = bundle.build_review_unit(payload)
    messages = unit["turns"][0]["visible"]["content_messages"]
    assert [row["type"] for row in messages] == ["text", "image", "text"]
    assert unit["evidence_strength"] == "customer_path_return_only"
    assert unit["turns"][0]["telemetry"]["delivery"]["reason"] == "return_only"


def test_return_only_takes_precedence_over_contradictory_success_status() -> None:
    payload = {
        "debug_payload": {
            "request": {"delivery_mode": "return_only"},
            "turn_record": _turn(),
            "rendered": {"content_messages": [{"type": "text", "text": "Preview lang po."}]},
            "delivery_result": {"status": "success", "reason": "return_only"},
        }
    }
    assert bundle.build_review_unit(payload)["evidence_strength"] == "customer_path_return_only"


def test_compact_include_debug_api_payload_is_supported() -> None:
    payload = {
        "scenario": {"id": "api_compact", "turns": ["may Falken 215/45R17 po?"]},
        "response": {"bubble1": "Ito po ang current options."},
        "content_messages": [{"type": "text", "text": "Ito po ang current options."}],
        "images": [],
        "payment": {},
        "delivery_result": {"status": "skipped", "reason": "return_only", "delivery_mode": "return_only"},
        "debug": {
            "turn_id": "turn_1",
            "tool_calls": [{"name": "search_products", "status": "success"}],
            "llm_usage_summary": {"total_tokens": 420},
            "final_composer_status": "used",
            "response_guard_events": [],
        },
    }
    unit = bundle.build_review_unit(payload)
    assert unit["evidence_strength"] == "customer_path_return_only"
    assert unit["turns"][0]["user_message"] == "may Falken 215/45R17 po?"
    assert unit["turns"][0]["telemetry"]["tools"] == [
        {"name": "search_products", "status": "success", "latency_ms": None}
    ]


def test_explicit_empty_rendered_payload_is_blocked_not_reconstructed() -> None:
    payload = {
        "debug_payload": {
            "turn_record": _turn(user_message="hello po"),
            "rendered": {},
            "delivery_result": {"status": "failed"},
        }
    }
    unit = bundle.build_review_unit(payload)
    assert unit["turns"][0]["visible"]["content_messages"] == []
    assert {item["code"] for item in unit["mechanical_summary"]["findings"]} == {
        "missing_customer_visible_messages"
    }


def test_missing_customer_input_blocks_qualitative_review() -> None:
    payload = {
        "response": {"bubble1": "May options po."},
        "content_messages": [{"type": "text", "text": "May options po."}],
        "debug": {"turn_id": "turn_1"},
    }
    unit = bundle.build_review_unit(payload)
    assert "missing_customer_input_evidence" in {
        item["code"] for item in unit["mechanical_summary"]["findings"]
    }


def test_allowlist_redacts_pii_and_drops_internal_fields() -> None:
    visible = bundle._sanitize_visible(  # noqa: SLF001
        {
            "type": "text",
            "text": "Text 09171234567 or buyer@example.com",
            "system_prompt": "secret",
            "profile_fields": {"phone": "09171234567"},
            "buttons": [{"title": "Choose", "payload": "ps1|safe", "private_debug": "secret"}],
        }
    )
    assert visible["text"] == "Text [redacted-phone] or [redacted-email]"
    assert "system_prompt" not in visible
    assert "profile_fields" not in visible
    assert visible["buttons"] == [{"title": "Choose", "payload": "ps1|safe"}]


def test_real_renderer_shape_keeps_bubbles_actions_images_and_presentations() -> None:
    payload = {
        "debug_payload": {
            "request": {"delivery_mode": "return_only", "session_id": "private-session"},
            "turn_record": _turn(),
            "rendered": {
                "response": {"bubble1": "Ito po ang choices."},
                "content_messages": [
                    {
                        "type": "cards",
                        "image_aspect_ratio": "square",
                        "elements": [
                            {
                                "title": "Roadstone N'Fera",
                                "image_url": "https://cdn.example.test/roadstone.png?private=token",
                                "buttons": [
                                    {
                                        "type": "flow",
                                        "caption": "Choose Roadstone",
                                        "target": "internal-router-name",
                                        "actions": [
                                            {
                                                "action": "set_field_value",
                                                "field_name": "promo_selected_id",
                                                "value": "ps1|products_demo|roadstone_1",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                    {"type": "image", "url": "https://cdn.example.test/qr.png", "image_ref": "img_payment_qr"},
                ],
                "images": [{"url": "https://cdn.example.test/qr.png", "image_ref": "img_payment_qr"}],
                "choice_presentations": [
                    {
                        "presentation_ref": "products_demo",
                        "choice_type": "product_selection",
                        "choices": [{"choice_ref": "product:roadstone_1", "label": "Roadstone N'Fera"}],
                    }
                ],
                "product_presentations": [
                    {
                        "presentation_ref": "products_demo",
                        "price_list_included": True,
                        "cards": [
                            {
                                "card_ref": "roadstone_1",
                                "brand": "Roadstone",
                                "tire_size": "205/60R16",
                                "pricing_facts": {"quantity": 4, "payable_total": 19800},
                            }
                        ],
                    }
                ],
                "payment": {"order_id": "private-order", "payment_stage": "deposit", "expected_amount": 5000},
            },
            "delivery_result": {"status": "skipped", "reason": "return_only"},
        },
        "_source_path": "C:/Users/private/customer-debug.json",
    }
    unit = bundle.build_review_unit(payload)
    turn = unit["turns"][0]
    assert unit["source_artifact"] == "customer-debug.json"
    assert turn["visible"]["response"] == {"bubble1": "Ito po ang choices."}
    button = turn["visible"]["content_messages"][0]["elements"][0]["buttons"][0]
    assert button["target"] == "[configured]"
    assert button["actions"][0]["value"].startswith("ps1|")
    assert turn["visible"]["content_messages"][0]["elements"][0]["image_url"].endswith("roadstone.png")
    assert turn["visible"]["images"][0]["image_ref"] == "img_payment_qr"
    assert turn["presentation_evidence"]["products"][0]["price_list_included"] is True
    assert turn["presentation_evidence"]["products"][0]["cards"][0]["pricing_facts"]["payable_total"] == 19800
    assert "order_id" not in turn["presentation_evidence"]["payment"]
    assert "identity" not in turn["telemetry"]


def test_redaction_handles_spaced_phone_and_url_secrets() -> None:
    text = "Call +63 917 123 4567 or see https://example.test/pay?id=secret#frag"
    assert bundle._redact_text(text) == "Call [redacted-phone] or see https://example.test/pay"  # noqa: SLF001


def test_mechanical_findings_do_not_grade_style() -> None:
    messages = [{"type": "text", "text": "Hello po!!! 😊😊 mahaba man ito, human review pa rin."}]
    assert bundle._mechanical_findings(_turn(), messages) == []  # noqa: SLF001


def test_duplicate_choice_token_and_multiple_layers_block_mechanically() -> None:
    messages = [
        {"type": "card", "buttons": [{"title": "A", "payload": "ps1|same"}, {"title": "Again", "payload": "ps1|same"}]},
        {"type": "quick_replies", "items": [{"title": "City", "payload": "lc1|city"}]},
    ]
    findings = bundle._mechanical_findings(_turn(), messages)  # noqa: SLF001
    assert {row["code"] for row in findings} == {"duplicate_choice_tokens", "multiple_active_choice_layers"}
    assert all(row["blocking"] for row in findings)


def test_supporting_promo_action_can_accompany_product_selection() -> None:
    messages = [
        {"type": "cards", "buttons": [{"title": "Choose tire", "payload": "ps1|product_options|tire_1"}]},
        {"type": "cards", "buttons": [{"title": "Warranty details", "payload": "pc1|august_promos|double_warranty"}]},
    ]
    assert bundle._mechanical_findings(_turn(), messages) == []  # noqa: SLF001


def test_completed_review_requires_orchestrator_judgment_and_rationales() -> None:
    unit = bundle.build_review_unit(
        {
            "scenario_id": "review_case",
            "runtime_payload": {"turns": [_turn()]},
            "scenario": {"id": "review_case", "hard_fact_checks": ["No unsupported price."]},
        }
    )
    assert bundle.validate_completed_review(unit)
    review = unit["review"]
    review["hard_fact_reviews"][0].update({"rating": "pass"})
    for dimension in bundle.REVIEW_DIMENSIONS:
        review["dimensions"][dimension].update({"rating": "pass"})
    review["dimensions"]["presentation"].update({"rating": "concern", "rationale": "The card order needs review."})
    review["overall"].update({"decision": "revise", "rationale": "One presentation concern remains."})
    assert bundle.validate_completed_review(unit) == []


def test_review_pass_cannot_override_mechanical_or_hard_fact_failure() -> None:
    unit = {
        "mechanical_summary": {"blocking_finding_count": 1},
        "review": {
            "hard_fact_reviews": [{"check": "Price", "rating": "fail", "rationale": "Wrong basis."}],
            "dimensions": {dimension: {"rating": "pass", "rationale": ""} for dimension in bundle.REVIEW_DIMENSIONS},
            "overall": {"decision": "pass", "rationale": "Looks friendly."},
        },
    }
    errors = bundle.validate_completed_review(unit)
    assert "overall.pass_not_allowed_with_mechanical_blocker" in errors
    assert "overall.pass_not_allowed_with_hard_fact_failure" in errors


def test_review_pass_cannot_drop_checks_or_override_dimension_failure() -> None:
    unit = bundle.build_review_unit(
        {
            "scenario_id": "review_integrity",
            "runtime_payload": {"turns": [_turn()]},
            "scenario": {"id": "review_integrity", "hard_fact_checks": ["Price is grounded."]},
        }
    )
    review = unit["review"]
    review["hard_fact_reviews"] = []
    for dimension in bundle.REVIEW_DIMENSIONS:
        review["dimensions"][dimension].update({"rating": "pass"})
    review["dimensions"]["grounding"].update({"rating": "fail", "rationale": "Unsupported fact."})
    review["overall"].update({"decision": "pass", "rationale": "Cannot override failures."})
    errors = bundle.validate_completed_review(unit)
    assert "hard_fact_reviews:declared_checks_changed_or_missing" in errors
    assert "overall.pass_not_allowed_with_dimension_failure" in errors


def test_write_bundle_round_trips_utf8(tmp_path: Path) -> None:
    paths = bundle.write_review_bundle(
        [{"scenario_id": "bundle_case", "runtime_payload": {"turns": [_turn()]}, "scenario": {"id": "bundle_case"}}],
        out_dir=tmp_path,
    )
    summary = json.loads(Path(paths["summary_json"]).read_text(encoding="utf-8"))
    assert summary["scenario_count"] == 1
    artifact = Path(paths["summary_json"]).parent / summary["rows"][0]["json"]
    assert "😊" in artifact.read_text(encoding="utf-8")


def test_unsupported_artifact_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "unknown.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported Runtime V7 artifact"):
        bundle.load_probe_artifacts(path)
