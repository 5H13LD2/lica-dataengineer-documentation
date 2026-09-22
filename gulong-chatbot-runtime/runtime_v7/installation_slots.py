"""Runtime V7 read-only installation slot lookup.

This module ports the scheduling read path from Runtime V6 into the V7
product/service slice. It checks Gulong branch slot endpoints and applies the
same lead-time and same-day gating rules before exposing candidate slots.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from runtime.http.sync_http_client import SyncHTTPClient, SyncHTTPClientConfig
from runtime_v7.installation_partners import DEFAULT_API_BASE_URL

try:
    from configs.log_utils import manila_tz
except Exception:  # pragma: no cover - fallback for isolated imports
    from zoneinfo import ZoneInfo

    manila_tz = ZoneInfo("Asia/Manila")


DEFAULT_DAY_START = dt.time(8, 0)
DEFAULT_DAY_END = dt.time(17, 0)
MIDDAY_START = dt.time(11, 0)
MIDDAY_END = dt.time(15, 0)
MAX_LOOKAHEAD_DAYS = 14
INSTALL_TRANSACTION_TYPE = 1
DEFAULT_SLOT_LIMIT = 2
DEFAULT_API_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 0.15


@dataclass(frozen=True)
class GatedWindow:
    """Computed allowed scheduling window for one branch lookup."""

    start: dt.datetime
    first_day_end: Optional[dt.datetime]
    reason: str
    lead_days: int = 0


class InstallationSlotLookup:
    """Read-only branch slot helper for Runtime V7 service tools."""

    def __init__(
        self,
        *,
        http_client: Optional[Any] = None,
        base_url: Optional[str] = None,
        retries: int = DEFAULT_API_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    ) -> None:
        resolved_base_url = str(base_url or os.getenv("GULONG_API_BASE_URL") or DEFAULT_API_BASE_URL).rstrip("/")
        self._http = http_client or SyncHTTPClient(config=SyncHTTPClientConfig(base_url=resolved_base_url))
        self._retries = max(0, int(retries or 0))
        self._retry_backoff_seconds = max(0.0, float(retry_backoff_seconds or 0.0))
        self._holidays: Optional[set[str]] = None
        self._holidays_ts: Optional[dt.datetime] = None
        self._holidays_ttl_sec = 3600
        self._day_capacity_cache: Dict[str, Tuple[dt.datetime, Dict[str, Any]]] = {}
        self._slot_time_cache: Dict[str, Tuple[dt.datetime, List[dt.time]]] = {}
        self._cache_ttl_sec = 300

    def branch_slots(
        self,
        branch: Dict[str, Any],
        *,
        request_time: Optional[str] = None,
        limit: int = DEFAULT_SLOT_LIMIT,
        max_days: int = MAX_LOOKAHEAD_DAYS,
        prefer_weekend: bool = False,
        preferred_weekday: Optional[str] = None,
        preferred_date: Optional[str] = None,
        preferred_date_start: Optional[str] = None,
        preferred_date_end: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return candidate slots for a branch after lead-time gating."""

        branch_id = _branch_id(branch)
        if branch_id is None:
            return {
                "status": "not_found",
                "branch_id": None,
                "branch_name": _clean_text(branch.get("name")),
                "slots": [],
                "reason": "missing_branch_id",
            }

        req_time, gating = self._resolve_request_and_gating(branch, request_time)
        slots = self._collect_candidate_slots(
            branch,
            gating,
            limit=max(1, int(limit or DEFAULT_SLOT_LIMIT)),
            max_days=max(0, min(MAX_LOOKAHEAD_DAYS, int(max_days or MAX_LOOKAHEAD_DAYS))),
            prefer_weekend=prefer_weekend,
            preferred_weekday=preferred_weekday,
            preferred_date=preferred_date,
            preferred_date_start=preferred_date_start,
            preferred_date_end=preferred_date_end,
        )
        payload: Dict[str, Any] = {
            "status": "ok" if slots else "unavailable",
            "branch_id": branch_id,
            "branch_name": _clean_text(branch.get("name")),
            "request_time": _format_dt(req_time),
            "gating_reason": gating.reason,
            "earliest_allowed": _format_dt(gating.start),
            "lead_days_applied": gating.lead_days,
            "slots": slots,
        }
        if gating.first_day_end:
            payload["first_day_window_end"] = _format_dt(gating.first_day_end)
        return payload

    def branch_availability(
        self,
        branch: Dict[str, Any],
        *,
        request_time: Optional[str] = None,
        horizon_days: int = MAX_LOOKAHEAD_DAYS,
        not_before_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return the next open slot for a branch, if any."""

        branch_id = _branch_id(branch)
        if branch_id is None:
            return {"status": "not_found", "branch_id": None, "slots": []}
        req_time, gating = self._resolve_request_and_gating(branch, request_time)
        slot = self._find_next_available_slot(
            branch,
            gating,
            horizon_days=horizon_days,
            not_before_date=not_before_date,
        )
        payload: Dict[str, Any] = {
            "status": "ok" if slot else "unavailable",
            "branch_id": branch_id,
            "branch_name": _clean_text(branch.get("name")),
            "request_time": _format_dt(req_time),
            "gating_reason": gating.reason,
            "earliest_allowed": _format_dt(gating.start),
            "lead_days_applied": gating.lead_days,
        }
        if gating.first_day_end:
            payload["first_day_window_end"] = _format_dt(gating.first_day_end)
        if slot:
            payload["next_open_slot"] = slot
        return payload

    def _resolve_request_and_gating(
        self,
        branch: Dict[str, Any],
        request_time: Optional[str],
    ) -> Tuple[dt.datetime, GatedWindow]:
        req_time = _parse_request_time(request_time)
        lead_days = _coerce_int(branch.get("lead_day") or branch.get("lead_days"), default=0)
        gating = _compute_gated_window(req_time, lead_days=lead_days)
        return req_time, gating

    def _find_next_available_slot(
        self,
        branch: Dict[str, Any],
        gating: GatedWindow,
        *,
        horizon_days: int = MAX_LOOKAHEAD_DAYS,
        not_before_date: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        branch_id = _branch_id(branch)
        if branch_id is None:
            return None
        holidays = self._get_holidays()
        search_date = gating.start.date()
        parsed_not_before = _parse_date(not_before_date)
        if parsed_not_before and parsed_not_before > search_date:
            search_date = parsed_not_before
        for offset in range(max(0, min(MAX_LOOKAHEAD_DAYS, int(horizon_days or MAX_LOOKAHEAD_DAYS))) + 1):
            current_date = search_date + dt.timedelta(days=offset)
            if current_date.isoformat() in holidays:
                continue
            times = self._get_day_available_times(branch_id, current_date)
            if not times:
                continue
            window_start, window_end = _window_for_date(current_date, gating)
            filtered = _filter_times_by_window(times, window_start, window_end)
            if not filtered:
                continue
            return _slot_payload(
                branch=branch,
                branch_id=branch_id,
                slot_date=current_date,
                slot_time=filtered[0],
                reason=gating.reason if current_date == gating.start.date() else "default_hours",
            )
        return None

    def _collect_candidate_slots(
        self,
        branch: Dict[str, Any],
        gating: GatedWindow,
        *,
        limit: int,
        max_days: int,
        prefer_weekend: bool,
        preferred_weekday: Optional[str],
        preferred_date: Optional[str],
        preferred_date_start: Optional[str],
        preferred_date_end: Optional[str],
    ) -> List[Dict[str, Any]]:
        branch_id = _branch_id(branch)
        if branch_id is None:
            return []
        slots: List[Dict[str, Any]] = []
        holidays = self._get_holidays()
        allowed_weekdays = {5, 6} if prefer_weekend else None
        preferred_date_obj = _parse_date(preferred_date)
        preferred_start_obj = _parse_date(preferred_date_start)
        preferred_end_obj = _parse_date(preferred_date_end)
        preferred_weekday_idx = _parse_weekday(preferred_weekday)

        if preferred_date_obj:
            if preferred_date_obj < gating.start.date():
                preferred_date_obj = gating.start.date()
            search_dates = [preferred_date_obj]
        elif preferred_start_obj or preferred_end_obj:
            start_date = preferred_start_obj or gating.start.date()
            end_date = preferred_end_obj or start_date
            if start_date < gating.start.date():
                start_date = gating.start.date()
            if end_date < start_date:
                end_date = start_date
            end_date = min(end_date, start_date + dt.timedelta(days=max_days))
            search_dates = [
                start_date + dt.timedelta(days=offset)
                for offset in range((end_date - start_date).days + 1)
            ]
        elif preferred_weekday_idx is not None:
            search_dates = _find_preferred_weekday_dates(gating.start.date(), preferred_weekday_idx, max_days=max_days)
        else:
            search_dates = [gating.start.date() + dt.timedelta(days=offset) for offset in range(max_days + 1)]

        for current_date in search_dates:
            if len(slots) >= limit:
                break
            if current_date.isoformat() in holidays:
                continue
            if allowed_weekdays and current_date.weekday() not in allowed_weekdays:
                continue
            times = self._get_day_available_times(branch_id, current_date)
            if not times:
                continue
            window_start, window_end = _window_for_date(current_date, gating)
            for slot_time in _filter_times_by_window(times, window_start, window_end):
                slots.append(
                    _slot_payload(
                        branch=branch,
                        branch_id=branch_id,
                        slot_date=current_date,
                        slot_time=slot_time,
                        reason=gating.reason if current_date == gating.start.date() else "default_hours",
                    )
                )
                if len(slots) >= limit:
                    break
        return slots

    def _get_holidays(self) -> set[str]:
        now = _now_manila()
        if self._holidays is not None and self._holidays_ts:
            if (now - self._holidays_ts).total_seconds() < self._holidays_ttl_sec:
                return self._holidays
        payload = self._get_json_with_retry("/holidays")
        holidays = {str(item).strip() for item in payload if str(item).strip()} if isinstance(payload, list) else set()
        self._holidays = holidays
        self._holidays_ts = now
        return holidays

    def _get_day_available_times(self, branch_id: int, date: dt.date) -> List[dt.time]:
        cache_key = f"{branch_id}:{date.isoformat()}"
        now = _now_manila()
        cached = self._slot_time_cache.get(cache_key)
        if cached and (now - cached[0]).total_seconds() < self._cache_ttl_sec:
            return list(cached[1])
        times = self._fetch_day_available_times(branch_id, date)
        self._slot_time_cache[cache_key] = (now, times)
        return times

    def _get_day_capacity_info(self, branch_id: int, date: dt.date) -> Dict[str, Any]:
        cache_key = f"{branch_id}:{date.isoformat()}:{INSTALL_TRANSACTION_TYPE}"
        now = _now_manila()
        cached = self._day_capacity_cache.get(cache_key)
        if cached and (now - cached[0]).total_seconds() < self._cache_ttl_sec:
            return dict(cached[1])

        date_str = date.isoformat()
        payload = self._get_json_with_retry(
            "/available_days",
            params={"branch_id": branch_id, "sd": date_str, "trans_type": INSTALL_TRANSACTION_TYPE},
        )
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                candidate = item.get(date_str)
                if isinstance(candidate, dict):
                    self._day_capacity_cache[cache_key] = (now, dict(candidate))
                    return dict(candidate)
        self._day_capacity_cache[cache_key] = (now, {})
        return {}

    def _fetch_day_available_times(self, branch_id: int, date: dt.date) -> List[dt.time]:
        date_str = date.isoformat()
        day_info = self._get_day_capacity_info(branch_id, date)
        if not day_info:
            legacy = self._get_json_with_retry(
                "/slots",
                params={"branch_id": branch_id, "sd": date_str, "trans_type": INSTALL_TRANSACTION_TYPE},
            )
            if isinstance(legacy, list) and legacy:
                first = legacy[0] if isinstance(legacy[0], dict) else {}
                day_info = first.get(date_str, {}) if isinstance(first.get(date_str, {}), dict) else {}
        if int(day_info.get("total_slots", 0) or 0) <= int(day_info.get("used_slots", 0) or 0):
            return []

        schedule = self._get_json_with_retry(
            "/available_slots",
            params={"branch": branch_id, "date": date_str, "tType": INSTALL_TRANSACTION_TYPE},
        )
        if not isinstance(schedule, dict):
            schedule = self._get_json_with_retry(
                "/branchSched",
                params={"branch": branch_id, "date": date_str, "tType": INSTALL_TRANSACTION_TYPE},
            )
        if not isinstance(schedule, dict):
            return []

        times: List[dt.time] = []
        for entry in schedule.get("sched", []):
            if isinstance(entry, dict) and entry.get("available") is False:
                continue
            time_str = entry.get("available_time") if isinstance(entry, dict) else ""
            if not time_str:
                continue
            try:
                times.append(dt.datetime.strptime(str(time_str), "%H:%M:%S").time())
            except ValueError:
                continue
        return sorted(times)

    def _get_json_with_retry(self, path: str, *, params: Optional[Dict[str, Any]] = None) -> Any:
        attempts = self._retries + 1
        last_payload: Any = None
        for attempt in range(1, attempts + 1):
            payload = self._http.get_json(path, params=params)
            last_payload = payload
            if not _is_error_payload(payload):
                return payload
            if attempt < attempts and self._retry_backoff_seconds:
                time.sleep(self._retry_backoff_seconds)
        return last_payload


def preferred_date_options(
    value: Any,
    *,
    request_time: Optional[str] = None,
    preferred_date_start: Optional[str] = None,
    preferred_date_end: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert customer date wording into slot-search options."""

    text = _clean_text(value).lower()
    request_dt = _parse_request_time(request_time)
    explicit_start = _parse_date(preferred_date_start)
    explicit_end = _parse_date(preferred_date_end)
    if explicit_start or explicit_end:
        start = explicit_start or explicit_end
        end = explicit_end or explicit_start
        if end and start and end < start:
            end = start
        return _date_range_options(start, end, request_dt=request_dt, label="explicit_date_range")
    if not text:
        return _empty_date_options()
    parsed_range = _parse_text_date_range(text)
    if parsed_range:
        return _date_range_options(parsed_range[0], parsed_range[1], request_dt=request_dt, label="text_date_range")
    if text in {"today", "ngayon", "asap", "now", "same day", "same-day"}:
        return {
            "preferred_date": request_dt.date().isoformat(),
            "preferred_date_start": None,
            "preferred_date_end": None,
            "preferred_weekday": None,
            "prefer_weekend": False,
            "same_day_requested": True,
            "date_search_mode": "exact_date",
        }
    if text in {"tomorrow", "bukas"}:
        return {
            "preferred_date": (request_dt.date() + dt.timedelta(days=1)).isoformat(),
            "preferred_date_start": None,
            "preferred_date_end": None,
            "preferred_weekday": None,
            "prefer_weekend": False,
            "same_day_requested": False,
            "date_search_mode": "exact_date",
        }
    if "next week" in text:
        start = _next_weekday(request_dt.date(), 0)
        return _date_range_options(start, start + dt.timedelta(days=6), request_dt=request_dt, label="next_week")
    if "this week" in text:
        start = request_dt.date()
        end = start + dt.timedelta(days=(6 - start.weekday()))
        return _date_range_options(start, end, request_dt=request_dt, label="this_week")
    if "weekend" in text:
        if "next" in text or "this" in text:
            start = _next_weekday(request_dt.date() - dt.timedelta(days=1), 5)
            return _date_range_options(start, start + dt.timedelta(days=1), request_dt=request_dt, label="weekend_range")
        options = _empty_date_options()
        options.update({"prefer_weekend": True, "date_search_mode": "weekend"})
        return options
    weekday_date = _preferred_weekday_date(text, request_dt.date())
    if weekday_date:
        return {
            "preferred_date": weekday_date.isoformat(),
            "preferred_date_start": None,
            "preferred_date_end": None,
            "preferred_weekday": None,
            "prefer_weekend": False,
            "same_day_requested": weekday_date == request_dt.date(),
            "date_search_mode": "exact_weekday",
        }
    parsed_date = _parse_date(text)
    if parsed_date:
        return {
            "preferred_date": parsed_date.isoformat(),
            "preferred_date_start": None,
            "preferred_date_end": None,
            "preferred_weekday": None,
            "prefer_weekend": False,
            "same_day_requested": parsed_date == request_dt.date(),
            "date_search_mode": "exact_date",
        }
    weekday = _parse_weekday(text)
    return {
        "preferred_date": None,
        "preferred_date_start": None,
        "preferred_date_end": None,
        "preferred_weekday": text if weekday is not None else None,
        "prefer_weekend": False,
        "same_day_requested": False,
        "date_search_mode": "weekday" if weekday is not None else None,
    }


def _empty_date_options() -> Dict[str, Any]:
    return {
        "preferred_date": None,
        "preferred_date_start": None,
        "preferred_date_end": None,
        "preferred_weekday": None,
        "prefer_weekend": False,
        "same_day_requested": False,
        "date_search_mode": None,
    }


def _date_range_options(
    start: Optional[dt.date],
    end: Optional[dt.date],
    *,
    request_dt: dt.datetime,
    label: str,
) -> Dict[str, Any]:
    start = start or request_dt.date()
    end = end or start
    if end < start:
        end = start
    return {
        "preferred_date": None,
        "preferred_date_start": start.isoformat(),
        "preferred_date_end": end.isoformat(),
        "preferred_weekday": None,
        "prefer_weekend": False,
        "same_day_requested": start <= request_dt.date() <= end,
        "date_search_mode": label,
    }


def _parse_text_date_range(text: str) -> Optional[Tuple[dt.date, dt.date]]:
    dates = [
        dt.datetime.strptime(match, "%Y-%m-%d").date()
        for match in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
    ]
    if len(dates) >= 2:
        start, end = dates[0], dates[1]
        return (start, max(start, end))
    return None


def _preferred_weekday_date(text: str, request_date: dt.date) -> Optional[dt.date]:
    weekday = _parse_weekday(text)
    if weekday is None:
        return None
    normalized = _clean_text(text).lower()
    has_modifier = any(token in normalized.split() for token in {"next", "this", "upcoming"})
    if not has_modifier:
        return None
    if "next" in normalized or "upcoming" in normalized:
        return _next_weekday(request_date, weekday)
    days_ahead = (weekday - request_date.weekday()) % 7
    return request_date + dt.timedelta(days=days_ahead)


def slot_is_same_day(slot: Dict[str, Any], *, request_time: Optional[str] = None) -> bool:
    """Return whether a slot date is the request date in Manila time."""

    slot_date = _parse_date(slot.get("date"))
    if slot_date is None:
        return False
    return slot_date == _parse_request_time(request_time).date()


def compact_slot(slot: Dict[str, Any], *, request_time: Optional[str] = None) -> Dict[str, Any]:
    """Return compact model-facing slot data."""

    return {
        "slot_ref": slot.get("slot_ref"),
        "start": slot.get("start"),
        "end": slot.get("end"),
        "date": slot.get("date"),
        "weekday": slot.get("weekday"),
        "time_text": slot.get("time_text"),
        "same_day": slot_is_same_day(slot, request_time=request_time),
    }


def _compute_gated_window(request_time: dt.datetime, *, lead_days: int = 0) -> GatedWindow:
    request_time = _ensure_tz(request_time)
    weekday = request_time.weekday()
    clock = request_time.time()

    if weekday == 5 and clock < MIDDAY_START:
        monday = _next_weekday(request_time.date(), 0)
        start = _local_dt(monday, DEFAULT_DAY_START)
        gating = GatedWindow(start=start, first_day_end=None, reason="saturday_before_11")
    elif (weekday == 5 and clock >= MIDDAY_START) or weekday == 6:
        monday = request_time.date() if weekday == 0 else _next_weekday(request_time.date(), 0)
        start = _local_dt(monday, MIDDAY_START)
        end = _local_dt(monday, MIDDAY_END)
        gating = GatedWindow(start=start, first_day_end=end, reason="weekend_lock_to_monday")
    elif clock >= DEFAULT_DAY_END:
        next_day = request_time.date() + dt.timedelta(days=1)
        start = _local_dt(next_day, MIDDAY_START)
        end = _local_dt(next_day, MIDDAY_END)
        gating = GatedWindow(start=start, first_day_end=end, reason="after_hours")
    elif clock < MIDDAY_START:
        same_day_open = _local_dt(request_time.date(), DEFAULT_DAY_START)
        start = max(request_time, same_day_open)
        end = _local_dt(request_time.date(), MIDDAY_END)
        gating = GatedWindow(start=start, first_day_end=end, reason="same_day_before_11")
    else:
        next_day = request_time.date() + dt.timedelta(days=1)
        start = _local_dt(next_day, DEFAULT_DAY_START)
        gating = GatedWindow(start=start, first_day_end=None, reason="same_day_after_11")

    if lead_days > 0:
        lead_date = request_time.date() + dt.timedelta(days=int(lead_days))
        lead_start = _local_dt(lead_date, DEFAULT_DAY_START)
        start = gating.start
        first_day_end = gating.first_day_end
        if lead_start > start:
            start = lead_start
            if first_day_end and first_day_end.date() != start.date():
                first_day_end = None
        elif lead_start.date() == start.date() and lead_start.time() > start.time():
            start = lead_start
        return GatedWindow(
            start=start,
            first_day_end=first_day_end,
            reason=f"{gating.reason}|lead_time",
            lead_days=int(lead_days),
        )
    return GatedWindow(start=gating.start, first_day_end=gating.first_day_end, reason=gating.reason, lead_days=0)


def _slot_payload(
    *,
    branch: Dict[str, Any],
    branch_id: int,
    slot_date: dt.date,
    slot_time: dt.time,
    reason: str,
) -> Dict[str, Any]:
    start_dt = _local_dt(slot_date, slot_time)
    end_dt = start_dt + dt.timedelta(hours=1)
    slot_ref = f"slot_{branch_id}_{slot_date.isoformat()}_{slot_time.strftime('%H%M')}"
    return {
        "slot_ref": slot_ref,
        "branch_id": branch_id,
        "branch_name": _clean_text(branch.get("name")),
        "start": _format_dt(start_dt),
        "end": _format_dt(end_dt),
        "date": slot_date.isoformat(),
        "weekday": start_dt.strftime("%A"),
        "time_text": start_dt.strftime("%I:%M %p").lstrip("0"),
        "reason": reason,
    }


def _window_for_date(current_date: dt.date, gating: GatedWindow) -> Tuple[dt.time, Optional[dt.time]]:
    if current_date == gating.start.date():
        return gating.start.time(), gating.first_day_end.time() if gating.first_day_end else None
    return DEFAULT_DAY_START, None


def _filter_times_by_window(
    times: Sequence[dt.time],
    window_start: dt.time,
    window_end: Optional[dt.time],
) -> List[dt.time]:
    return [
        slot_time
        for slot_time in times
        if slot_time >= window_start and (window_end is None or slot_time <= window_end)
    ]


def _parse_request_time(request_time: Optional[str]) -> dt.datetime:
    if request_time:
        parsed = _coerce_to_manila(request_time)
        if parsed:
            return parsed
    return _now_manila()


def _parse_date(value: Any) -> Optional[dt.date]:
    text = _clean_text(value)
    if not text:
        return None
    try:
        return dt.datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_weekday(value: Any) -> Optional[int]:
    text = _clean_text(value).lower()
    mapping = {
        "monday": 0,
        "mon": 0,
        "tuesday": 1,
        "tue": 1,
        "tues": 1,
        "wednesday": 2,
        "wed": 2,
        "thursday": 3,
        "thu": 3,
        "thur": 3,
        "thurs": 3,
        "friday": 4,
        "fri": 4,
        "saturday": 5,
        "sat": 5,
        "sunday": 6,
        "sun": 6,
    }
    if text in mapping:
        return mapping[text]
    for token in re.findall(r"[a-z]+", text):
        if token in mapping:
            return mapping[token]
    return None


def _find_preferred_weekday_dates(start_date: dt.date, weekday: int, *, max_days: int) -> List[dt.date]:
    dates: List[dt.date] = []
    for offset in range(max_days + 1):
        current = start_date + dt.timedelta(days=offset)
        if current.weekday() == weekday:
            dates.append(current)
    return dates


def _coerce_to_manila(value: Any) -> Optional[dt.datetime]:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return _ensure_tz(value)
    text = _clean_text(value)
    if not text:
        return None
    candidates = [text, text.replace(" ", "T")]
    for candidate in candidates:
        try:
            return _ensure_tz(dt.datetime.fromisoformat(candidate))
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = dt.datetime.strptime(text, fmt)
            return _ensure_tz(parsed)
        except ValueError:
            continue
    return None


def _ensure_tz(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        if hasattr(manila_tz, "localize"):
            return manila_tz.localize(value)
        return value.replace(tzinfo=manila_tz)
    return value.astimezone(manila_tz)


def _local_dt(date: dt.date, clock: dt.time) -> dt.datetime:
    naive = dt.datetime.combine(date, clock)
    if hasattr(manila_tz, "localize"):
        return manila_tz.localize(naive)
    return naive.replace(tzinfo=manila_tz)


def _format_dt(value: dt.datetime) -> str:
    return _ensure_tz(value).strftime("%Y-%m-%d %H:%M:%S")


def _now_manila() -> dt.datetime:
    return dt.datetime.now(tz=manila_tz)


def _next_weekday(start: dt.date, weekday: int) -> dt.date:
    days_ahead = (weekday - start.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return start + dt.timedelta(days=days_ahead)


def _branch_id(branch: Dict[str, Any]) -> Optional[int]:
    try:
        return int(branch.get("branch_id") or branch.get("id"))
    except Exception:
        return None


def _clean_text(value: Any) -> str:
    import re

    return re.sub(r"\s+", " ", str(value or "").strip())


def _coerce_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _is_error_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and str(payload.get("status") or "").lower() == "error"
