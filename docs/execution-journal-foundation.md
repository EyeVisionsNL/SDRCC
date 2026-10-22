# Execution Journal Foundation — v0.43.0c1

The Execution Journal is an observer-only, in-memory audit foundation for
read-only Execution Plans.

## Authority boundaries

- Execution Plans remain immutable descriptions.
- Mission Engine, Receiver Runtime and existing service paths keep authority.
- The Journal never executes, starts, stops, reserves, releases or mutates.
- Storage is process-local and intentionally non-persistent in this release.

## Lifecycle scope

This foundation records only `PLAN_CREATED`. Later releases may add lifecycle
observations without turning the Journal into a state machine.

## API

`GET /api/execution-journal`

Optional filters: `limit`, `plugin`, `status`.
