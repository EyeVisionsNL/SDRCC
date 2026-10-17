# SDRCC Emergency Monitor — implementation plan (develop only)

Status: **DESIGN / NOT IMPLEMENTED**  
Scope: **develop** branch only. No release or merge to main.  
Date: 2026-10-17

## 1. Goals and fixed choices

Build a read-only emergency awareness service in SDRCC that combines:
- Lifeliner helicopter detections from local ADS-B.
- Police helicopter detections from local ADS-B when publicly broadcast and reliably identifiable.
- KNRM rescue vessel detections from local AIS.
- Waterpolitie vessel detections from local AIS when identifiable.
- Existing local P2000 events from an already running Home Assistant RTL-SDR add-on.
- Optional Home Assistant alerts through MQTT. **Home Assistant is not required for ADS-B/AIS local monitoring.**

Default **20 km** horizontal ground-distance radius around the station's configured Home Position (Vlaardingen in the current station configuration). Radius is for **live aircraft/vessel position events**, NOT a blanket P2000 capcode filter. A P2000 dispatch can have no valid coordinates, and a dispatch is not proof that an aircraft or vessel has started a mission.

The user's P2000 lightkrant must keep working unchanged. No second P2000 receiver, RTL decoder or competing RTL-SDR allocation. Existing Home Assistant P2000 sensors and TTS replacements are not modified.

**Opt-in requirement:** the Emergency Monitor is **OFF by default** and is configured exclusively under **System → Advanced Maintenance → Emergency Monitor** (the existing closed-by-default maintenance disclosure). An independent **Home Assistant / MQTT notifications** toggle is also **OFF by default**. The five detection-category preferences (Lifeliner, politie, KNRM, waterpolitie, P2000) do not override the master switch.

When the master switch is OFF: the monitor worker is not started, there is no background ADS-B/AIS polling, no MQTT connection/subscription/publishing, and no alert generation. Normal readsb/AIS-catcher operation, existing P2000 lightkrant, Home Assistant and receiver services remain completely unchanged. Turning the switch ON enables local ADS-B/AIS monitoring and SDRCC event history even **without** Home Assistant. The **P2000 source** requires an MQTT broker carrying the existing P2000 messages and must be separately connectable/disableable; without it, show P2000 **NOT CONFIGURED**, not a fake zero count.

## 2. Existing SDRCC architecture verified on develop

- **config/station.yaml**, **core/config.py**: station location / latitude / longitude / altitude is canonical; Home Position changes already synchronize readsb. Emergency Monitor reads this position; no separate duplicated home coordinates.
- **core/receiver_monitor.py**: read-only receiver observation. Aircraft JSON candidates: /run/readsb/aircraft.json, /var/run/readsb/aircraft.json, /run/dump1090-fa/aircraft.json. Freshness check for aircraft runtime file: <= 5 seconds. Ships via local http://127.0.0.1:8119/ships.json (fallback localhost), shared 1-second cache. Includes existing data freshness/validation conventions.
- **core/plugin_registry.py**: ADS-B is readsb.service, AIS is ais-catcher.service. This feature is a consumer, not a receiver-owning plugin, and must not reserve devices or change assignments.
- **core/event_bus.py**: persistent operator events with category/level/title/detail and a 100-entry bounded state file. Reuse for local timeline/status; a separate persisted alert-deduplication state is required for restart-safe cooldowns.
- **dashboard/app.py** and **dashboard/templates/index.html**: Flask backend and System page; the real **Advanced Maintenance** section is an existing `<details class="card system-maintenance-card-v0540f">` wrapper with internal `system-maintenance-group-v0540f` sections. Place Emergency Monitor **inside that existing disclosure**, not as a new navigation tab. Add narrow, allowlisted config/status/test APIs and scoped CSS/JS consistent with the existing UI.
- **systemd/sdrcc.service.in** and **install.sh / update manager**: identify how an optional independent monitor worker should start/stop and survive updates; do not introduce a persistent thread in each Flask request/worker.

Existing code and services must remain usable if Emergency Monitor is disabled.

## 3. Existing Home Assistant P2000 source (no changes to it)

The user has the **cyberjunky/addon-p2000_rtlsdr** add-on already receiving FLEX on a separate RTL-SDR, with Home Assistant MQTT auto-discovery. Existing sensor IDs:

| Existing sensor | ID | Proposed role |
| --- | --- | --- |
| P2000 GRIP | 2002 | Optional local event display |
| P2000 Lifeliners | 2003 | P2000 dispatch source |
| P2000 regional/keyword | 2004 | Optional regional event display |
| P2000 KNRM | 2005 | P2000 dispatch source |

