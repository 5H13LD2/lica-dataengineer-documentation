"""Tests for selective Runtime V7 health-layer orchestration."""

from __future__ import annotations

import json

import scripts.runtime_v7_layered_health_runner as health_runner


def test_profiles_keep_no_llm_and_metered_layers_explicit() -> None:
    assert health_runner.resolve_layers(
        profile="daily-no-llm", requested=[]
    ) == ["api-core", "api-commerce", "api-channel-reads"]
    assert health_runner.resolve_layers(
        profile="complete", requested=["model-initial", "api-core", "model-initial"]
    ) == ["model-initial", "api-core"]
    assert health_runner.LAYER_METADATA["model-initial"]["cost_class"] == (
        "metered_model"
    )
    assert "model-hydrated-history" in health_runner.resolve_layers(
        profile="pre-staging", requested=[]
    )
    assert health_runner.LAYER_METADATA["model-hydrated-history"]["cost_class"] == (
        "metered_model"
    )
    assert health_runner.LAYER_METADATA["deterministic-full"]["cost_class"] == (
        "local_no_metered_calls"
    )
    assert health_runner.LAYER_METADATA["api-commerce"]["cost_class"] == (
        "external_api_no_llm"
    )


def test_external_api_and_metered_model_layers_require_separate_opt_in() -> None:
    assert health_runner.layer_opt_in_failures(
        "api-commerce",
        allow_external_apis=False,
        allow_metered_models=True,
    ) == ["external_api_opt_in_required"]
    assert health_runner.layer_opt_in_failures(
        "model-initial",
        allow_external_apis=True,
        allow_metered_models=False,
    ) == ["metered_model_opt_in_required"]
    assert health_runner.layer_opt_in_failures(
        "deterministic-core",
        allow_external_apis=False,
        allow_metered_models=False,
    ) == []


def test_json_contract_checks_schema_values_and_non_empty_paths() -> None:
    payload = {
        "status": "ok",
        "data": {"items": [{"id": 1}]},
        "enabled": True,
    }

    assert health_runner.validate_json_contract(
        payload,
        {
            "root_type": "object",
            "required_paths": ["data.items.0.id"],
            "equals": {"status": "ok"},
            "types": {"data.items": "array", "enabled": "boolean"},
            "non_empty": ["data.items"],
        },
    ) == []

    failures = health_runner.validate_json_contract(
        payload,
        {
            "equals": {"status": "error"},
            "types": {"data.items": "object"},
            "non_empty": ["missing"],
        },
    )

    assert failures == [
        "value_mismatch:status",
        "type_mismatch:data.items:object",
        "missing_path:missing",
    ]


def test_dependency_layer_fails_closed_when_component_is_not_configured() -> None:
    config = {
        "probes": [
            {
                "id": component,
                "component": component,
                "enabled": component != "installation_slots",
            }
            for component in sorted(health_runner.REQUIRED_DEPENDENCY_COMPONENTS)
        ]
    }

    assert health_runner.dependency_config_failures(config) == [
        "missing_dependency_probe:installation_slots"
    ]


def test_mutation_like_api_probe_is_rejected_before_transport(monkeypatch) -> None:
    called = False

    def fake_urlopen(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("transport must not run")

    monkeypatch.setattr(
        health_runner.urllib.request,
        "build_opener",
        lambda *_args: type("Opener", (), {"open": fake_urlopen})(),
    )

    result = health_runner.run_http_probe(
        {
            "id": "tag-write",
            "component": "manychat_tags",
            "method": "POST",
            "read_only": True,
            "path": "/subscriber/addTagByName",
            "expected": {"equals": {"status": "success"}},
            "max_latency_ms": 1000,
        },
        default_base_url="https://example.test",
        timeout_s=1,
    )

    assert called is False
    assert result["passed"] is False
    assert "mutation_path_rejected:addtag" in result["failures"]
    assert "endpoint_not_allowlisted:manychat_tags:POST" not in result["failures"]


def test_http_probe_reports_contract_evidence_without_response_body(monkeypatch) -> None:
    handlers = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {"status": "ok", "data": {"custom_fields": ["secret-value"]}}
            ).encode("utf-8")

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response()

    def fake_build_opener(*items):
        handlers.extend(items)
        return Opener()

    monkeypatch.setattr(health_runner.urllib.request, "build_opener", fake_build_opener)

    result = health_runner.run_http_probe(
        {
            "id": "profile-read",
            "component": "manychat_profile",
            "method": "GET",
            "path": "/subscriber/getInfo",
            "expected": {
                "status_codes": [200],
                "equals": {"status": "ok"},
                "types": {"data.custom_fields": "array"},
            },
            "max_latency_ms": 1000,
        },
        default_base_url="https://example.test",
        timeout_s=1,
    )

    assert result == {
        "id": "profile-read",
        "component": "manychat_profile",
        "passed": True,
        "status_code": 200,
        "elapsed_ms": result["elapsed_ms"],
        "failures": [],
    }
    assert "secret-value" not in json.dumps(result)
    assert any(
        isinstance(item, health_runner._NoRedirectHandler) for item in handlers
    )


