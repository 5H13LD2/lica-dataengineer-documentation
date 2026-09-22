import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from apps.api.routers import gulong as gulong_router
from runtime.gateways.analytics_gateway import MemoryAnalyticsGateway
from runtime.gateways.sessions_gateway import SessionsGateway, SessionsGatewayConfig
from runtime.shared.types import MessageTurn, UserDoc
from runtime.storage.session_store import MemorySessionStore
from runtime.utils.time_utils import now_manila_str
from runtime_v7.api_runtime import (
    RuntimeV7APIRequest,
    RuntimeV7APIResult,
    RuntimeV7APIService,
    _emit_followup_alerts,
    _followup_attempt_status,
    _followup_reasoning_effort,
    _response_seed_overrides_for_flow,
)
from runtime_v7.channel_renderer import RuntimeV7ChannelRender
from runtime_v7.conversation_hydrator import ConversationHydrationResult
from runtime_v7.followup import (
    apply_sales_permissive_followup_policy,
    build_fallback_followup_message,
    build_followup_composer_messages,
    build_followup_context,
    deterministic_followup_gate,
    followup_message_hash,
    latest_followup_customer_message,
    parse_followup_composer,
    sanitize_followup_message,
)


class FakeFollowupModelClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def acomplete(
        self,
        *,
        messages,
        tools=None,
        tool_choice="auto",
        metadata=None,
        response_format=None,
        max_tokens=None,
    ):
        self.calls.append(
            {
                "messages": list(messages),
                "tools": tools,
                "tool_choice": tool_choice,
                "metadata": dict(metadata or {}),
                "response_format": response_format,
                "max_tokens": max_tokens,
            }
        )
        payload = self.responses.pop(0)
        return {
            "content": json.dumps(payload),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "latency_ms": 7,
            "model": "fake-followup-model",
            "provider": "fake",
            "finish_reason": "stop",
        }


class FakeDeliveryClient:
    def __init__(self):
        self.calls = []

    async def send_content(self, messages, channel_subtype=None):
        self.calls.append({"messages": list(messages), "channel_subtype": channel_subtype})
        return {"status": "success", "status_code": 200}


class FailingDeliveryClient:
    def __init__(self):
        self.calls = []

    async def send_content(self, messages, channel_subtype=None):
        self.calls.append({"messages": list(messages), "channel_subtype": channel_subtype})
        return {"status": "error", "status_code": 500, "reason": "fake_delivery_failure"}


class RaisingDeliveryClient:
    async def send_content(self, messages, channel_subtype=None):
        raise TimeoutError("manychat delivery timed out")


def _gateway():
    return SessionsGateway(
        config=SessionsGatewayConfig(
            project_id="test",
            users_collection="users",
            sessions_subcollection="sessions",
            storage_kind="memory",
        ),
        store=MemorySessionStore(),
    )


def _seed_session(gateway, *, user_id="user_1", channel_user_id="mc_1", v7_state=None, initial_user_text="Need 185/65R15 around QC"):
    loaded = gateway.load(user_id=user_id, channel_user_id=channel_user_id, user_id_source="manychat")
    now = now_manila_str()
    anchor = datetime.strptime(now, "%Y-%m-%d %H:%M:%S")
    user_ts = (anchor - timedelta(minutes=61)).strftime("%Y-%m-%d %H:%M:%S")
    assistant_ts = (anchor - timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")
    loaded.session_doc.messages = [
        MessageTurn(role="user", text=initial_user_text, ts=user_ts),
        MessageTurn(
            role="assistant",
            text="May options po for 185/65R15. Gusto niyo po ba lowest total or known brand?",
            ts=assistant_ts,
        ),
    ]
    loaded.session_doc.strategy_state = {
        "runtime_v7": {
            "background_signals": [
                {"key": "tire_size", "value": "185/65R15", "source": "latest_user_message"},
                {"key": "location", "value": "Quezon City", "source": "latest_user_message"},
            ],
            **dict(v7_state or {}),
        }
    }
    loaded.session_doc.updated_at = now
    gateway.save(
        user_doc=UserDoc(
            user_id=user_id,
            channel_user_id=channel_user_id,
            active_session_id=loaded.session_doc.session_id,
            updated_at=now,
            user_id_source="manychat",
        ),
        session_doc=loaded.session_doc,
    )
    return loaded.session_doc.session_id


def test_runtime_v7_followup_sends_and_logs(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_PRE_DELIVERY_FRESHNESS_CHECK", "0")
    monkeypatch.setattr("runtime_v7.api_runtime.load_current_promo_brands", lambda: {"status": "ok", "brands": []})
    gateway = _gateway()
    session_id = _seed_session(gateway)
    analytics = MemoryAnalyticsGateway()
    delivery = FakeDeliveryClient()
    planner = FakeFollowupModelClient(
        [
            {
                "action": "send",
                "customer_stance": "active",
                "focus_field": "tire_brand",
                "visible_text": "Kamusta po? Aling tire brand ang gusto niyong i-check next? 😊",
                "benefit_refs": [],
                "reason": "continue the open brand choice",
            }
        ]
    )
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        analytics_gateway=analytics,
        delivery_mode="send_content",
        fetch_manychat_messages=False,
        followup_model_client=planner,
        delivery_client_factory=lambda _request: delivery,
    )

    result = asyncio.run(
        service.handle_followup(
            RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                channel="manychat",
                user_text="",
                delivery_mode="send_content",
            ),
            request_id="req_followup",
        )
    )
    payload = result.to_payload(include_debug=True)

    assert payload["status"] == "success"
    assert (
        payload["response"]["bubble1"]
        == "Kamusta po? Aling tire brand ang gusto niyong i-check next? \U0001f60a"
    )
    assert delivery.calls[0]["messages"] == [
        {
            "type": "text",
            "text": "Kamusta po? Aling tire brand ang gusto niyong i-check next? \U0001f60a",
        }
    ]
    assert len(planner.calls) == 1
    assert planner.calls[0]["response_format"].__name__ == "RuntimeV7FollowupPlanModel"
    assert planner.calls[0]["metadata"]["component"] == "followup_generation"
    assert analytics.last_debug_log()["debug_payload"]["kind"] == "runtime_v7_turn_trace"
    assert analytics.turn_fact_logs[-1]["flow_stage_after"] == "followup_sent"
    assert analytics.llm_span_logs[-1]["component"] == "followup_generation"
    assert analytics.followup_event_logs[-1]["focus_field"] == "tire_brand"
    followup_debug = payload["debug"]["followup"]
    logged_followup_text = json.dumps(
        {
            "decision": followup_debug["decision"],
            "validation": followup_debug["validation"],
        }
    ).lower()
    for term in ["price", "pricing", "presyo", "quote", "total"]:
        assert term not in logged_followup_text

    stored = gateway.load(user_id="user_1", channel_user_id="mc_1").session_doc
    assert stored.session_id == session_id
    followup_state = stored.strategy_state["runtime_v7"]["followup"]
    assert followup_state["attempts"][-1]["status"] == "sent"
    assert followup_state["last_decision"] == "send"
    assert followup_state["last_sent_focus_field"]
    assert followup_state["last_sent_focus_field"] in followup_state["sent_focus_fields"]
    ledger_text = json.dumps(followup_state).lower()
    for term in ["price", "pricing", "presyo", "quote", "total"]:
        assert term not in ledger_text
    cached_messages = stored.strategy_state["channel_conversation_history_v1"]["messages"]
    assert cached_messages[-1]["role"] == "assistant"
    assert "gusto niyong i-check next" in cached_messages[-1]["content"]


