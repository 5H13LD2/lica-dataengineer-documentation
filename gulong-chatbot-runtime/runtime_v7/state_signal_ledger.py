"""Small Runtime V7 store for normalized BackgroundSignal continuity.

The ledger is intentionally simple: it persists the latest normalized signal
view per session for the isolated V7 harness. It is not a parser and does not
derive facts from prose. Production can replace this with a Firestore-backed
store while keeping the same load/save boundary.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from runtime_v7.state_signal_schema import (
    DURABLE_SIGNAL_RELATIONS,
    signal_has_durable_authority,
    signal_is_lookup_only_evidence,
)


@dataclass
class InMemoryBackgroundSignalLedgerStore:
    """In-memory signal ledger used by Runtime V7 probes."""

    _items: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    def load(self, session_id: str) -> List[Dict[str, Any]]:
        """Return the last merged signal view for a session."""

        return deepcopy(self._items.get(str(session_id), []))

    def save(
        self,
        session_id: str,
        signals: List[Dict[str, Any]],
        *,
        turn_index: Optional[int] = None,
    ) -> None:
        """Save normalized signals with lightweight ledger metadata."""

        session_key = str(session_id)
        previous_by_key = {
            str(signal.get("key") or ""): signal
            for signal in self._items.get(session_key, [])
            if isinstance(signal, dict) and signal.get("key")
        }
        saved: List[Dict[str, Any]] = []
        for signal in signals or []:
            if not isinstance(signal, dict):
                continue
            key = str(signal.get("key") or "").strip()
            value = signal.get("value")
            relation = str(signal.get("relation") or "asserted").strip().lower()
            if (
                not key
                or value in (None, "", [])
                or relation not in DURABLE_SIGNAL_RELATIONS
                # External/OCR evidence remains available through its evidence
                # ref for a validation lookup, but never becomes customer
                # state merely because a turn completed.
                or signal_is_lookup_only_evidence(signal)
                or not signal_has_durable_authority(signal)
            ):
                continue
            row = deepcopy(signal)
            metadata = dict(row.get("metadata") or {})
            ledger = dict(metadata.get("ledger") or {})
            previous_ledger = (
                previous_by_key.get(key, {}).get("metadata", {}).get("ledger", {})
                if isinstance(previous_by_key.get(key, {}).get("metadata"), dict)
                else {}
            )
            if turn_index is not None:
                ledger["first_seen_turn"] = previous_ledger.get("first_seen_turn") or int(turn_index)
                ledger["last_seen_turn"] = int(turn_index)
            source = str(row.get("source") or "").strip()
            status = str(row.get("status") or "").strip()
            if source == "signal_ledger":
                if previous_ledger.get("authority_source"):
                    ledger["authority_source"] = previous_ledger[
                        "authority_source"
                    ]
                if previous_ledger.get("authority_status"):
                    ledger["authority_status"] = previous_ledger[
                        "authority_status"
                    ]
                if previous_ledger.get("authority_relation"):
                    ledger["authority_relation"] = previous_ledger[
                        "authority_relation"
                    ]
            elif source:
                ledger["authority_source"] = source
                ledger["authority_status"] = status
                ledger["authority_relation"] = relation
            ledger["persisted_in_signal_ledger"] = True
            metadata["ledger"] = ledger
            row["metadata"] = metadata
            saved.append(row)
        self._items[session_key] = saved
