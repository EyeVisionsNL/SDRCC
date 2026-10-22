# SDRCC v0.46.0a — ISS Voice Foundation

This release activates ISS Voice as a registered, assignable plugin while
remaining deliberately non-operational.

## Included

- active `iss_voice` plugin metadata;
- assignment role selectable as `sdr1` or `sdr2` through the existing generic
  assignment configuration path;
- dedicated `config/iss_voice.yaml`;
- 437.800 MHz NFM repeater profile;
- Route A metadata: wideband IQ capture with Doppler tracking;
- fail-closed execution and receiver claim;
- validation script.

## Explicitly not included

- Mission Queue insertion;
- receiver reservation;
- SDR process launch;
- audio recording;
- Doppler correction runtime;
- changes to Weather/SatDump satellite planning.

Those operational changes belong to later, separately validated releases.
