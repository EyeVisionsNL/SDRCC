"""SDRCC Runtime v2 foundation.

This package is deliberately isolated from existing mission execution during
v0.30.1b. Import ``get_snapshot`` to inspect configured receiver runtimes.
"""

from .health import ReceiverHealth
from .receiver_runtime import ReceiverRuntime
from .runtime_manager import RuntimeManager, get_runtime_manager, get_snapshot
from .runtime_state import RuntimeState

__all__ = [
    "ReceiverHealth",
    "ReceiverRuntime",
    "RuntimeManager",
    "RuntimeState",
    "get_runtime_manager",
    "get_snapshot",
]
