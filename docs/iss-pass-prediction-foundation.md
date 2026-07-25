# v0.46.0f – ISS Pass Prediction Foundation

Adds NORAD 25544 pass prediction as a planning-only provider in the existing Multi-Mission Planner.

## Contract

- Uses the existing station coordinates and Skyfield orbital engine.
- Reads `data/tle/iss.tle`.
- Produces ISS Voice candidates in the same Mission Queue as Weather.
- Keeps `automation_eligible: false` and `execution_enabled: false`.
- Does not claim receivers, control services, start RF tools, or mutate scheduler authority.
- `scripts/refresh_iss_tle.py` refreshes the ISS TLE atomically from CelesTrak.
