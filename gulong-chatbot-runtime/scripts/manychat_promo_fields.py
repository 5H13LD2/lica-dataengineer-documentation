"""Inspect or create the semantic ManyChat fields used by promo galleries."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

import httpx


API_BASE = "https://api.manychat.com/fb"
KNOWN_FLOW_FIELD_IDS = {
    "14765453",
    "14765454",
    "14765455",
    "14765456",
    "14765457",
    "14765458",
    "14765547",
    "14569532",
    "14568567",
    "14765513",
}


@dataclass(frozen=True)
class RequiredField:
    name: str
    field_type: str
    description: str


REQUIRED_FIELDS = (
    RequiredField("promo_catalog_version", "text", "Active promo catalog version last shown or selected"),
    RequiredField("promo_gallery_shown", "boolean", "Whether Runtime V7 showed a promo gallery"),
    RequiredField("promo_gallery_last_shown_at", "datetime", "UTC time of the latest promo gallery"),
    RequiredField("promo_gallery_show_count", "number", "Number of promo galleries shown to the contact"),
    RequiredField("promo_gallery_promo_ids", "text", "Comma-separated promo IDs in the latest gallery"),
    RequiredField("promo_selected_id", "text", "Promo ID selected from a gallery button"),
    RequiredField("promo_selected_card_id", "text", "Card ID selected from a gallery button"),
    RequiredField("promo_selected_action", "text", "Tracked promo card action"),
    RequiredField("promo_selected_brand", "text", "Brand selected from a promo card"),
    RequiredField("promo_selected_at", "datetime", "UTC time of the latest promo card selection"),
    RequiredField("promo_source", "text", "Source of promo presentation or selection"),
    RequiredField("discovery_surface_type", "text", "Latest interactive discovery surface type"),
    RequiredField("discovery_surface_ref", "text", "Latest interactive discovery presentation reference"),
    RequiredField("discovery_surface_shown_at", "datetime", "Latest discovery surface delivery time"),
    RequiredField("discovery_choice_type", "text", "Latest discovery choice type"),
    RequiredField("discovery_choice_value", "text", "Latest discovery choice value"),
    RequiredField("discovery_choice_selected_at", "datetime", "Latest discovery choice time"),
    RequiredField("chatbot_state", "text", "Current chatbot workflow state"),
)


class ManyChatFieldClient:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("MANYCHAT_API_KEY is required")
        self._client = httpx.Client(
            base_url=API_BASE,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=30,
        )

    def list_fields(self) -> List[Dict[str, Any]]:
        response = self._client.get("/page/getCustomFields")
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if isinstance(data, list):
            return [dict(row) for row in data if isinstance(row, dict)]
        if isinstance(data, dict):
            for key in ("fields", "custom_fields"):
                if isinstance(data.get(key), list):
                    return [dict(row) for row in data[key] if isinstance(row, dict)]
        return []

    def create_field(self, required: RequiredField) -> Dict[str, Any]:
        response = self._client.post(
            "/page/createCustomField",
            json={
                "caption": required.name,
                "type": required.field_type,
                "description": required.description,
            },
        )
        response.raise_for_status()
        return dict(response.json())


def inspect_required_fields(
    existing_fields: Iterable[Dict[str, Any]],
    *,
    required_fields: Iterable[RequiredField] = REQUIRED_FIELDS,
) -> Dict[str, Any]:
    """Match by exact public name and enforce compatible field types."""

    existing = list(existing_fields)
    by_name = {
        str(row.get("name") or row.get("caption") or "").strip(): row
        for row in existing
        if str(row.get("name") or row.get("caption") or "").strip()
    }
    found = []
    missing = []
    conflicts = []
    for required in required_fields:
        row = by_name.get(required.name)
        if row is None:
            missing.append(required)
            continue
        actual_type = normalize_field_type(row.get("type"))
        if actual_type != normalize_field_type(required.field_type):
            conflicts.append(
                {
                    "name": required.name,
                    "field_id": str(row.get("id") or row.get("field_id") or ""),
                    "expected_type": required.field_type,
                    "actual_type": actual_type,
                }
            )
            continue
        found.append(
            {
                "name": required.name,
                "field_id": str(row.get("id") or row.get("field_id") or ""),
                "type": actual_type,
                "reuses_known_flow_field_id": str(row.get("id") or row.get("field_id") or "") in KNOWN_FLOW_FIELD_IDS,
            }
        )
    return {"found": found, "missing": missing, "conflicts": conflicts}


def normalize_field_type(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("date_time", "datetime")
    return {"bool": "boolean", "true/false": "boolean", "float": "number", "int": "number"}.get(
        normalized,
        normalized,
    )


def run(*, apply: bool) -> Dict[str, Any]:
    client = ManyChatFieldClient(os.getenv("MANYCHAT_API_KEY", ""))
    inspection = inspect_required_fields(client.list_fields())
    created = []
    if apply and not inspection["conflicts"]:
        for required in inspection["missing"]:
            created.append({"name": required.name, "result": client.create_field(required)})
        inspection = inspect_required_fields(client.list_fields())
    return {
        "status": "ok" if not inspection["missing"] and not inspection["conflicts"] else "needs_changes",
        "apply": apply,
        "found": inspection["found"],
        "missing": [field.name for field in inspection["missing"]],
        "conflicts": inspection["conflicts"],
        "created": created,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = run(apply=args.apply)
    except Exception as exc:
        result = {"status": "error", "error_type": type(exc).__name__, "error": str(exc)}
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
