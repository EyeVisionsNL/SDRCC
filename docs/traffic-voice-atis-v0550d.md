# Traffic Voice ATIS decoder foundation — v0.55.0d

## Scope

This release adds passive decoding of inland-waterway Automatic Transmitter
Identification System (ATIS) bursts to the existing Marine Traffic Voice audio
path. It does not add a receiver, UDP listener, service, configuration authority
or AIS data store.

The first real validation source was a fixed-channel recording from V61 Sector
Botlek at 160.675 MHz. The decoder recovered:

- ATIS identity `9244089629`;
- MID `244` (Netherlands);
- converted call sign `PH9629`;
- format specifier `121`, end-of-sequence `127` and ECC `03`;
- a public AIS identity match to tanker `EVY`, MMSI `244003435`.

The complete 293-second recording produced exactly one ECC-valid packet. Only
synthetic protocol vectors are included in the repository validator; the user's
radio recording is not installed or stored in the project.

## Ownership

- RTLSDR-Airband remains the only SDR owner and audio producer.
- `core.traffic_voice_audio` remains the only UDP listener.
- `core.traffic_voice_atis` receives copied float32 blocks through a bounded,
  non-blocking in-process queue.
- Decoded results are ephemeral read-only observations.
- Receiver Manager, service control and `config/traffic_voice.yaml` remain
  unchanged.
- AIS-Catcher remains the only AIS and map authority.

## Decoder contract

The observer accepts a packet only after all of these checks succeed:

1. the 16-symbol ATIS phasing sequence matches;
2. every selected ten-unit symbol passes its three check bits;
3. the primary or time-diverse repeated symbol is usable;
4. the two format specifiers equal `121`;
5. the end-of-sequence symbol equals `127`;
6. the received and calculated vertical ECC agree;
7. the ten-digit identity starts with `9` and contains a valid second call-sign
   letter.

Validated state appears read-only under `atis` in `GET /api/traffic-voice`.
While Marine is selected, the existing `Possible speaker` field shows the most
recent fresh call sign. No speech recognition or probabilistic name guess is
performed.

## Deliberately deferred

- Correlation of the decoded call sign with live AIS-Catcher vessel data.
- Highlighting the matched vessel in the existing AIS-Catcher map.
- Durable ATIS history or logging.

Those functions require a separately validated read-only AIS correlation and
presentation contract.
