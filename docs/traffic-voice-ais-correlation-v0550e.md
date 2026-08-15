# Traffic Voice ATIS to AIS correlation — v0.55.0e

## Scope

SDRCC correlates a freshly validated Marine ATIS call sign with the live vessel
list already published by AIS-Catcher. A successful result enriches `Possible
speaker` and enables `Show on full AIS map` in Traffic Voice.

## Authority boundary

- `core/traffic_voice_atis.py` remains a passive audio observer and knows
  nothing about AIS.
- `core/receiver_monitor.py` remains the only SDRCC reader of AIS-Catcher
  `ships.json`; metrics and correlation share its short-lived cache.
- AIS-Catcher remains the vessel-data and map authority.
- SDRCC creates no second map, AIS datastore, listener, service or receiver
  owner.
- The dashboard opens AIS-Catcher's full viewer in a new browser tab through
  the supported `?mmsi=<MMSI>&zoom=14` contract. It does not access the
  cross-origin iframe DOM.
- The standalone AIS-Catcher application keeps its own interface; SDRCC does
  not restyle or modify it.

## Traffic Voice status semantics

- `MARINE + AIRBAND READY` means both Traffic Voice modes are executable.
- `MARINE RUNNING` or `AIRBAND RUNNING` identifies the mode that is actually
  using the shared Voice service.
- `SELECTED · STOPPED` means the mode is retained as the next start choice but
  Voice is not running.
- `ACTIVE MODE` is shown only while the selected mode is actually running.
- `Receiver software` identifies the shared `RTLSDR-Airband 5.2.0` engine. The
  `AM/NFM` suffix makes explicit that the same pinned program handles both
  Airband AM and Marine NFM; it is not a separate active Airband mode.

## Fail-closed matching

A vessel is selected only when all conditions hold:

1. the ATIS result is fresh and contains a call sign;
2. exactly one live AIS record has the same trimmed, upper-case call sign;
3. AIS-Catcher reports `validated = 1`;
4. `last_signal` is between 0 and 30 seconds;
5. MMSI and latitude/longitude are valid.

No match, duplicate call signs, stale data, an unvalidated record or an invalid
position remain explicit non-matches. SDRCC never chooses the nearest vessel as
a substitute.

## Returned projection

The Traffic Voice API returns the bounded `ais_match` projection with status,
MMSI, ship name, ENI, position, distance, bearing, speed/course/heading,
destination and AIS signal age. It does not copy the complete AIS-Catcher
record or configuration.

## Validated live vector

The captured Rotterdam vector correlated ATIS call sign `PC4621` with exactly
one fresh AIS-Catcher vessel:

- ship: `MI-DESEO`;
- MMSI: `244670658`;
- ENI: `02327130`;
- position: `51.894627, 4.336788`;
- AIS signal age: 6 seconds.

The bundled validator also covers not found, ambiguity, stale data,
unvalidated records and invalid positions.
