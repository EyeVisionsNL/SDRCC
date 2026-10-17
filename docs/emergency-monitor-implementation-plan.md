# SDRCC Emergency Monitor — implementation and acceptance

**Status:** Beta **v0.67.7**, on `develop` only. No merge to `main`.  
**Location:** Inside **System → Advanced Maintenance** (the existing, closed-by-default panel).  
**Station radius:** Default **20 km** around the canonical SDRCC Home Position.

## Scope and ownership — essential separation

- **SDRCC** independently monitors **local readsb ADS-B** and **AIS-catcher AIS** for nearby, identifiable emergency-service aircraft and vessels.
- **Home Assistant** remains the **only owner of P2000**: RTL-SDR/FLEX decoding, the P2000 MQTT add-on, sensors, the lightkrant, P2000 filters and notification automations.
- **SDRCC must NEVER subscribe to, store, display, filter, forward or duplicate P2000 messages.** It makes no connection to P2000 topics. No P2000 sensor, P2000 input switch or P2000 event card appears in SDRCC.
- Optional **SDRCC → MQTT → Home Assistant** is **outbound only**. It publishes *nearby aircraft/vessel detections* under the dedicated `sdrcc/emergency/` namespace. It does not consume the Home Assistant P2000 namespace.
- Enabling or disabling SDRCC Emergency Monitor changes nothing in the existing P2000 receiver, lightkrant, P2000 sensors, TTS replacements or Home Assistant automations.

## Existing code reused

| Existing source | Use |
| --- | --- |
| `config/station.yaml`, `core/config.py` | Current Home Position, no competing coordinates |
| `core/receiver_monitor.py` | Local readsb `aircraft.json` and localhost AIS-catcher `ships.json`, source freshness conventions |
| `core/plugin_registry.py` | No additional receiver reservation, service control or role |
| `core/event_bus.py` | General operator event display (new ADS-B/AIS detections only) |
| `dashboard/app.py` | API `GET/POST /api/emergency-monitor`, `POST /api/emergency-monitor/test` |
| `dashboard/templates/index.html` | Emergency Monitor section nested *inside* Advanced Maintenance |
| `scripts/install/update_manifest.json` | Hash approvals for managed develop updates |

## Implemented beta features

- Master **Enable Emergency Monitor** switch: **OFF by default**.
- Source/category switches: **Lifeliners**, **Police helicopters**, **KNRM vessels**, **Water police**.
- Radius slider default **20 km**; measured as great-circle horizontal ground distance between Home Position and a **fresh target location**. Saved user choices (including 50 km) are preserved by the updater.
- Opt-in **Only alert when moving** toggle, **OFF by default**. When ON, suppress AIS vessels moving below **2.0 knots** and ADS-B aircraft below **30.0 knots**. Speed must be known and fresh in the respective valid AIS/ADS-B observation; no speed or AIS 102.3 "unknown" does **not** count as movement. Two qualifying in-range polls are needed before an alert. Reported speed is displayed on resulting detection events.
- Keep one notification per identity per continuously observed in-range session; re-arm upon confirmed observation beyond the radius + 2 km, subject to the existing 30-minute restart-safe cooldown.
- **Read-only** local ADS-B/AIS observation; missing or stale data appears as unavailable, not proof of no activity.
- Lifeliner identification on verified hex allowlist or clearly matching `LIFELN1`–`LIFELN9` callsign; police helicopters require explicitly verified hex identifiers.
- KNRM and Waterpolitie AIS detection requires explicitly verified nine-digit MMSI entries.
- Fresh position requirement, basic enter/exit hysteresis, cooldown and bounded persistence; do not infer an incident or active mission from mere presence.
- Local recent-detection history (no Home Assistant required).
- The Emergency Monitor group spans the **entire Advanced Maintenance width** (`grid-column: 1 / -1`) while the other maintenance controls retain their existing layout; identification inputs use a responsive full-width grid.
- Optional **Send SDRCC alerts to Home Assistant via MQTT** switch: **OFF by default**. Only when enabled is a broker connection made.
- User-provided broker host, port, login and optional TLS. Password is saved in a protected local file, not Git. The test button publishes a clearly marked synthetic event.

## MQTT output contract

- `sdrcc/emergency/events` — JSON event with `source: adsb` or `source: ais`, relevant category, distance and timestamp; QoS 1, **retain=false**.
- `sdrcc/emergency/status` — own SDRCC availability state (retained); it does not modify Home Assistant's P2000 sensors.
- **No MQTT subscriptions to any topic**, including `homeassistant/sensor/p2000_rtlsdr/#`.
- This MQTT broker may be the same broker already serving Home Assistant, but SDRCC uses its own client ID and publishes on separate topics.
- Secure per-client MQTT credentials and broker ACLs are recommended. Never commit credentials, OpenCage tokens or raw P2000 messages.
- An existing beta setting such as `p2000_input` or `categories.p2000` is discarded by the v0.67.6 settings loader. Previously persisted P2000 events are purged from Emergency Monitor's state **and** precisely matched old P2000 copies are removed from SDRCC's general Event Bus at startup, leaving all unrelated events intact.

## Optional dependency

`paho-mqtt>=2,<3` is in `requirements.txt` for fresh installations. The current managed updater does **not automatically pip install a newly added dependency**, so existing installations must run:

```bash
cd ~/SDRCC
./venv/bin/python -m pip install "paho-mqtt>=2,<3"
```

This dependency was already installed by the tester as version **2.1.0**.

## Acceptance checks

- [ ] The Emergency Monitor is visibly **inside Advanced Maintenance** (not a top-level tab and not a separate card below the maintenance panel).
- [ ] Master OFF prevents observation polling and MQTT connections.
- [ ] Four target categories only; **no P2000 fields or incoming subscriptions** in SDRCC.
- [ ] With **Only alert when moving** ON: moored vessels/parked aircraft are ignored; AIS >= 2 knots / ADS-B >= 30 knots qualify; unknown speed is silent; switch OFF restores presence-based alerts.
- [ ] Full-width layout in the Advanced Maintenance two-column grid, including mobile responsive behavior.
- [ ] One event per continuously in-range session, without repeated alerts each 30 minutes.
- [ ] Existing HA P2000 lights/sign, capcode sensors and notifications operate as before.
- [ ] With MQTT disabled, local ADS-B/AIS detections still work.
- [ ] With MQTT enabled, synthetic test events and actual valid detections reach Home Assistant on `sdrcc/emergency/events`.
- [ ] No false detection for unrelated hex/MMSI or stale/invalid positions; changing Home Position changes 20-km center.
- [ ] No duplicate alerts on every observation or after a routine SDRCC restart.
- [ ] Beta update verifies manifest hashes, backend syntax, UI element presence, restart and rollback; no receiver service regressions.
- [ ] No changes to `main` before explicit approval.

**Offline validator:** `./venv/bin/python scripts/validate_emergency_monitor_v0675.py` (name retained for compatibility; also covers P2000 removal, motion thresholds and full-width placement).  
**Live readsb, AIS, MQTT and Home Assistant tests:** pending execution on the station.

## Why v0.67.6?

The first v0.67.5 beta erroneously included incoming P2000 support. Removing that is a correction that must reach installations already running v0.67.5. The updater skips same-version updates; v0.67.6 ensures delivery without disturbing `main`.
