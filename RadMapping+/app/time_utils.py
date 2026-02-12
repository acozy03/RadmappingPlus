from datetime import datetime
from zoneinfo import ZoneInfo

EASTERN_TZ = ZoneInfo("America/New_York")


def eastern_now() -> datetime:
    """Return current timezone-aware datetime in US Eastern time."""
    return datetime.now(EASTERN_TZ)


def eastern_today():
    """Return current date in US Eastern time."""
    return eastern_now().date()
