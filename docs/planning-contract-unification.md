# v0.47.0a – Planning Contract Unification

## Root cause

The station Planning Settings stored a 50° minimum elevation, while the ISS
provider independently read 20° from `config/iss_voice.yaml`. The Mission Queue
therefore received ISS passes that the dashboard subsequently labelled
`BELOW LIMIT`.

## Resolution

- `core.mission_planner` is the sole owner of elevation eligibility.
- The persisted compatibility source remains
  `config/station.yaml:weather_planning.minimum_elevation`.
- The policy scope is now explicitly all mission types.
- ISS pass prediction detects full above-horizon passes and does not own a
  planning threshold.
- The Mission Queue receives only centrally approved candidates.
- Queue decisions and reasons are supplied by the API.
- The browser no longer recalculates elevation eligibility.

## Operational boundaries

ISS remains planning-only and non-executable. No receiver, service, scheduler,
Mission Engine, recording, or RF authority was added.
