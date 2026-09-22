"""Focused regression coverage for the tester-only provider-call ceiling."""

from __future__ import annotations

import pytest

from apps.api.routers.gulong import ChatRequestPayload, _runtime_request
from runtime_v7.api_runtime import RuntimeV7APIRequest, _tester_provider_call_guard, build_runtime_v7_harness
from runtime_v7.brand_knowledge import BrandKnowledgeRepository
from runtime_v7.llm_gateway import (
    RuntimeV7LLMGateway,
    RuntimeV7LLMGatewayConfig,
    RuntimeV7ProviderCallGuard,
    RuntimeV7ProviderCallLimitExceeded,
)
from runtime_v7.promo_catalog import PromoCatalogRepository


class _FakeLiteLLMClient:
    def __init__(self) -> None:
        self.completion_calls = []
        self.embedding_calls = []

    async def acompletion(self, **kwargs):
        self.completion_calls.append(dict(kwargs))
        return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    def embedding(self, **kwargs):
        self.embedding_calls.append(dict(kwargs))
        return {"data": [{"embedding": [1.0, 0.0]}]}


def _gateway(*, client: _FakeLiteLLMClient, guard: RuntimeV7ProviderCallGuard, **config):
    return RuntimeV7LLMGateway(
        config=RuntimeV7LLMGatewayConfig(
            model="gemini/gemini-2.5-flash-lite",
            api_key_env="MISSING_KEY",
            transport_retry_backoff_s=0,
            provider_call_guard=guard,
            **config,
        ),
        client=client,
    )


def test_provider_call_guard_counts_completion_and_embedding_and_stops_before_provider_io():
    client = _FakeLiteLLMClient()
    guard = RuntimeV7ProviderCallGuard(max_provider_calls=2)
    gateway = _gateway(client=client, guard=guard)

    gateway.complete(messages=[{"role": "user", "content": "hello"}])
    gateway.embed(texts=["tire warranty"])

    with pytest.raises(RuntimeV7ProviderCallLimitExceeded) as raised:
        gateway.complete(messages=[{"role": "user", "content": "one more"}])

    assert len(client.completion_calls) == 1
    assert len(client.embedding_calls) == 1
    assert guard.provider_call_count == 2
    assert raised.value.diagnostic() == {
        "code": "runtime_v7_tester_model_call_limit_exceeded",
        "max_provider_calls": 2,
        "attempted_provider_calls": 3,
        "reservation_ordinal": 3,
    }


def test_provider_call_guard_counts_transport_retries_before_retrying():
    class _TransientClient(_FakeLiteLLMClient):
        async def acompletion(self, **kwargs):
            self.completion_calls.append(dict(kwargs))
            raise RuntimeError('{"code": 503, "status": "UNAVAILABLE"}')

    client = _TransientClient()
    gateway = _gateway(
        client=client,
        guard=RuntimeV7ProviderCallGuard(max_provider_calls=1),
        max_transport_retries=1,
    )

    with pytest.raises(RuntimeV7ProviderCallLimitExceeded, match="tester_model_call_limit") as raised:
        gateway.complete(messages=[{"role": "user", "content": "hello"}])

    assert len(client.completion_calls) == 1
    assert raised.value.attempted_provider_calls == 2


def test_provider_call_guard_counts_context_cache_fallback_before_retrying():
    class _CacheConflictClient(_FakeLiteLLMClient):
        async def acompletion(self, **kwargs):
            self.completion_calls.append(dict(kwargs))
            raise RuntimeError(
                "CachedContent can not be used with GenerateContent request setting system_instruction."
            )

    client = _CacheConflictClient()
    gateway = _gateway(
        client=client,
        guard=RuntimeV7ProviderCallGuard(max_provider_calls=1),
        enable_context_cache=True,
    )

    with pytest.raises(RuntimeV7ProviderCallLimitExceeded) as raised:
        gateway.complete(
            messages=[
                {"role": "system", "content": "stable prompt " * 900},
                {"role": "user", "content": "hello"},
            ]
        )

    assert len(client.completion_calls) == 1
    assert raised.value.attempted_provider_calls == 2


def test_tester_call_guard_is_server_marked_and_defaults_to_ten(monkeypatch):
    monkeypatch.delenv("RUNTIME_V7_TESTER_MAX_PROVIDER_CALLS", raising=False)
    normal = RuntimeV7APIRequest(user_id="u", user_text="hello")
    tester = RuntimeV7APIRequest(user_id="u", user_text="hello", tester=True)

    assert _tester_provider_call_guard(normal) is None
    assert _tester_provider_call_guard(tester).max_provider_calls == 10

    monkeypatch.setenv("RUNTIME_V7_TESTER_MAX_PROVIDER_CALLS", "0")
    assert _tester_provider_call_guard(tester).max_provider_calls is None


def test_provider_call_guard_allows_nine_calls_at_ten_and_rejects_the_ninth_at_eight():
    client = _FakeLiteLLMClient()
    gateway = _gateway(
        client=client,
        guard=RuntimeV7ProviderCallGuard(max_provider_calls=10),
    )

    for _ in range(9):
        gateway.complete(messages=[{"role": "user", "content": "hello"}])

    assert len(client.completion_calls) == 9

    limited_client = _FakeLiteLLMClient()
    limited_gateway = _gateway(
        client=limited_client,
        guard=RuntimeV7ProviderCallGuard(max_provider_calls=8),
    )
    for _ in range(8):
        limited_gateway.complete(messages=[{"role": "user", "content": "hello"}])

    with pytest.raises(RuntimeV7ProviderCallLimitExceeded) as raised:
        limited_gateway.complete(messages=[{"role": "user", "content": "hello"}])

    assert len(limited_client.completion_calls) == 8
    assert raised.value.diagnostic()["reservation_ordinal"] == 9


