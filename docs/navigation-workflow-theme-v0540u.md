# SDRCC v0.54.0u - Workflow Navigation Theme

## Scope

This release changes dashboard navigation presentation only.

## Approved workflow order

1. System
2. Radio Control
3. Radio View
4. Mission Control
5. Mission Planner
6. Mission Operations
7. Mission History
8. Mission Analytics
9. Logs

System is the initial page after opening or reloading SDRCC. This matches the
operator workflow after a host restart: start or inspect continuous services,
verify receiver operation, and then move into mission work.

## Button theme

All tab buttons share one consistent card-like navigation style. Each retains a
subtle accent colour so the button identity matches the visual language already
used by the corresponding dashboard area. Active, hover and keyboard-focus
states remain distinct.

The navigation uses nine equal columns on wide screens and a responsive grid on
narrow screens.

## Architecture boundary

- No API, service, receiver or mission authority changes.
- No new JavaScript navigation path.
- Existing `data-tab` identifiers and page IDs are retained.
- The top banner and page contents are unchanged.
- Compatibility validators locate tab sections by ID so the active class can
  change without weakening their existing content checks.