The add-on code publishes data under:
- **homeassistant/sensor/p2000_rtlsdr/2003/attributes**
- **homeassistant/sensor/p2000_rtlsdr/2003/state**
- **homeassistant/sensor/p2000_rtlsdr/2005/attributes**
- **homeassistant/sensor/p2000_rtlsdr/2005/state**
- Analogous topics for IDs 2002 and 2004.
- Availability: **p2000_rtlsdr/status**.
- Discovery: **homeassistant/sensor/p2000_rtlsdr/2003/config** etc.

Do **not** assume the P2000 live data is published at p2000_rtlsdr/2003/state: the inspected add-on code adds the prefix homeassistant/sensor/ to state/attribute topics.

Attributes include **time received**, **capcodes**, **priority**, **region**, **disciplines**, **latitude**, **longitude**, and **raw message**. The add-on publishes attributes then the state message, with retain currently disabled for events. Consume the state as the event trigger and cache the most recent attributes by sensor ID, validating timestamps / content association. Deduplicate repeated decodes and overlapping sensors. Subscribe read-only. P2000 categories alone do not prove a police helicopter/water police deployment.

**Prerequisite:** during integration test, verify topic names, actual payloads and Home Assistant/broker connectivity on the user's installation using a safe read-only subscription. Do not store actual incident messages or personal addresses in project fixtures.

**Security:** user-supplied OpenCage API token was exposed in chat. Rotate at the provider; never copy it to repository, examples, logs or tests. MQTT credentials should come from protected local configuration or environment; do not put secrets in committed YAML. Use unique MQTT client IDs.

## 4. Proposed implementation modules (later milestones, not yet added)

| New / changed path | Responsibility |
| --- | --- |
| config/emergency_monitor.yaml | Non-secret defaults: `enabled: false`, `radius_km: 20`, five category preferences, separate `p2000_mqtt_input.enabled: false`, and `home_assistant_notifications.enabled: false` |
| core/emergency_monitor.py | Coordinator: normalize inputs, classify, calculate distances, derive event types |
| core/emergency_monitor_adsb.py | Read-only parsing of readsb aircraft.json, source/position freshness and verified allowlist |
| core/emergency_monitor_ais.py | Read-only parsing of AIS ships.json and verified MMSI allowlist |
| core/emergency_monitor_p2000.py | Read-only MQTT subscriber to existing sensor topics; normalize dispatch events |
| core/emergency_monitor_mqtt.py | Bounded outbound MQTT queue, reconnect/backoff, status/LWT, event publishing |
| core/emergency_monitor_state.py | Atomic and bounded restart-safe per-identity deduplication |
| dashboard/app.py | Narrow read-only status/events endpoint, validated settings/test endpoint |
| dashboard/templates/index.html | One opt-in Emergency Monitor group **inside System → Advanced Maintenance**; no new top-level tab |
| dashboard/static/js/emergency_monitor.js | Status, events, settings/test action |
| dashboard/static/css/emergency_monitor.css | Existing SDRCC theme, no unrelated green palette or style rewrite |
| systemd/sdrcc-emergency-monitor.service.in | Single service worker as a candidate; audit installer/update lifecycle before enabling |
| requirements.txt | Add paho-mqtt with a reviewed compatible version, only when implementation begins |
| tests/test_emergency_monitor_*.py | Offline deterministic tests with sanitized mock data |
| docs/emergency-monitor-implementation-plan.md | This develop-only design document |

Prefer sharing proven read/validation helpers with **core/receiver_monitor.py** without refactoring its services or receiver authority. Keep hardware detection and MQTT transport behind independently testable interfaces.

## 5. Identity, freshness, 20 km and false-positive rules

**ADS-B:** Maintain a reviewable local verified set of ICAO hex IDs and relevant callsigns for Lifeliners and police helicopters. Do not classify solely on arbitrary keyword fragments or guess changing registrations. Check readsb runtime file freshness and per-target fresh position (consider **seen_pos** where available), valid latitude/longitude and acceptable age (initial proposed limit <= 30s). Exclude stale, missing or ambiguous targets. Calculate great-circle ground distance by Haversine using current Home Position. A stationary helicopter at a heliport is presence, not an emergency response: label alerts **detected nearby**, not **dispatched**.

