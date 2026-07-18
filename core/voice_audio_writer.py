#!/usr/bin/env python3
"""Write rtl_fm PCM from stdin to WAV and optionally mirror it to aplay."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import wave


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--rate", type=int, default=48000)
    parser.add_argument("--monitor", action="store_true")
    args = parser.parse_args()

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    player = None
    if args.monitor:
        if shutil.which("aplay") is None:
            raise RuntimeError("aplay is required for live monitoring")
        player = subprocess.Popen(
            ["aplay", "-q", "-r", str(args.rate), "-f", "S16_LE", "-c", "1"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=sys.stderr,
        )

    try:
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(args.rate)
            while True:
                chunk = sys.stdin.buffer.read(65536)
                if not chunk:
                    break
                wav.writeframesraw(chunk)
                if player is not None and player.stdin is not None:
                    try:
                        player.stdin.write(chunk)
                        player.stdin.flush()
                    except (BrokenPipeError, OSError):
                        player = None
    finally:
        if player is not None:
            if player.stdin is not None:
                try:
                    player.stdin.close()
                except OSError:
                    pass
            try:
                player.wait(timeout=2)
            except subprocess.TimeoutExpired:
                player.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
