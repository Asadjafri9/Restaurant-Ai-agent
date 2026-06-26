from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.routes.analytics import BUSINESS_TZ, resolve_date_range


def test_today_range_is_calendar_day_in_business_tz():
    date_from, date_to, granularity = resolve_date_range("today", None, None)
    now = datetime.now(BUSINESS_TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    assert date_from == start
    assert date_to == start + timedelta(days=1)
    assert granularity == "hour"


def test_7d_range_includes_today():
    date_from, date_to, granularity = resolve_date_range("7d", None, None)
    now = datetime.now(BUSINESS_TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    assert date_from == start - timedelta(days=6)
    assert date_to == start + timedelta(days=1)
    assert granularity == "day"


def test_all_time_range_unchanged():
    legacy_from = datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC"))
    date_from, date_to, granularity = resolve_date_range(None, legacy_from, None)
    assert date_from == legacy_from
    assert date_to is None
    assert granularity == "day"
