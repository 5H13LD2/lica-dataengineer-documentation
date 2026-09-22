import asyncio
import json
from types import SimpleNamespace

from runtime.shared.types import MessageTurn
from apps.api.routers.gulong import ChatV7RequestPayload, _chat_v7_has_external_idempotency_basis
from runtime.gateways.sessions_gateway import SessionsGateway, SessionsGatewayConfig
from runtime.storage.session_store import MemorySessionStore
from runtime_v7.conversation_evidence import build_conversation_evidence_context
from runtime_v7.conversation_hydrator import (
    append_current_turn_to_channel_history,
    build_channel_history_cache,
    build_conversation_hydration_result,
    find_current_user_message,
    hydrate_conversation_history,
)
from runtime_v7.api_runtime import (
    RuntimeV7APIRequest,
    RuntimeV7APIResult,
    RuntimeV7APIService,
    build_runtime_v7_harness,
    _apply_button_only_ambiguity_envelope,
    _compact_llm_span,
    _conversation_messages_include_product_inclusions,
    _debug_session_store_diagnostics,
    _emit_normalized_turn_logs,
    _export_product_store,
    _export_harness_state,
    _hydrate_harness,
    _inbound_event_replay,
    _remember_channel_conversation_history,
    _remember_inbound_event,
    _rendered_product_inclusions_visible,
    _resolve_message_identity,
    _runtime_handoff_stop_reason,
)
from runtime_v7.channel_renderer import RuntimeV7ChannelRender
from runtime_v7.product_observations import ProductToolHarness
from runtime_v7.runtime_harness import RuntimeV7Harness
from runtime_v7.fulfillment_aliases import fulfillment_alias_candidates, resolve_fulfillment_alias
from runtime_v7.manychat_message_loader import _literal_env_dict, load_manychat_messages_fast
from runtime_v7.model_contract import build_runtime_v7_context
from runtime_v7.runtime_harness import _lead_qualification_with_selected_product
from runtime_v7.state_signals import build_commercial_state_context
from runtime_v7.tagging import evaluate_runtime_v7_tagging, mark_runtime_v7_tags_applied
from runtime_v7.turn_trace import build_inbound_event, build_inbound_event_key, build_turn_trace


def test_conversation_hydrator_merges_session_and_human_agent_history():
    hydrated = hydrate_conversation_history(
        session_messages=[
            MessageTurn(role="user", text="may continental kayo?", ts="2026-06-01 10:00:00"),
            MessageTurn(role="assistant", text="Wala pong Continental stock ngayon.", ts="2026-06-01 10:01:00"),
        ],
        request_history=[
            {
                "role": "agent",
                "content": "Customer is asking for Xpander 205/55R16 options.",
                "message_id": "agent_1",
                "datetime": "2026-06-01 10:02:00",
                "sender": "Jeanel",
            }
        ],
        current_message_id="msg_current",
        current_user_text="205/55R16",
    )

    assert [row["role"] for row in hydrated] == ["user", "assistant", "human_agent"]
    assert hydrated[-1]["source"] == "request_history"
    assert "Xpander" in hydrated[-1]["content"]


class _DummyRuntimeV7ModelClient:
    def complete(self, **_kwargs):
        return {}


def test_session_store_debug_diagnostics_are_strictly_allowlisted() -> None:
    exported = _debug_session_store_diagnostics(
        {
            "storage_kind": "firestore",
            "write_mode": "transactional_full_document_cas",
            "saved": True,
            "attempt_count": 1,
            "total_ms": 20_000.0,
            "read_ms": [150.0, "not-a-number"],
            "transaction_body_ms": [155.0],
            "commit_retry_overhead_ms": 19_845.0,
            "rpc_observer_status": "active",
            "commit_rpc_attempt_count": 2,
            "commit_rpc_attempt_ms": [10_000.0, 9_000.0, "bad"],
            "commit_rpc_process_cpu_ms": [9_500.0, 8_500.0],
            "commit_rpc_thread_cpu_ms": [500.0, 450.0],
            "commit_rpc_other_threads_cpu_ms": [9_000.0, 8_050.0],
            "commit_rpc_gc_collections": [[2, 1, 0], [0, 0, 1], "bad"],
            "commit_rpc_gc_collected": [[20, 5, 0], [0, 0, 2]],
            "commit_rpc_outcomes": ["error", "success", {"unsafe": "value"}],
            "commit_rpc_error_types": ["ServiceUnavailable", ""],
            "commit_rpc_status_codes": ["UNAVAILABLE", ""],
            "commit_rpc_gapic_retryable": [True, False, "bad"],
            "commit_rpc_transactional_retryable": [False, False],
            "rpc_unattributed_ms": 845.0,
            "process_id": 2,
            "instance_id_hash": "abc123",
            "active_saves_at_start": 1,
            "process_cpu_ms": 250.0,
            "payload_sizes_measured": True,
            "payload_json_bytes": 41_200,
            "strategy_state_json_bytes": 39_764,
            "diagnostic_overhead_ms": 0.5,
            "instrumented_call_total_ms": 20_000.5,
            "message_text": "must not escape",
            "strategy_state": {"secret": "must not escape"},
        }
    )

    assert exported["read_ms"] == [150.0]
    assert exported["payload_sizes_measured"] is True
    assert exported["diagnostic_overhead_ms"] == 0.5
    assert exported["commit_rpc_attempt_ms"] == [10_000.0, 9_000.0]
    assert exported["commit_rpc_thread_cpu_ms"] == [500.0, 450.0]
    assert exported["commit_rpc_gc_collections"] == [[2, 1, 0], [0, 0, 1]]
    assert exported["commit_rpc_outcomes"] == ["error", "success"]
    assert exported["commit_rpc_gapic_retryable"] == [True, False]
    assert exported["instance_id_hash"] == "abc123"
    assert "message_text" not in exported
    assert "strategy_state" not in exported


def test_compact_llm_span_preserves_final_composer_repair_observability():
    span = _compact_llm_span(
        {
            "component": "final_composer",
            "round": "final_composer_repair",
            "attempt_kind": "contract_repair",
            "repair_reason": "contract_violations",
            "violation_types": [
                "missing_required_surface",
                "unauthorized_claim_category",
            ],
            "provider_call_count": 2,
            "metered_provider_call_count": 2,
            "usage_summary": {"prompt_tokens": 123},
        },
        index=2,
    )

    assert span["component"] == "final_composer"
    assert span["round"] == "final_composer_repair"
    assert span["attempt_kind"] == "contract_repair"
    assert span["repair_reason"] == "contract_violations"
    assert span["violation_types"] == [
        "missing_required_surface",
        "unauthorized_claim_category",
    ]
    assert span["provider_call_count"] == 2
    assert span["metered_provider_call_count"] == 2


def test_turn_trace_log_persists_durable_moderate_qualification(monkeypatch):
    monkeypatch.setenv("SERVICE_ENVIRONMENT", "staging")
    monkeypatch.setenv("RUNTIME_HOST", "runtime-staging")
    monkeypatch.setenv("RELEASE_VERSION", "qualification-test")
    monkeypatch.setenv("GIT_SHA", "deadbeef")

    class TraceAnalytics:
        def __init__(self):
            self.debug_rows = []
            self.turn_trace_rows = []

        def enqueue_debug_log(self, row):
            self.debug_rows.append(dict(row))

        def enqueue_turn_trace_log(self, row):
            self.turn_trace_rows.append(dict(row))

    analytics = TraceAnalytics()
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        analytics_gateway=analytics,
        delivery_mode="return_only",
    )
    request = RuntimeV7APIRequest(
        user_id="user-trace-qualification",
        channel_user_id="channel-user-trace-qualification",
        channel="manychat",
        user_text="225/55R18 Hankook Makati",
        message_id="msg-trace-qualification",
        channel_event_id="evt-trace-qualification",
        channel_event_ts="2026-08-11T10:30:00+08:00",
        idempotency_key="idem-trace-qualification",
        request_time="2026-08-11T10:30:01+08:00",
        flow_context={
            "choice_action_runtime_context": {
                "surface_type": "product_choices",
                "presentation_ref": "pres-trace-products",
                "card_ref": "card-trace-hankook",
                "choice_type": "product_selection",
                "choice_ref": "card-trace-hankook",
            }
        },
    )
    tagging = mark_runtime_v7_tags_applied(
        evaluate_runtime_v7_tagging(
            current_user_message=request.user_text,
            background_signals=[
                {"key": "tire_size", "value": "225/55R18"},
                {"key": "tire_brand", "value": "Hankook"},
                {"key": "location", "value": "Makati"},
            ],
            lead_qualification={"moderate_intent": True, "lead_stage": "complete"},
            tool_results=[],
        ),
        applied_tags=["Moderate Intent"],
        apply_status="success",
    )
    inbound_event = build_inbound_event(
        request_id="req-trace-qualification",
        trace_id="trace-qualification",
        runtime_version="v7",
        user_id=request.user_id,
        channel_user_id=request.channel_user_id,
        channel=request.channel,
        message_id=request.message_id,
        idempotency_key=request.idempotency_key,
        channel_event_id=request.channel_event_id,
        channel_event_ts=request.channel_event_ts,
    )
    turn = {
        "turn_id": "turn-trace-qualification",
        "tool_results": [],
        "llm_calls": [],
        "tagging": tagging,
    }
    trace = build_turn_trace(
        inbound_event=inbound_event,
        turn_record=turn,
        delivery_result={"status": "success"},
        tagging_result=tagging,
        state_saved=True,
    )

    service._persist_turn_trace(
        request=request,
        turn=turn,
        rendered=RuntimeV7ChannelRender(response={}, content_messages=[]),
        turn_trace=trace,
        delivery_result={"status": "success"},
        tagging_result=tagging,
        session_id="session-trace-qualification",
        request_id="req-trace-qualification",
        trace_id="trace-qualification",
        user_id=request.user_id,
    )

    qualification = analytics.turn_trace_rows[0]["tagging"]["analytical_qualifications"][0]
    assert qualification["qualification_level"] == "moderate"
    assert qualification["event_identity"]["idempotency_key"] == "idem-trace-qualification"
    assert qualification["environment"]["service_environment"] == "staging"
    assert qualification["context"] == {
        "user_id": "user-trace-qualification",
        "channel_user_id": "channel-user-trace-qualification",
        "session_id": "session-trace-qualification",
        "trace_id": "trace-qualification",
        "turn_id": "turn-trace-qualification",
        "channel": "manychat",
        "runtime_version": "v7",
    }
    assert qualification["interaction_context"] == {
        "surface_type": "product_choices",
        "presentation_ref": "pres-trace-products",
        "card_ref": "card-trace-hankook",
        "choice_type": "product_selection",
        "choice_ref": "card-trace-hankook",
    }
    assert qualification["tag_application_outcome"]["moderate_tag_outcome"] == "applied"


