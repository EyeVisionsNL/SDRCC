"""Local operator-owned station notebook; AI has read-only access.

The database lives outside the model assets directory. Only operator actions and the enabled anomaly monitor may write;
no raw log copying, cloud services, or receiver control.
"""
from contextlib import closing
from datetime import datetime
import hashlib
import json
import os
import re
import sqlite3
import time

from core import local_ai_health as health, local_ai_reception as reception

SOURCE="data/state/station_memory.sqlite3"
KINDS=("incident","hardware","configuration","note")
MAX_ENTRIES=1000
PAGE=10
EVENT_LIMIT=200
LOG_BYTES=65536


def validated_text(value, limit, required=False):
    if not isinstance(value,str):
        raise ValueError("Expected text.")
    value=value.strip()
    if len(value)>limit or (required and not value) or "\x00" in value:
        raise ValueError(f"Text must fit within {limit} characters.")
    return value


def connect_write(root):
    path=root/SOURCE
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        pass
    else:
        os.close(fd)
    db=sqlite3.connect(path,timeout=.5)
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS entries(
            id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL,
            kind TEXT NOT NULL, title TEXT NOT NULL, details TEXT NOT NULL,
            outcome TEXT NOT NULL, source TEXT NOT NULL, event_key TEXT UNIQUE)""")
        db.commit()
        return db
    except Exception:
        db.close()
        raise


def insert(db, entry):
    if db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]>=MAX_ENTRIES:
        raise ValueError("Station Memory is full; delete old entries before adding more.")
    db.execute("INSERT INTO entries(created,kind,title,details,outcome,source,event_key) VALUES(?,?,?,?,?,?,?)",entry)


def add(root, body, *, now=None):
    kind=body.get("entry_kind")
    if kind not in KINDS:
        raise ValueError("Invalid entry category.")
    title=validated_text(body.get("title"),100,True)
    details=validated_text(body.get("details",""),500)
    outcome=validated_text(body.get("outcome",""),300)
    now=time.time() if now is None else now
    with closing(connect_write(root)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        insert(db,(now,kind,title,details,outcome,"operator",None))


def delete(root, entry_id):
    if type(entry_id) is not int or entry_id<1:
        raise ValueError("Invalid entry ID.")
    path=root/SOURCE
    if not path.is_file():
        raise ValueError("Station Memory does not exist.")
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=rw",uri=True,timeout=.5)) as db,db:
        if db.execute("DELETE FROM entries WHERE id=?",(entry_id,)).rowcount!=1:
            raise ValueError("Memory entry not found.")


def classified(source, stamp, message, identity):
    # Store only fixed classifications, not raw messages or identifiers.
    for kind,pattern in health.PATTERNS.items():
        if pattern.search(message):
            key=hashlib.sha256((source+"|"+identity+"|"+kind).encode("utf-8")).hexdigest()
            title=kind.replace("_"," ").capitalize()
            yield (stamp,"incident",title,"Matching log entry from "+source,
                   "Reset reported successful; long-term stability unverified." if kind=="usb_reset_ok" else "",
                   source,key)


def recent_events(root,now):
    entries=[]
    sources={}
    try:
        with (root/"logs/sdrcc.log").open("rb") as handle:
            handle.seek(0,2)
            handle.seek(max(0,handle.tell()-LOG_BYTES))
            raw=handle.read(LOG_BYTES).decode("utf-8","replace")
        sources["SDRCC"]="observed"
        for line in raw.splitlines():
            match=re.match(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] (.*)",line)
            if not match:
                continue
            try:
                stamp=datetime.strptime(match[1],"%Y-%m-%d %H:%M:%S").timestamp()
            except ValueError:
                continue
            if now-86400<=stamp<=now:
                entries.extend(classified("SDRCC",stamp,match[2],line))
    except OSError:
        sources["SDRCC"]="unavailable"
    for label,unit in health.UNITS.items():
        raw=health.command(["journalctl","-u",unit,"--since=-24h","-n",str(EVENT_LIMIT),"--no-pager","-o","json"])
        sources[label]="observed" if raw else "no_visible_entries" if raw=="" else "unavailable"
        for line in (raw or "").splitlines()[-EVENT_LIMIT:]:
            try:
                row=json.loads(line)
                stamp=int(row["__REALTIME_TIMESTAMP"])/1e6
                cursor=row["__CURSOR"]
                message=row["MESSAGE"]
                if isinstance(cursor,str) and isinstance(message,str) and now-86400<=stamp<=now:
                    entries.extend(classified(label,stamp,message,cursor))
            except (ValueError,TypeError,KeyError):
                continue
    # Repeat scans of the same entries are idempotent. Multiple distinct log
    # messages may describe the same incident; this is not an incident count.
    unique={row[-1]:row for row in entries}
    ordered=sorted(unique.values(),key=lambda row:(row[0],row[-1]),reverse=True)
    return ordered[:EVENT_LIMIT],sources,len(ordered)>EVENT_LIMIT


def import_events(root, *, now=None):
    now=time.time() if now is None else now
    events,sources,truncated=recent_events(root,now)
    added=0
    if events:
        with closing(connect_write(root)) as db,db:
            db.execute("BEGIN IMMEDIATE")
            for entry in events:
                if db.execute("SELECT 1 FROM entries WHERE event_key=?",(entry[-1],)).fetchone():
                    continue
                insert(db,entry)
                added+=1
    return {"added":added,"matched":len(events),"sources":sources,"truncated":truncated}


def snapshot(root, query="", page=1, *, now=None):
    query=validated_text(query,100)
    if type(page) is not int or not 1<=page<=100:
        raise ValueError("Invalid memory page.")
    now=time.time() if now is None else now
    base={"kind":"station_memory","source":SOURCE,"observed_utc":reception.utc(int(now)),
          "query":query,"page":page,"page_size":PAGE,"capacity":MAX_ENTRIES,
          "scope":"Local operator notes, explicitly imported classified log entries and automatic anomaly transitions while monitoring is enabled. Log entries are not unique incidents. No verified causality. AI receives only a bounded excerpt of the displayed page."}
    path=root/SOURCE
    if not path.is_file():
        return dict(base,status="empty",total=0,matched=0,counts={},entries=[])
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=.3)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            total=db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            counts=dict(db.execute("SELECT kind,COUNT(*) FROM entries GROUP BY kind"))
            clause="WHERE instr(lower(title||' '||details||' '||outcome||' '||kind||' '||source),lower(?))>0"
            matched=db.execute("SELECT COUNT(*) FROM entries "+clause,(query,)).fetchone()[0] if query else total
            rows=db.execute("SELECT id,created,kind,title,details,outcome,source FROM entries "+(clause if query else "")+" ORDER BY created DESC,id DESC LIMIT ? OFFSET ?",(*([query] if query else []),PAGE,(page-1)*PAGE)).fetchall()
        entries=[dict(zip(("id","created_utc","kind","title","details","outcome","source"),(row[0],reception.utc(row[1]),*row[2:]))) for row in rows]
        return dict(base,status="ok" if total else "empty",total=total,matched=matched,counts=counts,entries=entries)
    except (OSError,sqlite3.Error,ValueError,OverflowError):
        return dict(base,status="unavailable",total=None,matched=None,counts={},entries=[],reason="Station Memory could not be read.")


def model_evidence(data):
    """Keep prompt bounded; UI receives the full selected page separately."""
    result=dict(data)
    result["entries"]=[dict(row,details=row["details"][:240],outcome=row["outcome"][:160]) for row in data["entries"][:6]]
    result["model_excerpt_count"]=len(result["entries"])
    result["model_excerpt_limits"]="At most six entries from the selected page; details limited to 240 and outcomes to 160 characters."
    return result
