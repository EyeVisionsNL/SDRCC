# SDRCC 0.58.0 — Marine Traffic speech filter

Marine Traffic browser audio now uses a 3 kHz, fourth-order Butterworth low-pass
filter to reduce high-frequency hiss during conversations. It is automatic in
marine mode; there is no extra dependency or receiver setting to configure.
This is speech-band filtering, not adaptive noise reduction: noise within the
speech band and weak reception can still be audible.

The filter runs per listening client, after the shared audio queue. The ATIS
observer still receives the original float32 UDP payload, byte for byte.
RTLSDR-Airband demodulation, 75 µs de-emphasis, gain and squelch are unchanged.
Airband playback bypasses the filter. Mode changes are checked once per second.
Filter state persists across audio chunks and resets on a mode change, a queue
gap or a listening gap longer than 0.5 seconds.

## Validation

Run `python scripts/validate_marine_speech_filter_v0580.py`.
It checks the 1/3/6 kHz frequency response, chunk continuity, filter reset,
raw ATIS delivery through the UDP listener, marine-only stream filtering,
airband bypass and synthetic ATIS decoding (including a damaged symbol).

The older `validate_traffic_voice_atis_v0550d.py` full runner has a stale
hard-coded module version assertion (0.55.0e). The new test calls its decoder
regression directly without changing that historical script.

Live acceptance: listen to several strong and weak marine conversations, check
speech intelligibility and continued ATIS detections, then compare airband.
The audible result still needs evaluation on the receiving station.

## Develop installation

This release is on `develop`. The dashboard update button currently follows
`main`, so it will not install this develop-only release yet.

```sh
cd ~/SDRCC
git pull --ff-only origin develop
sudo systemctl restart sdrcc.service
```

Restart browser listening after the service restart. Local station and receiver
configuration is not part of this change. The update manifest includes both
the original audio bridge hash and its new hash for subsequent updates.

## 0.58.0-r1 — adjustable listening filter

The Speech filter selector beside Browser volume offers Off (original audio),
Light (3.8 kHz), Normal (3 kHz, the 0.58.0 default), and Strong (2.4 kHz).
The choice is saved in browser local storage, with Normal as the default.
Switching briefly reopens only that browser's stream with the selected filter;
it does not restart the receiver or change ATIS input. Each client has its own
filter state. The selector is hidden for airband, which always bypasses filtering.