def test_product_inclusions_sent_state_survives_harness_export_hydration():
    harness = RuntimeV7Harness(model_client=_DummyRuntimeV7ModelClient(), tools=ProductToolHarness())
    harness.product_inclusions_sent = True

    state = _export_harness_state(harness)
    restored = RuntimeV7Harness(model_client=_DummyRuntimeV7ModelClient(), tools=ProductToolHarness())
    _hydrate_harness(restored, state)

    assert state["product_inclusions_sent"] is True
    assert restored.product_inclusions_sent is True


def test_legacy_memory_note_is_migrated_once_to_active_working_memory():
    restored = RuntimeV7Harness(model_client=_DummyRuntimeV7ModelClient(), tools=ProductToolHarness())
    _hydrate_harness(
        restored,
        {
            "memory_note": "Customer is comparing highway-terrain options for a Ford Everest.",
            "active_working_memory": {},
        },
    )

    memory = restored.memory_store.load(restored.session_id)
    state = _export_harness_state(restored)
    assert memory.text == "Customer is comparing highway-terrain options for a Ford Everest."
    assert memory.source == "legacy_memory_note_migration"
    assert "memory_note" not in state
    assert state["active_working_memory"]["text"] == memory.text


def test_active_working_memory_wins_over_legacy_memory_note_during_hydration():
    restored = RuntimeV7Harness(model_client=_DummyRuntimeV7ModelClient(), tools=ProductToolHarness())
    _hydrate_harness(
        restored,
        {
            "memory_note": "Stale legacy note.",
            "active_working_memory": {
                "text": "Customer selected a validated product card and is checking Cebu installation.",
                "version": 4,
                "source": "hybrid_model",
            },
        },
    )

    memory = restored.memory_store.load(restored.session_id)
    assert memory.text == "Customer selected a validated product card and is checking Cebu installation."
    assert memory.version == 4
    assert memory.source == "hybrid_model"


def test_active_working_memory_round_trip_has_no_duplicate_legacy_field():
    harness = RuntimeV7Harness(model_client=_DummyRuntimeV7ModelClient(), tools=ProductToolHarness())
    harness.memory_updater.seed(
        harness.session_id,
        "Customer wants two touring tires and prefers pickup in Davao City.",
        source="test_seed",
    )

    state = _export_harness_state(harness)
    restored = RuntimeV7Harness(model_client=_DummyRuntimeV7ModelClient(), tools=ProductToolHarness())
    _hydrate_harness(restored, state)

    assert "memory_note" not in state
    assert restored.memory_store.load(restored.session_id).text == state["active_working_memory"]["text"]


def test_service_policy_note_delivery_state_survives_harness_export_hydration():
    harness = RuntimeV7Harness(model_client=_DummyRuntimeV7ModelClient(), tools=ProductToolHarness())
    harness.service_policy_note_ids_sent = ["no_walkin_setup"]

    state = _export_harness_state(harness)
    restored = RuntimeV7Harness(model_client=_DummyRuntimeV7ModelClient(), tools=ProductToolHarness())
    _hydrate_harness(restored, state)

    assert state["service_policy_note_ids_sent"] == ["no_walkin_setup"]
    assert restored.service_policy_note_ids_sent == ["no_walkin_setup"]


def test_human_handoff_state_survives_harness_export_and_suppresses_followup():
    harness = RuntimeV7Harness(
        model_client=_DummyRuntimeV7ModelClient(),
        tools=ProductToolHarness(),
    )
    harness.human_handoff_state = {
        "status": "requested",
        "requested_at": "2026-08-01 09:00:00",
        "human_assignment_confirmed": False,
    }

    state = _export_harness_state(harness)
    restored = RuntimeV7Harness(
        model_client=_DummyRuntimeV7ModelClient(),
        tools=ProductToolHarness(),
    )
    _hydrate_harness(restored, state)

    assert restored.human_handoff_state == harness.human_handoff_state
    assert _runtime_handoff_stop_reason(state) == (
        "runtime_human_handoff_requested"
    )
    assert _runtime_handoff_stop_reason({}) == ""


def test_chat_ingress_suppresses_after_durable_human_handoff_request():
    store = MemorySessionStore()
    gateway = SessionsGateway(
        config=SessionsGatewayConfig(
            project_id="test",
            users_collection="users",
            sessions_subcollection="sessions",
            storage_kind="memory",
        ),
        store=store,
    )
    loaded = gateway.load(
        user_id="user_handoff_suppressed",
        channel_user_id="user_handoff_suppressed",
    )
    session = loaded.session_doc
    session.strategy_state = {
        "runtime_v7": {
            "version": 1,
            "session_id": session.session_id,
            "human_handoff_state": {
                "status": "requested",
                "requested_at": "2026-08-01 09:00:00",
                "human_assignment_confirmed": False,
            },
        }
    }
    store.save_session(
        "user_handoff_suppressed",
        session.session_id,
        session.to_dict(),
    )

    model = _DummyRuntimeV7ModelClient()
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        harness_factory=lambda session_id, _profile, _trace: RuntimeV7Harness(
            model_client=model,
            tools=ProductToolHarness(),
            session_id=session_id,
        ),
        delivery_mode="return_only",
        fetch_manychat_messages=False,
    )

    result = asyncio.run(
        service.handle(
            RuntimeV7APIRequest(
                user_id="user_handoff_suppressed",
                channel_user_id="user_handoff_suppressed",
                channel="manychat",
                user_text="May update na po?",
                message_id="msg_after_handoff",
                delivery_mode="return_only",
            ),
            request_id="req_after_handoff",
        )
    )

    assert result.status == "suppressed"
    assert result.content_messages == []
    assert result.delivery_result["reason"] == (
        "runtime_human_handoff_requested"
    )
    assert result.turn_record["llm_calls"] == []


def test_inbound_event_state_compacts_nested_delivery_and_handoff_payloads():
    state = {}
    inbound_event = {
        "event_key": "event_user_msg_1",
        "message_id": "msg_1",
        "message_id_source": "manychat",
        "channel_event_id": "evt_1",
        "dedupe_eligible": True,
        "received_at": "2026-06-28 10:00:00",
    }
    rendered = RuntimeV7ChannelRender(
        response={"bubble1": "May budget options po tayo."},
        content_messages=[{"type": "text", "text": "May budget options po tayo."}],
        images=[],
        payment={},
    )
    delivery_result = {
        "status": "success",
        "delivery_results": [
            {
                "status": "success",
                "raw": {
                    "data": {
                        "messages": [
                            [{"deep": {"value": "x" * 2000}}],
                            [{"deep": {"value": "y" * 2000}}],
                        ]
                    }
                },
            }
        ],
    }
    tagging_result = {
        "tags_applied": ["Moderate Intent"],
        "handoff_note": {
            "tag": "Moderate Intent",
            "status": "success",
            "preview": "Customer may be moderate intent.",
            "result": {
                "status": "success",
                "data": {
                    "messages": [
                        [{"nested": {"body": "raw note response should not persist"}}],
                    ]
                },
            },
        },
    }

    _remember_inbound_event(
        state,
        inbound_event=inbound_event,
        turn={"turn_id": "turn_1"},
        rendered=rendered,
        delivery_result=delivery_result,
        tagging_result=tagging_result,
        response_text="May budget options po tayo.",
    )

    saved_result = state["inbound_events_v1"][0]["result"]
    encoded = str(saved_result)
    assert saved_result["response"] == {"bubble1": "May budget options po tayo."}
    assert saved_result["content_messages"][0]["text"] == "May budget options po tayo."
    assert saved_result["tagging_result"]["handoff_note"] == {
        "tag": "Moderate Intent",
        "status": "success",
        "preview": "Customer may be moderate intent.",
    }
    assert "raw note response should not persist" not in encoded
    assert "messages" not in str(saved_result["tagging_result"]["handoff_note"])
    replay = _inbound_event_replay(state, inbound_event)
    assert replay["response"] == {"bubble1": "May budget options po tayo."}
    assert replay["tagging_result"]["tags_applied"] == ["Moderate Intent"]


def test_product_inclusions_sent_can_be_inferred_from_prior_visible_history():
    assert _conversation_messages_include_product_inclusions(
        [
            {"role": "assistant", "content": "Warranty and inclusions:\n- Install with our authorized Installation Partners and get:"}
        ]
    )


def test_double_warranty_catalog_card_counts_as_visible_product_inclusions():
    rendered = RuntimeV7ChannelRender(
        response={"bubble1": "Warranty details are shown below."},
        content_messages=[
            {
                "type": "cards",
                "elements": [{"title": "THE GULONG DOUBLE WARRANTY"}],
            }
        ],
        promo_presentation={
            "promo_refs": ["promo:the-gulong-double-warranty"],
        },
    )

    assert _rendered_product_inclusions_visible(rendered) is True


def test_api_channel_renderer_receives_pre_turn_product_inclusions_state(monkeypatch):
    gateway = SessionsGateway(
        config=SessionsGatewayConfig(
            project_id="test",
            users_collection="users",
            sessions_subcollection="sessions",
            storage_kind="memory",
        ),
        store=MemorySessionStore(),
    )
    captured = {}

    class FakeHarness:
        def __init__(self, session_id, *_args):
            self.session_id = session_id
            self.product_inclusions_sent = False

        def run_turn(self, user_text, **_kwargs):
            self.product_inclusions_sent = True
            return {
                "turn_id": "turn_1",
                "user_message": user_text,
                "runtime_final_response": "Warranty and inclusions:\n- First visible inclusions block",
                "tool_results": [],
                "llm_calls": [],
                "response_guard_events": [],
                "tagging": {},
            }

    def fake_render(turn, **_kwargs):
        captured["product_inclusions_previously_sent"] = turn.get("product_inclusions_previously_sent")
        return RuntimeV7ChannelRender(
            response={"bubble1": "Warranty and inclusions:\n- First visible inclusions block"},
            content_messages=[
                {"type": "text", "text": "Warranty and inclusions:\n- First visible inclusions block"}
            ],
            text="Warranty and inclusions:\n- First visible inclusions block",
        )

    monkeypatch.setattr("runtime_v7.api_runtime.render_turn_for_channel", fake_render)
    monkeypatch.setattr(
        "runtime_v7.api_runtime._export_harness_state",
        lambda harness: {"product_inclusions_sent": bool(harness.product_inclusions_sent)},
    )

    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        harness_factory=lambda session_id, profile_fields, trace_id: FakeHarness(session_id),
        delivery_mode="return_only",
        fetch_manychat_messages=False,
    )
    result = __import__("asyncio").run(
        service.handle(
            RuntimeV7APIRequest(
                user_id="user_inclusions_ordering",
                channel="manychat",
                user_text="hm 175 65 14",
                return_logs=True,
                delivery_mode="return_only",
            ),
            request_id="req_inclusions_ordering",
        )
    )

    payload = result.to_payload(include_debug=True)

    assert payload["status"] == "success"
    assert captured["product_inclusions_previously_sent"] is False
    assert "Warranty and inclusions:" in payload["response"]["bubble1"]
    phase_timings = payload["debug"]["runtime_phase_timings_ms"]
    assert phase_timings["session_state_assembly"] >= 0
    assert phase_timings["session_store_save"] >= 0
    assert phase_timings["session_persistence"] + 0.01 >= (
        phase_timings["session_state_assembly"]
        + phase_timings["session_store_save"]
    )
    assert payload["debug"]["session_store_diagnostics"] == {}


