# v0.54.0d — Pass Window Correctness

## Scope

This release corrects the selected satellite pass from planning through
execution. It does not add another scheduler, state machine, receiver owner or
TLE updater.

## Authority and data flow

| Responsibility | Existing owner retained |
|---|---|
| Station latitude, longitude and altitude | `config/station.yaml` |
| Per-satellite planning values | `config/satellites.yaml` and `config/iss_voice.yaml` |
| Planning configuration validation | `core/weather_planning.py` compatibility module |
| TLE parsing and status | `core/tle.py` |
| TLE network retrieval | `core/downloader.py` |
| Orbital pass calculation | `core/passes.py` |
| Eligibility policy | `core/mission_planner.py` |
| Chronological scheduling | `core/mission_scheduler.py` |
| Receiver ownership and handover | `core/receiver_manager.py` |
| Mission execution | existing Weather/SatDump and ISS Voice executors |

The historic `weather_planning` module and `/api/weather-planning` route remain
as compatibility layers. They no longer imply one global Weather-only policy.

## Configurable profiles

Mission Planner exposes three independent profiles:

- METEOR-M2 3;
- METEOR-M2 4;
- ISS Voice.

Each profile stores:

- `minimum_peak_elevation`: eligibility gate applied to the maximum elevation;
- `begin_elevation`: rising crossing that starts the mission window;
- `close_elevation`: falling crossing that closes the mission window.

The begin and close values may differ. Both must be less than or equal to the
minimum peak gate. All predictions use the configured ground-station location;
there are no Vlaardingen coordinates in the prediction code.

For an existing v0.54.0c installation, the migration:

1. preserves existing per-satellite v0.54.0d values when already present;
2. initializes METEOR peak gates from each existing `min_elevation`;
3. initializes ISS peak gating from the formerly authoritative station planning
   limit, because the old `iss_voice.minimum_elevation` field was not used by
   the Planner;
4. adds 10° begin/close defaults only when those new fields do not exist;
5. leaves assignments, RF settings, station coordinates and all unrelated YAML
   keys unchanged.

## Shared pass calculation

Weather and ISS now call `core.passes.predict_satellite_passes()`. Skyfield
calculates a rising event at `begin_elevation`, the culmination, and a falling
event at `close_elevation`. Mission Planner then applies the matching profile's
minimum peak gate.

ISS no longer publishes a 0°→0° horizon window. SatDump no longer adds a hidden
60-second extension.

## Immutable selected pass

When the Scheduler selects a pass, its execution contract includes:

- stable queue key;
- start, maximum and end epochs;
- minimum peak, begin and close elevations;
- NORAD catalog number;
- TLE source, epoch and SHA-256 fingerprint.

The contract remains pinned through preflight and execution. A later planning
refresh cannot silently replace it. Weather builds the SatDump command from the
pinned pass instead of recalculating at T−30. ISS and Weather both reduce their
actual capture timeout when startup is late so they still stop at the selected
falling boundary.

The pinned item is also injected into Mission Queue while targeted or active.
This keeps the Mission SDR1/SDR2 card on the active mission and shows remaining
time until the real close boundary.

## TLE integrity

The only network source is CelesTrak. SDRCC requests exactly these catalog
numbers:

- 57166 — METEOR-M2 3;
- 59051 — METEOR-M2 4;
- 25544 — ISS (ZARYA).

Before replacement, SDRCC validates:

- complete three-line blocks;
- matching line numbers and catalog numbers;
- both NORAD checksums;
- all three required catalogs exactly once;
- element epochs that are neither implausibly old nor in the future.

Both live files are replaced through one recoverable transaction. A failed
download or validation keeps the last complete valid files. Mission Planner
reports `CURRENT`, `STALE` or `INVALID`. Manual **Refresh TLE & planning** uses
the valid cache for two hours, then checks CelesTrak and recalculates planning.

## Explicit exclusions

This release does not change receiver assignments, AIS/ADS-B handover order,
RF gain, squelch, Doppler, audio filters, azimuth sectors, Mission History
classification or the general dashboard layout.

No Git commit is part of installation. A real METEOR and ISS passage must be
validated before committing v0.54.0d.