def test_runtime_v7_followup_suppresses_when_pre_delivery_transcript_is_unavailable(monkeypatch):
    monkeypatch.setattr("runtime_v7.api_runtime.load_current_promo_brands", lambda: {"status": "ok", "brands": []})
    gateway = _gateway()
    _seed_session(gateway)
    delivery = FakeDeliveryClient()
    planner = FakeFollowupModelClient(
        [
            {
                "action": "send",
                "customer_stance": "active",
                "focus_field": "tire_brand",
                "visible_text": "May preferred tire brand po ba kayong gustong unahin?",
                "benefit_refs": [],
                "reason": "continue the brand choice",
            }
        ]
    )
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        delivery_mode="send_content",
        fetch_manychat_messages=False,
        followup_model_client=planner,
        delivery_client_factory=lambda _request: delivery,
    )

    async def unavailable_freshness(*_args, **_kwargs):
        return {"status": "no_history", "loader_status": "error"}

    monkeypatch.setattr(service, "_freshness_check_before_delivery", unavailable_freshness)

    result = asyncio.run(
        service.handle_followup(
            RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                channel="manychat",
                user_text="",
                delivery_mode="send_content",
            ),
            request_id="req_followup_freshness_unavailable",
        )
    )

    assert result.status == "suppressed"
    assert result.delivery_result["reason"] == "pre_delivery_transcript_unavailable"
    assert delivery.calls == []


def test_runtime_v7_followup_does_not_deliver_when_sending_state_cannot_persist(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_PRE_DELIVERY_FRESHNESS_CHECK", "0")
    monkeypatch.setattr("runtime_v7.api_runtime.load_current_promo_brands", lambda: {"status": "ok", "brands": []})
    gateway = _gateway()
    _seed_session(gateway)
    delivery = FakeDeliveryClient()
    planner = FakeFollowupModelClient(
        [
            {
                "action": "send",
                "customer_stance": "active",
                "focus_field": "tire_brand",
                "visible_text": "Anong tire brand po ang pinaka-interested kayong makita?",
                "benefit_refs": [],
                "reason": "brand follow-up",
            }
        ]
    )
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        delivery_mode="send_content",
        fetch_manychat_messages=False,
        followup_model_client=planner,
        delivery_client_factory=lambda _request: delivery,
    )
    monkeypatch.setattr(service, "_persist_followup_attempt", lambda **_kwargs: False)

    result = asyncio.run(
        service.handle_followup(
            RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                channel="manychat",
                user_text="",
                delivery_mode="send_content",
            ),
            request_id="req_followup_pre_send_persist_fail",
        )
    )

    assert result.status == "suppressed"
    assert result.delivery_result["reason"] == "followup_sending_state_not_persisted"
    assert delivery.calls == []


def test_runtime_v7_followup_marks_delivery_unknown_when_final_state_cannot_persist(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_PRE_DELIVERY_FRESHNESS_CHECK", "0")
    monkeypatch.setattr("runtime_v7.api_runtime.load_current_promo_brands", lambda: {"status": "ok", "brands": []})
    gateway = _gateway()
    _seed_session(gateway)
    analytics = MemoryAnalyticsGateway()
    delivery = FakeDeliveryClient()
    planner = FakeFollowupModelClient(
        [
            {
                "action": "send",
                "customer_stance": "active",
                "focus_field": "tire_brand",
                "visible_text": "May brand preference po ba kayo para ma-narrow down natin?",
                "benefit_refs": [],
                "reason": "brand follow-up",
            }
        ]
    )
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        analytics_gateway=analytics,
        delivery_mode="send_content",
        fetch_manychat_messages=False,
        followup_model_client=planner,
        delivery_client_factory=lambda _request: delivery,
    )
    monkeypatch.setattr(service, "_save_followup_state", lambda **_kwargs: False)

    result = asyncio.run(
        service.handle_followup(
            RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                channel="manychat",
                user_text="",
                delivery_mode="send_content",
            ),
            request_id="req_followup_post_send_persist_fail",
        )
    )

    assert len(delivery.calls) == 1
    assert result.status == "delivery_unknown"
    assert result.delivery_result["original_status"] == "success"
    assert result.delivery_result["reason"] == "followup_post_delivery_state_not_persisted"
    assert analytics.followup_event_logs[-1]["attempt_status"] == "delivery_unknown"
    stored = gateway.load(user_id="user_1", channel_user_id="mc_1").session_doc
    assert stored.strategy_state["runtime_v7"]["followup"]["attempts"][-1]["status"] == "sending"


def test_runtime_v7_followup_records_attempted_focus_when_delivery_fails(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_PRE_DELIVERY_FRESHNESS_CHECK", "0")
    monkeypatch.setattr("runtime_v7.api_runtime.load_current_promo_brands", lambda: {"status": "ok", "brands": []})
    gateway = _gateway()
    _seed_session(gateway)
    delivery = FailingDeliveryClient()
    planner = FakeFollowupModelClient(
        [
            {
                "action": "send",
                "customer_stance": "active",
                "focus_field": "tire_brand",
                "visible_text": "Aling brand po ang gusto niyong i-check natin next?",
                "benefit_refs": [],
                "reason": "brand follow-up",
            }
        ]
    )
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        analytics_gateway=MemoryAnalyticsGateway(),
        delivery_mode="send_content",
        fetch_manychat_messages=False,
        followup_model_client=planner,
        delivery_client_factory=lambda _request: delivery,
    )

    result = asyncio.run(
        service.handle_followup(
            RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                channel="manychat",
                user_text="",
                delivery_mode="send_content",
            ),
            request_id="req_followup_delivery_fail",
        )
    )

    assert result.status == "delivery_failed"
    stored = gateway.load(user_id="user_1", channel_user_id="mc_1").session_doc
    followup_state = stored.strategy_state["runtime_v7"]["followup"]
    assert followup_state["last_decision"] == "send"
    assert followup_state["last_delivery_status"] == "error"
    assert followup_state["attempts"][-1]["status"] == "delivery_failed"
    assert followup_state["attempts"][-1]["focus_field"] == "tire_brand"
    assert "last_sent_focus_field" not in followup_state
    assert followup_state["sent_focus_fields"] == []


def test_runtime_v7_followup_return_only_records_evaluated_not_sent(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_PRE_DELIVERY_FRESHNESS_CHECK", "0")
    monkeypatch.setattr("runtime_v7.api_runtime.load_current_promo_brands", lambda: {"status": "ok", "brands": []})
    gateway = _gateway()
    _seed_session(gateway)
    planner = FakeFollowupModelClient(
        [
            {
                "action": "send",
                "customer_stance": "active",
                "focus_field": "tire_brand",
                "visible_text": "May particular tire brand po ba kayong preferred?",
                "benefit_refs": [],
                "reason": "brand follow-up",
            }
        ]
    )
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        delivery_mode="return_only",
        fetch_manychat_messages=False,
        followup_model_client=planner,
    )

    result = asyncio.run(
        service.handle_followup(
            RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                channel="manychat",
                user_text="",
                delivery_mode="return_only",
            ),
            request_id="req_followup_return_only",
        )
    )

    assert result.status == "evaluated"
    stored = gateway.load(user_id="user_1", channel_user_id="mc_1").session_doc
    followup_state = stored.strategy_state["runtime_v7"]["followup"]
    assert followup_state["attempts"][-1]["status"] == "evaluated"
    assert followup_state["sent_focus_fields"] == []
    assert "last_sent_at" not in followup_state


def test_runtime_v7_followup_applies_completion_gate_before_promo_lookup(monkeypatch):
    gateway = _gateway()
    _seed_session(
        gateway,
        v7_state={
            "latest_submitted_order_context": {
                "order_id": "order_redacted",
                "order_payload_ref": "order_payload_redacted",
                "submitted_at": now_manila_str(),
            }
        },
    )

    def unexpected_promo_lookup():
        raise AssertionError("promo lookup must not run for a completed conversation")

    monkeypatch.setattr("runtime_v7.api_runtime.load_current_promo_brands", unexpected_promo_lookup)
    planner = FakeFollowupModelClient([])
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        delivery_mode="return_only",
        fetch_manychat_messages=False,
        followup_model_client=planner,
    )

    result = asyncio.run(
        service.handle_followup(
            RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                channel="manychat",
                user_text="",
                delivery_mode="return_only",
            ),
            request_id="req_followup_completed",
        )
    )

    assert result.status == "suppressed"
    assert result.delivery_result["reason"] == "conversation_already_converted"
    assert planner.calls == []


