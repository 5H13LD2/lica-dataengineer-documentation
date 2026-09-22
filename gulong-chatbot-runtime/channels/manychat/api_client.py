"""
Minimal ManyChat API client for runtime channel delivery.

This is intentionally standalone so runtime does not depend on legacy code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict
import asyncio
import os

import httpx

from configs.config import ENV
from runtime.utils.time_utils import now_manila_str


@dataclass
class ManyChatAPI:
    """
    Lightweight ManyChat wrapper with delivery-first behavior.

    Guarantees:
    - Never raises on delivery; always returns a status dict.
    - Applies timeouts and basic retries for outbound calls.
    - Logs include a Manila timestamp for consistency.
    """

    api_base_url: str = "https://api.manychat.com/fb/"
    api_key: str = os.environ.get("MANYCHAT_API_KEY", "")
    psid: str = ""
    timeout: float = 15.0
    max_retries: int = 0
    headers: dict = field(init=False)

    def __post_init__(self) -> None:
        if not self.api_key:
            if isinstance(ENV, dict):
                self.api_key = ENV.get("MANYCHAT_API_KEY", "") or ""
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"

    def _log_error(self, function: str, message: str) -> Dict[str, Any]:
        return {
            "status": "error",
            "function": function,
            "error": message,
            "timestamp": now_manila_str(),
            "channel_user_id": self.psid,
        }

    def _log_unknown(self, message: str, *, status_code: int | None = None) -> Dict[str, Any]:
        """Record an ambiguous send that ManyChat may still deliver asynchronously."""

        result: Dict[str, Any] = {
            "status": "unknown",
            "function": "manychat.send",
            "reason": "manychat_delivery_ambiguous",
            "error": message,
            "timestamp": now_manila_str(),
            "channel_user_id": self.psid,
        }
        if status_code is not None:
            result["status_code"] = status_code
        return result

    async def _post_json(self, endpoint: str, payload: dict) -> Dict[str, Any]:
        if not self.api_key:
            return self._log_error("manychat.send", "api_key is missing")
        url = f"{self.api_base_url}{endpoint}"
        attempt = 0
        while attempt <= self.max_retries:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url=url, headers=self.headers, json=payload)
                if response.status_code == 200:
                    return {
                        "status": "success",
                        "status_code": response.status_code,
                        "message": "ok",
                        "data": response.json(),
                    }
                if response.status_code in {502, 503, 504}:
                    return self._log_unknown(
                        f"Ambiguous ManyChat gateway response: {response.status_code}",
                        status_code=response.status_code,
                    )
                error_msg = f"Non-200 ManyChat response: {response.status_code} {response.text or ''}".strip()
                return {
                    "status": "error",
                    "function": "manychat.send",
                    "status_code": response.status_code,
                    "message": response.text or "",
                    "error": error_msg,
                    "timestamp": now_manila_str(),
                    "channel_user_id": self.psid,
                    "data": None,
                }
            except httpx.ReadTimeout as exc:
                return self._log_unknown(f"ReadTimeout: {exc}")
            except Exception as exc:
                attempt += 1
                if attempt > self.max_retries:
                    return self._log_error("manychat.send", f"{type(exc).__name__}: {exc}")
                await asyncio.sleep(0.5 * attempt)
        return self._log_error("manychat.send", "Unknown error after retries")

    async def send_content(
        self,
        messages: list,
        channel_subtype: str | None = None,
        actions: list | None = None,
    ) -> dict:
        if not self.psid:
            return self._log_error("manychat.send", "subscriber_id is missing")
        normalized: list = []
        for message in messages:
            if not message:
                continue
            if isinstance(message, dict) and message.get("type"):
                normalized.append(message)
                continue
            if isinstance(message, str):
                normalized.append({"type": "text", "text": message})
        content: dict = {"messages": normalized}
        normalized_actions = [dict(action) for action in actions or [] if isinstance(action, dict)]
        if normalized_actions:
            content["actions"] = normalized_actions
        subtype = (channel_subtype or "").strip().lower()
        if subtype in {"instagram", "whatsapp", "telegram", "tiktok"}:
            content["type"] = subtype
        payload = {
            "subscriber_id": self.psid,
            "data": {
                "version": "v2",
                "content": content,
            },
        }
        return await self._post_json("sending/sendContent", payload)

    async def add_tag_by_name(self, tag_name: str) -> dict:
        """Add a tag to the subscriber by tag name."""

        if not self.psid:
            return self._log_error("manychat.add_tag", "subscriber_id is missing")
        tag = str(tag_name or "").strip()
        if not tag:
            return self._log_error("manychat.add_tag", "tag_name is missing")
        return await self._post_json(
            "subscriber/addTagByName",
            {"subscriber_id": self.psid, "tag_name": tag},
        )

    async def create_note(self, note_content: str) -> dict:
        """Create a ManyChat conversation note through the legacy app boundary."""

        if not self.psid:
            return self._log_error("manychat.create_note", "subscriber_id is missing")
        note = str(note_content or "").strip()
        if not note:
            return self._log_error("manychat.create_note", "note_content is missing")
        try:
            from channels.manychat.manychat_client import ManychatUtils

            legacy_client = ManychatUtils(user_id=self.psid)
            return dict(await asyncio.to_thread(legacy_client.create_note, note))
        except Exception as exc:  # pragma: no cover - defensive side-effect boundary
            return self._log_error("manychat.create_note", f"{type(exc).__name__}: {exc}")