def test_inbound_event_key_prefers_provider_event_id_and_not_derived_message_id():
    provider_key = build_inbound_event_key(
        user_id="u1",
        channel="manychat",
        channel_event_id="mc_event_123",
        message_id="msg_generated",
        message_id_source="derived",
        normalized_payload={"user_text": "hi"},
    )
    derived_key_1 = build_inbound_event_key(
        user_id="u1",
        channel="manychat",
        message_id="msg_generated",
        message_id_source="derived",
        normalized_payload={"user_text": "hi"},
        channel_event_ts="2026-06-01 10:00:01",
    )
    derived_key_2 = build_inbound_event_key(
        user_id="u1",
        channel="manychat",
        message_id="msg_generated",
        message_id_source="derived",
        normalized_payload={"user_text": "hi"},
        channel_event_ts="2026-06-01 10:00:09",
    )

    assert provider_key.startswith("evt_")
    assert derived_key_1 != derived_key_2


def test_inbound_event_without_provider_id_or_timestamp_is_not_replay_eligible():
    event = build_inbound_event(
        request_id="req_1",
        trace_id="trace_1",
        runtime_version="v7",
        user_id="u1",
        channel_user_id="u1",
        channel="manychat",
        message_id="msg_generated",
        message_id_source="derived",
        idempotency_key="msg_generated",
        normalized_payload={"user_text": "hi"},
    )

    assert event["dedupe_eligible"] is False


def test_loaded_manychat_message_id_becomes_replay_eligible_identity():
    hydration = build_conversation_hydration_result(
        loaded_channel_history=[
            {
                "role": "agent",
                "content": {"text": "Customer asked for Wigo rim 14 earlier."},
                "message_id": "agent_1",
                "datetime": "2026-06-01 10:00:00",
            },
            {
                "role": "user",
                "content": {"text": "may promo kayo sa apollo pang wigo? rim 14 sana"},
                "message_id": "mc_msg_123",
                "datetime": "2026-06-01 10:01:00",
            },
        ],
        current_user_text="may promo kayo sa apollo pang wigo? rim 14 sana",
        refresh_attempted=True,
        loader_status="success",
    )
    identity = _resolve_message_identity(
        RuntimeV7APIRequest(user_id="u1", user_text="may promo kayo sa apollo pang wigo? rim 14 sana"),
        hydration=hydration,
        user_id="u1",
    )
    event = build_inbound_event(
        request_id="req_1",
        trace_id="trace_1",
        runtime_version="v7",
        user_id="u1",
        channel_user_id="u1",
        channel="manychat",
        message_id=identity["message_id"],
        message_id_source=identity["message_id_source"],
        idempotency_key=identity["message_id"],
        normalized_payload={"user_text": "may promo kayo sa apollo pang wigo? rim 14 sana"},
    )

    assert identity == {"message_id": "mc_msg_123", "message_id_source": "manychat_load_messages"}
    assert event["dedupe_eligible"] is True


def test_channel_history_cache_can_short_circuit_current_message_lookup():
    cached_messages = append_current_turn_to_channel_history(
        [],
        user_text="hi may 175 65 14 kayo?",
        assistant_text="Meron po.",
        user_message_id="mc_msg_1",
        assistant_message_id="bot_msg_1",
        timestamp="2026-06-01 10:00:00",
    )
    cache = build_channel_history_cache(cached_messages, source="firestore_runtime_cache", refresh_status="refreshed")
    current = find_current_user_message(
        cache["messages"],
        current_user_text="hi may 175 65 14 kayo?",
    )

    assert cache["latest_message_id"] == "bot_msg_1"
    assert current["message_id"] == "mc_msg_1"


def test_cloudsql_compare_metadata_does_not_replace_hydrated_messages(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_MANYCHAT_CLOUDSQL_COMPARE_ENABLED", "1")
    calls = []

    def fake_cloudsql_reader(**kwargs):
        calls.append(kwargs)
        return {
            "status": "success",
            "latency_ms": 2,
            "row_count": 1,
            "data": [
                {
                    "role": "user",
                    "content": "hm 175 65 14",
                    "message_id": "mc_msg_1",
                    "datetime": "2026-07-09 10:00:00",
                    "source": "manychat_cloudsql_messages",
                }
            ],
        }

    monkeypatch.setattr("runtime_v7.api_runtime.load_manychat_messages_from_cloudsql", fake_cloudsql_reader)
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        conversation_history_loader=lambda _request: {
            "status": "success",
            "data": [
                {
                    "role": "user",
                    "content": "hm 175 65 14",
                    "message_id": "mc_msg_1",
                    "datetime": "2026-07-09 10:00:00",
                    "source": "manychat_load_messages_fast",
                }
            ],
        },
        fetch_manychat_messages=False,
    )

    hydration = asyncio.run(
        service._hydrate_conversation_for_turn(
            RuntimeV7APIRequest(
                user_id="u1",
                channel="manychat",
                user_text="hm 175 65 14",
                message_id="mc_msg_1",
            ),
            session_doc=SimpleNamespace(messages=[], strategy_state={}),
            state={},
        )
    )

    assert calls and calls[0]["user_id"] == "u1"
    assert hydration.source == "manychat_load_messages"
    assert hydration.channel_messages[0]["source"] == "manychat_load_messages"
    assert hydration.metadata["cloudsql_read_compare"]["match_status"] == "covered"


def test_cloudsql_compare_sampling_can_skip_reader(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_MANYCHAT_CLOUDSQL_COMPARE_ENABLED", "1")
    monkeypatch.setenv("RUNTIME_V7_MANYCHAT_CLOUDSQL_COMPARE_SAMPLE_RATE", "0")

    def fail_if_called(**_kwargs):
        raise AssertionError("Cloud SQL reader should not run when sample rate is zero")

    monkeypatch.setattr("runtime_v7.api_runtime.load_manychat_messages_from_cloudsql", fail_if_called)
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        conversation_history_loader=lambda _request: {
            "status": "success",
            "data": [
                {
                    "role": "user",
                    "content": "hm 175 65 14",
                    "message_id": "mc_msg_1",
                    "datetime": "2026-07-09 10:00:00",
                }
            ],
        },
        fetch_manychat_messages=False,
    )

    hydration = asyncio.run(
        service._hydrate_conversation_for_turn(
            RuntimeV7APIRequest(
                user_id="u1",
                channel="manychat",
                user_text="hm 175 65 14",
                message_id="mc_msg_1",
            ),
            session_doc=SimpleNamespace(messages=[], strategy_state={}),
            state={},
        )
    )

    assert "cloudsql_read_compare" not in hydration.metadata


def test_conversation_hydration_starts_new_segment_when_prior_message_is_too_old():
    hydration = build_conversation_hydration_result(
        loaded_channel_history=[
            {
                "role": "user",
                "content": "old tire inquiry",
                "message_id": "old_1",
                "datetime": "2026-01-01 10:00:00",
            },
            {
                "role": "user",
                "content": "hi may 175 65 14 kayo?",
                "message_id": "current_1",
                "datetime": "2026-02-05 10:00:00",
            },
        ],
        current_user_text="hi may 175 65 14 kayo?",
        current_message_datetime="2026-02-05 10:00:00",
        message_age_days=30,
    )

    assert hydration.messages == []
    assert [row["message_id"] for row in hydration.channel_messages] == ["current_1"]
    assert hydration.metadata["segment_message_count"] == 1


def test_conversation_hydration_breaks_on_partial_day_over_age_gap():
    hydration = build_conversation_hydration_result(
        loaded_channel_history=[
            {
                "role": "user",
                "content": "old tire inquiry with stale quote",
                "message_id": "old_1",
                "datetime": "2026-01-01 10:00:00",
            },
            {
                "role": "user",
                "content": "hi po",
                "message_id": "current_1",
                "datetime": "2026-01-31 10:01:00",
            },
        ],
        current_user_text="hi po",
        current_message_datetime="2026-01-31 10:01:00",
        message_age_days=30,
    )

    assert hydration.messages == []
    assert [row["message_id"] for row in hydration.channel_messages] == ["current_1"]


def test_conversation_hydration_drops_unparseable_history_when_current_datetime_is_known():
    hydration = build_conversation_hydration_result(
        loaded_channel_history=[
            {
                "role": "user",
                "content": "hi po",
                "message_id": "current_1",
                "datetime": "2026-06-24 10:00:00",
            }
        ],
        request_history=[
            {
                "role": "user",
                "content": "old quote had four tires and a budget",
                "message_id": "old_unparseable",
                "datetime": "Jan 1 2024 10AM",
            }
        ],
        current_user_text="hi po",
        current_message_datetime="2026-06-24 10:00:00",
        message_age_days=30,
    )

    assert hydration.messages == []
    assert [row["message_id"] for row in hydration.channel_messages] == ["current_1"]


def test_conversation_hydration_keeps_contiguous_recent_segment():
    hydration = build_conversation_hydration_result(
        loaded_channel_history=[
            {
                "role": "user",
                "content": "may yokohama?",
                "message_id": "prior_1",
                "datetime": "2026-02-01 10:00:00",
            },
            {
                "role": "assistant",
                "content": "Ano pong tire size?",
                "message_id": "bot_1",
                "datetime": "2026-02-01 10:01:00",
            },
            {
                "role": "user",
                "content": "175 65 14",
                "message_id": "current_1",
                "datetime": "2026-02-05 10:00:00",
            },
        ],
        current_user_text="175 65 14",
        current_message_datetime="2026-02-05 10:00:00",
        message_age_days=30,
    )

    assert [row["message_id"] for row in hydration.messages] == ["prior_1", "bot_1"]
    assert [row["message_id"] for row in hydration.channel_messages] == ["prior_1", "bot_1", "current_1"]


def test_conversation_hydration_reset_drops_prior_history_even_if_recent():
    hydration = build_conversation_hydration_result(
        cached_channel_history={
            "messages": [
                {
                    "role": "user",
                    "content": "may apollo?",
                    "message_id": "prior_1",
                    "datetime": "2026-02-04 10:00:00",
                },
                {
                    "role": "user",
                    "content": "fresh start",
                    "message_id": "current_1",
                    "datetime": "2026-02-05 10:00:00",
                },
            ]
        },
        current_user_text="fresh start",
        current_message_datetime="2026-02-05 10:00:00",
        reset_requested=True,
    )

    assert hydration.messages == []
    assert [row["message_id"] for row in hydration.channel_messages] == ["current_1"]
    assert hydration.cache_status == "reset"


