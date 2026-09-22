"""Runtime API routes for the Gulong chatbot service."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from configs.log_utils import get_logger, manila_tz
from runtime.gateways.sessions_gateway import SessionsGateway, SessionsGatewayConfig
from runtime.runtime_app import build_analytics_gateway, build_idempotency_gateway, build_sessions_gateway
from runtime.shared.config_loader import load_session_store_config, resolve_bu_config_path
from runtime.storage.firestore_transport_probe import (
    run_firestore_representation_probe,
    run_firestore_transport_probe,
)
from runtime.storage.session_store import MemorySessionStore
from runtime.utils.time_utils import now_manila_str
from runtime_v7.api_runtime import RuntimeV7APIRequest, RuntimeV7APIService
from runtime_v7.llm_gateway import RuntimeV7ProviderCallLimitExceeded
from runtime_v7.brand_knowledge import (
    BrandKnowledgeRepository,
    BrandKnowledgeService,
    brand_knowledge_enabled,
)
from runtime_v7.promo_catalog import (
    PROMO_SELECTION_ACTIONS,
    PromoCatalogRepository,
    PromoCatalogService,
    parse_promo_click_token,
    promo_catalog_enabled_for_user,
)
from runtime_v7.choice_actions import (
    parse_location_choice_token,
    parse_payment_method_choice_token,
    parse_payment_option_choice_token,
    parse_price_category_token,
    parse_product_choice_token,
    parse_schedule_choice_token,
)

router = APIRouter(prefix="/gulong", tags=["gulong"])
logger = get_logger(__name__, level="INFO")

DEFAULT_TEST_USER_ID = "4843256405786522"
DEFAULT_TEST_CHANNEL_USER_ID = "4843256405786522"
RUNTIME_GENERATION = os.getenv("RUNTIME_GENERATION", "v7")


class ChatRequestPayload(BaseModel):
    """Public chat request accepted by the runtime service."""

    user_id: Optional[str] = None
    channel_user_id: Optional[str] = None
    channel: str = "manychat"
    channel_subtype: Optional[str] = None
    user_text: str
    full_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    assigned_agent: Optional[str] = None
    profile_fields: Dict[str, Any] = Field(default_factory=dict)
    message_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    channel_event_id: Optional[str] = None
    channel_event_ts: Optional[str] = None
    flow_context: Dict[str, Any] = Field(default_factory=dict)
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    user_id_source: Optional[str] = None
    reset: int = 0
    save_analytics: int = 1
    return_logs: int = 0
    delivery_mode: Optional[str] = None

    @field_validator(
        "user_id",
        "channel_user_id",
        "message_id",
        "idempotency_key",
        "channel_event_id",
        "channel_event_ts",
        "user_id_source",
        mode="before",
    )
    @classmethod
    def _coerce_id_to_str(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        return str(value)


class ChatTesterRequestPayload(ChatRequestPayload):
    """Tester request that defaults to return-only delivery."""

    user_id: Optional[str] = DEFAULT_TEST_USER_ID
    channel_user_id: Optional[str] = DEFAULT_TEST_CHANNEL_USER_ID
    return_logs: int = 1
    delivery_mode: Optional[str] = "return_only"


class HydratedChatTesterRequestPayload(ChatTesterRequestPayload):
    """Authenticated synthetic-user probe that verifies ManyChat hydration."""


class FirestoreTransportTesterRequestPayload(BaseModel):
    """Bounded no-model persistence probe accepted only by staging."""

    warmups: int = Field(default=2, ge=0, le=5)
    rounds: int = Field(default=8, ge=2, le=20)
    payload_kib: Literal[40, 140] = 140


class FirestoreRepresentationTesterRequestPayload(BaseModel):
    """Bounded no-model representation probe accepted only by staging."""

    warmups: int = Field(default=2, ge=0, le=5)
    rounds: int = Field(default=8, ge=2, le=20)
    payload_kib: Literal[40, 140] = 40


ChatV7RequestPayload = ChatRequestPayload
ChatV7TesterRequestPayload = ChatTesterRequestPayload


class FollowupV7RequestPayload(BaseModel):
    """Authenticated follow-up trigger request for Runtime V7.

    The profile, transcript, delivery, force, logging, and request-time fields
    are retained only for migration compatibility. Production execution ignores
    them and records which deprecated fields were supplied.
    """

    user_id: Optional[str] = None
    channel_user_id: Optional[str] = None
    channel: str = "manychat"
    channel_subtype: Optional[str] = None
    full_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    assigned_agent: Optional[str] = None
    profile_fields: Dict[str, Any] = Field(default_factory=dict)
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    idempotency_key: Optional[str] = None
    channel_event_id: Optional[str] = None
    channel_event_ts: Optional[str] = None
    cadence: Optional[Literal["first", "second", "nurture", "auto"]] = None
    flow_context: Dict[str, Any] = Field(default_factory=dict)
    user_id_source: Optional[str] = None
    force: int = 0
    save_analytics: int = 1
    return_logs: int = 0
    delivery_mode: Optional[str] = None
    request_time: Optional[str] = None

    @field_validator(
        "user_id",
        "channel_user_id",
        "idempotency_key",
        "channel_event_id",
        "channel_event_ts",
        "user_id_source",
        mode="before",
    )
    @classmethod
    def _coerce_id_to_str(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        return str(value)


class FollowupV7TesterRequestPayload(FollowupV7RequestPayload):
    """Authenticated follow-up tester request that is always return-only."""


class PromoActionV7RequestPayload(BaseModel):
    """Tracked ManyChat interactive click accepted by Runtime V7."""

    user_id: Optional[str] = None
    channel_user_id: Optional[str] = None
    catalog_version_id: str = ""
    promo_id: str
    card_id: str = ""
    action: str = ""
    selected_brand: Optional[str] = None
    click_timestamp: str
    event_id: str
    idempotency_key: str
    channel: str = "manychat"
    channel_subtype: Optional[str] = None
    full_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    assigned_agent: Optional[str] = None
    profile_fields: Dict[str, Any] = Field(default_factory=dict)
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    save_analytics: int = 1
    return_logs: int = 0
    delivery_mode: Optional[str] = None

    @field_validator("user_id", "channel_user_id", mode="before")
    @classmethod
    def _coerce_promo_action_id_to_str(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        return str(value)

    @field_validator(
        "promo_id",
        "click_timestamp",
        "event_id",
        "idempotency_key",
        mode="before",
    )
    @classmethod
    def _require_promo_action_value(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must not be blank")
        return text

    @field_validator("action")
    @classmethod
    def _validate_promo_action(cls, value: str) -> str:
        return str(value or "").strip().lower()


def _resolve_bu() -> str:
    return os.getenv("BU", "gulong")


def _model_dump(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return dict(model.model_dump())
    if hasattr(model, "dict"):
        return dict(model.dict())
    return {}


def _stable_message_id(payload: Dict[str, Any]) -> str:
    stable = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return "msg_" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]


def _user_id(request: ChatRequestPayload) -> Optional[str]:
    return request.user_id or request.channel_user_id


def _normalized_payload(request: ChatRequestPayload, *, user_id: str) -> Dict[str, Any]:
    return {
        "user_id": str(user_id or ""),
        "channel": str(request.channel or ""),
        "channel_subtype": str(request.channel_subtype or ""),
        "user_text": str(request.user_text or ""),
        "channel_event_id": str(request.channel_event_id or ""),
        "channel_event_ts": str(request.channel_event_ts or ""),
    }


def _followup_normalized_payload(request: FollowupV7RequestPayload, *, user_id: str) -> Dict[str, Any]:
    return {
        "user_id": str(user_id or ""),
        "channel": str(request.channel or ""),
        "channel_subtype": str(request.channel_subtype or ""),
        "trigger": "followup_endpoint",
        "channel_event_id": str(request.channel_event_id or ""),
        "channel_event_ts": str(request.channel_event_ts or ""),
        "cadence": str(request.cadence or "first"),
    }


def _resolve_followup_cadence(
    cadence: Any,
    channel_event_ts: Any,
    *,
    current_time: Any = None,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve a shared ManyChat timer flow to an explicit runtime cadence."""

    requested = str(cadence or "first").strip().casefold()
    if requested != "auto":
        return requested, None
    event_time = _parse_followup_datetime(channel_event_ts)
    now = _parse_followup_datetime(current_time or now_manila_str())
    if event_time is None or now is None:
        return None, "invalid_channel_event_ts_for_auto_cadence"
    age_minutes = max(0.0, (now - event_time).total_seconds() / 60.0)
    second_min = float(
        os.getenv("RUNTIME_V7_FOLLOWUP_SECOND_MIN_MINUTES", "660") or "660"
    )
    nurture_min = float(
        os.getenv("RUNTIME_V7_FOLLOWUP_NURTURE_MIN_MINUTES", "1440") or "1440"
    )
    if age_minutes > nurture_min:
        return "nurture", None
    if age_minutes >= second_min:
        return "second", None
    return "first", None


