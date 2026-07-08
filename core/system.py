#!/usr/bin/env python3

import platform
import shutil
import subprocess


def command_exists(command):
    return shutil.which(command) is not None


def internet():
    try:
        subprocess.run(
            ["ping", "-c", "1", "1.1.1.1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return True
    except Exception:
        return False


def applications():

    return {
        "SatDump": command_exists("satdump"),
        "rtl_test": command_exists("rtl_test"),
        "Python": command_exists("python3"),
    }


def print_system():

    print("System")
    print("----------------")

    print("OS        :", platform.platform())
    print("Internet  :", "OK" if internet() else "OFFLINE")

    print()
    print("Applications")
    print("----------------")

    for app, state in applications().items():
        print(f"{app:<10}: {'OK' if state else 'Missing'}")
