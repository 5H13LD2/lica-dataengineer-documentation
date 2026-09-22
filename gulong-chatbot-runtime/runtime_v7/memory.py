"""Active working memory helpers for the Runtime V7 product/service slice.

This module is intentionally limited to conversation memory. Missing-info
signals, slot candidates, and action-readiness checks belong to state/context
modules that can be injected next to memory in the prompt packet.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Protocol, Sequence

from runtime_v7.llm_gateway import RuntimeV7ProviderCallLimitExceeded
from runtime_v7.state_signal_schema import (
    DURABLE_SIGNAL_RELATIONS,
    signal_authority_source,
    signal_has_durable_authority,
    signal_is_advisory_context,
)


MANILA_TZ = timezone(timedelta(hours=8))

ACTIVE_WORKING_MEMORY_GENERATOR_SYSTEM_PROMPT = """You update Active Working Memory for a commercial tire-shopping chatbot.

Return exact JSON only:
{"active_working_memory":"..."}

Rules:
- Write one short decision-oriented narrative, 100-300 words.
- Preserve current intent, active goal, important nuance, and confirmed vs unconfirmed details.
- When tools ran, decide whether the prior active goal remains unresolved, was
  satisfied, was deferred, or was replaced by the latest customer request. A
  tool call by itself does not replace the customer's active goal.
- Keep older details only if still relevant to the current shopping task.
- Do not write a transcript summary.
- Do not invent facts.
- Memory is not the source of truth for prices, promos, inventory, DOT, warranty, URLs, ETAs, payment instructions, or order submission.
- If a payment method is mentioned, preserve it as a preference only until validated by order/payment tools.
- Treat advisory background signals as normalized hints, not mandatory truth. If they conflict with customer wording, preserve uncertainty instead of forcing the signal.
- For customer location, prefer a resolved Background Signal display label/value over raw shorthand or overlapping place wording; preserve raw ambiguity only if unresolved or genuinely conflicting.
- If product observations are present, keep the observation_ref and presentation_ref so later turns can retrieve trusted facts.
- Copy observation, presentation, order, payment, and evidence refs exactly as
  supplied. Never shorten, reconstruct, or invent a ref.
