# v0.48.0a — Flexible Mission Execution & Mission Recordings

This release enables the existing ISS Voice wideband-IQ backend as an automatic Mission Queue executor.

## Ownership rules

- Mission Queue selects the configured receiver.
- Receiver Manager remains reservation authority.
- The executor discovers active conflicting services from the receiver/plugin assignments.
- Only services that were active and actually stopped are restored.
- No AIS or ADS-B service name is hardcoded in the executor.
- Receiver release and service restore run after success and failure.

## ISS result

The mission stores `recording.iq`, `capture.json`, `audio.wav` and audio metadata below `data/recordings/iss_voice/<mission_id>`.

## Mission Recordings

The former Images tab is renamed Mission Recordings. It retains Weather image rendering and adds browser playback for mission audio. The API inventories supported image and audio files below `data/recordings`.
