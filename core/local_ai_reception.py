"""Fixed, read-only Reception Analytics evidence for optional Local AI.

No model-controlled SQL, paths or execution. Never use the collector's
connect/report helpers: those may create or migrate the live database.
"""
from contextlib import closing
from datetime import datetime, timezone
import re
import sqlite3
import time

WINDOWS = {"24h": 86400, "7d": 604800, "30d": 2592000}
MODES = {"auto", "none", *WINDOWS}
SOURCE = "data/analytics/reception.sqlite3"
MAX_ROWS = 60000
QUERY_SECONDS = 1.5

# Auto mode is deliberately conservative; explicit selection always wins.
RECEPTION = re.compile(r"\b(?:ais|ads[- ]?b|reception|ontvangst|schepen|scheepvaart|schip|vaartuig\w*|vessel\w*|ship\w*|aircraft|airplanes?|vliegtuig\w*|vliegtuigen|bereik|range|targets?)\b", re.I)
PERIODS = (
    ("30d", r"\b(?:30\s*(?:d|days?|dagen)|(?:last|past|afgelopen|laatste)\s+(?:month|maand))\b"),
    ("7d", r"\b(?:7\s*(?:d|days?|dagen)|(?:last|past|afgelopen|laatste)\s+week)\b"),
    ("24h", r"\b(?:24\s*(?:h|hours?|uur)|(?:last|past|afgelopen|laatste)\s+(?:day|dag))\b"),
)


def select_period(question, mode):
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError("Invalid reception data period.")
    if mode == "none":
        return None
    if mode != "auto":
        return mode
    if not RECEPTION.search(question):
        return None
    found = [period for period, pattern in PERIODS if re.search(pattern, question, re.I)]
    return found[0] if len(found) == 1 else "24h" if not found else None


def utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds") if epoch is not None else None


def read_evidence(root, period, *, now=None):
    if period not in WINDOWS:
        raise ValueError("Unsupported analytics period.")
    end = int(time.time() if now is None else now)
    start = end - WINDOWS[period]
    result = {"source": SOURCE, "period": period, "window_start_utc": utc(start),
              "window_end_utc": utc(end), "scope": "whole station; simultaneous sampled targets, not unique totals",
              "sample_interval_seconds": 60, "expected_samples": WINDOWS[period] // 60}
    path = root / SOURCE
    if not path.is_file():
        return dict(result, status="unavailable", reason="Reception database missing.")
    deadline = time.monotonic() + QUERY_SECONDS
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.3)) as db:
            db.execute("PRAGMA query_only=ON")
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            # One consistent snapshot, no write transaction or migration.
            db.execute("BEGIN")
            columns = {row[1] for row in db.execute("PRAGMA table_info(samples)")}
            if "ts" not in columns:
                return dict(result, status="unavailable", reason="Reception samples schema missing.")
            n, first, last = db.execute(
                "SELECT COUNT(*), MIN(ts), MAX(ts) FROM (SELECT ts FROM samples WHERE ts > ? AND ts <= ? LIMIT ?)",
                (start, end, MAX_ROWS + 1)).fetchone()
            if n > MAX_ROWS:
                return dict(result, status="unavailable", reason="Reception query row limit exceeded.")
            result.update(samples=n, first_sample_utc=utc(first), last_sample_utc=utc(last),
                          coverage_pct=round(min(100, 100*n/result["expected_samples"]), 1),
                          latest_sample_age_seconds=end-last if last is not None else None,
                          latest_sample_stale=(end-last > 180) if last is not None else None)
            if not n:
                return dict(result, status="no_samples", reason="No samples in selected period.")
            for service, fields in (
                ("ais", (("targets", "ais_fresh", 1e9), ("rate", "ais_rate", 1e12), ("range_nm", "ais_valid_range", 300))),
                ("adsb", (("targets", "adsb_targets", 1e9), ("rate", "adsb_rate", 1e12), ("range_nm", "adsb_range", 500))),
            ):
                on = service + "_on"
                item = {"active_samples": None, "inactive_samples": None, "unknown_activity_samples": None}
                if on in columns:
                    active, inactive = db.execute(
                        f"SELECT COUNT(CASE WHEN {on}=1 THEN 1 END), COUNT(CASE WHEN {on}=0 THEN 1 END) FROM samples WHERE ts > ? AND ts <= ?",
                        (start, end)).fetchone()
                    item.update(active_samples=active, inactive_samples=inactive, unknown_activity_samples=n-active-inactive)
                for key, col, upper in fields:
                    metric = {"valid_samples": 0, "mean": None, "peak": None}
                    # No legacy AIS total or range fallback. Rate is only taken
                    # from active, validated-era AIS samples, not legacy rows.
                    if on in columns and col in columns and (service != "ais" or "ais_fresh" in columns):
                        validated = " AND typeof(ais_fresh) IN ('integer','real') AND ais_fresh >= 0" if service == "ais" else ""
                        count, mean, peak = db.execute(
                            f"SELECT COUNT({col}), ROUND(AVG({col}),2), MAX({col}) FROM samples "
                            f"WHERE ts > ? AND ts <= ? AND {on}=1 AND typeof({col}) IN ('integer','real') "
                            f"AND {col} BETWEEN 0 AND ?{validated}", (start, end, upper)).fetchone()
                        metric.update(valid_samples=count, mean=mean, peak=peak)
                    item[key] = metric
                result[service] = item
            return dict(result, status="ok")
    except (OSError, sqlite3.Error, ValueError, OverflowError):
        return dict(result, status="unavailable", reason="Reception database could not be read within safety limits.")
