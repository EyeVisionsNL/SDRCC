#!/usr/bin/env python3

from pathlib import Path
import yaml

CONFIG = Path(__file__).resolve().parent.parent / "config" / "satellites.yaml"


def load():

    with open(CONFIG, "r") as f:
        return yaml.safe_load(f)


def get_enabled():

    data = load()

    sats = []

    for name, cfg in data["satellites"].items():

        if cfg.get("enabled", False):
            sats.append((name, cfg))

    return sats


def print_satellites():

    print("Satellites")
    print("----------------")

    for name, cfg in get_enabled():

        print(name)
        print(f"  Frequency : {cfg['frequency']/1e6:.3f} MHz")
        print(f"  Mode      : {cfg['mode']}")
        print(f"  Min Elev  : {cfg['min_elevation']}°")
        print()