def test_followup_context_includes_lead_qualification_guidance():
    context = build_followup_context(
        request_time="2026-06-14 10:00:00",
        conversation_messages=[
            {"role": "user", "content": "Need 185/65R15", "datetime": "2026-06-14 08:58:00"},
            {
                "role": "assistant",
                "content": "May options po. Saan po location niyo?",
                "datetime": "2026-06-14 09:00:00",
            },
        ],
        session_messages=[],
        v7_state={
            "background_signals": [
                {"key": "tire_size", "value": "185/65R15"},
            ]
        },
        hydration_metadata={},
    )

    lead = context["lead_qualification"]

    assert lead["priority_order"] == ["tire_size", "location", "tire_brand", "contact_number"]
    assert lead["present"] == {"tire_size": "185/65R15"}
    assert lead["missing"] == ["location", "tire_brand"]
    assert lead["next_best_field"] == "location"
    assert lead["non_lead_fields"]["priority_order"] == ["installation_partner", "schedule", "payment_option"]


def test_followup_context_exposes_lead_qualification_next_field():
    context = build_followup_context(
        request_time="2026-06-14 10:00:00",
        conversation_messages=[
            {"role": "user", "content": "185/65R15 po", "datetime": "2026-06-14 08:58:00"},
            {
                "role": "assistant",
                "content": "May options po tayo. Pa-send po city or barangay.",
                "datetime": "2026-06-14 09:00:00",
            },
        ],
        session_messages=[],
        v7_state={
            "background_signals": [
                {"key": "tire_size", "value": "185/65R15"},
            ]
        },
        hydration_metadata={},
    )

    assert context["lead_qualification"]["next_best_field"] == "location"


def test_followup_lead_qualification_does_not_treat_presented_cards_as_customer_brand_choice():
    context = build_followup_context(
        request_time="2026-07-13 08:57:00",
        conversation_messages=[
            {"role": "user", "content": "205/45/rim 17", "datetime": "2026-07-13 08:09:44"},
            {
                "role": "assistant",
                "content": "May nakita po tayong options: MICHELIN 205/45/R17, APOLLO 205/45/R17, FRONWAY 205/45/R17.",
                "datetime": "2026-07-13 08:10:31",
            },
            {
                "role": "assistant",
                "content": "Alin po sa mga 'yan ang gusto niyong i-check, or send city/barangay.",
                "datetime": "2026-07-13 08:10:37",
            },
        ],
        session_messages=[],
        v7_state={
            "background_signals": [
                {"key": "tire_size", "value": "205/45R17", "source": "latest_user_message"},
            ]
        },
        hydration_metadata={},
    )

    display = context["normalized_entities"]["display_values"]
    lead = context["lead_qualification"]

    assert "preferred_brands" in display
    assert lead["present"] == {"tire_size": "205/45R17"}
    assert lead["missing"] == ["location", "tire_brand"]
    assert lead["next_best_field"] == "location"


def test_followup_context_keeps_presented_brands_unselected():
    context = build_followup_context(
        request_time="2026-07-15 09:15:00",
        conversation_messages=[
            {"role": "user", "content": "Hi po, may 205/55R16 kayo?", "datetime": "2026-07-15 07:30:00"},
            {
                "role": "assistant",
                "content": (
                    "Meron po tayo for 205/55R16. Shown options: Michelin Primacy 4 - Buy 3 Get 1 FREE, "
                    "BPI 6mo 0% interest. Apollo Alnac - Buy 3 Get 1 FREE, BPI 6mo 0% interest. "
                    "Fronway Ecogreen - Tire Protection Plan. Alin pong brand ang preferred niyo?"
                ),
                "datetime": "2026-07-15 07:40:00",
            },
        ],
        session_messages=[],
        v7_state={},
        hydration_metadata={},
    )

    assert context["lead_qualification"]["present"] == {"tire_size": "205/55R16"}
    assert context["lead_qualification"]["missing"] == ["location", "tire_brand"]


def test_followup_gate_still_recovers_latest_customer_before_rotation():
    context = build_followup_context(
        request_time="2026-07-13 21:10:00",
        conversation_messages=[
            {"role": "assistant", "content": "Interested pa po ba kayo sa Michelin tires?", "datetime": "2026-07-13 09:10:00"},
            {"role": "user", "content": "Sige Apollo na lang", "datetime": "2026-07-13 21:00:00"},
        ],
        session_messages=[],
        v7_state={
            "followup": {
                "last_sent_focus_field": "tire_brand",
                "sent_focus_fields": ["tire_brand"],
                "last_message_hash": followup_message_hash("Interested pa po ba kayo sa Michelin tires?"),
            },
        },
        hydration_metadata={},
    )
    context = {
        **context,
        "deterministic_followup_goal": {
            "goal_key": "missing_location",
            "missing_field": "location",
        },
    }

    gate = deterministic_followup_gate(context, request_time="2026-07-13 21:10:00")

    assert gate["status"] == "recover_to_chat"
    assert gate["reason"] == "latest_customer_message_recovery"


def test_followup_deterministic_gate_suppresses_outside_windows_and_human_agent():
    base_context = {
        "request_time": "2026-06-14 10:00:00",
        "state_signals": {},
        "normalized_entities": {},
        "recent_messages": [
            {"role": "user", "content": "Need 185/65R15", "datetime": "2026-06-14 08:00:00"},
            {"role": "assistant", "content": "Pa-send location po.", "datetime": "2026-06-14 09:30:00"},
        ],
        "latest_message": {"role": "assistant", "content": "Pa-send location po.", "datetime": "2026-06-14 09:30:00"},
    }
    assert deterministic_followup_gate(base_context, request_time="2026-06-14 10:00:00")["reason"] == "latest_assistant_message_too_recent_lt_45m"

    stale = {**base_context, "request_time": "2026-06-14 14:00:00"}
    assert deterministic_followup_gate(stale, request_time="2026-06-14 14:00:00")["reason"] == "latest_assistant_message_stale_gt_3h"

    human_after = {
        **base_context,
        "recent_messages": [
            {"role": "user", "content": "Need 185/65R15", "datetime": "2026-06-14 08:00:00"},
            {"role": "assistant", "content": "Pa-send location po.", "datetime": "2026-06-14 08:30:00"},
            {"role": "human_agent", "content": "Ako na po mag-assist.", "datetime": "2026-06-14 08:45:00"},
            {"role": "assistant", "content": "Pa-send location po.", "datetime": "2026-06-14 09:00:00"},
        ],
        "latest_message": {"role": "assistant", "content": "Pa-send location po.", "datetime": "2026-06-14 09:00:00"},
    }
    assert deterministic_followup_gate(human_after, request_time="2026-06-14 10:00:00")["reason"] == "human_agent_message_after_latest_customer"


def test_followup_deterministic_gate_handles_timezone_aware_manila_timestamps():
    context = {
        "request_time": "2026-06-14 10:00:00",
        "state_signals": {},
        "normalized_entities": {},
        "deterministic_followup_goal": {"goal_key": "missing_location"},
        "recent_messages": [
            {"role": "user", "content": "Michelin 225/55R19 hm", "datetime": "2026-06-14T08:58:00+08:00"},
            {
                "role": "assistant",
                "content": "Pa-send city or barangay po.",
                "datetime": "2026-06-14T09:00:00+08:00",
            },
        ],
        "latest_message": {
            "role": "assistant",
            "content": "Pa-send city or barangay po.",
            "datetime": "2026-06-14T09:00:00+08:00",
        },
    }

    gate = deterministic_followup_gate(context, request_time="2026-06-14 10:00:00")

    assert gate["status"] == "allow"
    assert gate["reason"] == "eligible_last_interaction_window"
    assert gate["age_minutes"] == 60.0


def test_runtime_v7_followup_context_exposes_latest_customer_message_id():
    context = build_followup_context(
        request_time="2026-06-04 22:00:00",
        conversation_messages=[
            {"role": "assistant", "content": "May options po tayo.", "datetime": "2026-06-04 21:00:00"},
            {
                "role": "user",
                "content": "Interested pa po",
                "datetime": "2026-06-04 21:05:00",
                "message_id": "msg_latest_user",
            },
        ],
        session_messages=[],
        v7_state={},
        hydration_metadata={},
    )

    latest = latest_followup_customer_message(context)

    assert latest["content"] == "Interested pa po"
    assert latest["message_id"] == "msg_latest_user"


