# SDRCC 0.58.0-r2 — compare Marine Traffic noise suppression

This is an opt-in offline experiment. The dashboard keeps the established
Off / Light / Normal / Strong filters. ATIS, receiver gain, squelch, de-emphasis
and channel bandwidth are unchanged. No denoiser is loaded by the live dashboard.
We have not yet selected a denoiser for production: that requires real marine
speech comparisons, especially weak signals, ship names and numbers.

## Prepare an existing station

Run as the normal SDRCC user:

```sh
cd ~/SDRCC
git pull --ff-only origin develop
./install.sh --audio-comparison
```

This dedicated installer mode bypasses reinstall/update and station setup.
It installs the Ubuntu packages `libspeexdsp1`, `ffmpeg`, `git`, `curl`,
`ca-certificates` and `build-essential`, then builds a private RNNoise library
with its embedded model. It neither starts nor stops receiver services.
The build and dependency downloads need internet; recording and denoising are local.
A normal clean install does not install comparison dependencies until this option
is requested. Run `./install.sh --audio-comparison --check` for a read-only check.

## Record once, produce four variants

Select Marine Traffic and start Voice in the dashboard. Leave it running:

```sh
./venv/bin/python scripts/compare_marine_audio.py --record 60
```

The recorder connects to the local SDRCC WAV endpoint with `speech_filter=off`.
It takes one of the three browser-audio client slots, never a second SDR handle.
The recorded signal still contains the existing receiver de-emphasis and squelch;
“original” means before the additional browser speech filter, not raw I/Q.
Keep Marine Traffic selected while recording. Choose a busy minute; record again
if nobody spoke. The command supports 5–300 seconds. It cannot recover missed
scan traffic. It exits with an error if the stream ends or its format is wrong.

The printed folder under `data/audio-comparison/` contains:

| File | Processing |
| --- | --- |
| `01_original.wav` | Original stream plus a common 100 ms silent tail |
| `02_strong.wav` | Current 2.4 kHz Strong filter |
| `03_strong_speex.wav` | SpeexDSP (maximum noise attenuation −12 dB), then Strong |
| `04_strong_rnnoise.wav` | RNNoise, then Strong |
| `comparison.json` | Settings, library provenance, execution times and failures |

SpeexDSP works at 16 kHz. RNNoise processes 48 kHz mono frames, with FFmpeg
resampling from and back to 16 kHz. Both candidates use the same final Strong
filter. Output volume is not normalized; a quieter output is not automatically
better. A common 100 ms tail allows processing buffers to drain. Small algorithmic
delays remain; these are playback comparisons, not sample-aligned difference tests.

For an existing uncompressed mono PCM16 16 kHz WAV (maximum five minutes):

```sh
./venv/bin/python scripts/compare_marine_audio.py --input /path/to/marine.wav
```

Listen to exactly the same words in all versions. Assess hiss, intelligibility,
missing syllables, metallic artifacts and the start/end of each transmission.
Keep the original. Real station recordings have not yet been evaluated.

## Dependency and update behavior

RNNoise v0.2 commit: `904a876dce1f9ab8860c0a5000ed151f9f6eef58`.
Model: `rnnoise_data-0b50c45.tar.gz`.
SHA-256: `4ac81c5c0884ec4bd5907026aaae16209b7b76cd9d7f71af582094a2f98f4b43`.
The private portable shared library, embedded model, license and provenance live
under `data/audio-comparison/runtime/`; there is no extra daemon or GPU requirement.
The build uses the upstream v0.2 library source list and a checksum-verified model.
Re-running preparation skips a compatible installed runtime. A successful rebuild
retains the old runtime under `previous-runtime`.

Both the manual updater and the updated dashboard updater refresh dependencies
only if this experiment was already installed. Failure warns and leaves ordinary
speech filtering available. The dashboard helper performs this before stopping
SDRCC. An already-installed older updater acquires this behavior only after that
helper has itself been updated; the explicit setup command above works immediately.
The dashboard update button still follows main, not this develop-only release.

Missing native libraries are reported as unavailable candidates, not replaced
with misleadingly labelled original audio. Original and Strong remain saved.
The comparison command returns a failure status when either candidate is missing.
No library is required to start SDRCC. System packages are shared and are not
automatically removed with the experiment; private runtime files are under data.

## Validation

```sh
./venv/bin/python scripts/validate_audio_comparison_v0580.py --runtime data/audio-comparison/runtime
./venv/bin/python scripts/validate_marine_speech_filter_v0580.py
```

Validation covers native processing, silence, partial frames, output length,
missing libraries, input validation, interrupted capture, unfiltered recording,
read-only dependency checks and opt-in refresh behavior. The existing ATIS
regression remains separate. Native tests were run in the development container
with SpeexDSP 1.2.1 and the pinned RNNoise v0.2 model. The Ubuntu apt installation
could not run there because the container does not support apt's UID switching;
a full clean-station install remains to be checked on Ubuntu.

Upstream references:
- https://github.com/xiph/speexdsp
- https://github.com/xiph/rnnoise/tree/v0.2
- https://github.com/rtl-airband/RTLSDR-Airband/wiki/Audio-filters-in-MP3-outputs
