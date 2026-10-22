# SDRCC v0.56.0g — Mission Analytics RF Gain History

## Goal
Expose the RF gain that was recorded with each historical mission so reception results can be compared against the actual mission setting.

## Authority
No new storage or authority is introduced. Mission History remains the historical source. Analytics reads `gain_mode` and `gain_db` from the existing stored mission records returned by `/api/mission-history`.

## UI
- Peak SNR Trend shows receiver plus historical gain.
- RF Gain vs Peak SNR shows the recorded gain and peak SNR per mission.
- Mission Outcome Timeline also shows historical gain.
- Auto Gain is shown as `Auto Gain`; it is never presented as a fixed dB value.
- Older records without gain data show `Gain unknown`.

## Compatibility
No Mission Engine, Mission History schema, receiver authority, or RF execution logic is changed.