def test_runtime_v7_followup_context_projects_normalized_entities_from_recent_turns():
    context = build_followup_context(
        request_time="2026-06-04 22:00:00",
        conversation_messages=[
            {"role": "user", "content": "Wedtlake po 1 pc for Xpander"},
            {
                "role": "assistant",
                "content": (
                    "Okay po, noted na Wedtlake ang hanap niyo at 1 pc lang. "
                    "Para ma-check ko po ang available na Wedtlake tires para sa Mitsubishi Xpander, "
                    "pa-confirm lang po ulit ng exact tire size sa sidewall."
                ),
            },
        ],
        session_messages=[],
        v7_state={},
        hydration_metadata={},
    )

    entities = context["normalized_entities"]
    assert entities["source"] == "central_entity_normalizer"
    assert entities["display_values"]["preferred_brands"] == "Westlake"
    assert entities["display_values"]["car_make_model"] == "Mitsubishi Xpander"

    messages = build_followup_composer_messages(context, {"should_follow_up": True})
    prompt_text = messages[1]["content"]

    assert prompt_text.startswith("Request time:")
    assert "Lead qualification:" in prompt_text
    assert "Recent conversation:" in prompt_text
    assert "Missing: tire_size" in prompt_text
    assert "Default next lead field" not in prompt_text
    assert "Westlake" in prompt_text
    assert "Wedtlake" not in prompt_text
    assert '"brief"' not in prompt_text
    assert '"context"' not in prompt_text
    assert "Task: Compose one short proactive" not in prompt_text
    assert "system message contains" not in prompt_text
    assert "dynamic brief" not in prompt_text
    assert "tone_guidance" not in prompt_text
    assert "state_signals" not in prompt_text
    assert "operational_state" not in prompt_text
    assert "followup_priority" not in prompt_text


def test_runtime_v7_followup_context_masks_contact_number():
    context = build_followup_context(
        request_time="2026-06-04 22:00:00",
        conversation_messages=[
            {"role": "user", "content": "185/65R15 QC 09171234567"},
            {
                "role": "assistant",
                "content": "Noted po. May preferred brand po kayo?",
            },
        ],
        session_messages=[],
        v7_state={
            "background_signals": [
                {"key": "tire_size", "value": "185/65R15"},
                {"key": "location", "value": "Quezon City"},
                {"key": "contact_number", "value": "09171234567"},
            ]
        },
        hydration_metadata={},
    )
    messages = build_followup_composer_messages(context, {"should_follow_up": True})
    prompt_text = messages[1]["content"]

    assert context["lead_qualification"]["present"]["contact_number"] == "provided"
    assert context["normalized_entities"]["display_values"]["contact_number"] == "provided"
    assert "09171234567" not in prompt_text
    assert context["lead_qualification"]["next_best_field"] == ""
    assert context["lead_qualification"]["optional_missing"] == ["tire_brand"]


def test_runtime_v7_followup_composer_gets_taglish_tone_guidance():
    context = build_followup_context(
        request_time="2026-06-04 22:00:00",
        conversation_messages=[
            {"role": "user", "content": "Roughly magkano presyu apat na gulong po"},
            {
                "role": "assistant",
                "content": (
                    "Pakitingnan na lang po ulit yung sidewall para makita yung exact size. "
                    "Para ma-check ko po yung presyo. Buy 3 Get 1 FREE promo. PHP 12345. "
                    "https://gulong.ph/product/sample " + ("long details " * 80)
                ),
            },
        ],
        session_messages=[],
        v7_state={},
        hydration_metadata={},
    )

    messages = build_followup_composer_messages(
        context,
        {"should_follow_up": True, "followup_goal": "provide pricing, promo, and total quote"},
    )
    prompt_text = messages[1]["content"]

    assert "Tone/language:" not in prompt_text
    assert "main chatbot" not in prompt_text
    assert "http" not in prompt_text
    assert "presyo" not in prompt_text.lower()
    assert "magkano" not in prompt_text.lower()
    assert "presyu" not in prompt_text.lower()
    assert "pricing" not in prompt_text.lower()
    assert "quote" not in prompt_text.lower()
    assert "total quote" not in prompt_text.lower()
    assert "Buy 3 Get 1 FREE was shown" in prompt_text
    assert "PHP 12345" not in prompt_text
    assert "Grounded offer highlights" in prompt_text


def test_runtime_v7_followup_sanitizer_polishes_sales_copy():
    message = sanitize_followup_message(
        "Hi po! Still interested in the Michelin options?\n"
        "Let me know po kung may question.\n"
        "Na-check niyo na po ba para ma-quote ko na po yung presyo?\n"
        "May Buy 3 Get 1 FREE promo pa po.\n"
        "https://gulong.ph/product/michelin-265-60-r18\n\n"
        "Salamat po! \U0001f60a"
    )

    assert "http" not in message
    assert "Salamat" not in message
    assert "Let me know" not in message
    assert "Sabihin niyo lang po kung" in message
    assert "presyo" not in message.lower()
    assert "quote" not in message.lower()
    assert "Buy 3 Get 1 FREE promo" in message
    assert "available options" in message
    assert message.endswith("\U0001f60a")


def test_runtime_v7_followup_sanitizer_drops_price_only_copy():
    message = sanitize_followup_message("Kamusta po, sir! Na-check niyo na po ba para ma-quote ko yung presyo?")

    assert message == "Kamusta po, sir! Na-check niyo na po ba para ma-check ko po yung available options? \U0001f60a"


def test_runtime_v7_followup_sanitizer_removes_stray_question_mark_emoji_markers():
    message = sanitize_followup_message(
        "Interested pa po ba kayo sa tires na 205/45R17? If yes po, send city/barangay. ?? \U0001f60a"
    )

    assert "??" not in message
    assert message.endswith("\U0001f60a")


def test_runtime_v7_followup_sanitizer_removes_candidate_size_lists_and_inline_thanks():
    message = sanitize_followup_message(
        "Kamusta po! Interested pa po ba kayo sa Westlake tires? "
        "Pa-send po ng exact tire size para ma-check ko po ang availability. "
        "Alin po ang nakita niyo sa mga sizes na ito: 185/65R15, 195/65R16, 205/55R16, or 205/55R17? "
        "Salamat po! \U0001f60a"
    )

    assert "185/65R15" not in message
    assert "sizes na ito" not in message
    assert "Salamat" not in message
    assert "Pa-send po ng exact tire size" in message
    assert message.endswith("\U0001f60a")


def test_runtime_v7_followup_fallback_copy_avoids_pricing_language():
    context = build_followup_context(
        request_time="2026-06-04 22:00:00",
        conversation_messages=[
            {"role": "user", "content": "Magkano po apat na gulong?"},
            {"role": "assistant", "content": "Pakitingnan po yung exact tire size sa sidewall."},
        ],
        session_messages=[],
        v7_state={},
        hydration_metadata={},
    )

    message = build_fallback_followup_message(
        context,
        {"should_follow_up": True, "followup_goal": "ask for size to provide pricing"},
    )

    assert "price" not in message.lower()
    assert "pricing" not in message.lower()
    assert "presyo" not in message.lower()
    assert "quote" not in message.lower()
    assert "available options" in message


def test_runtime_v7_followup_fallback_uses_normalized_brand_and_cta():
    context = build_followup_context(
        request_time="2026-06-04 22:00:00",
        conversation_messages=[
            {"role": "user", "content": "Wedtlake po for Xpander"},
            {"role": "assistant", "content": "Pa-confirm po ng exact tire size sa sidewall."},
        ],
        session_messages=[],
        v7_state={},
        hydration_metadata={},
    )

    message = build_fallback_followup_message(
        context,
        {"should_follow_up": True, "followup_goal": "ask for exact tire size"},
    )

    assert "Westlake" in message
    assert "Wedtlake" not in message
    assert "Reply niyo po yung exact tire size" in message


def test_runtime_v7_followup_composer_parser_accepts_wrapped_json():
    parsed = parse_followup_composer(
        'Here is the message: {"message": "Kamusta po! Interested pa po ba kayo?", "reason": "open_loop"}'
    )

    assert parsed["message"] == "Kamusta po! Interested pa po ba kayo? \U0001f60a"
    assert parsed["reason"] == "open_loop"


