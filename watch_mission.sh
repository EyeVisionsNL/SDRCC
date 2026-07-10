#!/bin/bash

cd ~/SDRCC || exit 1
source venv/bin/activate

clear
echo "========================================="
echo "       SDRCC Live Mission Watch"
echo "========================================="
echo "CTRL+C om te stoppen"
echo

while true; do
    clear
    echo "========================================="
    echo "       SDRCC Live Mission Watch"
    echo "========================================="
    echo

    python3 - <<'PY'
import json
from core import mission_engine

data = mission_engine.get_mission_status()

print(f"Phase      : {data.get('phase')}")
print(f"Detail     : {data.get('detail')}")
print(f"Progress   : {data.get('progress')}%")
print(f"Updated    : {data.get('updated')}")
print()

p = data.get("next_pass") or {}
ps = data.get("pass_state") or {}

print("Next pass")
print("---------")
print(f"Name       : {p.get('name', '-')}")
print(f"Start      : {p.get('start', '-')}")
print(f"Maximum    : {p.get('maximum', '-')}")
print(f"End        : {p.get('end', '-')}")
print(f"State      : {ps.get('state', '-')}")
print(f"To start   : {ps.get('seconds_to_start', '-')}")
print(f"To end     : {ps.get('seconds_to_end', '-')}")
print()

print("Activity")
print("--------")
print(f"Files seen : {data.get('files_seen')}")
print(f"Changed    : {data.get('files_changed')}")
print(f"Processes  : {len(data.get('processes') or [])}")
print()

for process in data.get("processes") or []:
    print(f"PID {process.get('pid')} | {process.get('match')} | {process.get('command')}")

if data.get("growing_files"):
    print()
    print("Growing files")
    print("-------------")
    for item in data.get("growing_files"):
        print(f"{item.get('name')} +{item.get('size_delta')} bytes")

if data.get("recent_images"):
    print()
    print("Recent images")
    print("-------------")
    for item in data.get("recent_images"):
        print(f"{item.get('name')} age={item.get('age_seconds')}s")

print()
print("Timeline")
print("--------")
for event in (data.get("events") or [])[:8]:
    print(f"{event.get('time')} | {event.get('phase')} | {event.get('detail')}")
PY

    sleep 2
done
