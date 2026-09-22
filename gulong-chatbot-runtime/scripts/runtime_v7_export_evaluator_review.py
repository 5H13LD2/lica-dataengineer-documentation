"""Export a redacted Runtime V7 evaluator bundle for external review.

The private matrix artifact remains the diagnostic source of truth. This
export retains synthetic prompts, customer-visible rendering, aggregate health,
and tool names/statuses while excluding user/session/request identifiers, tool
arguments/results, raw failures, headers, and subprocess logs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime_v7.promotion_health_evaluator import (  # noqa: E402
    artifact_evidence_digest,
    load_json,
    score_release_candidate,
)

SAFE_VISIBLE_KEYS = frozenset(
    {
        "type",
        "text",
        "caption",
        "title",
        "subtitle",
        "description",
        "elements",
        "buttons",
        "items",
        "image",
        "images",
    }
)


def _sanitize_visible_content(value: Any) -> Any:
    """Keep display text/shape while removing actions, tokens, URLs, and IDs."""

    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_visible_content(item)
            for key, item in value.items()
            if str(key) in SAFE_VISIBLE_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_visible_content(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _failure_codes(value: Any) -> list[str]:
    """Expose stable failure classes without raw exception or provider text."""

    return sorted(
        {
            str(item or "unknown").split(":", 1)[0]
            for item in (value if isinstance(value, list) else [])
        }
    )


def review_output_dir(root: Path, run_id: str) -> Path:
    """Resolve a unique run directory without accepting path traversal."""

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", run_id):
        raise ValueError("unsafe run_id for output path")
    resolved_root = root.resolve()
    out_dir = (resolved_root / run_id).resolve()
    if out_dir.parent != resolved_root:
        raise ValueError("review output escaped configured root")
    return out_dir


def _visible_response(response: Mapping[str, Any]) -> Dict[str, Any]:
    """Project only customer-visible content and bounded technical evidence."""

    debug = response.get("debug") or {}
    return {
        "http_status": response.get("_probe_http_status"),
        "elapsed_ms": response.get("_probe_elapsed_ms"),
        "status": response.get("status"),
        "bubbles": list((response.get("response") or {}).values()),
        "content_messages": _sanitize_visible_content(
            response.get("content_messages") or []
        ),
        "tools": [
            {"name": item.get("name"), "status": item.get("status")}
            for item in debug.get("tool_calls") or []
            if isinstance(item, Mapping)
        ],
        "llm_usage_summary": debug.get("llm_usage_summary") or {},
    }


def _public_funnel_stages(value: Any) -> Dict[str, Any]:
    """Expose stage outcomes and bounded provenance without signal values."""

    if not isinstance(value, Mapping):
        return {}
    output: Dict[str, Any] = {}
    for name, stage in value.items():
        if not isinstance(stage, Mapping):
            continue
        evidence = stage.get("evidence") or {}
        public_evidence = {
            key: evidence.get(key)
            for key in (
                "boundary",
                "input_mode",
                "required_choice_type",
                "accepted_choice_type",
                "source_signal_keys",
                "rendered_location_request",
                "rendered_contact_request",
                "has_guided_location_action",
                "exclusion_reason",
            )
            if isinstance(evidence, Mapping) and key in evidence
        }
        signal_evidence = (
            evidence.get("signal_evidence") if isinstance(evidence, Mapping) else None
        )
        if isinstance(signal_evidence, Mapping):
            public_evidence["signal_evidence"] = {
                "ledger_present": signal_evidence.get("ledger_present") is True,
                "keys": signal_evidence.get("keys") or [],
                "sources_by_key": signal_evidence.get("sources_by_key") or {},
            }
        output[str(name)] = {
            "applicable": stage.get("applicable") is True,
            "passed": stage.get("passed") is True,
            "evidence": public_evidence,
        }
    return output


def build_review_bundle(
    artifact: Mapping[str, Any],
    *,
    baseline: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a data-minimized, externally reviewable evaluator artifact."""

    integrity = artifact.get("artifact_integrity") or {}
    expected_digest = str(integrity.get("evidence_digest") or "")
    actual_digest = artifact_evidence_digest(artifact)
    if not expected_digest or expected_digest != actual_digest:
        raise ValueError("source artifact integrity check failed")

    single_turn = []
    for row in artifact.get("single_turn_cases") or []:
        if not isinstance(row, Mapping):
            continue
        single_turn.append(
            {
                "case_id": row.get("case_id"),
                "domain": row.get("domain"),
                "variation_tags": row.get("variation_tags") or [],
                "customer_message": row.get("message"),
                "expected_contract": row.get("expected_contract") or {},
                "passed": row.get("passed") is True,
                "failure_codes": _failure_codes(row.get("failures")),
                "response": _visible_response(row.get("response") or {}),
            }
        )

    journeys = []
    for row in artifact.get("journeys") or []:
        if not isinstance(row, Mapping):
            continue
        steps = []
        for step in row.get("steps") or []:
            if not isinstance(step, Mapping):
                continue
            steps.append(
                {
                    "action": step.get("action"),
                    "customer_input": step.get("message") or step.get("token"),
                    "response": _visible_response(step.get("response") or {}),
                }
            )
        journeys.append(
            {
                "case_id": row.get("case_id"),
                "domain": row.get("domain"),
                "variation_tags": row.get("variation_tags") or [],
                "expected_contract": row.get("expected_contract") or {},
                "passed": row.get("passed") is True,
                "failure_codes": _failure_codes(row.get("failures")),
                "steps": steps,
            }
        )

    operational_funnel_scenarios = []
    for row in artifact.get("operational_funnel_scenarios") or []:
        if not isinstance(row, Mapping):
            continue
        steps = []
        for step in row.get("steps") or []:
            if not isinstance(step, Mapping):
                continue
            steps.append(
                {
                    "action": step.get("action"),
                    "customer_input": step.get("message") or step.get("token"),
                    "response": _visible_response(step.get("response") or {}),
                }
            )
        operational_funnel_scenarios.append(
            {
                "case_id": row.get("case_id"),
                "domain": row.get("domain"),
                "variation_tags": row.get("variation_tags") or [],
                "provenance": (row.get("expected_contract") or {}).get("provenance"),
                "passed": row.get("passed") is True,
                "failure_codes": _failure_codes(row.get("failures")),
                "funnel_stages": _public_funnel_stages(row.get("funnel_stages")),
                "steps": steps,
            }
        )

    profile = artifact.get("evaluation_profile") or {}
    health = score_release_candidate(artifact, baseline=baseline)
    mechanical = dict(health.get("mechanical") or {})
    mechanical["failure_evidence"] = [
        {
            "case_id": item.get("case_id"),
            "failure_codes": _failure_codes(item.get("failures")),
        }
        for item in mechanical.get("failure_evidence") or []
        if isinstance(item, Mapping)
    ]
    public_health = {
        key: health.get(key)
        for key in (
            "grade",
            "promotion_status",
            "blockers",
            "warnings",
            "technical",
            "metered_usage",
            "cs_structural_proxy",
            "preverified_scenario_contract",
            "operational_funnel",
            "artifact_integrity",
            "target_identity",
            "baseline_comparison",
            "evidence_limits",
        )
    }
    public_health["mechanical"] = mechanical
    return {
        "schema_version": "runtime_v7_evaluator_external_review_v1",
        "run_id": artifact.get("run_id"),
        "release_identity": {
            "environment": profile.get("expected_environment"),
            "release_version": profile.get("expected_release"),
            "git_sha": profile.get("expected_git_sha"),
        },
        "scenario_contract": artifact.get("scenario_contract") or {},
        "operational_funnel_contract": artifact.get("operational_funnel_contract")
        or {},
        "source_evidence_digest": expected_digest,
        "promotion_health": public_health,
        "single_turn_cases": single_turn,
        "journeys": journeys,
        "operational_funnel_scenarios": operational_funnel_scenarios,
        "redaction": {
            "excluded": [
                "user/session/request/trace identifiers",
                "tool arguments and results",
                "raw HTTP bodies and headers",
                "subprocess logs and local absolute paths",
            ]
        },
    }


