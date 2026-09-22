from __future__ import annotations

from scripts.runtime_v7_local_endpoint_server import (
    LOCAL_SAFETY_OVERRIDES,
    REQUIRED_PARITY_KEYS,
    apply_local_evaluation_environment,
    literal_cloud_run_environment,
    parity_status,
)


def test_literal_cloud_run_environment_excludes_secret_references() -> None:
    payload = {
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "env": [
                                {
                                    "name": "PROMO_STAGING_ROUTER_FLOW_NAMESPACE",
                                    "value": "staging-router",
                                },
                                {
                                    "name": "GEMINI_API_KEY",
                                    "valueFrom": {"secretKeyRef": {"name": "gemini"}},
                                },
                            ]
                        }
                    ]
                }
            }
        }
    }

    assert literal_cloud_run_environment(payload) == {
        "PROMO_STAGING_ROUTER_FLOW_NAMESPACE": "staging-router"
    }


def test_parity_status_requires_guided_and_knowledge_features() -> None:
    environment = {key: "1" for key in REQUIRED_PARITY_KEYS}
    assert all(parity_status(environment).values())

    environment.pop("PROMO_STAGING_ROUTER_FLOW_NAMESPACE")
    assert parity_status(environment)["PROMO_STAGING_ROUTER_FLOW_NAMESPACE"] is False


def test_apply_local_evaluation_environment_forces_non_delivery(monkeypatch) -> None:
    for key in [*REQUIRED_PARITY_KEYS, *LOCAL_SAFETY_OVERRIDES]:
        monkeypatch.delenv(key, raising=False)
    staging = {key: "enabled" for key in REQUIRED_PARITY_KEYS}
    staging["RUNTIME_DELIVERY_MODE"] = "send_content"

    status = apply_local_evaluation_environment(
        staging,
        release_version="local-eval",
        git_sha="abc123",
    )

    assert all(status.values())
    assert LOCAL_SAFETY_OVERRIDES["RUNTIME_DELIVERY_MODE"] == "return_only"
    assert __import__("os").environ["RUNTIME_DELIVERY_MODE"] == "return_only"
    assert __import__("os").environ["RUNTIME_V7_APPLY_MANYCHAT_TAGS"] == "0"