def test_runtime_v7_followup_latest_customer_routes_to_full_chat(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_SESSION_LOCK_ENABLED", "0")
    gateway = _gateway()
    captured = {}

    class CaptureService(RuntimeV7APIService):
        async def _handle_locked_turn(
            self,
            request,
            *,
            request_id,
            trace_id,
            user_id,
            channel_user_id,
            session_doc,
        ):
            captured["request"] = request
            return RuntimeV7APIResult(
                response={"bubble1": "Sorry po sa late reply. Checking this now."},
                content_messages=[{"type": "text", "text": "Sorry po sa late reply. Checking this now."}],
                images=[],
                payment={},
                delivery_result={"status": "skipped", "reason": "return_only"},
                tagging_result={"tags_to_add": []},
                turn_record={
                    "turn_id": "turn_latest_user",
                    "user_message": request.user_text,
                    "runtime_final_response": "Sorry po sa late reply. Checking this now.",
                    "tool_results": [],
                    "llm_calls": [],
                },
                session_id=session_doc.session_id,
                trace_id=trace_id,
                request_id=request_id,
                message_id=request.message_id,
                idempotency_key=request.idempotency_key,
                state_saved=False,
                status="success",
            )

    service = CaptureService(
        sessions_gateway=gateway,
        delivery_mode="return_only",
        fetch_manychat_messages=False,
    )

    result = asyncio.run(
        service.handle_followup(
            RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                channel="manychat",
                user_text="",
                delivery_mode="return_only",
                request_time="2026-06-04 22:00:00",
                conversation_history=[
                    {
                        "role": "assistant",
                        "content": "May options po tayo. Interested pa po kayo?",
                        "datetime": "2026-06-04 21:00:00",
                        "message_id": "msg_assistant",
                    },
                    {
                        "role": "user",
                        "content": "Yes available pa?",
                        "datetime": "2026-06-04 21:10:00",
                        "message_id": "msg_user_latest",
                    },
                ],
            ),
            request_id="req_followup_latest_user",
        )
    )

    routed_request = captured["request"]
    assert result.status == "success"
    assert routed_request.user_text == "Yes available pa?"
    assert routed_request.message_id == "msg_user_latest"
    assert routed_request.idempotency_key == "msg_user_latest"
    assert routed_request.message_id_source == "followup_latest_customer_message"
    assert routed_request.flow_context["routed_to"] == "runtime_v7_chat"
    assert routed_request.flow_context["late_reply_apology_required"] is True
    seeds = _response_seed_overrides_for_flow(routed_request.flow_context)
    assert seeds[0]["type"] == "late_reply_apology"
    assert "Sorry po sa late reply" in seeds[0]["guidance"]


def test_customer_recovery_suppresses_old_response_when_newer_customer_message_arrives(monkeypatch):
    gateway = _gateway()
    _seed_session(gateway)
    loaded = gateway.load(user_id="user_1", channel_user_id="mc_1")
    delivery = FakeDeliveryClient()
    response_text = "Sorry po sa late reply. Checking this now."
    harness = SimpleNamespace(
        product_inclusions_sent=False,
        latest_promo_presentation={},
        promo_presentation_history=[],
        latest_product_presentation={},
        product_presentation_history=[],
        run_turn=lambda *_args, **_kwargs: {
            "turn_id": "turn_old_recovery",
            "user_message": "Available pa po?",
            "runtime_final_response": response_text,
            "tool_results": [],
            "llm_calls": [],
            "tagging": {"tags_to_add": []},
        },
    )
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        delivery_mode="send_content",
        fetch_manychat_messages=False,
        harness_factory=lambda *_args: harness,
        delivery_client_factory=lambda _request: delivery,
    )
    monkeypatch.setattr("runtime_v7.api_runtime._hydrate_harness", lambda *_args, **_kwargs: None)

    async def newer_customer_seen(*_args, **_kwargs):
        return {
            "status": "fresh_with_newer_user_message",
            "reason": "newer_user_message_seen_delivery_not_suppressed",
        }

    monkeypatch.setattr(service, "_freshness_check_before_delivery", newer_customer_seen)
    request = RuntimeV7APIRequest(
        user_id="user_1",
        channel_user_id="mc_1",
        channel="manychat",
        user_text="Available pa po?",
        message_id="msg_old_customer",
        idempotency_key="msg_old_customer",
        delivery_mode="send_content",
        request_time=now_manila_str(),
        conversation_history=[
            {
                "role": "user",
                "content": "Available pa po?",
                "datetime": now_manila_str(),
                "message_id": "msg_old_customer",
            }
        ],
        flow_context={"route": "customer_turn_recovery", "cadence": "first"},
    )

    result = asyncio.run(
        service._handle_locked_turn(
            request,
            request_id="req_old_recovery",
            trace_id="trace_old_recovery",
            user_id="user_1",
            channel_user_id="mc_1",
            session_doc=loaded.session_doc,
        )
    )

    assert result.delivery_result["status"] == "suppressed"
    assert result.delivery_result["reason"] == "newer_user_message_seen_recovery_suppressed"
    assert delivery.calls == []


def test_runtime_v7_followup_recovers_after_busy_lock(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_SESSION_LOCK_WAIT_S", "0")
    monkeypatch.setenv("RUNTIME_V7_SESSION_LOCK_RECOVERY_ENABLED", "1")
    monkeypatch.setenv("RUNTIME_V7_SESSION_LOCK_RECOVERY_WAIT_S", "0.4")
    monkeypatch.setenv("RUNTIME_V7_SESSION_LOCK_POLL_S", "0.05")
    gateway = _gateway()
    session_id = _seed_session(gateway)
    ok, _ = gateway.acquire_lock(
        user_id="user_1",
        session_id=session_id,
        owner="req_existing",
        ttl_seconds=60,
    )
    assert ok is True
    captured = {}

    class CaptureService(RuntimeV7APIService):
        async def _handle_locked_followup(
            self,
            request,
            *,
            request_id,
            trace_id,
            user_id,
            channel_user_id,
            session_doc,
            force,
        ):
            captured["request"] = request
            captured["session_id"] = session_doc.session_id
            return RuntimeV7APIResult(
                response={"bubble1": "Recovered follow-up"},
                content_messages=[{"type": "text", "text": "Recovered follow-up"}],
                images=[],
                payment={},
                delivery_result={"status": "skipped", "reason": "return_only"},
                tagging_result={"tags_to_add": []},
                turn_record={
                    "turn_id": "turn_followup_recovered",
                    "user_message": request.user_text,
                    "runtime_final_response": "Recovered follow-up",
                    "tool_results": [],
                    "llm_calls": [],
                },
                session_id=session_doc.session_id,
                trace_id=trace_id,
                request_id=request_id,
                message_id=request.message_id,
                idempotency_key=request.idempotency_key,
                state_saved=False,
                status="success",
            )

    service = CaptureService(
        sessions_gateway=gateway,
        delivery_mode="return_only",
        fetch_manychat_messages=False,
    )

    async def run_recovery():
        task = asyncio.create_task(
            service.handle_followup(
                RuntimeV7APIRequest(
                    user_id="user_1",
                    channel_user_id="mc_1",
                    channel="manychat",
                    user_text="",
                    delivery_mode="return_only",
                ),
                request_id="req_followup_recover",
            )
        )
        await asyncio.sleep(0.08)
        gateway.release_lock(user_id="user_1", session_id=session_id, owner="req_existing")
        return await task

    result = asyncio.run(run_recovery())

    assert result.status == "success"
    assert captured["session_id"] == session_id
    recovery = captured["request"].flow_context["session_lock_recovery"]
    assert recovery["phase"] == "followup"
    assert recovery["status"] == "lock_acquired"


def test_runtime_v7_followup_respects_model_suppression(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_PRE_DELIVERY_FRESHNESS_CHECK", "0")
    monkeypatch.setattr("runtime_v7.api_runtime.load_current_promo_brands", lambda: {"status": "ok", "brands": []})
    gateway = _gateway()
    _seed_session(gateway)
    delivery = FakeDeliveryClient()
    planner = FakeFollowupModelClient(
        [
            {
                "action": "suppress",
                "customer_stance": "unclear",
                "focus_field": None,
                "visible_text": "Anong detail po ang gusto niyong ma-check next?",
                "benefit_refs": [],
                "reason": "not respectful to continue now",
            }
        ]
    )
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        delivery_mode="send_content",
        fetch_manychat_messages=False,
        followup_model_client=planner,
        delivery_client_factory=lambda _request: delivery,
    )

    result = asyncio.run(
        service.handle_followup(
            RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                user_text="",
                delivery_mode="send_content",
            ),
            request_id="req_waiting_override",
        )
    )

    followup = result.to_payload(include_debug=True)["debug"]["followup"]
    assert result.status == "suppressed"
    assert followup["decision"]["action"] == "suppress"
    assert followup["decision"]["reason"] == "not respectful to continue now"
    assert len(planner.calls) == 1
    assert delivery.calls == []
    stored = gateway.load(user_id="user_1", channel_user_id="mc_1").session_doc
    assert stored.strategy_state["runtime_v7"]["followup"]["attempts"][-1]["status"] == "suppressed"


