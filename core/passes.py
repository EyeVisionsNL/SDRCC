#!/usr/bin/env python3

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from skyfield.api import EarthSatellite, load, wgs84

from core.config import load_station, get_enabled_satellites

TLE_FILE = Path(__file__).resolve().parent.parent / "data" / "tle" / "weather.tle"
LOCAL_TZ = ZoneInfo("Europe/Amsterdam")


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
        blocks[lines[i]] = (lines[i + 1], lines[i + 2])

    return blocks


def _fmt_local(dt):
    return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")


def get_passes(hours_ahead=48):
    station_location = _load_station_location()
    enabled = get_enabled_satellites()
    tle_blocks = _load_tle_blocks()

    ts = load.timescale()
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=hours_ahead)

    t0 = ts.from_datetime(now)
    t1 = ts.from_datetime(future)

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

        for index in range(len(events) - 2):
            if events[index] == 0 and events[index + 1] == 1 and events[index + 2] == 2:
                start_time = times[index]
                max_time = times[index + 1]
                end_time = times[index + 2]

                topocentric = (satellite - station_location).at(max_time)
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

    candidates.sort(key=lambda item: item["start"])
    return candidates


def get_next_pass(hours_ahead=48):
    passes = get_passes(hours_ahead)
    return passes[0] if passes else None


def _print_pass(pass_data):
    duration = pass_data["end"] - pass_data["start"]
    minutes = int(duration.total_seconds() // 60)
    seconds = int(duration.total_seconds() % 60)

    print(pass_data["name"])
    print()
    print("Start      :", _fmt_local(pass_data["start"]), "lokale tijd")
    print("Maximum    :", _fmt_local(pass_data["maximum"]), "lokale tijd")
    print("End        :", _fmt_local(pass_data["end"]), "lokale tijd")
    print("Duration   :", f"{minutes}m {seconds}s")
    print("Max Elev   :", f"{pass_data['max_elevation']}°")
    print("Azimuth    :", f"{pass_data['azimuth']}°")
    print("Frequency  :", f"{pass_data['frequency'] / 1e6:.3f} MHz")
    print("Mode       :", pass_data["mode"])
    print("Decoder    :", pass_data["decoder"])


def print_next_pass():
    next_pass = get_next_pass()

    print("Next pass")
    print("-----------------------------")

    if next_pass is None:
        print("Geen geschikte passage gevonden.")
        return

    _print_pass(next_pass)


def print_schedule(hours_ahead=24):
    upcoming = get_passes(hours_ahead)

    print(f"Schedule next {hours_ahead} hours")
    print("-----------------------------")

    if not upcoming:
        print("Geen geschikte passages gevonden.")
        return

    for item in upcoming:
        print(
            f"{_fmt_local(item['start'])} | "
            f"{item['name']} | "
            f"max {item['max_elevation']}° | "
            f"{item['frequency'] / 1e6:.3f} MHz"
        )
