# SDRCC 0.58.0-r3 — choose your listening audio

Marine and Airband now each have two independent browser preferences:

| Control | Options |
| --- | --- |
| Speech filter | Off, Light (3.8 kHz), Normal (3 kHz), Strong (2.4 kHz) |
| Noise reduction | Off, SpeexDSP, RNNoise |

Every combination is available in both modes. Preferences are saved per browser
and per mode. Existing Marine speech-filter preferences are migrated. Defaults
remain Marine Normal, Airband Off, and noise reduction Off in both modes.
Changing a control briefly reopens only that browser's audio stream. Switching
station mode loads the matching preferences and restarts an active listener.
A stopped listener stays stopped. Receiver settings are not changed.

The browser follows the station's selected mode; this does not enable Marine
and Airband reception simultaneously on the same receiver.

## Install on an existing develop station

```sh
cd ~/SDRCC
git pull --ff-only origin develop
./install.sh --audio-processing
sudo systemctl restart sdrcc.service
```

Reload the dashboard with Ctrl+F5. The dedicated installer option installs the
libraries without reinstalling the station or changing receiver configuration.
The older `--audio-comparison` option remains an alias. If you already installed
the comparison libraries, the same private RNNoise runtime is reused.

Normal clean installs now prepare both libraries. Both updated update paths
also prepare them; the dashboard updater does this before stopping SDRCC.
An older updater cannot acquire new preparation behavior until it has itself
been updated. Use the explicit setup command above for the first develop upgrade.
The update button still follows main; this release is develop-only.

The build uses Ubuntu libspeexdsp1 and pinned RNNoise v0.2 with a checksum-verified
embedded model. See the r2 comparison document for source/model checksums.
No new daemon or GPU is required. Initial provisioning requires downloads.
Normal listening performs no model downloads or external network processing.

## Processing and fallback

Each listener owns independent native state and bounded partial-frame buffers.
SpeexDSP processes 20 ms frames at 16 kHz with AGC disabled and maximum noise
attenuation of 12 dB. RNNoise processes 10 ms frames at 48 kHz; a continuous
63-tap windowed-sinc converter resamples the 16 kHz stream up and back down.
No FFmpeg subprocess is started for live audio. The existing offline comparison
still uses FFmpeg, so small differences from live resampling are possible.
Noise suppression runs before the selected speech filter. Buffer history is
reset on missing chunks and substantial gaps. Explicit mode-bound streams close
when the station changes mode (checked once per second).

The UDP listener, shared original PCM queue and float32 ATIS observer are
unchanged. Processing happens after the ATIS split, outside the queue lock.
This is listening processing only: it cannot improve RF reception or recover
transmissions missed by scanning.

If a library is missing, its option is disabled and the UI shows a warning for
a saved unavailable selection. The stream falls back to the chosen speech
filter. Runtime processing errors close the affected processor and also fall
back; warnings are exposed in audio status. Capability probes are cached for
30 seconds. A successful new processor clears the previous engine error.
Reopen listening after repairing a missing dependency.

## Validation and limits

```sh
./venv/bin/python scripts/validate_live_audio_v0580.py --runtime data/audio-comparison/runtime
./venv/bin/python scripts/validate_marine_speech_filter_v0580.py
node scripts/validate_audio_preferences_v0580.cjs
```

Native tests cover SpeexDSP/RNNoise, silence, arbitrary packet boundaries, all
speech filters in both modes, resampler continuity and speech-band gain, fallback
and client cleanup on mode changes. Browser logic tests cover per-mode saved
preferences, migration, stream parameters, unavailable engines, disabled storage
and stopped playback. ATIS byte delivery and decoding have separate regression
tests. Node is a development test tool, not an installation requirement.

Full Ubuntu package installation and sound quality with real station reception
still require station testing. The user decides which combination sounds best.
