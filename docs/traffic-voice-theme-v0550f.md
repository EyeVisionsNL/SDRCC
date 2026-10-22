# Traffic Voice theme alignment — v0.55.0f-r3

## Scope

This presentation-only correction aligns the Traffic Voice cards with the
existing SDRCC panel theme. It reuses the established top-right circular
ornament, coloured border treatment and neon left accent rail.

## Panel identity

- Traffic Voice header: rose.
- Marine Voice + AIS: cyan, including while selected.
- Airband Voice + ADS-B: purple.
- Active Receiver / Shared Voice Controls & Audio: rose with a neon left rail.

Selected, stopped, available and running states remain independent status
signals. Selection is expressed by the stronger border and status text while
the panel keeps its Marine or Aviation identity colour. JavaScript state
classes remain unchanged.

## Unchanged contracts

- No Traffic Voice JavaScript, backend, API, receiver assignment or service is changed.
- The Marine and Aviation two-column layout is unchanged.
- The compact header and visible banner satellite remain unchanged.
- The corner ornament uses the same 76-by-76 pixel geometry as the System,
  Mission Control and Radio View themes.
