# v0.47.1b – Receiver Runtime & Service Control

The Radio page no longer exposes the legacy Receiver Roles configuration form.
Mission receiver assignments and receiver default contexts are managed exclusively
through the Mission Assignments & Receiver Defaults card introduced in v0.47.1a.

The former Receiver Roles card is retained as an operational service-control card:

- read-only AIS and ADS-B runtime status;
- manual Start and Stop controls;
- no receiver assignment writes;
- no automatic service changes during installation.

The legacy receiver-role API routes remain temporarily available for compatibility.
They are no longer called by the Radio page.
