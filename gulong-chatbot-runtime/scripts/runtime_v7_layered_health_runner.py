"""Run selectable Runtime V7 health layers with explicit cost and safety gates.

The runner keeps deterministic regression, read-only HTTP dependency checks,
and metered deployed-model evaluation separate. It writes one UTF-8 artifact
before returning a failing exit code. Metered layers never run without
``--allow-metered-models``; configured HTTP probes reject mutation-like paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime_v7.promotion_health_evaluator import (  # noqa: E402
    DEFAULT_HEALTH_POLICY,
    load_json,
    score_release_candidate,
)

DETERMINISTIC_CORE_TESTS = (
    "test/test_runtime_v7_layered_health_runner.py",
    "test/test_runtime_v7_release_candidate_matrix.py",
    "test/test_runtime_v7_promotion_health_evaluator.py",
    "test/test_runtime_v7_product_search_runner.py",
    "test/test_runtime_v7_transaction_choices.py",
    "test/test_runtime_v7_promo_action_endpoint.py",
    "test/test_runtime_v7_followup_endpoint.py",
)
DETERMINISTIC_INTENT_OBSERVABILITY_TESTS = (
    "test/test_runtime_v7_lead_tagging.py",
    "test/test_runtime_v7_ingress_trace.py",
    "test/test_runtime_v7_channel_renderer.py",
)
COMMERCE_DEPENDENCY_COMPONENTS = frozenset(
    {
        "product_search",
        "payment_catalog",
        "transaction_types",
        "installation_partners",
        "installation_slots",
    }
)
CHANNEL_READ_COMPONENTS = frozenset({"manychat_messages", "manychat_profile"})
REQUIRED_DEPENDENCY_COMPONENTS = (
    COMMERCE_DEPENDENCY_COMPONENTS | CHANNEL_READ_COMPONENTS
)
MUTATION_PATH_MARKERS = frozenset(
    {
        "addtag",
        "removetag",
        "setcustomfield",
        "createnote",
        "sendcontent",
        "submit",
        "book",
        "payment/create",
        "payment/submit",
        "payment/charge",
        "payment/checkout",
    }
)

LAYER_METADATA: Mapping[str, Mapping[str, Any]] = {
    "deterministic-core": {
        "cost_class": "local_no_metered_calls",
        "scope": "focused runtime, provider, endpoint, and evaluator contracts",
    },
    "deterministic-intent-observability": {
        "cost_class": "local_no_metered_calls",
        "scope": "Moderate/High rules, tagging, handoff, trace, and event schemas",
    },
    "deterministic-full": {
        "cost_class": "local_no_metered_calls",
        "scope": "complete local repository regression suite",
    },
    "api-core": {
        "cost_class": "external_api_no_llm",
        "scope": "runtime health endpoints and release metadata",
    },
    "api-commerce": {
        "cost_class": "external_api_no_llm",
        "scope": "configured read-only product, payment, partner, and slot contracts",
    },
    "api-channel-reads": {
        "cost_class": "external_api_no_llm",
        "scope": "configured read-only ManyChat history and profile contracts",
    },
    "api-dependencies": {
        "cost_class": "external_api_no_llm",
        "scope": "all configured read-only commerce and ManyChat dependency contracts",
    },
    "model-hydrated-history": {
        "cost_class": "metered_model",
        "scope": "one authenticated tester turn using deployed ManyChat history hydration",
    },
    "model-initial": {
        "cost_class": "metered_model",
        "scope": "three release smoke scenarios",
    },
    "model-in-depth": {
        "cost_class": "metered_model",
        "scope": "promotion matrix, tracked journeys, and data-derived size+brand progression",
    },
    "model-complete": {
        "cost_class": "metered_model",
        "scope": "full pre-verified matrix, operational funnel, and compatible baseline",
    },
}

PROFILES: Mapping[str, Sequence[str]] = {
    "pr-no-cost": (
        "deterministic-core",
        "deterministic-intent-observability",
    ),
    "daily-no-llm": (
        "api-core",
        "api-commerce",
        "api-channel-reads",
    ),
    "pre-staging": (
        "deterministic-full",
        "api-core",
        "api-commerce",
        "api-channel-reads",
        "model-hydrated-history",
        "model-initial",
    ),
    "pre-live": (
        "deterministic-full",
        "api-core",
        "api-commerce",
        "api-channel-reads",
        "model-hydrated-history",
        "model-in-depth",
    ),
    "complete": (
        "deterministic-full",
        "api-core",
        "api-commerce",
        "api-channel-reads",
        "model-hydrated-history",
        "model-complete",
    ),
}

API_LAYER_COMPONENTS: Mapping[str, frozenset[str]] = {
    "api-commerce": COMMERCE_DEPENDENCY_COMPONENTS,
    "api-channel-reads": CHANNEL_READ_COMPONENTS,
    "api-dependencies": REQUIRED_DEPENDENCY_COMPONENTS,
}

COMPONENT_ENDPOINT_CONTRACTS: Mapping[str, frozenset[tuple[str, str]]] = {
    "runtime_http": frozenset({("GET", "/health"), ("GET", "/gulong/health")}),
    "product_search": frozenset({("POST", "/shop")}),
    "payment_catalog": frozenset({("GET", "/payment/list")}),
    "transaction_types": frozenset({("GET", "/transaction_list")}),
    "installation_partners": frozenset({("GET", "/branch_list_loc")}),
    "installation_slots": frozenset({("GET", "/available_slots")}),
    "manychat_messages": frozenset({("GET", "/im/loadmessages")}),
    "manychat_profile": frozenset({("GET", "/subscriber/getinfo")}),
}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Surface redirects as failures instead of following an unreviewed target."""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        """Reject the redirect by declining to construct a follow-up request."""

        return None


