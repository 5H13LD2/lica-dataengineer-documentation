"""
Time helpers for runtime (Asia/Manila, YYYY-MM-DD HH:MM:SS).

Usage:
    from runtime.utils.time_utils import now_manila_str
    ts = now_manila_str()
"""

from __future__ import annotations

from datetime import datetime

from configs.log_utils import manila_tz


def now_manila_str() -> str:
    """Return current time in Asia/Manila as YYYY-MM-DD HH:MM:SS."""
    return datetime.now(manila_tz).strftime("%Y-%m-%d %H:%M:%S")
