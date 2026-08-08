# SDRCC v0.54.0l — Mission Operations Integrity and Visual Clarity

## r2 follow-up

- Normalizes `receiver01` / `RX01` / `sdr1` to `SDR1` and `receiver02` / `RX02` / `sdr2` to `SDR2` in Mission Operations.
- Completes the approved SDRCC theme with stronger satellite-colour cards, result-status accents and metric tiles.
- Keeps APIs, mission ownership, recorder ownership, history classification and audio transport unchanged.

## Scope

Mission Operations remains a read-only live workspace and bounded result viewer. This release adds no receiver, scheduler, service, capture, decode, or Mission History authority.

## Authority map

| Presentation | Existing owner/source | v0.54.0l rule |
|---|---|---|
| Active Weather mission | Mission Engine + `live_rf` | Only active state is projected; stale completed RF state is rejected. |
| Active ISS mission | `iss_voice_runtime` | Existing executor observation remains authoritative. |
| Receiver reservation | Receiver Manager | Display-only; identity resolves through the existing Receiver Manager projection. |
| ISS IQ progress | Existing IQ file + `iss_voice_audio_monitor` | Read-only file observation; no receiver or process is opened. |
| ISS live audio | Existing `iss_voice_audio_monitor` stream | Tails the single active IQ capture; maximum three browser listeners. |
| Weather preview | Existing `/api/mission-monitor` | Live image during Weather, latest successful image while idle. |
| Stored files | Existing Mission Recordings inventory | No new file index or writer. |
| Result metadata | Existing Mission History | Presentation lookup only; no reclassification or write. |

## Integrity corrections

- Removed `last_result` from the live mission projection. An old ISS result can no longer combine with stale METEOR RF fields and appear as a fictitious Weather/SatDump mission.
- ISS recorder state now follows the IQ capture lifecycle rather than the browser audio stream state.
- Weather no longer shows fabricated `0 B` capture and write-rate values that have no Live RF source.
- Scheduler phase is displayed from the Scheduler observer instead of repeating mission state.
- Weather decoder metrics remain visible only for active Weather missions; ISS shows the dedicated IQ/audio view.
- `Clients` moved out of general Runtime and is now `Audio listeners`, displayed as active/maximum only in ISS Live Audio.
- Nested products such as `MSU-MR` display their owning Mission History ID in the result list.
- Selected result and highlight survive inventory refresh.

## Duplication cleanup

- `capture_live.js` is no longer loaded. It duplicated existing dashboard and Mission Briefing image refreshes and could overwrite the selected Mission Operations result.
- Generic `capture.js` no longer writes to the Mission Operations selected-result viewer.
- The old Weather image pipeline footer was removed because Live/Latest Preview already owns that presentation.
- Mission Operations API polling now runs only while the tab is visible.

## Visual contract

- Same dark navy foundation as Mission Planner and Mission Analytics.
- METEOR-M2 3 cyan, METEOR-M2 4 purple, and ISS yellow.
- Green for ready/success, amber for transitional attention, and red for live/error states with explicit labels.
- Balanced live workspace and result library/detail grids.
- ISS Live Audio replaces Weather Preview during an active ISS mission, keeping mission-specific controls together.