def resolve_layers(*, profile: str, requested: Sequence[str]) -> list[str]:
    """Resolve an ordered profile or explicit layer list without duplicates."""

    values = list(requested) if requested else list(PROFILES[profile])
    unknown = [value for value in values if value not in LAYER_METADATA]
    if unknown:
        raise ValueError(f"unknown layer(s): {', '.join(sorted(set(unknown)))}")
    return list(dict.fromkeys(values))


def layer_opt_in_failures(
    layer: str, *, allow_external_apis: bool, allow_metered_models: bool
) -> list[str]:
    """Require independent authorization for external API and model spending."""

    cost_class = str(LAYER_METADATA[layer]["cost_class"])
    if cost_class == "external_api_no_llm" and not allow_external_apis:
        return ["external_api_opt_in_required"]
    if cost_class == "metered_model" and not allow_metered_models:
        return ["metered_model_opt_in_required"]
    return []


def json_path_value(payload: Any, path: str) -> tuple[bool, Any]:
    """Resolve a dotted object/list path while distinguishing absent from null."""

    current = payload
    for part in str(path or "").split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
            continue
        return False, None
    return True, current


def validate_json_contract(payload: Any, expected: Mapping[str, Any]) -> list[str]:
    """Validate stable response schema and values without snapshotting full bodies."""

    failures: list[str] = []
    root_type = str(expected.get("root_type") or "")
    if root_type and not _matches_type(payload, root_type):
        failures.append(f"root_type:{root_type}")
    for path in expected.get("required_paths") or []:
        present, _ = json_path_value(payload, str(path))
        if not present:
            failures.append(f"missing_path:{path}")
    for path, expected_value in (expected.get("equals") or {}).items():
        present, actual = json_path_value(payload, str(path))
        if not present:
            failures.append(f"missing_path:{path}")
        elif actual != expected_value:
            failures.append(f"value_mismatch:{path}")
    for path, type_name in (expected.get("types") or {}).items():
        present, actual = json_path_value(payload, str(path))
        if not present:
            failures.append(f"missing_path:{path}")
        elif not _matches_type(actual, str(type_name)):
            failures.append(f"type_mismatch:{path}:{type_name}")
    for path in expected.get("non_empty") or []:
        present, actual = json_path_value(payload, str(path))
        if not present:
            failures.append(f"missing_path:{path}")
        elif actual in (None, "", [], {}):
            failures.append(f"empty_path:{path}")
    return list(dict.fromkeys(failures))


def validate_probe_spec(
    spec: Mapping[str, Any], *, resolved_url: str = ""
) -> list[str]:
    """Reject ambiguous or mutation-capable HTTP probes before network access."""

    failures: list[str] = []
    if not str(spec.get("id") or "").strip():
        failures.append("missing_id")
    if not str(spec.get("component") or "").strip():
        failures.append("missing_component")
    method = str(spec.get("method") or "GET").upper()
    if method not in {"GET", "POST"}:
        failures.append(f"method_not_allowed:{method}")
    if method == "POST" and spec.get("read_only") is not True:
        failures.append("post_requires_read_only_true")
    component = str(spec.get("component") or "").strip()
    contracts = COMPONENT_ENDPOINT_CONTRACTS.get(component)
    if component and contracts is None:
        failures.append(f"unknown_component:{component}")
    target = str(resolved_url or f"{spec.get('url') or ''}{spec.get('path') or ''}")
    target = urllib.parse.unquote(target).casefold()
    for marker in sorted(MUTATION_PATH_MARKERS):
        if marker in target:
            failures.append(f"mutation_path_rejected:{marker}")
    if resolved_url and contracts:
        path = urllib.parse.urlparse(resolved_url).path.rstrip("/").casefold()
        if not any(
            method == allowed_method and path.endswith(suffix)
            for allowed_method, suffix in contracts
        ):
            failures.append(f"endpoint_not_allowlisted:{component}:{method}")
    expected = spec.get("expected")
    if not isinstance(expected, Mapping):
        failures.append("expected_contract_required")
    elif not any(
        expected.get(key)
        for key in ("root_type", "required_paths", "equals", "types", "non_empty")
    ):
        failures.append("expected_schema_or_value_required")
    try:
        max_latency_ms = int(spec.get("max_latency_ms") or 0)
    except (TypeError, ValueError):
        max_latency_ms = 0
    if max_latency_ms <= 0:
        failures.append("positive_max_latency_ms_required")
    return failures


