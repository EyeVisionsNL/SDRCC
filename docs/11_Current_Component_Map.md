# Current Component Map

## Top-level execution flow

```text
Pass calculation
    |
    v
Mission Scheduler
    |
    v
Automation Controller
    |
    v
dashboard/app.py autopilot worker
    |
    +--> Mission Preflight
    |
    +--> Receiver Manager
    |
    +--> service handover / process control
    |
    +--> SatDump
    |
    +--> Mission Engine
    |
    +--> Live RF / diagnostics / history / result
```

## Component responsibilities

### `core/receiver_manager.py`

Current responsibility:

- central runtime reservation state;
- reserve, activate and release a receiver;
- persist reservation state;
- publish receiver events.

Current limitation:

- only one station-wide reservation.

Recommended future responsibility:

- one central registry containing reservation state per receiver.

### `core/mission_engine.py`

Current responsibility:

- mission state machine;
- active mission job;
- mission progress;
- mission result completion;
- history append;
- mission events.

Current limitation:

- one global singleton instance.

Recommended future responsibility:

- reusable Mission Engine class;
- instances managed by a runtime registry.

### `core/mission_scheduler.py`

Current responsibility:

- scheduler mode;
- upcoming pass serialization;
- observer phase;
- automatic preflight trigger.

Current limitation:

- selects one next pass;
- does not allocate multiple receivers;
- preflight is not target-specific.

Recommended future responsibility:

- planning only;
- produce candidate missions for a separate allocator.

### `core/automation_controller.py`

Current responsibility:

- controller status;
- dry-run;
- manual override;
- skipped passes;
- event publication.

Current limitation:

- one controller state.

Recommended future responsibility:

- either station-wide policy plus per-runtime execution status, or a thin facade over the runtime registry.

### `core/mission_queue.py`

Current responsibility:

- build queue;
- persist queue item overrides;
- evaluate conflicts;
- combine pass and receiver information.

Current limitation:

- reads one Receiver Manager status.

Recommended future responsibility:

- show allocation eligibility per receiver and runtime.

### `core/mission_preflight.py`

Current responsibility:

- validate mission readiness.

Current limitation:

- reads global mission and receiver state;
- uses the dynamically configured weather receiver.

Recommended future responsibility:

```python
run_preflight(runtime_id, receiver_id, mission_definition)
```

### `core/satdump.py`

Current responsibility:

- build recording command;
- service handover;
- start recording;
- inspect result;
- decode CADU products.

Current limitation:

- active mission context is obtained indirectly;
- weather receiver selection is configuration-driven;
- command execution is not runtime-scoped.

Recommended future responsibility:

- remain the SatDump adapter;
- accept explicit runtime, receiver and mission context.

### `core/live_rf.py`

Current responsibility:

- persist one live RF state;
- parse SNR and decoder output;
- report recording status.

Current limitation:

- one global state file and one global in-memory state.

Recommended future responsibility:

- state indexed by runtime ID.

### `dashboard/app.py`

Current responsibility:

- Flask routes;
- service controls;
- mission worker;
- autopilot worker;
- process monitoring;
- runtime globals;
- mission status assembly;
- receiver configuration;
- history and media endpoints.

Current limitation:

- web layer and execution layer are coupled;
- one autopilot runtime;
- one process handle;
- one stop flag.

Recommended future responsibility:

- HTTP/API adapter only;
- runtime execution moved into `core/mission_runtime.py` or equivalent.

## Persisted state files affected

Likely affected by Epic 1:

- `data/state/receiver_manager.json`
- `data/state/mission_scheduler.json`
- `data/state/mission_history.json`
- live RF state file
- queue state file

Suggested new state model:

```text
receiver_manager.json
mission_runtimes.json
mission_scheduler.json
mission_queue.json
live_rf/<runtime_id>.json
```

## Authority boundaries

```text
Receiver Manager
    owns physical receiver reservations

Runtime Registry
    owns runtime instances and their lifecycle

Mission Engine
    owns mission state for one runtime

Scheduler
    owns planning and timing

Allocator
    decides which eligible receiver a planned mission may use

SatDump adapter
    owns command construction and process-specific decode interaction

Dashboard
    exposes state and commands through HTTP
```
