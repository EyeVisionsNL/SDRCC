"""Passive Marine ATIS funnel with server-side, page-independent photo discovery.

The validated decoder only enqueues records. AIS matching and external credited
photo searches use separate bounded workers and never block reception.
"""
from __future__ import annotations
from contextlib import closing
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
_match_q=queue.Queue(maxsize=192)
_photo_q=queue.Queue(maxsize=128)
_lock=threading.Lock()
_started=False
_dropped=0
_match_dropped=0
_photo_dropped=0
_error=None
_match_error=None
_photo_error=None

def _connect():
    DB.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DB,timeout=5)
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("""CREATE TABLE IF NOT EXISTS atis_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
      decoded INTEGER NOT NULL DEFAULT 0, code TEXT,
      photo_loaded INTEGER NOT NULL DEFAULT 0, photo_mmsi TEXT,
      photo_source TEXT, photo_found INTEGER NOT NULL DEFAULT 0,
      ais_matched INTEGER NOT NULL DEFAULT 0,
      photo_checked INTEGER NOT NULL DEFAULT 0)""")
    existing={row[1] for row in db.execute("PRAGMA table_info(atis_events)")}
    # Keep old browser-only photo_loaded records. They are not reclassified
    # as server-discovered photos or deleted when migrating an existing DB.
    for column in ("photo_found","ais_matched","photo_checked"):
        if column not in existing:
            db.execute(f"ALTER TABLE atis_events ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0")
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

def _near(db,when,code=None):
    rows=db.execute("""SELECT id,code,decoded FROM atis_events
      WHERE ts BETWEEN ? AND ? ORDER BY ABS(ts-?) LIMIT 16""",
      (when-.9,when+.9,when)).fetchall()
    if code is None:return rows[0] if rows else None
    return (next((row for row in rows if row[1]==code),None)
            or next((row for row in rows if row[1] is None),None))

def _store(db,kind,args):
    """Return the new valid event only once, after decoder deduplication."""
    if kind=="candidate":
        (when,)=args
        if _near(db,when) is None:
            db.execute("INSERT INTO atis_events(ts) VALUES (?)",(when,))
    elif kind=="decoded":
        when,code=args
        row=_near(db,when,code)
        if row is None:
            cursor=db.execute(
                "INSERT INTO atis_events(ts,decoded,code) VALUES (?,1,?)",(when,code))
            return (cursor.lastrowid,when,code)
        if row[2]!=1:
            db.execute("UPDATE atis_events SET decoded=1,code=? WHERE id=?",(code,row[0]))
            return (row[0],when,code)
    return None


def _worker():
    """Database writer, deliberately separated from all network operations."""
    global _error,_match_dropped
    log=logging.getLogger(__name__)
    while True:
        try:kind,args=_q.get(timeout=45)
        except queue.Empty:kind,args=None,()
        job=None
        try:
            with closing(_connect()) as db:
                with db:
                    if kind is not None:
                        job=_store(db,kind,args)
                    db.execute("DELETE FROM atis_events WHERE ts < ?",(time.time()-DAYS*86400,))
            _error=None
            if job is not None:
                try:_match_q.put_nowait(job)
                except queue.Full:_match_dropped+=1
        except Exception as exc:
            _error=f"{type(exc).__name__}: {exc}"[:220]
            log.exception("ATIS statistics writer failed")
        finally:
            if kind is not None:_q.task_done()


def _match_worker():
    """Resolve a unique recent AIS match quickly without photo-network latency."""
    global _match_error,_photo_dropped
    from core import receiver_monitor
    log=logging.getLogger(__name__)
    while True:
        event_id,when,code=_match_q.get()
        try:
            match=None
            # AIS ship identity sometimes arrives just after the ATIS packet.
            # Only a few brief retries; the decoder is never held up.
            for attempt in range(3):
                result=receiver_monitor.match_ais_atis(code)
                if result.get("matched") and re.fullmatch(r"[0-9]{9}",str(result.get("mmsi") or "")):
                    match=result
                    break
                if attempt<2:time.sleep(2)
            if match is not None:
                with closing(_connect()) as db:
                    with db:
                        db.execute("""UPDATE atis_events SET ais_matched=1
                            WHERE id=? AND code=? AND decoded=1""",(event_id,code))
                photo_job=(event_id,code,str(match["mmsi"]),
                    str(match.get("shipname") or ""),str(match.get("imo") or ""),
                    str(match.get("eni") or ""))
                try:_photo_q.put_nowait(photo_job)
                except queue.Full:_photo_dropped+=1
            _match_error=None
        except Exception as exc:
            _match_error=f"{type(exc).__name__}: {exc}"[:220]
            log.exception("ATIS background AIS matching failed")
        finally:_match_q.task_done()


def _photo_worker():
    """Single bounded photo worker reuses the normal credited sources and cache."""
    global _photo_error
    from core import traffic_voice_vessel_photo
    log=logging.getLogger(__name__)
    while True:
        event_id,code,mmsi,shipname,imo,eni=_photo_q.get()
        try:
            # lookup() can contact external sources and has a shared TTL cache.
            # Never call it from the decoder, RF thread or ATIS SQLite writer.
            result=traffic_voice_vessel_photo.lookup(mmsi,shipname,imo,eni)
            found=(result.get("ok") is True
                and bool(str(result.get("image_url") or "").strip())
                and bool(str(result.get("source") or "").strip()))
            with closing(_connect()) as db:
                with db:
                    if found:
                        db.execute("""UPDATE atis_events SET photo_found=1,
                            photo_checked=1,photo_mmsi=?,photo_source=?
                            WHERE id=? AND code=? AND decoded=1 AND photo_found=0""",
                            (mmsi,str(result["source"])[:80],event_id,code))
                    else:
                        db.execute("""UPDATE atis_events SET photo_checked=1
                            WHERE id=? AND code=? AND decoded=1""",(event_id,code))
            _photo_error=None
        except Exception as exc:
            _photo_error=f"{type(exc).__name__}: {exc}"[:220]
            log.exception("ATIS background vessel photo lookup failed")
        finally:_photo_q.task_done()


def start_worker():
    global _started
    with _lock:
        if _started:return
        _started=True
        for name,worker in (
            ("sdrcc-atis-statistics",_worker),
            ("sdrcc-atis-ais-match",_match_worker),
            ("sdrcc-atis-photo-lookup",_photo_worker),
        ):
            threading.Thread(target=worker,name=name,daemon=True).start()

def report(since,until):
    with _connect() as db:
        detected,valid,photos,matched,checked,first=db.execute("""SELECT COUNT(*),
           COALESCE(SUM(decoded),0),COALESCE(SUM(photo_found),0),
           COALESCE(SUM(ais_matched),0),COALESCE(SUM(photo_checked),0),MIN(ts)
           FROM atis_events WHERE ts BETWEEN ? AND ?""",(since,until)).fetchone()
    return {
      "candidates":detected,"decoded":valid,"photos":photos,"first_sample_ts":first,
      "ais_matched":matched,"photo_checked":checked,
      "decode_percent":round(valid/detected*100,1) if detected else None,
      "photo_percent":round(photos/valid*100,1) if valid else None,
      "dropped_queue_events":_dropped+_match_dropped+_photo_dropped,
      "last_error":_error or _match_error or _photo_error,
      "pending_photo_checks":_match_q.qsize()+_photo_q.qsize(),
      "photo_scope":"server-side credited photo lookup, independent of browser",
      "retention_days":DAYS
    }
