# SDRCC 0.59.0

Stable release of the tested 0.58 development audio features, on main and develop.

- Keep both SpeexDSP and RNNoise selectable, as well as no denoising.
- Speech filtering remains independently selectable (off/light/normal/strong).
- Remember listening preferences separately for Marine and Airband.
- Process listening audio per browser; preserve the original ATIS input.
- Install audio dependencies through install.sh and the managed updater.

The update button recognizes both 0.57.0 and 0.58.0-r3 as older releases.
An older installed update worker can deploy 0.59.0 without installing its new
audio libraries. After that explicitly requested update, the new dashboard
automatically starts one completion pass. If it fails or the dashboard is opened
more than 15 minutes later, use **Complete audio setup** to retry. The completion
pass validates the source and receiver state, and does not redeploy or restart
SDRCC. Stop active receiver work before updating or completing installation.
Already installed libraries are reused. Audio-library failure leaves speech
filtering available and exposes completion through the update panel.

Release checks cover version ordering, same-version completion, failure handling,
browser continuation without retry loops, and source compatibility against the
published main and develop trees. These checks simulate the update flow; actual
systemd restart and package installation require validation on the receiver host.
