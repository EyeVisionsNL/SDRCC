"""Read-only ATIS reception funnel: detected phasing, valid decode, loaded photo.

Packet events from the audio decoder are queued without blocking the RF/audio
pipeline. Duplicates from overlapping scan windows are coalesced. Oldest data
is pruned after 90 days; pre-installation ATIS data cannot be reconstructed.
"""
from __future__ import annotations
import logging
import math
import queue
import re
import sqlite3
import threading
import time
from pathlib import Path

DB=Path(__file__).resolve().parent.parent/"data"/"analytics"/"atis_statistics.sqlite3"
DAYS=90
_q=queue.Queue(maxsize=1024)
_lock=threading.Lock()
_started=False
_dropped=0
_error=None

def _connect():
    DB.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DB,timeout=5)
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("""CREATE TABLE IF NOT EXISTS atis_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
      decoded INTEGER NOT NULL DEFAULT 0, code TEXT,
      photo_loaded INTEGER NOT NULL DEFAULT 0, photo_mmsi TEXT,
      photo_source TEXT)""")
    db.execute("CREATE INDEX IF NOT EXISTS atis_events_ts ON atis_events(ts)")
    return db

def _time(value):
    try:epoch=float(value)
    except (TypeError,ValueError):return None
    if not math.isfinite(epoch) or abs(epoch-time.time())>120:return None
    return epoch

def _enqueue(kind,*args):
    global _dropped
    try:
        _q.put_nowait((kind,args))
        return True
    except queue.Full:
        _dropped+=1
        return False

def candidate(epoch):
    """An ATIS-like phasing pattern was found, regardless of valid checksum."""
    when=_time(epoch)
    if when is not None:_enqueue("candidate",when)

def decoded(epoch,code):
    """The existing decoder accepted one non-duplicate ATIS identity."""
    when=_time(epoch);code=str(code or "")
    if when is not None and re.fullmatch(r"9[0-9]{9}",code):
        _enqueue("decoded",when,code)

def photo_loaded(epoch,code,mmsi,source):
    """Browser acknowledgement occurs only after a real vessel image loaded."""
    when=_time(epoch);code=str(code or "");mmsi=str(mmsi or "")
    source=str(source or "").strip()[:80]
    if (when is None or not re.fullmatch(r"9[0-9]{9}",code)
        or not re.fullmatch(r"[0-9]{9}",mmsi) or not source):return False
    return _enqueue("photo",when,code,mmsi,source)

def _near(db,when,code=None):
    rows=db.execute("""SELECT id,code FROM atis_events
      WHERE ts BETWEEN ? AND ? ORDER BY ABS(ts-?) LIMIT 16""",
      (when-.9,when+.9,when)).fetchall()
    if code is None:return rows[0] if rows else None
    return (next((row for row in rows if row[1]==code),None)
            or next((row for row in rows if row[1] is None),None))

def _store(db,kind,args):
    if kind=="candidate":
        (when,)=args
        if _near(db,when) is None:db.execute("INSERT INTO atis_events(ts) VALUES (?)",(when,))
    elif kind=="decoded":
        when,code=args
        row=_near(db,when,code)
        if row is None:
            db.execute("INSERT INTO atis_events(ts,decoded,code) VALUES (?,1,?)",(when,code))
        else:
            db.execute("UPDATE atis_events SET decoded=1,code=? WHERE id=?",(code,row[0]))
    elif kind=="photo":
        when,code,mmsi,source=args
        row=db.execute("""SELECT id FROM atis_events WHERE decoded=1 AND code=?
           AND ts BETWEEN ? AND ? ORDER BY ABS(ts-?) LIMIT 1""",
           (code,when-2,when+2,when)).fetchone()
        if row:
            db.execute("""UPDATE atis_events SET photo_loaded=1,photo_mmsi=?,
                photo_source=? WHERE id=? AND photo_loaded=0""",(mmsi,source,row[0]))

def _worker():
    global _error
    while True:
        try:kind,args=_q.get(timeout=45)
        except queue.Empty:kind,args=None,()
        try:
            with _connect() as db:
                if kind is not None:_store(db,kind,args)
                db.execute("DELETE FROM atis_events WHERE ts < ?",(time.time()-DAYS*86400,))
            _error=None
        except Exception as exc:
            _error=f"{type(exc).__name__}: {exc}"[:220]
            logging.getLogger(__name__).exception("ATIS statistics save failed")
        finally:
            if kind is not None:_q.task_done()

def start_worker():
    global _started
    with _lock:
        if _started:return
        _started=True
        threading.Thread(target=_worker,name="sdrcc-atis-statistics",daemon=True).start()

def report(since,until):
    with _connect() as db:
        detected,valid,photos,first=db.execute("""SELECT COUNT(*),
           COALESCE(SUM(decoded),0),COALESCE(SUM(photo_loaded),0),MIN(ts)
           FROM atis_events WHERE ts BETWEEN ? AND ?""",(since,until)).fetchone()
    return {
      "candidates":detected,"decoded":valid,"photos":photos,"first_sample_ts":first,
      "decode_percent":round(valid/detected*100,1) if detected else None,
      "photo_percent":round(photos/valid*100,1) if valid else None,
      "dropped_queue_events":_dropped,"last_error":_error,
      "retention_days":DAYS
    }
