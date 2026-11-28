"""Read-only aggregate of atomically published Mission History records."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
import time

from core import local_ai_reception as reception

SOURCE = "data/state/mission_history.json"
MAX_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 500
MAX_GROUPS = 8
COMPLETED = {"SUCCESS", "NO IMAGES", "NO SYNC", "NO SIGNAL", "FAILED"}
PERIODS = {"all": None, "30d": 30*86400, "7d": 7*86400, "24h": 86400}


def numeric(value, low, high):
    if isinstance(value,bool):
        return None
    try:
        value=float(value)
        return value if math.isfinite(value) and low<=value<=high else None
    except (TypeError,ValueError,OverflowError):
        return None


def safe_label(value):
    return " ".join(str(value or "Unknown").split())[:64]


def timestamp(value):
    if not isinstance(value,str):
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except (ValueError,OverflowError,OSError):
        return None


def simulated(row):
    return (str(row.get("pipeline") or "").lower().startswith("simulation_")
            or "/simulations/" in str(row.get("output_path") or "").replace("\\","/").lower()
            or row.get("simulated") is True or row.get("virtual") is True)


def summary(rows):
    counts=Counter(str(r.get("result") or "").strip().upper() for r in rows)
    known=sum(counts[k] for k in COMPLETED)
    snr=[v for r in rows if (v:=numeric(r.get("peak_snr_db"),-100,100)) is not None]
    images=[v for r in rows if (v:=numeric(r.get("image_count"),0,1e7)) is not None and v.is_integer()]
    frames=[v for r in rows if (v:=numeric(r.get("frames"),0,1e12)) is not None and v.is_integer()]
    quality=[v for r in rows if (v:=numeric(r.get("quality_score"),0,100)) is not None]
    duration=[v for r in rows if (v:=numeric(r.get("duration_seconds"),0,86400*7)) is not None]
    return {"missions":len(rows),"completed":known,"success":counts["SUCCESS"],
            "success_pct":round(100*counts["SUCCESS"]/known,1) if known else None,
            "cancelled":counts["CANCELLED"],"unknown_result":len(rows)-known-counts["CANCELLED"],
            "results":{k:counts[k] for k in sorted(COMPLETED|{"CANCELLED"}) if counts[k]},
            "peak_snr_mean_db":round(sum(snr)/len(snr),2) if snr else None,
            "peak_snr_best_db":max(snr) if snr else None,"snr_samples":len(snr),
            "images":int(sum(images)) if images else None,"image_samples":len(images),
            "frames":int(sum(frames)) if frames else None,"frame_samples":len(frames),
            "quality_mean_pct":round(sum(quality)/len(quality),1) if quality else None,"quality_samples":len(quality),
            "duration_mean_s":round(sum(duration)/len(duration),1) if duration else None}


def group_summary(rows, key):
    groups=defaultdict(list)
    for row in rows:
        groups[safe_label(row.get(key))].append(row)
    ordered=sorted(groups.items(),key=lambda item:(-len(item[1]),item[0]))
    # Compact evidence; counts for omitted groups explicitly reported.
    return {"groups":[{"name":name,**{k:v for k,v in summary(items).items() if k in (
        "missions","completed","success","success_pct","peak_snr_mean_db","peak_snr_best_db","snr_samples","images","image_samples")}}
        for name,items in ordered[:MAX_GROUPS]],
        "omitted_groups":max(0,len(ordered)-MAX_GROUPS)}


def elevation_summary(rows):
    groups={"0–29°":[],"30–59°":[],"60–90°":[],"Unknown":[]}
    for row in rows:
        v=numeric(row.get("max_elevation"),0,90)
        key="Unknown" if v is None else "0–29°" if v<30 else "30–59°" if v<60 else "60–90°"
        groups[key].append(row)
    return [{"name":key,**{k:v for k,v in summary(items).items() if k in (
        "missions","completed","success_pct","peak_snr_mean_db","snr_samples")}}
        for key,items in groups.items() if items]


def snapshot(root, period="all", *, now=None):
    if period not in PERIODS:
        raise ValueError("Invalid mission history period")
    now=time.time() if now is None else now
    span=PERIODS[period]
    base={"kind":"mission_analyst","observed_utc":reception.utc(int(now)),"source":SOURCE,"period":period,
          "scope":"Stored completed/cancelled mission records only (up to 500 retained). Known simulation records excluded. Success denominator excludes cancelled and unknown outcomes. SNR is peak SNR per mission; not a controlled comparison of satellite, receiver or antenna. No future pass predictions."}
    path=root/SOURCE
    try:
        # Writer uses atomic replacement. Reading a single file descriptor
        # provides a consistent old or new snapshot, without creating locks.
        with path.open("rb") as handle:
            raw=handle.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:
            raise ValueError("History exceeds byte limit")
        rows=json.loads(raw)
        if not isinstance(rows,list) or len(rows)>MAX_RECORDS or any(not isinstance(r,dict) for r in rows):
            raise ValueError("Unexpected mission history schema")
    except (OSError,ValueError,UnicodeError):
        return dict(base,status="unavailable",reason="Mission History missing, unreadable or exceeds safety limits.")
    selected=[]
    excluded=0
    undated=0
    for row in rows:
        if simulated(row):
            excluded+=1
            continue
        stamp=timestamp(row.get("ended_at")) 
        if stamp is None:
            undated+=1
        if span is not None and (stamp is None or not now-span<stamp<=now):
            continue
        selected.append(row)
    return dict(base,status="ok" if selected else "no_missions",retained_records=len(rows),
                excluded_simulations=excluded,undated_records=undated,
                summary=summary(selected),satellites=group_summary(selected,"satellite"),
                receivers=group_summary(selected,"receiver"),elevation=elevation_summary(selected))
