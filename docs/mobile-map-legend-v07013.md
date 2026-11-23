# Mobile map legend positioning — 0.70.13

Fix the fullscreen mobile map legend so its panel opens below the Legend
control and stays inside the phone viewport. Each new fullscreen map session
starts with the legend collapsed; desktop Map Lab keeps its saved preference.

Install the candidate from **System → Advanced Maintenance → Update** with the
beta/develop channel selected. Confirm `0.70.13`, open Marine → 3D Map, then
open Legend and verify that the full panel is visible on screen. Close and
reopen the 3D map to confirm the panel starts collapsed again.

The managed updater performs its normal backup and reports the rollback path.
This is a server-side CSS/JavaScript correction; the Android APK remains
`2.0.7`.
