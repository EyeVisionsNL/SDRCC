# FlexGround SDR v0.56.0w – Traffic Voice scan speed

Traffic Voice can now adjust the RTLSDR-Airband scan interval from the receiver controls.

- Slider: **Scan speed**, directly below Squelch.
- Range: **100–500 ms per channel**, in 50 ms steps.
- Default: **200 ms/channel**, preserving the pinned RTLSDR-Airband 5.2.0 behavior.
- Lower values scan faster.
- The value is persisted in `config/traffic_voice.yaml` as `backend.scan_interval_ms`.
- A bounded source patch adds the `scan_interval_ms` setting to the pinned RTLSDR-Airband 5.2.0 build.
- The existing Receiver Manager and Traffic Voice service restart/rollback transaction remain the runtime authority.

## Validation before commit

```bash
git diff --check
git diff
python3 scripts/validate_traffic_voice_scan_speed_v0560w.py
python3 scripts/validate_traffic_voice_controls_v0550b.py
python3 scripts/validate_traffic_voice_scan_exclusions_v0560e.py
python3 -m compileall -q core dashboard
./scripts/install/rebuild_rtlsdr_airband_scan_speed.sh
```

Then test Traffic Voice with Scan all channels at 200 ms/ch and 100 ms/ch. Confirm signal hold, audio, AIS/ADS-B context, Stop/restore and a mode switch before committing.
