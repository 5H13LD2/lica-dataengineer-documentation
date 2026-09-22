"""Run a bounded, fixed-corpus Runtime V7 Background Signal retention probe.

This probe deliberately stops at the signal-extraction component boundary.  It
does not run ``RuntimeV7Harness`` or any product/service tools.  Each fixed
free-text turn is passed to ``build_commercial_state_context`` with the prior
normalized state from ``InMemoryBackgroundSignalLedgerStore``.  The resulting
turn state and durable ledger state are written to UTF-8 JSON/Markdown
artifacts before the only stdout output (the artifact paths).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime_v7.llm_gateway import RuntimeV7ProviderCallLimitExceeded
from runtime_v7.canonical_values import (
    CanonicalValuesProvider,
    RuntimeV7CanonicalValuesProvider,
)
from runtime_v7.service_tools import RuntimeV7ServiceTools
from runtime_v7.state_signal_schema import MULTI_VALUE_KEYS
from runtime_v7.state_signal_ledger import InMemoryBackgroundSignalLedgerStore
from runtime_v7.state_signals import (
    BackgroundSignalExtractionModelClient,
    RuntimeV7BackgroundSignalModelClient,
    build_commercial_state_context,
)


DEFAULT_PACK = REPO_ROOT / "test_packs" / "runtime_v7_signal_retention_probe.json"
DEFAULT_OUT_DIR = REPO_ROOT / "tmp" / "runtime_v7_signal_retention_probe"
DEFAULT_MODEL = os.environ.get(
    "RUNTIME_V7_BACKGROUND_SIGNAL_MODEL", "gemini/gemini-2.5-flash-lite"
)

# These dimensions are intentionally broad.  The pack validator checks that a
# fixed corpus exercises each one, while individual expected checks remain
# explicit per turn.
REQUIRED_COVERAGE_DIMENSIONS = {
    "tire_size",
    "brand",
    "car",
    "location",
    "contact_or_customer_info",
    "service_type",
    "schedule",
    "payment",
    "promo_interest",
    "correction_or_retraction",
    "conditional_or_question_only",
    "interruptions_5_plus",
}


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class SignalRetentionPackError(ValueError):
    """Raised when a retention probe pack is structurally incomplete."""


@dataclass
class ProbeCallGuard:
    """Count logical extraction calls and fail before exceeding the run cap.

    The live ``RuntimeV7BackgroundSignalModelClient`` receives this guard at
    its gateway, so provider transport retries also consume the same ceiling.
    A supplied fake/client is wrapped by ``_BudgetedSignalModelClient`` below
    to preserve that invariant in offline tests.
    """

    max_model_calls: int
    model_calls: int = 0
    call_log: List[Dict[str, Any]] = field(default_factory=list)
    current_scenario_id: str = ""
    current_turn_id: str = ""

    def __post_init__(self) -> None:
        self.max_model_calls = _positive_int(self.max_model_calls, "max_model_calls")

    @property
    def provider_call_count(self) -> int:
        """Compatibility property used by the live gateway and reports."""

        return int(self.model_calls)

    def reserve(self, *, scenario_id: str = "", turn_id: str = "") -> None:
        """Reserve one bounded provider call or fail before provider I/O."""

        attempted = self.model_calls + 1
        if attempted > self.max_model_calls:
            raise RuntimeV7ProviderCallLimitExceeded(
                max_provider_calls=self.max_model_calls,
                attempted_provider_calls=attempted,
            )
        self.model_calls = attempted
        self.call_log.append(
            {
                "model_call_index": attempted,
                "scenario_id": str(scenario_id or self.current_scenario_id or ""),
                "turn_id": str(turn_id or self.current_turn_id or ""),
            }
        )

    def set_context(self, *, scenario_id: str, turn_id: str) -> None:
        """Attach fixed-corpus coordinates to subsequent gateway calls."""

        self.current_scenario_id = str(scenario_id or "")
        self.current_turn_id = str(turn_id or "")

    def to_dict(self) -> Dict[str, Any]:
        """Return redacted call-budget telemetry for the probe artifact."""

        return {
            "max_model_calls_run": self.max_model_calls,
            "max_model_calls_per_run": self.max_model_calls,
            "model_calls_run": self.model_calls,
            "model_calls_per_run": self.model_calls,
            "remaining_model_calls": max(0, self.max_model_calls - self.model_calls),
            "call_log": list(self.call_log),
        }


class _BudgetedSignalModelClient:
    """Apply the run guard to a caller-supplied model client."""

    def __init__(
        self,
        delegate: BackgroundSignalExtractionModelClient,
        guard: ProbeCallGuard,
        *,
        scenario_id: str,
        turn_id: str,
    ) -> None:
        self.delegate = delegate
        self.guard = guard
        self.scenario_id = scenario_id
        self.turn_id = turn_id

    def extract_background_signals(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Charge the probe budget before delegating signal extraction."""

        self.guard.reserve(scenario_id=self.scenario_id, turn_id=self.turn_id)
        return self.delegate.extract_background_signals(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            metadata=metadata,
        )


