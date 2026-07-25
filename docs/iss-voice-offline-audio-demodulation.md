# ISS Voice offline audio demodulation — v0.46.0d

This release converts an existing CU8 `recording.iq` into mono 16-bit PCM
`audio.wav` using NumPy and Python's standard `wave` module.

It does not reserve a receiver, stop/start services, schedule a mission, or
apply live Doppler correction. The endpoint is explicit and bounded to files
inside `data/recordings/iss_voice/<mission_id>/`.

Endpoint:

`POST /api/iss-voice/demodulate`

Payload:

```json
{"mission_id":"iss_controlled_YYYYMMDD_HHMMSS_xxxxxx"}
```

Outputs beside the IQ file:

- `audio.wav`
- `demodulation.json`
