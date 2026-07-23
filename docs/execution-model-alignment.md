# v0.44.0b — Execution Model Alignment

This release aligns the Plugin Manager's effective execution model with the
already validated AIS delegation path introduced in v0.44.0a.

## Scope

- No new execution path.
- No new service controller.
- No new systemd calls.
- No ADS-B enablement.
- No receiver ownership changes.
- No Execution Journal changes.

The Execution Factory remains the source of adapter and plan foundation
metadata. The Plugin Manager now overlays the effective enablement state for
AIS so consumers no longer see AIS as both enabled and foundation-only.

## Effective AIS model

- `execution_enabled: true`
- `executable: true`
- `foundation_only: false`
- `execution_mode: delegated_service_control`
- `execution_authority: existing_dashboard_systemctl_path`

All other plugins remain unchanged and fail closed.
