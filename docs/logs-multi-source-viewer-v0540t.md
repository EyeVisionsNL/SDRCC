# SDRCC v0.54.0t — Multi-source Logs Viewer

## Tab audit

| Area | Finding |
| --- | --- |
| Goal | Read-only technical diagnostics for SDRCC and receiver services. |
| Navigation | Existing final `Logs` tab; tab ordering is intentionally unchanged in this release. |
| Existing UI | One unfiltered `<pre>` showing the newest 120 lines from `logs/sdrcc.log`. |
| Existing JavaScript | The global five-second dashboard poll rewrote the log on every tab. |
| Existing API | `/api/status` included SDRCC log lines. |
| Backend authority | `logs/sdrcc.log` remains the SDRCC log; systemd-journald remains authoritative for AIS-Catcher and readsb. |
| Overlap | The Live Event Timeline remains a separate structured operational event view sourced from `/api/events`. |
| Duplication decision | No event data, service control or journal storage is copied. Logs only projects existing sources. |

## Release boundary

- Adds the fixed sources `sdrcc`, `ais` and `adsb` to `/api/logs`.
- Maps AIS only to `ais-catcher.service` and ADS-B only to `readsb.service`.
- Rejects unknown source IDs; caller-provided systemd unit names are never executed.
- Reads at most 500 lines and uses a four-second journal timeout.
- Adds source buttons, client-side search, manual refresh, line count and update state.
- Polls the selected source every five seconds only while the Logs tab is visible.
- Keeps `/api/status` backward compatible. The dashboard itself requests
  `include_logs=0`, avoiding the legacy file read when Logs is closed.

## Authority and lifecycle

`core/log_sources.py` is explicitly observer-only. It does not start, stop,
restart, enable or disable any service. AIS-Catcher Control is not a normal
receiver log source and is not exposed on this page.

## Unchanged

- Service lifecycle and Mission Handover.
- Receiver Registry, Receiver Manager and receiver authority.
- Mission Engine, scheduler, recordings and result history.
- Event Timeline categories and `/api/events`.
- Tab order and top banner; these are reviewed after Logs as a separate step.
