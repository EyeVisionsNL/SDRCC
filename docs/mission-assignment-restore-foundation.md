# v0.47.1a – Mission Assignment & Restore Policy Foundation

This release adds a configuration-only contract for mission assignments and receiver default contexts.

## Authority boundaries

- `core/config.py` owns validated configuration.
- `core/plugin_registry.py` remains plugin metadata authority.
- `core/receiver_manager.py` remains receiver reservation authority.
- `core/receiver_contexts.py` is read-only observation and has no service, receiver, or Mission Engine authority.
- Existing service control remains unchanged.

## Configuration

- `mission_assignments`: maps `weather` and `iss_voice` independently to SDR1 or SDR2.
- `receiver_defaults`: maps each physical receiver to zero or one current continuous plugin (`ais` or `adsb`). The schema uses lists so future multiple compatible defaults can be introduced without another format migration.
- Existing `assignments` remain synchronized for backwards compatibility.

## Runtime scope

No service is started or stopped. No receiver is reserved. No mission is executed. Mission and restore context fields are exposed read-only and remain empty until the lifecycle integration release.
