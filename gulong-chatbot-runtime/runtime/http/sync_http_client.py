"""Sync HTTP client for threadpool-based tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


@dataclass
class SyncHTTPClientConfig:
    base_url: str
    timeout_connect_s: float = 3.0
    timeout_read_s: float = 10.0
    default_headers: Optional[Dict[str, str]] = None


class SyncHTTPClient:
    """
    Threadpool-safe HTTP client using requests.Session.

    Returns error-shaped dicts like:
        {"status": "Error", "status_code": 500, "content": "..."}
    """

    def __init__(self, *, config: SyncHTTPClientConfig, session: Optional[requests.Session] = None) -> None:
        self._config = config
        self._session = session or requests.Session()

    def get_json(
        self,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        url = f"{self._config.base_url.rstrip('/')}/{path.lstrip('/')}"
        merged_headers = {**(self._config.default_headers or {}), **(headers or {})}
        try:
            resp = self._session.get(
                url,
                params=params,
                headers=merged_headers,
                timeout=(self._config.timeout_connect_s, self._config.timeout_read_s),
            )
            if resp.status_code != 200:
                return {"status": "Error", "status_code": resp.status_code, "content": resp.text}
            return resp.json()
        except requests.Timeout:
            return {"status": "Error", "status_code": 408, "content": "Request timed out"}
        except requests.RequestException as exc:
            return {"status": "Error", "status_code": 500, "content": str(exc)}

    def post_json(
        self,
        path: str,
        *,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        url = f"{self._config.base_url.rstrip('/')}/{path.lstrip('/')}"
        merged_headers = {**(self._config.default_headers or {}), **(headers or {})}
        try:
            resp = self._session.post(
                url,
                params=params,
                json=json_data,
                headers=merged_headers,
                timeout=(self._config.timeout_connect_s, self._config.timeout_read_s),
            )
            if resp.status_code != 200:
                return {"status": "Error", "status_code": resp.status_code, "content": resp.text}
            return resp.json()
        except requests.Timeout:
            return {"status": "Error", "status_code": 408, "content": "Request timed out"}
        except requests.RequestException as exc:
            return {"status": "Error", "status_code": 500, "content": str(exc)}

    def close(self) -> None:
        if self._session:
            self._session.close()