def test_pre_delivery_suppression_is_recorded_as_retryable_evaluation():
    status = _followup_attempt_status(
        sent=False,
        decision={"action": "send"},
        validation={"status": "valid"},
        delivery_result={"status": "suppressed", "reason": "newer_channel_message_seen"},
    )

    assert status == "evaluated"


def test_transient_window_suppression_is_recorded_as_retryable_evaluation():
    status = _followup_attempt_status(
        sent=False,
        decision={"action": "suppress", "reason": "outside_first_followup_window"},
        validation={},
        delivery_result={"status": "suppressed", "reason": "outside_first_followup_window"},
    )

    assert status == "evaluated"


def test_runtime_v7_followup_suppresses_invalid_model_output(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_PRE_DELIVERY_FRESHNESS_CHECK", "0")
    monkeypatch.setattr("runtime_v7.api_runtime.load_current_promo_brands", lambda: {"status": "ok", "brands": []})
    gateway = _gateway()
    _seed_session(gateway)
    delivery = FakeDeliveryClient()
    planner = FakeFollowupModelClient(["not json"])
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        delivery_mode="send_content",
        fetch_manychat_messages=False,
        followup_model_client=planner,
        delivery_client_factory=lambda _request: delivery,
    )

    result = asyncio.run(
        service.handle_followup(
            RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                user_text="",
                delivery_mode="send_content",
            ),
            request_id="req_invalid_composer_fallback",
        )
    )

    payload = result.to_payload(include_debug=True)
    validation_debug = payload["debug"]["followup"]["validation"]
    assert result.status == "suppressed"
    assert payload["response"] == {}
    assert validation_debug["status"] == "not_applicable"
    assert delivery.calls == []


def test_runtime_v7_followup_policy_does_not_override_hard_no():
    context = build_followup_context(
        request_time="2026-06-04 22:00:00",
        conversation_messages=[
            {"role": "user", "content": "Wag na po, nakabili na ako sa ibang store."},
            {"role": "assistant", "content": "Sige po, salamat."},
        ],
        session_messages=[],
        v7_state={},
        hydration_metadata={},
    )
    decision = apply_sales_permissive_followup_policy(
        {
            "should_follow_up": False,
            "reason": "The latest message is from the assistant and customer has not responded.",
            "customer_state": "awaiting_customer_response",
        },
        context,
    )

    assert decision["should_follow_up"] is False
    assert decision["reason"].startswith("The latest message")


def test_runtime_v7_followup_model_defaults_disable_gemini_thinking(monkeypatch):
    monkeypatch.delenv("RUNTIME_V7_FOLLOWUP_DECISION_REASONING_EFFORT", raising=False)
    monkeypatch.setenv("RUNTIME_V7_FOLLOWUP_COMPOSER_REASONING_EFFORT", "none")

    assert _followup_reasoning_effort(
        "RUNTIME_V7_FOLLOWUP_DECISION_REASONING_EFFORT",
        "gemini/gemini-2.5-flash-lite",
        default="disable",
    ) == "disable"
    assert _followup_reasoning_effort(
        "RUNTIME_V7_FOLLOWUP_COMPOSER_REASONING_EFFORT",
        "gemini/gemini-2.5-flash-lite",
        default="disable",
    ) == "none"


def test_runtime_v7_followup_model_suppresses_hard_no(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_PRE_DELIVERY_FRESHNESS_CHECK", "0")
    monkeypatch.setattr("runtime_v7.api_runtime.load_current_promo_brands", lambda: {"status": "ok", "brands": []})
    gateway = _gateway()
    _seed_session(gateway, initial_user_text="Not interested na po")
    analytics = MemoryAnalyticsGateway()
    delivery = FakeDeliveryClient()
    planner = FakeFollowupModelClient(
        [
            {
                "action": "suppress",
                "customer_stance": "closed",
                "focus_field": None,
                "visible_text": "Pwede pong paki-confirm ang tire size na nasa sidewall?",
                "benefit_refs": [],
                "reason": "customer explicitly not interested",
            }
        ]
    )
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        analytics_gateway=analytics,
        delivery_mode="send_content",
        fetch_manychat_messages=False,
        followup_model_client=planner,
        delivery_client_factory=lambda _request: delivery,
    )

    result = asyncio.run(
        service.handle_followup(
            RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                channel="manychat",
                user_text="",
                delivery_mode="send_content",
            ),
            request_id="req_no_followup",
        )
    )

    assert result.status == "suppressed"
    assert result.delivery_result["reason"] == "customer explicitly not interested"
    assert delivery.calls == []
    assert len(planner.calls) == 1
    assert analytics.turn_fact_logs[-1]["flow_stage_after"] == "followup_suppressed"
    stored = gateway.load(user_id="user_1", channel_user_id="mc_1").session_doc
    assert stored.strategy_state["runtime_v7"]["followup"]["last_decision"] == "suppress"


def test_runtime_v7_followup_blocks_repeat_send_for_visible_followup(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_PRE_DELIVERY_FRESHNESS_CHECK", "0")
    monkeypatch.setattr("runtime_v7.api_runtime.load_current_promo_brands", lambda: {"status": "ok", "brands": []})
    gateway = _gateway()
    _seed_session(gateway)
    delivery = FakeDeliveryClient()
    planner = FakeFollowupModelClient(
        [
            {
                "action": "send",
                "customer_stance": "active",
                "focus_field": "tire_brand",
                "visible_text": "Saang city or area po natin iche-check ang options?",
                "benefit_refs": [],
                "reason": "open brand choice",
            }
        ]
    )
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        delivery_mode="send_content",
        fetch_manychat_messages=False,
        followup_model_client=planner,
        delivery_client_factory=lambda _request: delivery,
    )

    first = asyncio.run(
        service.handle_followup(
            RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                user_text="",
                delivery_mode="send_content",
            ),
            request_id="req_first",
        )
    )
    second = asyncio.run(
        service.handle_followup(
            RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                user_text="",
                delivery_mode="send_content",
            ),
            request_id="req_second",
        )
    )

    assert first.status == "success"
    assert second.status == "suppressed"
    assert second.delivery_result["reason"] == "cadence_already_sent"
    assert len(delivery.calls) == 1
    assert len(planner.calls) == 1


