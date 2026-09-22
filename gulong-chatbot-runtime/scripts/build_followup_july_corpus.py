"""Build a redacted July follow-up regression corpus from a bounded BQ export."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List


ROLLED_BACK_CASES = [
    {
        "case_id": "rollback_01_multi_field_size_location",
        "scenario_tags": ["rolled_back_release", "multi_field_cta", "tire_size"],
        "messages": [
            {"role": "user", "content": "Toyota Rush po, hindi ko sure ang exact tire size."},
            {"role": "assistant", "content": "Paki-send ang exact tire size or sidewall photo, at location niyo para ma-check ang options."},
        ],
    },
    {
        "case_id": "rollback_02_bfg_promo_low_pressure",
        "scenario_tags": ["rolled_back_release", "unsupported_promo", "deferred_intent", "bf_goodrich"],
        "messages": [
            {"role": "user", "content": "NANKANG or BFGOODRICH po."},
            {"role": "assistant", "content": "May options po tayo. Alin ang gusto niyong i-check?"},
            {"role": "user", "content": "None pa po medjo matagal tagal pa po thank you! just an inquiry po hehe"},
            {"role": "assistant", "content": "May Buy 3 Get 1 FREE promo for BFGoodrich tires. Installation partner or schedule po?"},
        ],
    },
    {
        "case_id": "rollback_03_175_65r14_shown_brand_omission",
        "scenario_tags": ["rolled_back_release", "shown_brand_retention", "tire_brand"],
        "messages": [
            {"role": "user", "content": "175/65R14 po."},
            {"role": "assistant", "content": "Shown options: Michelin, Vredestein, Deestone, and Fronway."},
            {"role": "assistant", "content": "Interested pa po ba kayo sa Michelin or Fronway?"},
        ],
    },
    {
        "case_id": "rollback_04_generic_size_car_photo",
        "scenario_tags": ["rolled_back_release", "multi_field_cta", "tire_size"],
        "messages": [
            {"role": "user", "content": "Can you help me find tires?"},
            {"role": "assistant", "content": "Send tire size, car model/year, or sidewall photo so we can check."},
        ],
    },
    {
        "case_id": "rollback_05_265_70r16_brand_location",
        "scenario_tags": ["rolled_back_release", "multi_field_cta", "shown_brand_retention"],
        "messages": [
            {"role": "user", "content": "265/70R16"},
            {"role": "assistant", "content": "Shown options: Michelin and Vredestein."},
            {"role": "assistant", "content": "Interested in Michelin or Vredestein, and what is your location?"},
        ],
    },
    {
        "case_id": "rollback_06_yokohama_preference_contradiction",
        "scenario_tags": ["rolled_back_release", "customer_preference", "brand_contradiction"],
        "messages": [
            {"role": "user", "content": "Yokohama po preferred ko."},
            {"role": "assistant", "content": "Interested pa po ba kayo sa Apollo or Michelin?"},
            {"role": "user", "content": "No. preferred Yokohama as stated."},
        ],
    },
    {
        "case_id": "rollback_07_motorcycle_roadsmart",
        "scenario_tags": ["rolled_back_release", "motorcycle", "unresolved_domain"],
        "messages": [
            {"role": "user", "content": "Dunlop Roadsmart IV motorcycle tire sizes po."},
            {"role": "assistant", "content": "Here are passenger-car tire options. Send location for installation."},
        ],
    },
    {
        "case_id": "rollback_08_yap_size_car",
        "scenario_tags": ["rolled_back_release", "ambiguous_reply", "tire_size"],
        "messages": [
            {"role": "assistant", "content": "Please send tire size or car model."},
            {"role": "user", "content": "Yap"},
            {"role": "assistant", "content": "Interested pa po ba kayo? Send tire size or car model."},
        ],
    },
    {
        "case_id": "rollback_09_arivo_after_product_list",
        "scenario_tags": ["rolled_back_release", "customer_preference", "shown_product_context"],
        "messages": [
            {"role": "assistant", "content": "Shown options: Michelin, Vredestein, Deestone, and Fronway."},
            {"role": "assistant", "content": "Interested pa po ba kayo in Michelin or Fronway?"},
            {"role": "user", "content": "Arivo po."},
        ],
    },
]


def _safety_cases() -> List[Dict[str, Any]]:
    """Return redacted July cases for gates that may be sparse in live samples."""

    presentation = {
        "presentation_ref": "safety_presentation_1",
        "observation_ref": "safety_observation_1",
        "delivery_status": "success",
        "delivered_at": "2026-07-15 09:00:00",
        "cards": [
            {
                "card_ref": "safety_michelin",
                "item_ref": "safety_item_michelin",
                "brand": "MICHELIN",
                "tire_size": "185/65R15",
                "promo_savings_line": "Buy 3 Get 1 FREE",
                "installment_text": "BPI 6mo 0% interest",
                "tire_protection_plan": "Tire Protection Plan (1 Year)",
            },
            {
                "card_ref": "safety_apollo",
                "item_ref": "safety_item_apollo",
                "brand": "APOLLO",
                "tire_size": "185/65R15",
                "promo_savings_line": "Buy 3 Get 1 FREE",
            },
            {
                "card_ref": "safety_fronway",
                "item_ref": "safety_item_fronway",
                "brand": "FRONWAY",
                "tire_size": "185/65R15",
            },
        ],
    }

    def messages(customer: str, assistant: str, *, customer_id: str) -> List[Dict[str, Any]]:
        return [
            {
                "role": "user",
                "content": customer,
                "datetime": "2026-07-15 08:58:00",
                "message_id": customer_id,
            },
            {
                "role": "assistant",
                "content": assistant,
                "datetime": "2026-07-15 09:00:00",
                "message_id": f"{customer_id}_assistant",
            },
        ]

    def fact(key: str, value: Any, message_id: str) -> Dict[str, Any]:
        return {"key": key, "value": value, "source": "latest_user_message", "message_id": message_id}

    base_expectations = {
        "one_model_call_or_less": True,
        "single_cta": True,
        "no_unsupported_claim": True,
        "no_customer_preference_contradiction": True,
    }
    cases: List[Dict[str, Any]] = [
        {
            "case_id": "safety_single_focus_tire_size",
            "scenario_tags": ["safety_matrix", "single_field_cta", "tire_size"],
            "messages": messages("Need tires po.", "Pa-send po ng tire details para ma-check natin.", customer_id="safety_size_user"),
            "expected": {**base_expectations, "route": "proactive_followup", "focus_field": "tire_size"},
        },
        {
            "case_id": "safety_single_focus_location",
            "scenario_tags": ["safety_matrix", "single_field_cta", "location"],
            "messages": messages("185/65R15 po.", "May matching options po tayo.", customer_id="safety_location_user"),
            "v7_state": {"background_signals": [fact("tire_size", "185/65R15", "safety_location_user")]},
            "expected": {**base_expectations, "route": "proactive_followup", "focus_field": "location"},
        },
        {
            "case_id": "safety_brand_focus_grounded_promo",
            "scenario_tags": ["safety_matrix", "single_field_cta", "tire_brand", "eligible_promo"],
            "messages": messages(
                "185/65R15 po, Quezon City.",
                "Ipinakita ko po ang Michelin, Apollo, at Fronway options.",
                customer_id="safety_brand_user",
            ),
            "v7_state": {
                "background_signals": [
                    fact("tire_size", "185/65R15", "safety_brand_user"),
                    fact("location", "Quezon City", "safety_brand_user"),
                ],
                "product_presentation_history": [presentation],
            },
            "promo_brand_result": {"status": "ok", "brands": ["MICHELIN", "APOLLO", "VREDESTEIN"]},
            "expected": {
                **base_expectations,
                "route": "proactive_followup",
                "focus_field": "tire_brand",
                "required_message_terms": ["MICHELIN", "APOLLO", "FRONWAY", "Buy 3 Get 1 FREE"],
            },
        },
        {
            "case_id": "safety_single_focus_contact",
            "scenario_tags": ["safety_matrix", "single_field_cta", "contact_number"],
            "messages": messages(
                "185/65R15 Michelin po, Quezon City.",
                "Noted po ang tire details ninyo.",
                customer_id="safety_contact_user",
            ),
            "v7_state": {
                "background_signals": [
                    fact("tire_size", "185/65R15", "safety_contact_user"),
                    fact("location", "Quezon City", "safety_contact_user"),
                    fact("required_brands", ["MICHELIN"], "safety_contact_user"),
                ]
            },
            "expected": {**base_expectations, "route": "proactive_followup", "focus_field": "contact_number"},
        },
        {
            "case_id": "safety_second_cadence_brand_to_location",
            "scenario_tags": ["safety_matrix", "focus_rotation", "second_cadence"],
            "messages": messages("185/65R15 po.", "May Michelin, Apollo, at Fronway options po.", customer_id="safety_rotation_user"),
            "request_time": "2026-07-15 21:00:00",
            "cadence": "second",
            "v7_state": {
                "background_signals": [fact("tire_size", "185/65R15", "safety_rotation_user")],
                "product_presentation_history": [presentation],
                "followup": {
                    "version": 2,
                    "attempts": [
                        {
                            "attempt_id": "safety_rotation_first",
                            "conversation_anchor_id": "safety_rotation_user",
                            "cadence": "first",
                            "route": "proactive_followup",
                            "action": "send",
                            "stance": "active",
                            "focus_field": "tire_brand",
                            "status": "sent",
                            "created_at": "2026-07-15 10:00:00",
                            "updated_at": "2026-07-15 10:00:00",
                        }
                    ],
                },
            },
            "expected": {**base_expectations, "route": "proactive_followup", "focus_field": "location"},
        },
        {
            "case_id": "safety_ineligible_bfg_promo",
            "scenario_tags": ["safety_matrix", "ineligible_promo", "bf_goodrich"],
            "messages": messages(
                "265/70R16 BFGoodrich po.",
                "May BFGoodrich option po na ipinakita.",
                customer_id="safety_bfg_user",
            ),
            "v7_state": {
                "background_signals": [
                    fact("tire_size", "265/70R16", "safety_bfg_user"),
                    fact("required_brands", ["BFGOODRICH"], "safety_bfg_user"),
                ],
                "product_presentation_history": [
                    {
                        **presentation,
                        "presentation_ref": "safety_bfg_presentation",
                        "cards": [
                            {
                                "card_ref": "safety_bfg",
                                "item_ref": "safety_item_bfg",
                                "brand": "BFGOODRICH",
                                "tire_size": "265/70R16",
                                "promo_savings_line": "Buy 3 Get 1 FREE",
                            }
                        ],
                    }
                ],
            },
            "promo_brand_result": {"status": "ok", "brands": ["MICHELIN", "APOLLO", "VREDESTEIN"]},
            "expected": {**base_expectations, "route": "proactive_followup", "forbidden_message_terms": ["Buy 3 Get 1 FREE"]},
        },
        {
            "case_id": "safety_customer_brand_preference",
            "scenario_tags": ["safety_matrix", "customer_preference"],
            "messages": messages("Yokohama po preferred ko.", "Noted po ang preference ninyo.", customer_id="safety_pref_user"),
            "v7_state": {"background_signals": [fact("required_brands", ["YOKOHAMA"], "safety_pref_user")]},
            "expected": {**base_expectations, "route": "proactive_followup", "forbidden_focus_fields": ["tire_brand"]},
        },
        {
            "case_id": "safety_deferred_interest",
            "scenario_tags": ["safety_matrix", "deferred_intent"],
            "messages": messages(
                "None pa po, matagal pa. Just an inquiry lang po.",
                "No problem po, noted.",
                customer_id="safety_defer_user",
            ),
            "expected": {**base_expectations, "route": "proactive_followup", "action": "defer"},
        },
        {
            "case_id": "safety_closed_interest",
            "scenario_tags": ["safety_matrix", "closed_intent"],
            "messages": messages("Not interested na po, nakabili na ako.", "Noted po.", customer_id="safety_closed_user"),
            "expected": {**base_expectations, "route": "proactive_followup", "action": "suppress"},
        },
        {
            "case_id": "safety_stop_chatbot",
            "scenario_tags": ["safety_matrix", "stop_tag", "stop_chatbot"],
            "messages": messages("185/65R15 po.", "May options po tayo.", customer_id="safety_stop_chatbot_user"),
            "profile_fields": {"tags": [{"name": "Stop Chatbot"}]},
            "expected": {**base_expectations, "action": "suppress", "reason": "stop_tag:stop_chatbot", "model_calls": 0},
        },
        {
            "case_id": "safety_stop_followup",
            "scenario_tags": ["safety_matrix", "stop_tag", "stop_followup"],
            "messages": messages("185/65R15 po.", "May options po tayo.", customer_id="safety_stop_followup_user"),
            "profile_fields": {"tags": [{"name": "Stop Followup"}]},
            "expected": {**base_expectations, "action": "suppress", "reason": "stop_tag:stop_followup", "model_calls": 0},
        },
        {
            "case_id": "safety_human_takeover",
            "scenario_tags": ["safety_matrix", "human_takeover"],
            "messages": [
                {
                    "role": "user",
                    "content": "185/65R15 po.",
                    "datetime": "2026-07-15 08:58:00",
                    "message_id": "safety_human_user",
                },
                {
                    "role": "human_agent",
                    "content": "Ako na po ang mag-assist dito.",
                    "datetime": "2026-07-15 09:00:00",
                    "message_id": "safety_human_agent",
                },
            ],
            "expected": {
                **base_expectations,
                "action": "suppress",
                "reason": "human_agent_message_after_latest_customer",
                "model_calls": 0,
            },
        },
        {
            "case_id": "safety_customer_last_recovery",
            "scenario_tags": ["safety_matrix", "customer_turn_recovery"],
            "messages": [
                {
                    "role": "assistant",
                    "content": "May options po tayo.",
                    "datetime": "2026-07-15 08:58:00",
                    "message_id": "safety_recovery_assistant",
                },
                {
                    "role": "user",
                    "content": "Available pa po?",
                    "datetime": "2026-07-15 09:00:00",
                    "message_id": "safety_recovery_user",
                },
            ],
            "expected": {**base_expectations, "route": "customer_turn_recovery", "action": "recover", "model_calls": 0},
        },
        {
            "case_id": "safety_completed_order",
            "scenario_tags": ["safety_matrix", "completion_gate"],
            "messages": messages("Proceed po.", "Placed na po ang order ninyo.", customer_id="safety_order_user"),
            "v7_state": {
                "latest_submitted_order_context": {
                    "order_id": "order_redacted",
                    "order_payload_ref": "order_payload_redacted",
                    "submitted_at": "2026-07-15 08:59:00",
                }
            },
            "expected": {**base_expectations, "action": "suppress", "reason": "conversation_already_converted", "model_calls": 0},
        },
        {
            "case_id": "safety_motorcycle_domain",
            "scenario_tags": ["safety_matrix", "motorcycle", "unresolved_domain"],
            "messages": messages(
                "Dunlop Roadsmart IV motorcycle tire po.",
                "Checking options po.",
                customer_id="safety_motorcycle_user",
            ),
            "expected": {**base_expectations, "action": "suppress", "reason": "unsupported_or_unresolved_domain", "model_calls": 0},
        },
    ]
    for case in cases:
        case.setdefault("request_time", "2026-07-15 10:00:00")
        case.setdefault("cadence", "first")
        case.setdefault("expected_invariants", list(base_expectations))
    return cases


def _load_bq_json(path: Path) -> List[Dict[str, Any]]:
    raw = path.read_text(encoding="utf-8-sig")
    # bq.cmd emits non-standard eight-digit \U escapes on Windows.
    raw = re.sub(r"\\U[0-9A-Fa-f]{8}", "", raw)
    payload = json.loads(raw)
    return [dict(item) for item in payload if isinstance(item, dict)]


def _redact_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"(?:https?://|www\.)\S+", "[url]", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[email]", text)
    text = re.sub(r"(?<!\d)(?:\+?63|0)9\d{9}(?!\d)", "[contact_number]", text)
    text = re.sub(r"\b(?:CO|ORD|ORDER)[- ]?\d{4,}\b", "[order_ref]", text, flags=re.IGNORECASE)
    text = re.sub(r"(?i)\b(?:hi|hello)\s+[^!\n]{1,60}!", "Hi po!", text)
    return " ".join(text.split())[:1200]


def _message_id(value: Any) -> str:
    return "m_" + hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:12]


def _scenario_tags(messages: List[Dict[str, Any]]) -> List[str]:
    text = " ".join(str(item.get("content") or "") for item in messages).casefold()
    tags = ["july_live_transcript", "assistant_last"]
    if any(term in text for term in ("just an inquiry", "matagal", "not yet", "future pa")):
        tags.append("deferred_intent")
    if "bfgo" in text:
        tags.append("bf_goodrich")
    if "buy 3 get 1" in text:
        tags.append("promo_evidence")
    if "motorcycle" in text or "roadsmart" in text:
        tags.append("motorcycle")
    if "tire size" in text or re.search(r"\b\d{3}/\d{2}r\d{2}\b", text):
        tags.append("tire_size")
    if "city" in text or "barangay" in text or "location" in text:
        tags.append("location")
    if sum(term in text for term in ("tire size", "car model", "city", "barangay", "brand", "contact number")) >= 2:
        tags.append("multi_field_risk")
    return tags


def _live_case(row: Dict[str, Any], index: int) -> Dict[str, Any]:
    raw_messages = [dict(item) for item in row.get("messages") or [] if isinstance(item, dict)]
    raw_messages.sort(key=lambda item: (str(item.get("datetime") or ""), int(item.get("sort_id") or 0)))
    messages = []
    for message in raw_messages[-8:]:
        content = _redact_text(message.get("text_content"))
        if not content:
            continue
        messages.append(
            {
                "role": str(message.get("role") or ""),
                "content": content,
                "datetime": str(message.get("datetime") or ""),
                "message_id": _message_id(message.get("message_id")),
            }
        )
    return {
        "case_id": f"july_live_{index:03d}",
        "source_user_key": str(row.get("user_key") or "")[:16],
        "scenario_tags": _scenario_tags(messages),
        "messages": messages,
        "expected_invariants": [
            "at_most_one_model_call",
            "at_most_one_focus_field",
            "no_unsupported_commercial_claim",
            "respect_customer_preference_and_stance",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-count", type=int, default=80)
    args = parser.parse_args()

    safety_cases = _safety_cases()
    required_cases = [*deepcopy_cases(ROLLED_BACK_CASES), *deepcopy_cases(safety_cases)]
    requested = max(len(required_cases), int(args.case_count))
    live_needed = requested - len(required_cases)
    rows = _load_bq_json(args.input)
    live_cases = [_live_case(row, index + 1) for index, row in enumerate(rows[:live_needed])]
    live_cases = [case for case in live_cases if len(case["messages"]) >= 2]
    if len(live_cases) < live_needed:
        raise SystemExit(f"insufficient redacted live cases: need={live_needed} actual={len(live_cases)}")

    cases = [*required_cases, *live_cases[:live_needed]]
    for case in cases[: len(ROLLED_BACK_CASES)]:
        case.setdefault(
            "expected_invariants",
            [
                "at_most_one_model_call",
                "at_most_one_focus_field",
                "no_unsupported_commercial_claim",
                "respect_customer_preference_and_stance",
            ],
        )
    output = {
        "schema_version": 1,
        "date_scope": {"start": "2026-07-01", "end_exclusive": "2026-07-21", "timezone": "Asia/Manila"},
        "source": "bounded_manychat_data.messages_export_plus_rolled_back_incidents_and_redacted_safety_matrix",
        "privacy": "hashed user/message identifiers; contact numbers, emails, URLs, and order refs redacted",
        "case_count": len(cases),
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(args.output.as_posix())


def deepcopy_cases(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return json.loads(json.dumps(cases))


if __name__ == "__main__":
    main()
