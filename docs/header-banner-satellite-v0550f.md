# Header banner satellite visibility — v0.55.0f

## Scope

This release is a presentation-only correction for the existing SDRCC header banner.
The inline satellite artwork is moved down within its unchanged SVG view box so the
satellite body, panels and dish remain visible in the compact desktop crop.

## Unchanged contracts

- The header remains 88 pixels high on desktop.
- The existing inline SVG, colours, orbit, earth curve and satellite artwork are reused.
- The SDRCC identity, GitHub link and LIVE indicator remain unchanged.
- No image asset, JavaScript, API, receiver authority, service or configuration is added.
- Traffic Voice, AIS, ADS-B and mission execution are not changed.

## Geometry

The satellite group moves from `translate(545 48)` to `translate(545 86)` while
retaining its `rotate(-12)` transform. At the capped 880-pixel artwork width used on
a 1920-pixel display, the `xMidYMid slice` crop exposes approximately SVG y=52..128.
The moved satellite occupies approximately y=56..109, including the rotated panels
and dish, and therefore remains fully inside the visible banner.