def test_reset_segment_is_persisted_and_used_by_next_non_reset_turn():
    hydration = build_conversation_hydration_result(
        cached_channel_history={
            "messages": [
                {
                    "role": "user",
                    "content": "old cached inquiry",
                    "message_id": "old_1",
                    "datetime": "2026-02-04 10:00:00",
                }
            ]
        },
        current_user_text="fresh start",
        current_message_datetime="2026-02-05 10:00:00",
        reset_requested=True,
    )
    strategy_state = {}

    _remember_channel_conversation_history(
        strategy_state,
        hydration=hydration,
        user_text="fresh start",
        assistant_text="Ano pong tire size?",
        user_message_id="derived_fresh_start",
        assistant_message_id="bot_after_reset",
        timestamp="2026-02-05 10:00:00",
    )
    cache = strategy_state["channel_conversation_history_v1"]
    next_turn = build_conversation_hydration_result(
        cached_channel_history=cache,
        current_user_text="175 65 14",
        current_message_datetime="2026-02-05 10:02:00",
        reset_requested=False,
    )

    assert [row["message_id"] for row in cache["messages"]] == ["derived_fresh_start", "bot_after_reset"]
    assert [row["message_id"] for row in next_turn.messages] == ["derived_fresh_start", "bot_after_reset"]


def test_cached_history_drops_messages_before_internal_age_gap_not_request_age_only():
    hydration = build_conversation_hydration_result(
        cached_channel_history={
            "messages": [
                {
                    "role": "user",
                    "content": "old January inquiry",
                    "message_id": "old_1",
                    "datetime": "2026-01-01 10:00:00",
                },
                {
                    "role": "assistant",
                    "content": "old January reply",
                    "message_id": "old_bot_1",
                    "datetime": "2026-01-01 10:01:00",
                },
                {
                    "role": "user",
                    "content": "recent February inquiry",
                    "message_id": "recent_1",
                    "datetime": "2026-02-05 10:00:00",
                },
                {
                    "role": "assistant",
                    "content": "recent February reply",
                    "message_id": "recent_bot_1",
                    "datetime": "2026-02-05 10:01:00",
                },
            ]
        },
        current_user_text="175 65 14",
        current_message_datetime="2026-02-05 10:03:00",
        message_age_days=30,
    )

    assert [row["message_id"] for row in hydration.channel_messages] == ["recent_1", "recent_bot_1"]
    assert [row["message_id"] for row in hydration.messages] == ["recent_1", "recent_bot_1"]


def test_hydrate_conversation_history_drops_old_session_messages_before_current_turn():
    hydrated = hydrate_conversation_history(
        session_messages=[
            MessageTurn(role="user", text="old request", ts="2026-01-01 10:00:00"),
            MessageTurn(role="assistant", text="old reply", ts="2026-01-01 10:01:00"),
        ],
        current_user_text="new request",
        current_message_datetime="2026-02-05 10:00:00",
        message_age_days=30,
    )

    assert hydrated == []


def test_runtime_v7_manychat_loader_extracts_compact_text_without_legacy_sleep():
    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "messages": [
                    {
                        "type": "msgout_api",
                        "timestamp": 1780000001,
                        "message_id": "bot_1",
                        "model": {"messages": [{"type": "text", "content": {"text": "Meron po tayo."}}]},
                    },
                    {
                        "type": "msgin",
                        "timestamp": 1780000000,
                        "message_id": "user_1",
                        "model": {"messages": [{"type": "text", "content": {"text": "hi hm 175 65 14"}}]},
                    },
                ]
            }

    calls = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        return FakeResponse()

    result = load_manychat_messages_fast(
        user_id="u1",
        limit=20,
        timeout_s=3,
        page_id="page_1",
        headers={"h": "1"},
        cookies={"c": "1"},
        transport_get=fake_get,
    )

    assert result["status"] == "success"
    assert [row["role"] for row in result["data"]] == ["user", "assistant"]
    assert result["data"][0]["content"] == "hi hm 175 65 14"
    assert 2.9 <= calls[0]["kwargs"]["timeout"] <= 3
    assert calls[0]["kwargs"]["params"]["limit"] == 20
    assert "/fbpage_1/im/loadMessages" in calls[0]["url"]
    assert "/fb/page_1/im/loadMessages" not in calls[0]["url"]


def test_runtime_v7_manychat_loader_parses_commented_app_header_secret(monkeypatch):
    monkeypatch.setattr(
        "runtime_v7.manychat_message_loader.ENV",
        {
            "MANYCHAT_APP_HEADERS": """{
                'accept': 'application/json',
                # 'cookie': 'session=old',
                'x-requested-with': 'XMLHttpRequest'
            """
        },
    )

    parsed = _literal_env_dict("MANYCHAT_APP_HEADERS")

    assert parsed == {
        "accept": "application/json",
        "x-requested-with": "XMLHttpRequest",
    }


def test_runtime_v7_followup_refreshes_channel_history_even_without_user_text():
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        conversation_history_loader=lambda _request: {"status": "success", "data": []},
        fetch_manychat_messages=False,
    )
    cache = {
        "messages": [
            {
                "role": "assistant",
                "content": "May options po tayo.",
                "message_id": "assistant_old",
                "datetime": "2026-06-28 09:00:00",
            }
        ]
    }

    followup_request = RuntimeV7APIRequest(
        user_id="user_1",
        channel_user_id="user_1",
        channel="manychat",
        user_text="",
        flow_context={"trigger": "followup_endpoint"},
    )
    normal_request = RuntimeV7APIRequest(
        user_id="user_1",
        channel_user_id="user_1",
        channel="manychat",
        user_text="",
    )

    assert service._should_refresh_channel_history(followup_request, cache) is True
    assert service._should_refresh_channel_history(normal_request, cache) is False


def test_runtime_v7_repeated_text_without_provider_id_refreshes_history():
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        conversation_history_loader=lambda _request: {"status": "success", "data": []},
        fetch_manychat_messages=False,
    )
    cache = {
        "messages": [
            {
                "role": "user",
                "content": "yes",
                "message_id": "msg_previous_yes",
                "datetime": "2026-07-28 16:00:00",
            }
        ]
    }
    request = RuntimeV7APIRequest(
        user_id="user_1",
        channel="manychat",
        user_text="yes",
    )

    assert service._should_refresh_channel_history(request, cache) is True


def test_runtime_v7_repeated_text_uses_provider_id_for_cache_identity():
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        conversation_history_loader=lambda _request: {"status": "success", "data": []},
        fetch_manychat_messages=False,
    )
    cache = {
        "messages": [
            {
                "role": "user",
                "content": "yes",
                "message_id": "msg_previous_yes",
                "datetime": "2026-07-28 16:00:00",
            }
        ]
    }

    duplicate_request = RuntimeV7APIRequest(
        user_id="user_1",
        channel="manychat",
        user_text="yes",
        message_id="msg_previous_yes",
    )
    new_repeated_request = RuntimeV7APIRequest(
        user_id="user_1",
        channel="manychat",
        user_text="yes",
        message_id="msg_new_yes",
    )

    assert service._should_refresh_channel_history(duplicate_request, cache) is False
    assert service._should_refresh_channel_history(new_repeated_request, cache) is True


def test_lock_recovery_selects_new_provider_event_when_text_is_identical():
    messages = [
        {
            "role": "user",
            "content": "yes",
            "message_id": "msg_previous_yes",
            "datetime": "2026-07-28 16:00:00",
        },
        {
            "role": "user",
            "content": "yes",
            "message_id": "msg_new_yes",
            "datetime": "2026-07-28 16:00:05",
        },
    ]
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        conversation_history_loader=lambda _request: {
            "status": "success",
            "data": messages,
        },
        fetch_manychat_messages=False,
    )
    request = RuntimeV7APIRequest(
        user_id="user_1",
        channel="manychat",
        user_text="yes",
        message_id="msg_previous_yes",
        message_id_source="provided",
    )

    recovered, recovery = asyncio.run(
        service._request_with_latest_customer_message_for_lock_recovery(
            request,
            processed_message_ids={"msg_previous_yes"},
        )
    )

    assert recovered.message_id == "msg_new_yes"
    assert recovered.user_text == "yes"
    assert recovery["message_selection"] == "latest_user_message"
    assert recovery["selected_message_id"] == "msg_new_yes"


def test_runtime_v7_choice_action_uses_session_cache_without_channel_refresh():
    def fail_if_called(_request):
        raise AssertionError("choice actions must not reload the visible transcript")

    service = RuntimeV7APIService(
        sessions_gateway=object(),
        conversation_history_loader=fail_if_called,
        fetch_manychat_messages=False,
    )
    request = RuntimeV7APIRequest(
        user_id="trial",
        channel="manychat",
        user_text="I selected the delivered Apollo card.",
        flow_context={
            "trigger": "choice_action",
            "choice_action_context": {
                "choice_type": "product_selection",
                "presentation_ref": "pres_products",
            },
        },
    )

    assert service._should_refresh_channel_history(request, {}) is False
    recovered, recovery = asyncio.run(
        service._request_with_latest_customer_message_for_lock_recovery(request)
    )

    assert recovered.user_text == request.user_text
    assert recovery["history_refresh_attempted"] is False
    assert recovery["history_refresh_status"] == "skipped_choice_action"
    assert recovery["message_selection"] == "original_request"


def test_runtime_v7_manychat_loader_includes_automated_default_messages():
    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "messages": [
                    {
                        "type": "msgin",
                        "timestamp": 1780000001,
                        "message_id": "user_1",
                        "model": {"messages": [{"type": "text", "content": {"text": "Vios 2020 po"}}]},
                    },
                    {
                        "type": "msgout_default",
                        "timestamp": 1780000000,
                        "message_id": "auto_1",
                        "model": {
                            "messages": [
                                {
                                    "type": "text",
                                    "content": {"text": "Welcome po! Ano pong car model or tire size nila?"},
                                }
                            ]
                        },
                    },
                ]
            }

    calls = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        return FakeResponse()

    result = load_manychat_messages_fast(
        user_id="u1",
        limit=20,
        timeout_s=3,
        transport_get=fake_get,
    )

    assert result["status"] == "success"
    assert [row["message_id"] for row in result["data"]] == ["auto_1", "user_1"]
    automation = result["data"][0]
    assert automation["role"] == "assistant"
    assert automation["type"] == "msgout_default"
    assert automation["sender"] == "ManyChat automation"
    assert automation["is_automated"] is True
    assert automation["message_kind"] == "manychat_automation"
    assert "hide_automation" not in calls[0]["kwargs"]["params"]