def test_provider_call_guard_diagnostics_keep_only_safe_call_origin_metadata():
    client = _FakeLiteLLMClient()
    gateway = _gateway(
        client=client,
        guard=RuntimeV7ProviderCallGuard(max_provider_calls=0),
    )
    prompt = "customer prompt must never appear in diagnostics"
    secret = "provider-payload-secret"

    with pytest.raises(RuntimeV7ProviderCallLimitExceeded) as raised:
        gateway.complete(
            messages=[{"role": "user", "content": prompt}],
            metadata={
                "component": "runtime_v7_final_composer",
                "phase": "format_retry",
                "provider_payload": secret,
            },
        )

    diagnostic = raised.value.diagnostic()

    assert diagnostic == {
        "code": "runtime_v7_tester_model_call_limit_exceeded",
        "max_provider_calls": 0,
        "attempted_provider_calls": 1,
        "reservation_ordinal": 1,
        "component": "runtime_v7_final_composer",
        "phase": "format_retry",
    }
    assert prompt not in str(diagnostic)
    assert secret not in str(diagnostic)

    with pytest.raises(RuntimeV7ProviderCallLimitExceeded) as embedding_raised:
        gateway.embed(
            texts=[prompt],
            metadata={
                "component": "runtime_v7_product_faq",
                "phase": "rag_query_embedding",
                "provider_payload": secret,
            },
        )

    embedding_diagnostic = embedding_raised.value.diagnostic()
    assert embedding_diagnostic["component"] == "runtime_v7_product_faq"
    assert embedding_diagnostic["phase"] == "rag_query_embedding"
    assert prompt not in str(embedding_diagnostic)
    assert secret not in str(embedding_diagnostic)


def test_public_chat_payload_cannot_enable_the_tester_guard_itself():
    payload = ChatRequestPayload(user_id="u", user_text="hello", flow_context={"tester": True})
    normal = _runtime_request(
        payload,
        user_id="u",
        message_id="m",
        idempotency_key="m",
        delivery_mode="return_only",
        tester=False,
    )
    tester = _runtime_request(
        payload,
        user_id="u",
        message_id="m",
        idempotency_key="m",
        delivery_mode="return_only",
        tester=True,
    )

    assert normal.tester is False
    assert tester.tester is True
    assert normal.flow_context["tester"] is True


def test_harness_shares_one_guard_with_main_and_specialized_gateway_clients(monkeypatch):
    monkeypatch.delenv("RUNTIME_V7_MAIN_TRANSPORT_RETRIES", raising=False)
    monkeypatch.delenv("RUNTIME_V7_MAIN_TRANSPORT_RETRY_BACKOFF_S", raising=False)
    guard = RuntimeV7ProviderCallGuard(max_provider_calls=8)
    harness = build_runtime_v7_harness("session", {}, "trace", provider_call_guard=guard)

    assert harness.model_client.config.provider_call_guard is guard
    assert harness.model_client.config.max_transport_retries == 1
    assert harness.model_client.config.transport_retry_backoff_s == 0.75
    assert harness.memory_generator.model_client.gateway.config.provider_call_guard is guard
    assert harness.background_signal_model_client.gateway.config.provider_call_guard is guard
    assert harness.image_evidence_extractor.model_client.gateway.config.provider_call_guard is guard


def test_main_transport_retry_setting_is_bounded(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_MAIN_TRANSPORT_RETRIES", "99")
    monkeypatch.setenv("RUNTIME_V7_MAIN_TRANSPORT_RETRY_BACKOFF_S", "1.25")

    harness = build_runtime_v7_harness("session", {}, "trace")

    assert harness.model_client.config.max_transport_retries == 2
    assert harness.model_client.config.transport_retry_backoff_s == 1.25


def test_direct_vertex_embedding_boundaries_share_the_tester_ceiling():
    class _Embedder:
        def __init__(self) -> None:
            self.calls = 0

        def embed(self, text, *, task_type):
            self.calls += 1
            return [1.0, 0.0]

    guard = RuntimeV7ProviderCallGuard(max_provider_calls=0)
    brand_embedder = _Embedder()
    brand_repository = BrandKnowledgeRepository(
        firestore_client=object(),
        embedder=brand_embedder,
        provider_call_guard=guard,
    )
    with pytest.raises(RuntimeV7ProviderCallLimitExceeded):
        brand_repository.semantic_profiles(version_id="v1", query_text="warranty", limit=1)

    promo_embedder = _Embedder()
    promo_repository = PromoCatalogRepository(
        firestore_client=object(),
        embedder=promo_embedder,
        provider_call_guard=guard,
    )
    with pytest.raises(RuntimeV7ProviderCallLimitExceeded):
        promo_repository.vector_candidates(catalog_version_id="v1", query_text="promo", limit=1)

    assert brand_embedder.calls == 0
    assert promo_embedder.calls == 0
