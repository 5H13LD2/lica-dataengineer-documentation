"""Runtime V7 local LLM gateway for tool-call probes.

This is a focused port of the LLMGateway idea for Runtime V7 experiments. It
keeps the Runtime V7 tests isolated from older runtime modules while still
using LiteLLM as the only model transport.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Sequence

try:
    from dotenv import dotenv_values, load_dotenv
except Exception:  # pragma: no cover - dependency is present in the repo env.
    dotenv_values = None
    load_dotenv = None


ENV_PATH = Path(__file__).resolve().parents[1] / "configs" / ".env"
GEMINI_CONTEXT_CACHE_DEFAULT_MIN_TOKENS = 2048
GEMINI_CONTEXT_CACHE_APPROX_CHARS_PER_TOKEN = 4
GEMINI_CONTEXT_CACHE_STRATEGY = "litellm_gemini_context_cache_system_prompt"
_MAX_PROVIDER_CALL_DIAGNOSTIC_LABEL_CHARS = 80


def _provider_call_metadata_label(
    metadata: Optional[Dict[str, Any]],
    key: str,
) -> Optional[str]:
    """Read one safe call-origin label without retaining provider metadata."""

    if not isinstance(metadata, dict):
        return None
    return _provider_call_diagnostic_label(metadata.get(key))


def _provider_call_diagnostic_label(value: Any) -> Optional[str]:
    """Keep only a short identifier; prompts and arbitrary metadata fail closed."""

    if not isinstance(value, str):
        return None
    label = value.strip()
    if (
        not label
        or len(label) > _MAX_PROVIDER_CALL_DIAGNOSTIC_LABEL_CHARS
        or not label[0].isalnum()
        or not all(character.isalnum() or character in "_.:-" for character in label)
    ):
        return None
    return label


class RuntimeV7ProviderCallLimitExceeded(RuntimeError):
    """Raised before a tester request would exceed its provider-call budget.

    The error deliberately carries only bounded counting diagnostics so it can
    be returned by the tester endpoint without exposing a provider payload,
    credentials, or upstream error text.
    """

    def __init__(
        self,
        *,
        max_provider_calls: int,
        attempted_provider_calls: int,
        component: Optional[str] = None,
        phase: Optional[str] = None,
    ) -> None:
        self.max_provider_calls = int(max_provider_calls)
        self.attempted_provider_calls = int(attempted_provider_calls)
        self.reservation_ordinal = min(max(1, self.attempted_provider_calls), 1000)
        self.component = _provider_call_diagnostic_label(component)
        self.phase = _provider_call_diagnostic_label(phase)
        super().__init__("runtime_v7_tester_model_call_limit_exceeded")

    def diagnostic(self) -> Dict[str, Any]:
        """Return the safe diagnostic contract for tester-only error payloads."""

        diagnostic = {
            "code": "runtime_v7_tester_model_call_limit_exceeded",
            "max_provider_calls": self.max_provider_calls,
            "attempted_provider_calls": self.attempted_provider_calls,
            "reservation_ordinal": self.reservation_ordinal,
        }
        if self.component:
            diagnostic["component"] = self.component
        if self.phase:
            diagnostic["phase"] = self.phase
        return diagnostic


@dataclass
class RuntimeV7ProviderCallGuard:
    """Share a hard per-request ceiling across Runtime V7 provider clients.

    ``reserve`` is called immediately before each completion or embedding
    transport invocation. This means retries consume a slot too, and a call
    that would exceed the ceiling never reaches the provider. ``None`` leaves
    normal serving behavior unchanged.
    """

    max_provider_calls: Optional[int] = None
    provider_call_count: int = 0
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def reserve(self, *, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Reserve one actual provider request or fail before sending it."""

        with self._lock:
            attempted = self.provider_call_count + 1
            if self.max_provider_calls is not None and attempted > self.max_provider_calls:
                raise RuntimeV7ProviderCallLimitExceeded(
                    max_provider_calls=self.max_provider_calls,
                    attempted_provider_calls=attempted,
                    component=_provider_call_metadata_label(metadata, "component"),
                    phase=_provider_call_metadata_label(metadata, "phase"),
                )
            self.provider_call_count = attempted


