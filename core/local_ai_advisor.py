"""Advisory view of existing satellite predictions; no queue or receiver mutations."""
import json
import time
from datetime import datetime, timezone
from core import local_ai_missions as history, local_ai_reception as reception

HOURS=(24,48)
MAX_CANDIDATES=200
DISPLAY_LIMIT=24
MODEL_LIMIT=6


def read_json(path, limit):
    with path.open("rb") as handle:
        raw=handle.read(limit+1)
    if len(raw)>limit:
        raise ValueError("Input exceeds observer limit")
    return json.loads(raw)


def history_rows(root, now):
    try:
        rows=read_json(root/history.SOURCE,history.MAX_BYTES)
        if not isinstance(rows,list) or len(rows)>history.MAX_RECORDS or any(not isinstance(r,dict) for r in rows):
            raise ValueError("Invalid mission history")
        return [r for r in rows if not history.simulated(r)
                and (stamp:=history.timestamp(r.get("ended_at"))) is not None
                and now-90*86400<stamp<=now
                and str(r.get("result") or "").strip().upper() in history.COMPLETED], "ok"
    except (OSError,ValueError,OverflowError):
        return [],"unavailable"


def key(value):
    return str(value or "").strip().casefold()


def band(elevation):
    return 0 if elevation<30 else 1 if elevation<60 else 2


def historical_match(rows, item, device):
    """Match the same satellite, pipeline, current receiver and elevation band."""
    if not device or not key(item.get("pipeline")):
        return {"status":"insufficient","completed":0}
    identities={key(device.get(k)) for k in ("runtime_id","registry_id","number","canonical_id")} - {""}
    serial=key(device.get("serial"))
    matches=[]
    for row in rows:
        if key(row.get("satellite"))!=key(item["name"]) or key(row.get("pipeline"))!=key(item["pipeline"]):
            continue
        # Prefer exact hardware serial when both are known. Otherwise match
        # canonical/runtime aliases, explicitly described as historical identity.
        if serial and key(row.get("receiver_serial")):
            same=serial==key(row["receiver_serial"])
        else:
            same=bool(identities & {key(row.get("receiver")),key(row.get("receiver_id"))})
        elev=history.numeric(row.get("max_elevation"),0,90)
        if same and elev is not None and band(elev)==band(item["elevation"]):
            matches.append(row)
    stats=history.summary(matches)
    n=stats["completed"]
    return {"status":"observed" if n>=3 else "insufficient","completed":n,
            "success":stats["success"],"success_pct":stats["success_pct"] if n>=3 else None,
            "mean_peak_snr_db":stats["peak_snr_mean_db"] if stats["snr_samples"]>=3 else None,
            "snr_samples":stats["snr_samples"]}


def epoch(value):
    if not isinstance(value,datetime) or value.tzinfo is None:
        return None
    return value.timestamp()