def load_pack(path: Path | str) -> Dict[str, Any]:
    """Load and structurally validate a JSON retention pack."""

    pack_path = Path(path)
    try:
        payload = json.loads(pack_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SignalRetentionPackError(f"Pack not found: {pack_path}") from exc
    except json.JSONDecodeError as exc:
        raise SignalRetentionPackError(f"Pack is not valid JSON: {pack_path}: {exc}") from exc
    validate_pack(payload)
    return payload


def validate_pack(pack: Mapping[str, Any]) -> None:
    """Validate pack shape and corpus coverage without making model calls."""

    if not isinstance(pack, Mapping):
        raise SignalRetentionPackError("Pack root must be a JSON object")
    if not str(pack.get("pack_id") or "").strip():
        raise SignalRetentionPackError("Pack requires a non-empty pack_id")
    scenarios = pack.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise SignalRetentionPackError("Pack requires a non-empty scenarios list")

    declared_coverage = {
        _normalize_dimension_key(item)
        for item in (pack.get("coverage_dimensions") or [])
        if str(item).strip()
    }
    covered: set[str] = set()
    seen_ids: set[str] = set()
    for scenario_index, scenario in enumerate(scenarios):
        if not isinstance(scenario, Mapping):
            raise SignalRetentionPackError(f"Scenario {scenario_index} must be an object")
        scenario_id = str(scenario.get("id") or "").strip()
        if not scenario_id:
            raise SignalRetentionPackError(f"Scenario {scenario_index} requires id")
        if scenario_id in seen_ids:
            raise SignalRetentionPackError(f"Duplicate scenario id: {scenario_id}")
        seen_ids.add(scenario_id)
        turns = scenario.get("turns")
        if not isinstance(turns, list) or not turns:
            raise SignalRetentionPackError(f"{scenario_id}: turns must be a non-empty list")
        min_interruptions = _nonnegative_int(
            scenario.get("min_interruptions", 0),
            f"{scenario_id}.min_interruptions",
        )
        if len(turns) - 1 < min_interruptions:
            raise SignalRetentionPackError(
                f"{scenario_id}: expected at least {min_interruptions} interruption turns, got {len(turns) - 1}"
            )
        if min_interruptions >= 5:
            covered.add("interruptions_5_plus")
        dimensions = scenario.get("variation_dimensions")
        if not isinstance(dimensions, Mapping):
            raise SignalRetentionPackError(f"{scenario_id}: variation_dimensions must be an object")
        covered.update(_normalize_dimension_key(key) for key in dimensions.keys())
        covered.update(
            _normalize_dimension_key(item)
            for item in (scenario.get("coverage") or [])
            if str(item).strip()
        )
        for turn_index, turn in enumerate(turns):
            if isinstance(turn, str):
                turn = {"message": turn}
            if not isinstance(turn, Mapping):
                raise SignalRetentionPackError(f"{scenario_id}.turns[{turn_index}] must be an object or string")
            if not str(turn.get("message") or "").strip():
                raise SignalRetentionPackError(f"{scenario_id}.turns[{turn_index}] requires message")
            _validate_expectation_list(turn.get("required_durable_signals"), scenario_id, turn_index, "required")
            _validate_expectation_list(turn.get("forbidden_durable_signals"), scenario_id, turn_index, "forbidden")
        _validate_expectation_list(
            scenario.get("final_required_durable_signals"), scenario_id, None, "final_required"
        )
        _validate_expectation_list(
            scenario.get("final_forbidden_durable_signals"), scenario_id, None, "final_forbidden"
        )

    missing = REQUIRED_COVERAGE_DIMENSIONS - (declared_coverage | covered)
    if missing:
        raise SignalRetentionPackError(
            "Pack is missing required fixed-corpus coverage dimensions: "
            + ", ".join(sorted(missing))
        )


def _validate_expectation_list(
    value: Any,
    scenario_id: str,
    turn_index: Optional[int],
    label: str,
) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        location = f"{scenario_id}.turns[{turn_index}]" if turn_index is not None else scenario_id
        raise SignalRetentionPackError(f"{location}.{label}_durable_signals must be a list")
    for index, expectation in enumerate(value):
        if isinstance(expectation, str):
            if "=" not in expectation and not expectation.strip():
                raise SignalRetentionPackError(f"{scenario_id}: empty {label} expectation at {index}")
            continue
        if not isinstance(expectation, Mapping):
            raise SignalRetentionPackError(
                f"{scenario_id}: {label} expectation {index} must be a string or object"
            )
        if not str(expectation.get("key") or "").strip():
            raise SignalRetentionPackError(
                f"{scenario_id}: {label} expectation {index} requires key"
            )


def run_probe(
    pack: Mapping[str, Any],
    *,
    model: str = DEFAULT_MODEL,
    model_client: Optional[BackgroundSignalExtractionModelClient] = None,
    model_retry_attempts: int = 0,
    model_extraction_policy: str = "always",
    max_model_calls_run: int = 60,
    model_timeout_s: float = 30.0,
    temperature: float = 0.0,
    reasoning_effort: Optional[str] = "low",
    enable_context_cache: bool = False,
    context_cache_ttl: str = "3600s",
    scenario_ids: Optional[Sequence[str]] = None,
    tags: Optional[Sequence[str]] = None,
    limit: int = 0,
) -> Dict[str, Any]:
    """Execute selected fixed scenarios and return a JSON-safe report payload."""

    os.environ.setdefault("LANGSMITH_TRACING", "false")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
    validate_pack(pack)
    retry_attempts = _nonnegative_int(model_retry_attempts, "model_retry_attempts")
    max_calls = _positive_int(max_model_calls_run, "max_model_calls_run")
    timeout_s = max(1.0, min(float(model_timeout_s), 60.0))
    selected = select_scenarios(
        pack.get("scenarios") or [],
        scenario_ids=scenario_ids or [],
        tags=tags or [],
        limit=limit,
    )
    guard = ProbeCallGuard(max_calls)
    run_id = f"runtime_v7_signal_retention_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    configured_client: Optional[BackgroundSignalExtractionModelClient]
    if model_client is None:
        configured_client = RuntimeV7BackgroundSignalModelClient(
            model=str(model or DEFAULT_MODEL),
            temperature=float(temperature),
            max_tokens=2400,
            timeout_s=timeout_s,
            enable_context_cache=bool(enable_context_cache),
            context_cache_ttl=str(context_cache_ttl or "3600s"),
            reasoning_effort=_normalize_reasoning_effort(reasoning_effort),
            metadata={
                "component": "runtime_v7_signal_retention_probe",
                "pack_id": str(pack.get("pack_id") or ""),
                "run_id": run_id,
            },
            provider_call_guard=guard,
        )
    else:
        configured_client = model_client

    canonical_values_provider = (
        RuntimeV7CanonicalValuesProvider()
        if model_client is None
        else None
    )
    location_resolver = (
        RuntimeV7ServiceTools(
            canonical_values_provider=canonical_values_provider,
        ).location_resolver
        if canonical_values_provider is not None
        else None
    )

    rows: List[Dict[str, Any]] = []
    aborted: Optional[Dict[str, Any]] = None
    for scenario in selected:
        scenario_id = str(scenario.get("id") or "scenario")
        # A fake or custom client has no gateway guard.  Apply the same hard
        # cap at the extraction boundary for offline validation.  The scenario
        # runner retains all completed turns if the cap trips mid-scenario.
        row = _run_scenario(
            scenario,
            model_client=configured_client,
            guard=guard,
            model_retry_attempts=retry_attempts,
            model_extraction_policy=model_extraction_policy,
            wrap_model_client=model_client is not None,
            canonical_values_provider=canonical_values_provider,
            location_resolver=location_resolver,
        )
        rows.append(row)
        if row.get("aborted"):
            aborted = {
                "scenario_id": scenario_id,
                "reason": row.get("abort"),
                "guard": guard.to_dict(),
            }
            break

    return {
        "probe_version": "runtime_v7_signal_retention_probe_v1",
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pack_id": str(pack.get("pack_id") or ""),
        "model": str(model or DEFAULT_MODEL),
        "selected_scenario_ids": [str(item.get("id") or "") for item in selected],
        "run_config": {
            "model_retry_attempts": retry_attempts,
            "model_extraction_policy": str(model_extraction_policy or "always"),
            "max_model_calls_run": max_calls,
            "max_model_calls_per_run": max_calls,
            "model_timeout_s": timeout_s,
            "temperature": float(temperature),
            "reasoning_effort": _normalize_reasoning_effort(reasoning_effort),
            "context_cache_enabled": bool(enable_context_cache),
            "context_cache_ttl": str(context_cache_ttl or "3600s"),
            "component_boundary": "background_signal_extraction_only",
            "normalization_parity": "runtime_canonical_values_and_service_location_resolver",
            "adaptive_customer_simulation": False,
        },
        "guard": guard.to_dict(),
        "aborted": bool(aborted),
        "abort": aborted,
        "scenario_count": len(rows),
        "scenarios": rows,
        "totals": _aggregate_totals(rows),
    }


def _run_scenario(
    scenario: Mapping[str, Any],
    *,
    model_client: BackgroundSignalExtractionModelClient,
    guard: ProbeCallGuard,
    model_retry_attempts: int,
    model_extraction_policy: str,
    wrap_model_client: bool = False,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
    location_resolver: Optional[Any] = None,
) -> Dict[str, Any]:
    scenario_id = str(scenario.get("id") or "scenario")
    ledger = InMemoryBackgroundSignalLedgerStore()
    recent_turns: List[Dict[str, str]] = []
    turn_rows: List[Dict[str, Any]] = []
    scenario_started = time.perf_counter()
    scenario_calls_before = guard.model_calls
    scenario_abort: Optional[Dict[str, Any]] = None
    turns = list(scenario.get("turns") or [])
    for turn_index, raw_turn in enumerate(turns, start=1):
        turn = {"message": raw_turn} if isinstance(raw_turn, str) else dict(raw_turn)
        turn_id = str(turn.get("id") or f"turn_{turn_index:02d}")
        message = str(turn.get("message") or "")
        guard.set_context(scenario_id=scenario_id, turn_id=turn_id)
        previous_state = ledger.load(scenario_id)
        turn_client: BackgroundSignalExtractionModelClient = model_client
        if wrap_model_client:
            turn_client = _BudgetedSignalModelClient(
                model_client,
                guard,
                scenario_id=scenario_id,
                turn_id=turn_id,
            )
        started = time.perf_counter()
        try:
            context = build_commercial_state_context(
                current_user_message=message,
                active_working_memory=str(
                    turn.get("active_working_memory")
                    or scenario.get("active_working_memory")
                    or ""
                ),
                recent_turns=recent_turns[-6:],
                previous_background_signals=previous_state,
                latest_product_observation=turn.get("latest_product_observation") or {},
                latest_service_observation=turn.get("latest_service_observation") or {},
                external_evidence_refs=turn.get("external_evidence_refs") or [],
                external_evidence_candidates=turn.get("external_evidence_candidates") or [],
                model_client=turn_client,
                canonical_values_provider=canonical_values_provider,
                location_resolver=location_resolver,
                model_extraction_policy=model_extraction_policy,
                model_retry_attempts=model_retry_attempts,
            )
        except RuntimeV7ProviderCallLimitExceeded as exc:
            scenario_abort = exc.diagnostic()
            break
        wall_latency_ms = int((time.perf_counter() - started) * 1000)
        signals = list(context.get("background_signals") or [])
        ledger.save(scenario_id, signals, turn_index=turn_index)
        durable_state = ledger.load(scenario_id)
        extraction = dict(context.get("background_signal_extraction") or {})
        extraction_report = {
            "status": str(extraction.get("status") or "not_called"),
            "attempts": int(extraction.get("model_attempts") or 0),
            "usage": _json_safe_dict(extraction.get("model_usage")),
            "cache_usage": _json_safe_dict(extraction.get("model_cache_usage")),
            "model_latency_ms": extraction.get("model_latency_ms"),
            "wall_latency_ms": wall_latency_ms,
            "retry_errors": list(extraction.get("model_retry_errors") or []),
            "candidate_count": int(extraction.get("model_candidate_count") or 0),
            "normalized_candidate_count": int(
                extraction.get("model_normalized_candidate_count") or 0
            ),
            "model_used": bool(extraction.get("model_used")),
            "mode": str(extraction.get("mode") or ""),
        }
        evaluation = evaluate_expectations(
            durable_state,
            required=turn.get("required_durable_signals") or [],
            forbidden=turn.get("forbidden_durable_signals") or [],
        )
        turn_rows.append(
            {
                "turn_index": turn_index,
                "turn_id": turn_id,
                "message": message,
                "extraction": extraction_report,
                "background_signals": signals,
                "durable_state_after_turn": durable_state,
                "expectation_evaluation": evaluation,
                "model_calls_run_after_turn": guard.model_calls,
            }
        )
        recent_turns.append({"role": "user", "content": message})

    final_state = ledger.load(scenario_id)
    final_evaluation = evaluate_expectations(
        final_state,
        required=scenario.get("final_required_durable_signals") or [],
        forbidden=scenario.get("final_forbidden_durable_signals") or [],
    )
    failures = _collect_failures(turn_rows, final_evaluation)
    return {
        "scenario_id": scenario_id,
        "title": str(scenario.get("title") or scenario_id),
        "coverage": list(scenario.get("coverage") or []),
        "variation_dimensions": dict(scenario.get("variation_dimensions") or {}),
        "turn_count": len(turn_rows),
        "scenario_latency_ms": int((time.perf_counter() - scenario_started) * 1000),
        "model_calls_used": guard.model_calls - scenario_calls_before,
        "aborted": bool(scenario_abort),
        "abort": scenario_abort,
        "turns": turn_rows,
        "final_durable_state": final_state,
        "final_expectation_evaluation": final_evaluation,
        "passed": not failures,
        "failures": failures,
    }


def evaluate_expectations(
    durable_state: Sequence[Mapping[str, Any]],
    *,
    required: Sequence[Any],
    forbidden: Sequence[Any],
) -> Dict[str, Any]:
    """Evaluate key/value expectations against normalized durable state."""

    state = [dict(item) for item in durable_state if isinstance(item, Mapping)]
    required_checks = [_evaluate_one(state, item, should_exist=True) for item in required]
    forbidden_checks = [_evaluate_one(state, item, should_exist=False) for item in forbidden]
    return {
        "passed": all(item["passed"] for item in [*required_checks, *forbidden_checks]),
        "required": required_checks,
        "forbidden": forbidden_checks,
    }


def _evaluate_one(
    state: Sequence[Mapping[str, Any]],
    expectation: Any,
    *,
    should_exist: bool,
) -> Dict[str, Any]:
    key, expected_value = _parse_expectation(expectation)
    matches = [
        item
        for item in state
        if str(item.get("key") or "").strip().lower() == key
        and (
            expected_value is None
            or _value_matches(item.get("value"), expected_value, key=key)
        )
    ]
    present = bool(matches)
    passed = present if should_exist else not present
    return {
        "key": key,
        "expected_value": expected_value,
        "should_exist": should_exist,
        "present": present,
        "passed": passed,
        "observed_values": [item.get("value") for item in state if str(item.get("key") or "").strip().lower() == key],
    }


def _parse_expectation(expectation: Any) -> Tuple[str, Optional[str]]:
    if isinstance(expectation, Mapping):
        return (
            str(expectation.get("key") or "").strip().lower(),
            _clean_expected_value(expectation.get("value")),
        )
    text = str(expectation or "").strip()
    if "=" in text:
        key, value = text.split("=", 1)
        return key.strip().lower(), _clean_expected_value(value)
    return text.lower(), None


def _value_matches(observed: Any, expected: str, *, key: str = "") -> bool:
    observed_text = " ".join(str(observed or "").split()).casefold()
    expected_text = " ".join(str(expected or "").split()).casefold()
    if observed_text == expected_text:
        return True
    if key not in MULTI_VALUE_KEYS:
        return False
    # Only schema-declared multi-value signals use comma-separated members.
    # A single location such as "Imus, Cavite" is one composite value.
    return expected_text in {
        member.strip().casefold() for member in observed_text.split(",") if member.strip()
    }


def _clean_expected_value(value: Any) -> Optional[str]:
    if value in (None, "", []):
        return None
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip()) or None
    return " ".join(str(value).split()) or None


