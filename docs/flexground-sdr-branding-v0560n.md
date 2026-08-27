# FlexGround SDR v0.56.0n — Branding Foundation

## Decision

The public project identity is **FlexGround SDR** with the descriptor
**Flexible SDR Ground Station**. The former public name, SDR Control Center
(SDRCC), is retained as a documented legacy identity.

## Changed presentation

- dashboard browser title, header, startup splash and status bar;
- application logo and favicon;
- README project introduction and current development line;
- CLI and systemd descriptions;
- dashboard log-source label and user-facing operational text;
- Traffic Voice spreadsheet/export branding.

## Compatibility retained

This release does not rename or migrate runtime authority. The following remain
unchanged deliberately:

- `sdrcc.service` and `sdrcc-traffic-voice.service`;
- `/home/eyevisions/SDRCC` and `/opt/sdrcc` paths;
- `SDRCC_ROOT` and other established environment variables;
- `sdrcc` CLI filenames and privileged helpers;
- browser event names, local-storage keys and log-source API identifiers;
- the existing `EyeVisionsNL/SDRCC` repository URL;
- configuration schemas, API routes, receiver identity and mission ownership.

Historical architecture and release documents retain their original SDRCC
wording because it identifies the version and contracts described at that time.

## Authority and duplication audit

No new state, service controller, API, backend module or source of truth is
introduced. The change is presentation-only. Receiver Registry, Receiver
Manager, Mission Engine and plugin/runtime ownership remain unchanged.