- If external image, screenshot, PDF, or human-agent evidence is present, keep evidence refs and validation status. Human-agent messages are trusted continuity context, but exact product/order/payment/schedule action still needs tool or runtime-state validation.
- Keep memory descriptive, not directive. Do not prescribe the chatbot's next step or say what the assistant should do next.
- Preserve customer-stated or human-agent-stated next steps only as quoted/stated context, not as runtime instructions.
- Mention unresolved details only when they are explicitly part of the current customer-stated task; do not append order-readiness checklists.
- Do not use markdown headings or bullets inside active_working_memory.
"""

_MAX_PERSISTED_MEMORY_TEXT_CHARS = 6000
_MAX_PERSISTED_METADATA_STRING_CHARS = 600
_MAX_PERSISTED_METADATA_LIST_ITEMS = 8
_MAX_PERSISTED_METADATA_DICT_KEYS = 16
_PERSISTED_MEMORY_METADATA_KEYS = {
    "generator",
    "model",
    "usage",
    "cache_usage",
    "request_cache",
    "latency_ms",
    "finish_reason",
    "fallback_used",
    "fallback_reason",
    "model_attempts",
    "model_retry_errors",
    "model_skipped_reason",
    "tool_result_count",
    "recent_turn_count",
    "background_signal_count",
    "external_evidence_ref_count",
    "model_output_chars",
    "fallback_candidate_chars",
    "error_type",
    "error_preview",
}
_PROMPT_METADATA_KEYS = {
    "prompt_preview",
    "generator_system_prompt",
    "generator_user_prompt",
    "model_output_content",
    "model_response",
    "error",
}


def manila_now_text() -> str:
    """Return the canonical Runtime V7 Manila timestamp text."""

    return datetime.now(tz=MANILA_TZ).strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class ActiveWorkingMemory:
    """Short, always-loaded narrative for the current conversation."""

    text: str = ""
    version: int = 0
    updated_at: str = ""
    source: str = "empty"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_prompt_text(self) -> str:
        return self.text.strip() or "(none)"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": _truncate_string(self.text, _MAX_PERSISTED_MEMORY_TEXT_CHARS),
            "version": self.version,
            "updated_at": self.updated_at,
            "source": self.source,
            "metadata": _clean_memory_metadata(self.metadata),
        }

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        version: int = 1,
        source: str = "seed",
        updated_at: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "ActiveWorkingMemory":
        cleaned = _clean_text(text)
        return cls(
            text=cleaned,
            version=version if cleaned else 0,
            updated_at=updated_at or (manila_now_text() if cleaned else ""),
            source=source if cleaned else "empty",
            metadata=_clean_memory_metadata(metadata),
        )

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "ActiveWorkingMemory":
        if not isinstance(payload, dict):
            return cls()
        return cls(
            text=_truncate_string(str(payload.get("text") or "").strip(), _MAX_PERSISTED_MEMORY_TEXT_CHARS),
            version=_int_or_default(payload.get("version"), 0),
            updated_at=str(payload.get("updated_at") or "").strip(),
            source=str(payload.get("source") or "loaded").strip(),
            metadata=_clean_memory_metadata(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}),
        )


def compact_active_working_memory_for_persistence(memory: Any) -> Dict[str, Any]:
    """Return the Firestore-safe active-memory payload.

    Active memory is hot-path cross-turn state. Prompt packets, raw model
    outputs, and exception strings are runtime inputs/debug artifacts, not
    durable state, and must not be allowed to recurse into future prompts.
    """

    if isinstance(memory, ActiveWorkingMemory):
        loaded = memory
    elif isinstance(memory, dict):
        loaded = ActiveWorkingMemory.from_dict(memory)
    else:
        loaded = ActiveWorkingMemory()
    return loaded.to_dict()


def active_working_memory_evidence_payload(memory: ActiveWorkingMemory) -> Dict[str, Any]:
    """Return the prompt-safe subset of memory for the generator evidence."""

    return {
        "text": _truncate_string(str(memory.text or "").strip(), _MAX_PERSISTED_MEMORY_TEXT_CHARS),
        "version": _int_or_default(memory.version, 0),
        "updated_at": str(memory.updated_at or "").strip(),
        "source": str(memory.source or "loaded").strip(),
    }


class ActiveWorkingMemoryStore(Protocol):
    """Persistence boundary for active working memory."""

    def load(self, session_id: str) -> ActiveWorkingMemory:
        ...

    def save(self, session_id: str, memory: ActiveWorkingMemory) -> None:
        ...


class InMemoryActiveWorkingMemoryStore:
    """Local harness store; production can replace this with Firestore."""

    def __init__(self) -> None:
        self._items: Dict[str, ActiveWorkingMemory] = {}

    def load(self, session_id: str) -> ActiveWorkingMemory:
        return ActiveWorkingMemory.from_dict(self._items.get(session_id, ActiveWorkingMemory()).to_dict())

    def save(self, session_id: str, memory: ActiveWorkingMemory) -> None:
        self._items[str(session_id)] = ActiveWorkingMemory.from_dict(memory.to_dict())


class ActiveWorkingMemoryGenerator(Protocol):
    """Compactor boundary used after a turn has completed."""

    def update(
        self,
        *,
        current_memory: ActiveWorkingMemory,
        latest_user_message: str,
        assistant_response: str,
        tool_results: Sequence[Dict[str, Any]],
        recent_turns: Sequence[Dict[str, str]],
        background_signals: Sequence[Dict[str, Any]] = (),
        external_evidence_refs: Sequence[Dict[str, Any]] = (),
    ) -> ActiveWorkingMemory:
        ...


class ActiveWorkingMemoryModelClient(Protocol):
    """Small model-client boundary for model-backed memory compaction."""

    def generate_memory(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ...


class RuntimeV7ActiveWorkingMemoryModelClient:
    """LiteLLM-backed memory compactor client using the Runtime V7 gateway."""

    def __init__(
        self,
        *,
        model: str = "gemini/gemini-2.5-flash-lite",
        temperature: float = 0.1,
        max_tokens: int = 500,
        timeout_s: float = 20.0,
        enable_context_cache: bool = False,
        context_cache_ttl: str = "3600s",
        metadata: Optional[Dict[str, Any]] = None,
        provider_call_guard: Optional[Any] = None,
    ) -> None:
        from runtime_v7.llm_gateway import RuntimeV7LLMGateway, RuntimeV7LLMGatewayConfig

        self.model = model
        self.metadata = dict(metadata or {})
        self.gateway = RuntimeV7LLMGateway(
            config=RuntimeV7LLMGatewayConfig(
                model=model,
                api_key_env="GEMINI_API_KEY",
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_s=timeout_s,
                enable_context_cache=enable_context_cache,
                context_cache_ttl=context_cache_ttl,
                provider_call_guard=provider_call_guard,
            )
        )

    def generate_memory(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        merged_metadata = dict(self.metadata)
        merged_metadata.update(metadata or {})
        return self.gateway.complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tools=[],
            metadata=merged_metadata,
        )


class EvidenceBoundActiveWorkingMemoryGenerator:
    """Compact durable typed state and trusted refs without re-parsing prose."""

    def __init__(self, *, max_words: int = 260) -> None:
        self.max_words = max(80, int(max_words or 260))

    def update(
        self,
        *,
        current_memory: ActiveWorkingMemory,
        latest_user_message: str,
        assistant_response: str,
        tool_results: Sequence[Dict[str, Any]],
        recent_turns: Sequence[Dict[str, str]],
        background_signals: Sequence[Dict[str, Any]] = (),
        external_evidence_refs: Sequence[Dict[str, Any]] = (),
    ) -> ActiveWorkingMemory:
        """Build continuity only from typed signals and trusted tool refs."""

        # Raw messages remain available in recent conversation context. This
        # fallback deliberately does not reinterpret them into durable memory.
        del latest_user_message, assistant_response, recent_turns
        typed_signals = _compact_background_signals(background_signals)
        signal_map = _signal_value_map(typed_signals)
        continuity_signals = _compact_context_only_signals(background_signals)
        continuity_map = _signal_value_map(continuity_signals)
        latest_search = _latest_product_search(tool_results)
        latest_fitment = _latest_fitment_observation(tool_results)
        latest_service = _latest_service_observation(tool_results)
        latest_order_state = _latest_order_state(tool_results)
        external_refs = _compact_external_evidence_refs(external_evidence_refs)

        paragraphs: List[str] = []
        shopping_bits: List[str] = []
        sizes = _split_signal_values(signal_map.get("tire_size"))
        brands = (
            _split_signal_values(signal_map.get("required_brands"))
            or _split_signal_values(signal_map.get("preferred_brands"))
        )
        vehicle = signal_map.get("car_make_model")
        quantity = signal_map.get("quantity")
        category = signal_map.get("tire_category_preference")
        budget = signal_map.get("budget")
        if vehicle:
            shopping_bits.append(f"vehicle {vehicle}")
        if sizes:
            size_text = ", ".join(sizes)
            if _signal_status_contains(typed_signals, "tire_size", "unconfirmed"):
                size_text += " (unconfirmed)"
            shopping_bits.append(f"tire size {size_text}")
        if quantity:
            shopping_bits.append(f"quantity {quantity} tires")
        if brands:
            shopping_bits.append(f"brand preference {', '.join(brands)}")
        if category:
            shopping_bits.append(f"category preference {category}")
        if budget:
            shopping_bits.append(f"budget {budget}")
        if shopping_bits:
            paragraphs.append("Typed customer context: " + "; ".join(shopping_bits) + ".")

        continuity_bits: List[str] = []
        for key, label in (
            ("tire_size", "tire size"),
            ("preferred_brands", "brand preference"),
            ("required_brands", "requested brand"),
            ("car_make_model", "vehicle"),
            ("location", "location"),
            ("quantity", "quantity"),
            ("tire_category_preference", "category preference"),
        ):
            value = continuity_map.get(key)
            if value:
                continuity_bits.append(f"{label} {value}")
        if continuity_bits:
            paragraphs.append(
                "Human-agent continuity context (not action or commercial authority): "
                + "; ".join(continuity_bits)
                + "."
            )

        service_bits: List[str] = []
        location = signal_map.get("location")
        service_type = signal_map.get("service_type")
        schedule = signal_map.get("chosen_schedule_slot")
        if location:
            service_bits.append(f"location {location}")
        if service_type:
            service_bits.append(f"service preference {service_type}")
        if schedule:
            service_bits.append(f"schedule preference {schedule}")
        if service_bits:
            paragraphs.append("Typed fulfillment context: " + "; ".join(service_bits) + ".")

        payment_preference = _payment_preference_from_signals(signal_map)
        if payment_preference:
            paragraphs.append(
                "Typed payment preference is mentioned but remains subject to checkout validation: "
                + payment_preference
                + "."
            )

        if latest_search:
            obs = latest_search.get("observation_ref")
            pres = latest_search.get("presentation_ref")
            card_count = latest_search.get("card_count")
            line = "Latest product search presented"
            line += f" {card_count} option(s)" if card_count else " product options"
            refs = " / ".join(ref for ref in [obs, pres] if ref)
            if refs:
                line += f"; retrieve exact product facts from {refs}"
            paragraphs.append(line + ".")

        if latest_fitment:
            line = _fitment_memory_line(latest_fitment)
            if line:
                paragraphs.append(line)

        if latest_service:
            line = _service_memory_line(latest_service)
            if line:
                paragraphs.append(line)

        if latest_order_state:
            ref = str(latest_order_state.get("evidence_ref") or "").strip()
            status = str(latest_order_state.get("status") or "").strip()
            tool_name = str(latest_order_state.get("tool_name") or "order tool").strip()
            line = f"Latest order progress came from {tool_name}"
            if ref:
                line += f"; retrieve exact order facts from {ref}"
            if status:
                line += f" (status: {status})"
            paragraphs.append(line + ".")

        if external_refs:
            refs = ", ".join(
                str(item.get("evidence_ref") or "")
                for item in external_refs
                if item.get("evidence_ref")
            )
            if refs:
                paragraphs.append(
                    "External evidence refs available: "
                    + refs
                    + ". Validate them before using commercial or action facts."
                )

        text = _trim_words(" ".join(paragraphs), self.max_words)
        if not text:
            # Preserve the existing advisory continuity note when there is no
            # newer durable state or tool evidence. Never rebuild it by
            # re-parsing the latest customer or assistant prose.
            text = _trim_words(current_memory.text, self.max_words)
        return ActiveWorkingMemory(
            text=text,
            version=max(1, current_memory.version + 1),
            updated_at=manila_now_text(),
            source="evidence_bound_compactor",
            metadata={
                "generator": self.__class__.__name__,
                "tool_result_count": len(tool_results or []),
                "background_signal_count": len(typed_signals),
                "external_evidence_ref_count": len(external_refs),
            },
        )



class HybridActiveWorkingMemoryGenerator:
    """Model-written memory with deterministic evidence, validation, and fallback."""

    def __init__(
        self,
        *,
        model_client: ActiveWorkingMemoryModelClient,
        fallback_generator: Optional[EvidenceBoundActiveWorkingMemoryGenerator] = None,
        max_words: int = 260,
        retry_attempts: int = 2,
        retry_delay_s: float = 0.6,
    ) -> None:
        self.model_client = model_client
        self.fallback_generator = fallback_generator or EvidenceBoundActiveWorkingMemoryGenerator(max_words=max_words)
        self.max_words = max(80, int(max_words or 260))
        self.retry_attempts = max(0, int(retry_attempts or 0))
        self.retry_delay_s = max(0.0, float(retry_delay_s or 0.0))

    def update(
        self,
        *,
        current_memory: ActiveWorkingMemory,
        latest_user_message: str,
        assistant_response: str,
        tool_results: Sequence[Dict[str, Any]],
        recent_turns: Sequence[Dict[str, str]],
        background_signals: Sequence[Dict[str, Any]] = (),
        external_evidence_refs: Sequence[Dict[str, Any]] = (),
    ) -> ActiveWorkingMemory:
        """Use one model-led continuity update with an evidence-bound fallback.

        Tool results are represented only by compact typed facts and stable
        refs in the evidence packet. The model therefore remains responsible
        for whether a customer goal continues across a tool-backed turn,
        without gaining authority over commercial or action facts.
        """

        fallback = self.fallback_generator.update(
            current_memory=current_memory,
            latest_user_message=latest_user_message,
            assistant_response=assistant_response,
            tool_results=tool_results,
            recent_turns=recent_turns,
            background_signals=background_signals,
            external_evidence_refs=external_evidence_refs,
        )
        evidence = build_active_working_memory_evidence(
            current_memory=current_memory,
            latest_user_message=latest_user_message,
            assistant_response=assistant_response,
            tool_results=tool_results,
            recent_turns=recent_turns,
            background_signals=background_signals,
            external_evidence_refs=external_evidence_refs,
        )
        user_prompt = build_active_working_memory_generator_prompt(evidence)
        retry_errors: List[str] = []
        total_attempts = self.retry_attempts + 1
        for attempt_index in range(1, total_attempts + 1):
            try:
                response = self.model_client.generate_memory(
                    system_prompt=ACTIVE_WORKING_MEMORY_GENERATOR_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    metadata={
                        "component": "runtime_v7_active_working_memory",
                        "task_type": "active_working_memory_update",
                        "attempt": attempt_index,
                        "max_attempts": total_attempts,
                    },
                )
            except RuntimeV7ProviderCallLimitExceeded:
                # A tester ceiling is a terminal request safeguard, not a
                # degradable model outage. Let the API return its safe
                # diagnostic instead of attempting more local retries.
                raise
            except Exception as exc:
                retry_errors.append(f"{type(exc).__name__}: {exc}")
                if attempt_index < total_attempts:
                    _sleep_before_retry(self.retry_delay_s, attempt_index=attempt_index)
                    continue
                return _fallback_memory(
                    fallback,
                    reason=f"model_error:{type(exc).__name__}",
                    error=str(exc),
                    prompt=user_prompt,
                    model_attempts=attempt_index,
                    model_retry_errors=retry_errors,
                )
            model_text = _extract_memory_text_from_model_response(response)
            if not _is_usable_memory_text(model_text):
                return _fallback_memory(
                    fallback,
                    reason="empty_or_invalid_model_memory",
                    model_response=response,
                    prompt=user_prompt,
                    model_attempts=attempt_index,
                    model_retry_errors=retry_errors,
                )
            text = _enforce_memory_invariants(
                model_text,
                evidence=evidence,
                fallback_text=fallback.text,
                max_words=self.max_words,
            )
            return ActiveWorkingMemory(
                text=text,
                version=max(1, current_memory.version + 1),
                updated_at=manila_now_text(),
                source="hybrid_model_compactor",
                metadata={
                    "generator": self.__class__.__name__,
                    "model": response.get("model"),
                    "usage": response.get("usage") or {},
                    "cache_usage": response.get("cache_usage") or {},
                    "request_cache": response.get("request_cache") or {},
                    "latency_ms": response.get("latency_ms"),
                    "finish_reason": response.get("finish_reason"),
                    "fallback_used": False,
                    "model_attempts": attempt_index,
                    "model_retry_errors": retry_errors,
                    "fallback_candidate_chars": len(fallback.text or ""),
                    "model_output_chars": len(str(response.get("content") or "")),
                },
            )
        return _fallback_memory(
            fallback,
            reason="model_error:unknown",
            error="memory model retry loop exited without response",
            prompt=user_prompt,
            model_attempts=total_attempts,
            model_retry_errors=retry_errors,
        )


class ActiveWorkingMemoryUpdater:
    """Loads, seeds, and updates active working memory for a session."""

    def __init__(
        self,
        *,
        store: Optional[ActiveWorkingMemoryStore] = None,
        generator: Optional[ActiveWorkingMemoryGenerator] = None,
    ) -> None:
        self.store = store or InMemoryActiveWorkingMemoryStore()
        self.generator = generator or EvidenceBoundActiveWorkingMemoryGenerator()

    def load(self, session_id: str) -> ActiveWorkingMemory:
        """Load the current session memory without changing authority."""

        return self.store.load(session_id)

    def seed(self, session_id: str, text: str, *, source: str = "seed") -> ActiveWorkingMemory:
        memory = ActiveWorkingMemory.from_text(text, source=source)
        self.store.save(session_id, memory)
        return memory

    def update_after_turn(
        self,
        *,
        session_id: str,
        latest_user_message: str,
        assistant_response: str,
        tool_results: Sequence[Dict[str, Any]],
        recent_turns: Sequence[Dict[str, str]],
        background_signals: Sequence[Dict[str, Any]] = (),
        external_evidence_refs: Sequence[Dict[str, Any]] = (),
    ) -> ActiveWorkingMemory:
        """Persist one evidence-bounded continuity update after a completed turn."""

        current = self.load(session_id)
        updated = self.generator.update(
            current_memory=current,
            latest_user_message=latest_user_message,
            assistant_response=assistant_response,
            tool_results=tool_results,
            recent_turns=recent_turns,
            background_signals=background_signals,
            external_evidence_refs=external_evidence_refs,
        )
        self.store.save(session_id, updated)
        return updated


def build_active_working_memory_evidence(
    *,
    current_memory: ActiveWorkingMemory,
    latest_user_message: str,
    assistant_response: str,
    tool_results: Sequence[Dict[str, Any]],
    recent_turns: Sequence[Dict[str, str]],
    background_signals: Sequence[Dict[str, Any]] = (),
    external_evidence_refs: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    """Build the evidence packet sent to a model compactor.

    The packet deliberately separates model-interpreted memory from
    normalized state signals and tool-grounded refs. Commercial facts such as
    price, promo, stock, installment availability, totals, and order details
    must stay behind retrievable refs or future validation tools.
    """

    advisory_signals = _compact_background_signals(background_signals)
    external_refs = _compact_external_evidence_refs(external_evidence_refs)
    latest_search = _latest_product_search(tool_results)
    latest_fitment = _latest_fitment_observation(tool_results)
    latest_service = _latest_service_observation(tool_results)
    latest_order_state = _latest_order_state(tool_results)
    return {
        "current_memory": active_working_memory_evidence_payload(current_memory),
        "latest_user_message": str(latest_user_message or ""),
        "assistant_response_summary": _assistant_response_summary_for_memory(
            assistant_response,
            latest_product_search=latest_search,
            latest_fitment_observation=latest_fitment,
            latest_service_observation=latest_service,
            latest_order_state=latest_order_state,
        ),
        "recent_turns": _memory_safe_recent_turns(recent_turns),
        "advisory_background_signals": advisory_signals,
        "latest_product_observation": latest_search,
        "latest_fitment_observation": latest_fitment,
        "latest_service_observation": latest_service,
        "latest_order_state": latest_order_state,
        "external_evidence_refs": external_refs,
        "memory_fact_policy": [
            "Active working memory is a continuity note, not the commercial source of truth.",
            "Advisory background signals are normalized hints from a separate extractor/normalizer. Use them for awareness, but do not force them over the latest customer wording when there is genuine conflict.",
            "Tool-grounded product observations may be remembered by observation_ref and presentation_ref. Exact product facts must be retrieved from those refs or revalidated by tools.",
            "Tool-grounded fitment observations may be remembered as candidate sizes only. They are not confirmed fitment until the customer confirms the sidewall size or accepts a provisional search.",
            "Tool-grounded service observations may be remembered by observation_ref, presentation_ref, normalized location label, and read-only status. Exact partner, slot, addon, booking, reservation, or fulfillment facts must be retrieved from service refs or revalidated by tools.",
            "Tool-grounded order progress may be remembered only by its order summary, payload, submission, or payment ref. Exact totals, discounts, payment eligibility, and order fields must be retrieved or revalidated.",
            "Runtime assistant messages are omitted from memory evidence because they are conversational continuity, not business-fact authority.",
            "External image, screenshot, PDF, human-agent, or customer-provided evidence should be remembered by evidence_ref and validation status. Do not store extracted prices, discounts, totals, fulfillment details, payment instructions, or order details as trusted memory facts. Human-agent messages are trusted continuity context, but guarded actions still need tool/state validation.",
        ],
        "rules": [
            "Use advisory background signals as context, but preserve nuance from the messages.",
            "For customer location, prefer the resolved Background Signal display label/value over raw shorthand or overlapping place wording when updating memory.",
            "If a value is only mentioned or uncertain, mark it as unconfirmed.",
            "If latest_product_observation exists, include its observation_ref and presentation_ref.",
            "If latest_fitment_observation exists, include the candidate sizes and the fact that sidewall confirmation is still needed.",
            "If latest_service_observation exists, include its observation_ref and presentation_ref plus the normalized customer_location_label when present.",
            "If latest_order_state exists, include its evidence_ref and status without copying exact totals, discounts, payment eligibility, or order fields.",
            "Do not copy product card prices or URLs into memory.",
            "Do not treat service observations as booking, reservation, payment, or fulfillment confirmations.",
            "Do not copy screenshot, pricelist, or order-image commercial details into memory. Human-agent conversation details may be summarized for continuity when still relevant, with refs and validation state preserved.",
            "Do not use location as a product-search filter unless the user explicitly asks for branch/service fulfillment.",
            "If a payment preference was mentioned, preserve it as mentioned-but-not-final until validated by order/payment tools.",
            "If no final product is selected and the customer is actively continuing, product choice/detail/compare remains the active milestone; payment/contact/order fields are later readiness items. A customer pause or close remains a pause/close, not an instruction to revive that milestone.",
        ],
    }


def build_active_working_memory_generator_prompt(evidence: Dict[str, Any]) -> str:
    """Return the exact user prompt for the model-backed memory generator."""

    return "\n".join(
        [
            "Update the Active Working Memory from this evidence packet.",
            "Return JSON only with key active_working_memory.",
            "Evidence packet:",
            json.dumps(evidence, ensure_ascii=False, indent=2, default=str),
        ]
    )


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _latest_product_search(tool_results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    for tool_result in reversed(tool_results or []):
        if tool_result.get("name") != "product_search":
            continue
        result = tool_result.get("result") or {}
        full_result = tool_result.get("full_result") or {}
        cards = result.get("product_card_headers") or []
        query_basis = result.get("query_basis") or {}
        if not query_basis and isinstance(full_result, dict):
            query_basis = full_result.get("query_basis") or {}
        return {
            "observation_ref": result.get("observation_ref"),
            "presentation_ref": result.get("presentation_ref"),
            "card_count": len(cards) if isinstance(cards, list) else None,
            "tool_query_basis": _compact_product_query_basis(query_basis),
        }
    return {}


def _latest_fitment_observation(tool_results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    for tool_result in reversed(tool_results or []):
        if tool_result.get("name") != "extract_compatible_fitment":
            continue
        result = tool_result.get("result") or {}
        full_result = tool_result.get("full_result") or {}
        candidate_rows = result.get("candidate_sizes") or full_result.get("candidate_sizes") or []
        sizes: List[str] = []
        for row in candidate_rows:
            if not isinstance(row, dict):
                continue
            size = str(row.get("size") or "").strip()
            if size and size not in sizes:
                sizes.append(size)
        return {
            "status": result.get("status") or full_result.get("status"),
            "vehicle_query": result.get("vehicle_query") or full_result.get("vehicle_query"),
            "candidate_sizes": sizes[:8],
            "requires_customer_confirmation": bool(
                result.get("requires_customer_confirmation")
                if result.get("requires_customer_confirmation") is not None
                else full_result.get("requires_customer_confirmation")
            ),
        }
    return {}


def _latest_service_observation(tool_results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    service_tool_names = {
        "find_installation_partners",
        "find_service_locations",
        "find_installation_slots",
        "get_branch_addons",
        "validate_installation_slot",
    }
    for tool_result in reversed(tool_results or []):
        tool_name = str(tool_result.get("name") or "")
        if tool_name not in service_tool_names:
            continue
        result = tool_result.get("result") or {}
        full_result = tool_result.get("full_result") or {}
        query_basis = result.get("query_basis") or {}
        if not query_basis and isinstance(full_result, dict):
            query_basis = full_result.get("query_basis") or {}
        coverage = result.get("coverage_assessment") or {}
        if not coverage and isinstance(full_result, dict):
            coverage = full_result.get("coverage_assessment") or {}
        availability = result.get("availability") or {}
        if not availability and isinstance(full_result, dict):
            availability = full_result.get("availability") or {}
        partner_cards = result.get("installation_partner_card_headers") or []
        if not partner_cards and isinstance(full_result, dict):
            partner_cards = full_result.get("installation_partner_cards") or []
        slot_groups = result.get("slot_group_headers") or []
        if not slot_groups and isinstance(full_result, dict):
            slot_groups = full_result.get("slot_groups") or []
        return {
            "observation_ref": result.get("observation_ref") or full_result.get("observation_ref"),
            "presentation_ref": result.get("presentation_ref") or full_result.get("presentation_ref"),
            "tool_name": tool_name,
            "status": result.get("status") or full_result.get("status"),
            "query_basis": _compact_service_query_basis(query_basis),
            "coverage_status": coverage.get("installation_service_area_status") if isinstance(coverage, dict) else None,
            "availability_status": availability.get("availability_status") if isinstance(availability, dict) else None,
            "card_count": len(partner_cards) if isinstance(partner_cards, list) else None,
            "slot_group_count": len(slot_groups) if isinstance(slot_groups, list) else None,
        }
    return {}


def _latest_order_state(tool_results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Return only the stable ref/status for the latest order-facing tool."""

    ref_keys_by_tool = {
        "build_order_summary": ("order_summary_ref",),
        "build_order_payload": ("order_payload_ref",),
        "submit_order": ("submitted_order_ref", "order_ref"),
        "request_payment": ("payment_request_ref",),
    }
    for tool_result in reversed(tool_results or []):
        tool_name = str(tool_result.get("name") or "")
        ref_keys = ref_keys_by_tool.get(tool_name)
        if not ref_keys:
            continue
        result = tool_result.get("result") or {}
        full_result = tool_result.get("full_result") or {}
        evidence_ref = ""
        for key in ref_keys:
            evidence_ref = str(result.get(key) or full_result.get(key) or "").strip()
            if evidence_ref:
                break
        return {
            "tool_name": tool_name,
            "status": result.get("status") or full_result.get("status"),
            "evidence_ref": evidence_ref or None,
        }
    return {}


