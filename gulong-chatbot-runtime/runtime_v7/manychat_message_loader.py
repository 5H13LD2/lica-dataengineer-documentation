"""Fast ManyChat message history loader for Runtime V7 ingress.

The legacy ManychatUtils loader is feature-rich, but it also does profile
hydration and per-message pacing that are too expensive for pre-turn chatbot
context. This module keeps V7 hydration narrow: one hidden loadMessages request,
compact text extraction, and best-effort failure semantics.
"""

from __future__ import annotations

import ast
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import requests

from configs.config import ENV
from configs.log_utils import manila_tz


DEFAULT_MESSAGE_TYPES = {
    "msgin",
    "msgin_tiktok",
    "msgin_instagram",
    "msgout_api",
    "msgout_api_tiktok",
    "msgout_api_instagram",
    "msgout_default",
    "msgout_default_tiktok",
    "msgout_default_instagram",
    "msgout_lc",
    "msgout_lc_tiktok",
    "msgout_lc_instagram",
}


def load_manychat_messages_fast(
    *,
    user_id: str,
    user_name: str = "",
    limit: int = 20,
    timeout_s: float = 8.0,
    message_age_days: int = 30,
    max_pages: int = 4,
    page_id: str = "",
    headers: Optional[Mapping[str, Any]] = None,
    cookies: Optional[Mapping[str, Any]] = None,
    transport_get: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Load compact ManyChat conversation turns with minimal runtime overhead."""

    started = time.perf_counter()
    user_id = str(user_id or "").strip()
    if not user_id:
        return _result("error", [], started, "user_id is required", status_code=400)

    page_id = str(page_id or _env("MANYCHAT_PAGE_ID") or "").strip()
    target_url = _manychat_load_messages_url(page_id=page_id)
    request_headers = dict(headers or _literal_env_dict("MANYCHAT_APP_HEADERS"))
    request_cookies = dict(cookies or _literal_env_dict("MANYCHAT_COOKIES"))
    getter = transport_get or requests.get
    raw_messages: List[Dict[str, Any]] = []
    limiter: Any = None
    status_code: Optional[int] = None
    page_count = 0
    page_limit = max(1, int(max_pages or 4))
    accepted_limit = max(1, int(limit or 20))
    total_timeout = max(0.5, float(timeout_s or 8.0))
    while page_count < page_limit:
        remaining = total_timeout - (time.perf_counter() - started)
        if remaining <= 0.25:
            break
        params = {
            "limit": accepted_limit,
            "user_id": user_id,
            "type": "facebook",
            "limiter": limiter,
        }
        try:
            response = getter(
                target_url,
                params=params,
                cookies=request_cookies,
                headers=request_headers,
                timeout=min(3.0, max(0.1, remaining)),
            )
        except Exception as exc:
            if raw_messages:
                break
            return _result("error", [], started, f"{type(exc).__name__}: {exc}", status_code=None)

        page_count += 1
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code != 200:
            if raw_messages:
                break
            text = str(getattr(response, "text", "") or "")
            return _result("error", [], started, f"ManyChat loadMessages returned {status_code}: {text[:180]}", status_code=status_code)

        try:
            body = response.json()
        except Exception:
            if raw_messages:
                break
            text = str(getattr(response, "text", "") or "")
            message = "ManyChat loadMessages returned non-JSON response"
            if text.lstrip().lower().startswith("<!doctype html"):
                message = "ManyChat loadMessages returned HTML; cookies or headers are likely expired"
            return _result("error", [], started, message, status_code=status_code)

        payload = body.get("messages") if isinstance(body, dict) else []
        if not isinstance(payload, list):
            if raw_messages:
                break
            return _result("error", [], started, "ManyChat loadMessages response missing messages list", status_code=status_code)
        raw_messages.extend([dict(item) for item in payload if isinstance(item, Mapping)])
        messages = _normalize_messages(
            raw_messages,
            user_id=user_id,
            user_name=user_name,
            limit=accepted_limit,
            message_age_days=max(1, int(message_age_days or 30)),
        )
        if len(messages) >= accepted_limit:
            return _result(
                "success",
                messages,
                started,
                f"Loaded {len(messages)} compact ManyChat text messages.",
                status_code=status_code,
                page_count=page_count,
                raw_event_count=len(raw_messages),
            )
        limiter = body.get("limiter") if isinstance(body, dict) else None
        if not limiter:
            return _result(
                "success",
                messages,
                started,
                f"Loaded {len(messages)} compact ManyChat text messages.",
                status_code=status_code,
                page_count=page_count,
                raw_event_count=len(raw_messages),
            )

    messages = _normalize_messages(
        raw_messages,
        user_id=user_id,
        user_name=user_name,
        limit=accepted_limit,
        message_age_days=max(1, int(message_age_days or 30)),
    )
    return _result(
        "success",
        messages,
        started,
        f"Loaded {len(messages)} compact ManyChat text messages.",
        status_code=status_code,
        page_count=page_count,
        raw_event_count=len(raw_messages),
    )


def _normalize_messages(
    raw_messages: Sequence[Mapping[str, Any]],
    *,
    user_id: str,
    user_name: str,
    limit: int,
    message_age_days: int,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    previous_accepted: Optional[datetime] = None
    sorted_messages = sorted(
        [dict(item) for item in raw_messages or [] if isinstance(item, Mapping)],
        key=lambda item: int(item.get("timestamp") or 0),
        reverse=True,
    )
    for item in sorted_messages:
        if len(rows) >= limit:
            break
        message_type = str(item.get("type") or "").strip()
        if message_type not in DEFAULT_MESSAGE_TYPES:
            continue
        timestamp = item.get("timestamp")
        try:
            message_dt = datetime.fromtimestamp(float(timestamp)).astimezone(manila_tz)
        except Exception:
            message_dt = datetime.now(manila_tz)
        if previous_accepted is not None and (previous_accepted - message_dt).days > message_age_days:
            break
        content = _extract_model_text(item.get("model"))
        if not content:
            continue
        is_automated = _is_automated_message_type(message_type)
        sender = _sender_name(message_type, item.get("model"), user_name=user_name)
        rows.append(
            {
                "datetime": message_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "type": message_type,
                "user_id": str(user_id or ""),
                "user_name": str(user_name or ""),
                "sender": sender,
                "role": _role_from_type(message_type),
                "message_id": str(item.get("message_id") or item.get("id") or "").strip(),
                "content": content,
                **({"is_automated": True, "message_kind": "manychat_automation"} if is_automated else {}),
                "source": "manychat_load_messages_fast",
            }
        )
        previous_accepted = message_dt
    unique = {str(row.get("message_id") or f"{row.get('datetime')}:{row.get('role')}:{row.get('content')}"): row for row in rows}
    return sorted(unique.values(), key=lambda row: (str(row.get("datetime") or ""), str(row.get("message_id") or "")))


def _extract_model_text(model: Any) -> str:
    if model in (None, "", [], {}):
        return ""
    if isinstance(model, str):
        return " ".join(model.split())
    if isinstance(model, Mapping):
        messages = model.get("messages")
        if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes)):
            chunks: List[str] = []
            for message in messages:
                if not isinstance(message, Mapping):
                    continue
                content = message.get("content")
                if isinstance(content, Mapping):
                    text = str(content.get("text") or content.get("caption") or content.get("url") or "").strip()
                else:
                    text = str(content or "").strip()
                if text:
                    chunks.append(text)
            if chunks:
                return "\n".join(chunks).strip()
        for key in ["text", "caption", "body", "message", "url"]:
            text = str(model.get(key) or "").strip()
            if text:
                return " ".join(text.split())
    return ""


def _role_from_type(message_type: str) -> str:
    if message_type.startswith("msgin"):
        return "user"
    if message_type.startswith("msgout_api") or _is_automated_message_type(message_type):
        return "assistant"
    if message_type.startswith("msgout_lc"):
        return "human_agent"
    return "unknown"


def _sender_name(message_type: str, model: Any, *, user_name: str) -> str:
    if message_type.startswith("msgin"):
        return str(user_name or "").strip()
    if message_type.startswith("msgout_api"):
        return "Taira"
    if _is_automated_message_type(message_type):
        return "ManyChat automation"
    if isinstance(model, Mapping):
        sender = model.get("sender")
        if isinstance(sender, Mapping):
            return str(sender.get("user_name") or sender.get("name") or "").strip()
    return ""


def _is_automated_message_type(message_type: str) -> bool:
    return str(message_type or "").strip().startswith("msgout_default")


def _manychat_load_messages_url(*, page_id: str) -> str:
    base = "https://app.manychat.com/fb"
    page = str(page_id or "").strip().strip("/")
    return f"{base}{page}/im/loadMessages" if page else f"{base}/im/loadMessages"


def _literal_env_dict(key: str) -> Dict[str, Any]:
    raw = _env(key)
    if not raw:
        return {}
    parsed = _parse_mapping_literal(str(raw))
    if parsed:
        return parsed
    cleaned = _close_mapping_literal(_strip_mapping_literal_comments(str(raw)))
    if cleaned != str(raw):
        parsed = _parse_mapping_literal(cleaned)
        if parsed:
            return parsed
    return {}


def _parse_mapping_literal(raw: str) -> Dict[str, Any]:
    try:
        value = ast.literal_eval(raw)
    except Exception:
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _strip_mapping_literal_comments(raw: str) -> str:
    lines: List[str] = []
    for line in str(raw or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(_strip_inline_comment(line).rstrip())
    return "\n".join(line for line in lines if line.strip())


def _strip_inline_comment(line: str) -> str:
    quote = ""
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char == "#":
            return line[:index]
    return line


def _close_mapping_literal(raw: str) -> str:
    value = str(raw or "").strip()
    if not value.startswith("{"):
        return value
    missing = value.count("{") - value.count("}")
    if missing > 0:
        value = value + ("}" * missing)
    return value


def _env(key: str) -> str:
    if isinstance(ENV, dict):
        return str(ENV.get(key) or "")
    return ""


def _result(
    status: str,
    data: List[Dict[str, Any]],
    started: float,
    message: str,
    *,
    status_code: Optional[int],
    page_count: int = 0,
    raw_event_count: int = 0,
) -> Dict[str, Any]:
    return {
        "status": status,
        "status_code": status_code,
        "message": message,
        "data": data,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "page_count": int(page_count or 0),
        "raw_event_count": int(raw_event_count or 0),
        "source": "runtime_v7_manychat_message_loader",
    }


__all__ = ["load_manychat_messages_fast"]
