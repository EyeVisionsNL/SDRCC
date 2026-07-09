#!/usr/bin/env python3

from pathlib import Path
import yaml

from core import state

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "profiles.yaml"


def load_profiles():
    if not CONFIG_FILE.exists():
        return {}

    with open(CONFIG_FILE, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    return data.get("profiles", {})


def list_profiles():
    return load_profiles()


def get_profile(name):
    return load_profiles().get(name)


def set_active_profile(profile_name):
    profiles = load_profiles()

    if profile_name not in profiles:
        raise ValueError(f"Onbekend profiel: {profile_name}")

    profile = profiles[profile_name]

    state.set_sdr2_state(
        status="idle",
        profile=profile_name,
        locked=False,
        process=None,
    )

    return profile


def print_profiles():
    profiles = list_profiles()

    print("Profiles")
    print("-----------------------------")

    current = state.get_sdr2_state()["profile"]

    for key, profile in profiles.items():

        marker = "●" if key == current else " "

        print(f"{marker} {profile['name']}")
        print(f"    Key        : {key}")
        print(f"    Device     : {profile['device']}")
        print(f"    Managed by : {profile['managed_by']}")
        print(f"    Description: {profile['description']}")
        print()
