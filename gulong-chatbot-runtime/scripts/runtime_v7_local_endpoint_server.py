"""Run a safe local Runtime V7 endpoint with Cloud Run staging feature parity.

The launcher copies only literal, non-secret environment values from the current
staging service, then applies local safety overrides before importing the API
application. Secret-backed Cloud Run values are never read or printed; local
credentials continue to come from the selected dotenv file. This prevents local
customer-path probes from silently dropping guided surfaces or disabling
published brand knowledge because staging-only feature flags were absent.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Mapping

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DEFAULT_ENV_FILE = REPO_ROOT / "configs" / ".env"
REQUIRED_PARITY_KEYS = (
    "PROMO_STAGING_ROUTER_FLOW_NAMESPACE",
    "RUNTIME_V7_TURN_PLAN_ENABLED",
    "RUNTIME_V7_PROMO_CATALOG_ENABLED",
    "RUNTIME_V7_BRAND_KNOWLEDGE_ENABLED",
)
LOCAL_SAFETY_OVERRIDES = {
    "SERVICE_ENVIRONMENT": "staging",
    "STATUS": "staging",
    "RUNTIME_DELIVERY_MODE": "return_only",
    "RUNTIME_V7_APPLY_MANYCHAT_TAGS": "0",
    "RUNTIME_V7_FETCH_MANYCHAT_PROFILE": "0",
    "RUNTIME_V7_FETCH_MANYCHAT_MESSAGES": "0",
    "RUNTIME_V7_FOLLOWUP_SEND_ENABLED": "0",
    "LANGSMITH_TRACING": "false",
    "LANGCHAIN_TRACING_V2": "false",
}


def literal_cloud_run_environment(service_payload: Mapping[str, Any]) -> Dict[str, str]:
    """Return only plain Cloud Run env values, excluding secret references."""

    containers = (
        (((service_payload.get("spec") or {}).get("template") or {}).get("spec") or {}).get("containers")
        or []
    )
    if not containers or not isinstance(containers[0], Mapping):
        return {}
    output: Dict[str, str] = {}
    for item in containers[0].get("env") or []:
        if not isinstance(item, Mapping) or "value" not in item:
            continue
        name = str(item.get("name") or "").strip()
        value = str(item.get("value") or "")
        if name:
            output[name] = value
    return output


def parity_status(environment: Mapping[str, str]) -> Dict[str, bool]:
    """Return non-sensitive readiness booleans for customer-path evaluation."""

    return {
        key: bool(str(environment.get(key) or "").strip())
        for key in REQUIRED_PARITY_KEYS
    }


def load_staging_literal_environment(
    *, service: str, project: str, region: str
) -> Dict[str, str]:
    """Read the deployed service description through gcloud without mutations."""

    executable = shutil.which("gcloud.cmd") or shutil.which("gcloud")
    if not executable:
        raise RuntimeError("gcloud is required for --sync-staging-env")
    completed = subprocess.run(
        [
            executable,
            "run",
            "services",
            "describe",
            service,
            f"--project={project}",
            f"--region={region}",
            "--format=json",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return literal_cloud_run_environment(json.loads(completed.stdout))


def apply_local_evaluation_environment(
    staging_values: Mapping[str, str],
    *,
    release_version: str,
    git_sha: str,
) -> Dict[str, bool]:
    """Apply feature parity followed by non-delivery local safety overrides."""

    for name, value in staging_values.items():
        os.environ[name] = str(value)
    for name, value in LOCAL_SAFETY_OVERRIDES.items():
        os.environ[name] = value
    os.environ["RELEASE_VERSION"] = release_version
    os.environ["GIT_SHA"] = git_sha
    return parity_status(os.environ)


def _git_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def main() -> None:
    """Validate staging parity and start a return-only local uvicorn service."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--service", default="gulong-chatbot-runtime-staging")
    parser.add_argument("--project", default="gulong-chatbot-459723")
    parser.add_argument("--region", default="asia-southeast1")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--release-version", default="local-staging-parity-eval")
    parser.add_argument("--git-sha", default="")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument(
        "--sync-staging-env",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Copy literal non-secret feature configuration from deployed staging.",
    )
    args = parser.parse_args()

    env_file = Path(args.env_file).expanduser()
    if env_file.exists():
        load_dotenv(env_file, override=False)

    staging_values = (
        load_staging_literal_environment(
            service=args.service,
            project=args.project,
            region=args.region,
        )
        if args.sync_staging_env
        else {}
    )
    status = apply_local_evaluation_environment(
        staging_values,
        release_version=str(args.release_version),
        git_sha=str(args.git_sha or _git_sha()),
    )
    missing = [name for name, ready in status.items() if not ready]
    print(
        json.dumps(
            {
                "mode": "return_only_local_endpoint",
                "staging_feature_parity": status,
                "ready": not missing,
                "missing": missing,
                "host": args.host,
                "port": args.port,
            },
            ensure_ascii=False,
        )
    )
    if missing:
        raise SystemExit(
            "Local evaluator is missing staging feature configuration: "
            + ", ".join(missing)
        )
    if args.check_only:
        return

    import uvicorn

    uvicorn.run("apps.api.main:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
