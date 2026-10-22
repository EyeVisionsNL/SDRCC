# SDRCC v0.56.0j — v1.0 Installer Foundation

This release replaces the obsolete `SatStation` prototype installer with a generic SDRCC installer foundation.

## Boundaries

- Default project path is `<install-user-home>/SDRCC`; no `eyevisions` or Vlaardingen values are embedded.
- RTL-SDR identity is detected by serial. USB indexes are display-only and are never persisted.
- `sdrcc.service`, Traffic Voice service, sudoers boundaries and the root-owned receiver-role helper are reproducible from repository sources.
- Initial station/location and receiver serial mapping is explicit and separate from external AIS/readsb role changes.
- External receiver services are not enabled automatically.
- Missing SatDump, readsb, AIS-catcher or the pinned SDRCC RTLSDR-Airband backend cause a fail-closed install in v0.56.0j. Clean-machine third-party provisioning is intentionally the scope of v0.56.0k.
- Uninstall preserves runtime data by default.

This foundation does not create a new runtime/service authority. It installs the existing dashboard systemctl boundary and existing receiver-role helper.

## Release package r2
The release updater validates the running dashboard through the existing `/api/status` endpoint. It also accepts recovery from a partially applied r1 and restores its backup on post-install health-check failure.
