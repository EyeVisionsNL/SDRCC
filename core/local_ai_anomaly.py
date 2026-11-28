"""Low-cost observer: persistent alert episodes, no model or receiver actions."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime
import json
import logging
import math
import os
import sqlite3
import statistics
import tempfile
import threading
import time
from uuid import uuid4

from core import local_ai_health as health, local_ai_reception as reception, local_ai_memory as memory

INTERVAL=60
CONFIRM=3
CLEAR=3
HISTORY=40
MAX_PENDING=80
SOURCE="data/state/anomaly_monitor.json"
UPDATE="data/state/update_service_state.json"
LOG=logging.getLogger(__name__)
RULES={
    "ais_service":"AIS service failure / recovery exhausted",
    "adsb_service":"ADS-B service failure / recovery exhausted",
    "usb_identity":"Configured USB identity",
    "analytics":"Reception history freshness",
    "ais_rate":"AIS message rate",
    "adsb_rate":"ADS-B message rate",
    "ram":"Available RAM",
    "disk":"Free disk space",
    "temperature":"CPU temperature",
    "load":"CPU load per logical CPU",
}


def result(state, detail):
    return {"state":state,"detail":detail}


def rate_window(db, service, end):
    # Fixed column names only. All fifteen minutes must represent a mostly
    # continuous active decoder; no legacy AIS or synthetic zero values.
    on=service+"_on"
    rate=service+"_rate"
    extra=" AND typeof(ais_fresh) IN ('integer','real') AND ais_fresh>=0" if service=="ais" else ""
    count, active, n, avg = db.execute(
        f"SELECT COUNT(*), SUM(CASE WHEN {on}=1 THEN 1 ELSE 0 END), "
        f"COUNT(CASE WHEN {on}=1 AND typeof({rate}) IN ('integer','real') AND {rate} BETWEEN 0 AND 1e12{extra} THEN 1 END), "
        f"AVG(CASE WHEN {on}=1 AND typeof({rate}) IN ('integer','real') AND {rate} BETWEEN 0 AND 1e12{extra} THEN {rate} END) "
        "FROM samples WHERE ts>? AND ts<=?",(end-900,end)).fetchone()
    return avg if 10<=count<=20 and active==count and n>=10 and n>=count*.8 else None


def history_checks(root, now):
    checks={key:result("unknown","Reception history unavailable") for key in ("analytics","ais_rate","adsb_rate")}
    path=root/reception.SOURCE
    if not path.is_file():
        return checks
    deadline=time.monotonic()+1
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=.3)) as db:
            db.execute("PRAGMA query_only=ON")
            db.set_progress_handler(lambda:int(time.monotonic()>=deadline),1000)
            db.execute("BEGIN")
            newest=db.execute("SELECT MAX(ts) FROM samples WHERE ts<=?",(now,)).fetchone()[0]
            if newest is None:
                return checks
            age=now-newest
            checks["analytics"]=result("bad" if age>180 else "ok",f"Latest sample age: {int(age)} s")
            if age>180:
                return checks
            cols={r[1] for r in db.execute("PRAGMA table_info(samples)")}
            for service in ("ais","adsb"):
                key=service+"_rate"
                required={service+"_on",key}|({"ais_fresh"} if service=="ais" else set())
                if not required<=cols:
                    continue
                current=rate_window(db,service,now)
                prior=[v for d in range(1,8) if (v:=rate_window(db,service,now-d*86400)) is not None]
                if current is None or len(prior)<3:
                    checks[key]=result("unknown","Need 10 valid active samples in current 15 min and at least 3 comparable prior days")
                    continue
                baseline=statistics.median(prior)
                if baseline<1:
                    checks[key]=result("unknown","Baseline below 1 message/sec")
                    continue
                ratio=current/baseline
                detail=f"Current {current:.2f} msg/s; baseline {baseline:.2f} msg/s ({len(prior)} prior days); {100*(ratio-1):+.1f}%"
                # Hysteresis: warning <=40%; clear >=60%. Between: hold.
                checks[key]=result("bad" if ratio<=.4 else "ok" if ratio>=.6 else "hold",detail)
    except (OSError,sqlite3.Error,ValueError,TypeError):
        return checks
    return checks


def collect(root, now):
    checks=history_checks(root,now)
    from core import receiver_manager
    for label,key in (("AIS","ais"),("ADS-B","adsb")):
        service=health.observe_service(label)
        exhausted=receiver_manager.crash_recovery_exhausted(health.UNITS[label])
        checks[key+"_service"]=result("bad" if exhausted or service["status"]=="attention" else
                                      "ok" if service["state"]=="active" and service["status"]=="ok" else "unknown",
                                      "Recovery budget exhausted" if exhausted else "Service: "+service["state"]+"; idle may be intentional")
        if service["state"]!="active":
            checks[key+"_rate"]=result("unknown","Service not active; reception comparison paused")
    usb=health.usb_observation()
    checks["usb_identity"]=result({"attention":"bad","ok":"ok"}.get(usb["status"],"unknown"),"Kernel USB identity: "+usb["status"])
    resources=health.resources(root)
    for key,field,bad,clear,low,unit in (
        ("ram","available_ram_gib",2,3,True,"GiB"),
        ("disk","disk_free_gib",2,3,True,"GiB"),
        ("temperature","cpu_temperature_c",85,78,False,"°C"),
        ("load","load_1m_per_cpu",1.5,1.0,False,""),
    ):
        value=resources.get(field)
        if value is None or not math.isfinite(value):
            checks[key]=result("unknown","Measurement unavailable")
        else:
            alarm=value<bad if low else value>=bad
            normal=value>=clear if low else value<=clear
            checks[key]=result("bad" if alarm else "ok" if normal else "hold",f"{value:g} {unit}".strip())
    return checks


def defaults():
    return {"enabled":True,"mqtt":False,"active":{},"history":[],"outbox":[]}


def load(root):
    path=root/SOURCE
    if not path.exists():
        return defaults()
    with path.open("rb") as handle:
        raw=handle.read(256*1024+1)
    if len(raw)>256*1024:
        raise ValueError("Anomaly state exceeds limit")
    state=json.loads(raw)
    if (not isinstance(state,dict) or type(state.get("enabled")) is not bool or type(state.get("mqtt")) is not bool
            or not isinstance(state.get("active"),dict) or not set(state["active"])<=RULES.keys()
            or not isinstance(state.get("history"),list) or len(state["history"])>HISTORY
            or not isinstance(state.get("outbox"),list) or len(state["outbox"])>MAX_PENDING):
        raise ValueError("Invalid anomaly state")
    for event in [*state["active"].values(),*state["history"],*state["outbox"]]:
        if (not isinstance(event,dict) or event.get("rule") not in RULES
                or event.get("transition") not in ("opened","cleared")
                or not all(isinstance(event.get(k),str) for k in ("id","title","timestamp","detail"))):
            raise ValueError("Invalid stored anomaly event")
        datetime.fromisoformat(event["timestamp"])
    if any(e["rule"]!=k or e["transition"]!="opened" for k,e in state["active"].items()):
        raise ValueError("Invalid open anomaly episode")
    return state


def save(root,state):
    path=root/SOURCE
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=path.parent,prefix=".anomaly-",delete=False) as f:
        temp=type(path)(f.name)
        try:
            json.dump(state,f,allow_nan=False,separators=(",",":"))
            f.flush()
            os.fsync(f.fileno())
            os.replace(temp,path)
        finally:
            temp.unlink(missing_ok=True)


def advance(state, streak, checks, now):
    """Three consecutive bad/normal observations; unknown never clears."""
    events=[]
    for key,title in RULES.items():
        reading=checks.get(key,result("unknown","Not observed"))
        status=reading["state"]
        old=streak.get(key,("unknown",0))
        count=min(CONFIRM,old[1]+1) if old[0]==status else 1
        streak[key]=(status,count)
        if status=="bad" and count>=CONFIRM and key not in state["active"]:
            event={"id":uuid4().hex,"rule":key,"title":title,"transition":"opened",
                   "timestamp":reception.utc(int(now)),"detail":reading["detail"]}
            state["active"][key]=event
            events.append(event)
        elif status=="ok" and count>=CLEAR and key in state["active"]:
            previous=state["active"].pop(key)
            events.append(dict(previous,transition="cleared",timestamp=reception.utc(int(now)),
                               detail=reading["detail"]))
    for event in events:
        state["history"]=([event]+state["history"])[:HISTORY]
        if len(state["outbox"])<MAX_PENDING:
            state["outbox"].append(event)
        else:
            state["memory_overflow"]=True
    return events


def persist_memory(root,event):
    # Same transaction as notebook insertion; deterministic idempotency key.
    key="anomaly:"+event["id"]+":"+event["transition"]
    stamp=datetime.fromisoformat(event["timestamp"]).timestamp()
    with closing(memory.connect_write(root)) as db,db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM entries WHERE event_key=?",(key,)).fetchone():
            return
        memory.insert(db,(stamp,"incident",("Alert: " if event["transition"]=="opened" else "Cleared: ")+event["title"],
                          event["detail"],"Threshold cleared; cause and lasting repair not verified." if event["transition"]=="cleared" else "",
                          "anomaly_monitor",key))


class Monitor:
    def __init__(self,root):
        self.root=root
        self.lock=threading.RLock()
        self.streak={}
        self.checks={}
        self.last=None
        self.last_epoch=None
        self.error=""
        self.memory_error=""
        self.mqtt_result="Not sent"
        self.running=False
        self.state=None
        self.generation=0

    def get_state(self):
        if self.state is None:
            self.state=load(self.root)
        return self.state

    def configure(self,enabled,mqtt):
        if type(enabled) is not bool or type(mqtt) is not bool:
            raise ValueError("Invalid monitoring settings")
        with self.lock:
            state=deepcopy(self.get_state())
            state.update(enabled=enabled,mqtt=mqtt)
            save(self.root,state)
            self.state=state
            self.generation+=1
            self.streak.clear()
            self.running=False
            return self.snapshot()

    def snapshot(self):
        with self.lock:
            try:
                state=self.get_state()
            except (OSError,ValueError) as exc:
                return {"kind":"anomaly_detection","status":"unavailable","reason":str(exc)[:160],
                        "enabled":False,"mqtt":False,"active":[],"history":[],"checks":{}}
            return {"kind":"anomaly_detection","status":"monitoring" if self.running and state["enabled"] else "paused",
                    "enabled":state["enabled"],"mqtt":state["mqtt"],"observed_utc":self.last,
                    "active":list(state["active"].values()),"history":state["history"][:12],
                    "checks":{key:dict(self.checks.get(key,result("unknown","Not observed")),title=title,
                                       consecutive=self.streak.get(key,("",0))[1]) for key,title in RULES.items()},
                    "error":self.error,"memory_error":self.memory_error,"memory_pending":len(state["outbox"]),
                    "memory_overflow":state.get("memory_overflow",False),"mqtt_result":self.mqtt_result,
                    "scope":"Advisory only; 3 consecutive minute observations to open/clear. Missing/idle data does not prove recovery. Rates compare 15 min with median of same UTC time windows on at least 3 of previous 7 days. Drop >=60%, clear when current rate reaches >=60% of baseline. Traffic, schedules and RF conditions vary. No automatic repair."}

    def tick(self, permitted, *, now=None):
        now=time.time() if now is None else now
        with self.lock:
            state=self.get_state()
            if not permitted() or not state["enabled"]:
                self.running=False
                self.streak.clear()
                return
            generation=self.generation
        checks=collect(self.root,now)
        with self.lock:
            if generation!=self.generation or not permitted() or not self.get_state()["enabled"]:
                self.running=False
                self.streak.clear()
                return
            candidate=deepcopy(self.get_state())
            streak=deepcopy(self.streak)
            if self.last_epoch is None or not 0<now-self.last_epoch<=150:
                streak.clear()
            events=advance(candidate,streak,checks,now)
            if events:
                save(self.root,candidate)
                self.state=candidate
            self.streak=streak
            self.checks=checks
            self.last=reception.utc(int(now))
            self.last_epoch=now
            self.running=True
            self.error=""
            # Retry durable local memory outbox, bounded work per tick.
            for event in self.get_state()["outbox"][:5]:
                try:
                    persist_memory(self.root,event)
                    candidate=deepcopy(self.get_state())
                    candidate["outbox"].pop(0)
                    save(self.root,candidate)
                    self.state=candidate
                    self.memory_error=""
                except (OSError,sqlite3.Error,ValueError) as exc:
                    self.memory_error=str(exc)[:160]
                    break
            if self.get_state()["mqtt"]:
                from core import emergency_monitor
                for event in events:
                    self.mqtt_result=emergency_monitor.publish_station_anomaly(event)

    def worker(self, permitted):
        while True:
            try:
                self.tick(permitted)
            except Exception as exc:
                with self.lock:
                    self.error=f"{type(exc).__name__}: {exc}"[:160]
                    self.running=False
                    self.streak.clear()
                LOG.warning("Anomaly monitor observation failed: %s",exc)
            time.sleep(INTERVAL)


_instance=None
_start_lock=threading.Lock()
_started=False


def instance(root):
    global _instance
    with _start_lock:
        if _instance is None or _instance.root!=root:
            _instance=Monitor(root)
        return _instance


def start_worker(root,permitted):
    global _started
    monitor=instance(root)
    with _start_lock:
        if _started:
            return
        _started=True
        threading.Thread(target=monitor.worker,args=(permitted,),name="sdrcc-anomaly-monitor",daemon=True).start()
