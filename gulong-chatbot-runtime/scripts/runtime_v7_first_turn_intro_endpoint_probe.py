"""Probe Runtime V7 first-turn intro behavior through the chat tester endpoint.

The probe is intentionally return-only by default. It validates customer-visible
bubbles from `/gulong/v7/chat/tester` while reusing the focused first-turn live
pack that the harness runner can also execute for deeper prompt/tool artifacts.
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


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


DEFAULT_PACK = "test_packs/runtime_v7_first_turn_intro_live_pack.json"
DEFAULT_ENDPOINT = "/gulong/v7/chat/tester"
WELCOME_NEEDLE = "welcome to gulong.ph"
FULL_INTAKE_NEEDLES = (
    "para ma-check namin yung best tires",
    "guide lang po: tire size usually",
)


def main() -> None:
    os.environ.setdefault("LANGSMITH_TRACING", "false")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", default=DEFAULT_PACK)
    parser.add_argument("--base-url", default=os.environ.get("RUNTIME_V7_LIVE_BASE_URL", ""))
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--timeout-s", type=float, default=90.0)
    parser.add_argument("--out-dir", default="tmp/runtime_v7_first_turn_intro_endpoint_probe")
    parser.add_argument("--user-prefix", default="runtime-v7-first-turn-probe")
    parser.add_argument("--delivery-mode", default="return_only")
    parser.add_argument("--save-analytics", type=int, default=0)
    parser.add_argument("--return-logs", type=int, default=1)
    parser.add_argument("--warn-only", action="store_true", help="Write artifacts but return exit code 0 even when checks fail.")
    args = parser.parse_args()

    pack_path = _resolve_path(args.pack)
    pack = _load_json(pack_path)
    scenarios = _select_scenarios(pack.get("scenarios") or [], scenario_ids=args.scenario, tags=args.tag, limit=args.limit)
    if args.list:
        _print_scenario_list(scenarios)
        return

    if not str(args.base_url or "").strip():
        raise SystemExit("Missing --base-url or RUNTIME_V7_LIVE_BASE_URL for endpoint live probe.")

    endpoint = str(args.endpoint or pack.get("endpoint") or DEFAULT_ENDPOINT)
    run_id = f"runtime_v7_first_turn_endpoint_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir = _resolve_path(args.out_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, Any]] = []
    for scenario in scenarios:
        row = _run_scenario(
            scenario,
            base_url=args.base_url,
            endpoint=endpoint,
            timeout_s=args.timeout_s,
            run_id=run_id,
            user_prefix=args.user_prefix,
            delivery_mode=args.delivery_mode,
            save_analytics=args.save_analytics,
            return_logs=args.return_logs,
            out_dir=out_dir,
        )
        rows.append(row)

    summary = {
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pack": pack.get("pack_id"),
        "base_url": _redact_url(args.base_url),
        "endpoint": endpoint,
        "scenario_count": len(rows),
        "passed": sum(1 for row in rows if row.get("passed")),
        "failed": sum(1 for row in rows if not row.get("passed")),
        "rows": rows,
    }
    summary_json = out_dir / "summary.json"
    summary_md = out_dir / "summary.md"
    _write_json(summary_json, summary)
    summary_md.write_text(_render_summary_markdown(summary), encoding="utf-8")
    _safe_print(json.dumps({"summary_json": str(summary_json.resolve()), "summary_markdown": str(summary_md.resolve())}, ensure_ascii=False, indent=2))

    if summary["failed"] and not args.warn_only:
        raise SystemExit(1)


def _run_scenario(
    scenario: Dict[str, Any],
    *,
    base_url: str,
    endpoint: str,
    timeout_s: float,
    run_id: str,
    user_prefix: str,
    delivery_mode: str,
    save_analytics: int,
    return_logs: int,
    out_dir: Path,
) -> Dict[str, Any]:
    scenario_id = str(scenario.get("id") or "scenario")
    message = _first_turn_message(scenario)
    request_payload = _build_request_payload(
        scenario,
        user_text=message,
        run_id=run_id,
        user_prefix=user_prefix,
        delivery_mode=delivery_mode,
        save_analytics=save_analytics,
        return_logs=return_logs,
    )
    url = _join_url(base_url, endpoint)
    started = time.perf_counter()
    http_status, response_payload, raw_body, error = _post_json(url, request_payload, timeout_s=timeout_s)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    bubbles = _extract_bubbles(response_payload)
    checks = _evaluate_response(scenario, response_payload=response_payload, bubbles=bubbles, http_status=http_status, error=error)
    artifact = {
        "scenario": scenario,
        "url": _redact_url(url),
        "elapsed_ms": elapsed_ms,
        "http_status": http_status,
        "request_payload": _redact_request_payload(request_payload),
        "response_payload": response_payload,
        "raw_body": raw_body[:4000],
        "bubbles": bubbles,
        "checks": checks,
        "error": error,
    }
    safe_id = _safe_file_name(scenario_id)
    json_path = out_dir / f"{safe_id}.json"
    md_path = out_dir / f"{safe_id}.md"
    _write_json(json_path, artifact)
    md_path.write_text(_render_scenario_markdown(artifact), encoding="utf-8")

    return {
        "scenario_id": scenario_id,
        "title": scenario.get("title") or "",
        "passed": checks["passed"],
        "failure_count": len(checks["failures"]),
        "failures": checks["failures"],
        "warnings": checks["warnings"],
        "http_status": http_status,
        "runtime_status": response_payload.get("status") if isinstance(response_payload, dict) else "",
        "elapsed_ms": elapsed_ms,
        "bubble_count": len(bubbles),
        "bubbles": bubbles,
        "artifact_json": str(json_path.resolve()),
        "artifact_markdown": str(md_path.resolve()),
    }


def _build_request_payload(
    scenario: Dict[str, Any],
    *,
    user_text: str,
    run_id: str,
    user_prefix: str,
    delivery_mode: str,
    save_analytics: int,
    return_logs: int,
) -> Dict[str, Any]:
    scenario_id = _safe_id(str(scenario.get("id") or "scenario"))
    unique = uuid.uuid4().hex[:10]
    user_id = f"{_safe_id(user_prefix)}-{scenario_id}-{unique}"
    message_id = f"probe_{scenario_id}_{unique}"
    conversation_history = [dict(item) for item in scenario.get("conversation_history") or [] if isinstance(item, dict)]
    return {
        "user_id": user_id,
        "channel_user_id": user_id,
        "channel": "manychat",
        "user_text": user_text,
        "message_id": message_id,
        "idempotency_key": message_id,
        "channel_event_id": f"probe_event_{scenario_id}_{unique}",
        "conversation_history": conversation_history,
        "flow_context": {
            "probe": "runtime_v7_first_turn_intro_endpoint",
            "run_id": run_id,
            "scenario_id": str(scenario.get("id") or ""),
        },
        "profile_fields": dict(scenario.get("profile_fields") or {}),
        "delivery_mode": delivery_mode,
        "return_logs": int(return_logs),
        "save_analytics": int(save_analytics),
        "reset": 0 if conversation_history else 1,
    }


def _post_json(url: str, payload: Dict[str, Any], *, timeout_s: float) -> Tuple[int, Dict[str, Any], str, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, float(timeout_s or 90.0))) as response:
            raw = response.read().decode("utf-8", errors="replace")
            parsed = _parse_json(raw)
            return int(response.status), parsed, raw, ""
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), _parse_json(raw), raw, str(exc)
    except Exception as exc:
        return 0, {}, "", f"{type(exc).__name__}: {exc}"


def _evaluate_response(
    scenario: Dict[str, Any],
    *,
    response_payload: Dict[str, Any],
    bubbles: Sequence[str],
    http_status: int,
    error: str,
) -> Dict[str, Any]:
    endpoint_expected = ((scenario.get("expected") or {}).get("endpoint") or {}) if isinstance(scenario.get("expected"), dict) else {}
    failures: List[str] = []
    warnings: List[str] = []
    joined = _normalize(" ".join(bubbles))
    first = _normalize(bubbles[0] if bubbles else "")

    if error:
        failures.append(f"request_error: {error}")
    if http_status < 200 or http_status >= 300:
        failures.append(f"http_status_not_2xx: {http_status}")
    runtime_status = str(response_payload.get("status") or "") if isinstance(response_payload, dict) else ""
    if runtime_status and runtime_status != "success":
        failures.append(f"runtime_status_not_success: {runtime_status}")
    if not bubbles:
        failures.append("no_response_bubbles_returned")

    intro_mode = str(endpoint_expected.get("intro_mode") or "").strip().lower()
    if intro_mode == "full_intake":
        _require_ordered_prefixes(
            bubbles,
            [
                WELCOME_NEEDLE,
                "para ma-check namin yung best tires",
                "guide lang po: tire size usually",
            ],
            failures=failures,
        )
        _require_continuation_without_greeting(bubbles, continuation_index=3, failures=failures)
    elif intro_mode == "welcome_only":
        for needle in FULL_INTAKE_NEEDLES:
            if needle in joined:
                failures.append(f"welcome_only_response_contains_full_intake_text: {needle}")
    elif intro_mode == "none":
        if WELCOME_NEEDLE in first:
            failures.append("intro_suppression_failed_bubble1_contains_welcome")
        for needle in FULL_INTAKE_NEEDLES:
            if needle in joined:
                failures.append(f"intro_suppression_failed_contains_full_intake_text: {needle}")

    max_welcome = endpoint_expected.get("max_welcome_occurrences")
    if max_welcome is not None:
        count = joined.count(WELCOME_NEEDLE)
        try:
            limit = int(max_welcome)
        except (TypeError, ValueError):
            limit = -1
        if limit >= 0 and count > limit:
            failures.append(f"welcome_occurrences_exceeded: count={count}, limit={limit}")

    for needle in endpoint_expected.get("must_contain_all") or []:
        if _normalize(needle) not in joined:
            failures.append(f"missing_required_text: {needle}")
    for group in endpoint_expected.get("must_contain_any") or []:
        options = [str(item) for item in group] if isinstance(group, list) else [str(group)]
        if not any(_normalize(option) in joined for option in options):
            failures.append(f"missing_any_required_text: {' | '.join(options)}")
    for needle in endpoint_expected.get("must_not_contain") or []:
        normalized = _normalize(needle)
        if normalized and normalized in joined:
            failures.append(f"forbidden_text_present: {needle}")
    for needle in endpoint_expected.get("must_not_start_with") or []:
        normalized = _normalize(needle)
        if normalized and first.startswith(normalized):
            failures.append(f"forbidden_start_text_present: {needle}")

    debug = response_payload.get("debug") if isinstance(response_payload, dict) else None
    if not isinstance(debug, dict):
        warnings.append("debug_payload_missing_or_not_requested")
    else:
        if not debug.get("turn_id"):
            warnings.append("debug_turn_id_missing")
        if not isinstance(debug.get("tool_calls"), list):
            warnings.append("debug_tool_calls_missing")

    return {
        "passed": not failures,
        "failures": failures,
        "warnings": warnings,
        "observed": {
            "runtime_status": runtime_status,
            "bubble_count": len(bubbles),
            "welcome_occurrences": joined.count(WELCOME_NEEDLE),
        },
    }


def _require_ordered_prefixes(bubbles: Sequence[str], needles: Sequence[str], *, failures: List[str]) -> None:
    for index, needle in enumerate(needles):
        if len(bubbles) <= index:
            failures.append(f"missing_bubble_{index + 1}_for_intro")
            continue
        if _normalize(needle) not in _normalize(bubbles[index]):
            failures.append(f"bubble_{index + 1}_does_not_contain_expected_intro_text: {needle}")


def _require_continuation_without_greeting(
    bubbles: Sequence[str],
    *,
    continuation_index: int,
    failures: List[str],
) -> None:
    if len(bubbles) <= continuation_index:
        return
    continuation = _normalize(bubbles[continuation_index])
    if _starts_with_greeting(continuation):
        failures.append(f"continuation_starts_with_greeting_after_runtime_intro: bubble_{continuation_index + 1}")


def _starts_with_greeting(text: str) -> bool:
    normalized = _normalize(text)
    return bool(re.match(r"^(hi|hello|good day|welcome)(\b|\s|[!.?,])", normalized))


def _extract_bubbles(payload: Dict[str, Any]) -> List[str]:
    response = payload.get("response") if isinstance(payload, dict) else None
    if isinstance(response, dict) and response:
        items = sorted(response.items(), key=lambda item: _bubble_sort_key(str(item[0])))
        return [str(value or "").strip() for _, value in items if str(value or "").strip()]
    messages = payload.get("content_messages") if isinstance(payload, dict) else None
    if isinstance(messages, list):
        return [str(item.get("text") or "").strip() for item in messages if isinstance(item, dict) and str(item.get("text") or "").strip()]
    return []


def _first_turn_message(scenario: Dict[str, Any]) -> str:
    turns = scenario.get("turns") or []
    if not turns:
        return str(scenario.get("user_text") or "")
    first = turns[0]
    if isinstance(first, dict):
        return str(first.get("message") or first.get("user_text") or "")
    return str(first)


def _select_scenarios(
    scenarios: Sequence[Dict[str, Any]],
    *,
    scenario_ids: Sequence[str],
    tags: Sequence[str],
    limit: int,
) -> List[Dict[str, Any]]:
    wanted_ids = {str(value) for value in scenario_ids or []}
    wanted_tags = {str(value) for value in tags or []}
    selected: List[Dict[str, Any]] = []
    for scenario in scenarios:
        scenario_tags = {str(value) for value in scenario.get("tags") or []}
        if wanted_ids and str(scenario.get("id")) not in wanted_ids:
            continue
        if wanted_tags and not wanted_tags.intersection(scenario_tags):
            continue
        selected.append(dict(scenario))
        if limit and len(selected) >= limit:
            break
    return selected


def _print_scenario_list(scenarios: Sequence[Dict[str, Any]]) -> None:
    for scenario in scenarios:
        _safe_print(
            "{id}\t{category}\t{tags}\t{title}".format(
                id=scenario.get("id"),
                category=scenario.get("category"),
                tags=",".join(str(value) for value in scenario.get("tags") or []),
                title=scenario.get("title"),
            )
        )


def _render_summary_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        f"# {summary.get('run_id')}",
        "",
        f"Pack: `{summary.get('pack')}`",
        f"Endpoint: `{summary.get('endpoint')}`",
        f"Passed: `{summary.get('passed')}`",
        f"Failed: `{summary.get('failed')}`",
        "",
        "## Scenarios",
        "",
    ]
    for row in summary.get("rows") or []:
        status = "PASS" if row.get("passed") else "FAIL"
        lines.extend(
            [
                f"### {status} {row.get('scenario_id')}: {row.get('title')}",
                "",
                f"HTTP: `{row.get('http_status')}` Runtime: `{row.get('runtime_status')}` Latency: `{row.get('elapsed_ms')}ms`",
                "",
                "Bubbles:",
                "",
            ]
        )
        for index, bubble in enumerate(row.get("bubbles") or [], start=1):
            lines.extend([f"{index}. {bubble}", ""])
        if row.get("failures"):
            lines.extend(["Failures:", ""])
            lines.extend(f"- {failure}" for failure in row.get("failures") or [])
            lines.append("")
        if row.get("warnings"):
            lines.extend(["Warnings:", ""])
            lines.extend(f"- {warning}" for warning in row.get("warnings") or [])
            lines.append("")
        lines.extend([f"Artifact: `{row.get('artifact_json')}`", ""])
    return "\n".join(lines)


def _render_scenario_markdown(artifact: Dict[str, Any]) -> str:
    scenario = artifact.get("scenario") or {}
    checks = artifact.get("checks") or {}
    status = "PASS" if checks.get("passed") else "FAIL"
    lines = [
        f"# {status} {scenario.get('id')}: {scenario.get('title')}",
        "",
        f"HTTP: `{artifact.get('http_status')}`",
        f"Latency: `{artifact.get('elapsed_ms')}ms`",
        "",
        "## Expected",
        "",
        "```json",
        json.dumps(((scenario.get("expected") or {}).get("endpoint") or {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Bubbles",
        "",
    ]
    for index, bubble in enumerate(artifact.get("bubbles") or [], start=1):
        lines.extend([f"### Bubble {index}", "", bubble, ""])
    lines.extend(
        [
            "## Checks",
            "",
            "```json",
            json.dumps(checks, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Debug Summary",
            "",
            "```json",
            json.dumps(_debug_summary(artifact.get("response_payload") or {}), ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _debug_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    debug = payload.get("debug") if isinstance(payload, dict) else {}
    if not isinstance(debug, dict):
        debug = {}
    return {
        "request_id": payload.get("request_id"),
        "trace_id": payload.get("trace_id"),
        "session_id": payload.get("session_id"),
        "message_id": payload.get("message_id"),
        "delivery_result": payload.get("delivery_result"),
        "tagging_result": payload.get("tagging_result"),
        "turn_trace_summary": payload.get("turn_trace_summary"),
        "tool_calls": debug.get("tool_calls"),
        "llm_usage_summary": debug.get("llm_usage_summary"),
    }


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _parse_json(raw: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {"payload": parsed}


def _join_url(base_url: str, endpoint: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    path = str(endpoint or DEFAULT_ENDPOINT).strip()
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def _resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _bubble_sort_key(key: str) -> Tuple[int, str]:
    match = re.search(r"(\d+)$", key)
    if match:
        return int(match.group(1)), key
    return 9999, key


def _safe_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip())
    return text.strip("-") or "probe"


def _safe_file_name(value: str) -> str:
    return _safe_id(value)[:120]


def _redact_url(value: str) -> str:
    text = str(value or "")
    return re.sub(r"([?&](?:key|token|api_key|access_token)=)[^&]+", r"\1<redacted>", text, flags=re.IGNORECASE)


def _redact_request_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    redacted = dict(payload)
    profile_fields = redacted.get("profile_fields")
    if isinstance(profile_fields, dict):
        redacted["profile_fields"] = {key: "<redacted>" if "token" in str(key).lower() else value for key, value in profile_fields.items()}
    return redacted


def _safe_print(value: str) -> None:
    try:
        print(value)
    except UnicodeEncodeError:
        print(value.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))


if __name__ == "__main__":
    main()