**AIS:** Maintain a reviewable MMSI allowlist for verified KNRM and Waterpolitie vessels; names/callsigns are corroborating evidence only. Accept position only with valid MMSI, valid lat/lon, positive validation when supplied, and fresh last_signal/age fields. For emergency notifications prefer a much tighter position-age threshold than the current ATIS/AIS correlation maximum of 1800s (initial proposed <= 120s). AIS is not mandatory for every rescue/police craft and may be disabled.

**Alert triggering:** Initial detection requires two consecutive fresh in-radius samples, 20 km enter threshold, and 22 km exit threshold (hysteresis). One 'entered radius' event per verified identity. Re-arm after confirmed exit and a quiet interval; persist per-identity notification state across process/system restarts. Proposed cooldown 30 minutes and a 60-second startup warm-up. Do not emit a new alert for each position update. Keep events distinguished by source and classification.

**P2000:** Display the dispatch event independently of ADS-B/AIS. No 20 km radius requirement unless explicitly configured for a separately geocoded incident with trustworthy coordinates. Missing geocoding must not suppress the Lifeliners/KNRM capcode event. Route local/general P2000 categories to HA only if explicitly enabled, to avoid duplicate notifications from existing HA automations. Do not automatically claim a causal link between an incident and a passing helicopter/ship. Optional future correlation is informational and confidence-marked.

When a decoder/source is stopped or unavailable, display **SOURCE UNAVAILABLE** / **POSITION UNKNOWN**, never 'no emergency activity'.

## 6. Optional MQTT design and Home Assistant interoperability

MQTT must be **optional** and never a prerequisite to run the ADS-B/AIS part of Emergency Monitor. With the master switch ON and HA notifications OFF, SDRCC stores and displays local detections only. Input and output are controlled independently:
- **P2000 MQTT input (OFF by default):** subscribe only if the user supplies/enables broker connection details. It can be used for an existing local P2000 source without requiring Home Assistant notifications.
- **Home Assistant notifications (OFF by default):** publish only if explicitly enabled and broker connection succeeds. If disabled, do not publish discovery or alerts; hide/disable the HA test button.
- When **both** MQTT input and HA output are OFF, **do not open an MQTT connection**. When the entire Emergency Monitor is OFF, its worker is stopped; none of these connectors run.

When opted in, reuse the **same broker** already used for P2000, with a different SDRCC MQTT client ID and **different outbound topics**. Proposed names:
- **sdrcc/emergency/events** — JSON event, QoS 1, **retain=false**
- **sdrcc/emergency/status** — online/offline/health, QoS 1, retained availability/LWT
- **sdrcc/emergency/summary** — optional latest status with expiry semantics, not used to trigger new push notifications
- Optional HA discovery under **homeassistant/device/sdrcc_emergency/config** only after verification (unique IDs and birth-message handling, never conflicting with P2000 add-on IDs).

Illustrative event (no real aircraft/vessel data):

~~~json
{
  "schema_version": 1,
  "event_id": "example-unique-event-id",
  "timestamp": "2026-10-17T12:00:00+02:00",
  "source": "adsb",
  "category": "lifeliner",
  "kind": "entered_radius",
  "identity": "example-icao-hex",
  "callsign": "EXAMPLE",
  "distance_km": 12.4,
  "radius_km": 20,
  "station": "Vlaardingen",
  "confidence": "verified-identity"
}
~~~

Do not put broker credentials, API keys, full P2000 personal addresses, or unfiltered raw incident data on the new SDRCC outbound topics. MQTT ACLs should permit SDRCC to subscribe only to intended input topics, publish only to sdrcc/emergency/# and its own HA discovery topic if enabled. No MQTT control messages accepted.

Home Assistant can create a notification automation from **sdrcc/emergency/events** and test with a synthetic test event (with clearly marked test=true), then from real local sources. Keep existing P2000 sensor notification automations as-is unless explicitly migrating them; protect against overlapping alerts.

## 7. Proposed UI: System → Advanced Maintenance → Emergency Monitor

