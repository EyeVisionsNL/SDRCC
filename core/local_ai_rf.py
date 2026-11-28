"""Operator-recorded RF comparisons. No RF control or background inference."""
from contextlib import closing
import json
import sqlite3
import time
from core import local_ai_reception as reception, local_ai_memory as memory
from core import local_ai_performance as performance

PERIODS=("24h","7d")
SERVICES=("ais","adsb")
CATEGORIES=("antenna","lna","splitter","gain","filter","cable","other")
GAP=900
MAX_EXPERIMENTS=100
MIN_COVERAGE=75
TABLE="rf_experiments"
SCHEMA="""CREATE TABLE IF NOT EXISTS rf_experiments(
 id INTEGER PRIMARY KEY AUTOINCREMENT, changed INTEGER NOT NULL,
 service TEXT NOT NULL, category TEXT NOT NULL, title TEXT NOT NULL,
 details TEXT NOT NULL, period TEXT NOT NULL, baseline TEXT NOT NULL,
 final TEXT, note_id INTEGER NOT NULL)"""
SCOPE=("Equal 24h or 7d before/after windows, excluding 15 minutes on either side of the recorded change. "
       "Active valid samples only; require 75% nominal coverage, 75% active samples and 75% valid metric coverage "
       "in each window, no stale endpoints, and nonzero baseline. Recorded intervening changes for the same "
       "service suppress percentage comparisons. Targets are simultaneous counts; range is sampled maximum in NM. "
       "Traffic, propagation, scheduling and unrecorded changes can differ. Observational comparison, not causal proof.")


def window(data, service):
    return {**{k:data.get(k) for k in ("status","reason","window_start_utc","window_end_utc","samples",
                                      "expected_samples","coverage_pct","latest_sample_stale")},
            service:data.get(service,{})}


def decode(row):
    return {"id":row[0],"changed":row[1],"service":row[2],"category":row[3],"title":row[4],
            "details":row[5],"period":row[6],"baseline":json.loads(row[7]),
            "final":json.loads(row[8]) if row[8] is not None else None,"note_id":row[9]}


def read_all(root):
    path=root/memory.SOURCE
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=.3)) as db:
        db.execute("PRAGMA query_only=ON")
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(TABLE,)).fetchone():
            return []
        rows=db.execute("SELECT id,changed,service,category,title,details,period,baseline,final,note_id FROM rf_experiments ORDER BY changed DESC,id DESC LIMIT ?",(MAX_EXPERIMENTS+1,)).fetchall()
        if len(rows)>MAX_EXPERIMENTS:
            raise ValueError("RF experiment capacity exceeded.")
        return [decode(row) for row in rows]


def record(root, body, *, now=None):
    service,category,period=body.get("service"),body.get("category"),body.get("period")
    if service not in SERVICES or category not in CATEGORIES or period not in PERIODS:
        raise ValueError("Invalid RF experiment selection.")
    title=memory.validated_text(body.get("title"),80,True)
    details=memory.validated_text(body.get("details",""),350)
    changed=int(time.time() if now is None else now)
    baseline=window(reception.read_evidence(root,period,now=changed-GAP),service)
    # Atomic with a Station Memory entry. No partial experiment if memory is full.
    with closing(memory.connect_write(root)) as db,db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(SCHEMA)
        if db.execute("SELECT COUNT(*) FROM rf_experiments").fetchone()[0]>=MAX_EXPERIMENTS:
            raise ValueError("RF experiment capacity reached.")
        memory.insert(db,(changed,"configuration" if category=="gain" else "hardware",
                          "RF: "+title, f"{service.upper()} / {category} / {period}. "+details,
                          "Operator recorded change; outcome not yet measured.","rf_optimization",None))
        note_id=db.execute("SELECT last_insert_rowid()").fetchone()[0]
        cursor=db.execute("INSERT INTO rf_experiments(changed,service,category,title,details,period,baseline,note_id) VALUES(?,?,?,?,?,?,?,?)",
                          (changed,service,category,title,details,period,json.dumps(baseline,allow_nan=False),note_id))
        return cursor.lastrowid


def comparison(after,before,service,metric,overlap):
    result=performance.compare(after,before,service,metric)
    for w in (before,after):
        active=w.get(service,{}).get("active_samples")
        valid=w.get(service,{}).get(metric,{}).get("valid_samples",0)
        expected=w.get("expected_samples") or 0
        if (w.get("status")!="ok" or (w.get("coverage_pct") or 0)<MIN_COVERAGE
                or not expected or not active or active<expected*.75 or valid<active*.75
                or w.get("latest_sample_stale") is not False):
            result.update(status="insufficient",change_pct=None)
            break
    if overlap:
        result.update(status="intervening_change",change_pct=None)
    return result


