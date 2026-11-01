"""SDRCC passive reception history, with 90-day retention and activity context.

Historical pre-0.69.16 AIS totals were not freshness-checked. They remain stored
but are deliberately excluded from validated vessel and distance charts.
"""
from __future__ import annotations
import math
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from core import config, mission_engine, receiver_monitor

DB = Path(__file__).resolve().parent.parent / "data" / "analytics" / "reception.sqlite3"
_lock = threading.Lock()
_started = False


def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=6)
    db.execute("PRAGMA busy_timeout=6000")
    db.execute("""CREATE TABLE IF NOT EXISTS samples
       (ts INTEGER PRIMARY KEY, ais_on INTEGER, ais_targets INTEGER, ais_rate REAL,
        ais_range REAL, adsb_on INTEGER, adsb_targets INTEGER, adsb_rate REAL,
        adsb_range REAL)""")
    columns = {c[1] for c in db.execute("PRAGMA table_info(samples)")}
    for col, kind in (("ais_fresh", "INTEGER"), ("ais_valid_range", "REAL"),
                      ("mission_on", "INTEGER"), ("marine_on", "INTEGER"),
                      ("airband_on", "INTEGER"), ("ais_catcher_total", "INTEGER")):
        if col not in columns:
            db.execute(f"ALTER TABLE samples ADD COLUMN {col} {kind}")
    return db


def active(service):
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", service],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=3, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


def fresh_ais():
    """Count distinct, validated, positioned MMSIs seen <=5 min ago.

    Compute range from station coordinates (great circle in NM) instead of
    trusting feed 'distance', whose units and stale outliers can be misleading.
    """
    raw, _source = receiver_monitor._read_ais_ships()
    if raw is None:
        return None, None
    rows = receiver_monitor._extract_list(raw, ("ships", "vessels", "targets", "data"))
    position = None
    try:
        home = config.get_home_position()
        if home.get("configured"):
            lat, lon = num(home.get("latitude")), num(home.get("longitude"))
            if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
                position = (lat, lon)
    except (OSError, ValueError, TypeError, KeyError):
        pass
    found, ranges = set(), []
    for ship in rows:
        if not isinstance(ship, dict):
            continue
        mmsi = receiver_monitor._valid_mmsi(ship.get("mmsi"))
        age = receiver_monitor._first_number(ship, ("last_signal", "last_signal_seconds", "age"))
        lat = receiver_monitor._first_number(ship, ("lat", "latitude"))
        lon = receiver_monitor._first_number(ship, ("lon", "longitude"))
        if (not mmsi or age is None or not 0 <= age <= 300 or
                lat is None or lon is None or not -90 <= lat <= 90 or
                not -180 <= lon <= 180 or (lat == 0 and lon == 0) or
                receiver_monitor._safe_number(ship.get("validated")) != 1):
            continue
        if position is not None:
            a1, a2 = math.radians(position[0]), math.radians(lat)
            dlat = a2-a1
            dlon = math.radians(lon-position[1])
            h = math.sin(dlat/2)**2+math.cos(a1)*math.cos(a2)*math.sin(dlon/2)**2
            range_nm = 3440.065*2*math.asin(math.sqrt(min(1.0,max(0.0,h))))
            if range_nm > 300:
                continue
            ranges.append(range_nm)
        found.add(mmsi)
    return len(found), round(max(ranges),1) if ranges else None


def service_activity():
    try:
        m = mission_engine.get_mission_status()
        mission = int(bool(m.get("active_job")) or
                      str(m.get("phase") or "").upper() not in ("READY", "IDLE"))
    except Exception:
        mission = None
    if not active("sdrcc-traffic-voice.service"):
        marine = 0
        airband = 0
    else:
        try:
            voice_mode = str(config.get_traffic_voice_config().get("selected_mode") or "")
            marine = int(voice_mode == "marine_ais")
            airband = int(voice_mode == "airband_adsb")
        except Exception:
            # Service is active but mode could not be observed: mark unknown,
            # not inactive. Never infer Airband from the ADS-B decoder.
            marine = None
            airband = None
    return mission, marine, airband


