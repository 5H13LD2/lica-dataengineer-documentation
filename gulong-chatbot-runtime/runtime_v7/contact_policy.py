"""Runtime V7 customer contact-number policy.

Contact routing depends on ManyChat/customer profile assignment, so the runtime
keeps this out of model-authored text and resolves it through a small policy
helper before rendering FAQ/tool answers.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict


JEANEL_AGENT_KEYS = {"jeanelco", "jeanel"}


def contact_answer_for_agent(agent_assigned: Any = "") -> str:
    """Return the customer-facing contact spiel for an assigned agent."""

    if _agent_key(agent_assigned) in JEANEL_AGENT_KEYS:
        return "\n".join(
            [
                "You may contact us here:",
                "📞 0945-371-9372 (Call/Text)",
                "📱 0995-018-2435 (Viber)",
            ]
        )
    return "\n".join(
        [
            "You may contact us here:",
            "📞 0956-701-9222",
        ]
    )


def get_business_contact(payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Return exact Gulong.PH contact details for the current customer profile."""

    payload = dict(payload or {})
    agent_assigned = agent_assigned_from_payload(payload)
    answer = contact_answer_for_agent(agent_assigned)
    evidence_digest = hashlib.sha256(answer.encode("utf-8")).hexdigest()[:16]
    return {
        "status": "ok",
        "domain": "general",
        "source_type": "contact_policy",
        "agent_assigned": agent_assigned,
        "question": str(payload.get("question") or "Gulong.PH contact number").strip(),
        "answer": answer,
        "evidence_ref": f"business_contact:{evidence_digest}",
        "generated_at": datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat(),
        "ttl_seconds": 86400,
        "note": "Runtime-owned contact details. The model should not rewrite phone numbers.",
    }


def agent_assigned_from_payload(payload: Dict[str, Any]) -> str:
    """Extract agent assignment from direct or runtime-injected tool payload."""

    for key in (
        "agent_assigned",
        "_profile_agent_assigned",
        "profile_agent_assigned",
        "assigned_agent",
        "sales_agent",
    ):
        value = str((payload or {}).get(key) or "").strip()
        if value:
            return value
    profile = (payload or {}).get("profile_fields")
    if isinstance(profile, dict):
        for key in ("agent_assigned", "_profile_agent_assigned", "assigned_agent", "sales_agent"):
            value = str(profile.get(key) or "").strip()
            if value:
                return value
    return ""


def _agent_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())