def _fitment_memory_line(latest_fitment: Dict[str, Any]) -> str:
    sizes = latest_fitment.get("candidate_sizes") if isinstance(latest_fitment, dict) else []
    sizes = [str(size).strip() for size in sizes or [] if str(size).strip()]
    if not sizes:
        return ""
    vehicle = str(latest_fitment.get("vehicle_query") or "").strip()
    vehicle_part = f" for {vehicle}" if vehicle else ""
    line = f"Fitment candidate sizes{vehicle_part}: {', '.join(sizes[:8])}."
    if latest_fitment.get("requires_customer_confirmation"):
        line += " These are candidate sizes only; customer sidewall confirmation is still needed before treating size as final."
    return line


def _compact_product_query_basis(query_basis: Any) -> Dict[str, Any]:
    """Keep only memory-safe product-search query metadata."""

    if not isinstance(query_basis, dict):
        return {}
    normalized_filters = query_basis.get("normalized_filters")
    compact_filters = _compact_product_filters(normalized_filters if isinstance(normalized_filters, dict) else {})
    payload: Dict[str, Any] = {}
    if compact_filters:
        payload["normalized_filters"] = compact_filters
    for key in ["partial_match", "stopped_reason"]:
        value = query_basis.get(key)
        if value not in (None, "", [], {}):
            payload[key] = value
    return payload


