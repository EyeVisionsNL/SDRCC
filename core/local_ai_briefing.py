"""Daily station reports: bounded read-only inputs, local immutable snapshots.

Automatic reports close at UTC midnight, never run model inference.
"""
from datetime import datetime, timedelta, timezone
import json
import logging
import os
import re
import tempfile
import threading
import time

from core import local_ai_reception as reception, local_ai_missions as missions
from core import local_ai_maritime as maritime, local_ai_anomaly as anomaly

DIRECTORY="data/state/daily_briefings"
KEEP=30
MAX_BYTES=65536
LOG=logging.getLogger(__name__)
DATE=re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def day_key(value):
    if not isinstance(value,str) or not DATE.fullmatch(value):
        raise ValueError("Invalid briefing date.")
    day=datetime.strptime(value,"%Y-%m-%d").date()
    if day.isoformat()!=value:
        raise ValueError("Invalid briefing date.")
    return day


def archive_days(root):
    directory=root/DIRECTORY
    if not directory.is_dir():
        return []
    days=[]
    for path in directory.glob("*.json"):
        try:
            day_key(path.stem)
            if path.is_file() and not path.is_symlink():
                days.append(path.stem)
        except ValueError:
            continue
    return sorted(days,reverse=True)[:KEEP]


def alert_summary(root,start,end):
    """Visible bounded transition history, never a claim of full coverage."""
    if not (root/anomaly.SOURCE).is_file():
        return {"status":"unavailable","opened":None,"cleared":None,"rules":{},
                "scope":"No persisted anomaly history; monitoring coverage unknown."}
    try:
        state=anomaly.load(root)
        events=[]
        for event in state["history"]:
            stamp=datetime.fromisoformat(event["timestamp"]).timestamp()
            if start<stamp<=end:
                events.append(event)
        rules={}
        for event in events:
            key=event["rule"]
            counts=rules.setdefault(key,{"opened":0,"cleared":0})
            counts[event["transition"]]+=1
        return {"status":"partial","opened":sum(v["opened"] for v in rules.values()),
                "cleared":sum(v["cleared"] for v in rules.values()),"rules":rules,
                "retained_transitions":len(state["history"]),
                "history_at_capacity":len(state["history"])>=anomaly.HISTORY,
                "scope":"Visible retained transitions only (max 40); monitor uptime and earlier discarded transitions unknown. Zero means none in available history, not no incidents."}
    except (OSError,ValueError,TypeError,KeyError,OverflowError):
        return {"status":"unavailable","opened":None,"cleared":None,"rules":{},
                "scope":"Anomaly history could not be read."}


def build(root,end,*,date=None,generated=None):
    end=int(end)
    start=end-86400
    generated=time.time() if generated is None else generated
    rx=reception.read_evidence(root,"24h",now=end)
    rx_data={key:rx.get(key) for key in ("status","samples","expected_samples","coverage_pct","first_sample_utc","last_sample_utc","latest_sample_age_seconds")}
    for name in ("ais","adsb"):
        if name in rx:
            rx_data[name]=rx[name]
    ms=missions.snapshot(root,"24h",now=end)
    mission_data={key:ms.get(key) for key in ("status","summary","retained_records","excluded_simulations","undated_records")}
    atis=maritime.atis_history(root,end)
    alerts=alert_summary(root,start,end)
    return {"kind":"daily_briefing","status":"ok" if rx["status"]=="ok" else "partial",
            "mode":"archive" if date else "rolling","date":date,
            "observed_utc":reception.utc(int(generated)),
            "window_start_utc":reception.utc(start),"window_end_utc":reception.utc(end),
            "reception":rx_data,"missions":mission_data,"atis":atis,"alerts":alerts,
            "scope":"24-hour UTC window (start exclusive, end inclusive). Sampled simultaneous targets, not unique totals; range in NM. Mission records by end time, known simulations excluded; ATIS station-wide events. Alert history is bounded and not proof of monitoring coverage. Sources read independently; missing values are not zero. Archived snapshots are not revised."}


def read_archive(root,date):
    day_key(date)
    path=root/DIRECTORY/(date+".json")
    if path.is_symlink():
        raise ValueError("Invalid briefing file.")
    with path.open("rb") as handle:
        raw=handle.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:
        raise ValueError("Briefing exceeds size limit.")
    data=json.loads(raw)
    if not isinstance(data,dict) or data.get("kind")!="daily_briefing" or data.get("date")!=date or data.get("mode")!="archive":
        raise ValueError("Invalid briefing archive.")
    return data


def snapshot(root,selection="rolling",*,now=None):
    now=time.time() if now is None else now
    if selection=="rolling":
        data=build(root,now,generated=now)
    else:
        day_key(selection)
        try:
            data=read_archive(root,selection)
        except (OSError,ValueError):
            data={"kind":"daily_briefing","status":"unavailable","mode":"archive","date":selection,
                  "observed_utc":reception.utc(int(now)),"reason":"Selected archived briefing unavailable."}
    return dict(data,available_dates=archive_days(root))


def archive_once(root,permitted,*,now=None):
    now=time.time() if now is None else now
    current=datetime.fromtimestamp(now,timezone.utc)
    midnight=current.replace(hour=0,minute=0,second=0,microsecond=0)
    # Grace for the reception collector and mission history publishing.
    if not permitted() or now-midnight.timestamp()<300:
        return False
    date=(midnight.date()-timedelta(days=1)).isoformat()
    path=root/DIRECTORY/(date+".json")
    if path.exists():
        return False
    report=build(root,midnight.timestamp(),date=date,generated=now)
    if not permitted():
        return False
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(report,ensure_ascii=True,separators=(",",":"),allow_nan=False)
    if len(raw.encode("utf-8"))>MAX_BYTES:
        raise ValueError("Briefing exceeds size limit.")
    with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=path.parent,prefix=".briefing-",delete=False) as f:
        temp=type(path)(f.name)
        try:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
            # Atomic no-overwrite publication even if two workers race.
            try:
                os.link(temp,path)
            except FileExistsError:
                return False
        finally:
            temp.unlink(missing_ok=True)
    # Retain only our recognized dated report files, not arbitrary files.
    dated=[]
    for item in path.parent.glob("*.json"):
        try:
            day_key(item.stem)
            if item.is_file() and not item.is_symlink():
                dated.append(item)
        except ValueError:
            continue
    for old in sorted(dated,reverse=True)[KEEP:]:
        old.unlink(missing_ok=True)
    return True


_started=False
_lock=threading.Lock()


def worker(root,permitted):
    while True:
        try:
            archive_once(root,permitted)
        except Exception as exc:
            LOG.warning("Daily briefing archive failed: %s",exc)
        time.sleep(300)


def start_worker(root,permitted):
    global _started
    with _lock:
        if _started:
            return
        _started=True
        threading.Thread(target=worker,args=(root,permitted),name="sdrcc-daily-briefing",daemon=True).start()
