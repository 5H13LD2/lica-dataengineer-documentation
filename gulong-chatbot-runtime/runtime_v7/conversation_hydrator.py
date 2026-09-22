"""Pre-turn conversation history hydration for Runtime V7 API ingress.

The harness already knows how to consume conversation evidence. This module
builds that input from API-supplied channel history and stored session messages
without making the harness depend on a specific storage backend.
"""

from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence


CHANNEL_CONVERSATION_HISTORY_STATE_KEY = "channel_conversation_history_v1"


@dataclass
class ConversationHydrationResult:
    """Resolved pre-turn history plus channel-cache metadata."""

    messages: List[Dict[str, Any]]
    channel_messages: List[Dict[str, Any]]
    source: str
    cache_status: str
    current_message: Dict[str, Any] = field(default_factory=dict)
    latest_cached_message: Dict[str, Any] = field(default_factory=dict)
    latest_loaded_message: Dict[str, Any] = field(default_factory=dict)
    refresh_attempted: bool = False
    loader_status: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


def hydrate_conversation_history(
    *,
    session_messages: Optional[Sequence[Any]] = None,
    channel_history: Optional[Sequence[Mapping[str, Any]]] = None,
    request_history: Optional[Sequence[Mapping[str, Any]]] = None,
    stored_v7_history: Optional[Sequence[Mapping[str, Any]]] = None,
    current_message_id: str = "",
    current_user_text: str = "",
    current_message_datetime: str = "",
    message_age_days: int = 30,
    reset_requested: bool = False,
    max_messages: int = 24,
) -> List[Dict[str, Any]]:
    """Return normalized prior conversation messages for V7 evidence intake."""

    if reset_requested:
        return []
    merged: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    sources = [
        ("channel_history", channel_history or []),
        ("stored_v7_history", stored_v7_history or []),
        ("session_messages", session_messages or []),
        ("request_history", request_history or []),
    ]
    for source, messages in sources:
        for message in messages or []:
            normalized = _normalize_history_message(message, source=source)
            if not normalized:
                continue
            if _is_current_message(
                normalized,
                current_message_id=current_message_id,
                current_user_text=current_user_text,
            ):
                continue
            key = (
                str(normalized.get("message_id") or ""),
                str(normalized.get("role") or ""),
                str(normalized.get("content") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(normalized)
    merged = _trim_to_current_age_segment(
        merged,
        current_message_id=current_message_id,
        current_user_text=current_user_text,
        current_message_datetime=current_message_datetime,
        message_age_days=message_age_days,
    )
    return merged[-max(1, int(max_messages or 24)) :]


def build_conversation_hydration_result(
    *,
    session_messages: Optional[Sequence[Any]] = None,
    request_history: Optional[Sequence[Mapping[str, Any]]] = None,
    stored_v7_history: Optional[Sequence[Mapping[str, Any]]] = None,
    cached_channel_history: Optional[Mapping[str, Any]] = None,
    loaded_channel_history: Optional[Sequence[Mapping[str, Any]]] = None,
    current_message_id: str = "",
    current_user_text: str = "",
    current_message_datetime: str = "",
    message_age_days: int = 30,
    reset_requested: bool = False,
    refresh_attempted: bool = False,
    loader_status: str = "",
    max_messages: int = 24,
) -> ConversationHydrationResult:
    """Build model-facing history from cached or freshly loaded channel history."""

    cached_messages = normalize_conversation_messages(
        (cached_channel_history or {}).get("messages") if isinstance(cached_channel_history, Mapping) else [],
        source="channel_history_cache",
    )
    loaded_messages = normalize_conversation_messages(loaded_channel_history or [], source="manychat_load_messages")
    raw_channel_messages = loaded_messages or cached_messages
    source = "manychat_load_messages" if loaded_messages else "channel_history_cache" if cached_messages and not reset_requested else "session_state"
    current_message = find_current_user_message(
        raw_channel_messages,
        current_message_id=current_message_id,
        current_user_text=current_user_text,
    )
    effective_current_message_id = str(current_message.get("message_id") or current_message_id or "").strip()
    effective_current_datetime = str(
        current_message.get("datetime") or current_message_datetime or ""
    ).strip()
    channel_messages = _trim_to_current_age_segment(
        raw_channel_messages,
        current_message_id=effective_current_message_id,
        current_user_text=current_user_text,
        current_message_datetime=effective_current_datetime,
        message_age_days=message_age_days,
        keep_current=True,
        reset_requested=reset_requested,
    )
    messages = hydrate_conversation_history(
        session_messages=session_messages,
        channel_history=channel_messages,
        request_history=[] if reset_requested else request_history,
        stored_v7_history=[] if reset_requested else stored_v7_history,
        current_message_id=effective_current_message_id,
        current_user_text=current_user_text,
        current_message_datetime=effective_current_datetime,
        message_age_days=message_age_days,
        reset_requested=reset_requested,
        max_messages=max_messages,
    )
    cache_status = "reset" if reset_requested else "refreshed" if loaded_messages else "cache_hit" if cached_messages else "empty"
    return ConversationHydrationResult(
        messages=messages,
        channel_messages=channel_messages,
        source=source,
        cache_status=cache_status,
        current_message=current_message,
        latest_cached_message=latest_conversation_message(cached_messages),
        latest_loaded_message=latest_conversation_message(loaded_messages),
        refresh_attempted=bool(refresh_attempted),
        loader_status=loader_status,
        metadata={
            "cached_message_count": len(cached_messages),
            "loaded_message_count": len(loaded_messages),
            "segment_message_count": len(channel_messages),
            "model_facing_message_count": len(messages),
            "message_age_days": max(1, int(message_age_days or 30)),
            "reset_requested": bool(reset_requested),
        },
    )


def normalize_conversation_messages(
    messages: Optional[Sequence[Any]],
    *,
    source: str,
    max_messages: int = 80,
) -> List[Dict[str, Any]]:
    """Normalize channel/session message rows into compact text history."""

    normalized: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for message in messages or []:
        row = _normalize_history_message(message, source=source)
        if not row:
            continue
        key = (
            str(row.get("message_id") or ""),
            str(row.get("role") or ""),
            str(row.get("content") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        normalized.append(row)
    normalized = _ordered_messages(normalized)
    return normalized[-max(1, int(max_messages or 80)) :]


def latest_conversation_message(messages: Optional[Sequence[Mapping[str, Any]]]) -> Dict[str, Any]:
    """Return the last normalized channel message."""

    ordered = _ordered_messages([dict(item) for item in messages or [] if isinstance(item, Mapping)])
    return dict(ordered[-1]) if ordered else {}


def latest_prior_conversation_message(
    messages: Optional[Sequence[Mapping[str, Any]]],
    *,
    current_message_id: str = "",
    current_user_text: str = "",
) -> Dict[str, Any]:
    """Return the latest message before the current inbound message."""

    ordered = _ordered_messages([dict(item) for item in messages or [] if isinstance(item, Mapping)])
    current = find_current_user_message(ordered, current_message_id=current_message_id, current_user_text=current_user_text)
    if current:
        current_id = str(current.get("message_id") or "").strip()
        for index, message in enumerate(ordered):
            if current_id and str(message.get("message_id") or "").strip() == current_id:
                return dict(ordered[index - 1]) if index > 0 else {}
            if not current_id and _is_current_message(message, current_message_id="", current_user_text=current_user_text):
                return dict(ordered[index - 1]) if index > 0 else {}
    for message in reversed(ordered):
        if not _is_current_message(message, current_message_id=current_message_id, current_user_text=current_user_text):
            return dict(message)
    return {}


def find_current_user_message(
    messages: Optional[Sequence[Mapping[str, Any]]],
    *,
    current_message_id: str = "",
    current_user_text: str = "",
) -> Dict[str, Any]:
    """Find the current inbound user message in normalized channel history."""

    ordered = _ordered_messages([dict(item) for item in messages or [] if isinstance(item, Mapping)])
    current_id = str(current_message_id or "").strip()
    if current_id:
        for message in reversed(ordered):
            if str(message.get("message_id") or "").strip() == current_id:
                return dict(message)
    current = _compact_text(current_user_text)
    if not current:
        return {}
    for message in reversed(ordered):
        if str(message.get("role") or "") != "user":
            continue
        if _compact_text(message.get("content")) == current:
            return dict(message)
    return {}


def build_channel_history_cache(
    messages: Optional[Sequence[Mapping[str, Any]]],
    *,
    source: str,
    refresh_status: str,
    max_messages: int = 60,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the Firestore-safe channel history cache payload."""

    normalized = normalize_conversation_messages(messages or [], source=source, max_messages=max_messages)
    latest = latest_conversation_message(normalized)
    return {
        "version": 1,
        "source": str(source or ""),
        "refresh_status": str(refresh_status or ""),
        "latest_message_id": latest.get("message_id") or "",
        "latest_message_datetime": latest.get("datetime") or "",
        "latest_message_role": latest.get("role") or "",
        "message_count": len(normalized),
        "messages": normalized,
        "metadata": dict(metadata or {}),
    }


def append_current_turn_to_channel_history(
    messages: Optional[Sequence[Mapping[str, Any]]],
    *,
    user_text: str,
    assistant_text: str,
    user_message_id: str = "",
    assistant_message_id: str = "",
    timestamp: str = "",
    max_messages: int = 60,
) -> List[Dict[str, Any]]:
    """Append current user/assistant turns to a normalized channel cache."""

    appended = [dict(item) for item in messages or [] if isinstance(item, Mapping)]
    if user_text:
        appended.append(
            {
                "role": "user",
                "content": str(user_text or "").strip(),
                "message_id": str(user_message_id or "").strip(),
                "datetime": str(timestamp or "").strip(),
                "source": "runtime_v7_current_turn",
            }
        )
    if assistant_text:
        appended.append(
            {
                "role": "assistant",
                "content": str(assistant_text or "").strip(),
                "message_id": str(assistant_message_id or "").strip(),
                "datetime": str(timestamp or "").strip(),
                "source": "runtime_v7_current_turn",
            }
        )
    return normalize_conversation_messages(appended, source="channel_history_cache", max_messages=max_messages)


def _trim_to_current_age_segment(
    messages: Optional[Sequence[Mapping[str, Any]]],
    *,
    current_message_id: str = "",
    current_user_text: str = "",
    current_message_datetime: str = "",
    message_age_days: int = 30,
    keep_current: bool = False,
    reset_requested: bool = False,
) -> List[Dict[str, Any]]:
    ordered = _ordered_messages([dict(item) for item in messages or [] if isinstance(item, Mapping)])
    if not ordered:
        return []
    current = find_current_user_message(
        ordered,
        current_message_id=current_message_id,
        current_user_text=current_user_text,
    )
    current_dt = _parse_datetime((current or {}).get("datetime") or current_message_datetime)
    if reset_requested:
        return [dict(current)] if keep_current and current else []

    end_index = len(ordered) - 1
    if current:
        current_id = str(current.get("message_id") or "").strip()
        for index, message in enumerate(ordered):
            if current_id and str(message.get("message_id") or "").strip() == current_id:
                end_index = index
                break
            if not current_id and _is_current_message(message, current_message_id="", current_user_text=current_user_text):
                end_index = index
                break
    anchor_dt = current_dt or _parse_datetime(ordered[end_index].get("datetime"))
    segment_reversed: List[Dict[str, Any]] = []
    previous_dt = anchor_dt
    max_gap_seconds = max(1, int(message_age_days or 30)) * 24 * 60 * 60
    for index in range(end_index, -1, -1):
        message = ordered[index]
        is_current = bool(current and index == end_index)
        if is_current and not keep_current:
            continue
        message_dt = _parse_datetime(message.get("datetime"))
        if is_current and keep_current:
            segment_reversed.append(dict(message))
            if message_dt:
                previous_dt = message_dt
            continue
        if previous_dt and not message_dt:
            continue
        if previous_dt and message_dt and (previous_dt - message_dt).total_seconds() > max_gap_seconds:
            break
        segment_reversed.append(dict(message))
        if message_dt:
            previous_dt = message_dt
    return list(reversed(segment_reversed))


def _normalize_history_message(message: Any, *, source: str) -> Dict[str, Any]:
    if message is None:
        return {}
    if isinstance(message, Mapping):
        data = dict(message)
    else:
        data = {
            "role": getattr(message, "role", ""),
            "text": getattr(message, "text", ""),
            "ts": getattr(message, "ts", ""),
            "message_id": getattr(message, "message_id", ""),
        }
    content = _message_content(data)
    if not content:
        return {}
    role = _normalize_role(data.get("role") or data.get("sender_role") or data.get("type"))
    if role == "unknown" and source == "session_messages":
        role = _normalize_role(data.get("role"))
    message_type = str(data.get("type") or data.get("message_type") or "").strip()
    is_automated = _is_automated_history_message(data, message_type=message_type, role=role)
    sender = str(data.get("sender") or data.get("agent_name") or data.get("user_name") or "").strip()
    if is_automated and not sender:
        sender = "ManyChat automation"
    normalized = {
        "role": role,
        "content": content,
        "message_id": str(data.get("message_id") or data.get("id") or "").strip(),
        "datetime": str(data.get("datetime") or data.get("created_at") or data.get("timestamp") or data.get("ts") or "").strip(),
        "sender": sender,
        "source": source,
    }
    if message_type:
        normalized["type"] = message_type
    if is_automated:
        normalized["is_automated"] = True
        normalized["message_kind"] = "manychat_automation"
    return normalized


def _ordered_messages(messages: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    indexed = list(enumerate(messages or []))

    def _sort_key(item: tuple[int, Dict[str, Any]]) -> tuple[str, int]:
        index, message = item
        timestamp = str(message.get("datetime") or message.get("created_at") or message.get("timestamp") or "").strip()
        return timestamp, index

    return [message for _index, message in sorted(indexed, key=_sort_key)]


def _parse_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    candidates = [text]
    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is not None:
                parsed = parsed.replace(tzinfo=None)
            return parsed
        except Exception:
            pass
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%m/%d/%y %H:%M", "%m/%d/%Y %H:%M"]:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass
    return None


def _is_current_message(
    message: Mapping[str, Any],
    *,
    current_message_id: str,
    current_user_text: str,
) -> bool:
    message_id = str(message.get("message_id") or "").strip()
    if current_message_id and message_id and message_id == current_message_id:
        return True
    if str(message.get("role") or "") != "user":
        return False
    content = " ".join(str(message.get("content") or "").split())
    current = " ".join(str(current_user_text or "").split())
    return bool(current and content == current)


def _message_content(data: Mapping[str, Any]) -> str:
    for key in ["text_content", "text", "message", "content_extracted", "msg_body"]:
        value = str(data.get(key) or "").strip()
        if value:
            return value
    if "content" in data:
        return _content_to_text(data.get("content"))
    return ""


def _content_to_text(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        for key in ["text", "caption", "title", "message", "body"]:
            text = str(value.get(key) or "").strip()
            if text:
                return text
        messages = value.get("messages")
        if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes)):
            chunks = [_content_to_text(item) for item in messages]
            return "\n".join(chunk for chunk in chunks if chunk).strip()
        content = value.get("content")
        if content is not value:
            text = _content_to_text(content)
            if text:
                return text
        url = str(value.get("url") or "").strip()
        if url:
            return url
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        chunks = [_content_to_text(item) for item in value]
        return "\n".join(chunk for chunk in chunks if chunk).strip()
    return ""


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalize_role(value: Any) -> str:
    role = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "customer": "user",
        "client": "user",
        "subscriber": "user",
        "user": "user",
        "msgin": "user",
        "msgin_tiktok": "user",
        "msgin_instagram": "user",
        "bot": "assistant",
        "chatbot": "assistant",
        "assistant": "assistant",
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
        "msgout_lc": "human_agent",
        "msgout_lc_tiktok": "human_agent",
        "msgout_lc_instagram": "human_agent",
    }
    return aliases.get(role, "unknown")


def _is_automated_history_message(data: Mapping[str, Any], *, message_type: str, role: str) -> bool:
    kind = str(data.get("message_kind") or "").strip().lower()
    if kind in {"manychat_automation", "automation", "automated"}:
        return True
    if bool(data.get("is_automated")):
        return True
    if str(message_type or "").strip().startswith("msgout_default"):
        return True
    return role == "assistant" and kind == "default_automation"


__all__ = [
    "CHANNEL_CONVERSATION_HISTORY_STATE_KEY",
    "ConversationHydrationResult",
    "append_current_turn_to_channel_history",
    "build_channel_history_cache",
    "build_conversation_hydration_result",
    "find_current_user_message",
    "hydrate_conversation_history",
    "latest_conversation_message",
    "latest_prior_conversation_message",
    "normalize_conversation_messages",
]
