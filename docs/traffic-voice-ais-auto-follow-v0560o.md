# FlexGround SDR v0.56.0o — Traffic Voice AIS Auto Follow

## Operator behavior

Traffic Voice adds an **Auto: off/on** control beside the existing manual
**Show on full AIS map** action. Enabling Auto opens one AIS-Catcher map window
from the operator click. When a later validated ATIS message produces a new
exact AIS match, that same window navigates to the matched MMSI. It does not
open a new map for every transmission.

If the operator closes the controlled map window, Auto disables itself and
reports that state in the existing Traffic Voice action message. The operator
must click Auto again to open a new controlled window; background polling never
creates unsolicited pop-ups.

## Architecture and authority

- `core/traffic_voice.py` remains the sole projection of validated ATIS/AIS
  correlation results.
- `dashboard/static/js/traffic_voice.js` observes the existing API payload and
  owns only the local Auto toggle and last-presented MMSI.
- `dashboard/static/js/radio_view.js` remains the only AIS viewer URL/window
  integration owner.
- The existing manual map action remains unchanged.
- No API, backend state, AIS matcher, polling loop, service control or receiver
  authority is added.
- Auto follows only `ais_match.matched` results with a valid nine-digit MMSI.