def _parse_followup_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(manila_tz).replace(tzinfo=None)
        return parsed
    except (TypeError, ValueError):
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _followup_webhook_token() -> str:
    return str(os.getenv("FOLLOWUP_WEBHOOK_TOKEN") or "").strip()


def _authorize_followup(authorization: str = Header(default="")) -> None:
    """Authenticate follow-up ingress before runtime I/O or state mutation."""

    expected = _followup_webhook_token()
    if not expected:
        raise HTTPException(status_code=503, detail="followup_webhook_token_not_configured")
    scheme, _, supplied = str(authorization or "").partition(" ")
    if scheme.casefold() != "bearer" or not supplied or not hmac.compare_digest(supplied.strip(), expected):
        raise HTTPException(status_code=401, detail="unauthorized_followup_request")


def _firestore_transport_probe_enabled() -> bool:
    """Keep the mutating benchmark endpoint explicit and staging-only."""

    environment = str(os.getenv("SERVICE_ENVIRONMENT") or "").strip().casefold()
    enabled = str(
        os.getenv("RUNTIME_V7_FIRESTORE_RPC_DIAGNOSTICS") or ""
    ).strip().casefold() in {"1", "true", "yes", "on"}
    return enabled and environment in {"staging", "stage", "test"}


def _hydrated_tester_history_user_allowlist() -> set[str]:
    """Return synthetic accounts permitted to trigger a ManyChat history read."""

    configured = os.getenv(
        "RUNTIME_V7_TESTER_HISTORY_USER_ALLOWLIST",
        DEFAULT_TEST_USER_ID,
    )
    return {
        value.strip()
        for value in str(configured or "").split(",")
        if value.strip()
    }


def _supplied_model_fields(request: BaseModel) -> set[str]:
    """Read Pydantic v1/v2 field-presence metadata without serializing input."""

    fields = getattr(request, "model_fields_set", None)
    if fields is None:
        fields = getattr(request, "__fields_set__", set())
    return {str(field) for field in fields or set()}


def _hydrated_tester_request_error(
    request: HydratedChatTesterRequestPayload,
) -> Optional[str]:
    """Fail closed before runtime I/O when a hydration probe is not isolated."""

    if str(request.channel or "").strip().casefold() != "manychat":
        return "hydrated_tester_requires_manychat_channel"
    user_id = str(request.user_id or "").strip()
    channel_user_id = str(request.channel_user_id or "").strip()
    if not user_id or not channel_user_id or user_id != channel_user_id:
        return "hydrated_tester_requires_matching_user_ids"
    if user_id not in _hydrated_tester_history_user_allowlist():
        return "hydrated_tester_user_not_allowlisted"
    if "conversation_history" in _supplied_model_fields(request):
        return "hydrated_tester_request_history_not_allowed"
    if bool(int(request.reset)):
        return "hydrated_tester_reset_not_allowed"
    return None


def _hydrated_tester_hydration_diagnostics(turn_record: Dict[str, Any]) -> Dict[str, Any]:
    """Return only scalar hydration status and count diagnostics for probes."""

    hydration = (
        turn_record.get("conversation_hydration")
        if isinstance(turn_record.get("conversation_hydration"), dict)
        else {}
    )
    metadata = hydration.get("metadata") if isinstance(hydration.get("metadata"), dict) else {}
    count_names = (
        "cached_message_count",
        "loaded_message_count",
        "segment_message_count",
        "model_facing_message_count",
        "message_age_days",
    )
    counts = {
        name: int(metadata[name])
        for name in count_names
        if isinstance(metadata.get(name), (int, float)) and not isinstance(metadata.get(name), bool)
    }
    return {
        "source": str(hydration.get("source") or ""),
        "cache_status": str(hydration.get("cache_status") or ""),
        "refresh_attempted": bool(hydration.get("refresh_attempted")),
        "loader_status": str(hydration.get("loader_status") or ""),
        "counts": counts,
    }


def _hydrated_tester_usage_diagnostics(turn_record: Dict[str, Any]) -> Dict[str, int]:
    """Return only numeric model-usage totals needed for the shared run budget."""

    usage = (
        turn_record.get("llm_usage_summary")
        if isinstance(turn_record.get("llm_usage_summary"), dict)
        else {}
    )
    names = (
        "llm_call_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cache_read_input_tokens",
        "uncached_prompt_tokens",
        "reasoning_tokens",
        "latency_ms",
    )
    return {
        name: int(usage[name])
        for name in names
        if isinstance(usage.get(name), (int, float))
        and not isinstance(usage.get(name), bool)
    }
def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return bool(default)
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _followup_send_enabled_for_user(user_id: str) -> bool:
    """Return server-configured delivery admission; requests cannot override it."""

    if not _env_flag("FOLLOWUP_SEND_ENABLED", default=False):
        return False
    allowlist = {
        item.strip()
        for item in str(os.getenv("FOLLOWUP_SEND_USER_ALLOWLIST") or "").split(",")
        if item.strip()
    }
    if allowlist:
        return str(user_id) in allowlist
    try:
        canary_percent = max(0, min(100, int(os.getenv("FOLLOWUP_SEND_CANARY_PERCENT", "0") or "0")))
    except (TypeError, ValueError):
        canary_percent = 0
    if canary_percent <= 0:
        return False
    bucket = int(hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:8], 16) % 100
    return bucket < canary_percent


