# SDRCC v0.55.0c-r3 — balanced Traffic Voice layout

This correction makes Marine Voice and Airband Voice equal first-class
workspaces without adding a second control authority.

## Layout

- The Marine card owns the Marine start action and all 27 Marine channels.
- The Airband card owns the Airband start action and all 13 aviation channels.
- Both channel lists have the same visible height and scroll independently.
- Only the selected mode has clickable channel rows and live measurements.
- Receiver tuning, gain, squelch, audio and Stop remain one shared workspace.
- The mostly duplicated Selected Configuration card has been removed; its
  relevant runtime facts remain in the shared workspace.

## Channel-bank names

The user-facing banks are now `Rotterdam Port` and `Rotterdam Aviation`.
Personal naming is not used in configuration, documentation or validation.

## Architecture

No API, service, receiver authority or handover lifecycle was added. Both
workspaces consume the existing `/api/traffic-voice` mode list. All mutations
continue through the existing `/api/traffic-voice/action` route and the single
`config/traffic_voice.yaml` authority.
