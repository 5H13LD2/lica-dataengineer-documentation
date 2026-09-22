"""Ingress contract tests for the isolated Runtime V7 hydration probe."""

from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.routers import gulong


class _FakeResult:
    def __init__(self) -> None:
        self.turn_record = {
            "llm_usage_summary": {
                "llm_call_count": 2,
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "private_prompt": "must not be exposed",
            },
            "conversation_hydration": {
                "source": "manychat_load_messages",
                "cache_status": "refreshed",
                "refresh_attempted": True,
                "loader_status": "success",
                "metadata": {
                    "cached_message_count": 2,
                    "loaded_message_count": 4,
                    "segment_message_count": 3,
                    "model_facing_message_count": 2,
                    "message_age_days": 30,
                    "private_transcript": "private hydrated customer message",
                },
            }
        }

    def to_payload(self, *, include_debug: bool = False) -> dict:
        return {
            "status": "success",
            "response": {"bubble1": "Safe probe response."},
            "content_messages": [{"type": "text", "text": "Safe probe response."}],
            "debug": {"turn_trace": {"transcript": "private hydrated customer message"}},
            "turn_trace_summary": {"transcript": "private hydrated customer message"},
        }


class _FakeRuntimeService:
    instances: list["_FakeRuntimeService"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.requests = []
        self.__class__.instances.append(self)

    async def handle(self, request, *, request_id: str):
        self.requests.append((request, request_id))
        return _FakeResult()


def _tester_request(**overrides) -> gulong.ChatTesterRequestPayload:
    values = {"user_text": "Please check my recent conversation."}
    values.update(overrides)
    return gulong.ChatTesterRequestPayload(**values)


def _hydrated_request(**overrides) -> gulong.HydratedChatTesterRequestPayload:
    values = {"user_text": "Please check my recent conversation."}
    values.update(overrides)
    return gulong.HydratedChatTesterRequestPayload(**values)


def test_existing_tester_routes_keep_manychat_history_fetch_disabled(monkeypatch) -> None:
    _FakeRuntimeService.instances = []
    monkeypatch.setattr(gulong, "RuntimeV7APIService", _FakeRuntimeService)

    asyncio.run(gulong.chat_tester(_tester_request()))
    asyncio.run(gulong.chat_v7_tester_compat(_tester_request()))

    assert len(_FakeRuntimeService.instances) == 2
    for service in _FakeRuntimeService.instances:
        assert service.kwargs["fetch_manychat_profile"] is False
        assert service.kwargs["fetch_manychat_messages"] is False
        assert service.kwargs["analytics_gateway"] is None
        assert service.kwargs["delivery_mode"] == "return_only"
        assert service.requests[0][0].tester is True


def test_hydrated_tester_enables_only_manychat_history_fetch_and_bounds_debug(monkeypatch) -> None:
    _FakeRuntimeService.instances = []
    monkeypatch.setattr(gulong, "RuntimeV7APIService", _FakeRuntimeService)

    result = asyncio.run(
        gulong._handle_hydrated_tester_chat(
            _hydrated_request(delivery_mode="send_content", return_logs=0)
        )
    )

    service = _FakeRuntimeService.instances[0]
    assert service.kwargs["fetch_manychat_profile"] is False
    assert service.kwargs["fetch_manychat_messages"] is True
    assert service.kwargs["analytics_gateway"] is None
    assert service.kwargs["delivery_mode"] == "return_only"
    assert service.requests[0][0].tester is True
    assert result["debug"] == {
        "conversation_hydration": {
            "source": "manychat_load_messages",
            "cache_status": "refreshed",
            "refresh_attempted": True,
            "loader_status": "success",
            "counts": {
                "cached_message_count": 2,
                "loaded_message_count": 4,
                "segment_message_count": 3,
                "model_facing_message_count": 2,
                "message_age_days": 30,
            },
        },
        "llm_usage_summary": {
            "llm_call_count": 2,
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
        },
    }
    assert result["delivery_result"]["delivery_mode"] == "return_only"
    assert "turn_trace_summary" not in result
    assert "response" not in result
    assert "content_messages" not in result
    assert "private hydrated customer message" not in json.dumps(result)
    assert "Safe probe response" not in json.dumps(result)
    assert "must not be exposed" not in json.dumps(result)


def test_hydrated_tester_uses_followup_bearer_authentication(monkeypatch) -> None:
    monkeypatch.setenv("FOLLOWUP_WEBHOOK_TOKEN", "hydrated-probe-secret")
    handled = []

    async def fake_handle(request):
        handled.append(request)
        return {"status": "success", "debug": {"conversation_hydration": {}}}

    monkeypatch.setattr(gulong, "_handle_hydrated_tester_chat", fake_handle)
    client = TestClient(create_app())
    body = {"user_text": "Probe history."}

    assert client.post("/gulong/v7/chat/tester/hydrated", json=body).status_code == 401
    assert (
        client.post(
            "/gulong/v7/chat/tester/hydrated",
            json=body,
            headers={"Authorization": "Bearer wrong"},
        ).status_code
        == 401
    )
    accepted = client.post(
        "/gulong/v7/chat/tester/hydrated",
        json=body,
        headers={"Authorization": "Bearer hydrated-probe-secret"},
    )

    assert accepted.status_code == 200
    assert accepted.json()["status"] == "success"
    assert len(handled) == 1


def test_hydrated_tester_blocks_untrusted_or_injected_requests_before_runtime_io(monkeypatch) -> None:
    class _UnexpectedRuntimeService:
        def __init__(self, **_kwargs) -> None:
            raise AssertionError("blocked hydration probes must not construct the runtime service")

    monkeypatch.setattr(gulong, "RuntimeV7APIService", _UnexpectedRuntimeService)
    cases = (
        (_hydrated_request(channel="web"), "hydrated_tester_requires_manychat_channel"),
        (
            _hydrated_request(user_id="other-synthetic", channel_user_id="other-synthetic"),
            "hydrated_tester_user_not_allowlisted",
        ),
        (
            _hydrated_request(user_id="4843256405786522", channel_user_id="different-account"),
            "hydrated_tester_requires_matching_user_ids",
        ),
        (
            _hydrated_request(conversation_history=[{"role": "user", "content": "injected transcript"}]),
            "hydrated_tester_request_history_not_allowed",
        ),
        (
            _hydrated_request(conversation_history=[]),
            "hydrated_tester_request_history_not_allowed",
        ),
        (_hydrated_request(reset=1), "hydrated_tester_reset_not_allowed"),
    )

    for request, expected_message in cases:
        result = asyncio.run(gulong._handle_hydrated_tester_chat(request))
        assert result["status"] == "error"
        assert result["message"] == expected_message


def test_hydrated_tester_history_allowlist_defaults_safely_and_is_configurable(monkeypatch) -> None:
    monkeypatch.delenv("RUNTIME_V7_TESTER_HISTORY_USER_ALLOWLIST", raising=False)
    assert gulong._hydrated_tester_history_user_allowlist() == {gulong.DEFAULT_TEST_USER_ID}

    monkeypatch.setenv("RUNTIME_V7_TESTER_HISTORY_USER_ALLOWLIST", "synthetic-a, synthetic-b")
    assert gulong._hydrated_tester_history_user_allowlist() == {"synthetic-a", "synthetic-b"}
