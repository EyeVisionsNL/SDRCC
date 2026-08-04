# v0.54.0e — Mission Control Status Clarity

## Scope

This release improves the existing Mission Control presentation. It does not
add concurrent execution, a second Mission Engine, another scheduler or a new
service-control path.

## Existing authorities retained

- Mission Planner remains the planning-policy authority.
- Mission Scheduler and the existing automation runtime retain mission
  selection and execution timing.
- Mission Engine retains Weather/METEOR lifecycle ownership.
- ISS Voice Executor retains ISS capture lifecycle ownership.
- Receiver Manager retains receiver reservation and handover authority.
- Mission Operations remains an observer-only aggregation layer.
- Mission Queue projects scheduling conflicts for the UI; it does not execute
  or cancel missions.

## Mission overlap projection

SDRCC currently has one automatic mission lane. Queue candidates are evaluated
chronologically after operator skips are applied:

1. The first mission keeps its normal `NEXT`, `TARGET` or `IN PROGRESS` state.
2. A later mission whose pass window overlaps that accepted mission is marked
   `BLOCKED`.
3. The blocked item reports the blocking queue key, satellite, receiver,
   conflict scope and exact overlap duration.
4. A same-receiver overlap reports `receiver` scope. An overlap across SDR1 and
   SDR2 reports `mission_engine` scope because the current automatic mission
   lane is global.
5. If an item is manually skipped it does not occupy the automatic mission
   lane.
6. An actually active mission always wins the UI projection, even if its queue
   order changed after planning refresh.

This is visibility only. True simultaneous Weather and ISS execution requires
a separately audited multi-runtime architecture.

## Receiver cards

Both receiver cards now consume the existing Mission Operations observer and
Mission Queue contracts through one `mission.js` renderer. The obsolete
badge-only compatibility script is no longer loaded.

The cards use the same restrained visual status language as Mission Queue:

- green: next/ready;
- cyan: active preparation or receiver activity;
- red: verified recording or failure;
- orange: processing, overlap or blocked;
- neutral: no active or planned mission.

During ISS Voice execution, the ISS observer now retains the queue key and
planned pass epochs and calculates live elapsed time, remaining time and
progress without changing executor authority.

Before a blocked window begins, the receiver card shows `MISSION OVERLAP`.
After its start time passes without execution, the same card shows
`NOT STARTED` until the pass window closes, with the blocking mission in the
detail line.

## Compatibility

- Existing API routes are reused; no new route is introduced.
- Existing Queue fields remain present. Rich conflict metadata is additive.
- `conflicts` remains a payload count and now counts the missions that are
  actually blocked, rather than coloring both sides of one overlap equally.
- Station location, receiver assignments, RF settings and user pass-window
  settings are not modified by this release.

## Validation

`scripts/validate_mission_control_status_clarity_v0540e.py` deterministically
checks:

- cross-receiver and same-receiver overlap projection;
- active-mission precedence;
- skip behavior;
- exact overlap duration and blocker metadata;
- ISS queue identity and live timing;
- Mission Operations and status API integration;
- one central receiver-card renderer;
- Queue and receiver-card status styling and asset cache busting.
