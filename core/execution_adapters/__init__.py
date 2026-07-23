"""Built-in read-only execution adapters for SDRCC."""

from core.execution_adapters.null_adapter import NullAdapter
from core.execution_adapters.satdump_adapter import SatDumpAdapter
from core.execution_adapters.service_adapter import ServiceAdapter

__all__ = [
    "NullAdapter",
    "SatDumpAdapter",
    "ServiceAdapter",
]