def run_http_probe(
    spec: Mapping[str, Any], *, default_base_url: str, timeout_s: float
) -> Dict[str, Any]:
    """Run one redacted read-only HTTP contract probe."""

    started = time.perf_counter()
    try:
        url = _probe_url(spec, default_base_url=default_base_url)
    except Exception as exc:
        return _probe_result(
            spec,
            failures=[f"configuration_error:{type(exc).__name__}"],
            elapsed_ms=0,
        )
    failures = validate_probe_spec(spec, resolved_url=url)
    if failures:
        return _probe_result(spec, failures=failures, elapsed_ms=0)
    try:
        method = str(spec.get("method") or "GET").upper()
        query = _resolve_env_values(spec.get("query") or {})
        if query:
            url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(query, doseq=True)}"
        body = _resolve_env_values(spec.get("json_body") or {})
        request = urllib.request.Request(
            url,
            data=(
                json.dumps(body, ensure_ascii=False).encode("utf-8")
                if method == "POST"
                else None
            ),
            headers=_probe_headers(spec),
            method=method,
        )
        opener = urllib.request.build_opener(_NoRedirectHandler())
        with opener.open(request, timeout=timeout_s) as response:
            status_code = int(response.status)
            raw = response.read().decode("utf-8", errors="replace")
        payload = json.loads(raw) if raw.strip() else None
        expected = spec.get("expected") or {}
        allowed_statuses = [
            int(value) for value in expected.get("status_codes") or [200]
        ]
        if status_code not in allowed_statuses:
            failures.append(f"http_status:{status_code}")
        failures.extend(validate_json_contract(payload, expected))
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        failures.append(f"http_status:{status_code}")
    except Exception as exc:
        status_code = 0
        failures.append(f"transport_error:{type(exc).__name__}")
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    max_latency_ms = int(spec.get("max_latency_ms") or 0)
    if max_latency_ms and elapsed_ms > max_latency_ms:
        failures.append(f"latency_ms:{elapsed_ms}>{max_latency_ms}")
    return _probe_result(
        spec,
        failures=failures,
        elapsed_ms=elapsed_ms,
        status_code=status_code,
    )


def run_hydrated_history_probe(
    *,
    base_url: str,
    user_id: str,
    auth_token: str,
    timeout_s: float,
    max_latency_ms: int,
    expected_release: str,
    expected_git_sha: str,
    expected_environment: str,
) -> Dict[str, Any]:
    """Exercise deployed history hydration without retaining transcript content.

    The protected tester route performs one metered, return-only model turn for
    an allowlisted synthetic contact. This function keeps only identity,
    hydration counters, latency, and pass/fail evidence; neither the bearer
    token nor returned customer-visible content enters the artifact.
    """

    failures: list[str] = []
    safe_user_id = str(user_id or "").strip()
    secret = str(auth_token or "").strip()
    if not safe_user_id:
        failures.append("hydrated_history_user_id_required")
    if not secret:
        failures.append("hydrated_history_auth_token_required")
    for field_name, value in (
        ("expected_release", expected_release),
        ("expected_git_sha", expected_git_sha),
        ("expected_environment", expected_environment),
    ):
        if not str(value or "").strip():
            failures.append(f"{field_name}_required")
    if failures:
        return {
            "id": "manychat_hydrated_tester_turn",
            "component": "runtime_manychat_hydration",
            "passed": False,
            "status_code": 0,
            "elapsed_ms": 0,
            "failures": failures,
        }

    run_token = datetime.now(ZoneInfo("Asia/Manila")).strftime("%Y%m%d%H%M%S%f")
    payload = {
        "user_id": safe_user_id,
        "channel_user_id": safe_user_id,
        "channel": "manychat",
        "user_text": "Please continue based on our previous conversation.",
        "message_id": f"hydration_probe_{run_token}",
        "idempotency_key": f"hydration_probe_{run_token}",
        "reset": 0,
        "save_analytics": 0,
        "return_logs": 1,
        "delivery_mode": "return_only",
    }
    url = f"{str(base_url or '').rstrip('/')}/gulong/v7/chat/tester/hydrated"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.perf_counter()
    response_payload: Any = None
    status_code = 0
    try:
        opener = urllib.request.build_opener(_NoRedirectHandler())
        with opener.open(request, timeout=max(0.1, timeout_s)) as response:
            status_code = int(response.status)
            raw = response.read().decode("utf-8", errors="replace")
        response_payload = json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        failures.append(f"http_status:{status_code}")
    except Exception as exc:
        failures.append(f"transport_error:{type(exc).__name__}")
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    hydration: Mapping[str, Any] = {}
    identity: Dict[str, Any] = {}
    usage: Mapping[str, Any] = {}
    model_calls = 0
    total_tokens = 0
    if (
        status_code
        and status_code != 200
        and f"http_status:{status_code}" not in failures
    ):
        failures.append(f"http_status:{status_code}")
    if isinstance(response_payload, Mapping):
        identity = {
            "release_version": response_payload.get("release_version"),
            "git_sha": response_payload.get("git_sha"),
            "service_environment": response_payload.get("service_environment"),
        }
        if response_payload.get("status") != "success":
            failures.append("runtime_status_not_success")
        debug = response_payload.get("debug")
        if isinstance(debug, Mapping) and isinstance(
            debug.get("conversation_hydration"), Mapping
        ):
            hydration = debug["conversation_hydration"]
        else:
            failures.append("conversation_hydration_metadata_missing")
        if isinstance(debug, Mapping) and isinstance(
            debug.get("llm_usage_summary"), Mapping
        ):
            usage = debug["llm_usage_summary"]
        try:
            model_calls = int(usage.get("llm_call_count") or 0)
            total_tokens = int(usage.get("total_tokens") or 0)
        except (TypeError, ValueError):
            model_calls = 0
            total_tokens = 0
        if model_calls <= 0 or total_tokens <= 0:
            failures.append("positive_model_usage_not_proven")
        for field_name, expected in (
            ("release_version", expected_release),
            ("git_sha", expected_git_sha),
            ("service_environment", expected_environment),
        ):
            if str(response_payload.get(field_name) or "") != str(expected or ""):
                failures.append(f"identity_mismatch:{field_name}")
        delivery = response_payload.get("delivery_result")
        if (
            not isinstance(delivery, Mapping)
            or str(delivery.get("delivery_mode") or "").casefold() != "return_only"
        ):
            failures.append("return_only_delivery_not_proven")
    elif not failures:
        failures.append("response_not_object")

    metadata = hydration.get("counts") if isinstance(hydration, Mapping) else {}
    if not isinstance(metadata, Mapping):
        metadata = hydration.get("metadata") if isinstance(hydration, Mapping) else {}
    metadata = metadata if isinstance(metadata, Mapping) else {}
    if hydration:
        if str(hydration.get("loader_status") or "").casefold() not in {
            "success",
            "loaded",
            "ok",
        }:
            failures.append("manychat_history_loader_not_successful")
        if hydration.get("refresh_attempted") is not True:
            failures.append("manychat_history_refresh_not_attempted")
        if str(hydration.get("source") or "") != "manychat_load_messages":
            failures.append("manychat_history_not_selected_as_source")
        try:
            loaded_count = int(metadata.get("loaded_message_count") or 0)
        except (TypeError, ValueError):
            loaded_count = 0
        if loaded_count <= 0:
            failures.append("manychat_history_empty")
    else:
        loaded_count = 0
    if max_latency_ms > 0 and elapsed_ms > max_latency_ms:
        failures.append(f"latency_ms:{elapsed_ms}>{max_latency_ms}")

    return {
        "id": "manychat_hydrated_tester_turn",
        "component": "runtime_manychat_hydration",
        "passed": not failures,
        "status_code": status_code,
        "elapsed_ms": elapsed_ms,
        "failures": list(dict.fromkeys(failures)),
        "identity": identity,
        "hydration": {
            "source": hydration.get("source") if hydration else None,
            "cache_status": hydration.get("cache_status") if hydration else None,
            "refresh_attempted": hydration.get("refresh_attempted")
            if hydration
            else None,
            "loader_status": hydration.get("loader_status") if hydration else None,
            "loaded_message_count": loaded_count,
            "model_facing_message_count": metadata.get("model_facing_message_count"),
        },
        "usage": {
            "model_call_count": model_calls,
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": total_tokens,
        },
    }


