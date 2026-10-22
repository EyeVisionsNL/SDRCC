# FlexGround autostart guard — v0.56.0s-r1

Advanced Maintenance contains a `FlexGround test mode` action for temporarily
disabling boot autostart of `sdrcc.service`.

The action does not use `--now`, so the dashboard handling the request stays
running. After a reboot FlexGround must be restored from a terminal with:

```bash
sudo systemctl enable --now sdrcc.service
```

The dashboard delegates the privileged change to the root-owned, argument-free
`/usr/local/sbin/sdrcc-disable-self-autostart` helper. Its sudoers rule grants no
general systemctl access.
