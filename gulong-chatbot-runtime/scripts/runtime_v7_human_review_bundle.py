"""Build minimized human-review bundles from Runtime V7 probe artifacts.

The script is deliberately offline. It consumes existing live-pack scenario
JSON or API debug envelopes, preserves only customer-visible output plus compact
telemetry, redacts phone numbers and emails, and leaves tone/naturalness
decisions blank for an orchestrator. Inputs still need to be approved or
redacted because free-form names and addresses cannot be removed reliably.
Mechanical findings cover structure and explicit runtime contract signals only;
they never infer response quality from phrases, emoji, length, or punctuation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime_v7.channel_renderer import render_turn_for_channel  # noqa: E402


SCHEMA_VERSION = "runtime_v7_human_review_bundle_v1"
RATINGS = {"pass", "concern", "fail"}
OVERALL_DECISIONS = {"pass", "revise", "reject"}
REVIEW_DIMENSIONS = (
    "understands_customer",
    "natural_language",
    "directness",
    "grounding",
    "progression",
    "presentation",
    "consistency",
)
CHOICE_PREFIXES = {
    "bc1": "price_category",
    "lc1": "location",
    "pc1": "promo",
    "pm1": "payment_method",
    "po1": "payment_option",
    "ps1": "product",
    "ss1": "schedule",
}
CUSTOMER_VISIBLE_KEYS = {
    "type",
    "text",
    "title",
    "subtitle",
    "caption",
    "alt",
    "url",
    "image_url",
    "image_ref",
    "image_aspect_ratio",
    "payload",
    "action",
    "actions",
    "field_name",
    "target",
    "name",
    "label",
    "value",
    "buttons",
    "quick_replies",
    "items",
    "elements",
    "cards",
    "rows",
    "content",
}
PRESENTATION_KEYS = {
    "brand",
    "can_accept_payment_proof",
    "card_ref",
    "card_refs",
    "cards",
    "catalog_version_id",
    "choice_ref",
    "choice_type",
    "choices",
    "deal_price_line",
    "expected_amount",
    "expected_amount_text",
    "explicit_redisplay",
    "image_url",
    "inclusions",
    "installment_text",
    "item_ref",
    "label",
    "level",
    "payment_instruction_type",
    "payment_link_url",
    "payment_stage",
    "position",
    "presentation_ref",
    "price_list_included",
    "primary_method",
    "product_id",
    "pricing_facts",
    "promo_ids",
    "promo_label",
    "promo_refs",
    "promo_savings_line",
    "quantity",
    "qr_image_url",
    "renderer_variant",
    "show_count",
    "sku_model",
    "slug",
    "subtitle",
    "surface_type",
    "tire_protection_plan",
    "tire_size",
    "title",
    "tool",
    "trigger_mode",
    "warranty",
}
PHONE_RE = re.compile(r"(?<!\d)(?:\+?63|0)?[ .-]*9(?:[ .-]*\d){9}(?!\d)")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
URL_WITH_QUERY_RE = re.compile(r"(https?://[^\s?#]+)(?:\?[^\s#]*)?(?:#[^\s]*)?", re.IGNORECASE)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, help="Scenario artifact JSON, API debug JSON, summary JSON, or directory.")
    parser.add_argument("--pack", type=Path, help="Optional scenario pack used to attach review metadata and hard-fact checks.")
    parser.add_argument("--out-dir", type=Path, default=Path("tmp/runtime_v7_human_review_bundle"))
    parser.add_argument("--validate-pack", type=Path, help="Validate a pack without model, network, or tool calls.")
    parser.add_argument("--validate-review", type=Path, help="Validate one completed review JSON and exit.")
    return parser.parse_args()


def validate_pack(pack: Mapping[str, Any]) -> List[str]:
    """Return pack-schema errors without judging the intended response."""

    errors: List[str] = []
    scenarios = [item for item in pack.get("scenarios") or [] if isinstance(item, Mapping)]
    if not scenarios:
        return ["pack_has_no_scenarios"]
    ids = [str(item.get("id") or "").strip() for item in scenarios]
    if any(not value for value in ids):
        errors.append("scenario_id_missing")
    if len(set(ids)) != len(ids):
        errors.append("scenario_ids_not_unique")
    allowed_provenance = {
        "paraphrased_bq_pattern",
        "user_requested_scenario",
        "human_authored_variant",
        "synthetic_negative_control",
        "redacted_transcript",
    }
    for scenario in scenarios:
        scenario_id = str(scenario.get("id") or "scenario")
        if not str(scenario.get("case_family_id") or "").strip():
            errors.append(f"{scenario_id}:case_family_id_missing")
        if str(scenario.get("input_provenance") or "") not in allowed_provenance:
            errors.append(f"{scenario_id}:input_provenance_invalid")
        if not list(scenario.get("turns") or []):
            errors.append(f"{scenario_id}:turns_missing")
        if not list(scenario.get("hard_fact_checks") or []):
            errors.append(f"{scenario_id}:hard_fact_checks_missing")
        if "expected_response" in scenario or "required_message_terms" in scenario:
            errors.append(f"{scenario_id}:scripted_response_expectation_forbidden")
    return errors


def load_probe_artifacts(path: Path) -> List[Dict[str, Any]]:
    """Load supported artifacts deterministically without recursive log scans."""

    if path.is_dir():
        rows: List[Dict[str, Any]] = []
        for child in sorted(path.glob("*.json")):
            if child.name in {"summary.json", "review_summary.json"}:
                continue
            payload = _read_json(child)
            if _is_supported_artifact(payload):
                payload["_source_path"] = str(child.resolve())
                rows.append(payload)
        return rows

    payload = _read_json(path)
    if isinstance(payload.get("rows"), list):
        rows = []
        for item in payload.get("rows") or []:
            artifact_path = ((item or {}).get("artifact_paths") or {}).get("json") if isinstance(item, Mapping) else None
            if artifact_path and Path(str(artifact_path)).exists():
                child = _read_json(Path(str(artifact_path)))
                child["_source_path"] = str(Path(str(artifact_path)).resolve())
                rows.append(child)
        if rows:
            return rows
    if not _is_supported_artifact(payload):
        raise ValueError(f"Unsupported Runtime V7 artifact: {path}")
    payload["_source_path"] = str(path.resolve())
    return [payload]


def build_review_unit(
    payload: Mapping[str, Any],
    *,
    scenario_metadata: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build one sanitized review unit from a live-pack or API debug artifact."""

    scenario = dict(scenario_metadata or {})
    scenario.update(dict(payload.get("scenario") or {}))
    scenario_id = str(payload.get("scenario_id") or scenario.get("id") or _artifact_identity(payload))
    turns, evidence_strength = _turns_and_evidence(payload)
    review_turns = [render_turn_evidence(turn, evidence_strength=evidence_strength) for turn in turns]
    findings = [item for turn in review_turns for item in turn.get("mechanical_findings") or []]
    blocking = [item for item in findings if item.get("blocking") is True]
    hard_checks = [str(value) for value in scenario.get("hard_fact_checks") or [] if str(value).strip()]
    review = {
        "hard_fact_reviews": [
            {"check": value, "rating": None, "rationale": ""}
            for value in hard_checks
        ],
        "dimensions": {
            dimension: {"rating": None, "rationale": ""}
            for dimension in REVIEW_DIMENSIONS
        },
        "overall": {"decision": None, "rationale": ""},
        "orchestrator_review_required": True,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": scenario_id,
        "case_family_id": scenario.get("case_family_id"),
        "title": scenario.get("title"),
        "category": scenario.get("category"),
        "posture": scenario.get("posture"),
        "tags": list(scenario.get("tags") or []),
        "input_provenance": scenario.get("input_provenance"),
        "source_artifact": Path(str(payload.get("_source_path") or "")).name,
        "evidence_strength": evidence_strength,
        "evidence_limit": _evidence_limit(evidence_strength),
        "turns": review_turns,
        "mechanical_summary": {
            "status": "blocked" if blocking else "clear",
            "finding_count": len(findings),
            "blocking_finding_count": len(blocking),
            "findings": findings,
        },
        "declared_hard_fact_checks": hard_checks,
        "review_focus": list(scenario.get("review_focus") or []),
        "review": review,
    }


