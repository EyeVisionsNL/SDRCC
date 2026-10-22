# SDRCC v0.55.0a — Traffic Voice Foundation

## Release boundary

This release adds the configuration, metadata, receiver role, read-only API and dashboard shell for Traffic Voice Monitor. It deliberately adds no receive execution.

The two supported modes are:

| Mode | Voice profile | Modulation | Live context | Derived voice receiver |
|---|---|---|---|---|
| `marine_ais` | `marine_voice` | NFM | AIS | Receiver opposite the AIS assignment |
| `airband_adsb` | `airband_voice` | AM | ADS-B | Receiver opposite the ADS-B assignment |

Only one mode can be selected at a time. The initial mode is `marine_ais`.

## Authority contract

- `config/traffic_voice.yaml` owns Traffic Voice configuration only.
- `config/station.yaml:assignments` remains the sole persistent receiver-role authority.
- Receiver Registry remains hardware and serial identity authority.
- Receiver Manager remains reservation, handover and restore authority.
- The existing dashboard/systemd transaction remains the only service-control boundary.
- Plugin Registry remains metadata authority.
- Plugin Runtime and Traffic Voice Foundation remain read-only observers.

## Non-execution protection

In v0.55.0a the Traffic Voice plugin is `planned`, has no executor, declares no services and exposes no action endpoint or UI controls. The foundation must not:

- open an SDR;
- start a process;
- call `systemctl`;
- reserve or release a receiver;
- write assignments;
- persist runtime state.

The dashboard's channel-activity, audio and possible-speaker areas are explicit placeholders. They do not claim live RF or identity data.

## Initial receiver projection

The current assignments produce:

- Marine Voice + AIS: voice on SDR2, AIS context on SDR1.
- Airband Voice + ADS-B: voice on SDR1, ADS-B context on SDR2.

This mapping is derived from assignments and receiver identity; serial numbers are never hardcoded into Traffic Voice logic.

## Follow-up

`v0.55.0b` may enable Marine Voice only after RTLSDR-Airband packaging, local audio transport, channel-bank configuration and Receiver Manager handover/restore have separate contract coverage.
