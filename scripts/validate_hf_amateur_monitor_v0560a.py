#!/usr/bin/env python3
"""Compatibility entry point after v0.56.0a was superseded by live v0.56.0b."""

from validate_hf_amateur_monitor_v0560b import main


if __name__ == "__main__":
    raise SystemExit(main())