def dependency_config_failures(
    config: Mapping[str, Any],
    *,
    required_components: Iterable[str] = REQUIRED_DEPENDENCY_COMPONENTS,
) -> list[str]:
    """Require every named read dependency before calling the layer complete."""

    probes = [item for item in config.get("probes") or [] if isinstance(item, Mapping)]
    enabled = [item for item in probes if item.get("enabled", True)]
    configured = {str(item.get("component") or "").strip() for item in enabled}
    required = frozenset(str(value) for value in required_components)
    failures = [
        f"missing_dependency_probe:{component}"
        for component in sorted(required - configured)
    ]
    probe_ids = [str(item.get("id") or "").strip() for item in enabled]
    duplicate_ids = sorted(
        {
            probe_id
            for probe_id in probe_ids
            if probe_id and probe_ids.count(probe_id) > 1
        }
    )
    failures.extend(f"duplicate_probe_id:{probe_id}" for probe_id in duplicate_ids)
    return failures


def _matches_type(value: Any, type_name: str) -> bool:
    types = {
        "object": Mapping,
        "array": list,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "null": type(None),
    }
    expected = types.get(type_name)
    return bool(
        expected
        and isinstance(value, expected)
        and not (type_name in {"number", "integer"} and isinstance(value, bool))
    )


def _resolve_env_values(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("$ENV:"):
        name = value[5:]
        if not os.getenv(name):
            raise ValueError(f"required environment variable is unset: {name}")
        return os.environ[name]
    if isinstance(value, Mapping):
        return {str(key): _resolve_env_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_env_values(item) for item in value]
    return value


def _probe_url(spec: Mapping[str, Any], *, default_base_url: str) -> str:
    if spec.get("url"):
        return str(_resolve_env_values(spec["url"]))
    base_url = str(_resolve_env_values(spec.get("base_url") or default_base_url))
    path = str(spec.get("path") or "")
    if not base_url or not path:
        raise ValueError("probe requires url or base_url plus path")
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _probe_headers(spec: Mapping[str, Any]) -> Dict[str, str]:
    headers = {"Accept": "application/json"}
    for name, value in (spec.get("headers") or {}).items():
        headers[str(name)] = str(_resolve_env_values(value))
    if str(spec.get("method") or "GET").upper() == "POST":
        headers.setdefault("Content-Type", "application/json")
    return headers


def _probe_result(
    spec: Mapping[str, Any],
    *,
    failures: Sequence[str],
    elapsed_ms: int,
    status_code: int = 0,
) -> Dict[str, Any]:
    return {
        "id": str(spec.get("id") or "unnamed"),
        "component": str(spec.get("component") or "unknown"),
        "passed": not failures,
        "status_code": status_code,
        "elapsed_ms": elapsed_ms,
        "failures": list(failures),
    }


def _core_probe_specs(args: argparse.Namespace) -> list[Dict[str, Any]]:
    common_paths = ["status", "release_version", "git_sha", "service_environment"]
    equals = {"status": "ok"}
    for key, value in {
        "release_version": args.expected_release,
        "git_sha": args.expected_git_sha,
        "service_environment": args.expected_environment,
    }.items():
        if value:
            equals[key] = value
    return [
        {
            "id": "root_health",
            "component": "runtime_http",
            "method": "GET",
            "path": "/health",
            "expected": {
                "status_codes": [200],
                "root_type": "object",
                "required_paths": [*common_paths, "runtime_generation", "runtime_host"],
                "equals": {**equals, "runtime_generation": "v7"},
                "types": {"runtime_host": "string"},
            },
            "max_latency_ms": args.api_latency_ms,
        },
        {
            "id": "gulong_health",
            "component": "runtime_http",
            "method": "GET",
            "path": "/gulong/health",
            "expected": {
                "status_codes": [200],
                "root_type": "object",
                "required_paths": [
                    *common_paths,
                    "followup",
                    "interactive_discovery.router_configured",
                ],
                "equals": equals,
                "types": {
                    "followup": "object",
                    "interactive_discovery.router_configured": "boolean",
                },
            },
            "max_latency_ms": args.api_latency_ms,
        },
    ]


def _run_subprocess_layer(
    layer: str, command: Sequence[str], *, out_dir: Path
) -> Dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        list(command),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "LANGSMITH_TRACING": "false",
            "LANGCHAIN_TRACING_V2": "false",
        },
        check=False,
    )
    log_path = out_dir / f"{layer}.log"
    log_path.write_text(
        completed.stdout
        + ("\n[stderr]\n" + completed.stderr if completed.stderr else ""),
        encoding="utf-8",
    )
    return {
        "layer": layer,
        **dict(LAYER_METADATA[layer]),
        "status": "passed" if completed.returncode == 0 else "failed",
        "passed": completed.returncode == 0,
        "return_code": completed.returncode,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "log_path": log_path.name,
    }


