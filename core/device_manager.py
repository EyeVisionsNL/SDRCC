#!/usr/bin/env python3

from core.config import get_receiver_assignments, load_station


def get_devices():
    cfg = load_station()
    assignments = get_receiver_assignments()
    devices = []
    for index in (1, 2):
        device_id = f"sdr{index}"
        if device_id not in cfg:
            continue
        item = cfg[device_id]
        roles = [role for role, assigned in assignments.items() if assigned == device_id]
        fixed_role = next(
            (role for role in ("ais", "adsb") if assignments.get(role) == device_id),
            "manual",
        )
        devices.append({
            "id": device_id,
            "number": f"SDR{index}",
            "name": item.get("name", f"SDR{index}"),
            "serial": str(item.get("serial", "")),
            "role": fixed_role,
            "roles": roles,
            "locked": item.get("locked", False),
            "weather_selected": assignments["weather"] == device_id,
        })
    return devices


def get_receiver_role(device_id):
    """Return the fixed receiver role from assignments only."""
    assignments = get_receiver_assignments()
    for role in ("ais", "adsb"):
        if assignments.get(role) == device_id:
            return role
    return "manual"


def get_device(device_id):
    return next((d for d in get_devices() if d["id"] == device_id), None)


def get_assigned_device(role):
    assignments = get_receiver_assignments()
    device_id = assignments.get(role)
    return get_device(device_id) if device_id else None


def get_weather_device():
    return get_assigned_device("weather")


def get_dynamic_device():
    return get_weather_device()


def get_conflicting_service(device_id):
    assignments = get_receiver_assignments()
    if assignments.get("ais") == device_id:
        return "ais-catcher.service"
    if assignments.get("adsb") == device_id:
        return "readsb.service"
    return None



def get_receiver_context(device_id):
    """Return the configured role and conflicting service for a receiver.

    This is intentionally configuration-only. Runtime reservation state remains
    owned by :mod:`core.receiver_manager`.
    """
    device = get_device(device_id)
    if device is None:
        return None
    role = get_receiver_role(device_id)
    service = get_conflicting_service(device_id)
    return {
        "receiver_id": device_id,
        "receiver_number": device.get("number"),
        "receiver_name": device.get("name"),
        "receiver_serial": device.get("serial"),
        "previous_role": role,
        "conflicting_service": service,
    }


def print_devices():
    print("SDR Devices")
    print("-----------------------------")
    for device in get_devices():
        print(device["name"])
        print(f"  ID     : {device['id']}")
        print(f"  Serial : {device['serial']}")
        print(f"  Roles  : {', '.join(device['roles']) or '-'}")
        print(f"  Locked : {'YES' if device['locked'] else 'NO'}")
        print()
    weather = get_weather_device()
    print("Selected weather receiver")
    print("-----------------------------")
    print(f"{weather['name']} / {weather['serial']}" if weather else "Niet ingesteld")
