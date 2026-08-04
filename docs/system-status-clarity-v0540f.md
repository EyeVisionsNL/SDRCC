# SDRCC v0.54.0f — System Status Clarity

## Goal

Bring the System tab into the same compact visual language as Mission Queue while retaining the existing operational controls and authority boundaries.

## UI changes

- System Status is replaced by a full-width System Health section with compact CPU, RAM, disk and uptime status cards.
- Receiver Inventory remains read-only and uses compact Queue-style receiver cards.
- Service Control remains the visible manual authority for AIS and ADS-B and now presents both services as equal status cards.
- Mission Tools is removed as a primary card.
- Simulate Recording and Reset Mission Engine remain available under a closed-by-default Advanced Maintenance section.
- Mission sound controls move into the same Advanced Maintenance section.
- The System and Mission Events explanation card is removed.
- The large Mission Event Center settings card is removed; runtime notifications and sounds remain operational.
- TLE management remains exclusively in Mission Planner.

## Status colors

- Green: nominal health, active continuous service or service-active receiver.
- Cyan: ready/read-only information.
- Orange: elevated health or attention/reservation state.
- Red: high resource use, unavailable receiver or active mission recording.

## Authority and data sources

- System Health continues to consume the existing `/api/status` system metrics.
- Receiver Inventory continues to consume the existing read-only `/api/receiver-inventory` observer.
- AIS and ADS-B buttons continue to use the existing dashboard action handlers.
- Simulate Recording and Reset Mission Engine keep their existing endpoints and confirmation behavior.
- Mission notification settings remain browser-local and do not create backend state.
- No new endpoint, service controller, scheduler, state machine or persistent state is introduced.

## Modified files

- `dashboard/templates/index.html`
- `dashboard/static/css/system.css`
- `dashboard/static/css/receiver_inventory.css`
- `dashboard/static/dashboard.js`
- `dashboard/static/js/dashboard.js`
- `dashboard/static/js/system.js`
- `dashboard/static/js/services.js`
- `dashboard/static/js/receiver_inventory.js`
- `dashboard/static/js/mission_sounds.js`
- `scripts/validate_mission_control_status_clarity_v0540e.py` (accepts the newer dashboard asset cache bust)

## Acceptance

- The System tab contains only System Health, Receiver Inventory, Service Control and collapsed Advanced Maintenance as primary sections.
- CPU, RAM and disk use the existing 65% warning and 85% critical thresholds.
- AIS and ADS-B retain Start and Stop actions and show RUNNING or STOPPED status.
- Receiver Registry remains identity authority and Receiver Inventory remains read-only.
- Advanced Maintenance is closed on page load.
- Simulate Recording, Reset Mission Engine, sound enable, volume and sound test remain available after opening Advanced Maintenance.
- System and Mission Events and Mission Event Center no longer appear as primary cards.
- Existing mission, receiver, service and notification behavior is unchanged.
