# SDRCC v0.54.0o — Radio Control Visual Clarity

Revision r2 makes the legacy v0.54.0g validator configuration-independent: both automatic and manual ISS gain are checked with isolated inputs, while the active operator configuration is only validated and preserved.

## Scope

This release changes only the presentation of the existing Radio Control tab.
No endpoint, polling loop, form handler, receiver assignment, RF setting,
mission rule, service state or backend authority is changed.

## Visual system

- Receiver Monitor: cyan.
- Receiver Runtime Diagnostics: purple.
- Receiver Assignments: green.
- Weather / METEOR Settings: cyan.
- ISS Voice Settings: yellow.
- Healthy, attention and failure states remain green, amber and red.
- Receiver role colors remain visible inside Receiver Monitor.

The theme is isolated to `#tab-radio` in
`dashboard/static/css/radio_control_theme.css`.

## Ownership preserved

- Receiver Monitor remains a read-only observer.
- Receiver Runtime Diagnostics remains a read-only projection.
- Receiver Assignments remains the only assignment authority presentation.
- Weather / METEOR and ISS Voice forms keep their existing APIs and handlers.
- No Radio View, Mission Planner or Mission Operations styling is changed.

## Validation

`scripts/validate_radio_control_visual_clarity_v0540o.py` verifies the scoped
theme, the five approved sections, the existing form IDs and endpoints, and the
absence of data or control coupling in the stylesheet.