def _compact_service_query_basis(query_basis: Any) -> Dict[str, Any]:
    """Keep memory-safe service lookup metadata without copying addresses or slot bodies."""

    if not isinstance(query_basis, dict):
        return {}
    payload: Dict[str, Any] = {}
    for key in [
        "customer_location_label",
        "location",
        "service_type",
        "service_type_was_defaulted",
        "preferred_date",
        "preferred_date_start",
        "preferred_date_end",
        "preferred_time_window",
        "source_schedule_phrase",
        "trusted_order_total",
    ]:
        value = query_basis.get(key)
        if value not in (None, "", [], {}):
            payload[key] = value
    slot_search = query_basis.get("slot_search")
    if isinstance(slot_search, dict):
        payload["slot_search"] = {
            key: value
            for key, value in slot_search.items()
            if key
            in {
                "candidate_label",
                "candidate_confidence",
                "preferred_date",
                "preferred_date_start",
                "preferred_date_end",
                "same_day_requested",
                "date_search_mode",
            }
            and value not in (None, "", [], {})
        }
    return payload


def _service_memory_line(latest_service: Dict[str, Any]) -> str:
    obs = str(latest_service.get("observation_ref") or "")
    pres = str(latest_service.get("presentation_ref") or "")
    refs = " / ".join(ref for ref in [obs, pres] if ref)
    query_basis = latest_service.get("query_basis") if isinstance(latest_service.get("query_basis"), dict) else {}
    location_label = str(query_basis.get("customer_location_label") or "").strip()
    status = str(latest_service.get("status") or "").strip()
    coverage = str(latest_service.get("coverage_status") or "").strip()
    availability = str(latest_service.get("availability_status") or "").strip()
    parts = ["Latest service lookup was read-only"]
    if status:
        parts.append(f"status={status}")
    if coverage:
        parts.append(f"coverage={coverage}")
    if availability:
        parts.append(f"availability={availability}")
    if location_label:
        parts.append(f"for {location_label}")
    if refs:
        parts.append(f"; use refs {refs} for exact service facts")
    parts.append("Service observations are not booking, reservation, payment, or fulfillment confirmations.")
    return " ".join(parts)