def summarize(candidates, devices, assignments, receiver_state, tle_state, overrides, rows, now, hours, scheduler):
    if len(candidates)>MAX_CANDIDATES:
        raise ValueError("Planner candidate limit exceeded")
    result=[]
    by_id={key(d.get("runtime_id")):d for d in devices if d.get("runtime_id")}
    for raw in candidates:
        start,end=epoch(raw.get("start")),epoch(raw.get("end"))
        elev=history.numeric(raw.get("max_elevation"),0,90)
        if start is None or end is None or not now<start<=now+hours*3600 or end<=start or elev is None:
            continue
        plugin=str(raw.get("plugin_id") or "")
        if plugin not in ("weather","iss_voice") or not raw.get("name"):
            continue
        name=history.safe_label(raw["name"])
        role=raw.get("receiver_role") or plugin
        runtime=key(assignments.get(role))
        device=by_id.get(runtime)
        canonical=device.get("registry_id") if device else None
        queue_key=f"{plugin}:{raw['name']}:{int(start)}"
        override=overrides.get(queue_key,{})
        flags=[]
        if override.get("skipped"):
            flags.append("Operator skipped")
        if not raw.get("automation_eligible") or not raw.get("execution_enabled"):
            flags.append("Execution not enabled")
        tle_info=tle_state.get(plugin,{})
        if tle_info.get("valid") is not True:
            flags.append("TLE unavailable")
        elif tle_info.get("stale") is not False:
            flags.append("TLE stale")
        if not device:
            flags.append("Receiver not assigned")
        elif device.get("presence")!="PRESENT":
            flags.append("Receiver presence not confirmed")
        elif receiver_state.get("transaction") or canonical in receiver_state.get("recovery",{}):
            flags.append("Receiver binding / recovery pending")
        if device and device.get("locked"):
            flags.append("Receiver locked")
        if scheduler not in ("AUTO","MANUAL","PAUSED"):
            flags.append("Scheduler mode unknown")
        item={"name":name,"mission_type":history.safe_label(raw.get("mission_type") or plugin),
              "pipeline":history.safe_label(raw.get("pipeline")),"start_utc":reception.utc(start),
              "end_utc":reception.utc(end),"elevation":round(elev,1),"duration_seconds":int(end-start),
              "receiver":history.safe_label(device.get("number") or runtime) if device else None,
              "receiver_presence":device.get("presence") if device else None,
              "shared_roles":sorted(str(r) for r in (device.get("roles") or []) if r!=role)[:8] if device else [],
              "flags":flags,"start_epoch":start,"end_epoch":end}
        item["history"]=historical_match(rows,item,device)
        result.append(item)
    # Identify overlap on the single mission automation lane, irrespective of SDR.
    eligible=[r for r in result if not r["flags"]]
    for item in eligible:
        peers=[other for other in eligible if other is not item and
               max(item["start_epoch"],other["start_epoch"])<min(item["end_epoch"],other["end_epoch"])]
        if peers:
            item["flags"].append("Overlapping mission windows")
    for item in result:
        item["assessment"]="review" if item["flags"] else "high elevation" if item["elevation"]>=60 else "moderate elevation" if item["elevation"]>=30 else "low elevation"
    result.sort(key=lambda r:(r["start_epoch"],r["name"]))
    # Advisory ranking by geometry only; history is descriptive, not a probability.
    ranked=sorted((r for r in result if not r["flags"]),key=lambda r:(-r["elevation"],r["start_epoch"],r["name"]))
    return {"candidate_count":len(result),"review_count":sum(bool(r["flags"]) for r in result),
            "high_elevation_count":sum(r["elevation"]>=60 and not r["flags"] for r in result),
            "best_geometry":ranked[0] if ranked else None,"passes":result[:DISPLAY_LIMIT],
            "omitted_passes":max(0,len(result)-DISPLAY_LIMIT)}


def snapshot(root,hours=24,*,now=None):
    if type(hours) is not int or hours not in HOURS:
        raise ValueError("Invalid mission advisor horizon")
    now=time.time() if now is None else now
    base={"kind":"mission_advisor","observed_utc":reception.utc(now),"hours":hours,
          "scope":"Existing policy-approved future pass predictions only; not a reservation or execution decision. Geometry ranking is descriptive. Historical results cover retained known completed missions in the last 90 days with matching satellite, pipeline, receiver identity and elevation band; minimum 3 for percentage or SNR. Overlapping windows use the single automation lane; no handover/preflight time or live availability guarantee. Shared receiver roles may require interruption. No automatic scheduling."}
    from core import features, config
    if not features.feature_enabled("satellite"):
        return dict(base,status="disabled",reason="Satellite feature disabled.")
    if not config.home_position_configured():
        return dict(base,status="unavailable",reason="Configure Home Position first.")
    from core import mission_planner, device_manager, receiver_manager, tle
    try:
        try:
            overrides=read_json(root/"data/state/mission_queue.json",256*1024).get("overrides")
        except FileNotFoundError:
            overrides={}
        if not isinstance(overrides,dict) or any(not isinstance(v,dict) for v in overrides.values()):
            raise ValueError("Invalid queue overrides")
        try:
            scheduler=read_json(root/"data/state/mission_scheduler.json",16384).get("mode")
        except FileNotFoundError:
            scheduler="MANUAL"
        tle_state=tle.get_status()
        rows,historical_status=history_rows(root,now)
        data=summarize(mission_planner.get_candidates(hours),device_manager.get_devices(),
                       config.get_receiver_assignments(),receiver_manager.binding_status(),
                       tle_state,overrides,rows,now,hours,scheduler)
        return dict(base,status="ok" if data["candidate_count"] else "no_passes",scheduler_mode=scheduler,
                    history_status=historical_status,history_completed=len(rows),
                    tle={k:{"valid":tle_state[k].get("valid"),"stale":tle_state[k].get("stale"),
                            "age_hours":tle_state[k].get("age_hours")} for k in ("weather","iss_voice")},**data)
    except (OSError,ValueError,TypeError,KeyError,AttributeError,RuntimeError):
        return dict(base,status="unavailable",reason="Planner or receiver observations could not be read safely.")


def model_evidence(data):
    result=dict(data)
    result["passes"]=data.get("passes",[])[:MODEL_LIMIT]
    result["model_pass_limit"]=MODEL_LIMIT
    result["model_scope"]="First six chronological displayed passes plus best geometry across all unflagged candidates."
    return result
