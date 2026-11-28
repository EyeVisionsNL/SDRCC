"""Local AIS and historical ATIS evidence, observer only."""
from collections import Counter
from contextlib import closing
import math
import sqlite3
import time

from core import features, local_ai_reception

RADII = (10, 25, 50, 100)
MAX_INPUT = 10000
MAX_EXAMPLES = 12
MAX_AGE = 300


def distance_km(lat, lon, lat2, lon2):
    a, b = math.radians(lat), math.radians(lat2)
    h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon2-lon)/2)**2
    return 6371.0088*2*math.asin(math.sqrt(max(0, min(1, h))))


def finite(value):
    try:
        v = float(value)
        return v if math.isfinite(v) and not isinstance(value, bool) else None
    except (ValueError, TypeError):
        return None


def atis_history(root, now):
    source = "data/analytics/atis_statistics.sqlite3"
    base = {"source": source, "period": "24h", "scope": "Station-wide events, not unique vessels or radius-filtered counts"}
    if not features.feature_enabled("traffic_voice"):
        return dict(base, status="disabled")
    path = root / source
    if not path.is_file():
        return dict(base, status="unavailable")
    deadline = time.monotonic()+1.0
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=.3)) as db:
            db.execute("PRAGMA query_only=ON")
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            db.execute("BEGIN")
            cols = {r[1] for r in db.execute("PRAGMA table_info(atis_events)")}
            if not {"ts","decoded"} <= cols:
                return dict(base, status="unavailable")
            fields = ("decoded","ais_matched","photo_found")
            projections = [f"SUM(CASE WHEN {c}=1 THEN 1 ELSE 0 END)" if c in cols else "NULL" for c in fields]
            n, *values = db.execute("SELECT COUNT(*), "+",".join(projections)+" FROM (SELECT * FROM atis_events WHERE ts > ? AND ts <= ? LIMIT 60001)", (now-86400,now)).fetchone()
            if n > 60000:
                return dict(base,status="unavailable")
            return dict(base,status="ok" if n else "no_events",candidates=n,
                        **{c: (v if v is not None else (0 if c in cols and n == 0 else None)) for c,v in zip(fields,values)})
    except (OSError,sqlite3.Error):
        return dict(base,status="unavailable")


def summarize(payload, home, radius):
    """Only fresh, validated, positioned MMSIs; map's existing profile logic."""
    from core import traffic_map, receiver_monitor
    rows = receiver_monitor._extract_list(payload, ("ships","vessels","targets","data"))
    if not (isinstance(payload,list) or isinstance(payload,dict) and (bool(rows) or any(isinstance(payload.get(k),(list,dict)) for k in ("ships","vessels","targets","data")))):
        return {"status":"unavailable"}
    if len(rows)>MAX_INPUT:
        return {"status":"unavailable","reason":"Feed exceeds observation limit"}
    lat,lon = finite(home.get("latitude")),finite(home.get("longitude"))
    if not home.get("configured") or lat is None or lon is None or abs(lat)>90 or abs(lon)>180:
        return {"status":"unavailable","reason":"Configure SDRCC Home Position for radius filtering"}
    # Filter before map normalization, so an older duplicate cannot hide a newer fix.
    selected={}
    for row in rows:
        mmsi=receiver_monitor._valid_mmsi(row.get("mmsi"))
        age=receiver_monitor._first_number(row,("last_signal","last_signal_seconds","age"))
        if not mmsi or age is None or not 0<=age<=MAX_AGE or finite(row.get("validated"))!=1:
            continue
        old=selected.get(mmsi)
        if old is None or age<old[0]:
            selected[mmsi]=(age,row)
    if len(selected)>traffic_map.MAX_TARGETS:
        return {"status":"unavailable","reason":"Validated map target limit exceeded"}
    vessels=traffic_map.vessels([v[1] for v in selected.values()])
    local=[]
    for v in vessels:
        if v.get("validation_state")!="verified" or v.get("age_seconds") is None or v["age_seconds"]>MAX_AGE:
            continue
        if v.get("is_offshore_structure") or v.get("shipclass") in (10,11,12) or str(v.get("id","")).startswith("99") or v.get("render_profile") in ("ais_helicopter","aton","ais_aton"):
            continue
        if v["lat"]==0 and v["lon"]==0:
            continue
        d=distance_km(lat,lon,v["lat"],v["lon"])
        if d<=radius:
            local.append((d,v))
    local.sort(key=lambda pair:pair[0])
    counts=Counter(v.get("render_profile") or "unknown" for _,v in local)
    moving=sum(v.get("speed_knots") is not None and v["speed_knots"]>.5 for _,v in local)
    speed_unknown=sum(v.get("speed_knots") is None for _,v in local)
    # Bounded, ordinary AIS vessel examples. No raw positions, destinations or
    # identifiers for emergency/law-enforcement vessels are sent to the model.
    ordinary=[(d,v) for d,v in local if not any(t in str(v.get("render_profile","")).lower() for t in ("police","rescue","sar","military","knrm","coastguard","port_authority","oil_response"))]
    examples=[{"name":str(v["name"])[:60],"profile":v.get("render_profile"),"distance_km":round(d,1),
               "speed_knots":v.get("speed_knots"),"age_seconds":v.get("age_seconds")} for d,v in ordinary[:MAX_EXAMPLES]]
    return {"status":"ok","validated_targets":len(local),"moving":moving,
            "stationary_or_slow":len(local)-moving-speed_unknown,"speed_unknown":speed_unknown,
            "by_profile":dict(sorted(counts.items())), "nearest_examples":examples,
            "examples_limited":len(ordinary)>MAX_EXAMPLES,
            "source_rows":len(rows),"freshness_seconds":MAX_AGE}


def snapshot(root, radius, *, now=None):
    if isinstance(radius,bool) or radius not in RADII:
        raise ValueError("Unsupported maritime radius")
    now=time.time() if now is None else now
    from core import config, receiver_monitor, local_ai_health
    state=local_ai_health.observe_service("AIS")
    if state["state"]!="active":
        ais={"status":"inactive" if state["state"]=="inactive" else "unavailable"}
    else:
        data,_=receiver_monitor._read_ais_ships()
        ais=summarize(data,config.get_home_position(),radius)
    return {"kind":"maritime","observed_utc":local_ai_reception.utc(int(now)),
            "radius_km":radius,"source":"Local AIS-Catcher ships.json",
            "scope":"Current received AIS reports only; not all traffic. ATIS is station-wide last 24h.",
            "ais":ais,"atis":atis_history(root,now)}
