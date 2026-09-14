# SDRCC — SDR Control Center · v0.56.0x

The project returns to the name used by its community: **SDRCC — SDR Control Center**.

The dashboard banner, startup splash, browser title, favicon, README, Logs label,
maintenance controls and messages now use SDRCC. The original `sdrcc.png` logo and
`sdrcc-favicon.png` are reused. The existing space/satellite banner artwork and
navigation remain intact. Browser asset version keys refresh the renamed controls.

Fresh installations offer `SDRCC` as the station-name default. Explicit station
names and existing configuration are preserved. Installer/uninstaller output,
systemd descriptions and Traffic Voice workbook instructions use SDRCC. The CLI
reads the current release from `VERSION`, replacing its stale hard-coded version.

## Compatibility

Receiver ownership, mission execution, service names, API paths, configuration
keys, saved settings and the repository URL are unchanged. Existing channel
workbooks still import. The AIS auto-window name, AIS managed-mode drop-in and
external-configuration backup suffix retain their previous internal identifiers
so an existing session, installation or uninstall keeps using the same resources.

Historical release notes, screenshots and unused legacy assets remain available
as records of earlier releases. The README banner shows the current identity.

## Update an existing Git checkout

With active missions and live receiver sessions stopped, run these commands as the
normal installation user from a v0.56.0w checkout. `git pull --ff-only` uses the
checkout's existing tracked branch. Resolve any reported local source conflicts
before continuing; keep your local configuration.

```bash
cd ~/SDRCC
git pull --ff-only
sudo install -o root -g root -m 0755 scripts/sdrcc_disable_self_autostart.py /usr/local/sbin/sdrcc-disable-self-autostart
sudo sed -i 's/^Description=FlexGround SDR - Flexible SDR Ground Station$/Description=SDRCC - SDR Control Center/' /etc/systemd/system/sdrcc.service
sudo sed -i 's/^Description=FlexGround SDR Traffic Voice Monitor (RTLSDR-Airband)$/Description=SDRCC Traffic Voice Monitor (RTLSDR-Airband)/' /etc/systemd/system/sdrcc-traffic-voice.service
sudo systemctl daemon-reload
sudo systemctl restart sdrcc.service
cat VERSION
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/status
```

Expected: `0.56.0x`, HTTP `200`, and the SDRCC banner and original logo after a
browser reload. The two description replacements preserve every other unit
setting. No backend rebuild is required specifically for this naming release;
the v0.56.0w scan-speed backend requirement still applies.

## Rollback

If `HEAD` is still the v0.56.0x naming commit and no later changes have been made,
revert that commit locally with `git revert --no-edit HEAD`, reinstall the helper
with the same `sudo install` command above, and restart `sdrcc.service`. This
reverts the application changes without replacing station configuration. For
full label rollback, restore the two unit descriptions to their previous values
and run `sudo systemctl daemon-reload`.

## Validation

- Python compilation, JavaScript and shell syntax, full diff review.
- Existing startup/banner, navigation, Logs and autostart regression checks.
- Headless Chromium checks and visual inspection of the desktop/mobile banner
  and startup screen, including the original logo and JavaScript runtime.
- Actual `install.sh` runs through station configuration, systemd rendering and
  completion with package/service/hardware boundaries simulated: interactive
  default, non-interactive default and an explicit custom station name.
- AIS wizard and installer resume tests (14 cases); actual isolated uninstall
  runs including preservation and restoration of pre-existing external software.
- CLI header, current workbook export and legacy workbook import.
- Flask dashboard, logo, favicon, Logs and idle status endpoints.

These are software and isolated workflow checks; no physical SDR reception was
performed for this presentation change.
