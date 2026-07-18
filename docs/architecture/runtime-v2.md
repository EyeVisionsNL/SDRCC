# SDRCC Receiver Runtime Architecture v2

Status: **Accepted design**  
Target release line: **v0.30.1+**  
Purpose: transform SDRCC from a weather-first controller with separate Voice execution into a receiver-oriented, extensible SDR Ground Control Center.

## 1. Why this change is required

The current application has two execution paths:

- Weather missions run through `Automation Controller -> Mission Scheduler -> Mission Engine -> SatDump`.
- Voice recordings run through `Voice Schedule Executor -> Voice Receiver -> WAV`.

The current `MissionEngine` owns one global `active_job`, and the current `receiver_manager` stores one global `reservation`. These structures cannot safely represent two simultaneous missions on two different receivers. They also cause Voice activity to remain invisible to Mission Control and make the global Stop Mission action unable to stop Voice.

The v2 architecture removes those limitations without hard-coding the system to exactly two receivers.

## 2. Non-negotiable design rules

1. A receiver is a physical resource, identified by a stable receiver ID and hardware serial.
2. No receiver is permanently tied to Weather, Voice, AIS, ADS-B, 2 metre, 70 centimetre, or any future task.
3. Default role, current role, preferred mission assignment, reservation, and active mission are separate concepts.
4. There is one generic runtime instance per physical receiver.
5. The backend must support an arbitrary number of receivers. SDR1 and SDR2 are the current hardware, not architectural limits.
6. Missions on separate receivers may run simultaneously.
7. Two missions may not use the same receiver at the same time unless an explicit future sharing mode supports it.
8. Stopping or failing one receiver runtime must not stop or corrupt another runtime.
9. Mission-specific code belongs in mission adapters/plugins, not in the generic runtime manager.
10. UI cards may initially show SDR1 and SDR2, but must be generated from backend receiver data so SDR3 can be added without a backend redesign.
11. Existing Weather, AIS, ADS-B, and Voice functionality must remain operational during migration.
12. Migration must be incremental and backward compatible until old endpoints are deliberately retired.

## 3. Core concepts

### 3.1 Receiver

A receiver represents one physical SDR device.

Required identity and configuration fields:

```yaml
receivers:
  sdr1:
    number: SDR1
    serial: "05419737"
    enabled: true
    capabilities:
      - ais
      - adsb
      - weather
      - voice
      - vhf
      - uhf
  sdr2:
    number: SDR2
    serial: "24006572"
    enabled: true
    capabilities:
      - ais
      - adsb
      - weather
      - voice
      - vhf
      - uhf
```

Future receivers can add capabilities such as `two_meter`, `seventy_centimeter`, `hf`, or hardware-specific limits.

### 3.2 Roles

- **Default role**: normal background task when no mission owns the receiver, for example AIS, ADS-B, or MANUAL.
- **Current role**: task actually running now, for example VOICE or WEATHER.
- **Preferred assignment**: preferred receiver for a mission type, for example Voice prefers SDR2. This is a preference, not a permanent binding.
- **Restore role**: role to restore after mission release.
- **Pending role**: operator-requested default role change waiting until the receiver becomes available.

### 3.3 Mission

A mission is a request to perform work. It is receiver-independent until the coordinator assigns it.

Minimum mission contract:

```json
{
  "mission_id": "...",
  "mission_type": "VOICE",
  "target": "ISS (ZARYA)",
  "frequency_hz": 145800000,
  "mode": "FM",
  "start_time": "...",
  "end_time": "...",
  "preferred_receiver": "sdr2",
  "required_capabilities": ["voice", "vhf"],
  "priority": 50,
  "parameters": {}
}
```

### 3.4 Receiver Runtime

Each physical receiver has one independent runtime state machine:

```text
IDLE
  -> RESERVED
  -> PREPARING
  -> RUNNING
  -> PROCESSING        optional
  -> RESTORING
  -> IDLE
```

Failure and operator paths:

```text
PREPARING/RUNNING/PROCESSING
  -> STOPPING
  -> RESTORING
  -> IDLE

PREPARING/RUNNING/PROCESSING
  -> FAILED
  -> RESTORING
  -> IDLE
```

Runtime state must contain at least:

```json
{
  "receiver_id": "sdr2",
  "state": "RUNNING",
  "mission_id": "...",
  "mission_type": "VOICE",
  "target": "ISS (ZARYA)",
  "frequency_hz": 145800000,
  "mode": "FM",
  "started_at": "...",
  "expected_end_at": "...",
  "elapsed_seconds": 120,
  "remaining_seconds": 290,
  "processes": [],
  "reservation": {},
  "restore_role": "adsb",
  "telemetry": {},
  "error": null
}
```

### 3.5 Mission Coordinator