@dataclass
class RuntimeV7LLMGatewayConfig:
    """Configuration for the V7 LiteLLM gateway."""

    model: str = "gemini/gemini-2.5-flash"
    api_key_env: str = "GEMINI_API_KEY"
    reasoning_effort: Optional[str] = None
    embedding_model: str = ""
    embedding_api_key_env: str = ""
    embedding_timeout_s: float = 20.0
    temperature: float = 0.2
    max_tokens: int = 1400
    timeout_s: float = 30.0
    max_transport_retries: int = 0
    transport_retry_backoff_s: float = 0.75
    sanitize_tools: bool = True
    enable_context_cache: bool = False
    context_cache_ttl: Optional[str] = "300s"
    provider_call_guard: Optional[RuntimeV7ProviderCallGuard] = None


@dataclass(frozen=True)
class _ContextCachePolicy:
    """Provider-specific context-cache behavior for a single gateway request."""

    provider_mode: str
    should_mark_cache: bool
    omit_tool_choice_for_cached_tools: bool
    retry_without_cache_on_settings_conflict: bool
    strategy: str
    skipped_reason: Optional[str] = None


class RuntimeV7LLMGateway:
    """Small LiteLLM gateway with JSON-safe response normalization."""

    def __init__(self, *, config: Optional[RuntimeV7LLMGatewayConfig] = None, client: Optional[Any] = None) -> None:
        self.config = config or RuntimeV7LLMGatewayConfig()
        self._env_from_file = _load_env_file()
        self._client = client or self._load_litellm()

    def complete(
        self,
        *,
        messages: Sequence[Dict[str, Any]],
        tools: Optional[Sequence[Dict[str, Any]]] = None,
        tool_choice: Any = "auto",
        metadata: Optional[Dict[str, Any]] = None,
        response_format: Optional[Any] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Synchronous wrapper for local probes and tests."""

        return asyncio.run(
            self.acomplete(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                metadata=metadata,
                response_format=response_format,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
                temperature=temperature,
            )
        )

    def embed(
        self,
        *,
        texts: Sequence[str],
        model: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        dimensions: Optional[int] = None,
        timeout_s: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Return query embeddings through LiteLLM for local V7 RAG tools."""

        started = time.perf_counter()
        embedding_model = str(
            model
            or self.config.embedding_model
            or os.getenv("RAG_EMBEDDING_MODEL")
            or "gemini/text-embedding-004"
        ).strip()
        payload: Dict[str, Any] = {
            "model": embedding_model,
            "input": list(texts or []),
            "timeout": timeout_s or self.config.embedding_timeout_s,
        }
        api_key = self._embedding_api_key(embedding_model)
        if api_key:
            payload["api_key"] = api_key
        if dimensions and _supports_embedding_dimensions(embedding_model):
            payload["dimensions"] = int(dimensions)

        self._reserve_provider_call(metadata=metadata)
        raw = self._client.embedding(**payload)
        latency_ms = int((time.perf_counter() - started) * 1000)
        vectors = _extract_embedding_vectors(raw)
        return {
            "vectors": vectors,
            "raw": _jsonable(raw),
            "provider": _provider_for_model(embedding_model),
            "model": embedding_model,
            "latency_ms": latency_ms,
            "request_debug": {
                "model": embedding_model,
                "input_count": len(list(texts or [])),
                "dimensions": dimensions if _supports_embedding_dimensions(embedding_model) else None,
                "metadata": dict(metadata or {}),
            },
        }

    async def acomplete(
        self,
        *,
        messages: Sequence[Dict[str, Any]],
        tools: Optional[Sequence[Dict[str, Any]]] = None,
        tool_choice: Any = "auto",
        metadata: Optional[Dict[str, Any]] = None,
        response_format: Optional[Any] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Run one guarded completion and retain safe usage/cache diagnostics."""

        started = time.perf_counter()
        base_messages = deepcopy(list(messages))
        request_messages = deepcopy(base_messages)
        request_tools = _sanitize_tools(tools) if tools and self.config.sanitize_tools else deepcopy(list(tools or []))
        cache_policy = _context_cache_policy(self.config, has_tools=bool(request_tools))
        request_cache = _cache_disabled_debug(cache_policy, ttl=self.config.context_cache_ttl)
        if cache_policy.should_mark_cache:
            request_messages, request_cache = _mark_gemini_context_cache(
                request_messages,
                model=self.config.model,
                client=self._client,
                ttl=self.config.context_cache_ttl,
            )
        request_cache.update(
            _cache_policy_debug(cache_policy, request_tools, cache_enabled=bool(request_cache.get("enabled")))
        )

        def _build_payload(messages_for_request: Sequence[Dict[str, Any]], cache_info: Dict[str, Any]) -> Dict[str, Any]:
            output_tokens = int(max_tokens or self.config.max_tokens)
            request_reasoning_effort = _normalize_reasoning_effort(
                reasoning_effort if reasoning_effort is not None else self.config.reasoning_effort
            )
            payload: Dict[str, Any] = {
                "model": self.config.model,
                "messages": list(messages_for_request),
                "temperature": (
                    float(temperature)
                    if temperature is not None
                    else self.config.temperature
                ),
                "max_tokens": output_tokens,
                "timeout": self.config.timeout_s,
            }
            if request_reasoning_effort:
                payload["reasoning_effort"] = request_reasoning_effort
            api_key = self._api_key()
            if api_key:
                payload["api_key"] = api_key
            if metadata:
                payload["metadata"] = dict(metadata)
            if request_tools:
                payload["tools"] = request_tools
                if not (
                    cache_info.get("enabled")
                    and cache_policy.omit_tool_choice_for_cached_tools
                    and request_tools
                    and _is_auto_tool_choice(tool_choice)
                ):
                    payload["tool_choice"] = tool_choice
            if response_format is not None:
                payload["response_format"] = response_format
            if _is_gemini_model(self.config.model):
                payload["max_output_tokens"] = output_tokens
            return payload

        payload = _build_payload(request_messages, request_cache)
        cache_guard_events: List[Dict[str, Any]] = []
        successful_messages = request_messages
        successful_cache = request_cache
        transport_retry_events: List[Dict[str, Any]] = []
        try:
            raw, transport_retry_events = await self._acompletion_with_transport_retry(
                payload,
                metadata=metadata,
            )
        except Exception as exc:
            if not _should_retry_without_context_cache(
                exc,
                cache_policy=cache_policy,
                request_cache=request_cache,
                has_tools=bool(request_tools),
            ):
                raise
            cache_guard_events.append(
                {
                    "event": "GEMINI_CONTEXT_CACHE_RETRY_WITHOUT_CACHE",
                    "reason": "cached_content_generate_content_settings_conflict",
                    "provider_mode": cache_policy.provider_mode,
                    "error": _compact_error_message(exc),
                }
            )
            successful_messages = deepcopy(base_messages)
            successful_cache = _retry_without_cache_debug(
                cache_policy,
                previous_cache=request_cache,
                ttl=self.config.context_cache_ttl,
                error=exc,
            )
            successful_cache.update(_cache_policy_debug(cache_policy, request_tools, cache_enabled=False))
            retry_payload = _build_payload(successful_messages, successful_cache)
            raw, retry_events = await self._acompletion_with_transport_retry(
                retry_payload,
                metadata=metadata,
            )
            transport_retry_events.extend(retry_events)
        latency_ms = int((time.perf_counter() - started) * 1000)
        normalized = _normalize_litellm_response(raw, model=self.config.model, latency_ms=latency_ms)
        normalized["request_cache"] = successful_cache
        normalized["cache_guard_events"] = cache_guard_events
        normalized["transport_retry_events"] = transport_retry_events
        normalized["request_debug"] = {
            "messages": successful_messages,
            "tool_schema_hash": _stable_hash(request_tools),
            "tool_schema_count": len(request_tools),
            "response_format": _response_format_debug(response_format),
            "reasoning_effort": _normalize_reasoning_effort(
                reasoning_effort if reasoning_effort is not None else self.config.reasoning_effort
            ),
            "transport_attempt_count": 1 + len(transport_retry_events),
        }
        return normalized

    async def _acompletion_with_transport_retry(
        self,
        payload: Dict[str, Any],
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[Any, List[Dict[str, Any]]]:
        """Retry only transient provider/transport failures for one logical call."""

        retry_events: List[Dict[str, Any]] = []
        max_retries = max(0, int(self.config.max_transport_retries or 0))
        for attempt_index in range(max_retries + 1):
            try:
                self._reserve_provider_call(metadata=metadata)
                raw = await asyncio.wait_for(
                    self._client.acompletion(**payload),
                    timeout=self.config.timeout_s + 5,
                )
                return raw, retry_events
            except Exception as exc:
                if attempt_index >= max_retries or not _is_retryable_transport_error(exc):
                    raise
                delay_s = min(
                    5.0,
                    max(0.0, float(self.config.transport_retry_backoff_s or 0.0)) * (2**attempt_index),
                )
                retry_events.append(
                    {
                        "event": "LLM_TRANSIENT_TRANSPORT_RETRY",
                        "attempt": attempt_index + 2,
                        "delay_s": delay_s,
                        "error_type": type(exc).__name__,
                        "error": _compact_error_message(exc),
                    }
                )
                if delay_s:
                    await asyncio.sleep(delay_s)
        raise RuntimeError("llm_transport_retry_loop_exhausted")

    def _reserve_provider_call(self, *, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Consume a shared request slot immediately before provider I/O."""

        if self.config.provider_call_guard is not None:
            self.config.provider_call_guard.reserve(metadata=metadata)

    def _api_key(self) -> Optional[str]:
        return os.environ.get(self.config.api_key_env) or self._env_from_file.get(self.config.api_key_env)

    def _embedding_api_key(self, model: str) -> Optional[str]:
        env_name = self.config.embedding_api_key_env or _api_key_env_for_model(model)
        return os.environ.get(env_name) or self._env_from_file.get(env_name)

    @staticmethod
    def _load_litellm() -> Any:
        import litellm  # type: ignore

        return litellm


def _load_env_file() -> Dict[str, str]:
    if load_dotenv is not None:
        load_dotenv(ENV_PATH, override=False)
    if dotenv_values is None or not ENV_PATH.exists():
        return {}
    raw = dotenv_values(ENV_PATH)
    return {str(key): str(value) for key, value in raw.items() if value is not None}


def _context_cache_policy(config: RuntimeV7LLMGatewayConfig, *, has_tools: bool) -> _ContextCachePolicy:
    """Return the provider-specific cache behavior for the current request."""

    provider_mode = _context_cache_provider_mode(config.model)
    if not config.enable_context_cache:
        return _ContextCachePolicy(
            provider_mode=provider_mode,
            should_mark_cache=False,
            omit_tool_choice_for_cached_tools=False,
            retry_without_cache_on_settings_conflict=False,
            strategy=GEMINI_CONTEXT_CACHE_STRATEGY,
            skipped_reason="context_cache_disabled",
        )
    if not _is_gemini_model(config.model):
        return _ContextCachePolicy(
            provider_mode=provider_mode,
            should_mark_cache=False,
            omit_tool_choice_for_cached_tools=False,
            retry_without_cache_on_settings_conflict=False,
            strategy=GEMINI_CONTEXT_CACHE_STRATEGY,
            skipped_reason="context_cache_supported_for_gemini_only",
        )
    return _ContextCachePolicy(
        provider_mode=provider_mode,
        should_mark_cache=True,
        omit_tool_choice_for_cached_tools=bool(has_tools and provider_mode == "google_ai_studio_gemini"),
        retry_without_cache_on_settings_conflict=True,
        strategy=GEMINI_CONTEXT_CACHE_STRATEGY,
    )


def _context_cache_provider_mode(model: str) -> str:
    lowered = str(model or "").lower()
    if lowered.startswith("gemini/"):
        return "google_ai_studio_gemini"
    if lowered.startswith("vertex_ai/") or lowered.startswith("vertex_ai_beta/"):
        return "vertex_ai_gemini"
    if lowered.startswith("gemini"):
        return "gemini"
    return "unsupported"


def _is_auto_tool_choice(tool_choice: Any) -> bool:
    if tool_choice is None:
        return True
    if isinstance(tool_choice, str):
        return tool_choice.strip().lower() in {"", "auto"}
    return False


def _cache_disabled_debug(policy: _ContextCachePolicy, *, ttl: Optional[str]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "enabled": False,
        "strategy": policy.strategy,
        "ttl": ttl,
        "marked_message_indexes": [],
        "provider_mode": policy.provider_mode,
        "omit_tool_choice_for_cached_tools": policy.omit_tool_choice_for_cached_tools,
        "retry_without_cache_on_settings_conflict": policy.retry_without_cache_on_settings_conflict,
    }
    if policy.skipped_reason:
        payload["skipped_reason"] = policy.skipped_reason
    return payload


def _cache_policy_debug(
    policy: _ContextCachePolicy,
    tools: Sequence[Dict[str, Any]],
    *,
    cache_enabled: bool,
) -> Dict[str, Any]:
    return {
        "provider_mode": policy.provider_mode,
        "omit_tool_choice_for_cached_tools": policy.omit_tool_choice_for_cached_tools,
        "retry_without_cache_on_settings_conflict": policy.retry_without_cache_on_settings_conflict,
        "tool_schema_count": len(tools or []),
        "tool_schema_hash": _stable_hash(tools),
        "tool_names": _tool_names(tools),
        "tool_schemas_in_cache_scope": bool(tools and cache_enabled),
    }


def _retry_without_cache_debug(
    policy: _ContextCachePolicy,
    *,
    previous_cache: Dict[str, Any],
    ttl: Optional[str],
    error: Exception,
) -> Dict[str, Any]:
    return {
        "enabled": False,
        "strategy": policy.strategy,
        "ttl": ttl,
        "marked_message_indexes": [],
        "provider_mode": policy.provider_mode,
        "skipped_reason": "retry_without_cache_after_gemini_cached_content_settings_conflict",
        "retry_of_cache_enabled_request": True,
        "retry_reason": "cached_content_generate_content_settings_conflict",
        "previous_cache_enabled": bool(previous_cache.get("enabled")),
        "previous_tool_schema_hash": previous_cache.get("tool_schema_hash"),
        "error": _compact_error_message(error),
    }


def _should_retry_without_context_cache(
    error: Exception,
    *,
    cache_policy: _ContextCachePolicy,
    request_cache: Dict[str, Any],
    has_tools: bool,
) -> bool:
    if not request_cache.get("enabled"):
        return False
    if not cache_policy.retry_without_cache_on_settings_conflict:
        return False
    return _is_gemini_cached_content_settings_conflict(error)


def _is_gemini_cached_content_settings_conflict(error: Exception) -> bool:
    message = str(error or "")
    return (
        "CachedContent can not be used with GenerateContent request setting" in message
        or ("cachedContent" in message and "tool_config" in message)
        or ("cachedContent" in message and "system_instruction" in message)
    )


def _is_retryable_transport_error(exc: Exception) -> bool:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError)):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
    try:
        if int(status_code) in {408, 429, 500, 502, 503, 504}:
            return True
    except (TypeError, ValueError):
        pass
    error_type = type(exc).__name__.casefold()
    if any(
        marker in error_type
        for marker in ("ratelimit", "serviceunavailable", "apiconnection", "timeout", "internalserver")
    ):
        return True
    message = " ".join(str(exc or "").casefold().split())
    return any(
        marker in message
        for marker in (
            "status code: 408",
            "status code: 429",
            "status code: 500",
            "status code: 502",
            "status code: 503",
            "status code: 504",
            '"code": 503',
            "status': 503",
            '"status": "unavailable"',
            "temporarily unavailable",
            "connection reset",
            "connection aborted",
            "rate limit",
        )
    )


