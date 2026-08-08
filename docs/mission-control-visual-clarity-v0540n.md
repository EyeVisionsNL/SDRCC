# Mission Control Visual Clarity — v0.54.0n

Mission Control now uses the same approved SDRCC presentation language as Mission Planner, Mission Analytics, Mission Operations and Mission History.

## Scope

- Presentation-only refresh of Mission Queue, mission receiver cards, operator controls, Live Event Timeline and Execution Journal.
- METEOR-M2 3 uses cyan, METEOR-M2 4 purple and ISS yellow.
- READY and healthy/finished states use green, waiting/attention states amber and failures red.
- Receiver cards receive a display-only satellite class from their already-authoritative visible mission data.

## Preserved contracts

- Mission Queue remains the planning projection and next-pass authority.
- Mission Engine remains mission lifecycle authority.
- Receiver Manager remains receiver reservation authority.
- Execution Journal remains observer-only.
- Existing controls, polling, API routes, status projection, countdown and overlap handling are unchanged.
