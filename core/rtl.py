#!/usr/bin/env python3
"""Compatibility display; physical discovery is shared with the installer."""
from core.receiver_hardware import scan
from core.device_manager import get_devices

def detect():
    configured = {d['serial']: d for d in get_devices() if d['serial']}
    result = []
    for row in scan()['receivers']:
        device = configured.get(row['serial'], {})
        result.append({**row, 'name': device.get('name', row['description']),
                       'role': device.get('role', 'unassigned'),
                       'locked': device.get('locked', False), 'status': 'ONLINE'})
    return result

def print_status():
    for device in detect():
        print(f"{device['name']}: {device['serial']} · {device['role']} · {device['status']}")
