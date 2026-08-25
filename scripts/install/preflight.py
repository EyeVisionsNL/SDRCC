#!/usr/bin/env python3
"""SDRCC v1.0 installer preflight. Observer-only: performs no system changes."""
from __future__ import annotations
import argparse, json, os, platform, shutil, subprocess, sys
from pathlib import Path

REQUIRED_COMMANDS = ("git", "cmake", "make", "gcc", "g++", "pkg-config", "rtl_test")
EXTERNAL_RUNTIME = ("satdump", "readsb", "AIS-catcher", "AIS-catcher-control")


def command_path(name: str) -> str | None:
    return shutil.which(name)


def ubuntu_release() -> dict:
    data = {}
    path = Path('/etc/os-release')
    if path.exists():
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if '=' in line:
                key, value = line.split('=', 1)
                data[key] = value.strip().strip('"')
    return data


def rtl_devices() -> list[dict]:
    exe = command_path('rtl_test')
    if not exe: return []
    try:
        done = subprocess.run([exe, '-t'], text=True, capture_output=True, timeout=4, check=False)
        text = (done.stdout or '') + '\n' + (done.stderr or '')
    except Exception:
        return []
    devices=[]
    for line in text.splitlines():
        line=line.strip()
        if not line or ':' not in line or 'SN:' not in line: continue
        head, rest = line.split(':',1)
        if not head.isdigit(): continue
        serial=rest.split('SN:',1)[1].strip()
        fields=[p.strip() for p in rest.split(',')]
        devices.append({'index':int(head),'serial':serial,'description':', '.join(fields[:-1])})
    return devices


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--require-external', action='store_true')
    args=ap.parse_args()
    release=ubuntu_release()
    required={name:command_path(name) for name in REQUIRED_COMMANDS}
    external={name:command_path(name) for name in EXTERNAL_RUNTIME}
    payload={
        'ok': all(required.values()) and (not args.require_external or all(external.values())),
        'os': release,
        'python': platform.python_version(),
        'user': os.environ.get('SUDO_USER') or os.environ.get('USER'),
        'required_commands': required,
        'external_runtime': external,
        'rtl_devices': rtl_devices(),
        'traffic_voice_backend': Path('/opt/sdrcc/traffic_voice/bin/rtl_airband').exists(),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"OS: {release.get('PRETTY_NAME','unknown')}")
        print(f"Python: {payload['python']}")
        for name,path in required.items(): print(f"{'PASS' if path else 'MISS'} base {name}: {path or '-'}")
        for name,path in external.items(): print(f"{'PASS' if path else 'MISS'} external {name}: {path or '-'}")
        print(f"{'PASS' if payload['traffic_voice_backend'] else 'MISS'} external RTLSDR-Airband: /opt/sdrcc/traffic_voice/bin/rtl_airband")
        for dev in payload['rtl_devices']:
            print(f"RTL-SDR index {dev['index']}: serial={dev['serial']} {dev['description']}")
    return 0 if payload['ok'] else 2

if __name__ == '__main__': raise SystemExit(main())
