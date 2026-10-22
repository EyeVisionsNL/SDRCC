# SDRCC v0.56.0e — Traffic Voice scan exclusions

This release adds a persistent per-channel scan inclusion flag to the existing Traffic Voice channel banks.

- Existing Marine and Aviation channel definitions remain authoritative.
- Missing `scan_enabled` is interpreted as `true`, so the upgrade is backward compatible.
- Scan mode renders only channels whose `scan_enabled` flag is not false.
- Fixed-channel listening remains available even when a channel is excluded from scanning.
- At least one channel must remain enabled when scan mode is selected.
- Applying an exclusion uses the existing Traffic Voice settings transaction and service restart/rollback path.
- No second scanner, channel database, receiver owner or service controller is introduced.

Traffic Voice Auto Gain is intentionally not implemented in this release. The pinned native RTLSDR-Airband 5.2.0 RTL-SDR backend requires a numeric `gain` field, so a true AGC control requires a separately validated backend rebuild rather than a UI-only switch.
