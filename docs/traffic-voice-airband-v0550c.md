# SDRCC v0.55.0c — Airband Voice execution

## Scope

This release enables the existing `airband_adsb` Traffic Voice mode. It reuses
the same `sdrcc-traffic-voice.service`, RTLSDR-Airband 5.2.0 binary, localhost
UDP audio bridge, Receiver Manager handover and station assignment authority as
Marine Voice. It introduces no second SDR owner, reservation manager or service
controller.

## Mode contract

- Marine Voice uses NFM on the receiver opposite the current AIS assignment.
- Airband Voice uses AM on the receiver opposite the current ADS-B assignment.
- The inactive continuous traffic service is stopped before Voice starts.
- Both modes use the pinned NFM-enabled backend build. Its compile-time audio
  rate is 16 kHz for AM and NFM output.
- Airband uses the 13 configured Zestienhoven and aviation favourites,
  including the stored 8.33 kHz channel designators and exact SDR carrier
  frequencies.

## Transaction and recovery

The first Start action stores the previous AIS, ADS-B and Voice service states
plus the previous Traffic Voice assignment before any mutation. A direct
Marine/Airband switch stops Voice, changes the traffic context, moves the Voice
assignment, selects the modulation profile and restarts Voice as one bounded
transaction. The original session baseline is retained across every switch.

If a switch fails, the preceding selected mode, service states and assignment
are restored. `Stop Voice` always restores the topology captured before the
first Start. Incomplete restoration leaves the durable session record in place
so Stop can retry.

Receiver Manager remains handover authority. Start, switching, Stop and live
settings changes are blocked while a receiver is reserved, and the existing
handover restore intent is never replaced by Traffic Voice.

## User interface

The page exposes separate `Start Marine + AIS` and `Start Airband + ADS-B`
actions. When the other mode is already running, either Start action performs a
direct transaction-safe switch. Receiver controls and the clickable activity
list always follow the selected mode. For 8.33 kHz airband channels the channel
designator and exact carrier are both displayed.
