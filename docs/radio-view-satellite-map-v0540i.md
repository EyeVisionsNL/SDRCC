# Radio View Satellite Map — v0.54.0i-r2

## Tab audit

| Item | Finding |
|---|---|
| Purpose | Fast read-only overview of reception activity across ADS-B, AIS and satellites. |
| Navigation | Correctly placed after Radio Control and before Mission Planner. |
| Existing UI | ADS-B and AIS embed live interactive viewers. Satellite View used a fixed CSS ellipse, fixed icons and only changed the next-pass label. |
| Existing JavaScript | `radio_view.js` polled Mission Engine, capture status and the generic dashboard status. It had no orbital geometry. |
| Existing APIs | `/api/status` exposed one next Weather pass. No multi-satellite position or ground-track API existed. |
| Existing backend | `core.tle` validates TLE inventory; `core.passes` and `core.iss_passes` own pass-window prediction; Mission Queue owns planned mission order. |
| Duplication decision | Live map geometry did not exist. A read-only observer is permitted; it must not schedule missions, store TLEs, reserve receivers or change configuration. |

## Ownership retained

- `core.tle`: validated METEOR and ISS TLE inventory.
- `config/station.yaml`: home-station coordinates and altitude.
- Mission Planner and Mission Queue: pass eligibility, timing and next planned mission.
- Mission Engine and Receiver Manager: execution and receiver ownership.
- Mission Operations: live mission images and audio.
- `core.satellite_view`: short-lived presentation snapshot only.

## Implementation

- `/api/satellite-view` returns current positions for NORAD 25544, 57166 and 59051.
- Each satellite includes latitude, longitude, altitude, station-relative elevation, azimuth and range.
- The API includes a 45-minute past and 75-minute future ground track, split safely at the date line.
- The radio-horizon footprint is calculated from orbital altitude.
- Results are cached for 20 seconds to limit Skyfield/SGP4 CPU use.
- The browser polls every 10 seconds and always keeps the map visible during a mission.
- The next-pass panel reads the existing Mission Queue instead of predicting passes again.
- The next planned mission uses a fixed English date and 24-hour time, independent of browser locale.
- The world map is a bundled equirectangular Natural Earth 1:110m asset; runtime internet access is not required.

## Presentation rules

- ISS: yellow.
- METEOR-M2 3: cyan.
- METEOR-M2 4: violet.
- HOME / Vlaardingen: green.
- Dashed orbit: past 45 minutes.
- Solid orbit: next 75 minutes.
- Pulsing marker: above the local horizon.
- Clicking a satellite shows elevation, azimuth, range and altitude.

## Explicit non-goals

- No second scheduler or pass predictor.
- No browser-side TLE parsing.
- No external map tiles.
- No receiver or service control.
- No duplicate live image panel; the button opens Mission Operations.

## Data and API references

- Skyfield latitude/longitude, height and topocentric altitude/azimuth APIs: <https://rhodesmill.org/skyfield/earth-satellites.html>
- Natural Earth map data is public domain: <https://www.naturalearthdata.com/about/terms-of-use/>