def test_manychat_automation_history_is_visible_in_model_context():
    hydration = build_conversation_hydration_result(
        loaded_channel_history=[
            {
                "type": "msgout_default",
                "content": "Welcome po! Ano pong car model or tire size nila?",
                "message_id": "auto_1",
                "datetime": "2026-06-04 09:00:00",
            },
            {
                "role": "user",
                "content": "Vios 2020 po",
                "message_id": "user_1",
                "datetime": "2026-06-04 09:01:00",
            },
        ],
        current_user_text="Vios 2020 po",
        refresh_attempted=True,
        loader_status="success",
    )

    assert hydration.messages[0]["role"] == "assistant"
    assert hydration.messages[0]["is_automated"] is True
    assert hydration.messages[0]["sender"] == "ManyChat automation"
    evidence = build_conversation_evidence_context(hydration.messages)
    assert evidence["recent_turns"][0]["message_kind"] == "manychat_automation"

    context = build_runtime_v7_context(
        current_user_message="Vios 2020 po",
        recent_turns=evidence["recent_turns"],
    )

    assert "- assistant (ManyChat automation): Welcome po!" in context


def test_runtime_v7_manychat_loader_pages_until_text_messages():
    class FakeResponse:
        status_code = 200
        text = ""

        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    responses = [
        FakeResponse(
            {
                "limiter": 123,
                "messages": [
                    {
                        "type": "user_cuf_set",
                        "timestamp": 1780000002,
                        "message_id": "cf_1",
                        "model": {"name": "field"},
                    }
                ],
            }
        ),
        FakeResponse(
            {
                "limiter": None,
                "messages": [
                    {
                        "type": "msgin",
                        "timestamp": 1780000001,
                        "message_id": "user_1",
                        "model": {"messages": [{"type": "text", "content": {"text": "hm po"}}]},
                    }
                ],
            }
        ),
    ]
    calls = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        return responses.pop(0)

    result = load_manychat_messages_fast(
        user_id="u1",
        limit=2,
        timeout_s=5,
        max_pages=3,
        transport_get=fake_get,
    )

    assert result["status"] == "success"
    assert result["page_count"] == 2
    assert result["data"][0]["message_id"] == "user_1"
    assert calls[1]["kwargs"]["params"]["limiter"] == 123


def test_runtime_v7_manychat_loader_failure_is_best_effort_error_envelope():
    class HtmlResponse:
        status_code = 200
        text = "<!doctype html><html></html>"

        def json(self):
            raise ValueError("not json")

    result = load_manychat_messages_fast(
        user_id="u1",
        timeout_s=1,
        transport_get=lambda *args, **kwargs: HtmlResponse(),
    )

    assert result["status"] == "error"
    assert result["data"] == []
    assert "HTML" in result["message"]


def test_v7_legacy_idempotency_requires_external_identity_basis():
    assert _chat_v7_has_external_idempotency_basis(ChatV7RequestPayload(user_id="u1", user_text="hi")) is False
    assert _chat_v7_has_external_idempotency_basis(
        ChatV7RequestPayload(user_id="u1", user_text="hi", message_id="manychat_msg_1")
    ) is True
    assert _chat_v7_has_external_idempotency_basis(
        ChatV7RequestPayload(user_id="u1", user_text="hi", channel_event_id="manychat_event_1")
    ) is True


def test_fulfillment_alias_resolver_maps_courier_shipping_to_delivery_context():
    resolved = resolve_fulfillment_alias("Shipping po gaya ng J&T or LBC if mag avail ako")
    candidates = fulfillment_alias_candidates("Shipping po gaya ng J&T or LBC if mag avail ako")

    assert resolved["service_type"] == "delivery"
    assert candidates[0]["key"] == "service_type"
    assert candidates[0]["value"] == "delivery"
    assert candidates[0]["origin"] == "fulfillment_alias_resolver"


def test_fulfillment_alias_resolver_does_not_treat_ui_delivery_state_as_fulfillment():
    assert (
        resolve_fulfillment_alias(
            "I selected Apollo from the delivered product choices."
        )
        is None
    )
    assert (
        resolve_fulfillment_alias(
            "Can these tires be delivered to San Pedro?"
        )["service_type"]
        == "delivery"
    )


def test_state_context_does_not_infer_delivery_alias_without_model():
    state = build_commercial_state_context(
        current_user_message="Nagshiship po kayo via lbc?",
        model_extraction_policy="never",
    )
    signals = {signal["key"]: signal for signal in state["background_signals"]}

    assert "service_type" not in signals
    assert state["background_signal_extraction"]["raw_message_extraction"] == "disabled"


def test_state_context_normalizes_terrain_type_signal():
    state = build_commercial_state_context(
        current_user_message="205/75R16 RT or 215/70R16 RT",
        external_evidence_candidates=[
            {
                "key": "terrain_types",
                "value": "RT",
                "source": "latest_user_message",
                "confidence": "high",
                "status_hint": "product_pattern_constraint",
            }
        ],
        model_extraction_policy="never",
    )
    signals = {signal["key"]: signal for signal in state["background_signals"]}

    assert signals["terrain_types"]["value"] == "RUGGED_TERRAIN"
    assert signals["terrain_types"]["ask_timing"] == "now_for_product_search"


def test_selected_product_context_counts_as_brand_support_for_lead_tags():
    lead = {
        "lead_stage": "incomplete",
        "moderate_intent": False,
        "present": {"tire_size": "235/45R19", "location": "Zamboanga City"},
        "missing": ["tire_brand"],
        "support_count": 1,
    }
    selected = {"product_summary": {"brand": "ARIVO", "sku_model": "ARIVO 235/45/R19 ULTRA ARZ5 95W"}}

    updated = _lead_qualification_with_selected_product(lead, selected_product_context=selected)

    assert updated["present"]["tire_brand"] == "ARIVO"
    assert updated["lead_stage"] == "complete"
    assert updated["moderate_intent"] is True
    assert updated["missing"] == []


def test_session_lock_blocks_overlapping_owner_until_release():
    gateway = SessionsGateway(
        config=SessionsGatewayConfig(
            project_id="test",
            users_collection="users",
            sessions_subcollection="sessions",
            storage_kind="memory",
        ),
        store=MemorySessionStore(),
    )
    loaded = gateway.load(user_id="user_1", channel_user_id="user_1")

    ok1, _ = gateway.acquire_lock(
        user_id="user_1",
        session_id=loaded.session_doc.session_id,
        owner="req_1",
        ttl_seconds=60,
    )
    ok2, _ = gateway.acquire_lock(
        user_id="user_1",
        session_id=loaded.session_doc.session_id,
        owner="req_2",
        ttl_seconds=60,
    )
    gateway.release_lock(user_id="user_1", session_id=loaded.session_doc.session_id, owner="req_1")
    ok3, _ = gateway.acquire_lock(
        user_id="user_1",
        session_id=loaded.session_doc.session_id,
        owner="req_2",
        ttl_seconds=60,
    )

    assert ok1 is True
    assert ok2 is False
    assert ok3 is True


def test_api_runtime_refreshes_session_after_first_poll_lock_acquisition(
    monkeypatch,
):
    """A fast follow-up must not validate against the pre-lock snapshot."""

    class CommitBetweenLoadAndLockGateway(SessionsGateway):
        def __init__(self):
            super().__init__(
                config=SessionsGatewayConfig(
                    project_id="test",
                    users_collection="users",
                    sessions_subcollection="sessions",
                    storage_kind="memory",
                ),
                store=MemorySessionStore(),
            )
            self.load_count = 0
            self.reload_count = 0
            self.injected_prior_commit = False

        def load(self, **kwargs):
            self.load_count += 1
            return super().load(**kwargs)

        def reload_session(self, **kwargs):
            self.reload_count += 1
            return super().reload_session(**kwargs)

        def acquire_lock(self, **kwargs):
            if not self.injected_prior_commit:
                data = self._store.load_session(
                    kwargs["user_id"],
                    kwargs["session_id"],
                )
                data["strategy_state"] = {
                    "runtime_v7": {
                        "turn_count": 7,
                        "choice_presentation_history": [
                            {
                                "presentation_ref": "pres_slots_latest",
                                "choice_type": "schedule_selection",
                                "choices": [{"choice_ref": "d2t2"}],
                                "delivery_status": "success",
                            }
                        ],
                    }
                }
                data["revision"] = int(data.get("revision") or 0) + 1
                self._store.save_session(
                    kwargs["user_id"],
                    kwargs["session_id"],
                    data,
                )
                self.injected_prior_commit = True
            return super().acquire_lock(**kwargs)

    gateway = CommitBetweenLoadAndLockGateway()
    captured = {}

    class FakeHarness:
        def __init__(self, session_id):
            self.session_id = session_id
            self.product_inclusions_sent = False
            self.service_policy_note_ids_sent = []

        def run_turn(self, user_text, **_kwargs):
            return {
                "turn_id": "turn_after_refresh",
                "user_message": user_text,
                "runtime_final_response": "Current state loaded.",
                "tool_results": [],
                "llm_calls": [],
                "response_guard_events": [],
                "tagging": {},
            }

    def fake_hydrate(_harness, state):
        captured["state"] = state

    def fake_render(turn, **_kwargs):
        text = str(turn.get("runtime_final_response") or "")
        return RuntimeV7ChannelRender(
            response={"bubble1": text},
            content_messages=[{"type": "text", "text": text}],
            text=text,
        )

    monkeypatch.setattr("runtime_v7.api_runtime._hydrate_harness", fake_hydrate)
    monkeypatch.setattr("runtime_v7.api_runtime.render_turn_for_channel", fake_render)
    monkeypatch.setattr(
        "runtime_v7.api_runtime._export_harness_state",
        lambda harness: {
            "version": 1,
            "session_id": harness.session_id,
            "turn_count": 8,
            "conversation_history": [],
            "product_inclusions_sent": False,
        },
    )
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        harness_factory=lambda session_id, profile_fields, trace_id: FakeHarness(
            session_id
        ),
        delivery_mode="return_only",
        fetch_manychat_messages=False,
    )

    result = asyncio.run(
        service.handle(
            RuntimeV7APIRequest(
                user_id="user_fast_click",
                channel_user_id="user_fast_click",
                channel="manychat",
                user_text="next choice",
                message_id="msg_fast_click",
                delivery_mode="return_only",
            ),
            request_id="req_fast_click",
        )
    )

    assert gateway.load_count == 1
    assert gateway.reload_count == 1
    assert captured["state"]["turn_count"] == 7
    assert captured["state"]["choice_presentation_history"][0][
        "presentation_ref"
    ] == "pres_slots_latest"
    assert result.state_saved is True


