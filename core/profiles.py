#!/usr/bin/env python3

from pathlib import Path
import yaml

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "profiles.yaml"


def load_profiles():
    if not CONFIG_FILE.exists():
        return {}

    with open(CONFIG_FILE, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    return data.get("profiles", {})


def get_profile(name):
    return load_profiles().get(name)


def list_profiles():
    return load_profiles()


def print_profiles():
    profiles = list_profiles()

    print("Profiles")
    print("-----------------------------")

    if not profiles:
        print("Geen profielen gevonden.")
        return

    for key, profile in profiles.items():
        print(f"{profile['name']}")
        print(f"  Key        : {key}")
        print(f"  Device     : {profile['device']}")
        print(f"  Managed by : {profile['managed_by']}")
        print(f"  Description: {profile['description']}")
        print()