def select_scenarios(
    scenarios: Sequence[Mapping[str, Any]],
    *,
    scenario_ids: Sequence[str],
    tags: Sequence[str],
    limit: int = 0,
) -> List[Dict[str, Any]]:
    """Filter the fixed pack by explicit IDs and tags without changing order."""

    wanted_ids = {str(item).strip() for item in scenario_ids if str(item).strip()}
    wanted_tags = {str(item).strip() for item in tags if str(item).strip()}
    selected: List[Dict[str, Any]] = []
    for scenario in scenarios:
        scenario_id = str(scenario.get("id") or "")
        scenario_tags = {str(item).strip() for item in scenario.get("tags") or []}
        if wanted_ids and scenario_id not in wanted_ids:
            continue
        if wanted_tags and not wanted_tags.intersection(scenario_tags):
            continue
        selected.append(dict(scenario))
    if limit > 0:
        selected = selected[: int(limit)]
    if not selected:
        raise SignalRetentionPackError("No scenarios selected by the requested filters")
    return selected


def write_artifacts(payload: Mapping[str, Any], out_dir: Path | str) -> Dict[str, Path]:
    """Write full JSON and concise Markdown artifacts before any stdout."""

    root = Path(out_dir)
    run_id = str(payload.get("run_id") or "runtime_v7_signal_retention")
    target = root / run_id
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "signal_retention_probe.json"
    markdown_path = target / "signal_retention_probe.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json": json_path.resolve(), "markdown": markdown_path.resolve()}


