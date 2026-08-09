# SDRCC v0.54.0q — System Service Lifecycle Integrity

## r3 operational/maintenance separation

`ais-catcher-control.service` is the temporary web configuration interface on
port 8110, not an operational dependency of AIS reception. r1/r2 incorrectly
used the Receiver Manager handover group for normal System Start/Stop actions,
so **Start AIS** also launched the maintenance interface. r3 restores the
existing Plugin Registry distinction:

- normal AIS Start/Stop operates only `ais-catcher.service`;
- AIS-Catcher Control has its own Start/Stop controls under Advanced Maintenance;
- Receiver Runtime still observes both services because either can make the
  assigned receiver unavailable;
- Receiver Manager handover still stops Control before AIS-Catcher when a
  mission needs the receiver.

## r2 compatibility correction

The System observer names systemd's process identifier `main_pid`, while the
existing Receiver Authority interface consumes `pid`. v0.54.0q-r1 passed the
observer object through without that alias, causing both active services to be
verified against PID 0 and displayed as `ATTENTION`. r2 adds the compatibility
alias only at the existing System-to-Authority boundary. It does not weaken
serial verification or change any lifecycle action.

## Scope

This release repairs the System service-control lifecycle before the separate
System visual refresh in v0.54.0r. It does not add a service controller and it
does not change Mission Engine, Receiver Manager, assignments or RF settings.

## Audit result

| Concern | Existing owner | v0.54.0q change |
| --- | --- | --- |
| Physical receiver identity | Receiver Registry | Unchanged |
| Reservations and mission handover | Receiver Manager | Unchanged |
| AIS operational service metadata | Plugin Registry `services` | Normal System Start/Stop uses only AIS-Catcher |
| AIS receiver release metadata | Plugin Registry `handover_services` | Receiver Runtime and mission handover retain both services |
| Service execution | Existing dashboard `run_systemctl()` path | Executes operational and explicit maintenance actions |
| Runtime receiver serial | Receiver Authority | Reused as a readiness requirement |
| readsb runtime data | Receiver Monitor | Adds bounded file-age and current-process checks |
| System presentation | Existing `/api/status` projection | Adds lifecycle states and button capabilities |

## AIS lifecycle

- Normal Start/Stop controls only `ais-catcher.service`.
- `RUNNING` requires AIS-Catcher, disabled autostart and a verified receiver serial.
- AIS-Catcher Control never starts as a side effect of Start AIS.
- AIS-Catcher Control is explicitly started and stopped under Advanced Maintenance.
- Mission handover release order remains Control then AIS-Catcher.
- Receiver Runtime observes both; either active unit keeps the receiver unavailable.
- The installer disables autostart for both AIS units without stopping a running unit.
- Start and stop actions do not call `systemctl enable` or `systemctl disable`.

## ADS-B readiness

`readsb.service` being active is necessary but no longer sufficient. `RUNNING`
also requires:

- the configured SDR serial to match the active readsb command;
- current `aircraft.json` and `stats.json` files;
- both files to have been updated by the current service activation.

Aircraft count and message count are not health requirements. A quiet RF period
with zero aircraft remains a valid running receiver.

## Lifecycle states

- `RUNNING`: complete and verified runtime.
- `STOPPED`: the selected operational or maintenance service is inactive.
- `STARTING`: service active inside the bounded verification grace period.
- `PARTIAL`: retained as a compatibility presentation for bounded multi-service states.
- `ATTENTION`: service remains active or autostart-capable without complete verification.

## Failure behavior

A failed group command restores the service states observed before the action.
A successful start whose runtime cannot be verified is left active for diagnosis
and reported as `ATTENTION`; SDRCC does not perform an automatic second restart.

## Explicit exclusions

- No new service authority or persistent lifecycle state.
- No change to systemd unit files or restart policy.
- No automatic service startup on boot.
- No dependency on receiving aircraft or ships.
- No System theme changes; those remain v0.54.0r.
