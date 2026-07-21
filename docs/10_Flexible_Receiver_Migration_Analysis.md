# Flexible Receiver Migration Analysis

## Scope

This analysis covers the current SDRCC receiver, mission, scheduler, automation and dashboard architecture as supplied in the Epic 1 analysis package.

No code changes are included.

## Executive conclusion

The current codebase already contains several useful building blocks for a flexible ground station:

- a dedicated Receiver Manager;
- a Mission Engine class;
- a separate scheduler;
- mission queue, diagnostics, history and result modules;
- a separate receiver monitor;
- a central event bus.

The main limitation is not the absence of these components. The main limitation is that runtime state is still modelled as one global mission and one global receiver reservation.

The safest migration path is therefore evolutionary:

1. keep Receiver Manager as the only receiver authority;
2. change Receiver Manager from one reservation to reservations per receiver;
3. make Mission Engine instances addressable by runtime ID;
4. move autopilot runtime state out of `dashboard/app.py`;
5. update API responses to expose multiple runtime slots;
6. preserve the existing single-runtime API as a compatibility layer until the new API is stable.

## Current strengths

### Receiver Manager

`core/receiver_manager.py` already owns:

- reservation;
- activation;
- release;
- receiver validation;
- persisted receiver state;
- receiver events.

This is the correct authority boundary and should remain in place.

### Mission Engine

`core/mission_engine.py` already encapsulates mission state in a `MissionEngine` class.

The class itself is reusable, but the module creates one global instance:

```python
mission_engine = MissionEngine()
```

The public helper functions all operate on that singleton.

### Scheduler

`core/mission_scheduler.py` is relatively isolated and primarily performs:

- pass discovery;
- phase calculation;
- scheduler mode persistence;
- observer status;
- preflight invocation.

It is not yet a multi-runtime scheduler, but it does not directly execute SatDump.

### Mission support modules

The following modules are already suitably separated:

- `mission_history.py`
- `mission_result.py`
- `mission_diagnostics.py`
- `mission_queue.py`
- `receiver_monitor.py`
- `event_bus.py`
- `live_rf.py`

Some contain global state files, but their responsibilities are clear enough to extend without replacing them.

## Single-runtime assumptions

### Receiver Manager

The persisted state contains exactly one field:

```json
{
  "reservation": null,
  "last_release": null
}
```

Consequences:

- reserving SDR1 blocks SDR2 as well;
- only one mission key can exist;
- `available` describes the whole station instead of a receiver;
- one `last_release` record exists for all receivers.

This is the first architectural bottleneck.

### Mission Engine

The module exposes one global engine and one active job.

Consequences:

- only one active mission job can exist;
- state changes are station-wide;
- reset and cancel are station-wide;
- the helper API has no runtime or receiver identifier;
- mission status is singular.

### Dashboard autopilot

`dashboard/app.py` contains one global `autopilot_runtime` dictionary and one autopilot worker.

That dictionary stores:

- selected pass;
- pass key;
- preparation state;
- lock state;
- recording state;
- process handle;
- stop request;
- service restoration state;
- recording metadata.

This is execution state and does not belong in the Flask application module long-term.

### Virtual mission runtime

`dashboard/app.py` also contains one global `virtual_mission_runtime`.

It is separate from the real mission runtime but still singleton state.

### Mission operations

`core/mission_operations.py` combines one Mission Engine status, one Receiver Manager status and one Scheduler status into one snapshot.

This aggregator will need a multi-runtime response model.

### Preflight

`core/mission_preflight.py` reads the global Mission Engine status and the global Receiver Manager status.

Preflight must eventually receive a target receiver and runtime ID explicitly.

## Migration principles

- Do not introduce a second Receiver Manager.
- Do not duplicate Mission Engine logic for SDR1 and SDR2.
- Do not make SDR1 and SDR2 separate hard-coded code paths.
- Use runtime identifiers and receiver identifiers as data.
- Preserve historical mission storage unless a schema change is required.
- Add compatibility adapters before removing old endpoints.
- Keep service handover and receiver release transactional.
- A runtime may reserve one receiver; a receiver may have at most one active reservation.
- Two runtimes may execute concurrently only when they use different receivers.