def test_api_runtime_session_busy_is_non_success_and_persists_trace(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_SESSION_LOCK_WAIT_S", "0")
    monkeypatch.setenv("RUNTIME_V7_SESSION_LOCK_RECOVERY_ENABLED", "0")
    gateway = SessionsGateway(
        config=SessionsGatewayConfig(
            project_id="test",
            users_collection="users",
            sessions_subcollection="sessions",
            storage_kind="memory",
        ),
        store=MemorySessionStore(),
    )
    loaded = gateway.load(user_id="user_1", channel_user_id="user_1")
    ok, _ = gateway.acquire_lock(
        user_id="user_1",
        session_id=loaded.session_doc.session_id,
        owner="req_existing",
        ttl_seconds=60,
    )
    assert ok is True

    class FakeAnalytics:
        def __init__(self):
            self.rows = []
            self.request_state_logs = []
            self.request_attempt_logs = []
            self.turn_trace_logs = []
            self.turn_fact_logs = []
            self.normalized_dispatches = 0

        def enqueue_debug_log(self, row):
            self.rows.append(dict(row))

        def enqueue_request_state_log(self, row):
            self.request_state_logs.append(dict(row))

        def enqueue_request_attempt_log(self, row):
            self.request_attempt_logs.append(dict(row))

        def enqueue_turn_trace_log(self, row):
            self.turn_trace_logs.append(dict(row))

        def enqueue_turn_fact_log(self, row):
            self.turn_fact_logs.append(dict(row))

        def flush_normalized_async(self):
            self.normalized_dispatches += 1

    analytics = FakeAnalytics()
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        analytics_gateway=analytics,
        delivery_mode="return_only",
        fetch_manychat_messages=False,
    )
    result = __import__("asyncio").run(
        service.handle(
            RuntimeV7APIRequest(user_id="user_1", channel="manychat", user_text="hi hm 175 65 14"),
            request_id="req_busy",
        )
    )
    payload = result.to_payload(include_debug=True)

    assert payload["status"] == "session_busy_retry_later"
    assert payload["delivery_result"]["reason"] == "session_lock_busy"
    assert payload["response"] == {}
    assert payload["state_saved"] is False
    assert analytics.rows
    assert analytics.rows[0]["request_id"] == "req_busy"
    assert analytics.rows[0]["debug_payload"]["delivery_result"]["reason"] == "session_lock_busy"
    assert analytics.request_state_logs[0]["runtime_version"] == "v7"
    assert analytics.request_state_logs[0]["status"] == "session_busy_retry_later"
    assert analytics.request_attempt_logs[0]["retryable"] is True
    assert analytics.turn_trace_logs[0]["orchestration_mode"] == "single_orchestrator"
    assert analytics.turn_fact_logs[0]["llm_calls"] == 0
    assert analytics.normalized_dispatches == 1


def test_api_runtime_recovers_busy_lock_with_latest_customer_message(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_SESSION_LOCK_WAIT_S", "0")
    monkeypatch.setenv("RUNTIME_V7_SESSION_LOCK_RECOVERY_ENABLED", "1")
    monkeypatch.setenv("RUNTIME_V7_SESSION_LOCK_RECOVERY_WAIT_S", "0.4")
    monkeypatch.setenv("RUNTIME_V7_SESSION_LOCK_POLL_S", "0.05")
    gateway = SessionsGateway(
        config=SessionsGatewayConfig(
            project_id="test",
            users_collection="users",
            sessions_subcollection="sessions",
            storage_kind="memory",
        ),
        store=MemorySessionStore(),
    )
    loaded = gateway.load(user_id="user_recover", channel_user_id="user_recover")
    ok, _ = gateway.acquire_lock(
        user_id="user_recover",
        session_id=loaded.session_doc.session_id,
        owner="req_existing",
        ttl_seconds=60,
    )
    assert ok is True

    captured = {}

    class FakeHarness:
        def __init__(self, session_id):
            self.session_id = session_id
            self.product_inclusions_sent = False

        def run_turn(self, user_text, **kwargs):
            captured["user_text"] = user_text
            captured["conversation_history"] = kwargs.get("conversation_history") or []
            return {
                "turn_id": "turn_recovered",
                "user_message": user_text,
                "runtime_final_response": f"Replying to {user_text}",
                "tool_results": [],
                "llm_calls": [],
                "response_guard_events": [],
                "tagging": {},
            }

    def fake_render(turn, **_kwargs):
        text = str(turn.get("runtime_final_response") or "")
        return RuntimeV7ChannelRender(
            response={"bubble1": text},
            content_messages=[{"type": "text", "text": text}],
            text=text,
        )

    history_loader_calls = []

    def fake_history_loader(_request):
        history_loader_calls.append(str(_request.message_id or ""))
        messages = [
            {
                "role": "user",
                "content": "hm 175 65 14",
                "message_id": "msg_old",
                "datetime": "2026-06-05 10:00:00",
            },
            {
                "role": "user",
                "content": "mode of payment po?",
                "message_id": "msg_mid",
                "datetime": "2026-06-05 10:00:04",
            },
        ]
        if len(history_loader_calls) > 1:
            messages.append(
                {
                    "role": "user",
                    "content": "gcash pwede?",
                    "message_id": "msg_latest",
                    "datetime": "2026-06-05 10:00:08",
                }
            )
        return {
            "status": "success",
            "data": messages,
        }

    monkeypatch.setattr("runtime_v7.api_runtime.render_turn_for_channel", fake_render)
    monkeypatch.setattr(
        "runtime_v7.api_runtime._export_harness_state",
        lambda harness: {
            "version": 1,
            "session_id": harness.session_id,
            "turn_count": 1,
            "conversation_history": [],
            "product_inclusions_sent": False,
        },
    )
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        harness_factory=lambda session_id, profile_fields, trace_id: FakeHarness(session_id),
        conversation_history_loader=fake_history_loader,
        delivery_mode="return_only",
        fetch_manychat_messages=False,
    )

    async def run_recovery():
        task = asyncio.create_task(
            service.handle(
                RuntimeV7APIRequest(
                    user_id="user_recover",
                    channel_user_id="user_recover",
                    channel="manychat",
                    user_text="hm 175 65 14",
                    message_id="msg_old",
                    delivery_mode="return_only",
                ),
                request_id="req_recover",
            )
        )
        await asyncio.sleep(0.08)
        gateway.release_lock(
            user_id="user_recover",
            session_id=loaded.session_doc.session_id,
            owner="req_existing",
        )
        return await task

    result = asyncio.run(run_recovery())

    assert result.status == "success"
    assert result.message_id == "msg_latest"
    assert result.idempotency_key == "msg_latest"
    assert captured["user_text"] == "gcash pwede?"
    assert result.response["bubble1"] == "Replying to gcash pwede?"
    inbound_event = result.turn_record["inbound_event"]
    assert inbound_event["normalized_payload"]["user_text"] == "gcash pwede?"
    assert inbound_event["normalized_payload"]["message_id"] == "msg_latest"
    recovery = inbound_event["flow_context"]["session_lock_recovery"]
    assert recovery["status"] == "lock_acquired"
    assert recovery["message_selection"] == "latest_user_message"
    assert recovery["selected_message_id"] == "msg_mid"
    assert recovery["post_lock_message_selection"] == "latest_user_message"
    assert recovery["post_lock_selected_message_id"] == "msg_latest"


def test_api_result_debug_tool_calls_preserve_raw_and_model_visible_statuses():
    result = RuntimeV7APIResult(
        response={},
        content_messages=[],
        images=[],
        payment={},
        delivery_result={"status": "skipped"},
        tagging_result={},
        turn_record={
            "turn_id": "turn_1",
            "runtime_phase_timings_ms": {
                "session_load": 12.3456,
                "handler_total": 456.7894,
                "invalid": "secret",
            },
            "tool_results": [
                {
                    "name": "build_order_summary",
                    "latency_ms": 4321,
                    "full_result": {"status": "incomplete", "missing_fields": ["Payment method"]},
                    "result": {"status": "error", "message": "legacy compact label"},
                }
            ],
        },
        session_id="sess_1",
        trace_id="trace_1",
        request_id="req_1",
        message_id="msg_1",
        idempotency_key="msg_1",
        state_saved=True,
    )

    call = result.to_payload(include_debug=True)["debug"]["tool_calls"][0]

    assert call["status"] == "incomplete"
    assert call["raw_status"] == "incomplete"
    assert call["model_visible_status"] == "error"
    assert call["latency_ms"] == 4321
    assert result.to_payload(include_debug=True)["debug"][
        "runtime_phase_timings_ms"
    ] == {
        "session_load": 12.346,
        "handler_total": 456.789,
    }


def test_turn_trace_includes_supplemental_model_and_tool_latency_telemetry():
    inbound = build_inbound_event(
        request_id="req-telemetry",
        trace_id="trace-telemetry",
        runtime_version="v7",
        user_id="user-telemetry",
        channel_user_id="user-telemetry",
        channel="manychat",
        message_id="msg-telemetry",
        idempotency_key="msg-telemetry",
    )
    turn = {
        "turn_id": "turn-telemetry",
        "background_signal_extraction": {
            "status": "ok",
            "model_used": True,
            "model": "signal-model",
            "model_latency_ms": 123,
            "model_attempts": 1,
            "model_metered_attempts": 1,
            "model_usage": {
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "total_tokens": 30,
            },
        },
        "llm_calls": [],
        "supplemental_llm_calls": [
            {
                "component": "background_signal_extraction",
                "round": "background_signal_extraction",
                "finish_reason": "ok",
                "latency_ms": 123,
                "provider_call_count": 1,
                "usage_summary": {
                    "prompt_tokens": 20,
                    "completion_tokens": 10,
                    "total_tokens": 30,
                },
            }
        ],
        "tool_results": [
            {
                "name": "find_installation_slots",
                "latency_ms": 4567,
                "args": {"location": "Makati"},
                "full_result": {"status": "ok"},
            }
        ],
    }

    trace = build_turn_trace(
        inbound_event=inbound,
        turn_record=turn,
        delivery_result={"status": "skipped"},
        tagging_result={},
        state_saved=True,
    )

    state_span = next(
        span
        for span in trace["component_spans"]
        if span["component_type"] == "state_extraction"
    )
    tool_span = next(
        span
        for span in trace["component_spans"]
        if span["component_type"] == "tool_call"
    )
    assert state_span["latency_ms"] == 123
    assert state_span["usage"]["total_tokens"] == 30
    assert state_span["model"] == "signal-model"
    assert state_span["metered_provider_call_count"] == 1
    assert not any(
        span.get("component_type") == "model_call"
        and span.get("component_name") == "background_signal_extraction"
        for span in trace["component_spans"]
    )
    assert tool_span["latency_ms"] == 4567


