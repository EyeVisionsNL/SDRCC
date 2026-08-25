# SDRCC v0.56.0i — Runtime Storage & Log Retention

This release bounds runtime storage without introducing a new storage authority.

- ISS Voice keeps `audio.wav`, `capture.json`, demodulation metadata and Mission History.
- `recording.iq` is removed only after WAV validation and successful receiver-context restoration.
- Failed or incomplete missions retain raw IQ for diagnosis.
- `iss_voice.storage.keep_raw_iq: true` disables automatic IQ removal.
- Existing Mission History deletion remains the manual whole-mission deletion authority.
- `logs/sdrcc.log` rotates at 10 MiB with three retained backups.
