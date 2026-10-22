# SDRCC v0.48.0b — Unified Mission Scheduler

## Purpose

Make Mission Planner the sole source of the executable mission queue and keep Mission Scheduler plugin-independent.

## Runtime architecture

Mission providers → Mission Planner policy → executable mission queue → Mission Scheduler selection → mission autopilot → Receiver Manager → plugin executor → Mission Recordings.

## Changes

- ISS Voice execution eligibility is derived from its enabled planner, backend and receiver-claim configuration.
- Mission Planner publishes `get_executable_candidates()` as the single chronological runtime queue.
- Mission Scheduler consumes only that queue and no longer filters or knows individual providers.
- Weather and ISS Voice use the same scheduling contract.
- Scheduler serialization preserves mission type, plugin, receiver role, execution flags and priority.
- Observer and next-action text follow the selected mission type.
- Mission Scheduler no longer runs preflight. The existing mission autopilot remains the sole preflight and lifecycle owner.
- Receiver Manager remains the only receiver arbitration authority.

## Operational scope

No UI layout changes. No receiver-control duplication. No Git commit.
