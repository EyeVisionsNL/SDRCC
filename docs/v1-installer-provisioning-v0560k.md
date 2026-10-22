# SDRCC v0.56.0k — v1.0 External Provisioning

This stage extends the v1.0 installer foundation with explicit provisioning for the third-party radio applications that SDRCC delegates to.

## Reference stack

- SatDump: Ubuntu package (`satdump`, `satdump-data`). On Ubuntu 26.04 this is 1.2.2+gb79af48-2.
- readsb: `wiedehopf/readsb`, pinned to commit `cc0d099`, built as a Debian package with RTL-SDR support.
- AIS-catcher: official installer pinned to release tag `v0.70` in the raw URL.
- AIS-catcher-control: official installer; the downloaded script must still declare release `v0.1` before it is executed.
- RTLSDR-Airband: tag `v5.2.0`, exact commit `61c5c4061967752da6b491a924664d72184b38fa`, native RTL-SDR/NFM build with the existing SDRCC v0.56.0f Auto Gain patch.

## Authority boundary

Provisioning installs software only. It does not create a second receiver/service authority. At the end, readsb, AIS-catcher, AIS-catcher-control and Traffic Voice are disabled/stopped. SDRCC retains the existing dashboard systemctl path and Receiver Manager/handover policy.

## Safety

`provision_external.sh --check` is read-only. `--plan` prints the pinned plan. The project `install.sh --skip-third-party` can be used only when the complete reference stack is already installed and passes the check.

The v0.56.0k stage does not yet promise a fully unattended AIS managed-mode first-run configuration. That is deliberately reported at installer completion rather than hidden behind guessed AIS settings.