def test_production_harness_uses_signal_driven_domain_projection(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_PROMO_CATALOG_ENABLED", "0")
    monkeypatch.setenv("RUNTIME_V7_BRAND_KNOWLEDGE_ENABLED", "0")

    harness = build_runtime_v7_harness(
        "session-domain-projection",
        {},
        "trace-domain-projection",
        user_id="test-domain-projection",
    )

    assert tuple(harness.default_domains) == ()


def test_normalized_logs_include_supplemental_model_components():
    class CapturingAnalytics:
        def __init__(self):
            self.request_states = []
            self.request_attempts = []
            self.turn_traces = []
            self.turn_facts = []
            self.llm_spans = []

        def enqueue_request_state_log(self, row):
            self.request_states.append(dict(row))

        def enqueue_request_attempt_log(self, row):
            self.request_attempts.append(dict(row))

        def enqueue_turn_trace_log(self, row):
            self.turn_traces.append(dict(row))

        def enqueue_turn_fact_log(self, row):
            self.turn_facts.append(dict(row))

        def enqueue_llm_span_log(self, row):
            self.llm_spans.append(dict(row))

        def flush_normalized_async(self):
            return None

    analytics = CapturingAnalytics()
    usage = {
        "llm_call_count": 2,
        "prompt_tokens": 120,
        "completion_tokens": 30,
        "total_tokens": 150,
        "latency_ms": 30,
    }
    turn = {
        "turn_id": "turn-normalized-telemetry",
        "runtime_final_response": "Okay po.",
        "llm_usage_summary": usage,
        "llm_calls": [
            {
                "round": 1,
                "model": "main-model",
                "latency_ms": 20,
                "usage_summary": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
            }
        ],
        "supplemental_llm_calls": [
            {
                "component": "active_working_memory",
                "round": "active_working_memory",
                "model": "memory-model",
                "latency_ms": 10,
                "usage_summary": {
                    "prompt_tokens": 20,
                    "completion_tokens": 10,
                    "total_tokens": 30,
                },
                "supplemental_usage_record": True,
            }
        ],
        "tool_results": [],
    }
    request = RuntimeV7APIRequest(
        user_id="user-normalized-telemetry",
        channel="manychat",
        user_text="test",
        message_id="msg-normalized-telemetry",
    )

    _emit_normalized_turn_logs(
        analytics,
        request=request,
        turn=turn,
        rendered=RuntimeV7ChannelRender(
            response={"bubble1": "Okay po."}, content_messages=[]
        ),
        turn_trace={"status": "completed", "component_spans": []},
        delivery_result={"status": "skipped", "reason": "return_only"},
        tagging_result={},
        session_id="session-normalized-telemetry",
        request_id="req-normalized-telemetry",
        trace_id="trace-normalized-telemetry",
        user_id=request.user_id,
    )

    assert analytics.turn_facts[0]["llm_calls"] == 2
    assert analytics.turn_facts[0]["tokens_total"] == 150
    assert [row["component"] for row in analytics.llm_spans] == [
        "main_tool_loop",
        "active_working_memory",
    ]


def test_api_result_debug_exposes_safe_payment_lookup_scope():
    result = RuntimeV7APIResult(
        response={},
        content_messages=[],
        images=[],
        payment={},
        delivery_result={"status": "skipped"},
        tagging_result={},
        turn_record={
            "turn_id": "turn_payment",
            "tool_results": [
                {
                    "round": 2,
                    "tool_call_id": "call_payment_executed",
                    "name": "answer_order_faq",
                    "args": {
                        "requested_payment_method": "Example Finance",
                        "requested_product_brand": "EXAMPLE",
                        "question": "private free-form customer wording",
                    },
                    "model_args": {
                        "requested_payment_method": "Example Finance",
                        "requested_product_brand": "EXAMPLE",
                        "question": "private pre-hydration wording",
                    },
                    "full_result": {
                        "status": "ok",
                        "source": "checkout_metadata",
                        "evidence_ref": "faq:order:payment",
                        "faq_id": "order_how_do_i_pay",
                        "payment_policy": {
                            "requested_payment_method": "Example Finance",
                            "requested_payment_status": "unsupported",
                            "requested_product_brand": "EXAMPLE",
                        },
                    },
                    "result": {"status": "ok"},
                }
            ],
            "tool_dedupe_events": [
                {
                    "round": 2,
                    "type": "duplicate_tool_call_reused",
                    "name": "answer_order_faq",
                    "tool_call_id": "call_payment_duplicate",
                    "first_round": 2,
                    "first_tool_call_id": "call_payment_executed",
                    "cache_match_type": "exact",
                    "cache_key": "must-not-be-exposed",
                    "args": {
                        "requested_payment_method": "Example Finance",
                        "question": "private reused wording",
                    },
                }
            ],
        },
        session_id="sess_payment",
        trace_id="trace_payment",
        request_id="req_payment",
        message_id="msg_payment",
        idempotency_key="msg_payment",
        state_saved=True,
        turn_trace={
            "component_spans": [
                {
                    "component_type": "model_call",
                    "round": 2,
                    "tool_calls": [
                        {
                            "id": "call_payment_executed",
                            "name": "answer_order_faq",
                            "args": {
                                "requested_payment_method": "Example Finance",
                                "question": "private trace wording",
                            },
                        }
                    ],
                }
            ]
        },
    )

    call = result.to_payload(include_debug=True)["debug"]["tool_calls"][0]

    assert call["payment_scope"] == {
        "requested_method": "Example Finance",
        "requested_status": "unsupported",
        "brand": "EXAMPLE",
        "brand_eligibility": None,
        "payment_option": None,
    }
    assert call["args"] == {
        "requested_payment_method": "Example Finance",
        "requested_product_brand": "EXAMPLE",
    }
    assert call["round"] == 2
    assert call["tool_call_id"] == "call_payment_executed"
    assert call["model_args"] == {
        "requested_payment_method": "Example Finance",
        "requested_product_brand": "EXAMPLE",
    }
    assert call["authority"] == {
        "source": "checkout_metadata",
        "evidence_ref": "faq:order:payment",
        "faq_id": "order_how_do_i_pay",
    }
    dedupe = result.to_payload(include_debug=True)["debug"]["tool_dedupe_events"][0]
    assert dedupe == {
        "round": 2,
        "type": "duplicate_tool_call_reused",
        "name": "answer_order_faq",
        "tool_call_id": "call_payment_duplicate",
        "first_round": 2,
        "first_tool_call_id": "call_payment_executed",
        "cache_match_type": "exact",
        "args": {"requested_payment_method": "Example Finance"},
    }
    trace_call = result.to_payload(include_debug=True)["debug"]["turn_trace"][
        "component_spans"
    ][0]["tool_calls"][0]
    assert trace_call == {
        "id": "call_payment_executed",
        "name": "answer_order_faq",
        "args": {"requested_payment_method": "Example Finance"},
    }


def test_product_observation_persistence_keeps_latest_three_refs() -> None:
    store = ProductToolHarness().store
    for index in range(5):
        store.save_search_result(
            {
                "observation_ref": f"obs_{index}",
                "presentation_ref": f"pres_{index}",
                "product_cards": [{"card_ref": f"card_{index}"}],
            }
        )

    payload = _export_product_store(store)

    assert [item["observation_ref"] for item in payload["observations"]] == ["obs_2", "obs_3", "obs_4"]
    assert payload["presentation_index"] == {
        "pres_2": "obs_2",
        "pres_3": "obs_3",
        "pres_4": "obs_4",
    }
    assert payload["latest_ref"] == "obs_4"


def test_api_runtime_freshness_check_keeps_delivery_for_newer_user_message(monkeypatch):
    service = RuntimeV7APIService(sessions_gateway=object(), delivery_mode="send_content")
    request = RuntimeV7APIRequest(
        user_id="user_1",
        channel="manychat",
        user_text="hi hm 175 65 14",
        request_time="2026-06-02 17:23:13",
    )
    hydration = build_conversation_hydration_result(
        current_user_text="hi hm 175 65 14",
        current_message_datetime="2026-06-02 17:23:13",
    )

    def fake_loader(_request):
        return {
            "status": "success",
            "data": [
                {
                    "role": "user",
                    "content": "Yo",
                    "message_id": "mc_2",
                    "datetime": "2026-06-02 17:23:28",
                }
            ],
        }

    monkeypatch.setattr("runtime_v7.api_runtime._load_manychat_messages_for_freshness", fake_loader)

    result = __import__("asyncio").run(
        service._freshness_check_before_delivery(
            request,
            hydration=hydration,
            delivery_mode="send_content",
        )
    )

    assert result["status"] == "fresh_with_newer_user_message"
    assert result["reason"] == "newer_user_message_seen_delivery_not_suppressed"


def test_api_runtime_freshness_check_marks_newer_human_agent_message_stale(monkeypatch):
    service = RuntimeV7APIService(sessions_gateway=object(), delivery_mode="send_content")
    request = RuntimeV7APIRequest(
        user_id="user_1",
        channel="manychat",
        user_text="hi hm 175 65 14",
        request_time="2026-06-02 17:23:13",
    )
    hydration = build_conversation_hydration_result(
        current_user_text="hi hm 175 65 14",
        current_message_datetime="2026-06-02 17:23:13",
    )

    def fake_loader(_request):
        return {
            "status": "success",
            "data": [
                {
                    "role": "human_agent",
                    "content": "Ako na po sasagot.",
                    "message_id": "mc_agent_2",
                    "datetime": "2026-06-02 17:23:28",
                }
            ],
        }

    monkeypatch.setattr("runtime_v7.api_runtime._load_manychat_messages_for_freshness", fake_loader)

    result = __import__("asyncio").run(
        service._freshness_check_before_delivery(
            request,
            hydration=hydration,
            delivery_mode="send_content",
        )
    )

    assert result["status"] == "stale"
    assert result["reason"] == "newer_human_agent_message_seen"


def test_tracked_interaction_settle_checks_newer_click_in_return_only(
    monkeypatch,
):
    monkeypatch.setenv("RUNTIME_V7_INTERACTION_BATCHING_ENABLED", "1")
    monkeypatch.setenv("RUNTIME_V7_INTERACTION_SETTLE_MS", "1")
    monkeypatch.setenv("RUNTIME_V7_INTERACTION_MAX_WAIT_MS", "600")
    monkeypatch.setenv("RUNTIME_V7_DELIVERY_FRESHNESS_ENABLED", "0")
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        delivery_mode="return_only",
    )
    request = RuntimeV7APIRequest(
        user_id="user_1",
        channel="manychat",
        user_text="Premium",
        message_id="mc_click_1",
        request_time="2026-07-28 10:00:00",
        delivery_mode="return_only",
        flow_context={
            "choice_action_context": {
                "choice_type": "price_category",
                "presentation_ref": "pres-price",
            }
        },
    )
    hydration = build_conversation_hydration_result(
        current_message_id="mc_click_1",
        current_user_text="Premium",
        current_message_datetime="2026-07-28 10:00:00",
    )
    calls = []

    def fake_loader(_request):
        calls.append("load")
        return {
            "status": "success",
            "data": [
                {
                    "role": "user",
                    "content": "Budget",
                    "message_id": "mc_click_2",
                    "datetime": "2026-07-28 10:00:00.300",
                }
            ],
        }

    monkeypatch.setattr(
        "runtime_v7.api_runtime._load_manychat_messages_for_freshness",
        fake_loader,
    )

    result = asyncio.run(
        service._settle_tracked_interaction(
            request,
            hydration=hydration,
        )
    )

    assert calls == ["load"]
    assert result["intentional_wait_ms"] == 1
    assert result["status"] == "fresh_with_newer_user_message"


