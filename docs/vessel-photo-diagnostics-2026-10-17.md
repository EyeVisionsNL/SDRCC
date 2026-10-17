# Vessel photograph lookup: root-cause investigation (2026-10-17)

## Symptom

SDRCC Traffic Voice matched the correct AIS vessels to ATIS, but showed “No vessel photo found” for INVOTIS VII (244740814), KOSTRA 3 (244660735), GROENENDAAL (244029535), and DEROVA (205580990), despite published photographs.

## Verified root causes

- Shipspotting returned **HTTP 403** for automated Shipspotting search and detail requests from the GitHub-hosted test runner. This is specific to that client/location; it does **not** prove the SDRCC host has the same problem. Do not attempt to bypass access restrictions.
- The previous De Binnenvaart integration used `https://www.debinnenvaart.nl/schepen_a_z/` and `/schip_detail/`, which returned **HTTP 404**.
- The publisher's current website `https://debinnenvaart.nl` is a JavaScript client backed by public read-only metadata endpoints `/api/schepen?q=<name>` and `/api/schepen/<id>`. The old HTML parser never saw those records.
- Previous MMSI-specific exceptions were symptoms, not a scalable solution. The old scraper was retired.

## Implementation (develop v0.67.16)

- `core/traffic_voice_debinnenvaart_api.py` queries the current public JSON endpoints and finds **one unique, current** ship name; optional AIS ENI must match and disagreed identifiers are rejected.
- Result-set pagination is bounded. Incomplete or ambiguous searches return no photo.
- The ship detail JSON must refer to the selected record, and the photo must be approved, individually credited, linked to that same ship and hosted on a published first-party photo domain.
- The former `core/traffic_voice_debinnenvaart.py` is now a compatibility import. Shared `core/traffic_voice_vessel_photo.py` still calls De Binnenvaart **last** after Mark Prummel, Binnenvaartspotter, Shipspotting and Wikimedia Commons.
- A cache policy increment discards previously cached “not found” responses.
- Browser and Android mobile app share the same backend route, with photographer and original-page link. Existing watermarks remain unmodified; the publisher's name is hidden in the photo credit UI.
- The source adapter fetches metadata only; image display is handled by the browser from the publisher's URLs.

## Validation

Offline CI: [SDRCC Mobile UI validation](https://github.com/EyeVisionsNL/SDRCC/actions/runs/39051852790) — passed.

Bounded live read-only source check: [Live photo API diagnostic](https://github.com/EyeVisionsNL/SDRCC/actions/runs/39051976648) — passed.

Live API results:

| Vessel | MMSI | First verified photographer returned | Current source profile |
| --- | --- | --- | --- |
| INVOTIS VII | 244740814 | Kor Heidinga | https://debinnenvaart.nl/schip/15560 |
| KOSTRA 3 | 244660735 | Ruud Zegwaard | https://debinnenvaart.nl/schip/14304 |
| GROENENDAAL | 244029535 | Roland Hesse | https://debinnenvaart.nl/schip/groenendaal |
| DEROVA | 205580990 | Gerd Schuth | https://debinnenvaart.nl/schip/derova |

The live check confirms *retrieved photo metadata and URLs*. It is not a browser/image-load or installed-mini-PC integration test. Those still require user validation via the Update Manager and Traffic Voice.

## Regressions

`scripts/validate_debinnenvaart_photo.py` tests identity ambiguity, historic names, mismatched ENIs, incompatible URLs, uncredited/unauthorized photos, paging failures, source ordering and shared mobile/desktop route.

Do not publish unverified photos, infer permissions from indexing or bypass remote provider access restrictions.
