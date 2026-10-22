# SDRCC develop: quicker first installation

This beta work simplifies the **fresh-install** path; `main` and the existing managed updater remain unchanged.

## What happens on a clean Ubuntu installation?

1. Run `./install.sh` as a normal user, **without** `sudo` in front.
2. Select the three install-time features: satellite reception, Traffic Voice/ATIS and Radio Receiver.
3. Finish the AIS-catcher browser wizard (select one active RTL-SDR input, account and sharing/output settings). **An RTL-SDR serial number is optional**: AIS-catcher can use automatic receiver selection, and you can adjust SDRCC receiver bindings later. SDRCC tries to open the wizard on Ubuntu Desktop; server/remote sessions get a URL. After **Save & Close**, click **Verify AIS setup** in the graphical installer (or press Enter in CLI mode). The wizard must be saved; a missing input or explicit `UNBOUND` placeholder is not accepted. Use `d` in CLI mode to defer AIS.
4. Open the SDRCC dashboard on port `8080`. Under **System → Advanced Maintenance → Home Position**, enter the station name, location, latitude, longitude and altitude, and save.
5. Bind SDR receivers from Receiver Manager. Position-dependent pass planning and AUTO scheduling are unavailable until a real position is saved.

**Do not enter coordinates for somebody else's location.** A fresh install sets `station.position_configured: false`, clears the repository's demonstration coordinates from its runtime station configuration and does not synchronise readsb until Home Position is saved. Position-dependent pass providers and the satellite overview are gated until then. Legacy sites without the marker are considered configured and keep their previous behavior.

For unattended installations, provide **all three** of `SDRCC_LOCATION`, `SDRCC_LATITUDE` and `SDRCC_LONGITUDE` to configure a known position immediately. `SDRCC_STATION_NAME` and `SDRCC_ALTITUDE_M` are optional; incomplete coordinate input fails explicitly.

## Testing on develop

- Run `python3 scripts/validate_installer_step1.py` on a checkout with PyYAML installed.
- Fresh install: no coordinate questions, verify HOME POSITION NOT SET in the terminal.
- Check Maintenance initially shows empty latitude/longitude with a visible warning.
- Before saving Home Position: check satellite pass predictions and scheduler AUTO cannot use `0,0` or demo coordinates.
- Save the real Home Position, verify readsb sync, Radio View refresh, and normal satellite planning.
- On Ubuntu Desktop, check that the AIS-catcher wizard is opened in the browser; on Ubuntu Server, verify the printed HTTP link works.
- Check AIS password, sharing, receiver selection **without a serial number**, Save & Close, Verify, receiver service handover, and subsequent SDRCC binding changes.
- Check `./install.sh --ais-setup` still resumes AIS only and an already-installed SDRCC still redirects to its managed updater.
- Check the updater's SHA-256 manifest before deploying a beta.

**Keep this on develop until a clean-machine hardware test succeeds.**