def _model_command(layer: str, args: argparse.Namespace, out_dir: Path) -> list[str]:
    tier = {
        "model-initial": "smoke",
        "model-in-depth": "promotion",
        "model-complete": "full",
    }[layer]
    command = [
        sys.executable,
        "scripts/runtime_v7_release_candidate_matrix.py",
        "--base-url",
        args.base_url,
        "--tier",
        tier,
        "--timeout-s",
        str(args.model_timeout_s),
        "--workers",
        str(args.model_workers),
        "--out-dir",
        str(out_dir / layer),
    ]
    for flag, value in (
        ("--expected-release", args.expected_release),
        ("--expected-git-sha", args.expected_git_sha),
        ("--expected-environment", args.expected_environment),
        ("--feature-expectations", args.feature_expectations),
        ("--baseline-summary", args.baseline_summary),
        ("--max-core-model-tokens", str(args.max_core_model_tokens)),
        (
            "--max-operational-funnel-tokens",
            str(args.max_operational_funnel_tokens),
        ),
    ):
        if value:
            command.extend([flag, value])
    if layer in {"model-in-depth", "model-complete"}:
        command.append("--require-baseline")
    return command


def _promotion_result_from_model_output(
    layer_out_dir: Path,
    *,
    layer: str,
    baseline_summary: str = "",
    expected_release: str = "",
    expected_git_sha: str = "",
    expected_environment: str = "",
    expected_base_url: str = "",
) -> Dict[str, Any]:
    """Recompute the child gate instead of trusting its stored derived score."""

    candidates = sorted(
        layer_out_dir.glob("runtime_v7_release_candidate_*/summary.json"),
        key=lambda path: path.stat().st_mtime,
    )
    if not candidates:
        return {
            "status": "missing",
            "passed": False,
            "failures": ["model_summary_missing"],
        }
    if len(candidates) != 1:
        return {
            "status": "invalid",
            "passed": False,
            "failures": [f"model_summary_count:{len(candidates)}"],
        }
    path = candidates[-1]
    try:
        artifact = load_json(path)
        baseline = load_json(Path(baseline_summary)) if baseline_summary else None
        health = score_release_candidate(artifact, baseline=baseline)
    except (OSError, ValueError) as exc:
        return {
            "status": "invalid",
            "passed": False,
            "failures": [f"model_summary_invalid:{type(exc).__name__}"],
            "summary_path": str(path.relative_to(layer_out_dir)),
        }
    promotion_status = str(health.get("promotion_status") or "missing")
    expected_tier = {
        "model-initial": "smoke",
        "model-in-depth": "promotion",
        "model-complete": "full",
    }[layer]
    tier_matches = (
        str((artifact.get("evaluation_profile") or {}).get("tier")) == expected_tier
    )
    profile = artifact.get("evaluation_profile") or {}
    outer_expectations = {
        "expected_release": expected_release,
        "expected_git_sha": expected_git_sha,
        "expected_environment": expected_environment,
        "base_url": expected_base_url.rstrip("/"),
    }
    outer_mismatches = [
        key
        for key, value in outer_expectations.items()
        if value and str(profile.get(key) or "").rstrip("/") != value
    ]
    run_id = str(artifact.get("run_id") or "")
    if path.parent.name != f"runtime_v7_release_candidate_{run_id}":
        outer_mismatches.append("run_id_path_binding")
    if layer in {"model-in-depth", "model-complete"}:
        if not baseline_summary:
            outer_mismatches.append("baseline_summary")
        if profile.get("require_compatible_baseline") is not True:
            outer_mismatches.append("require_compatible_baseline")
    accepted_statuses = (
        {"diagnostic_pass"} if layer == "model-initial" else {"ready_for_promotion"}
    )
    return {
        "status": promotion_status,
        "passed": (
            promotion_status in accepted_statuses
            and tier_matches
            and not outer_mismatches
        ),
        "tier_matches": tier_matches,
        "expected_tier": expected_tier,
        "outer_mismatches": outer_mismatches,
        "grade": health.get("grade"),
        "blockers": list(health.get("blockers") or []),
        "warnings": list(health.get("warnings") or []),
        "summary_path": str(path.relative_to(layer_out_dir)),
        "evidence_digest": (
            (artifact.get("artifact_integrity") or {}).get("evidence_digest")
        ),
        "usage": dict(health.get("metered_usage") or {}),
        "operational_funnel": health.get("operational_funnel") or {},
    }