def _deprecated_followup_fields(request: FollowupV7RequestPayload) -> List[str]:
    supplied: List[str] = []
    values = {
        "profile_fields": request.profile_fields,
        "conversation_history": request.conversation_history,
        "flow_context": request.flow_context,
        "force": request.force,
        "save_analytics": 0 if int(request.save_analytics) != 1 else None,
        "return_logs": request.return_logs,
        "delivery_mode": request.delivery_mode,
        "assigned_agent": request.assigned_agent,
        "full_name": request.full_name,
        "first_name": request.first_name,
        "last_name": request.last_name,
        "user_id_source": request.user_id_source,
        "request_time": request.request_time,
        "channel_user_id": request.channel_user_id,
        "channel": request.channel if str(request.channel or "manychat").casefold() != "manychat" else None,
        "channel_subtype": request.channel_subtype,
    }
    for field_name, value in values.items():
        if value not in (None, "", 0, [], {}):
            supplied.append(field_name)
    return supplied


def _followup_config_alerts() -> List[str]:
    alerts: List[str] = []
    enabled = _env_flag("FOLLOWUP_SEND_ENABLED", default=False)
    expected_raw = os.getenv("FOLLOWUP_EXPECT_SEND_ENABLED")
    if expected_raw is not None and enabled != _env_flag("FOLLOWUP_EXPECT_SEND_ENABLED", default=False):
        alerts.append("followup_send_mode_unexpected")
    is_cloud_run = bool(str(os.getenv("K_SERVICE") or "").strip())
    has_allowlist = bool(str(os.getenv("FOLLOWUP_SEND_USER_ALLOWLIST") or "").strip())
    if is_cloud_run and enabled and not has_allowlist:
        alerts.append("cloud_run_followup_send_enabled_without_trial_allowlist")
    return alerts


def _discovery_config_alerts() -> List[str]:
    """Report delivery configuration that would suppress interactive cards."""

    environment = str(os.getenv("SERVICE_ENVIRONMENT") or "").strip().casefold()
    if environment in {"staging", "stage", "test", "development", "dev"}:
        router = str(
            os.getenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE")
            or os.getenv("PROMO_STAGING_ROUTER_FLOW_NAMESPACE")
            or ""
        ).strip()
    else:
        router = str(
            os.getenv("PRICE_CATEGORY_LIVE_ROUTER_FLOW_NAMESPACE")
            or os.getenv("PROMO_LIVE_ROUTER_FLOW_NAMESPACE")
            or ""
        ).strip()
    return [] if router else ["interactive_choice_router_not_configured"]


def _has_external_idempotency_basis(request: ChatRequestPayload) -> bool:
    """Return true only when the channel supplied a real event identity."""

    return bool(
        str(request.idempotency_key or "").strip()
        or str(request.message_id or "").strip()
        or str(request.channel_event_id or "").strip()
        or str(request.channel_event_ts or "").strip()
    )


def _chat_v7_has_external_idempotency_basis(request: ChatRequestPayload) -> bool:
    return _has_external_idempotency_basis(request)


def _runtime_request(
    request: ChatRequestPayload,
    *,
    user_id: str,
    message_id: str,
    idempotency_key: str,
    delivery_mode: str,
    tester: bool = False,
) -> RuntimeV7APIRequest:
    return RuntimeV7APIRequest(
        user_id=user_id,
        channel_user_id=str(request.channel_user_id or user_id),
        channel=request.channel,
        channel_subtype=request.channel_subtype or "",
        user_text=request.user_text,
        full_name=request.full_name or "",
        first_name=request.first_name or "",
        last_name=request.last_name or "",
        assigned_agent=request.assigned_agent or "",
        profile_fields=dict(request.profile_fields or {}),
        message_id=str(request.message_id or ""),
        message_id_source="provided" if request.message_id else "derived",
        idempotency_key=str(request.idempotency_key or idempotency_key or ""),
        channel_event_id=str(request.channel_event_id or ""),
        channel_event_ts=str(request.channel_event_ts or ""),
        flow_context=dict(request.flow_context or {}),
        conversation_history=[dict(item) for item in request.conversation_history or [] if isinstance(item, dict)],
        raw_payload=_model_dump(request),
        normalized_payload=_normalized_payload(request, user_id=user_id),
        user_id_source=str(request.user_id_source or request.channel or "manychat"),
        reset=bool(int(request.reset)),
        return_logs=bool(int(request.return_logs)),
        tester=bool(tester),
        delivery_mode=delivery_mode,
    )


def _runtime_followup_request(
    request: FollowupV7RequestPayload,
    *,
    user_id: str,
    message_id: str,
    idempotency_key: str,
    delivery_mode: str,
    tester: bool = False,
) -> RuntimeV7APIRequest:
    flow_context = {
        "trigger": "followup_endpoint",
        "cadence": str(request.cadence or "first"),
        "route_contract_version": 2,
        "tester": bool(tester),
        "deprecated_request_fields_ignored": _deprecated_followup_fields(request),
    }
    return RuntimeV7APIRequest(
        user_id=user_id,
        channel_user_id=str(user_id),
        channel="manychat",
        channel_subtype="",
        user_text="",
        full_name="",
        first_name="",
        last_name="",
        assigned_agent="",
        profile_fields={},
        message_id=message_id,
        message_id_source="followup_trigger",
        idempotency_key=str(idempotency_key or ""),
        channel_event_id=str(request.channel_event_id or ""),
        channel_event_ts=str(request.channel_event_ts or ""),
        flow_context=flow_context,
        conversation_history=[],
        raw_payload={
            "user_id": str(user_id),
            "channel_event_id": str(request.channel_event_id or ""),
            "channel_event_ts": str(request.channel_event_ts or ""),
            "idempotency_key": str(idempotency_key),
            "cadence": str(request.cadence or "first"),
            "deprecated_request_fields_ignored": _deprecated_followup_fields(request),
        },
        normalized_payload=_followup_normalized_payload(request, user_id=user_id),
        user_id_source="manychat",
        reset=False,
        return_logs=bool(tester),
        tester=bool(tester),
        delivery_mode=delivery_mode,
    )


