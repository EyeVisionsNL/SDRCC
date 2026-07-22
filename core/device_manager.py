#!/usr/bin/env python3

from core import plugin_registry
from core.config import get_assignment, get_receiver_assignments, load_station


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
            (
                role
                for role in plugin_registry.get_plugin_roles()
                if plugin_registry.get_plugin_executor(role) == "service"
                and assignments.get(role) == device_id
            ),
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
            "weather_selected": assignments.get("weather") == device_id,
        })
    return devices


def get_receiver_role(device_id):
    """Return the fixed receiver role from assignments only."""
    assignments = get_receiver_assignments()
    for role in plugin_registry.get_plugin_roles():
        if (
            plugin_registry.get_plugin_executor(role) == "service"
            and assignments.get(role) == device_id
        ):
            return role
    return "manual"


def get_device(device_id):
    return next((d for d in get_devices() if d["id"] == device_id), None)


def get_assigned_device(role):
    device_id = get_assignment(role)
    return get_device(device_id) if device_id else None


def get_weather_device():
    return get_assigned_device("weather")


def get_dynamic_device():
    return get_weather_device()


def get_assigned_roles(device_id):
    """Return all configured roles assigned to one receiver."""
    assignments = get_receiver_assignments()
    return [
        role
        for role, assigned_device in assignments.items()
        if assigned_device == device_id
    ]


def get_role_services(role):
    """Return services owned by a plugin role from the central registry."""
    return plugin_registry.get_plugin_services(role)


def get_conflicting_services(device_id, *, exclude_role=None):
    """Return unique services that currently occupy a receiver."""
    services = []
    for role in get_assigned_roles(device_id):
        if exclude_role and role == exclude_role:
            continue
        for service in get_role_services(role):
            if service not in services:
                services.append(service)
    return services


def get_conflicting_service(device_id):
    """Backward-compatible wrapper returning the first conflicting service."""
    services = get_conflicting_services(device_id)
    return services[0] if services else None


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
