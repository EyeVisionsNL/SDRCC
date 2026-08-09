# SDRCC v0.54.0r — System Visual Clarity

## Scope

Presentation-only refresh of the existing System tab after v0.54.0q System Service Lifecycle Integrity.

## Architecture and duplication audit

- Goal: host health, receiver occupancy, manual continuous-service control and exceptional maintenance.
- Navigation: existing `System` tab; position and order are unchanged.
- UI owner: `dashboard/templates/index.html` with the existing System and Receiver Inventory components.
- Presentation owner: existing System styles plus the new `dashboard/static/css/system_theme.css` layer.
- JavaScript: existing `system.js`, `receiver_inventory.js`, `services.js` and `mission_sounds.js`; unchanged.
- APIs: `/api/status`, `/api/receiver-inventory` and the existing service action route; unchanged.
- Backend authority: Receiver Registry for identity, Receiver Manager for reservations/handover, and the existing dashboard service-control boundary for manual actions; unchanged.
- Status sources: host metrics, Receiver Runtime/Inventory and verified v0.54.0q lifecycle snapshots; unchanged.
- Intentional repetition: System summarizes receiver and service state for maintenance decisions.
- Duplicate functionality: none added. No new polling, service controller, status source, API or backend module.

## Visual mapping

- System Health: cyan identity.
- Receiver Inventory: purple identity.
- AIS: cyan identity.
- ADS-B: purple identity.
- Advanced Maintenance and AIS-Catcher Control: amber warning identity.
- Green: healthy/running state.
- Amber: starting/partial/attention state.
- Red: failure or unavailable state.
- Slate: stopped/loading/neutral state.

Identity is shown with the left rail, heading, border tint and corner accent. Runtime state is shown independently with the existing badge and a narrow right rail.

## Preserved contracts

- All sections, element IDs, buttons and their order.
- AIS normal Start/Stop controls only `ais-catcher.service`.
- AIS-Catcher Control remains independent and closed under Advanced Maintenance.
- ADS-B verification, lifecycle states and button capabilities.
- Receiver Inventory identity and runtime authorities.
- System polling, mission sounds, API routes and backend behavior.
