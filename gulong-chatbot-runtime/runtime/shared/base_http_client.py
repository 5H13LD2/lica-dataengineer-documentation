"""
BaseToolsClient
===============

A small, reusable HTTP client for agent tools. It centralizes:

- One reusable `aiohttp.ClientSession` (connection pooling, DNS cache)
- Consistent default headers for GET/POST
- A tiny, lock-protected in-memory TTL cache for GETs
- Structured error shaping (status, content)
- Clean, testable surface (no framework coupling)

Recommended usage:
    from app.tools.base import BaseToolsClient
    client = BaseToolsClient(api_base_url="https://api.gulong.ph/api")
    data = await client.get_json_cached("/promo_brands")
    await client.aclose()  # on shutdown

Notes:
- Designed for a single process / single event loop. Do not share across loops/threads.
- Cache is best-effort and volatile; do not use for correctness-critical paths.
"""

import aiohttp, asyncio, time, atexit
import weakref
from typing import Any, Dict, Optional, Tuple, List, Union

class BaseHTTPClient:
    """
    Summary:
        Shared HTTP base client for all agent tool classes.

    Parameters:
        api_base_url (str):
            Base URL used to build request URLs. e.g., "https://api.gulong.ph/api".
        timeout_sec (int, optional):
            Total request timeout (seconds) applied to the underlying `aiohttp.ClientSession`.
            Default: 10.
        cache_ttl_sec (int, optional):
            TTL (seconds) for the small in-memory GET cache. Default: 300.
        default_headers (dict[str, str] | None, optional):
            Default headers merged into GET requests. If None, sensible defaults are used:
            Accept, User-Agent, Origin, Connection.
        post_headers (dict[str, str] | None, optional):
            Default headers for POST requests. If None, inherits default headers and adds
            "Content-Type: application/json".

    Returns:
        BaseToolsClient:
            An initialized client. Use `await aclose()` to close the underlying session.

    Exceptions:
        None directly on construction. See method-level docs for runtime exceptions.

    Example:
        >>> client = BaseToolsClient(api_base_url="https://api.gulong.ph/api", timeout_sec=8)
        >>> brands = await client.get_json_cached("/product_list_dropdown_brand")
        >>> resp = await client.post_json("/shop", params={"page": 1, "sn": "y", "v": 1})
        >>> await client.aclose()

    Logging & Debugging:
        - This class itself does not log. Callers should log on error-shaped payloads:
          {"status": "Error", "status_code": int, "content": "..."}.
        - Wrap calls with your app logger for correlation (URL, params, agent/customer IDs, etc.).
    """
    def __init__(
        self,
        api_base_url: str = "https://api.gulong.ph/api",
        timeout_sec: int = 10,
        cache_ttl_sec: int = 300,
        default_headers: Optional[Dict[str, str]] = None,
        post_headers: Optional[Dict[str, str]] = None,
    ):
        self.api_base_url = api_base_url.rstrip("/") or "https://api.gulong.ph/api"
        self._timeout = aiohttp.ClientTimeout(total=timeout_sec)
        self._connector = aiohttp.TCPConnector(limit=50, ttl_dns_cache=300)
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[Tuple[str, Tuple[Tuple[str, Any], ...]], Tuple[float, Any]] = {}
        self._cache_ttl_sec = cache_ttl_sec
        self._lock: Optional[asyncio.Lock] = None
        self._base_headers = default_headers or {
            "Accept": "*/*",
            "User-Agent": "Mozilla/5.0",
            "Origin": "https://gulong.ph",
            "Connection": "keep-alive",
        }
        self._post_headers = post_headers or {**self._base_headers, "Content-Type": "application/json"}
        _register_client(self)

    async def get_session(self) -> aiohttp.ClientSession:
        """
        Summary:
            Lazily create or reuse a single `aiohttp.ClientSession`.

        Returns:
            aiohttp.ClientSession: The active session.

        Exceptions:
            None expected; aiohttp may raise if system resources are exhausted.

        Example:
            >>> sess = await client._get_session()
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout, connector=self._connector)
            _register_session(self._session)
        return self._session

    async def _get_lock(self) -> asyncio.Lock:
        """
        Lazily create the cache lock inside an event loop to avoid warnings
        when instantiated from a sync context.
        """
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def aclose(self):
        """
        Summary:
            Close the underlying `aiohttp.ClientSession`.

        Returns:
            None

        Exceptions:
            None

        Example:
            >>> await client.aclose()
        """
        if self._session and not self._session.closed:
            await self._session.close()

    # ---- caching + key
    def _cache_key(self, url: str, params: Optional[Dict[str, Any]]) -> Tuple[str, Tuple[Tuple[str, Any], ...]]:
        """
        Summary:
            Compute a stable GET cache key from URL + params (ignoring None values).

        Parameters:
            url (str):
                Fully-qualified request URL.
            params (dict[str, Any] | None):
                Query params.

        Returns:
            tuple: (url, tuple(sorted(params.items())))
        """
        items = tuple(sorted((k, v) for k, v in (params or {}).items() if v is not None))
        return (url, items)

    async def get_json_cached(
        self,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """
        Summary:
            GET with a small TTL cache. Good for stable endpoints (e.g., `/promo_brands`).

        Parameters:
            path (str):
                Path relative to `api_base_url`, e.g. "/promo_brands".
            params (dict[str, Any] | None):
                Query parameters (None values skipped).
            headers (dict[str, str] | None):
                Extra headers to merge with default GET headers.

        Returns:
            Any:
                Parsed JSON from server (dict/list) OR an error-shaped dict:
                {"status": "Error", "status_code": int, "content": str}

        Exceptions:
            - Does not raise network exceptions; errors are returned in error-shaped dict.

        Example:
            >>> await client.get_json_cached("/product_list_dropdown_brand")
        """
        url = f"{self.api_base_url}/{path.lstrip('/')}"
        key = self._cache_key(url, params)

        # Fast path — no lock
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and (now - hit[0]) < self._cache_ttl_sec:
            return hit[1]

        # Slow path - locked fetch + fill
        lock = await self._get_lock()
        async with lock:
            hit = self._cache.get(key)
            if hit and (time.monotonic() - hit[0]) < self._cache_ttl_sec:
                return hit[1]

            data = await self.get_json(path, params=params, headers=headers)
            if isinstance(data, (dict, list)):
                self._cache[key] = (time.monotonic(), data)
            return data

    async def get_json(self, path: str, *, params: Optional[Dict[str, Any]]=None, headers: Optional[Dict[str, str]]=None):
        url = f"{self.api_base_url}/{path.lstrip('/')}"
        sess = await self.get_session()
        merged = {**self._base_headers, **(headers or {})}
        try:
            async with sess.get(url, params=params, headers=merged) as resp:
                if resp.status != 200:
                    return {"status": "Error", "status_code": resp.status, "content": await resp.text()}
                return await resp.json(content_type=None)
        except asyncio.TimeoutError:
            return {"status": "Error", "status_code": 408, "content": "Request timed out"}
        except aiohttp.ClientError as e:
            return {"status": "Error", "status_code": 500, "content": str(e)}

    async def post_json(self, path: str, *, params: Optional[Dict[str, Any]]=None, json_data: Optional[Union[Dict, List]]=None,
                        headers: Optional[Dict[str, str]]=None, timeout_sec: Optional[int]=None):
        url = f"{self.api_base_url}/{path.lstrip('/')}"
        sess = await self.get_session()
        merged = headers or self._post_headers
        timeout = aiohttp.ClientTimeout(total=timeout_sec) if timeout_sec else self._timeout
        try:
            async with sess.post(url, params=params, json=json_data, headers=merged, timeout=timeout) as resp:
                if resp.status != 200:
                    return {"status": "Error", "status_code": resp.status, "content": await resp.text()}
                return await resp.json(content_type=None)
        except asyncio.TimeoutError:
            return {"status": "Error", "status_code": 408, "content": "Request timed out"}
        except aiohttp.ClientError as e:
            return {"status": "Error", "status_code": 500, "content": str(e)}


_CLIENTS: "weakref.WeakSet[BaseHTTPClient]" = weakref.WeakSet()
_SESSIONS: "weakref.WeakSet[aiohttp.ClientSession]" = weakref.WeakSet()


def _register_client(client: "BaseHTTPClient") -> None:
    _CLIENTS.add(client)

def _register_session(session: aiohttp.ClientSession) -> None:
    _SESSIONS.add(session)


async def _close_all_async() -> None:
    tasks = []
    for session in list(_SESSIONS):
        if not session.closed:
            tasks.append(session.close())
    for client in list(_CLIENTS):
        if client._session and not client._session.closed:  # pylint: disable=protected-access
            tasks.append(client.aclose())
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _close_all_sync() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        loop.create_task(_close_all_async())
    else:
        try:
            asyncio.run(_close_all_async())
        except Exception:
            pass


atexit.register(_close_all_sync)


def close_all_clients_sync() -> None:
    """Best-effort sync cleanup for BaseHTTPClient sessions."""
    _close_all_sync()