def test_post_probe_requires_explicit_read_only_declaration() -> None:
    assert health_runner.validate_probe_spec(
        {
            "id": "product",
            "component": "product_search",
            "method": "POST",
            "path": "/shop",
            "expected": {"types": {"data": "array"}},
            "max_latency_ms": 1000,
        }
    ) == ["post_requires_read_only_true"]


def test_component_endpoint_allowlist_rejects_mislabeled_health_probe() -> None:
    failures = health_runner.validate_probe_spec(
        {
            "id": "fake-product",
            "component": "product_search",
            "method": "GET",
            "path": "/health",
            "expected": {"equals": {"status": "ok"}},
            "max_latency_ms": 1000,
        },
        resolved_url="https://example.test/health",
    )

    assert failures == ["endpoint_not_allowlisted:product_search:GET"]


def test_resolved_environment_url_is_validated_before_transport(monkeypatch) -> None:
    called = False

    class Opener:
        def open(self, *_args, **_kwargs):
            nonlocal called
            called = True
            raise AssertionError("transport must not run")

    monkeypatch.setenv(
        "RUNTIME_HEALTH_PROFILE_URL",
        "https://example.test/subscriber/setCustomFieldByName",
    )
    monkeypatch.setattr(
        health_runner.urllib.request, "build_opener", lambda *_args: Opener()
    )

    result = health_runner.run_http_probe(
        {
            "id": "profile-read",
            "component": "manychat_profile",
            "method": "GET",
            "url": "$ENV:RUNTIME_HEALTH_PROFILE_URL",
            "expected": {"types": {"data": "object"}},
            "max_latency_ms": 1000,
        },
        default_base_url="https://unused.test",
        timeout_s=1,
    )

    assert called is False
    assert result["passed"] is False
    assert "mutation_path_rejected:setcustomfield" in result["failures"]


def test_payment_catalog_read_is_allowlisted() -> None:
    assert health_runner.validate_probe_spec(
        {
            "id": "payment-catalog",
            "component": "payment_catalog",
            "method": "GET",
            "path": "/payment/list",
            "expected": {"root_type": "array", "non_empty": ["0"]},
            "max_latency_ms": 1000,
        },
        resolved_url="https://example.test/payment/list",
    ) == []


