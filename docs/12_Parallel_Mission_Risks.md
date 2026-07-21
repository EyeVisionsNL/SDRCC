# Parallel Mission Risks

## Critical risks

### 1. Global receiver reservation

Severity: Critical

Current behaviour allows only one reservation for the entire station.

Required control:

- reservations keyed by receiver ID;
- atomic reserve operation under one lock;
- reject only conflicts on the same receiver.

### 2. Global Mission Engine singleton

Severity: Critical

Two workers would mutate the same state and active job.

Required control:

- runtime registry;
- one Mission Engine instance per runtime;
- no global helper call without a runtime ID.

### 3. Global autopilot runtime dictionary

Severity: Critical

Two mission workers would overwrite:

- pass key;
- process;
- stop flag;
- preparation state;
- restoration state.

Required control:

- runtime object with its own lock;
- process handle stored per runtime;
- stop operation addressed by runtime ID.

### 4. Service handover collisions

Severity: High

Two missions may attempt to stop or restore the same default service.

Required control:

- service ownership token;
- restoration only by the runtime that performed the handover;
- ref-counting or explicit receiver/service ownership;
- do not restore while another runtime still needs the service stopped.

### 5. Shared Live RF state

Severity: High

Output from two SatDump processes could be mixed.

Required control:

- Live RF state per runtime;
- parser callbacks bound to one process;
- API selects runtime explicitly.

### 6. Non-targeted stop/reset API

Severity: High

A station-wide stop could terminate the wrong mission.

Required control:

```text
POST /api/mission-runtimes/<runtime_id>/stop
POST /api/mission-runtimes/<runtime_id>/reset
```

Keep the old endpoint temporarily only when exactly one runtime is active.

### 7. History write concurrency

Severity: Medium to High

Multiple mission completions may write the same history JSON file concurrently.

Required control:

- shared history file lock;
- atomic read-modify-write;
- preferably one history repository component.

### 8. Mission ID collisions

Severity: Low

Microsecond timestamps make collisions unlikely, but runtime identity should still be explicit.

Required control:

- UUID or runtime-prefixed mission ID;
- never use receiver ID alone as mission ID.

### 9. Scheduler double allocation

Severity: High

Two candidate missions may select the same receiver before either reservation is persisted.

Required control:

- allocation and reservation must be one atomic operation;
- scheduler cannot assume availability from a stale snapshot.

### 10. Backwards compatibility

Severity: Medium

Existing JavaScript expects singular mission fields.

Required control:

- add a new multi-runtime payload;
- retain singular compatibility fields while the UI migrates;
- remove compatibility only in a later version.

## Safe concurrency rules

1. Each receiver has zero or one reservation.
2. Each runtime has zero or one receiver.
3. Each runtime has zero or one active process.
4. A runtime may release only its own reservation.
5. A service restoration action belongs to the runtime that stopped it.
6. History writes use a global repository lock.
7. Events include both `runtime_id` and `receiver_id`.
8. Stop, reset and status operations are runtime-addressed.
9. Scheduler decisions are advisory until Receiver Manager confirms reservation.
10. UI never infers runtime identity from panel position alone.

## Rollback requirements

Every implementation package in Epic 1 should include:

- backup of changed files;
- syntax validation before restart;
- restore script;
- service restart;
- API smoke test;
- receiver state validation;
- no automatic Git commit.
