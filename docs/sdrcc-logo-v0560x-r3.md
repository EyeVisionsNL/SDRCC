# SDRCC logo refresh — v0.56.0x-r3

Uses the approved ship-based AIS / ATIS artwork, with ADS-B and satellite
reception. Removes MeshCore and the shore tower from the active logo.

The dashboard header, startup splash, favicon, README logo and full-resolution
asset use the new artwork. The splash logo grows from about 216 px to up to
520 px, constrained by viewport width and height. Header logos grow to 88 px
on desktop and 72 px on narrow screens. Asset cache keys refresh the browser.
Splash timing, session behavior and receiver workflows are unchanged.

Update a clean tracked checkout using `git pull --ff-only`, then restart
`sdrcc.service` and reload the dashboard. The splash appears once per browser
session; use a fresh private window to inspect it again.

Validation: full diff review, Python compilation, JavaScript syntax and the
existing header/splash validation passed. Browser visual validation was not
completed in this environment; the user explicitly chose to perform that check
on the installed dashboard before accepting the appearance.
