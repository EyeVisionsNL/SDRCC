# SDRCC v0.54.0g — Radio Control Clarity and ISS Voice Squelch

## Scope

This release makes Radio Control the single page for receiver observation,
assignment and RF/audio configuration. It does not add scheduling, mission,
receiver reservation or service-control authority.

## Retained operational sections

- Receiver Monitor: daily traffic and receiver overview.
- Receiver Runtime Diagnostics: read-only authority, reservation, mission and
  observed-service diagnostics.
- Receiver Assignments: the existing Assignment Authority and transactional
  service synchronization.
- Weather / METEOR Settings: existing RF and SatDump options.
- ISS Voice Settings: tuner gain and RF-power squelch for live and archived
  ISS audio.

## Removed Radio Control duplication

- SDR Status is removed because Receiver Monitor and Runtime Diagnostics expose
  the same state from more authoritative sources.
- Mission Monitor is removed because Mission Operations owns live mission,
  decoder, image, frame, CADU and SNR presentation.
- Live RF Console is removed from Radio Control because Mission Operations owns
  that live execution view. The existing Live RF backend remains available to
  its real consumers.

## ISS Voice settings

The existing wideband IQ recorder already accepts a bounded tuner gain. The new
settings API exposes automatic or supported manual tuner gain without changing
receiver ownership.

Squelch is implemented as one RF-power gate shared by:

- the live browser WAV stream;
- the final offline-demodulated WAV recording.

The gate uses IQ power instead of browser volume or quiet audio amplitude. It
adds hysteresis, a short hang time and fades to avoid chatter and clicks.
Squelch is disabled by default, preserving existing ISS audio until the
operator explicitly enables it. Settings cannot be changed during an active
mission.

Browser playback volume remains exclusively in Mission Operations and is not a
receiver or demodulation setting.

## Authority boundaries

- Receiver Manager remains reservation and handover authority.
- Mission Engine and Scheduler remain mission and timing authorities.
- Dashboard service actions remain the existing service-control authority.
- `core/iss_voice_squelch.py` transforms captured samples only and starts no
  process, receiver, service or mission.
- No second audio capture, mission state machine, receiver state machine or
  service controller is introduced.

## Configuration compatibility

Existing `config/iss_voice.yaml` files remain valid without new keys. Safe
defaults are projected at read time. The four operator settings are written
atomically only after the operator presses **Save ISS Voice settings**.