def main() -> None:
    """Write one checksummed review bundle without publishing it externally."""

    parser = argparse.ArgumentParser()
    parser.add_argument("summary", help="Private evaluator summary.json")
    parser.add_argument("--baseline-summary", default="")
    parser.add_argument("--out-dir", default="tmp/runtime_v7_evaluator_review")
    args = parser.parse_args()

    source = Path(args.summary)
    artifact = load_json(source)
    baseline = load_json(Path(args.baseline_summary)) if args.baseline_summary else None
    bundle = build_review_bundle(artifact, baseline=baseline)
    run_id = str(bundle.get("run_id") or "unknown")
    out_dir = review_output_dir(Path(args.out_dir), run_id)
    out_dir.mkdir(parents=True, exist_ok=False)
    review_path = out_dir / "review_summary.json"
    review_path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    digest = hashlib.sha256(review_path.read_bytes()).hexdigest()
    manifest_path = out_dir / "review_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "runtime_v7_evaluator_review_bundle_v1",
                "run_id": run_id,
                "created_at": datetime.now(ZoneInfo("Asia/Manila")).isoformat(),
                "source_evidence_digest": bundle["source_evidence_digest"],
                "files": {
                    review_path.name: {
                        "sha256": digest,
                        "bytes": review_path.stat().st_size,
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "review_summary": str(review_path.resolve()),
                "review_manifest": str(manifest_path.resolve()),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