def render_turn_evidence(turn_envelope: Mapping[str, Any], *, evidence_strength: str) -> Dict[str, Any]:
    """Return allowlisted visible evidence and compact telemetry for one turn."""

    turn = dict(turn_envelope.get("turn_record") or turn_envelope.get("turn") or turn_envelope)
    rendered = turn_envelope.get("rendered") if isinstance(turn_envelope.get("rendered"), Mapping) else None
    if rendered is None:
        reconstructed = render_turn_for_channel(turn)
        rendered = {
            "response": reconstructed.response,
            "content_messages": reconstructed.content_messages,
            "images": reconstructed.images,
            "payment": reconstructed.payment,
            "text": reconstructed.text,
            "promo_presentation": reconstructed.promo_presentation,
            "choice_presentations": reconstructed.choice_presentations,
            "product_presentations": reconstructed.product_presentations,
            "service_policy_note_ids": reconstructed.service_policy_note_ids,
        }
    visible = {
        "response": _sanitize_visible(rendered.get("response") or {}),
        "content_messages": _sanitize_visible(rendered.get("content_messages") or []),
        "images": _sanitize_visible(rendered.get("images") or []),
        "text": _redact_text(str(rendered.get("text") or "")),
    }
    messages = visible["content_messages"] if isinstance(visible["content_messages"], list) else []
    findings = _mechanical_findings(turn, messages)
    return {
        "turn_id": turn.get("turn_id"),
        "user_message": _redact_text(str(turn.get("user_message") or _nested(turn_envelope, "request", "user_text") or "")),
        "evidence_strength": evidence_strength,
        "visible": visible,
        "presentation_evidence": _presentation_evidence(rendered),
        "telemetry": _compact_telemetry(turn, turn_envelope),
        "mechanical_findings": findings,
    }