The coordinator assigns missions to receivers. It does not perform recording or decoding itself.

Responsibilities:

- validate mission requirements;
- select an enabled, connected, capable receiver;
- honour preferred assignment when possible;
- detect reservation, service, hardware, and timing conflicts;
- reserve the selected receiver atomically;
- start the correct mission adapter through that receiver runtime;
- expose decisions and rejection reasons;
- allow parallel missions when different receivers are selected.

The coordinator must not assume that Weather uses SDR1 or Voice uses SDR2.

### 3.6 Mission adapters/plugins

Mission-specific execution is isolated behind a shared interface.

Examples:

- Weather/METEOR adapter: SatDump recording, decoding, processing, images and RF telemetry.
- Voice adapter: `rtl_fm`, WAV writer, optional live monitor and recording metadata.
- Future 2 metre adapter: configurable FM receive/record/monitor workflow.
- Future AIS/ADS-B capture adapters where required.

Conceptual interface:

```python
class MissionAdapter:
    def prepare(self, context): ...
    def start(self, context): ...
    def status(self, context): ...
    def stop(self, context, reason): ...
    def finalize(self, context): ...
    def restore(self, context): ...
```

The generic runtime controls lifecycle and state. The adapter controls mission-specific processes and telemetry.

## 4. State model

The new persistent receiver state is keyed by receiver ID:

```json
{
  "schema_version": 2,
  "receivers": {
    "sdr1": {
      "reservation": null,
      "runtime": {
        "state": "IDLE"
      },
      "last_release": null,
      "pending_role": null
    },
    "sdr2": {
      "reservation": null,
      "runtime": {
        "state": "IDLE"
      },
      "last_release": null,
      "pending_role": null
    }
  }
}
```

All updates to reservation and runtime ownership must be atomic under one manager lock. State writes must continue to use temporary-file replacement.

### Migration from schema v1

The current single `reservation`, `last_release`, and `pending_roles` values must be migrated without discarding active or historical information:

1. Detect missing or older `schema_version`.
2. Create entries for every configured receiver.
3. Move an existing reservation into the entry named by its `receiver_id`.
4. Preserve `last_release` on the matching receiver when possible.
5. Convert pending role data into per-receiver pending roles.
6. Keep legacy summary fields in API responses during the compatibility period.
7. Never perform a destructive migration while a mission is active without a verified rollback path.

## 5. API direction

Preferred generic endpoints:

```text
GET  /api/receivers
GET  /api/receivers/{receiver_id}
GET  /api/receiver-runtimes
GET  /api/receiver-runtimes/{receiver_id}
POST /api/receiver-runtimes/{receiver_id}/stop
GET  /api/missions
POST /api/missions/{mission_id}/assign
GET  /api/coordinator
```

The stop operation is generic. The UI may label it `Stop Mission SDR1`, but the backend endpoint must not be duplicated per hard-coded receiver.

During migration, existing endpoints remain available and are backed by the new state where practical.

## 6. Parallel execution rules

Allowed:

```text
SDR1 -> METEOR Weather mission
SDR2 -> ISS Voice mission
```

Also allowed:

```text
SDR1 -> ADS-B default service
SDR2 -> AIS default service
```

Not allowed:

```text
SDR1 -> Weather mission
SDR1 -> Voice mission at the same time
```

Assignment checks must include:

- receiver exists and is connected;
- receiver is enabled;
- required capabilities match;
- no active reservation conflict exists;
- required service handover can be performed;
- serial binding is valid;
- mission timing is still valid;
- the adapter is available;
- restoration information is captured before the mission starts.

## 7. Service handover and restoration

Service handover is receiver-specific. A mission runtime records:

- services inspected;
- which services were active;
- which services were stopped;
- intended restore role;
- restoration result and error details.

Restoration must be idempotent. Repeated stop or restore requests must not start duplicate services or affect another receiver.

## 8. Mission Control design

`Latest Reception` is removed from Mission Control.

Mission Control renders one identical base card per configured receiver:

```text
Mission Status SDR1 | Mission Status SDR2 | future SDR3...
```

Each card shows common fields:

- receiver ID and serial;
- runtime state;
- current role;
- mission type and target;
- frequency and mode;
- start, elapsed and remaining time;
- current stage;
- reservation owner;
- restore role;
- runtime error;
- receiver-specific Stop Mission button.

Mission-specific telemetry is supplied as an extension block:

- Weather: SNR, frames, CADU, images and SatDump stage.
- Voice: recording state, WAV size, audio duration and monitor status.
- AIS/ADS-B: service state, messages per second, targets and range where available.

The frontend must iterate over the receiver collection rather than contain permanent `sdr1`/`sdr2` branches.

## 9. Radio Control design

Radio Control remains receiver-focused and shows:

- assignments and default roles;
- capabilities;
- active reservations;
- current role;
- restore role;
- reserved owner and exact expiry/end time;
- pending role;
- RF settings;
- live receiver monitor sourced from the same runtime state.

Active Reservations and Receiver Monitor must consume one authoritative runtime/reservation model to prevent contradictory displays such as `Reserved by ISS` together with `Task: Free`.

## 10. System tab

A new `System` tab receives technical and administrative components:

- CPU, RAM, disk, temperature and uptime;
- Mission Event Center;
- event timeline;
- service and process status;
- Automation Controller/coordinator diagnostics;
- advanced controls and diagnostics;
- other system-level information agreed during UI review.

Mission Control remains operational rather than administrative.

## 11. Automation Controller review

The current Automation Controller is weather/pass oriented. It must be reviewed before reuse.

Its future responsibility is limited to automation policy and candidate selection. Receiver selection and lifecycle execution belong to the coordinator and runtimes.

The review must classify every current field and action as one of:

- keep in automation policy;
- move to Mission Coordinator;
- move to Receiver Runtime;
- move to System diagnostics;
- remove as obsolete.

No old Automation Controller component is removed until the Weather flow is proven through the new runtime.

## 12. Mission history

All mission adapters write to one common mission-history contract with shared fields and optional mission-specific metadata.

Common fields include:

- mission ID and type;
- receiver ID and serial;
- target;
- frequency/mode;
- planned and actual start/end;
- result;
- stop/failure reason;
- files;
- restoration result.

Weather and Voice continue to expose their own useful metadata without forcing irrelevant fields onto other mission types.

## 13. Stop semantics

A stop request is scoped to one receiver runtime.

The runtime must:

1. mark the stop request and reason;
2. stop only processes owned by that runtime;
3. finalize partial output where possible;
4. restore only that receiver's prior service/role;
5. write history/result;
6. return to IDLE;
7. leave other receiver runtimes untouched.

## 14. Incremental migration plan

### v0.30.1a — Architecture and contracts

- commit this design and workflow documentation;
- define schema and compatibility requirements;
- no production behavior change.

### v0.30.1b — Multi-receiver state

- schema v2 receiver state;
- per-receiver reservations and pending roles;
- safe migration and legacy API summaries;
- isolated tests using the complete project import context.

### v0.30.1c — Receiver Runtime Manager

- generic runtime objects keyed by receiver ID;
- runtime status API;
- generic receiver-scoped stop contract;
- no mission adapter migration yet.

### v0.30.1d — Voice adapter migration

- Voice execution through the assigned receiver runtime;
- proper runtime telemetry, stop and restoration;
- preserve WAV playback/download.

### v0.30.1e — Weather adapter migration

- existing Mission Engine/SatDump flow wrapped or adapted into a receiver runtime;
- no regression to scheduling, RF telemetry, processing, history or images.

### v0.30.1f — Mission Coordinator

- assignment and conflict decisions;
- preferred receiver plus capability-based fallback;
- parallel assignment support.

### v0.30.1g — Dynamic Mission Control

- one card per receiver;
- remove Latest Reception;
- receiver-scoped stop actions;
- mission-specific telemetry extensions.

### v0.30.1h — Radio Control consistency

- one authoritative reservation/runtime source;
- correct exact reservation times;
- correct Receiver Monitor task and runtime data.

### v0.30.1i — System tab and controller cleanup

- move CPU/system statistics and Mission Event Center;
- review and simplify Automation Controller;
- move technical diagnostics and advanced controls.

### v0.30.1j — Parallel validation

- simultaneous Weather and Voice test on separate receivers;
- independent stop test for each receiver;
- restoration and service recovery test;
- history and UI validation;
- final commit/push only after acceptance.

## 15. Acceptance criteria

The architecture migration is complete only when all of these are true:

- SDR1 and SDR2 can exchange default and mission roles without code changes.
- Weather and Voice can run simultaneously on different receivers.
- Either mission can be stopped independently.
- A stopped/failed mission restores only its own receiver.
- Mission Control shows real runtime status for each receiver.
- Active Reservations and Receiver Monitor agree at all times.
- Voice and Weather both appear correctly in history.
- Existing AIS and ADS-B services return to the correct configured receivers.
- Adding SDR3 requires configuration and UI rendering, not a redesign of the runtime manager.
- Adding a 2 metre mission requires a capability and adapter, not a second hard-coded engine.

## 16. Explicitly rejected approaches

- Two copied engines named `Engine SDR1` and `Engine SDR2`.
- Hard-coded Weather-to-SDR1 or Voice-to-SDR2 logic.
- One global reservation with receiver metadata inside it.
- A global Stop Mission action that kills all SDR activity.
- Separate, contradictory reservation and monitor state sources.
- Large one-shot migration that replaces all working flows before intermediate validation.
