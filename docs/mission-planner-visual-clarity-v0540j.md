# Mission Planner Visual Clarity — v0.54.0j

## Scope

This release gives Mission Planner the established Mission Queue visual language without changing planning behavior or authority.

Changed presentation:

- summary cards use cyan, green, amber and purple state accents;
- METEOR-M2 3, METEOR-M2 4 and ISS Voice have stable recognition colors;
- the next target, active, conflict, blocked, eligible and skipped rows are visually distinct;
- quality labels render as English status badges;
- satellite planning controls use the SDRCC dark control theme;
- pass-window angles render on a separate line instead of touching the end time.

## Authority and duplication audit

- Mission Queue remains the planning source of truth.
- `GET /api/mission-queue` remains the only source for the planned-pass table.
- `POST /api/weather-planning` remains the existing owner of satellite planning settings and TLE refresh.
- Mission Planner does not schedule, reserve, start or stop receivers.
- No API, backend module, state machine, planning rule or configuration key is added.
- Mission Queue status vocabulary and colors are reused intentionally as presentation consistency, not duplicated business logic.

## Presentation mapping

| Meaning | Color |
| --- | --- |
| Next target | Cyan with green target accent |
| Eligible / clear | Green |
| Conflict / blocked / skipped count | Amber |
| Active mission | Red |
| METEOR-M2 3 | Cyan |
| METEOR-M2 4 | Purple |
| ISS Voice | Yellow |

Stored quality values are not modified. The UI presents `MATIG`, `GOED`, `ZEER GOED` and `UITSTEKEND` as `FAIR`, `GOOD`, `VERY GOOD` and `EXCELLENT`.

## Files

- `dashboard/static/css/mission_planner.css`
- `dashboard/static/js/mission_planner.js`
- `dashboard/templates/index.html`
- `scripts/validate_mission_planner_visual_clarity_v0540j.py`
- `scripts/validate_rf_receive_chain_v0540h.py` (cache-version compatibility only)
