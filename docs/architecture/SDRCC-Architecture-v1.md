# SDRCC Architecture v1

Status: foundation document for v0.35.x  
Scope: flexible receivers, receiver-bound missions, Mission History, Analytics and Images.

## Design principles

1. **Receiver-first** — a physical receiver is the primary constrained resource.
2. **Mission-centric** — runtime, telemetry, products, diagnostics and results remain linked to one mission identity.
3. **Single ownership** — each mutable state has one authoritative owner.
4. **Receiver-bound operations** — start and stop commands always identify the receiver concerned.
5. **Plugin-ready** — METEOR, ISS and future mission types must use a common operations contract.
6. **Scheduler separation** — AUTO, MANUAL and PAUSED are global Mission Scheduler modes, not receiver modes.
7. **Historical integrity** — Mission History, Analytics and Images consume persisted mission results and must never infer ownership from a global active job.
8. **Backwards compatibility** — existing APIs remain available until their callers are migrated and tested.
9. **Small stable releases** — each architectural step is independently installable and reversible.

## Current functional components

- Mission Queue: planned passes, priority and skip state.
- Mission Scheduler: global AUTO, MANUAL and PAUSED planning mode.
- Mission Engine: current production mission lifecycle.
- Mission Simulator: deterministic hardware-free mission scenarios.
- Receiver Manager: receiver inventory, roles and reservations.
- Mission Operations snapshot: read-only combined dashboard state.
- Mission History: persisted completed, failed and cancelled missions.
- Analytics: mission quality and performance views.
- Images: products linked to completed missions.
- Radio / Receiver Monitor: physical receiver and service status.
- System / Advanced: maintenance, diagnostics and developer actions.

## Ownership matrix

| State or responsibility | Authoritative owner | Consumers |
|---|---|---|
| Physical receiver inventory | Receiver Manager | Operations, UI, plugins |
| Receiver reservation | Receiver Manager | Operations, Scheduler, UI |
| Queue order, priority and skip | Mission Queue | Scheduler, UI |
| Scheduler mode | Mission Scheduler | Automation, UI |
| Production mission lifecycle | Mission Engine | Operations, History, UI |
| Simulation lifecycle | Mission Simulator | Operations, UI |
| Live RF telemetry | Live RF | UI, History, Analytics |
| Persisted mission result | Mission History/result layer | History, Analytics, Images |
| Receiver-bound operator command | Mission Operations | Engine, Simulator, future plugins |

No consumer may silently become a second owner of the same state.

## Receiver runtime target model

Each receiver will ultimately expose an independent runtime context:

```yaml
receiver_id: sdr1
hardware_serial: "05419737"
base_role: ais
reservation:
  mission_id: null
  mission_type: null
runtime:
  active: false
  state: idle
  operator: null
restore:
  role: ais
```

SDR1 and SDR2 must be able to hold different runtime contexts simultaneously. v0.35.0a does **not** yet enable concurrent Mission Engine jobs; it establishes receiver-bound stop semantics and UI separation as the first migration step.

## Mission identity and persisted data

Every mission must retain the same `mission_id` across:

- receiver reservation;
- plugin/runtime state;
- events and telemetry;
- recording and decoder output;
- diagnostics;
- Mission History;
- Analytics;
- Images.

At minimum a persisted mission record must identify:

```yaml
mission_id: unique
receiver_id: sdr1
receiver_serial: "05419737"
mission_type: meteor
plugin: satdump
started_at: timestamp
ended_at: timestamp
result: success
```

## Mission Operations contract

The UI issues receiver-bound commands. It must not decide which runtime implementation is active.

Initial endpoint introduced in v0.35.0a:

```text
POST /api/mission-operations/stop
{"receiver_id":"sdr1"}
```

The backend dispatches to the active runtime and rejects a receiver mismatch. The legacy global `/api/mission/stop` remains for compatibility.

Target operations contract for later v0.35.x releases:

```text
GET  /api/mission-operations
POST /api/mission-operations/start
POST /api/mission-operations/stop
POST /api/mission-operations/pause
POST /api/mission-operations/resume
```

## UI architecture

Mission Operations is divided into explicit sections:

- **Mission Scheduler** — AUTO, MANUAL and PAUSE; applies to planning for all receivers.
- **Receiver Mission Control** — independent Stop SDR1 and Stop SDR2 controls.
- **System** — Update TLE and future maintenance actions.
- **Advanced** — simulator, reset and diagnostics.

`Next Mission` is removed from this panel because queue skip/priority actions already own that workflow. `Record Now` is removed because it bypasses the Queue → Scheduler → Operations flow.

## History, Analytics and Images

These tabs are first-class architecture components:

- History is the authoritative view of persisted mission outcomes.
- Analytics calculates from persisted mission records, never transient global UI state.
- Images links products through `mission_id` and output inventory.
- Concurrent missions must never exchange telemetry or products.

## Migration roadmap

1. v0.35.0a — receiver-bound stop API, scheduler/UI separation, architecture baseline.
2. v0.35.1 — explicit per-receiver runtime snapshot without changing existing owners.
3. v0.35.2 — operations adapter contract for Mission Engine and Simulator.
4. v0.35.3 — History/Analytics/Images audit for mission and receiver identity.
5. v0.35.4 — multi-runtime groundwork; remove remaining global-active assumptions.
6. v0.36.x — first ISS plugin using the common operations contract.
