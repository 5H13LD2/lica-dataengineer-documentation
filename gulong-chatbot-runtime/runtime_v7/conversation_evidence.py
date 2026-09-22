"""Conversation-history evidence hydration for Runtime V7.

Runtime V7 can receive prior ManyChat/customer-service messages before the
current turn. This module normalizes those messages into prompt-facing recent
turns and compact evidence refs. It does not parse commercial meaning from raw
text; the model-backed signal extractor owns that semantic step.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Sequence


def build_conversation_evidence_context(
    messages: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    max_turns: int = 12,
    max_human_agent_refs: int = 6,
) -> Dict[str, Any]:
    """Normalize stored conversation messages into context turns and refs."""

    normalized_messages = [
        _normalize_message(message)
        for message in _ordered_messages(messages or [])
        if isinstance(message, dict)
    ]
    turns = [
        _turn_from_message(message)
        for message in normalized_messages
        if message.get("content")
    ]
    human_refs = [
        _human_agent_ref_from_message(message)
        for message in normalized_messages
        if message.get("role") == "human_agent" and message.get("content")
    ]
    return {
        "recent_turns": turns[-max(1, int(max_turns or 12)) :],
        "external_evidence_refs": human_refs[-max(1, int(max_human_agent_refs or 6)) :],
        "message_count": len(normalized_messages),
        "human_agent_message_count": sum(1 for message in normalized_messages if message.get("role") == "human_agent"),
    }


def merge_recent_turns(*turn_sets: Sequence[Dict[str, Any]], limit: int = 12) -> List[Dict[str, str]]:
    """Merge hydrated and in-session turns while preserving order."""

    merged: List[Dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for turns in turn_sets:
        for turn in turns or []:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role") or "").strip()
            content = str(turn.get("content") or "").strip()
            message_id = str(turn.get("message_id") or "").strip()
            if not role or not content:
                continue
            key = (message_id, role, content)
            if key in seen:
                continue
            seen.add(key)
            row: Dict[str, str] = {"role": role, "content": content}
            for extra_key in ["message_id", "datetime", "sender"]:
                value = str(turn.get(extra_key) or "").strip()
                if value:
                    row[extra_key] = value
            if turn.get("is_automated"):
                row["is_automated"] = True
            message_kind = str(turn.get("message_kind") or "").strip()
            if message_kind:
                row["message_kind"] = message_kind
            merged.append(row)
    return merged[-max(1, int(limit or 12)) :]


def _ordered_messages(messages: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    indexed = list(enumerate(messages or []))

    def _sort_key(item: tuple[int, Dict[str, Any]]) -> tuple[str, str, int]:
        index, message = item
        timestamp = str(message.get("datetime") or message.get("created_at") or message.get("timestamp") or "").strip()
        sort_id = str(message.get("sort_id") or message.get("raw_timestamp") or "").strip()
        return timestamp, sort_id, index

    return [message for _index, message in sorted(indexed, key=_sort_key)]


def _normalize_message(message: Dict[str, Any]) -> Dict[str, Any]:
    content = _message_content(message)
    message_type = str(message.get("type") or message.get("message_type") or "").strip()
    role = _normalize_role(message.get("role") or message.get("sender_role") or message_type)
    is_automated = _is_automated_message(message, message_type=message_type)
    sender = str(message.get("sender") or message.get("agent_name") or message.get("user_name") or "").strip()
    if is_automated and not sender:
        sender = "ManyChat automation"
    normalized = {
        "role": role,
        "content": _trim_text(content, 700),
        "message_id": str(message.get("message_id") or message.get("id") or "").strip(),
        "datetime": str(message.get("datetime") or message.get("created_at") or message.get("timestamp") or "").strip(),
        "sender": sender,
    }
    if message_type:
        normalized["type"] = message_type
    if is_automated:
        normalized["is_automated"] = True
        normalized["message_kind"] = "manychat_automation"
    return normalized


def _message_content(message: Dict[str, Any]) -> str:
    for key in ["text_content", "content", "text", "message", "content_extracted"]:
        value = str(message.get(key) or "").strip()
        if value:
            return value
    return ""


def _normalize_role(value: Any) -> str:
    role = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "customer": "user",
        "client": "user",
        "subscriber": "user",
        "bot": "assistant",
        "chatbot": "assistant",
        "ai": "assistant",
        "msgout_api": "assistant",
        "msgout_api_tiktok": "assistant",
        "msgout_api_instagram": "assistant",
        "msgout_default": "assistant",
        "msgout_default_tiktok": "assistant",
        "msgout_default_instagram": "assistant",
        "agent": "human_agent",
        "human": "human_agent",
        "human_agent": "human_agent",
        "staff": "human_agent",
        "admin": "human_agent",
        "page_admin": "human_agent",
        "cs": "human_agent",
    }
    role = aliases.get(role, role)
    if role in {"user", "assistant", "human_agent"}:
        return role
    return "unknown"


def _turn_from_message(message: Dict[str, Any]) -> Dict[str, str]:
    row: Dict[str, str] = {
        "role": str(message.get("role") or "unknown"),
        "content": str(message.get("content") or ""),
    }
    for key in ["message_id", "datetime", "sender"]:
        value = str(message.get(key) or "").strip()
        if value:
            row[key] = value
    if message.get("is_automated"):
        row["is_automated"] = True
    message_kind = str(message.get("message_kind") or "").strip()
    if message_kind:
        row["message_kind"] = message_kind
    return row


def _human_agent_ref_from_message(message: Dict[str, Any]) -> Dict[str, Any]:
    message_id = str(message.get("message_id") or "").strip()
    content = str(message.get("content") or "").strip()
    sender = str(message.get("sender") or "human agent").strip()
    evidence_ref = _conversation_evidence_ref(message_id=message_id, content=content)
    return {
        "evidence_ref": evidence_ref,
        "source": "human_agent_history",
        "media_type": "conversation_message",
        "status": "trusted_context_unvalidated_for_action",
        "safe_for_action": False,
        "requires_validation": True,
        "trusted_for_context": True,
        "validation_ref": message_id,
        "summary": f"{sender} said: {_trim_text(content, 180)}",
        "extracted_fields": [f"agent_message={_trim_text(content, 160)}"],
        "message_id": message_id,
        "datetime": str(message.get("datetime") or "").strip(),
        "sender": sender,
    }


def _conversation_evidence_ref(*, message_id: str, content: str) -> str:
    basis = message_id or content
    digest = hashlib.sha1(str(basis or "").encode("utf-8")).hexdigest()[:12]
    return f"conv_{digest}"


def _trim_text(text: str, max_chars: int) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(0, max_chars - 1)].rstrip() + "."


def _is_automated_message(message: Dict[str, Any], *, message_type: str) -> bool:
    kind = str(message.get("message_kind") or "").strip().lower()
    if kind in {"manychat_automation", "automation", "automated"}:
        return True
    if bool(message.get("is_automated")):
        return True
    return str(message_type or "").strip().startswith("msgout_default")
