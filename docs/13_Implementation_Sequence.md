# Epic 1 Implementation Sequence

## Strategy

The migration should be completed in small compatibility-preserving versions.

No UI redesign is required in the first stages.

## Phase A – Analysis baseline

Status: Completed by this package

Deliverables:

- architecture map;
- single-runtime inventory;
- risk register;
- migration sequence.

No code changes.

## Phase B – Receiver Manager multi-reservation foundation

Goal:

Allow SDR1 and SDR2 to be reserved independently while keeping Receiver Manager as sole authority.

Changes:

- replace singular `reservation` with `reservations`;
- key reservations by receiver ID;
- track `last_release` per receiver;
- add `get_receiver_status(receiver_id)`;
- make `available` receiver-specific;
- retain compatibility fields for existing consumers.

Validation:

- reserve SDR1;
- verify SDR2 remains available;
- reserve SDR2 with a different mission key;
- reject second reservation of SDR1;
- release SDR1 without affecting SDR2;
- restart service and verify persisted state.

This should be the first code package.

## Phase C – Runtime Registry foundation

Goal:

Create one runtime registry with reusable Mission Engine instances.

Proposed module:

```text
core/mission_runtime.py
```

Responsibilities:

- create/get/list runtime;
- bind runtime to receiver;
- own Mission Engine instance;
- hold process handle and stop flag;
- runtime lock;
- lifecycle status.

No parallel SatDump execution yet.

Validation:

- create runtime for SDR1;
- create runtime for SDR2;
- transition states independently;
- stop/reset one runtime without affecting the other.

## Phase D – Mission Engine API scoping

Goal:

Remove internal dependence on the module singleton.

Changes:

- public functions accept `runtime_id`, or call the runtime registry;
- existing singular helpers remain as compatibility wrappers;
- events include runtime and receiver context.

Validation:

- existing Mission Engine API still works;
- new runtime API returns two independent states.

## Phase E – Move autopilot execution out of Flask

Goal:

Remove `autopilot_runtime` and worker ownership from `dashboard/app.py`.

Proposed module:

```text
core/mission_executor.py
```

Responsibilities:

- preflight;
- prepare;
- lock;
- record;
- decode;
- archive;
- cancellation;
- service restoration;
- receiver release.

Validation:

- current single METEOR flow works unchanged;
- Flask restart does not create duplicate worker logic;
- stop operation targets the correct runtime.

## Phase F – Runtime-scoped SatDump and Live RF

Goal:

Permit process and telemetry separation.

Changes:

- SatDump receives explicit mission context;
- Live RF state keyed by runtime ID;
- process monitors bound to runtime;
- output paths remain mission-specific.

Validation:

- two simulated missions produce separate telemetry;
- no log-line crossover;
- stop one process only.

## Phase G – Scheduler allocation

Goal:

Separate planning from allocation.

Add:

```text
core/receiver_allocator.py
```

Responsibilities:

- evaluate capabilities;
- select eligible receiver;
- call Receiver Manager atomically;
- report allocation conflicts.

Validation:

- two non-conflicting missions allocate two receivers;
- conflicting missions are ordered or rejected predictably;
- default receiver roles restore after release.

## Phase H – API v2

Suggested endpoints:

```text
GET  /api/mission-runtimes
GET  /api/mission-runtimes/<runtime_id>
POST /api/mission-runtimes/<runtime_id>/stop
POST /api/mission-runtimes/<runtime_id>/reset

GET  /api/receivers
GET  /api/receivers/<receiver_id>
POST /api/receivers/<receiver_id>/reserve
POST /api/receivers/<receiver_id>/release
```

Compatibility:

- keep `/api/mission-engine`;
- keep `/api/receiver-manager`;
- map old responses to the primary runtime during transition.

## Phase I – Mission Control UI

Only after backend validation:

- Mission SDR1 panel;
- Mission SDR2 panel;
- independent stop and status;
- shared queue and scheduler;
- diagnostics moved to System;
- no unrelated layout changes.

## Immediate next development package

The next package should implement only:

**Receiver Manager multi-reservation foundation**

It should not yet modify Mission Engine, scheduler or UI layout.

Expected files:

```text
core/receiver_manager.py
core/mission_queue.py              only if compatibility requires it
core/mission_operations.py         only if compatibility requires it
dashboard/app.py                   API compatibility only if required
tests or validation script
install.sh
rollback.sh
CHANGELOG
```

Commit only after:

1. idle validation;
2. API validation;
3. receiver reservation conflict tests;
4. service restart test;
5. user approval.
