"""Read-only Linux USB descriptor discovery; never opens or retunes a receiver."""
from pathlib import Path
from collections import Counter
from copy import deepcopy
import time
from threading import RLock

SYSFS = Path('/sys/bus/usb/devices')
# RTL2832/2838 IDs used by RTL-SDR Blog and NESDR. Other branded RTL devices
# exposing their chipset in the product descriptor are recognised as well.
RTL_IDS = {('0bda', '2832'), ('0bda', '2838')}
_lock = RLock()
_cache = (0.0, None)

def scan(*, refresh=False):
    global _cache
    with _lock:
        if not refresh and _cache[1] is not None and time.monotonic()-_cache[0] < 1:
            return deepcopy(_cache[1])
        devices = []
        try:
            for path in sorted(SYSFS.iterdir()):
                if ':' in path.name or not (path/'idVendor').exists():
                    continue
                vendor = (path/'idVendor').read_text().strip().lower()
                product_id = (path/'idProduct').read_text().strip().lower()
                product = (path/'product').read_text().strip() if (path/'product').exists() else ''
                recognised = (vendor, product_id) in RTL_IDS or any(
                    token in product.lower() for token in ('rtl2832', 'rtl2838', 'nesdr', 'rtl-sdr'))
                if not recognised:
                    continue
                serial = (path/'serial').read_text().strip() if (path/'serial').exists() else ''
                devices.append({'serial': serial, 'description': product or 'RTL-SDR', 'usb_path': path.name})
            counts = Counter(d['serial'] for d in devices)
            ambiguous = any(not serial or count > 1 for serial, count in counts.items())
            result = {'ok': True, 'receivers': devices, 'ambiguous': ambiguous,
                      'error': 'Missing or duplicate USB serial; unique serials required.' if ambiguous else None}
        except OSError as error:
            result = {'ok': False, 'receivers': [], 'ambiguous': False, 'error': str(error)}
        _cache = (time.monotonic(), result)
        return deepcopy(result)

def presence(serial, snapshot=None):
    snapshot = scan() if snapshot is None else snapshot
    if not snapshot['ok']:
        return 'UNKNOWN'
    if not serial:
        return 'UNBOUND'
    matches = [r for r in snapshot['receivers'] if r['serial'] == serial]
    return 'PRESENT' if len(matches) == 1 else ('UNKNOWN' if matches else 'MISSING')

def detect(**kwargs):
    return scan(refresh=True)['receivers']
