# SDRCC v0.46.0b – ISS Voice Wideband IQ Backend

This release adds a bounded, reusable `rtl_sdr` CU8 IQ recorder and a
`wideband_iq` execution-plan adapter. It does not yet connect ISS Voice to the
Mission Queue or automatically stop/restore AIS/ADS-B services. Doppler
correction and FM-to-WAV processing remain separate follow-up releases.

Safety boundaries:
- installer performs no RF capture;
- execution plan remains read-only and fail-closed;
- explicit capture requires `--execute --services-confirmed-stopped`;
- duration is bounded to 1–1200 seconds;
- output is restricted to `data/recordings`;
- no Git commit is made.
