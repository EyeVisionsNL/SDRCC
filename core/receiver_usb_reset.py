"""Bounded, unprivileged reset of one uniquely identified RTL-SDR USB device.

The kernel's cached sysfs serial can still identify a wedged device when
librtlsdr cannot read its live strings. Never reset by port alone.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import time

from core import receiver_hardware

USBFS = Path("/dev/bus/usb")
USBDEVFS_RESET = 0x5514
USBDEVFS_DROP_PRIVILEGES = 0x4004551E
_last_ports = {}


def _identity(serial, port):
    if not serial or not re.fullmatch(r"[0-9]+-[0-9]+(?:\.[0-9]+)*", port):
        raise RuntimeError("USB reset requires an exact serial and physical port")
    snapshot = receiver_hardware.scan(refresh=True)
    matches = [d for d in snapshot["receivers"] if d["serial"] == serial]
    if not snapshot["ok"] or snapshot["ambiguous"] or len(matches) != 1 or matches[0]["usb_path"] != port:
        raise RuntimeError("USB identity missing, changed or ambiguous; reset refused")
    path = receiver_hardware.SYSFS / port
    def read(name):
        return (path / name).read_text().strip()
    if read("serial") != serial or (read("idVendor").lower(), read("idProduct").lower()) not in receiver_hardware.RTL_IDS:
        raise RuntimeError("USB reset supports only uniquely identified RTL2832/2838 devices")
    bus, number = int(read("busnum")), int(read("devnum"))
    if not 1 <= bus <= 999 or not 1 <= number <= 127:
        raise RuntimeError("Invalid USB address")
    major, minor = map(int, read("dev").split(":"))
    return USBFS / f"{bus:03d}" / f"{number:03d}", os.makedev(major, minor)


def reset_once(serial, port):
    """Child process only. Hold the exact fd and refuse claimed interfaces."""
    node, device = _identity(serial, port)
    fd = os.open(node, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(fd)
        current = os.stat(node, follow_symlinks=False)
        if not stat.S_ISCHR(opened.st_mode) or opened.st_rdev != device or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError("USB device node changed before reset")
        if _identity(serial, port) != (node, device):
            raise RuntimeError("USB identity changed before reset")
        # Linux rejects RESET on a claimed interface after privileges are dropped.
        # Never detach an occupied interface or elevate to root.
        fcntl.ioctl(fd, USBDEVFS_DROP_PRIVILEGES, struct.pack("I", 0))
        fcntl.ioctl(fd, USBDEVFS_RESET, 0)
    finally:
        os.close(fd)


def remember(snapshot):
    if snapshot.get("ok") and not snapshot.get("ambiguous"):
        for row in snapshot["receivers"]:
            if row.get("serial") and row.get("usb_path"):
                _last_ports[row["serial"]] = row["usb_path"]


def reset_receiver(device):
    serial = device.get("serial")
    snapshot = receiver_hardware.scan(refresh=True)
    remember(snapshot)
    matches = [d for d in snapshot["receivers"] if d["serial"] == serial]
    if not serial or not snapshot["ok"] or snapshot["ambiguous"] or len(matches) != 1:
        raise RuntimeError(f"USB reset refused: serial {serial!r} not unique/present; last known port {_last_ports.get(serial, 'unknown')}")
    port = matches[0]["usb_path"]
    # A separate process bounds the dashboard's wait on a stalled USB driver.
    result = subprocess.run(
        [sys.executable, "-m", "core.receiver_usb_reset", serial, port],
        cwd=str(Path(__file__).resolve().parents[1]), capture_output=True,
        text=True, timeout=15, check=False,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "USB reset failed").strip()[:400])
    for _ in range(10):
        try:
            _identity(serial, port)
            return f"USB reset OK: {serial} at {port}; kernel identity verified"
        except (OSError, RuntimeError, ValueError):
            time.sleep(0.3)
    raise RuntimeError(f"USB reset completed but {serial} at {port} did not reappear")


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3:
            raise RuntimeError("Expected serial and physical USB port")
        reset_once(sys.argv[1], sys.argv[2])
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
