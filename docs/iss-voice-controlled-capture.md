# v0.46.0c – ISS Voice Receiver Lifecycle & Controlled Capture

Adds one explicit POST-only, bounded IQ capture path. It is not connected to
Mission Queue or the automatic scheduler.

Authority boundaries:
- Receiver Manager owns reserve/activate/release.
- Dashboard `run_systemctl` remains the only service-control path.
- `controlled_iq_capture` receives service callbacks and contains no systemctl.
- Execution Journal observes ACCEPTED/STARTED/FINISHED/FAILED.

Endpoint:
`POST /api/iss-voice/controlled-capture`

Body example: `{"duration_seconds": 5}`. Allowed range: 1–30 seconds.
The assigned ISS receiver is used, active conflicting services are stopped and
restored, and the receiver is always released in `finally`.
