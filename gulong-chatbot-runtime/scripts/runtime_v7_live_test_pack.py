"""Run Runtime V7 live model probe packs without embedding scenarios in code.

The script is intentionally dormant until invoked. It reads a JSON test pack,
runs selected scenarios through the Runtime V7 harness with live model clients,
and writes UTF-8 artifacts under tmp/ for manual review.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime_v7.image_evidence import ImageEvidenceExtractor, RuntimeV7ImageEvidenceModelClient
from runtime_v7.llm_gateway import RuntimeV7LLMGateway, RuntimeV7LLMGatewayConfig
from runtime_v7.memory import HybridActiveWorkingMemoryGenerator, RuntimeV7ActiveWorkingMemoryModelClient
from runtime_v7.product_observations import ProductToolHarness
from runtime_v7.product_search import ProductSearchRunner
from runtime_v7.promo_catalog import PromoCatalogRepository, PromoCatalogService
from runtime_v7.runtime_harness import RuntimeV7Harness
from runtime_v7.state_signals import RuntimeV7BackgroundSignalModelClient


DEFAULT_MODEL_PRICING = {
    "profile": "gemini_paid_standard_2026_05_22",
    "currency": "USD",
    "unit": "per_1m_tokens",
    "source": "https://ai.google.dev/gemini-api/docs/pricing",
    "notes": [
        "Gemini Developer API paid-tier standard token rates observed 2026-05-22.",
        "Estimated cost excludes context-cache storage, Google Search/Maps grounding charges, Gulong API calls, geocoding charges, and model attempts that fail without provider usage metadata.",
        "Output cost uses completion_tokens as the billable output-token count; provider-reported reasoning tokens are tracked separately and assumed included in completion_tokens when the provider reports both.",
    ],
    "models": {
        "gemini-2.5-flash": {"input_per_1m": 0.30, "cached_input_per_1m": 0.03, "output_per_1m": 2.50},
        "gemini-2.5-flash-lite": {"input_per_1m": 0.10, "cached_input_per_1m": 0.01, "output_per_1m": 0.40},
        "gemini-2.5-flash-lite-preview-09-2025": {"input_per_1m": 0.10, "cached_input_per_1m": 0.01, "output_per_1m": 0.40},
        "gemini-3.1-flash-lite": {"input_per_1m": 0.25, "cached_input_per_1m": 0.025, "output_per_1m": 1.50},
        "gemini-3.1-flash-lite-preview": {"input_per_1m": 0.25, "cached_input_per_1m": 0.025, "output_per_1m": 1.50},
        "gemini-3.5-flash": {"input_per_1m": 1.50, "cached_input_per_1m": 0.15, "output_per_1m": 9.00},
    },
}


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class RuntimeV7PackModelClient:
    """LiteLLM-backed model client with pack-specific metadata."""

    def __init__(
        self,
        *,
        model: str,
        trace_id: str,
        scenario_id: str,
        enable_context_cache: bool,
        context_cache_ttl: str,
        temperature: float,
        timeout_s: float,
        reasoning_effort: str | None,
        guard: "RuntimeV7LiveRunGuard",
    ) -> None:
        self.model = model
        self.trace_id = trace_id
        self.scenario_id = scenario_id
        self.guard = guard
        self.reasoning_effort = _normalize_reasoning_arg(reasoning_effort)
        self.gateway = RuntimeV7LLMGateway(
            config=RuntimeV7LLMGatewayConfig(
                model=model,
                api_key_env="GEMINI_API_KEY",
                temperature=temperature,
                max_tokens=1400,
                timeout_s=timeout_s,
                embedding_timeout_s=timeout_s,
                enable_context_cache=enable_context_cache,
                context_cache_ttl=context_cache_ttl,
            )
        )

    def complete(
        self,
        *,
        messages: Sequence[Dict[str, Any]],
        tools: Sequence[Dict[str, Any]],
        tool_choice: Any = "auto",
        response_format: Any = None,
        max_tokens: int | None = None,
    ) -> Dict[str, Any]:
        """Run one guarded live model call with accurate component attribution."""

        response_format_name = getattr(response_format, "__name__", "")
        component = {
            "RuntimeV7SemanticAnswerAuditModel": "semantic_answer_goal_audit",
            "RuntimeV7PromoFactAuditModel": "promo_fact_scope_audit",
            "RuntimeV7PricingRepairResponseModel": "pricing_repair",
            "RuntimeV7HumanHandoffDecisionModel": "human_handoff_decision",
        }.get(
            response_format_name,
            "final_composer" if response_format is not None else "main_tool_loop",
        )
        self.guard.before_model_call(component=component, model=self.model)
        return self.gateway.complete(
            messages=list(messages),
            tools=list(tools),
            tool_choice=tool_choice,
            response_format=response_format,
            max_tokens=max_tokens,
            reasoning_effort=self.reasoning_effort if response_format is None else None,
            metadata=_metadata(
                trace_id=self.trace_id,
                scenario_id=self.scenario_id,
                component=f"runtime_v7_live_test_pack_{component}",
            ),
        )

    def embed(self, **kwargs: Any) -> Dict[str, Any]:
        self.guard.before_model_call(component="faq_embedding", model=str(kwargs.get("model") or os.getenv("RAG_EMBEDDING_MODEL") or "gemini/text-embedding-004"))
        return self.gateway.embed(**kwargs)


class RuntimeV7LiveRunGuard:
    """Hard stop for live probe model-call budgets."""

    def __init__(
        self,
        *,
        max_model_calls_per_turn: int,
        max_model_calls_per_scenario: int,
        max_model_calls_per_run: int,
    ) -> None:
        self.max_model_calls_per_turn = max(1, int(max_model_calls_per_turn or 1))
        self.max_model_calls_per_scenario = max(1, int(max_model_calls_per_scenario or 1))
        self.max_model_calls_per_run = max(1, int(max_model_calls_per_run or 1))
        self.run_model_calls = 0
        self.scenario_model_calls = 0
        self.turn_model_calls = 0
        self.current_scenario_id = ""
        self.current_turn = ""
        self.call_log: List[Dict[str, Any]] = []

    def start_scenario(self, scenario_id: str) -> None:
        self.current_scenario_id = str(scenario_id or "")
        self.scenario_model_calls = 0
        self.turn_model_calls = 0
        self.current_turn = ""

    def start_turn(self, turn_id: str) -> None:
        self.current_turn = str(turn_id or "")
        self.turn_model_calls = 0

    def before_model_call(self, *, component: str, model: str) -> None:
        next_run = self.run_model_calls + 1
        next_scenario = self.scenario_model_calls + 1
        next_turn = self.turn_model_calls + 1
        if next_run > self.max_model_calls_per_run:
            raise ModelCallBudgetExceeded(self._message("run", next_run, self.max_model_calls_per_run, component, model))
        if next_scenario > self.max_model_calls_per_scenario:
            raise ModelCallBudgetExceeded(self._message("scenario", next_scenario, self.max_model_calls_per_scenario, component, model))
        if next_turn > self.max_model_calls_per_turn:
            raise ModelCallBudgetExceeded(self._message("turn", next_turn, self.max_model_calls_per_turn, component, model))
        self.run_model_calls = next_run
        self.scenario_model_calls = next_scenario
        self.turn_model_calls = next_turn
        self.call_log.append(
            {
                "scenario_id": self.current_scenario_id,
                "turn": self.current_turn,
                "component": component,
                "model": model,
                "run_model_call_index": self.run_model_calls,
                "scenario_model_call_index": self.scenario_model_calls,
                "turn_model_call_index": self.turn_model_calls,
            }
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_model_calls_per_turn": self.max_model_calls_per_turn,
            "max_model_calls_per_scenario": self.max_model_calls_per_scenario,
            "max_model_calls_per_run": self.max_model_calls_per_run,
            "run_model_calls": self.run_model_calls,
            "current_scenario_id": self.current_scenario_id,
            "current_turn": self.current_turn,
            "recent_call_log": self.call_log[-20:],
        }

    def _message(self, scope: str, attempted: int, limit: int, component: str, model: str) -> str:
        return (
            f"Runtime V7 live test aborted: {scope} model-call budget exceeded "
            f"(attempted={attempted}, limit={limit}, scenario={self.current_scenario_id}, "
            f"turn={self.current_turn}, component={component}, model={model})."
        )


class ModelCallBudgetExceeded(RuntimeError):
    """Raised before a live model call would exceed the configured budget."""


class GuardedActiveWorkingMemoryModelClient:
    """Guard wrapper for memory compaction model calls."""

    def __init__(self, delegate: RuntimeV7ActiveWorkingMemoryModelClient, guard: RuntimeV7LiveRunGuard, model: str) -> None:
        self.delegate = delegate
        self.guard = guard
        self.model = model

    def generate_memory(self, **kwargs: Any) -> Dict[str, Any]:
        self.guard.before_model_call(component="active_working_memory", model=self.model)
        return self.delegate.generate_memory(**kwargs)


class GuardedBackgroundSignalModelClient:
    """Guard wrapper for background signal extraction model calls."""

    def __init__(self, delegate: RuntimeV7BackgroundSignalModelClient, guard: RuntimeV7LiveRunGuard, model: str) -> None:
        self.delegate = delegate
        self.guard = guard
        self.model = model

    def extract_background_signals(self, **kwargs: Any) -> Dict[str, Any]:
        self.guard.before_model_call(component="background_signal_extraction", model=self.model)
        return self.delegate.extract_background_signals(**kwargs)


class GuardedImageEvidenceModelClient:
    """Guard wrapper for image evidence model calls."""

    def __init__(self, delegate: RuntimeV7ImageEvidenceModelClient, guard: RuntimeV7LiveRunGuard, model: str) -> None:
        self.delegate = delegate
        self.guard = guard
        self.model = model

    def extract_image_evidence(self, **kwargs: Any) -> Dict[str, Any]:
        self.guard.before_model_call(component="image_evidence", model=self.model)
        return self.delegate.extract_image_evidence(**kwargs)


def main() -> None:
    """Run selected live-pack scenarios and write bounded review artifacts."""

    os.environ.setdefault("LANGSMITH_TRACING", "false")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", default="test_packs/runtime_v7_live_model_test_pack.json")
    parser.add_argument("--mode", choices=["live"], default="live", help="Live model execution only; kept for explicitness.")
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--strict-env", action="store_true", help="Fail if a selected scenario references an unset $ENV value.")
    parser.add_argument("--model", default=os.environ.get("RUNTIME_V7_AGENT_MODEL", "gemini/gemini-2.5-flash"))
    parser.add_argument("--memory-generator", choices=["heuristic", "hybrid-live"], default="hybrid-live")
    parser.add_argument("--memory-model", default=os.environ.get("RUNTIME_V7_MEMORY_MODEL", "gemini/gemini-2.5-flash-lite"))
    parser.add_argument("--background-signal-generator", choices=["none", "hybrid-live"], default="hybrid-live")
    parser.add_argument("--background-signal-model", default=os.environ.get("RUNTIME_V7_BACKGROUND_SIGNAL_MODEL", "gemini/gemini-2.5-flash-lite"))
    parser.add_argument("--background-signal-policy", choices=["auto", "always", "never"], default="auto")
    parser.add_argument("--image-evidence-generator", choices=["none", "live"], default="live")
    parser.add_argument("--image-evidence-model", default=os.environ.get("RUNTIME_V7_IMAGE_EVIDENCE_MODEL", "gemini/gemini-2.5-flash"))
    parser.add_argument("--enable-context-cache", action="store_true")
    parser.add_argument(
        "--enable-promo-catalog",
        action="store_true",
        help="Attach the read-only published promo catalog for promo-dependent scenarios.",
    )
    parser.add_argument("--context-cache-ttl", default="3600s")
    parser.add_argument("--temperature", type=float, default=0.2, help="Temperature for the main Runtime V7 model/tool-loop client.")
    parser.add_argument(
        "--main-reasoning-effort",
        default=os.environ.get(
            "RUNTIME_V7_MAIN_REASONING_EFFORT",
            os.environ.get("RUNTIME_V7_REASONING_EFFORT", "low"),
        ),
        choices=["provider_default", "none", "disable", "minimal", "low", "medium", "high"],
    )
    parser.add_argument(
        "--background-signal-reasoning-effort",
        default=os.environ.get("RUNTIME_V7_BACKGROUND_SIGNAL_REASONING_EFFORT", "low"),
        choices=["provider_default", "none", "disable", "minimal", "low", "medium", "high"],
    )
    parser.add_argument(
        "--thought-signature-mode",
        default=os.environ.get("RUNTIME_V7_THOUGHT_SIGNATURE_MODE", "preserve"),
        choices=["preserve", "strip"],
        help="Preserve LiteLLM Gemini thought-signature tool-call IDs or strip them for A/B probes.",
    )
    parser.add_argument("--pricing-config", default="", help="Optional JSON pricing override for model cost estimates.")
    parser.add_argument("--model-timeout-s", type=float, default=60.0, help="Per-model-call timeout. Hard-capped at 60 seconds.")
    parser.add_argument("--max-tool-rounds", type=int, default=4, help="Hard cap for tool-loop LLM rounds per turn.")
    parser.add_argument("--max-model-calls-per-turn", type=int, default=12)
    parser.add_argument("--max-model-calls-per-scenario", type=int, default=60)
    parser.add_argument("--max-model-calls-per-run", type=int, default=350)
    parser.add_argument("--out-dir", default="tmp/runtime_v7_live_test_pack")
    args = parser.parse_args()

    pack = _load_pack(Path(args.pack))
    pricing = _load_pricing(Path(args.pricing_config)) if args.pricing_config else DEFAULT_MODEL_PRICING
    scenarios = _select_scenarios(pack.get("scenarios") or [], scenario_ids=args.scenario, tags=args.tag, limit=args.limit)
    if args.list:
        _print_scenario_list(scenarios)
        return
    scenarios = [_resolve_env_refs(scenario, strict=args.strict_env, path=f"scenario:{scenario.get('id')}") for scenario in scenarios]

    run_id = f"runtime_v7_live_pack_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir = Path(args.out_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    guard = RuntimeV7LiveRunGuard(
        max_model_calls_per_turn=args.max_model_calls_per_turn,
        max_model_calls_per_scenario=args.max_model_calls_per_scenario,
        max_model_calls_per_run=args.max_model_calls_per_run,
    )
    model_timeout_s = _bounded_model_timeout(args.model_timeout_s)
    max_tool_rounds = _bounded_tool_rounds(args.max_tool_rounds)

    summary_rows: List[Dict[str, Any]] = []
    aborted: Dict[str, Any] = {}
    try:
        for scenario in scenarios:
            guard.start_scenario(str(scenario.get("id") or "scenario"))
            payload = run_scenario(
                scenario,
                mode=args.mode,
                model=args.model,
                enable_context_cache=args.enable_context_cache,
                enable_promo_catalog=args.enable_promo_catalog,
                context_cache_ttl=args.context_cache_ttl,
                memory_generator=args.memory_generator,
                memory_model=args.memory_model,
                background_signal_generator=args.background_signal_generator,
                background_signal_model=args.background_signal_model,
                background_signal_policy=args.background_signal_policy,
                image_evidence_generator=args.image_evidence_generator,
                image_evidence_model=args.image_evidence_model,
                temperature=args.temperature,
                main_reasoning_effort=args.main_reasoning_effort,
                background_signal_reasoning_effort=args.background_signal_reasoning_effort,
                thought_signature_mode=args.thought_signature_mode,
                model_timeout_s=model_timeout_s,
                max_tool_rounds=max_tool_rounds,
                guard=guard,
            )
            _attach_cost_breakdowns(payload, pricing=pricing)
            cost_summary = _scenario_cost_summary(payload, pricing=pricing)
            payload["runtime_payload"]["cost_summary"] = cost_summary
            paths = _write_scenario_artifacts(payload, out_dir=out_dir)
            summary_rows.append(_summary_row(payload, artifact_paths=paths, pricing=pricing))
    except ModelCallBudgetExceeded as exc:
        aborted = {
            "aborted": True,
            "reason": str(exc),
            "guard": guard.to_dict(),
        }

    summary = {
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pack": pack.get("pack_id"),
        "mode": args.mode,
        "aborted": bool(aborted),
        "abort": aborted or None,
        "guardrails": {
            "model_timeout_s": model_timeout_s,
            "max_tool_rounds": max_tool_rounds,
            "max_model_calls_per_turn": guard.max_model_calls_per_turn,
            "max_model_calls_per_scenario": guard.max_model_calls_per_scenario,
            "max_model_calls_per_run": guard.max_model_calls_per_run,
        },
        "scenario_count": len(summary_rows),
        "pricing": _pricing_public_summary(pricing),
        "totals": _aggregate_summary_rows(summary_rows),
        "rows": summary_rows,
    }
    summary_json = out_dir / "summary.json"
    summary_md = out_dir / "summary.md"
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_md.write_text(_render_summary_markdown(summary), encoding="utf-8")
    print(json.dumps({"summary_json": str(summary_json.resolve()), "summary_markdown": str(summary_md.resolve())}, ensure_ascii=False, indent=2))
    if aborted:
        raise SystemExit(2)


def run_scenario(
    scenario: Dict[str, Any],
    *,
    mode: str,
    model: str,
    enable_context_cache: bool,
    enable_promo_catalog: bool,
    context_cache_ttl: str,
    memory_generator: str,
    memory_model: str,
    background_signal_generator: str,
    background_signal_model: str,
    background_signal_policy: str,
    image_evidence_generator: str,
    image_evidence_model: str,
    temperature: float,
    main_reasoning_effort: str | None,
    background_signal_reasoning_effort: str | None,
    thought_signature_mode: str,
    model_timeout_s: float,
    max_tool_rounds: int,
    guard: RuntimeV7LiveRunGuard,
) -> Dict[str, Any]:
    """Execute one isolated multi-turn scenario through the live Runtime V7 harness."""

    scenario_id = str(scenario.get("id") or "scenario")
    trace_id = f"runtime_v7_live_pack_{scenario_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    runner = ProductSearchRunner(max_api_calls=int(scenario.get("max_api_calls") or 12), max_pages_per_attempt=1)
    product_tools = ProductToolHarness(runner=runner)
    promo_catalog = None
    if enable_promo_catalog:
        promo_catalog = PromoCatalogService(
            PromoCatalogRepository(
                project_id=os.environ.get(
                    "GOOGLE_CLOUD_PROJECT",
                    "gulong-chatbot-459723",
                ),
                cards_collection=os.environ.get(
                    "PROMO_CATALOG_CARDS_COLLECTION",
                    "promo_catalog_cards",
                ),
                mechanics_collection=os.environ.get(
                    "PROMO_CATALOG_MECHANICS_COLLECTION",
                    "promo_catalog_mechanics",
                ),
                brand_profiles_collection=os.environ.get(
                    "PROMO_BRAND_PROFILES_COLLECTION",
                    "promo_brand_profiles",
                ),
                config_collection=os.environ.get(
                    "PROMO_CATALOG_CONFIG_COLLECTION",
                    "promo_catalog_config",
                ),
            ),
            product_lookup=lambda tire_size, brands: _promo_exact_size_products(
                product_tools,
                tire_size=tire_size,
                brands=brands,
            ),
        )
    model_client = RuntimeV7PackModelClient(
        model=model,
        trace_id=trace_id,
        scenario_id=scenario_id,
        enable_context_cache=enable_context_cache,
        context_cache_ttl=context_cache_ttl,
        temperature=temperature,
        timeout_s=model_timeout_s,
        reasoning_effort=main_reasoning_effort,
        guard=guard,
    )

    active_memory_generator = None
    if memory_generator == "hybrid-live":
        active_memory_generator = HybridActiveWorkingMemoryGenerator(
            model_client=GuardedActiveWorkingMemoryModelClient(
                RuntimeV7ActiveWorkingMemoryModelClient(
                    model=memory_model,
                    timeout_s=model_timeout_s,
                    enable_context_cache=enable_context_cache,
                    context_cache_ttl=context_cache_ttl,
                    metadata=_metadata(trace_id=trace_id, scenario_id=scenario_id, component="runtime_v7_live_test_pack_memory"),
                ),
                guard,
                memory_model,
            )
        )

    background_signal_model_client = None
    if background_signal_generator == "hybrid-live":
        background_signal_model_client = GuardedBackgroundSignalModelClient(
            RuntimeV7BackgroundSignalModelClient(
                model=background_signal_model,
                timeout_s=model_timeout_s,
                enable_context_cache=enable_context_cache,
                context_cache_ttl=context_cache_ttl,
                reasoning_effort=_normalize_reasoning_arg(background_signal_reasoning_effort),
                metadata=_metadata(
                    trace_id=trace_id,
                    scenario_id=scenario_id,
                    component="runtime_v7_live_test_pack_background_signals",
                ),
            ),
            guard,
            background_signal_model,
        )

    image_evidence_extractor = ImageEvidenceExtractor()
    if image_evidence_generator == "live":
        image_evidence_extractor = ImageEvidenceExtractor(
            model_client=GuardedImageEvidenceModelClient(
                RuntimeV7ImageEvidenceModelClient(
                    model=image_evidence_model,
                    timeout_s=model_timeout_s,
                    metadata=_metadata(trace_id=trace_id, scenario_id=scenario_id, component="runtime_v7_live_test_pack_image_evidence"),
                ),
                guard,
                image_evidence_model,
            ),
            retry_attempts=2,
        )

    default_domains = scenario.get("default_domains")
    if default_domains is None:
        default_domains = []

    harness = RuntimeV7Harness(
        model_client=model_client,
        tools=product_tools,
        session_id=f"runtime-v7-live-test-pack-{scenario_id}",
        memory_generator=active_memory_generator,
        background_signal_model_client=background_signal_model_client,
        background_signal_model_policy=background_signal_policy,
        image_evidence_extractor=image_evidence_extractor,
        max_tool_rounds=min(_int_or_zero(scenario.get("max_tool_rounds")) or max_tool_rounds, max_tool_rounds),
        default_domains=tuple(default_domains),
        conversation_history=list(scenario.get("conversation_history") or []),
        thought_signature_mode=thought_signature_mode,
        profile_fields={"channel": "manychat"},
        promo_catalog=promo_catalog,
    )
    initial_memory = str(scenario.get("active_working_memory") or "").strip()
    if initial_memory:
        harness.memory_updater.seed(
            harness.session_id,
            initial_memory,
            source="live_test_pack_seed",
        )

    for turn_index, turn in enumerate(scenario.get("turns") or [], start=1):
        guard.start_turn(f"turn_{turn_index}")
        turn_payload = turn if isinstance(turn, dict) else {"message": str(turn)}
        image_urls = [str(value) for value in turn_payload.get("image_urls") or [] if str(value or "").strip()]
        harness.run_turn(
            str(turn_payload.get("message") or ""),
            image_urls=image_urls,
            conversation_history=turn_payload.get("conversation_history"),
            request_time_override=turn_payload.get("request_time") or scenario.get("request_time"),
        )
        _remember_synthetic_product_delivery(harness)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "scenario": scenario,
        "scenario_id": scenario_id,
        "trace_id": trace_id,
        "model": model,
        "runtime_payload": {
            "turn_count": len(harness.turn_records),
            "turns": harness.turn_records,
            "llm_usage_summary": _aggregate_usage(harness.turn_records),
            "final_observation_headers": harness.tools.store.headers(limit=5),
            "final_service_observation_headers": harness.service_tools.store.headers(limit=5),
            "final_recent_turns": harness.recent_turns,
            "final_active_working_memory": harness.memory_updater.load(harness.session_id).to_dict(),
        },
        "run_config": {
            "memory_generator": memory_generator,
            "memory_model": memory_model if memory_generator == "hybrid-live" else None,
            "background_signal_generator": background_signal_generator,
            "background_signal_model": background_signal_model if background_signal_generator == "hybrid-live" else None,
            "background_signal_policy": background_signal_policy,
            "image_evidence_generator": image_evidence_generator,
            "image_evidence_model": image_evidence_model if image_evidence_generator == "live" else None,
            "context_cache_enabled": bool(enable_context_cache),
            "promo_catalog_enabled": bool(enable_promo_catalog),
            "context_cache_ttl": context_cache_ttl if enable_context_cache else None,
            "main_reasoning_effort": _normalize_reasoning_arg(main_reasoning_effort),
            "background_signal_reasoning_effort": _normalize_reasoning_arg(background_signal_reasoning_effort),
            "thought_signature_mode": str(thought_signature_mode or "preserve"),
            "temperature": temperature,
            "model_timeout_s": model_timeout_s,
            "max_tool_rounds": max_tool_rounds,
            "model_call_guard": guard.to_dict(),
        },
    }
    return payload


def _remember_synthetic_product_delivery(harness: RuntimeV7Harness) -> None:
    """Make a visible local probe turn available to its next synthetic turn.

    Production records this state only after the channel delivery result is
    known.  The live test pack has no delivery adapter, so it records success
    only when the exact rendered response visibly contains a stored card title.
    """

    if not harness.turn_records:
        return
    observation = harness.tools.store.latest()
    if observation is None:
        return
    response = str(harness.turn_records[-1].get("runtime_final_response") or "")
    response_norm = re.sub(r"[^A-Z0-9]+", "", response.upper())
    visible_cards = [
        dict(card)
        for card in observation.product_cards or []
        if isinstance(card, dict)
        and (
            re.sub(r"[^A-Z0-9]+", "", str(card.get("sku_model") or "").upper())
            in response_norm
        )
    ]
    if not visible_cards:
        return
    presentation_ref = str(observation.presentation_ref or "").strip()
    if not presentation_ref:
        return
    if any(
        str(entry.get("presentation_ref") or "").strip() == presentation_ref
        and str(entry.get("delivery_status") or "").strip() == "success"
        for entry in harness.product_presentation_history or []
        if isinstance(entry, dict)
    ):
        return
    entry = {
        "observation_ref": observation.observation_ref,
        "presentation_ref": presentation_ref,
        "cards": visible_cards,
        "delivery_status": "success",
        "delivery_mode": "synthetic_local_visible_output",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    harness.product_presentation_history = [
        *harness.product_presentation_history[-9:],
        entry,
    ]
    harness.latest_product_presentation = dict(entry)


def _promo_exact_size_products(
    product_tools: ProductToolHarness,
    *,
    tire_size: str,
    brands: Sequence[str],
) -> List[Dict[str, Any]]:
    """Run the same bounded hidden inventory lookup as the API harness."""

    match = re.fullmatch(
        r"(\d{3})/(\d{2})(ZR|R)(\d{2})",
        str(tire_size or "").upper(),
    )
    if not match:
        return []
    result = product_tools.runner.run(
        {
            "section_width": match.group(1),
            "aspect_ratio": match.group(2),
            "rim_size": f"{match.group(3)}{match.group(4)}",
            "preferred_brands": list(brands or []),
            "top_k": 12,
        }
    )
    rows = [
        dict(row)
        for row in [
            *(result.get("best_products") or []),
            *(result.get("presented_products") or []),
        ]
        if isinstance(row, dict)
    ]
    seen = set()
    output = []
    for row in rows:
        key = str(
            row.get("item_ref")
            or row.get("product_id")
            or row.get("slug")
            or json.dumps(row, sort_keys=True)
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def _load_pack(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_pricing(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    default_models = dict(DEFAULT_MODEL_PRICING.get("models") or {})
    override_models = dict(payload.get("models") or {})
    merged = dict(DEFAULT_MODEL_PRICING)
    merged.update({key: value for key, value in payload.items() if key != "models"})
    merged["models"] = {**default_models, **override_models}
    return merged


def _bounded_model_timeout(value: Any) -> float:
    try:
        timeout = 60.0 if value is None else float(value)
    except (TypeError, ValueError):
        timeout = 60.0
    return max(1.0, min(timeout, 60.0))


def _bounded_tool_rounds(value: Any) -> int:
    try:
        rounds = 4 if value is None else int(value)
    except (TypeError, ValueError):
        rounds = 4
    return max(1, min(rounds, 8))


def _normalize_reasoning_arg(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text or text in {"provider_default", "provider-default", "default", "auto"}:
        return None
    if text in {"none", "disable", "minimal", "low", "medium", "high"}:
        return text
    return None


def _resolve_env_refs(value: Any, *, strict: bool, path: str) -> Any:
    """Resolve full-string $ENV placeholders without committing private media URLs."""
    if isinstance(value, str):
        if value.startswith("$") and len(value) > 1:
            env_name = value[1:]
            resolved = os.environ.get(env_name)
            if resolved is None:
                if strict:
                    raise SystemExit(f"Missing required environment variable {env_name} referenced at {path}")
                return ""
            return resolved
        return value
    if isinstance(value, list):
        return [_resolve_env_refs(item, strict=strict, path=f"{path}[{idx}]") for idx, item in enumerate(value)]
    if isinstance(value, dict):
        return {
            key: _resolve_env_refs(item, strict=strict, path=f"{path}.{key}")
            for key, item in value.items()
        }
    return value


def _select_scenarios(
    scenarios: Sequence[Dict[str, Any]],
    *,
    scenario_ids: Sequence[str],
    tags: Sequence[str],
    limit: int,
) -> List[Dict[str, Any]]:
    wanted_ids = {str(value) for value in scenario_ids or []}
    wanted_tags = {str(value) for value in tags or []}
    selected = []
    for scenario in scenarios:
        scenario_tags = {str(value) for value in scenario.get("tags") or []}
        if wanted_ids and str(scenario.get("id")) not in wanted_ids:
            continue
        if wanted_tags and not wanted_tags.intersection(scenario_tags):
            continue
        selected.append(dict(scenario))
    if limit > 0:
        selected = selected[:limit]
    return selected


def _print_scenario_list(scenarios: Sequence[Dict[str, Any]]) -> None:
    for scenario in scenarios:
        print(
            "{id}\t{category}\t{tags}\t{title}".format(
                id=scenario.get("id"),
                category=scenario.get("category"),
                tags=",".join(str(value) for value in scenario.get("tags") or []),
                title=scenario.get("title"),
            )
        )


def _write_scenario_artifacts(payload: Dict[str, Any], *, out_dir: Path) -> Dict[str, str]:
    scenario_id = str(payload.get("scenario_id") or "scenario")
    safe_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in scenario_id)
    json_path = out_dir / f"{safe_id}.json"
    md_path = out_dir / f"{safe_id}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_scenario_markdown(payload), encoding="utf-8")
    return {"json": str(json_path.resolve()), "markdown": str(md_path.resolve())}


def _render_scenario_markdown(payload: Dict[str, Any]) -> str:
    scenario = payload.get("scenario") or {}
    runtime_payload = payload.get("runtime_payload") or {}
    lines = [
        f"# {scenario.get('id')}: {scenario.get('title')}",
        "",
        f"Category: `{scenario.get('category')}`",
        f"Tags: `{', '.join(str(value) for value in scenario.get('tags') or [])}`",
        f"Mode: `{payload.get('mode')}`",
        f"Trace: `{payload.get('trace_id')}`",
        "",
        "## Expected",
        "```json",
        json.dumps(scenario.get("expected") or {}, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Review Focus",
        "```json",
        json.dumps(scenario.get("review_focus") or [], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Usage Summary",
        "```json",
        json.dumps(runtime_payload.get("llm_usage_summary") or {}, ensure_ascii=False, indent=2),
        "```",
        "",
        "## All Model Usage Summary",
        "```json",
        json.dumps(runtime_payload.get("all_model_usage_summary") or {}, ensure_ascii=False, indent=2),
        "```",
    ]
    for turn in runtime_payload.get("turns") or []:
        lines.extend(
            [
                "",
                f"## {turn.get('turn_id')}",
                "",
                f"User: {turn.get('user_message')}",
                "",
                "### Capability Profile",
                "```json",
                json.dumps(turn.get("capability_profile") or {}, ensure_ascii=False, indent=2),
                "```",
                "",
                "### Background Signals",
                "```json",
                json.dumps(turn.get("background_signals_before_turn") or [], ensure_ascii=False, indent=2),
                "```",
                "",
                "### Turn Cost Summary",
                "```json",
                json.dumps(turn.get("cost_summary") or {}, ensure_ascii=False, indent=2),
                "```",
                "",
                "### Turn All Model Usage Summary",
                "```json",
                json.dumps(turn.get("all_model_usage_summary") or {}, ensure_ascii=False, indent=2),
                "```",
                "",
                "### Model Calls",
            ]
        )
        for call in turn.get("llm_calls") or []:
            lines.extend(
                [
                    "- round={round} latency_ms={latency} finish={finish} tool_calls={tool_calls} estimated_cost_usd={cost}".format(
                        round=call.get("round"),
                        latency=call.get("latency_ms"),
                        finish=call.get("finish_reason"),
                        tool_calls=len(call.get("tool_calls") or []),
                        cost=(call.get("cost_summary") or {}).get("estimated_cost_usd"),
                    ),
                    "```json",
                    json.dumps(call.get("cost_summary") or {}, ensure_ascii=False, indent=2),
                    "```",
                ]
            )
        lines.extend(
            [
                "",
                "### Tool Calls / Results",
            ]
        )
        for result in turn.get("tool_results") or []:
            lines.extend(
                [
                    f"- `{result.get('name')}` latency_ms={result.get('latency_ms')} args=`{json.dumps(result.get('args') or {}, ensure_ascii=False)}`",
                    "```json",
                    json.dumps(result.get("result") or {}, ensure_ascii=False, indent=2),
                    "```",
                ]
            )
        lines.extend(
            [
                "",
                "### Runtime Final Response",
                "```text",
                str(turn.get("runtime_final_response") or ""),
                "```",
                "",
                "### Memory After Turn",
                "```json",
                json.dumps(turn.get("active_working_memory_after_turn") or {}, ensure_ascii=False, indent=2),
                "```",
            ]
        )
    return "\n".join(lines)


def _summary_row(payload: Dict[str, Any], *, artifact_paths: Dict[str, str], pricing: Dict[str, Any]) -> Dict[str, Any]:
    scenario = payload.get("scenario") or {}
    runtime_payload = payload.get("runtime_payload") or {}
    turns = runtime_payload.get("turns") or []
    usage_summary = runtime_payload.get("llm_usage_summary") or {}
    cost_summary = runtime_payload.get("cost_summary") or _scenario_cost_summary(payload, pricing=pricing)
    model_metrics = _model_metrics_from_cost_summary(cost_summary)
    latency = {
        "model_total": sum(int((call.get("model_output") or {}).get("latency_ms") or 0) for turn in turns for call in turn.get("llm_calls") or []),
        "tool_total": sum(int(result.get("latency_ms") or 0) for turn in turns for result in turn.get("tool_results") or []),
    }
    return {
        "scenario_id": scenario.get("id"),
        "category": scenario.get("category"),
        "tags": scenario.get("tags") or [],
        "turn_count": len(turns),
        "tool_sequence": [
            result.get("name")
            for turn in turns
            for result in turn.get("tool_results") or []
            if result.get("name")
        ],
        "latency_ms": latency,
        "usage_summary": usage_summary,
        "metrics": {
            "llm_call_count": _int_or_zero(model_metrics.get("llm_call_count")),
            "prompt_tokens": _int_or_zero(model_metrics.get("prompt_tokens")),
            "cache_read_input_tokens": _int_or_zero(model_metrics.get("cache_read_input_tokens")),
            "uncached_prompt_tokens": _int_or_zero(model_metrics.get("uncached_prompt_tokens")),
            "cache_hit_rate": float(model_metrics.get("cache_hit_rate") or 0),
            "completion_tokens": _int_or_zero(model_metrics.get("completion_tokens")),
            "total_tokens": _int_or_zero(model_metrics.get("total_tokens")),
            "reasoning_tokens": _int_or_zero(model_metrics.get("reasoning_tokens")),
            "model_latency_ms": _int_or_zero(model_metrics.get("model_latency_ms")),
            "tool_latency_ms": _int_or_zero(latency.get("tool_total")),
            "tool_call_count": sum(1 for turn in turns for result in turn.get("tool_results") or [] if result.get("name")),
            "estimated_cost_usd": cost_summary.get("estimated_cost_usd") or 0.0,
        },
        "cost_summary": cost_summary,
        "models": sorted((cost_summary.get("by_model") or {}).keys()),
        "artifact_paths": artifact_paths,
    }


def _render_summary_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        "# Runtime V7 Live Test Pack Summary",
        "",
        f"Run: `{summary.get('run_id')}`",
        f"Generated: `{summary.get('generated_at')}`",
        f"Mode: `{summary.get('mode')}`",
        f"Aborted: `{bool(summary.get('aborted'))}`",
        "",
        "## Guardrails",
        "```json",
        json.dumps(summary.get("guardrails") or {}, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    if summary.get("aborted"):
        lines.extend(
            [
                "## Abort",
                "```json",
                json.dumps(summary.get("abort") or {}, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    lines.extend(
        [
        "## Totals",
        "```json",
        json.dumps(summary.get("totals") or {}, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Pricing",
        "```json",
        json.dumps(summary.get("pricing") or {}, ensure_ascii=False, indent=2),
        "```",
        "",
        "| Scenario | Turns | LLM | Prompt | Cache Read | Cache Hit | Uncached | Total | Cost USD | Model ms | Tool ms | Models | Tools | Artifact |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
        ]
    )
    for row in summary.get("rows") or []:
        artifacts = row.get("artifact_paths") or {}
        metrics = row.get("metrics") or {}
        lines.append(
            "| {id} | {turns} | {llm_calls} | {prompt_tokens} | {cache_read} | {cache_hit} | {uncached} | {total_tokens} | {cost_usd} | {model_ms} | {tool_ms} | {models} | {tools} | {artifact} |".format(
                id=row.get("scenario_id"),
                turns=row.get("turn_count") or 0,
                llm_calls=metrics.get("llm_call_count") or 0,
                prompt_tokens=metrics.get("prompt_tokens") or 0,
                cache_read=metrics.get("cache_read_input_tokens") or 0,
                cache_hit=_format_percent(metrics.get("cache_hit_rate")),
                uncached=metrics.get("uncached_prompt_tokens") or 0,
                total_tokens=metrics.get("total_tokens") or 0,
                cost_usd=_format_usd(metrics.get("estimated_cost_usd")),
                model_ms=metrics.get("model_latency_ms") or 0,
                tool_ms=metrics.get("tool_latency_ms") or 0,
                models=", ".join(str(value) for value in row.get("models") or []),
                tools=", ".join(str(value) for value in row.get("tool_sequence") or []),
                artifact=artifacts.get("markdown") or "",
            )
        )
    return "\n".join(lines)


def _aggregate_usage(turns: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    totals: Dict[str, Any] = {
        "turn_count": len(turns),
        "llm_call_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cache_read_input_tokens": 0,
        "uncached_prompt_tokens": 0,
        "latency_ms": 0,
        "reasoning_tokens": 0,
    }
    for turn in turns:
        for call in turn.get("llm_calls") or []:
            totals["llm_call_count"] += 1
            usage_summary = call.get("usage_summary") or {}
            for key in [
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "cache_read_input_tokens",
                "uncached_prompt_tokens",
                "latency_ms",
                "reasoning_tokens",
            ]:
                totals[key] += _int_or_zero(usage_summary.get(key))
    totals["cache_hit_rate"] = _ratio(totals["cache_read_input_tokens"], totals["prompt_tokens"])
    return totals


def _aggregate_summary_rows(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    totals: Dict[str, Any] = {
        "scenario_count": len(rows),
        "turn_count": 0,
        "llm_call_count": 0,
        "tool_call_count": 0,
        "prompt_tokens": 0,
        "cache_read_input_tokens": 0,
        "uncached_prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": 0,
        "model_latency_ms": 0,
        "tool_latency_ms": 0,
        "estimated_cost_usd": 0.0,
        "estimated_cost_available": True,
        "missing_pricing_models": [],
    }
    missing_models: List[str] = []
    for row in rows:
        metrics = row.get("metrics") or {}
        totals["turn_count"] += _int_or_zero(row.get("turn_count"))
        for key in [
            "llm_call_count",
            "tool_call_count",
            "prompt_tokens",
            "cache_read_input_tokens",
            "uncached_prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "reasoning_tokens",
            "model_latency_ms",
            "tool_latency_ms",
        ]:
            totals[key] += _int_or_zero(metrics.get(key))
        totals["estimated_cost_usd"] += float(metrics.get("estimated_cost_usd") or 0.0)
        cost_summary = row.get("cost_summary") or {}
        if cost_summary.get("missing_pricing_models"):
            missing_models.extend(str(model) for model in cost_summary.get("missing_pricing_models") or [])
        if cost_summary.get("estimated_cost_available") is False:
            totals["estimated_cost_available"] = False
    totals["cache_hit_rate"] = _ratio(totals["cache_read_input_tokens"], totals["prompt_tokens"])
    totals["estimated_cost_usd"] = round(float(totals["estimated_cost_usd"]), 8)
    totals["missing_pricing_models"] = sorted(set(missing_models))
    return totals


def _scenario_cost_summary(payload: Dict[str, Any], *, pricing: Dict[str, Any]) -> Dict[str, Any]:
    records = _model_usage_records(payload)
    by_model: Dict[str, Dict[str, Any]] = {}
    by_component: Dict[str, Dict[str, Any]] = {}
    missing_pricing: List[str] = []
    total_cost = 0.0
    for record in records:
        estimate = _estimate_record_cost(record, pricing=pricing)
        record.update(estimate)
        total_cost += float(estimate.get("estimated_cost_usd") or 0.0)
        if estimate.get("pricing_found") is False:
            missing_pricing.append(str(record.get("model") or "unknown"))
        _add_cost_rollup(by_model, str(record.get("model") or "unknown"), record)
        _add_cost_rollup(by_component, str(record.get("component") or "unknown"), record)
    return {
        "estimated_cost_usd": round(total_cost, 8),
        "currency": str(pricing.get("currency") or "USD"),
        "pricing_profile": pricing.get("profile"),
        "estimated_cost_available": not missing_pricing,
        "missing_pricing_models": sorted(set(missing_pricing)),
        "by_model": by_model,
        "by_component": by_component,
        "model_usage_records": records,
        "notes": list(pricing.get("notes") or []),
    }


def _model_usage_records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    runtime_payload = payload.get("runtime_payload") or {}
    run_config = payload.get("run_config") or {}
    records: List[Dict[str, Any]] = []
    for turn in runtime_payload.get("turns") or []:
        turn_id = str(turn.get("turn_id") or "")
        for call in turn.get("llm_calls") or []:
            response = call.get("model_output") or {}
            usage_summary = call.get("usage_summary") or _usage_summary_from_usage(
                response.get("usage") or {},
                response.get("cache_usage") or {},
                latency_ms=response.get("latency_ms"),
            )
            records.append(
                _usage_record(
                    component=str(call.get("component") or "main_tool_loop"),
                    model=str(response.get("model") or payload.get("model") or ""),
                    turn_id=turn_id,
                    usage_summary=usage_summary,
                )
            )

        extraction = turn.get("background_signal_extraction") or {}
        if extraction.get("model_used"):
            records.append(
                _usage_record(
                    component="background_signal_extraction",
                    model=str(extraction.get("model") or run_config.get("background_signal_model") or ""),
                    turn_id=turn_id,
                    usage_summary=_usage_summary_from_usage(
                        extraction.get("model_usage") or {},
                        extraction.get("model_cache_usage") or {},
                        latency_ms=extraction.get("model_latency_ms"),
                    ),
                )
            )

        memory = turn.get("active_working_memory_after_turn") or {}
        memory_meta = memory.get("metadata") if isinstance(memory.get("metadata"), dict) else {}
        if memory_meta and memory_meta.get("usage"):
            records.append(
                _usage_record(
                    component="active_working_memory",
                    model=str(memory_meta.get("model") or run_config.get("memory_model") or ""),
                    turn_id=turn_id,
                    usage_summary=_usage_summary_from_usage(
                        memory_meta.get("usage") or {},
                        memory_meta.get("cache_usage") or {},
                        latency_ms=memory_meta.get("latency_ms"),
                    ),
                )
            )

        image_evidence = turn.get("image_evidence") or {}
        for ref in image_evidence.get("external_evidence_refs") or []:
            if not isinstance(ref, dict):
                continue
            model_response = ref.get("model_response") if isinstance(ref.get("model_response"), dict) else {}
            if model_response.get("usage"):
                records.append(
                    _usage_record(
                        component="image_evidence",
                        model=str(model_response.get("model") or run_config.get("image_evidence_model") or ""),
                        turn_id=turn_id,
                        usage_summary=_usage_summary_from_usage(
                            model_response.get("usage") or {},
                            model_response.get("cache_usage") or {},
                            latency_ms=model_response.get("latency_ms"),
                        ),
                    )
                )
    return records


def _attach_cost_breakdowns(payload: Dict[str, Any], *, pricing: Dict[str, Any]) -> None:
    runtime_payload = payload.get("runtime_payload") or {}
    run_config = payload.get("run_config") or {}
    default_model = str(payload.get("model") or run_config.get("model") or "")
    all_records: List[Dict[str, Any]] = []
    for turn in runtime_payload.get("turns") or []:
        turn_id = str(turn.get("turn_id") or "")
        turn_records: List[Dict[str, Any]] = []
        for call in turn.get("llm_calls") or []:
            response = call.get("model_output") or {}
            usage_summary = call.get("usage_summary") or _usage_summary_from_usage(
                response.get("usage") or {},
                response.get("cache_usage") or {},
                latency_ms=response.get("latency_ms"),
            )
            record = _usage_record(
                component=str(call.get("component") or "main_tool_loop"),
                model=str(response.get("model") or default_model),
                turn_id=turn_id,
                usage_summary=usage_summary,
            )
            record.update(_estimate_record_cost(record, pricing=pricing))
            call["cost_summary"] = record
            turn_records.append(record)

        extraction = turn.get("background_signal_extraction") or {}
        if extraction.get("model_used"):
            record = _usage_record(
                component="background_signal_extraction",
                model=str(extraction.get("model") or run_config.get("background_signal_model") or ""),
                turn_id=turn_id,
                usage_summary=_usage_summary_from_usage(
                    extraction.get("model_usage") or {},
                    extraction.get("model_cache_usage") or {},
                    latency_ms=extraction.get("model_latency_ms"),
                ),
            )
            record.update(_estimate_record_cost(record, pricing=pricing))
            extraction["cost_summary"] = record
            turn_records.append(record)

        memory = turn.get("active_working_memory_after_turn") or {}
        memory_meta = memory.get("metadata") if isinstance(memory.get("metadata"), dict) else {}
        if memory_meta and memory_meta.get("usage"):
            record = _usage_record(
                component="active_working_memory",
                model=str(memory_meta.get("model") or run_config.get("memory_model") or ""),
                turn_id=turn_id,
                usage_summary=_usage_summary_from_usage(
                    memory_meta.get("usage") or {},
                    memory_meta.get("cache_usage") or {},
                    latency_ms=memory_meta.get("latency_ms"),
                ),
            )
            record.update(_estimate_record_cost(record, pricing=pricing))
            memory_meta["cost_summary"] = record
            turn_records.append(record)

        image_evidence = turn.get("image_evidence") or {}
        for ref in image_evidence.get("external_evidence_refs") or []:
            if not isinstance(ref, dict):
                continue
            model_response = ref.get("model_response") if isinstance(ref.get("model_response"), dict) else {}
            if not model_response.get("usage"):
                continue
            record = _usage_record(
                component="image_evidence",
                model=str(model_response.get("model") or run_config.get("image_evidence_model") or ""),
                turn_id=turn_id,
                usage_summary=_usage_summary_from_usage(
                    model_response.get("usage") or {},
                    model_response.get("cache_usage") or {},
                    latency_ms=model_response.get("latency_ms"),
                ),
            )
            record.update(_estimate_record_cost(record, pricing=pricing))
            model_response["cost_summary"] = record
            turn_records.append(record)

        turn["cost_summary"] = _cost_summary_from_records(turn_records, pricing=pricing)
        turn["all_model_usage_summary"] = _model_usage_summary_from_records(turn_records)
        all_records.extend(turn_records)
    runtime_payload["turn_cost_summary"] = _cost_summary_from_records(all_records, pricing=pricing)
    runtime_payload["all_model_usage_summary"] = _model_usage_summary_from_records(all_records)


def _usage_record(*, component: str, model: str, turn_id: str, usage_summary: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "component": component,
        "turn_id": turn_id,
        "model": _normalize_model_name(model),
        "prompt_tokens": _int_or_zero(usage_summary.get("prompt_tokens")),
        "cache_read_input_tokens": _int_or_zero(usage_summary.get("cache_read_input_tokens")),
        "uncached_prompt_tokens": _int_or_zero(usage_summary.get("uncached_prompt_tokens")),
        "completion_tokens": _int_or_zero(usage_summary.get("completion_tokens")),
        "reasoning_tokens": _int_or_zero(usage_summary.get("reasoning_tokens")),
        "total_tokens": _int_or_zero(usage_summary.get("total_tokens")),
        "latency_ms": _int_or_zero(usage_summary.get("latency_ms")),
    }


def _usage_summary_from_usage(usage: Dict[str, Any], cache_usage: Dict[str, Any], *, latency_ms: Any = 0) -> Dict[str, Any]:
    prompt_tokens = _int_or_zero(usage.get("prompt_tokens"))
    completion_tokens = _int_or_zero(usage.get("completion_tokens"))
    total_tokens = _int_or_zero(usage.get("total_tokens"))
    cache_read = _int_or_zero(
        cache_usage.get("cache_read_input_tokens")
        or usage.get("cache_read_input_tokens")
        or _nested_get(usage, "prompt_tokens_details", "cached_tokens")
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cache_read_input_tokens": cache_read,
        "uncached_prompt_tokens": max(prompt_tokens - cache_read, 0),
        "reasoning_tokens": _int_or_zero(
            cache_usage.get("reasoning_tokens")
            or usage.get("reasoning_tokens")
            or _nested_get(usage, "completion_tokens_details", "reasoning_tokens")
        ),
        "latency_ms": _int_or_zero(latency_ms),
    }


def _estimate_record_cost(record: Dict[str, Any], *, pricing: Dict[str, Any]) -> Dict[str, Any]:
    model = str(record.get("model") or "").strip()
    rates = _pricing_for_model(model, pricing=pricing)
    if not rates:
        return {
            "pricing_found": False,
            "estimated_cost_usd": 0.0,
            "input_cost_usd": 0.0,
            "cached_input_cost_usd": 0.0,
            "output_cost_usd": 0.0,
            "output_billable_tokens": _int_or_zero(record.get("completion_tokens")),
        }
    uncached_input_tokens = _int_or_zero(record.get("uncached_prompt_tokens"))
    cached_input_tokens = _int_or_zero(record.get("cache_read_input_tokens"))
    completion_tokens = _int_or_zero(record.get("completion_tokens"))
    reasoning_tokens = _int_or_zero(record.get("reasoning_tokens"))
    output_billable_tokens = max(completion_tokens, reasoning_tokens)
    input_cost = uncached_input_tokens * float(rates.get("input_per_1m") or 0.0) / 1_000_000
    cached_cost = cached_input_tokens * float(rates.get("cached_input_per_1m") or 0.0) / 1_000_000
    output_cost = output_billable_tokens * float(rates.get("output_per_1m") or 0.0) / 1_000_000
    return {
        "pricing_found": True,
        "rate_per_1m": dict(rates),
        "output_billable_tokens": output_billable_tokens,
        "input_cost_usd": round(input_cost, 10),
        "cached_input_cost_usd": round(cached_cost, 10),
        "output_cost_usd": round(output_cost, 10),
        "estimated_cost_usd": round(input_cost + cached_cost + output_cost, 10),
    }


def _cost_summary_from_records(records: Sequence[Dict[str, Any]], *, pricing: Dict[str, Any]) -> Dict[str, Any]:
    by_model: Dict[str, Dict[str, Any]] = {}
    by_component: Dict[str, Dict[str, Any]] = {}
    missing_pricing: List[str] = []
    total_cost = 0.0
    for record in records:
        if "estimated_cost_usd" not in record:
            record.update(_estimate_record_cost(record, pricing=pricing))
        total_cost += float(record.get("estimated_cost_usd") or 0.0)
        if record.get("pricing_found") is False:
            missing_pricing.append(str(record.get("model") or "unknown"))
        _add_cost_rollup(by_model, str(record.get("model") or "unknown"), record)
        _add_cost_rollup(by_component, str(record.get("component") or "unknown"), record)
    return {
        "estimated_cost_usd": round(total_cost, 8),
        "currency": str(pricing.get("currency") or "USD"),
        "pricing_profile": pricing.get("profile"),
        "estimated_cost_available": not missing_pricing,
        "missing_pricing_models": sorted(set(missing_pricing)),
        "by_model": by_model,
        "by_component": by_component,
        "model_usage_records": list(records),
    }


def _model_usage_summary_from_records(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    totals: Dict[str, Any] = {
        "model_call_count": 0,
        "prompt_tokens": 0,
        "cache_read_input_tokens": 0,
        "uncached_prompt_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "latency_ms": 0,
    }
    for record in records:
        if not isinstance(record, dict):
            continue
        totals["model_call_count"] += 1
        for field_name in [
            "prompt_tokens",
            "cache_read_input_tokens",
            "uncached_prompt_tokens",
            "completion_tokens",
            "reasoning_tokens",
            "total_tokens",
            "latency_ms",
        ]:
            totals[field_name] += _int_or_zero(record.get(field_name))
    totals["cache_hit_rate"] = _ratio(totals["cache_read_input_tokens"], totals["prompt_tokens"])
    return totals


def _add_cost_rollup(target: Dict[str, Dict[str, Any]], key: str, record: Dict[str, Any]) -> None:
    row = target.setdefault(
        key,
        {
            "call_count": 0,
            "prompt_tokens": 0,
            "cache_read_input_tokens": 0,
            "uncached_prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "output_billable_tokens": 0,
            "estimated_cost_usd": 0.0,
            "input_cost_usd": 0.0,
            "cached_input_cost_usd": 0.0,
            "output_cost_usd": 0.0,
            "latency_ms": 0,
        },
    )
    row["call_count"] += 1
    for field_name in [
        "prompt_tokens",
        "cache_read_input_tokens",
        "uncached_prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "total_tokens",
        "output_billable_tokens",
        "latency_ms",
    ]:
        row[field_name] += _int_or_zero(record.get(field_name))
    for field_name in ["estimated_cost_usd", "input_cost_usd", "cached_input_cost_usd", "output_cost_usd"]:
        row[field_name] = round(float(row[field_name]) + float(record.get(field_name) or 0.0), 10)


def _model_metrics_from_cost_summary(cost_summary: Dict[str, Any]) -> Dict[str, Any]:
    totals = {
        "llm_call_count": 0,
        "prompt_tokens": 0,
        "cache_read_input_tokens": 0,
        "uncached_prompt_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "model_latency_ms": 0,
    }
    for record in cost_summary.get("model_usage_records") or []:
        if not isinstance(record, dict):
            continue
        totals["llm_call_count"] += 1
        totals["prompt_tokens"] += _int_or_zero(record.get("prompt_tokens"))
        totals["cache_read_input_tokens"] += _int_or_zero(record.get("cache_read_input_tokens"))
        totals["uncached_prompt_tokens"] += _int_or_zero(record.get("uncached_prompt_tokens"))
        totals["completion_tokens"] += _int_or_zero(record.get("completion_tokens"))
        totals["reasoning_tokens"] += _int_or_zero(record.get("reasoning_tokens"))
        totals["total_tokens"] += _int_or_zero(record.get("total_tokens"))
        totals["model_latency_ms"] += _int_or_zero(record.get("latency_ms"))
    totals["cache_hit_rate"] = _ratio(totals["cache_read_input_tokens"], totals["prompt_tokens"])
    return totals


def _pricing_for_model(model: str, *, pricing: Dict[str, Any]) -> Dict[str, Any]:
    models = pricing.get("models") if isinstance(pricing.get("models"), dict) else {}
    normalized = _normalize_model_name(model)
    candidates = [
        normalized,
        normalized.replace("gemini/", ""),
        normalized.replace("models/", ""),
    ]
    for candidate in candidates:
        if candidate in models and isinstance(models[candidate], dict):
            return dict(models[candidate])
    return {}


def _pricing_public_summary(pricing: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "profile": pricing.get("profile"),
        "currency": pricing.get("currency") or "USD",
        "unit": pricing.get("unit") or "per_1m_tokens",
        "source": pricing.get("source"),
        "models": dict(pricing.get("models") or {}),
        "notes": list(pricing.get("notes") or []),
    }


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _format_percent(value: Any) -> str:
    try:
        return f"{float(value or 0) * 100:.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def _format_usd(value: Any) -> str:
    try:
        return f"{float(value or 0):.6f}"
    except (TypeError, ValueError):
        return "0.000000"


def _nested_get(payload: Dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _normalize_model_name(model: str) -> str:
    normalized = str(model or "").strip().lower()
    if normalized.startswith("gemini/"):
        normalized = normalized[len("gemini/") :]
    return normalized


def _metadata(*, trace_id: str, scenario_id: str, component: str) -> Dict[str, Any]:
    return {
        "trace_id": trace_id,
        "session_id": f"runtime-v7-live-test-pack-{scenario_id}",
        "user_id": "local-live-test-pack-user",
        "component": component,
        "channel": "local_probe",
        "business_unit": "gulong",
        "scenario_id": scenario_id,
        "prompt_version": "runtime_v7_live_test_pack_v1",
        "slot_spec_version": "runtime_v7_live_test_pack_v1",
        "tool_policy_version": "runtime_v7_live_test_pack_v1",
        "renderer_version": "runtime_v7_cards_v1",
    }


if __name__ == "__main__":
    main()