def _compact_error_message(error: Exception, *, limit: int = 500) -> str:
    message = " ".join(str(error or "").split())
    if len(message) <= limit:
        return message
    return f"{message[:limit]}..."


def _normalize_litellm_response(raw: Any, *, model: str, latency_ms: int) -> Dict[str, Any]:
    raw_dict = _jsonable(raw)
    choices = raw_dict.get("choices") if isinstance(raw_dict, dict) else []
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    content = _extract_text(message.get("content"))
    tool_calls = _normalize_tool_calls(message.get("tool_calls") or [])
    usage = raw_dict.get("usage") if isinstance(raw_dict, dict) else {}
    cache_usage = _extract_cache_usage(usage if isinstance(usage, dict) else {}, raw_dict if isinstance(raw_dict, dict) else {})
    return {
        "content": content,
        "tool_calls": tool_calls,
        "usage": usage or {},
        "cache_usage": cache_usage,
        "latency_ms": latency_ms,
        "finish_reason": choice.get("finish_reason"),
        "model": model,
        "provider": "gemini" if _is_gemini_model(model) else "unknown",
        "raw_message": message,
        "raw_choice": choice,
    }


def _mark_gemini_context_cache(
    messages: Sequence[Dict[str, Any]],
    *,
    model: str,
    client: Optional[Any] = None,
    ttl: Optional[str],
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Mark the stable system prompt for LiteLLM's Gemini context-cache transform."""

    marked = deepcopy(list(messages))
    min_tokens = _gemini_context_cache_min_tokens(model)
    min_cacheable_text_chars = min_tokens * GEMINI_CONTEXT_CACHE_APPROX_CHARS_PER_TOKEN
    cache_control: Dict[str, Any] = {"type": "ephemeral"}
    if ttl:
        cache_control["ttl"] = ttl
    for index, message in enumerate(marked):
        if message.get("role") != "system":
            continue
        content = message.get("content")
        if isinstance(content, str):
            cacheable_tokens = _cacheable_text_token_count(model, content, client=client)
            if cacheable_tokens is not None and cacheable_tokens < min_tokens:
                return marked, {
                    "enabled": False,
                    "strategy": GEMINI_CONTEXT_CACHE_STRATEGY,
                    "ttl": ttl,
                    "marked_message_indexes": [],
                    "skipped_reason": "cacheable_system_text_below_gemini_minimum",
                    "cacheable_text_chars": len(content),
                    "cacheable_tokens": cacheable_tokens,
                    "min_cacheable_tokens": min_tokens,
                    "token_count_source": "litellm_token_counter",
                }
            if cacheable_tokens is None and len(content) < min_cacheable_text_chars:
                return marked, {
                    "enabled": False,
                    "strategy": GEMINI_CONTEXT_CACHE_STRATEGY,
                    "ttl": ttl,
                    "marked_message_indexes": [],
                    "skipped_reason": "cacheable_system_text_below_gemini_minimum",
                    "cacheable_text_chars": len(content),
                    "min_cacheable_text_chars": min_cacheable_text_chars,
                    "min_cacheable_tokens": min_tokens,
                    "chars_per_token_estimate": GEMINI_CONTEXT_CACHE_APPROX_CHARS_PER_TOKEN,
                    "token_count_source": "char_estimate_fallback",
                }
            message["content"] = [{"type": "text", "text": content, "cache_control": cache_control}]
            return marked, {
                "enabled": True,
                "strategy": GEMINI_CONTEXT_CACHE_STRATEGY,
                "ttl": ttl,
                "marked_message_indexes": [index],
                "min_cacheable_tokens": min_tokens,
                "cacheable_tokens": cacheable_tokens,
                "token_count_source": "litellm_token_counter" if cacheable_tokens is not None else "char_estimate_fallback",
            }
        if isinstance(content, list):
            marked_indexes: List[int] = []
            cacheable_chars = 0
            cacheable_text_parts: List[str] = []
            for part_index, part in enumerate(content):
                if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                    text_part = str(part.get("text") or "")
                    cacheable_chars += len(text_part)
                    cacheable_text_parts.append(text_part)
            cacheable_text = "\n\n".join(cacheable_text_parts)
            cacheable_tokens = _cacheable_text_token_count(model, cacheable_text, client=client)
            if cacheable_tokens is not None and cacheable_tokens < min_tokens:
                return marked, {
                    "enabled": False,
                    "strategy": GEMINI_CONTEXT_CACHE_STRATEGY,
                    "ttl": ttl,
                    "marked_message_indexes": [],
                    "skipped_reason": "cacheable_system_text_below_gemini_minimum",
                    "cacheable_text_chars": cacheable_chars,
                    "cacheable_tokens": cacheable_tokens,
                    "min_cacheable_tokens": min_tokens,
                    "token_count_source": "litellm_token_counter",
                }
            if cacheable_tokens is None and cacheable_chars < min_cacheable_text_chars:
                return marked, {
                    "enabled": False,
                    "strategy": GEMINI_CONTEXT_CACHE_STRATEGY,
                    "ttl": ttl,
                    "marked_message_indexes": [],
                    "skipped_reason": "cacheable_system_text_below_gemini_minimum",
                    "cacheable_text_chars": cacheable_chars,
                    "min_cacheable_text_chars": min_cacheable_text_chars,
                    "min_cacheable_tokens": min_tokens,
                    "chars_per_token_estimate": GEMINI_CONTEXT_CACHE_APPROX_CHARS_PER_TOKEN,
                    "token_count_source": "char_estimate_fallback",
                }
            for part_index, part in enumerate(content):
                if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                    part["cache_control"] = cache_control
                    marked_indexes.append(part_index)
            if marked_indexes:
                return marked, {
                    "enabled": True,
                    "strategy": GEMINI_CONTEXT_CACHE_STRATEGY,
                    "ttl": ttl,
                    "marked_message_indexes": [index],
                    "marked_part_indexes": marked_indexes,
                    "min_cacheable_tokens": min_tokens,
                    "cacheable_tokens": cacheable_tokens,
                    "token_count_source": "litellm_token_counter" if cacheable_tokens is not None else "char_estimate_fallback",
                }
    return marked, {
        "enabled": True,
        "strategy": GEMINI_CONTEXT_CACHE_STRATEGY,
        "ttl": ttl,
        "marked_message_indexes": [],
        "min_cacheable_tokens": min_tokens,
        "warning": "no cacheable system text message found",
    }


def _gemini_context_cache_min_tokens(model: str) -> int:
    """Return the conservative minimum token threshold for Gemini cache marking."""

    override = os.getenv("RUNTIME_V7_GEMINI_CONTEXT_CACHE_MIN_TOKENS", "").strip()
    if override:
        try:
            parsed = int(override)
            if parsed > 0:
                return parsed
        except ValueError:
            pass
    return GEMINI_CONTEXT_CACHE_DEFAULT_MIN_TOKENS


def _cacheable_text_token_count(model: str, text: str, *, client: Optional[Any] = None) -> Optional[int]:
    """Return LiteLLM's token count when available; callers fall back to chars."""

    if not str(text or "").strip():
        return 0
    token_counter = getattr(client, "token_counter", None)
    if callable(token_counter):
        try:
            return int(token_counter(model=model, messages=[{"role": "system", "content": text}]))
        except Exception:
            return None
    return None


def _extract_cache_usage(usage: Dict[str, Any], raw_dict: Dict[str, Any]) -> Dict[str, Any]:
    prompt_details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    completion_details = (
        usage.get("completion_tokens_details") if isinstance(usage.get("completion_tokens_details"), dict) else {}
    )
    raw_usage_metadata = raw_dict.get("usageMetadata") if isinstance(raw_dict.get("usageMetadata"), dict) else {}
    cache_read = (
        usage.get("cache_read_input_tokens")
        or usage.get("cached_tokens")
        or prompt_details.get("cached_tokens")
        or raw_usage_metadata.get("cachedContentTokenCount")
    )
    return {
        "cache_read_input_tokens": _int_or_none(cache_read),
        "prompt_cached_tokens": _int_or_none(prompt_details.get("cached_tokens")),
        "prompt_text_tokens": _int_or_none(prompt_details.get("text_tokens")),
        "reasoning_tokens": _int_or_none(usage.get("reasoning_tokens") or completion_details.get("reasoning_tokens")),
        "raw_usage_metadata_cached_content_tokens": _int_or_none(raw_usage_metadata.get("cachedContentTokenCount")),
    }


def _normalize_tool_calls(raw_calls: Sequence[Any]) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    for index, call in enumerate(raw_calls or []):
        row = _jsonable(call)
        function = row.get("function") if isinstance(row.get("function"), dict) else {}
        calls.append(
            {
                "id": row.get("id") or f"call_{index + 1}",
                "type": row.get("type") or "function",
                "function": {
                    "name": row.get("name") or function.get("name"),
                    "arguments": function.get("arguments") if function.get("arguments") is not None else row.get("arguments"),
                },
            }
        )
    return calls


def _sanitize_tools(tools: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sanitized = deepcopy(list(tools or []))
    for tool in sanitized:
        function = tool.get("function") if isinstance(tool, dict) else None
        parameters = function.get("parameters") if isinstance(function, dict) else None
        if isinstance(parameters, dict):
            _sanitize_schema(parameters)
    return sanitized


def _sanitize_schema(schema: Dict[str, Any]) -> None:
    schema.pop("additionalProperties", None)
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        non_null = [value for value in schema_type if value != "null"]
        if len(non_null) == 1:
            schema["type"] = non_null[0]
        elif non_null:
            schema["type"] = non_null[0]
        else:
            schema.pop("type", None)
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for child in properties.values():
            if isinstance(child, dict):
                _sanitize_schema(child)
    items = schema.get("items")
    if isinstance(items, dict):
        _sanitize_schema(items)


def _extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            if isinstance(item, dict):
                if item.get("type") in {"text", "output_text"}:
                    parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return str(value)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(child) for child in value]
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "dict"):
        try:
            return _jsonable(value.dict())
        except Exception:
            pass
    return str(value)


