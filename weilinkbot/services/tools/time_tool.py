"""get_current_time tool — returns the current date and time."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from .base import Tool

_DEFAULT_TZ = "Asia/Shanghai"

# Fallback timezone map (name → UTC offset hours) for systems without tzdata
_TZ_OFFSETS: dict[str, float] = {
    "Asia/Shanghai": 8, "Asia/Tokyo": 9, "Asia/Seoul": 9,
    "Asia/Singapore": 8, "Asia/Hong_Kong": 8, "Asia/Taipei": 8,
    "Asia/Kolkata": 5.5, "Asia/Dubai": 4, "Asia/Bangkok": 7,
    "America/New_York": -5, "America/Chicago": -6,
    "America/Denver": -7, "America/Los_Angeles": -8,
    "Europe/London": 0, "Europe/Paris": 1, "Europe/Berlin": 1,
    "Europe/Moscow": 3, "Australia/Sydney": 11,
    "UTC": 0,
}


def _resolve_tz(timezone_name: str):
    """Resolve timezone to a tzinfo, with fallback for missing tzdata."""
    # Try zoneinfo first (requires tzdata on Windows)
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(timezone_name), timezone_name
    except Exception:
        pass

    # Fallback: lookup common timezone names
    offset_hours = _TZ_OFFSETS.get(timezone_name)
    if offset_hours is not None:
        tz = timezone(timedelta(hours=offset_hours))
        return tz, timezone_name

    # Try parsing as UTC offset like "+08:00" or "-05:00"
    try:
        sign = 1 if timezone_name[0] == "+" else -1
        parts = timezone_name.lstrip("+-").split(":")
        hours = int(parts[0])
        minutes = int(parts[1]) if len(parts) > 1 else 0
        tz = timezone(timedelta(hours=sign * hours, minutes=sign * minutes))
        return tz, f"UTC{timezone_name}"
    except Exception:
        pass

    return None, None


class GetCurrentTimeTool(Tool):
    name = "get_current_time"
    description = (
        "Get the current date and time. "
        "Optionally specify a timezone (e.g. 'Asia/Shanghai', 'America/New_York', 'UTC'). "
        "Defaults to Asia/Shanghai."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": f"Timezone name (IANA format or UTC offset like '+08:00'). Defaults to '{_DEFAULT_TZ}'.",
            },
        },
        "required": [],
        "additionalProperties": False,
    }

    async def execute(self, *, timezone: str = _DEFAULT_TZ, **kwargs) -> str:
        tz, tz_label = _resolve_tz(timezone)
        if tz is None:
            return (
                f"Error: Unknown timezone '{timezone}'. "
                f"Use IANA format (e.g. 'Asia/Shanghai') or UTC offset (e.g. '+08:00')."
            )

        now = datetime.now(tz)
        weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        weekday_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        wd = now.weekday()
        return (
            f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S')} ({weekday_names[wd]}/{weekday_cn[wd]})\n"
            f"Timezone: {tz_label}\n"
            f"UTC offset: {now.strftime('%z')}"
        )
