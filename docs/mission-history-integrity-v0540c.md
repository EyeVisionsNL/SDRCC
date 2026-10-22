# v0.54.0c – Mission History Integrity

## Scope

This release protects future mission results. It does not reconstruct, migrate
or restore previously missing Mission History records and it does not modify
existing `data/state/mission_history.json` content during installation.

## Authority

`core/mission_history.py` is the only storage authority for Mission History. It
owns:

- shared and exclusive file locking;
- strict JSON reads;
- idempotent deduplication by `mission_id`;
- a single retention limit of 500 records;
- atomic file replacement;
- filtering, statistics and deletion from one raw stored result model.

Mission Engine remains the Weather lifecycle and result producer. ISS Voice
Executor remains the ISS technical result producer. Both submit one completed
record to Mission History and never write the JSON file directly.

## Result meaning

Stored producer results are immutable in meaning. Readers, APIs, Mission
Operations and dashboard detail views do not run them through LRPT
classification again.

- Weather/SatDump result classification remains in `core/mission_result.py` at
  Weather mission completion.
- ISS Voice `SUCCESS` means that the technical IQ/WAV recording completed.
- ISS audio content is stored as `UNASSESSED`; noise energy is not interpreted
  as speech.
- Decoder, image and LRPT SNR quality fields are not applicable to ISS Voice.

## Failure behaviour

Malformed or unreadable existing History is never treated as an empty list. A
new write is rejected so valid or recoverable bytes cannot be silently erased.
The API reports the storage error, while Mission Engine runtime status remains
available with an explicit `history_error` field.

## Validation

`scripts/validate_mission_history_integrity_v0540c.py` runs completely offline
against temporary state and verifies concurrent writers, idempotency, strict
corruption handling, delete integrity, a single API snapshot, stored ISS
results, filter/statistics behaviour and the Mission Recordings limit fix.
