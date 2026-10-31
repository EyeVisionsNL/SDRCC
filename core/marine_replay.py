"""Marine Replay: bounded audio archive + validated ATIS/AIS snapshots, never RF control."""
from __future__ import annotations
import queue, re, sqlite3, threading, time, wave
from pathlib import Path
from datetime import datetime
from uuid import uuid4
ROOT=Path(__file__).resolve().parent.parent/"data"/"marine_replay"
DB=ROOT/"history.sqlite3"
AUDIO=ROOT/"recordings"
DAYS=14
CAP_BYTES=512*1024*1024
CAP_CLIPS=1800
_ID=re.compile(r"[a-f0-9]{32}\Z")
_queue=queue.Queue(maxsize=48)
_lock=threading.Lock()
_started=False

def connect():
    ROOT.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(DB,timeout=6)
    con.execute("PRAGMA busy_timeout=6000")
    con.execute("""CREATE TABLE IF NOT EXISTS clips (
        id TEXT PRIMARY KEY, ts REAL NOT NULL, duration REAL NOT NULL,
        channel TEXT, frequency REAL, bytes INTEGER NOT NULL)""")
    con.execute("CREATE INDEX IF NOT EXISTS clip_ts ON clips(ts)")
    con.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, code TEXT NOT NULL,
        callsign TEXT, status TEXT, mmsi TEXT, shipname TEXT, lat REAL, lon REAL,
        distance_nm REAL, clip_id TEXT)""")
    con.execute("CREATE INDEX IF NOT EXISTS events_ts ON events(ts)")
    con.execute("CREATE INDEX IF NOT EXISTS events_clip ON events(clip_id)")
    return con

def number(value):
    try:
        x=float(value)
        return x if x==x and abs(x)<1e10 else None
    except (ValueError,TypeError):return None

def enqueue_atis(event):
    if not isinstance(event,dict) or not re.fullmatch(r"9[0-9]{9}",str(event.get("atis_code") or "")):return
    try:_queue.put_nowait(("atis",dict(event)))
    except queue.Full:pass

def enqueue_recording(clip,sample_rate):
    if not isinstance(clip,dict) or not _ID.fullmatch(str(clip.get("id") or "")) or not isinstance(clip.get("pcm"),bytes):return
    try:ts=datetime.fromisoformat(str(clip.get("received_at"))).timestamp()
    except (ValueError,TypeError):ts=time.time()
    record={"id":clip["id"],"ts":ts,"pcm":clip["pcm"],
            "rate":int(sample_rate),"channel":str(clip.get("channel") or "")[:120],
            "frequency":number(clip.get("frequency_mhz"))}
    try:_queue.put_nowait(("clip",record))
    except queue.Full:pass

def link(conn):
    # ATIS timestamp must lie within the recording, never attach last-known identities.
    conn.execute("""UPDATE events SET clip_id=(
        SELECT c.id FROM clips c WHERE events.ts BETWEEN c.ts-1 AND c.ts+c.duration+2
        ORDER BY c.ts DESC LIMIT 1)
        WHERE clip_id IS NULL AND ts > ?""",(time.time()-86400,))

def store_event(conn,event):
    from core import receiver_monitor
    code=str(event["atis_code"])
    m=receiver_monitor.match_ais_atis(code)
    good=bool(m.get("matched"))
    conn.execute("""INSERT INTO events(ts,code,callsign,status,mmsi,shipname,lat,lon,distance_nm)
        VALUES (?,?,?,?,?,?,?,?,?)""",(
        number(event.get("received_epoch")) or time.time(),code,
        str(event.get("callsign") or "")[:32],str(m.get("status") or "")[:32],
        str(m.get("mmsi") or "") if good else None,
        str(m.get("shipname") or "")[:100] if good else None,
        number(m.get("latitude")) if good else None,
        number(m.get("longitude")) if good else None,
        number(m.get("distance_nm")) if good else None))
    link(conn)

def store_clip(conn,record):
    AUDIO.mkdir(parents=True,exist_ok=True)
    target=AUDIO/(record["id"]+".wav")
    temporary=AUDIO/(record["id"]+"-"+uuid4().hex+".tmp")
    with wave.open(str(temporary),"wb") as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(record["rate"])
        out.writeframes(record["pcm"])
    temporary.replace(target)
    try:
        conn.execute("""INSERT OR IGNORE INTO clips(id,ts,duration,channel,frequency,bytes)
            VALUES (?,?,?,?,?,?)""",(record["id"],record["ts"],
            len(record["pcm"])/(record["rate"]*2),record["channel"],
            record["frequency"],target.stat().st_size))
        link(conn)
    except Exception:
        target.unlink(missing_ok=True)
        raise

def prune(conn):
    cutoff=time.time()-DAYS*86400
    old=[r[0] for r in conn.execute("SELECT id FROM clips WHERE ts<?",(cutoff,))]
    size=0
    for n,(ident,amount) in enumerate(conn.execute(
            "SELECT id,bytes FROM clips WHERE ts>=? ORDER BY ts DESC",(cutoff,))):
        size+=amount
        if n>=CAP_CLIPS or size>CAP_BYTES:old.append(ident)
    for ident in old:
        conn.execute("DELETE FROM clips WHERE id=?",(ident,))
        conn.execute("UPDATE events SET clip_id=NULL WHERE clip_id=?",(ident,))
        (AUDIO/(ident+".wav")).unlink(missing_ok=True)
    conn.execute("DELETE FROM events WHERE ts<?",(cutoff,))

def worker():
    while True:
        try:kind,item=_queue.get(timeout=60)
        except queue.Empty:kind,item=None,None
        try:
            with connect() as conn:
                if kind=="atis":store_event(conn,item)
                elif kind=="clip":store_clip(conn,item)
                prune(conn)
        except Exception:pass  # Passive archive never stops the live decoder.
        finally:
            if kind is not None:_queue.task_done()

def start_worker():
    global _started
    with _lock:
        if _started:return
        _started=True
        threading.Thread(target=worker,name="sdrcc-marine-archive",daemon=True).start()

def counts(after):
    with connect() as conn:
        clips=conn.execute("SELECT COUNT(*) FROM clips WHERE ts>=?",(after,)).fetchone()[0]
        events,matched=conn.execute("""SELECT COUNT(*),
          SUM(CASE WHEN mmsi IS NOT NULL THEN 1 ELSE 0 END)
          FROM events WHERE ts>=?""",(after,)).fetchone()
    return {"clips":clips,"validated":events,"matched":matched or 0}

def list_replays(limit=50,offset=0):
    limit=max(1,min(100,int(limit)));offset=max(0,min(10000,int(offset)))
    with connect() as conn:
        conn.row_factory=sqlite3.Row
        rows=conn.execute("""SELECT c.id,c.ts,c.duration,c.channel,c.frequency,
            e.code,e.callsign,e.status,e.mmsi,e.shipname,e.lat,e.lon,e.distance_nm
            FROM clips c LEFT JOIN events e ON e.id=(
              SELECT x.id FROM events x WHERE x.clip_id=c.id
              ORDER BY x.ts DESC LIMIT 1)
            ORDER BY c.ts DESC LIMIT ? OFFSET ?""",(limit,offset)).fetchall()
        total=conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
    result=[]
    for row in rows:
        item=dict(row)
        item["received_at"]=datetime.fromtimestamp(item.pop("ts")).astimezone().isoformat(timespec="seconds")
        item["audio_url"]="/api/marine-replay/audio/"+item["id"]
        result.append(item)
    return {"ok":True,"total":total,"rows":result,
            "retention_days":DAYS,"storage_limit_mb":CAP_BYTES//1048576}

def audio_path(ident):
    if not _ID.fullmatch(str(ident or "")):return None
    with connect() as conn:
        found=conn.execute("SELECT 1 FROM clips WHERE id=?",(ident,)).fetchone()
    path=AUDIO/(ident+".wav")
    return path if found and path.is_file() else None
