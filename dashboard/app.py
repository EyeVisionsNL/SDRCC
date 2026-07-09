#!/usr/bin/env python3

import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, jsonify, render_template

from core import device_manager
from core import passes
from core import process_manager
from core import state
from core import tle
from core import system_stats

app = Flask(__name__)


def serialize_pass(pass_data):
    if pass_data is None:
        return None

    start_local = pass_data["start"].astimezone()
    maximum_local = pass_data["maximum"].astimezone()
    end_local = pass_data["end"].astimezone()

    return {
        "name": pass_data["name"],
        "start": start_local.strftime("%Y-%m-%d %H:%M:%S"),
        "maximum": maximum_local.strftime("%Y-%m-%d %H:%M:%S"),
        "end": end_local.strftime("%Y-%m-%d %H:%M:%S"),
        "start_epoch": int(start_local.timestamp()),
        "maximum_epoch": int(maximum_local.timestamp()),
        "end_epoch": int(end_local.timestamp()),
        "max_elevation": pass_data["max_elevation"],
        "azimuth": pass_data["azimuth"],
        "frequency_mhz": round(pass_data["frequency"] / 1000000, 3),
        "mode": pass_data["mode"],
        "pipeline": pass_data.get("pipeline"),
    }


def get_dashboard_data():
    sdr2 = state.get_sdr2_state()
    next_pass = passes.get_next_pass()
    adsb = process_manager.readsb_status()
    devices = device_manager.get_devices()

    return {
        "server_time_epoch": int(datetime.now().timestamp()),
        "sdr2": sdr2,
        "next_pass": serialize_pass(next_pass),
        "adsb": adsb,
        "devices": devices,
        "tle_present": tle.exists(),
        "system": system_stats.get_stats(),
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    return jsonify(get_dashboard_data())


def run():
    app.run(
        host="0.0.0.0",
        port=8080,
        debug=False,
    )


if __name__ == "__main__":
    run()