def _compact_product_filters(filters: Dict[str, Any]) -> Dict[str, Any]:
    """Remove product-card facts while retaining the normalized search basis."""

    allowed_keys = [
        "section_width",
        "aspect_ratio",
        "rim_size",
        "brands",
        "brand_match_mode",
        "preferred_brands",
        "excluded_brands",
        "model_patterns",
        "budget_max",
        "budget_scope",
        "promo_only",
        "tire_categories",
        "excluded_tire_categories",
        "origins",
        "excluded_origins",
        "installment_banks",
        "installment_months",
        "sort",
        "top_k",
    ]
    compact: Dict[str, Any] = {}
    for key in allowed_keys:
        value = filters.get(key)
        if value in (None, "", [], {}):
            continue
        compact[key] = value
    return compact


def _compact_background_signals(signals: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return durable typed signal rows for the compactor prompt."""

    compact: List[Dict[str, Any]] = []
    for signal in signals or []:
        if (
            not isinstance(signal, dict)
            or not signal_has_durable_authority(signal)
            or str(signal.get("relation") or "asserted").strip().casefold()
            not in DURABLE_SIGNAL_RELATIONS
        ):
            continue
        key = str(signal.get("key") or "").strip()
        value = signal.get("value")
        if not key or value in (None, ""):
            continue
        row: Dict[str, Any] = {
            "key": key,
            "value": value,
            "status": signal.get("status") or "unknown",
            "source": signal.get("source") or "unknown",
            "confidence": signal.get("confidence") or "unknown",
        }
        for optional_key in ["ask_timing", "relevance"]:
            optional_value = signal.get(optional_key)
            if optional_value not in (None, "", [], {}):
                row[optional_key] = optional_value
        resolution = signal.get("resolution")
        if isinstance(resolution, dict) and resolution:
            row["resolution"] = {
                key: value
                for key, value in resolution.items()
                if key
                in {
                    "status",
                    "source",
                    "needs",
                    "selected_ref",
                    "resolution_tier",
                    "candidate_count",
                    "display_label",
                    "city_hint",
                    "province_hint",
                    "location_precision",
                }
                and value not in (None, "", [], {})
            }
        compact.append(row)
    return compact


def _compact_context_only_signals(signals: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep bounded human-agent continuity without granting typed authority."""

    compact: List[Dict[str, Any]] = []
    for signal in signals or []:
        if (
            not isinstance(signal, dict)
            or signal_has_durable_authority(signal)
            or not signal_is_advisory_context(signal)
            or signal_authority_source(signal) != "human_agent_history"
            or str(signal.get("relation") or "asserted").strip().casefold()
            not in DURABLE_SIGNAL_RELATIONS
        ):
            continue
        key = str(signal.get("key") or "").strip()
        value = signal.get("value")
        if key and value not in (None, "", [], {}):
            compact.append(
                {
                    "key": key,
                    "value": value,
                    "source": "human_agent_history",
                    "status": "context_only",
                }
            )
    return compact


def _compact_external_evidence_refs(refs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return compact refs for future image/screenshot/order evidence."""

    compact: List[Dict[str, Any]] = []
    for ref in refs or []:
        if not isinstance(ref, dict):
            continue
        evidence_ref = str(ref.get("evidence_ref") or ref.get("ref") or "").strip()
        if not evidence_ref:
            continue
        row: Dict[str, Any] = {"evidence_ref": evidence_ref}
        for key in [
            "source",
            "media_type",
            "status",
            "trusted_for_context",
            "summary",
            "validation_ref",
        ]:
            value = ref.get(key)
            if value in (None, "", [], {}):
                continue
            row[key] = value
        extracted_fields = ref.get("extracted_fields")
        if isinstance(extracted_fields, list) and extracted_fields:
            row["extracted_fields"] = [str(item)[:80] for item in extracted_fields[:12] if str(item or "").strip()]
        compact.append(row)
    return compact


def _signal_value_map(signals: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    """Map compact advisory signals by key."""

    values: Dict[str, str] = {}
    for signal in signals or []:
        if not isinstance(signal, dict):
            continue
        key = str(signal.get("key") or "").strip()
        value = signal.get("value")
        if key and value not in (None, ""):
            values[key] = str(value)
    return values


def _signal_by_key(signals: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Map compact advisory signals by key with full row metadata."""

    return {
        str(signal.get("key")): signal
        for signal in signals or []
        if isinstance(signal, dict) and str(signal.get("key") or "").strip()
    }


def _split_signal_values(value: Optional[str]) -> List[str]:
    """Split comma-separated advisory values while preserving display text."""

    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _payment_preference_from_signals(signal_map: Dict[str, str]) -> Optional[str]:
    """Build a non-final payment preference phrase from payment signals."""

    parts = [
        signal_map.get("reservation_payment_method"),
        signal_map.get("balance_payment_method"),
        signal_map.get("payment_method"),
    ]
    cleaned = [part for part in parts if part]
    return "; ".join(cleaned) if cleaned else None


def _signal_status_contains(signals: Sequence[Dict[str, Any]], key: str, token: str) -> bool:
    """Return whether a signal status contains a token."""

    token = str(token or "").lower()
    for signal in signals or []:
        if signal.get("key") != key:
            continue
        if token and token in str(signal.get("status") or "").lower():
            return True
    return False


def _assistant_response_summary_for_memory(
    assistant_response: str,
    *,
    latest_product_search: Dict[str, Any],
    latest_fitment_observation: Optional[Dict[str, Any]] = None,
    latest_service_observation: Optional[Dict[str, Any]] = None,
    latest_order_state: Optional[Dict[str, Any]] = None,
) -> str:
    if latest_product_search:
        obs = latest_product_search.get("observation_ref")
        pres = latest_product_search.get("presentation_ref")
        card_count = latest_product_search.get("card_count")
        refs = " / ".join(ref for ref in [obs, pres] if ref)
        parts = ["Assistant presented product-search options"]
        if card_count:
            parts.append(f"({card_count} visible card(s))")
        if refs:
            parts.append(f"through refs {refs}")
        parts.append("Exact product facts should be retrieved from stored observations, not memory.")
        return " ".join(parts)
    if latest_fitment_observation:
        fitment_line = _fitment_memory_line(latest_fitment_observation)
        if fitment_line:
            return fitment_line
    if latest_service_observation:
        service_line = _service_memory_line(latest_service_observation)
        if service_line:
            return service_line
    if latest_order_state:
        ref = str(latest_order_state.get("evidence_ref") or "").strip()
        status = str(latest_order_state.get("status") or "").strip()
        tool_name = str(latest_order_state.get("tool_name") or "order tool").strip()
        parts = [f"Assistant response followed validated {tool_name} state"]
        if ref:
            parts.append(f"at ref {ref}")
        if status:
            parts.append(f"with status {status}")
        parts.append("Exact commercial and order facts must be retrieved from that state.")
        return " ".join(parts)
    return (
        "Assistant prose is omitted from Active Working Memory evidence. "
        "It remains conversation continuity, not business-fact authority."
    )


def _memory_safe_recent_turns(
    recent_turns: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Keep customer and human-agent evidence out of assistant-fact authority."""

    safe_turns: List[Dict[str, Any]] = []
    for turn in (recent_turns or [])[-12:]:
        if not isinstance(turn, dict):
            continue
        if str(turn.get("role") or "").strip() not in {"user", "human_agent"}:
            continue
        safe_turns.append(dict(turn))
    return safe_turns[-8:]


def _trim_words(text: str, max_words: int) -> str:
    words = _clean_text(text).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(" .,") + "."


def _extract_memory_text_from_model_response(response: Dict[str, Any]) -> str:
    content = str((response or {}).get("content") or "").strip()
    if not content:
        return ""
    parsed = _parse_json_object(content)
    if isinstance(parsed, dict):
        return str(
            parsed.get("active_working_memory")
            or parsed.get("memory_text")
            or parsed.get("text")
            or ""
        ).strip()
    return content


def _parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        loaded = json.loads(raw)
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            loaded = json.loads(raw[start : end + 1])
        except Exception:
            return None
    return loaded if isinstance(loaded, dict) else None


def _is_usable_memory_text(text: str) -> bool:
    cleaned = _clean_text(text)
    return 40 <= len(cleaned) <= 2400


def _enforce_memory_invariants(
    text: str,
    *,
    evidence: Dict[str, Any],
    fallback_text: str,
    max_words: int,
) -> str:
    cleaned = _clean_text(text)
    advisory_signals = (
        evidence.get("advisory_background_signals")
        if isinstance(evidence.get("advisory_background_signals"), list)
        else []
    )
    signals = _signal_value_map(advisory_signals)
    signals_by_key = _signal_by_key(advisory_signals)
    latest_search = (
        evidence.get("latest_product_observation")
        if isinstance(evidence.get("latest_product_observation"), dict)
        else {}
    )
    latest_fitment = (
        evidence.get("latest_fitment_observation")
        if isinstance(evidence.get("latest_fitment_observation"), dict)
        else {}
    )
    latest_service = (
        evidence.get("latest_service_observation")
        if isinstance(evidence.get("latest_service_observation"), dict)
        else {}
    )
    cleaned = _remove_premature_order_next_steps(cleaned)
    required_parts: List[str] = []
    for key, label in [
        ("tire_size", "Tire size signal"),
        ("rim_size", "Rim size signal"),
        ("car_make_model", "Vehicle"),
        ("tire_category_preference", "Product preference"),
        ("budget", "Budget signal"),
        ("location", "Location signal for later fulfillment"),
        ("reservation_payment_method", "Payment preference mentioned but not final or validated"),
        ("balance_payment_method", "Payment preference mentioned but not final or validated"),
        ("payment_method", "Payment preference mentioned but not final or validated"),
    ]:
        value = signals.get(key)
        if value and str(value).lower() not in cleaned.lower():
            status = str((signals_by_key.get(key) or {}).get("status") or "").strip()
            status_text = f" ({status})" if status else ""
            required_parts.append(f"{label}: {value}{status_text}.")

    obs = latest_search.get("observation_ref")
    pres = latest_search.get("presentation_ref")
    if obs and str(obs) not in cleaned:
        refs = " / ".join(ref for ref in [obs, pres] if ref)
        required_parts.append(f"Use refs {refs} for exact product facts.")

    fitment_line = _fitment_memory_line(latest_fitment)
    if fitment_line:
        candidate_sizes = latest_fitment.get("candidate_sizes") if isinstance(latest_fitment, dict) else []
        has_any_size = any(str(size or "").strip() and str(size).strip() in cleaned for size in candidate_sizes or [])
        if not has_any_size:
            required_parts.append(fitment_line)

    service_obs = latest_service.get("observation_ref")
    service_pres = latest_service.get("presentation_ref")
    service_refs = " / ".join(ref for ref in [service_obs, service_pres] if ref)
    service_query = latest_service.get("query_basis") if isinstance(latest_service.get("query_basis"), dict) else {}
    service_location = str(service_query.get("customer_location_label") or "").strip()
    if service_refs and str(service_obs) not in cleaned:
        required_parts.append(
            f"Use refs {service_refs} for exact service facts. Service observations are read-only and not booking confirmations."
        )
    if service_location and service_location.lower() not in cleaned.lower():
        required_parts.append(f"Latest service lookup location: {service_location}.")

    external_refs = (
        evidence.get("external_evidence_refs")
        if isinstance(evidence.get("external_evidence_refs"), list)
        else []
    )
    evidence_ref_text = ", ".join(
        str(item.get("evidence_ref") or "")
        for item in external_refs
        if isinstance(item, dict) and item.get("evidence_ref")
    )
    if evidence_ref_text and evidence_ref_text not in cleaned:
        required_parts.append(
            f"External evidence refs available: {evidence_ref_text}. Validate image, screenshot, or human-agent details before action."
        )

    if required_parts:
        cleaned = " ".join([cleaned] + required_parts)
    if not _is_usable_memory_text(cleaned):
        cleaned = fallback_text
    return _trim_words(cleaned, max_words)


def _remove_premature_order_next_steps(text: str) -> str:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", str(text or "").strip()) if part.strip()]
    kept: List[str] = []
    for sentence in sentences:
        lowered = sentence.lower()
        is_next_step_sentence = any(
            token in lowered
            for token in [
                "next step",
                "next steps",
                "next commercial action",
                "next action",
            ]
        )
        is_context_attributed = any(
            token in lowered
            for token in [
                "customer said",
                "customer asked",
                "customer requested",
                "user said",
                "user asked",
                "human agent",
                "staff said",
                "agent said",
                "agent asked",
            ]
        )
        mentions_order_collection = any(
            token in lowered
            for token in [
                "payment method",
                "payment",
                "contact number",
                "schedule",
                "order placement",
                "order confirmation",
                "necessary details",
            ]
        )
        if is_next_step_sentence and (mentions_order_collection or not is_context_attributed):
            continue
        kept.append(sentence)
    return " ".join(kept) if kept else _clean_text(text)


def _fallback_memory(
    fallback: ActiveWorkingMemory,
    *,
    reason: str,
    prompt: str,
    model_response: Optional[Dict[str, Any]] = None,
    error: str = "",
    model_attempts: int = 0,
    model_retry_errors: Optional[Sequence[str]] = None,
) -> ActiveWorkingMemory:
    metadata = dict(fallback.metadata or {})
    error_preview = str(error or "").strip()
    metadata.update(
        {
            "generator": "HybridActiveWorkingMemoryGenerator",
            "fallback_used": True,
            "fallback_reason": reason,
            "model_attempts": model_attempts,
            "model_retry_errors": list(model_retry_errors or []),
            "model_output_chars": len(str((model_response or {}).get("content") or "")),
            "error_type": reason.split(":", 1)[1] if ":" in reason else "",
            "error_preview": error_preview[:_MAX_PERSISTED_METADATA_STRING_CHARS],
        }
    )
    return ActiveWorkingMemory(
        text=fallback.text,
        version=fallback.version,
        updated_at=fallback.updated_at,
        source="hybrid_model_fallback",
        metadata=metadata,
    )


def _clean_memory_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    cleaned: Dict[str, Any] = {}
    for key, value in metadata.items():
        key_text = str(key or "").strip()
        if not key_text or key_text in _PROMPT_METADATA_KEYS or key_text not in _PERSISTED_MEMORY_METADATA_KEYS:
            continue
        if key_text == "model_retry_errors":
            cleaned[key_text] = [
                _truncate_string(str(item or ""), _MAX_PERSISTED_METADATA_STRING_CHARS)
                for item in list(value or [])[:_MAX_PERSISTED_METADATA_LIST_ITEMS]
            ]
            continue
        cleaned[key_text] = _compact_memory_metadata_value(value, depth=0)
    return cleaned


def _compact_memory_metadata_value(value: Any, *, depth: int) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate_string(value, _MAX_PERSISTED_METADATA_STRING_CHARS)
    if depth >= 2:
        return _truncate_string(str(value), _MAX_PERSISTED_METADATA_STRING_CHARS)
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for index, key in enumerate(sorted(value.keys(), key=lambda item: str(item))):
            if index >= _MAX_PERSISTED_METADATA_DICT_KEYS:
                break
            key_text = _truncate_string(str(key or ""), 80)
            if not key_text:
                continue
            result[key_text] = _compact_memory_metadata_value(value.get(key), depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [
            _compact_memory_metadata_value(item, depth=depth + 1)
            for item in list(value)[:_MAX_PERSISTED_METADATA_LIST_ITEMS]
        ]
    return _truncate_string(str(value), _MAX_PERSISTED_METADATA_STRING_CHARS)


def _truncate_string(value: str, max_chars: int) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 12)] + "...[truncated]"


def _sleep_before_retry(delay_s: float, *, attempt_index: int) -> None:
    """Pause briefly between transient memory model failures."""

    if delay_s <= 0:
        return
    time.sleep(delay_s * max(1, attempt_index))
