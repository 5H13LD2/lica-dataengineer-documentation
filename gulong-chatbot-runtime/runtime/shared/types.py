"""
Core data contracts for runtime.

These types define the canonical shapes for sessions, tool outputs, and
LLM usage spans. They are designed to be JSON-serializable.

Usage:
    session = SessionDoc(...)
    payload = session.to_dict()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MessageTurn:
    """
    Compact representation of a single message turn.

    Fields:
        role: "user" or "assistant".
        text: Message text.
        ts: Asia/Manila timestamp string.
        tool_summary_refs: Optional list of tool refs or ids.
    """
    role: str
    text: str
    ts: str
    tool_summary_refs: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {"role": self.role, "text": self.text, "ts": self.ts}
        if self.tool_summary_refs:
            data["tool_summary_refs"] = list(self.tool_summary_refs)
        return data


@dataclass
class UserDoc:
    """
    Firestore user document keyed by user_id.

    Fields:
        channel_user_id: Channel-native identifier for cross-channel mapping.
        active_session_id: Current active session for the user.
    """
    user_id: str
    channel_user_id: Optional[str]
    active_session_id: str
    updated_at: str
    user_id_source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "channel_user_id": self.channel_user_id,
            "active_session_id": self.active_session_id,
            "updated_at": self.updated_at,
            "user_id_source": self.user_id_source,
        }


@dataclass
class SessionDoc:
    """
    Firestore session document stored under users/{user_id}/sessions/{session_id}.

    Fields:
        status: active|closed.
        opened_at, last_user_message_at, closed_at: Asia/Manila timestamps.
        strategy_state, handoff_state: Reserved for future use.
    """
    session_id: str
    user_id: str
    status: str
    opened_at: str
    last_user_message_at: str
    closed_at: Optional[str]
    summary: str
    slots: Dict[str, Any] = field(default_factory=dict)
    messages: List[MessageTurn] = field(default_factory=list)
    strategy_state: Optional[Dict[str, Any]] = None
    handoff_state: Optional[Dict[str, Any]] = None
    updated_at: Optional[str] = None
    revision: int = 0
    last_request_id: Optional[str] = None
    active_lock_until: Optional[str] = None
    active_lock_owner: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "status": self.status,
            "opened_at": self.opened_at,
            "last_user_message_at": self.last_user_message_at,
            "closed_at": self.closed_at,
            "summary": self.summary,
            "slots": dict(self.slots),
            "messages": [m.to_dict() for m in self.messages],
            "strategy_state": self.strategy_state,
            "handoff_state": self.handoff_state,
            "updated_at": self.updated_at,
            "revision": int(self.revision or 0),
            "last_request_id": self.last_request_id,
            "active_lock_until": self.active_lock_until,
            "active_lock_owner": self.active_lock_owner,
        }


@dataclass
class ToolEnvelopeMeta:
    """
    Metadata for tool execution.

    Fields:
        source: Trusted price source if applicable.
        generated_at: Asia/Manila timestamp string.
        ttl_seconds: Recency TTL for price safety checks.
        args_hash/idempotency_key: Deterministic ids for retries/dedupe.
        error_type: timeout|validation|upstream|unknown.
    """
    trace_id: str
    session_id: str
    user_id: str
    source: Optional[str]
    generated_at: str
    ttl_seconds: int
    cache_hit: bool
    args_hash: Optional[str] = None
    idempotency_key: Optional[str] = None
    error_type: Optional[str] = None
    truncated: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "source": self.source,
            "generated_at": self.generated_at,
            "ttl_seconds": self.ttl_seconds,
            "cache_hit": self.cache_hit,
            "args_hash": self.args_hash,
            "idempotency_key": self.idempotency_key,
            "error_type": self.error_type,
            "truncated": self.truncated,
        }


@dataclass
class ToolEnvelope:
    """
    Tool execution envelope used for logging and guardrails.

    Usage:
        envelope = ToolEnvelope(...).to_dict()
    """
    tool_name: str
    ok: bool
    ms: int
    args: Dict[str, Any]
    data: Any
    error: Optional[str]
    meta: ToolEnvelopeMeta

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "ok": self.ok,
            "ms": self.ms,
            "args": dict(self.args),
            "data": self.data,
            "error": self.error,
            "meta": self.meta.to_dict(),
        }


@dataclass
class LLMSpanMeta:
    """
    Metadata for an LLMSpan, including version tags for auditability.

    Fields:
        prompt_version, slot_spec_version, tool_policy_version, renderer_version.
    """
    trace_id: str
    session_id: str
    user_id: str
    channel: str
    business_unit: str
    prompt_version: str
    slot_spec_version: str
    tool_policy_version: str
    renderer_version: str
    tool_name: Optional[str] = None
    used_fallback_attempted: Optional[bool] = None
    remaining_ms_at_start: Optional[int] = None
    max_tokens_requested: Optional[int] = None
    token_buckets: Optional[Dict[str, int]] = None
    token_bucket_model: Optional[str] = None
    cached_prompt_tokens: Optional[int] = None
    cache_creation_prompt_tokens: Optional[int] = None
    effective_prompt_tokens: Optional[int] = None
    fallback_trigger_error: Optional[str] = None
    fallback_trigger_provider: Optional[str] = None
    fallback_trigger_model: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "channel": self.channel,
            "business_unit": self.business_unit,
            "prompt_version": self.prompt_version,
            "slot_spec_version": self.slot_spec_version,
            "tool_policy_version": self.tool_policy_version,
            "renderer_version": self.renderer_version,
            "tool_name": self.tool_name,
            "used_fallback_attempted": self.used_fallback_attempted,
            "remaining_ms_at_start": self.remaining_ms_at_start,
            "max_tokens_requested": self.max_tokens_requested,
            "token_buckets": self.token_buckets,
            "token_bucket_model": self.token_bucket_model,
            "cached_prompt_tokens": self.cached_prompt_tokens,
            "cache_creation_prompt_tokens": self.cache_creation_prompt_tokens,
            "effective_prompt_tokens": self.effective_prompt_tokens,
            "fallback_trigger_error": self.fallback_trigger_error,
            "fallback_trigger_provider": self.fallback_trigger_provider,
            "fallback_trigger_model": self.fallback_trigger_model,
        }


@dataclass
class LLMSpan:
    """
    LLM call span for cost and latency tracking.

    Usage:
        span = LLMSpan(...).to_dict()
    """
    span_id: str
    component: str
    model: str
    provider: str
    tokens_in: int
    tokens_out: int
    cost_est: float
    latency_ms: int
    ok: bool
    error: Optional[str]
    meta: LLMSpanMeta

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_id": self.span_id,
            "component": self.component,
            "model": self.model,
            "provider": self.provider,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_est": self.cost_est,
            "latency_ms": self.latency_ms,
            "ok": self.ok,
            "error": self.error,
            "meta": self.meta.to_dict(),
        }
