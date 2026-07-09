#!/usr/bin/env python3

import shutil
import time
import psutil


def get_stats():
    disk = shutil.disk_usage("/")

    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "ram_percent": psutil.virtual_memory().percent,
        "disk_percent": round((disk.used / disk.total) * 100, 1),
        "uptime_seconds": int(time.time() - psutil.boot_time()),
    }