def _with_release_metadata(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload["runtime_generation"] = RUNTIME_GENERATION
    payload["release_version"] = os.getenv("RELEASE_VERSION", "")
    payload["git_sha"] = os.getenv("GIT_SHA", "")
    payload["service_environment"] = os.getenv("SERVICE_ENVIRONMENT", "")
    payload["runtime_host"] = os.getenv("RUNTIME_HOST", os.getenv("K_SERVICE", ""))
    return payload


_TEST_SESSION_STORE = MemorySessionStore()


def _with_test_suffix(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return name
    return name if name.endswith("_test") else f"{name}_test"


def _build_test_sessions_gateway() -> SessionsGateway:
    cfg_path = resolve_bu_config_path(_resolve_bu(), "session_store.json")
    cfg = load_session_store_config(cfg_path)
    config = SessionsGatewayConfig(
        project_id=cfg.firestore.project_id,
        users_collection=_with_test_suffix(cfg.firestore.users_collection),
        sessions_subcollection=_with_test_suffix(cfg.firestore.sessions_subcollection),
        enable_firestore=True,
        credentials_json=cfg.firestore.credentials_json,
        storage_kind="firestore",
        strategy_state_format=cfg.firestore.strategy_state_format,
    )
    return SessionsGateway(config=config, store=None)


async def _handle_chat(
    request: ChatRequestPayload,
    *,
    tester: bool = False,
    ingress_idempotency: bool = True,
    hydrated_tester: bool = False,
) -> Dict[str, Any]:
    """Run the standard chat path, with an opt-in isolated hydration probe."""

    bu = _resolve_bu()
    user_id = _user_id(request)
    if not user_id:
        return {"status": "error", "message": "user_id is required."}

    normalized_payload = _normalized_payload(request, user_id=user_id)
    message_id = str(request.message_id or _stable_message_id(normalized_payload))
    idempotency_key = str(request.idempotency_key or message_id)
    request_id = f"req_{uuid.uuid4().hex}"
    delivery_mode = (
        "return_only"
        if hydrated_tester
        else str(
            request.delivery_mode
            or ("return_only" if tester else os.getenv("RUNTIME_DELIVERY_MODE", "send_content"))
        )
    )

    idempotency_enabled = (
        not tester
        and ingress_idempotency
        and _has_external_idempotency_basis(request)
        and str(os.getenv("IDEMPOTENCY_ON", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
    )
    idempotency_gateway = build_idempotency_gateway(bu=bu) if idempotency_enabled else None
    if idempotency_enabled:
        decision = idempotency_gateway.begin(  # type: ignore[union-attr]
            user_id=user_id,
            message_id=message_id,
            idempotency_key=idempotency_key,
            payload=normalized_payload,
            request_id=request_id,
        )
        request_id = decision.request_id
        if decision.action == "replay" and isinstance(decision.replay_payload, dict):
            return _with_release_metadata(decision.replay_payload)
        if decision.action == "conflict":
            return _with_release_metadata(
                {"status": "error", "message": "idempotency_key_conflict", "idempotency_key": idempotency_key}
            )
        if decision.action == "in_progress":
            return _with_release_metadata(
                {"status": "in_progress", "message": "duplicate_request_processing", "idempotency_key": idempotency_key}
            )

    service = RuntimeV7APIService(
        sessions_gateway=_build_test_sessions_gateway() if tester else build_sessions_gateway(bu=bu),
        analytics_gateway=None if tester or not int(request.save_analytics) else build_analytics_gateway(bu=bu),
        delivery_mode=delivery_mode,
        fetch_manychat_profile=False if tester else None,
        fetch_manychat_messages=True if hydrated_tester else False if tester else None,
    )
    try:
        result = await service.handle(
            _runtime_request(
                request,
                user_id=user_id,
                message_id=message_id,
                idempotency_key=idempotency_key,
                delivery_mode=delivery_mode,
                tester=tester,
            ),
            request_id=request_id,
        )
        payload = result.to_payload(
            include_debug=bool(hydrated_tester or int(request.return_logs))
        )
        if hydrated_tester:
            # The normal debug payload can contain broader turn diagnostics.
            # This probe exposes only hydration provenance and scalar counts.
            payload.pop("turn_trace_summary", None)
            payload["debug"] = {
                "conversation_hydration": _hydrated_tester_hydration_diagnostics(
                    result.turn_record
                ),
                "llm_usage_summary": _hydrated_tester_usage_diagnostics(
                    result.turn_record
                ),
            }
    except RuntimeV7ProviderCallLimitExceeded as exc:
        if not tester:
            raise
        payload = {
            "status": "error",
            "request_id": request_id,
            "message": "tester_model_call_limit_exceeded",
            "tester_diagnostic": exc.diagnostic(),
            "idempotency_key": idempotency_key,
        }
        return _with_release_metadata(payload)
    except Exception as exc:
        logger.exception(
            "Runtime V7 chat request failed request_id=%s user_id=%s channel_user_id=%s channel=%s "
            "message_id=%s idempotency_key=%s tester=%s error_type=%s",
            request_id,
            user_id,
            str(request.channel_user_id or user_id),
            str(request.channel or ""),
            message_id,
            idempotency_key,
            tester,
            type(exc).__name__,
        )
        if idempotency_enabled:
            idempotency_gateway.fail(  # type: ignore[union-attr]
                user_id=user_id,
                idempotency_key=idempotency_key,
                error_type=type(exc).__name__,
            )
        payload = {
            "status": "error",
            "request_id": request_id,
            "response": {
                "bubble1": "Sorry po, may temporary issue sa system.",
                "bubble2": "Paki-send ulit yung last message para ma-check natin.",
            },
            "idempotency_key": idempotency_key,
        }
        return _with_release_metadata(payload)

    if idempotency_enabled:
        idempotency_gateway.complete(  # type: ignore[union-attr]
            user_id=user_id,
            idempotency_key=idempotency_key,
            response_payload=payload,
        )
    return _with_release_metadata(payload)


async def _handle_followup(
    request: FollowupV7RequestPayload,
    *,
    tester: bool = False,
) -> Dict[str, Any]:
    bu = _resolve_bu()
    user_id = request.user_id or (request.channel_user_id if tester else None)
    if not user_id:
        return {"status": "error", "message": "user_id is required."}
    requested_cadence = str(request.cadence or "first").strip().casefold()
    if not tester:
        required_values = {
            "channel_event_id": request.channel_event_id,
            "channel_event_ts": request.channel_event_ts,
            "idempotency_key": request.idempotency_key,
            "cadence": request.cadence,
        }
        missing = [name for name, value in required_values.items() if not str(value or "").strip()]
        if missing:
            return {
                "status": "error",
                "message": "missing_required_followup_fields",
                "missing_fields": missing,
            }
    resolved_cadence, cadence_error = _resolve_followup_cadence(
        requested_cadence,
        request.channel_event_ts,
    )
    if cadence_error:
        return {
            "status": "error",
            "message": cadence_error,
        }
    request.cadence = resolved_cadence  # type: ignore[assignment]

    normalized_payload = _followup_normalized_payload(request, user_id=user_id)
    request_id = f"req_{uuid.uuid4().hex}"
    external_key = str(request.idempotency_key or "followup_" + _stable_message_id(normalized_payload)[4:])
    if requested_cadence == "auto":
        external_key = f"{external_key}:{resolved_cadence}"
    idempotency_key = f"followup_tester:{external_key}" if tester else external_key
    message_id = idempotency_key
    delivery_mode = "return_only" if tester or not _followup_send_enabled_for_user(user_id) else "send_content"
    idempotency_gateway = build_idempotency_gateway(bu=bu)
    decision = idempotency_gateway.begin(
        user_id=str(user_id),
        message_id=message_id,
        idempotency_key=idempotency_key,
        payload=normalized_payload,
        request_id=request_id,
    )
    request_id = decision.request_id
    if decision.action == "replay" and isinstance(decision.replay_payload, dict):
        return _with_release_metadata(decision.replay_payload)
    if decision.action == "conflict":
        return _with_release_metadata(
            {"status": "error", "message": "idempotency_key_conflict", "idempotency_key": idempotency_key}
        )
    if decision.action == "in_progress":
        return _with_release_metadata(
            {"status": "in_progress", "message": "duplicate_request_processing", "idempotency_key": idempotency_key}
        )
    service = RuntimeV7APIService(
        sessions_gateway=build_sessions_gateway(bu=bu),
        analytics_gateway=build_analytics_gateway(bu=bu),
        delivery_mode=delivery_mode,
        fetch_manychat_profile=True,
        fetch_manychat_messages=True,
    )
    try:
        result = await service.handle_followup(
            _runtime_followup_request(
                request,
                user_id=user_id,
                message_id=message_id,
                idempotency_key=idempotency_key,
                delivery_mode=delivery_mode,
                tester=tester,
            ),
            request_id=request_id,
            force=False,
        )
        payload = result.to_payload(include_debug=bool(tester))
    except RuntimeV7ProviderCallLimitExceeded as exc:
        if not tester:
            raise
        payload = {
            "status": "error",
            "request_id": request_id,
            "message": "tester_model_call_limit_exceeded",
            "tester_diagnostic": exc.diagnostic(),
            "idempotency_key": idempotency_key,
        }
        idempotency_gateway.fail(
            user_id=str(user_id),
            idempotency_key=idempotency_key,
            error_type=type(exc).__name__,
        )
        return _with_release_metadata(payload)
    except Exception as exc:
        logger.exception(
            "Runtime V7 follow-up request failed request_id=%s user_id=%s channel_user_id=%s channel=%s "
            "idempotency_key=%s error_type=%s",
            request_id,
            user_id,
            str(request.channel_user_id or user_id),
            str(request.channel or ""),
            idempotency_key,
            type(exc).__name__,
        )
        payload = {
            "status": "error",
            "request_id": request_id,
            "response": {},
            "delivery_result": {
                "status": "suppressed",
                "reason": "followup_runtime_error",
                "error_type": type(exc).__name__,
            },
            "idempotency_key": idempotency_key,
        }
        idempotency_gateway.fail(
            user_id=str(user_id),
            idempotency_key=idempotency_key,
            error_type=type(exc).__name__,
        )
        return _with_release_metadata(payload)
    idempotency_gateway.complete(
        user_id=str(user_id),
        idempotency_key=idempotency_key,
        response_payload=payload,
    )
    return _with_release_metadata(payload)


async def _handle_hydrated_tester_chat(
    request: HydratedChatTesterRequestPayload,
) -> Dict[str, Any]:
    """Exercise real ManyChat hydration only for an authenticated synthetic user."""

    error = _hydrated_tester_request_error(request)
    if error:
        return _with_release_metadata({"status": "error", "message": error})
    payload = await _handle_chat(request, tester=True, hydrated_tester=True)
    delivery = payload.get("delivery_result")
    delivery = delivery if isinstance(delivery, dict) else {}
    tagging = payload.get("tagging_result")
    tagging = tagging if isinstance(tagging, dict) else {}
    # Even model output can echo private history. The authenticated probe only
    # returns mechanical evidence and never exposes rendered customer content.
    bounded = {
        "status": payload.get("status"),
        "request_id": payload.get("request_id"),
        "delivery_result": {
            **{
                key: delivery.get(key)
                for key in ("status", "reason")
                if delivery.get(key) not in (None, "")
            },
            # This route forces return_only before constructing the runtime;
            # expose the enforced contract even when a provider omits it.
            "delivery_mode": "return_only",
        },
        "tagging_result": {
            key: tagging.get(key)
            for key in ("status", "reason")
            if tagging.get(key) not in (None, "")
        },
        "debug": payload.get("debug") if isinstance(payload.get("debug"), dict) else {},
    }
    return _with_release_metadata(bounded)


def _promo_catalog_service() -> PromoCatalogService:
    brand_knowledge = None
    if brand_knowledge_enabled():
        brand_knowledge = BrandKnowledgeService(
            BrandKnowledgeRepository(
                project_id=os.getenv(
                    "GOOGLE_CLOUD_PROJECT",
                    "gulong-chatbot-459723",
                ),
                profiles_collection=os.getenv(
                    "BRAND_KNOWLEDGE_PROFILES_COLLECTION",
                    "brand_knowledge_profiles",
                ),
                chunks_collection=os.getenv(
                    "BRAND_KNOWLEDGE_CHUNKS_COLLECTION",
                    "brand_knowledge_chunks",
                ),
                config_collection=os.getenv(
                    "BRAND_KNOWLEDGE_CONFIG_COLLECTION",
                    "brand_knowledge_config",
                ),
            )
        )
    return PromoCatalogService(
        PromoCatalogRepository(
            project_id=os.getenv("GOOGLE_CLOUD_PROJECT", "gulong-chatbot-459723"),
            cards_collection=os.getenv("PROMO_CATALOG_CARDS_COLLECTION", "promo_catalog_cards"),
            mechanics_collection=os.getenv("PROMO_CATALOG_MECHANICS_COLLECTION", "promo_catalog_mechanics"),
            brand_profiles_collection=os.getenv("PROMO_BRAND_PROFILES_COLLECTION", "promo_brand_profiles"),
            config_collection=os.getenv("PROMO_CATALOG_CONFIG_COLLECTION", "promo_catalog_config"),
        ),
        brand_knowledge=brand_knowledge,
    )


def _promo_action_user_text(validation: Dict[str, Any]) -> str:
    if validation.get("status") == "stale":
        return "The promo card I clicked is no longer current. Please show me the current promos."
    promo = validation.get("promo") if isinstance(validation.get("promo"), dict) else {}
    title = str(promo.get("title") or "this promo").strip()
    brand = str(validation.get("selected_brand") or "").strip()
    action = str(validation.get("action") or "").strip()
    if action == "check_price":
        return f"I selected {brand or title} from the promo gallery and want to check the tire price."
    if action == "promo_details":
        return (
            "Please explain the reviewed promo details from the clicked card. "
            "This is an information request only, not a brand or product selection."
        )
    if action == "about_brand":
        return (
            "I clicked About Brand. Tell me about the tire brand named in "
            "the validated action context. I am asking about the tire brand, "
            "not submitting a customer review or feedback. This is "
            "information only, not a brand or product selection."
        )
    if action == "choose_brand" and not brand:
        return (
            "I clicked Choose Brand from the promo gallery. Show me the "
            "available tire-brand choices. I have not selected a brand or "
            "product yet; ask for my tire size if it is still needed."
        )
    return (
        f"I selected {brand or title} from the promo gallery. "
        "Show eligible promo tire prices for my current tire size; ask for my tire size if it is not confirmed."
    )


def _choice_validation_with_runtime(
    payload: Dict[str, Any],
    parsed_choice: Dict[str, Any],
) -> Dict[str, Any]:
    """Prefer Runtime V7's session allowlist result over parsed token shape."""

    runtime_validation = payload.get("choice_action_validation")
    if not isinstance(runtime_validation, dict) or not runtime_validation:
        runtime_validation = {"status": "accepted"}
    return {**parsed_choice, **runtime_validation}


async def _handle_promo_action(
    request: PromoActionV7RequestPayload,
    *,
    tester: bool = False,
) -> Dict[str, Any]:
    """Validate one guided action and preserve tester-session isolation."""
    user_id = str(request.user_id or request.channel_user_id or "").strip()
    if not user_id:
        return {"status": "error", "message": "user_id is required."}
    action_payload = _model_dump(request)
    try:
        choice_payload = parse_price_category_token(action_payload.get("promo_id"))
    except ValueError:
        return _with_release_metadata(
            {
                "status": "error",
                "message": "invalid_price_category_click_token",
                "choice_action_validation": {"status": "invalid", "reason": "malformed_click_token"},
            }
        )
    if choice_payload:
        return await _handle_price_category_action(
            request, choice_payload, tester=tester
        )
    try:
        product_payload = parse_product_choice_token(action_payload.get("promo_id"))
    except ValueError:
        return _with_release_metadata(
            {
                "status": "error",
                "message": "invalid_product_click_token",
                "choice_action_validation": {
                    "status": "invalid",
                    "reason": "malformed_click_token",
                },
            }
        )
    if product_payload:
        return await _handle_product_choice_action(
            request, product_payload, tester=tester
        )
    reference_choice_parsers = (
        (
            parse_schedule_choice_token,
            "schedule_selection",
            "invalid_schedule_click_token",
        ),
        (
            parse_payment_option_choice_token,
            "payment_option_selection",
            "invalid_payment_option_click_token",
        ),
        (
            parse_payment_method_choice_token,
            "payment_method_selection",
            "invalid_payment_method_click_token",
        ),
    )
    for parser, choice_type, error_message in reference_choice_parsers:
        try:
            reference_choice = parser(action_payload.get("promo_id"))
        except ValueError:
            return _with_release_metadata(
                {
                    "status": "error",
                    "message": error_message,
                    "choice_action_validation": {
                        "status": "invalid",
                        "reason": "malformed_click_token",
                    },
                }
            )
        if reference_choice:
            return await _handle_reference_choice_action(
                request,
                reference_choice,
                choice_type=choice_type,
                tester=tester,
            )
    try:
        location_payload = parse_location_choice_token(action_payload.get("promo_id"))
    except ValueError:
        return _with_release_metadata(
            {
                "status": "error",
                "message": "invalid_location_click_token",
                "choice_action_validation": {
                    "status": "invalid",
                    "reason": "malformed_click_token",
                },
            }
        )
    if location_payload:
        return await _handle_location_action(
            request, location_payload, tester=tester
        )
    if not promo_catalog_enabled_for_user(user_id):
        return _with_release_metadata(
            {
                "status": "error",
                "message": "promo_catalog_disabled",
                "promo_action_validation": {"status": "invalid", "reason": "feature_disabled"},
            }
        )
    try:
        token_payload = parse_promo_click_token(action_payload.get("promo_id"))
    except ValueError:
        return _with_release_metadata(
            {
                "status": "error",
                "message": "invalid_promo_click_token",
                "promo_action_validation": {"status": "invalid", "reason": "malformed_click_token"},
            }
        )
    action_payload.update(token_payload)
    validation = _promo_catalog_service().validate_action(action_payload)
    if validation.get("status") == "invalid":
        return _with_release_metadata(
            {
                "status": "error",
                "message": str(validation.get("reason") or "invalid_promo_action"),
                "promo_action_validation": validation,
            }
        )
    action = str(action_payload["action"]).strip().lower()
    selection_action = action in PROMO_SELECTION_ACTIONS
    selected_brand = (
        str(action_payload.get("selected_brand") or "")
        if selection_action
        else ""
    )
    profile_fields = {
        **dict(request.profile_fields or {}),
        "promo_catalog_version": str(action_payload["catalog_version_id"]),
        "promo_selected_id": str(action_payload["promo_id"]),
        "promo_selected_card_id": str(action_payload["card_id"]),
        "promo_selected_action": action,
        "promo_selected_brand": selected_brand,
        "promo_selected_at": str(request.click_timestamp),
        "promo_source": "manychat_router_flow",
        "chatbot_state": "promo_action",
        "_promo_action_mirror": {
            "promo_id": str(action_payload["promo_id"]),
            "card_id": str(action_payload["card_id"]),
            "action": action,
            "selected_brand": selected_brand,
            "click_timestamp": str(request.click_timestamp),
        },
    }
    chat_request = ChatRequestPayload(
        user_id=user_id,
        channel_user_id=str(request.channel_user_id or user_id),
        channel=request.channel,
        channel_subtype=request.channel_subtype,
        user_text=_promo_action_user_text(validation),
        full_name=request.full_name,
        first_name=request.first_name,
        last_name=request.last_name,
        assigned_agent=request.assigned_agent,
        profile_fields=profile_fields,
        message_id=request.event_id,
        idempotency_key=request.idempotency_key,
        channel_event_id=request.event_id,
        channel_event_ts=request.click_timestamp,
        flow_context={
            "trigger": "promo_action",
            "promo_action_context": validation,
            "promo_action_status": validation.get("status"),
        },
        conversation_history=request.conversation_history,
        user_id_source="manychat_promo_action",
        save_analytics=request.save_analytics,
        return_logs=request.return_logs,
        delivery_mode="return_only" if tester else request.delivery_mode,
    )
    # The locked Runtime V7 session ledger already deduplicates inbound events.
    # Avoid a second Firestore response write on this latency-sensitive click path.
    payload = await _handle_chat(
        chat_request, tester=tester, ingress_idempotency=False
    )
    payload["promo_action_validation"] = validation
    return payload


async def _handle_price_category_action(
    request: PromoActionV7RequestPayload,
    choice: Dict[str, str],
    *,
    tester: bool = False,
) -> Dict[str, Any]:
    """Route one tracked category selection through the normal Runtime V7 turn."""

    user_id = str(request.user_id or request.channel_user_id or "").strip()
    if not user_id:
        return {"status": "error", "message": "user_id is required."}
    category_labels = {
        "budget": "Budget",
        "economy": "Economy",
        "mid_range": "Mid Range",
        "premium": "Premium",
    }
    label = category_labels[choice["category"]]
    tire_size = f"{choice['section_width']}/{choice['aspect_ratio']}{choice['rim_size']}"
    profile_fields = {
        **dict(request.profile_fields or {}),
        "promo_selected_id": str(request.promo_id),
        "promo_selected_action": "choose_price_category",
        "promo_selected_brand": "",
        "promo_selected_at": str(request.click_timestamp),
        "promo_source": "manychat_router_flow",
        "chatbot_state": "price_category_action",
        "discovery_surface_type": "price_category_choices",
        "discovery_surface_ref": choice["presentation_ref"],
        "discovery_choice_type": "price_category",
        "discovery_choice_value": label,
        "discovery_choice_selected_at": str(request.click_timestamp),
    }
    chat_request = ChatRequestPayload(
        user_id=user_id,
        channel_user_id=str(request.channel_user_id or user_id),
        channel=request.channel,
        channel_subtype=request.channel_subtype,
        user_text=(
            f"I selected the {label} price category for tire size {tire_size}. "
            "Show me the best two to four matching current products in this category."
        ),
        full_name=request.full_name,
        first_name=request.first_name,
        last_name=request.last_name,
        assigned_agent=request.assigned_agent,
        profile_fields=profile_fields,
        message_id=request.event_id,
        idempotency_key=request.idempotency_key,
        channel_event_id=request.event_id,
        channel_event_ts=request.click_timestamp,
        flow_context={
            "trigger": "choice_action",
            "choice_action_context": {
                **choice,
                "choice_type": "price_category",
                "label": label,
                "tire_size": tire_size,
            },
        },
        conversation_history=request.conversation_history,
        user_id_source="manychat_price_category_action",
        save_analytics=request.save_analytics,
        return_logs=request.return_logs,
        delivery_mode="return_only" if tester else request.delivery_mode,
    )
    payload = await _handle_chat(
        chat_request, tester=tester, ingress_idempotency=False
    )
    payload["choice_action_validation"] = _choice_validation_with_runtime(
        payload,
        {
        "presentation_ref": choice["presentation_ref"],
        "choice_type": "price_category",
        "category": choice["category"],
        "tire_size": tire_size,
        },
    )
    return payload


async def _handle_location_action(
    request: PromoActionV7RequestPayload,
    choice: Dict[str, str],
    *,
    tester: bool = False,
) -> Dict[str, Any]:
    """Route a source-backed province or city click through the normal turn."""

    user_id = str(request.user_id or request.channel_user_id or "").strip()
    if not user_id:
        return {"status": "error", "message": "user_id is required."}
    level = choice["level"]
    choice_type = f"serviceable_{level}"
    is_other = level == "province" and choice["choice_code"] == "other"
    if is_other:
        user_text = (
            "I selected Others from the guided installation-area choices. "
            "This is not a positive location or fulfillment selection. "
            "Continue from the validated guided-choice context."
        )
    elif level == "province":
        user_text = (
            "I selected a serviceable province. "
            "Show only the currently serviceable cities under that province."
        )
    else:
        user_text = (
            "I selected a serviceable city for installation. "
            "Continue with the nearest current installation-partner options."
        )
    profile_fields = {
        **dict(request.profile_fields or {}),
        "promo_selected_id": str(request.promo_id),
        "promo_selected_action": f"choose_{level}",
        "promo_selected_brand": "",
        "promo_selected_at": str(request.click_timestamp),
        "promo_source": "manychat_router_flow",
        "chatbot_state": f"location_{level}_action",
        "discovery_surface_type": f"serviceable_{level}_choices",
        "discovery_surface_ref": choice["presentation_ref"],
        "discovery_choice_type": choice_type,
        "discovery_choice_value": choice["choice_code"],
        "discovery_choice_selected_at": str(request.click_timestamp),
    }
    chat_request = ChatRequestPayload(
        user_id=user_id,
        channel_user_id=str(request.channel_user_id or user_id),
        channel=request.channel,
        channel_subtype=request.channel_subtype,
        user_text=user_text,
        full_name=request.full_name,
        first_name=request.first_name,
        last_name=request.last_name,
        assigned_agent=request.assigned_agent,
        profile_fields=profile_fields,
        message_id=request.event_id,
        idempotency_key=request.idempotency_key,
        channel_event_id=request.event_id,
        channel_event_ts=request.click_timestamp,
        flow_context={
            "trigger": "choice_action",
            "choice_action_context": {
                **choice,
                "choice_type": choice_type,
                "recommended_service_path": "delivery" if is_other else "",
                "service_path_selected": False if is_other else None,
            },
        },
        conversation_history=request.conversation_history,
        user_id_source="manychat_location_choice_action",
        save_analytics=request.save_analytics,
        return_logs=request.return_logs,
        delivery_mode="return_only" if tester else request.delivery_mode,
    )
    payload = await _handle_chat(
        chat_request, tester=tester, ingress_idempotency=False
    )
    payload["choice_action_validation"] = _choice_validation_with_runtime(
        payload,
        {
        "presentation_ref": choice["presentation_ref"],
        "choice_type": choice_type,
        "choice_code": choice["choice_code"],
        "parent_code": choice["parent_code"],
        },
    )
    return payload


async def _handle_product_choice_action(
    request: PromoActionV7RequestPayload,
    choice: Dict[str, str],
    *,
    tester: bool = False,
) -> Dict[str, Any]:
    """Route an exact delivered product-card choice through Runtime V7."""

    user_id = str(request.user_id or request.channel_user_id or "").strip()
    if not user_id:
        return {"status": "error", "message": "user_id is required."}
    profile_fields = {
        **dict(request.profile_fields or {}),
        "promo_selected_id": str(request.promo_id),
        "promo_selected_action": "choose_product",
        "promo_selected_at": str(request.click_timestamp),
        "promo_source": "manychat_router_flow",
        "chatbot_state": "product_choice_action",
        "discovery_surface_type": "product_choices",
        "discovery_surface_ref": choice["presentation_ref"],
        "discovery_choice_type": "product_selection",
        "discovery_choice_value": choice["card_ref"],
        "discovery_choice_selected_at": str(request.click_timestamp),
    }
    chat_request = ChatRequestPayload(
        user_id=user_id,
        channel_user_id=str(request.channel_user_id or user_id),
        channel=request.channel,
        channel_subtype=request.channel_subtype,
        user_text=(
            "I selected one exact tire from the product buttons. "
            "Continue from that validated product selection."
        ),
        full_name=request.full_name,
        first_name=request.first_name,
        last_name=request.last_name,
        assigned_agent=request.assigned_agent,
        profile_fields=profile_fields,
        message_id=request.event_id,
        idempotency_key=request.idempotency_key,
        channel_event_id=request.event_id,
        channel_event_ts=request.click_timestamp,
        flow_context={
            "trigger": "choice_action",
            "choice_action_context": {
                **choice,
                "choice_type": "product_selection",
            },
        },
        conversation_history=request.conversation_history,
        user_id_source="manychat_product_choice_action",
        save_analytics=request.save_analytics,
        return_logs=request.return_logs,
        delivery_mode="return_only" if tester else request.delivery_mode,
    )
    payload = await _handle_chat(
        chat_request, tester=tester, ingress_idempotency=False
    )
    payload["choice_action_validation"] = _choice_validation_with_runtime(
        payload,
        {
        "presentation_ref": choice["presentation_ref"],
        "choice_type": "product_selection",
        "card_ref": choice["card_ref"],
        },
    )
    return payload


async def _handle_reference_choice_action(
    request: PromoActionV7RequestPayload,
    choice: Dict[str, str],
    *,
    choice_type: str,
    tester: bool = False,
) -> Dict[str, Any]:
    """Route a delivered schedule or checkout choice through Runtime V7."""

    user_id = str(request.user_id or request.channel_user_id or "").strip()
    if not user_id:
        return {"status": "error", "message": "user_id is required."}
    action_labels = {
        "schedule_selection": "choose_schedule",
        "payment_option_selection": "choose_payment_option",
        "payment_method_selection": "choose_payment_method",
    }
    user_texts = {
        "schedule_selection": (
            "I selected one schedule control that the runtime just delivered. "
            "Validate it against that schedule presentation and continue."
        ),
        "payment_option_selection": (
            "I selected one Pay Now or Pay Later control that the runtime just "
            "delivered. Continue from that validated checkout option."
        ),
        "payment_method_selection": (
            "I selected one payment method that the runtime just delivered. "
            "Continue from that validated checkout method."
        ),
    }
    action = action_labels[choice_type]
    profile_fields = {
        **dict(request.profile_fields or {}),
        "promo_selected_id": str(request.promo_id),
        "promo_selected_action": action,
        "promo_selected_at": str(request.click_timestamp),
        "promo_source": "manychat_router_flow",
        "chatbot_state": f"{choice_type}_action",
        "discovery_surface_type": choice_type,
        "discovery_surface_ref": choice["presentation_ref"],
        "discovery_choice_type": choice_type,
        "discovery_choice_value": choice["choice_ref"],
        "discovery_choice_selected_at": str(request.click_timestamp),
    }
    chat_request = ChatRequestPayload(
        user_id=user_id,
        channel_user_id=str(request.channel_user_id or user_id),
        channel=request.channel,
        channel_subtype=request.channel_subtype,
        user_text=user_texts[choice_type],
        full_name=request.full_name,
        first_name=request.first_name,
        last_name=request.last_name,
        assigned_agent=request.assigned_agent,
        profile_fields=profile_fields,
        message_id=request.event_id,
        idempotency_key=request.idempotency_key,
        channel_event_id=request.event_id,
        channel_event_ts=request.click_timestamp,
        flow_context={
            "trigger": "choice_action",
            "choice_action_context": {
                **choice,
                "choice_type": choice_type,
            },
        },
        conversation_history=request.conversation_history,
        user_id_source=f"manychat_{choice_type}_action",
        save_analytics=request.save_analytics,
        return_logs=request.return_logs,
        delivery_mode="return_only" if tester else request.delivery_mode,
    )
    payload = await _handle_chat(
        chat_request,
        tester=tester,
        ingress_idempotency=False,
    )
    payload["choice_action_validation"] = _choice_validation_with_runtime(
        payload,
        {
        "presentation_ref": choice["presentation_ref"],
        "choice_type": choice_type,
        "choice_ref": choice["choice_ref"],
        },
    )
    return payload


@router.get("/health", response_model=Dict[str, Any])
async def health() -> Dict[str, Any]:
    return _with_release_metadata(
        {
            "status": "ok",
            "ts": now_manila_str(),
            "followup": {
                "send_enabled": _env_flag("FOLLOWUP_SEND_ENABLED", default=False),
                "webhook_token_configured": bool(_followup_webhook_token()),
                "allowlist_configured": bool(str(os.getenv("FOLLOWUP_SEND_USER_ALLOWLIST") or "").strip()),
                "canary_percent": str(os.getenv("FOLLOWUP_SEND_CANARY_PERCENT", "0") or "0"),
                "config_alerts": _followup_config_alerts(),
            },
            "interactive_discovery": {
                "router_configured": not _discovery_config_alerts(),
                "config_alerts": _discovery_config_alerts(),
            },
        }
    )


@router.post("/chat", response_model=Dict[str, Any])
async def chat(request: ChatRequestPayload) -> Dict[str, Any]:
    return await _handle_chat(request, tester=False)


@router.post("/chat/tester", response_model=Dict[str, Any])
async def chat_tester(request: ChatTesterRequestPayload) -> Dict[str, Any]:
    return await _handle_chat(request, tester=True)


@router.post("/v7/chat", response_model=Dict[str, Any])
async def chat_v7_compat(request: ChatRequestPayload) -> Dict[str, Any]:
    return await _handle_chat(request, tester=False)


@router.post("/v7/chat/tester", response_model=Dict[str, Any])
async def chat_v7_tester_compat(request: ChatTesterRequestPayload) -> Dict[str, Any]:
    return await _handle_chat(request, tester=True)


@router.post("/v7/chat/tester/hydrated", response_model=Dict[str, Any])
async def chat_v7_tester_hydrated(
    request: HydratedChatTesterRequestPayload,
    _authorized: None = Depends(_authorize_followup),
) -> Dict[str, Any]:
    """Probe ManyChat history hydration without delivery, tags, or analytics."""

    return await _handle_hydrated_tester_chat(request)


@router.post("/v7/session-persistence/tester", response_model=Dict[str, Any])
async def session_persistence_v7_tester(
    request: FirestoreTransportTesterRequestPayload,
    _authorized: None = Depends(_authorize_followup),
) -> Dict[str, Any]:
    """Run generated Firestore CAS writes without model or customer access."""

    if not _firestore_transport_probe_enabled():
        raise HTTPException(status_code=404, detail="transport_probe_disabled")
    project_id = str(
        os.getenv("GOOGLE_CLOUD_PROJECT") or "gulong-chatbot-459723"
    ).strip()
    result = await asyncio.to_thread(
        run_firestore_transport_probe,
        project_id=project_id,
        warmups=request.warmups,
        rounds=request.rounds,
        payload_kib=request.payload_kib,
    )
    return _with_release_metadata(result)


@router.post(
    "/v7/session-persistence/representation-tester",
    response_model=Dict[str, Any],
)
async def session_persistence_representation_v7_tester(
    request: FirestoreRepresentationTesterRequestPayload,
    _authorized: None = Depends(_authorize_followup),
) -> Dict[str, Any]:
    """Compare generated nested, JSON, and gzip state through one CAS path."""

    if not _firestore_transport_probe_enabled():
        raise HTTPException(status_code=404, detail="transport_probe_disabled")
    project_id = str(
        os.getenv("GOOGLE_CLOUD_PROJECT") or "gulong-chatbot-459723"
    ).strip()
    session_store_config = load_session_store_config(
        resolve_bu_config_path(_resolve_bu(), "session_store.json")
    )
    result = await asyncio.to_thread(
        run_firestore_representation_probe,
        project_id=project_id,
        warmups=request.warmups,
        rounds=request.rounds,
        payload_kib=request.payload_kib,
        configured_strategy_state_format=(
            session_store_config.firestore.strategy_state_format
        ),
    )
    return _with_release_metadata(result)


@router.post("/v7/followup", response_model=Dict[str, Any])
async def chat_v7_followup(
    request: FollowupV7RequestPayload,
    _authorized: None = Depends(_authorize_followup),
) -> Dict[str, Any]:
    return await _handle_followup(request, tester=False)


@router.post("/v7/followup/tester", response_model=Dict[str, Any])
async def chat_v7_followup_tester(
    request: FollowupV7TesterRequestPayload,
    _authorized: None = Depends(_authorize_followup),
) -> Dict[str, Any]:
    return await _handle_followup(request, tester=True)


@router.post("/v7/promo-action", response_model=Dict[str, Any])
async def chat_v7_promo_action(request: PromoActionV7RequestPayload) -> Dict[str, Any]:
    return await _handle_promo_action(request)


@router.post("/v7/choice-action", response_model=Dict[str, Any])
async def chat_v7_choice_action(request: PromoActionV7RequestPayload) -> Dict[str, Any]:
    """Generic interactive router; promo-action remains a compatibility alias."""

    return await _handle_promo_action(request)


@router.post("/v7/choice-action/tester", response_model=Dict[str, Any])
async def chat_v7_choice_action_tester(
    request: PromoActionV7RequestPayload,
) -> Dict[str, Any]:
    """Exercise guided actions against tester storage with no channel delivery."""

    return await _handle_promo_action(request, tester=True)
