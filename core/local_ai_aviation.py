"""Aggregate fresh local ADS-B observations; no individual aircraft tracking."""
from collections import Counter
import json
import math
import os
import re
import time

from core import local_ai_reception as reception
from core.local_ai_maritime import distance_km, finite

RADII = (10, 25, 50, 100, 200)
MAX_BYTES = 8*1024*1024
MAX_ROWS = 10000
POSITION_AGE = 30


def fresh_json(paths, now, max_age):
    for path in paths:
        try:
            with path.open("rb") as handle:
                age = now-os.fstat(handle.fileno()).st_mtime
                if not -1 <= age <= max_age:
                    continue
                raw=handle.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:
                continue
            value=json.loads(raw)
            if isinstance(value,dict):
                return value
        except (OSError,ValueError,UnicodeError):
            continue
    return None


def summarize(payload, home, radius, now):
    from core import traffic_map
    if not isinstance(payload,dict) or not isinstance(payload.get("aircraft"),list):
        return {"status":"unavailable","reason":"Fresh aircraft data unavailable."}
    stamp=finite(payload.get("now"))
    if stamp is None or not -1<=now-stamp<=5:
        return {"status":"unavailable","reason":"Aircraft snapshot timestamp missing or stale."}
    rows=payload["aircraft"]
    if len(rows)>MAX_ROWS:
        return {"status":"unavailable","reason":"Aircraft observation limit exceeded."}
    lat,lon=finite(home.get("latitude")),finite(home.get("longitude"))
    if not home.get("configured") or lat is None or lon is None or abs(lat)>90 or abs(lon)>180:
        return {"status":"unavailable","reason":"Configure SDRCC Home Position."}
    targets={}
    for row in rows:
        if not isinstance(row,dict):
            continue
        ident=str(row.get("hex") or "").lower()
        pos_age=finite(row.get("seen_pos"))
        seen=finite(row.get("seen"))
        a,b=finite(row.get("lat")),finite(row.get("lon"))
        if (not re.fullmatch(r"~?[0-9a-f]{6}",ident) or pos_age is None or not 0<=pos_age<=POSITION_AGE
                or seen is None or not 0<=seen<=POSITION_AGE
                or a is None or b is None or abs(a)>90 or abs(b)>180 or (a==0 and b==0)):
            continue
        previous=targets.get(ident)
        if previous is None or pos_age<previous[0]:
            targets[ident]=(pos_age,row,distance_km(lat,lon,a,b))
    bins=dict.fromkeys(("Below 5,000 ft","5,000–14,999 ft","15,000–24,999 ft","25,000+ ft","Unknown"),0)
    cats=Counter()
    altitudes=[]
    speeds=[]
    ranges=[]
    ground=helicopters=surface=aircraft_count=0
    for _,row,distance in targets.values():
        if distance>radius:
            continue
        category=str(row.get("category") or "").upper()
        if category in ("C1","C2","C3","C4","C5"):
            surface+=1
            continue
        aircraft_count+=1
        ranges.append(distance)
        helicopter=traffic_map._is_helicopter(row)
        helicopters+=int(helicopter)
        if helicopter:
            group="Rotorcraft"
        elif category in ("A1","A2","A3","A4","A5","A6"):
            group={"A1":"Light","A2":"Small","A3":"Large","A4":"High vortex","A5":"Heavy","A6":"High performance"}[category]
        elif category in ("B1","B2","B3","B4","B5","B6"):
            group="Other airborne category"
        else:
            group="Unknown category"
        cats[group]+=1
        if row.get("alt_baro")=="ground":
            ground+=1
            continue
        altitude=finite(row.get("alt_baro"))
        if altitude is None:
            altitude=finite(row.get("alt_geom"))
        if altitude is None or not -2000<=altitude<=70000:
            bins["Unknown"]+=1
        else:
            altitudes.append(altitude)
            bins["Below 5,000 ft" if altitude<5000 else "5,000–14,999 ft" if altitude<15000 else "15,000–24,999 ft" if altitude<25000 else "25,000+ ft"]+=1
        speed=finite(row.get("gs"))
        if speed is not None and 0<=speed<=2000:
            speeds.append(speed)
    return {"status":"ok","aircraft":aircraft_count,"helicopters":helicopters,"ground_aircraft":ground,
            "surface_targets_excluded":surface,"altitude_mean_ft":round(sum(altitudes)/len(altitudes)) if altitudes else None,
            "altitude_samples":len(altitudes),"speed_mean_knots":round(sum(speeds)/len(speeds),1) if speeds else None,
            "speed_samples":len(speeds),"max_range_nm":round(max(ranges)/1.852,1) if ranges else None,
            "altitude_bands":bins,"categories":dict(sorted(cats.items())),"source_rows":len(rows)}


def snapshot(root, radius, *, now=None):
    if type(radius) is not int or radius not in RADII:
        raise ValueError("Unsupported aviation radius")
    from core import config, receiver_monitor, local_ai_health
    state=local_ai_health.observe_service("ADS-B")
    now=time.time() if now is None else now
    base={"kind":"aviation","observed_utc":reception.utc(int(now)),"radius_km":radius,
          "source":"Local readsb aircraft.json and stats.json",
          "scope":"Received aircraft with positions and messages <=30s old; snapshot <=5s old. Counts are within radius, not total air traffic. Ground is explicit ADS-B ground status, surface categories excluded. Altitude/speed exclude reported ground aircraft. Categories are reported/inferred, not verified. Message rate is station-wide last-minute decoder data, not radius-filtered. No individual locations, identifiers or tracking.",
          "message_rate_station":None}
    if state["state"]!="active":
        return dict(base,status="inactive" if state["state"]=="inactive" else "unavailable",reason="ADS-B service not confirmed active.")
    payload=fresh_json(receiver_monitor.READSB_AIRCRAFT_FILES,now,5)
    data=summarize(payload,config.get_home_position(),radius,now)
    if data["status"]=="ok":
        stats=fresh_json(receiver_monitor.READSB_STATS_FILES,now,15)
        rate=receiver_monitor._readsb_window_message_rate(stats)
        base["message_rate_station"]=round(rate,2) if rate is not None and math.isfinite(rate) and rate>=0 else None
    return dict(base,**data)
