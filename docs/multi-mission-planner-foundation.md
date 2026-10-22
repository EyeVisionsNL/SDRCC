# v0.46.0e – Multi-Mission Planner Foundation

This release introduces one planning-only aggregation contract for multiple mission types.

## Included

- `core/mission_planner.py` registers Weather and ISS Voice planning sources.
- Existing Weather passes are enriched with generic mission metadata.
- Mission Queue consumes the generic planner.
- Mission Scheduler selects only candidates marked `automation_eligible`.
- Queue conflicts are receiver-aware rather than treating every time overlap as a conflict.
- ISS Voice is registered as `foundation_only` and produces no pass candidates yet.

## Explicitly not included

- No ISS TLE provider.
- No Doppler calculation.
- No automatic ISS execution.
- No receiver claim or service control.
- No UI layout change.
