#!/usr/bin/env python3
"""Validate the observer-only Radio View satellite world map contract."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import satellite_view  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    split = satellite_view._split_dateline([
        [170.0, 5.0],
        [179.0, 6.0],
        [-179.0, 7.0],
        [-170.0, 8.0],
    ])
    check(len(split) == 2, "ground tracks split cleanly at the dateline")

    footprint, radius = satellite_view._footprint_segments(20.0, 175.0, 420.0)
    check(len(footprint) >= 2, "radio footprint splits cleanly at the dateline")
    check(1500.0 < radius < 3000.0, "radio-horizon footprint radius is physically plausible")

    snapshot = satellite_view.get_snapshot(force=True)
    check(snapshot.get("ok") is True, "live orbital snapshot is available")
    check(snapshot.get("authority") == "read_only_tle_observer", "satellite map is observer-only")
    check(snapshot.get("projection") == "equirectangular", "API and offline map share one projection")
    check(
        {item.get("norad_id") for item in snapshot.get("satellites", [])}
        == {25544, 57166, 59051},
        "ISS, METEOR-M2 3 and METEOR-M2 4 are tracked from validated TLEs",
    )
    station = snapshot.get("station") or {}
    check(
        -90.0 <= float(station.get("latitude")) <= 90.0
        and -180.0 <= float(station.get("longitude")) <= 180.0,
        "configured home station is projected on the map",
    )
    for item in snapshot["satellites"]:
        position = item.get("position") or {}
        observer = item.get("observer") or {}
        ground_track = item.get("ground_track") or {}
        footprint_data = item.get("footprint") or {}
        check(
            -90.0 <= float(position.get("latitude")) <= 90.0
            and -180.0 <= float(position.get("longitude")) <= 180.0,
            f"{item['name']} live position is bounded",
        )
        check(float(position.get("altitude_km")) > 100.0, f"{item['name']} altitude is present")
        check(
            -90.0 <= float(observer.get("elevation_deg")) <= 90.0
            and 0.0 <= float(observer.get("azimuth_deg")) <= 360.0
            and float(observer.get("range_km")) > 0.0,
            f"{item['name']} station-relative geometry is present",
        )
        check(
            bool(ground_track.get("past")) and bool(ground_track.get("future")),
            f"{item['name']} past and future ground tracks are present",
        )
        check(
            bool(footprint_data.get("segments")) and float(footprint_data.get("radius_km")) > 0.0,
            f"{item['name']} radio-horizon footprint is present",
        )

    template = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "dashboard/static/js/radio_view.js").read_text(encoding="utf-8")
    stylesheet = (ROOT / "dashboard/static/css/radio_view.css").read_text(encoding="utf-8")
    application = (ROOT / "dashboard/app.py").read_text(encoding="utf-8")
    world_map = ROOT / "dashboard/static/assets/world-map-equirectangular.svg"

    check('@app.route("/api/satellite-view")' in application, "dedicated read-only API route is registered")
    check("/api/satellite-view" in javascript, "Radio View consumes the orbital observer API")
    check("/api/mission-queue" in javascript, "next mission remains sourced from Mission Queue")
    check(
        'toLocaleDateString("en-GB"' in javascript
        and 'toLocaleTimeString("en-GB"' in javascript
        and "hour12: false" in javascript,
        "next mission date is fixed to English with 24-hour time",
    )
    check("radio-view-satellite-footprints" in template, "satellite footprint SVG layer exists")
    check("radio-view-satellite-tracks" in template, "satellite ground-track SVG layer exists")
    check("radio-view-satellite-selector" in template, "all satellites can be selected")
    check("radio-view-orbit-line" not in template, "static decorative orbit is removed")
    check("radio-view-live-image-wrap" not in template, "Mission Operations preview is not duplicated")
    check("radio-view-orbit-track" in stylesheet, "past and future track styling exists")
    check(world_map.is_file() and world_map.stat().st_size > 10_000, "offline world map asset is packaged")
    check("world-map-equirectangular.svg" in template, "Satellite View uses the local world map")

    print("PASS: v0.54.0i-r2 Radio View Satellite Map validation complete")


if __name__ == "__main__":
    main()