def test_v7_followup_route_maps_payload_to_service(monkeypatch):
    captured = {}

    class FakeIdempotencyDecision:
        action = "process"
        request_id = "req_followup_route"
        replay_payload = None

    class FakeIdempotencyGateway:
        def begin(self, **kwargs):
            captured["idempotency_begin"] = kwargs
            return FakeIdempotencyDecision()

        def complete(self, **kwargs):
            captured["idempotency_complete"] = kwargs

        def fail(self, **kwargs):
            captured["idempotency_fail"] = kwargs

    class FakeService:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        async def handle_followup(self, request, *, request_id="", force=False):
            captured["request"] = request
            captured["request_id"] = request_id
            captured["force"] = force
            return RuntimeV7APIResult(
                response={},
                content_messages=[],
                images=[],
                payment={},
                delivery_result={"status": "suppressed", "reason": "test"},
                tagging_result={},
                turn_record={"turn_id": "followup_test", "tool_results": [], "llm_calls": []},
                session_id="sess_1",
                trace_id="trace_1",
                request_id=request_id,
                message_id=request.message_id,
                idempotency_key=request.idempotency_key,
                state_saved=False,
                status="suppressed",
            )

    monkeypatch.setattr(gulong_router, "RuntimeV7APIService", FakeService)
    monkeypatch.setattr(gulong_router, "build_sessions_gateway", lambda bu: object())
    monkeypatch.setattr(gulong_router, "build_analytics_gateway", lambda bu: object())
    monkeypatch.setattr(gulong_router, "build_idempotency_gateway", lambda bu: FakeIdempotencyGateway())
    monkeypatch.setenv("FOLLOWUP_SEND_ENABLED", "0")

    payload = asyncio.run(
        gulong_router.chat_v7_followup(
            gulong_router.FollowupV7RequestPayload(
                user_id="user_1",
                channel_user_id="mc_1",
                channel_event_id="evt_route_1",
                channel_event_ts="2026-07-20T09:00:00+08:00",
                idempotency_key="followup_route_1",
                cadence="first",
                channel_subtype="instagram",
                force=1,
                save_analytics=0,
                return_logs=1,
                delivery_mode="return_only",
                conversation_history=[{"role": "assistant", "content": "Which brand po?"}],
            )
        )
    )

    assert payload["status"] == "suppressed"
    assert captured["force"] is False
    assert captured["request"].user_text == ""
    assert captured["request"].idempotency_key == "followup_route_1"
    assert captured["request"].channel_subtype == ""
    assert captured["request"].delivery_mode == "return_only"
    assert captured["request"].conversation_history == []
    assert captured["request"].profile_fields == {}
    assert "conversation_history" in captured["request"].flow_context["deprecated_request_fields_ignored"]
    assert "channel_subtype" in captured["request"].flow_context["deprecated_request_fields_ignored"]
    assert captured["init"]["analytics_gateway"] is not None
    assert captured["init"]["fetch_manychat_profile"] is True
    assert captured["init"]["fetch_manychat_messages"] is True
    assert "idempotency_complete" in captured


def test_runtime_v7_followup_delivery_exception_is_ledgered(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_PRE_DELIVERY_FRESHNESS_CHECK", "0")
    monkeypatch.setattr("runtime_v7.api_runtime.load_current_promo_brands", lambda: {"status": "ok", "brands": []})
    gateway = _gateway()
    _seed_session(gateway)
    planner = FakeFollowupModelClient(
        [
            {
                "action": "send",
                "customer_stance": "active",
                "focus_field": "tire_brand",
                "visible_text": "Ano pong next detail ang gusto niyong ayusin natin?",
                "benefit_refs": [],
                "reason": "continue brand choice",
            }
        ]
    )
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        analytics_gateway=MemoryAnalyticsGateway(),
        delivery_mode="send_content",
        fetch_manychat_messages=False,
        followup_model_client=planner,
        delivery_client_factory=lambda _request: RaisingDeliveryClient(),
    )

    result = asyncio.run(
        service.handle_followup(
            RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                channel="manychat",
                user_text="",
                delivery_mode="send_content",
            ),
            request_id="req_followup_delivery_exception",
        )
    )

    assert result.status == "delivery_failed"
    assert result.delivery_result["reason"] == "followup_delivery_exception"
    stored = gateway.load(user_id="user_1", channel_user_id="mc_1").session_doc
    attempt = stored.strategy_state["runtime_v7"]["followup"]["attempts"][-1]
    assert attempt["status"] == "delivery_failed"
    assert attempt["delivery_result"]["error_type"] == "TimeoutError"


def _customer_recovery_replay_fixture(gateway, *, ledger_status):
    _seed_session(gateway)
    loaded = gateway.load(user_id="user_1", channel_user_id="mc_1")
    message_id = "mc_customer_recovery_1"
    event_key = "manychat:mc_1:" + message_id
    response_text = "Sorry po sa late reply. Available pa po ba itong inquiry ninyo?"
    replay = {
        "_ledger_status": ledger_status,
        "turn_id": "turn_recovery_original",
        "response": {"bubble1": response_text},
        "content_messages": [{"type": "text", "text": response_text}],
        "images": [],
        "payment": {},
        "response_text": response_text,
        "delivery_result": {"status": "error", "reason": "original_failure"},
        "tagging_result": {"tags_to_add": []},
    }
    strategy_state = dict(loaded.session_doc.strategy_state or {})
    v7_state = dict(strategy_state.get("runtime_v7") or {})
    v7_state["followup"] = {
        "version": 2,
        "attempts": [
            {
                "attempt_id": "fu_recovery_original",
                "trigger_key": message_id + ":first",
                "conversation_anchor_id": message_id,
                "cadence": "first",
                "route": "customer_turn_recovery",
                "action": "send",
                "stance": "active",
                "focus_field": "",
                "status": ledger_status,
                "message_hash": "stored_hash",
                "evidence_refs": [message_id],
                "created_at": now_manila_str(),
                "updated_at": now_manila_str(),
                "delivery_result": replay["delivery_result"],
            }
        ],
    }
    strategy_state["runtime_v7"] = v7_state
    strategy_state["inbound_events_v1"] = [
        {
            "event_key": event_key,
            "status": ledger_status,
            "message_id": message_id,
            "result": {key: value for key, value in replay.items() if key != "_ledger_status"},
        }
    ]
    loaded.session_doc.strategy_state = strategy_state
    gateway.save(user_doc=loaded.user_doc, session_doc=loaded.session_doc)
    inbound_event = {"event_key": event_key, "message_id": message_id}
    hydration = ConversationHydrationResult(
        messages=[
            {
                "role": "user",
                "content": "Available pa po?",
                "datetime": now_manila_str(),
                "message_id": message_id,
            }
        ],
        channel_messages=[
            {
                "role": "user",
                "content": "Available pa po?",
                "datetime": now_manila_str(),
                "message_id": message_id,
            }
        ],
        source="manychat_load_messages",
        cache_status="refreshed",
        loader_status="success",
    )
    return loaded.session_doc, inbound_event, replay, hydration


def test_customer_recovery_replay_suppresses_confirmed_delivery(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_PRE_DELIVERY_FRESHNESS_CHECK", "0")
    gateway = _gateway()
    session_doc, inbound_event, replay, hydration = _customer_recovery_replay_fixture(
        gateway,
        ledger_status="delivered",
    )
    analytics = MemoryAnalyticsGateway()
    delivery = FakeDeliveryClient()
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        analytics_gateway=analytics,
        delivery_mode="send_content",
        fetch_manychat_messages=False,
        delivery_client_factory=lambda _request: delivery,
    )

    result = asyncio.run(
        service._handle_customer_recovery_replay(
            request=RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                user_text="Available pa po?",
                message_id=inbound_event["message_id"],
                delivery_mode="send_content",
                flow_context={"route": "customer_turn_recovery", "cadence": "first"},
            ),
            request_id="req_recovery_duplicate",
            trace_id="trace_recovery_duplicate",
            user_id="user_1",
            channel_user_id="mc_1",
            session_doc=session_doc,
            hydration=hydration,
            inbound_event=inbound_event,
            replay=replay,
        )
    )

    assert result.status == "suppressed"
    assert result.delivery_result["reason"] == "customer_turn_already_handled"
    assert delivery.calls == []
    assert analytics.followup_event_logs[-1]["route"] == "customer_turn_recovery"


def test_customer_recovery_already_delivered_event_emits_immediate_alert(monkeypatch):
    calls = []
    monkeypatch.setattr("runtime_v7.api_runtime.logger.error", lambda *args, **kwargs: calls.append((args, kwargs)))

    _emit_followup_alerts(
        {
            "request_id": "req_duplicate_recovery",
            "user_id": "user_redacted",
            "route": "customer_turn_recovery",
            "delivery_status": "suppressed",
            "delivery_reason": "customer_turn_already_handled",
            "validation_reasons": [],
            "meta": {},
        }
    )

    assert any("customer_recovery_already_delivered_event" in str(args) for args, _kwargs in calls)


def test_customer_recovery_ambiguous_delivery_emits_immediate_alert(monkeypatch):
    calls = []
    monkeypatch.setattr("runtime_v7.api_runtime.logger.error", lambda *args, **kwargs: calls.append((args, kwargs)))

    _emit_followup_alerts(
        {
            "request_id": "req_ambiguous_recovery",
            "user_id": "user_redacted",
            "route": "customer_turn_recovery",
            "delivery_status": "suppressed",
            "delivery_reason": "customer_turn_delivery_ambiguous",
            "validation_reasons": [],
            "meta": {},
        }
    )

    assert any("customer_recovery_delivery_ambiguous" in str(args) for args, _kwargs in calls)