def sample_once(ais_on=None, adsb_on=None, *, mission_on=None, marine_on=None, airband_on=None):
    ais_on = active("ais-catcher.service") if ais_on is None else bool(ais_on)
    adsb_on = active("readsb.service") if adsb_on is None else bool(adsb_on)
    a = receiver_monitor.get_ais_metrics(ais_on)
    b = receiver_monitor.get_adsb_metrics(adsb_on)
    ais_count, ais_range = fresh_ais() if a.get("available") else (None,None)
    # Unfiltered AIS-Catcher ships.json count, matching its viewer.
    catcher_total = a.get("targets") if a.get("available") else None
    if mission_on is None or marine_on is None or airband_on is None:
        mission_status, marine_status, airband_status = service_activity()
        if mission_on is None: mission_on = mission_status
        if marine_on is None: marine_on = marine_status
        if airband_on is None: airband_on = airband_status
    ts = int(time.time())
    with connect() as con:
        con.execute("""INSERT OR REPLACE INTO samples
            (ts,ais_on,ais_targets,ais_rate,ais_range,adsb_on,adsb_targets,
            adsb_rate,adsb_range,ais_fresh,ais_valid_range,mission_on,marine_on,airband_on,ais_catcher_total)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            ts, int(ais_on), ais_count,
            num(a.get("messages_per_second")) if a.get("available") else None,
            ais_range, int(adsb_on),
            b.get("targets") if b.get("available") else None,
            num(b.get("messages_per_second")) if b.get("available") else None,
            num(b.get("max_range_nm")) if b.get("available") else None,
            ais_count, ais_range,
            int(bool(mission_on)) if mission_on is not None else None,
            int(bool(marine_on)) if marine_on is not None else None,
            int(bool(airband_on)) if airband_on is not None else None,
            catcher_total))
        con.execute("DELETE FROM samples WHERE ts < ?", (ts-90*86400,))


def worker():
    while True:
        try: sample_once()
        except Exception: pass  # Statistics must never interfere with receivers.
        time.sleep(60)


def start_worker():
    global _started
    with _lock:
        if _started: return
        _started = True
        threading.Thread(target=worker,name="sdrcc-reception-analytics",daemon=True).start()


def report(period="24h"):
    windows = {"24h":(86400,300), "7d":(604800,3600), "30d":(2592000,10800)}
    if period not in windows: raise ValueError("Invalid analytics period")
    span, bucket = windows[period]
    since = int(time.time())-span
    with connect() as con:
        con.row_factory=sqlite3.Row
        rows=con.execute("""SELECT (ts / ?) * ? AS ts,
            ROUND(AVG(ais_fresh),1) ais_targets,
            ROUND(AVG(COALESCE(ais_catcher_total,
                CASE WHEN ais_fresh IS NULL THEN ais_targets END)),1) ais_total,
            ROUND(AVG(ais_rate),2) ais_rate,
            MAX(CASE WHEN ais_valid_range BETWEEN 0 AND 300 THEN ais_valid_range END) ais_range,
            ROUND(AVG(adsb_targets),1) adsb_targets, ROUND(AVG(adsb_rate),2) adsb_rate,
            MAX(CASE WHEN adsb_range BETWEEN 0 AND 500 THEN adsb_range END) adsb_range,
            MAX(ais_on) ais_on, MAX(adsb_on) adsb_on,
            MAX(mission_on) mission_on, MAX(marine_on) marine_on,
            MAX(airband_on) airband_on
            FROM samples WHERE ts >= ? GROUP BY (ts / ?) ORDER BY ts""",
            (bucket,bucket,since,bucket)).fetchall()
        summary=con.execute("""SELECT COUNT(*) samples, MAX(ais_fresh) ais_peak,
            MAX(COALESCE(ais_catcher_total,
                CASE WHEN ais_fresh IS NULL THEN ais_targets END)) ais_total_peak,
            MIN(CASE WHEN ais_fresh IS NOT NULL THEN ts END) first_fresh_ais,
            MIN(CASE WHEN COALESCE(ais_catcher_total,
                CASE WHEN ais_fresh IS NULL THEN ais_targets END) IS NOT NULL
                THEN ts END) first_total_ais,
            MAX(adsb_targets) adsb_peak,
            MAX(CASE WHEN ais_valid_range BETWEEN 0 AND 300 THEN ais_valid_range END) ais_range,
            MAX(CASE WHEN adsb_range BETWEEN 0 AND 500 THEN adsb_range END) adsb_range,
            ROUND(AVG(ais_rate),2) ais_avg, ROUND(AVG(adsb_rate),2) adsb_avg,
            SUM(CASE WHEN mission_on=1 THEN 1 ELSE 0 END) mission_minutes,
            SUM(CASE WHEN marine_on=1 THEN 1 ELSE 0 END) marine_minutes,
            SUM(CASE WHEN airband_on=1 THEN 1 ELSE 0 END) airband_minutes,
            COUNT(ais_fresh) fresh_ais_samples
            FROM samples WHERE ts >= ?""",(since,)).fetchone()
        # Report a current comparison only for samples no more than 180 sec old.
        latest=con.execute("""SELECT ts,ais_catcher_total,ais_fresh
            FROM samples WHERE ts >= ? ORDER BY ts DESC LIMIT 1""",
            (int(time.time())-180,)).fetchone()
    info=dict(summary)
    info["current_catcher_total"] = latest["ais_catcher_total"] if latest else None
    info["current_ais_fresh"] = latest["ais_fresh"] if latest else None
    return {"ok":True,"read_only":True,"period":period,"summary":info,
            "series":[dict(row) for row in rows],"bucket_seconds":bucket,"period_seconds":span,
            "retention_days":90,"sample_interval_seconds":60,
            "updated_at":datetime.now(timezone.utc).isoformat()}
