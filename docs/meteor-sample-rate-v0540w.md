# v0.54.0w — METEOR Sample Rate Correction

## Scope

Both enabled METEOR LRPT profiles now use `1024000` samples per second. This is
the command-line equivalent of SatDump's `1.024 MSPS` selection and is shown by
Mission Operations as `1024 kS/s`.

## Authority and data flow

- `config/satellites.yaml` remains the only METEOR sample-rate authority.
- `core/passes.py` copies that value into the planned pass.
- `core/satdump.py` passes it unchanged as `--samplerate 1024000`.
- Mission Operations observes the active value and formats it as kS/s.

No API, state machine, receiver assignment, service lifecycle, RF gain, AGC,
bandwidth, pipeline, frequency, or decoder behavior was added or changed.

## Validation

`scripts/validate_meteor_sample_rate_v0540w.py` verifies both profile values,
the unchanged pipeline and decoder identities, the SatDump command for each
METEOR satellite, runtime telemetry propagation, and the existing `1024 kS/s`
display conversion.
