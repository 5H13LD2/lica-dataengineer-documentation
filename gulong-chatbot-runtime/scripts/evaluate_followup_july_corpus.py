"""Run the July follow-up corpus against the configured production model."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime_v7.followup_v2 import (  # noqa: E402
    build_followup_case,
    build_followup_plan_messages,
    build_followup_plan_response_model,
    followup_stop_reason,
    parse_followup_plan,
    proactive_followup_gate,
    validate_and_render_followup,
)
from runtime_v7.llm_gateway import RuntimeV7LLMGateway, RuntimeV7LLMGatewayConfig  # noqa: E402


KNOWN_BRANDS = (
    "MICHELIN",
    "APOLLO",
    "VREDESTEIN",
    "DEESTONE",
    "FRONWAY",
    "BFGOODRICH",
    "YOKOHAMA",
    "GOODYEAR",
    "DUNLOP",
    "ARIVO",
    "NANKANG",
    "WESTLAKE",
    "LINGLONG",
    "BRIDGESTONE",
    "DURATURN",
    "PETLAS",
    "LAUFENN",
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path("test/fixtures/runtime_v7_followup_july_corpus.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--model", default="")
    return parser.parse_args()


def _signals(messages: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    customer_messages = [item for item in messages if str(item.get("role") or "") == "user"]
    output: List[Dict[str, Any]] = []
    for message in reversed(customer_messages):
        text = str(message.get("content") or "")
        message_id = str(message.get("message_id") or "customer_evidence")
        if not any(item.get("key") == "tire_size" for item in output):
            size_match = re.search(r"\b(\d{3})\s*[/ ]\s*(\d{2})\s*(?:R|r|/|\s)\s*(\d{2})\b", text)
            if size_match:
                output.append(
                    {
                        "key": "tire_size",
                        "value": f"{size_match.group(1)}/{size_match.group(2)}R{size_match.group(3)}",
                        "source": "latest_user_message",
                        "message_id": message_id,
                    }
                )
        if not any(item.get("key") == "required_brands" for item in output):
            upper = text.upper()
            brands = [brand for brand in KNOWN_BRANDS if re.search(rf"\b{re.escape(brand)}\b", upper)]
            if brands:
                output.append(
                    {
                        "key": "required_brands",
                        "value": brands,
                        "source": "latest_user_message",
                        "message_id": message_id,
                    }
                )
    return output


def _request_time(messages: Sequence[Mapping[str, Any]]) -> str:
    latest = str((messages[-1] if messages else {}).get("datetime") or "")
    try:
        parsed = datetime.fromisoformat(latest)
    except ValueError:
        parsed = datetime(2026, 7, 15, 9, 0, 0)
    return (parsed + timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")


def _apply_expected_checks(row: Dict[str, Any], case_row: Mapping[str, Any]) -> Dict[str, Any]:
    expected = case_row.get("expected") if isinstance(case_row.get("expected"), Mapping) else {}
    checks = dict(row.get("checks") or {})
    if expected.get("route"):
        checks["expected_route"] = str(row.get("route") or "") == str(expected.get("route") or "")
    if expected.get("action"):
        checks["expected_action"] = str(row.get("action") or "") == str(expected.get("action") or "")
    if expected.get("focus_field"):
        checks["expected_focus_field"] = str(row.get("focus_field") or "") == str(expected.get("focus_field") or "")
    forbidden_focus = {str(item) for item in expected.get("forbidden_focus_fields") or []}
    if forbidden_focus:
        checks["forbidden_focus_fields"] = str(row.get("focus_field") or "") not in forbidden_focus
    if expected.get("reason"):
        checks["expected_reason"] = str(row.get("reason") or "") == str(expected.get("reason") or "")
    if expected.get("model_calls") is not None:
        checks["expected_model_calls"] = int(row.get("model_calls") or 0) == int(expected.get("model_calls") or 0)
    message = str(row.get("message") or "").casefold()
    required_terms = [str(item).casefold() for item in expected.get("required_message_terms") or []]
    forbidden_terms = [str(item).casefold() for item in expected.get("forbidden_message_terms") or []]
    if required_terms:
        checks["required_message_terms"] = all(term in message for term in required_terms)
    if forbidden_terms:
        checks["forbidden_message_terms"] = not any(term in message for term in forbidden_terms)
    row["checks"] = checks
    return row


def _normalize_messages(case: Mapping[str, Any]) -> List[Dict[str, Any]]:
    output = []
    base = datetime(2026, 7, 15, 8, 0, 0)
    for index, raw in enumerate(case.get("messages") or []):
        if not isinstance(raw, Mapping):
            continue
        output.append(
            {
                "role": str(raw.get("role") or ""),
                "content": str(raw.get("content") or ""),
                "datetime": str(raw.get("datetime") or (base + timedelta(minutes=index)).isoformat()),
                "message_id": str(raw.get("message_id") or f"{case.get('case_id')}_m{index + 1}"),
            }
        )
    return output[-12:]


def _usage(response: Mapping[str, Any]) -> Dict[str, int]:
    usage = response.get("usage") if isinstance(response.get("usage"), Mapping) else {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


def _mentioned_brands(value: Any) -> set[str]:
    text = str(value or "").upper()
    return {brand for brand in KNOWN_BRANDS if re.search(rf"\b{re.escape(brand)}\b", text)}


async def _evaluate_one(
    case_row: Mapping[str, Any],
    *,
    run_index: int,
    gateway: RuntimeV7LLMGateway,
    semaphore: asyncio.Semaphore,
) -> Dict[str, Any]:
    messages = _normalize_messages(case_row)
    request_time = str(case_row.get("request_time") or _request_time(messages))
    v7_state = dict(case_row.get("v7_state") or {})
    v7_state.setdefault("background_signals", _signals(messages))
    profile_fields = dict(case_row.get("profile_fields") or {})
    profile_fields.setdefault("tags", [])
    profile_fields.setdefault("profile_loaded_at", request_time)
    case = build_followup_case(
        request_time=request_time,
        recent_messages=messages,
        v7_state=v7_state,
        profile_fields=profile_fields,
        cadence=str(case_row.get("cadence") or "first"),
        promo_brand_result=dict(
            case_row.get("promo_brand_result")
            or {"status": "ok", "brands": ["MICHELIN", "APOLLO", "VREDESTEIN"]}
        ),
    )
    row: Dict[str, Any] = {
        "case_id": case_row.get("case_id"),
        "run": run_index,
        "route": case.get("route"),
        "scenario_tags": case_row.get("scenario_tags") or [],
        "next_step_candidates": case.get("next_step_candidates") or [],
        "model_calls": 0,
    }
    stop_reason = followup_stop_reason(profile_fields=profile_fields, recent_messages=messages)
    if stop_reason:
        row.update(
            {
                "action": "suppress",
                "reason": stop_reason,
                "validation_status": "not_applicable",
                "checks": {"one_model_call_or_less": True},
            }
        )
        return _apply_expected_checks(row, case_row)
    if case.get("route") == "customer_turn_recovery":
        row.update(
            {
                "action": "recover",
                "validation_status": "not_applicable",
                "checks": {"one_model_call_or_less": True, "recovery_not_proactive": True},
            }
        )
        return _apply_expected_checks(row, case_row)
    gate = proactive_followup_gate(case)
    row["gate"] = gate
    if gate.get("status") != "allow":
        row.update(
            {
                "action": "suppress",
                "reason": gate.get("reason"),
                "validation_status": "not_applicable",
                "checks": {"one_model_call_or_less": True},
            }
        )
        return _apply_expected_checks(row, case_row)

    started = time.perf_counter()
    try:
        async with semaphore:
            response = await gateway.acomplete(
                messages=build_followup_plan_messages(case),
                tools=None,
                tool_choice="none",
                metadata={
                    "component": "followup_generation",
                    "prompt_version": "runtime_v7_followup_generation_v2",
                    "scenario_id": str(case_row.get("case_id") or ""),
                    "run": run_index,
                },
                response_format=build_followup_plan_response_model(case),
                max_tokens=int(os.getenv("RUNTIME_V7_FOLLOWUP_MAX_TOKENS", "700") or "700"),
            )
    except Exception as exc:
        row.update(
            {
                "model_calls": 1,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "action": "error",
                "validation_status": "not_run",
                "error_type": type(exc).__name__,
                "error": str(exc)[:1000],
                "checks": {
                    "one_model_call_or_less": True,
                    "model_call_succeeded": False,
                },
            }
        )
        return _apply_expected_checks(row, case_row)
    row["model_calls"] = 1
    model_content = str(response.get("content") or "")
    plan = parse_followup_plan(model_content)
    validation = validate_and_render_followup(case, plan)
    message = str(validation.get("message") or "")
    preferred_brands = _mentioned_brands(case.get("customer_brand_preference"))
    rendered_brands = _mentioned_brands(message)
    row.update(
        {
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "usage": _usage(response),
            "transport_attempt_count": int(
                (response.get("request_debug") or {}).get("transport_attempt_count") or 1
            ),
            "transport_retry_count": len(response.get("transport_retry_events") or []),
            "action": plan.get("action"),
            "stance": plan.get("customer_stance"),
            "focus_field": validation.get("focus_field") or plan.get("focus_field"),
            "visible_text": plan.get("visible_text"),
            "benefit_refs": plan.get("benefit_refs") or [],
            "reason": plan.get("reason"),
            "parse_status": plan.get("parse_status"),
            "validation_status": validation.get("status"),
            "validation_reasons": validation.get("validation_reasons") or [],
            "message": message,
            "checks": {
                "one_model_call_or_less": True,
                "single_cta": validation.get("status") != "valid" or message.count("?") <= 1,
                # Invalid plans are suppressed and therefore customer-safe.
                "no_unsupported_claim": not message
                or not any(
                    reason == "benefit_ref_not_allowed"
                    for reason in validation.get("validation_reasons") or []
                ),
                "valid_structured_output": plan.get("parse_status") == "valid",
                "no_customer_preference_contradiction": not preferred_brands
                or not bool(rendered_brands.difference(preferred_brands)),
            },
        }
    )
    if plan.get("parse_status") != "valid":
        row["invalid_model_content"] = model_content[:2000]
    return _apply_expected_checks(row, case_row)


def _summary(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    model_rows = [row for row in rows if int(row.get("model_calls") or 0) > 0]
    invalid = [row for row in model_rows if row.get("parse_status") != "valid"]
    validation_failed = [row for row in model_rows if row.get("validation_status") == "invalid"]
    model_errors = [row for row in model_rows if row.get("action") == "error"]
    failed_checks = [
        {"case_id": row.get("case_id"), "run": row.get("run"), "checks": row.get("checks")}
        for row in rows
        if any(value is False for value in (row.get("checks") or {}).values())
    ]
    tokens = sum(int((row.get("usage") or {}).get("total_tokens") or 0) for row in model_rows)
    transport_retries = sum(int(row.get("transport_retry_count") or 0) for row in model_rows)
    invalid_rate = (len(invalid) / len(model_rows)) if model_rows else 0.0
    validation_failure_rate = (len(validation_failed) / len(model_rows)) if model_rows else 0.0
    return {
        "evaluations": len(rows),
        "model_evaluations": len(model_rows),
        "model_calls": sum(int(row.get("model_calls") or 0) for row in rows),
        "invalid_structured_outputs": len(invalid),
        "invalid_structured_output_rate": invalid_rate,
        "semantic_validation_failures": len(validation_failed),
        "semantic_validation_failure_rate": validation_failure_rate,
        "model_errors": len(model_errors),
        "failed_invariant_checks": failed_checks,
        "tokens_total": tokens,
        "transport_retries": transport_retries,
        "deployment_blockers_passed": (
            not failed_checks
            and not model_errors
            and invalid_rate <= 0.01
            and validation_failure_rate <= 0.02
        ),
    }


async def _main() -> None:
    args = _args()
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    payload = json.loads(args.corpus.read_text(encoding="utf-8"))
    cases = [dict(item) for item in payload.get("cases") or [] if isinstance(item, Mapping)]
    if args.case:
        selected = set(args.case)
        cases = [item for item in cases if str(item.get("case_id") or "") in selected]
    if args.limit > 0:
        cases = cases[: args.limit]
    model = args.model or os.getenv("RUNTIME_V7_FOLLOWUP_MODEL", "gemini/gemini-2.5-flash-lite")
    gateway = RuntimeV7LLMGateway(
        config=RuntimeV7LLMGatewayConfig(
            model=model,
            temperature=float(os.getenv("RUNTIME_V7_FOLLOWUP_TEMPERATURE", "0.1") or "0.1"),
            max_tokens=int(os.getenv("RUNTIME_V7_FOLLOWUP_MAX_TOKENS", "700") or "700"),
            timeout_s=float(os.getenv("RUNTIME_V7_FOLLOWUP_TIMEOUT_S", "30") or "30"),
            max_transport_retries=max(
                0,
                min(2, int(os.getenv("RUNTIME_V7_FOLLOWUP_TRANSPORT_RETRIES", "1") or "1")),
            ),
            transport_retry_backoff_s=float(
                os.getenv("RUNTIME_V7_FOLLOWUP_TRANSPORT_RETRY_BACKOFF_S", "0.75") or "0.75"
            ),
            enable_context_cache=False,
            reasoning_effort=os.getenv("RUNTIME_V7_FOLLOWUP_REASONING_EFFORT", "disable"),
        )
    )
    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    tasks = [
        _evaluate_one(case, run_index=run, gateway=gateway, semaphore=semaphore)
        for case in cases
        for run in range(1, max(1, args.runs) + 1)
    ]
    rows = await asyncio.gather(*tasks)
    result = {
        "model": model,
        "runs_per_case": max(1, args.runs),
        "case_count": len(cases),
        "summary": _summary(rows),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output.as_posix())


if __name__ == "__main__":
    asyncio.run(_main())
