import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .database import DB_PATH

MINUTE_LIMIT = 20
DAILY_LIMIT = 600
KST = timezone(timedelta(hours=9))

class QuotaExceeded(Exception):
    pass

def reserve_ai_request(
    storage: Path | None = None,
    timestamp: int | None = None,
):
    now = int(time.time()) if timestamp is None else timestamp
    db = storage if storage is not None else DB_PATH.with_name(
        "ai_quota.sqlite3"
    )

    minute_key = str(now // 60)
    day_key = datetime.fromtimestamp(
        now, KST
    ).strftime("%Y-%m-%d")

    limits = [
        ("minute", minute_key, MINUTE_LIMIT),
        ("day", day_key, DAILY_LIMIT),
    ]

    conn = sqlite3.connect(str(db), timeout=10)

    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_counters (
                period TEXT NOT NULL,
                bucket TEXT NOT NULL,
                calls INTEGER NOT NULL,
                PRIMARY KEY (period, bucket)
            )
        """)

        for period, bucket, limit in limits:
            row = conn.execute(
                """SELECT calls FROM usage_counters
                   WHERE period=? AND bucket=?""",
                (period, bucket),
            ).fetchone()

            if row and row[0] >= limit:
                raise QuotaExceeded(
                    f"{period} limit exceeded: {limit}"
                )

        for period, bucket, _ in limits:
            conn.execute("""
                INSERT INTO usage_counters
                    (period, bucket, calls)
                VALUES (?, ?, 1)
                ON CONFLICT(period, bucket)
                DO UPDATE SET calls=calls+1
            """, (period, bucket))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
