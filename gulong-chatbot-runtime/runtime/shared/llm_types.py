"""Small LLM config and embedding request types shared by Runtime V7 helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ModelPolicy:
    """Provider/model selection policy loaded from BU config."""

    main: List[Tuple[str, str]] = field(default_factory=list)
    main_tool_loop: List[Tuple[str, str]] = field(default_factory=list)
    main_finalize: List[Tuple[str, str]] = field(default_factory=list)
    slot_extract: List[Tuple[str, str]] = field(default_factory=list)
    tool_llm: List[Tuple[str, str]] = field(default_factory=list)
    env_keys: Dict[str, str] = field(default_factory=dict)


@dataclass
class LLMGatewayConfig:
    """Config shape retained for config-loader compatibility."""

    primary_provider: str = "openai"
    fallback_provider: str = "gemini"
    primary_model: str = "gpt-4.1"
    fallback_model: str = "gemini-2.5-pro"
    main_model: Optional[str] = None
    slot_model: Optional[str] = None
    tool_llm_model: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 1500
    max_retries: int = 1
    timeout_s: float = 12.0
    backoff_base_s: float = 0.4
    backoff_jitter_s: float = 0.2
    hard_fail_closed: bool = False
    log_request_bodies: bool = False
    model_policy: Optional[ModelPolicy] = None


@dataclass
class LLMEmbeddingRequest:
    """Embedding request wrapper used by the local RAG index helper."""

    request_id: str
    texts: List[str]
    model: str
    provider: Optional[str] = None
    timeout_s: float = 20.0
    metadata: Optional[Dict[str, Any]] = None