def render_markdown(payload: Mapping[str, Any]) -> str:
    """Render a compact review summary without dropping JSON detail."""

    lines = [
        "# Runtime V7 Background Signal Retention Probe",
        "",
        f"- Pack: `{payload.get('pack_id')}`",
        f"- Run: `{payload.get('run_id')}`",
        f"- Scenarios completed: {payload.get('scenario_count', 0)}",
        f"- Model calls: {payload.get('guard', {}).get('model_calls_run', 0)} / {payload.get('guard', {}).get('max_model_calls_run', 0)}",
        f"- Aborted by call cap: `{bool(payload.get('aborted'))}`",
        "",
        "## Scenario results",
        "",
        "| Scenario | Turns | Calls | Result | Failures |",
        "|---|---:|---:|---|---:|",
    ]
    for row in payload.get("scenarios") or []:
        lines.append(
            "| `{}` | {} | {} | {} | {} |".format(
                row.get("scenario_id"),
                row.get("turn_count", 0),
                row.get("model_calls_used", 0),
                "PASS" if row.get("passed") else "CHECK",
                len(row.get("failures") or []),
            )
        )
    lines.extend(["", "## Final durable state", ""])
    for row in payload.get("scenarios") or []:
        lines.append(f"### `{row.get('scenario_id')}`")
        state = row.get("final_durable_state") or []
        if not state:
            lines.append("- _(empty)_")
        else:
            for signal in state:
                lines.append(
                    f"- `{signal.get('key')}` = `{signal.get('value')}` "
                    f"({signal.get('relation', 'asserted')}; {signal.get('status', '')})"
                )
        final_eval = row.get("final_expectation_evaluation") or {}
        lines.append(f"- Final expectation checks: **{'PASS' if final_eval.get('passed') else 'CHECK'}**")
        lines.append("")
    if payload.get("aborted"):
        lines.extend(["## Abort", "", f"```json\n{json.dumps(payload.get('abort'), ensure_ascii=False, indent=2)}\n```"])
    return "\n".join(lines).rstrip() + "\n"


