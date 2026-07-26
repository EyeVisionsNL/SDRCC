# v0.48.0a-r2 — Unified Mission Preflight

This correction removes the ISS Voice shortcut around the normal mission preparation boundaries.

ISS Voice now emits and enforces:

1. queue selection (existing Automation event),
2. mission-specific preflight at the configured preflight boundary,
3. configured receiver preparation at the normal prepare boundary,
4. receiver reservation at the normal lock boundary,
5. executor start at AOS only after a successful lock.

The ISS executor reuses the same reservation key established by the autopilot. It remains receiver-assignment driven and contains no hardcoded AIS or ADS-B service choice. Weather keeps its existing preparation and SatDump path unchanged.
