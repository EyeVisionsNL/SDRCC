# AIS autostart guard — v0.56.0r-r1

Advanced Maintenance now contains an `AIS update protection` action. It is
intended for one use after an AIS-Catcher or AIS-Catcher Control update when
the third-party installer has enabled boot autostart again.

The action disables only:

- `ais-catcher.service`
- `ais-catcher-control.service`

It does not use `--now`, so neither current AIS reception nor the temporary
Control interface is stopped. The dashboard delegates the privileged change
to `/usr/local/sbin/sdrcc-disable-ais-autostart`, a root-owned helper without
arguments. The corresponding sudoers rule grants no general systemctl access.