def validate_completed_review(review_unit: Mapping[str, Any]) -> List[str]:
    """Validate orchestrator-entered judgments without making the judgments."""

    errors: List[str] = []
    review = review_unit.get("review") if isinstance(review_unit.get("review"), Mapping) else review_unit
    hard_reviews = review.get("hard_fact_reviews") if isinstance(review, Mapping) else []
    declared_checks = [str(value) for value in review_unit.get("declared_hard_fact_checks") or []]
    submitted_checks = [str((item or {}).get("check") or "") for item in hard_reviews or []]
    if declared_checks and submitted_checks != declared_checks:
        errors.append("hard_fact_reviews:declared_checks_changed_or_missing")
    for index, item in enumerate(hard_reviews or []):
        rating = str((item or {}).get("rating") or "")
        rationale = str((item or {}).get("rationale") or "").strip()
        if rating not in {"pass", "fail", "not_applicable"}:
            errors.append(f"hard_fact_reviews[{index}]:rating_required")
        if rating in {"fail", "not_applicable"} and not rationale:
            errors.append(f"hard_fact_reviews[{index}]:rationale_required")
    dimensions = review.get("dimensions") if isinstance(review, Mapping) else {}
    for dimension in REVIEW_DIMENSIONS:
        item = dimensions.get(dimension) if isinstance(dimensions, Mapping) else None
        rating = str((item or {}).get("rating") or "")
        rationale = str((item or {}).get("rationale") or "").strip()
        if rating not in RATINGS:
            errors.append(f"dimensions.{dimension}:rating_required")
        if rating in {"concern", "fail"} and not rationale:
            errors.append(f"dimensions.{dimension}:rationale_required")
    overall = review.get("overall") if isinstance(review, Mapping) else {}
    decision = str((overall or {}).get("decision") or "")
    rationale = str((overall or {}).get("rationale") or "").strip()
    if decision not in OVERALL_DECISIONS:
        errors.append("overall.decision_required")
    if not rationale:
        errors.append("overall.rationale_required")
    mechanical = review_unit.get("mechanical_summary") if isinstance(review_unit.get("mechanical_summary"), Mapping) else {}
    if decision == "pass" and int(mechanical.get("blocking_finding_count") or 0) > 0:
        errors.append("overall.pass_not_allowed_with_mechanical_blocker")
    if decision == "pass" and any(str((item or {}).get("rating") or "") == "fail" for item in hard_reviews or []):
        errors.append("overall.pass_not_allowed_with_hard_fact_failure")
    if decision == "pass" and any(
        str((item or {}).get("rating") or "") == "fail"
        for item in (dimensions.values() if isinstance(dimensions, Mapping) else [])
    ):
        errors.append("overall.pass_not_allowed_with_dimension_failure")
    return errors