The Emergency Monitor **is not a separate SDRCC tab**. Add one `system-maintenance-group-v0540f` section inside the **existing closed-by-default System → Advanced Maintenance** panel, matching the current SDRCC theme:
- Top **Enable Emergency Monitor** master switch defaults OFF. Show **DISABLED** prominently, not a false *all clear*.
- Only when enabled, reveal the nested options: the five requested categories (Lifeliner, politiehelikopter, KNRM, waterpolitie, P2000), ADS-B/AIS source status, local recent events, and the distance slider **20 km**.
- Separate **Use existing P2000 MQTT source** toggle defaults OFF; provide broker configuration only when needed. Disabling it has no effect on the existing P2000 addon or the lightkrant.
- Separate **Send notifications to Home Assistant via MQTT** toggle defaults OFF; show broker connection state and **Send test to Home Assistant** only when this option is enabled.
- Home Assistant credentials are optional; a user without HA or a broker can still enable local **ADS-B/AIS detection**. Avoid showing an MQTT configuration error as a failure of local monitoring.
- Show source freshness/availability, last detection time, and latest 20 events. Display _P2000 dispatch_ versus _nearby target detected_ separately. Never auto-center the map.
- No new top-level navigation button and no unrelated mobile/Android changes in the first iteration.

Proposed initial configuration (non-secret values only):

~~~yaml
emergency_monitor:
  enabled: false
  radius_km: 20
  categories:
    lifeliner: true
    police_helicopter: true
    knrm: true
    waterpolitie: true
    p2000: true
  p2000_mqtt_input:
    enabled: false
  home_assistant_notifications:
    enabled: false
~~~

## 8. Safe staged development on develop

1. **Design (this document):** verify SDRCC source paths and P2000 add-on published topics; freeze initial event schema and acceptance cases. No runtime changes.
2. **Offline normalization:** implement ADS-B and AIS readers/classifiers/geometry, deterministic tests, test allowlists; read-only, initially disabled and no MQTT.
3. **P2000 read-only input:** subscribe to verified 2003/2005 (optional 2002/2004), verify pairing of state/attributes and de-duplication; do not change user's lightkrant/add-on.
4. **Outbound MQTT and HA:** isolated event namespace, reconnect/LWT and QoS; manual test event; then a real target, with no retained push event.
5. **UI/configuration:** add an opt-in group only inside existing **System → Advanced Maintenance**; master enabled OFF by default, nested 20 km/categories, independently disabled P2000 MQTT input and HA notification output; display local events without broker and expose test action only when HA output is enabled.
6. **Installer/update/rollback:** service lifecycle, requirements, version/manifest workflow, receiver handover regression and documentation only on develop.
7. **Live acceptance:** real observed ADS-B/AIS/P2000 inputs when available, HA MQTT broker and phone notifications; update main only after explicit approval, never as part of these stages.

## 9. Acceptance checklist

- [ ] Existing P2000 RTL-SDR add-on, MQTT sensors, text replacements and lightkrant unchanged.
- [ ] Emergency Monitor appears inside existing **System → Advanced Maintenance**, not in main navigation.
- [ ] Emergency Monitor master toggle is **OFF by default**; disabled means no monitor worker, polling, MQTT session or alerts.
- [ ] Without Home Assistant/MQTT, enabling the monitor still provides local ADS-B/AIS monitoring and event history.
- [ ] P2000 MQTT input and Home Assistant MQTT notifications are **separate opt-in toggles**; each defaults OFF.
- [ ] Disabling HA notifications prevents outgoing HA event/discovery messages, and hides its test button; it does not disable local ADS-B/AIS monitoring.
- [ ] Existing ADS-B, AIS, ATIS, Marine Traffic, satellites, receiver handover, Android app and Update Manager still work.
- [ ] Radius defaults to 20 km and follows updated station Home Position.
- [ ] Lifeliners/police only when recognized by verified identities with fresh ADS-B positions.
- [ ] KNRM/Waterpolitie only when recognized by verified MMSI with fresh AIS positions.
- [ ] P2000 Lifeliners/KNRM events visible even without a corresponding aircraft/vessel position.
- [ ] No double MQTT alerts due to replayed sensor messages, receiver refresh, RSSI flicker or SDRCC restart.
- [ ] Stopped readsb/AIS/MQTT show source-unavailable rather than 'all clear'.
- [ ] HA receives test and actual events on SDRCC namespace; P2000 existing topics untouched.
- [ ] No secret or real location/address payload leaks into repository, log or example.
- [ ] Clean installer/update/rollback and no new receiver allocations.
- [ ] No changes to main until separately approved.

## References

- SDRCC develop: core/receiver_monitor.py, core/config.py, core/event_bus.py, dashboard/app.py, dashboard/templates/index.html.
- P2000 RTL-SDR add-on: https://github.com/cyberjunky/addon-p2000_rtlsdr ; inspected p2000_rtlsdr/p2000.py.
- HA MQTT integration: https://www.home-assistant.io/integrations/mqtt/
- HA MQTT trigger: https://www.home-assistant.io/triggers/mqtt/
