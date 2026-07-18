"""Generic receiver runtime states for SDRCC Runtime v2."""

from enum import StrEnum


class RuntimeState(StrEnum):
    """Lifecycle state of one physical receiver runtime."""

    OFFLINE = "OFFLINE"
    IDLE = "IDLE"
    RESERVED = "RESERVED"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    PROCESSING = "PROCESSING"
    RESTORING = "RESTORING"
    ERROR = "ERROR"