def _is_gemini_model(model: str) -> bool:
    return str(model or "").lower().startswith("gemini")


def _provider_for_model(model: str) -> str:
    lowered = str(model or "").lower()
    if lowered.startswith("gemini"):
        return "gemini"
    if lowered.startswith("text-embedding") or lowered.startswith("openai/"):
        return "openai"
    return "litellm"


def _api_key_env_for_model(model: str) -> str:
    return "GEMINI_API_KEY" if _provider_for_model(model) == "gemini" else "OPENAI_API_KEY"


def _supports_embedding_dimensions(model: str) -> bool:
    lowered = str(model or "").lower()
    return lowered.startswith("text-embedding") or lowered.startswith("openai/text-embedding")


def _extract_embedding_vectors(raw: Any) -> List[List[float]]:
    raw_dict = _jsonable(raw)
    data = raw_dict.get("data") if isinstance(raw_dict, dict) else None
    vectors: List[List[float]] = []
    for item in data or []:
        embedding = item.get("embedding") if isinstance(item, dict) else None
        if embedding is not None:
            vectors.append([float(value) for value in list(embedding)])
    return vectors


def _stable_hash(value: Any) -> str:
    payload = _jsonable(value)
    text = str(payload)
    try:
        import json

        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        pass
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _tool_names(tools: Sequence[Dict[str, Any]]) -> List[str]:
    names: List[str] = []
    for tool in tools or []:
        function = tool.get("function") if isinstance(tool, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if name:
            names.append(str(name))
    return names


def _response_format_debug(response_format: Optional[Any]) -> Optional[str]:
    """Return a compact debug label without serializing schema internals."""

    if response_format is None:
        return None
    if isinstance(response_format, dict):
        return str(response_format.get("type") or "dict")
    return str(getattr(response_format, "__name__", response_format.__class__.__name__))


def _normalize_reasoning_effort(value: Optional[str]) -> Optional[str]:
    """Return a LiteLLM reasoning_effort value or None for provider default."""

    normalized = str(value or "").strip().lower()
    if not normalized or normalized in {"default", "provider_default", "provider-default", "auto"}:
        return None
    allowed = {"none", "disable", "minimal", "low", "medium", "high"}
    if normalized not in allowed:
        return None
    return normalized


def _int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None
