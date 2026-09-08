#!/usr/bin/env python3
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.receiver_hardware import scan
if __name__ == '__main__':
    snapshot = scan(refresh=True)
    if '--json' in sys.argv:
        print(json.dumps(snapshot, indent=2))
    else:
        for item in snapshot['receivers']:
            print(f"{item['description']} serial={item['serial']} USB={item['usb_path']}")
        if not snapshot['receivers']: print('No receivers connected.' if snapshot['ok'] else snapshot['error'])
    raise SystemExit(0 if snapshot['ok'] else 1)