def bounds(row):
    span=reception.WINDOWS[row["period"]]
    changed=row["changed"]
    return changed-GAP-span,changed-GAP,changed+GAP,changed+GAP+span


def evaluate(root,row,rows,now):
    start,before_end,after_start,end=bounds(row)
    base={k:row[k] for k in ("id","service","category","title","details","period","note_id")}
    base.update(changed_utc=reception.utc(row["changed"]),after_start_utc=reception.utc(after_start),
                after_end_utc=reception.utc(end),before=row["baseline"],after=None,metrics={},
                remaining_seconds=max(0,end-int(now)),saved=False)
    if row["final"] is not None:
        return base | row["final"] | {"saved":True,"remaining_seconds":0}
    if now<end:
        return dict(base,status="measuring")
    after=window(reception.read_evidence(root,row["period"],now=end),row["service"])
    overlaps=sum(other["id"]!=row["id"] and other["service"]==row["service"]
                 and start<other["changed"]<=end for other in rows)
    metrics={m:comparison(after,row["baseline"],row["service"],m,overlaps) for m in performance.METRICS}
    return dict(base,status="ready" if any(m["change_pct"] is not None for m in metrics.values()) else "insufficient",
                after=after,metrics=metrics,intervening_changes=overlaps)


def snapshot(root, experiment_id=0, *, now=None):
    now=time.time() if now is None else now
    if type(experiment_id) is not int or experiment_id<0:
        raise ValueError("Invalid RF experiment ID.")
    base={"kind":"rf_optimization","observed_utc":reception.utc(now),"scope":SCOPE,
          "source":reception.SOURCE,"capacity":MAX_EXPERIMENTS}
    try:
        rows=read_all(root)
        choices=[{"id":r["id"],"title":r["title"],"service":r["service"],"changed_utc":reception.utc(r["changed"]),
                  "saved":r["final"] is not None} for r in rows]
        selected=next((r for r in rows if r["id"]==experiment_id),None) if experiment_id else (rows[0] if rows else None)
        return dict(base,status="ok" if selected else "empty" if not rows else "not_found",
                    experiments=choices,experiment=evaluate(root,selected,rows,now) if selected else None)
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,OverflowError):
        return dict(base,status="unavailable",reason="RF experiment storage could not be read.",experiments=[],experiment=None)


def finalize(root,experiment_id,*,now=None):
    if type(experiment_id) is not int or experiment_id<1:
        raise ValueError("Invalid RF experiment ID.")
    now=time.time() if now is None else now
    rows=read_all(root)
    row=next((r for r in rows if r["id"]==experiment_id),None)
    if row is None:
        raise ValueError("RF experiment not found.")
    if row["final"] is not None:
        return
    result=evaluate(root,row,rows,now)
    if result["status"]=="measuring":
        raise ValueError("Measurement window has not finished.")
    result["saved_utc"]=reception.utc(now)
    with closing(memory.connect_write(root)) as db,db:
        db.execute("BEGIN IMMEDIATE")
        changed=db.execute("UPDATE rf_experiments SET final=? WHERE id=? AND final IS NULL",
                           (json.dumps(result,allow_nan=False),experiment_id)).rowcount
        if changed:
            # The linked operator note may have been explicitly deleted.
            summary="; ".join(f"{k}: {v['change_pct']:+.1f}%" if v["change_pct"] is not None else f"{k}: {v['status']}" for k,v in result["metrics"].items())
            db.execute("UPDATE entries SET outcome=? WHERE id=? AND source='rf_optimization'",
                       (("Observed changes, not causal proof: "+summary)[:300],row["note_id"]))


def delete(root,experiment_id):
    if type(experiment_id) is not int or experiment_id<1:
        raise ValueError("Invalid RF experiment ID.")
    path=root/memory.SOURCE
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=rw",uri=True,timeout=.5)) as db,db:
        if db.execute("DELETE FROM rf_experiments WHERE id=?",(experiment_id,)).rowcount!=1:
            raise ValueError("RF experiment not found.")


def model_evidence(data):
    result=dict(data)
    result["experiment_count"]=len(result.pop("experiments",[]))
    return result
