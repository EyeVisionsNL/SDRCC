"""Passive RF reception trend collector. Keeps 90 days locally, never controls SDRs."""
from __future__ import annotations
import sqlite3, subprocess, threading, time
from pathlib import Path
from datetime import datetime, timezone
from core import receiver_monitor
DB=Path(__file__).resolve().parent.parent/"data"/"analytics"/"reception.sqlite3"
_lock=threading.Lock()
_started=False

def connect():
    DB.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(DB,timeout=6)
    con.execute("PRAGMA busy_timeout=6000")
    con.execute("""CREATE TABLE IF NOT EXISTS samples (
      ts INTEGER PRIMARY KEY, ais_on INTEGER, ais_targets INTEGER, ais_rate REAL, ais_range REAL,
      adsb_on INTEGER, adsb_targets INTEGER, adsb_rate REAL, adsb_range REAL)""")
    return con

def active(service):
    try:
        return subprocess.run(["systemctl","is-active","--quiet",service],
                              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                              timeout=3,check=False).returncode==0
    except (OSError,subprocess.TimeoutExpired):
        return False

def num(value):
    try:
        x=float(value)
        return round(x,3) if x==x and abs(x)<1e10 else None
    except (TypeError,ValueError):
        return None

def sample_once(ais_on=None,adsb_on=None):
    ais_on=active("ais-catcher.service") if ais_on is None else bool(ais_on)
    adsb_on=active("readsb.service") if adsb_on is None else bool(adsb_on)
    a=receiver_monitor.get_ais_metrics(ais_on)
    b=receiver_monitor.get_adsb_metrics(adsb_on)
    ts=int(time.time())
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO samples VALUES (?,?,?,?,?,?,?,?,?)",(
            ts,int(ais_on),a.get("targets") if a.get("available") else None,
            num(a.get("messages_per_second")) if a.get("available") else None,
            num(a.get("max_range_nm")) if a.get("available") else None,
            int(adsb_on),b.get("targets") if b.get("available") else None,
            num(b.get("messages_per_second")) if b.get("available") else None,
            num(b.get("max_range_nm")) if b.get("available") else None))
        conn.execute("DELETE FROM samples WHERE ts < ?",(ts-90*86400,))

def worker():
    while True:
        try:sample_once()
        except Exception:pass  # Read-only sampling must not affect reception.
        time.sleep(60)

def start_worker():
    global _started
    with _lock:
        if _started:return
        _started=True
        threading.Thread(target=worker,name="sdrcc-reception-analytics",daemon=True).start()

def report(period="24h"):
    windows={"24h":(86400,300),"7d":(604800,3600),"30d":(2592000,10800)}
    if period not in windows:raise ValueError("Invalid analytics period")
    seconds,bucket=windows[period]
    since=int(time.time())-seconds
    with connect() as conn:
        conn.row_factory=sqlite3.Row
        rows=conn.execute("""SELECT (ts / ?) * ? AS ts,
            ROUND(AVG(ais_targets),1) ais_targets, ROUND(AVG(ais_rate),2) ais_rate,
            MAX(ais_range) ais_range, ROUND(AVG(adsb_targets),1) adsb_targets,
            ROUND(AVG(adsb_rate),2) adsb_rate, MAX(adsb_range) adsb_range
            FROM samples WHERE ts>=? GROUP BY (ts / ?) ORDER BY ts""",
            (bucket,bucket,since,bucket)).fetchall()
        summary=conn.execute("""SELECT COUNT(*) samples, MAX(ais_targets) ais_peak,
            MAX(adsb_targets) adsb_peak, MAX(ais_range) ais_range,
            MAX(adsb_range) adsb_range, ROUND(AVG(ais_rate),2) ais_avg,
            ROUND(AVG(adsb_rate),2) adsb_avg FROM samples WHERE ts>=?""",
            (since,)).fetchone()
    from core import marine_replay
    return {"ok":True,"read_only":True,"period":period,"summary":dict(summary),
            "series":[dict(row) for row in rows],"marine":marine_replay.counts(since),
            "retention_days":90,"updated_at":datetime.now(timezone.utc).isoformat()}
