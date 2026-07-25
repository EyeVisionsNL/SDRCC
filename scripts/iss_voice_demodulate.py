#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from core import iss_voice, iss_voice_audio

parser = argparse.ArgumentParser(description="Offline ISS Voice CU8 IQ to WAV demodulation")
parser.add_argument("mission_id")
args = parser.parse_args()
validation = iss_voice.validate_config()
if not validation["ok"]:
    raise SystemExit("ISS Voice-config ongeldig: " + "; ".join(validation["errors"]))
print(json.dumps(iss_voice_audio.demodulate_mission(args.mission_id, validation["config"]), indent=2, ensure_ascii=False))
