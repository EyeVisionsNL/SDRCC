#!/usr/bin/env python3

from core.config import load_station


def get_devices():
    cfg = load_station()

    devices = []

    if "sdr1" in cfg:
        devices.append(
            {
                "id": "sdr1",
                "name": cfg["sdr1"].get("name", "SDR1"),
                "serial": cfg["sdr1"].get("serial"),
                "role": cfg["sdr1"].get("task", "unknown"),
                "locked": cfg["sdr1"].get("locked", True),
            }
        )

    if "sdr2" in cfg:
        devices.append(
            {
                "id": "sdr2",
                "name": cfg["sdr2"].get("name", "SDR2"),
                "serial": cfg["sdr2"].get("serial"),
                "role": cfg["sdr2"].get("task", "dynamic"),
                "locked": cfg["sdr2"].get("locked", False),
            }
        )

    return devices


def get_device(device_id):
    for device in get_devices():
        if device["id"] == device_id:
            return device

    return None


def get_dynamic_device():
    for device in get_devices():
        if not device["locked"]:
            return device

    return None


def print_devices():
    print("SDR Devices")
    print("-----------------------------")

    devices = get_devices()

    if not devices:
        print("Geen SDR-apparaten geconfigureerd.")
        return

    for device in devices:
        print(device["name"])
        print(f"  ID     : {device['id']}")
        print(f"  Serial : {device['serial']}")
        print(f"  Role   : {device['role']}")
        print(f"  Locked : {'YES' if device['locked'] else 'NO'}")
        print()

    dynamic = get_dynamic_device()

    print("Selected recorder")
    print("-----------------------------")

    if dynamic:
        print(f"{dynamic['name']} / {dynamic['serial']}")
    else:
        print("Geen vrije dynamische SDR gevonden.")
