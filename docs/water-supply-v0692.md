# Drinking-water supply vessels — 0.69.2

Develop-only display change. Numbered DWS, DRINKWATER, DRINKWATERBOOT and
WATERBOOT names receive the `water_supply` profile when their reported type is
compatible. DWS 15 / WATERMAN-DWS 15 variants are included. Plain WATERMAN,
unrelated names, fixed marks, aircraft and explicitly conflicting vessel types
are excluded. ERI 8000 alone still means unknown; AIS records and alert categories
are unchanged. Name matching is an illustrative display hint, not identity proof.

User-supplied AIS example: DWS 15, MMSI 244700532, ENI 02009392, type 8000,
25 x 6 metres and course 177.1 degrees. Real AIS dimensions/orientation determine
the model; no dimensions are invented. Existing zoom thresholds and 2D icons
remain unchanged. Missing usable dimensions/bearing retain the ordinary icon.

The schematic model has a low blue hull, low tank deck, white aft wheelhouse,
dark windows, light roof, three tank hatches, water pipe, pump and twin hose reels.
These fittings are illustrative, not measured equipment or a claim of operator
livery. All footprint geometry remains inside AIS length and beam.

Validation: 70 Python map/recognition tests; numerical geometry checks at four
headings; existing Map Lab symbol suite; syntax and actual managed-update
preflight against 0.69.1. Historical hashes retained.

Install via SDRCC's normal beta/develop Update button. Confirm 0.69.2, open 3D
Map and zoom past 15 to a DWS/drinking-water boat with valid AIS dimensions.
Station browser appearance remains to be confirmed. Main is unchanged. The
existing updater records the backup and code rollback instructions; do not
replace configuration or install optional satellite/Radio Receiver components.