def _config_failure_layer(layer: str, failures: Iterable[str]) -> Dict[str, Any]:
    rows = list(failures)
    return {
        "layer": layer,
        **dict(LAYER_METADATA[layer]),
        "status": "configuration_failed",
        "passed": False,
        "failures": rows,
    }


def summarize_metered_usage(
    results: Sequence[Mapping[str, Any]],
    *,
    max_core_model_tokens: int | None = None,
    max_operational_funnel_tokens: int = int(
        DEFAULT_HEALTH_POLICY["max_operational_funnel_tokens"]
    ),
    max_hydrated_history_tokens: int = 100_000,
    max_total_tokens: int | None = None,
) -> Dict[str, Any]:
    """Meter core, operational, and hydrated usage separately and in total.

    ``max_total_tokens`` is retained as a compatibility alias for the frozen
    core cap; it no longer merges additive operational or hydrated traffic.
    """

    if max_core_model_tokens is None:
        max_core_model_tokens = (
            max_total_tokens
            if max_total_tokens is not None
            else int(DEFAULT_HEALTH_POLICY["max_total_tokens"])
        )
    buckets = {
        "core": {"model_call_count": 0, "total_tokens": 0},
        "operational_funnel": {"model_call_count": 0, "total_tokens": 0},
        "hydrated_history": {"model_call_count": 0, "total_tokens": 0},
    }
    for row in results:
        if str(row.get("cost_class") or "") != "metered_model":
            continue
        if row.get("layer") == "model-hydrated-history":
            probes = row.get("probes") or []
            first_probe = probes[0] if probes and isinstance(probes[0], Mapping) else {}
            usage = first_probe.get("usage") or {}
            target = buckets["hydrated_history"]
        else:
            usage = (row.get("promotion_result") or {}).get("usage") or {}
            core_usage = usage.get("core") if isinstance(usage, Mapping) else None
            operational_usage = (
                usage.get("operational_funnel") if isinstance(usage, Mapping) else None
            )
            # Older sealed child artifacts expose only combined matrix usage.
            # Keep them conservatively chargeable to core rather than dropping
            # any metered traffic from the gate.
            if not isinstance(core_usage, Mapping):
                core_usage = usage
            for target_name, bucket_usage in (
                ("core", core_usage),
                ("operational_funnel", operational_usage),
            ):
                if not isinstance(bucket_usage, Mapping):
                    continue
                buckets[target_name]["model_call_count"] += int(
                    bucket_usage.get("model_call_count") or 0
                )
                buckets[target_name]["total_tokens"] += int(
                    bucket_usage.get("total_tokens") or 0
                )
            continue
        target["model_call_count"] += int(usage.get("model_call_count") or 0)
        target["total_tokens"] += int(usage.get("total_tokens") or 0)
    failures = []
    caps = {
        "core": max(1, int(max_core_model_tokens)),
        "operational_funnel": max(1, int(max_operational_funnel_tokens)),
        "hydrated_history": max(1, int(max_hydrated_history_tokens)),
    }
    for name, bucket in buckets.items():
        bucket["max_total_tokens"] = caps[name]
        if bucket["total_tokens"] > caps[name]:
            failures.append(
                f"{name}_model_tokens:{bucket['total_tokens']}>{caps[name]}"
            )
    model_calls = sum(bucket["model_call_count"] for bucket in buckets.values())
    total_tokens = sum(bucket["total_tokens"] for bucket in buckets.values())
    return {
        "model_call_count": model_calls,
        "total_tokens": total_tokens,
        "max_total_tokens": caps["core"],
        "core": buckets["core"],
        "operational_funnel": buckets["operational_funnel"],
        "hydrated_history": buckets["hydrated_history"],
        "combined": {
            "model_call_count": model_calls,
            "total_tokens": total_tokens,
        },
        "failures": failures,
    }


