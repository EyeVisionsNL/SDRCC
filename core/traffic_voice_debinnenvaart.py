#!/usr/bin/env python3
"""Compatibility import: De Binnenvaart now uses its official public ship JSON API.

The old HTML routes have been retired by the publisher. Keep the historic
import name for the shared SDRCC desktop/mobile photo pipeline.
"""
from core.traffic_voice_debinnenvaart_api import lookup

__all__ = ["lookup"]
