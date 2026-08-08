#!/usr/bin/env python3
"""TLE-backed digital Doppler correction for the ISS UHF voice downlink."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core import tle


ROOT = Path(__file__).resolve().parent.parent
TLE_FILE = ROOT / "data" / "tle" / "iss.tle"
SPEED_OF_LIGHT_KM_S = 299_792.458


class IssDopplerTracker:
    """Return observed carrier offset from nominal at an absolute sample time."""

    def __init__(self, *, nominal_frequency_hz: int, doppler_guard_hz: int,
                 norad_id: int = 25544, satellite_name: str = "ISS (ZARYA)") -> None:
        self.nominal_frequency_hz = int(nominal_frequency_hz)
        self.doppler_guard_hz = int(doppler_guard_hz)
        self.norad_id = int(norad_id)
        if self.nominal_frequency_hz <= 0 or self.doppler_guard_hz < 1:
            raise ValueError("Ongeldige Dopplerconfiguratie")

        # Imports remain lazy so offline validators can inspect the DSP chain on
        # systems without Skyfield. Production fails closed when tracking was
        # requested but its orbital dependency or validated TLE is unavailable.
        from skyfield.api import EarthSatellite, load, wgs84
        from core.config import load_station

        expected = {self.norad_id: str(satellite_name)}
        block = tle.load_file(TLE_FILE, expected_catalogs=expected)[self.norad_id]
        station_config = (load_station() or {}).get("station", {})
        self._timescale = load.timescale()
        self._satellite = EarthSatellite(
            block["line1"], block["line2"], block["name"], self._timescale
        )
        self._station = wgs84.latlon(
            float(station_config["latitude"]),
            float(station_config["longitude"]),
            elevation_m=float(station_config.get("altitude_m", 0)),
        )
        self.metadata = {
            "source": "skyfield_frame_latlon_and_rates",
            "norad_id": self.norad_id,
            "tle_epoch": block["epoch_iso"],
            "tle_sha256": block["sha256"],
            "station_latitude": float(station_config["latitude"]),
            "station_longitude": float(station_config["longitude"]),
            "station_altitude_m": float(station_config.get("altitude_m", 0)),
        }

    def offset_hz(self, epoch_seconds: float) -> float:
        moment = datetime.fromtimestamp(float(epoch_seconds), tz=timezone.utc)
        topocentric = (self._satellite - self._station).at(
            self._timescale.from_datetime(moment)
        )
        _lat, _lon, _distance, _lat_rate, _lon_rate, range_rate = (
            topocentric.frame_latlon_and_rates(self._station)
        )
        # Negative range rate means approaching and therefore a positive
        # observed offset. The decoder removes this offset with an inverse NCO.
        offset = -self.nominal_frequency_hz * float(range_rate.km_per_s) / SPEED_OF_LIGHT_KM_S
        if abs(offset) > self.doppler_guard_hz:
            raise RuntimeError(
                f"Berekende ISS Doppler {offset:.0f} Hz overschrijdt guard "
                f"{self.doppler_guard_hz} Hz"
            )
        return float(offset)


def build_tracker(config: dict[str, Any]) -> IssDopplerTracker:
    if not bool(config.get("doppler_tracking")):
        raise RuntimeError("ISS Dopplertracking staat niet actief")
    return IssDopplerTracker(
        nominal_frequency_hz=int(config["downlink_frequency_hz"]),
        doppler_guard_hz=int(config["doppler_guard_hz"]),
        norad_id=int(config.get("norad_id") or 25544),
        satellite_name=str(config.get("satellite_name") or "ISS (ZARYA)"),
    )
