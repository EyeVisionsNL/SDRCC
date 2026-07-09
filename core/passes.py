#!/usr/bin/env python3

from datetime import datetime, timedelta
from pathlib import Path

from skyfield.api import EarthSatellite, load, wgs84

from core.config import load_station, get_enabled_satellites

TLE_FILE = Path(__file__).resolve().parent.parent / "data" / "tle" / "weather.tle"


def _load_station_location():
    cfg = load_station()
    station = cfg.get("station", {})

    latitude = float(station.get("latitude"))
    longitude = float(station.get("longitude"))
    altitude_m = float(station.get("altitude_m", 0))

    return wgs84.latlon(latitude, longitude, elevation_m=altitude_m)


def _load_tle_blocks():
    if not TLE_FILE.exists():
        return {}

    lines = [line.strip() for line in TLE_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    blocks = {}

    for i in range(0, len(lines), 3):
        if i + 2 >= len(lines):
            continue

        name = lines[i]
        line1 = lines[i + 1]
        line2 = lines[i + 2]

        blocks[name] = (line1, line2)

    return blocks


def get_next_pass(hours_ahead=48):
    station_location = _load_station_location()
    enabled = get_enabled_satellites()
    tle_blocks = _load_tle_blocks()

    ts = load.timescale()
    now = datetime.utcnow()
    t0 = ts.utc(now.year, now.month, now.day, now.hour, now.minute, now.second)

    future = now + timedelta(hours=hours_ahead)
    t1 = ts.utc(future.year, future.month, future.day, future.hour, future.minute, future.second)

    candidates = []

    for sat_name, sat_cfg in enabled.items():
        if sat_name not in tle_blocks:
            continue

        line1, line2 = tle_blocks[sat_name]
        satellite = EarthSatellite(line1, line2, sat_name, ts)

        min_elevation = float(sat_cfg.get("min_elevation", 30))

        times, events = satellite.find_events(
            station_location,
            t0,
            t1,
            altitude_degrees=min_elevation,
        )

        # Events: 0 = rise above min elevation, 1 = culminate, 2 = set below min elevation
        for index in range(len(events) - 2):
            if events[index] == 0 and events[index + 1] == 1 and events[index + 2] == 2:
                start_time = times[index]
                max_time = times[index + 1]
                end_time = times[index + 2]

                difference = satellite - station_location
                topocentric = difference.at(max_time)
                alt, az, distance = topocentric.altaz()

                candidates.append(
                    {
                        "name": sat_name,
                        "start": start_time.utc_datetime(),
                        "maximum": max_time.utc_datetime(),
                        "end": end_time.utc_datetime(),
                        "max_elevation": round(alt.degrees, 1),
                        "azimuth": round(az.degrees, 1),
                        "frequency": sat_cfg.get("frequency"),
                        "mode": sat_cfg.get("mode"),
                        "decoder": sat_cfg.get("decoder"),
                        "min_elevation": min_elevation,
                    }
                )

    if not candidates:
        return None

    candidates.sort(key=lambda item: item["start"])
    return candidates[0]


def print_next_pass():
    next_pass = get_next_pass()

    print("Next pass")
    print("-----------------------------")

    if next_pass is None:
        print("Geen geschikte passage gevonden.")
        return

    duration = next_pass["end"] - next_pass["start"]
    minutes = int(duration.total_seconds() // 60)
    seconds = int(duration.total_seconds() % 60)

    print(next_pass["name"])
    print()
    print("Start      :", next_pass["start"].strftime("%Y-%m-%d %H:%M:%S UTC"))
    print("Maximum    :", next_pass["maximum"].strftime("%Y-%m-%d %H:%M:%S UTC"))
    print("End        :", next_pass["end"].strftime("%Y-%m-%d %H:%M:%S UTC"))
    print("Duration   :", f"{minutes}m {seconds}s")
    print("Max Elev   :", f"{next_pass['max_elevation']}°")
    print("Azimuth    :", f"{next_pass['azimuth']}°")
    print("Frequency  :", f"{next_pass['frequency'] / 1e6:.3f} MHz")
    print("Mode       :", next_pass["mode"])
    print("Decoder    :", next_pass["decoder"])
