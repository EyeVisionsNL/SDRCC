#!/usr/bin/env python3

"""Receiver inventory facade backed by the central Receiver Registry.

The public ``id`` field remains the compatibility runtime alias during the
migration. ``registry_id`` and ``canonical_id`` are the authoritative IDs.
"""

from core import plugin_registry
from core.config import get_assignment, get_receiver_assignments
from core.receiver_registry import get_receiver as registry_get_receiver, get_receivers


def get_devices():
    from core import receiver_hardware
    hardware = receiver_hardware.scan()
    assignments = get_receiver_assignments()
    devices = []
    for item in get_receivers():
        runtime_id = item["runtime_id"]
        canonical_id = item["id"]
        roles = [role for role, assigned in assignments.items() if assigned == runtime_id]
        fixed_role = next(
            (
                role
                for role in plugin_registry.get_plugin_roles()
                if plugin_registry.get_plugin_executor(role) == "service"
                and assignments.get(role) == runtime_id
            ),
            "manual",
        )
        devices.append({
            # Compatibility contract used by the current UI and executors.
            "id": runtime_id,
            "runtime_id": runtime_id,
            # Canonical Receiver Registry identity.
            "registry_id": canonical_id,
            "canonical_id": canonical_id,
            "number": item["number"],
            "name": item["name"],
            "description": item["description"],
            "serial": item["serial"],
            "presence": receiver_hardware.presence(item["serial"], hardware),
            "present": receiver_hardware.presence(item["serial"], hardware) == "PRESENT",
            "driver": item["driver"],
            "aliases": item["aliases"],
            "capabilities": item["capabilities"],
            "role": fixed_role,
            "roles": roles,
            "locked": item["locked"],
            "weather_selected": assignments.get("weather") == runtime_id,
        })
    return devices


def get_receiver_role(device_id):
    """Return the fixed receiver role from assignments only."""
    device = get_device(device_id)
    runtime_id = device["runtime_id"] if device else str(device_id or "").strip().lower()
    assignments = get_receiver_assignments()
    for role in plugin_registry.get_plugin_roles():
        if (
            plugin_registry.get_plugin_executor(role) == "service"
            and assignments.get(role) == runtime_id
        ):
            return role
    return "manual"


def get_device(device_id):
    """Resolve canonical IDs and aliases through the Receiver Registry."""
    registry_item = registry_get_receiver(device_id)
    if registry_item is None:
        return None
    canonical_id = registry_item["id"]
    return next((d for d in get_devices() if d["registry_id"] == canonical_id), None)


def get_assigned_device(role):
    device_id = get_assignment(role)
    return get_device(device_id) if device_id else None


def get_weather_device():
    return get_assigned_device("weather")


def get_dynamic_device():
    return get_weather_device()


def get_assigned_roles(device_id):
    """Return all configured roles assigned to one receiver."""
    device = get_device(device_id)
    runtime_id = device["runtime_id"] if device else str(device_id or "").strip().lower()
    assignments = get_receiver_assignments()
    return [
        role
        for role, assigned_device in assignments.items()
        if assigned_device == runtime_id
    ]


def get_role_services(role):
    """Return services owned by a plugin role from the central registry."""
    return plugin_registry.get_plugin_services(role)


def get_role_handover_services(role):
    """Return ordered services that must release a receiver for a mission."""
    return plugin_registry.get_plugin_handover_services(role)


def get_conflicting_services(device_id, *, exclude_role=None):
    """Return unique services that currently occupy a receiver."""
    services = []
    for role in get_assigned_roles(device_id):
        if exclude_role and role == exclude_role:
            continue
        for service in get_role_handover_services(role):
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
        print(f"  Registry ID : {device['registry_id']}")
        print(f"  Runtime ID  : {device['runtime_id']}")
        print(f"  Serial      : {device['serial']}")
        print(f"  Roles       : {', '.join(device['roles']) or '-'}")
        print(f"  Locked      : {'YES' if device['locked'] else 'NO'}")
        print()
    weather = get_weather_device()
    print("Selected weather receiver")
    print("-----------------------------")
    print(f"{weather['name']} / {weather['serial']}" if weather else "Niet ingesteld")