def test_unknown_followup_delivery_emits_immediate_alert(monkeypatch):
    calls = []
    monkeypatch.setattr("runtime_v7.api_runtime.logger.error", lambda *args, **kwargs: calls.append((args, kwargs)))

    _emit_followup_alerts(
        {
            "request_id": "req_unknown_followup",
            "user_id": "user_redacted",
            "route": "proactive_followup",
            "attempt_status": "delivery_unknown",
            "delivery_status": "delivery_unknown",
            "validation_reasons": [],
            "meta": {},
        }
    )

    assert any("followup_delivery_unknown" in str(args) for args, _kwargs in calls)


def test_customer_recovery_replay_redelivers_stored_response_without_regeneration(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_PRE_DELIVERY_FRESHNESS_CHECK", "0")
    gateway = _gateway()
    session_doc, inbound_event, replay, hydration = _customer_recovery_replay_fixture(
        gateway,
        ledger_status="delivery_failed",
    )
    analytics = MemoryAnalyticsGateway()
    delivery = FakeDeliveryClient()
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        analytics_gateway=analytics,
        delivery_mode="send_content",
        fetch_manychat_messages=False,
        delivery_client_factory=lambda _request: delivery,
    )

    result = asyncio.run(
        service._handle_customer_recovery_replay(
            request=RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                user_text="Available pa po?",
                message_id=inbound_event["message_id"],
                delivery_mode="send_content",
                flow_context={"route": "customer_turn_recovery", "cadence": "first"},
            ),
            request_id="req_recovery_redelivery",
            trace_id="trace_recovery_redelivery",
            user_id="user_1",
            channel_user_id="mc_1",
            session_doc=session_doc,
            hydration=hydration,
            inbound_event=inbound_event,
            replay=replay,
        )
    )

    assert result.status == "success"
    assert result.delivery_result["reason"] == "customer_turn_stored_response_redelivered"
    assert len(delivery.calls) == 1
    stored = gateway.load(user_id="user_1", channel_user_id="mc_1").session_doc
    assert stored.strategy_state["inbound_events_v1"][-1]["status"] == "delivered"
    attempts = stored.strategy_state["runtime_v7"]["followup"]["attempts"]
    assert attempts[-1]["attempt_id"] == "fu_recovery_original"
    assert attempts[-1]["status"] == "sent"
    assert analytics.followup_event_logs[-1]["attempt_status"] == "sent"


def test_customer_recovery_replay_delivers_prior_return_only_render(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_PRE_DELIVERY_FRESHNESS_CHECK", "0")
    gateway = _gateway()
    session_doc, inbound_event, replay, hydration = _customer_recovery_replay_fixture(
        gateway,
        ledger_status="rendered",
    )
    delivery = FakeDeliveryClient()
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        delivery_mode="send_content",
        fetch_manychat_messages=False,
        delivery_client_factory=lambda _request: delivery,
    )

    result = asyncio.run(
        service._handle_customer_recovery_replay(
            request=RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                user_text="Available pa po?",
                message_id=inbound_event["message_id"],
                delivery_mode="send_content",
                flow_context={"route": "customer_turn_recovery", "cadence": "first"},
            ),
            request_id="req_recovery_rendered_delivery",
            trace_id="trace_recovery_rendered_delivery",
            user_id="user_1",
            channel_user_id="mc_1",
            session_doc=session_doc,
            hydration=hydration,
            inbound_event=inbound_event,
            replay=replay,
        )
    )

    assert result.status == "success"
    assert result.delivery_result["reason"] == "customer_turn_stored_response_redelivered"
    assert len(delivery.calls) == 1
    stored = gateway.load(user_id="user_1", channel_user_id="mc_1").session_doc
    assert stored.strategy_state["inbound_events_v1"][-1]["status"] == "delivered"


def test_customer_recovery_unknown_delivery_suppresses_when_transcript_unavailable(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_PRE_DELIVERY_FRESHNESS_CHECK", "0")
    gateway = _gateway()
    session_doc, inbound_event, replay, hydration = _customer_recovery_replay_fixture(
        gateway,
        ledger_status="delivery_unknown",
    )
    hydration.loader_status = "unavailable"
    delivery = FakeDeliveryClient()
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        delivery_mode="send_content",
        fetch_manychat_messages=False,
        delivery_client_factory=lambda _request: delivery,
    )

    result = asyncio.run(
        service._handle_customer_recovery_replay(
            request=RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                user_text="Available pa po?",
                message_id=inbound_event["message_id"],
                delivery_mode="send_content",
                flow_context={"route": "customer_turn_recovery", "cadence": "first"},
            ),
            request_id="req_recovery_ambiguous",
            trace_id="trace_recovery_ambiguous",
            user_id="user_1",
            channel_user_id="mc_1",
            session_doc=session_doc,
            hydration=hydration,
            inbound_event=inbound_event,
            replay=replay,
        )
    )

    assert result.status == "suppressed"
    assert result.delivery_result["reason"] == "customer_turn_delivery_ambiguous"
    assert delivery.calls == []


def test_customer_recovery_legacy_completed_without_delivery_proof_is_ambiguous(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_PRE_DELIVERY_FRESHNESS_CHECK", "0")
    gateway = _gateway()
    session_doc, inbound_event, replay, hydration = _customer_recovery_replay_fixture(
        gateway,
        ledger_status="completed",
    )
    replay["delivery_result"] = {}
    delivery = FakeDeliveryClient()
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        delivery_mode="send_content",
        fetch_manychat_messages=False,
        delivery_client_factory=lambda _request: delivery,
    )

    result = asyncio.run(
        service._handle_customer_recovery_replay(
            request=RuntimeV7APIRequest(
                user_id="user_1",
                channel_user_id="mc_1",
                user_text="Available pa po?",
                message_id=inbound_event["message_id"],
                delivery_mode="send_content",
                flow_context={"route": "customer_turn_recovery", "cadence": "first"},
            ),
            request_id="req_recovery_legacy_ambiguous",
            trace_id="trace_recovery_legacy_ambiguous",
            user_id="user_1",
            channel_user_id="mc_1",
            session_doc=session_doc,
            hydration=hydration,
            inbound_event=inbound_event,
            replay=replay,
        )
    )

    assert result.status == "suppressed"
    assert result.delivery_result["reason"] == "customer_turn_delivery_ambiguous"
    assert delivery.calls == []


def test_customer_recovery_return_only_state_does_not_claim_assistant_visibility():
    gateway = _gateway()
    _seed_session(gateway)
    loaded = gateway.load(user_id="user_1", channel_user_id="mc_1")
    service = RuntimeV7APIService(sessions_gateway=gateway, delivery_mode="return_only")
    original_messages = list(loaded.session_doc.messages)
    response_text = "Sorry po sa late reply. I-check natin ito."
    rendered = RuntimeV7ChannelRender(
        response={"bubble1": response_text},
        content_messages=[{"type": "text", "text": response_text}],
        text=response_text,
    )

    saved = service._save_customer_recovery_render_state(
        user_id="user_1",
        channel_user_id="mc_1",
        user_id_source="manychat",
        request_id="req_recovery_shadow",
        session_doc=loaded.session_doc,
        turn={
            "turn_id": "turn_recovery_shadow",
            "user_message": "Available pa po?",
            "runtime_final_response": response_text,
        },
        response_text=response_text,
        inbound_event={
            "event_key": "manychat:msg_recovery_shadow",
            "message_id": "msg_recovery_shadow",
            "message_id_source": "manychat_message_id",
        },
        rendered=rendered,
        delivery_result={"status": "skipped", "reason": "return_only"},
        tagging_result={"tags_to_add": [], "tag_apply_skipped": True},
    )

    stored = gateway.load(user_id="user_1", channel_user_id="mc_1").session_doc
    assert saved is True
    assert stored.messages == original_messages
    assert "channel_conversation_history_v1" not in stored.strategy_state
    assert stored.strategy_state["inbound_events_v1"][-1]["status"] == "rendered"
    assert stored.strategy_state["inbound_events_v1"][-1]["result"]["response_text"] == response_text
