# Mobile 3D map controls — 0.70.12

The SDRCC Android 3D map now opens as a map-first view. The app header and the
map page's mode buttons are hidden while the map is open. Swipe down from the
top edge to return to the mobile controls; Android Back still returns too.

Map controls are grouped in one compact row: **Legend**, refresh, and
**Possible speaker**. The former Reset control and map compass/Home control
have been removed. Zoom controls remain available.

## Versions and update path

- SDRCC server: `0.70.12`, installed from the beta/develop channel using
  **System → Advanced Maintenance → Update**.
- Android app: `2.0.7` (versionCode `14`), offered through the Android app's
  **↓** update button after the signed release workflow publishes the APK and
  the stable update feed.
- The Android source change is native, so the server update alone does not hide
  the app header in an installed older APK.

The managed server updater verifies source hashes, makes its normal code and
configuration backup, and reports the rollback command if the update fails.
Use the rollback path shown by the updater; leave station configuration and
receiver services under the updater's state handling.

## Operator check

After both updates, open Marine → 3D Map. Confirm the map fills the screen, the
Legend/refresh/Possible speaker controls stay in one row, zoom still works,
and a downward swipe from the top edge returns to the mobile controls. Confirm
Android Back also returns to the mobile controls. `main` is unchanged for the
SDRCC server; the Android release workflow publishes the signed APK and
updates the app's production feed.
