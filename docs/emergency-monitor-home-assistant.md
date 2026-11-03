# SDRCC Emergency Monitor — Home Assistant notification cleanup

SDRCC develop 0.70.3 checks local ADS-B/AIS every five seconds. New detections
still use `sdrcc/emergency/events`; clear messages use the separate
`sdrcc/emergency/cleared` topic with a stable per-target `notification_id`.
A clear means **no longer observed**, not that an emergency has ended.
The P2000 receiver, P2000 topics, sensors and automations are not changed.

## Home Assistant automation

Replace the existing **SDRCC - Emergency Monitor** notification automation
with the YAML below. Keep any MeshCore action in the **detection** branch only;
do not broadcast an expiry as a new emergency. The lightkrant still receives
only the original `sdrcc/emergency/events` messages.

```yaml
alias: SDRCC - Emergency Monitor
description: Create and dismiss notifications by SDRCC target identity
triggers:
  - trigger: mqtt
    topic: sdrcc/emergency/events
    id: detected
  - trigger: mqtt
    topic: sdrcc/emergency/cleared
    id: cleared
conditions: []
actions:
  - choose:
      - conditions: "{{ trigger.id == 'cleared' }}"
        sequence:
          - action: persistent_notification.dismiss
            data:
              notification_id: "{{ trigger.payload_json.notification_id }}"
    default:
      - action: persistent_notification.create
        data:
          notification_id: "{{ trigger.payload_json.get('notification_id', 'sdrcc_emergency_test') }}"
          title: "{{ trigger.payload_json.get('title', 'SDRCC Emergency Monitor') }}"
          message: >-
            {{ trigger.payload_json.get('detail', 'New SDRCC alert') }}
            {% if trigger.payload_json.get('distance_km') is not none %}
            Distance: {{ trigger.payload_json.distance_km }} km.
            {% endif %}
            {% if trigger.payload_json.get('speed_knots') is not none %}
            Speed: {{ trigger.payload_json.speed_knots }} knots.
            {% endif %}
            Source: {{ trigger.payload_json.get('source', 'unknown') }}
mode: queued
max: 20
```

**One-time cleanup:** Existing notifications created without a stable
`notification_id` cannot be matched reliably. Dismiss those old messages
manually once. All subsequent detections and clears use the same ID.

## MQTT lifecycle

| Topic | Payload |
| --- | --- |
| `sdrcc/emergency/events` | The original `nearby_detected` event plus `notification_id` |
| `sdrcc/emergency/cleared` | `kind: no_longer_observed`, `reason`, `last_seen`, matching `notification_id` |
| `sdrcc/emergency/status` | Existing online/offline broker status |

ADS-B expires after 90 seconds without a new qualifying in-range position.
AIS expires after 180 seconds. A positively observed target outside the
radius + 2 km is cleared immediately. An announced target is tracked across
normal SDRCC worker restarts. Clear messages have QoS 1 and are not retained.
