# 🔧 Updates & help

## Update from SDRCC

In **System → Advanced Maintenance**, check the offered version and notes. Finish active reception before starting a managed update.

**Stable = main; Beta = develop.** Local station settings and receiver bindings are kept.

![Advanced Maintenance](https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/e807e4aa5ca56bb72dc76efbea117077be94ce0a/images/maintenance.webp)

## Quick checks

- **No dashboard:** Computer powered on, service running, correct IP and port.
- **Receiver missing/busy:** Check USB serial, System bindings, Traffic Voice and active missions.
- **No sound:** Browser audio permission, playback control, volume and squelch.
- **No vessel match:** A valid ATIS decode and current AIS data are needed; not every call matches.
- **Android maps blank:** Correct map URLs and enabled VTS sector / SDRCC ATIS plugins.
- **Satellite reception missing:** Mission status and logs, antenna, receiver and activity.
- **Remote access fails:** Tailscale connected on both computer and phone.

## Update failed?

For **“Update source hash is not approved”**, report the exact file, version and channel. Do **not** change hashes or bypass the safety check.

For a bug report, include the version, reproduction steps, expected/actual result and a screenshot or relevant log. Remove private data first.

![SDRCC logs](https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/e807e4aa5ca56bb72dc76efbea117077be94ce0a/images/logs.webp)

[Report a bug](https://github.com/EyeVisionsNL/SDRCC/issues) · [Questions and ideas](https://github.com/EyeVisionsNL/SDRCC/discussions)

To remove SDRCC, run `~/SDRCC/uninstall.sh` and follow its prompts.
