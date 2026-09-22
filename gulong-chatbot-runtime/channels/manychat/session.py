from __future__ import annotations
from typing import Any, Dict, Optional, Sequence
from channels.manychat import manychat_client
from configs.log_utils import manila_tz
from uuid import uuid4
from datetime import datetime

try:
    from apps.shared.models.manychat import UserInfoRequest  # type: ignore
except Exception:  # pragma: no cover - optional type-only dependency
    UserInfoRequest = Any  # type: ignore

def session_from_request(request: UserInfoRequest):
    """
    Generic dependency: given a request model that has `user_id` and `user_name`,
    return a ManychatSession.
    Works with AnalysisRequest or any model that defines these fields.
    """
    return ManychatSession(user_id=str(request.user_id), user_name=getattr(request, "user_name", "") or "")

class ManychatSession:
    """
    Per-request session that wraps one ManychatUtils instance and lazily caches:
      - user_info
      - messages (optionally filtered)
      - agent_data (derived from cached messages when possible)
    """
    def __init__(self, user_id: str, user_name: str | None, 
                 task_id : Optional[str] = None):
        self.user_id = user_id
        self.user_name = user_name or ""
        self.task_id : Optional[str] = task_id or self._make_task_id(self.user_id)
        self.mc = manychat_client.ManychatUtils(user_id=user_id, user_name=user_name)
        self._user_info: Optional[Dict[str, Any]] = None
        self._messages: Optional[Dict[str, Any]] = None
        self._messages_limit: Optional[int] = None
        self._agent_data: Optional[Dict[str, Any]] = None

    def _make_task_id(self, user_id: str) -> str:
        ts = datetime.now(manila_tz).strftime("%Y%m%d%H%M%S")
        return f"sync-{user_id}-{ts}-{uuid4().hex[:6]}"

    # ---- Lazy getters -----------------------------------------------------

    def get_user_info(self) -> Dict[str, Any]:
        if self._user_info is not None:
            self._user_info['message'] = "Cached user data"
            return self._user_info
        self._user_info = self.mc.get_user_info()
        try:
            data = (self._user_info or {}).get("data") or {}
            self.user_name = data.get("user_name") or self.user_name
        except Exception:
            pass
        return self._user_info

    def load_messages(
        self,
        *,
        limit: int = 100,
        timeout: Optional[int] = None,
        message_age_filter: Optional[int] = None,
        per_message_sleep_s: Optional[float] = None,
    ) -> Dict[str, Any]:
        # If already loaded full set, reuse; otherwise (or narrower types) reload
        if limit <= 0:
            limit = 1

        if self._messages is not None and self._messages_limit is not None:
            if limit <= self._messages_limit:
                cached = dict(self._messages)
                data = cached.get("data")
                if isinstance(data, list) and limit < len(data):
                    cached["data"] = data[:limit]
                cached["message"] = "Cached messages data"
                return cached

        kwargs: Dict[str, Any] = {"limit": limit}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if message_age_filter is not None:
            kwargs["message_age_filter"] = message_age_filter
        if per_message_sleep_s is not None:
            kwargs["per_message_sleep_s"] = per_message_sleep_s
        self._messages = self.mc.load_messages(**kwargs)
        self._messages_limit = limit

        # 🔧 keep the ManychatUtils cache in sync so downstream methods reuse it
        try:
            self.mc._messages_data = self._messages
        except Exception:
            pass

        return self._messages

    def get_agent_data(self) -> Dict[str, Any]:
        """
        Prefer using cached messages to compute agent data;
        if not available, do a minimal fetch via mc.get_agent_data (your optimized version).
        """
        if self._agent_data is not None and (self._agent_data.get('status', '') == 'success'):
            self._agent_data['message'] = "Cached agent data"
            return self._agent_data
        self.mc.limiter = None
        self._agent_data = self.mc.get_agent_data()
        return self._agent_data

    # ---- Convenience helpers ---------------------------------------------

    def infer_source(self) -> str:
        """
        Infer source from tags/custom fields; default 'facebook'.
        (Uses cached user_info when available.)
        """
        try:
            ui = self.get_user_info()
            data = ui.get("data", {})
            tags = data.get("tags", []) or []
            if any(t.get("name") == "FB_Comment" for t in tags):
                return "facebook comment"
            for cf in data.get("custom_fields", []) or []:
                if cf.get("name") == "channel" and cf.get("value") in {"instagram", "tiktok"}:
                    return cf["value"]
            return "facebook"
        except Exception:
            return "facebook"

    # ---- Tags / Custom Fields helpers -----------------------------------

    def get_tags(
        self,
        names: Optional[Sequence[str]] = None,
        *,
        message_age: Optional[int] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Fetch tags using the shared ManychatUtils instance.

        - When names is provided, returns a dict of {tag_name: bool} indicating
          whether each tag is present on the user profile.
        - When names is None, returns the latest tag events payload (cached when available).
        """
        # Profile-level presence check
        if names:
            ui = self.get_user_info()
            data = ui.get("data") or {}
            profile_tags = {t.get("name") for t in (data.get("tags") or []) if isinstance(t, dict)}
            presence = {name: (name in profile_tags) for name in names}
            return {"status": "success", "status_code": 200, "data": presence, "message": "Tag presence computed."}

        # Default: return tag events (reuses ManychatUtils cache)
        resp = self.mc.get_tags_data(message_age=message_age, timeout=timeout)
        if resp.get("status") != "success":
            return resp
        tags_data = resp.get("data")
        if tags_data is None:
            tags_data = []
        self.mc.tags_data = tags_data
        return resp

    def get_custom_fields(
        self,
        names: Optional[Sequence[str]] = None,
        *,
        message_age: Optional[int] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Fetch custom fields using the shared ManychatUtils instance.

        - When names is provided, returns a dict of {cf_name: value} pulled from
          the user profile's custom_fields collection (None if absent).
        - When names is None, returns the latest custom-field set events payload (cached when available).
        """
        if names:
            ui = self.get_user_info()
            data = ui.get("data") or {}
            cf_list = data.get("custom_fields") or []
            by_name = {}
            for cf in cf_list:
                if not isinstance(cf, dict):
                    continue
                name = cf.get("name")
                if name in names:
                    by_name[name] = cf.get("value")
            for name in names:
                by_name.setdefault(name, None)
            return {"status": "success", "status_code": 200, "data": by_name, "message": "Custom field values fetched."}

        resp = self.mc.get_cfs_data(message_age=message_age, timeout=timeout)
        if resp.get("status") != "success":
            return resp
        cfs_data = resp.get("data")
        if cfs_data is None:
            cfs_data = []
        self.mc.cfs_data = cfs_data
        return resp



