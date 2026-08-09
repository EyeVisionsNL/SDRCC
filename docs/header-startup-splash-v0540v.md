# SDRCC v0.54.0v-r2 - Logo Startup Splash and Compact Header

## Scope

This release refreshes only the dashboard identity area:

- show the existing SDRCC logo in a short startup splash once per browser session;
- dismiss the splash after the existing System metrics receive their first value;
- replace the old banner copy with `SDRCC – Flexible Ground Station`;
- add a responsive blue satellite/space treatment;
- add a keyboard-accessible link to `https://github.com/EyeVisionsNL/SDRCC`;
- retain the existing LIVE indicator;
- place the title and subtitle directly beside the logo;
- place the GitHub link and LIVE indicator on one row;
- reduce the desktop banner from a 142 px minimum to a compact 88 px minimum.

## Authority and duplication boundary

The splash observes the existing `system-cpu` presentation value. It does not fetch data,
create a polling loop or introduce a status source. The header has no service controls and
does not alter service, receiver, mission or execution authority.

The v0.54.0u workflow navigation remains the owner of tab order, tab accents and responsive
button layout. The new header stylesheet does not style `.tabs`, `.tab-button` or `.tab-page`.

The r2 correction changes only the header layout and cache key. The approved startup splash,
its one-per-session behavior and all navigation contracts are unchanged.

## Accessibility and resilience

- GitHub opens in a new tab with `noopener noreferrer`.
- The project link has an explicit accessible label and keyboard focus state.
- Reduced-motion preferences disable the entrance and loading animations.
- Session-storage failures do not block dashboard startup.
- A fallback timeout prevents the splash from remaining visible if initial status loading fails.