def _collect_failures(turn_rows: Sequence[Mapping[str, Any]], final_evaluation: Mapping[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    for row in turn_rows:
        evaluation = row.get("expectation_evaluation") or {}
        if evaluation.get("passed"):
            continue
        failures.append(
            {
                "scope": f"turn:{row.get('turn_id')}",
                "required_missing": [
                    item for item in evaluation.get("required") or [] if not item.get("passed")
                ],
                "forbidden_present": [
                    item for item in evaluation.get("forbidden") or [] if not item.get("passed")
                ],
            }
        )
    if not final_evaluation.get("passed"):
        failures.append(
            {
                "scope": "final",
                "required_missing": [
                    item for item in final_evaluation.get("required") or [] if not item.get("passed")
                ],
                "forbidden_present": [
                    item for item in final_evaluation.get("forbidden") or [] if not item.get("passed")
                ],
            }
        )
    return failures


def _aggregate_totals(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return {
        "turns": sum(int(row.get("turn_count") or 0) for row in rows),
        "model_calls": sum(int(row.get("model_calls_used") or 0) for row in rows),
        "scenarios_passed": sum(1 for row in rows if row.get("passed")),
        "scenarios_with_failures": sum(1 for row in rows if not row.get("passed")),
        "expectation_failures": sum(len(row.get("failures") or []) for row in rows),
    }


def _normalize_dimension_key(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "vehicle": "car",
        "cars": "car",
        "vehicles": "car",
        "customer_info": "contact_or_customer_info",
        "contact_info": "contact_or_customer_info",
        "contact": "contact_or_customer_info",
        "corrections": "correction_or_retraction",
        "retractions": "correction_or_retraction",
        "correction_retraction": "correction_or_retraction",
        "conditional_question": "conditional_or_question_only",
        "conditional_questions": "conditional_or_question_only",
        "question_only": "conditional_or_question_only",
        "questions": "conditional_or_question_only",
        "interruption_5_plus": "interruptions_5_plus",
        "interruptions_5plus": "interruptions_5_plus",
    }
    return aliases.get(text, text)


def _json_safe_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _positive_int(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SignalRetentionPackError(f"{name} must be a positive integer") from exc
    if parsed < 1:
        raise SignalRetentionPackError(f"{name} must be a positive integer")
    return parsed


def _nonnegative_int(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SignalRetentionPackError(f"{name} must be a non-negative integer") from exc
    if parsed < 0:
        raise SignalRetentionPackError(f"{name} must be a non-negative integer")
    return parsed


def _normalize_reasoning_effort(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    if not text or text in {"provider_default", "provider-default", "default", "auto", "none", "disable"}:
        return None
    return text if text in {"minimal", "low", "medium", "high"} else None


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the bounded, artifact-first probe command-line interface."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", default=str(DEFAULT_PACK))
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-retry-attempts", type=int, default=0)
    parser.add_argument("--model-extraction-policy", choices=["always", "auto", "never"], default="always")
    parser.add_argument(
        "--max-model-calls-run",
        "--max-model-calls-per-run",
        dest="max_model_calls_run",
        type=int,
        default=60,
    )
    parser.add_argument("--model-timeout-s", type=float, default=30.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--reasoning-effort", default="low")
    parser.add_argument("--enable-context-cache", action="store_true")
    parser.add_argument("--context-cache-ttl", default="3600s")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--list", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run selected retention probes and return nonzero only for aborts."""

    os.environ.setdefault("LANGSMITH_TRACING", "false")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
    args = build_arg_parser().parse_args(argv)
    pack = load_pack(args.pack)
    scenarios = select_scenarios(
        pack.get("scenarios") or [],
        scenario_ids=args.scenario,
        tags=args.tag,
        limit=args.limit,
    )
    if args.list:
        for scenario in scenarios:
            print(f"{scenario.get('id')}: {scenario.get('title', '')}")
        return 0
    payload = run_probe(
        pack,
        model=args.model,
        model_retry_attempts=args.model_retry_attempts,
        model_extraction_policy=args.model_extraction_policy,
        max_model_calls_run=args.max_model_calls_run,
        model_timeout_s=args.model_timeout_s,
        temperature=args.temperature,
        reasoning_effort=args.reasoning_effort,
        enable_context_cache=args.enable_context_cache,
        context_cache_ttl=args.context_cache_ttl,
        scenario_ids=args.scenario,
        tags=args.tag,
        limit=args.limit,
    )
    artifacts = write_artifacts(payload, args.out_dir)
    # Artifact-first: stdout contains paths only after both files are durable.
    print(json.dumps({key: str(path) for key, path in artifacts.items()}, ensure_ascii=False, indent=2))
    return 2 if payload.get("aborted") else 0


if __name__ == "__main__":  # pragma: no cover - exercised through CLI smoke only
    raise SystemExit(main())
