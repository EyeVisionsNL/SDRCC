#!/usr/bin/env python3

import subprocess

from core.device_manager import get_devices


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
    for info in get_devices():
        serial = str(info.get("serial", ""))
        if serial and serial in output:
            devices.append({
                "serial": serial,
                "role": info.get("role", "manual"),
                "locked": bool(info.get("locked", False)),
                "name": info.get("name", info.get("number", "SDR")),
                "status": "ONLINE",
            })
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
