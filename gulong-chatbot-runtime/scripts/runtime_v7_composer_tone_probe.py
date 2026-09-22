"""Evaluate grounded Runtime V7 replies for conversational customer-service tone.

The probe uses the return-only tester endpoint. It writes the full request,
response, debug metadata, and evaluation result to UTF-8 artifacts before
printing a compact summary.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACK = "test_packs/runtime_v7_composer_tone_live_pack.json"
DEFAULT_ENDPOINT = "/gulong/v7/chat/tester"


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    os.environ.setdefault("LANGSMITH_TRACING", "false")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", default=DEFAULT_PACK)
    parser.add_argument("--base-url", default=os.environ.get("RUNTIME_V7_LIVE_BASE_URL", ""))
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--out-dir", default="tmp/runtime_v7_composer_tone_probe")
    parser.add_argument("--warn-only", action="store_true")
    args = parser.parse_args()

    if not str(args.base_url or "").strip():
        raise SystemExit("Missing --base-url or RUNTIME_V7_LIVE_BASE_URL.")
    pack_path = _resolve_path(args.pack)
    pack = _load_json(pack_path)
    scenarios = [
        dict(item)
        for item in pack.get("scenarios") or []
        if not args.scenario or str(item.get("id")) in set(args.scenario)
    ]
    endpoint = str(args.endpoint or pack.get("endpoint") or DEFAULT_ENDPOINT)
    run_id = f"runtime_v7_composer_tone_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir = _resolve_path(args.out_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, Any]] = []
    for repeat_index in range(max(1, args.repeats)):
        for scenario in scenarios:
            rows.append(
                _run_scenario(
                    scenario,
                    repeat_index=repeat_index + 1,
                    base_url=args.base_url,
                    endpoint=endpoint,
                    timeout_s=args.timeout_s,
                    run_id=run_id,
                    out_dir=out_dir,
                )
            )

    summary = {
        "run_id": run_id,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "pack": pack.get("pack_id"),
        "base_url": _redact_url(args.base_url),
        "endpoint": endpoint,
        "scenario_count": len(rows),
        "passed": sum(1 for row in rows if row["passed"]),
        "failed": sum(1 for row in rows if not row["passed"]),
        "guard_rewrites": sum(1 for row in rows if row["payment_guard_status"] == "rewritten"),
        "rows": rows,
    }
    summary_json = out_dir / "summary.json"
    summary_markdown = out_dir / "summary.md"
    _write_json(summary_json, summary)
    summary_markdown.write_text(_render_summary(summary), encoding="utf-8")
    print(
        json.dumps(
            {
                "summary_json": str(summary_json.resolve()),
                "summary_markdown": str(summary_markdown.resolve()),
                "passed": summary["passed"],
                "failed": summary["failed"],
                "guard_rewrites": summary["guard_rewrites"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if summary["failed"] and not args.warn_only:
        raise SystemExit(1)


def _run_scenario(
    scenario: Dict[str, Any],
    *,
    repeat_index: int,
    base_url: str,
    endpoint: str,
    timeout_s: float,
    run_id: str,
    out_dir: Path,
) -> Dict[str, Any]:
    scenario_id = str(scenario.get("id") or "scenario")
    unique = uuid.uuid4().hex[:10]
    user_id = f"composer-tone-{scenario_id}-{repeat_index}-{unique}"
    message_id = f"composer_tone_{scenario_id}_{repeat_index}_{unique}"
    request_payload = {
        "user_id": user_id,
        "channel_user_id": user_id,
        "channel": "manychat",
        "user_text": str(scenario.get("user_text") or ""),
        "message_id": message_id,
        "idempotency_key": message_id,
        "channel_event_id": f"event_{message_id}",
        "flow_context": {
            "probe": "runtime_v7_composer_tone",
            "run_id": run_id,
            "scenario_id": scenario_id,
            "repeat_index": repeat_index,
        },
        "delivery_mode": "return_only",
        "return_logs": 1,
        "save_analytics": 0,
        "reset": 1,
    }
    url = _join_url(base_url, endpoint)
    started = time.perf_counter()
    http_status, response_payload, raw_body, error = _post_json(
        url,
        request_payload,
        timeout_s=timeout_s,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    bubbles = _extract_bubbles(response_payload)
    evaluation = evaluate_customer_reply(
        scenario,
        bubbles=bubbles,
        response_payload=response_payload,
        http_status=http_status,
        error=error,
    )
    artifact = {
        "scenario": scenario,
        "repeat_index": repeat_index,
        "url": _redact_url(url),
        "elapsed_ms": elapsed_ms,
        "http_status": http_status,
        "request_payload": request_payload,
        "response_payload": response_payload,
        "raw_body": raw_body,
        "bubbles": bubbles,
        "evaluation": evaluation,
        "error": error,
    }
    stem = f"{_safe_id(scenario_id)}_{repeat_index}"
    _write_json(out_dir / f"{stem}.json", artifact)
    (out_dir / f"{stem}.md").write_text(
        _render_scenario(artifact),
        encoding="utf-8",
    )
    debug = response_payload.get("debug") if isinstance(response_payload, dict) else {}
    debug = debug if isinstance(debug, dict) else {}
    guard = debug.get("payment_policy_truth_guard")
    guard = guard if isinstance(guard, dict) else {}
    return {
        "scenario_id": scenario_id,
        "repeat_index": repeat_index,
        "passed": evaluation["passed"],
        "failures": evaluation["failures"],
        "warnings": evaluation["warnings"],
        "http_status": http_status,
        "request_id": response_payload.get("request_id"),
        "release_version": response_payload.get("release_version"),
        "elapsed_ms": elapsed_ms,
        "bubbles": bubbles,
        "payment_guard_status": str(guard.get("status") or ""),
        "final_composer_status": str(debug.get("final_composer_status") or ""),
        "commercial_payment_claims": debug.get("commercial_payment_claims") or [],
        "tool_calls": debug.get("tool_calls") or [],
        "llm_usage_summary": debug.get("llm_usage_summary") or {},
    }


def evaluate_customer_reply(
    scenario: Dict[str, Any],
    *,
    bubbles: Sequence[str],
    response_payload: Dict[str, Any],
    http_status: int,
    error: str,
) -> Dict[str, Any]:
    """Score semantic completeness separately from conversational quality."""

    failures: List[str] = []
    warnings: List[str] = []
    joined = "\n".join(str(item or "") for item in bubbles)
    normalized = _normalize(joined)
    debug = response_payload.get("debug") if isinstance(response_payload, dict) else {}
    debug = debug if isinstance(debug, dict) else {}
    guard = debug.get("payment_policy_truth_guard")
    guard = guard if isinstance(guard, dict) else {}

    if error:
        failures.append(f"request_error:{error}")
    if not 200 <= http_status < 300:
        failures.append(f"http_status:{http_status}")
    if str(response_payload.get("status") or "") != "success":
        failures.append(f"runtime_status:{response_payload.get('status')}")
    if not bubbles:
        failures.append("no_customer_bubbles")
    if str(guard.get("status") or "") == "rewritten":
        failures.append(f"deterministic_payment_rewrite:{guard.get('reason')}")
    if str(debug.get("final_composer_status") or "") not in {"used", "repaired"}:
        failures.append(
            f"final_composer_status:{debug.get('final_composer_status')}"
        )

    expected = scenario.get("expected") if isinstance(scenario.get("expected"), dict) else {}
    for pattern in expected.get("required_patterns") or []:
        if not re.search(str(pattern), normalized, flags=re.IGNORECASE):
            failures.append(f"missing_required_pattern:{pattern}")
    for pattern in expected.get("forbidden_patterns") or []:
        if re.search(str(pattern), normalized, flags=re.IGNORECASE):
            failures.append(f"forbidden_pattern:{pattern}")

    conversational = _customer_answer_without_runtime_intro(bubbles)
    conversational_normalized = _normalize(conversational)
    had_standalone_runtime_welcome = any(
        _is_standalone_runtime_welcome(bubble) for bubble in bubbles
    )
    if had_standalone_runtime_welcome and re.match(
        r"^(?:hi|hello|good day|welcome)\b",
        conversational_normalized,
    ):
        failures.append("duplicate_greeting_after_runtime_intro")
    repeated_negative = len(
        re.findall(
            r"\b(?:hindi|wala)\s+(?:po\s+)?(?:currently\s+)?available\b",
            conversational_normalized,
        )
    )
    if repeated_negative > 1:
        failures.append(f"repeated_negative_template:{repeated_negative}")
    if re.search(r"(?m)^\s*[-*]\s+", conversational):
        failures.append("database_list_delivery")
    minimum_claims = int(expected.get("minimum_commercial_claims") or 0)
    if minimum_claims > 1 and not re.search(
        (
            r"\b(?:pero|naman|but|however|while|though|instead|"
            r"on the other hand)\b"
        ),
        conversational_normalized,
    ):
        failures.append("missing_natural_contrast_connector")
    if conversational.count("?") > 1:
        failures.append("more_than_one_next_question")
    for phrase in (
        "bilang payment method",
        "as payment method",
        "under the active checkout options",
        "not currently eligible",
        "compatible payment options when you are ready",
    ):
        if phrase in conversational_normalized:
            failures.append(f"stiff_policy_phrase:{phrase}")
    if re.search(r"\bregarding\b", conversational_normalized):
        failures.append("stiff_policy_phrase:regarding")
    if re.search(
        r"\b(?:eligible|ineligible)\s+(?:payment|method|option|brand)\b",
        conversational_normalized,
    ):
        failures.append("policy_label_in_customer_prose")
    if re.search(r"\b6\s*%\s*interest\b", conversational_normalized):
        failures.append("invented_six_percent_interest")
    if re.search(r"\banong bank\b|\bwhich bank\b", conversational_normalized):
        failures.append("asks_bank_instead_of_answering")

    claims = debug.get("commercial_payment_claims")
    claims = claims if isinstance(claims, list) else []
    grounded_evidence_count = _grounded_commercial_evidence_count(debug)
    if grounded_evidence_count < minimum_claims:
        failures.append(
            "commercial_evidence_below_minimum:"
            f"{grounded_evidence_count}<{minimum_claims}"
        )
    if not claims:
        warnings.append("no_commercial_claim_debug_metadata")

    return {
        "passed": not failures,
        "failures": failures,
        "warnings": warnings,
        "customer_answer": conversational,
    }


def _grounded_commercial_evidence_count(debug: Dict[str, Any]) -> int:
    """Count distinct successful commercial authorities used by the turn.

    ``commercial_payment_claims`` covers validated payment claims but does not
    represent promo, product, or policy authorities. The probe therefore uses
    the larger of that claim count and the distinct successful commercial tool
    families, avoiding false failures when a grounded mixed turn uses two
    authorities but only one emits payment-claim telemetry.
    """

    claims = debug.get("commercial_payment_claims")
    claims = claims if isinstance(claims, list) else []
    families = set()
    family_by_tool = {
        "answer_order_faq": "policy",
        "answer_policy_faq": "policy",
        "search_promo_catalog": "promo",
        "product_search": "product",
        "get_product_details": "product",
        "calculate_order_quote": "quote",
        "build_order_summary": "order",
        "prepare_payment_request": "payment_request",
    }
    for call in debug.get("tool_calls") or []:
        if not isinstance(call, dict) or str(call.get("status") or "") != "ok":
            continue
        family = family_by_tool.get(str(call.get("name") or ""))
        if family:
            families.add(family)
    return max(len(claims), len(families))


def _customer_answer_without_runtime_intro(bubbles: Sequence[str]) -> str:
    kept = []
    for bubble in bubbles:
        if _is_standalone_runtime_welcome(bubble):
            continue
        kept.append(str(bubble or "").strip())
    return "\n".join(item for item in kept if item)


def _is_standalone_runtime_welcome(value: Any) -> bool:
    """Match only the exact fixed runtime welcome, never merged answer prose."""

    normalized = _normalize(_normalize(str(value or "")).replace("😊", ""))
    return normalized.strip() == (
        "hi po! welcome to gulong.ph we'll help you find brand-new, legit "
        "tires that fit your car, budget, and area."
    )


def _extract_bubbles(payload: Dict[str, Any]) -> List[str]:
    response = payload.get("response") if isinstance(payload, dict) else None
    if isinstance(response, dict) and response:
        items = sorted(response.items(), key=lambda item: _bubble_key(str(item[0])))
        return [str(value or "").strip() for _, value in items if str(value or "").strip()]
    messages = payload.get("content_messages") if isinstance(payload, dict) else None
    if isinstance(messages, list):
        return [
            str(item.get("text") or "").strip()
            for item in messages
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]
    return []


def _post_json(
    url: str,
    payload: Dict[str, Any],
    *,
    timeout_s: float,
) -> Tuple[int, Dict[str, Any], str, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return int(response.status), _parse_json(raw), raw, ""
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), _parse_json(raw), raw, str(exc)
    except Exception as exc:
        return 0, {}, "", f"{type(exc).__name__}:{exc}"


def _render_summary(summary: Dict[str, Any]) -> str:
    lines = [
        f"# {summary['run_id']}",
        "",
        f"Passed: `{summary['passed']}`",
        f"Failed: `{summary['failed']}`",
        f"Guard rewrites: `{summary['guard_rewrites']}`",
        "",
    ]
    for row in summary["rows"]:
        status = "PASS" if row["passed"] else "FAIL"
        lines.extend(
            [
                f"## {status} {row['scenario_id']} repeat {row['repeat_index']}",
                "",
                f"Request: `{row.get('request_id')}`",
                f"Release: `{row.get('release_version')}`",
                f"Latency: `{row.get('elapsed_ms')}ms`",
                f"Composer: `{row.get('final_composer_status')}`",
                f"Payment guard: `{row.get('payment_guard_status') or 'silent'}`",
                "",
            ]
        )
        for index, bubble in enumerate(row["bubbles"], start=1):
            lines.extend([f"Bubble {index}:", "", bubble, ""])
        if row["failures"]:
            lines.extend(["Failures:", ""])
            lines.extend(f"- {item}" for item in row["failures"])
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_scenario(artifact: Dict[str, Any]) -> str:
    lines = [
        f"# {artifact['scenario'].get('id')}",
        "",
        f"HTTP: `{artifact['http_status']}`",
        f"Latency: `{artifact['elapsed_ms']}ms`",
        "",
    ]
    for index, bubble in enumerate(artifact["bubbles"], start=1):
        lines.extend([f"## Bubble {index}", "", bubble, ""])
    lines.extend(
        [
            "## Evaluation",
            "",
            "```json",
            json.dumps(artifact["evaluation"], ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _join_url(base_url: str, endpoint: str) -> str:
    return f"{str(base_url).rstrip('/')}/{str(endpoint).lstrip('/')}"


def _redact_url(value: str) -> str:
    return re.sub(r"([?&](?:token|key|secret)=)[^&]+", r"\1REDACTED", str(value))


def _normalize(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _parse_json(value: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-") or "scenario"


def _bubble_key(value: str) -> Tuple[int, str]:
    match = re.search(r"(\d+)$", value)
    return (int(match.group(1)) if match else 9999, value)


if __name__ == "__main__":
    main()
