"""Generic receiver health values for SDRCC Runtime v2."""

from enum import StrEnum


class ReceiverHealth(StrEnum):
    """Operational health of one physical receiver."""

    ONLINE = "ONLINE"
    BUSY = "BUSY"
    RECOVERING = "RECOVERING"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"
