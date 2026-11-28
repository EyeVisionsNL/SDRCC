"""Compare bounded historical reception windows without touching the collector."""
import time
from core import local_ai_reception as reception

MIN_COVERAGE = 50
MIN_METRIC_SAMPLES = 60
METRICS = ("targets", "rate", "range_nm")


def compare(current, baseline, service, metric):
    a = current.get(service, {})
    b = baseline.get(service, {})
    x = a.get(metric, {})
    y = b.get(metric, {})
    result = {"current_mean": x.get("mean"), "baseline_mean": y.get("mean"),
              "current_peak": x.get("peak"), "baseline_peak": y.get("peak"),
              "current_valid_samples": x.get("valid_samples", 0),
              "baseline_valid_samples": y.get("valid_samples", 0),
              "change_pct": None, "status": "insufficient"}
    # Require adequate wall-clock coverage and metric coverage of active samples
    # in both windows. Inactive minutes are never inserted as zero.
    for period, row, value in ((current,a,x),(baseline,b,y)):
        active = row.get("active_samples")
        n = value.get("valid_samples",0)
        if (period.get("status") != "ok" or (period.get("coverage_pct") or 0) < MIN_COVERAGE
                or not active or n < MIN_METRIC_SAMPLES or n < active*0.5
                or value.get("mean") is None):
            return result
    if current.get("latest_sample_stale"):
        result["status"] = "stale"
        return result
    if y["mean"] == 0:
        result["status"] = "zero_baseline"
        return result
    delta = round(100*(x["mean"]-y["mean"])/y["mean"],1)
    result.update(change_pct=delta,status="above" if delta >= 10 else "below" if delta <= -10 else "similar")
    return result


def window_summary(value):
    return {key:value.get(key) for key in ("status","window_start_utc","window_end_utc","samples",
                                            "expected_samples","coverage_pct","latest_sample_stale")}


def snapshot(root, *, now=None):
    end = int(time.time() if now is None else now)
    current = reception.read_evidence(root,"24h",now=end)
    baseline = reception.read_evidence(root,"7d",now=end-86400)
    services = {}
    for service in ("ais","adsb"):
        a,b=current.get(service,{}),baseline.get(service,{})
        services[service] = {
            "current_active_samples":a.get("active_samples"),
            "baseline_active_samples":b.get("active_samples"),
            "current_inactive_samples":a.get("inactive_samples"),
            "baseline_inactive_samples":b.get("inactive_samples"),
            "metrics":{key:compare(current,baseline,service,key) for key in METRICS},
        }
    return {"kind":"reception_performance","observed_utc":reception.utc(end),
            "source":reception.SOURCE,"current":window_summary(current),"baseline":window_summary(baseline),
            "status":"ok" if any(m["change_pct"] is not None for s in services.values() for m in s["metrics"].values()) else "insufficient",
            "services":services,
            "scope":"Last 24h versus preceding 7 days, non-overlapping. Means of valid active samples; range is sampled maximum in NM. Changes >=10% are descriptive, not fault detection. Traffic, receiver scheduling, propagation and RF configuration can differ. Minimum 50% nominal window coverage and 60 valid samples plus 50% of active samples per metric. No comparison to a zero baseline."}
