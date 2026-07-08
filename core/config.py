#!/usr/bin/env python3

import yaml
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config" / "station.yaml"


def load():
    with open(CONFIG, "r") as f:
        return yaml.safe_load(f)