def main() -> None:
    """Execute only selected layers and emit one consolidated status artifact."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=tuple(PROFILES), default="pr-no-cost")
    parser.add_argument(
        "--layer", action="append", choices=tuple(LAYER_METADATA), default=[]
    )
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-external-apis", action="store_true")
    parser.add_argument("--allow-metered-models", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--api-contracts", default="")
    parser.add_argument("--api-timeout-s", type=float, default=15.0)
    parser.add_argument("--api-latency-ms", type=int, default=5000)
    parser.add_argument("--model-timeout-s", type=float, default=120.0)
    parser.add_argument("--model-workers", type=int, default=1)
    parser.add_argument(
        "--hydrated-history-user-id",
        default=os.getenv("RUNTIME_V7_TESTER_HISTORY_USER_ID", ""),
        help="Allowlisted synthetic ManyChat ID for the protected hydrated tester turn.",
    )
    parser.add_argument(
        "--hydrated-history-auth-env",
        default="FOLLOWUP_WEBHOOK_TOKEN",
        help="Environment variable containing the protected tester Bearer token.",
    )
    parser.add_argument("--hydrated-history-max-latency-ms", type=int, default=95000)
    parser.add_argument(
        "--max-core-model-tokens",
        type=int,
        default=None,
        help="Hard cap for the frozen core matrix (default: 2000000).",
    )
    parser.add_argument(
        "--max-operational-funnel-tokens",
        type=int,
        default=int(DEFAULT_HEALTH_POLICY["max_operational_funnel_tokens"]),
        help="Separate cap for the additive operational-funnel matrix (default: 1200000).",
    )
    parser.add_argument(
        "--max-hydrated-history-tokens",
        type=int,
        default=100_000,
        help="Separate cap for the protected hydrated-history turn (default: 100000).",
    )
    parser.add_argument(
        "--max-total-model-tokens",
        type=int,
        default=None,
        help="Deprecated compatibility alias for --max-core-model-tokens.",
    )
    parser.add_argument("--expected-release", default="")
    parser.add_argument("--expected-git-sha", default="")
    parser.add_argument("--expected-environment", default="")
    parser.add_argument("--feature-expectations", default="")
    parser.add_argument("--baseline-summary", default="")
    parser.add_argument("--out-dir", default="tmp/runtime_v7_layered_health")
    args = parser.parse_args()
    if args.max_core_model_tokens is None:
        args.max_core_model_tokens = (
            args.max_total_model_tokens
            if args.max_total_model_tokens is not None
            else int(DEFAULT_HEALTH_POLICY["max_total_tokens"])
        )
    budget_config_failures = []
    if args.max_total_model_tokens is not None and (
        args.max_total_model_tokens != args.max_core_model_tokens
    ):
        budget_config_failures.append("legacy_core_budget_conflict")
    if not 0 < args.max_core_model_tokens <= DEFAULT_HEALTH_POLICY["max_total_tokens"]:
        budget_config_failures.append("core_model_token_budget_invalid")
    if not 0 < args.max_operational_funnel_tokens <= DEFAULT_HEALTH_POLICY[
        "max_operational_funnel_tokens"
    ]:
        budget_config_failures.append("operational_funnel_token_budget_invalid")
    if not 0 < args.max_hydrated_history_tokens <= 100_000:
        budget_config_failures.append("hydrated_history_token_budget_invalid")

    selected = resolve_layers(profile=args.profile, requested=args.layer)
    if args.list or args.dry_run:
        print(
            json.dumps(
                {
                    "profile": args.profile,
                    "selected_layers": [
                        {"layer": layer, **dict(LAYER_METADATA[layer])}
                        for layer in selected
                    ],
                    "external_api_opt_in": bool(args.allow_external_apis),
                    "metered_opt_in": bool(args.allow_metered_models),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    run_id = datetime.now(ZoneInfo("Asia/Manila")).strftime("%Y%m%d_%H%M%S_%f")
    out_dir = Path(args.out_dir) / f"runtime_v7_health_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[Dict[str, Any]] = []
    for layer in selected:
        if budget_config_failures and str(
            LAYER_METADATA[layer].get("cost_class")
        ) == "metered_model":
            results.append(_config_failure_layer(layer, budget_config_failures))
            continue
        opt_in_failures = layer_opt_in_failures(
            layer,
            allow_external_apis=args.allow_external_apis,
            allow_metered_models=args.allow_metered_models,
        )
        if opt_in_failures:
            results.append(_config_failure_layer(layer, opt_in_failures))
            continue
        if layer == "deterministic-core":
            results.append(
                _run_subprocess_layer(
                    layer,
                    [sys.executable, "-m", "pytest", "-q", *DETERMINISTIC_CORE_TESTS],
                    out_dir=out_dir,
                )
            )
        elif layer == "deterministic-intent-observability":
            results.append(
                _run_subprocess_layer(
                    layer,
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        *DETERMINISTIC_INTENT_OBSERVABILITY_TESTS,
                    ],
                    out_dir=out_dir,
                )
            )
        elif layer == "deterministic-full":
            results.append(
                _run_subprocess_layer(
                    layer,
                    [sys.executable, "-m", "pytest", "-q"],
                    out_dir=out_dir,
                )
            )
        elif layer == "api-core":
            probes = [
                run_http_probe(
                    spec,
                    default_base_url=args.base_url,
                    timeout_s=max(0.1, args.api_timeout_s),
                )
                for spec in _core_probe_specs(args)
            ]
            results.append(
                {
                    "layer": layer,
                    **dict(LAYER_METADATA[layer]),
                    "status": "passed"
                    if all(row["passed"] for row in probes)
                    else "failed",
                    "passed": all(row["passed"] for row in probes),
                    "probes": probes,
                }
            )
        elif layer in API_LAYER_COMPONENTS:
            if not args.api_contracts:
                results.append(_config_failure_layer(layer, ["api_contracts_required"]))
                continue
            try:
                config = json.loads(
                    Path(args.api_contracts).read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                results.append(
                    _config_failure_layer(
                        layer,
                        [f"api_contracts_invalid:{type(exc).__name__}"],
                    )
                )
                continue
            if not isinstance(config, Mapping):
                results.append(
                    _config_failure_layer(layer, ["api_contracts_not_object"])
                )
                continue
            required_components = API_LAYER_COMPONENTS[layer]
            config_failures = dependency_config_failures(
                config,
                required_components=required_components,
            )
            if config_failures:
                results.append(_config_failure_layer(layer, config_failures))
                continue
            probes = [
                run_http_probe(
                    spec,
                    default_base_url=args.base_url,
                    timeout_s=max(0.1, args.api_timeout_s),
                )
                for spec in config.get("probes") or []
                if (
                    isinstance(spec, Mapping)
                    and spec.get("enabled", True)
                    and str(spec.get("component") or "") in required_components
                )
            ]
            results.append(
                {
                    "layer": layer,
                    **dict(LAYER_METADATA[layer]),
                    "status": "passed"
                    if all(row["passed"] for row in probes)
                    else "failed",
                    "passed": all(row["passed"] for row in probes),
                    "probes": probes,
                }
            )
        elif layer == "model-hydrated-history":
            auth_env = str(args.hydrated_history_auth_env or "").strip()
            auth_token = os.getenv(auth_env, "") if auth_env else ""
            probe = run_hydrated_history_probe(
                base_url=args.base_url,
                user_id=args.hydrated_history_user_id,
                auth_token=auth_token,
                timeout_s=max(0.1, args.model_timeout_s),
                max_latency_ms=max(1, args.hydrated_history_max_latency_ms),
                expected_release=args.expected_release,
                expected_git_sha=args.expected_git_sha,
                expected_environment=args.expected_environment,
            )
            budget_failures = []
            if int((probe.get("usage") or {}).get("total_tokens") or 0) > args.max_hydrated_history_tokens:
                budget_failures.append(
                    "hydrated_history_model_tokens:"
                    f"{int((probe.get('usage') or {}).get('total_tokens') or 0)}"
                    f">{args.max_hydrated_history_tokens}"
                )
            results.append(
                {
                    "layer": layer,
                    **dict(LAYER_METADATA[layer]),
                    "status": "passed" if probe["passed"] and not budget_failures else "failed",
                    "passed": bool(probe["passed"] and not budget_failures),
                    "probes": [probe],
                    "budget_failures": budget_failures,
                    "credential_alias": auth_env,
                }
            )
        else:
            complete_missing = []
            if (
                layer in {"model-in-depth", "model-complete"}
                and not args.baseline_summary
            ):
                complete_missing.append("baseline_summary_required")
            for field_name, value in (
                ("expected_release", args.expected_release),
                ("expected_git_sha", args.expected_git_sha),
                ("expected_environment", args.expected_environment),
            ):
                if not str(value or "").strip():
                    complete_missing.append(f"{field_name}_required")
            if complete_missing:
                results.append(_config_failure_layer(layer, complete_missing))
                continue
            layer_result = _run_subprocess_layer(
                layer,
                _model_command(layer, args, out_dir),
                out_dir=out_dir,
            )
            promotion_result = _promotion_result_from_model_output(
                out_dir / layer,
                layer=layer,
                baseline_summary=args.baseline_summary,
                expected_release=args.expected_release,
                expected_git_sha=args.expected_git_sha,
                expected_environment=args.expected_environment,
                expected_base_url=args.base_url,
            )
            layer_result["promotion_result"] = promotion_result
            layer_result["passed"] = bool(
                layer_result["passed"] and promotion_result["passed"]
            )
            layer_result["status"] = "passed" if layer_result["passed"] else "failed"
            results.append(layer_result)

    metered_usage = summarize_metered_usage(
        results,
        max_core_model_tokens=args.max_core_model_tokens,
        max_operational_funnel_tokens=args.max_operational_funnel_tokens,
        max_hydrated_history_tokens=args.max_hydrated_history_tokens,
    )

    artifact = {
        "schema_version": "runtime_v7_layered_health_v1",
        "run_id": run_id,
        "profile": args.profile,
        "selected_layers": selected,
        "base_url": args.base_url,
        "passed": (
            all(row.get("passed") is True for row in results)
            and not metered_usage["failures"]
        ),
        "layer_results": results,
        "metered_usage": metered_usage,
        "limits": [
            "API layers make real external requests and may consume provider or infrastructure quota even though they make no LLM calls",
            "API reads do not prove tag, custom-field, note, or delivery mutation",
            "deterministic intent/observability checks prove code contracts, not deployed analytics persistence",
            "the protected hydrated-history turn is metered, transcript-redacted, and included in the outer total-token budget",
            "model-in-depth and model-complete require a compatible baseline and an automated green result from the exact pre-verified corpus",
        ],
    }
    artifact_path = out_dir / "summary.json"
    artifact_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    bundle_files: Dict[str, Any] = {}
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file() or path.name == "run_manifest.json":
            continue
        relative = path.relative_to(out_dir).as_posix()
        bundle_files[relative] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
    manifest_path = out_dir / "run_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "runtime_v7_layered_health_bundle_v1",
                "run_id": run_id,
                "created_at": datetime.now(ZoneInfo("Asia/Manila")).isoformat(),
                "profile": args.profile,
                "environment": args.expected_environment,
                "release_version": args.expected_release,
                "git_sha": args.expected_git_sha,
                "passed": artifact["passed"],
                "files": bundle_files,
                "external_storage_key": (
                    f"runtime-v7-evaluator/{args.expected_environment or 'local'}/"
                    f"{datetime.now(ZoneInfo('Asia/Manila')).date().isoformat()}/{run_id}/"
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "artifact": str(artifact_path.resolve()),
                "run_manifest": str(manifest_path.resolve()),
                "passed": artifact["passed"],
                "layers": [
                    {"layer": row["layer"], "status": row["status"]} for row in results
                ],
            },
            ensure_ascii=False,
        )
    )
    if not artifact["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
