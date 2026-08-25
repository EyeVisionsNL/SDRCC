# SDRCC v0.56.0m — Configurable Home Position

Adds one bounded operator control for the existing station-location authority.

## Authority

`config/station.yaml` → `station.location`, `station.latitude`,
`station.longitude` and `station.altitude_m` remain the only Home Position
authority.

The new System page card and `/api/home-position` endpoint only read/write that
existing configuration through `core.config.save_station()`.

No Radio View, Mission Planner or Doppler-specific location store is added.

## Consumers

The saved Home Position is already consumed by:

- shared Skyfield pass prediction / Mission Queue,
- Radio View station marker and station-relative orbital geometry,
- ISS Voice station-relative Doppler calculations.

Radio View observer cache is invalidated after a successful save. Mission
Planner is refreshed through its existing planning refresh event.

## UI

System → Home Position provides:

- location name,
- latitude,
- longitude,
- altitude above sea level,
- Use browser location,
- Save Home Position.

Browser geolocation only fills the form. It never writes configuration until
the operator explicitly saves.

Changing Home Position is rejected while a mission is active or preparing.
