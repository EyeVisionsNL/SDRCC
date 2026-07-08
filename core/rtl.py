#!/usr/bin/env python3

import subprocess
from core.config import load

cfg = load()

SDRS = {
    cfg["sdr1"]["serial"]: cfg["sdr1"],
    cfg["sdr2"]["serial"]: cfg["sdr2"],
}


def detect():

    try:
        result = subprocess.run(
            ["rtl_test", "-t"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        output = result.stdout + result.stderr

    except Exception:
        return []

    devices = []

    for serial, info in SDRS.items():

        if serial in output:

            devices.append(
                {
                    "serial": serial,
                    "role": info["task"],
                    "locked": info["locked"],
                    "name": info["name"],
                    "status": "ONLINE",
                }
            )

    return devices


def print_status():

    print()

    for dev in detect():

        print(dev["name"])
        print("-" * len(dev["name"]))
        print("Serial :", dev["serial"])
        print("Role   :", dev["role"])
        print("Locked :", dev["locked"])
        print("Status :", dev["status"])
        print()
