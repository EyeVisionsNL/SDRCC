# 🔧 Updates and troubleshooting

## Update SDRCC

1. Open the desktop dashboard and go to **System → Advanced Maintenance**.
2. Check the offered version and release notes. Use the stable main channel for the stable release; develop contains changes under test.
3. Finish active reception work that should not be interrupted, then start the managed update.
4. Wait for the update result. Reopen or refresh the dashboard and check the installed version and service status.

The managed workflow preserves local station settings, receiver bindings and runtime data outside the code replacement path.

![Advanced Maintenance](https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/maintenance.webp)

## Find the right first check

| Symptom | What to check |
| --- | --- |
| Dashboard will not open | Computer powered on, SDRCC running, correct IP and port, reachable network |
| Receiver is missing | USB connection, detected serial and System receiver bindings |
| Receiver is busy | Active mission, Traffic Voice or Radio Receiver ownership in the dashboard |
| Receiver runs but there is no audio | Page playback control, browser audio permission, muted tab/system output and squelch |
| Voice is audible but no vessel match | Validated ATIS decode and available AIS vessel identity data; not every transmission yields a match |
| Android connects but maps do not | Each map URL under System → Settings → Map Connections, relevant map service and reachability |
| Sector or ATIS overlay is missing | Installed map plugins and selection of VTS sector / SDRCC ATIS |
| Works on Wi-Fi but not remotely | Tailscale connected on both devices; computer's Tailscale address used for station and maps |
| Satellite mission has no usable image/audio | Mission logs, actual reception window, receiver, antenna, gain and satellite transmission activity |

## An update failed

Copy the exact error and check the update log. For **Update source hash is not approved**, report the named file, current version and update channel so the release metadata can be checked. Do not edit hashes or disable verification as a workaround.

If a receiver or mission is reported as active, inspect Mission Control and the listening pages before retrying. Stop an active task through its normal controls. If the warning remains despite an idle station, include that in the report.

## Make a useful bug report

Include:

- SDRCC version and branch/channel; Android version if relevant.
- Ubuntu version and receiver model, plus the affected service.
- The steps to reproduce the problem.
- Expected result and actual result.
- Exact error, relevant log excerpt and a screenshot where useful.

Remove passwords, tokens and other private information from shared logs or screenshots.

![Logs](https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/logs.webp)

[Report a bug](https://github.com/EyeVisionsNL/SDRCC/issues) · [Questions and future ideas](https://github.com/EyeVisionsNL/SDRCC/discussions)

## Remove SDRCC

If you intend to uninstall, run **~/SDRCC/uninstall.sh** and read its prompts carefully. The receipt-aware uninstaller removes externally provisioned radio applications only when the installation receipt records that SDRCC installed them. Shared Ubuntu packages are preserved.

[[Home]] · [[Installation]] · [[Android companion]]