def test_hydrated_history_probe_keeps_only_bounded_metadata(monkeypatch) -> None:
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "status": "success",
                    "release_version": "candidate",
                    "git_sha": "abc1234",
                    "service_environment": "staging",
                    "response": {"version": "private customer text"},
                    "delivery_result": {
                        "status": "skipped",
                        "delivery_mode": "return_only",
                    },
                    "debug": {
                        "llm_usage_summary": {
                            "llm_call_count": 2,
                            "prompt_tokens": 100,
                            "completion_tokens": 20,
                            "total_tokens": 120,
                        },
                        "conversation_hydration": {
                            "source": "manychat_load_messages",
                            "cache_status": "refreshed",
                            "refresh_attempted": True,
                            "loader_status": "success",
                            "metadata": {
                                "loaded_message_count": 5,
                                "model_facing_message_count": 5,
                            },
                        },
                        "ingress_conversation_history": ["private transcript"],
                    },
                }
            ).encode("utf-8")

    class Opener:
        def open(self, request, **_kwargs):
            captured["authorization"] = request.headers.get("Authorization")
            return Response()

    monkeypatch.setattr(
        health_runner.urllib.request, "build_opener", lambda *_args: Opener()
    )

    result = health_runner.run_hydrated_history_probe(
        base_url="https://candidate.example",
        user_id="synthetic-account",
        auth_token="secret-token",
        timeout_s=1,
        max_latency_ms=1000,
        expected_release="candidate",
        expected_git_sha="abc1234",
        expected_environment="staging",
    )

    assert result["passed"] is True
    assert result["hydration"] == {
        "source": "manychat_load_messages",
        "cache_status": "refreshed",
        "refresh_attempted": True,
        "loader_status": "success",
        "loaded_message_count": 5,
        "model_facing_message_count": 5,
    }
    assert result["usage"] == {
        "model_call_count": 2,
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
    }
    assert captured["authorization"] == "Bearer secret-token"
    serialized = json.dumps(result)
    assert "secret-token" not in serialized
    assert "private customer text" not in serialized
    assert "private transcript" not in serialized


def test_hydrated_history_probe_fails_closed_before_transport(monkeypatch) -> None:
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("transport must not run")

    monkeypatch.setattr(
        health_runner.urllib.request, "build_opener", fail_if_called
    )

    result = health_runner.run_hydrated_history_probe(
        base_url="https://candidate.example",
        user_id="",
        auth_token="",
        timeout_s=1,
        max_latency_ms=1000,
        expected_release="",
        expected_git_sha="",
        expected_environment="",
    )

    assert called is False
    assert result["passed"] is False
    assert result["failures"] == [
        "hydrated_history_user_id_required",
        "hydrated_history_auth_token_required",
        "expected_release_required",
        "expected_git_sha_required",
        "expected_environment_required",
    ]


def test_metered_usage_budgets_core_operational_and_hydration_separately() -> None:
    result = health_runner.summarize_metered_usage(
        [
            {
                "layer": "model-hydrated-history",
                "cost_class": "metered_model",
                "probes": [
                    {"usage": {"model_call_count": 2, "total_tokens": 125000}}
                ],
            },
            {
                "layer": "model-complete",
                "cost_class": "metered_model",
                "promotion_result": {
                    "usage": {
                        "core": {"model_call_count": 80, "total_tokens": 1900000},
                        "operational_funnel": {
                            "model_call_count": 20,
                            "total_tokens": 1100000,
                        },
                        "model_call_count": 100,
                        "total_tokens": 3000000,
                    }
                },
            },
            {"layer": "api-core", "cost_class": "external_api_no_llm"},
        ],
        max_total_tokens=2000000,
        max_operational_funnel_tokens=1200000,
        max_hydrated_history_tokens=100000,
    )

    assert result == {
        "model_call_count": 102,
        "total_tokens": 3125000,
        "max_total_tokens": 2000000,
        "core": {
            "model_call_count": 80,
            "total_tokens": 1900000,
            "max_total_tokens": 2000000,
        },
        "operational_funnel": {
            "model_call_count": 20,
            "total_tokens": 1100000,
            "max_total_tokens": 1200000,
        },
        "hydrated_history": {
            "model_call_count": 2,
            "total_tokens": 125000,
            "max_total_tokens": 100000,
        },
        "combined": {"model_call_count": 102, "total_tokens": 3125000},
        "failures": ["hydrated_history_model_tokens:125000>100000"],
    }


def test_layered_runner_recomputes_and_rejects_forged_child_green(tmp_path) -> None:
    child = tmp_path / "runtime_v7_release_candidate_1"
    child.mkdir()
    (child / "summary.json").write_text(
        json.dumps(
            {
                "promotion_health": {
                    "grade": "green",
                    "promotion_status": "ready_for_promotion",
                }
            }
        ),
        encoding="utf-8",
    )

    result = health_runner._promotion_result_from_model_output(
        tmp_path,
        layer="model-complete",
    )

    assert result["passed"] is False
    assert result["status"] == "blocked"
    assert "artifact_integrity_digest_missing" in result["blockers"]
