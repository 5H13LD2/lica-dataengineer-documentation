"""Customer-safe provider names projected from checkout payment rows."""

from __future__ import annotations

import re
from typing import Any, List, Mapping


_PROVIDER_PATTERNS = (
    (r"\bMETRO\s*BANK\b|\bMETROBANK\b", "Metrobank"),
    (r"\bBPI\b", "BPI"),
    (r"\bBDO\b", "BDO"),
    (r"\bEWB\b|\bEAST\s*WEST\b|\bEASTWEST\b", "EastWest"),
    (r"\bCBC\b|\bCHINA\s*BANK\b|\bCHINABANK\b", "China Bank"),
    (r"\bHSBC\b", "HSBC"),
    (r"\bBOC\b|\bBANK\s+OF\s+COMMERCE\b", "Bank of Commerce"),
)


def payment_provider_names_from_row(row: Mapping[str, Any]) -> List[str]:
    """Return provider names supported by one authoritative checkout row.

    Provider copy and icon filenames are fields of the same ``/payment/list``
    record. Reading both prevents cards and prose from projecting different
    bank lists when one field contains only a subset of the providers.
    """

    text = " ".join(
        str((row or {}).get(key) or "")
        for key in ("name", "label", "value", "description", "icons")
    ).upper()
    output: List[str] = []
    for pattern, label in _PROVIDER_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE) and label not in output:
            output.append(label)
    return output


def payment_provider_phrase(names: List[str]) -> str:
    """Format provider names as a compact customer-facing association."""

    values = [str(value or "").strip() for value in names if str(value or "").strip()]
    if not values:
        return ""
    if len(values) == 1:
        return f"{values[0]} Credit Cards"
    if len(values) == 2:
        return f"{values[0]} and {values[1]} Credit Cards"
    return f"{', '.join(values[:-1])}, and {values[-1]} Credit Cards"