def test_tracked_interaction_freshness_uses_prelock_inbox_when_manychat_lags(
    monkeypatch,
):
    monkeypatch.setenv("RUNTIME_V7_INTERACTION_BATCHING_ENABLED", "1")
    store = MemorySessionStore()
    gateway = SessionsGateway(
        config=SessionsGatewayConfig(
            project_id="test",
            users_collection="users",
            sessions_subcollection="sessions",
            storage_kind="memory",
        ),
        store=store,
    )
    loaded = gateway.load(
        user_id="user_prelock",
        channel_user_id="user_prelock",
    )
    session_id = loaded.session_doc.session_id
    current = {
        "event_id": "evt-premium",
        "idempotency_key": "evt-premium",
        "source": "choice_action",
        "presentation_ref": "pres-price",
        "choice_type": "price_category",
        "label": "Premium",
        "occurred_at": "2026-07-28T10:00:00+08:00",
        "received_at": "2026-07-28 10:00:00",
    }
    newer = {
        "event_id": "evt-budget",
        "idempotency_key": "evt-budget",
        "source": "choice_action",
        "presentation_ref": "pres-price",
        "choice_type": "price_category",
        "label": "Budget",
        "occurred_at": "2026-07-28T10:00:10+08:00",
        "received_at": "2026-07-28 10:00:10",
    }
    gateway.record_interaction_event(
        user_id="user_prelock",
        session_id=session_id,
        event=current,
    )
    gateway.record_interaction_event(
        user_id="user_prelock",
        session_id=session_id,
        event=newer,
    )
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        delivery_mode="send_content",
    )
    request = RuntimeV7APIRequest(
        user_id="user_prelock",
        channel="manychat",
        user_text="Premium",
        message_id="evt-premium",
        channel_event_id="evt-premium",
        channel_event_ts="2026-07-28T10:00:00+08:00",
        idempotency_key="evt-premium",
        request_time="2026-07-28 10:00:00",
        delivery_mode="send_content",
        flow_context={
            "choice_action_context": {
                "choice_type": "price_category",
                "presentation_ref": "pres-price",
                "label": "Premium",
            }
        },
    )
    hydration = build_conversation_hydration_result(
        current_message_id="evt-premium",
        current_user_text="Premium",
        current_message_datetime="2026-07-28 10:00:00",
    )
    loader_calls = []
    monkeypatch.setattr(
        "runtime_v7.api_runtime._load_manychat_messages_for_freshness",
        lambda _request: loader_calls.append("load") or {
            "status": "success",
            "data": [
                {
                    "role": "assistant",
                    "content": "Choose a category.",
                    "message_id": "assistant-surface",
                    "datetime": "2026-07-28 09:59:59",
                }
            ],
        },
    )

    result = asyncio.run(
        service._freshness_check_before_delivery(
            request,
            hydration=hydration,
            delivery_mode="send_content",
            session_id=session_id,
        )
    )

    assert loader_calls == []
    assert result["status"] == "fresh_with_newer_user_message"
    assert result["reason"] == "newer_tracked_interaction_seen"
    assert result["latest_interaction"]["event_id"] == "evt-budget"


def test_button_only_same_layer_choices_accept_latest_for_every_dimension():
    discovery = _apply_button_only_ambiguity_envelope(
        {
            "runtime_relation": "same_layer_distinct",
            "events": [
                {"decision_layer": "price_category"},
                {"decision_layer": "price_category"},
            ],
            "allowed_model_interpretations": [
                "accept_latest",
                "compare",
                "clarify",
            ],
        }
    )
    payment = _apply_button_only_ambiguity_envelope(
        {
            "runtime_relation": "same_layer_distinct",
            "events": [
                {"decision_layer": "payment_option"},
                {"decision_layer": "payment_option"},
            ],
            "allowed_model_interpretations": [
                "accept_latest",
                "clarify",
            ],
        }
    )
    promo_information = _apply_button_only_ambiguity_envelope(
        {
            "runtime_relation": "same_layer_distinct",
            "events": [
                {"decision_layer": "promo_information"},
                {"decision_layer": "promo_information"},
            ],
            "allowed_model_interpretations": [
                "accept_latest",
                "compare",
                "clarify",
            ],
        }
    )

    assert discovery["allowed_model_interpretations"] == ["accept_latest"]
    assert discovery["state_commit_deferred"] is True
    assert payment["allowed_model_interpretations"] == ["accept_latest"]
    assert promo_information["allowed_model_interpretations"] == ["accept_latest"]


def test_api_resolves_rapid_distinct_category_clicks_to_latest_choice(
    monkeypatch,
):
    monkeypatch.setenv("RUNTIME_V7_INTERACTION_BATCHING_ENABLED", "1")
    monkeypatch.setenv("RUNTIME_V7_INTERACTION_SETTLE_MS", "0")
    store = MemorySessionStore()
    gateway = SessionsGateway(
        config=SessionsGatewayConfig(
            project_id="test",
            users_collection="users",
            sessions_subcollection="sessions",
            storage_kind="memory",
        ),
        store=store,
    )
    loaded = gateway.load(
        user_id="user_multi_click",
        channel_user_id="user_multi_click",
    )
    session_data = store.load_session(
        "user_multi_click",
        loaded.session_doc.session_id,
    )
    session_data["strategy_state"] = {
        "runtime_v7": {
            "turn_count": 1,
            "choice_presentation_history": [
                {
                    "presentation_ref": "pres-price",
                    "choice_type": "price_category",
                    "tire_size": "195/60R15",
                    "choices": [
                        {
                            "category": "Premium",
                            "label": "Premium",
                        },
                        {
                            "category": "Budget",
                            "label": "Budget",
                        },
                    ],
                    "delivery_status": "success",
                }
            ],
            "choice_action_history": [
                {
                    "event_id": "evt-premium",
                    "idempotency_key": "idem-premium",
                    "presentation_ref": "pres-price",
                    "choice_ref": "price_category:premium",
                    "choice_type": "price_category",
                    "category": "Premium",
                    "label": "Premium",
                    "validation_status": "valid",
                    "delivery_status": "superseded_before_composition",
                    "click_timestamp": (
                        "2026-07-28T10:00:00+08:00"
                    ),
                }
            ],
            "latest_choice_action": {
                "event_id": "evt-premium",
                "idempotency_key": "idem-premium",
                "presentation_ref": "pres-price",
                "choice_ref": "price_category:premium",
                "choice_type": "price_category",
                "category": "Premium",
                "label": "Premium",
                "validation_status": "valid",
                "delivery_status": "superseded_before_composition",
            },
        }
    }
    session_data["revision"] = int(session_data.get("revision") or 0) + 1
    store.save_session(
        "user_multi_click",
        loaded.session_doc.session_id,
        session_data,
    )

    class InteractionModel:
        def complete(
            self,
            *,
            messages,
            tools,
            tool_choice="auto",
            response_format=None,
            max_tokens=None,
        ):
            del tools, tool_choice, max_tokens
            if response_format is not None:
                payload = json.loads(messages[-1]["content"])
                assert payload["interaction_packet"][
                    "runtime_relation"
                ] == "same_layer_distinct"
                return {
                    "content": json.dumps(
                        {
                            "interaction_decision": {
                                "interpretation": "accept_latest",
                                "effective_event_ids": ["evt-budget"],
                                "reason_code": "latest_validated_choice",
                                "needs_clarification": False,
                            },
                            "response_units": [
                                {
                                    "type": "text",
                                    "content": {
                                        "text": (
                                            "Budget options it is."
                                        )
                                    },
                                }
                            ],
                        }
                    ),
                    "tool_calls": [],
                    "usage": {},
                    "cache_usage": {},
                    "latency_ms": 1,
                    "finish_reason": "stop",
                }
            return {
                "content": "I can help resolve those choices.",
                "tool_calls": [],
                "usage": {},
                "cache_usage": {},
                "latency_ms": 1,
                "finish_reason": "stop",
            }

    monkeypatch.setattr(
        "runtime_v7.api_runtime._load_manychat_messages_for_freshness",
        lambda _request: {
            "status": "success",
            "data": [
                {
                    "role": "user",
                    "content": "Budget",
                    "message_id": "evt-budget",
                    "datetime": "2026-07-28 10:00:00.300",
                }
            ],
        },
    )
    service = RuntimeV7APIService(
        sessions_gateway=gateway,
        harness_factory=lambda session_id, _profile, _trace: RuntimeV7Harness(
            model_client=InteractionModel(),
            tools=ProductToolHarness(),
            session_id=session_id,
        ),
        delivery_mode="return_only",
        fetch_manychat_messages=False,
    )
    result = asyncio.run(
        service.handle(
            RuntimeV7APIRequest(
                user_id="user_multi_click",
                channel_user_id="user_multi_click",
                channel="manychat",
                user_text="Budget",
                message_id="evt-budget",
                channel_event_id="evt-budget",
                channel_event_ts="2026-07-28T10:00:00.300+08:00",
                idempotency_key="idem-budget",
                request_time="2026-07-28 10:00:00.300",
                delivery_mode="return_only",
                flow_context={
                    "trigger": "choice_action",
                    "choice_action_context": {
                        "choice_type": "price_category",
                        "presentation_ref": "pres-price",
                        "category": "Budget",
                        "tire_size": "195/60R15",
                    },
                },
            ),
            request_id="req-multi-click",
        )
    )

    assert result.turn_record["interaction_decision_validation"][
        "interpretation"
    ] == "accept_latest"
    assert "Budget options it is" in result.turn_record[
        "runtime_final_response"
    ]
    assert result.turn_record["interaction_state_commit"]["status"] == (
        "price_category_selection_committed"
    )
    signals = {
        item["key"]: item
        for item in result.turn_record.get("background_signal_ledger_after_turn") or []
    }
    assert signals["tire_category_preference"]["value"] == "Budget"
    saved = store.load_session(
        "user_multi_click",
        loaded.session_doc.session_id,
    )
    history = saved["strategy_state"]["runtime_v7"][
        "choice_action_history"
    ]
    assert len(history) == 2
    assert {item["delivery_status"] for item in history} == {"evaluated"}
    assert gateway.load_interaction_events(
        user_id="user_multi_click",
        session_id=loaded.session_doc.session_id,
    ) == []
