import sqlite3

import pytest

from app.ai_quota import QuotaExceeded, reserve_ai_request


def test_twenty_per_minute_and_next_minute(tmp_path):
    path = tmp_path / "quota.sqlite3"
    for _ in range(20):
        reserve_ai_request(path, 60)
    with pytest.raises(QuotaExceeded):
        reserve_ai_request(path, 60)
    reserve_ai_request(path, 120)


def test_daily_limit_and_kst_midnight(tmp_path):
    path = tmp_path / "quota.sqlite3"
    reserve_ai_request(path, 0)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE usage_counters SET calls=600 WHERE period='day'")
    with pytest.raises(QuotaExceeded):
        reserve_ai_request(path, 120)
    # 1970-01-01 15:00 UTC is the next Korean calendar day.
    reserve_ai_request(path, 15 * 60 * 60)
