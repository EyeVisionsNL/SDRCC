# v0.47.1c – Radio Control Cleanup

This release separates receiver configuration from operational service control.

## Radio Control

- Keeps Mission Assignments and Receiver Defaults.
- Keeps RF settings and receiver diagnostics.
- Removes the Receiver Runtime & Service Control card.
- Widens Mission Assignments & Receiver Defaults into the freed space.

## System

- Adds a Service Control card.
- Reuses the existing AIS and ADS-B Start/Stop actions.
- Reuses the existing service status elements and refresh logic.

## Runtime impact

- No backend route changes.
- No new service controller.
- No receiver assignment changes.
- No service is switched by the installer.
- No mission is started.
