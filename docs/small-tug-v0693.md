# Small tug rendering — 0.69.3

Tug 3D hull/deck minimum length is now 8 metres (previously 12), at the user's
request. KRVE 83 (244039187), reporting 11 x 4 metres and AIS type 52, therefore
uses the existing tug model. Other vessel thresholds and zoom rules are unchanged.

When a tug has real AIS length/beam but lacks antenna offsets, center the antenna
illustratively. If heading is missing, use available course or a neutral north-up
orientation; the popup explicitly labels that as approximate, not true heading.
No dimensions are invented. Missing dimensions keep the ordinary icon. Fixed
marks and aircraft are excluded from this new fallback.

Checks: 75 Python tests; actual JS hull/deck generation at 8, 7.9 and 11 metres;
existing Map Lab symbol regression; Python/JS syntax; update preflight from
0.69.2 and source hash verification. Historical manifest hashes retained.

Install through the usual beta/develop dashboard Update button, confirm 0.69.3,
and inspect KRVE 83 in 3D above zoom 15. Station appearance still needs user
verification. Main unchanged. Existing updater creates its usual code backup
and reports rollback instructions. No optional modules or configuration changes.
