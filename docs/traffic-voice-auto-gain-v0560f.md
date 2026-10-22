# SDRCC v0.56.0f — Traffic Voice native Auto Gain

Traffic Voice Marine and Aviation now expose the same operator-facing Auto Gain model used elsewhere in SDRCC.

The pinned RTLSDR-Airband 5.2.0 backend remains the sole Voice SDR owner. SDRCC keeps the upstream-required numeric `gain` field and uses `-1.0` only as an internal sentinel for automatic tuner gain. The patched native RTL-SDR input path maps a negative gain to `rtlsdr_set_tuner_gain_mode(..., 0)` and leaves every non-negative gain on the existing manual path (`rtlsdr_set_tuner_gain_mode(..., 1)` plus `rtlsdr_set_tuner_gain`).

The original 5.2.0 source archive and commit provenance remain unchanged in `/opt/sdrcc/traffic_voice/share`; `BUILD-PROVENANCE` records the additional SDRCC patch. The package rebuilds from that exact archived source and refuses a source SHA mismatch.

`gain_mode` is persisted in `config/traffic_voice.yaml`. Existing configurations are migrated to `auto` without changing channel banks, scan exclusions, squelch, selected mode, assignments or manual gain value. Turning Auto Gain off restores the previously selected numeric gain.
