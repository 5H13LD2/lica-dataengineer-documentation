"""Joined pre-turn intake for Runtime V7 probes.

The product slice needs customer images, hydrated human-agent conversation
history, active working memory, and latest product observations before the
model packet is compiled. This module runs those independent reads in parallel
and joins them before returning, so results are not fire-and-forget context that
arrives after the model has already responded.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from runtime_v7.conversation_evidence import build_conversation_evidence_context, merge_recent_turns
from runtime_v7.image_evidence import ImageEvidenceExtractor, build_image_evidence_context, extract_image_urls


@dataclass
class PreTurnIntakeResult:
    """Context inputs and timing metadata produced before model invocation."""

    active_memory: Any
    latest_observation: Any
    latest_service_observation: Any
    conversation_evidence: Dict[str, Any]
    image_evidence: Dict[str, Any]
    context_recent_turns: List[Dict[str, str]]
    metadata: Dict[str, Any]


async def build_preturn_intake_context(
    *,
    session_id: str,
    turn_index: int,
    current_user_message: str,
    image_urls: Optional[Sequence[str]],
    conversation_history: Sequence[Dict[str, Any]],
    in_session_recent_turns: Sequence[Dict[str, Any]],
    load_active_memory: Callable[[], Any],
    load_latest_observation: Callable[[], Any],
    image_evidence_extractor: ImageEvidenceExtractor,
    load_latest_service_observation: Optional[Callable[[], Any]] = None,
) -> PreTurnIntakeResult:
    """Run independent pre-turn intake work concurrently, then join results."""

    started = time.perf_counter()
    stage_tasks = [
        _timed_to_thread("active_memory", load_active_memory),
        _timed_to_thread("latest_product_observation", load_latest_observation),
        _timed_to_thread(
            "latest_service_observation",
            load_latest_service_observation or (lambda: None),
        ),
        _timed_to_thread(
            "conversation_history",
            lambda: build_conversation_evidence_context(conversation_history),
        ),
        _timed_to_thread(
            "image_evidence",
            lambda: build_image_evidence_context(
                current_user_message=current_user_message,
                image_urls=image_urls,
                extractor=image_evidence_extractor,
                metadata={
                    "session_id": session_id,
                    "turn_index": turn_index,
                },
            ),
            fallback=lambda exc: _image_evidence_error_context(
                current_user_message=current_user_message,
                image_urls=image_urls,
                error=exc,
            ),
        ),
    ]
    stage_results = await asyncio.gather(*stage_tasks)
    values = {name: value for name, value, _timing in stage_results}
    stages = {name: timing for name, _value, timing in stage_results}

    conversation_evidence = values["conversation_history"]
    image_evidence = values["image_evidence"]
    context_recent_turns = merge_recent_turns(
        conversation_evidence.get("recent_turns") or [],
        in_session_recent_turns,
        limit=12,
    )
    total_latency_ms = int((time.perf_counter() - started) * 1000)
    metadata = {
        "mode": "joined_async_preturn_intake",
        "parallelized": True,
        "fire_and_forget": False,
        "joined_before_model_context": True,
        "total_latency_ms": total_latency_ms,
        "stages": stages,
    }
    return PreTurnIntakeResult(
        active_memory=values["active_memory"],
        latest_observation=values["latest_product_observation"],
        latest_service_observation=values.get("latest_service_observation"),
        conversation_evidence=conversation_evidence,
        image_evidence=image_evidence,
        context_recent_turns=context_recent_turns,
        metadata=metadata,
    )


def build_preturn_intake_context_sync(**kwargs: Any) -> PreTurnIntakeResult:
    """Synchronous adapter for the current Runtime V7 harness."""

    return asyncio.run(build_preturn_intake_context(**kwargs))


async def _timed_to_thread(
    name: str,
    func: Callable[[], Any],
    *,
    fallback: Optional[Callable[[Exception], Any]] = None,
) -> tuple[str, Any, Dict[str, Any]]:
    started = time.perf_counter()
    try:
        value = await asyncio.to_thread(func)
        status = "ok"
        error = ""
    except Exception as exc:
        if fallback is None:
            raise
        value = fallback(exc)
        status = "error_fallback"
        error = f"{exc.__class__.__name__}: {exc}"
    return (
        name,
        value,
        {
            "status": status,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            **({"error": error} if error else {}),
        },
    )


def _image_evidence_error_context(
    *,
    current_user_message: str,
    image_urls: Optional[Sequence[str]],
    error: Exception,
) -> Dict[str, Any]:
    urls = _unique([*(image_urls or []), *extract_image_urls(current_user_message)])
    refs = [
        {
            "evidence_ref": f"img_error_{index + 1}",
            "source": "customer_image",
            "media_type": "image",
            "image_url": url,
            "safe_for_action": False,
            "requires_validation": True,
            "status": "extraction_error",
            "summary": "image evidence was detected but pre-turn extraction raised an error",
            "extracted_fields": [],
            "error": f"{error.__class__.__name__}: {error}",
        }
        for index, url in enumerate(urls)
    ]
    return {
        "image_urls": urls,
        "external_evidence_refs": refs,
        "background_signal_candidates": [],
    }


def _unique(values: Sequence[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