def write_review_bundle(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    out_dir: Path,
    scenario_map: Mapping[str, Mapping[str, Any]] | None = None,
) -> Dict[str, str]:
    """Write one UTF-8 review bundle and return summary paths."""

    run_dir = out_dir / f"review_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=False)
    units: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []
    for payload in artifacts:
        scenario_id = str(payload.get("scenario_id") or (payload.get("scenario") or {}).get("id") or _artifact_identity(payload))
        unit = build_review_unit(payload, scenario_metadata=(scenario_map or {}).get(scenario_id))
        safe_id = _safe_id(unit["scenario_id"])
        json_path = run_dir / f"{safe_id}.review.json"
        md_path = run_dir / f"{safe_id}.review.md"
        json_path.write_text(json.dumps(unit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(_render_review_markdown(unit), encoding="utf-8")
        units.append(unit)
        rows.append(
            {
                "scenario_id": unit["scenario_id"],
                "case_family_id": unit.get("case_family_id"),
                "evidence_strength": unit["evidence_strength"],
                "mechanical_status": unit["mechanical_summary"]["status"],
                "blocking_findings": unit["mechanical_summary"]["blocking_finding_count"],
                "json": json_path.name,
                "markdown": md_path.name,
            }
        )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scenario_count": len(units),
        "mechanically_blocked": sum(1 for unit in units if unit["mechanical_summary"]["status"] == "blocked"),
        "human_reviews_completed": 0,
        "rows": rows,
    }
    summary_json = run_dir / "review_summary.json"
    summary_md = run_dir / "review_summary.md"
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_md.write_text(_render_summary_markdown(summary), encoding="utf-8")
    return {"summary_json": str(summary_json.resolve()), "summary_markdown": str(summary_md.resolve())}


def _turns_and_evidence(payload: Mapping[str, Any]) -> tuple[List[Dict[str, Any]], str]:
    runtime_payload = payload.get("runtime_payload") if isinstance(payload.get("runtime_payload"), Mapping) else {}
    live_turns = [dict(item) for item in runtime_payload.get("turns") or [] if isinstance(item, Mapping)]
    if live_turns:
        return live_turns, "structural_only"
    debug = payload.get("debug_payload") if isinstance(payload.get("debug_payload"), Mapping) else payload
    turn = debug.get("turn_record") if isinstance(debug.get("turn_record"), Mapping) else {}
    if turn:
        delivery = debug.get("delivery_result") if isinstance(debug.get("delivery_result"), Mapping) else {}
        request = debug.get("request") if isinstance(debug.get("request"), Mapping) else {}
        envelope: Dict[str, Any] = {
            "turn_record": dict(turn),
            "request": dict(request),
            "delivery_result": dict(delivery),
        }
        if isinstance(debug.get("rendered"), Mapping):
            envelope["rendered"] = dict(debug.get("rendered") or {})
        return [envelope], _evidence_strength(request, delivery)

    compact_debug = payload.get("debug") if isinstance(payload.get("debug"), Mapping) else {}
    has_customer_payload = isinstance(payload.get("response"), Mapping) or isinstance(payload.get("content_messages"), list)
    if not has_customer_payload:
        raise ValueError("Artifact contains neither a Runtime V7 turn record nor an API customer payload")
    scenario = payload.get("scenario") if isinstance(payload.get("scenario"), Mapping) else {}
    scenario_turns = [str(value) for value in scenario.get("turns") or [] if str(value).strip()]
    user_message = str(
        payload.get("user_message")
        or payload.get("user_text")
        or _nested(payload, "request", "user_text")
        or (scenario_turns[-1] if scenario_turns else "")
    )
    compact_turn = {
        "turn_id": compact_debug.get("turn_id"),
        "user_message": user_message,
        "llm_usage_summary": compact_debug.get("llm_usage_summary") or {},
        "context_cache_summary": compact_debug.get("context_cache_summary") or {},
        "tool_results": compact_debug.get("tool_calls") or [],
        "response_guard_events": compact_debug.get("response_guard_events") or [],
        "final_composer": {"status": compact_debug.get("final_composer_status")},
    }
    rendered = {
        key: payload.get(key)
        for key in (
            "response",
            "content_messages",
            "images",
            "payment",
            "promo_presentation",
            "choice_presentations",
            "product_presentations",
        )
        if key in payload
    }
    delivery = payload.get("delivery_result") if isinstance(payload.get("delivery_result"), Mapping) else {}
    request = payload.get("request") if isinstance(payload.get("request"), Mapping) else {}
    return [
        {
            "turn_record": compact_turn,
            "rendered": rendered,
            "request": dict(request),
            "delivery_result": dict(delivery),
        }
    ], _evidence_strength(request, delivery)


def _evidence_strength(request: Mapping[str, Any], delivery: Mapping[str, Any]) -> str:
    """Classify what the artifact proves without inferring Messenger receipt."""

    status = str(delivery.get("status") or "").lower()
    mode = str(request.get("delivery_mode") or delivery.get("delivery_mode") or "").lower()
    reason = str(delivery.get("reason") or "").lower()
    if mode == "return_only" or reason == "return_only":
        return "customer_path_return_only"
    elif status == "success":
        return "manychat_api_send_success"
    return "structural_only"


def _compact_telemetry(turn: Mapping[str, Any], envelope: Mapping[str, Any]) -> Dict[str, Any]:
    calls = []
    for call in turn.get("llm_calls") or []:
        if not isinstance(call, Mapping):
            continue
        output = call.get("model_output") if isinstance(call.get("model_output"), Mapping) else {}
        usage = call.get("usage_summary") if isinstance(call.get("usage_summary"), Mapping) else output.get("usage") or {}
        calls.append(
            {
                "component": call.get("component") or ("final_composer" if call.get("response_format") else "main_tool_loop"),
                "round": call.get("round"),
                "model": output.get("model"),
                "latency_ms": usage.get("latency_ms") or output.get("latency_ms"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
                "uncached_prompt_tokens": usage.get("uncached_prompt_tokens"),
                "reasoning_tokens": usage.get("reasoning_tokens"),
                "tool_call_count": len(call.get("tool_calls") or []),
            }
        )
    tools = []
    for item in turn.get("tool_results") or []:
        if not isinstance(item, Mapping):
            continue
        result = item.get("result") if isinstance(item.get("result"), Mapping) else item.get("full_result") or {}
        tools.append(
            {
                "name": item.get("name"),
                "status": (result.get("status") if isinstance(result, Mapping) else None) or item.get("status"),
                "latency_ms": item.get("latency_ms") or (result.get("latency_ms") if isinstance(result, Mapping) else None),
            }
        )
    plan = turn.get("customer_turn_plan") if isinstance(turn.get("customer_turn_plan"), Mapping) else {}
    composer = turn.get("final_composer") if isinstance(turn.get("final_composer"), Mapping) else {}
    delivery = envelope.get("delivery_result") if isinstance(envelope.get("delivery_result"), Mapping) else {}
    return {
        "llm_usage_summary": _allowlisted_metrics(turn.get("llm_usage_summary") or {}),
        "context_cache_summary": _allowlisted_metrics(turn.get("context_cache_summary") or {}),
        "model_calls": calls,
        "tools": tools,
        "composer": {key: composer.get(key) for key in ("status", "reason", "repair_count") if key in composer},
        "decision": {
            "current_layer": plan.get("current_decision_layer"),
            "next_layer": plan.get("next_decision_layer"),
            "already_satisfied_fields": list(plan.get("already_satisfied_fields") or []),
            "required_surfaces": _surface_types(plan.get("required_surfaces") or []),
            "optional_surfaces": _surface_types(plan.get("optional_surfaces") or []),
        },
        "guard_summary": {
            "contract_violation_count": len(composer.get("contract_violations") or turn.get("contract_violations") or []),
            "response_guard_event_types": [
                str(item.get("type") or "guard_event")
                for item in turn.get("response_guard_events") or []
                if isinstance(item, Mapping)
            ][:20],
        },
        "delivery": {key: delivery.get(key) for key in ("status", "reason", "delivery_mode") if key in delivery},
    }


def _mechanical_findings(turn: Mapping[str, Any], messages: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    if not str(turn.get("user_message") or "").strip():
        findings.append(_finding("missing_customer_input_evidence", "turn_record.user_message", blocking=True))
    if not messages:
        findings.append(_finding("missing_customer_visible_messages", "renderer", blocking=True))
    serialized = json.dumps(messages, ensure_ascii=False)
    tokens = re.findall(r"\b(?:bc1|lc1|pc1|pm1|po1|ps1|ss1)\|[^\s\"']+", serialized)
    duplicates = sorted({token for token in tokens if tokens.count(token) > 1})
    if duplicates:
        findings.append(_finding("duplicate_choice_tokens", "rendered.content_messages", blocking=True, details=duplicates))
    layers = sorted({CHOICE_PREFIXES[token.split("|", 1)[0]] for token in tokens})
    supporting_promo_pair = set(layers) == {"product", "promo"}
    if len(layers) > 1 and not supporting_promo_pair:
        findings.append(_finding("multiple_active_choice_layers", "rendered.content_messages", blocking=True, details=layers))
    for index, message in enumerate(messages):
        if index > 0 and message == messages[index - 1]:
            findings.append(_finding("consecutive_duplicate_message", f"rendered.content_messages[{index}]", blocking=True))
        if str(message.get("type") or "") == "image":
            url = str(message.get("url") or message.get("image_url") or "")
            if url and not url.startswith("https://"):
                findings.append(_finding("non_https_customer_image", f"rendered.content_messages[{index}]", blocking=True))
    composer = turn.get("final_composer") if isinstance(turn.get("final_composer"), Mapping) else {}
    violations = composer.get("contract_violations") or turn.get("contract_violations") or []
    if violations:
        findings.append(
            _finding(
                "recorded_contract_violation",
                "turn_record.final_composer",
                blocking=True,
                details=_violation_codes(violations),
            )
        )
    for event in turn.get("response_guard_events") or []:
        if not isinstance(event, Mapping):
            continue
        event_type = str(event.get("type") or "")
        if "violation" in event_type or event_type in {"unknown_render_surface", "unsupported_claim"}:
            findings.append(_finding(event_type or "response_guard_violation", "turn_record.response_guard_events", blocking=True))
    return findings


def _surface_types(values: Any) -> List[str]:
    """Return surface identifiers without copying full plan payloads."""

    output: List[str] = []
    for value in values if isinstance(values, list) else []:
        if isinstance(value, Mapping):
            name = value.get("surface_type") or value.get("type") or value.get("tool")
        else:
            name = value
        if str(name or "").strip():
            output.append(str(name).strip()[:80])
    return output[:20]


def _finding(code: str, source: str, *, blocking: bool, details: Any = None) -> Dict[str, Any]:
    return {"code": code, "source": source, "blocking": blocking, "details": details}


def _sanitize_visible(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, list):
        return [_sanitize_visible(item) for item in value]
    if isinstance(value, Mapping):
        sanitized: Dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if name not in CUSTOMER_VISIBLE_KEYS and not re.fullmatch(r"bubble\d+", name):
                continue
            if name == "target" and item:
                sanitized[name] = "[configured]"
            elif name in {"url", "image_url"}:
                sanitized[name] = _redact_text(str(item or ""))
            else:
                sanitized[name] = _sanitize_visible(item)
        return sanitized
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)


def _redact_text(value: str) -> str:
    without_url_secrets = URL_WITH_QUERY_RE.sub(r"\1", value)
    return EMAIL_RE.sub("[redacted-email]", PHONE_RE.sub("[redacted-phone]", without_url_secrets))


def _presentation_evidence(rendered: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep renderer-owned presentation facts needed for complete-turn review."""

    return {
        "promo": _sanitize_presentation(rendered.get("promo_presentation") or {}),
        "choices": _sanitize_presentation(rendered.get("choice_presentations") or []),
        "products": _sanitize_presentation(rendered.get("product_presentations") or []),
        "payment": _sanitize_presentation(rendered.get("payment") or {}),
    }


def _sanitize_presentation(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, list):
        return [_sanitize_presentation(item) for item in value]
    if isinstance(value, Mapping):
        sanitized: Dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if name not in PRESENTATION_KEYS:
                continue
            sanitized[name] = _sanitize_fact_map(item) if name == "pricing_facts" else _sanitize_presentation(item)
        return sanitized
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)


def _sanitize_fact_map(value: Any) -> Any:
    """Keep trusted structured pricing leaves while redacting strings."""

    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, list):
        return [_sanitize_fact_map(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _sanitize_fact_map(item) for key, item in value.items()}
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)


def _allowlisted_metrics(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    allowed = {
        "llm_call_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cache_read_input_tokens",
        "uncached_prompt_tokens",
        "cache_hit_rate",
        "reasoning_tokens",
        "latency_ms",
        "explicit_cache_enabled_call_count",
        "explicit_cache_disabled_call_count",
        "cache_guard_event_count",
    }
    return {key: value.get(key) for key in allowed if key in value}


def _render_review_markdown(unit: Mapping[str, Any]) -> str:
    lines = [
        f"# {unit.get('scenario_id')}: {unit.get('title') or ''}",
        "",
        f"Evidence: `{unit.get('evidence_strength')}`",
        f"Limit: {unit.get('evidence_limit')}",
        f"Mechanical status: `{(unit.get('mechanical_summary') or {}).get('status')}`",
        "",
    ]
    for index, turn in enumerate(unit.get("turns") or [], start=1):
        lines.extend(
            [
                f"## Turn {index}",
                "",
                f"Customer: {turn.get('user_message')}",
                "",
                "### Customer-visible content",
                "```json",
                json.dumps((turn.get("visible") or {}).get("content_messages") or [], ensure_ascii=False, indent=2),
                "```",
                "",
                "### Renderer-owned presentation evidence",
                "```json",
                json.dumps(turn.get("presentation_evidence") or {}, ensure_ascii=False, indent=2),
                "```",
                "",
                "### Compact telemetry",
                "```json",
                json.dumps(turn.get("telemetry") or {}, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    lines.extend(["## Mechanical findings", "```json", json.dumps((unit.get("mechanical_summary") or {}).get("findings") or [], ensure_ascii=False, indent=2), "```", "", "## Orchestrator review"])
    for item in (unit.get("review") or {}).get("hard_fact_reviews") or []:
        lines.append(f"- [ ] Hard fact: {item.get('check')} — rating: ___ — rationale: ___")
    for dimension in REVIEW_DIMENSIONS:
        lines.append(f"- [ ] {dimension}: pass / concern / fail — rationale: ___")
    lines.extend(["", "Overall: pass / revise / reject", "", "Rationale: ___", ""])
    return "\n".join(lines)


def _render_summary_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Runtime V7 Human Review Bundle",
        "",
        f"Scenarios: `{summary.get('scenario_count')}`",
        f"Mechanically blocked: `{summary.get('mechanically_blocked')}`",
        "",
        "| Scenario | Evidence | Mechanical | Blocking | Review artifact |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for row in summary.get("rows") or []:
        lines.append(f"| {row.get('scenario_id')} | {row.get('evidence_strength')} | {row.get('mechanical_status')} | {row.get('blocking_findings')} | {row.get('markdown')} |")
    return "\n".join(lines) + "\n"


def _read_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _is_supported_artifact(payload: Mapping[str, Any]) -> bool:
    return bool(
        _nested(payload, "runtime_payload", "turns")
        or payload.get("turn_record")
        or _nested(payload, "debug_payload", "turn_record")
        or isinstance(payload.get("response"), Mapping)
        or isinstance(payload.get("content_messages"), list)
    )


def _artifact_identity(payload: Mapping[str, Any]) -> str:
    return str(payload.get("trace_id") or _nested(payload, "turn_record", "trace_id") or "runtime_v7_episode")


def _nested(value: Mapping[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _violation_codes(values: Any) -> List[str]:
    """Return codes only; violation bodies may repeat customer or prompt text."""

    if not isinstance(values, list):
        values = [values]
    output: List[str] = []
    for value in values[:20]:
        if isinstance(value, Mapping):
            code = value.get("code") or value.get("type") or value.get("reason")
            output.append(str(code or "recorded_violation")[:80])
        else:
            output.append("recorded_violation")
    return output


def _safe_id(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "scenario")).strip("-") or "scenario"


def _evidence_limit(strength: str) -> str:
    if strength == "manychat_api_send_success":
        return "ManyChat API success is recorded; observed Messenger delivery still requires transcript or controlled-contact evidence."
    if strength == "customer_path_return_only":
        return "Customer-path rendering and state were evaluated without an actual customer send."
    return "Output was reconstructed from a harness turn and is structural-only, not customer-path delivery evidence."


def _scenario_map(pack_path: Path | None) -> Dict[str, Mapping[str, Any]]:
    if not pack_path:
        return {}
    pack = _read_json(pack_path)
    errors = validate_pack(pack)
    if errors:
        raise ValueError("Invalid scenario pack: " + "; ".join(errors))
    return {str(item.get("id")): item for item in pack.get("scenarios") or [] if isinstance(item, Mapping)}


def main() -> None:
    """Validate inputs or build a sanitized offline human-review bundle."""
    args = _args()
    if args.validate_pack:
        errors = validate_pack(_read_json(args.validate_pack))
        if errors:
            raise SystemExit("\n".join(errors))
        print(json.dumps({"valid": True, "pack": str(args.validate_pack.resolve())}))
        return
    if args.validate_review:
        errors = validate_completed_review(_read_json(args.validate_review))
        if errors:
            raise SystemExit("\n".join(errors))
        print(json.dumps({"valid": True, "review": str(args.validate_review.resolve())}))
        return
    if not args.input:
        raise SystemExit("--input is required unless --validate-pack or --validate-review is used")
    artifacts = load_probe_artifacts(args.input)
    paths = write_review_bundle(artifacts, out_dir=args.out_dir, scenario_map=_scenario_map(args.pack))
    print(json.dumps(paths, ensure_ascii=False))


if __name__ == "__main__":
    main()
