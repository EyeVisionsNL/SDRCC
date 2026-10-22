# SDRCC v0.54.0p - Radio View Visual Clarity

## Scope

This release changes only the presentation of Radio View.

- ADS-B Radar retains the existing tar1090 iframe and full-view link.
- AIS Traffic retains the existing AIS-Catcher iframe and full-view link.
- Satellite View remains an observer-only presentation of `/api/satellite-view`.
- Mission Queue remains the source of the next planned satellite mission.
- The offline world map, satellite selectors, ground tracks, radio-horizon footprints and station marker remain unchanged.
- No receiver, mission, service, TLE or API authority is added or moved.

## Visual vocabulary

- ADS-B uses purple.
- AIS uses cyan.
- M2-3 uses cyan, M2-4 purple and ISS yellow.
- Healthy/live state uses green, attention uses amber and failure uses red.
- Panels use the approved SDRCC tinted surface, left accent and corner highlight.

## Compatibility

The release adds one stylesheet scoped to `#tab-radio-view`. Existing element IDs, JavaScript, endpoints, refresh intervals, iframe URLs, internal navigation and responsive behavior are retained.
